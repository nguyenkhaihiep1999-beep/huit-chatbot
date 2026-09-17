"""
scripts/migrations/common.py
Thư viện tiện ích dùng chung cho các script migration MongoDB:
- Quản lý tham số dòng lệnh tiêu chuẩn: --dry-run, --apply, --database, --batch-size, --resume-from, --report-file.
- Kết nối MongoDB an toàn, tuyệt đối không in URI hoặc thông tin xác thực ra log.
- Quản lý batch processing, không nạp toàn bộ collection vào RAM.
- Tự động sao lưu collection trước khi ghi đè (khi có cờ --apply).
- Báo cáo tiến trình, số lượng document hợp lệ, sửa đổi, lỗi, bỏ qua.
"""
import argparse
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
import sys
ROOT_DIR = Path(__file__).resolve().parent.parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from typing import Any, Dict, Generator, List, Optional, Tuple
from urllib.parse import quote_plus
from pymongo import MongoClient
from pymongo.database import Database
from pymongo.collection import Collection

from backend.app.config import settings


# Cấu hình logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger("migration")


def get_base_parser(description: str) -> argparse.ArgumentParser:
    """Tạo parser với đầy đủ các tham số dòng lệnh quy định."""
    parser = argparse.ArgumentParser(description=description)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--dry-run",
        action="store_true",
        help="Chạy mô phỏng kiểm tra, tuyệt đối KHÔNG thay đổi dữ liệu trong database."
    )
    group.add_argument(
        "--apply",
        action="store_true",
        help="Thực thi thay đổi dữ liệu thật sự vào MongoDB."
    )
    parser.add_argument(
        "--database",
        type=str,
        default=settings.MONGODB_DB,
        help=f"Tên cơ sở dữ liệu (mặc định: {settings.MONGODB_DB})"
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=100,
        help="Số lượng document xử lý trong mỗi batch (mặc định: 100)"
    )
    parser.add_argument(
        "--resume-from",
        type=str,
        default=None,
        help="Khôi phục tiến trình từ _id chỉ định"
    )
    parser.add_argument(
        "--report-file",
        type=str,
        default=None,
        help="Đường dẫn file JSON ghi báo cáo kết quả"
    )
    return parser


def get_migration_db(database_name: Optional[str] = None) -> Tuple[MongoClient, Database]:
    """Khởi tạo kết nối MongoDB an toàn không để lộ password hay connection string."""
    target_db = database_name or settings.MONGODB_DB

    # URI kết nối (không in ra log)
    uri = settings.MONGODB_URI
    if not uri:
        pwd = settings.MONGODB_PASSWORD
        if not pwd:
            raise RuntimeError("Biến MONGODB_URI hoặc MONGODB_PASSWORD chưa được cấu hình!")
        user = settings.MONGODB_USER
        host = settings.MONGODB_HOST
        uri = f"mongodb+srv://{user}:{quote_plus(pwd)}@{host}/?appName=Cluster0"
    client = MongoClient(uri, serverSelectionTimeoutMS=settings.MONGODB_TIMEOUT_MS)
    db = client[target_db]
    # Kiểm tra kết nối
    db.command("ping")
    return client, db


def create_collection_backup(db: Database, col_name: str, suffix: Optional[str] = None) -> Optional[str]:
    """Tạo bản sao lưu collection trước khi migration."""
    source_col = db[col_name]
    doc_count = source_col.count_documents({})
    if doc_count == 0:
        logger.info(f"Collection '{col_name}' đang trống, không cần tạo bản backup.")
        return None

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    backup_name = f"{col_name}_backup_{suffix}_{timestamp}" if suffix else f"{col_name}_backup_{timestamp}"
    backup_col = db[backup_name]

    logger.info(f"Đang sao lưu {doc_count} documents từ '{col_name}' sang '{backup_name}'...")
    cursor = source_col.find({})
    batch = []
    for doc in cursor:
        batch.append(doc)
        if len(batch) >= 500:
            backup_col.insert_many(batch)
            batch = []
    if batch:
        backup_col.insert_many(batch)

    logger.info(f"Sao lưu hoàn tất: '{backup_name}' ({backup_col.count_documents({})} documents)")
    return backup_name


def iterate_batches(
    col: Collection,
    filter_query: Dict[str, Any],
    batch_size: int = 100,
    resume_from: Optional[str] = None,
    projection: Optional[Dict[str, Any]] = None
) -> Generator[List[Dict[str, Any]], None, None]:
    """Duyệt collection theo batch tuần tự để tránh tải toàn bộ vào RAM."""
    query = dict(filter_query)
    if resume_from:
        query["_id"] = {"$gt": resume_from}

    if projection:
        cursor = col.find(query, projection).sort("_id", 1).batch_size(batch_size)
    else:
        cursor = col.find(query).sort("_id", 1).batch_size(batch_size)

    batch = []
    for doc in cursor:
        batch.append(doc)
        if len(batch) >= batch_size:
            yield batch
            batch = []
    if batch:
        yield batch



def save_migration_report(report: Dict[str, Any], report_file: Optional[str] = None):
    """Ghi báo cáo kết quả migration ra file JSON."""
    if not report_file:
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        script_name = report.get("script", "migration")
        out_dir = Path("audit_outputs")
        out_dir.mkdir(parents=True, exist_ok=True)
        report_file = str(out_dir / f"{script_name}_{timestamp}_report.json")

    out_path = Path(report_file)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False, default=str)

    logger.info(f"Báo cáo migration đã được lưu tại: {out_path.resolve()}")
