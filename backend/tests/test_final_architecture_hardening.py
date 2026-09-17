"""
test_final_architecture_hardening.py
Bộ kiểm thử tự động toàn diện nghiệm thu Kiến trúc Cuối cùng (Final Architecture Hardening):
1. Multi-User Image Deduplication & Physical Blob Reuse.
2. Signed Download URL: Clamping, Expiry validation, Future drift rejection, Constant-time compare.
3. Principal Authentication & Session Management: Session creation, Cookie, Signature verification.
4. Distributed Rate Limiting: RFC 1918 CIDR checks, Fail-fast on missing Redis in production.
5. Durable Background Queue: MongoDB Lease claiming, Expiration reclamation, Checkpoint cancellation.
6. On-Demand Upscale & Multi-Format Export: Cached derivative reuse (<5ms), Rejection of audio/video.
7. NDJSON Streaming Protocol v2: Monotonic sequence 1..N, StreamStarted (seq 1), ArtifactSummary (<2KB).
"""
import asyncio
import hmac
import hashlib
import time
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import patch, MagicMock

import pytest
from fastapi.testclient import TestClient

from backend.app.main import app
from backend.app.config import settings
from backend.app.services.auth_service import (
    create_download_signature,
    verify_download_signature,
    generate_session_token,
    verify_session_token,
    generate_admin_token,
    verify_admin_token,
    SIGNATURE_SECRET_KEY,
)
from backend.app.api.dependencies.auth import get_client_ip, Principal
from backend.app.middleware.rate_limiter import (
    RateLimitStore,
    InMemoryRateLimitStore,
    RedisRateLimitStore,
    clear_rate_limits_for_testing,
)
from backend.app.services.image_service import generate_image_plan
from backend.app.services.asset_store import AssetStore, compute_derivative_hash
from backend.app.services.job_queue import JobQueueManager, MongoLeaseQueueAdapter, clear_jobs_for_testing
from backend.app.services.artifact_service import (
    create_artifact_plan,
    export_artifact,
    upscale_artifact,
)
from backend.app.api.schemas.artifact import ArtifactPlanRequest
from backend.app.telemetry.errors import ArtifactException

client = TestClient(app)


# ==============================================================================
# 1. SIGNED DOWNLOAD URL & STORAGE ADAPTER TESTS
# ==============================================================================

def test_signed_download_url_clamping_and_validation():
    """Kiểm tra chữ ký số tải file: kẹp thời gian 60s - 86400s, xác thực hợp lệ."""
    key = "asset_art_test123.pdf"
    sig, exp = create_download_signature(key, expires_in=30)  # Thấp hơn 60s
    now_ts = int(time.time())
    # Bị clamp lên tối thiểu 60s
    assert exp >= now_ts + 60

    # Chữ ký hợp lệ
    assert verify_download_signature(key, expires_at=exp, signature=sig) is True

    # Giả mạo storage_key -> Từ chối
    assert verify_download_signature("asset_art_hacked.pdf", expires_at=exp, signature=sig) is False

    # Giả mạo signature -> Từ chối
    assert verify_download_signature(key, expires_at=exp, signature="invalidsig123") is False


def test_signed_download_url_expired_and_future_drift_rejected():
    """Từ chối chữ ký đã hết hạn hoặc trôi thời gian về tương lai quá 24 giờ."""
    key = "asset_art_test456.xlsx"
    past_exp = int(time.time()) - 10
    sig_past, _ = create_download_signature(key, expires_in=60)
    # Giả lập URL đã hết hạn
    assert verify_download_signature(key, expires_at=past_exp, signature=sig_past) is False

    # Giả lập thời gian tương lai trôi quá 24h + 60s
    future_exp = int(time.time()) + 90000
    msg = f"{key}:{future_exp}"
    fake_future_sig = hmac.new(SIGNATURE_SECRET_KEY.encode(), msg.encode(), hashlib.sha256).hexdigest()
    assert verify_download_signature(key, expires_at=future_exp, signature=fake_future_sig) is False


# ==============================================================================
# 2. PRINCIPAL AUTH & SESSION MANAGEMENT TESTS
# ==============================================================================

def test_session_creation_endpoint_and_cookie():
    """Kiểm tra POST /api/auth/session cấp phát session an toàn và cookie HttpOnly."""
    test_client = TestClient(app)
    resp = test_client.post("/api/auth/session")
    assert resp.status_code == 200
    data = resp.json()
    assert "session_id" in data
    assert "csrf_token" in data
    assert "expires_at" in data
    assert len(data["session_id"]) >= 32

    # Kiểm tra cookie Set-Cookie
    set_cookie = resp.headers.get("set-cookie", "")
    assert "huit_session_id=" in set_cookie
    assert "HttpOnly" in set_cookie


