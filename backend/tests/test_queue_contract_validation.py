"""Tests for Phase 6 - Queue Contract Validation across system boundaries."""
import asyncio
from datetime import datetime, timezone
import jsonschema.exceptions
import pytest

from backend.app.contracts.schema_registry import (
    load_schema,
    get_schema_entry,
    validate_contract,
    SchemaRegistryError,
)
from backend.app.services.job_queue import (
    validate_job_input,
    validate_job_result,
    validate_job_error,
    validate_retry_metadata,
    JobQueueManager,
    MongoLeaseQueueAdapter,
    clear_jobs_for_testing,
)
from backend.app.telemetry.errors import ArtifactException


@pytest.fixture(autouse=True)
def setup_teardown():
    clear_jobs_for_testing()
    yield
    clear_jobs_for_testing()


def test_queue_dead_letter_schema_is_planned():
    """Verify dead-letter schema is explicitly marked as planned (no fake runtime claimed)."""
    entry = get_schema_entry("huit.queue.dead-letter-metadata", "1.0.0")
    assert entry is not None
    assert entry["status"] == "planned"
    schema = load_schema("huit.queue.dead-letter-metadata", "1.0.0")
    assert schema["$id"] == "urn:huit:schema:queue:dead-letter-metadata:1.0.0"


def test_validate_job_input_contract():
    """Verify validate_job_input enforces schema rules."""
    valid_payload = {
        "job_id": "job_12345",
        "action": "render",
        "artifact_id": "art_123",
        "format": "xlsx",
        "scale": 1,
        "owner_id": "user_456",
        "request_id": "req_789",
        "idempotency_key": "idem_101",
        "available_at": datetime.now(timezone.utc).isoformat(),
    }
    # Valid payload must not raise
    validate_job_input(valid_payload)

    # Missing required field 'job_id'
    invalid_missing_job_id = {
        "action": "render",
    }
    with pytest.raises((jsonschema.exceptions.ValidationError, SchemaRegistryError)):
        validate_job_input(invalid_missing_job_id)

    # Missing required field 'action'
    invalid_missing_action = {
        "job_id": "job_12345",
    }
    with pytest.raises((jsonschema.exceptions.ValidationError, SchemaRegistryError)):
        validate_job_input(invalid_missing_action)

    # Disallowed extra field (additionalProperties: false)
    invalid_extra_field = {
        "job_id": "job_12345",
        "action": "render",
        "unexpected_extra_property": True,
    }
    with pytest.raises((jsonschema.exceptions.ValidationError, SchemaRegistryError)):
        validate_job_input(invalid_extra_field)


def test_validate_job_result_contract():
    """Verify validate_job_result enforces schema rules."""
    valid_payload = {
        "url": "/api/artifacts/art_123/file?format=xlsx",
        "download_url": "https://example.com/download/signed",
        "media_type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "bytes": 1024,
        "filename": "report.xlsx",
        "scale": None,
        "upscaled_id": None,
    }
    validate_job_result(valid_payload)

    # Missing required 'url'
    with pytest.raises((jsonschema.exceptions.ValidationError, SchemaRegistryError)):
        validate_job_result({"download_url": "https://example.com"})

    # Scale out of range (maximum 4)
    with pytest.raises((jsonschema.exceptions.ValidationError, SchemaRegistryError)):
        validate_job_result({"url": "/api/artifacts/1", "scale": 10})


def test_validate_job_error_contract():
    """Verify validate_job_error enforces schema rules."""
    valid_payload = {
        "error_code": "RENDER_FAILED",
        "message": "Template rendering timed out",
        "request_id": "req_123",
        "job_id": "job_456",
        "artifact_id": "art_789",
        "stage": "worker_execution",
        "module": "artifact_worker",
        "retryable": True,
        "details": "Timeout after 120s",
    }
    validate_job_error(valid_payload)

    # Missing required 'error_code'
    with pytest.raises((jsonschema.exceptions.ValidationError, SchemaRegistryError)):
        validate_job_error({"message": "Something went wrong"})

    # Missing required 'message'
    with pytest.raises((jsonschema.exceptions.ValidationError, SchemaRegistryError)):
        validate_job_error({"error_code": "FAIL"})


