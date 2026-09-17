"""
redis_client.py
Singleton Redis Connection Pool và Client cho HUIT Chatbot:
- Quản lý pool kết nối dùng chung cho Rate Limiter, Distributed Lock, và Streaming Event Buffer.
- Tự động kiểm tra tính khả dụng khi khởi động (ping/healthcheck).
- Đóng kết nối an toàn (graceful shutdown) khi ứng dụng dừng.
- Hỗ trợ cô lập mock phục vụ Unit Test.
"""
import logging
from typing import Any, Dict, Optional, Tuple

from backend.app.config import settings

logger = logging.getLogger("huit_chatbot.redis")

_async_redis_client: Optional[Any] = None
_sync_redis_client: Optional[Any] = None


def get_redis_url() -> str:
    """Lấy URL Redis cấu hình theo thứ tự ưu tiên."""
    url = getattr(settings, "RATE_LIMIT_REDIS_URL", "").strip()
    if not url:
        url = getattr(settings, "STREAM_RESUME_REDIS_URL", "").strip()
    if not url:
        url = getattr(settings, "REDIS_URL", "").strip()
    return url


def get_async_redis_client() -> Optional[Any]:
    """
    Lấy thể hiện duy nhất (Singleton) của Async Redis Client.
    Trả về None nếu Redis không được cấu hình trong môi trường dev/test.
    """
    global _async_redis_client
    if _async_redis_client is not None:
        return _async_redis_client

    url = get_redis_url()
    if not url:
        if settings.IS_PRODUCTION:
            raise RuntimeError(
                "Lỗi cấu hình Production: Bắt buộc phải cấu hình Redis URL (RATE_LIMIT_REDIS_URL hoặc REDIS_URL)."
            )
        return None

    try:
        import redis.asyncio as aioredis
        _async_redis_client = aioredis.from_url(
            url,
            decode_responses=True,
            socket_timeout=5.0,
            socket_connect_timeout=5.0,
            health_check_interval=30,
            max_connections=50
        )
        return _async_redis_client
    except Exception as e:
        logger.error(f"Không thể khởi tạo kết nối Async Redis: {e}")
        if settings.IS_PRODUCTION:
            raise
        return None


def get_sync_redis_client() -> Optional[Any]:
    """Lấy thể hiện duy nhất (Singleton) của Sync Redis Client."""
    global _sync_redis_client
    if _sync_redis_client is not None:
        return _sync_redis_client

    url = get_redis_url()
    if not url:
        if settings.IS_PRODUCTION:
            raise RuntimeError(
                "Lỗi cấu hình Production: Bắt buộc phải cấu hình Redis URL (RATE_LIMIT_REDIS_URL hoặc REDIS_URL)."
            )
        return None

    try:
        import redis
        _sync_redis_client = redis.from_url(
            url,
            decode_responses=True,
            socket_timeout=5.0,
            socket_connect_timeout=5.0,
            health_check_interval=30,
            max_connections=20
        )
        return _sync_redis_client
    except Exception as e:
        logger.error(f"Không thể khởi tạo kết nối Sync Redis: {e}")
        if settings.IS_PRODUCTION:
            raise
        return None


async def check_redis_health() -> Dict[str, Any]:
    """Kiểm tra tình trạng kết nối tới Redis (sử dụng trong endpoint /health/ready)."""
    url = get_redis_url()
    if not url:
        return {
            "status": "disabled",
            "message": "Redis chưa được cấu hình (đang dùng In-Memory)",
            "ping_ms": None
        }

    try:
        client = get_async_redis_client()
        if client is None:
            return {"status": "error", "message": "Client chưa khởi tạo"}
        import time
        start = time.perf_counter()
        pong = await client.ping()
        latency_ms = round((time.perf_counter() - start) * 1000, 2)
        if pong:
            return {"status": "healthy", "ping_ms": latency_ms}
        return {"status": "unhealthy", "message": "Ping không nhận được phản hồi"}
    except Exception as e:
        return {"status": "unhealthy", "error": str(e)}


async def close_redis_connection() -> None:
    """Đóng an toàn tất cả kết nối Redis khi ứng dụng shutdown."""
    global _async_redis_client, _sync_redis_client
    if _async_redis_client is not None:
        try:
            await _async_redis_client.aclose()
            logger.info("Đã đóng kết nối Async Redis an toàn.")
        except Exception as e:
            logger.warning(f"Lỗi khi đóng Async Redis: {e}")
        _async_redis_client = None

    if _sync_redis_client is not None:
        try:
            _sync_redis_client.close()
            logger.info("Đã đóng kết nối Sync Redis an toàn.")
        except Exception as e:
            logger.warning(f"Lỗi khi đóng Sync Redis: {e}")
        _sync_redis_client = None


def set_redis_client_for_testing(async_client: Optional[Any] = None, sync_client: Optional[Any] = None) -> None:
    """Mock Redis client phục vụ Unit Test."""
    global _async_redis_client, _sync_redis_client
    _async_redis_client = async_client
    _sync_redis_client = sync_client