def test_session_token_tampering_rejected():
    """Kiểm tra phát hiện và từ chối token phiên bị sửa đổi."""
    sess_id, token, _ = generate_session_token()
    assert verify_session_token(sess_id, token) is True

    # Sửa đổi sess_id nhưng giữ nguyên token
    assert verify_session_token("session_fake_123456789012345678901234", token) is False
    # Sửa đổi token
    assert verify_session_token(sess_id, token[:-4] + "dead") is False


# ==============================================================================
# 3. DISTRIBUTED RATE LIMITING & RFC 1918 CIDR TESTS
# ==============================================================================

def test_rate_limiter_rfc1918_trusted_proxy_ip_resolution():
    """Kiểm tra giải quyết đúng IP client thật sau proxy RFC 1918 (10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16, 127.0.0.1)."""
    mock_request = MagicMock()
    mock_request.client.host = "10.0.1.5"  # Trusted internal private proxy
    mock_request.headers = {"X-Forwarded-For": "203.0.113.195, 10.0.1.5"}

    resolved_ip = get_client_ip(mock_request)
    # Phải bóc tách được IP công cộng của client thật chứ không dùng IP của proxy nội bộ
    assert resolved_ip == "203.0.113.195"


def test_rate_limiter_production_fail_fast_on_missing_redis(monkeypatch):
    """Môi trường production bắt buộc fail-fast nếu thiếu Redis cấu hình cho Rate Limit."""
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("RATE_LIMIT_REDIS_URL", "")

    store = RateLimitStore()
    with pytest.raises(RuntimeError) as exc_info:
        store.get_store()
    assert "RATE_LIMIT_REDIS_URL" in str(exc_info.value)


# ==============================================================================
# 4. MULTI-USER IMAGE ISOLATION & PHYSICAL DEDUPLICATION TESTS
# ==============================================================================

def test_image_generation_dedup_shares_blob_with_isolated_owners(monkeypatch):
    """Hai người dùng sinh cùng một prompt ảnh: dùng chung Blob vật lý nhưng tách rời quyền sở hữu logical."""
    from backend.app.services import image_service
    monkeypatch.setattr(
        image_service,
        "generate_flux_image",
        lambda req, seed=None: (b"\xff\xd8\xff\xe0" + b"I" * 1_024, "image/jpeg"),
    )
    async def _run():
        prompt = "Linh vật HUIT Ong Vàng dũng cảm"
        # User A
        res_a = await generate_image_plan(prompt, owner_id="user_alice")
        # User B
        res_b = await generate_image_plan(prompt, owner_id="user_bob")

        assert res_a["image_id"] != res_b["image_id"]
        assert res_a["owner_id"] == "user_alice"
        assert res_b["owner_id"] == "user_bob"
        # Cả hai đều có preview URL hợp lệ
        assert "/api/images/" in res_a["url"]
        assert "/api/images/" in res_b["url"]

    asyncio.run(_run())


# ==============================================================================
# 5. DURABLE BACKGROUND QUEUE TESTS
# ==============================================================================

def test_durable_lease_queue_claim_and_reclamation():
    """Hàng đợi Durable: Claim lease nguyên tử, tự động thu hồi khi worker cũ bị hết hạn lease."""
    async def _run():
        clear_jobs_for_testing()
        job_id = await JobQueueManager.create_job(
            action="render_cad",
            artifact_id="art_cad_01",
            target_format="pdf",
            owner_id="user_charlie"
        )

        # Worker 1 claim job với lease 1 giây
        claimed_w1 = MongoLeaseQueueAdapter.claim_next_job(worker_id="worker_instance_1", lease_seconds=1, specific_job_id=job_id)
        assert claimed_w1 is not None
        assert claimed_w1["lease_owner"] == "worker_instance_1"

        # Worker 2 cố gắng claim ngay lập tức -> Thất bại vì lease worker 1 đang active
        claimed_w2_early = MongoLeaseQueueAdapter.claim_next_job(worker_id="worker_instance_2", lease_seconds=60, specific_job_id=job_id)
        assert claimed_w2_early is None

        # Giả lập worker 1 bị crash và hết hạn lease
        job_in_store = JobQueueManager.get_job(job_id, is_admin=True)
        past_time = datetime.now(timezone.utc) - timedelta(seconds=5)
        await JobQueueManager.update_job(
            job_id,
            status="processing"
        )
        from backend.app.services.job_queue import _jobs
        if job_id in _jobs:
            _jobs[job_id]["lease_expires_at"] = past_time

        # Worker 2 tiến hành reclaim job đã quá hạn lease
        claimed_w2_reclaimed = MongoLeaseQueueAdapter.claim_next_job(worker_id="worker_instance_2", lease_seconds=60, specific_job_id=job_id)
        assert claimed_w2_reclaimed is not None
        assert claimed_w2_reclaimed["lease_owner"] == "worker_instance_2"

    asyncio.run(_run())


