"""
auth.py
Route xử lý xác thực phiên làm việc (Session Management):
- POST /api/auth/session: Cấp phát phiên làm việc có chữ ký bảo mật HMAC và thời hạn (TTL).
- Thiết lập HttpOnly, Secure, SameSite=Lax cookie 'huit_session_id'.
- GET /api/auth/session: Kiểm tra trạng thái xác thực của phiên hiện tại.
"""
import logging
import secrets
import time
import uuid
from fastapi import APIRouter, Response, Request, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from backend.app.config import settings
from backend.app.services.auth_service import (
    sign_session_id,
    verify_session_token,
    generate_csrf_token,
    DEFAULT_SESSION_TTL
)
from backend.app.api.dependencies.auth import get_current_principal, Principal

router = APIRouter(prefix="/auth", tags=["Authentication & Session"])


class SessionResponse(BaseModel):
    success: bool = True
    session_id: str
    csrf_token: str
    issued_at: int
    expires_at: int
    ttl_seconds: int


class SessionStatusResponse(BaseModel):
    user_id: str
    is_authenticated: bool
    is_admin: bool
    session_id: str | None = None

logger = logging.getLogger("huit_chatbot.auth")


@router.post("/session", response_model=SessionResponse)
async def create_or_refresh_session(
    request: Request,
    response: Response,
    ttl_seconds: int = DEFAULT_SESSION_TTL
):
    """
    Cấp phát hoặc gia hạn phiên làm việc (Session):
    - Tái sử dụng session hiện tại nếu cookie hợp lệ, chống tạo session mới vô hạn sau mỗi render.
    - Ký token HMAC kèm thời hạn và thiết lập HttpOnly cookie 'huit_session_id'.
    - Không trả signed token trong body JSON (cookie HttpOnly đã đủ đảm bảo an toàn).
    - Cung cấp CSRF token gắn kèm session_id cho các thao tác thay đổi dữ liệu.
    - Không phụ thuộc MongoDB, Redis, worker, LLM hoặc image service.
    - Fail-closed an toàn: Trả JSON có error_code, request_id, không làm lộ traceback.
    """
    req_id = request.headers.get("X-Request-ID") or getattr(request.state, "request_id", None) or f"req-{uuid.uuid4().hex[:12]}"
    response.headers["X-Request-ID"] = req_id

    try:
        now = int(time.time())
        ttl = min(max(300, ttl_seconds), 86400 * 7)  # Tối thiểu 5 phút, tối đa 7 ngày
        expires_at = now + ttl

        # Kiểm tra cookie hiện có để tái sử dụng session_id hợp lệ
        existing_cookie = request.cookies.get("huit_session_id")
        raw_session_id = None
        if existing_cookie:
            verified = verify_session_token(existing_cookie.strip())
            if verified:
                raw_session_id = verified

        if not raw_session_id:
            raw_session_id = f"sess_{secrets.token_urlsafe(24)}"

        token = sign_session_id(raw_session_id, ttl_seconds=ttl)
        csrf_token = generate_csrf_token(raw_session_id)

        # Thiết lập HttpOnly cookie an toàn
        response.set_cookie(
            key="huit_session_id",
            value=token,
            max_age=ttl,
            httponly=True,
            secure=not settings.IS_DEVELOPMENT,
            samesite="lax",
            path="/"
        )

        return SessionResponse(
            success=True,
            session_id=raw_session_id,
            csrf_token=csrf_token,
            issued_at=now,
            expires_at=expires_at,
            ttl_seconds=ttl
        )
    except Exception as exc:
        logger.error(
            "[%s] Session bootstrap failed (%s)",
            req_id,
            type(exc).__name__,
        )
        return JSONResponse(
            status_code=500,
            headers={"X-Request-ID": req_id},
            content={
                "success": False,
                "error_code": "SESSION_BOOTSTRAP_FAILED",
                "message": "Không thể khởi tạo phiên làm việc do lỗi cấu hình hệ thống.",
                "request_id": req_id
            }
        )



@router.get("/session", response_model=SessionStatusResponse)
async def get_session_status(
    principal: Principal = Depends(get_current_principal)
):
    """Lấy thông tin và trạng thái xác thực của phiên làm việc hiện tại."""
    return SessionStatusResponse(
        user_id=principal.user_id,
        is_authenticated=principal.is_authenticated,
        is_admin=principal.is_admin,
        session_id=principal.session_id or principal.user_id
    )
