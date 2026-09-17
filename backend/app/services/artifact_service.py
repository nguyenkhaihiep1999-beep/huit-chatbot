"""
artifact_service.py
Dịch vụ điều phối toàn diện cho Artifacts theo mô hình 'Mô tả nhẹ – Dựng nội dung khi cần':
- Tạo kế hoạch (Plan / Manifest) siêu nhẹ, không chứa nhị phân.
- Tái sử dụng tài nguyên (Deduplication) dựa trên Canonical Hashing.
- Dựng trước Preview (SVG / WebP) ngay lập tức (< 15ms).
- Chỉ dựng file nặng (Word, Excel, PDF, Upscale) khi người dùng yêu cầu.
- Chống chạy đua đồng thời (Concurrency Lock) cho các request giống nhau.
- Tích hợp chuẩn xác số liệu tuyển sinh HUIT 2026.
"""
import copy
import io
import json
import secrets
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from backend.app.api.schemas.artifact import (
    ArtifactManifest,
    ArtifactPlanRequest,
    PreviewInfo,
    RenderInfo
)
from backend.app.rag.artifact_intent import (
    TUITION_DATA_2026,
    CUTOFF_DATA_2026,
    detect_file_generation_intent,
    should_attach_illustrative_infographic
)
from backend.app.services.asset_store import (
    AssetStore,
    ArtifactStore,
    compute_canonical_hash,
    normalize_string_for_hash,
    get_hash_lock,
    RENDERER_VERSION,
    SAFE_MIME_MAP,
    compute_derivative_hash
)
from backend.app.services.docx_renderer import render_manifest_to_docx
from backend.app.services.pdf_renderer import render_manifest_to_pdf
from backend.app.services.visual_service import (
    render_svg_visual,
    render_raster_visual,
    export_visual_to_excel,
    get_visual_by_id,
    find_visual_by_context
)
from backend.app.telemetry.errors import (
    ArtifactException,
    ERROR_ARTIFACT_ACCESS_DENIED,
    ERROR_ARTIFACT_NOT_FOUND,
    ERROR_ARTIFACT_RENDER_FAILED,
    ERROR_ARTIFACT_UPSCALE_FAILED,
    ERROR_EXPORT_FAILED,
    ERROR_UNSUPPORTED_FILE_TYPE
)


def _normalize_artifact_type(val: Optional[str]) -> str:
    if not val:
        return "document"
    v = val.lower().strip().replace(".", "")
    if v in ("xlsx", "excel", "spreadsheet", "csv"):
        return "spreadsheet"
    if v in ("docx", "doc", "word", "document", "pdf"):
        return "document"
    if v in ("png", "svg", "webp", "jpg", "jpeg", "image"):
        return "image"
    return "document"