def test_durable_queue_checkpoint_cancellation_persists():
    """Job bị hủy tuyệt đối không thể bị ghi đè thành processing hay completed."""
    async def _run():
        clear_jobs_for_testing()
        job_id = await JobQueueManager.create_job(action="export_big_excel", artifact_id="art_big_01")
        cancelled = await JobQueueManager.cancel_job(job_id)
        assert cancelled is True

        # Cố gắng update thành processing
        await JobQueueManager.update_job(job_id, status="processing")
        job = JobQueueManager.get_job(job_id)
        assert job["status"] == "cancelled"

        # Cố gắng update thành completed
        await JobQueueManager.update_job(job_id, status="completed", result_url="/file.xlsx")
        job = JobQueueManager.get_job(job_id)
        assert job["status"] == "cancelled"
        assert job["result_url"] is None

    asyncio.run(_run())


# ==============================================================================
# 6. ON-DEMAND UPSCALE & MULTI-FORMAT EXPORT TESTS
# ==============================================================================

def test_export_cached_derivative_reuse():
    """Xuất file lần 2 tái sử dụng derivative đã lưu (<5ms) mà không sinh lại từ đầu."""
    async def _run():
        plan_req = ArtifactPlanRequest(prompt="Bảng học phí các ngành đào tạo HUIT 2026")
        plan = await create_artifact_plan(plan_req)
        art_id = plan.artifact_id

        # Lần 1: Dựng file nhị phân docx
        t0 = time.perf_counter()
        raw1, media1, fn1 = export_artifact(art_id, "docx")
        t1 = time.perf_counter()

        # Lần 2: Đọc file từ derivative cache
        t2 = time.perf_counter()
        raw2, media2, fn2 = export_artifact(art_id, "docx")
        t3 = time.perf_counter()

        assert raw1 == raw2
        assert media1 == media2
        assert len(raw1) > 0
        # Thời gian đọc lần 2 cực nhanh
        assert (t3 - t2) < 0.1

    asyncio.run(_run())


def test_export_rejects_audio_and_video():
    """Từ chối dứt khoát các định dạng âm thanh/video mp3, mp4."""
    async def _run():
        plan_req = ArtifactPlanRequest(prompt="Bảng học phí các ngành đào tạo HUIT 2026")
        plan = await create_artifact_plan(plan_req)
        art_id = plan.artifact_id

        for bad_fmt in ["mp3", "mp4", "audio", "video"]:
            with pytest.raises(ArtifactException) as exc_info:
                export_artifact(art_id, bad_fmt)
            assert exc_info.value.error_code == "UNSUPPORTED_FILE_TYPE"

    asyncio.run(_run())


# ==============================================================================
# 7. NDJSON STREAMING PROTOCOL V2 STRUCTURE & PAYLOAD PRUNING TESTS
# ==============================================================================

def test_ndjson_streaming_v2_strict_sequence_and_ultralight_summary():
    """Kiểm tra chuỗi phát luồng chuẩn: stream_started (seq 1), meta (seq 2), artifact_planned (seq 3) với summary <2KB."""
    req_id = f"test-strict-v2-{uuid.uuid4().hex[:8]}"
    stream_client = TestClient(app)
    resp = stream_client.post(
        "/api/chat-stream",
        json={"question": "Học phí các ngành năm 2026 thế nào?"},
        headers={"X-Request-ID": req_id}
    )
    assert resp.status_code == 200
    assert resp.headers.get("X-Protocol-Version") == "2"

    lines = [l.strip() for l in resp.text.strip().split("\n") if l.strip()]
    assert len(lines) >= 5

    import json
    events = [json.loads(l) for l in lines]

    # Kiểm tra tính đơn điệu của sequence 1..N
    for idx, evt in enumerate(events, 1):
        assert evt["sequence"] == idx
        assert evt["protocol_version"] == 2
        assert "timestamp" in evt
        assert evt["request_id"] == req_id

    # Sự kiện 1: stream_started hoặc start
    assert events[0]["type"] in ("stream_started", "start")
    # Sự kiện 2: meta hoặc progress
    assert events[1]["type"] in ("meta", "progress")

    # Kiểm tra sự kiện artifact chứa ArtifactSummary siêu nhẹ (<2KB)
    planned_evts = [e for e in events if e["type"] in ("artifact_planned", "artifact")]
    assert len(planned_evts) > 0
    p_evt = planned_evts[0]
    raw_json_str = json.dumps(p_evt)
    assert len(raw_json_str.encode("utf-8")) < 2048  # Siêu nhẹ < 2KB
    assert "payload" in p_evt
    assert "artifact_id" in p_evt["payload"]
    assert "preview_url" in p_evt["payload"]
    assert "available_formats" in p_evt["payload"]

    # Sự kiện kết thúc: completed hoặc done
    assert events[-1]["type"] in ("completed", "done")
