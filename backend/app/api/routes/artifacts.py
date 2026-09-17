"""
artifacts.py
FastAPI Router cho Hệ thống Quản lý và Dựng Tài nguyên Artifacts:
- POST /api/artifacts/plan: Lập kế hoạch sinh file (Manifest siêu nhẹ)
- POST /api/artifacts/render: Dựng file hoặc đẩy vào background queue
- GET  /api/artifacts/{id}: Lấy thông tin chi tiết và manifest của artifact
- GET  /api/artifacts/{id}/preview: Xem trước tức thì (SVG / WebP thumbnail)
- POST /api/artifacts/{id}/upscale: Upscale hình ảnh theo yêu cầu (2x, 4x)
- POST /api/artifacts/{id}/export: Xuất ra các định dạng nặng (.xlsx, .docx, .pdf, .png, .svg)
- GET  /api/artifacts/{id}/file: Tải file vật lý trực tiếp
- GET  /api/jobs/{id}: Kiểm tra trạng thái của tác vụ nền
- GET  /api/jobs/{id}/events: Lấy lịch sử tiến trình của tác vụ nền
- POST /api/jobs/{id}/cancel: Hủy tác vụ nền
"""
from typing import Optional, List
from fastapi import APIRouter, HTTPException, Query, Response, Request, Header, Depends
from fastapi.responses import JSONResponse

from backend.app.api.schemas.artifact import (
    ArtifactManifest,
    ArtifactPlanRequest,
    ArtifactRenderRequest,
    ArtifactUpscaleRequest,
    ArtifactExportRequest,
    JobStatusResponse
)
from backend.app.services.artifact_service import (
    create_artifact_plan,
    get_artifact,
    get_artifact_preview,
    upscale_artifact,
    export_artifact
)
from backend.app.services.asset_store import AssetStore, ArtifactStore, SAFE_MIME_MAP
from backend.app.services.job_queue import JobQueueManager
from backend.app.telemetry.errors import ArtifactException
from backend.app.api.dependencies.auth import Principal, get_current_principal
from backend.app.telemetry.logger import get_current_request_id
from backend.app.services.auth_service import verify_download_signature
from backend.app.storage.storage_adapter import get_storage_adapter

router = APIRouter()


@router.post("/artifacts/plan", response_model=ArtifactManifest)
async def plan_artifact_endpoint(
    req: ArtifactPlanRequest,
    principal: Principal = Depends(get_current_principal)
):
    """Tạo kế hoạch Artifact Manifest siêu nhẹ từ prompt hoặc cấu trúc."""
    try:
        manifest = await create_artifact_plan(req, owner_id=principal.user_id)
        return manifest
    except ArtifactException as a_err:
        return JSONResponse(status_code=400, content=a_err.to_dict())
    except Exception:
        req_id = get_current_request_id()
        return JSONResponse(
            status_code=500,
            content={
                "error_code": "ARTIFACT_PLAN_FAILED",
                "message": "Không thể lập kế hoạch tài nguyên lúc này.",
                "request_id": req_id
            }
        )


@router.get("/artifacts/{artifact_id}")
@router.get("/artifacts/{artifact_id}/manifest")
async def get_artifact_endpoint(
    artifact_id: str,
    principal: Principal = Depends(get_current_principal)
):
    """Lấy chi tiết và manifest của một Artifact (có kiểm tra quyền sở hữu, hỗ trợ alias /manifest)."""
    try:
        manifest = get_artifact(
            artifact_id,
            requester_id=principal.user_id,
            is_admin=principal.is_admin,
            principal=principal
        )
        return manifest
    except ArtifactException as a_err:
        status_code = 404 if "NOT_FOUND" in a_err.error_code else 403
        return JSONResponse(status_code=status_code, content=a_err.to_dict())


@router.get("/artifacts/{artifact_id}/preview")
async def get_artifact_preview_endpoint(
    artifact_id: str,
    principal: Principal = Depends(get_current_principal)
):
    """Xem trước nhanh tức thì (< 15ms) dạng SVG hoặc WebP nhẹ (có kiểm tra quyền)."""
    try:
        content, media_type = get_artifact_preview(
            artifact_id,
            requester_id=principal.user_id,
            is_admin=principal.is_admin,
            principal=principal
        )
        return Response(content=content, media_type=media_type)
    except ArtifactException as a_err:
        status_code = 404 if "NOT_FOUND" in a_err.error_code else 403
        return JSONResponse(status_code=status_code, content=a_err.to_dict())


