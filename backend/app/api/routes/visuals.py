from typing import Optional
from fastapi import APIRouter, HTTPException, Query, Response
from fastapi.responses import JSONResponse
from backend.app.services.visual_service import (
    list_all_visuals,
    get_visual_by_id,
    render_svg_visual,
    render_raster_visual,
    export_visual_to_excel
)

router = APIRouter()

@router.get("/admission-visuals")
async def get_visuals_list(
    category: str = Query("all", description="Bộ lọc danh mục (major, table, roadmap)"),
    search: str = Query("", description="Từ khóa tìm kiếm theo tên hoặc mã ngành")
):
    """Lấy danh sách Visuals tuyển sinh có sẵn."""
    data = list_all_visuals(category=category, search=search)
    return {"count": len(data), "items": data}

@router.get("/admission-visuals/{visual_id}")
async def get_single_visual(visual_id: str):
    """Lấy chi tiết Visual JSON theo ID."""
    doc = get_visual_by_id(visual_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Không tìm thấy bản ghi đồ họa tuyển sinh này.")
    return doc

@router.get("/admission-visuals/{visual_id}/render")
async def render_visual(
    visual_id: str,
    format: str = Query("svg", pattern="^(svg|png|xlsx)$"),
    scale: int = Query(1, ge=1, le=4)
):
    """Dựng trực tiếp hình ảnh vector SVG siêu nét, PNG Retina hoặc Excel."""
    doc = get_visual_by_id(visual_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Không tìm thấy bản ghi để dựng đồ họa.")

    if format == "svg":
        svg_content = render_svg_visual(doc, scale=scale)
        return Response(content=svg_content, media_type="image/svg+xml")
    elif format == "png":
        png_bytes = render_raster_visual(doc, scale=scale)
        if not png_bytes:
            # Fallback về SVG nếu server không có thư viện render PNG
            svg_content = render_svg_visual(doc, scale=scale)
            return Response(content=svg_content, media_type="image/svg+xml")
        return Response(content=png_bytes, media_type="image/png")
    elif format == "xlsx":
        buf = export_visual_to_excel(doc)
        return Response(
            content=buf.getvalue(),
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f'attachment; filename="{visual_id}.xlsx"'}
        )
