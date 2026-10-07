"""
test_migration_023_canonical_validators.py
Bộ kiểm thử toàn diện cho Migration 023: Đồng bộ MongoDB Canonical Validators:
1. Xác minh mapping 9 collections với canonical schema registry.
2. Kiểm thử chế độ Dry-Run mặc định (không gọi collMod).
3. Kiểm thử Preflight tính toán valid/invalid documents chính xác.
4. Kiểm thử Chặn Strict nếu tỷ lệ tuân thủ dữ liệu < 100%.
5. Kiểm thử Kích hoạt Strict khi dữ liệu đạt 100% tuân thủ.
6. Kiểm thử collMod chỉ được gọi khi có cờ --apply.
7. Kiểm thử bảo toàn indexes hiện có.
8. Kiểm thử sinh Rollback Metadata đầy đủ cho 9 collections.
9. Kiểm thử rào chắn an toàn bảo vệ Production.
"""
from datetime import datetime, timezone
import importlib
import pytest
from unittest.mock import MagicMock, patch

from backend.app.contracts.schema_registry import load_schema

migration_023 = importlib.import_module("scripts.migrations.023_sync_canonical_mongo_validators")
COLLECTION_SCHEMA_MAP = migration_023.COLLECTION_SCHEMA_MAP
run_sync_canonical_validators = migration_023.run_sync_canonical_validators
check_production_safety = migration_023.check_production_safety
get_parser = migration_023.get_parser


@pytest.fixture(autouse=True)
def mock_save_report(monkeypatch):
    """Tránh sinh file báo cáo rác ra thư mục audit_outputs trong lúc chạy test."""
    monkeypatch.setattr(
        "scripts.migrations.023_sync_canonical_mongo_validators.save_migration_report",
        lambda report, report_file: None
    )


def test_migration_023_has_expected_nine_collection_mappings():
    """Yêu cầu 1 & 2: Xác minh 9 mapping chuẩn xác với canonical schema registry."""
    expected_mappings = {
        "assets": "huit.mongo.asset-record",
        "artifacts": "huit.mongo.artifact-record",
        "jobs": "huit.mongo.job-record",
        "generated_images": "huit.mongo.generated-image-record",
        "admin_sessions": "huit.mongo.admin-session-document",
        "query_cache": "huit.mongo.query-cache-record",
        "rag_events": "huit.mongo.rag-event-record",
        "admission_visuals": "huit.mongo.admission-visual-record",
        "huit_kb": "huit.mongo.huit-kb-record",
    }
    assert len(COLLECTION_SCHEMA_MAP) == 9
    for col, (schema_id, version) in COLLECTION_SCHEMA_MAP.items():
        assert col in expected_mappings
        assert expected_mappings[col] == schema_id
        assert version == "1.0.0"
        # Xác minh schema load được từ canonical registry
        doc = load_schema(schema_id, version)
        assert "$jsonSchema" in doc
        assert doc["$jsonSchema"].get("bsonType") == "object"


def test_migration_023_production_safety_guard():
    """Yêu cầu 12: Rào chắn ngăn chặn chạy ngoài ý muốn trên production."""
    # Dry-run luôn an toàn kể cả trên production
    check_production_safety("huit_chatbot", is_dry_run=True)

    # Tên database sai convention phải bị chặn
    with pytest.raises(RuntimeError, match="DATABASE MISMATCH"):
        check_production_safety("production_customer_db", is_dry_run=False)

    # Khi IS_PRODUCTION = True mà thiếu biến môi trường cho phép -> chặn
    with patch.dict("os.environ", {"APP_ENV": "production"}, clear=True):
        with pytest.raises(RuntimeError, match="PRODUCTION BLOCK"):
            check_production_safety("huit_chatbot", is_dry_run=False)


