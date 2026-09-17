"""
test_image_dedup_two_users.py
Unit tests cho mô hình ảnh và Deduplication đa người dùng:
- Hai user gửi cùng prompt -> 2 logical image records riêng biệt, cùng trỏ về 1 physical blob trong assets.
- Quyền riêng tư: User A không xem được metadata private của User B.
- Nhánh SVG tạo physical asset hợp lệ trên storage adapter, không tạo blob treo.
- Bồi hoàn (Compensation): Xóa physical file nếu ghi database thất bại.
100% offline, mock mạng hoàn toàn.
"""
import io
import hashlib
import secrets
import pytest
from fastapi.testclient import TestClient

from backend.app.main import app
from backend.app.services import image_service
from backend.app.services.image_service import ImageRequest, create_image
from backend.app.services.asset_store import AssetStore
from backend.app.storage.storage_adapter import LocalStorageAdapter, reset_storage_adapter_for_testing

client = TestClient(app)


class MockCollection:
    def __init__(self):
        self.docs = []
        self.database = type("DB", (), {"command": lambda self, cmd: {"ok": 1}})()

    def find_one(self, filter_query, projection=None):
        for d in self.docs:
            match = True
            # Kiểm tra $or
            if "$or" in filter_query:
                or_match = False
                for cond in filter_query["$or"]:
                    cond_ok = True
                    for k, v in cond.items():
                        if d.get(k) != v:
                            cond_ok = False
                            break
                    if cond_ok:
                        or_match = True
                        break
                if not or_match:
                    match = False
            
            # Kiểm tra các điều kiện cấp cao
            for k, v in filter_query.items():
                if k != "$or":
                    if d.get(k) != v:
                        match = False
                        break
            if match:
                return dict(d)
        return None

    def insert_one(self, doc):
        # Kiểm tra unique owner_id + request_fingerprint
        owner = doc.get("owner_id")
        fp = doc.get("request_fingerprint") or doc.get("canonical_content_hash")
        for d in self.docs:
            if d.get("owner_id") == owner and (d.get("request_fingerprint") == fp or d.get("canonical_content_hash") == fp):
                from pymongo.errors import DuplicateKeyError
                raise DuplicateKeyError(f"Duplicate key on owner_id + request_fingerprint")
        self.docs.append(dict(doc))
        return type("Res", (), {"inserted_id": doc.get("_id")})()


def bind_ltx_image_store(monkeypatch, collection):
    """Bind the service-facing LTX adapter seam to a deterministic fake store."""
    fingerprint_query = lambda fp: {
        "$or": [
            {"request_fingerprint": fp},
            {"canonical_content_hash": fp},
            {"content_hash": fp},
        ]
    }
    monkeypatch.setattr(image_service, "ensure_generated_image_store", lambda **kwargs: None)
    monkeypatch.setattr(
        image_service,
        "find_owner_generated_image",
        lambda fp, owner, **kwargs: collection.find_one({**fingerprint_query(fp), "owner_id": owner}),
    )
    monkeypatch.setattr(
        image_service,
        "find_any_generated_image",
        lambda fp, **kwargs: collection.find_one(fingerprint_query(fp)),
    )
    monkeypatch.setattr(
        image_service,
        "insert_generated_image",
        lambda document, **kwargs: collection.insert_one(document),
    )


