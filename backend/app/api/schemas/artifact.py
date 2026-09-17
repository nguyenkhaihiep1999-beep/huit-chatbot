"""
Pydantic schemas chuẩn hóa cho Hệ thống Artifacts:
- Ultralight JSON Manifest Schema
- Kế hoạch sinh file (Plan Request)
- Yêu cầu render/upscale/export
- Trạng thái công việc nền (Job Status)
"""
import json
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field, field_validator, model_validator

ArtifactType = Literal["spreadsheet", "document", "image"]
RenderQuality = Literal["preview", "standard", "high", "retina", "4k"]
RenderStatus = Literal["pending", "rendering", "ready", "failed"]
ExportFormat = Literal["xlsx", "docx", "pdf", "png", "svg", "webp"]

MAX_MANIFEST_BYTES = 32768  # Tối đa 32KB cho manifest JSON
MAX_TABLE_ROWS = 100
MAX_TABLE_COLS = 20
MAX_LIST_ITEMS = 50

class PreviewInfo(BaseModel):
    type: str = Field(default="svg", description="Định dạng preview (svg, webp, png, json)")
    url: str = Field(..., description="Đường dẫn xem trước nhẹ")
    thumbnail_url: Optional[str] = Field(default=None, description="Ảnh thu nhỏ cực nhẹ")
    width: Optional[int] = Field(default=None)
    height: Optional[int] = Field(default=None)

class RenderInfo(BaseModel):
    status: RenderStatus = Field(default="pending", description="Trạng thái render")
    quality: RenderQuality = Field(default="preview", description="Mức chất lượng")
    scale: int = Field(default=1, ge=1, le=4, description="Hệ số phóng to (1x, 2x, 4x)")
    progress: int = Field(default=100, ge=0, le=100)
    error: Optional[str] = Field(default=None)

class ArtifactManifest(BaseModel):
    """
    Ultralight JSON Manifest Schema.
    Quy tắc:
    - Không chứa Base64 hay binary lớn.
    - Giới hạn kích thước UTF-8 <= 32KB.
    - Có version schema để mở rộng.
    """
    version: int = Field(default=1, description="Phiên bản schema")
    artifact_id: str = Field(..., description="Định danh duy nhất của artifact (art-xxx)")
    type: ArtifactType = Field(..., description="Loại artifact")
    template_id: str = Field(..., description="ID của template dựng hình/tài liệu")
    title: str = Field(..., min_length=1, max_length=200, description="Tên hiển thị tài liệu")
    description: Optional[str] = Field(default=None, max_length=500)
    content: Dict[str, Any] = Field(default_factory=dict, description="Nội dung, dữ liệu bảng, danh sách")
    style: Dict[str, Any] = Field(default_factory=dict, description="Màu sắc, bố cục, theme")
    assets: List[str] = Field(default_factory=list, description="Danh sách asset_id tham chiếu")
    preview: PreviewInfo = Field(..., description="Thông tin xem trước siêu nhẹ")
    render: RenderInfo = Field(default_factory=RenderInfo, description="Trạng thái dựng")
    export_options: List[ExportFormat] = Field(
        default_factory=lambda: ["xlsx", "docx", "pdf", "png", "svg"],
        description="Các định dạng có thể xuất"
    )
    content_hash: Optional[str] = Field(default=None, description="Mã hash SHA-256 chống trùng lặp")
    created_at: Optional[str] = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    owner_id: Optional[str] = Field(default=None, description="User ID hoặc Session ID sở hữu")

    @model_validator(mode="after")
    def validate_manifest_safety_and_limits(self) -> "ArtifactManifest":
        # 1. Kiểm tra kích thước tổng thể
        raw_json = self.model_dump_json()
        encoded_size = len(raw_json.encode("utf-8"))
        if encoded_size > MAX_MANIFEST_BYTES:
            raise ValueError(f"Manifest vượt quá giới hạn cho phép: {encoded_size} > {MAX_MANIFEST_BYTES} bytes")

        # 2. Cấm Base64 lớn trong content & style
        def check_no_large_base64(val: Any):
            if isinstance(val, str):
                if len(val) > 400 and re.search(r"data:[a-zA-Z0-9/]+;base64,", val):
                    raise ValueError("Không được đưa Base64 lớn vào Manifest JSON!")
                if len(val) > 1000 and re.match(r"^[A-Za-z0-9+/=]{1000,}$", val):
                    raise ValueError("Phát hiện chuỗi nhị phân Base64 lớn không hợp lệ!")
            elif isinstance(val, dict):
                for v in val.values():
                    check_no_large_base64(v)
            elif isinstance(val, list):
                for v in val:
                    check_no_large_base64(v)

        check_no_large_base64(self.content)
        check_no_large_base64(self.style)

        # 3. Giới hạn số phần tử trong bảng hoặc danh sách
        rows = self.content.get("rows")
        if isinstance(rows, list) and len(rows) > MAX_TABLE_ROWS:
            raise ValueError(f"Số dòng bảng vượt quá giới hạn: {len(rows)} > {MAX_TABLE_ROWS}")

        headers = self.content.get("headers")
        if isinstance(headers, list) and len(headers) > MAX_TABLE_COLS:
            raise ValueError(f"Số cột bảng vượt quá giới hạn: {len(headers)} > {MAX_TABLE_COLS}")

        items = self.content.get("items")
        if isinstance(items, list) and len(items) > MAX_LIST_ITEMS:
            raise ValueError(f"Số phần tử danh sách vượt quá giới hạn: {len(items)} > {MAX_LIST_ITEMS}")

        return self

