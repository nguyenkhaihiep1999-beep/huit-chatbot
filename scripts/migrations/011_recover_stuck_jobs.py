"""
011_recover_stuck_jobs.py
Migration phục hồi các job legacy bị kẹt ở trạng thái 'processing':
- Tìm các job 'processing' thiếu lease fields (lease_owner, lease_expires_at) hoặc lease đã quá hạn.
- Không xóa lịch sử sự kiện 'events', chỉ append thêm sự kiện phục hồi.
- Chính sách xử lý:
  + Các job cũ (tạo > 1 giờ trước): Đánh dấu 'failed' với lỗi giải thích rõ tác vụ bị gián đoạn do hệ thống cũ khởi động lại.
  + Các job mới hơn (tạo <= 1 giờ trước) và chưa quá số lần thử: Chuyển về 'queued' để worker mới nhận xử lý.
- Hỗ trợ đầy đủ --dry-run (mặc định) và --apply (tự động sao lưu jobs_backup_<timestamp> trước khi ghi).
- Xuất báo cáo chi tiết vào audit_outputs/.
"""
from pathlib import Path
import sys
ROOT_DIR = Path(__file__).resolve().parent.parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

from scripts.migrations.common import (
    get_base_parser,
    get_migration_db,
    create_collection_backup,
    save_migration_report,
    logger,
)


def recover_stuck_jobs(db, args) -> Dict[str, Any]:
    col = db["jobs"]
    now_dt = datetime.now(timezone.utc)
    
    # Query tìm các job processing bị kẹt:
    # 1. status == 'processing' VÀ (lease_owner không có HOẶC lease_expires_at không có HOẶC lease_expires_at <= now)
    stuck_filter = {
        "status": "processing",
        "$or": [
            {"lease_owner": {"$exists": False}},
            {"lease_owner": None},
            {"lease_expires_at": {"$exists": False}},
            {"lease_expires_at": None},
            {"lease_expires_at": {"$lte": now_dt}}
        ]
    }

    stuck_jobs = list(col.find(stuck_filter))
    total_stuck = len(stuck_jobs)
    logger.info(f"Tìm thấy {total_stuck} jobs bị kẹt ở trạng thái 'processing' cần phục hồi.")

    stats: Dict[str, Any] = {
        "total_stuck_found": total_stuck,
        "marked_failed": 0,
        "reset_to_queued": 0,
        "errors": 0,
        "backup": None,
        "recovered_jobs": []
    }

    if args.apply and total_stuck > 0:
        stats["backup"] = create_collection_backup(db, "jobs")

    cutoff_recent = now_dt - timedelta(hours=1)

    for doc in stuck_jobs:
        doc_id = doc["_id"]
        job_id = doc.get("job_id", str(doc_id))
        created_at = doc.get("created_at")

        # Chuẩn hóa datetime
        if isinstance(created_at, str):
            try:
                created_dt = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
            except Exception:
                created_dt = now_dt - timedelta(days=1)
        elif isinstance(created_at, datetime):
            created_dt = created_at if created_at.tzinfo else created_at.replace(tzinfo=timezone.utc)
        else:
            created_dt = now_dt - timedelta(days=1)

        attempt = doc.get("attempt", doc.get("retries", 0))
        max_attempts = doc.get("max_attempts", 3)

        # Quyết định chính sách:
        # Nếu job tạo hơn 1 giờ trước -> đã bỏ hoang từ đợt chạy trước -> chuyển sang 'failed' có giải thích
        # Nếu job gần đây và attempt < max_attempts -> đưa về 'queued' để xử lý lại
        if created_dt < cutoff_recent or attempt >= max_attempts:
            new_status = "failed"
            action_reason = "Tác vụ bị gián đoạn do worker cũ tắt/khởi động lại trước khi hoàn thành và không gửi heartbeat"
            err_obj = {
                "error_code": "JOB_ABANDONED_PREVIOUS_INSTANCE",
                "message": action_reason,
                "recovered_at": now_dt.isoformat()
            }
            update_data = {
                "status": "failed",
                "lease_owner": None,
                "lease_expires_at": None,
                "heartbeat_at": None,
                "error": err_obj,
                "updated_at": now_dt
            }
            stats["marked_failed"] += 1
        else:
            new_status = "queued"
            action_reason = "Phục hồi job bị mất lease về hàng đợi (re-queued) để worker xử lý lại"
            update_data = {
                "status": "queued",
                "lease_owner": None,
                "lease_expires_at": None,
                "heartbeat_at": None,
                "available_at": now_dt,
                "updated_at": now_dt
            }
            stats["reset_to_queued"] += 1

        recovery_event = {
            "timestamp": now_dt,
            "status": new_status,
            "progress": doc.get("progress", 0),
            "detail": f"[Migration 011] {action_reason}"
        }

        job_summary = {
            "job_id": job_id,
            "previous_status": "processing",
            "new_status": new_status,
            "reason": action_reason,
            "created_at": created_dt.isoformat()
        }
        stats["recovered_jobs"].append(job_summary)

        if args.apply:
            try:
                col.update_one(
                    {"_id": doc_id},
                    {
                        "$set": update_data,
                        "$push": {"events": {"$each": [recovery_event], "$slice": -30}}
                    }
                )
            except Exception as e:
                logger.error(f"Lỗi cập nhật job {job_id}: {e}")
                stats["errors"] += 1

    logger.info(f"Hoàn thành phân tích phục hồi: {stats['marked_failed']} job chuyển failed, {stats['reset_to_queued']} job chuyển queued.")
    return stats


def run_migration(args):
    client, db = get_migration_db(args.database)
    logger.info(f"=== Bắt đầu 011_recover_stuck_jobs (Mode: {'DRY-RUN' if args.dry_run else 'APPLY'}) ===")
    try:
        stats = recover_stuck_jobs(db, args)
        report = {
            "script": "011_recover_stuck_jobs",
            "mode": "dry-run" if args.dry_run else "apply",
            "database": args.database,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "stats": stats
        }
        out_path = save_migration_report(report, args.report_file)
        logger.info(f"Báo cáo chi tiết đã lưu tại: {out_path}")
        return 0
    except Exception as e:
        logger.error(f"Lỗi thực thi migration: {e}", exc_info=True)
        return 1
    finally:
        client.close()


if __name__ == "__main__":
    parser = get_base_parser("Migration 011: Phục hồi các job bị kẹt ở trạng thái processing trong collection jobs.")
    args = parser.parse_args()
    sys.exit(run_migration(args))
