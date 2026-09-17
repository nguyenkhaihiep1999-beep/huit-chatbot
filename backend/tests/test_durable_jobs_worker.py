"""
test_durable_jobs_worker.py
Bộ kiểm thử toàn diện cho hệ thống Durable Background Queue & Worker:
1. Exact HTTP 202: Mọi endpoint tạo job (render, export, upscale) phải trả đúng HTTP 202 (không chấp nhận 200).
2. GET file endpoint: Chỉ phục vụ file ĐÃ render, trả 404 FILE_NOT_RENDERED nếu chưa render, không chạy đồng bộ.
3. Idempotency: Gửi trùng lặp request trả lại đúng job_id đã có, không tạo job dư thừa.
4. Cross-owner: Chặn người dùng khác xem trạng thái job, hủy job, hoặc tải file private của chủ sở hữu.
5. Worker atomic lease claim & recovery: Worker 2 phục hồi lease khi Worker 1 gặp sự cố/hết hạn lease.
6. Worker retry & exponential backoff: Tự động retry khi gặp lỗi tạm thời với backoff tương ứng.
7. Worker cancellation checkpoints: Abort ngay trước khi chạy và chặn ghi đè completed nếu job đã bị cancel.
8. Export Word/Excel/PDF: Worker tạo file nhị phân chuẩn (DOCX/XLSX PK\\x03\\x04, PDF %PDF-) lưu vào StorageAdapter.
9. Upscale 2x/4x: Worker upscale ảnh, lưu derivative và cấp signed URL có chữ ký HMAC.
10. Zero Base64/Binary: MongoDB và events chỉ chứa metadata, tuyệt đối không chứa binary hay base64.
"""
import asyncio
import os
import re
import pytest
from datetime import datetime, timedelta, timezone
from fastapi.testclient import TestClient

from backend.app.main import app
from backend.app.config import settings
from backend.app.api.dependencies.auth import Principal, get_current_principal
from backend.app.api.schemas.artifact import ArtifactPlanRequest
from backend.app.services.artifact_service import create_artifact_plan
from backend.app.services.asset_store import AssetStore, ArtifactStore
from backend.app.services.job_queue import (
    JobQueueManager,
    MongoLeaseQueueAdapter,
    clear_jobs_for_testing,
    _jobs,
)
from backend.app.workers.artifact_worker import ArtifactWorker
from backend.app.storage.storage_adapter import get_storage_adapter
from backend.app.data_access.operations import job_operations

client = TestClient(app)

USER_ALICE = "user_alice_test"
USER_BOB = "user_bob_test"


def mock_principal(user_id: str, is_admin: bool = False) -> Principal:
    return Principal(
        user_id=user_id,
        is_admin=is_admin,
        is_authenticated=True,
        session_id=f"sess_{user_id}",
    )


@pytest.fixture(autouse=True)
def setup_test_artifacts():
    """Thiết lập dữ liệu mẫu và dọn dẹp trước mỗi test."""
    clear_jobs_for_testing()
    AssetStore.clear_memory_cache_for_testing()
    from backend.app.middleware.rate_limiter import clear_rate_limits_for_testing
    clear_rate_limits_for_testing()
    yield
    clear_jobs_for_testing()
    AssetStore.clear_memory_cache_for_testing()


def create_sample_artifact_sync(owner_id: str = USER_ALICE, prompt: str = "Học phí HUIT 2026") -> str:
    """Tạo artifact mẫu cho các test case đồng bộ."""
    app.dependency_overrides[get_current_principal] = lambda: mock_principal(owner_id)
    try:
        resp = client.post("/api/artifacts/plan", json={"prompt": prompt})
        assert resp.status_code == 200, f"Failed to create artifact: {resp.text}"
        return resp.json()["artifact_id"]
    finally:
        app.dependency_overrides.pop(get_current_principal, None)


async def create_sample_artifact_async(owner_id: str = USER_ALICE, prompt: str = "Học phí HUIT 2026") -> str:
    """Tạo artifact mẫu cho các test case bất đồng bộ."""
    req = ArtifactPlanRequest(prompt=prompt, user_id=owner_id)
    manifest = await create_artifact_plan(req, owner_id=owner_id)
    return manifest.artifact_id


