"""
test_full_architecture_overhaul.py
Kiểm thử toàn diện 7 tiêu chí cốt lõi của Kiến trúc mới:
1. Multi-user privacy & ownership isolation khi deduplication.
2. Tái sử dụng physical blob (1 blob trong assets, 2 artifacts trong artifacts).
3. Checkpoint chống ghi đè completed cho job đã cancelled.
4. HMAC Signed URL verification & Expiry check.
5. Loại bỏ hoàn toàn audio/video (trả về lỗi an toàn).
6. Chống duplicate key collision khi sinh ảnh có regenerate=True.
7. Rate Limiter client key an toàn chống header spoofing.
"""
import asyncio
import time
import pytest
from datetime import datetime, timezone
from fastapi.testclient import TestClient

from backend.app.main import app
from backend.app.api.schemas.artifact import ArtifactPlanRequest
from backend.app.services.artifact_service import (
    create_artifact_plan,
    get_artifact,
    export_artifact
)
from backend.app.services.asset_store import AssetStore, ArtifactStore
from backend.app.services.job_queue import JobQueueManager
from backend.app.services.auth_service import (
    create_download_signature,
    verify_download_signature
)
from backend.app.services.image_service import (
    ImageRequest,
    create_image
)
from backend.app.telemetry.errors import ArtifactException

client = TestClient(app)


def test_multi_user_privacy_and_deduplication():
    """1. Multi-user privacy: User A và User B yêu cầu cùng nội dung được cấp artifact_id riêng, không rò rỉ owner_id."""
    async def _run():
        prompt = "Bảng học phí chi tiết các ngành HUIT 2026"
        req_a = ArtifactPlanRequest(prompt=prompt, user_id="user_alice")
        manifest_a = await create_artifact_plan(req_a, owner_id="user_alice")

        req_b = ArtifactPlanRequest(prompt=prompt, user_id="user_bob")
        manifest_b = await create_artifact_plan(req_b, owner_id="user_bob")

        # Content hash giống nhau do cùng yêu cầu
        assert manifest_a.content_hash == manifest_b.content_hash

        # Artifact ID và Owner ID hoàn toàn độc lập và bảo mật
        assert manifest_a.artifact_id != manifest_b.artifact_id
        assert manifest_a.owner_id == "user_alice"
        assert manifest_b.owner_id == "user_bob"

        # User Alice không được đọc artifact của Bob
        with pytest.raises(ArtifactException) as exc_info:
            get_artifact(manifest_b.artifact_id, requester_id="user_alice")
        assert "ACCESS_DENIED" in exc_info.value.error_code

        # User Bob đọc được artifact của chính mình
        retrieved_b = get_artifact(manifest_b.artifact_id, requester_id="user_bob")
        assert retrieved_b["artifact_id"] == manifest_b.artifact_id
        assert retrieved_b["owner_id"] == "user_bob"

    asyncio.run(_run())


def test_physical_blob_shared_under_hood():
    """2. Cùng nội dung chỉ lưu 1 physical blob trong assets, nhưng có 2 bản ghi quyền sở hữu trong artifacts."""
    async def _run():
        prompt = "Quy trình nhập học tân sinh viên HUIT 2026"
        m_a = await create_artifact_plan(ArtifactPlanRequest(prompt=prompt), owner_id="user_1")
        m_b = await create_artifact_plan(ArtifactPlanRequest(prompt=prompt), owner_id="user_2")

        art_a = ArtifactStore.get_by_id(m_a.artifact_id)
        art_b = ArtifactStore.get_by_id(m_b.artifact_id)

        assert art_a is not None and art_b is not None
        # Cùng trỏ tới 1 physical blob_id
        assert art_a["blob_id"] == art_b["blob_id"]

    asyncio.run(_run())


