"""
artifact_worker.py
Tiến trình Worker độc lập cho các tác vụ nền nặng (Durable Background Queue):
- Dựng tài liệu Excel (.xlsx), Word (.docx), PDF (.pdf), ảnh Raster (.png, .webp).
- Upscale hình ảnh theo yêu cầu.
- Atomic Lease Claiming qua MongoDB find_one_and_update.
- Heartbeat định kỳ gia hạn lease trong suốt quá trình xử lý.
- Dừng ngay nếu mất lease và KHÔNG ghi đè kết quả đã mất quyền.
- Checkpoint hủy tác vụ (cancellation checkpoints).
- Retry tự động với exponential backoff.
- Graceful shutdown khi nhận tín hiệu kết thúc tiến trình (SIGINT, SIGTERM).
"""
import asyncio
import logging
import os
import secrets
import signal
import sys
import time
import traceback
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Optional

# Đảm bảo đường dẫn gốc import được backend modules
ROOT_DIR = Path(__file__).resolve().parent.parent.parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from backend.app.config import settings
from backend.app.services.job_queue import (
    JobQueueManager,
    MongoLeaseQueueAdapter,
    DEFAULT_LEASE_SECONDS,
    MAX_RETRIES
)
from backend.app.telemetry.errors import ArtifactException, ERROR_JOB_TIMEOUT

logger = logging.getLogger("huit_chatbot.artifact_worker")
WORKER_HEARTBEAT_FILE = Path(os.getenv("WORKER_HEARTBEAT_FILE", "/tmp/huit_worker_heartbeat"))


def _write_process_heartbeat() -> None:
    """Cập nhật dấu sống để Docker healthcheck phát hiện worker bị treo vòng lặp."""
    try:
        WORKER_HEARTBEAT_FILE.write_text(str(time.time()), encoding="ascii")
    except OSError as exc:
        logger.warning("Không thể cập nhật worker heartbeat: %s", type(exc).__name__)


