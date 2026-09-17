import hmac
import hashlib
import time
from typing import Optional, Tuple, Dict, Any
from backend.app.config import settings

MAX_DOWNLOAD_URL_TTL = 86400  # 24 hours maximum for signed download URLs
DEFAULT_DOWNLOAD_URL_TTL = 3600  # 1 hour
MAX_SESSION_TTL = 86400 * 7  # 7 days max
DEFAULT_SESSION_TTL = 86400  # 24 hours


def verify_admin_credentials(username: str, password: str) -> bool:
    """Xác thực thông tin đăng nhập quản trị viên qua timing-safe compare."""
    user_ok = hmac.compare_digest(username.strip(), settings.ADMIN_USERNAME)
    pass_ok = hmac.compare_digest(password.strip(), settings.ADMIN_PASSWORD)
    return user_ok and pass_ok


import logging
import secrets
import threading

logger = logging.getLogger("huit_chatbot.auth_service")


class AdminSessionStore:
    """
    Store quản lý phiên làm việc của Quản trị viên (Stateful Admin Session):
    - Tuyệt đối không lưu token/session dạng rõ; chỉ lưu SHA-256 hash của session secret.
    - Hỗ trợ lưu trữ phân tán qua Redis và MongoDB Atlas qua Registered Operation Gateway v2.
    - Fail-closed: Môi trường Production bắt buộc lưu trữ phân tán thành công, cấm fallback về RAM.
    - Hỗ trợ thu hồi (Revoke) ngay lập tức khi đăng xuất; không giả báo thành công nếu persistent revoke lỗi.
    - Memory store chỉ đóng vai trò L0 cache hoặc fallback cục bộ cho môi trường test/development.
    """
    _lock = threading.Lock()
    _memory_sessions: Dict[str, Dict[str, Any]] = {}

    @classmethod
    def save_session(
        cls,
        session_hash: str,
        session_id: str,
        expires_at: int,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
    ) -> None:
        now = int(time.time())
        ttl = max(1, expires_at - now)
        is_prod = getattr(settings, "IS_PRODUCTION", False) or getattr(settings, "APP_ENV", "") == "production"

        redis_ok = False
        redis_err: Optional[Exception] = None
        try:
            from backend.app.cache.redis_client import get_sync_redis_client
            r = get_sync_redis_client()
            if r:
                r.set(f"adm_sess:{session_hash}", session_id, ex=ttl)
                redis_ok = True
        except Exception as exc:
            redis_err = exc
            logger.warning("Không thể lưu admin session vào Redis: %s", exc)

        mongo_ok = False
        mongo_err: Optional[Exception] = None
        try:
            from backend.app.data_access.operations.admin_session_operations import save_admin_session_ltx
            from datetime import datetime, timezone
            exp_dt = datetime.fromtimestamp(expires_at, tz=timezone.utc)
            saved = save_admin_session_ltx(
                session_hash=session_hash,
                session_id=session_id,
                admin_id=settings.ADMIN_USERNAME,
                expires_at=exp_dt,
                ip_address=ip_address,
                user_agent=user_agent,
            )
            if saved:
                mongo_ok = True
        except Exception as exc:
            mongo_err = exc
            logger.error("Lỗi persistence admin session qua LTX Gateway v2: %s", exc)

        # Fail-closed policy:
        if not redis_ok and not mongo_ok:
            if is_prod:
                # Production cấm fallback về RAM khi toàn bộ persistent stores cùng lỗi
                err_msg = (
                    f"Admin session persistence failed on all stores (Redis: {redis_err}, Mongo: {mongo_err}). "
                    "Fail-closed: từ chối đăng nhập admin trên production."
                )
                logger.critical(err_msg)
                raise RuntimeError(err_msg)
            else:
                # Development/Test fallback
                logger.warning("Cả Redis và MongoDB không khả dụng. Sử dụng In-Memory fallback cho môi trường dev/test.")
                with cls._lock:
                    cls._cleanup()
                    cls._memory_sessions[session_hash] = {
                        "session_id": session_id,
                        "expires_at": expires_at,
                        "created_at": now,
                    }
                return

        # Lưu L0 cache vào RAM khi persistent store đã ghi nhận thành công
        with cls._lock:
            cls._cleanup()
            cls._memory_sessions[session_hash] = {
                "session_id": session_id,
                "expires_at": expires_at,
                "created_at": now,
            }

    @classmethod
    def is_active(cls, session_hash: str) -> Optional[str]:
        now = int(time.time())
        is_prod = getattr(settings, "IS_PRODUCTION", False) or getattr(settings, "APP_ENV", "") == "production"

        # 1. Thử kiểm tra Redis (L1 distributed cache)
        try:
            from backend.app.cache.redis_client import get_sync_redis_client
            r = get_sync_redis_client()
            if r:
                val = r.get(f"adm_sess:{session_hash}")
                if val:
                    session_id = val.decode("utf-8") if isinstance(val, bytes) else str(val)
                    with cls._lock:
                        cls._memory_sessions[session_hash] = {
                            "session_id": session_id,
                            "expires_at": now + 3600,
                            "created_at": now,
                        }
                    return session_id
        except Exception as exc:
            logger.warning("Lỗi tra cứu admin session trên Redis: %s", exc)

        # 2. Thử kiểm tra MongoDB qua LTX Gateway v2 (L2 persistent store)
        try:
            from backend.app.data_access.operations.admin_session_operations import find_valid_admin_session_ltx
            from datetime import timezone
            doc = find_valid_admin_session_ltx(session_hash)
            if doc and doc.get("found"):
                exp_dt = doc.get("expires_at")
                session_id = str(doc.get("session_id"))
                exp_ts = now + 3600
                if exp_dt:
                    if exp_dt.tzinfo is None:
                        exp_dt = exp_dt.replace(tzinfo=timezone.utc)
                    exp_ts = int(exp_dt.timestamp())

                # Đồng bộ lại memory và Redis
                with cls._lock:
                    cls._memory_sessions[session_hash] = {
                        "session_id": session_id,
                        "expires_at": exp_ts,
                        "created_at": now,
                    }
                try:
                    from backend.app.cache.redis_client import get_sync_redis_client
                    r = get_sync_redis_client()
                    if r:
                        rem_ttl = max(1, exp_ts - now)
                        r.set(f"adm_sess:{session_hash}", session_id, ex=rem_ttl)
                except Exception:
                    pass
                return session_id
        except Exception as exc:
            logger.warning("Lỗi tra cứu admin session trên MongoDB qua LTX: %s", exc)

        # 3. Kiểm tra Memory Store (chỉ áp dụng ở môi trường dev/test)
        if is_prod:
            # Trên production, không xác thực bằng memory store cục bộ nếu persistent store không tồn tại
            return None

        with cls._lock:
            record = cls._memory_sessions.get(session_hash)
            if record and record["expires_at"] > now:
                return record["session_id"]
        return None

    @classmethod
    def revoke(cls, session_hash: str) -> bool:
        """
        Thu hồi phiên làm việc của quản trị viên:
        - Xóa khỏi bộ nhớ RAM cục bộ.
        - Xóa khỏi Redis cache.
        - Cập nhật revoked: True trên MongoDB qua LTX Gateway.
        - Fail-closed: Trên production, nếu toàn bộ persistent store thất bại, không giả báo thành công.
        """
        is_prod = getattr(settings, "IS_PRODUCTION", False) or getattr(settings, "APP_ENV", "") == "production"

        with cls._lock:
            cls._memory_sessions.pop(session_hash, None)

        redis_revoked = False
        redis_err: Optional[Exception] = None
        try:
            from backend.app.cache.redis_client import get_sync_redis_client
            r = get_sync_redis_client()
            if r:
                r.delete(f"adm_sess:{session_hash}")
                redis_revoked = True
        except Exception as exc:
            redis_err = exc
            logger.warning("Lỗi xóa admin session trên Redis khi revoke: %s", exc)

        mongo_revoked = False
        mongo_err: Optional[Exception] = None
        try:
            from backend.app.data_access.operations.admin_session_operations import revoke_admin_session_ltx
            revoked_res = revoke_admin_session_ltx(session_hash)
            if revoked_res:
                mongo_revoked = True
        except Exception as exc:
            mongo_err = exc
            logger.error("Lỗi thu hồi admin session trên MongoDB qua LTX: %s", exc)

        if is_prod:
            if not redis_revoked and not mongo_revoked:
                logger.critical(
                    "Thu hồi admin session thất bại trên toàn bộ persistent stores (Redis: %s, Mongo: %s)",
                    redis_err,
                    mongo_err,
                )
                return False
            return True

        return True

    @classmethod
    def _cleanup(cls) -> None:
        now = int(time.time())
        expired = [k for k, v in cls._memory_sessions.items() if v.get("expires_at", 0) <= now]
        for k in expired:
            cls._memory_sessions.pop(k, None)

    @classmethod
    def clear_for_testing(cls) -> None:
        with cls._lock:
            cls._memory_sessions.clear()


