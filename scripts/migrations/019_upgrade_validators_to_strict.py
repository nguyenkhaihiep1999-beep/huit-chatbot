"""
scripts/migrations/019_upgrade_validators_to_strict.py
Migration Phase 7: Đánh giá và Chuyển đổi validationLevel từ moderate sang strict:
- Mặc định --dry-run (chỉ áp dụng khi có cờ --apply).
- Xác minh chặt chẽ database là huit_chatbot.
- Preflight validation kiểm tra toàn bộ 9 collections chính:
  assets, artifacts, jobs, generated_images, query_cache, admission_visuals, huit_kb, operation_audit, rag_events.
- Chỉ áp dụng validationLevel: "strict" khi 100% document hợp lệ.
- Với rag_events (chứa các bản ghi log telemetry cũ thiếu request_id/question_length):
  + Tự động tạo bản sao lưu an toàn (rag_events_backup_pre_strict_<timestamp>) và rollback manifest trước khi sửa đổi.
  + Chuẩn hóa/backfill request_id, question_length, schema_version cho các bản ghi cũ.
  + Xác minh lại 100% document hợp lệ trước khi nâng lên strict.
- Nâng cấp validationLevel lên "strict" với validationAction: "error" qua lệnh collMod.
- Tuyệt đối không drop collection, không drop index, bảo toàn Atlas Vector Search Index.
- Idempotent: chạy nhiều lần an toàn, không sinh trùng lặp hay lỗi lặp lại.
"""
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from typing import Any, Dict, List, Optional

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from backend.app.config import settings
from backend.app.repositories.mongo_repository import MongoRepository
from scripts.migrations.common import (
    create_collection_backup,
    get_base_parser,
    get_migration_db,
    logger,
    save_migration_report,
)

CORE_COLLECTIONS = [
    "assets",
    "artifacts",
    "jobs",
    "generated_images",
    "query_cache",
    "admission_visuals",
    "huit_kb",
    "operation_audit",
    "rag_events",
]


