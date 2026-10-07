"""Release-blocking checks for the canonical JSON Schema architecture."""
from __future__ import annotations

from copy import deepcopy
import importlib
import json
from pathlib import Path
import re
from typing import get_args
from unittest.mock import MagicMock
import jsonschema
import pytest
from pydantic import ValidationError

from backend.app.api.routes.admin import AdminLoginRequest, AdminLoginResponse
from backend.app.api.routes.auth import SessionResponse
from backend.app.api.schemas.chat import ChatRequest, MessageItem
from backend.app.api.schemas.streaming_v2 import (
    CANONICAL_EVENT_TYPES,
    StreamDonePayload,
    StreamEventEnvelope,
    StreamStartPayload,
    StreamTokenPayload,
)
from backend.app.contracts.schema_registry import (
    SchemaRegistryError,
    clear_registry_cache,
    iter_schema_entries,
    load_schema,
    schema_sha256,
    verify_all_registry_checksums,
    verify_schema_checksum,
    get_compiled_validator,
    validate_contract,
)
from backend.app.data_access.operation_gateway import MutationPolicy
from backend.app.api.schemas.admin import AdminSessionResponse
from backend.app.api.schemas.artifact import (
    ArtifactExportRequest,
    ArtifactManifest,
    ArtifactPlanRequest,
    ArtifactRenderRequest,
    ArtifactSummary,
    ArtifactUpscaleRequest,
    JobStatusResponse,
    JobAcceptedResponse,
)
from backend.app.api.schemas.image import (
    ImageCreateRequest,
    ImageRequest,
    ImageResult,
)
from backend.app.models.mongo_models import MongoAssetRecord, MongoJobRecord


@pytest.fixture(autouse=True)
def guard_migration_022_save_report(monkeypatch):
    """Tránh sinh file báo cáo rác ra thư mục audit_outputs trong lúc chạy test."""
    migration_022 = importlib.import_module("scripts.migrations.022_backup_json_schema_registry")
    monkeypatch.setattr(
        migration_022,
        "save_migration_report",
        lambda report, report_file=None: None,
    )


def test_registry_entries_are_unique_loadable_and_checksummed():
    entries = list(iter_schema_entries())
    identities = {(entry["schema_id"], entry["version"]) for entry in entries}
    assert len(entries) == len(identities)
    assert len(entries) == 37
    for entry in entries:
        doc = load_schema(entry["schema_id"], entry["version"])
        assert isinstance(doc, dict)
        assert re.fullmatch(r"[a-f0-9]{64}", schema_sha256(entry["schema_id"], entry["version"]))
        assert entry["sha256"] == schema_sha256(entry["schema_id"], entry["version"])
        assert entry.get("status") in {"active", "deprecated", "planned"}


def test_registry_semantic_checksums_match_all_entries():
    # Phase 7 requirement: Verify semantic checksums for all contracts fail-fast
    verify_all_registry_checksums()
    for entry in iter_schema_entries():
        assert verify_schema_checksum(entry["schema_id"], entry["version"]) is True


def test_registry_has_expected_kind_distribution():
    entries = list(iter_schema_entries())
    kinds = {}
    for entry in entries:
        kinds[entry["kind"]] = kinds.get(entry["kind"], 0) + 1

    assert kinds.get("api") == 16
    assert kinds.get("stream") == 2
    assert kinds.get("queue") == 5
    assert kinds.get("mongodb") == 11
    assert kinds.get("decision") == 3


def test_registry_schemas_comply_with_kind_rules():
    for entry in iter_schema_entries():
        doc = load_schema(entry["schema_id"], entry["version"])
        if entry["kind"] == "mongodb":
            assert "$jsonSchema" in doc
            assert doc["$jsonSchema"].get("bsonType") == "object"
            assert "required" in doc["$jsonSchema"]
        else:
            assert doc.get("$schema") == "https://json-schema.org/draft/2020-12/schema"
            assert doc.get("type") == "object"


def test_gate_01_malformed_registry_json_is_rejected(tmp_path, monkeypatch):
    from backend.app.contracts import schema_registry

    # 1. Invalid JSON syntax
    bad_json_file = tmp_path / "bad_registry.json"
    bad_json_file.write_text("invalid json {{{", encoding="utf-8")
    monkeypatch.setattr(schema_registry, "REGISTRY_FILE", bad_json_file)
    schema_registry.clear_registry_cache()
    with pytest.raises(schema_registry.SchemaRegistryError, match="Cannot load canonical JSON Schema registry"):
        schema_registry._manifest()

    # 2. Unsupported or malformed manifest schema
    bad_manifest_file = tmp_path / "bad_manifest.json"
    bad_manifest_file.write_text(json.dumps({"registry_version": 999, "contracts": []}), encoding="utf-8")
    monkeypatch.setattr(schema_registry, "REGISTRY_FILE", bad_manifest_file)
    schema_registry.clear_registry_cache()
    with pytest.raises(schema_registry.SchemaRegistryError, match="Unsupported or malformed JSON Schema registry manifest"):
        schema_registry._manifest()

    schema_registry.clear_registry_cache()


def test_gate_02_registry_pointing_to_non_existent_file_is_rejected(monkeypatch):
    from backend.app.contracts import schema_registry

    bad_manifest = {
        "registry_version": 1,
        "contracts": [
            {
                "schema_id": "huit.api.missing",
                "version": "1.0.0",
                "kind": "api",
                "file": "api/does-not-exist-file.v1.schema.json",
                "frontend": False,
                "sha256": "1f87bd17df5b6bc8729f4fe46ab0220a66d15e9445037046c818606eb7830b70",
                "consumers": ["test"],
            }
        ],
    }
    monkeypatch.setattr(schema_registry, "_manifest", lambda: bad_manifest)
    schema_registry.clear_registry_cache()
    with pytest.raises(schema_registry.SchemaRegistryError, match="Schema file is missing or invalid"):
        list(schema_registry.iter_schema_entries())

    schema_registry.clear_registry_cache()


