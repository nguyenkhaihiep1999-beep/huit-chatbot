"""
018_phase6_schema_sync_and_validators.py
Migration Phase 6: Chuẩn hóa Schema và Áp dụng $jsonSchema Validators cho huit_kb & operation_audit:
- Mặc định --dry-run (chỉ áp dụng khi có cờ --apply).
- Xác minh chặt chẽ database là huit_chatbot.
- Tạo bản sao lưu huit_kb trước khi sửa đổi (khi --apply).
- Chuẩn hóa 7 document legacy trong huit_kb sang BSON Date UTC và bổ sung metadata chuẩn.
- Preflight validation: Chỉ áp dụng validator khi 100% document trong huit_kb pass kiểm tra.
- Tạo collection, indexes và $jsonSchema validator cho operation_audit.
- Áp dụng $jsonSchema validator cho huit_kb mà không làm ảnh hưởng Atlas Vector Search Index (huit_vector_index).
- Hậu kiểm toàn diện và xuất báo cáo JSON.
- Tuyệt đối không drop collection, không xóa backup tự động, không log credentials.
"""
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from backend.app.config import settings
from backend.app.contracts.schema_registry import load_schema
from backend.app.models.mongo_models import (
    MongoHuitKbRecord,
    MongoOperationAuditRecord,
    ensure_utc_datetime,
)
from backend.app.repositories.mongo_repository import MongoRepository
from scripts.migrations.common import (
    create_collection_backup,
    get_base_parser,
    get_migration_db,
    logger,
    save_migration_report,
)

# 1. Validator operation_audit lấy trực tiếp từ nguồn chuẩn duy nhất.
OPERATION_AUDIT_VALIDATOR = load_schema("huit.mongo.operation-audit", "1.1.0")

# 2. $jsonSchema Validator cho huit_kb
HUIT_KB_VALIDATOR = {
    "$jsonSchema": {
        "bsonType": "object",
        "required": ["title", "text", "source_url", "category", "embedding"],
        "properties": {
            "_id": {"bsonType": ["string", "objectId"]},
            "schema_version": {"bsonType": "int", "minimum": 1},
            "title": {"bsonType": "string", "minLength": 1},
            "text": {"bsonType": "string", "minLength": 1},
            "source_url": {"bsonType": "string", "minLength": 1},
            "category": {"bsonType": "string", "minLength": 1},
            "embedding": {
                "bsonType": "array",
                "minItems": 1024,
                "maxItems": 1024,
                "items": {"bsonType": ["double", "int"]},
            },
            "raw_text": {"bsonType": ["string", "null"]},
            "page_title": {"bsonType": ["string", "null"]},
            "source_domain": {"bsonType": ["string", "null"]},
            "official": {"bsonType": ["bool", "null"]},
            "retrieved_at": {"bsonType": ["date", "null"]},
            "updated_at": {"bsonType": ["date", "null"]},
            "created_at": {"bsonType": ["date", "null"]},
            "verification_status": {"bsonType": ["string", "null"]},
            "major_code": {"bsonType": ["string", "null"]},
            "year": {"bsonType": ["int", "null"]},
            "visual_id": {"bsonType": ["string", "null"]},
            "chunk_hash": {"bsonType": ["string", "null"]},
            "url": {"bsonType": ["string", "null"]},
            "date": {"bsonType": ["string", "null"]},
            "cluster_id": {"bsonType": ["int", "null"]},
        },
    }
}


