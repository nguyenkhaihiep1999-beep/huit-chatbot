"""
auth.py
FastAPI dependencies cho xác thực và phân quyền:
- Principal abstraction: phân biệt rõ Admin, User sở hữu, và Khách (Anonymous).
- Loại bỏ hoàn toàn lỗ hổng bypass chuỗi "admin" từ client header.
- Hỗ trợ Signed Session Token và URL Signature có thời hạn.
"""
from dataclasses import dataclass
from typing import Optional
from fastapi import Header, Query, Request, HTTPException, Security, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from backend.app.services.auth_service import (
    verify_admin_token,
    verify_admin_token_get_session,
    verify_session_token,
    verify_download_signature
)
from backend.app.middleware.rate_limiter import get_client_ip

security = HTTPBearer(auto_error=False)


@dataclass
class Principal:
    user_id: str
    is_admin: bool = False
    is_authenticated: bool = False
    session_id: Optional[str] = None

    def can_access(self, owner_id: Optional[str], access_scope: str = "public") -> bool:
        """
        Kiểm tra quyền truy cập tài nguyên:
        - Nếu tài nguyên công khai (owner_id is None hoặc access_scope == 'public'): Cho phép.
        - Nếu người dùng là admin: Cho phép.
        - Nếu tài nguyên riêng tư (private): BẮT BUỘC principal.is_authenticated == True và user_id == owner_id.
        - Tuyệt đối không cho phép truy cập tài nguyên riêng tư nếu chỉ có raw unauthenticated session_id!
        """
        if not owner_id or access_scope == "public":
            return True
        if self.is_admin:
            return True
        # Bắt buộc phải được xác thực (signed token) và khớp owner_id
        if self.is_authenticated and self.user_id and self.user_id != "anonymous" and self.user_id == owner_id:
            return True
        return False


async def get_current_principal(
    request: Request,
    auth: Optional[HTTPAuthorizationCredentials] = Security(security),
    x_user_id: Optional[str] = Header(None),
    x_session_id: Optional[str] = Header(None),
    x_session_token: Optional[str] = Header(None),
    sig: Optional[str] = Query(None),
    expires: Optional[int] = Query(None),
    exp: Optional[int] = Query(None, description="Deprecated, use expires instead")
) -> Principal:
    """
    Xác định danh tính (Principal) từ request:
    1. Kiểm tra Bearer token quản trị -> Admin.
    2. Kiểm tra Signed Session Token -> Xác thực phiên người dùng (is_authenticated=True).
    3. Kiểm tra chữ ký tải xuống Signed URL (sig + expires).
    4. Session / User ID thô chỉ dùng làm correlation/tracking ID, KHÔNG BAO GIỜ cấp quyền (is_authenticated=False).
    5. Mặc định gán anonymous.
    """
    raw_correlation_id = (x_session_id or x_user_id or "").strip() or None
    expiry_val = expires if expires is not None else exp

    # 1. Bearer Token
    if auth and auth.credentials:
        token = auth.credentials.strip()
        admin_sess = verify_admin_token_get_session(token)
        if admin_sess:
            return Principal(user_id="admin", is_admin=True, is_authenticated=True, session_id=admin_sess)
        verified_session = verify_session_token(token)
        if verified_session:
            return Principal(user_id=verified_session, is_admin=False, is_authenticated=True, session_id=raw_correlation_id)

    # 1b. HttpOnly Cookie admin token 'huit_admin_token'
    cookie_admin = request.cookies.get("huit_admin_token")
    if cookie_admin:
        admin_sess = verify_admin_token_get_session(cookie_admin.strip())
        if admin_sess:
            return Principal(user_id="admin", is_admin=True, is_authenticated=True, session_id=admin_sess)

    # 2. Signed Session Token từ Header
    if x_session_token:
        verified_session = verify_session_token(x_session_token)
        if verified_session:
            return Principal(user_id=verified_session, is_admin=False, is_authenticated=True, session_id=raw_correlation_id or verified_session)

    # 3. HttpOnly Cookie session 'huit_session_id' (Ưu tiên cao hơn raw header, không để raw correlation header che mất)
    cookie_session = request.cookies.get("huit_session_id")
    if cookie_session:
        verified = verify_session_token(cookie_session.strip())
        if verified:
            return Principal(user_id=verified, is_admin=False, is_authenticated=True, session_id=raw_correlation_id or verified)

    # 4. Signed Download URL query params
    resource_id = request.path_params.get("storage_key") or request.path_params.get("artifact_id")
    if sig and expiry_val and resource_id:
        if verify_download_signature(resource_id, expiry_val, sig):
            return Principal(user_id="signed_download_guest", is_admin=False, is_authenticated=True, session_id=raw_correlation_id)

    # 5. Raw Session / User ID từ header (CHỈ dùng làm correlation ID, TUYỆT ĐỐI KHÔNG CẤP QUYỀN)
    if raw_correlation_id:
        return Principal(user_id="anonymous", is_admin=False, is_authenticated=False, session_id=raw_correlation_id)

    return Principal(user_id="anonymous", is_admin=False, is_authenticated=False)