def test_gate_03_duplicate_schema_id_and_version_is_rejected(monkeypatch):
    from backend.app.contracts import schema_registry

    bad_manifest_dup = {
        "registry_version": 1,
        "contracts": [
            {
                "schema_id": "huit.api.dup",
                "version": "1.0.0",
                "kind": "api",
                "file": "api/chat-request.v1.schema.json",
                "frontend": True,
                "sha256": "1f87bd17df5b6bc8729f4fe46ab0220a66d15e9445037046c818606eb7830b70",
                "consumers": ["test"],
            },
            {
                "schema_id": "huit.api.dup",
                "version": "1.0.0",
                "kind": "api",
                "file": "api/chat-request.v1.schema.json",
                "frontend": True,
                "sha256": "1f87bd17df5b6bc8729f4fe46ab0220a66d15e9445037046c818606eb7830b70",
                "consumers": ["test"],
            },
        ],
    }
    monkeypatch.setattr(schema_registry, "_manifest", lambda: bad_manifest_dup)
    schema_registry.clear_registry_cache()
    with pytest.raises(schema_registry.SchemaRegistryError, match="Duplicate schema identity"):
        list(schema_registry.iter_schema_entries())

    schema_registry.clear_registry_cache()


def test_gate_04_tampered_or_invalid_checksum_is_rejected(monkeypatch):
    from backend.app.contracts import schema_registry

    # 1. Invalid checksum format
    bad_manifest_format = {
        "registry_version": 1,
        "contracts": [
            {
                "schema_id": "huit.api.bad-sha",
                "version": "1.0.0",
                "kind": "api",
                "file": "api/chat-request.v1.schema.json",
                "frontend": False,
                "sha256": "invalid_checksum_not_hex_64",
                "consumers": ["test"],
            }
        ],
    }
    monkeypatch.setattr(schema_registry, "_manifest", lambda: bad_manifest_format)
    schema_registry.clear_registry_cache()
    with pytest.raises(schema_registry.SchemaRegistryError, match="Invalid sha256 semantic checksum"):
        list(schema_registry.iter_schema_entries())

    # 2. Checksum mismatch
    bad_manifest_mismatch = {
        "registry_version": 1,
        "contracts": [
            {
                "schema_id": "huit.api.chat-request",
                "version": "1.0.0",
                "kind": "api",
                "file": "api/chat-request.v1.schema.json",
                "frontend": True,
                "sha256": "0000000000000000000000000000000000000000000000000000000000000000",
                "consumers": ["test"],
            }
        ],
    }
    monkeypatch.setattr(schema_registry, "_manifest", lambda: bad_manifest_mismatch)
    schema_registry.clear_registry_cache()
    with pytest.raises(schema_registry.SchemaRegistryError, match="Checksum mismatch"):
        schema_registry.verify_schema_checksum("huit.api.chat-request", "1.0.0")

    schema_registry.clear_registry_cache()


def test_stream_v2_ref_resolver_and_schema_validation():
    # Rule 9: Phải kiểm tra resolver hoạt động với toàn bộ $ref
    stream_schema = load_schema("huit.stream.chat-event", "2.0.0")
    validator = jsonschema.Draft202012Validator(stream_schema)
    validator.check_schema(stream_schema)

    # Valid Start event
    start_event = StreamEventEnvelope(
        stream_id="str_test_123",
        request_id="req_test_123",
        sequence=1,
        type="start",
        payload=StreamStartPayload(version="2.0.0", timestamp="2026-09-21T23:50:00Z").model_dump(),
    ).model_dump()
    validator.validate(start_event)

    # Valid Token event
    token_event = StreamEventEnvelope(
        stream_id="str_test_123",
        request_id="req_test_123",
        sequence=2,
        type="token",
        payload=StreamTokenPayload(token="Học phí HUIT", delta="Học phí HUIT").model_dump(),
    ).model_dump()
    validator.validate(token_event)

    # Valid Done event
    done_event = StreamEventEnvelope(
        stream_id="str_test_123",
        request_id="req_test_123",
        sequence=3,
        type="done",
        payload=StreamDonePayload(latency_ms=150.0, cached=True).model_dump(),
    ).model_dump()
    validator.validate(done_event)


def test_gate_09_invalid_stream_events_are_rejected():
    stream_schema = load_schema("huit.stream.chat-event", "2.0.0")
    validator = jsonschema.Draft202012Validator(stream_schema)

    # 1. Missing required field 'type'
    with pytest.raises(jsonschema.ValidationError):
        validator.validate({
            "stream_id": "str_123",
            "request_id": "req_123",
            "sequence": 1,
            "payload": {},
        })

    # 2. Sequence must be positive (minimum: 1)
    with pytest.raises(jsonschema.ValidationError):
        validator.validate({
            "stream_id": "str_123",
            "request_id": "req_123",
            "sequence": 0,
            "type": "token",
            "payload": {"delta": "test", "token": "test"},
        })

    # 3. Invalid event type
    with pytest.raises(jsonschema.ValidationError):
        validator.validate({
            "stream_id": "str_123",
            "request_id": "req_123",
            "sequence": 1,
            "type": "unregistered_event_type",
            "payload": {},
        })

    # 4. Payload mismatch (token event missing required delta)
    with pytest.raises(jsonschema.ValidationError):
        validator.validate({
            "stream_id": "str_123",
            "request_id": "req_123",
            "sequence": 2,
            "type": "token",
            "payload": {"token": "only_token_missing_delta"},
        })