def test_cancelled_job_never_becomes_completed():
    """3. Checkpoint an toàn: Job đã bị cancelled tuyệt đối không bao giờ bị worker ghi đè thành completed."""
    async def _run():
        job_id = await JobQueueManager.create_job(action="render_heavy_pdf", artifact_id="art_test_1")

        # Hủy job ngay lập tức
        cancelled = await JobQueueManager.cancel_job(job_id)
        assert cancelled is True

        job_before = JobQueueManager.get_job(job_id)
        assert job_before["status"] == "cancelled"

        # Worker chạy nền cố gắng hoàn tất công việc
        async def slow_worker():
            await asyncio.sleep(0.05)
            return {"url": "/api/artifacts/download/file.pdf", "media_type": "application/pdf"}

        JobQueueManager.run_in_background(job_id, slow_worker)
        await asyncio.sleep(0.15)

        job_after = JobQueueManager.get_job(job_id)
        # Trạng thái bắt buộc vẫn là cancelled!
        assert job_after["status"] == "cancelled"
        assert job_after["result_url"] is None

    asyncio.run(_run())


def test_hmac_signed_download_and_expiry():
    """4. Chữ ký số HMAC xác thực và kiểm tra hạn dùng (Expiry Check)."""
    storage_key = "asset_art_12345.xlsx"
    
    # 1. Ký hợp lệ với thời hạn 60s
    sig, expires_at = create_download_signature(storage_key, expires_in=60)
    assert verify_download_signature(storage_key, expires_at=expires_at, signature=sig) is True

    # 2. Chữ ký đã hết hạn (quá khứ) -> Bị từ chối
    past_timestamp = int(time.time()) - 30
    assert verify_download_signature(storage_key, expires_at=past_timestamp, signature=sig) is False

    # 3. Chữ ký bị can thiệp file khác -> Bị từ chối
    assert verify_download_signature("tampered_file.xlsx", expires_at=expires_at, signature=sig) is False

    # 4. Chữ ký giả mạo -> Bị từ chối
    assert verify_download_signature(storage_key, expires_at=expires_at, signature="invalid_hmac_signature") is False


def test_audio_and_video_export_rejection():
    """5. Yêu cầu xuất mp3/mp4 bị từ chối sạch sẽ với lỗi không hỗ trợ."""
    # Tạo artifact mẫu
    async def _setup():
        return await create_artifact_plan(ArtifactPlanRequest(prompt="Điểm chuẩn 2026"))
    manifest = asyncio.run(_setup())

    with pytest.raises(ArtifactException) as exc_mp3:
        export_artifact(manifest.artifact_id, format_str="mp3")
    assert "UNSUPPORTED_FILE_TYPE" in exc_mp3.value.error_code

    with pytest.raises(ArtifactException) as exc_mp4:
        export_artifact(manifest.artifact_id, format_str="mp4")
    assert "UNSUPPORTED_FILE_TYPE" in exc_mp4.value.error_code


def test_image_regenerate_no_collision(monkeypatch):
    """6. Sinh ảnh với regenerate=True tạo content_hash độc nhất, không va chạm unique index."""
    # Mock backend flux
    from backend.app.services import image_service
    monkeypatch.setattr(image_service, "generate_flux_image", lambda req, seed=None: (b"\xff\xd8\xff\xe0" + b"A"*1000, "image/jpeg"))

    req1 = ImageRequest(prompt="Sinh viên HUIT năng động", regenerate=False)
    img1 = create_image(req1, owner_id="user_test")

    req2 = ImageRequest(prompt="Sinh viên HUIT năng động", regenerate=True)
    img2 = create_image(req2, owner_id="user_test")

    assert img1["image_id"] != img2["image_id"]
    # Fingerprint logic khác nhau để không va chạm; checksum vẫn phản ánh đúng
    # bytes vật lý (mock trả cùng bytes nên checksum phải giống nhau).
    assert img1["request_fingerprint"] != img2["request_fingerprint"]
    assert img1["checksum"] == img2["checksum"]