def test_migration_023_dry_run_default():
    """Yêu cầu 3 & 7: Mặc định chạy dry-run, không gọi collMod."""
    mock_client = MagicMock()
    mock_db = MagicMock()
    mock_db.name = "huit_chatbot"
    mock_db.list_collection_names.return_value = list(COLLECTION_SCHEMA_MAP.keys())

    mock_db.command.return_value = {
        "cursor": {
            "firstBatch": [
                {
                    "name": col,
                    "options": {
                        "validator": {"$jsonSchema": {"bsonType": "object"}},
                        "validationLevel": "moderate",
                        "validationAction": "warn",
                    },
                }
                for col in COLLECTION_SCHEMA_MAP
            ]
        }
    }

    # Giả lập collection counts: 10 docs, 10 valid
    for col in COLLECTION_SCHEMA_MAP:
        mock_col = MagicMock()
        mock_col.count_documents.side_effect = lambda query=None: 10
        mock_col.index_information.return_value = {"_id_": {"key": [("_id", 1)]}}
        setattr(mock_db, col, mock_col)
        mock_db.__getitem__.side_effect = lambda k: getattr(mock_db, k)

    report = run_sync_canonical_validators(
        is_dry_run=True,
        client_override=mock_client,
        db_override=mock_db,
    )

    assert report["mode"] == "dry_run"
    assert report["status"] == "SUCCESS"
    assert len(report["collections"]) == 9

    # Xác minh TUYỆT ĐỐI KHÔNG gọi collMod trong dry-run
    for call in mock_db.command.call_args_list:
        args, _ = call
        if args and args[0] == "collMod":
            pytest.fail("collMod was unexpectedly called in dry-run mode!")

    # Mọi collection phải có applied = False trong dry-run
    for col, col_rep in report["collections"].items():
        assert col_rep["applied"] is False


def test_migration_023_blocks_strict_if_data_not_100_percent_compliant():
    """Yêu cầu 5 & 6: Không bật strict validator nếu dữ liệu hiện có chưa đạt 100%."""
    mock_client = MagicMock()
    mock_db = MagicMock()
    mock_db.name = "huit_chatbot"
    mock_db.list_collection_names.return_value = ["rag_events"]

    mock_db.command.return_value = {
        "cursor": {
            "firstBatch": [
                {
                    "name": "rag_events",
                    "options": {
                        "validator": {},
                        "validationLevel": "off",
                        "validationAction": "warn",
                    },
                }
            ]
        }
    }

    mock_col = MagicMock()
    # 100 docs total, but only 85 docs pass canonical validator
    def mock_count(q=None):
        if not q or q == {}:
            return 100
        return 85

    mock_col.count_documents.side_effect = mock_count
    mock_col.index_information.return_value = {"_id_": {"key": [("_id", 1)]}}
    mock_db.__getitem__.return_value = mock_col

    report = run_sync_canonical_validators(
        is_dry_run=True,
        client_override=mock_client,
        db_override=mock_db,
    )

    rag_rep = report["collections"]["rag_events"]
    preflight = rag_rep["preflight"]
    assert preflight["total_docs"] == 100
    assert preflight["valid_docs"] == 85
    assert preflight["invalid_docs"] == 15
    assert preflight["compliance_rate_pct"] == 85.0
    assert preflight["strict_eligible"] is False
    # validationLevel phải là moderate, không được là strict
    assert rag_rep["validation_level"] == "moderate"
    assert rag_rep["validation_action"] == "warn"