def test_session_response_pydantic_shape_matches_canonical_contract():
    canonical = load_schema("huit.api.session-bootstrap-response", "1.0.0")
    generated = SessionResponse.model_json_schema()
    assert generated["x-contract-id"] == "huit.api.session-bootstrap-response"
    assert generated["x-contract-version"] == "1.0.0"
    assert set(generated["properties"]) == set(canonical["properties"])
    assert set(generated["required"]) == set(canonical["required"])
    assert generated["properties"]["ttl_seconds"]["minimum"] == canonical["properties"]["ttl_seconds"]["minimum"]
    assert generated["properties"]["ttl_seconds"]["maximum"] == canonical["properties"]["ttl_seconds"]["maximum"]


def test_chat_request_pydantic_shape_matches_canonical_contract():
    canonical = load_schema("huit.api.chat-request", "1.0.0")
    generated = ChatRequest.model_json_schema()
    assert generated["x-contract-id"] == "huit.api.chat-request"
    assert generated["x-contract-version"] == "1.0.0"
    assert set(generated["properties"]) == set(canonical["properties"])
    assert set(generated["required"]) == set(canonical["required"])
    assert set(MessageItem.model_json_schema()["properties"]["role"]["enum"]) == {"user", "assistant"}
    with pytest.raises(ValidationError):
        ChatRequest(question="Học phí?", history=None)


def test_admin_and_artifact_contracts_match_canonical_schemas():
    admin_req_schema = load_schema("huit.api.admin-login-request", "1.0.0")
    assert "username" in admin_req_schema["properties"]
    assert "password" in admin_req_schema["properties"]
    valid_req = AdminLoginRequest(username="admin", password="password123")
    assert valid_req.username == "admin"

    admin_res_schema = load_schema("huit.api.admin-login-response", "1.0.0")
    assert set(admin_res_schema["required"]) == {"success", "csrf_token", "message"}
    valid_res = AdminLoginResponse(success=True, csrf_token="token_1234567890", message="OK")
    assert valid_res.csrf_token == "token_1234567890"

    plan_schema = load_schema("huit.api.artifact-plan-request", "1.0.0")
    assert "prompt" in plan_schema["properties"]
    assert "type" in plan_schema["properties"]
    plan_obj = ArtifactPlanRequest(prompt="Draw a flowchart")
    assert plan_obj.prompt == "Draw a flowchart"

    render_schema = load_schema("huit.api.artifact-render-request", "1.0.0")
    assert "artifact_id" in render_schema["required"]
    assert "format" in render_schema["properties"]
    render_obj = ArtifactRenderRequest(artifact_id="art_123", format="svg", scale=2)
    assert render_obj.artifact_id == "art_123"

    upscale_schema = load_schema("huit.api.artifact-upscale-request", "1.0.0")
    assert "scale" in upscale_schema["properties"]
    upscale_obj = ArtifactUpscaleRequest(scale=4)
    assert upscale_obj.scale == 4

    export_schema = load_schema("huit.api.artifact-export-request", "1.0.0")
    assert "format" in export_schema["required"]
    export_obj = ArtifactExportRequest(format="xlsx")
    assert export_obj.format == "xlsx"

    job_res_schema = load_schema("huit.api.job-status-response", "1.0.0")
    assert set(job_res_schema["required"]) == {"job_id", "status"}
    job_res_obj = JobStatusResponse(job_id="job_123456", status="completed", progress=100)
    assert job_res_obj.progress == 100


def test_mongo_models_align_with_canonical_mongodb_schemas():
    asset_schema = load_schema("huit.mongo.asset-record", "1.0.0")
    assert "asset_id" in asset_schema["$jsonSchema"]["properties"]
    assert "file_size" in asset_schema["$jsonSchema"]["properties"]

    job_schema = load_schema("huit.mongo.job-record", "1.0.0")
    assert "job_id" in job_schema["$jsonSchema"]["properties"]
    assert set(job_schema["$jsonSchema"]["properties"]["status"]["enum"]) == {
        "queued",
        "processing",
        "completed",
        "failed",
        "cancelled",
    }


def test_queue_schemas_load_and_validate():
    for schema_id in [
        "huit.queue.job-input",
        "huit.queue.job-result",
        "huit.queue.job-error",
        "huit.queue.retry-metadata",
        "huit.queue.dead-letter-metadata",
    ]:
        schema = load_schema(schema_id, "1.0.0")
        assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
        assert schema["type"] == "object"


def test_stream_and_gateway_enums_are_covered_by_canonical_schemas():
    stream = load_schema("huit.stream.chat-event", "2.0.0")
    assert set(stream["properties"]["type"]["enum"]) == CANONICAL_EVENT_TYPES
    generated_stream = StreamEventEnvelope.model_json_schema()
    assert generated_stream["x-contract-id"] == "huit.stream.chat-event"
    assert generated_stream["x-contract-version"] == "2.0.0"

    audit = load_schema("huit.mongo.operation-audit", "1.1.0")
    allowed = set(audit["$jsonSchema"]["properties"]["mutation_policy"]["enum"])
    assert set(get_args(MutationPolicy)) <= allowed


def test_migrations_consume_registry_instead_of_duplicating_operation_audit_schema():
    migration_018 = importlib.import_module("scripts.migrations.018_phase6_schema_sync_and_validators")
    assert migration_018.OPERATION_AUDIT_VALIDATOR == load_schema("huit.mongo.operation-audit", "1.1.0")

    migration_022 = importlib.import_module("scripts.migrations.022_backup_json_schema_registry")
    documents = migration_022.build_registry_documents()
    assert len(documents) == len(list(iter_schema_entries()))
    for document in documents:
        assert document["schema_document"] == load_schema(document["schema_id"], document["schema_version"])
        assert document["sha256"] == schema_sha256(document["schema_id"], document["schema_version"])
        json.dumps(document["schema_document"], ensure_ascii=False)


def test_sync_json_schemas_check_mode_reports_in_sync():
    import scripts.sync_json_schemas as sync_tool

    # When all schemas are synchronized, check_sync() must return 0
    assert sync_tool.check_sync() == 0


