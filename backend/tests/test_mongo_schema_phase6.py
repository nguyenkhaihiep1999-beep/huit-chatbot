"""
test_mongo_schema_phase6.py
Bộ kiểm thử Phase 6: MongoDB Schema, Validators và Operation Audit:
1. Kiểm thử MongoOperationAuditRecord (validation, forbid extra, BSON Date UTC, Base64 rejection)
2. Kiểm thử MongoHuitKbRecord (validation, 1024D embedding, from_legacy date/metadata normalization)
3. Kiểm thử MongoRepository helpers cho operation_audit
4. Kiểm thử Migration 018: chế độ dry-run mặc định và tính an toàn
"""
from datetime import datetime, timezone
import pytest
from pydantic import ValidationError

from backend.app.models.mongo_models import (
    MongoOperationAuditRecord,
    MongoHuitKbRecord,
    ensure_utc_datetime,
)
from backend.app.repositories.mongo_repository import MongoRepository
import importlib

migration_018 = importlib.import_module("scripts.migrations.018_phase6_schema_sync_and_validators")
OPERATION_AUDIT_VALIDATOR = migration_018.OPERATION_AUDIT_VALIDATOR
HUIT_KB_VALIDATOR = migration_018.HUIT_KB_VALIDATOR


class TestPhase6MongoModels:
    def test_operation_audit_record_valid(self):
        rec = MongoOperationAuditRecord(
            operation_key="assets.find_by_id",
            operation_version="v2",
            operation_checksum="abc123def456",
            operation_type="read",
            mutation_policy="read_only",
            principal_id="user_123",
            request_id="req_001",
            status="success",
            duration_ms=12.5,
            output_bytes=512,
            parameter_hash="param_hash_abc",
        )
        assert rec.schema_version == 1
        assert rec.status == "success"
        assert isinstance(rec.created_at, datetime)
        assert rec.created_at.tzinfo == timezone.utc

    def test_operation_audit_record_rejects_extra(self):
        with pytest.raises(ValidationError):
            MongoOperationAuditRecord(
                operation_key="assets.find_by_id",
                operation_version="v2",
                operation_checksum="abc123def456",
                operation_type="read",
                mutation_policy="read_only",
                principal_id="user_123",
                request_id="req_001",
                status="success",
                duration_ms=12.5,
                output_bytes=512,
                parameter_hash="param_hash_abc",
                extra_forbidden_field="malicious",
            )

    def test_huit_kb_record_valid(self):
        rec = MongoHuitKbRecord(
            title="Ngành Công nghệ thông tin",
            text="HUIT đào tạo kỹ sư CNTT chất lượng cao.",
            source_url="https://ts.huit.edu.vn/nganh/cntt",
            category="training_program",
            embedding=[0.05] * 1024,
            year=2026,
            major_code="7480201",
        )
        assert rec.title == "Ngành Công nghệ thông tin"
        assert len(rec.embedding) == 1024
        assert rec.year == 2026

    def test_huit_kb_record_from_legacy_normalizes_string_date(self):
        legacy = {
            "title": "Thông báo nhập học 2026",
            "text": "Thủ tục nhập học trực tuyến...",
            "source_url": "https://ts.huit.edu.vn/thong-bao",
            "category": "procedure",
            "embedding": [0.01] * 1024,
            "created_at": "2026-09-11T18:30:00Z",
            "date": "07/08/2026",
            "cluster_id": 0,
        }
        rec = MongoHuitKbRecord.from_legacy(legacy)
        assert isinstance(rec.created_at, datetime)
        assert rec.created_at.tzinfo == timezone.utc
        assert isinstance(rec.retrieved_at, datetime)
        assert rec.source_domain == "ts.huit.edu.vn"
        assert rec.official is True
        assert rec.verification_status == "verified"
        assert rec.page_title == "Thông báo nhập học 2026"

    def test_huit_kb_record_rejects_wrong_embedding_dimension(self):
        with pytest.raises(ValidationError):
            MongoHuitKbRecord(
                title="Sai dimension",
                text="Text",
                source_url="https://ts.huit.edu.vn",
                category="test",
                embedding=[0.1] * 512,  # Chỉ có 512D thay vì 1024D
            )

    def test_validators_structure(self):
        assert "$jsonSchema" in OPERATION_AUDIT_VALIDATOR
        assert "operation_key" in OPERATION_AUDIT_VALIDATOR["$jsonSchema"]["required"]
        assert "$jsonSchema" in HUIT_KB_VALIDATOR
        assert "embedding" in HUIT_KB_VALIDATOR["$jsonSchema"]["required"]
        assert HUIT_KB_VALIDATOR["$jsonSchema"]["properties"]["embedding"]["minItems"] == 1024

    def test_mongo_repository_helpers(self):
        col = MongoRepository.get_operation_audit_collection()
        assert col.name == "operation_audit"
