"""
014_fix_image_dedup_index.py
Migration điều chỉnh Index Deduplication cho collection `generated_images`:
- Gỡ bỏ unique index toàn cục `content_hash_1` trên `generated_images` (vốn ngăn cản 2 người dùng khác nhau sinh cùng một nội dung).
- Đảm bảo mỗi bản ghi `generated_images` có trường `request_fingerprint` đồng bộ từ `canonical_content_hash`.
- Khởi tạo partial compound index `[('owner_id', 1), ('request_fingerprint', 1)]` (unique) để chống trùng cho cùng một user.
- Hỗ trợ đầy đủ --dry-run (mặc định) và --apply (tự động sao lưu collection trước khi thay đổi).
"""
from pathlib import Path
import sys
ROOT_DIR = Path(__file__).resolve().parent.parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from datetime import datetime, timezone
from typing import Any, Dict, List
from pymongo import UpdateOne

from scripts.migrations.common import (
    get_base_parser,
    get_migration_db,
    create_collection_backup,
    save_migration_report,
    logger,
)


def fix_image_dedup_indexes(db, args) -> Dict[str, Any]:
    images_col = db["generated_images"]
    now_dt = datetime.now(timezone.utc)

    existing_indexes = images_col.index_information()
    has_global_content_hash_unique = False
    global_unique_index_names = [
        name for name, spec in existing_indexes.items()
        if spec.get("key") == [("content_hash", 1)] and spec.get("unique", False)
    ]
    has_global_content_hash_unique = bool(global_unique_index_names)

    total_images = images_col.count_documents({})
    images_needing_fingerprint = images_col.count_documents({
        "$or": [
            {"request_fingerprint": {"$exists": False}},
            {"request_fingerprint": None}
        ]
    })
    duplicate_groups_preflight = list(images_col.aggregate([
        {"$set": {"_migration_fp": {"$ifNull": [
            "$request_fingerprint",
            {"$ifNull": ["$canonical_content_hash", "$content_hash"]},
        ]}}},
        {"$match": {
            "owner_id": {"$type": "string"},
            "_migration_fp": {"$type": "string"},
        }},
        {"$group": {
            "_id": {"owner_id": "$owner_id", "request_fingerprint": "$_migration_fp"},
            "count": {"$sum": 1},
        }},
        {"$match": {"count": {"$gt": 1}}},
        {"$limit": 20},
    ]))

    report = {
        "script": "014_fix_image_dedup_index",
        "started_at": now_dt.isoformat(),
        "mode": "apply" if args.apply else "dry-run",
        "total_images": total_images,
        "has_global_content_hash_unique": has_global_content_hash_unique,
        "images_needing_fingerprint": images_needing_fingerprint,
        "duplicate_owner_fingerprint_groups": len(duplicate_groups_preflight),
        "preflight_passed": len(duplicate_groups_preflight) == 0,
        "dropped_indexes": [],
        "created_indexes": [],
        "fingerprints_updated": 0,
        "errors": 0,
        "backups": {}
    }

    logger.info(f"Tổng số images: {total_images}. Index 'content_hash_1' unique hiện tại: {has_global_content_hash_unique}.")
    logger.info(f"Số bản ghi cần cập nhật 'request_fingerprint': {images_needing_fingerprint}.")

    if args.apply:
        if duplicate_groups_preflight:
            report["errors"] += 1
            report["duplicate_samples"] = [
                {"owner_id": row["_id"]["owner_id"], "count": row["count"]}
                for row in duplicate_groups_preflight
            ]
            logger.error("Preflight phát hiện duplicate owner/request_fingerprint; dừng trước mọi thay đổi.")
            report["completed_at"] = datetime.now(timezone.utc).isoformat()
            return report
        logger.info("Chế độ APPLY: Tiến hành sao lưu và cập nhật...")
        report["backups"]["generated_images"] = create_collection_backup(db, "generated_images")

        # 1. Điền request_fingerprint cho các bản ghi cũ từ canonical_content_hash hoặc content_hash
        bulk_ops = []
        for doc in images_col.find({"$or": [{"request_fingerprint": {"$exists": False}}, {"request_fingerprint": None}]}):
            fp = doc.get("canonical_content_hash") or doc.get("content_hash") or doc.get("generation_key") or str(doc["_id"])
            bulk_ops.append(UpdateOne({"_id": doc["_id"]}, {"$set": {"request_fingerprint": fp}}))

        if bulk_ops:
            res = images_col.bulk_write(bulk_ops, ordered=False)
            report["fingerprints_updated"] = res.modified_count
            logger.info(f"Đã cập nhật request_fingerprint cho {res.modified_count} bản ghi.")

        # 2. Fail closed nếu dữ liệu hiện tại vi phạm compound unique dự kiến.
        duplicate_groups = list(images_col.aggregate([
            {"$match": {
                "owner_id": {"$type": "string"},
                "request_fingerprint": {"$type": "string"},
            }},
            {"$group": {
                "_id": {"owner_id": "$owner_id", "request_fingerprint": "$request_fingerprint"},
                "count": {"$sum": 1},
            }},
            {"$match": {"count": {"$gt": 1}}},
            {"$limit": 20},
        ]))
        report["duplicate_owner_fingerprint_groups"] = len(duplicate_groups)
        if duplicate_groups:
            report["errors"] += 1
            report["duplicate_samples"] = [
                {"owner_id": row["_id"]["owner_id"], "count": row["count"]}
                for row in duplicate_groups
            ]
            logger.error("Phát hiện duplicate owner/request_fingerprint; dừng trước khi đổi index.")
            report["completed_at"] = datetime.now(timezone.utc).isoformat()
            return report

        # 3. Tạo compound partial unique TRƯỚC; index cũ vẫn bảo vệ nếu bước này thất bại.
        new_index_name = "owner_request_fingerprint_unique_v1"
        refreshed_indexes = images_col.index_information()
        matching_compound = next((
            (name, spec) for name, spec in refreshed_indexes.items()
            if spec.get("key") == [("owner_id", 1), ("request_fingerprint", 1)]
        ), None)
        if matching_compound is None:
            try:
                images_col.create_index(
                    [("owner_id", 1), ("request_fingerprint", 1)],
                    name=new_index_name,
                    unique=True,
                    partialFilterExpression={
                        "owner_id": {"$type": "string"},
                        "request_fingerprint": {"$type": "string"},
                    },
                )
                report["created_indexes"].append(new_index_name)
            except Exception as e:
                logger.error(f"Lỗi khi tạo index {new_index_name}: {e}")
                report["errors"] += 1
                report["completed_at"] = datetime.now(timezone.utc).isoformat()
                return report
        else:
            _, compound_spec = matching_compound
            expected_partial = {
                "owner_id": {"$type": "string"},
                "request_fingerprint": {"$type": "string"},
            }
            if not compound_spec.get("unique") or compound_spec.get("partialFilterExpression") != expected_partial:
                report["errors"] += 1
                logger.error("Compound index đã tồn tại nhưng sai options; dừng để review thủ công.")
                report["completed_at"] = datetime.now(timezone.utc).isoformat()
                return report

        # 4. Chỉ sau khi compound unique thành công mới bỏ global unique và tạo lookup non-unique.
        for index_name in global_unique_index_names:
            try:
                images_col.drop_index(index_name)
                report["dropped_indexes"].append(index_name)
            except Exception as e:
                logger.error(f"Lỗi khi drop index {index_name}: {e}")
                report["errors"] += 1

        lookup_exists = any(
            spec.get("key") == [("content_hash", 1)] and not spec.get("unique", False)
            for spec in images_col.index_information().values()
        )
        if not lookup_exists:
            images_col.create_index(
                [("content_hash", 1)],
                name="content_hash_lookup_v1",
                sparse=True,
            )
            report["created_indexes"].append("content_hash_lookup_v1")

    report["completed_at"] = datetime.now(timezone.utc).isoformat()
    return report


def main():
    parser = get_base_parser("Migration 014: Điều chỉnh index dedup cho generated_images")
    args = parser.parse_args()

    client, db = get_migration_db(args.database)
    try:
        report = fix_image_dedup_indexes(db, args)
        save_migration_report(report, args.report_file)
        logger.info(
            f"Hoàn thành Migration 014 ({report['mode']}): "
            f"Cần cập nhật fingerprint: {report['images_needing_fingerprint']}, "
            f"Dropped: {report['dropped_indexes']}, Created: {report['created_indexes']}, Lỗi: {report['errors']}."
        )
        if report["errors"] or not report["preflight_passed"]:
            raise SystemExit(2)
    finally:
        client.close()


if __name__ == "__main__":
    main()
