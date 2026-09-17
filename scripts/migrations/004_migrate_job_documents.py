"""
004_migrate_job_documents.py
Chuẩn hóa collection `jobs`:
- Thêm `schema_version = 1`.
- Chuyển đổi `created_at`, `updated_at` sang BSON Date UTC.
- Bổ sung `expires_at` (sau 7 ngày) phục vụ TTL index dọn dẹp job cũ tự động.
- Giới hạn mảng `events` tối đa 30 phần tử gần nhất.
- Hỗ trợ trạng thái `cancelled`.
- Validate từng document theo `MongoJobRecord`.
- Backup tự động sang `jobs_backup_<timestamp>`.
"""
from pathlib import Path
import sys
ROOT_DIR = Path(__file__).resolve().parent.parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from datetime import datetime, timedelta, timezone
from typing import Any, Dict

from scripts.migrations.common import (

    get_base_parser,
    get_migration_db,
    create_collection_backup,
    iterate_batches,
    save_migration_report,
    logger,
)
from backend.app.models.mongo_models import MongoJobRecord, ensure_utc_datetime


def migrate_jobs(db, args) -> Dict[str, Any]:
    col = db["jobs"]
    total_docs = col.count_documents({})
    logger.info(f"Bắt đầu chuẩn hóa {total_docs} documents trong collection 'jobs'...")

    stats = {
        "total_documents": total_docs,
        "valid": 0,
        "updated": 0,
        "errors": 0,
        "backup": None
    }

    if args.apply:
        stats["backup"] = create_collection_backup(db, "jobs")

    cursor = col.find({})
    for doc in cursor:
        doc_id = doc["_id"]
        try:
            model = MongoJobRecord.from_legacy(doc)
            # Tính expires_at nếu chưa có: 7 ngày sau updated_at
            exp_date = model.updated_at + timedelta(days=7)

            updates = {
                "schema_version": 1,
                "created_at": model.created_at,
                "updated_at": model.updated_at,
                "expires_at": exp_date,
                "events": [e.model_dump() for e in model.events]
            }

            if args.apply:
                col.update_one({"_id": doc_id}, {"$set": updates})

            stats["updated"] += 1
            stats["valid"] += 1
        except Exception as e:
            logger.error(f"Lỗi validate job {doc_id}: {e}")
            stats["errors"] += 1

    logger.info(f"Hoàn thành migrate jobs: {stats['updated']} docs cập nhật, {stats['errors']} lỗi.")
    return stats


def run_migration(args):
    client, db = get_migration_db(args.database)
    logger.info(f"=== Bắt đầu 004_migrate_job_documents (Mode: {'DRY-RUN' if args.dry_run else 'APPLY'}) ===")

    stats = migrate_jobs(db, args)
    report = {
        "script": "004_migrate_job_documents",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "database": args.database,
        "mode": "dry-run" if args.dry_run else "apply",
        "stats": stats
    }
    save_migration_report(report, args.report_file)
    return report


if __name__ == "__main__":
    parser = get_base_parser("Chuẩn hóa schema collection jobs và TTL expiration")
    args = parser.parse_args()
    run_migration(args)
