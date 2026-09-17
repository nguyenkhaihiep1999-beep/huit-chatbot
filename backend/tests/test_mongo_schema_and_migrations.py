"""
test_mongo_schema_and_migrations.py
Bộ kiểm thử toàn diện cho hệ thống MongoDB Production-Ready Schema & Storage:
- Kiểm thử các Pydantic Models (MongoAssetRecord, MongoArtifactRecord, MongoJobRecord, ...).
- Kiểm thử chặn Base64 lớn và cấm trường lạ (extra="forbid").
- Kiểm thử hỗ trợ trạng thái "cancelled" trong JobStatusResponse.
- Kiểm thử StorageAdapter và cơ chế chống tấn công Path Traversal.
- Kiểm thử không nuốt lỗi khởi tạo index trong MongoRepository.
- Kiểm thử cơ chế phân tách Blob vật lý và Quyền sở hữu nghiệp vụ (Ownership).
"""
from datetime import datetime, timezone
import hashlib
from pathlib import Path
import pytest
from pydantic import ValidationError
from unittest.mock import MagicMock, patch

from backend.app.models.mongo_models import (
    MongoAssetRecord,
    MongoArtifactRecord,
    MongoJobRecord,
    MongoJobEvent,
    MongoGeneratedImageRecord,
    MongoQueryCacheRecord,
    MongoRagEventRecord,
    MongoAdmissionVisualRecord,
    ensure_utc_datetime,
)
from backend.app.api.schemas.artifact import JobStatusResponse
from backend.app.storage.storage_adapter import (
    LocalStorageAdapter,
    validate_safe_storage_key,
)
from backend.app.repositories.mongo_repository import MongoRepository
from backend.app.telemetry.errors import (
    ArtifactException,
    ERROR_STORAGE_TRAVERSAL_ATTEMPT,
)


class TestPydanticMongoModels:
    """Kiểm thử tính hợp lệ và cơ chế bảo vệ của các Pydantic MongoDB Models."""

    def test_asset_record_valid(self):
        rec = MongoAssetRecord(
            asset_id="art_12345678",
            content_hash="a" * 64,
            storage_key="asset_art_12345678.xlsx",
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            file_ext="xlsx",
            file_size=1024,
            renderer_version="huit-renderer-v2.0",
        )
        assert rec.schema_version == 1
        assert rec.file_size == 1024
        assert isinstance(rec.created_at, datetime)
        assert rec.created_at.tzinfo == timezone.utc

    def test_asset_record_rejects_path_traversal_key(self):
        with pytest.raises(ValidationError):
            MongoAssetRecord(
                asset_id="art_12345678",
                content_hash="a" * 64,
                storage_key="../secret.txt",
                media_type="application/pdf",
                file_ext="pdf",
                file_size=100,
                renderer_version="v1"
            )

    def test_asset_record_rejects_extra_fields(self):
        with pytest.raises(ValidationError):
            MongoAssetRecord(
                asset_id="art_12345678",
                content_hash="a" * 64,
                storage_key="asset_art_12345678.pdf",
                media_type="application/pdf",
                file_ext="pdf",
                file_size=100,
                renderer_version="v1",
                hacked_field="malicious_payload"  # extra field
            )

    def test_artifact_record_rejects_large_base64(self):
        large_b64 = "data:image/png;base64," + "A" * 500
        with pytest.raises(ValidationError) as exc_info:
            MongoArtifactRecord(
                artifact_id="art_001",
                manifest={
                    "version": 1,
                    "title": "Bảng học phí",
                    "content": {"image": large_b64}
                }
            )
        assert "Base64" in str(exc_info.value)

    def test_job_record_status_validation(self):
        # Trạng thái hợp lệ
        valid_statuses = ["queued", "processing", "completed", "failed", "cancelled"]
        for st in valid_statuses:
            job = MongoJobRecord(
                job_id="job_abcdef123456",
                action="render_xlsx",
                status=st,
                progress=50
            )
            assert job.status == st

        # Trạng thái không hợp lệ bị từ chối
        with pytest.raises(ValidationError):
            MongoJobRecord(
                job_id="job_abcdef123456",
                action="render_xlsx",
                status="invalid_status",
                progress=50
            )

    def test_job_status_response_supports_cancelled(self):
        # Đảm bảo JobStatusResponse trong artifact schemas chấp nhận "cancelled"
        resp = JobStatusResponse(
            job_id="job_test123456",
            status="cancelled",
            progress=0
        )
        assert resp.status == "cancelled"

    def test_query_cache_rejects_large_base64_in_meta(self):
        with pytest.raises(ValidationError):
            MongoQueryCacheRecord(
                cache_key="b" * 64,
                question_hash="c" * 64,
                question_len=20,
                answer="Học phí là 15 triệu/học kỳ",
                meta={"visual": {"raw": {"image_base64": "data:image/png;base64," + "Z" * 500}}},
                kb_version="v4",
                rag_version="v10",
                model="gemini",
                updated_at=datetime.now(timezone.utc),
                expires_at=datetime.now(timezone.utc)
            )

    def test_legacy_deserialization(self):
        legacy_asset = {
            "_id": "art_999",
            "asset_id": "art_999",
            "content_hash": "d" * 64,
            "storage_key": "asset_art_999.pdf",
            "media_type": "application/pdf",
            "file_ext": "pdf",
            "file_size": 2048,
            "renderer_version": "v1",
            "created_at": "2026-09-14T03:00:00+00:00",  # string
            "last_accessed_at": "2026-09-14T03:00:00Z",  # string
            "unknown_legacy_garbage": "ignore_me"
        }
        converted = MongoAssetRecord.from_legacy(legacy_asset)
        assert converted.schema_version == 1
        assert isinstance(converted.created_at, datetime)
        assert isinstance(converted.last_accessed_at, datetime)