def test_validate_retry_metadata_contract():
    """Verify validate_retry_metadata enforces schema rules."""
    valid_payload = {
        "attempt": 1,
        "max_attempts": 3,
        "retries": 1,
        "lease_owner": "worker_abc",
        "lease_expires_at": datetime.now(timezone.utc).isoformat(),
        "heartbeat_at": datetime.now(timezone.utc).isoformat(),
        "available_at": datetime.now(timezone.utc).isoformat(),
    }
    validate_retry_metadata(valid_payload)

    # Missing required 'attempt' or 'max_attempts'
    with pytest.raises((jsonschema.exceptions.ValidationError, SchemaRegistryError)):
        validate_retry_metadata({"attempt": 1})

    # max_attempts > 10 (maximum 10)
    with pytest.raises((jsonschema.exceptions.ValidationError, SchemaRegistryError)):
        validate_retry_metadata({"attempt": 1, "max_attempts": 99})


def test_enqueue_job_boundary_validation():
    """Verify JobQueueManager.enqueue_job enforces queue input contract at boundary."""
    async def _run():
        job_id = await JobQueueManager.enqueue_job(
            action="render",
            artifact_id="art_valid_test",
            format_str="xlsx",
            owner_id="user_test",
            request_id="req_test",
        )
        assert job_id is not None

        job = JobQueueManager.get_job(job_id, is_admin=True)
        assert job is not None
        assert job["job_id"] == job_id
        assert job["status"] == "queued"

    asyncio.run(_run())