def _resolve_template_and_content_for_prompt(
    prompt: str,
    requested_type: Optional[str] = None
) -> Tuple[str, str, str, Dict[str, Any]]:
    """
    Xác định template_id, artifact_type, title và content từ prompt ngôn ngữ tự nhiên.
    """
    p_norm = normalize_string_for_hash(prompt)
    norm_type = _normalize_artifact_type(requested_type) if requested_type else None
    
    # 1. Học phí
    if any(k in p_norm for k in ["hoc phi", "tin chi", "tien hoc", "chi phi"]):
        return (
            "tuition-table-v1",
            norm_type or "spreadsheet",
            "Bảng Tra Cứu Định Mức Học Phí HUIT 2026",
            copy.deepcopy(TUITION_DATA_2026)
        )

    # 2. Điểm chuẩn / Điểm sàn
    if any(k in p_norm for k in ["diem chuan", "diem san", "diem trung tuyen"]):
        return (
            "cutoff-table-v1",
            "spreadsheet" if requested_type in (None, "spreadsheet", "document") else requested_type,
            "Bảng Điểm Chuẩn Trúng Tuyển Chính Thức HUIT 2026",
            copy.deepcopy(CUTOFF_DATA_2026)
        )

    # 3. Phương thức tuyển sinh / Thủ tục nhập học
    if any(k in p_norm for k in ["nhap hoc", "thu tuc nhap hoc"]):
        doc = get_visual_by_id("roadmap_nhaphoc_2026")
        content = doc or {
            "title": "QUY TRÌNH NHẬP HỌC TÂN SINH VIÊN K2026",
            "steps": [
                {"title": "Bước 1", "name": "Tra cứu kết quả", "desc": "Tại nhaphoc.huit.edu.vn từ 12/08/2026"},
                {"title": "Bước 2", "name": "Xác nhận nhập học", "desc": "Xác nhận trên cổng tuyển sinh Bộ GD&ĐT trước 17h00 ngày 21/08/2026"},
                {"title": "Bước 3", "name": "Đóng học phí & Nhận lớp", "desc": "Thanh toán trực tuyến hoặc tại Phòng Tài chính HUIT"},
            ]
        }
        return ("roadmap-nhaphoc-v1", "document", "Sơ Đồ Quy Trình Nhập Học HUIT 2026", content)

    # 4. Ngành đào tạo cụ thể (thử tìm theo mã ngành hoặc từ khóa trong visual_service)
    matched_visual = find_visual_by_context("general", prompt)
    if matched_visual:
        v_type = matched_visual.get("type", "major_card")
        art_type = "spreadsheet" if v_type == "excel_table" else "image"
        return (
            f"template-{matched_visual.get('visual_id', 'custom')}",
            art_type,
            matched_visual.get("title", "Thông tin Tuyển sinh HUIT"),
            matched_visual
        )

    # 5. Mặc định tài liệu tuyển sinh chung
    return (
        "general-admissions-v1",
        requested_type or "document",
        "Thông Tin Tư Vấn Tuyển Sinh HUIT 2026",
        {
            "title": "THÔNG TIN TUYỂN SINH TRƯỜNG ĐẠI HỌC CÔNG THƯƠNG TP.HCM",
            "headers": ["Chỉ mục", "Nội dung thông tin", "Ghi chú"],
            "rows": [
                ["1", "Thời gian nhập học", "Từ 12/08/2026 đến 21/08/2026"],
                ["2", "Cổng thông tin tuyển sinh", "https://ts.huit.edu.vn"],
                ["3", "Hotline tư vấn tuyển sinh", "(028) 3816 1673"],
            ]
        }
    )