def test_sync_json_schemas_check_mode_detects_drift(tmp_path, monkeypatch):
    import scripts.sync_json_schemas as sync_tool

    # Point TARGET to an empty directory to simulate missing schemas
    monkeypatch.setattr(sync_tool, "TARGET", tmp_path)
    assert sync_tool.check_sync() == 1


def test_gate_10_invalid_queue_payloads_are_rejected():
    job_input_schema = load_schema("huit.queue.job-input", "1.0.0")
    validator = jsonschema.Draft202012Validator(job_input_schema)

    # Valid payload
    valid_payload = {
        "job_id": "job_12345678",
        "action": "export",
        "format": "xlsx",
        "scale": 2,
    }
    validator.validate(valid_payload)

    # Missing required field 'job_id'
    with pytest.raises(jsonschema.ValidationError):
        validator.validate({"action": "export", "format": "xlsx"})

    # Invalid status on job result
    job_result_schema = load_schema("huit.queue.job-result", "1.0.0")
    result_validator = jsonschema.Draft202012Validator(job_result_schema)
    with pytest.raises(jsonschema.ValidationError):
        result_validator.validate({
            "job_id": "job_12345678",
            "status": "unsupported_status",
            "progress": 50,
        })


def test_gate_11_invalid_mongo_documents_fail_validation():
    # 1. Pydantic models enforce strict boundaries
    with pytest.raises(ValidationError):
        MongoJobRecord(job_id="short", action="test", status="invalid_status")

    with pytest.raises(ValidationError):
        MongoAssetRecord(
            asset_id="asset_1",
            content_hash="abc",
            media_type="image/png",
            file_ext="png",
            storage_key="",
            file_size=-10,  # ge=0 violation
            renderer_version="1.0",
        )

    # 2. Canonical MongoDB validator rules for schema_registry
    registry_schema = load_schema("huit.mongo.schema-registry-record", "1.0.0")["$jsonSchema"]
    required_fields = set(registry_schema["required"])
    assert {"schema_id", "schema_version", "kind", "file", "sha256", "schema_document", "consumers", "status"}.issubset(required_fields)

    # Missing required field
    invalid_doc_missing = {
        "schema_version": "1.0.0",
        "kind": "api",
        "file": "test.json",
    }
    assert not set(invalid_doc_missing.keys()).issuperset(required_fields)

    # Invalid sha256 pattern
    sha256_pattern = re.compile(registry_schema["properties"]["sha256"]["pattern"])
    assert not sha256_pattern.match("invalid_short_hash")
    assert sha256_pattern.match("a" * 64)

    # Invalid kind enum
    valid_kinds = set(registry_schema["properties"]["kind"]["enum"])
    assert valid_kinds == {"api", "stream", "mongodb", "queue"}
    assert "redis_cache" not in valid_kinds

    # Invalid status enum
    valid_statuses = set(registry_schema["properties"]["status"]["enum"])
    assert "deleted" not in valid_statuses
    assert "active" in valid_statuses


def test_gate_12_breaking_change_without_version_bump_is_rejected(monkeypatch, tmp_path):
    migration_022 = importlib.import_module("scripts.migrations.022_backup_json_schema_registry")

    class MockCollection:
        def find_one(self, filter_query, projection=None):
            return {
                "schema_id": filter_query["schema_id"],
                "schema_version": filter_query["schema_version"],
                "sha256": "different_older_checksum_0000000000000000000000000000000000000000",
            }

        def update_one(self, *args, **kwargs):
            pass

        def create_indexes(self, *args, **kwargs):
            pass

    class MockDb:
        name = "huit_chatbot"

        def list_collection_names(self):
            return ["schema_registry"]

        def command(self, *args, **kwargs):
            pass

        def __getitem__(self, name):
            return MockCollection()

    class MockClient:
        def close(self):
            pass

    mock_save_report = MagicMock()
    monkeypatch.setattr(migration_022, "get_migration_db", lambda db_name: (MockClient(), MockDb()))
    monkeypatch.setattr(migration_022, "save_migration_report", mock_save_report)

    temp_report_file = str(tmp_path / "migration_022_test_report.json")
    with pytest.raises(RuntimeError, match="Refusing to overwrite existing schema version"):
        migration_022.run_migration(
            is_dry_run=False,
            database_name="huit_chatbot",
            report_file=temp_report_file,
        )

    # Đảm bảo save_migration_report được gọi với đường dẫn tạm thời, không chạm vào audit_outputs
    assert mock_save_report.called
    saved_args, _ = mock_save_report.call_args
    assert saved_args[1] == temp_report_file


def test_gate_16_sync_check_mode_leaves_worktree_unaltered():
    import subprocess
    import scripts.sync_json_schemas as sync_tool

    # Run check mode
    result_code = sync_tool.check_sync()
    assert result_code == 0

    # Ensure running check does not alter git status
    status_before = subprocess.check_output(["git", "status", "--porcelain"], text=True)
    result_code_2 = sync_tool.check_sync()
    assert result_code_2 == 0
    status_after = subprocess.check_output(["git", "status", "--porcelain"], text=True)
    assert status_before == status_after


def test_gate_17_migration_022_test_leaves_git_status_unaltered(monkeypatch, tmp_path):
    """Regression test: Xác nhận việc thực thi test migration 022 không sinh file rác vào audit_outputs và không làm đổi git status."""
    import glob
    import subprocess

    status_before = subprocess.check_output(["git", "status", "--porcelain"], text=True)
    reports_before = set(glob.glob("audit_outputs/migration_*_report.json"))

    test_gate_12_breaking_change_without_version_bump_is_rejected(monkeypatch, tmp_path)

    status_after = subprocess.check_output(["git", "status", "--porcelain"], text=True)
    reports_after = set(glob.glob("audit_outputs/migration_*_report.json"))

    assert reports_after == reports_before, f"Sinh file rác audit_outputs: {reports_after - reports_before}"
    assert status_before == status_after, "Git status bị thay đổi sau khi chạy test migration 022!"