def test_update_job_boundary_validation():
    """Verify JobQueueManager.update_job validates result, error, and retry boundaries."""
    async def _run():
        job_id = await JobQueueManager.enqueue_job(
            action="render",
            artifact_id="art_update_test",
            format_str="xlsx",
            owner_id="user_test",
        )

        # Update to processing
        await JobQueueManager.update_job(job_id, status="processing", progress=50)
        job = JobQueueManager.get_job(job_id, is_admin=True)
        assert job["status"] == "processing"

        # Update to retry (status='queued', attempt=1)
        await JobQueueManager.update_job(
            job_id,
            status="queued",
            progress=0,
            attempt=1,
            retries=1,
            event_detail="Retry attempt 1",
        )
        job = JobQueueManager.get_job(job_id, is_admin=True)
        assert job["status"] == "queued"

        # Update to completed with result_url
        await JobQueueManager.update_job(
            job_id,
            status="completed",
            progress=100,
            result_url="/api/artifacts/art_update_test/file?format=xlsx",
            download_url="/api/artifacts/art_update_test/file?format=xlsx",
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        job = JobQueueManager.get_job(job_id, is_admin=True)
        assert job["status"] == "completed"

    asyncio.run(_run())


def test_worker_returning_empty_dict_fails_and_does_not_complete():
    """1. Worker trả {} không được completed."""
    async def _run():
        job_id = await JobQueueManager.enqueue_job(action="render", artifact_id="art_empty_dict")

        async def _bad_worker():
            return {}

        JobQueueManager.run_in_background(job_id, _bad_worker)
        # Chờ worker hoàn thành
        await asyncio.sleep(0.3)

        job = JobQueueManager.get_job(job_id, is_admin=True)
        assert job["status"] != "completed"
        assert job["status"] == "failed"
        assert job["error"]["error_code"] == "QUEUE_RESULT_CONTRACT_VIOLATION"
        assert job["error"]["stage"] == "queue_result_validation"

    asyncio.run(_run())


def test_worker_returning_none_fails_and_does_not_complete():
    """2. Worker trả None không được completed."""
    async def _run():
        job_id = await JobQueueManager.enqueue_job(action="render", artifact_id="art_none")

        async def _none_worker():
            return None

        JobQueueManager.run_in_background(job_id, _none_worker)
        await asyncio.sleep(0.3)

        job = JobQueueManager.get_job(job_id, is_admin=True)
        assert job["status"] != "completed"
        assert job["status"] == "failed"
        assert job["error"]["error_code"] == "QUEUE_RESULT_CONTRACT_VIOLATION"

    asyncio.run(_run())


def test_worker_returning_result_missing_url_fails_and_does_not_complete():
    """3. Worker trả result thiếu url không được completed."""
    async def _run():
        job_id = await JobQueueManager.enqueue_job(action="render", artifact_id="art_missing_url")

        async def _missing_url_worker():
            return {"download_url": "https://example.com/no-url-prop"}

        JobQueueManager.run_in_background(job_id, _missing_url_worker)
        await asyncio.sleep(0.3)

        job = JobQueueManager.get_job(job_id, is_admin=True)
        assert job["status"] != "completed"
        assert job["status"] == "failed"
        assert job["error"]["error_code"] == "QUEUE_RESULT_CONTRACT_VIOLATION"

    asyncio.run(_run())


def test_result_with_extra_field_rejected_at_boundary():
    """4. Result có field ngoài schema bị từ chối."""
    async def _run():
        job_id = await JobQueueManager.enqueue_job(action="render", artifact_id="art_extra")
        await JobQueueManager.update_job(job_id, status="processing")

        with pytest.raises(ArtifactException) as exc_info:
            await JobQueueManager.update_job(
                job_id,
                status="completed",
                raw_result={"url": "https://example.com/res", "unexpected_payload_key": 999}
            )
        assert exc_info.value.error_code == "QUEUE_RESULT_CONTRACT_VIOLATION"

        job = JobQueueManager.get_job(job_id, is_admin=True)
        assert job["status"] == "processing"

    asyncio.run(_run())


def test_result_with_scale_greater_than_4_rejected():
    """5. Result có scale > 4 bị từ chối."""
    async def _run():
        job_id = await JobQueueManager.enqueue_job(action="upscale", artifact_id="art_scale")
        await JobQueueManager.update_job(job_id, status="processing")

        with pytest.raises(ArtifactException) as exc_info:
            await JobQueueManager.update_job(
                job_id,
                status="completed",
                raw_result={"url": "https://example.com/res", "scale": 8}
            )
        assert exc_info.value.error_code == "QUEUE_RESULT_CONTRACT_VIOLATION"

        job = JobQueueManager.get_job(job_id, is_admin=True)
        assert job["status"] == "processing"

    asyncio.run(_run())


def test_error_payload_invalid_schema_sanitized_not_raw():
    """6. Error payload sai schema không được lưu raw."""
    async def _run():
        job_id = await JobQueueManager.enqueue_job(action="render", artifact_id="art_err_test")

        # Gửi error chứa thông tin secret / stacktrace và trường không hợp lệ
        raw_malicious_error = {
            "error_code": "SECRET_ERROR",
            "message": "Error occurred with secret=sk-1234567890",
            "raw_stacktrace": "File main.py, line 42, in crash\n  password = 'secret'",
            "extra_field_disallowed": True,
        }
        await JobQueueManager.update_job(job_id, status="failed", error=raw_malicious_error)

        job = JobQueueManager.get_job(job_id, is_admin=True)
        assert job["status"] == "failed"
        stored_error = job["error"]
        assert isinstance(stored_error, dict)
        # Đảm bảo trường thừa raw_stacktrace hoặc extra_field_disallowed không bị lưu raw
        assert "raw_stacktrace" not in stored_error
        assert "extra_field_disallowed" not in stored_error
        # Error phải validate thành công theo canonical schema huit.queue.job-error
        validate_job_error(stored_error)

    asyncio.run(_run())


def test_retry_metadata_invalid_does_not_mutate_attempt_or_retries():
    """7. Retry metadata sai không được mutate attempt/retries."""
    async def _run():
        job_id = await JobQueueManager.enqueue_job(action="render", artifact_id="art_retry_test")
        job_initial = JobQueueManager.get_job(job_id, is_admin=True)
        assert job_initial["attempt"] == 0
        assert job_initial["retries"] == 0

        # Thử mutate attempt âm hoặc sai kiểu
        with pytest.raises(ArtifactException) as exc_info:
            await JobQueueManager.update_job(job_id, status="queued", attempt=-99, retries=-1)
        assert exc_info.value.error_code == "QUEUE_RETRY_CONTRACT_VIOLATION"

        # Kiểm tra state RAM không bị thay đổi
        job_after = JobQueueManager.get_job(job_id, is_admin=True)
        assert job_after["attempt"] == 0
        assert job_after["retries"] == 0

    asyncio.run(_run())


def test_validation_happens_before_state_mutation():
    """8. Validation phải diễn ra trước mutation."""
    async def _run():
        job_id = await JobQueueManager.enqueue_job(action="render", artifact_id="art_before_mut")
        await JobQueueManager.update_job(job_id, status="processing")

        # Gọi completed với URL rỗng / None
        with pytest.raises(ArtifactException) as exc_info:
            await JobQueueManager.update_job(job_id, status="completed", result_url=None, download_url=None)
        assert exc_info.value.error_code == "QUEUE_RESULT_CONTRACT_VIOLATION"

        # State phải vẫn là processing, không hề chuyển sang completed
        job = JobQueueManager.get_job(job_id, is_admin=True)
        assert job["status"] == "processing"

    asyncio.run(_run())


def test_production_never_falls_back_to_ram():
    """9. Production không fallback sang RAM."""
    from unittest.mock import patch
    from backend.app.config import settings
    from backend.app.services.job_queue import _jobs

    # Đặt một job trực tiếp vào RAM (không lưu Mongo)
    ram_only_job_id = "job_ram_only_12345"
    _jobs[ram_only_job_id] = {
        "job_id": ram_only_job_id,
        "action": "render",
        "artifact_id": "art_ram_only",
        "status": "queued",
        "attempt": 0,
        "max_attempts": 3,
        "retries": 0,
        "available_at": datetime.now(timezone.utc),
    }

    # Giả lập Mongo không có job này (atomic_claim_next_job trả None)
    with patch("backend.app.services.job_queue.job_operations.atomic_claim_next_job", return_value=None):
        # 1. Trên Production: Tuyệt đối không fallback sang RAM -> phải trả None
        with patch.object(type(settings), "IS_PRODUCTION", new_callable=lambda: property(lambda self: True)):
            claimed_prod = MongoLeaseQueueAdapter.claim_next_job("worker_prod", specific_job_id=ram_only_job_id)
            assert claimed_prod is None, "Production tuyệt đối không được fallback sang RAM!"

        # 2. Trên Dev/Test: Được phép fallback sang RAM
        with patch.object(type(settings), "IS_PRODUCTION", new_callable=lambda: property(lambda self: False)):
            claimed_dev = MongoLeaseQueueAdapter.claim_next_job("worker_dev", specific_job_id=ram_only_job_id)
            assert claimed_dev is not None
            assert claimed_dev["job_id"] == ram_only_job_id


def test_claimed_job_with_invalid_contract_is_not_stuck_in_processing():
    """10. Job contract invalid sau khi claim không bị mắc kẹt vô hạn ở processing."""
    from backend.app.services.job_queue import _jobs

    # Tạo một job trong _jobs có contract bị hỏng (ví dụ action rỗng hoặc scale > 4)
    bad_job_id = "job_corrupted_12345"
    _jobs[bad_job_id] = {
        "job_id": bad_job_id,
        "action": "",  # minLength 1 vi phạm
        "scale": 99,   # maximum 4 vi phạm
        "status": "queued",
        "attempt": 0,
        "max_attempts": 3,
        "retries": 0,
        "available_at": datetime.now(timezone.utc),
    }

    # Worker claim job bị hỏng
    claimed = MongoLeaseQueueAdapter.claim_next_job("worker_recovery", specific_job_id=bad_job_id)
    # Claim bị từ chối
    assert claimed is None

    # Job phải được chuyển sang failed có kiểm soát, không mắc kẹt ở processing
    bad_job = _jobs[bad_job_id]
    assert bad_job["status"] == "failed"
    assert bad_job["error"]["error_code"] == "QUEUE_CLAIM_CONTRACT_VIOLATION"
    assert bad_job["lease_owner"] is None
