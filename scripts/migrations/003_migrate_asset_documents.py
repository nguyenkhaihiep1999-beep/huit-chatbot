"""
003_migrate_asset_documents.py
Di chuyển và chuẩn hóa collection `assets`:
- Giải quyết triệt để dữ liệu trùng lặp theo `content_hash` trước khi tạo unique index.
- Thêm trường `schema_version = 1`.
- Đảm bảo các trường ngày giờ (`created_at`, `last_accessed_at`) là BSON Date UTC.
- Validate từng document theo Pydantic model `MongoAssetRecord`.
- Tự động backup sang `assets_backup_<timestamp>` trước khi sửa đổi.
- Hỗ trợ đầy đủ --dry-run và --apply.
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
from backend.app.models.mongo_models import MongoAssetRecord, ensure_utc_datetime


def resolve_duplicate_content_hashes(db, args) -> Dict[str, Any]:
    """Tìm và xử lý các bản ghi trùng content_hash trong collection assets."""
    col = db["assets"]
    pipeline = [
        {"$match": {"content_hash": {"$exists": True, "$ne": None, "$ne": ""}}},
        {"$group": {"_id": "$content_hash", "count": {"$sum": 1}, "docs": {"$push": {"_id": "$_id", "created_at": "$created_at"}}}},
        {"$match": {"count": {"$gt": 1}}}
    ]
    duplicate_groups = list(col.aggregate(pipeline))
    logger.info(f"Phát hiện {len(duplicate_groups)} nhóm content_hash bị trùng lặp trong 'assets'.")

    dedup_report = {
        "groups_found": len(duplicate_groups),
        "total_duplicates_resolved": 0,
        "details": []
    }

    for grp in duplicate_groups:
        c_hash = grp["_id"]
        doc_list = grp["docs"]
        # Sắp xếp để giữ lại document mới nhất
        doc_list_sorted = sorted(doc_list, key=lambda x: str(x.get("created_at", "")), reverse=True)
        primary = doc_list_sorted[0]
        duplicates_to_archive = doc_list_sorted[1:]

        logger.info(f"Nhóm hash {c_hash[:10]}...: Giữ lại bản ghi chính '{primary['_id']}', xử lý {len(duplicates_to_archive)} bản ghi phụ.")

        for dup in duplicates_to_archive:
            dup_id = dup["_id"]
            if args.apply:
                # Đổi content_hash của bản ghi phụ thành dạng archived để không vi phạm unique index
                archived_hash = f"archived_{dup_id}_{c_hash[:32]}"
                col.update_one({"_id": dup_id}, {"$set": {"content_hash": archived_hash, "is_archived_duplicate": True}})
            dedup_report["total_duplicates_resolved"] += 1
            dedup_report["details"].append({
                "primary_id": primary["_id"],
                "archived_id": dup_id,
                "original_hash": c_hash[:16] + "..."
            })

    return dedup_report


def migrate_asset_records(db, args) -> Dict[str, Any]:
    col = db["assets"]
    total_docs = col.count_documents({})
    logger.info(f"Bắt đầu chuẩn hóa cấu trúc {total_docs} documents trong 'assets'...")

    stats = {
        "total_documents": total_docs,
        "valid": 0,
        "updated": 0,
        "errors": 0,
        "backup": None
    }

    if args.apply:
        stats["backup"] = create_collection_backup(db, "assets")

    # 1. Xử lý trùng lặp trước
    dedup_results = resolve_duplicate_content_hashes(db, args)
    stats["deduplication"] = dedup_results

    # 2. Chuẩn hóa từng document theo MongoAssetRecord
    cursor = col.find({})
    for doc in cursor:
        doc_id = doc["_id"]
        try:
            # Tạo model chuẩn
            model = MongoAssetRecord.from_legacy(doc)
            updates = {
                "schema_version": 1,
                "created_at": model.created_at,
                "last_accessed_at": model.last_accessed_at
            }
            if args.apply:
                col.update_one({"_id": doc_id}, {"$set": updates})
            stats["updated"] += 1
            stats["valid"] += 1
        except Exception as e:
            logger.error(f"Lỗi validate asset {doc_id}: {e}")
            stats["errors"] += 1

    logger.info(f"Hoàn thành migrate assets: {stats['updated']} docs chuẩn hóa, {stats['errors']} lỗi.")
    return stats


def run_migration(args):
    client, db = get_migration_db(args.database)
    logger.info(f"=== Bắt đầu 003_migrate_asset_documents (Mode: {'DRY-RUN' if args.dry_run else 'APPLY'}) ===")

    stats = migrate_asset_records(db, args)
    report = {
        "script": "003_migrate_asset_documents",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "database": args.database,
        "mode": "dry-run" if args.dry_run else "apply",
        "stats": stats
    }
    save_migration_report(report, args.report_file)
    return report


if __name__ == "__main__":
    parser = get_base_parser("Deduplication và chuẩn hóa schema collection assets")
    args = parser.parse_args()
    run_migration(args)
