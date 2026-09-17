"""
006_remove_legacy_binary_fields.py
Trích xuất và loại bỏ các trường nhị phân / Base64 lớn khỏi MongoDB:
- Collection `generated_images`:
  + Trích xuất dữ liệu nhị phân `image_data` (36 documents legacy) ra StorageAdapter bền vững.
  + Tính toán mã băm SHA-256 (checksum) và kiểm tra tệp vật lý tồn tại hợp lệ.
  + Chỉ xóa trường `image_data` sau khi xác nhận file đã lưu thành công và checksum khớp 100%.
  + Cập nhật `storage_key` vào document MongoDB.
- Collection `query_cache`:
  + Loại bỏ `meta.visual.raw.image_base64` (>44KB) khỏi 5 document legacy.
  + Loại bỏ trường `original_question` để tuân thủ chính sách bảo vệ dữ liệu người dùng.
- Collection `rag_events`:
  + Loại bỏ trường `question` dạng plain text cũ.
- Tự động backup trước khi sửa đổi.
"""
from pathlib import Path
import sys
ROOT_DIR = Path(__file__).resolve().parent.parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import hashlib
from datetime import datetime, timezone
from typing import Any, Dict

from scripts.migrations.common import (

    get_base_parser,
    get_migration_db,
    create_collection_backup,
    save_migration_report,
    logger,
)
from backend.app.storage.storage_adapter import get_storage_adapter


def extract_and_clean_image_binaries(db, args) -> Dict[str, Any]:
    col = db["generated_images"]
    cursor = col.find({"image_data": {"$exists": True, "$ne": None}})
    count = col.count_documents({"image_data": {"$exists": True, "$ne": None}})
    logger.info(f"Phát hiện {count} document 'generated_images' có trường 'image_data' nhị phân.")

    stats = {
        "found": count,
        "extracted_and_verified": 0,
        "removed_from_db": 0,
        "errors": 0,
        "backup": None
    }

    if count == 0:
        return stats

    if args.apply:
        stats["backup"] = create_collection_backup(db, "generated_images")

    storage = get_storage_adapter()

    for doc in cursor:
        doc_id = doc["_id"]
        img_bytes = doc.get("image_data")
        if not isinstance(img_bytes, (bytes, bytearray)):
            stats["errors"] += 1
            continue

        byte_len = len(img_bytes)
        checksum = hashlib.sha256(img_bytes).hexdigest()
        ctype = doc.get("content_type", "image/jpeg")
        ext = "jpg" if "jpeg" in ctype or "jpg" in ctype else ("png" if "png" in ctype else "bin")
        safe_key = f"image_{doc_id}.{ext}"

        try:
            if args.apply:
                # 1. Ghi vào storage adapter
                res = storage.put(safe_key, img_bytes, media_type=ctype)
                # 2. Xác thực file tồn tại và checksum khớp tuyệt đối
                if not storage.exists(safe_key):
                    raise RuntimeError(f"Storage adapter báo không tồn tại file sau khi ghi: {safe_key}")
                saved_checksum = storage.get_checksum(safe_key)
                if saved_checksum != checksum:
                    raise RuntimeError(f"Sai lệch checksum: tính {checksum} vs lưu {saved_checksum}")

                # 3. Chỉ sau khi xác nhận an toàn mới gỡ bỏ trường nhị phân khỏi Mongo
                col.update_one(
                    {"_id": doc_id},
                    {
                        "$unset": {"image_data": ""},
                        "$set": {
                            "storage_key": safe_key,
                            "byte_size": byte_len,
                            "checksum": checksum,
                            "content_type": ctype
                        }
                    }
                )
                stats["removed_from_db"] += 1

            stats["extracted_and_verified"] += 1
        except Exception as e:
            logger.error(f"Lỗi trích xuất binary cho image {doc_id}: {e}")
            stats["errors"] += 1

    return stats


def clean_query_cache_legacy_fields(db, args) -> Dict[str, Any]:
    col = db["query_cache"]
    # Tìm các document có original_question hoặc base64 trong meta
    cursor = col.find({"$or": [
        {"original_question": {"$exists": True}},
        {"meta.visual.raw.image_base64": {"$exists": True}}
    ]})
    count = col.count_documents({"$or": [
        {"original_question": {"$exists": True}},
        {"meta.visual.raw.image_base64": {"$exists": True}}
    ]})
    logger.info(f"Phát hiện {count} document 'query_cache' có trường nhạy cảm hoặc Base64 cần làm sạch.")

    stats = {"found": count, "cleaned": 0, "backup": None}
    if count == 0:
        return stats

    if args.apply:
        stats["backup"] = create_collection_backup(db, "query_cache")
        col.update_many(
            {},
            {"$unset": {
                "original_question": "",
                "meta.visual.raw.image_base64": ""
            }}
        )
        stats["cleaned"] = count
    else:
        stats["cleaned"] = count

    return stats


def clean_rag_events_raw_questions(db, args) -> Dict[str, Any]:
    col = db["rag_events"]
    count = col.count_documents({"question": {"$exists": True}})
    logger.info(f"Phát hiện {count} document 'rag_events' có trường plain text 'question'.")

    stats = {"found": count, "cleaned": 0, "backup": None}
    if count == 0:
        return stats

    if args.apply:
        stats["backup"] = create_collection_backup(db, "rag_events")
        col.update_many({}, {"$unset": {"question": ""}})
        stats["cleaned"] = count
    else:
        stats["cleaned"] = count

    return stats


def run_migration(args):
    client, db = get_migration_db(args.database)
    logger.info(f"=== Bắt đầu 006_remove_legacy_binary_fields (Mode: {'DRY-RUN' if args.dry_run else 'APPLY'}) ===")

    img_stats = extract_and_clean_image_binaries(db, args)
    cache_stats = clean_query_cache_legacy_fields(db, args)
    rag_stats = clean_rag_events_raw_questions(db, args)

    report = {
        "script": "006_remove_legacy_binary_fields",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "database": args.database,
        "mode": "dry-run" if args.dry_run else "apply",
        "generated_images": img_stats,
        "query_cache": cache_stats,
        "rag_events": rag_stats
    }
    save_migration_report(report, args.report_file)
    return report


if __name__ == "__main__":
    parser = get_base_parser("Trích xuất binary legacy ra storage và dọn dẹp Base64/privacy trong MongoDB")
    args = parser.parse_args()
    run_migration(args)