def test_migration_023_apply_mode_executes_collmod_and_preserves_indexes():
    """Yêu cầu 7, 8, 9, 10, 11: Khi --apply, collMod được gọi, index được bảo toàn, có rollback metadata."""
    mock_client = MagicMock()
    mock_db = MagicMock()
    mock_db.name = "huit_chatbot"
    mock_db.list_collection_names.return_value = ["assets"]

    mock_db.command.return_value = {
        "cursor": {
            "firstBatch": [
                {
                    "name": "assets",
                    "options": {
                        "validator": {"$jsonSchema": {"bsonType": "object"}},
                        "validationLevel": "moderate",
                        "validationAction": "warn",
                    },
                }
            ]
        }
    }

    mock_col = MagicMock()
    mock_col.count_documents.return_value = 50  # 50/50 valid -> 100% compliant
    mock_col.index_information.return_value = {
        "_id_": {"key": [("_id", 1)]},
        "uniq_content_hash": {"key": [("content_hash", 1)], "unique": True},
    }
    mock_db.__getitem__.return_value = mock_col

    # Mock list_collections filter for post-verification
    mock_db.list_collections.return_value = [
        {
            "name": "assets",
            "options": {
                "validator": {"$jsonSchema": {"bsonType": "object"}},
                "validationLevel": "strict",
                "validationAction": "error",
            },
        }
    ]

    report = run_sync_canonical_validators(
        is_dry_run=False,
        client_override=mock_client,
        db_override=mock_db,
    )

    assert report["mode"] == "apply"
    assert report["status"] == "SUCCESS"
    assert "assets" in report["collections"]
    col_rep = report["collections"]["assets"]
    assert col_rep["applied"] is True
    assert col_rep["validation_level"] == "strict"
    assert col_rep["validation_action"] == "error"
    assert col_rep["indexes_preserved"] is True

    # Xác minh lệnh collMod đã được gọi đúng tham số
    collmod_calls = [
        call for call in mock_db.command.call_args_list
        if call[0] and call[0][0] == "collMod"
    ]
    assert len(collmod_calls) >= 1
    c_args, c_kwargs = collmod_calls[0]
    assert c_args[0] == "collMod"
    assert c_args[1] == "assets"
    assert c_kwargs["validationLevel"] == "strict"
    assert c_kwargs["validationAction"] == "error"
    assert "$jsonSchema" in c_kwargs["validator"]

    # Xác minh Rollback Metadata đã được lưu
    assert "assets" in report["rollback_metadata"]
    rb = report["rollback_metadata"]["assets"]
    assert rb["previous_validation_level"] == "moderate"
    assert rb["previous_validation_action"] == "warn"
    assert rb["rollback_command"]["collMod"] == "assets"


def test_migration_023_parser_modes_and_mutual_exclusion():
    """Yêu cầu Phase 9: Kiểm thử CLI parser mặc định dry-run, --dry-run, --apply, và mutual exclusion."""
    parser = get_parser()

    # 1. Không truyền flag -> mặc định dry-run
    args_empty = parser.parse_args([])
    assert not args_empty.apply
    is_dry_run_empty = not args_empty.apply
    assert is_dry_run_empty is True
    assert args_empty.dry_run is False

    # 2. --dry-run -> dry-run
    args_dry = parser.parse_args(["--dry-run"])
    assert not args_dry.apply
    is_dry_run_flag = not args_dry.apply
    assert is_dry_run_flag is True
    assert args_dry.dry_run is True

    # 3. --apply -> apply
    args_apply = parser.parse_args(["--apply"])
    assert args_apply.apply is True
    is_dry_run_apply = not args_apply.apply
    assert is_dry_run_apply is False

    # 4. Không thể dùng đồng thời hai flag (--dry-run và --apply)
    with pytest.raises(SystemExit):
        parser.parse_args(["--dry-run", "--apply"])


def test_migration_023_production_apply_requires_confirmation():
    """Yêu cầu Phase 9: Production apply bắt buộc có ALLOW_PRODUCTION_MIGRATION_023."""
    with patch.dict("os.environ", {"APP_ENV": "production", "ALLOW_PRODUCTION_MIGRATION_023": "true"}, clear=True):
        # Có cờ xác nhận -> thành công
        check_production_safety("huit_chatbot", is_dry_run=False)

    with patch.dict("os.environ", {"APP_ENV": "production"}, clear=True):
        # Thiếu cờ xác nhận -> bị chặn
        with pytest.raises(RuntimeError, match="PRODUCTION BLOCK"):
            check_production_safety("huit_chatbot", is_dry_run=False)