async def create_artifact_plan(req: ArtifactPlanRequest, owner_id: Optional[str] = None) -> ArtifactManifest:
    """
    Tạo một kế hoạch Artifact Manifest siêu nhẹ (JSON manifest).
    - Kiểm tra cache chống trùng lặp (Deduplication) theo user và theo nội dung blob.
    - User B có cùng nội dung với User A sẽ tái sử dụng blob_id nhưng có artifact_id và owner_id riêng biệt, không rò rỉ manifest của User A.
    - Không sinh file nhị phân lớn ở bước này.
    """
    prompt = req.prompt.strip()
    template_id, art_type, title, content = _resolve_template_and_content_for_prompt(prompt, req.type)

    if req.template_id:
        template_id = req.template_id
    if req.content:
        content = req.content

    style = {
        "theme": "huit_royal_blue",
        "primary_color": "#0066C4",
        "font_family": "Calibri, Segoe UI, sans-serif"
    }

    # 1. Tính toán Canonical Hash
    c_hash = compute_canonical_hash(
        prompt=prompt,
        template_id=template_id,
        content=content,
        style=style,
        renderer_version=RENDERER_VERSION
    )

    clean_owner = owner_id or req.user_id or req.session_id
    if clean_owner == "anonymous":
        clean_owner = None

    # 2. Khóa Concurrency Lock
    lock = await get_hash_lock(c_hash)
    async with lock:
        # 2a. Nếu chính user này đã yêu cầu cùng nội dung trước đó, trả về manifest của chính họ
        existing_user_art = ArtifactStore.find_by_owner_and_hash(clean_owner, c_hash)
        if existing_user_art and existing_user_art.get("manifest"):
            m_dict = copy.deepcopy(existing_user_art["manifest"])
            m_dict.setdefault("render", {})["status"] = "ready"
            return ArtifactManifest.model_validate(m_dict)

        # 2b. Kiểm tra xem physical blob đã tồn tại chưa (Deduplication ở tầng blob)
        existing_blob = AssetStore.find_by_hash(c_hash)
        blob_id = existing_blob["asset_id"] if existing_blob else None

        # 3. Khởi tạo Artifact ID mới cho user này
        artifact_id = f"art_{secrets.token_hex(10)}"
        if not blob_id:
            blob_id = artifact_id
        preview_url = f"/api/artifacts/{artifact_id}/preview"

        manifest_dict = {
            "version": 1,
            "artifact_id": artifact_id,
            "type": art_type,
            "template_id": template_id,
            "title": title,
            "description": f"Dữ liệu chính thức chuẩn hóa theo yêu cầu: {prompt[:80]}",
            "content": content,
            "style": style,
            "assets": [],
            "preview": {
                "type": "svg",
                "url": preview_url
            },
            "render": {
                "status": "pending",
                "quality": "preview",
                "scale": 1,
                "progress": 100
            },
            "export_options": ["xlsx", "docx", "pdf", "png", "svg"],
            "content_hash": c_hash,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "owner_id": clean_owner
        }

        # Validate qua Pydantic schema
        manifest = ArtifactManifest.model_validate(manifest_dict)

        # Lưu logical artifact vào ArtifactStore
        ArtifactStore.save_artifact(
            artifact_id=artifact_id,
            manifest=manifest.model_dump(),
            owner_id=clean_owner,
            blob_id=blob_id,
            access_scope="private" if clean_owner else "public",
            content_hash=c_hash
        )

        # Nếu physical asset chưa tồn tại, khởi tạo placeholder trong AssetStore
        if not existing_blob:
            AssetStore.save_asset(
                asset_id=blob_id,
                media_type="application/json",
                content_hash=c_hash,
                preview_key=preview_url
            )

        return manifest


def get_artifact(artifact_id: str, requester_id: Optional[str] = None, is_admin: bool = False, principal: Any = None) -> Dict[str, Any]:
    """Lấy chi tiết một Artifact Manifest từ ArtifactStore (kiểm tra quyền riêng tư)."""
    art = ArtifactStore.get_by_id(artifact_id)
    if not art:
        raise ArtifactException(
            error_code=ERROR_ARTIFACT_NOT_FOUND,
            message=f"Không tìm thấy Artifact có mã {artifact_id}",
            artifact_id=artifact_id
        )
    # Kiểm tra quyền truy cập
    if not ArtifactStore.check_ownership(artifact_id, requester_id=requester_id, is_admin=is_admin, principal=principal):
        raise ArtifactException(
            error_code=ERROR_ARTIFACT_ACCESS_DENIED,
            message="Bạn không có quyền truy cập tài nguyên này",
            artifact_id=artifact_id
        )
    return art.get("manifest") or art


def get_artifact_preview(artifact_id: str, requester_id: Optional[str] = None, is_admin: bool = False, principal: Any = None) -> Tuple[str, str]:
    """
    Sinh preview tức thì (< 15ms) dạng SVG vector nét căng.
    """
    art = ArtifactStore.get_by_id(artifact_id)
    if not art:
        raise ArtifactException(
            error_code=ERROR_ARTIFACT_NOT_FOUND,
            message=f"Không tìm thấy Artifact {artifact_id} để tạo preview",
            artifact_id=artifact_id
        )
    if not ArtifactStore.check_ownership(artifact_id, requester_id=requester_id, is_admin=is_admin, principal=principal):
        raise ArtifactException(
            error_code=ERROR_ARTIFACT_ACCESS_DENIED,
            message="Bạn không có quyền xem trước tài nguyên này",
            artifact_id=artifact_id
        )
    manifest = art.get("manifest") or {}
    content = manifest.get("content") or {}
    
    # Định dạng theo loại template
    data_for_render = copy.deepcopy(content)
    if "type" not in data_for_render:
        if "headers" in data_for_render and "rows" in data_for_render:
            data_for_render["type"] = "excel_table"
        elif "steps" in data_for_render:
            data_for_render["type"] = "roadmap"
        else:
            data_for_render["type"] = "major_card"
            
    if "title" not in data_for_render:
        data_for_render["title"] = manifest.get("title", "Thông tin Tuyển sinh HUIT")

    svg_code = render_svg_visual(data_for_render, scale=1)
    return svg_code, "image/svg+xml"