class ArtifactWorker:
    """
    Worker xử lý tác vụ nền độc lập, hỗ trợ scale ngang trên nhiều instance/container.
    """

    def __init__(
        self,
        worker_id: Optional[str] = None,
        lease_seconds: int = DEFAULT_LEASE_SECONDS,
        heartbeat_interval: int = 15,
        poll_interval: float = 1.0,
        task_timeout: int = 120
    ):
        self.worker_id = worker_id or f"worker_{secrets.token_hex(6)}"
        self.lease_seconds = lease_seconds
        self.heartbeat_interval = heartbeat_interval
        self.poll_interval = poll_interval
        self.task_timeout = task_timeout
        self._running = False
        self._shutdown_event = asyncio.Event()
        self._current_job_id: Optional[str] = None

    def stop(self):
        """Kích hoạt dừng worker an toàn."""
        logger.info(f"[{self.worker_id}] Nhận tín hiệu dừng, hoàn tất công việc hiện tại...")
        self._running = False
        self._shutdown_event.set()

    async def execute_task(self, job: Dict[str, Any]) -> Dict[str, Any]:
        """
        Thực thi nghiệp vụ cốt lõi theo action của job:
        - render: dựng file và lưu vào StorageAdapter
        - export: xuất file sang định dạng yêu cầu và lưu vào StorageAdapter
        - upscale: phóng to hình ảnh 2x/4x và lưu vào StorageAdapter
        - Trả về URL an toàn và Signed Download URL, không kích hoạt re-render.
        """
        action = job.get("action", "render")
        artifact_id = job.get("artifact_id")
        target_format = (job.get("format") or "xlsx").lower().strip()
        owner_id = job.get("owner_id")

        if action in ("render", "export"):
            from backend.app.services.artifact_service import export_artifact
            from backend.app.services.asset_store import ArtifactStore, AssetStore, compute_derivative_hash
            from backend.app.services.auth_service import create_download_signature

            raw_bytes, media_type, filename = await asyncio.to_thread(
                export_artifact,
                artifact_id=artifact_id,
                format_str=target_format,
                requester_id=owner_id,
                is_admin=False
            )

            art = ArtifactStore.get_by_id(artifact_id)
            blob_id = (art.get("blob_id") or artifact_id) if art else artifact_id
            export_d_hash = compute_derivative_hash(blob_id, scale=1, file_ext=target_format, quality="standard")
            existing_export = AssetStore.find_by_hash(export_d_hash)
            storage_key = existing_export.get("storage_key") if existing_export else None

            download_url = None
            if storage_key:
                sig, exp = create_download_signature(storage_key, expires_in=86400)
                download_url = f"/api/artifacts/download/{storage_key}?sig={sig}&expires={exp}"

            result_url = f"/api/artifacts/{artifact_id}/file?format={target_format}"
            return {
                "url": result_url,
                "download_url": download_url or result_url,
                "media_type": media_type,
                "bytes": len(raw_bytes),
                "filename": filename
            }

        elif action == "upscale":
            from backend.app.services.artifact_service import upscale_artifact
            from backend.app.services.asset_store import AssetStore, ArtifactStore
            from backend.app.services.auth_service import create_download_signature

            scale_val = job.get("scale")
            if not scale_val:
                fmt_str = str(job.get("format") or "")
                if "x" in fmt_str:
                    try:
                        scale_val = int(fmt_str.replace("x", ""))
                    except Exception:
                        scale_val = 2
                else:
                    scale_val = 2
            scale = int(scale_val)
            res = await upscale_artifact(
                artifact_id=artifact_id,
                scale=scale,
                requester_id=owner_id,
                is_admin=False
            )
            upscaled_id = res.get("upscaled_id")
            blob_id = None
            if upscaled_id:
                art_doc = ArtifactStore.get_by_id(upscaled_id)
                blob_id = (art_doc.get("blob_id") if art_doc else None) or upscaled_id
            upscaled_asset = AssetStore.get_by_id(blob_id) if blob_id else None
            storage_key = upscaled_asset.get("storage_key") if upscaled_asset else None
            download_url = None
            if storage_key:
                sig, exp = create_download_signature(storage_key, expires_in=86400)
                download_url = f"/api/artifacts/download/{storage_key}?sig={sig}&expires={exp}"
            elif upscaled_id:
                sig, exp = create_download_signature(upscaled_id, expires_in=86400)
                download_url = f"/api/artifacts/{upscaled_id}/file?format=png&sig={sig}&expires={exp}"

            result_url = download_url or res.get("url") or f"/api/artifacts/{artifact_id}/file?format=png"
            return {
                "url": result_url,
                "download_url": result_url,
                "media_type": "image/png",
                "bytes": res.get("bytes", 0),
                "scale": scale,
                "upscaled_id": upscaled_id
            }

        else:
            raise ValueError(f"Hành động không được hỗ trợ: {action}")

    async def process_job(self, job: Dict[str, Any]) -> bool:
        """
        Quy trình xử lý một job có lease atomic:
        1. Checkpoint: kiểm tra xem job đã bị cancelled chưa.
        2. Khởi tạo heartbeat background loop.
        3. Thực thi nghiệp vụ.
        4. Checkpoint: kiểm tra trạng thái hủy và kiểm tra mất lease.
        5. Cập nhật completed hoặc retry/failed.
        """
        job_id = job["job_id"]
        self._current_job_id = job_id
        attempt = job.get("attempt", 1)
        max_attempts = job.get("max_attempts", MAX_RETRIES)

        logger.info(f"[{self.worker_id}] Bắt đầu xử lý job {job_id} (Lần thử {attempt}/{max_attempts})")

        # CHECKPOINT 1: Kiểm tra trạng thái đã bị hủy trước đó
        fresh_job = JobQueueManager.get_job(job_id, is_admin=True)
        if fresh_job and fresh_job.get("status") == "cancelled":
            logger.info(f"[{self.worker_id}] Job {job_id} đã bị hủy trước khi xử lý, dừng ngay.")
            self._current_job_id = None
            return False

        # Khởi tạo heartbeat và cờ mất lease
        lease_lost_event = asyncio.Event()
        heartbeat_task = None

        async def _heartbeat_loop():
            while not lease_lost_event.is_set():
                await asyncio.sleep(self.heartbeat_interval)
                if lease_lost_event.is_set():
                    break
                ok = MongoLeaseQueueAdapter.heartbeat(job_id, self.worker_id, extend_seconds=self.lease_seconds)
                if not ok:
                    logger.warning(f"[{self.worker_id}] Mất lease của job {job_id}! Dừng cập nhật kết quả.")
                    lease_lost_event.set()
                    break

        heartbeat_task = asyncio.create_task(_heartbeat_loop())

        try:
            # Cập nhật trạng thái bắt đầu xử lý
            await JobQueueManager.update_job(
                job_id,
                status="processing",
                progress=20,
                event_detail=f"Worker {self.worker_id} đang xử lý (lần {attempt})",
                worker_id=self.worker_id
            )

            # Thực thi tác vụ (có thể dài vài giây)
            task_future = asyncio.create_task(self.execute_task(job))

            # Chờ tác vụ hoàn thành hoặc phát hiện mất lease hoặc timeout
            done, pending = await asyncio.wait(
                [task_future, asyncio.create_task(lease_lost_event.wait())],
                timeout=self.task_timeout,
                return_when=asyncio.FIRST_COMPLETED
            )

            for p in pending:
                p.cancel()

            # CHECKPOINT TIMEOUT: Nếu không task nào hoàn thành trong thời hạn timeout
            if not done or task_future not in done:
                if lease_lost_event.is_set():
                    logger.error(f"[{self.worker_id}] Job {job_id}: Đã mất lease cho worker khác, hủy bỏ ghi nhận hoàn thành.")
                    return False
                raise ArtifactException(
                    error_code=ERROR_JOB_TIMEOUT,
                    message=f"Tác vụ {job_id} đã vượt quá giới hạn thời gian thực thi ({self.task_timeout}s)",
                    job_id=job_id,
                    stage="worker_execution",
                    retryable=False
                )

            # CHECKPOINT 2: Nếu mất lease trong lúc đang chạy
            if lease_lost_event.is_set():
                logger.error(f"[{self.worker_id}] Job {job_id}: Đã mất lease cho worker khác, hủy bỏ ghi nhận hoàn thành.")
                return False

            # Lấy kết quả từ task
            res = await task_future

            # CHECKPOINT 3: Kiểm tra lại xem job có bị hủy giữa chừng không
            latest_status = JobQueueManager.get_job(job_id, is_admin=True)
            if latest_status and latest_status.get("status") == "cancelled":
                logger.info(f"[{self.worker_id}] Job {job_id} đã bị hủy trong quá trình chạy, không ghi đè completed.")
                return False

            # Ghi nhận kết quả thành công
            download_url = res.get("download_url") if isinstance(res, dict) else None
            result_url = download_url or (res.get("url") if isinstance(res, dict) else None)
            media_type = res.get("media_type") if isinstance(res, dict) else None

            await JobQueueManager.update_job(
                job_id,
                status="completed",
                progress=100,
                result_url=result_url,
                download_url=download_url,
                media_type=media_type,
                event_detail="Tác vụ hoàn thành thành công",
                worker_id=self.worker_id
            )
            logger.info(f"[{self.worker_id}] Hoàn thành xuất sắc job {job_id}")
            return True

        except ArtifactException as a_err:
            logger.warning(f"[{self.worker_id}] Lỗi ArtifactException job {job_id}: {a_err}")
            if a_err.retryable and attempt < max_attempts:
                backoff = min(1.0 * (2 ** (attempt - 1)), 15.0)
                next_avail = datetime.now(timezone.utc) + timedelta(seconds=backoff)
                await JobQueueManager.update_job(
                    job_id,
                    status="queued",
                    progress=0,
                    retries=attempt,
                    attempt=attempt,
                    available_at=next_avail,
                    event_detail=f"Thử lại lần {attempt + 1}/{max_attempts} sau {backoff:.1f}s do lỗi khôi phục được",
                    worker_id=self.worker_id
                )
            else:
                await JobQueueManager.update_job(
                    job_id,
                    status="failed",
                    progress=0,
                    retries=attempt,
                    attempt=attempt,
                    error=a_err.to_dict(),
                    event_detail=f"Thất bại vĩnh viễn: {a_err.message}",
                    worker_id=self.worker_id
                )
            return False

        except Exception as ex:
            logger.error(f"[{self.worker_id}] Lỗi hệ thống khi xử lý job {job_id}: {ex}\n{traceback.format_exc()}")
            if attempt < max_attempts:
                backoff = min(1.0 * (2 ** (attempt - 1)), 15.0)
                next_avail = datetime.now(timezone.utc) + timedelta(seconds=backoff)
                await JobQueueManager.update_job(
                    job_id,
                    status="queued",
                    progress=0,
                    retries=attempt,
                    attempt=attempt,
                    available_at=next_avail,
                    event_detail=f"Thử lại lần {attempt + 1}/{max_attempts} sau sự cố",
                    worker_id=self.worker_id
                )
            else:
                err_payload = {
                    "error_code": "WORKER_EXECUTION_FAILED",
                    "message": "Không thể hoàn thành xử lý file sau các lần thử"
                }
                await JobQueueManager.update_job(
                    job_id,
                    status="failed",
                    progress=0,
                    error=err_payload,
                    event_detail="Quá số lần thử tối đa, đánh dấu thất bại",
                    worker_id=self.worker_id
                )
            return False

        finally:
            lease_lost_event.set()
            if heartbeat_task and not heartbeat_task.done():
                heartbeat_task.cancel()
            self._current_job_id = None

    async def run_once(self) -> bool:
        """Claim và xử lý đúng 1 job nếu có. Trả về True nếu có job được xử lý, False nếu trống."""
        claimed = MongoLeaseQueueAdapter.claim_next_job(self.worker_id, lease_seconds=self.lease_seconds)
        if not claimed:
            return False
        await self.process_job(claimed)
        return True

    async def run_loop(self):
        """Vòng lặp lắng nghe và xử lý job liên tục cho đến khi nhận tín hiệu dừng."""
        self._running = True
        logger.info(f"[{self.worker_id}] Khởi động vòng lặp Worker lắng nghe hàng đợi...")

        while self._running:
            try:
                _write_process_heartbeat()
                processed = await self.run_once()
                _write_process_heartbeat()
                if not processed:
                    # Hàng đợi trống, nghỉ ngơi poll_interval
                    await asyncio.sleep(self.poll_interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[{self.worker_id}] Lỗi vòng lặp worker: {e}")
                await asyncio.sleep(self.poll_interval)

        logger.info(f"[{self.worker_id}] Worker đã dừng an toàn.")


async def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    worker = ArtifactWorker()

    # Đăng ký signal handlers cho Graceful Shutdown
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, worker.stop)
        except (NotImplementedError, RuntimeError):
            # Trên Windows có thể không add_signal_handler được trực tiếp cho loop
            pass

    try:
        await worker.run_loop()
    except KeyboardInterrupt:
        worker.stop()


if __name__ == "__main__":
    asyncio.run(main())
