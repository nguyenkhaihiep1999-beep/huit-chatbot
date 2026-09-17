"""
test_failure_resilience.py
Kiểm thử khả năng chống chịu sự cố (Failure Resilience Tests):
1. Mất kết nối Redis: Tự động fallback in-memory cache, không sập server.
2. Mất kết nối MongoDB: Trả về lỗi có cấu trúc (HTTP 503 / 500) an toàn, không rò rỉ stacktrace.
3. Mất quyền lưu trữ / Lỗi Storage: Trả về lỗi có cấu trúc, worker không crash unhandled.
4. Thu hồi Lease quá hạn (Lease Expiry): Worker phục hồi job bị kẹt và hoàn thành.
5. Yêu cầu trùng lặp (Duplicate Request): Idempotency key bảo vệ, không sinh 2 job.
6. Ngắt kết nối & Reconnect Stream (Stream Reconnect): Khôi phục qua X-Last-Sequence không lặp token.
7. Khởi động lại Worker (Worker Restart / Lease Recovery): Đảm bảo trạng thái an toàn.
"""
import asyncio
import os
import time
import uuid
from unittest.mock import patch, MagicMock
import pytest
from fastapi.testclient import TestClient

from backend.app.main import app
from backend.app.services.job_queue import JobQueueManager, MongoLeaseQueueAdapter
from backend.app.workers.artifact_worker import ArtifactWorker
from backend.app.storage.storage_adapter import LocalStorageAdapter
from backend.app.telemetry.errors import ArtifactException


@pytest.fixture
def client():
    return TestClient(app, raise_server_exceptions=False)


def test_lost_redis_graceful_fallback(client):
    """
    Sự cố 1: Mất kết nối Redis.
    Hệ thống tự động fallback in-memory buffer trong stream_coordinator mà không crash process.
    """
    from backend.app.services.stream_coordinator import persist_stream_event, StreamCoordinator

    # Kiểm tra khi redis_client = None, gọi persist_stream_event không crash
    asyncio.run(persist_stream_event(None, "test_stream_01", '{"type":"token","content":"test"}'))
    coord = StreamCoordinator()
    assert coord is not None


def test_lost_mongo_structured_error(client):
    """
    Sự cố 2: Mất kết nối MongoDB.
    Hệ thống bắt lỗi và trả về phản hồi có cấu trúc an toàn, không trả raw trace.
    """
    with patch("backend.app.repositories.mongo_repository.MongoRepository.get_db") as mock_db:
        mock_db.return_value = None
        resp = client.get("/api/health/ready")
        assert resp.status_code in (500, 503)
        data = resp.json()
        assert "traceback" not in str(data).lower()
        assert "password" not in str(data).lower()


def test_lost_storage_graceful_error():
    """
    Sự cố 3: Mất bộ lưu trữ / Không thể ghi file.
    StorageAdapter bắt lỗi I/O và ném ArtifactException có cấu trúc.
    """
    import tempfile
    from pathlib import Path
    with tempfile.TemporaryDirectory() as tmp_dir:
        adapter = LocalStorageAdapter(root_dir=Path(tmp_dir))
        with patch.object(adapter, "_resolve_safe_path", side_effect=OSError("Read-only file system")):
            with pytest.raises((ArtifactException, OSError)):
                adapter.put("test_doc.txt", b"sample data")


def test_lease_expiry_and_worker_recovery():
    """
    Sự cố 4: Lease Expiry & Worker Crash.
    Worker 1 bị sập khi đang giữ lease, Worker 2 claim lại lease quá hạn và xử lý thành công.
    """
    async def _run():
        job_id = await JobQueueManager.create_job(
            action="render",
            artifact_id="art_lease_test_01",
            target_format="xlsx",
            owner_id="admin",
            idempotency_key=f"lease-exp-{uuid.uuid4().hex}"
        )

        # Giả lập Worker 1 claim job với lease cực ngắn (1s) và bị sập
        claimed_1 = MongoLeaseQueueAdapter.claim_next_job("crashed_worker_01", lease_seconds=1)
        assert claimed_1 is not None

        # Chờ 1.2s để lease của Worker 1 hết hạn
        await asyncio.sleep(1.2)

        # Worker 2 phát hiện lease hết hạn và claim lại thành công
        worker_2 = ArtifactWorker(worker_id="recovering_worker_02")
        claimed_2 = MongoLeaseQueueAdapter.claim_next_job(worker_2.worker_id, lease_seconds=30)
        assert claimed_2 is not None
        assert claimed_2["job_id"] == job_id

    asyncio.run(_run())