# ============================================================================
# 1. TEST EXACT HTTP 202 RESPONSES
# ============================================================================
def test_exact_http_202_responses():
    """Xác minh POST render, export, upscale PHẢI trả đúng HTTP 202 (không chấp nhận 200)."""
    art_id = create_sample_artifact_sync(USER_ALICE, "Học phí HUIT 2026")
    app.dependency_overrides[get_current_principal] = lambda: mock_principal(USER_ALICE)

    try:
        # A. POST /api/artifacts/render (SVG) -> 202
        resp_render = client.post("/api/artifacts/render", json={"artifact_id": art_id, "format": "svg"})
        assert resp_render.status_code == 202, f"Expected 202 Accepted, got {resp_render.status_code}"
        data_render = resp_render.json()
        assert data_render["status"] == "queued"
        assert "job_id" in data_render
        assert data_render["check_status_url"] == f"/api/jobs/{data_render['job_id']}"

        # B. POST /api/artifacts/{id}/export (Word) -> 202
        resp_export_docx = client.post(f"/api/artifacts/{art_id}/export?format=docx")
        assert resp_export_docx.status_code == 202, f"Expected 202 Accepted, got {resp_export_docx.status_code}"
        data_docx = resp_export_docx.json()
        assert data_docx["status"] == "queued"
        assert "job_id" in data_docx
        assert data_docx["check_status_url"] == f"/api/jobs/{data_docx['job_id']}"

        # C. POST /api/artifacts/{id}/export (Excel) -> 202
        resp_export_xlsx = client.post(f"/api/artifacts/{art_id}/export?format=xlsx")
        assert resp_export_xlsx.status_code == 202, f"Expected 202 Accepted, got {resp_export_xlsx.status_code}"
        data_xlsx = resp_export_xlsx.json()
        assert data_xlsx["status"] == "queued"
        assert "job_id" in data_xlsx

        # D. POST /api/artifacts/{id}/upscale (2x) -> 202
        resp_upscale = client.post(f"/api/artifacts/{art_id}/upscale", json={"scale": 2})
        assert resp_upscale.status_code == 202, f"Expected 202 Accepted, got {resp_upscale.status_code}"
        data_upscale = resp_upscale.json()
        assert data_upscale["status"] == "queued"
        assert "job_id" in data_upscale
        assert data_upscale["check_status_url"] == f"/api/jobs/{data_upscale['job_id']}"

        # E. Cấm định dạng âm thanh/video -> 400 hoặc 422
        resp_audio = client.post("/api/artifacts/render", json={"artifact_id": art_id, "format": "mp3"})
        assert resp_audio.status_code in (400, 422)
        resp_video = client.post(f"/api/artifacts/{art_id}/export?format=mp4")
        assert resp_video.status_code in (400, 422)
    finally:
        app.dependency_overrides.clear()


# ============================================================================
# 2. TEST GET FILE NO SIDE-EFFECTS
# ============================================================================
def test_get_file_no_side_effects():
    """GET file chỉ tải kết quả đã render, trả 404 FILE_NOT_RENDERED nếu chưa render."""
    art_id = create_sample_artifact_sync(USER_ALICE, "Báo cáo tuyển sinh 2026")
    app.dependency_overrides[get_current_principal] = lambda: mock_principal(USER_ALICE)

    try:
        # File chưa render -> trả 404 FILE_NOT_RENDERED, không kích hoạt tác vụ nền
        initial_job_count = len(_jobs)
        resp_not_rendered = client.get(f"/api/artifacts/{art_id}/file?format=pdf")
        assert resp_not_rendered.status_code == 404
        assert resp_not_rendered.json()["error_code"] == "FILE_NOT_RENDERED"
        # Không có job nào được tạo ra bởi GET
        assert len(_jobs) == initial_job_count

        # Xử lý export qua worker
        async def _run_worker():
            worker = ArtifactWorker(worker_id="worker_pdf_exporter")
            job_id = await JobQueueManager.create_job(action="export", artifact_id=art_id, target_format="pdf", owner_id=USER_ALICE)
            MongoLeaseQueueAdapter.claim_next_job(worker.worker_id, specific_job_id=job_id)
            await worker.process_job(JobQueueManager.get_job(job_id))

        asyncio.run(_run_worker())

        # Sau khi file đã được lưu trong StorageAdapter -> GET tải về thành công (HTTP 200)
        resp_rendered = client.get(f"/api/artifacts/{art_id}/file?format=pdf")
        assert resp_rendered.status_code == 200
        assert resp_rendered.headers["content-type"].startswith("application/pdf")
        assert resp_rendered.content.startswith(b"%PDF-")
    finally:
        app.dependency_overrides.clear()