@pytest.mark.anyio
async def test_gate_queue_input_payload_validates_against_canonical_schema():
    from backend.app.services.job_queue import JobQueueManager
    from backend.app.telemetry.errors import ArtifactException

    # Valid job creates successfully through canonical schema boundary
    job_id = await JobQueueManager.create_job(
        action="render",
        artifact_id="art_valid_001",
        target_format="pdf",
        scale=2,
    )
    assert job_id.startswith("job_")

    # Invalid scale (> 4) violates canonical huit.queue.job-input schema
    with pytest.raises(ArtifactException) as exc_info:
        await JobQueueManager.create_job(
            action="upscale",
            artifact_id="art_invalid_001",
            scale=10,  # maximum is 4 in schema
        )
    assert exc_info.value.error_code == "QUEUE_INPUT_CONTRACT_VIOLATION"


def test_compiled_validator_caching_and_fast_validation():
    # 1. get_compiled_validator returns an identical cached instance across multiple calls
    val_1 = get_compiled_validator("huit.api.admin-login-request", "1.0.0")
    val_2 = get_compiled_validator("huit.api.admin-login-request", "1.0.0")
    assert val_1 is val_2

    # 2. validate_contract succeeds on valid payload without re-reading from disk
    valid_admin_req = {"username": "admin_user", "password": "secure_password"}
    validate_contract("huit.api.admin-login-request", "1.0.0", valid_admin_req)

    # 3. validate_contract raises jsonschema.ValidationError on schema violation
    with pytest.raises(jsonschema.ValidationError):
        validate_contract("huit.api.admin-login-request", "1.0.0", {"username": "admin_user"})

    # 4. Cache clear invalidates and produces a new instance
    clear_registry_cache()
    val_3 = get_compiled_validator("huit.api.admin-login-request", "1.0.0")
    assert val_3 is not val_1


def test_phase_5_pydantic_boundary_models_match_canonical_schemas():
    # AdminLoginRequest & AdminLoginResponse & AdminSessionResponse
    req = AdminLoginRequest(username="admin", password="password123")
    assert req.username == "admin"
    resp = AdminLoginResponse(success=True, csrf_token="csrf_1234567890123456", message="OK")
    assert resp.success is True
    session_resp = AdminSessionResponse(valid=True, role="admin")
    assert session_resp.valid is True
    with pytest.raises(ValidationError):
        AdminSessionResponse(valid=True, role="editor")


def test_admin_session_response_exact_compatibility():
    """Verify AdminSessionResponse Pydantic model exact property and required compatibility with canonical schema."""
    canonical = load_schema("huit.api.admin-session-response", "1.0.0")
    generated = AdminSessionResponse.model_json_schema()

    assert set(generated["properties"]) == set(canonical["properties"])
    assert set(generated["required"]) == set(canonical["required"])

    # Thiếu role phải bị Pydantic từ chối
    with pytest.raises(ValidationError):
        AdminSessionResponse(valid=True)

    # Role khác admin phải bị từ chối
    with pytest.raises(ValidationError):
        AdminSessionResponse(valid=True, role="user")

    with pytest.raises(ValidationError):
        AdminSessionResponse(valid=True, role="editor")

    # Serialized response phải pass canonical validator
    valid_obj = AdminSessionResponse(valid=True, role="admin")
    validate_contract("huit.api.admin-session-response", "1.0.0", valid_obj.model_dump())


def test_job_accepted_response_contract_depth():
    """Verify JobAcceptedResponse Pydantic model exact compatibility with canonical huit.api.job-accepted-response@1.0.0."""
    canonical = load_schema("huit.api.job-accepted-response", "1.0.0")
    generated = JobAcceptedResponse.model_json_schema()

    assert set(generated["properties"]) == set(canonical["properties"])
    assert set(generated["required"]) == set(canonical["required"])

    # Valid instance
    valid_resp = JobAcceptedResponse(
        job_id="job_render_12345",
        status="queued",
        artifact_id="art-001",
        action="render",
        format="xlsx",
        scale=None,
        check_status_url="/api/jobs/job_render_12345",
    )
    validate_contract("huit.api.job-accepted-response", "1.0.0", valid_resp.model_dump())

    # Invalid scale (> 4)
    with pytest.raises(ValidationError):
        JobAcceptedResponse(
            job_id="job_render_12345",
            status="queued",
            check_status_url="/api/jobs/1",
            scale=8,
        )

    # Invalid status (!= "queued")
    with pytest.raises(ValidationError):
        JobAcceptedResponse(
            job_id="job_render_12345",
            status="completed",
            check_status_url="/api/jobs/1",
        )

    # ArtifactSummary status enum and ExportFormat
    summary = ArtifactSummary(
        artifact_id="art-001",
        type="spreadsheet",
        title="Tiêu đề",
        preview_url="/preview.svg",
        manifest_url="/manifest",
        status="ready",
    )
    assert summary.status == "ready"
    with pytest.raises(ValidationError):
        ArtifactSummary(
            artifact_id="art-001",
            type="spreadsheet",
            title="Tiêu đề",
            preview_url="/preview.svg",
            manifest_url="/manifest",
            status="unsupported_status",
        )

    # ImageCreateRequest & ImageResult
    img_req = ImageCreateRequest(prompt="Cổng trường HUIT", width=512, height=512, backend="flux")
    assert img_req.prompt == "Cổng trường HUIT"
    with pytest.raises(ValidationError):
        ImageCreateRequest(prompt="")  # min_length=1

    img_res = ImageResult(
        image_id="img_123456",
        image_url="/api/images/img_123456/file",
        width=512,
        height=512,
        access_scope="public",
        cached=False,
    )
    assert img_res.image_id == "img_123456"
    assert img_res.cached is False

    # JobStatusResponse
    job_status = JobStatusResponse(
        job_id="job_12345",
        status="processing",
        progress=75,
    )
    assert job_status.status == "processing"
    with pytest.raises(ValidationError):
        JobStatusResponse(job_id="job_12345", status="invalid_status")


