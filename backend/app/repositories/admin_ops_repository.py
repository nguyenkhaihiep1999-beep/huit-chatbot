"""
admin_ops_repository.py
Repository đóng gói toàn bộ truy vấn MongoDB phục vụ Admin Operations:
- Tuân thủ LTX-RULE-1: Cách ly toàn bộ raw mongo primitives trong tầng repository.
- Ghi nhận audit logs vào operation_audit.
- Truy vấn jobs, queue counts, error logs, backup metadata và alert metrics.
"""
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from backend.app.repositories.mongo_repository import MongoRepository

logger = logging.getLogger("huit_chatbot.admin_ops_repository")


class AdminOpsRepository:
    """Tầng Repository chuyên biệt cho các thao tác dữ liệu của Admin Operations."""

    @staticmethod
    def insert_audit_log(doc: Dict[str, Any]) -> bool:
        """Ghi nhận nhật ký kiểm toán vào collection operation_audit."""
        try:
            col = MongoRepository.get_operation_audit_collection()
            if col is not None:
                col.insert_one(doc)
                return True
        except Exception as exc:
            logger.warning(f"Không thể ghi audit log: {exc}")
        return False

    @staticmethod
    def count_jobs(filter_query: Dict[str, Any]) -> int:
        """Đếm số lượng jobs thỏa điều kiện."""
        db = MongoRepository.get_db()
        if db is None:
            return 0
        try:
            return db["jobs"].count_documents(filter_query)
        except Exception as exc:
            logger.warning(f"Lỗi đếm jobs: {exc}")
            return 0

    @staticmethod
    def find_jobs(filter_query: Dict[str, Any], skip: int = 0, limit: int = 15) -> List[Dict[str, Any]]:
        """Truy vấn danh sách jobs có phân trang."""
        db = MongoRepository.get_db()
        if db is None:
            return []
        try:
            cursor = db["jobs"].find(filter_query).sort("created_at", -1).skip(skip).limit(limit)
            return list(cursor)
        except Exception as exc:
            logger.warning(f"Lỗi truy vấn jobs: {exc}")
            return []

    @staticmethod
    def get_queue_counts(
        stuck_threshold: datetime,
        time_threshold: Optional[datetime] = None
    ) -> Dict[str, int]:
        """Thống kê số lượng jobs theo các trạng thái hàng đợi."""
        db = MongoRepository.get_db()
        if db is None:
            return {
                "queued": 0,
                "processing": 0,
                "stuck": 0,
                "failed": 0,
                "completed": 0,
                "cancelled": 0,
                "total": 0,
            }
        try:
            col = db["jobs"]
            base_q: Dict[str, Any] = {}
            if time_threshold:
                base_q["created_at"] = {"$gte": time_threshold}

            q_queued = {**base_q, "status": "queued"}
            q_proc = {**base_q, "status": "processing"}
            q_stuck = {**base_q, "status": "processing", "lease_expires_at": {"$lt": stuck_threshold}}
            q_fail = {**base_q, "status": "failed"}
            q_comp = {**base_q, "status": "completed"}
            q_canc = {**base_q, "status": "cancelled"}

            return {
                "queued": col.count_documents(q_queued),
                "processing": col.count_documents(q_proc),
                "stuck": col.count_documents(q_stuck),
                "failed": col.count_documents(q_fail),
                "completed": col.count_documents(q_comp),
                "cancelled": col.count_documents(q_canc),
                "total": col.count_documents(base_q),
            }
        except Exception as exc:
            logger.warning(f"Lỗi thống kê queue counts: {exc}")
            return {
                "queued": 0,
                "processing": 0,
                "stuck": 0,
                "failed": 0,
                "completed": 0,
                "cancelled": 0,
                "total": 0,
            }

    @staticmethod
    def find_error_logs(
        filter_query: Dict[str, Any],
        limit: int = 50
    ) -> List[Dict[str, Any]]:
        """Truy vấn các bản ghi sự cố từ rag_events và jobs."""
        db = MongoRepository.get_db()
        if db is None:
            return []
        try:
            cursor = db["rag_events"].find(filter_query).sort("timestamp", -1).limit(limit)
            return list(cursor)
        except Exception as exc:
            logger.warning(f"Lỗi truy vấn error logs: {exc}")
            return []

    @staticmethod
    def list_backups_metadata() -> List[Dict[str, Any]]:
        """Liệt kê danh sách các collection sao lưu và số lượng tài liệu."""
        db = MongoRepository.get_db()
        if db is None:
            return []
        try:
            collections = db.list_collection_names()
            backup_cols = [c for c in collections if "backup" in c.lower() or c.endswith("_bak")]
            items = []
            for col_name in backup_cols:
                cnt = db[col_name].count_documents({})
                items.append({
                    "collection_name": col_name,
                    "document_count": cnt,
                })
            return items
        except Exception as exc:
            logger.warning(f"Lỗi đọc metadata backups: {exc}")
            return []

    @staticmethod
    def get_alert_metrics(
        stuck_threshold: datetime,
        failed_threshold: datetime
    ) -> Dict[str, int]:
        """Lấy số lượng jobs bị kẹt và thất bại phục vụ cảnh báo."""
        db = MongoRepository.get_db()
        if db is None:
            return {"stuck_jobs_count": 0, "failed_jobs_24h_count": 0}
        try:
            col = db["jobs"]
            stuck_cnt = col.count_documents({
                "status": "processing",
                "lease_expires_at": {"$lt": stuck_threshold},
            })
            fail_cnt = col.count_documents({
                "status": "failed",
                "created_at": {"$gte": failed_threshold},
            })
            return {"stuck_jobs_count": stuck_cnt, "failed_jobs_24h_count": fail_cnt}
        except Exception as exc:
            logger.warning(f"Lỗi đọc alert metrics: {exc}")
            return {"stuck_jobs_count": 0, "failed_jobs_24h_count": 0}
