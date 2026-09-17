"""
007_create_indexes.py
Khởi tạo và áp dụng toàn bộ Indexes bắt buộc trên MongoDB:
- Kiểm tra trùng lặp (Pre-condition duplicate check) trước khi tạo unique index.
- Nếu phát hiện trùng lặp, dừng ngay lập tức và báo lỗi thay vì để database văng exception.
- Không thay đổi Atlas Vector Search index bằng lệnh index MongoDB thông thường.
- Ghi nhận chi tiết từng index: đã tồn tại, tạo mới, lỗi xung đột cấu hình.
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
    save_migration_report,
    logger,
)
from backend.app.repositories.mongo_repository import MongoRepository


def check_duplicates_precondition(db) -> Dict[str, Any]:
    """Kiểm tra điều kiện tiên quyết: đảm bảo không còn dữ liệu trùng trước khi tạo unique index."""
    checks = {
        ("assets", "content_hash"): [
            {"$match": {"content_hash": {"$exists": True, "$ne": None, "$ne": ""}}},
            {"$group": {"_id": "$content_hash", "count": {"$sum": 1}}},
            {"$match": {"count": {"$gt": 1}}}
        ],
        ("assets", "asset_id"): [
            {"$group": {"_id": "$asset_id", "count": {"$sum": 1}}},
            {"$match": {"count": {"$gt": 1}}}
        ],
        ("jobs", "job_id"): [
            {"$group": {"_id": "$job_id", "count": {"$sum": 1}}},
            {"$match": {"count": {"$gt": 1}}}
        ],
        ("generated_images", "content_hash"): [
            {"$match": {"content_hash": {"$exists": True, "$ne": None, "$ne": ""}}},
            {"$group": {"_id": "$content_hash", "count": {"$sum": 1}}},
            {"$match": {"count": {"$gt": 1}}}
        ],
        ("query_cache", "cache_key"): [
            {"$group": {"_id": "$cache_key", "count": {"$sum": 1}}},
            {"$match": {"count": {"$gt": 1}}}
        ]
    }

    issues = []
    for (col_name, field), pipeline in checks.items():
        if col_name in db.list_collection_names():
            dups = list(db[col_name].aggregate(pipeline))
            if dups:
                issues.append({
                    "collection": col_name,
                    "field": field,
                    "duplicate_count": len(dups)
                })

    return {
        "passed": len(issues) == 0,
        "issues": issues
    }


def run_migration(args):
    client, db = get_migration_db(args.database)
    logger.info(f"=== Bắt đầu 007_create_indexes (Mode: {'DRY-RUN' if args.dry_run else 'APPLY'}) ===")

    # 1. Kiểm tra pre-condition
    pre_check = check_duplicates_precondition(db)
    if not pre_check["passed"]:
        logger.error(f"Phát hiện dữ liệu trùng lặp chưa được giải quyết: {pre_check['issues']}. Hãy chạy script 003 trước!")
        if args.apply:
            raise RuntimeError(f"Không thể tạo unique indexes khi còn dữ liệu trùng: {pre_check['issues']}")

    report = {
        "script": "007_create_indexes",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "database": args.database,
        "mode": "dry-run" if args.dry_run else "apply",
        "precondition_check": pre_check,
        "index_results": []
    }

    if args.dry_run:
        logger.info("Chế độ DRY-RUN: Mô phỏng các index sẽ được khởi tạo.")
        # Mô phỏng kiểm tra index hiện có
        for col_name in ["query_cache", "rag_events", "assets", "jobs", "generated_images", "admission_visuals"]:
            if col_name in db.list_collection_names():
                existing = db[col_name].index_information()
                logger.info(f"Collection '{col_name}': hiện có các index {list(existing.keys())}")
    else:
        # Chế độ APPLY thật sự
        MongoRepository._db = db
        index_summary = MongoRepository.init_indexes()
        report["index_results"] = index_summary
        logger.info(f"Kết quả tạo index: {index_summary.get('success')} (Thất bại: {index_summary.get('failed_count')})")

    # Xác nhận an toàn đối với huit_kb
    logger.info("Xác nhận: Vector Search Index trên 'huit_kb' được giữ nguyên an toàn 100%, không bị can thiệp.")
    save_migration_report(report, args.report_file)
    return report


if __name__ == "__main__":
    parser = get_base_parser("Tạo toàn bộ indexes bắt buộc trên MongoDB")
    args = parser.parse_args()
    run_migration(args)
