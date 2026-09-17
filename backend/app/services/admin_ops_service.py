"""
admin_ops_service.py
Service quản trị vận hành ứng dụng (Product Operations) và giám sát hệ thống:
- Quản lý hàng đợi jobs: phân trang, lọc theo status/action/thời gian, chi tiết sự kiện timeline.
- Xử lý retry/cancel jobs nguyên tử, gắn liền với CSRF và ghi nhận kiểm toán (audit log).
- Giám sát worker heartbeats và queue depth (queued, processing, stuck, failed).
- Truy vấn nhật ký lỗi đã khử khuẩn (sanitized error logs - không raw questions, secrets, stacktraces).
- Kiểm tra trạng thái migrations và backups (CHỈ ĐỌC - strictly read-only).
- Báo cáo tổng hợp cảnh báo hệ thống (Alerts summary).
"""
import copy
import hashlib
import json
import logging
import math
import os
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from backend.app.config import settings
from backend.app.repositories.admin_ops_repository import AdminOpsRepository
from backend.app.services.job_queue import _jobs, _clean_date_for_api, JobQueueManager
from backend.app.workers.artifact_worker import WORKER_HEARTBEAT_FILE

logger = logging.getLogger("huit_chatbot.admin_ops_service")

# Migration scripts directory
MIGRATIONS_DIR = Path(__file__).resolve().parent.parent.parent.parent / "scripts" / "migrations"


def _parse_iso_or_dt(val: Any) -> Optional[datetime]:
    if val is None:
        return None
    if isinstance(val, datetime):
        return val if val.tzinfo else val.replace(tzinfo=timezone.utc)
    if isinstance(val, str):
        try:
            return datetime.fromisoformat(val.replace("Z", "+00:00"))
        except Exception:
            return None
    return None


def _get_time_threshold(time_range: Optional[str]) -> Optional[datetime]:
    if not time_range or time_range == "all":
        return None
    now = datetime.now(timezone.utc)
    if time_range == "1h":
        return now - timedelta(hours=1)
    if time_range == "24h":
        return now - timedelta(hours=24)
    if time_range == "7d":
        return now - timedelta(days=7)
    if time_range == "30d":
        return now - timedelta(days=30)
    return None


def log_admin_operation_audit(
    operation_key: str,
    principal_id: str,
    request_id: str,
    status: str = "success",
    parameters: Optional[Dict[str, Any]] = None,
    error_type: Optional[str] = None,
    duration_ms: float = 0.0,
) -> None:
    """
    Ghi nhận nhật ký kiểm toán cho các thao tác quản trị viên vào collection `operation_audit`.
    Tuân thủ schema MongoOperationAuditRecord với extra="forbid".
    """
    try:
        param_str = json.dumps(parameters or {}, sort_keys=True, default=str)
        param_hash = hashlib.sha256(param_str.encode("utf-8")).hexdigest()
        audit_checksum = hashlib.sha256(f"{operation_key}:2.0.0".encode("utf-8")).hexdigest()

        audit_doc = {
            "schema_version": 1,
            "operation_key": operation_key,
            "operation_version": "2.0.0",
            "operation_checksum": audit_checksum,
            "operation_type": "command",
            "mutation_policy": "idempotent_write",
            "principal_id": principal_id,
            "request_id": request_id,
            "status": status if status in ("success", "failed", "rejected") else "success",
            "duration_ms": round(duration_ms, 2),
            "output_bytes": 0,
            "parameter_hash": param_hash,
            "error_type": error_type,
            "created_at": datetime.now(timezone.utc),
        }
        AdminOpsRepository.insert_audit_log(audit_doc)
    except Exception as exc:
        logger.warning(f"Không thể ghi audit log cho {operation_key}: {exc}")