async def upscale_artifact(artifact_id: str, scale: int = 2, requester_id: Optional[str] = None, is_admin: bool = False, principal: Any = None) -> Dict[str, Any]:
    """
    Upscale ảnh/infographic theo yêu cầu (2x hoặc 4x).
    Chỉ thực hiện khi người dùng nhấn 'Xem rõ' hoặc 'Phóng to'.
    Tự động tái sử dụng nếu bản derivative cùng scale đã tồn tại (Deduplication).
    """
    art = ArtifactStore.get_by_id(artifact_id)
    if not art:
        raise ArtifactException(
            error_code=ERROR_ARTIFACT_NOT_FOUND,
            message=f"Không tìm thấy Artifact {artifact_id} để upscale",
            artifact_id=artifact_id
        )
    if not ArtifactStore.check_ownership(artifact_id, requester_id=requester_id, is_admin=is_admin, principal=principal):
        raise ArtifactException(
            error_code=ERROR_ARTIFACT_ACCESS_DENIED,
            message="Bạn không có quyền thao tác trên tài nguyên này",
            artifact_id=artifact_id
        )

    scale = max(2, min(int(scale), 4))
    blob_id = art.get("blob_id") or artifact_id

    manifest = art.get("manifest") or {}
    preview_info = manifest.get("preview") or {}
    if manifest.get("type") == "vector" or (isinstance(preview_info, dict) and preview_info.get("type") == "svg" and "rows" not in (manifest.get("content") or {})):
        # Vector / SVG là định dạng độc lập độ phân giải, không cần upscale file nhị phân
        return {
            "upscaled_id": artifact_id,
            "original_id": artifact_id,
            "scale": scale,
            "format": "svg",
            "url": f"/api/artifacts/{artifact_id}/preview?scale={scale}",
            "bytes": len(json.dumps(manifest).encode("utf-8")),
            "is_vector": True
        }

    owner = requester_id or art.get("owner_id")
    # 1. TÁI SỬ DỤNG DERIVATIVE NẾU ĐÃ CÓ:
    existing_derivative = AssetStore.find_derivative(blob_id, scale=scale, file_ext="png")
    if existing_derivative:
        user_derivative_id = f"art_up_{secrets.token_hex(8)}"
        ArtifactStore.save_artifact(
            artifact_id=user_derivative_id,
            manifest=manifest,
            owner_id=owner,
            blob_id=existing_derivative["asset_id"],
            access_scope=art.get("access_scope", "public"),
            source_artifact_id=artifact_id,
            derivative_spec={"scale": scale, "format": "png"}
        )
        return {
            "upscaled_id": user_derivative_id,
            "original_id": artifact_id,
            "scale": scale,
            "format": "png",
            "url": f"/api/artifacts/{user_derivative_id}/export?format=png",
            "bytes": existing_derivative.get("file_size", 0)
        }

    content = manifest.get("content") or {}

    data_for_render = copy.deepcopy(content)
    if "type" not in data_for_render:
        data_for_render["type"] = "excel_table" if ("headers" in data_for_render and "rows" in data_for_render) else "major_card"

    # Khóa concurrency per derivative hash chống chạy đua
    d_lock = await get_hash_lock(f"upscale_{blob_id}_{scale}")
    async with d_lock:
        # Double-check
        existing_again = AssetStore.find_derivative(blob_id, scale=scale, file_ext="png")
        if existing_again:
            user_derivative_id = f"art_up_{secrets.token_hex(8)}"
            ArtifactStore.save_artifact(
                artifact_id=user_derivative_id,
                manifest=manifest,
                owner_id=owner,
                blob_id=existing_again["asset_id"],
                access_scope=art.get("access_scope", "public"),
                source_artifact_id=artifact_id,
                derivative_spec={"scale": scale, "format": "png"}
            )
            return {
                "upscaled_id": user_derivative_id,
                "original_id": artifact_id,
                "scale": scale,
                "format": "png",
                "url": f"/api/artifacts/{user_derivative_id}/export?format=png",
                "bytes": existing_again.get("file_size", 0)
            }

        try:
            raster_bytes = render_raster_visual(data_for_render, scale=scale, format="png")
            upscaled_blob_id = f"art_upscaled_{secrets.token_hex(8)}"
            
            # Lưu physical derivative blob
            AssetStore.save_asset(
                asset_id=upscaled_blob_id,
                media_type="image/png",
                content_hash=f"{art.get('content_hash', '')}_scale_{scale}",
                raw_bytes=raster_bytes,
                file_ext="png",
                source_asset_id=blob_id,
                scale=scale
            )
            # Lưu logical artifact riêng cho owner
            user_derivative_id = f"art_up_{secrets.token_hex(8)}"
            ArtifactStore.save_artifact(
                artifact_id=user_derivative_id,
                manifest=manifest,
                owner_id=owner,
                blob_id=upscaled_blob_id,
                access_scope=art.get("access_scope", "public"),
                source_artifact_id=artifact_id,
                derivative_spec={"scale": scale, "format": "png"}
            )

            return {
                "upscaled_id": upscaled_blob_id,
                "original_id": artifact_id,
                "scale": scale,
                "format": "png",
                "url": f"/api/artifacts/{upscaled_blob_id}/export?format=png",
                "bytes": len(raster_bytes)
            }
        except Exception as ex:
            raise ArtifactException(
                error_code=ERROR_ARTIFACT_UPSCALE_FAILED,
                message=f"Lỗi upscale artifact: {str(ex)}",
                artifact_id=artifact_id
            )


