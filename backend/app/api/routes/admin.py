from typing import Optional
from fastapi import APIRouter, HTTPException, Depends, Response, Request, Query
from backend.app.config import settings
from backend.app.api.schemas.admin import (
    AdminLoginRequest,
    AdminLoginResponse,
    ClearCacheRequest,
    AdminJobListResponse,
    AdminJobDetailResponse,
    AdminJobActionRequest,
    AdminJobActionResponse,
    AdminWorkersResponse,
    AdminQueueStatsResponse,
    AdminErrorLogsResponse,
    AdminMigrationsResponse,
    AdminBackupsResponse,
    AdminAlertSummaryResponse,
)
from backend.app.services.auth_service import (
    verify_admin_credentials,
    create_admin_session,
    revoke_admin_token,
)
from backend.app.api.dependencies.auth import require_admin, Principal, verify_csrf_protection
from backend.app.cache.mongo_cache import CacheManager
from backend.app.services.admin_metrics_service import get_admin_metrics
from backend.app.services import admin_ops_service

router = APIRouter()


# ==============================================================================
# AUTHENTICATION & SESSION
# ==============================================================================
@router.post("/admin/login", response_model=AdminLoginResponse)
async def admin_login(req: AdminLoginRequest, request: Request, response: Response):
    """Xác thực đăng nhập admin HUIT và thiết lập HttpOnly cookie."""
    if verify_admin_credentials(req.username, req.password):
        ip_addr = request.client.host if request.client else None
        user_agent = request.headers.get("user-agent")
        raw_session_id, cookie_token, csrf_token = create_admin_session(
            ip_address=ip_addr,
            user_agent=user_agent,
        )
        is_secure = (settings.APP_ENV == "production" or settings.IS_PRODUCTION)
        response.set_cookie(
            key="huit_admin_token",
            value=cookie_token,
            max_age=86400,
            httponly=True,
            secure=is_secure,
            samesite="lax",
            path="/"
        )
        return AdminLoginResponse(
            success=True,
            csrf_token=csrf_token,
            message="Đăng nhập quản trị viên thành công!"
        )
    raise HTTPException(status_code=401, detail="Tài khoản hoặc mật khẩu không chính xác.")


@router.post("/admin/logout")
async def admin_logout(
    request: Request,
    response: Response,
    principal: Principal = Depends(require_admin),
    _csrf: None = Depends(verify_csrf_protection)
):
    """Đăng xuất quản trị viên, thu hồi session phía server và xóa HttpOnly cookie."""
    cookie_token = request.cookies.get("huit_admin_token")
    revocation_ok = True
    if cookie_token:
        if not revoke_admin_token(cookie_token):
            revocation_ok = False

    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.startswith("Bearer "):
        if not revoke_admin_token(auth_header[7:].strip()):
            revocation_ok = False

    is_secure = (settings.APP_ENV == "production" or settings.IS_PRODUCTION)
    if is_secure and not revocation_ok:
        raise HTTPException(
            status_code=500,
            detail="Thu hồi phiên thất bại trên hệ thống lưu trữ phân tán"
        )

    response.delete_cookie(
        key="huit_admin_token",
        path="/",
        httponly=True,
        secure=is_secure,
        samesite="lax"
    )
    return {"success": True, "message": "Đã đăng xuất quản trị viên"}


@router.get("/admin/verify")
async def admin_verify(admin: Principal = Depends(require_admin)):
    """Kiểm tra tính hợp lệ của token admin hiện tại."""
    return {"valid": True, "role": "admin"}


# ==============================================================================
# SYSTEM METRICS & CACHE CONTROL
# ==============================================================================
@router.get("/admin/metrics")
async def admin_metrics(admin: Principal = Depends(require_admin)):
    """Xem số liệu thống kê hệ thống (Logs, Cache size, KB count)."""
    try:
        return get_admin_metrics(admin.user_id)
    except Exception:
        raise HTTPException(status_code=503, detail="Không thể đọc metrics hệ thống lúc này")


@router.post("/admin/clear-cache")
async def admin_clear_cache(
    req: ClearCacheRequest,
    _csrf: None = Depends(verify_csrf_protection),
    admin: Principal = Depends(require_admin)
):
    """Xóa toàn bộ bộ nhớ đệm (RAM và MongoDB)."""
    if req.confirm:
        res = CacheManager.clear_all_cache()
        admin_ops_service.log_admin_operation_audit(
            operation_key="admin.cache.clear",
            principal_id=admin.user_id,
            request_id="admin-clear-cache",
            status="success",
        )
        return {"success": True, "message": "Đã xóa toàn bộ cache!", "details": res}
    return {"success": False, "message": "Chưa xác nhận thao tác xóa cache."}


# ==============================================================================
# JOB QUEUE MANAGEMENT (PAGINATION, FILTERS, TIMELINE)
# ==============================================================================
@router.get("/admin/jobs", response_model=AdminJobListResponse)
async def admin_list_jobs(
    page: int = Query(1, ge=1, description="Số trang hiện tại"),
    limit: int = Query(20, ge=1, le=100, description="Số lượng mục mỗi trang"),
    status: Optional[str] = Query(None, description="Lọc theo trạng thái: queued, processing, completed, failed, cancelled"),
    action: Optional[str] = Query(None, description="Lọc theo loại hành động: render, export, upscale"),
    time_range: Optional[str] = Query(None, description="Khoảng thời gian: 1h, 24h, 7d, 30d, all"),
    admin: Principal = Depends(require_admin)
):
    """Lấy danh sách các tác vụ nền trong Durable Queue có phân trang và bộ lọc."""
    res = admin_ops_service.list_admin_jobs(
        page=page,
        limit=limit,
        status=status,
        action=action,
        time_range=time_range
    )
    return AdminJobListResponse(**res)


