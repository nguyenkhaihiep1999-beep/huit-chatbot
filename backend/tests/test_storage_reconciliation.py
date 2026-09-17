"""
test_storage_reconciliation.py
Unit tests cho cơ chế đối soát lưu trữ (Storage Reconciliation & File Integrity):
- Kiểm tra phục hồi deterministic SVG từ scene.
- Kiểm tra phục hồi deterministic Excel từ manifest content.
- Kiểm tra phát hiện file bị xóa/thất lạc thực tế.
- Kiểm tra endpoint trả mã lỗi ERROR_ASSET_UNAVAILABLE khi tài nguyên unavailable.
100% offline, không gọi dịch vụ bên ngoài.
"""
import io
import hashlib
import tempfile
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from backend.app.main import app
from backend.app.services.image_service import render_svg, Scene
from backend.app.services.visual_service import export_visual_to_excel
from backend.app.storage.storage_adapter import LocalStorageAdapter
from backend.app.repositories.mongo_repository import MongoRepository
from scripts.storage_reconciliation import collect_referenced_storage_keys

client = TestClient(app)


def test_orphan_detection_collects_all_supported_reference_keys():
    keys = collect_referenced_storage_keys(
        assets=[{"storage_key": "main.jpg", "preview_key": "preview.webp"}],
        images=[
            {
                "storage_key": "image.jpg",
                "thumbnail_key": "thumb.webp",
                "preview_key": "legacy_preview.webp",
            }
        ],
        admission_visuals=[{"storage_key": "visual.svg"}, {"storage_key": None}],
    )

    assert keys == {
        "main.jpg",
        "preview.webp",
        "image.jpg",
        "thumb.webp",
        "legacy_preview.webp",
        "visual.svg",
    }


def test_deterministic_svg_render():
    """Kiểm tra việc render SVG từ scene là hoàn toàn deterministic."""
    sample_doc = {
        "width": 512,
        "height": 512,
        "scene": {
            "background": "#0066C4",
            "shapes": [
                {"type": "rect", "x": 50, "y": 50, "width": 200, "height": 100, "fill": "#FFFFFF"},
                {"type": "circle", "x": 256, "y": 256, "radius": 80, "fill": "#FFCC00"},
                {"type": "text", "x": 100, "y": 300, "text": "HUIT Tuyển Sinh", "size": 24, "fill": "#FFFFFF"}
            ]
        }
    }
    
    svg_1 = render_svg(sample_doc)
    svg_2 = render_svg(sample_doc)
    
    assert svg_1 == svg_2
    assert "<svg" in svg_1
    assert "</svg>" in svg_1
    assert "HUIT Tuyển Sinh" in svg_1
    
    b1 = svg_1.encode("utf-8")
    assert hashlib.sha256(b1).hexdigest() == hashlib.sha256(svg_2.encode("utf-8")).hexdigest()


def test_deterministic_excel_render():
    """Cùng manifest phải tạo XLSX hợp lệ và có bytes/checksum giống hệt nhau."""
    sample_manifest = {
        "title": "Bảng Điểm Chuẩn HUIT 2026",
        "content": {
            "title": "BẢNG ĐIỂM CHUẨN TRÚNG TUYỂN",
            "headers": ["Mã ngành", "Tên ngành", "Điểm chuẩn"],
            "rows": [
                ["7480201", "Công nghệ thông tin", "20.00"],
                ["7480107", "Trí tuệ nhân tạo", "20.50"]
            ]
        }
    }
    
    first = export_visual_to_excel(sample_manifest["content"]).getvalue()
    second = export_visual_to_excel(sample_manifest["content"]).getvalue()

    assert len(first) > 1000
    # File XLSX bản chất là ZIP archive, bắt đầu bằng magic bytes 'PK\x03\x04'
    assert first[:4] == b"PK\x03\x04"
    assert first == second
    assert hashlib.sha256(first).digest() == hashlib.sha256(second).digest()


def test_storage_adapter_detects_physical_file_removal(tmp_path):
    """Kiểm tra StorageAdapter phát hiện chính xác khi file bị xóa trên đĩa thực tế."""
    adapter = LocalStorageAdapter(root_dir=tmp_path)
    
    key = "test_artifact_file.txt"
    content = b"HUIT Chatbot Physical Blob Content"
    put_res = adapter.put(key, content, media_type="text/plain")
    
    assert adapter.exists(key) is True
    assert adapter.get(key) == content
    assert put_res["checksum"] == hashlib.sha256(content).hexdigest()
    
    # Xóa file vật lý trên đĩa
    file_on_disk = tmp_path / key
    file_on_disk.unlink()
    
    # Adapter phải phát hiện file không còn tồn tại
    assert adapter.exists(key) is False
    assert adapter.get(key) is None


def test_image_file_endpoint_returns_error_when_unavailable(monkeypatch):
    """Kiểm tra endpoint /api/images/{id}/file trả mã lỗi ổn định 410 khi ảnh bị unavailable."""
    from backend.app.api.routes import images as images_route
    
    valid_hex_id = "a1b2c3d4e5f60718293a4b5c6d7e8f90"
    fake_rec = {
        "_id": valid_hex_id,
        "image_id": valid_hex_id,
        "status": "unavailable",
        "corrupted": True,
        "access_scope": "public"
    }
    monkeypatch.setattr(images_route, "service_get_image", lambda img_id: fake_rec if img_id == valid_hex_id else None)
    
    resp = client.get(f"/api/images/{valid_hex_id}/file")
    assert resp.status_code == 410
    data = resp.json()
    assert data["detail"]["error_code"] == "ERROR_ASSET_UNAVAILABLE"