@router.post("/artifacts/render")
async def render_artifact_endpoint(
    req: ArtifactRenderRequest,
    principal: Principal = Depends(get_current_principal)
):
    """
    Kích hoạt quá trình render file qua Durable Queue:
    - Validate request.
    - Đẩy vào Durable Background Queue kèm owner_id và idempotency.
    - Trả chính xác HTTP 202 Accepted cùng job_id và check_status_url.
    - Không thực hiện công việc nặng đồng bộ trong vòng đời request.
    """
    try:
        target_fmt = (req.format or "svg").lower().strip()
        if target_fmt in ("mp3", "mp4", "audio", "video"):
            raise HTTPException(status_code=400, detail="Định dạng âm thanh/video không được hỗ trợ.")

        req_id = get_current_request_id()
        idemp_key = f"render:{req.artifact_id}:{target_fmt}:{principal.user_id or 'anon'}"
        job_id = await JobQueueManager.create_job(
            action="render",
            artifact_id=req.artifact_id,
            target_format=target_fmt,
            owner_id=principal.user_id,
            request_id=req_id,
            idempotency_key=idemp_key
        )

        def _execute_render():
            raw_bytes, media_type, filename = export_artifact(
                req.artifact_id,
                target_fmt,
                requester_id=principal.user_id,
                is_admin=principal.is_admin,
                principal=principal
            )
            return {
                "url": f"/api/artifacts/{req.artifact_id}/file?format={target_fmt}",
                "media_type": media_type,
                "bytes": len(raw_bytes),
                "filename": filename
            }

        JobQueueManager.run_in_background(job_id, _execute_render)
        return JSONResponse(
            status_code=202,
            content={
                "job_id": job_id,
                "status": "queued",
                "artifact_id": req.artifact_id,
                "format": target_fmt,
                "check_status_url": f"/api/jobs/{job_id}"
            }
        )
    except ArtifactException as a_err:
        return JSONResponse(status_code=400, content=a_err.to_dict())


@router.post("/artifacts/{artifact_id}/upscale")
async def upscale_artifact_endpoint(
    artifact_id: str,
    req: ArtifactUpscaleRequest,
    principal: Principal = Depends(get_current_principal)
):
    """
    Upscale ảnh/infographic sang 2x hoặc 4x qua Durable Queue:
    - Trả về chính xác HTTP 202 Accepted.
    - Đẩy vào hàng đợi nền bền vững.
    - Không chạy CPU rasterization trong request HTTP.
    """
    try:
        scale = max(2, min(int(req.scale), 4))
        # Kiểm tra tồn tại và quyền sở hữu trước khi tạo job
        get_artifact(artifact_id, requester_id=principal.user_id, is_admin=principal.is_admin, principal=principal)

        req_id = get_current_request_id()
        idemp_key = f"upscale:{artifact_id}:{scale}:{principal.user_id or 'anon'}"
        job_id = await JobQueueManager.create_job(
            action="upscale",
            artifact_id=artifact_id,
            target_format="png",
            scale=scale,
            owner_id=principal.user_id,
            request_id=req_id,
            idempotency_key=idemp_key
        )

        async def _execute_upscale():
            res = await upscale_artifact(
                artifact_id=artifact_id,
                scale=scale,
                requester_id=principal.user_id,
                is_admin=principal.is_admin,
                principal=principal
            )
            return res

        JobQueueManager.run_in_background(job_id, _execute_upscale)
        return JSONResponse(
            status_code=202,
            content={
                "job_id": job_id,
                "status": "queued",
                "artifact_id": artifact_id,
                "scale": scale,
                "check_status_url": f"/api/jobs/{job_id}"
            }
        )
    except ArtifactException as a_err:
        status_code = 404 if "NOT_FOUND" in a_err.error_code else (403 if "ACCESS_DENIED" in a_err.error_code else 400)
        return JSONResponse(status_code=status_code, content=a_err.to_dict())