# ============================================================================
# 3. TEST JOB IDEMPOTENCY
# ============================================================================
def test_job_idempotency():
    """Các yêu cầu giống nhau trả lại cùng job_id mà không sinh job mới."""
    async def _run():
        art_id = await create_sample_artifact_async(USER_ALICE)

        job1_id = await JobQueueManager.create_job(
            action="export",
            artifact_id=art_id,
            target_format="xlsx",
            owner_id=USER_ALICE,
            idempotency_key=f"export:{art_id}:xlsx:{USER_ALICE}"
        )

        job2_id = await JobQueueManager.create_job(
            action="export",
            artifact_id=art_id,
            target_format="xlsx",
            owner_id=USER_ALICE,
            idempotency_key=f"export:{art_id}:xlsx:{USER_ALICE}"
        )

        assert job1_id == job2_id
        # Xác minh trong hàng đợi chỉ có đúng 1 bản ghi
        matching = [jid for jid, j in _jobs.items() if j.get("idempotency_key") == f"export:{art_id}:xlsx:{USER_ALICE}"]
        assert len(matching) == 1

    asyncio.run(_run())


# ============================================================================
# 4. TEST CROSS-OWNER ACCESS PROTECTION
# ============================================================================
def test_cross_owner_job_access_denied():
    """Chặn User Bob truy cập job hoặc file private của User Alice."""
    art_id = create_sample_artifact_sync(USER_ALICE)

    # Alice tạo job export
    app.dependency_overrides[get_current_principal] = lambda: mock_principal(USER_ALICE)
    resp = client.post(f"/api/artifacts/{art_id}/export?format=docx")
    assert resp.status_code == 202
    job_id = resp.json()["job_id"]

    # Bob cố tình truy vấn job của Alice -> 403 Forbidden
    app.dependency_overrides[get_current_principal] = lambda: mock_principal(USER_BOB)
    resp_bob_job = client.get(f"/api/jobs/{job_id}")
    assert resp_bob_job.status_code == 403
    assert resp_bob_job.json()["error_code"] == "ARTIFACT_ACCESS_DENIED"

    # Bob cố tình hủy job của Alice -> 403 Forbidden
    resp_bob_cancel = client.post(f"/api/jobs/{job_id}/cancel")
    assert resp_bob_cancel.status_code == 403

    # Bob cố tình truy cập file private của Alice -> 403 Forbidden
    resp_bob_file = client.get(f"/api/artifacts/{art_id}/file?format=docx")
    assert resp_bob_file.status_code == 403

    # Admin có quyền truy cập
    app.dependency_overrides[get_current_principal] = lambda: mock_principal("admin_user", is_admin=True)
    resp_admin_job = client.get(f"/api/jobs/{job_id}")
    assert resp_admin_job.status_code == 200
    assert resp_admin_job.json()["job_id"] == job_id

    app.dependency_overrides.clear()


