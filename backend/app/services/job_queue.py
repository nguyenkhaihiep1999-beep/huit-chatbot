"""
job_queue.py
Hàng đợi bất đồng bộ bền vững (Durable Background Job Queue) cho các tác vụ render nặng:
- Xuất tài liệu Word, Excel, PDF.
- Upscale ảnh chất lượng cao 2x, 4x, Retina.
- Lưu trữ bền vững hai cấp: RAM Cache + Registered Operation Gateway cho Collection `jobs` (chống mất trạng thái khi instance restart).
- Quản lý trạng thái: queued -> processing -> completed / failed / cancelled.
- Hỗ trợ retry an toàn tối đa 3 lần cho các lỗi retryable.
- Theo dõi tiến trình qua GET /api/jobs/{id} và GET /api/jobs/{id}/events.
- Hỗ trợ hủy tác vụ qua POST /api/jobs/{id}/cancel.
- Bảo vệ quyền sở hữu (owner_id) cho mỗi tác vụ.
"""
import asyncio
import copy
import logging
import secrets
import traceback
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional

from backend.app.config import settings
from backend.app.data_access.operations import job_operations
from backend.app.telemetry.errors import ArtifactException, ERROR_JOB_TIMEOUT, ERROR_ARTIFACT_ACCESS_DENIED

logger = logging.getLogger("huit_chatbot.job_queue")
MAX_RETRIES = 3
DEFAULT_LEASE_SECONDS = 120
DEFAULT_JOB_TIMEOUT_SECONDS = 120

_jobs: Dict[str, Dict[str, Any]] = {}
_jobs_lock = asyncio.Lock()


def clear_jobs_for_testing() -> None:
    """Xóa bộ nhớ đệm jobs phục vụ isolated testing."""
    global _jobs
    _jobs.clear()


def _clean_date_for_api(val: Any) -> Optional[str]:
    if val is None:
        return None
    if isinstance(val, datetime):
        return val.isoformat()
    return str(val)