class ArtifactSummary(BaseModel):
    """
    Tóm tắt siêu nhẹ dành riêng cho event stream (tối đa ~2KB):
    - Không mang toàn bộ content hay manifest nặng vào luồng chat.
    - Full manifest được tải riêng qua GET /api/artifacts/{artifact_id}.
    """
    artifact_id: str = Field(..., description="Mã tài nguyên")
    type: ArtifactType = Field(..., description="Loại artifact: spreadsheet, document, image")
    title: str = Field(..., description="Tiêu đề hiển thị")
    preview_url: str = Field(..., description="Đường dẫn tải preview SVG nhẹ")
    manifest_url: str = Field(..., description="Đường dẫn API lấy full manifest")
    available_formats: List[ExportFormat] = Field(default_factory=lambda: ["xlsx", "docx", "pdf", "svg"])
    checksum: Optional[str] = Field(default=None, description="Mã SHA-256 xác thực nếu có")
    preview_bytes: Optional[int] = Field(default=None, description="Dung lượng preview tính bằng byte")
    chart_type: Optional[str] = Field(default=None)

    def to_stream_dict(self) -> Dict[str, Any]:
        return self.model_dump(exclude_none=True)


class ArtifactPlanRequest(BaseModel):
    prompt: str = Field(..., min_length=1, max_length=1000, description="Mô tả ngôn ngữ tự nhiên yêu cầu sinh file")
    type: Optional[ArtifactType] = Field(default=None, description="Loại file mong muốn nếu có")
    template_id: Optional[str] = Field(default=None)
    content: Optional[Dict[str, Any]] = Field(default=None)
    user_id: Optional[str] = Field(default=None)
    session_id: Optional[str] = Field(default=None)

class ArtifactRenderRequest(BaseModel):
    artifact_id: str = Field(..., description="Mã artifact cần render")
    format: Optional[ExportFormat] = Field(default="svg")
    quality: Optional[RenderQuality] = Field(default="preview")
    scale: Optional[int] = Field(default=1, ge=1, le=4)

class ArtifactUpscaleRequest(BaseModel):
    scale: int = Field(default=2, ge=2, le=4, description="Hệ số upscale (2x hoặc 4x)")

class ArtifactExportRequest(BaseModel):
    format: ExportFormat = Field(..., description="Định dạng xuất (xlsx, docx, pdf, png, svg)")

class JobStatusResponse(BaseModel):
    job_id: str = Field(...)
    status: Literal["queued", "processing", "completed", "failed", "cancelled"] = Field(...)

    progress: int = Field(default=0, ge=0, le=100)
    artifact_id: Optional[str] = Field(default=None)
    result_url: Optional[str] = Field(default=None)
    download_url: Optional[str] = Field(default=None)
    check_status_url: Optional[str] = Field(default=None)
    media_type: Optional[str] = Field(default=None)
    error: Optional[Dict[str, Any]] = Field(default=None)
    created_at: Optional[str] = Field(default=None)
    updated_at: Optional[str] = Field(default=None)

