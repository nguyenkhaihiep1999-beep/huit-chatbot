"""
test_resilient_queue_worker.py
Unit tests kiểm thử độ bền bỉ và tính chịu lỗi của Queue & Worker (Phase 5):
1. Test claiming with expired lease (tự động thu hồi lease khi worker crash).
2. Test rejection when attempt >= max_attempts (không claim lại job đã quá số lần thử).
3. Test cancel during execution preventing completed overwrite (checkpoint hủy tác vụ).
4. Test heartbeat extending lease (gia hạn lease thành công).
5. Test execution timeout handling (hủy tác vụ và báo lỗi khi timeout).
"""
import asyncio
from datetime import datetime, timedelta, timezone
import pytest

from backend.app.services.job_queue import (
    JobQueueManager,
    MongoLeaseQueueAdapter,
    clear_jobs_for_testing,
    MAX_RETRIES,
)
from backend.app.workers.artifact_worker import ArtifactWorker
from backend.app.telemetry.errors import ArtifactException, ERROR_JOB_TIMEOUT


@pytest.fixture(autouse=True)
def setup_teardown():
    clear_jobs_for_testing()
    yield
    clear_jobs_for_testing()


def test_expired_lease_claim():
    """Worker B claim được job khi lease của Worker A đã hết hạn."""
    async def _run():
        job_id = await JobQueueManager.create_job(
            action="render",
            artifact_id="art_test_lease_1",
            target_format="xlsx"
        )

        # Worker A claim
        worker_a = "worker_alpha"
        job_a = MongoLeaseQueueAdapter.claim_next_job(worker_a, lease_seconds=1, specific_job_id=job_id)
        assert job_a is not None
        assert job_a["job_id"] == job_id
        assert job_a["lease_owner"] == worker_a

        # Worker B thử claim ngay khi Worker A còn lease -> thất bại
        worker_b = "worker_beta"
        job_b_too_early = MongoLeaseQueueAdapter.claim_next_job(worker_b, specific_job_id=job_id)
        assert job_b_too_early is None

        # Chờ lease hết hạn (1 giây)
        await asyncio.sleep(1.1)

        # Worker B claim lại -> thành công do lease Worker A đã hết hạn
        job_b_recovered = MongoLeaseQueueAdapter.claim_next_job(worker_b, lease_seconds=60, specific_job_id=job_id)
        assert job_b_recovered is not None
        assert job_b_recovered["job_id"] == job_id
        assert job_b_recovered["lease_owner"] == worker_b
        assert job_b_recovered["attempt"] == 2

    asyncio.run(_run())


def test_rejection_when_max_attempts_reached():
    """Job đã đạt attempt >= max_attempts sẽ không thể bị claim lại dù ở queued hay processing expired."""
    async def _run():
        job_id = await JobQueueManager.create_job(
            action="render",
            artifact_id="art_test_max_att",
            target_format="docx"
        )

        # Giả lập job đã retry 3 lần và đạt max attempts
        await JobQueueManager.update_job(
            job_id,
            status="queued",
            retries=MAX_RETRIES,
            attempt=MAX_RETRIES
        )

        # Worker claim -> Phải trả về None vì đã đạt max_attempts
        claimed = MongoLeaseQueueAdapter.claim_next_job("worker_gamma", specific_job_id=job_id)
        assert claimed is None

    asyncio.run(_run())


def test_cancel_during_execution_prevents_completed_overwrite():
    """Khi job bị cancel trong quá trình worker đang chạy, worker không được ghi đè status='completed'."""
    async def _run():
        job_id = await JobQueueManager.create_job(
            action="render",
            artifact_id="art_test_cancel_checkpoint",
            target_format="pdf"
        )

        worker_id = "worker_delta"
        claimed = MongoLeaseQueueAdapter.claim_next_job(worker_id, specific_job_id=job_id)
        assert claimed is not None

        # Người dùng gửi yêu cầu hủy
        cancelled = await JobQueueManager.cancel_job(job_id)
        assert cancelled is True

        # Worker hoàn thành sau đó và cố ghi completed
        await JobQueueManager.update_job(
            job_id,
            status="completed",
            progress=100,
            result_url="/test/file.pdf",
            worker_id=worker_id
        )

        # Trạng thái cuối cùng phải vẫn là 'cancelled', không phải 'completed'
        final_job = JobQueueManager.get_job(job_id)
        assert final_job["status"] == "cancelled"
        assert final_job["progress"] == 0

    asyncio.run(_run())


def test_heartbeat_extends_lease():
    """Heartbeat gia hạn lease_expires_at thành công."""
    async def _run():
        job_id = await JobQueueManager.create_job(
            action="render",
            artifact_id="art_test_heartbeat",
            target_format="xlsx"
        )

        worker_id = "worker_heartbeat"
        claimed = MongoLeaseQueueAdapter.claim_next_job(worker_id, lease_seconds=10, specific_job_id=job_id)
        assert claimed is not None

        orig_exp = claimed.get("lease_expires_at")

        # Chờ 0.2s rồi gửi heartbeat với thời gian kéo dài 30s
        await asyncio.sleep(0.2)
        success = MongoLeaseQueueAdapter.heartbeat(job_id, worker_id, extend_seconds=30)
        assert success is True

        updated_job = JobQueueManager.get_job(job_id)
        new_exp = updated_job.get("lease_expires_at")
        assert new_exp is not None
        assert new_exp != orig_exp

    asyncio.run(_run())


def test_worker_task_timeout():
    """Worker hủy và đánh dấu lỗi khi tác vụ vượt quá task_timeout."""
    async def _run():
        worker = ArtifactWorker(worker_id="worker_timeout_tester", task_timeout=1)

        # Giả lập execute_task chạy lâu hơn timeout (2.5s)
        async def fake_slow_task(job):
            await asyncio.sleep(2.5)
            return {"url": "dummy"}

        worker.execute_task = fake_slow_task

        job_id = await JobQueueManager.create_job(
            action="render",
            artifact_id="art_slow_job",
            target_format="xlsx"
        )

        claimed = MongoLeaseQueueAdapter.claim_next_job(worker.worker_id, specific_job_id=job_id)
        assert claimed is not None

        # Xử lý job qua worker
        success = await worker.process_job(claimed)
        assert success is False

        # Job phải ở trạng thái failed hoặc queued retry do timeout
        failed_job = JobQueueManager.get_job(job_id)
        assert failed_job["status"] in ("failed", "queued")
        if failed_job["status"] == "failed":
            assert failed_job["error"]["error_code"] == ERROR_JOB_TIMEOUT

    asyncio.run(_run())