def create_admin_session(
    ttl_seconds: int = 86400,
    ip_address: Optional[str] = None,
    user_agent: Optional[str] = None,
) -> Tuple[str, str, str]:
    """
    Tạo phiên làm việc mới cho Quản trị viên:
    - Sinh session ID ngẫu nhiên bằng secrets.
    - Sinh secret part ngẫu nhiên bằng secrets.
    - Tính SHA-256 hash và chỉ lưu hash vào AdminSessionStore kèm TTL.
    - Ký token opaque chứa chữ ký HMAC đặt vào HttpOnly cookie.
    - Sinh CSRF token gắn liền với session ID.
    - Trả về (session_id, cookie_token, csrf_token).
    """
    now = int(time.time())
    ttl = min(max(60, ttl_seconds), 86400 * 7)
    exp = now + ttl

    raw_session_id = f"adm_sess_{secrets.token_hex(16)}"
    secret_part = secrets.token_urlsafe(32)

    session_hash = hashlib.sha256(f"{raw_session_id}:{secret_part}".encode("utf-8")).hexdigest()
    AdminSessionStore.save_session(
        session_hash,
        raw_session_id,
        expires_at=exp,
        ip_address=ip_address,
        user_agent=user_agent,
    )

    sig_msg = f"adm-sess:{raw_session_id}:{secret_part}:{exp}"
    sig = hmac.new(settings.ADMIN_TOKEN.encode("utf-8"), sig_msg.encode("utf-8"), hashlib.sha256).hexdigest()[:24]

    cookie_token = f"huit-adm-s.{raw_session_id}.{secret_part}.{exp}.{sig}"
    csrf_token = generate_csrf_token(raw_session_id)
    return raw_session_id, cookie_token, csrf_token