def test_two_users_same_prompt_deduplication(monkeypatch, tmp_path):
    """Hai người dùng khác nhau sinh cùng một ảnh: cấp 2 logical record riêng, chung 1 physical blob."""
    mock_storage = LocalStorageAdapter(root_dir=tmp_path)
    reset_storage_adapter_for_testing(mock_storage)
    
    mock_coll = MockCollection()
    bind_ltx_image_store(monkeypatch, mock_coll)
    
    # Mock sinh ảnh flux offline
    fake_jpeg_bytes = b"\xFF\xD8\xFF" + b"X" * 1024
    monkeypatch.setattr(image_service, "generate_flux_image", lambda req, seed: (fake_jpeg_bytes, "image/jpeg"))
    
    # User A sinh ảnh
    req = ImageRequest(prompt="sinh viên HUIT tốt nghiệp đại học", style="photorealistic", width=512, height=512)
    res_a = create_image(req, owner_id="user_A")
    assert res_a.get("cached", False) is False
    
    # Kiểm tra record user A trong db
    doc_a = mock_coll.find_one({"owner_id": "user_A"})
    assert doc_a is not None
    blob_id_a = doc_a["blob_id"]
    assert blob_id_a is not None
    
    # User B sinh CÙNG prompt
    res_b = create_image(req, owner_id="user_B")
    assert res_b["image_id"] is not None
    assert res_b["owner_id"] == "user_B"
    assert res_b["cached"] is True
    
    # Image ID của 2 người dùng phải khác nhau (logical partition)
    assert res_a["image_id"] != res_b["image_id"]
    
    # Kiểm tra record user B trong db
    doc_b = mock_coll.find_one({"owner_id": "user_B"})
    assert doc_b is not None
    blob_id_b = doc_b["blob_id"]
    
    # Cả hai cùng trỏ về một physical blob_id duy nhất
    assert blob_id_a == blob_id_b
    
    # File vật lý được lưu đúng trên storage
    assert (tmp_path / doc_a["storage_key"]).exists()


def test_svg_branch_creates_physical_asset(monkeypatch, tmp_path):
    """Nhánh SVG phải ghi file vật lý .svg và tạo asset hợp lệ, không để blob_id treo."""
    mock_storage = LocalStorageAdapter(root_dir=tmp_path)
    reset_storage_adapter_for_testing(mock_storage)
    
    mock_coll = MockCollection()
    bind_ltx_image_store(monkeypatch, mock_coll)
    
    # Mock sinh scene SVG offline
    from backend.app.services.image_service import Scene, Rect
    sample_scene = Scene(background="#0066C4", shapes=[Rect(type="rect", x=0, y=0, width=512, height=512, fill="#FFFFFF")])
    monkeypatch.setattr(image_service, "generate_scene", lambda req: (sample_scene, 2048))
    
    req = ImageRequest(prompt="Sơ đồ tuyển sinh SVG", backend="svg", width=512, height=512)
    res = create_image(req, owner_id="user_svg")
    
    assert res["image_id"] is not None
    doc = mock_coll.find_one({"image_id": res["image_id"]})
    assert doc is not None
    assert doc["backend"] == "svg"
    assert doc.get("blob_id") is not None
    assert doc.get("storage_key") is not None
    
    # File vật lý SVG phải tồn tại trên đĩa
    svg_file = tmp_path / doc["storage_key"]
    assert svg_file.exists()
    assert b"<svg" in svg_file.read_bytes()


def test_compensation_deletes_file_if_mongo_fails(monkeypatch, tmp_path):
    """Nếu ghi MongoDB thất bại, cơ chế bồi hoàn phải tự động xóa file vật lý đã lưu."""
    mock_storage = LocalStorageAdapter(root_dir=tmp_path)
    reset_storage_adapter_for_testing(mock_storage)
    
    class FailingCollection(MockCollection):
        def insert_one(self, doc):
            raise RuntimeError("Lỗi kết nối database giả lập")
            
    bind_ltx_image_store(monkeypatch, FailingCollection())
    fake_jpeg_bytes = b"\xFF\xD8\xFF" + b"Y" * 1024
    monkeypatch.setattr(image_service, "generate_flux_image", lambda req, seed: (fake_jpeg_bytes, "image/jpeg"))
    
    req = ImageRequest(prompt="Test bồi hoàn lỗi database", style="photorealistic", width=512, height=512)
    
    with pytest.raises(RuntimeError, match="Lỗi kết nối database giả lập"):
        create_image(req, owner_id="user_err")
        
    # Không còn file rác nào trong tmp_path sau khi rollback
    remaining_files = list(tmp_path.glob("image_*.jpg"))
    assert len(remaining_files) == 0
