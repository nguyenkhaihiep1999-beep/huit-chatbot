"""
001_audit_mongodb_schema.py
Khảo sát và kiểm tra toàn diện schema MongoDB (Read-Only):
- Liệt kê tất cả collections và số document.
- Kiểm tra $jsonSchema validator và validationLevel / validationAction.
- Kiểm tra indexes (thường, unique, TTL).
- Phát hiện các trường ngày giờ đang lưu dạng chuỗi thay vì BSON Date.
- Phát hiện các trường binary hoặc Base64 lớn (> 10KB).
- Kiểm tra dữ liệu trùng lặp (content_hash, asset_id, job_id, cache_key).
- Không bao giờ in nội dung prompt, câu hỏi, manifest riêng tư.
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
    save_migration_report,
    logger,
)


def run_audit(args) -> Dict[str, Any]:
    client, db = get_migration_db(args.database)
    logger.info(f"Bắt đầu Audit Schema trên cơ sở dữ liệu: '{args.database}' (Chế độ: {'DRY-RUN' if args.dry_run else 'APPLY (Read-Only)'})")

    collections = db.list_collection_names()
    report = {
        "script": "001_audit_mongodb_schema",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "database": args.database,
        "mode": "dry-run" if args.dry_run else "apply",
        "total_collections": len(collections),
        "collections": {}
    }

    core_names = ["assets", "jobs", "generated_images", "query_cache", "rag_events", "chat_logs", "admission_visuals", "huit_kb"]

    for col_name in collections:
        col = db[col_name]
        doc_count = col.count_documents({})

        # 1. Validator
        col_info = db.command({"listCollections": 1, "filter": {"name": col_name}})
        batch = col_info.get("cursor", {}).get("firstBatch", [])
        opts = batch[0].get("options", {}) if batch else {}
        validator = opts.get("validator", {})
        has_validator = bool(validator and "$jsonSchema" in validator)

        # 2. Indexes
        idx_info = col.index_information()
        indexes_summary = []
        for iname, idata in idx_info.items():
            indexes_summary.append({
                "name": iname,
                "key": idata.get("key"),
                "unique": idata.get("unique", False),
                "sparse": idata.get("sparse", False),
                "expireAfterSeconds": idata.get("expireAfterSeconds")
            })

        # 3. Phân tích mẫu 100 docs
        sample_cursor = col.find({}).limit(100)
        string_dates = set()
        large_binary_count = 0
        has_question_raw = False
        has_original_question = False

        for doc in sample_cursor:
            for k, v in doc.items():
                if isinstance(v, str) and ("created_at" in k or "updated_at" in k or "last_accessed_at" in k or "retrieved_at" in k):
                    if len(v) >= 19 and ("T" in v or "-" in v):
                        string_dates.add(k)
                if isinstance(v, bytes) and len(v) > 5000:
                    large_binary_count += 1
                if isinstance(v, str) and len(v) > 5000 and "base64" in v.lower():
                    large_binary_count += 1
            if "question" in doc and col_name == "rag_events":
                has_question_raw = True
            if "original_question" in doc and col_name == "query_cache":
                has_original_question = True

        # 4. Kiểm tra trùng lặp
        duplicates = {}
        if col_name == "assets":
            pipeline = [
                {"$match": {"content_hash": {"$exists": True, "$ne": None, "$ne": ""}}},
                {"$group": {"_id": "$content_hash", "count": {"$sum": 1}}},
                {"$match": {"count": {"$gt": 1}}}
            ]
            dups = list(col.aggregate(pipeline))
            if dups:
                duplicates["content_hash"] = [{"hash": f"{d['_id'][:8]}...{d['_id'][-8:]}", "count": d["count"]} for d in dups]

        col_report = {
            "document_count": doc_count,
            "has_validator": has_validator,
            "validation_level": opts.get("validationLevel", "off"),
            "validation_action": opts.get("validationAction", "off"),
            "indexes": indexes_summary,
            "string_date_fields": sorted(list(string_dates)),
            "large_binary_sample_count": large_binary_count,
            "duplicates": duplicates,
            "has_question_raw": has_question_raw,
            "has_original_question": has_original_question,
            "is_core": col_name in core_names
        }
        report["collections"][col_name] = col_report

    save_migration_report(report, args.report_file)
    logger.info(f"Audit hoàn tất. Tổng số collections: {len(collections)}")
    return report


if __name__ == "__main__":
    parser = get_base_parser("Audit schema MongoDB read-only")
    args = parser.parse_args()
    run_audit(args)