# ============================================================================
# 5. TEST WORKER ATOMIC LEASE CLAIM & RECOVERY (RESTART)
# ============================================================================
def test_worker_lease_recovery_and_restart():
    """Worker 2 phục hồi và xử lý thành công job khi Worker 1 gặp sự cố / hết hạn lease."""
    async def _run():
        art_id = await create_sample_artifact_async(USER_ALICE)
        job_id = await JobQueueManager.create_job(
            action="export",
            artifact_id=art_id,
            target_format="xlsx",
            owner_id=USER_ALICE
        )

        # Worker 1 claim job với lease_expires_at trong quá khứ (giả lập crash)
        worker_1 = ArtifactWorker(worker_id="worker_alpha_crashed", lease_seconds=5)
        claimed_1 = MongoLeaseQueueAdapter.claim_next_job(worker_1.worker_id, specific_job_id=job_id)
        assert claimed_1 is not None

        # Giả lập Worker 1 bị crash và thời gian trôi qua khiến lease hết hạn
        now_past = datetime.now(timezone.utc) - timedelta(seconds=10)
        _jobs[job_id]["lease_expires_at"] = now_past
        from backend.app.repositories.mongo_repository import MongoRepository
        col = MongoRepository.get_collection("jobs")
        if col is not None:
            col.update_one({"$or": [{"_id": job_id}, {"job_id": job_id}]}, {"$set": {"lease_expires_at": now_past}})

        # Worker 2 xuất hiện, thực hiện claim job hết hạn
        worker_2 = ArtifactWorker(worker_id="worker_beta_restarted", lease_seconds=30)
        claimed_2 = MongoLeaseQueueAdapter.claim_next_job(worker_2.worker_id, specific_job_id=job_id)
        assert claimed_2 is not None

        # Worker 2 hoàn thành công việc
        job_doc = JobQueueManager.get_job(job_id)
        assert job_doc["lease_owner"] == worker_2.worker_id

        success = await worker_2.process_job(job_doc)
        assert success is True

        final_job = JobQueueManager.get_job(job_id)
        assert final_job["status"] == "completed"
        assert final_job["progress"] == 100
        assert final_job["result_url"] is not None

    asyncio.run(_run())


# ============================================================================
# 6. TEST WORKER RETRY & BACKOFF
# ============================================================================
def test_worker_retry_backoff_on_failure():
    """Worker tự động retry với exponential backoff khi gặp lỗi tạm thời (retryable)."""
    async def _run():
        art_id = await create_sample_artifact_async(USER_ALICE)
        job_id = await JobQueueManager.create_job(
            action="render",
            artifact_id=art_id,
            target_format="pdf",
            owner_id=USER_ALICE
        )

        worker = ArtifactWorker(worker_id="worker_retry_tester")
        claimed = MongoLeaseQueueAdapter.claim_next_job(worker.worker_id, specific_job_id=job_id)
        assert claimed is not None

        # Giả lập lần 1: tác vụ thất bại do lỗi tạm thời (connection reset / timeout)
        attempt_count = 0

        async def _failing_execute_task(job):
            nonlocal attempt_count
            attempt_count += 1
            if attempt_count == 1:
                raise ConnectionResetError("Mạng chập chờn, lỗi tạm thời kết nối storage")
            return {
                "url": f"/api/artifacts/{art_id}/file?format=pdf",
                "media_type": "application/pdf",
                "bytes": 1024,
                "filename": "test.pdf"
            }

        worker.execute_task = _failing_execute_task

        # Lần 1 chạy: phải thất bại và chuyển sang retry với available_at lùi về tương lai
        res1 = await worker.process_job(JobQueueManager.get_job(job_id))
        assert res1 is False

        job_after_fail = JobQueueManager.get_job(job_id)
        assert job_after_fail["status"] == "queued"
        assert job_after_fail["retries"] == 1
        assert job_after_fail["attempt"] == 1
        assert job_after_fail["available_at"] is not None

        # Tua thời gian available_at về hiện tại để claim lần 2
        _jobs[job_id]["available_at"] = datetime.now(timezone.utc) - timedelta(seconds=1)

        # Lần 2 chạy: thành công
        claimed_retry = MongoLeaseQueueAdapter.claim_next_job(worker.worker_id, specific_job_id=job_id)
        assert claimed_retry is not None
        res2 = await worker.process_job(JobQueueManager.get_job(job_id))
        assert res2 is True

        job_after_success = JobQueueManager.get_job(job_id)
        assert job_after_success["status"] == "completed"
        assert job_after_success["retries"] == 1

    asyncio.run(_run())


