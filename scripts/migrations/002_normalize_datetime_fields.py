"""
002_normalize_datetime_fields.py
Chuẩn hóa các trường ngày giờ lưu dạng chuỗi ISO sang BSON Date (UTC):
- Mục tiêu: `jobs`, `assets`, `admission_visuals`, `huit_kb`.
- Chế độ --dry-run: Chỉ kiểm tra và đếm số document cần chuẩn hóa, không sửa đổi dữ liệu.
- Chế độ --apply: Tự động tạo backup collection, xử lý theo batch, chuyển đổi an toàn.
- Tính lũy đẳng (Idempotent): Bỏ qua các document đã có trường kiểu BSON Date.
"""
from pathlib import Path
import sys
ROOT_DIR = Path(__file__).resolve().parent.parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from datetime import datetime, timezone
from typing import Any, Dict, List

from scripts.migrations.common import (

    get_base_parser,
    get_migration_db,
    create_collection_backup,
    iterate_batches,
    save_migration_report,
    logger,
)
from backend.app.models.mongo_models import ensure_utc_datetime

TARGET_CONFIG = {
    "jobs": ["created_at", "updated_at"],
    "assets": ["created_at", "last_accessed_at"],
    "admission_visuals": ["created_at"],
    "huit_kb": ["retrieved_at"]
}


def normalize_collection_dates(db, col_name: str, date_fields: List[str], args) -> Dict[str, Any]:
    col = db[col_name]
    total_docs = col.count_documents({})
    logger.info(f"--- Bắt đầu xử lý collection '{col_name}' ({total_docs} docs) ---")

    # Tìm các document có ít nhất một trường là string
    string_query = {
        "$or": [{field: {"$type": "string"}} for field in date_fields]
    }
    docs_to_fix = col.count_documents(string_query)
    logger.info(f"Collection '{col_name}': Phát hiện {docs_to_fix} documents có trường ngày dạng string.")

    stats = {
        "collection": col_name,
        "total_documents": total_docs,
        "string_date_documents": docs_to_fix,
        "converted": 0,
        "skipped": total_docs - docs_to_fix,
        "errors": 0,
        "backup": None
    }

    if docs_to_fix == 0:
        logger.info(f"Collection '{col_name}' đã chuẩn hóa 100%, bỏ qua.")
        return stats

    if args.apply:
        stats["backup"] = create_collection_backup(db, col_name)

    date_proj = {"_id": 1, **{f: 1 for f in date_fields}}
    batch_gen = iterate_batches(col, string_query, batch_size=args.batch_size, resume_from=args.resume_from, projection=date_proj)

    for batch in batch_gen:
        for doc in batch:
            doc_id = doc["_id"]
            updates = {}
            for f in date_fields:
                val = doc.get(f)
                if isinstance(val, str):
                    try:
                        dt = ensure_utc_datetime(val)
                        updates[f] = dt
                    except Exception as e:
                        logger.warning(f"Lỗi parse ngày {f} cho doc {doc_id}: {e}")
                        stats["errors"] += 1

            if updates:
                if args.apply:
                    col.update_one({"_id": doc_id}, {"$set": updates})
                stats["converted"] += 1

    logger.info(f"Hoàn thành '{col_name}': {stats['converted']} docs đã chuyển đổi (Chế độ: {'DRY-RUN' if args.dry_run else 'APPLY'}).")
    return stats


def run_migration(args):
    client, db = get_migration_db(args.database)
    logger.info(f"=== Bắt đầu 002_normalize_datetime_fields (Mode: {'DRY-RUN' if args.dry_run else 'APPLY'}) ===")

    report = {
        "script": "002_normalize_datetime_fields",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "database": args.database,
        "mode": "dry-run" if args.dry_run else "apply",
        "results": {}
    }

    for col_name, fields in TARGET_CONFIG.items():
        res = normalize_collection_dates(db, col_name, fields, args)
        report["results"][col_name] = res

    save_migration_report(report, args.report_file)
    return report


if __name__ == "__main__":
    parser = get_base_parser("Chuẩn hóa các trường ngày giờ sang BSON Date")
    args = parser.parse_args()
    run_migration(args)