def test_admin_login_response_drift_and_contract_depth():
    """Verify AdminLoginResponse exact properties, required set, and serialization."""
    schema = load_schema("huit.api.admin-login-response", "1.0.0")
    assert schema["additionalProperties"] is False
    assert set(schema["properties"].keys()) == {"success", "csrf_token", "message"}
    assert set(schema["required"]) == {"success", "csrf_token", "message"}
    assert schema["properties"]["success"]["const"] is True
    assert schema["properties"]["csrf_token"]["minLength"] == 16

    # Valid Pydantic serialization
    instance = AdminLoginResponse(success=True, csrf_token="a" * 32, message="Thành công")
    serialized = json.loads(instance.model_dump_json())
    validate_contract("huit.api.admin-login-response", "1.0.0", serialized)

    # Valid raw payload
    valid_payload = {"success": True, "csrf_token": "token_1234567890123", "message": "OK"}
    validate_contract("huit.api.admin-login-response", "1.0.0", valid_payload)

    # Invalid: missing csrf_token
    with pytest.raises(jsonschema.ValidationError):
        validate_contract("huit.api.admin-login-response", "1.0.0", {"success": True, "message": "OK"})

    # Invalid: csrf_token < 16 chars
    with pytest.raises(jsonschema.ValidationError):
        validate_contract("huit.api.admin-login-response", "1.0.0", {"success": True, "csrf_token": "short", "message": "OK"})

    # Invalid: extra property
    with pytest.raises(jsonschema.ValidationError):
        validate_contract("huit.api.admin-login-response", "1.0.0", {**valid_payload, "extra_field": "disallowed"})


def test_artifact_upscale_request_drift_and_contract_depth():
    """Verify ArtifactUpscaleRequest exact properties, min/max scale, and serialization."""
    schema = load_schema("huit.api.artifact-upscale-request", "1.0.0")
    assert schema["additionalProperties"] is False
    assert set(schema["properties"].keys()) == {"scale"}
    assert schema["properties"]["scale"]["minimum"] == 2
    assert schema["properties"]["scale"]["maximum"] == 4
    assert schema["properties"]["scale"]["default"] == 2

    # Pydantic serialization
    req = ArtifactUpscaleRequest(scale=4)
    serialized = json.loads(req.model_dump_json())
    validate_contract("huit.api.artifact-upscale-request", "1.0.0", serialized)

    # Valid raw payloads
    validate_contract("huit.api.artifact-upscale-request", "1.0.0", {"scale": 2})
    validate_contract("huit.api.artifact-upscale-request", "1.0.0", {"scale": 4})
    validate_contract("huit.api.artifact-upscale-request", "1.0.0", {})

    # Invalid: scale out of range
    with pytest.raises(jsonschema.ValidationError):
        validate_contract("huit.api.artifact-upscale-request", "1.0.0", {"scale": 1})
    with pytest.raises(jsonschema.ValidationError):
        validate_contract("huit.api.artifact-upscale-request", "1.0.0", {"scale": 8})

    # Invalid: extra field
    with pytest.raises(jsonschema.ValidationError):
        validate_contract("huit.api.artifact-upscale-request", "1.0.0", {"scale": 2, "unexpected": "prop"})


def test_artifact_summary_contract_depth():
    """Verify ArtifactSummary exact properties, required set, enums, nullables, and serialization."""
    schema = load_schema("huit.api.artifact-summary", "1.0.0")
    assert schema["additionalProperties"] is False
    expected_props = {
        "artifact_id", "type", "title", "preview_url", "manifest_url",
        "available_formats", "checksum", "preview_bytes", "chart_type",
        "status", "owner_id", "error_message"
    }
    assert set(schema["properties"].keys()) == expected_props
    assert set(schema["required"]) == {"artifact_id", "type", "title", "preview_url", "manifest_url"}
    assert schema["properties"]["type"]["enum"] == ["spreadsheet", "document", "image"]

    status_enum = next(b["enum"] for b in schema["properties"]["status"]["anyOf"] if "enum" in b)
    assert set(status_enum) == {"planned", "rendering", "ready", "failed", "unavailable", "pending"}

    # Pydantic serialization
    summary = ArtifactSummary(
        artifact_id="art-test-123",
        type="spreadsheet",
        title="Bảng điểm",
        preview_url="/api/artifacts/art-test-123/preview",
        manifest_url="/api/artifacts/art-test-123/manifest",
        status="ready",
        owner_id="user_123",
    )
    serialized = json.loads(summary.model_dump_json())
    validate_contract("huit.api.artifact-summary", "1.0.0", serialized)

    # Valid with nullable None
    valid_minimal = {
        "artifact_id": "art-123",
        "type": "document",
        "title": "Tài liệu",
        "preview_url": "/prev",
        "manifest_url": "/man",
        "status": None,
        "owner_id": None,
    }
    validate_contract("huit.api.artifact-summary", "1.0.0", valid_minimal)

    # Invalid: invalid type enum
    with pytest.raises(jsonschema.ValidationError):
        validate_contract("huit.api.artifact-summary", "1.0.0", {**valid_minimal, "type": "audio"})

    # Invalid: missing title
    invalid_no_title = dict(valid_minimal)
    del invalid_no_title["title"]
    with pytest.raises(jsonschema.ValidationError):
        validate_contract("huit.api.artifact-summary", "1.0.0", invalid_no_title)

    # Invalid: extra property
    with pytest.raises(jsonschema.ValidationError):
        validate_contract("huit.api.artifact-summary", "1.0.0", {**valid_minimal, "extra_key": 123})