@router.get("/admin/jobs/{job_id}", response_model=AdminJobDetailResponse)
async def admin_get_job_detail(
    job_id: str,
    admin: Principal = Depends(require_admin)
):
    """Xem chi tiết một tác vụ nền cùng lịch sử sự kiện (event timeline)."""
    res = admin_ops_service.get_admin_job_detail(job_id)
    if not res:
        raise HTTPException(status_code=404, detail=f"Không tìm thấy công việc {job_id}")
    return AdminJobDetailResponse(**res)


@router.post("/admin/jobs/{job_id}/retry", response_model=AdminJobActionResponse)
async def admin_retry_job(
    job_id: str,
    request: Request,
    body: Optional[AdminJobActionRequest] = None,
    _csrf: None = Depends(verify_csrf_protection),
    admin: Principal = Depends(require_admin)
):
    """Đưa một tác vụ nền về trạng thái queued để thử lại (kèm CSRF và kiểm toán)."""
    req_id = request.headers.get("X-Request-ID") or f"admin_retry_{job_id}"
    reason = body.reason if body else None
    ok, msg = await admin_ops_service.retry_admin_job(
        job_id=job_id,
        admin_id=admin.user_id,
        request_id=req_id,
        reason=reason
    )
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return AdminJobActionResponse(success=True, message=msg, job_id=job_id)


@router.post("/admin/jobs/{job_id}/cancel", response_model=AdminJobActionResponse)
async def admin_cancel_job(
    job_id: str,
    request: Request,
    body: Optional[AdminJobActionRequest] = None,
    _csrf: None = Depends(verify_csrf_protection),
    admin: Principal = Depends(require_admin)
):
    """Hủy một tác vụ nền đang chờ hoặc đang xử lý (kèm CSRF và kiểm toán)."""
    req_id = request.headers.get("X-Request-ID") or f"admin_cancel_{job_id}"
    reason = body.reason if body else None
    ok, msg = await admin_ops_service.cancel_admin_job(
        job_id=job_id,
        admin_id=admin.user_id,
        request_id=req_id,
        reason=reason
    )
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return AdminJobActionResponse(success=True, message=msg, job_id=job_id)


# ==============================================================================
# WORKERS & QUEUE OBSERVABILITY
# ==============================================================================
@router.get("/admin/workers", response_model=AdminWorkersResponse)
async def admin_get_workers(admin: Principal = Depends(require_admin)):
    """Kiểm tra danh sách và trạng thái heartbeat của các Worker xử lý tác vụ nền."""
    res = admin_ops_service.get_admin_workers()
    return AdminWorkersResponse(**res)


@router.get("/admin/queue/stats", response_model=AdminQueueStatsResponse)
async def admin_get_queue_stats(admin: Principal = Depends(require_admin)):
    """Xem thống kê độ sâu hàng đợi: queued, processing, stuck, failed, completed."""
    res = admin_ops_service.get_admin_queue_stats()
    return AdminQueueStatsResponse(**res)


# ==============================================================================
# SANITIZED ERROR LOGS (NO RAW PROMPTS, NO SECRETS)
# ==============================================================================
@router.get("/admin/logs/errors", response_model=AdminErrorLogsResponse)
async def admin_get_error_logs(
    request_id: Optional[str] = Query(None, description="Tìm kiếm lỗi theo mã Request ID"),
    time_range: str = Query("24h", description="Khoảng thời gian: 1h, 24h, 7d, 30d, all"),
    limit: int = Query(20, ge=1, le=100, description="Giới hạn số bản ghi"),
    admin: Principal = Depends(require_admin)
):
    """
    Truy vấn nhật ký lỗi đã được khử khuẩn an ninh (Sanitized Error Logs):
    Tuyệt đối không để lộ câu hỏi thô của người dùng, secrets, API keys hay raw stacktraces.
    """
    res = admin_ops_service.get_sanitized_error_logs(
        request_id=request_id,
        time_range=time_range,
        limit=limit
    )
    return AdminErrorLogsResponse(**res)


# ==============================================================================
# READ-ONLY MIGRATIONS & BACKUPS STATUS
# ==============================================================================
@router.get("/admin/migrations", response_model=AdminMigrationsResponse)
async def admin_get_migrations(admin: Principal = Depends(require_admin)):
    """
    Xem danh sách các script migration và trạng thái cơ sở dữ liệu (CHỈ ĐỌC).
    Tuyệt đối không có nút hay API thực thi migration qua giao diện web.
    """
    res = admin_ops_service.get_readonly_migrations()
    return AdminMigrationsResponse(**res)


@router.get("/admin/backups", response_model=AdminBackupsResponse)
async def admin_get_backups(admin: Principal = Depends(require_admin)):
    """
    Xem danh sách các bản sao lưu cơ sở dữ liệu (CHỈ ĐỌC).
    Tuyệt đối không có tính năng phục hồi dữ liệu từ xa qua giao diện web.
    """
    res = admin_ops_service.get_readonly_backups()
    return AdminBackupsResponse(**res)


# ==============================================================================
# SYSTEM ALERT SUMMARY
# ==============================================================================
@router.get("/admin/alerts", response_model=AdminAlertSummaryResponse)
async def admin_get_alerts(admin: Principal = Depends(require_admin)):
    """Báo cáo tổng hợp tình trạng cảnh báo hệ thống (Stuck jobs, failed jobs, offline workers)."""
    res = admin_ops_service.get_alert_summary()
    return AdminAlertSummaryResponse(**res)