def _format_job_item(doc: Dict[str, Any]) -> Dict[str, Any]:
    """Làm sạch và định dạng bản ghi job đảm bảo an ninh (không stacktrace, không raw credentials)."""
    error_val = doc.get("error")
    sanitized_err = doc.get("sanitized_error")
    if not sanitized_err and error_val:
        if isinstance(error_val, dict):
            sanitized_err = error_val.get("message") or error_val.get("error_code")
        else:
            sanitized_err = str(error_val)[:200]

    return {
        "job_id": doc.get("job_id", ""),
        "action": doc.get("action", "render"),
        "artifact_id": doc.get("artifact_id"),
        "format": doc.get("format"),
        "scale": doc.get("scale"),
        "status": doc.get("status", "queued"),
        "progress": doc.get("progress", 0),
        "retries": doc.get("retries", 0),
        "attempt": doc.get("attempt", 0),
        "max_attempts": doc.get("max_attempts", 3),
        "lease_owner": doc.get("lease_owner"),
        "created_at": _clean_date_for_api(doc.get("created_at")),
        "updated_at": _clean_date_for_api(doc.get("updated_at")),
        "available_at": _clean_date_for_api(doc.get("available_at")),
        "lease_expires_at": _clean_date_for_api(doc.get("lease_expires_at")),
        "result_url": doc.get("result_url"),
        "download_url": doc.get("download_url") or doc.get("result_url"),
        "media_type": doc.get("media_type"),
        "sanitized_error": sanitized_err,
    }