def run_migration_phase6(
    is_dry_run: bool,
    database_name: str,
    batch_size: int = 100,
    report_file: Optional[str] = None,
) -> Dict[str, Any]:
    mode_str = "DRY-RUN (Mô phỏng)" if is_dry_run else "APPLY (Thực thi)"
    logger.info(f"=== Bắt đầu Migration 018: Chuẩn hóa Schema & Validators Phase 6 [{mode_str}] ===")

    # 1. Kiểm tra an toàn Database
    target_db = database_name or settings.MONGODB_DB
    if target_db != "huit_chatbot":
        raise ValueError(f"Chỉ được phép thực thi trên database 'huit_chatbot'. Hiện tại: '{target_db}'")

    client, db = get_migration_db(target_db)
    logger.info(f"Kết nối database thành công: {db.name}")

    report: Dict[str, Any] = {
        "script": "018_phase6_schema_sync_and_validators",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "dry_run": is_dry_run,
        "database": db.name,
        "backup_name": None,
        "huit_kb": {
            "total_documents_scanned": 0,
            "legacy_documents_detected": 0,
            "documents_normalized": 0,
            "preflight_passed": 0,
            "preflight_failed": 0,
            "validator_applied": False,
        },
        "operation_audit": {
            "collection_created": False,
            "validator_applied": False,
            "indexes_created": [],
        },
        "post_verification": {},
        "status": "pending",
        "errors": [],
    }

    # =========================================================================
    # BƯỚC 1: XỬ LÝ VÀ CHUẨN HÓA HUIT_KB
    # =========================================================================
    kb_col = db["huit_kb"]
    total_docs = kb_col.count_documents({})
    report["huit_kb"]["total_documents_scanned"] = total_docs
    logger.info(f"Collection 'huit_kb' có tổng cộng {total_docs} documents.")

    # Tìm các legacy documents có created_at dạng chuỗi hoặc thiếu metadata
    legacy_docs = []
    for d in kb_col.find({}):
        is_legacy = False
        if isinstance(d.get("created_at"), str):
            is_legacy = True
        elif not d.get("retrieved_at") or not d.get("source_domain"):
            is_legacy = True
        if is_legacy:
            legacy_docs.append(d)

    report["huit_kb"]["legacy_documents_detected"] = len(legacy_docs)
    logger.info(f"Phát hiện {len(legacy_docs)} documents legacy cần chuẩn hóa trong 'huit_kb'.")

    # Tạo backup nếu là chế độ apply
    if not is_dry_run and len(legacy_docs) > 0:
        logger.info("Đang tạo bản sao lưu collection 'huit_kb' trước khi chuẩn hóa...")
        bk_name = create_collection_backup(db, "huit_kb")
        report["backup_name"] = bk_name
        logger.info(f"Đã tạo backup an toàn: {bk_name}")
    elif is_dry_run:
        report["backup_name"] = "[DRY-RUN] Sẽ tạo huit_kb_backup_<timestamp>"

    # Chuẩn hóa các document legacy
    preflight_docs = []
    cursor = kb_col.find({})
    for doc in cursor:
        doc_id = doc["_id"]
        # Kiểm tra xem có phải doc legacy cần chuẩn hóa không
        is_legacy = any(ld["_id"] == doc_id for ld in legacy_docs)
        if is_legacy:
            # Tạo doc đã chuẩn hóa
            rec = MongoHuitKbRecord.from_legacy(doc)
            norm_dict = rec.model_dump()
            norm_dict["_id"] = doc_id
            if not is_dry_run:
                # Cập nhật vào DB
                update_fields = {
                    "created_at": norm_dict["created_at"],
                    "retrieved_at": norm_dict["retrieved_at"],
                    "updated_at": norm_dict["updated_at"],
                    "source_domain": norm_dict["source_domain"],
                    "official": norm_dict["official"],
                    "verification_status": norm_dict["verification_status"],
                    "page_title": norm_dict["page_title"],
                    "schema_version": 1,
                }
                kb_col.update_one({"_id": doc_id}, {"$set": update_fields})
            report["huit_kb"]["documents_normalized"] += 1
            preflight_docs.append(norm_dict)
        else:
            preflight_docs.append(doc)

    logger.info(f"Đã chuẩn hóa {report['huit_kb']['documents_normalized']} documents legacy.")

    # Chạy Preflight Validation trên toàn bộ documents
    preflight_errors = []
    for d in preflight_docs:
        try:
            MongoHuitKbRecord.from_legacy(d)
            report["huit_kb"]["preflight_passed"] += 1
        except Exception as p_err:
            report["huit_kb"]["preflight_failed"] += 1
            preflight_errors.append(f"Doc {d.get('_id')}: {p_err}")

    logger.info(
        f"Kết quả Preflight 'huit_kb': {report['huit_kb']['preflight_passed']}/{total_docs} PASS, "
        f"{report['huit_kb']['preflight_failed']} FAIL"
    )

    if report["huit_kb"]["preflight_failed"] > 0:
        err_msg = f"Preflight thất bại: có {report['huit_kb']['preflight_failed']} documents không đạt chuẩn!"
        logger.error(err_msg)
        report["errors"].extend(preflight_errors[:5])
        raise RuntimeError(err_msg)

    # Áp dụng $jsonSchema Validator cho huit_kb sau khi preflight đạt 100%
    if not is_dry_run:
        logger.info("Áp dụng $jsonSchema validator cho 'huit_kb' bằng collMod...")
        db.command({
            "collMod": "huit_kb",
            "validator": HUIT_KB_VALIDATOR,
            "validationLevel": "moderate",
            "validationAction": "error",
        })
        report["huit_kb"]["validator_applied"] = True
        logger.info("Đã kích hoạt validator cho 'huit_kb' thành công.")
    else:
        report["huit_kb"]["validator_applied"] = False
        logger.info("[DRY-RUN] Preflight 100% PASS -> Sẽ áp dụng $jsonSchema validator cho 'huit_kb'.")

    # =========================================================================
    # BƯỚC 2: THIẾT LẬP COLLECTION VÀ VALIDATOR CHO OPERATION_AUDIT
    # =========================================================================
    existing_colls = db.list_collection_names()
    if "operation_audit" not in existing_colls:
        if not is_dry_run:
            logger.info("Tạo collection 'operation_audit' kèm validator và options...")
            db.create_collection(
                "operation_audit",
                validator=OPERATION_AUDIT_VALIDATOR,
                validationLevel="moderate",
                validationAction="error",
            )
            report["operation_audit"]["collection_created"] = True
            report["operation_audit"]["validator_applied"] = True
        else:
            logger.info("[DRY-RUN] Sẽ tạo collection 'operation_audit' kèm $jsonSchema validator.")
            report["operation_audit"]["collection_created"] = False
            report["operation_audit"]["validator_applied"] = False
    else:
        if not is_dry_run:
            logger.info("Cập nhật validator cho collection 'operation_audit' hiện hữu...")
            db.command({
                "collMod": "operation_audit",
                "validator": OPERATION_AUDIT_VALIDATOR,
                "validationLevel": "moderate",
                "validationAction": "error",
            })
            report["operation_audit"]["validator_applied"] = True
        else:
            logger.info("[DRY-RUN] Sẽ cập nhật validator cho 'operation_audit'.")

    # Khởi tạo indexes cho operation_audit
    if not is_dry_run:
        oa_col = db["operation_audit"]
        idx_res = [
            oa_col.create_index([("created_at", -1)]),
            oa_col.create_index([("operation_key", 1), ("operation_version", 1), ("created_at", -1)]),
            oa_col.create_index([("request_id", 1)], sparse=True),
            oa_col.create_index([("status", 1), ("created_at", -1)]),
            oa_col.create_index([("principal_id", 1), ("created_at", -1)]),
        ]
        report["operation_audit"]["indexes_created"] = idx_res
        logger.info(f"Đã tạo {len(idx_res)} indexes cho 'operation_audit': {idx_res}")
    else:
        report["operation_audit"]["indexes_created"] = [
            "[DRY-RUN] created_at_-1",
            "[DRY-RUN] operation_key_1_operation_version_1_created_at_-1",
            "[DRY-RUN] request_id_1 (sparse)",
            "[DRY-RUN] status_1_created_at_-1",
            "[DRY-RUN] principal_id_1_created_at_-1",
        ]

    # =========================================================================
    # BƯỚC 3: HẬU KIỂM (POST-VERIFICATION)
    # =========================================================================
    logger.info("=== Bắt đầu Hậu kiểm (Post-Verification) ===")
    post_checks: Dict[str, Any] = {
        "huit_kb_document_count": kb_col.count_documents({}),
        "huit_kb_vector_search_status": "UNKNOWN",
        "huit_kb_has_validator": False,
        "operation_audit_has_validator": False,
        "operation_audit_indexes_count": 0,
    }

    # Kiểm tra tính toàn vẹn của Vector Search Index trên huit_kb
    try:
        vs_list = list(kb_col.aggregate([{"$listSearchIndexes": {}}]))
        for si in vs_list:
            if si.get("name") == "huit_vector_index":
                post_checks["huit_kb_vector_search_status"] = si.get("status")
    except Exception as e:
        post_checks["huit_kb_vector_search_status"] = f"Check failed: {e}"

    # Kiểm tra validators
    col_infos = {c["name"]: c for c in db.list_collections()}
    if "huit_kb" in col_infos:
        opts = col_infos["huit_kb"].get("options", {})
        post_checks["huit_kb_has_validator"] = bool(opts.get("validator"))
    if "operation_audit" in col_infos:
        opts = col_infos["operation_audit"].get("options", {})
        post_checks["operation_audit_has_validator"] = bool(opts.get("validator"))
        post_checks["operation_audit_indexes_count"] = len(list(db["operation_audit"].list_indexes()))

    report["post_verification"] = post_checks
    report["status"] = "success"

    logger.info(f"Hậu kiểm hoàn tất: {json.dumps(post_checks, ensure_ascii=False, indent=2)}")

    # Ghi báo cáo JSON
    save_migration_report(report, report_file)
    logger.info("=== Hoàn thành Migration 018 thành công ===")
    return report


if __name__ == "__main__":
    parser = get_base_parser("Migration 018: Chuẩn hóa Schema và Áp dụng $jsonSchema Validators Phase 6")
    args = parser.parse_args()

    try:
        run_migration_phase6(
            is_dry_run=args.dry_run,
            database_name=args.database,
            batch_size=args.batch_size,
            report_file=args.report_file,
        )
    except Exception as exc:
        logger.error(f"Migration 018 thất bại: {exc}", exc_info=True)
        sys.exit(1)