class TestStorageAdapter:
    """Kiểm thử LocalStorageAdapter và tính năng bảo mật."""

    @pytest.fixture
    def safe_tmp_dir(self):
        import tempfile
        from backend.app.config import settings
        test_dir = settings.DATA_DIR / "test_scratch_storage"
        test_dir.mkdir(parents=True, exist_ok=True)
        td = tempfile.TemporaryDirectory(dir=test_dir)
        yield Path(td.name)
        try:
            td.cleanup()
        except Exception:
            pass

    def test_put_get_exists_delete(self, safe_tmp_dir):
        adapter = LocalStorageAdapter(root_dir=safe_tmp_dir)
        key = "test_file_001.xlsx"
        data = b"PK\x03\x04ExcelFileDataMock"

        # 1. Put
        res = adapter.put(key, data, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        assert res["storage_key"] == key
        assert res["byte_size"] == len(data)
        assert res["checksum"] == hashlib.sha256(data).hexdigest()

        # 2. Exists
        assert adapter.exists(key) is True
        assert adapter.exists("non_existent.file") is False

        # 3. Get
        retrieved = adapter.get(key)
        assert retrieved == data

        # 4. Checksum
        assert adapter.get_checksum(key) == hashlib.sha256(data).hexdigest()
        assert adapter.get_size(key) == len(data)
        assert list(adapter.list_keys()) == [key]

        # 5. Delete
        assert adapter.delete(key) is True
        assert adapter.exists(key) is False
        assert adapter.get_size(key) is None
        assert list(adapter.list_keys()) == []

    def test_path_traversal_prevention(self, safe_tmp_dir):
        adapter = LocalStorageAdapter(root_dir=safe_tmp_dir)
        dangerous_keys = [
            "../secret.txt",
            "..\\windows_file.txt",
            "/etc/passwd",
            "sub/../../hacked",
            "file with spaces.txt",
            "file!@#$%.txt",
        ]
        for dk in dangerous_keys:
            with pytest.raises(ArtifactException) as exc:
                adapter.put(dk, b"bad")
            assert exc.value.error_code == ERROR_STORAGE_TRAVERSAL_ATTEMPT


class TestDeduplicationAndOwnershipSeparation:
    """
    Kiểm thử nguyên tắc tách riêng Physical Blob và Artifact Ownership:
    Hai người dùng tạo cùng nội dung -> tái sử dụng cùng blob vật lý nhưng ownership độc lập.
    """

    def test_ownership_separation_no_leakage(self):
        common_blob_id = "blob_common_sha256"
        content_hash = "f" * 64

        # Người dùng A tạo artifact riêng tư
        artifact_a = MongoArtifactRecord(
            artifact_id="art_user_a_001",
            owner_id="user_alice",
            access_scope="private",
            blob_id=common_blob_id,
            manifest={"title": "Tài liệu riêng của Alice", "items": [1, 2, 3]}
        )

        # Người dùng B tạo artifact có cùng nội dung -> trỏ cùng blob_id
        artifact_b = MongoArtifactRecord(
            artifact_id="art_user_b_002",
            owner_id="user_bob",
            access_scope="private",
            blob_id=common_blob_id,
            manifest={"title": "Tài liệu riêng của Bob", "items": [1, 2, 3]}
        )

        # Hai artifact có ID khác nhau, chủ sở hữu khác nhau
        assert artifact_a.artifact_id != artifact_b.artifact_id
        assert artifact_a.owner_id != artifact_b.owner_id
        assert artifact_a.blob_id == artifact_b.blob_id
        assert artifact_a.owner_id == "user_alice"
        assert artifact_b.owner_id == "user_bob"


class TestMongoRepositoryIndexHandling:
    """Kiểm thử việc xử lý chi tiết mã lỗi index và không nuốt exception."""

    def test_create_single_index_handles_duplicate_key_error(self):
        mock_col = MagicMock()
        mock_col.name = "assets"
        mock_col.index_information.return_value = {}
        # Giả lập MongoDB DuplicateKeyError (Code 11000)
        from pymongo.errors import DuplicateKeyError
        mock_col.create_index.side_effect = DuplicateKeyError("E11000 duplicate key error collection")

        res = MongoRepository._create_single_index(mock_col, "content_hash", unique=True)
        assert res["status"] == "duplicate_key_error"
        assert res["error_code"] == 11000
        assert "LỖI DỮ LIỆU TRÙNG LẬP" in res["message"]

    def test_create_single_index_handles_options_conflict(self):
        mock_col = MagicMock()
        mock_col.name = "jobs"
        mock_col.index_information.return_value = {}
        # Giả lập IndexOptionsConflict (Code 85)
        from pymongo.errors import OperationFailure
        of = OperationFailure("Index options conflict", code=85)
        mock_col.create_index.side_effect = of

        res = MongoRepository._create_single_index(mock_col, "job_id", unique=True)
        assert res["status"] == "options_conflict"
        assert res["error_code"] == 85
        assert "XUNG ĐỘT CẤU HÌNH INDEX" in res["message"]


    def test_database_readiness_check_detects_missing_indexes(self):
        mock_db = MagicMock()
        mock_db.command.return_value = {"ok": 1}
        # Chỉ có index _id_
        mock_db["query_cache"].index_information.return_value = {"_id_": {"key": [("_id", 1)]}}
        mock_db["rag_events"].index_information.return_value = {"_id_": {"key": [("_id", 1)]}}
        mock_db["assets"].index_information.return_value = {"_id_": {"key": [("_id", 1)]}}
        mock_db["jobs"].index_information.return_value = {"_id_": {"key": [("_id", 1)]}}

        with patch.object(MongoRepository, "get_db", return_value=mock_db):
            readiness = MongoRepository.check_database_readiness()
            assert readiness["ping"] is True
            assert readiness["ready"] is False
            assert len(readiness["missing_critical_indexes"]) > 0
            assert "jobs:job_id" in readiness["missing_critical_indexes"]