def generate_admin_token(ttl_seconds: int = 43200) -> str:
    """Hàm sinh token tương thích: tạo phiên admin stateful mới và trả về cookie token."""
    _, cookie_token, _ = create_admin_session(ttl_seconds=ttl_seconds)
    return cookie_token


def verify_admin_token_get_session(token: Optional[str]) -> Optional[str]:
    """
    Xác thực token quản trị viên và trả về admin_session_id nếu hợp lệ:
    - Bắt buộc kiểm tra chữ ký HMAC.
    - Bắt buộc kiểm tra hạn dùng (expires_at).
    - Bắt buộc kiểm tra session hash còn active trong AdminSessionStore (chống dùng lại token sau logout).
    """
    if not token or not isinstance(token, str):
        return None

    token_clean = token.strip()

    # Chặn việc dùng trực tiếp static secret làm Bearer token
    if hmac.compare_digest(token_clean, settings.ADMIN_TOKEN):
        return None

    # 1. Định dạng phiên mới: huit-adm-s.{session_id}.{secret_part}.{exp}.{sig}
    if token_clean.startswith("huit-adm-s."):
        parts = token_clean.split(".")
        if len(parts) == 5:
            _, session_id, secret_part, exp_str, sig = parts
            try:
                exp = int(exp_str)
                now = int(time.time())
                if now > exp:
                    return None  # Đã hết hạn

                expected_msg = f"adm-sess:{session_id}:{secret_part}:{exp_str}"
                expected_sig = hmac.new(settings.ADMIN_TOKEN.encode("utf-8"), expected_msg.encode("utf-8"), hashlib.sha256).hexdigest()[:24]
                if not hmac.compare_digest(sig, expected_sig):
                    return None  # Chữ ký giả mạo

                session_hash = hashlib.sha256(f"{session_id}:{secret_part}".encode("utf-8")).hexdigest()
                active_session_id = AdminSessionStore.is_active(session_hash)
                if not active_session_id:
                    return None  # Đã bị thu hồi (logged out) hoặc không tồn tại

                return active_session_id
            except (ValueError, TypeError):
                return None

    return None