@router.post("/artifacts/{artifact_id}/export")
async def export_artifact_endpoint(
    artifact_id: str,
    req: Optional[ArtifactExportRequest] = None,
    format: Optional[str] = Query(None),
    principal: Principal = Depends(get_current_principal)
):
    """
    Tạo job xuất file (.xlsx, .docx, .pdf, .png, .svg, .webp) qua Durable Queue:
    - Trả về chính xác HTTP 202 Accepted.
    - Không thực hiện render nặng đồng bộ trong HTTP request.
    """
    try:
        target_fmt = (format or (req.format if req else None) or "xlsx").lower().strip()
        if target_fmt in ("mp3", "mp4", "audio", "video"):
            raise HTTPException(status_code=400, detail="Định dạng âm thanh/video không được hỗ trợ.")

        # Kiểm tra quyền truy cập artifact
        get_artifact(artifact_id, requester_id=principal.user_id, is_admin=principal.is_admin, principal=principal)

        req_id = get_current_request_id()
        idemp_key = f"export:{artifact_id}:{target_fmt}:{principal.user_id or 'anon'}"
        job_id = await JobQueueManager.create_job(
            action="export",
            artifact_id=artifact_id,
            target_format=target_fmt,
            owner_id=principal.user_id,
            request_id=req_id,
            idempotency_key=idemp_key
        )

        def _execute_export():
            raw_bytes, media_type, filename = export_artifact(
                artifact_id=artifact_id,
                format_str=target_fmt,
                requester_id=principal.user_id,
                is_admin=principal.is_admin,
                principal=principal
            )
            return {
                "url": f"/api/artifacts/{artifact_id}/file?format={target_fmt}",
                "media_type": media_type,
                "bytes": len(raw_bytes),
                "filename": filename
            }

        JobQueueManager.run_in_background(job_id, _execute_export)
        return JSONResponse(
            status_code=202,
            content={
                "job_id": job_id,
                "status": "queued",
                "artifact_id": artifact_id,
                "format": target_fmt,
                "check_status_url": f"/api/jobs/{job_id}"
            }
        )
    except ArtifactException as a_err:
        status_code = 404 if "NOT_FOUND" in a_err.error_code else (403 if "ACCESS_DENIED" in a_err.error_code else 400)
        return JSONResponse(status_code=status_code, content=a_err.to_dict())


@router.get("/artifacts/{artifact_id}/file")
@router.get("/artifacts/{artifact_id}/export")
async def get_artifact_file_endpoint(
    artifact_id: str,
    format: Optional[str] = Query("xlsx"),
    principal: Principal = Depends(get_current_principal)
):
    """
    Tải file vật lý trực tiếp của artifact:
    - TUYỆT ĐỐI KHÔNG khởi tạo tác vụ có side-effect trong GET request.
    - CHỈ phục vụ file ĐÃ ĐƯỢC RENDER sẵn trong StorageAdapter / AssetStore.
    - Nếu file chưa render, trả về HTTP 404 FILE_NOT_RENDERED (chống synchronous heavy work).
    """
    art = ArtifactStore.get_by_id(artifact_id)
    if not art:
        raise HTTPException(status_code=404, detail="Không tìm thấy Artifact.")

    if not ArtifactStore.check_ownership(artifact_id, requester_id=principal.user_id, is_admin=principal.is_admin, principal=principal):
        raise HTTPException(status_code=403, detail="Bạn không có quyền truy cập file này.")

    fmt = (format or "xlsx").lower().strip()
    blob_id = art.get("blob_id") or artifact_id

    # 1. Tra cứu file đã lưu trong AssetStore / StorageAdapter
    from backend.app.services.asset_store import compute_derivative_hash
    export_d_hash = compute_derivative_hash(blob_id, scale=1, file_ext=fmt, quality="standard")
    existing_export = AssetStore.find_by_hash(export_d_hash)
    saved_bytes = None
    media_type = SAFE_MIME_MAP.get(fmt, "application/octet-stream")

    if existing_export and existing_export.get("storage_key"):
        saved_bytes = AssetStore.get_asset_file_bytes(existing_export["asset_id"])
        media_type = existing_export.get("media_type") or media_type

    if saved_bytes is None:
        physical_asset = AssetStore.get_by_id(blob_id) or {}
        if physical_asset.get("file_ext") == fmt and physical_asset.get("storage_key"):
            saved_bytes = AssetStore.get_asset_file_bytes(blob_id)
            media_type = physical_asset.get("media_type") or media_type

    if saved_bytes is None and fmt in ("png", "webp"):
        derivative = AssetStore.find_derivative(blob_id, scale=1, file_ext=fmt)
        if derivative and derivative.get("storage_key"):
            saved_bytes = AssetStore.get_asset_file_bytes(derivative["asset_id"])
            media_type = "image/png" if fmt == "png" else "image/webp"

    # Nếu chưa render: TUYỆT ĐỐI KHÔNG render đồng bộ trong GET, trả 404
    if saved_bytes is None:
        return JSONResponse(
            status_code=404,
            content={
                "error_code": "FILE_NOT_RENDERED",
                "message": f"Tài liệu định dạng '{fmt}' chưa được render. Vui lòng gửi yêu cầu tạo job qua POST /api/artifacts/{artifact_id}/export.",
                "artifact_id": artifact_id,
                "format": fmt
            }
        )

    filename = f"huit_{art.get('manifest', {}).get('type', 'document')}_{artifact_id[:8]}.{fmt}"
    is_private = (art.get("access_scope") == "private") or bool(art.get("owner_id") and art.get("owner_id") != "anonymous")
    cache_control = "private, no-store" if is_private else "public, max-age=3600"

    return Response(
        content=saved_bytes,
        media_type=media_type,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": cache_control
        }
    )