def export_artifact(artifact_id: str, format_str: str, requester_id: Optional[str] = None, is_admin: bool = False, principal: Any = None) -> Tuple[bytes, str, str]:
    """
    Dựng file nặng và xuất dữ liệu theo định dạng yêu cầu:
    - xlsx: Microsoft Excel
    - docx: Microsoft Word
    - pdf: Adobe PDF
    - png: Raster PNG (scale phù hợp)
    - svg: Vector SVG
    - webp: WebP image
    Returns (raw_bytes, media_type, filename)
    Tự động đọc file đã lưu nếu có (không re-render).
    """
    art = ArtifactStore.get_by_id(artifact_id)
    if not art:
        raise ArtifactException(
            error_code=ERROR_ARTIFACT_NOT_FOUND,
            message=f"Không tìm thấy Artifact {artifact_id} để xuất file",
            artifact_id=artifact_id
        )
    if not ArtifactStore.check_ownership(artifact_id, requester_id=requester_id, is_admin=is_admin, principal=principal):
        raise ArtifactException(
            error_code=ERROR_ARTIFACT_ACCESS_DENIED,
            message="Bạn không có quyền xuất tài nguyên này",
            artifact_id=artifact_id
        )

    fmt = format_str.lower().strip().replace(".", "")
    if fmt in ("mp3", "mp4", "audio", "video"):
        raise ArtifactException(
            error_code=ERROR_UNSUPPORTED_FILE_TYPE,
            message=f"Định dạng xuất '{fmt}' không được hỗ trợ",
            artifact_id=artifact_id
        )

    blob_id = art.get("blob_id") or artifact_id
    physical_asset = AssetStore.get_by_id(blob_id) or {}
    manifest = art.get("manifest") or {}
    content = manifest.get("content") or {}

    filename = f"huit_{manifest.get('type', 'document')}_{secrets.token_hex(4)}.{fmt}"

    # 1. TÁI SỬ DỤNG FILE ĐÃ LƯU: Kiểm tra physical derivative blob theo composite hash
    target_scale = 1
    export_d_hash = compute_derivative_hash(blob_id, scale=target_scale, file_ext=fmt, quality="standard")
    existing_export = AssetStore.find_by_hash(export_d_hash)
    if existing_export and existing_export.get("storage_key"):
        saved_bytes = AssetStore.get_asset_file_bytes(existing_export["asset_id"])
        if saved_bytes is not None:
            media_type = existing_export.get("media_type") or SAFE_MIME_MAP.get(fmt, "application/octet-stream")
            return saved_bytes, media_type, filename

    if physical_asset.get("file_ext") == fmt and physical_asset.get("storage_key"):
        saved_bytes = AssetStore.get_asset_file_bytes(blob_id)
        if saved_bytes is not None:
            media_type = physical_asset.get("media_type") or SAFE_MIME_MAP.get(fmt, "application/octet-stream")
            return saved_bytes, media_type, filename

    # 2. Nếu định dạng là ảnh raster (png, webp), kiểm tra xem có derivative khớp scale không
    if fmt in ("png", "webp"):
        derivative = AssetStore.find_derivative(blob_id, scale=target_scale, file_ext=fmt)
        if derivative and derivative.get("storage_key"):
            saved_bytes = AssetStore.get_asset_file_bytes(derivative["asset_id"])
            if saved_bytes is not None:
                media_type = "image/png" if fmt == "png" else "image/webp"
                return saved_bytes, media_type, filename

    try:
        if fmt == "xlsx":
            data_to_export = copy.deepcopy(content)
            if "headers" not in data_to_export and "rows" not in data_to_export:
                data_to_export["type"] = "major_card"
            buf = export_visual_to_excel(data_to_export)
            raw_bytes = buf.getvalue()
            media_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

        elif fmt == "docx":
            buf = render_manifest_to_docx(manifest)
            raw_bytes = buf.getvalue()
            media_type = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

        elif fmt == "pdf":
            buf = render_manifest_to_pdf(manifest)
            raw_bytes = buf.getvalue()
            media_type = "application/pdf"

        elif fmt == "svg":
            svg_code, media_type = get_artifact_preview(artifact_id, requester_id=requester_id, is_admin=is_admin, principal=principal)
            raw_bytes = svg_code.encode("utf-8")

        elif fmt in ("png", "webp"):
            scale = target_scale
            data_to_export = copy.deepcopy(content)
            if "type" not in data_to_export:
                data_to_export["type"] = "excel_table" if "headers" in data_to_export else "major_card"
            raw_bytes = render_raster_visual(data_to_export, scale=scale, format=fmt)
            media_type = "image/png" if fmt == "png" else "image/webp"

        else:
            raise ArtifactException(
                error_code=ERROR_UNSUPPORTED_FILE_TYPE,
                message=f"Định dạng xuất '{fmt}' không được hỗ trợ",
                artifact_id=artifact_id
            )

        # Lưu file nhị phân thành physical derivative riêng biệt trong AssetStore (không ghi đè source blob)
        if fmt in ("xlsx", "docx", "pdf", "png", "webp"):
            export_blob_id = f"art_exp_{secrets.token_hex(8)}"
            AssetStore.save_asset(
                asset_id=export_blob_id,
                media_type=media_type,
                content_hash=export_d_hash,
                raw_bytes=raw_bytes,
                file_ext=fmt,
                source_asset_id=blob_id,
                scale=target_scale
            )

        return raw_bytes, media_type, filename

    except ArtifactException:
        raise
    except Exception as ex:
        raise ArtifactException(
            error_code=ERROR_EXPORT_FAILED,
            message=f"Lỗi khi xuất file {fmt}: {str(ex)}",
            artifact_id=artifact_id
        )


