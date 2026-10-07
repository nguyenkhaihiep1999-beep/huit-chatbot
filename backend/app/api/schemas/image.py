"""image.py
Pydantic schemas chuẩn hóa cho Hệ thống Image Generation:
- ImageCreateRequest (alias ImageRequest)
- ImageResult
Khớp chính xác với canonical schemas:
- huit.api.image-create-request@1.0.0
- huit.api.image-result@1.0.0
"""
from typing import Literal, Optional
from pydantic import BaseModel, ConfigDict, Field


class ImageCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    prompt: str = Field(..., min_length=1, max_length=800, description="Mô tả ngôn ngữ tự nhiên yêu cầu sinh ảnh")
    width: int = Field(default=512, ge=128, le=1024, description="Chiều rộng ảnh (pixel)")
    height: int = Field(default=512, ge=128, le=1024, description="Chiều cao ảnh (pixel)")
    max_json_kb: int = Field(default=12, ge=2, le=24, description="Kích thước tối đa cho Scene SVG (KB)")
    style: Optional[str] = Field(default="photorealistic", description="Phong cách hình ảnh")
    backend: Literal["flux", "svg"] = Field(default="flux", description="Bộ sinh ảnh backend")
    regenerate: bool = Field(default=False, description="Cờ bắt buộc tạo ảnh mới, bỏ qua cache")


# Alias for backward compatibility across image services and routes
ImageRequest = ImageCreateRequest


class ImageResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    image_id: str = Field(..., min_length=1, max_length=64, description="Mã định danh ảnh")
    id: Optional[str] = Field(default=None, description="Mã định danh alias")
    image_url: str = Field(..., description="Đường dẫn truy xuất file ảnh")
    thumbnail_url: Optional[str] = Field(default=None, description="Đường dẫn ảnh thu nhỏ")
    svg_url: Optional[str] = Field(default=None, description="Đường dẫn xem dạng SVG")
    json_url: Optional[str] = Field(default=None, description="Đường dẫn metadata JSON")
    width: Optional[int] = Field(default=None, description="Chiều rộng ảnh")
    height: Optional[int] = Field(default=None, description="Chiều cao ảnh")
    model: Optional[str] = Field(default=None, description="Mô hình sinh ảnh")
    style: Optional[str] = Field(default=None, description="Phong cách ảnh")
    byte_size: Optional[int] = Field(default=None, description="Kích thước tệp (bytes)")
    checksum: Optional[str] = Field(default=None, description="Mã checksum SHA-256")
    request_fingerprint: Optional[str] = Field(default=None, description="Fingerprint của yêu cầu")
    billing: Optional[str] = Field(default=None, description="Gói cước")
    cached: Optional[bool] = Field(default=None, description="Cờ ảnh được lấy từ cache")
    access_scope: Optional[Literal["public", "private", "legacy_public"]] = Field(
        default="public", description="Phạm vi truy cập"
    )
    owner_id: Optional[str] = Field(default=None, max_length=64, description="User ID sở hữu")