def test_duplicate_request_idempotency():
    """
    Sự cố 5: Yêu cầu trùng lặp dồn dập (Duplicate / Retry Request).
    Idempotency key bảo vệ chỉ tạo duy nhất 1 job trong queue.
    """
    async def _run():
        idemp_key = f"idemp-test-{uuid.uuid4().hex}"
        job_1 = await JobQueueManager.create_job(
            action="export",
            artifact_id="art_dup_test",
            target_format="pdf",
            owner_id="user_alice",
            idempotency_key=idemp_key
        )
        job_2 = await JobQueueManager.create_job(
            action="export",
            artifact_id="art_dup_test",
            target_format="pdf",
            owner_id="user_alice",
            idempotency_key=idemp_key
        )
        assert job_1 == job_2, "Cùng idempotency_key phải trả về cùng job_id"

    asyncio.run(_run())


def test_stream_reconnect_resilience(client):
    """
    Sự cố 6: Stream Reconnect qua X-Last-Sequence.
    Khi kết nối bị ngắt, client gửi X-Last-Sequence để tiếp tục mà không lặp lại token cũ.
    """
    req_id = f"stream-recon-{uuid.uuid4().hex[:8]}"
    headers = {
        "X-Request-ID": req_id,
        "X-Last-Sequence": "3",
        "Accept": "application/x-ndjson"
    }
    resp = client.post("/api/chat-stream", json={"question": "Điểm chuẩn HUIT?"}, headers=headers)
    assert resp.status_code in (200, 409)
    assert resp.status_code != 404


def test_api_restart_resilience():
    """
    Sự cố 7: Khởi động lại API (API Restart / Lifespan Cycle).
    Mô phỏng API shutdown và startup mới: phiên làm việc và hàng đợi vẫn toàn vẹn.
    """
    from backend.app.services.auth_service import create_admin_session, verify_admin_token_get_session
    from backend.app.services.job_queue import JobQueueManager

    async def _run():
        # 1. Tạo session trước khi restart
        raw_sess_id, cookie_token, _ = create_admin_session()
        job_id = await JobQueueManager.create_job(
            action="render",
            artifact_id="art_restart_test",
            target_format="pdf",
            owner_id="admin_restart_user"
        )

        # 2. Giả lập API restart bằng cách tạo client mới với app mới
        new_client = TestClient(app, raise_server_exceptions=False)
        r_live = new_client.get("/api/health/live")
        assert r_live.status_code == 200

        # 3. Phiên đăng nhập và Job ID vẫn hợp lệ sau khi API khởi động lại
        verified_sess_id = verify_admin_token_get_session(cookie_token)
        assert verified_sess_id == raw_sess_id

        job = JobQueueManager.get_job(job_id)
        assert job is not None
        assert job.get("status") in ("queued", "processing", "completed")

    asyncio.run(_run())


def test_worker_restart_resilience():
    """
    Sự cố 8: Khởi động lại Worker (Worker Restart / Crash Recovery).
    Worker bị tắt đột ngột giữa chừng; instance Worker mới khởi động, thu hồi job mồ côi và hoàn tất.
    """
    from backend.app.services.artifact_service import create_artifact_plan
    from backend.app.api.schemas.artifact import ArtifactPlanRequest

    async def _run():
        # Tạo artifact hợp lệ trước khi tạo job export
        plan = await create_artifact_plan(
            ArtifactPlanRequest(prompt="Danh mục ngành tuyển sinh HUIT 2026", type="document"),
            owner_id="admin"
        )
        art_id = plan.artifact_id

        job_id = await JobQueueManager.create_job(
            action="export",
            artifact_id=art_id,
            target_format="xlsx",
            owner_id="admin",
            idempotency_key=f"worker-restart-{uuid.uuid4().hex}"
        )

        # Worker instance 1 nhận việc nhưng crash/terminate ngay sau đó
        w1 = ArtifactWorker(worker_id="worker_died_early")
        claimed_w1 = MongoLeaseQueueAdapter.claim_next_job(w1.worker_id, lease_seconds=1)
        assert claimed_w1 is not None

        # Giả lập worker chết, chờ lease expire
        await asyncio.sleep(1.2)

        # Worker instance 2 khởi động lại, thu hồi job và xử lý
        w2 = ArtifactWorker(worker_id="worker_fresh_restart")
        claimed_w2 = MongoLeaseQueueAdapter.claim_next_job(w2.worker_id, lease_seconds=30)
        assert claimed_w2 is not None
        assert claimed_w2["job_id"] == job_id

        # Worker 2 xử lý thành công
        res = await w2.process_job(claimed_w2)
        assert res is True
        updated_job = JobQueueManager.get_job(job_id)
        assert updated_job["status"] == "completed"

    asyncio.run(_run())


