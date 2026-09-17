from fastapi import APIRouter, HTTPException, Query, Response, Depends, Request
from fastapi.responses import JSONResponse

from backend.app.services.image_service import (
    ImageRequest,
    create_image as service_create_image,
    get_image as service_get_image,
    list_recent_images as service_list_recent_images,
    render_svg,
)
from backend.app.storage.storage_adapter import get_storage_adapter
from backend.app.services.asset_store import STORAGE_ROOT
from backend.app.api.dependencies.auth import Principal, get_current_principal, check_resource_access
from backend.app.telemetry.logger import get_current_request_id

router = APIRouter()

PLACEHOLDER_THUMBNAIL_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" width="256" height="256" viewBox="0 0 256 256">'
    '<rect width="256" height="256" rx="8" fill="#F1F5F9"/>'
    '<text x="50%" y="46%" dominant-baseline="middle" text-anchor="middle" fill="#0066C4" font-family="system-ui, sans-serif" font-size="22" font-weight="700">HUIT</text>'
    '<text x="50%" y="58%" dominant-baseline="middle" text-anchor="middle" fill="#64748B" font-family="system-ui, sans-serif" font-size="13">Hình ảnh thu nhỏ</text>'
    '</svg>'
).encode("utf-8")


@router.post("/images")
async def generate_image_endpoint(
    req: ImageRequest,
    principal: Principal = Depends(get_current_principal)
):
    """Sinh hình ảnh mascot hoặc bối cảnh sinh viên HUIT bằng FLUX.1 hoặc SVG (On-demand & Dedup)."""
    try:
        res = service_create_image(req, owner_id=principal.user_id)
        return res
    except ValueError as ve:
        raise HTTPException(
            status_code=400,
            detail={"error_code": "INVALID_IMAGE_PROMPT", "message": str(ve)}
        )
    except Exception:
        req_id = get_current_request_id()
        raise HTTPException(
            status_code=500,
            detail={
                "error_code": "IMAGE_GENERATION_FAILED",
                "message": "Không thể sinh hình ảnh tại thời điểm này. Vui lòng thử lại sau.",
                "request_id": req_id
            }
        )


@router.get("/images/{image_id}/file")
async def get_image_file(
    image_id: str,
    principal: Principal = Depends(get_current_principal)
):
    """Lấy file ảnh gốc nhị phân (JPEG hoặc SVG). Không còn dead URL!"""
    rec = service_get_image(image_id)
    if not rec:
        raise HTTPException(status_code=404, detail="Không tìm thấy hình ảnh này.")

    owner = rec.get("owner_id")
    scope = rec.get("access_scope", "public" if not owner else "private")
    if not check_resource_access(principal, owner, scope):
        raise HTTPException(status_code=403, detail="Bạn không có quyền truy cập hình ảnh này.")

    if rec.get("status") == "unavailable" or rec.get("corrupted"):
        raise HTTPException(
            status_code=410,
            detail={
                "error_code": "ERROR_ASSET_UNAVAILABLE",
                "message": "Tài nguyên hình ảnh hiện không khả dụng. Vui lòng tạo lại ảnh mới.",
                "image_id": image_id
            }
        )

    # 1. Đọc file vật lý lưu qua StorageAdapter
    storage_key = rec.get("storage_key")
    if storage_key:
        storage = get_storage_adapter()
        content = storage.get(storage_key)
        if content:
            media_type = rec.get("content_type", "image/jpeg")
            return Response(content=content, media_type=media_type)
        # Fallback local disk (trong môi trường development/test)
        file_path = STORAGE_ROOT / storage_key
        if file_path.exists():
            content = file_path.read_bytes()
            media_type = rec.get("content_type", "image/jpeg")
            return Response(content=content, media_type=media_type)

    # 2. Nếu là scene SVG
    if rec.get("scene"):
        svg_code = render_svg(rec)
        return Response(content=svg_code, media_type="image/svg+xml")

    raise HTTPException(
        status_code=404,
        detail={
            "error_code": "ERROR_ASSET_UNAVAILABLE",
            "message": "Không tìm thấy tệp tin hình ảnh.",
            "image_id": image_id
        }
    )