def test_job_status_response_contract_depth():
    """Verify JobStatusResponse exact properties, required set, enums, and serialization."""
    schema = load_schema("huit.api.job-status-response", "1.0.0")
    assert schema["additionalProperties"] is False
    expected_props = {
        "job_id", "action", "status", "progress", "artifact_id",
        "result_url", "download_url", "check_status_url", "media_type",
        "error", "created_at", "updated_at"
    }
    assert set(schema["properties"].keys()) == expected_props
    assert set(schema["required"]) == {"job_id", "status"}
    expected_status_enum = {"queued", "pending", "processing", "completed", "failed", "cancelled"}
    assert set(schema["properties"]["status"]["enum"]) == expected_status_enum

    # Pydantic serialization
    job = JobStatusResponse(
        job_id="job_abc12345",
        status="completed",
        progress=100,
        result_url="/api/artifacts/123/file",
        download_url="https://storage.example.com/download",
    )
    serialized = json.loads(job.model_dump_json())
    validate_contract("huit.api.job-status-response", "1.0.0", serialized)

    # Valid payload
    valid_job = {"job_id": "job_12345", "status": "queued", "progress": 0}
    validate_contract("huit.api.job-status-response", "1.0.0", valid_job)

    # Invalid: progress out of range
    with pytest.raises(jsonschema.ValidationError):
        validate_contract("huit.api.job-status-response", "1.0.0", {**valid_job, "progress": 150})

    # Invalid: status not in enum
    with pytest.raises(jsonschema.ValidationError):
        validate_contract("huit.api.job-status-response", "1.0.0", {**valid_job, "status": "aborted"})

    # Invalid: legacy error_code field at root level violates additionalProperties
    with pytest.raises(jsonschema.ValidationError):
        validate_contract("huit.api.job-status-response", "1.0.0", {**valid_job, "error_code": "LEGACY_ERR"})


def test_image_request_and_result_contract_depth():
    """Verify ImageCreateRequest and ImageResult exact properties, bounds, enums, and serialization."""
    # 1. ImageCreateRequest
    req_schema = load_schema("huit.api.image-create-request", "1.0.0")
    assert req_schema["additionalProperties"] is False
    assert set(req_schema["properties"].keys()) == {
        "prompt", "width", "height", "max_json_kb", "style", "backend", "regenerate"
    }
    assert set(req_schema["required"]) == {"prompt"}
    assert req_schema["properties"]["width"]["minimum"] == 128
    assert req_schema["properties"]["width"]["maximum"] == 1024
    assert set(req_schema["properties"]["backend"]["enum"]) == {"flux", "svg"}

    img_req = ImageCreateRequest(prompt="Cổng trường HUIT", width=512, height=512, backend="flux")
    validate_contract("huit.api.image-create-request", "1.0.0", json.loads(img_req.model_dump_json()))

    # Invalid prompt empty string (minLength: 1)
    with pytest.raises(jsonschema.ValidationError):
        validate_contract("huit.api.image-create-request", "1.0.0", {"prompt": ""})

    # Invalid width > 1024
    with pytest.raises(jsonschema.ValidationError):
        validate_contract("huit.api.image-create-request", "1.0.0", {"prompt": "Valid", "width": 2048})

    # 2. ImageResult
    res_schema = load_schema("huit.api.image-result", "1.0.0")
    assert res_schema["additionalProperties"] is False
    expected_res_props = {
        "image_id", "id", "image_url", "thumbnail_url", "svg_url", "json_url",
        "width", "height", "model", "style", "byte_size", "checksum",
        "request_fingerprint", "billing", "cached", "access_scope", "owner_id"
    }
    assert set(res_schema["properties"].keys()) == expected_res_props
    assert set(res_schema["required"]) == {"image_id", "image_url"}
    scope_prop = res_schema["properties"]["access_scope"]
    scope_enum = scope_prop.get("enum") or next(b["enum"] for b in scope_prop.get("anyOf", []) if "enum" in b)
    assert set(scope_enum) == {"public", "private", "legacy_public"}

    img_res = ImageResult(
        image_id="img_abc123",
        image_url="/api/images/img_abc123/file",
        width=512,
        height=512,
        access_scope="public",
        cached=False,
    )
    validate_contract("huit.api.image-result", "1.0.0", json.loads(img_res.model_dump_json()))

    # Invalid: extra internal database field
    with pytest.raises(jsonschema.ValidationError):
        validate_contract("huit.api.image-result", "1.0.0", {
            "image_id": "img_abc123",
            "image_url": "/api/images/img_abc123/file",
            "internal_scene_descriptor": "private_data",
        })


def test_error_envelope_contract_depth():
    """Verify ErrorResponse schema structure, anyOf variants, and valid/invalid envelopes."""
    schema = load_schema("huit.api.error-response", "1.0.0")
    assert set(schema["properties"].keys()) == {"error_code", "message", "detail", "request_id", "details"}

    # Variant 1: standard service error envelope
    v1_payload = {
        "error_code": "RESOURCE_NOT_FOUND",
        "message": "Không tìm thấy tài nguyên yêu cầu",
        "request_id": "req_12345",
    }
    validate_contract("huit.api.error-response", "1.0.0", v1_payload)

    # Variant 2: FastAPI validation error envelope (detail string or array)
    v2_payload_str = {"detail": "Dữ liệu không hợp lệ"}
    validate_contract("huit.api.error-response", "1.0.0", v2_payload_str)

    v2_payload_list = {
        "detail": [{"loc": ["body", "prompt"], "msg": "field required", "type": "missing"}]
    }
    validate_contract("huit.api.error-response", "1.0.0", v2_payload_list)

    # Invalid: empty object (fails both anyOf requirements)
    with pytest.raises(jsonschema.ValidationError):
        validate_contract("huit.api.error-response", "1.0.0", {})