class MongoLeaseQueueAdapter:
    """Adapter xử lý cấp phát và thu hồi lease công việc nền nguyên tử qua Registered Operation Gateway."""

    @staticmethod
    def claim_next_job(worker_id: str, lease_seconds: int = DEFAULT_LEASE_SECONDS, specific_job_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """
        Nhận quyền thực thi (lease) một tác vụ một cách nguyên tử qua Gateway:
        - Tác vụ ở trạng thái 'queued' và đã đến giờ thực hiện (available_at <= now).
        - Hoặc tác vụ ở trạng thái 'processing' nhưng lease đã quá hạn (lease_expires_at <= now, worker cũ bị crash) và chưa quá số lần thử tối đa.
        """
        now_dt = datetime.now(timezone.utc)
        lease_expiry = now_dt + timedelta(seconds=lease_seconds)

        try:
            doc = job_operations.atomic_claim_next_job(
                worker_id=worker_id,
                lease_seconds=lease_seconds,
                specific_job_id=specific_job_id,
            )
            if doc:
                if not settings.IS_PRODUCTION:
                    _jobs[doc["job_id"]] = copy.deepcopy(doc)
                return doc
        except Exception as e:
            logger.debug(f"[Queue Claim Gateway Exception] {e}")
            if settings.IS_PRODUCTION:
                raise RuntimeError(f"Lỗi truy vấn Gateway khi claim job: {e}")

        # Trên Production: Tuyệt đối không fallback sang RAM!
        if settings.IS_PRODUCTION:
            return None

        # Fallback in-memory cho môi trường test offline / development
        for j_id, j in _jobs.items():
            if specific_job_id and j_id != specific_job_id:
                continue
            status = j.get("status")
            avail_at = j.get("available_at") or now_dt
            if isinstance(avail_at, str):
                try:
                    avail_at = datetime.fromisoformat(avail_at.replace("Z", "+00:00"))
                except Exception:
                    avail_at = now_dt
            lease_exp = j.get("lease_expires_at")
            if isinstance(lease_exp, str):
                try:
                    lease_exp = datetime.fromisoformat(lease_exp.replace("Z", "+00:00"))
                except Exception:
                    lease_exp = None
            attempt_count = j.get("attempt", 0)
            max_att = j.get("max_attempts", MAX_RETRIES)

            is_ready_queued = (status == "queued" and avail_at <= now_dt and attempt_count < max_att)
            is_expired_lease = (status == "processing" and lease_exp is not None and lease_exp <= now_dt and attempt_count < max_att)

            if is_ready_queued or is_expired_lease:
                j["status"] = "processing"
                j["lease_owner"] = worker_id
                j["lease_expires_at"] = lease_expiry
                j["heartbeat_at"] = now_dt
                j["attempt"] = j.get("attempt", 0) + 1
                j["updated_at"] = now_dt
                try:
                    job_operations.update_job_record(
                        j_id,
                        status="processing",
                        attempt=j["attempt"],
                        worker_id=worker_id,
                    )
                except Exception:
                    pass
                return copy.deepcopy(j)

        return None

    @staticmethod
    def heartbeat(job_id: str, worker_id: str, extend_seconds: int = DEFAULT_LEASE_SECONDS) -> bool:
        """Kéo dài thời hạn lease khi worker vẫn đang xử lý bình thường qua Gateway."""
        now_dt = datetime.now(timezone.utc)
        try:
            ok = job_operations.heartbeat_job_lease(
                job_id=job_id,
                worker_id=worker_id,
                extend_seconds=extend_seconds,
            )
            if ok:
                if not settings.IS_PRODUCTION and job_id in _jobs:
                    _jobs[job_id]["heartbeat_at"] = now_dt
                    _jobs[job_id]["lease_expires_at"] = now_dt + timedelta(seconds=extend_seconds)
                return True
            if settings.IS_PRODUCTION:
                return False
        except Exception:
            if settings.IS_PRODUCTION:
                return False

        if not settings.IS_PRODUCTION and job_id in _jobs and _jobs[job_id].get("lease_owner") == worker_id:
            _jobs[job_id]["heartbeat_at"] = now_dt
            _jobs[job_id]["lease_expires_at"] = now_dt + timedelta(seconds=extend_seconds)
            return True
        return False

    @staticmethod
    def release_lease(job_id: str, worker_id: str) -> bool:
        """Giải phóng lease nếu worker dừng mà không hoàn tất qua Gateway."""
        try:
            ok = job_operations.release_job_lease(
                job_id=job_id,
                worker_id=worker_id,
            )
            if ok:
                if not settings.IS_PRODUCTION and job_id in _jobs:
                    _jobs[job_id]["status"] = "queued"
                    _jobs[job_id]["lease_owner"] = None
                    _jobs[job_id]["lease_expires_at"] = None
                return True
            if settings.IS_PRODUCTION:
                return False
        except Exception:
            if settings.IS_PRODUCTION:
                return False

        if not settings.IS_PRODUCTION and job_id in _jobs and _jobs[job_id].get("lease_owner") == worker_id:
            _jobs[job_id]["status"] = "queued"
            _jobs[job_id]["lease_owner"] = None
            _jobs[job_id]["lease_expires_at"] = None
            return True
        return False


class JobQueueManager:
    """Quản lý hàng đợi tác vụ nền bền vững (Durable Job Store) với kiểm soát lease và checkpoint hủy."""

    @staticmethod
    def get_job(job_id: str, requester_id: Optional[str] = None, is_admin: bool = False, principal: Any = None) -> Optional[Dict[str, Any]]:
        """Lấy thông tin tiến trình của một job theo ID, kiểm tra quyền sở hữu."""
        if not job_id:
            return None

        job = None
        try:
            doc = job_operations.get_job_by_id(job_id)
            if doc:
                if not settings.IS_PRODUCTION:
                    _jobs[job_id] = doc
                job = copy.deepcopy(doc)
        except Exception:
            pass

        if not job and not settings.IS_PRODUCTION and job_id in _jobs:
            job = copy.deepcopy(_jobs[job_id])

        if not job:
            return None

        # Kiểm tra quyền sở hữu (TUYỆT ĐỐI KHÔNG bypass bằng chuỗi requester_id == 'admin')
        owner = job.get("owner_id")
        if principal:
            if owner and not principal.can_access(owner, "private"):
                raise ArtifactException(
                    error_code=ERROR_ARTIFACT_ACCESS_DENIED,
                    message="Bạn không có quyền truy cập thông tin công việc này",
                    job_id=job_id
                )
        elif requester_id is not None:
            if owner and owner != "anonymous" and not is_admin:
                if not (requester_id != "anonymous" and requester_id == owner):
                    raise ArtifactException(
                        error_code=ERROR_ARTIFACT_ACCESS_DENIED,
                        message="Bạn không có quyền truy cập thông tin công việc này",
                        job_id=job_id
                    )

        # Chuyển đổi datetime sang ISO string phục vụ API serialization
        formatted_job = copy.deepcopy(job)
        formatted_job["check_status_url"] = f"/api/jobs/{job_id}"
        formatted_job["download_url"] = formatted_job.get("download_url") or formatted_job.get("result_url")
        formatted_job["created_at"] = _clean_date_for_api(formatted_job.get("created_at"))
        formatted_job["updated_at"] = _clean_date_for_api(formatted_job.get("updated_at"))
        formatted_job["lease_expires_at"] = _clean_date_for_api(formatted_job.get("lease_expires_at"))
        formatted_job["available_at"] = _clean_date_for_api(formatted_job.get("available_at"))
        formatted_job["heartbeat_at"] = _clean_date_for_api(formatted_job.get("heartbeat_at"))

        # Bảo vệ an ninh: Không rò rỉ stacktrace hoặc chi tiết nội bộ ra client nếu không phải admin
        if formatted_job.get("error") and not is_admin:
            if isinstance(formatted_job["error"], dict):
                formatted_job["error"] = {
                    "error_code": formatted_job["error"].get("error_code", "RENDER_JOB_FAILED"),
                    "message": formatted_job["error"].get("message") or formatted_job.get("sanitized_error") or "Không thể xử lý tác vụ",
                    "stage": formatted_job["error"].get("stage", "general"),
                    "retryable": formatted_job["error"].get("retryable", False)
                }

        if "events" in formatted_job and isinstance(formatted_job["events"], list):
            for e in formatted_job["events"]:
                e["timestamp"] = _clean_date_for_api(e.get("timestamp"))

        return formatted_job

    @staticmethod
    async def create_job(
        action: str,
        artifact_id: Optional[str] = None,
        target_format: Optional[str] = None,
        scale: Optional[int] = None,
        owner_id: Optional[str] = None,
        request_id: Optional[str] = None,
        idempotency_key: Optional[str] = None
    ) -> str:
        """Khởi tạo một job mới trong hàng đợi bền vững với Idempotency Key qua Gateway."""
        now_dt = datetime.now(timezone.utc)
        clean_owner_id = owner_id if (owner_id and owner_id != "anonymous") else None

        # Idempotency key tự động nếu không truyền
        idemp_key = idempotency_key or f"{action}:{artifact_id or ''}:{target_format or ''}:{scale or ''}:{clean_owner_id or 'anon'}"

        # 1. KIỂM TRA IDEMPOTENCY: Không tạo job trùng lặp nếu tác vụ tương tự đang queued / processing / completed
        try:
            existing_id = job_operations.find_job_by_idempotency(idemp_key)
            if existing_id:
                return existing_id
        except Exception as e:
            logger.warning(f"Lỗi kiểm tra idempotency qua Gateway: {e}")
            if settings.IS_PRODUCTION:
                raise RuntimeError(f"Lỗi kiểm tra idempotency qua Gateway trên production: {e}")

        if not settings.IS_PRODUCTION:
            for j_id, j in _jobs.items():
                if j.get("idempotency_key") == idemp_key and j.get("status") in ("queued", "processing", "completed"):
                    return j_id

        job_id = f"job_{secrets.token_hex(12)}"
        if action == "upscale" and scale and not target_format:
            target_format = f"{scale}x"

        initial_event = {
            "timestamp": now_dt,
            "status": "queued",
            "progress": 0,
            "detail": f"Khởi tạo công việc {action} cho artifact {artifact_id or ''}"
        }
        job_record = {
            "schema_version": 1,
            "job_id": job_id,
            "action": action,
            "artifact_id": artifact_id,
            "format": target_format,
            "scale": scale,
            "status": "queued",
            "progress": 0,
            "retries": 0,
            "attempt": 0,
            "max_attempts": MAX_RETRIES,
            "lease_owner": None,
            "lease_expires_at": None,
            "available_at": now_dt,
            "heartbeat_at": None,
            "idempotency_key": idemp_key,
            "result_url": None,
            "download_url": None,
            "media_type": None,
            "error": None,
            "owner_id": clean_owner_id,
            "request_id": request_id,
            "events": [initial_event],
            "created_at": now_dt,
            "updated_at": now_dt
        }

        if not settings.IS_PRODUCTION:
            async with _jobs_lock:
                _jobs[job_id] = copy.deepcopy(job_record)

        # Đồng bộ bền vững vào MongoDB qua Gateway
        try:
            # Lọc chính xác các trường được phép của MongoJobRecord để tuân thủ strict JSON schema và extra="forbid"
            allowed_mongo_fields = {
                "schema_version", "job_id", "owner_id", "request_id", "idempotency_key",
                "action", "artifact_id", "format", "status", "progress", "attempt",
                "max_attempts", "retries", "lease_owner", "lease_expires_at",
                "heartbeat_at", "available_at", "sanitized_error", "result_url",
                "media_type", "error", "events", "created_at", "updated_at", "expires_at"
            }
            mongo_doc = {k: v for k, v in job_record.items() if k in allowed_mongo_fields}
            job_operations.create_job_record(mongo_doc)
        except Exception as e:
            logger.error(f"Lỗi lưu job qua Gateway: {e}")
            if settings.IS_PRODUCTION:
                raise RuntimeError(f"Không thể lưu job vào cơ sở dữ liệu qua Gateway trên production: {e}")

        return job_id

    @staticmethod
    async def update_job(
        job_id: str,
        status: Optional[str] = None,
        progress: Optional[int] = None,
        retries: Optional[int] = None,
        attempt: Optional[int] = None,
        result_url: Optional[str] = None,
        download_url: Optional[str] = None,
        media_type: Optional[str] = None,
        error: Optional[Dict[str, Any]] = None,
        event_detail: Optional[str] = None,
        available_at: Optional[datetime] = None,
        worker_id: Optional[str] = None
    ):
        """Cập nhật tiến trình và ghi nhật ký sự kiện công việc (kiểm soát lease và checkpoint hủy)."""
        now_dt = datetime.now(timezone.utc)

        if not settings.IS_PRODUCTION:
            async with _jobs_lock:
                if job_id in _jobs:
                    job = _jobs[job_id]
                    if job.get("status") == "cancelled" and status in ("processing", "completed"):
                        return

                    if status:
                        job["status"] = status
                        if status in ("completed", "failed", "cancelled"):
                            job["lease_owner"] = None
                            job["lease_expires_at"] = None

                    if progress is not None:
                        job["progress"] = progress
                    if retries is not None:
                        job["retries"] = retries
                    if attempt is not None:
                        job["attempt"] = attempt
                    if available_at is not None:
                        job["available_at"] = available_at
                    if result_url:
                        job["result_url"] = result_url
                    if download_url:
                        job["download_url"] = download_url
                    if media_type:
                        job["media_type"] = media_type
                    if error:
                        job["error"] = error
                        job["sanitized_error"] = error.get("message") if isinstance(error, dict) else str(error)
                    job["updated_at"] = now_dt

                    # Ghi sự kiện tiến trình
                    evt = {
                        "timestamp": now_dt,
                        "status": job["status"],
                        "progress": job["progress"],
                        "detail": event_detail or f"Trạng thái: {job['status']} ({job['progress']}%)"
                    }
                    if "events" not in job or not isinstance(job["events"], list):
                        job["events"] = []
                    job["events"].append(evt)
                    job["events"] = job["events"][-30:]

        # Cập nhật qua Gateway atomic
        try:
            job_operations.update_job_record(
                job_id=job_id,
                status=status,
                progress=progress,
                retries=retries,
                attempt=attempt,
                result_url=result_url,
                media_type=media_type,
                error=error,
                sanitized_error=error.get("message") if isinstance(error, dict) else (str(error) if error else None),
                event_detail=event_detail,
                available_at=available_at,
                worker_id=worker_id,
            )
        except Exception as e:
            logger.warning(f"Lỗi cập nhật job qua Gateway: {e}")
            if settings.IS_PRODUCTION:
                raise RuntimeError(f"Lỗi cập nhật job qua Gateway trên production: {e}")

    @staticmethod
    async def cancel_job(job_id: str, requester_id: Optional[str] = None, is_admin: bool = False, principal: Any = None) -> bool:
        """Hủy công việc đang chờ hoặc đang xử lý."""
        job = JobQueueManager.get_job(job_id, requester_id=requester_id, is_admin=is_admin, principal=principal)
        if not job:
            return False
        if job.get("status") in ("completed", "failed", "cancelled"):
            return False

        await JobQueueManager.update_job(
            job_id,
            status="cancelled",
            progress=0,
            event_detail="Công việc đã được hủy theo yêu cầu của người dùng"
        )
        return True

    @staticmethod
    def get_job_events(job_id: str, requester_id: Optional[str] = None, is_admin: bool = False, principal: Any = None) -> List[Dict[str, Any]]:
        """Lấy lịch sử sự kiện của công việc."""
        job = JobQueueManager.get_job(job_id, requester_id=requester_id, is_admin=is_admin, principal=principal)
        if not job:
            return []
        return job.get("events", [])

    @staticmethod
    def run_in_background(job_id: str, coro_or_func: Callable, *args, **kwargs):
        """
        Khởi chạy worker nền cho môi trường phát triển / kiểm thử local.
        Trong production, các job được đẩy bền vững vào MongoDB và được xử lý bởi ArtifactWorker độc lập.
        """
        worker_id = f"worker_{secrets.token_hex(4)}"

        async def _worker():
            retries = 0
            while retries <= MAX_RETRIES:
                raw_job = JobQueueManager.get_job(job_id)
                if raw_job and raw_job.get("status") == "cancelled":
                    logger.info(f"[Job {job_id}] Đã bị hủy trước khi worker bắt đầu, dừng ngay.")
                    return

                claimed = MongoLeaseQueueAdapter.claim_next_job(worker_id, specific_job_id=job_id)
                if not claimed:
                    # Chờ thêm một chút đề phòng lệch đồng hồ (clock drift) giữa client và MongoDB Atlas
                    await asyncio.sleep(0.15)
                    claimed = MongoLeaseQueueAdapter.claim_next_job(worker_id, specific_job_id=job_id)

                if not claimed:
                    current = JobQueueManager.get_job(job_id)
                    if current and current.get("status") == "cancelled":
                        return
                    logger.info(f"[Job {job_id}] Không lấy được lease; worker local dừng để tránh xử lý trùng.")
                    return

                try:
                    await JobQueueManager.update_job(
                        job_id,
                        status="processing",
                        progress=25,
                        retries=retries,
                        event_detail=f"Bắt đầu xử lý tác vụ nền (lần {retries + 1})",
                        worker_id=worker_id
                    )

                    MongoLeaseQueueAdapter.heartbeat(job_id, worker_id)

                    try:
                        if asyncio.iscoroutinefunction(coro_or_func):
                            res = await asyncio.wait_for(coro_or_func(*args, **kwargs), timeout=DEFAULT_JOB_TIMEOUT_SECONDS)
                        else:
                            res = await asyncio.wait_for(asyncio.to_thread(coro_or_func, *args, **kwargs), timeout=DEFAULT_JOB_TIMEOUT_SECONDS)
                    except asyncio.TimeoutError:
                        raise ArtifactException(
                            error_code=ERROR_JOB_TIMEOUT,
                            message=f"Tác vụ {job_id} đã vượt quá giới hạn thời gian thực thi ({DEFAULT_JOB_TIMEOUT_SECONDS}s)",
                            job_id=job_id,
                            stage="job_execution",
                            retryable=False
                        )

                    raw_job = JobQueueManager.get_job(job_id)
                    if raw_job and raw_job.get("status") == "cancelled":
                        logger.info(f"[Job {job_id}] Đã bị hủy trong quá trình thực thi, không ghi đè completed.")
                        return

                    result_url = res.get("url") if isinstance(res, dict) else None
                    download_url = res.get("download_url") if isinstance(res, dict) else None
                    media_type = res.get("media_type") if isinstance(res, dict) else None
                    await JobQueueManager.update_job(
                        job_id,
                        status="completed",
                        progress=100,
                        result_url=result_url,
                        download_url=download_url,
                        media_type=media_type,
                        event_detail="Tác vụ hoàn thành thành công",
                        worker_id=worker_id
                    )
                    return
                except ArtifactException as a_err:
                    if a_err.retryable and retries < MAX_RETRIES:
                        retries += 1
                        backoff = min(0.1 * (2 ** (retries - 1)), 2.0)
                        now_dt = datetime.now(timezone.utc)
                        next_available = now_dt + timedelta(seconds=backoff)
                        await JobQueueManager.update_job(
                            job_id,
                            status="queued",
                            retries=retries,
                            available_at=next_available,
                            event_detail=f"Thử lại do lỗi có thể khôi phục ({retries}/{MAX_RETRIES})...",
                            worker_id=worker_id
                        )
                        await asyncio.sleep(backoff)
                        continue

                    await JobQueueManager.update_job(
                        job_id,
                        status="failed",
                        progress=0,
                        error=a_err.to_dict(),
                        event_detail=f"Lỗi: {a_err.message}",
                        worker_id=worker_id
                    )
                    return
                except Exception as ex:
                    logger.error(f"[Job {job_id}] Lỗi thực thi: {ex}\n{traceback.format_exc()}")
                    if retries < MAX_RETRIES:
                        retries += 1
                        backoff = min(0.1 * (2 ** (retries - 1)), 2.0)
                        now_dt = datetime.now(timezone.utc)
                        next_available = now_dt + timedelta(seconds=backoff)
                        await JobQueueManager.update_job(
                            job_id,
                            status="queued",
                            retries=retries,
                            available_at=next_available,
                            event_detail=f"Thử lại do sự cố thực thi ({retries}/{MAX_RETRIES})...",
                            worker_id=worker_id
                        )
                        await asyncio.sleep(backoff)
                        continue

                    err_dict = {
                        "error_code": "RENDER_JOB_FAILED",
                        "message": "Không thể hoàn thành quá trình dựng tài nguyên. Vui lòng thử lại sau.",
                        "job_id": job_id,
                        "stage": "job_execution",
                        "retryable": False
                    }
                    await JobQueueManager.update_job(
                        job_id,
                        status="failed",
                        progress=0,
                        error=err_dict,
                        event_detail="Lỗi thực thi công việc nền",
                        worker_id=worker_id
                    )
                    return

        # Chỉ chạy in-process task khi trong môi trường dev/test
        if not settings.IS_PRODUCTION:
            asyncio.create_task(_worker())
        else:
            logger.info(f"[Durable Queue] Job {job_id} đã được lưu bền vững qua Gateway, chờ ArtifactWorker claim.")