def verify_admin_token(token: Optional[str]) -> bool:
    """Xác thực token quản trị viên (trả về bool)."""
    session_id = verify_admin_token_get_session(token)
    return session_id is not None


def revoke_admin_token(token: Optional[str]) -> bool:
    """Thu hồi phiên làm việc của quản trị viên khi đăng xuất."""
    if not token or not isinstance(token, str):
        return False
    token_clean = token.strip()
    if token_clean.startswith("huit-adm-s."):
        parts = token_clean.split(".")
        if len(parts) == 5:
            _, session_id, secret_part, _, _ = parts
            session_hash = hashlib.sha256(f"{session_id}:{secret_part}".encode("utf-8")).hexdigest()
            return AdminSessionStore.revoke(session_hash)
    return False


SIGNATURE_SECRET_KEY = settings.ADMIN_TOKEN


def sign_session_id(session_id: str, ttl_seconds: int = DEFAULT_SESSION_TTL) -> str:
    """Tạo signed session token cho client kèm thời hạn hết hạn."""
    s_clean = session_id.strip()
    exp = int(time.time()) + min(max(60, ttl_seconds), MAX_SESSION_TTL)
    msg = f"sess:{s_clean}:{exp}"
    sig = hmac.new(settings.ADMIN_TOKEN.encode("utf-8"), msg.encode("utf-8"), hashlib.sha256).hexdigest()[:24]
    return f"{s_clean}.{exp}.{sig}"


def generate_session_token(session_id: Optional[str] = None, ttl_seconds: int = DEFAULT_SESSION_TTL) -> Tuple[str, str, int]:
    """Sinh session_id ngẫu nhiên, signed token và thời gian hết hạn."""
    import secrets
    raw_session_id = session_id or f"sess_{secrets.token_urlsafe(24)}"
    now = int(time.time())
    ttl = min(max(60, ttl_seconds), MAX_SESSION_TTL)
    expires_at = now + ttl
    token = sign_session_id(raw_session_id, ttl_seconds=ttl)
    return raw_session_id, token, expires_at


def _internal_verify_session_token(token: Optional[str]) -> Optional[str]:
    """Giải mã và kiểm tra chữ ký token phiên, trả về session_id nếu hợp lệ."""
    if not token or not isinstance(token, str) or "." not in token:
        return None

    parts = token.strip().split(".")
    now = int(time.time())

    # Định dạng mới: session_id.exp.sig (bắt buộc có hạn dùng)
    if len(parts) == 3:
        session_id, exp_str, sig = parts
        try:
            exp = int(exp_str)
            if now > exp:
                return None  # Đã hết hạn
            if exp - now > MAX_SESSION_TTL:
                return None  # Thời hạn phi lý
            msg = f"sess:{session_id}:{exp_str}"
            expected_sig = hmac.new(settings.ADMIN_TOKEN.encode("utf-8"), msg.encode("utf-8"), hashlib.sha256).hexdigest()[:24]
            if hmac.compare_digest(sig, expected_sig):
                return session_id.strip()
        except ValueError:
            return None

    # Định dạng cũ 2 phần (session_id.sig) thiếu expiry -> Từ chối hoàn toàn để loại bỏ lỗ hổng token vĩnh viễn
    return None


