"""
rate_limiter.py
Middleware và Storage giới hạn tần suất yêu cầu (Rate Limiter) phân tán:
- Hỗ trợ Distributed Store (Redis / Upstash) cho môi trường Production (atomic INCR + EXPIRE).
- Fail-fast trên production nếu thiếu cấu hình distributed store.
- InMemoryRateLimitStore chỉ được dùng trong development hoặc test.
- Chỉ dùng Bearer / Session Token đã xác thực làm bucket key (chống bypass bằng token giả).
- Chuẩn hóa kiểm tra Trusted Proxy bằng ipaddress RFC 1918 (10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16).
- Tuyệt đối không ghép raw X-User-ID / X-Session-ID vào bucket.
- Phân tách chính sách giới hạn cho từng nhóm endpoint (Admin login, Chat/Stream, Tác vụ nặng, Job polling).
"""
import ipaddress
import logging
import os
import time
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Tuple

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from backend.app.config import settings
from backend.app.services.auth_service import verify_admin_token, verify_session_token

logger = logging.getLogger("huit_chatbot.rate_limiter")

# Dải mạng private chuẩn RFC 1918 và loopback
_DEFAULT_TRUSTED_NETWORKS = [
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
]


class RateLimitStore:
    """Giao diện / Manager cho Rate Limit Store (hỗ trợ phân tán nhiều instance)."""

    def __init__(self, store: Optional["RateLimitStore"] = None):
        self._underlying_store = store

    def get_store(self) -> "RateLimitStore":
        """Lấy instance store thực thi (Redis trong production, In-Memory trong test/dev)."""
        if self._underlying_store is not None:
            return self._underlying_store
        return get_rate_limit_store()

    async def is_allowed(self, key: str, max_requests: int, window_seconds: int) -> Tuple[bool, int, int]:
        """Kiểm tra và ghi nhận request."""
        target = self.get_store()
        if target is self:
            raise NotImplementedError("Subclasses must implement is_allowed")
        return await target.is_allowed(key, max_requests, window_seconds)

    def clear(self):
        """Xóa sạch bộ nhớ đệm."""
        target = self.get_store()
        if target is self:
            return
        target.clear()


class InMemoryRateLimitStore(RateLimitStore):
    """Store lưu trong RAM (chỉ dùng cho development và chạy test offline)."""

    def __init__(self):
        self._records: Dict[str, List[float]] = {}
        self._last_cleanup = time.time()

    async def is_allowed(self, key: str, max_requests: int, window_seconds: int) -> Tuple[bool, int, int]:
        now = time.time()
        # Dọn dẹp định kỳ
        if now - self._last_cleanup > 300:
            self._last_cleanup = now
            for k in list(self._records.keys()):
                self._records[k] = [t for t in self._records[k] if now - t < 120]
                if not self._records[k]:
                    self._records.pop(k, None)

        history = [t for t in self._records.get(key, []) if now - t < window_seconds]
        if len(history) >= max_requests:
            oldest = history[0]
            retry_after = max(1, int(window_seconds - (now - oldest)))
            return False, 0, retry_after

        history.append(now)
        self._records[key] = history
        remaining = max(0, max_requests - len(history))
        return True, remaining, 0

    def clear(self):
        self._records.clear()


LUA_RATE_LIMIT_SCRIPT = """
local current = redis.call('INCR', KEYS[1])
if tonumber(current) == 1 then
    redis.call('EXPIRE', KEYS[1], ARGV[1])
end
local ttl = redis.call('TTL', KEYS[1])
return {current, ttl}
"""


