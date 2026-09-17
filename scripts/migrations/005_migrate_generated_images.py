"""
005_migrate_generated_images.py
Chuẩn hóa metadata collection `generated_images`:
- Phân loại rõ backend="flux" (raster) và backend="svg" (vector).
- Bổ sung `schema_version = 1`.
- Bổ sung `generation_key` nếu chưa có.
- Đảm bảo `created_at` là BSON Date UTC.
- Kiểm tra trùng lặp trên `content_hash` / `generation_key`.
- Backup tự động sang `generated_images_backup_<timestamp>`.
"""
from pathlib import Path
import sys
ROOT_DIR = Path(__file__).resolve().parent.parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from datetime import datetime, timezone
from typing import Any, Dict

from scripts.migrations.common import (

    get_base_parser,
    get_migration_db,
    create_collection_backup,
    save_migration_report,
    logger,
)
from backend.app.models.mongo_models import MongoGeneratedImageRecord, ensure_utc_datetime


import hashlib

def migrate_generated_images(db, args) -> Dict[str, Any]:
    col = db["generated_images"]
    total_docs = col.count_documents({})
    logger.info(f"Bắt đầu chuẩn hóa {total_docs} documents trong 'generated_images'...")

    stats = {
        "total_documents": total_docs,
        "valid": 0,
        "updated": 0,
        "errors": 0,
        "duplicates_resolved": 0,
        "backup": None
    }

    if args.apply:
        stats["backup"] = create_collection_backup(db, "generated_images")

    seen_hashes = {}
    for d in col.find({"content_hash": {"$exists": True, "$ne": None}}, {"_id": 1, "content_hash": 1}):
        seen_hashes[d["content_hash"]] = d["_id"]

    cursor = col.find({})
    for doc in cursor:
        doc_id = doc["_id"]
        try:
            model = MongoGeneratedImageRecord.from_legacy(doc)
            c_hash = model.content_hash
            is_dup = False

            if c_hash in seen_hashes and seen_hashes[c_hash] != doc_id:
                is_dup = True
                canonical_hash = c_hash
                c_hash = hashlib.sha256(f"archived_{doc_id}_{c_hash}".encode("utf-8")).hexdigest()
            else:
                seen_hashes[c_hash] = doc_id

            updates = {
                "schema_version": 1,
                "backend": model.backend,
                "image_id": model.image_id,
                "content_hash": c_hash,
                "generation_key": c_hash if is_dup else model.generation_key,
                "created_at": model.created_at
            }
            if is_dup:
                updates["is_archived_duplicate"] = True
                updates["canonical_content_hash"] = canonical_hash

            if args.apply:
                col.update_one({"_id": doc_id}, {"$set": updates})

            stats["updated"] += 1
            stats["valid"] += 1
            if is_dup:
                stats["duplicates_resolved"] += 1
        except Exception as e:
            logger.error(f"Lỗi validate image {doc_id}: {e}")
            stats["errors"] += 1

    logger.info(f"Hoàn thành migrate generated_images: {stats['updated']} docs cập nhật, {stats['duplicates_resolved']} trùng lặp xử lý, {stats['errors']} lỗi.")
    return stats


def run_migration(args):
    client, db = get_migration_db(args.database)
    logger.info(f"=== Bắt đầu 005_migrate_generated_images (Mode: {'DRY-RUN' if args.dry_run else 'APPLY'}) ===")

    stats = migrate_generated_images(db, args)
    report = {
        "script": "005_migrate_generated_images",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "database": args.database,
        "mode": "dry-run" if args.dry_run else "apply",
        "stats": stats
    }
    save_migration_report(report, args.report_file)
    return report


if __name__ == "__main__":
    parser = get_base_parser("Chuẩn hóa schema collection generated_images")
    args = parser.parse_args()
    run_migration(args)