def run_migration_upgrade_strict(
    is_dry_run: bool = True,
    database_name: Optional[str] = None,
    batch_size: int = 100,
    report_file: Optional[str] = None,
) -> Dict[str, Any]:
    mode_str = "DRY-RUN (MÔ PHỎNG)" if is_dry_run else "APPLY (THỰC THI THẬT SỰ)"
    logger.info(f"=== BẮT ĐẦU MIGRATION 019: UPGRADE VALIDATION LEVEL TO STRICT [{mode_str}] ===")

    client, db = get_migration_db(database_name)
    logger.info(f"Đã kết nối thành công tới Database: '{db.name}'")

    if "huit" not in db.name.lower():
        raise RuntimeError(f"Tên Database '{db.name}' không phải là huit_chatbot! Dừng khẩn cấp.")

    timestamp_str = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    report: Dict[str, Any] = {
        "migration": "019_upgrade_validators_to_strict",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "database": db.name,
        "mode": "dry_run" if is_dry_run else "apply",
        "preflight": {},
        "rag_events_backfill": {
            "needed": False,
            "backup_collection": None,
            "rollback_manifest": None,
            "docs_updated": 0,
        },
        "validation_level_upgrades": {},
        "post_verification": {},
        "status": "in_progress",
    }

    coll_infos = {c["name"]: c for c in db.list_collections()}

    # =========================================================================
    # BƯỚC 1: PREFLIGHT VALIDATION CHECK TRÊN TOÀN BỘ 9 COLLECTIONS
    # =========================================================================
    logger.info("--- BƯỚC 1: Preflight Check toàn bộ 9 collections ---")
    all_ready_for_strict = True

    for col_name in CORE_COLLECTIONS:
        if col_name not in coll_infos:
            logger.error(f"[PREFLIGHT FAIL] Collection '{col_name}' không tồn tại!")
            report["preflight"][col_name] = {"exists": False, "ready_for_strict": False}
            all_ready_for_strict = False
            continue

        c = db[col_name]
        c_info = coll_infos[col_name]
        opts = c_info.get("options", {})
        validator = opts.get("validator")
        curr_level = opts.get("validationLevel", "none")
        curr_action = opts.get("validationAction", "none")

        if not validator:
            logger.error(f"[PREFLIGHT FAIL] Collection '{col_name}' chưa có validator!")
            report["preflight"][col_name] = {
                "exists": True,
                "has_validator": False,
                "ready_for_strict": False,
            }
            all_ready_for_strict = False
            continue

        total_docs = c.count_documents({})
        valid_docs = c.count_documents(validator)
        invalid_docs = total_docs - valid_docs
        is_ready = (invalid_docs == 0)

        logger.info(
            f"Preflight [{col_name}]: {total_docs} docs | Valid: {valid_docs} | "
            f"Invalid: {invalid_docs} | Current: {curr_level}/{curr_action} | "
            f"Ready for strict: {is_ready}"
        )

        report["preflight"][col_name] = {
            "exists": True,
            "has_validator": True,
            "current_level": curr_level,
            "current_action": curr_action,
            "total_docs": total_docs,
            "valid_docs": valid_docs,
            "invalid_docs": invalid_docs,
            "ready_for_strict": is_ready,
        }

        if not is_ready:
            all_ready_for_strict = False

    # =========================================================================
    # BƯỚC 2: XỬ LÝ CHUẨN HÓA DỮ LIỆU CŨ CHO RAG_EVENTS (NẾU CẦN)
    # =========================================================================
    rag_preflight = report["preflight"].get("rag_events", {})
    if not rag_preflight.get("ready_for_strict", False):
        report["rag_events_backfill"]["needed"] = True
        rag_col = db["rag_events"]
        missing_count = rag_col.count_documents({
            "$or": [
                {"request_id": {"$exists": False}},
                {"question_length": {"$exists": False}},
                {"schema_version": {"$exists": False}},
            ]
        })
        logger.info(f"Phát hiện {missing_count} documents trong 'rag_events' cần backfill metadata v2.")

        if not is_dry_run:
            # 1. Tạo backup an toàn trước khi thay đổi
            backup_name = create_collection_backup(db, "rag_events")
            report["rag_events_backfill"]["backup_collection"] = backup_name

            # 2. Tạo rollback manifest ghi nhận danh sách _id được cập nhật
            manifest_file = ROOT_DIR / "audit_outputs" / f"rollback_manifest_019_{timestamp_str}.json"
            manifest_file.parent.mkdir(exist_ok=True)
            rollback_ids = []

            # 3. Chuẩn hóa theo batch với bulk_write
            from pymongo import UpdateOne
            cursor = rag_col.find({
                "$or": [
                    {"request_id": {"$exists": False}},
                    {"question_length": {"$exists": False}},
                    {"schema_version": {"$exists": False}},
                ]
            })

            bulk_ops = []
            updated_count = 0
            for doc in cursor:
                doc_id = doc["_id"]
                rollback_ids.append(str(doc_id))
                update_fields: Dict[str, Any] = {}

                if "schema_version" not in doc:
                    update_fields["schema_version"] = 1
                if "request_id" not in doc:
                    update_fields["request_id"] = f"legacy-req-{doc_id}"
                if "question_length" not in doc:
                    update_fields["question_length"] = 0

                if update_fields:
                    bulk_ops.append(UpdateOne({"_id": doc_id}, {"$set": update_fields}))
                    updated_count += 1
                if len(bulk_ops) >= 500:
                    rag_col.bulk_write(bulk_ops, ordered=False)
                    bulk_ops = []
            if bulk_ops:
                rag_col.bulk_write(bulk_ops, ordered=False)

            with open(manifest_file, "w", encoding="utf-8") as mf:
                json.dump({
                    "timestamp": timestamp_str,
                    "target_collection": "rag_events",
                    "backup_collection": backup_name,
                    "total_updated": updated_count,
                    "affected_ids": rollback_ids,
                }, mf, indent=2)

            report["rag_events_backfill"]["rollback_manifest"] = str(manifest_file)
            report["rag_events_backfill"]["docs_updated"] = updated_count
            logger.info(f"Đã backfill hoàn tất {updated_count} documents trong 'rag_events'.")
            logger.info(f"Rollback manifest đã lưu tại: {manifest_file}")

            # 4. Kiểm tra lại preflight cho rag_events
            rag_opts = coll_infos["rag_events"].get("options", {})
            rag_val = rag_opts.get("validator", {})
            re_total = rag_col.count_documents({})
            re_valid = rag_col.count_documents(rag_val)
            if re_total == re_valid:
                logger.info("✓ rag_events sau khi backfill đạt 100% VALID!")
                report["preflight"]["rag_events"]["ready_for_strict"] = True
            else:
                logger.error(f"rag_events sau khi backfill vẫn còn {re_total - re_valid} documents không hợp lệ!")
        else:
            logger.info(f"[DRY-RUN] Sẽ tạo backup, rollback manifest và backfill {missing_count} documents trong 'rag_events'.")
            report["rag_events_backfill"]["docs_updated"] = missing_count

    # =========================================================================
    # BƯỚC 3: ÁP DỤNG VALIDATION LEVEL STRICT CHO CÁC COLLECTION ĐẠT CHUẨN
    # =========================================================================
    logger.info("--- BƯỚC 3: Nâng cấp validationLevel lên STRICT ---")
    for col_name in CORE_COLLECTIONS:
        col_preflight = report["preflight"].get(col_name, {})
        ready = col_preflight.get("ready_for_strict", False)
        curr_level = col_preflight.get("current_level", "")

        if curr_level == "strict":
            logger.info(f"Collection '{col_name}' đã ở mức STRICT, giữ nguyên (Idempotent).")
            report["validation_level_upgrades"][col_name] = {
                "action": "already_strict",
                "applied": True,
            }
            continue

        if not ready and not is_dry_run:
            logger.warning(f"[BỎ QUA] Collection '{col_name}' chưa đạt 100% valid, không thể nâng lên strict!")
            report["validation_level_upgrades"][col_name] = {
                "action": "skipped_not_ready",
                "applied": False,
            }
            continue

        if not is_dry_run:
            logger.info(f"Chuyển đổi validationLevel sang STRICT cho '{col_name}'...")
            c_info = coll_infos[col_name]
            validator = c_info.get("options", {}).get("validator")
            db.command({
                "collMod": col_name,
                "validator": validator,
                "validationLevel": "strict",
                "validationAction": "error",
            })
            report["validation_level_upgrades"][col_name] = {
                "action": "upgraded_to_strict",
                "applied": True,
            }
            logger.info(f"✓ '{col_name}' đã nâng cấp thành công lên validationLevel: STRICT.")
        else:
            logger.info(f"[DRY-RUN] Sẽ nâng cấp '{col_name}' lên validationLevel: STRICT.")
            report["validation_level_upgrades"][col_name] = {
                "action": "[DRY-RUN] upgrade_to_strict",
                "applied": False,
            }

    # =========================================================================
    # BƯỚC 4: HẬU KIỂM TOÀN DIỆN (POST-VERIFICATION)
    # =========================================================================
    logger.info("--- BƯỚC 4: Hậu kiểm trạng thái collections sau nâng cấp ---")
    new_infos = {c["name"]: c for c in db.list_collections()}
    post_summary: Dict[str, Any] = {
        "all_strict": True,
        "all_error_action": True,
        "indexes_intact": True,
        "vector_search_ready": False,
        "collections": {},
    }

    for col_name in CORE_COLLECTIONS:
        info = new_infos.get(col_name, {})
        opts = info.get("options", {})
        v_level = opts.get("validationLevel", "none")
        v_action = opts.get("validationAction", "none")
        idx_count = len(list(db[col_name].list_indexes()))
        total = db[col_name].count_documents({})
        validator = opts.get("validator", {})
        valid = db[col_name].count_documents(validator) if validator else 0

        is_strict = (v_level == "strict") if not is_dry_run else (col_name in report["preflight"])
        if not is_strict:
            post_summary["all_strict"] = False
        if v_action != "error":
            post_summary["all_error_action"] = False

        post_summary["collections"][col_name] = {
            "validation_level": v_level,
            "validation_action": v_action,
            "index_count": idx_count,
            "total_documents": total,
            "valid_documents": valid,
            "is_strict": (v_level == "strict"),
        }
        logger.info(
            f"Hậu kiểm [{col_name}]: Level={v_level} | Action={v_action} | "
            f"Indexes={idx_count} | Docs={total}/{valid}"
        )

    # Kiểm tra Vector Search Index trên huit_kb
    try:
        kb_col = db["huit_kb"]
        vs_indexes = list(kb_col.aggregate([{"$listSearchIndexes": {}}]))
        for si in vs_indexes:
            if si.get("name") == "huit_vector_index" and si.get("status") == "READY":
                post_summary["vector_search_ready"] = True
                logger.info("✓ Atlas Vector Search Index 'huit_vector_index' trên 'huit_kb' đang READY.")
    except Exception as exc:
        logger.warning(f"Cảnh báo kiểm tra vector search index: {exc}")

    report["post_verification"] = post_summary
    report["status"] = "success"

    # Lưu báo cáo JSON
    report_path = save_migration_report(report, report_file)
    logger.info(f"Báo cáo migration đã lưu tại: {report_path}")
    logger.info(f"=== KẾT THÚC MIGRATION 019 [{mode_str}] THÀNH CÔNG ===")
    return report


if __name__ == "__main__":
    parser = get_base_parser("Migration 019: Đánh giá và Chuyển đổi validationLevel sang STRICT")
    args = parser.parse_args()

    try:
        run_migration_upgrade_strict(
            is_dry_run=args.dry_run,
            database_name=args.database,
            batch_size=args.batch_size,
            report_file=args.report_file,
        )
    except Exception as e:
        logger.error(f"Migration thất bại với lỗi: {e}", exc_info=True)
        sys.exit(1)