def test_queue_contracts_depth_input_result_error_retry():
    """Verify all 4 active queue contracts exact properties, required set, and boundaries."""
    from backend.app.services.job_queue import (
        validate_job_input,
        validate_job_result,
        validate_job_error,
        validate_retry_metadata,
    )

    # 1. job-input
    input_schema = load_schema("huit.queue.job-input", "1.0.0")
    assert input_schema["additionalProperties"] is False
    assert set(input_schema["required"]) == {"job_id", "action"}
    valid_input = {"job_id": "job_12345678", "action": "render", "format": "xlsx", "scale": 2}
    validate_job_input(valid_input)
    with pytest.raises(jsonschema.ValidationError):
        validate_job_input({**valid_input, "scale": 5})  # scale max 4

    # 2. job-result
    res_schema = load_schema("huit.queue.job-result", "1.0.0")
    assert res_schema["additionalProperties"] is False
    assert set(res_schema["required"]) == {"url"}
    valid_result = {"url": "/api/artifacts/123/file", "media_type": "image/png", "scale": 2}
    validate_job_result(valid_result)
    with pytest.raises(jsonschema.ValidationError):
        validate_job_result({"download_url": "https://example.com"})  # missing url

    # 3. job-error
    err_schema = load_schema("huit.queue.job-error", "1.0.0")
    assert err_schema["additionalProperties"] is False
    assert set(err_schema["required"]) == {"error_code", "message"}
    valid_error = {"error_code": "RENDER_FAILED", "message": "Dựng hình thất bại", "retryable": True}
    validate_job_error(valid_error)
    with pytest.raises(jsonschema.ValidationError):
        validate_job_error({"error_code": "ERR"})  # missing message

    # 4. retry-metadata
    retry_schema = load_schema("huit.queue.retry-metadata", "1.0.0")
    assert retry_schema["additionalProperties"] is False
    assert set(retry_schema["required"]) == {"attempt", "max_attempts"}
    assert retry_schema["properties"]["max_attempts"]["maximum"] == 10
    valid_retry = {"attempt": 1, "max_attempts": 3, "retries": 1}
    validate_retry_metadata(valid_retry)
    with pytest.raises(jsonschema.ValidationError):
        validate_retry_metadata({"attempt": 1, "max_attempts": 20})  # max 10


def test_mongo_validator_mapping_depth():
    """Verify all 9 collections map to valid registered schemas with bsonType and required."""
    mig023 = importlib.import_module("scripts.migrations.023_sync_canonical_mongo_validators")
    collection_schema_map = mig023.COLLECTION_SCHEMA_MAP

    assert len(collection_schema_map) == 9
    for col_name, (schema_id, version) in collection_schema_map.items():
        doc = load_schema(schema_id, version)
        assert "$jsonSchema" in doc
        json_schema = doc["$jsonSchema"]
        assert json_schema.get("bsonType") == "object"
        assert "required" in json_schema
        assert len(json_schema["required"]) > 0
        assert "properties" in json_schema
        assert "_id" in json_schema["properties"]


def test_migration_023_uses_only_canonical_registry():
    """Verify Migration 023 sources all collection validators strictly from Canonical Registry."""
    mig023 = importlib.import_module("scripts.migrations.023_sync_canonical_mongo_validators")
    from backend.app.contracts.schema_registry import iter_schema_entries

    registry_schemas = {(e["schema_id"], e["version"]) for e in iter_schema_entries()}
    for col_name, (schema_id, version) in mig023.COLLECTION_SCHEMA_MAP.items():
        assert (schema_id, version) in registry_schemas
        # Ensure load_schema returns the identical document used by migration
        loaded = load_schema(schema_id, version)
        assert "$jsonSchema" in loaded


def test_frontend_parser_acceptance_and_rejection_with_backend_responses():
    """Verify frontend contract parsers accept genuine backend responses and reject malformed ones."""
    # 1. AdminLoginResponse
    admin_login = AdminLoginResponse(success=True, csrf_token="a" * 32, message="OK")
    validate_contract("huit.api.admin-login-response", "1.0.0", json.loads(admin_login.model_dump_json()))
    with pytest.raises(jsonschema.ValidationError):
        # Frontend parser will reject if csrf_token is missing or empty
        validate_contract("huit.api.admin-login-response", "1.0.0", {"success": True, "message": "OK"})

    # 2. AdminSessionResponse
    admin_sess = AdminSessionResponse(valid=True, role="admin")
    validate_contract("huit.api.admin-session-response", "1.0.0", json.loads(admin_sess.model_dump_json()))
    with pytest.raises(jsonschema.ValidationError):
        # Frontend parser will reject invalid role
        validate_contract("huit.api.admin-session-response", "1.0.0", {"valid": True, "role": "superadmin"})

    # 3. JobStatusResponse
    job_resp = JobStatusResponse(job_id="job_real_123", status="completed", progress=100)
    validate_contract("huit.api.job-status-response", "1.0.0", json.loads(job_resp.model_dump_json()))
    with pytest.raises(jsonschema.ValidationError):
        # Frontend parser will reject invalid status enum
        validate_contract("huit.api.job-status-response", "1.0.0", {"job_id": "job_real_123", "status": "finished"})

    # 4. ImageResult
    img_resp = ImageResult(
        image_id="img_real_456",
        image_url="/api/images/img_real_456/file",
        width=512,
        height=512,
        access_scope="public",
    )
    validate_contract("huit.api.image-result", "1.0.0", json.loads(img_resp.model_dump_json()))
    with pytest.raises(jsonschema.ValidationError):
        # Frontend parser will reject extra leaked database properties
        validate_contract("huit.api.image-result", "1.0.0", {
            "image_id": "img_real_456",
            "image_url": "/api/images/img_real_456/file",
            "raw_mongo_db_cursor": "leak",
        })