class RedisRateLimitStore(RateLimitStore):
    """
    Store phân tán sử dụng Redis / Upstash (Atomic Lua script INCR + EXPIRE).
    Đảm bảo tính nhất quán trên nhiều container/worker production.
    """

    def __init__(self, redis_url: Optional[str] = None):
        self.redis_url = redis_url
        self._client = None

    def _get_client(self):
        if self._client is None:
            from backend.app.cache.redis_client import get_async_redis_client
            client = get_async_redis_client()
            if client is not None:
                self._client = client
            elif self.redis_url:
                try:
                    import redis.asyncio as aioredis
                    self._client = aioredis.from_url(self.redis_url, decode_responses=True)
                except Exception as e:
                    logger.error(f"Lỗi khởi tạo Redis client: {e}")
                    raise RuntimeError(f"Không thể kết nối Redis Rate Limiter: {e}")
            else:
                raise RuntimeError("Không thể khởi tạo Redis Rate Limiter: thiếu cấu hình Redis URL")
        return self._client

    async def is_allowed(self, key: str, max_requests: int, window_seconds: int) -> Tuple[bool, int, int]:
        client = self._get_client()
        redis_key = f"ratelimit:{key}"
        try:
            result = await client.eval(LUA_RATE_LIMIT_SCRIPT, 1, redis_key, window_seconds)
            current_count = int(result[0])
            current_ttl = int(result[1])

            if current_count > max_requests:
                retry_after = max(1, current_ttl if current_ttl > 0 else window_seconds)
                return False, 0, retry_after

            remaining = max(0, max_requests - current_count)
            return True, remaining, 0
        except Exception as ex:
            logger.error(f"Lỗi truy vấn Redis Rate Limiter: {ex}")
            if not settings.IS_DEVELOPMENT:
                raise
            return True, max_requests, 0

    def clear(self):
        pass


_global_rate_limit_store: Optional[RateLimitStore] = None


def get_rate_limit_store() -> RateLimitStore:
    """Khởi tạo và lấy singleton RateLimitStore theo cấu hình môi trường."""
    global _global_rate_limit_store

    app_env = (os.getenv("APP_ENV") or getattr(settings, "APP_ENV", "development")).strip().lower()
    is_prod = getattr(settings, "IS_PRODUCTION", False) or app_env == "production" or os.getenv("IS_PRODUCTION", "").lower() == "true"
    redis_url = os.getenv("RATE_LIMIT_REDIS_URL", "").strip() or getattr(settings, "RATE_LIMIT_REDIS_URL", "").strip()

    if is_prod or app_env == "production":
        if not redis_url:
            _global_rate_limit_store = None
            raise RuntimeError(
                "CẤU HÌNH THIẾU TRÊN PRODUCTION: RATE_LIMIT_REDIS_URL bắt buộc phải được thiết lập."
            )
        if _global_rate_limit_store is None or isinstance(_global_rate_limit_store, InMemoryRateLimitStore):
            _global_rate_limit_store = RedisRateLimitStore(redis_url)
        return _global_rate_limit_store

    if _global_rate_limit_store is not None:
        return _global_rate_limit_store

    if redis_url:
        _global_rate_limit_store = RedisRateLimitStore(redis_url)
    else:
        _global_rate_limit_store = InMemoryRateLimitStore()
    return _global_rate_limit_store


def set_rate_limit_store_for_testing(store: Optional[RateLimitStore]) -> None:
    """Thiết lập store tùy biến phục vụ Unit Test."""
    global _global_rate_limit_store
    _global_rate_limit_store = store


def clear_rate_limits_for_testing():
    """Dọn dẹp bộ nhớ đệm phục vụ Unit Test."""
    global _global_rate_limit_store
    if _global_rate_limit_store:
        _global_rate_limit_store.clear()


def get_trusted_networks() -> List[Any]:
    raw_proxies = getattr(settings, "TRUSTED_PROXIES", [])
    networks = []
    has_custom_env = bool(os.getenv("TRUSTED_PROXIES"))
    if has_custom_env:
        for item in raw_proxies:
            try:
                networks.append(ipaddress.ip_network(item, strict=False))
            except ValueError:
                pass
        return networks

    if settings.IS_DEVELOPMENT:
        return [
            ipaddress.ip_network("127.0.0.0/8"),
            ipaddress.ip_network("::1/128"),
            ipaddress.ip_network("10.0.0.0/8"),
            ipaddress.ip_network("172.16.0.0/12"),
            ipaddress.ip_network("192.168.0.0/16"),
        ]
    return [
        ipaddress.ip_network("127.0.0.1/32"),
        ipaddress.ip_network("::1/128"),
    ]


def is_trusted_proxy_ip(ip_str: str) -> bool:
    """Kiểm tra địa chỉ IP có thuộc danh sách trusted proxy CIDR cấu hình qua settings.TRUSTED_PROXIES."""
    try:
        ip = ipaddress.ip_address(ip_str.strip())
        trusted_nets = get_trusted_networks()
        return any(ip in net for net in trusted_nets)
    except ValueError:
        return False