@router.get("/artifacts/download/{storage_key:path}")
async def download_artifact_signed_file(
    storage_key: str,
    sig: str = Query(..., description="HMAC-SHA256 signature"),
    expires: int = Query(..., description="Unix timestamp expiration")
):
    """Tải tệp vật lý trực tiếp với chữ ký số bảo mật (HMAC Signature & Expiration)."""
    # 1. Xác thực chữ ký số và hạn dùng
    if not verify_download_signature(storage_key, expires_at=expires, signature=sig):
        raise HTTPException(status_code=403, detail="Chữ ký tải tệp không hợp lệ hoặc đã hết hạn.")

    # 2. Đọc file từ StorageAdapter
    storage = get_storage_adapter()
    content = storage.get(storage_key)
    if content is None:
        raise HTTPException(status_code=404, detail="Không tìm thấy tệp tin trên hệ thống lưu trữ.")

    # 3. Phân giải media_type
    ext = storage_key.split(".")[-1].lower() if "." in storage_key else "bin"
    media_type = SAFE_MIME_MAP.get(ext, "application/octet-stream")
    filename = storage_key.split("/")[-1]

    return Response(
        content=content,
        media_type=media_type,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "private, no-transform"
        }
    )


@router.get("/jobs/{job_id}", response_model=JobStatusResponse)
async def get_job_status_endpoint(
    job_id: str,
    principal: Principal = Depends(get_current_principal)
):
    """Lấy trạng thái và tiến trình công việc nền (có kiểm tra quyền sở hữu)."""
    try:
        job = JobQueueManager.get_job(
            job_id,
            requester_id=principal.user_id,
            is_admin=principal.is_admin
        )
        if not job:
            raise HTTPException(status_code=404, detail=f"Không tìm thấy công việc {job_id}")
        return job
    except ArtifactException as a_err:
        status_code = 403 if "ACCESS_DENIED" in a_err.error_code else 404
        return JSONResponse(status_code=status_code, content=a_err.to_dict())


@router.get("/jobs/{job_id}/events")
async def get_job_events_endpoint(
    job_id: str,
    principal: Principal = Depends(get_current_principal)
):
    """Lấy lịch sử sự kiện tiến trình của công việc nền."""
    try:
        events = JobQueueManager.get_job_events(
            job_id,
            requester_id=principal.user_id,
            is_admin=principal.is_admin
        )
        return {"job_id": job_id, "events": events}
    except ArtifactException as a_err:
        status_code = 403 if "ACCESS_DENIED" in a_err.error_code else 404
        return JSONResponse(status_code=status_code, content=a_err.to_dict())


@router.post("/jobs/{job_id}/cancel")
async def cancel_job_endpoint(
    job_id: str,
    principal: Principal = Depends(get_current_principal)
):
    """Hủy một tác vụ nền đang chạy hoặc đang chờ."""
    try:
        success = await JobQueueManager.cancel_job(
            job_id,
            requester_id=principal.user_id,
            is_admin=principal.is_admin
        )
        if not success:
            raise HTTPException(status_code=400, detail="Không thể hủy công việc này (đã hoàn thành hoặc không tồn tại).")
        return {"job_id": job_id, "status": "cancelled", "message": "Công việc đã được hủy thành công"}
    except ArtifactException as a_err:
        status_code = 403 if "ACCESS_DENIED" in a_err.error_code else 400
        return JSONResponse(status_code=status_code, content=a_err.to_dict())
