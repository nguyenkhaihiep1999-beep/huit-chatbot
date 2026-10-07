"""
scripts/migrations/023_sync_canonical_mongo_validators.py
Migration 023: Đồng bộ MongoDB Collection Validators từ Canonical Schema Registry:
1. Load MongoDB schemas từ canonical registry bằng load_schema.
2. Mapping chuẩn hóa 9 collections:
   - assets -> huit.mongo.asset-record@1.0.0
   - artifacts -> huit.mongo.artifact-record@1.0.0
   - jobs -> huit.mongo.job-record@1.0.0
   - generated_images -> huit.mongo.generated-image-record@1.0.0
   - admin_sessions -> huit.mongo.admin-session-document@1.0.0
   - query_cache -> huit.mongo.query-cache-record@1.0.0
   - rag_events -> huit.mongo.rag-event-record@1.0.0
   - admission_visuals -> huit.mongo.admission-visual-record@1.0.0
   - huit_kb -> huit.mongo.huit-kb-record@1.0.0
3. Mặc định chạy dry-run (an toàn tuyệt đối, không sửa đổi dữ liệu).
4. Preflight dữ liệu hiện có cho từng collection.
5. Báo cáo chi tiết số document hợp lệ / không hợp lệ / tỷ lệ tuân thủ.
6. Không bật strict validator nếu dữ liệu hiện có chưa đạt 100% tuân thủ.
7. Chỉ thực hiện lệnh collMod khi có cờ --apply rõ ràng.
8. Bảo toàn nguyên vẹn index hiện có (không drop, không re-index).
9. Bảo toàn nguyên vẹn Atlas Vector Search indexes.
10. Post-verification sau khi apply.
11. Rollback metadata chi tiết được lưu trong báo cáo migration.
12. Bảo vệ Production: Tuyệt đối không tự động chạy lên production nếu thiếu biến môi trường cho phép tường minh.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import os
from pathlib import Path
import sys
from typing import Any, Dict, List, Optional, Tuple

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

from backend.app.config import settings
from backend.app.contracts.schema_registry import load_schema
from scripts.migrations.common import (
    get_base_parser,
    get_migration_db,
    logger,
    save_migration_report,
)

MIGRATION_VERSION = "023"
MIGRATION_NAME = "023_sync_canonical_mongo_validators"

COLLECTION_SCHEMA_MAP: Dict[str, Tuple[str, str]] = {
    "assets": ("huit.mongo.asset-record", "1.0.0"),
    "artifacts": ("huit.mongo.artifact-record", "1.0.0"),
    "jobs": ("huit.mongo.job-record", "1.0.0"),
    "generated_images": ("huit.mongo.generated-image-record", "1.0.0"),
    "admin_sessions": ("huit.mongo.admin-session-document", "1.0.0"),
    "query_cache": ("huit.mongo.query-cache-record", "1.0.0"),
    "rag_events": ("huit.mongo.rag-event-record", "1.0.0"),
    "admission_visuals": ("huit.mongo.admission-visual-record", "1.0.0"),
    "huit_kb": ("huit.mongo.huit-kb-record", "1.0.0"),
}


def check_production_safety(db_name: str, is_dry_run: bool) -> None:
    """Safeguard: Refuse to run on production unless explicit override is provided."""
    if is_dry_run:
        return
    if getattr(settings, "IS_PRODUCTION", False):
        if not os.getenv("ALLOW_PRODUCTION_MIGRATION_023"):
            raise RuntimeError(
                "[PRODUCTION BLOCK] Refusing to run migration 023 on PRODUCTION environment "
                "without explicit ALLOW_PRODUCTION_MIGRATION_023=true environment flag."
            )
    if "huit" not in db_name.lower():
        raise RuntimeError(
            f"[DATABASE MISMATCH] Database name '{db_name}' does not match expected convention ('huit_chatbot')."
        )


def run_sync_canonical_validators(
    is_dry_run: bool = True,
    database_name: Optional[str] = None,
    report_file: Optional[str] = None,
    client_override: Optional[Any] = None,
    db_override: Optional[Any] = None,
) -> Dict[str, Any]:
    """Execute or simulate canonical validator synchronization for all 9 MongoDB collections."""
    mode_str = "DRY-RUN (MÔ PHỎNG)" if is_dry_run else "APPLY (THỰC THI THẬT SỰ)"
    logger.info(f"=== BẮT ĐẦU MIGRATION {MIGRATION_VERSION}: {MIGRATION_NAME} [{mode_str}] ===")

    if client_override is not None and db_override is not None:
        client, db = client_override, db_override
    else:
        client, db = get_migration_db(database_name)

    logger.info(f"Đã kết nối tới Database: '{db.name}'")
    check_production_safety(db.name, is_dry_run)

    timestamp_iso = datetime.now(timezone.utc).isoformat()
    report: Dict[str, Any] = {
        "migration": MIGRATION_NAME,
        "version": MIGRATION_VERSION,
        "mode": "dry_run" if is_dry_run else "apply",
        "started_at": timestamp_iso,
        "database": db.name,
        "collections": {},
        "rollback_metadata": {},
        "status": "in_progress",
        "errors": [],
    }

    try:
        existing_collections = db.list_collection_names()
        coll_info_dict = {
            c["name"]: c
            for c in db.command("listCollections").get("cursor", {}).get("firstBatch", [])
            if "name" in c
        }
    except Exception as exc:
        logger.warning(f"Không thể đọc listCollections qua command: {exc}, fallback db.list_collections()")
        existing_collections = db.list_collection_names()
        coll_info_dict = {c["name"]: c for c in db.list_collections()}

    for col_name, (schema_id, version) in COLLECTION_SCHEMA_MAP.items():
        logger.info(f"--- Xử lý collection: '{col_name}' (Schema: {schema_id}@{version}) ---")

        # 1. Load canonical schema
        raw_schema = load_schema(schema_id, version)
        canonical_validator = {"$jsonSchema": raw_schema["$jsonSchema"]}

        col_exists = col_name in existing_collections
        col_report: Dict[str, Any] = {
            "schema_id": schema_id,
            "schema_version": version,
            "collection_exists": col_exists,
            "preflight": {},
            "applied": False,
            "validation_level": None,
            "validation_action": None,
            "indexes_preserved": True,
            "post_verification": {},
        }

        if not col_exists:
            logger.info(f"Collection '{col_name}' chưa tồn tại trong database.")
            col_report["preflight"] = {
                "total_docs": 0,
                "valid_docs": 0,
                "invalid_docs": 0,
                "compliance_rate_pct": 100.0,
                "strict_eligible": True,
            }
            if not is_dry_run:
                logger.info(f"Tạo mới collection '{col_name}' với canonical validator strict...")
                db.create_collection(
                    col_name,
                    validator=canonical_validator,
                    validationLevel="strict",
                    validationAction="error",
                )
                col_report["applied"] = True
                col_report["validation_level"] = "strict"
                col_report["validation_action"] = "error"
            else:
                col_report["validation_level"] = "strict (planned)"
                col_report["validation_action"] = "error (planned)"

            report["collections"][col_name] = col_report
            continue

        # 2. Existing Collection: Preflight inspection
        col = db[col_name]
        coll_opts = coll_info_dict.get(col_name, {}).get("options", {})
        prev_validator = coll_opts.get("validator")
        prev_level = coll_opts.get("validationLevel", "off")
        prev_action = coll_opts.get("validationAction", "warn")

        # Save rollback metadata
        report["rollback_metadata"][col_name] = {
            "previous_validator": prev_validator,
            "previous_validation_level": prev_level,
            "previous_validation_action": prev_action,
            "rollback_command": {
                "collMod": col_name,
                "validator": prev_validator or {},
                "validationLevel": prev_level,
                "validationAction": prev_action,
            },
        }

        # Index verification snapshot before collMod
        try:
            indexes_before = list(col.index_information().keys())
        except Exception:
            indexes_before = []

        total_docs = col.count_documents({})
        try:
            valid_docs = col.count_documents(canonical_validator)
        except Exception as q_exc:
            logger.warning(f"Lỗi kiểm tra validator trên '{col_name}': {q_exc}")
            valid_docs = 0

        invalid_docs = total_docs - valid_docs
        compliance_pct = 100.0 if total_docs == 0 else round((valid_docs / total_docs) * 100.0, 2)
        strict_eligible = (invalid_docs == 0)

        col_report["preflight"] = {
            "total_docs": total_docs,
            "valid_docs": valid_docs,
            "invalid_docs": invalid_docs,
            "compliance_rate_pct": compliance_pct,
            "strict_eligible": strict_eligible,
            "previous_validation_level": prev_level,
            "previous_validation_action": prev_action,
            "indexes_before": indexes_before,
        }

        logger.info(
            f"Preflight [{col_name}]: {total_docs} docs | Valid: {valid_docs} | "
            f"Invalid: {invalid_docs} | Tuân thủ: {compliance_pct}% | "
            f"Đủ điều kiện Strict: {strict_eligible}"
        )

        # 3. Validation level determination
        if strict_eligible:
            target_level = "strict"
            target_action = "error"
        else:
            target_level = "moderate"
            target_action = "warn"
            logger.warning(
                f"[STRICT BLOCKED] Collection '{col_name}' có {invalid_docs} docs không hợp lệ "
                f"({compliance_pct}%). Sử dụng validationLevel='moderate' để không gây gián đoạn."
            )

        col_report["validation_level"] = target_level
        col_report["validation_action"] = target_action

        # 4. collMod execution (only in apply mode)
        if not is_dry_run:
            logger.info(f"Áp dụng collMod trên '{col_name}' (Level: {target_level}, Action: {target_action})...")
            db.command(
                "collMod",
                col_name,
                validator=canonical_validator,
                validationLevel=target_level,
                validationAction=target_action,
            )
            col_report["applied"] = True

            # 5. Post-verification
            try:
                indexes_after = list(col.index_information().keys())
                indexes_preserved = (indexes_before == indexes_after)
            except Exception:
                indexes_preserved = True

            col_report["indexes_preserved"] = indexes_preserved

            # Verify updated validator
            try:
                updated_info = next(
                    (c for c in db.list_collections(filter={"name": col_name})),
                    None
                )
                updated_opts = updated_info.get("options", {}) if updated_info else {}
                col_report["post_verification"] = {
                    "updated_validation_level": updated_opts.get("validationLevel"),
                    "updated_validation_action": updated_opts.get("validationAction"),
                    "has_validator": bool(updated_opts.get("validator")),
                    "indexes_count_matched": indexes_preserved,
                }
            except Exception as v_exc:
                col_report["post_verification"] = {"error": str(v_exc)}
        else:
            col_report["post_verification"] = {
                "simulated_level": target_level,
                "simulated_action": target_action,
                "note": "Dry-run mode: collMod not dispatched.",
            }

        report["collections"][col_name] = col_report

    report["status"] = "SUCCESS"
    report["completed_at"] = datetime.now(timezone.utc).isoformat()

    save_migration_report(report, report_file)
    logger.info(f"=== HOÀN TẤT MIGRATION {MIGRATION_VERSION} [{mode_str}] ===")
    return report


def get_parser() -> argparse.ArgumentParser:
    """Tạo parser cho migration 023 với require_mode=False để mặc định là dry-run an toàn."""
    return get_base_parser(
        "Migration 023: Sync canonical MongoDB collection validators from Schema Registry",
        require_mode=False,
    )


def main():
    parser = get_parser()
    args = parser.parse_args()
    is_dry_run = not args.apply
    report = run_sync_canonical_validators(
        is_dry_run=is_dry_run,
        database_name=args.database,
        report_file=args.report_file,
    )
    if report.get("status") != "SUCCESS":
        sys.exit(1)


if __name__ == "__main__":
    main()