def get_client_ip(request: Request) -> str:
    """Trích xuất địa chỉ IP của client thực sự, giải quyết trusted reverse proxy theo cấu hình CIDR."""
    socket_ip = request.client.host if request.client else "127.0.0.1"
    if is_trusted_proxy_ip(socket_ip):
        forwarded = request.headers.get("X-Forwarded-For")
        if forwarded:
            first_ip = forwarded.split(",")[0].strip()
            try:
                ipaddress.ip_address(first_ip)
                return first_ip
            except ValueError:
                pass
    return socket_ip


def get_client_key(request: Request) -> str:
    """
    Xác định khóa nhận diện client an toàn:
    1. Nếu có Bearer / Session Token: Chỉ dùng khi token HỢP LỆ (auth:{user_id}).
    2. Token giả hoặc token sai KHÔNG ĐƯỢC tạo bucket riêng -> rơi về IP bucket.
    3. Trích xuất IP khách từ socket; chỉ đọc X-Forwarded-For nếu socket IP là proxy tin cậy.
    4. Tuyệt đối không ghép raw X-User-ID / X-Session-ID vào bucket!
    """
    # 1. Kiểm tra Bearer token hoặc Session token đã xác thực
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header[7:].strip()
        if token:
            if verify_admin_token(token):
                return "auth:admin"
            verified_session = verify_session_token(token)
            if verified_session:
                return f"auth:{verified_session}"

    cookie_admin = request.cookies.get("huit_admin_token")
    if cookie_admin:
        if verify_admin_token(cookie_admin.strip()):
            return "auth:admin"

    cookie_session = request.cookies.get("huit_session_id")
    if cookie_session:
        verified_session = verify_session_token(cookie_session.strip())
        if verified_session:
            return f"auth:{verified_session}"

    x_session_token = request.headers.get("X-Session-Token")
    if x_session_token:
        verified_session = verify_session_token(x_session_token.strip())
        if verified_session:
            return f"auth:{verified_session}"

    # 2. Khách vãng lai (hoặc token giả): Định danh theo địa chỉ IP
    client_ip = get_client_ip(request)
    return f"ip:{client_ip}"


def get_limit_for_path(path: str) -> Tuple[int, int]:
    """
    Chính sách giới hạn (max_requests, window_seconds) cho từng nhóm endpoint:
    - Admin login: 5 req / 60s (chống brute-force)
    - Tác vụ nặng (sinh ảnh, upscale, render, export): 10 req / 60s
    - Chat & Streaming & Plan: settings.RATE_LIMIT_PER_MINUTE req / 60s
    - Job polling (/jobs/): 60 req / 60s
    - Khác: 60 req / 60s
    """
    p = path.lower()
    if "/admin/login" in p:
        return 5, 60
    if any(k in p for k in ["/images", "/render", "/upscale", "/export"]):
        return 10, 60
    if "/jobs" in p:
        return 60, 60
    if any(k in p for k in ["/chat", "/chat-stream", "/artifacts/plan"]):
        return settings.RATE_LIMIT_PER_MINUTE, 60
    return 60, 60


class RateLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        # Bỏ qua health, docs, openapi và static files
        if path.startswith(("/health", "/docs", "/openapi.json", "/assets", "/favicon.ico")):
            return await call_next(request)

        client_key = get_client_key(request)
        max_requests, window_seconds = get_limit_for_path(path)
        route_bucket = path.split("/")[2] if len(path.split("/")) > 2 else "root"
        record_key = f"{client_key}:{route_bucket}"

        store = get_rate_limit_store()
        allowed, remaining, retry_after = await store.is_allowed(record_key, max_requests, window_seconds)

        if not allowed:
            req_id = getattr(request.state, "request_id", None) or request.headers.get("X-Request-ID")
            return JSONResponse(
                status_code=429,
                content={
                    "error_code": "RATE_LIMIT_EXCEEDED",
                    "message": "Quá giới hạn số lượng yêu cầu trong một khoảng thời gian. Vui lòng thử lại sau.",
                    "limit": max_requests,
                    "window_seconds": window_seconds,
                    "retry_after_seconds": retry_after,
                    "request_id": req_id
                },
                headers={
                    "Retry-After": str(retry_after),
                    "X-RateLimit-Limit": str(max_requests),
                    "X-RateLimit-Remaining": "0"
                }
            )

        response: Response = await call_next(request)
        response.headers["X-RateLimit-Limit"] = str(max_requests)
        response.headers["X-RateLimit-Remaining"] = str(remaining)
        return response