def resolve_artifact_for_chat(
    intent: str,
    question: str,
    docs: Optional[List[Dict[str, Any]]] = None,
    owner_id: Optional[str] = None
) -> Optional[Dict[str, Any]]:
    """
    Tích hợp với RAG Pipeline:
    Tự động chuẩn bị Artifact Manifest cho câu hỏi của người dùng (học phí, điểm chuẩn, hoặc yêu cầu tạo file).
    Dữ liệu trả về giữ nguyên tính tương thích với trường 'visual' của frontend cũ, đồng thời cung cấp đầy đủ
    cấu trúc 'artifact' manifest siêu nhẹ.
    """
    fmt, topic = detect_file_generation_intent(question)
    infographic_topic = should_attach_illustrative_infographic(intent, question)

    if not fmt and not infographic_topic:
        return None

    # Tạo plan manifest
    template_id, art_type, title, content = _resolve_template_and_content_for_prompt(question, fmt)

    c_hash = compute_canonical_hash(
        prompt=question,
        template_id=template_id,
        content=content,
        renderer_version=RENDERER_VERSION
    )

    clean_owner = owner_id if (owner_id and owner_id != "anonymous") else None

    # Kiểm tra artifact của user này
    user_art = ArtifactStore.find_by_owner_and_hash(clean_owner, c_hash)
    if user_art and user_art.get("manifest"):
        art_id = user_art["artifact_id"]
        manifest = user_art["manifest"]
    else:
        # Tìm blob
        existing_blob = AssetStore.find_by_hash(c_hash)
        blob_id = existing_blob["asset_id"] if existing_blob else None

        art_id = f"art_{secrets.token_hex(8)}"
        if not blob_id:
            blob_id = art_id
        preview_url = f"/api/artifacts/{art_id}/preview"

        manifest_dict = {
            "version": 1,
            "artifact_id": art_id,
            "type": art_type,
            "template_id": template_id,
            "title": title,
            "description": "Dữ liệu chính thức chuẩn hóa từ Cổng tuyển sinh HUIT 2026",
            "content": content,
            "style": {"theme": "huit_royal_blue", "primary_color": "#0066C4"},
            "assets": [],
            "preview": {"type": "svg", "url": preview_url},
            "render": {"status": "ready", "quality": "preview", "scale": 1, "progress": 100},
            "export_options": ["xlsx", "docx", "pdf", "png", "svg"],
            "content_hash": c_hash,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "owner_id": clean_owner
        }
        manifest = ArtifactManifest.model_validate(manifest_dict).model_dump()

        # Lưu logical artifact
        ArtifactStore.save_artifact(
            artifact_id=art_id,
            manifest=manifest,
            owner_id=clean_owner,
            blob_id=blob_id,
            access_scope="private" if clean_owner else "public",
            content_hash=c_hash
        )

        # Lưu physical asset placeholder nếu chưa có
        if not existing_blob:
            AssetStore.save_asset(
                asset_id=blob_id,
                media_type="application/json",
                content_hash=c_hash,
                preview_key=preview_url
            )

    # Dữ liệu tương thích ngược cho Visual Card cũ
    return {
        "visual_id": art_id,
        "artifact_id": art_id,
        "type": content.get("type", "excel_table" if "headers" in content else "major_card"),
        "title": title,
        "svg_url": f"/api/artifacts/{art_id}/preview",
        "png_url": f"/api/artifacts/{art_id}/export?format=png",
        "xlsx_url": f"/api/artifacts/{art_id}/export?format=xlsx",
        "docx_url": f"/api/artifacts/{art_id}/export?format=docx",
        "pdf_url": f"/api/artifacts/{art_id}/export?format=pdf",
        "json_url": f"/api/artifacts/{art_id}",
        "manifest": manifest,
        "raw": content
    }