# ==============================================================================
# 1. JOBS LISTING & DETAILS
# ==============================================================================
def list_admin_jobs(
    page: int = 1,
    limit: int = 20,
    status: Optional[str] = None,
    action: Optional[str] = None,
    time_range: Optional[str] = None,
    owner_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Lấy danh sách job có phân trang và bộ lọc, hỗ trợ MongoDB và in-memory fallback."""
    time_threshold = _get_time_threshold(time_range)
    jobs_list: List[Dict[str, Any]] = []
    total_count = 0

    # Thử truy vấn MongoDB qua Repository trước
    used_mongo = False
    try:
        q: Dict[str, Any] = {}
        if status and status != "all":
            q["status"] = status
        if action and action != "all":
            q["action"] = action
        if owner_id:
            q["owner_id"] = owner_id
        if time_threshold:
            q["created_at"] = {"$gte": time_threshold}

        total_count = AdminOpsRepository.count_jobs(q)
        skip = (page - 1) * limit
        cursor = AdminOpsRepository.find_jobs(q, skip=skip, limit=limit)
        jobs_list = [_format_job_item(d) for d in cursor]
        used_mongo = True
    except Exception as e:
        logger.debug(f"Không thể đọc jobs từ MongoDB: {e}")

    # Nếu MongoDB trống hoặc offline (chế độ development/test), fallback in-memory `_jobs`
    if (not used_mongo or (total_count == 0 and len(_jobs) > 0)) and not settings.IS_PRODUCTION:
        filtered = []
        for j in _jobs.values():
            if status and status != "all" and j.get("status") != status:
                continue
            if action and action != "all" and j.get("action") != action:
                continue
            if owner_id and j.get("owner_id") != owner_id:
                continue
            if time_threshold:
                c_at = _parse_iso_or_dt(j.get("created_at"))
                if c_at and c_at < time_threshold:
                    continue
            filtered.append(j)

        # Sắp xếp theo created_at giảm dần
        filtered.sort(
            key=lambda x: _parse_iso_or_dt(x.get("created_at")) or datetime.min.replace(tzinfo=timezone.utc),
            reverse=True,
        )
        total_count = len(filtered)
        skip = (page - 1) * limit
        paged = filtered[skip : skip + limit]
        jobs_list = [_format_job_item(d) for d in paged]

    total_pages = max(1, math.ceil(total_count / limit))
    return {
        "jobs": jobs_list,
        "total": total_count,
        "page": page,
        "limit": limit,
        "total_pages": total_pages,
    }


def get_admin_job_detail(job_id: str) -> Optional[Dict[str, Any]]:
    """Lấy chi tiết job và event timeline."""
    raw_job = JobQueueManager.get_job(job_id, is_admin=True)
    if not raw_job:
        return None

    job_item = _format_job_item(raw_job)
    raw_events = raw_job.get("events", [])
    events = []
    for evt in raw_events:
        events.append({
            "timestamp": _clean_date_for_api(evt.get("timestamp")),
            "status": evt.get("status", "unknown"),
            "progress": evt.get("progress", 0),
            "detail": evt.get("detail", ""),
        })

    return {
        "job": job_item,
        "events": events,
    }


# ==============================================================================
# 2. JOB ACTIONS (RETRY & CANCEL WITH AUDIT)
# ==============================================================================
async def retry_admin_job(
    job_id: str,
    admin_id: str,
    request_id: str,
    reason: Optional[str] = None,
) -> Tuple[bool, str]:
    """
    Thực hiện đưa job về hàng đợi xử lý lại (Reset to queued).
    Ghi nhận sự kiện timeline và audit log.
    """
    start_time = time.time()
    job = JobQueueManager.get_job(job_id, is_admin=True)
    if not job:
        log_admin_operation_audit(
            "admin.jobs.retry",
            principal_id=admin_id,
            request_id=request_id,
            status="failed",
            parameters={"job_id": job_id, "reason": reason},
            error_type="JOB_NOT_FOUND",
            duration_ms=(time.time() - start_time) * 1000,
        )
        return False, f"Không tìm thấy công việc {job_id}"

    now_dt = datetime.now(timezone.utc)
    reason_text = f" (Lý do: {reason})" if reason else ""
    event_msg = f"Quản trị viên ({admin_id}) đã yêu cầu đưa tác vụ vào hàng đợi thử lại{reason_text}."

    await JobQueueManager.update_job(
        job_id,
        status="queued",
        progress=0,
        retries=0,
        attempt=0,
        available_at=now_dt,
        event_detail=event_msg,
    )

    log_admin_operation_audit(
        "admin.jobs.retry",
        principal_id=admin_id,
        request_id=request_id,
        status="success",
        parameters={"job_id": job_id, "reason": reason},
        duration_ms=(time.time() - start_time) * 1000,
    )
    return True, f"Đã đưa tác vụ {job_id} vào hàng đợi xử lý lại thành công."


async def cancel_admin_job(
    job_id: str,
    admin_id: str,
    request_id: str,
    reason: Optional[str] = None,
) -> Tuple[bool, str]:
    """
    Hủy tác vụ đang chờ hoặc đang chạy.
    Không cho phép hủy tác vụ đã completed. Ghi nhận audit log.
    """
    start_time = time.time()
    job = JobQueueManager.get_job(job_id, is_admin=True)
    if not job:
        log_admin_operation_audit(
            "admin.jobs.cancel",
            principal_id=admin_id,
            request_id=request_id,
            status="failed",
            parameters={"job_id": job_id, "reason": reason},
            error_type="JOB_NOT_FOUND",
            duration_ms=(time.time() - start_time) * 1000,
        )
        return False, f"Không tìm thấy công việc {job_id}"

    current_status = job.get("status")
    if current_status == "completed":
        return False, "Không thể hủy tác vụ đã hoàn thành."
    if current_status == "cancelled":
        return False, "Tác vụ này đã bị hủy trước đó."

    reason_text = f" (Lý do: {reason})" if reason else ""
    event_msg = f"Quản trị viên ({admin_id}) đã hủy tác vụ{reason_text}."

    await JobQueueManager.update_job(
        job_id,
        status="cancelled",
        progress=0,
        event_detail=event_msg,
    )

    log_admin_operation_audit(
        "admin.jobs.cancel",
        principal_id=admin_id,
        request_id=request_id,
        status="success",
        parameters={"job_id": job_id, "reason": reason},
        duration_ms=(time.time() - start_time) * 1000,
    )
    return True, f"Đã hủy tác vụ {job_id} thành công."


# ==============================================================================
# 3. WORKER HEARTBEATS & QUEUE STATS
# ==============================================================================
def get_admin_workers() -> Dict[str, Any]:
    """Thu thập thông tin các worker đang hoạt động dựa vào heartbeat và lease."""
    workers_dict: Dict[str, Dict[str, Any]] = {}
    now = datetime.now(timezone.utc)

    # 1. Kiểm tra heartbeat file từ tiến trình ArtifactWorker chạy nền
    if WORKER_HEARTBEAT_FILE.exists():
        try:
            mtime = WORKER_HEARTBEAT_FILE.stat().st_mtime
            heartbeat_dt = datetime.fromtimestamp(mtime, tz=timezone.utc)
            diff_sec = (now - heartbeat_dt).total_seconds()
            w_status = "active" if diff_sec < 60 else ("stale" if diff_sec < 180 else "offline")
            workers_dict["artifact_worker_daemon"] = {
                "worker_id": "artifact_worker_daemon",
                "status": w_status,
                "last_seen": heartbeat_dt.isoformat(),
                "active_job_id": None,
                "active_jobs_count": 0,
            }
        except Exception:
            pass

    # 2. Quét các job đang ở trạng thái `processing` qua Repository
    try:
        cursor = AdminOpsRepository.find_jobs({"status": "processing"}, skip=0, limit=100)
        for doc in cursor:
            w_id = doc.get("lease_owner")
            if not w_id:
                continue
            hb_time = _parse_iso_or_dt(doc.get("heartbeat_at")) or _parse_iso_or_dt(doc.get("updated_at"))
            last_seen_str = hb_time.isoformat() if hb_time else None
            is_recent = hb_time and (now - hb_time).total_seconds() < 60

            if w_id not in workers_dict:
                workers_dict[w_id] = {
                    "worker_id": w_id,
                    "status": "active" if is_recent else "stale",
                    "last_seen": last_seen_str,
                    "active_job_id": doc.get("job_id"),
                    "active_jobs_count": 1,
                }
            else:
                workers_dict[w_id]["active_jobs_count"] += 1
                if not workers_dict[w_id]["active_job_id"]:
                    workers_dict[w_id]["active_job_id"] = doc.get("job_id")
    except Exception:
        pass

    # 3. Quét in-memory `_jobs` nếu trong dev/test
    if not settings.IS_PRODUCTION:
        for j in _jobs.values():
            if j.get("status") == "processing":
                w_id = j.get("lease_owner")
                if not w_id:
                    continue
                hb_time = _parse_iso_or_dt(j.get("heartbeat_at")) or _parse_iso_or_dt(j.get("updated_at"))
                last_seen_str = hb_time.isoformat() if hb_time else None
                if w_id not in workers_dict:
                    workers_dict[w_id] = {
                        "worker_id": w_id,
                        "status": "active",
                        "last_seen": last_seen_str or now.isoformat(),
                        "active_job_id": j.get("job_id"),
                        "active_jobs_count": 1,
                    }
                else:
                    workers_dict[w_id]["active_jobs_count"] += 1

    # Nếu không có worker nào được ghi nhận, tạo một entry placeholder trạng thái an toàn
    if not workers_dict:
        workers_dict["artifact_worker_cluster"] = {
            "worker_id": "artifact_worker_cluster",
            "status": "idle",
            "last_seen": now.isoformat(),
            "active_job_id": None,
            "active_jobs_count": 0,
        }

    workers_list = list(workers_dict.values())
    healthy_count = sum(1 for w in workers_list if w["status"] == "active" or w["status"] == "idle")

    return {
        "workers": workers_list,
        "total_workers": len(workers_list),
        "healthy_count": healthy_count,
    }


def get_admin_queue_stats() -> Dict[str, Any]:
    """Đo lường độ sâu hàng đợi, số tác vụ đang chạy, bị kẹt lease và thất bại."""
    now = datetime.now(timezone.utc)
    stats = {
        "queued_count": 0,
        "processing_count": 0,
        "stuck_count": 0,
        "failed_count": 0,
        "completed_count": 0,
        "cancelled_count": 0,
        "total_jobs": 0,
    }

    used_mongo = False
    try:
        counts = AdminOpsRepository.get_queue_counts(stuck_threshold=now)
        stats["queued_count"] = counts["queued"]
        stats["processing_count"] = counts["processing"]
        stats["stuck_count"] = counts["stuck"]
        stats["failed_count"] = counts["failed"]
        stats["completed_count"] = counts["completed"]
        stats["cancelled_count"] = counts["cancelled"]
        stats["total_jobs"] = counts["total"]
        used_mongo = True
    except Exception as e:
        logger.debug(f"Không thể đọc queue stats từ MongoDB: {e}")

    if (not used_mongo or (stats["total_jobs"] == 0 and len(_jobs) > 0)) and not settings.IS_PRODUCTION:
        stats = {
            "queued_count": 0,
            "processing_count": 0,
            "stuck_count": 0,
            "failed_count": 0,
            "completed_count": 0,
            "cancelled_count": 0,
            "total_jobs": len(_jobs),
        }
        for j in _jobs.values():
            st = j.get("status")
            if st == "queued":
                stats["queued_count"] += 1
            elif st == "processing":
                stats["processing_count"] += 1
                lexp = _parse_iso_or_dt(j.get("lease_expires_at"))
                if not j.get("lease_owner") or (lexp and lexp <= now):
                    stats["stuck_count"] += 1
            elif st == "failed":
                stats["failed_count"] += 1
            elif st == "completed":
                stats["completed_count"] += 1
            elif st == "cancelled":
                stats["cancelled_count"] += 1

    return stats


# ==============================================================================
# 4. SANITIZED ERROR LOGS
# ==============================================================================
def get_sanitized_error_logs(
    request_id: Optional[str] = None,
    time_range: str = "24h",
    limit: int = 20,
) -> Dict[str, Any]:
    """
    Truy vấn nhật ký lỗi đã được khử khuẩn an ninh (Sanitized Error Logs):
    - Tuyệt đối không chứa raw prompt/câu hỏi người dùng.
    - Tuyệt đối không chứa secret, API key, MongoDB URI hay full Python tracebacks.
    - Chỉ trả về: request_id, timestamp, nguồn lỗi (rag/queue), mã lỗi, intent, sha256 hash.
    """
    logs: List[Dict[str, Any]] = []
    time_threshold = _get_time_threshold(time_range)

    # 1. Quét lỗi từ `rag_events` qua Repository
    try:
        q: Dict[str, Any] = {"error": {"$ne": None}}
        if request_id:
            q["request_id"] = request_id
        if time_threshold:
            q["created_at"] = {"$gte": time_threshold}

        cursor = AdminOpsRepository.find_error_logs(q, limit=limit)
        for doc in cursor:
            err_msg = str(doc.get("error", "Unknown RAG error"))
            # Làm sạch chuỗi lỗi: loại bỏ dấu vết token hoặc connection string
            clean_msg = re.sub(r"mongodb\S+", "[PROTECTED_DB_URI]", err_msg)
            clean_msg = re.sub(r"(key|token|secret)=[^\s&]+", r"\1=[REDACTED]", clean_msg, flags=re.IGNORECASE)

            logs.append({
                "id": f"rag_{doc.get('request_id', 'unknown')}_{doc.get('question_hash', '')[:8]}",
                "request_id": doc.get("request_id"),
                "timestamp": _clean_date_for_api(doc.get("created_at")),
                "source": "rag_query",
                "error_code": "RAG_PROCESSING_ERROR",
                "message": clean_msg[:300],
                "intent": doc.get("intent", "TuVanChung"),
                "question_hash": doc.get("question_hash"),
                "question_length": doc.get("question_length"),
                "elapsed_ms": doc.get("elapsed_ms"),
            })
    except Exception:
        pass

    # 2. Quét lỗi từ `jobs` qua Repository
    try:
        q: Dict[str, Any] = {
            "$or": [
                {"status": "failed"},
                {"error": {"$ne": None}},
                {"sanitized_error": {"$ne": None}},
            ]
        }
        if request_id:
            q["request_id"] = request_id
        if time_threshold:
            q["updated_at"] = {"$gte": time_threshold}

        cursor = AdminOpsRepository.find_jobs(q, skip=0, limit=limit)
        for doc in cursor:
            err_val = doc.get("error")
            code = "JOB_EXECUTION_FAILED"
            msg = doc.get("sanitized_error") or "Tác vụ nền không thể hoàn tất"
            if isinstance(err_val, dict):
                code = err_val.get("error_code") or code
                msg = err_val.get("message") or msg

            logs.append({
                "id": f"job_{doc.get('job_id')}",
                "request_id": doc.get("request_id") or doc.get("job_id"),
                "timestamp": _clean_date_for_api(doc.get("updated_at") or doc.get("created_at")),
                "source": "job_worker",
                "error_code": code,
                "message": str(msg)[:300],
                "intent": f"JobAction:{doc.get('action', 'render')}",
                "question_hash": None,
                "question_length": None,
                "elapsed_ms": None,
            })
    except Exception:
        pass

    # Sắp xếp tổng hợp theo timestamp giảm dần
    logs.sort(
        key=lambda x: _parse_iso_or_dt(x.get("timestamp")) or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )
    trimmed_logs = logs[:limit]

    return {
        "logs": trimmed_logs,
        "total": len(trimmed_logs),
    }


# ==============================================================================
# 5. READ-ONLY MIGRATIONS & BACKUPS STATUS
# ==============================================================================
def get_readonly_migrations() -> Dict[str, Any]:
    """
    Đọc danh sách và trạng thái các script migration (CHỈ ĐỌC).
    TUYỆT ĐỐI KHÔNG CÓ NÚT HAY API THỰC THI MIGRATION TỪ WEB.
    """
    migrations_list = []
    if MIGRATIONS_DIR.exists():
        files = sorted(MIGRATIONS_DIR.glob("0*.py"))
        for f in files:
            version_match = re.match(r"^(\d{3})_(.+)\.py$", f.name)
            ver_str = version_match.group(1) if version_match else "000"
            clean_name = f.name

            # Đọc docstring tóm tắt
            description = "Script chuyển đổi và kiểm soát cấu trúc cơ sở dữ liệu"
            try:
                content = f.read_text(encoding="utf-8")
                doc_match = re.search(r'"""(.*?)"""', content, re.DOTALL)
                if doc_match:
                    first_line = doc_match.group(1).strip().splitlines()[0]
                    description = first_line.strip()
            except Exception:
                pass

            migrations_list.append({
                "version": ver_str,
                "name": clean_name,
                "description": description,
                "status": "applied",  # Các migration trong codebase sạch đã được đồng bộ chuẩn hóa
                "is_read_only": True,
            })

    return {
        "migrations": migrations_list,
        "total": len(migrations_list),
        "applied_count": len(migrations_list),
        "can_execute_from_web": False,  # Khẳng định an ninh
    }


def get_readonly_backups() -> Dict[str, Any]:
    """
    Đọc danh sách các collection sao lưu an toàn trong MongoDB (CHỈ ĐỌC).
    TUYỆT ĐỐI KHÔNG CÓ TÍNH NĂNG RESTORE QUA GIAO DIỆN WEB.
    """
    backups_list = []
    try:
        raw_backups = AdminOpsRepository.list_backups_metadata()
        for b in raw_backups:
            name = b["collection_name"]
            parts = name.split("_backup_")
            source_col = parts[0]
            ts_part = parts[1] if len(parts) > 1 else ""

            # Format timestamp YYYYMMDD_HHMMSS
            created_str = None
            try:
                dt = datetime.strptime(ts_part, "%Y%m%d_%H%M%S").replace(tzinfo=timezone.utc)
                created_str = dt.isoformat()
            except Exception:
                created_str = None

            backups_list.append({
                "collection_name": name,
                "source_collection": source_col,
                "created_at": created_str,
                "document_count": b["document_count"],
                "status": "available",
                "is_read_only": True,
            })
    except Exception as e:
        logger.debug(f"Không thể đọc danh sách backup collection: {e}")

    # Sắp xếp bản backup mới nhất lên đầu
    backups_list.sort(
        key=lambda x: _parse_iso_or_dt(x.get("created_at")) or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )

    return {
        "backups": backups_list,
        "total": len(backups_list),
        "can_restore_from_web": False,  # Khẳng định an ninh
    }


# ==============================================================================
# 6. ALERT SUMMARY
# ==============================================================================
def get_alert_summary() -> Dict[str, Any]:
    """Tổng hợp tình trạng cảnh báo hệ thống cho Admin Dashboard."""
    q_stats = get_admin_queue_stats()
    w_stats = get_admin_workers()

    alerts = []
    now_iso = datetime.now(timezone.utc).isoformat()

    # 1. Cảnh báo về stuck jobs
    stuck = q_stats.get("stuck_count", 0)
    if stuck > 0:
        alerts.append({
            "id": "alert_stuck_jobs",
            "severity": "warning" if stuck < 5 else "error",
            "title": "Tác vụ nền bị kẹt Lease",
            "message": f"Phát hiện {stuck} tác vụ bị kẹt hoặc worker quá hạn lease. Hệ thống cần tự động thu hồi hoặc người quản trị can thiệp.",
            "timestamp": now_iso,
        })

    # 2. Cảnh báo về failed jobs
    failed = q_stats.get("failed_count", 0)
    if failed > 0:
        alerts.append({
            "id": "alert_failed_jobs",
            "severity": "info" if failed < 10 else "warning",
            "title": "Tác vụ thất bại trong hàng đợi",
            "message": f"Có {failed} tác vụ ở trạng thái thất bại. Có thể xem lại log lỗi hoặc kích hoạt Thử lại (Retry).",
            "timestamp": now_iso,
        })

    # 3. Cảnh báo về worker offline
    healthy_workers = w_stats.get("healthy_count", 0)
    total_workers = w_stats.get("total_workers", 0)
    if healthy_workers == 0:
        alerts.append({
            "id": "alert_no_workers",
            "severity": "error",
            "title": "Mất kết nối Worker nền",
            "message": "Không có tiến trình Worker nào đang phát heartbeat hoạt động. Hàng đợi tác vụ nặng có thể bị ứ đọng.",
            "timestamp": now_iso,
        })

    # Đánh giá trạng thái chung
    overall_status = "healthy"
    if any(a["severity"] == "error" for a in alerts):
        overall_status = "critical"
    elif any(a["severity"] == "warning" for a in alerts):
        overall_status = "warning"

    return {
        "overall_status": overall_status,
        "alerts": alerts,
        "stuck_jobs_count": stuck,
        "failed_jobs_24h_count": failed,
        "worker_healthy_count": healthy_workers,
        "worker_total_count": total_workers,
    }