def check_resource_access(
    principal: Principal,
    owner_id: Optional[str],
    access_scope: str = "public"
) -> bool:
    """
    Authorization Helper duy nhất cho mọi tài nguyên (Artifact, Image, Job, Signed Download):
    - Public: cho phép tất cả mọi người đọc.
    - Private: chỉ cho phép owner đã xác thực hoặc admin.
    - Anonymous tuyệt đối không được xem tài nguyên private.
    """
    return principal.can_access(owner_id=owner_id, access_scope=access_scope)


def require_admin(principal: Principal = Security(get_current_principal)) -> Principal:
    """Dependency bắt buộc quyền quản trị viên."""
    if not principal.is_admin:
        status_code = 401 if not principal.is_authenticated else 403
        raise HTTPException(
            status_code=status_code,
            detail={"error_code": "UNAUTHORIZED" if not principal.is_authenticated else "FORBIDDEN", "message": "Yêu cầu quyền quản trị viên hợp lệ"}
        )
    return principal


async def verify_csrf_protection(
    request: Request,
    principal: Principal = Depends(get_current_principal)
):
    """
    Bảo vệ CSRF cho các phương thức thay đổi dữ liệu (POST, PUT, DELETE, PATCH).
    - Áp dụng cho cả User Session ('huit_session_id') và Admin Session ('huit_admin_token').
    - Tuyệt đối KHÔNG miễn trừ CSRF chỉ vì principal là admin!
    """
    if request.method in ("GET", "HEAD", "OPTIONS"):
        return

    # Endpoint login admin được miễn trừ CSRF nhưng phải chịu rate limit 5 req/min
    if request.url.path.endswith("/admin/login") or request.url.path.endswith("/auth/session"):
        return

    from backend.app.services.auth_service import verify_csrf_token

    # 1. Kiểm tra nếu request là Admin (dùng cookie admin hoặc bearer)
    cookie_admin = request.cookies.get("huit_admin_token")
    if cookie_admin or principal.is_admin:
        csrf_token = request.headers.get("X-CSRF-Token")
        admin_session_id = principal.session_id or "admin"
        if not csrf_token or not verify_csrf_token(admin_session_id, csrf_token):
            raise HTTPException(
                status_code=403,
                detail={"error_code": "CSRF_TOKEN_INVALID", "message": "CSRF token cho quản trị viên không hợp lệ hoặc đã hết hạn."}
            )
        return

    # 2. Kiểm tra nếu request sử dụng User Cookie Session
    cookie = request.cookies.get("huit_session_id")
    if cookie and principal.is_authenticated:
        csrf_token = request.headers.get("X-CSRF-Token")
        if not csrf_token or not verify_csrf_token(principal.user_id, csrf_token):
            raise HTTPException(
                status_code=403,
                detail={"error_code": "CSRF_TOKEN_INVALID", "message": "CSRF token không hợp lệ hoặc đã hết hạn."}
            )