# ============================================================================
# 7. TEST WORKER CANCELLATION CHECKPOINTS
# ============================================================================
def test_worker_cancellation_checkpoints():
    """Worker tôn trọng checkpoint hủy: dừng ngay và không ghi đè completed nếu job đã bị hủy."""
    async def _run():
        art_id = await create_sample_artifact_async(USER_ALICE)

        # Checkpoint 1: Job bị hủy TRƯỚC KHI worker thực thi
        job1_id = await JobQueueManager.create_job(action="export", artifact_id=art_id, target_format="docx", owner_id=USER_ALICE)
        await JobQueueManager.cancel_job(job1_id, requester_id=USER_ALICE)

        worker = ArtifactWorker(worker_id="worker_cancel_tester")
        job1_doc = JobQueueManager.get_job(job1_id)
        assert job1_doc["status"] == "cancelled"

        res1 = await worker.process_job(job1_doc)
        assert res1 is False
        assert JobQueueManager.get_job(job1_id)["status"] == "cancelled"

        # Checkpoint 2: Job bị hủy TRONG KHI worker đang thực thi
        job2_id = await JobQueueManager.create_job(action="export", artifact_id=art_id, target_format="xlsx", owner_id=USER_ALICE)
        claimed = MongoLeaseQueueAdapter.claim_next_job(worker.worker_id, specific_job_id=job2_id)
        assert claimed is not None

        async def _slow_task(job):
            # Giả lập người dùng ấn hủy giữa chừng
            await JobQueueManager.cancel_job(job2_id, requester_id=USER_ALICE)
            return {"url": "/test", "bytes": 100}

        worker.execute_task = _slow_task
        res2 = await worker.process_job(JobQueueManager.get_job(job2_id))
        assert res2 is False

        # Trạng thái cuối cùng vẫn phải là cancelled, không bị completed ghi đè
        final_job2 = JobQueueManager.get_job(job2_id)
        assert final_job2["status"] == "cancelled"

    asyncio.run(_run())


# ============================================================================
# 8. TEST EXPORT WORD/EXCEL/PDF BINARY GENERATION & STORAGE ADAPTER
# ============================================================================
def test_export_word_excel_pdf_storage_adapter():
    """Worker tạo file nhị phân hợp lệ (DOCX/XLSX/PDF) và lưu vào StorageAdapter."""
    async def _run():
        art_id = await create_sample_artifact_async(USER_ALICE)
        worker = ArtifactWorker(worker_id="worker_binary_tester")

        # 1. Export DOCX (Word)
        job_docx = await JobQueueManager.create_job(action="export", artifact_id=art_id, target_format="docx", owner_id=USER_ALICE)
        claimed_docx = MongoLeaseQueueAdapter.claim_next_job(worker.worker_id, specific_job_id=job_docx)
        assert claimed_docx is not None
        success_docx = await worker.process_job(JobQueueManager.get_job(job_docx))
        assert success_docx is True

        # 2. Export XLSX (Excel)
        job_xlsx = await JobQueueManager.create_job(action="export", artifact_id=art_id, target_format="xlsx", owner_id=USER_ALICE)
        claimed_xlsx = MongoLeaseQueueAdapter.claim_next_job(worker.worker_id, specific_job_id=job_xlsx)
        assert claimed_xlsx is not None
        success_xlsx = await worker.process_job(JobQueueManager.get_job(job_xlsx))
        assert success_xlsx is True

        # 3. Export PDF
        job_pdf = await JobQueueManager.create_job(action="export", artifact_id=art_id, target_format="pdf", owner_id=USER_ALICE)
        claimed_pdf = MongoLeaseQueueAdapter.claim_next_job(worker.worker_id, specific_job_id=job_pdf)
        assert claimed_pdf is not None
        success_pdf = await worker.process_job(JobQueueManager.get_job(job_pdf))
        assert success_pdf is True

        # Xác minh tải file nhị phân qua GET endpoint
        app.dependency_overrides[get_current_principal] = lambda: mock_principal(USER_ALICE)
        try:
            resp_docx = client.get(f"/api/artifacts/{art_id}/file?format=docx")
            assert resp_docx.status_code == 200
            # Định dạng DOCX là ZIP package bắt đầu bằng PK\x03\x04
            assert resp_docx.content[:4] == b"PK\x03\x04"

            resp_xlsx = client.get(f"/api/artifacts/{art_id}/file?format=xlsx")
            assert resp_xlsx.status_code == 200
            # Định dạng XLSX là ZIP package bắt đầu bằng PK\x03\x04
            assert resp_xlsx.content[:4] == b"PK\x03\x04"

            resp_pdf = client.get(f"/api/artifacts/{art_id}/file?format=pdf")
            assert resp_pdf.status_code == 200
            # Định dạng PDF bắt đầu bằng %PDF-
            assert resp_pdf.content.startswith(b"%PDF-")
        finally:
            app.dependency_overrides.clear()

    asyncio.run(_run())