def generate_csrf_token(session_id: str) -> str:
    """Sinh CSRF token gắn chặt với session_id và có thời hạn."""
    now = int(time.time())
    msg = f"csrf:{session_id}:{now}"
    sig = hmac.new(settings.ADMIN_TOKEN.encode("utf-8"), msg.encode("utf-8"), hashlib.sha256).hexdigest()[:24]
    return f"{now}.{sig}"


def verify_csrf_token(session_id: str, csrf_token: Optional[str], max_age_seconds: int = 86400) -> bool:
    """Xác thực CSRF token chống tấn công Cross-Site Request Forgery."""
    if not session_id or not csrf_token or "." not in csrf_token:
        return False
    parts = csrf_token.strip().split(".")
    if len(parts) != 2:
        return False
    ts_str, sig = parts
    try:
        ts = int(ts_str)
        now = int(time.time())
        if now < ts - 60 or now - ts > max_age_seconds:
            return False
        expected_msg = f"csrf:{session_id}:{ts_str}"
        expected_sig = hmac.new(settings.ADMIN_TOKEN.encode("utf-8"), expected_msg.encode("utf-8"), hashlib.sha256).hexdigest()[:24]
        return hmac.compare_digest(sig, expected_sig)
    except (ValueError, TypeError):
        return False


def verify_session_token(token_or_session_id: Optional[str], token: Optional[str] = None) -> Any:
    """
    Xác thực signed session token:
    - Nếu gọi 1 tham số: verify_session_token(token) -> trả về session_id: Optional[str].
    - Nếu gọi 2 tham số: verify_session_token(session_id, token) -> trả về bool (True/False).
    """

    if token is not None:
        expected_session_id = token_or_session_id
        actual_token = token
        extracted = _internal_verify_session_token(actual_token)
        if not extracted or not expected_session_id:
            return False
        return hmac.compare_digest(extracted.strip(), expected_session_id.strip())
    else:
        return _internal_verify_session_token(token_or_session_id)



def generate_download_signature(resource_id: str, expires_at: int) -> str:
    """Tạo chữ ký HMAC cho URL tải xuống có thời hạn."""
    msg = f"{resource_id}:{expires_at}"
    return hmac.new(settings.ADMIN_TOKEN.encode("utf-8"), msg.encode("utf-8"), hashlib.sha256).hexdigest()[:32]


def create_download_signature(resource_id: str, expires_in: int = DEFAULT_DOWNLOAD_URL_TTL) -> Tuple[str, int]:
    """
    Tạo chữ ký HMAC và Unix timestamp hết hạn trong tương lai:
    - Giới hạn expires_in trong khoảng [60s, 86400s] (tối đa 24h).
    """
    clamped_ttl = min(max(60, expires_in), MAX_DOWNLOAD_URL_TTL)
    expires_at = int(time.time()) + clamped_ttl
    sig = generate_download_signature(resource_id, expires_at)
    return sig, expires_at


def verify_download_signature(resource_id: str, expires_at: int, signature: str) -> bool:
    """
    Xác thực chữ ký URL tải xuống:
    - signature phải khớp với HMAC của (resource_id, expires_at).
    - expires_at phải còn hạn (expires_at >= now).
    - Chặn các thời hạn phi lý (> 24 giờ kể từ thời điểm tạo).
    - Tuyệt đối không ghi log chữ ký hoặc secret.
    """
    if not signature or not expires_at or not resource_id:
        return False

    try:
        exp_int = int(expires_at)
    except (ValueError, TypeError):
        return False

    now = int(time.time())
    if now > exp_int:
        return False  # Đã hết hạn

    if exp_int - now > MAX_DOWNLOAD_URL_TTL:
        return False  # Chặn thời hạn phi lý (> 24 giờ)

    expected = generate_download_signature(resource_id, exp_int)
    return hmac.compare_digest(signature.strip(), expected)