@router.get("/images/{image_id}/thumbnail")
async def get_image_thumbnail(
    image_id: str,
    principal: Principal = Depends(get_current_principal)
):
    """
    Lấy ảnh thumbnail WebP siêu nhẹ (10-40 KB, tối đa 256px).
    Tuyệt đối không âm thầm trả ảnh gốc dung lượng lớn nếu thiếu thumbnail.
    """
    rec = service_get_image(image_id)
    if not rec:
        raise HTTPException(status_code=404, detail="Không tìm thấy hình ảnh này.")

    owner = rec.get("owner_id")
    scope = rec.get("access_scope", "public" if not owner else "private")
    if not check_resource_access(principal, owner, scope):
        raise HTTPException(status_code=403, detail="Bạn không có quyền xem hình thu nhỏ này.")

    # Đọc thumbnail qua StorageAdapter
    thumb_key = rec.get("thumbnail_key")
    if thumb_key:
        storage = get_storage_adapter()
        thumb_bytes = storage.get(thumb_key)
        if thumb_bytes:
            return Response(content=thumb_bytes, media_type="image/webp" if thumb_key.endswith(".webp") else "image/jpeg")
        thumb_path = STORAGE_ROOT / thumb_key
        if thumb_path.exists():
            return Response(content=thumb_path.read_bytes(), media_type="image/webp" if thumb_key.endswith(".webp") else "image/jpeg")

    # Nếu không có thumbnail WebP, trả về placeholder SVG siêu nhẹ thay vì ảnh gốc khổng lồ
    return Response(content=PLACEHOLDER_THUMBNAIL_SVG, media_type="image/svg+xml")


@router.get("/images/{image_id}/svg")
async def get_image_svg(
    image_id: str,
    principal: Principal = Depends(get_current_principal)
):
    """Render trực tiếp dạng SVG vector sạch."""
    rec = service_get_image(image_id)
    if not rec:
        raise HTTPException(status_code=404, detail="Không tìm thấy hình ảnh này.")

    owner = rec.get("owner_id")
    scope = rec.get("access_scope", "public" if not owner else "private")
    if not check_resource_access(principal, owner, scope):
        raise HTTPException(status_code=403, detail="Bạn không có quyền xem hình ảnh này.")

    if rec.get("scene"):
        svg_code = render_svg(rec)
        return Response(content=svg_code, media_type="image/svg+xml")
    
    return await get_image_file(image_id, principal=principal)


@router.get("/images/{image_id}")
async def get_single_image(
    image_id: str,
    format: str = Query("json", pattern="^(json|svg|png|file|thumbnail)$"),
    principal: Principal = Depends(get_current_principal)
):
    """Lấy thông tin metadata hoặc render trực tiếp ảnh đã sinh theo chuẩn chung."""
    if format == "file":
        return await get_image_file(image_id, principal=principal)
    elif format == "thumbnail":
        return await get_image_thumbnail(image_id, principal=principal)
    elif format == "svg":
        return await get_image_svg(image_id, principal=principal)
    elif format == "png":
        return await get_image_file(image_id, principal=principal)

    rec = service_get_image(image_id)
    if not rec:
        raise HTTPException(status_code=404, detail="Không tìm thấy hình ảnh này.")

    owner = rec.get("owner_id")
    scope = rec.get("access_scope", "public" if not owner else "private")
    if not check_resource_access(principal, owner, scope):
        raise HTTPException(status_code=403, detail="Bạn không có quyền xem thông tin hình ảnh này.")

    clean_rec = {k: v for k, v in rec.items() if k not in ("_id", "image_data", "storage_key", "thumbnail_key")}
    img_id = clean_rec.get("image_id") or image_id
    clean_rec["image_id"] = img_id
    clean_rec["id"] = img_id
    clean_rec["image_url"] = f"/api/images/{img_id}/file"
    clean_rec["thumbnail_url"] = f"/api/images/{img_id}/thumbnail"
    clean_rec["svg_url"] = f"/api/images/{img_id}/svg"
    clean_rec["json_url"] = f"/api/images/{img_id}"
    return clean_rec


@router.get("/images")
async def get_recent_images(
    limit: int = Query(20, ge=1, le=50),
    principal: Principal = Depends(get_current_principal)
):
    """
    Danh sách các hình ảnh gần đây (DTO siêu nhẹ < 2KB, không kèm binary, không scene lớn).
    """
    try:
        return service_list_recent_images(
            owner_id=principal.user_id,
            is_admin=principal.is_admin,
            is_authenticated=principal.is_authenticated,
            limit=limit,
        )
    except Exception:
        return {"count": 0, "items": []}