# ============================================================================
# 9. TEST UPSCALE 2X/4X & SIGNED URL
# ============================================================================
def test_upscale_2x_4x_and_signed_url():
    """Worker thực hiện upscale 2x/4x và cấp signed URL download không render đồng bộ."""
    async def _run():
        img_art_id = await create_sample_artifact_async(USER_ALICE, "Bảng tra cứu điểm chuẩn HUIT 2026")
        worker = ArtifactWorker(worker_id="worker_upscale_tester")

        # A. Upscale 2x
        job_2x = await JobQueueManager.create_job(action="upscale", artifact_id=img_art_id, scale=2, owner_id=USER_ALICE)
        claimed_2x = MongoLeaseQueueAdapter.claim_next_job(worker.worker_id, specific_job_id=job_2x)
        assert claimed_2x is not None
        ok_2x = await worker.process_job(JobQueueManager.get_job(job_2x))
        assert ok_2x is True

        job_data_2x = JobQueueManager.get_job(job_2x)
        assert job_data_2x["status"] == "completed"
        assert "download_url" in job_data_2x
        assert "sig=" in job_data_2x["download_url"]
        assert "expires=" in job_data_2x["download_url"]

        # B. Upscale 4x
        job_4x = await JobQueueManager.create_job(action="upscale", artifact_id=img_art_id, scale=4, owner_id=USER_ALICE)
        claimed_4x = MongoLeaseQueueAdapter.claim_next_job(worker.worker_id, specific_job_id=job_4x)
        assert claimed_4x is not None
        ok_4x = await worker.process_job(JobQueueManager.get_job(job_4x))
        assert ok_4x is True

        job_data_4x = JobQueueManager.get_job(job_4x)
        assert job_data_4x["status"] == "completed"
        assert "sig=" in job_data_4x["download_url"]

    asyncio.run(_run())


# ============================================================================
# 10. TEST NO BINARY OR BASE64 IN MONGO OR EVENTS
# ============================================================================
def test_no_binary_or_base64_in_mongo_or_events():
    """Đảm bảo tuyệt đối không lưu dữ liệu nhị phân hoặc chuỗi Base64 lớn trong MongoDB/events."""
    async def _run():
        art_id = await create_sample_artifact_async(USER_ALICE)
        worker = ArtifactWorker(worker_id="worker_audit_tester")

        job_id = await JobQueueManager.create_job(action="export", artifact_id=art_id, target_format="docx", owner_id=USER_ALICE)
        claimed = MongoLeaseQueueAdapter.claim_next_job(worker.worker_id, specific_job_id=job_id)
        assert claimed is not None
        await worker.process_job(JobQueueManager.get_job(job_id))

        job_record = JobQueueManager.get_job(job_id)

        def _check_no_binary_or_base64(obj, path="root"):
            if isinstance(obj, bytes):
                pytest.fail(f"Phát hiện raw bytes tại '{path}': độ dài {len(obj)}")
            elif isinstance(obj, str):
                if obj.startswith("data:image/") or obj.startswith("data:application/"):
                    pytest.fail(f"Phát hiện Data URI Base64 tại '{path}': {obj[:50]}...")
                # Kiểm tra không có chuỗi Base64 dài ngẫu nhiên (> 512 ký tự)
                if len(obj) > 512 and re.match(r"^[A-Za-z0-9+/=]+$", obj):
                    pytest.fail(f"Phát hiện chuỗi Base64 dung lượng lớn tại '{path}': độ dài {len(obj)}")
            elif isinstance(obj, dict):
                for k, v in obj.items():
                    _check_no_binary_or_base64(v, f"{path}.{k}")
            elif isinstance(obj, list):
                for idx, item in enumerate(obj):
                    _check_no_binary_or_base64(item, f"{path}[{idx}]")

        _check_no_binary_or_base64(job_record)
        # Xác minh events
        assert "events" in job_record
        assert len(job_record["events"]) > 0
        for evt in job_record["events"]:
            assert "timestamp" in evt
            assert "status" in evt
            assert "detail" in evt
            assert not isinstance(evt.get("detail"), bytes)

    asyncio.run(_run())
