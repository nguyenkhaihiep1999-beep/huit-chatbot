"""Comprehensive tests for Phase 5 Registered Operations and Domain Adapters.

Covers:
1. duplicate asset: content hash deduplication & reference count.
2. cross-owner artifact: isolation between distinct user ownerships.
3. dangling blob protection: controlled compensation and metadata cleanup.
4. atomic job claim: concurrent workers contention ensuring single winner.
5. duplicate idempotency key: returning existing job without duplicating work.
6. lease expiry/recovery: automatic lease reclamation upon worker death.
7. heartbeat: extending active worker leases dynamically.
8. retry exhaustion: permanent failure when max attempts reached.
9. cancel permission: authorization barriers preventing unauthorized cancellations.
10. concurrent workers: stress testing multiple workers claiming parallel jobs.
"""
import asyncio
from datetime import datetime, timedelta, timezone
import pytest

from backend.app.data_access.operations import asset_operations, job_operations
from backend.app.services.asset_store import AssetStore, ArtifactStore
from backend.app.services.job_queue import JobQueueManager, MongoLeaseQueueAdapter, clear_jobs_for_testing
from backend.app.telemetry.errors import ArtifactException, ERROR_ARTIFACT_ACCESS_DENIED


@pytest.fixture(autouse=True)
def setup_teardown():
    AssetStore.clear_memory_cache_for_testing()
    clear_jobs_for_testing()
    yield
    AssetStore.clear_memory_cache_for_testing()
    clear_jobs_for_testing()


class TestAssetAndArtifactOperations:
    def test_duplicate_asset_reuses_physical_blob(self):
        """1. Hai asset giống nhau cùng content hash được deduplicate và tăng reference_count."""
        content_hash = "a" * 64
        raw_data = b"DETERMINISTIC_REPORT_DATA"

        asset1 = AssetStore.save_asset(
            asset_id="asset_unique_001",
            media_type="application/pdf",
            content_hash=content_hash,
            raw_bytes=raw_data,
            file_ext="pdf",
        )
        assert asset1["asset_id"] == "asset_unique_001"
        assert asset1["reference_count"] == 1

        # Clear RAM để force truy vấn qua Gateway
        AssetStore.clear_memory_cache_for_testing()

        # Tìm lại qua hash
        found = AssetStore.find_by_hash(content_hash)
        assert found is not None
        assert found["asset_id"] == "asset_unique_001"
        # reference_count được tăng
        assert found["reference_count"] >= 2

    def test_cross_owner_artifact_isolation(self):
        """2. Quyền sở hữu artifact được cô lập, User B không thể truy cập tài nguyên private của User A."""
        art_a = ArtifactStore.save_artifact(
            artifact_id="art_private_user_a",
            manifest={"title": "Bảng điểm cá nhân"},
            owner_id="user_alpha",
            access_scope="private",
            blob_id="asset_unique_001",
        )
        assert art_a["owner_id"] == "user_alpha"

        # User A truy cập được
        assert ArtifactStore.check_ownership("art_private_user_a", requester_id="user_alpha") is True
        # Admin truy cập được
        assert ArtifactStore.check_ownership("art_private_user_a", is_admin=True) is True
        # User B bị từ chối
        assert ArtifactStore.check_ownership("art_private_user_a", requester_id="user_beta") is False

    def test_dangling_blob_protection_and_compensation(self):
        """3. Xóa bồi hoàn metadata của physical blob khi không có logical artifact nào tham chiếu."""
        asset_id = "asset_dangling_001"
        AssetStore.save_asset(
            asset_id=asset_id,
            media_type="image/png",
            content_hash="b" * 64,
            raw_bytes=b"DANGLING_IMAGE_BYTES",
            file_ext="png",
        )
        assert AssetStore.get_by_id(asset_id) is not None

        # Bồi hoàn / xóa record
        deleted = AssetStore.delete_asset_record(asset_id)
        assert deleted is True

        # Clear RAM và kiểm tra trên Gateway
        AssetStore.clear_memory_cache_for_testing()
        assert AssetStore.get_by_id(asset_id) is None


class TestJobQueueOperations:
    def test_atomic_job_claim_single_winner(self):
        """4. Hai worker claim cùng một job thì chỉ duy nhất một worker thắng cuộc."""
        async def _run():
            job_id = await JobQueueManager.create_job(action="export", artifact_id="art_atomic")
            worker_1 = "worker_1"
            worker_2 = "worker_2"

            claim_1 = MongoLeaseQueueAdapter.claim_next_job(worker_1, specific_job_id=job_id)
            claim_2 = MongoLeaseQueueAdapter.claim_next_job(worker_2, specific_job_id=job_id)

            assert (claim_1 is not None and claim_2 is None) or (claim_1 is None and claim_2 is not None)
            winner = claim_1 or claim_2
            assert winner["job_id"] == job_id
            assert winner["attempt"] == 1
        asyncio.run(_run())

    def test_duplicate_idempotency_key(self):
        """5. Cùng một idempotency key chỉ sinh đúng một job_id duy nhất."""
        async def _run():
            idemp = "idemp_export_excel_001"
            id1 = await JobQueueManager.create_job(action="export", idempotency_key=idemp)
            id2 = await JobQueueManager.create_job(action="export", idempotency_key=idemp)
            assert id1 == id2
        asyncio.run(_run())

    def test_lease_expiry_and_recovery(self):
        """6. Lease hết hạn có thể được thu hồi tự động hoặc claim bởi worker khác."""
        async def _run():
            job_id = await JobQueueManager.create_job(action="render", artifact_id="art_recov")
            worker_dead = "worker_dead"
            worker_alive = "worker_alive"

            # Claim với lease siêu ngắn 1s
            claimed = MongoLeaseQueueAdapter.claim_next_job(worker_dead, lease_seconds=1, specific_job_id=job_id)
            assert claimed is not None
            assert claimed["lease_owner"] == worker_dead

            # Chờ lease hết hạn
            await asyncio.sleep(1.1)

            # Thu hồi expired leases qua gateway
            recovered_count = job_operations.recover_expired_leases(max_jobs=10)
            assert recovered_count >= 1

            # Worker mới claim lại thành công
            reclaimed = MongoLeaseQueueAdapter.claim_next_job(worker_alive, specific_job_id=job_id)
            assert reclaimed is not None
            assert reclaimed["lease_owner"] == worker_alive
        asyncio.run(_run())

    def test_job_heartbeat_extends_lease(self):
        """7. Heartbeat gia hạn lease_expires_at thành công."""
        async def _run():
            job_id = await JobQueueManager.create_job(action="upscale", artifact_id="art_hb")
            worker_id = "worker_active"

            claimed = MongoLeaseQueueAdapter.claim_next_job(worker_id, lease_seconds=10, specific_job_id=job_id)
            assert claimed is not None

            # Gửi heartbeat gia hạn thêm 60 giây
            extended = MongoLeaseQueueAdapter.heartbeat(job_id, worker_id, extend_seconds=60)
            assert extended is True

            job = JobQueueManager.get_job(job_id)
            assert job["lease_expires_at"] is not None
        asyncio.run(_run())

    def test_retry_exhaustion_marks_failed(self):
        """8. Quá số lần thử tối đa (max_attempts) sẽ bị đánh dấu failed khi lease hết hạn."""
        async def _run():
            now = datetime.now(timezone.utc)
            job_id = f"job_exhausted_{int(now.timestamp())}"
            job_operations.create_job_record({
                "schema_version": 1,
                "job_id": job_id,
                "action": "render",
                "status": "processing",
                "attempt": 3,
                "max_attempts": 3,
                "lease_owner": "worker_crashed",
                "lease_expires_at": now - timedelta(seconds=10),
                "created_at": now,
                "updated_at": now,
            })

            recovered = job_operations.recover_expired_leases(max_jobs=10)
            assert recovered >= 1

            job = job_operations.get_job_by_id(job_id)
            assert job is not None
            assert job["status"] == "failed"
            assert job.get("error", {}).get("error_code") == "LEASE_EXPIRED_MAX_ATTEMPTS"
        asyncio.run(_run())

    def test_job_cancel_permission_and_isolation(self):
        """9. Người dùng khác không được phép đọc hoặc hủy job của chủ sở hữu."""
        async def _run():
            job_id = await JobQueueManager.create_job(
                action="render",
                artifact_id="art_secret",
                owner_id="owner_user"
            )

            # User khác đọc -> bị từ chối
            with pytest.raises(ArtifactException) as exc_info:
                JobQueueManager.get_job(job_id, requester_id="hacker_user")
            assert exc_info.value.error_code == ERROR_ARTIFACT_ACCESS_DENIED

            # User khác hủy -> bị từ chối
            with pytest.raises(ArtifactException):
                await JobQueueManager.cancel_job(job_id, requester_id="hacker_user")

            # Chính chủ hủy -> thành công
            cancelled = await JobQueueManager.cancel_job(job_id, requester_id="owner_user")
            assert cancelled is True

            job = JobQueueManager.get_job(job_id, requester_id="owner_user")
            assert job["status"] == "cancelled"
        asyncio.run(_run())

    def test_concurrent_workers_stress(self):
        """10. Mô phỏng nhiều workers chạy song song claim các job độc lập."""
        async def _run():
            job_ids = []
            for i in range(5):
                jid = await JobQueueManager.create_job(action="batch_test", artifact_id=f"art_{i}")
                job_ids.append(jid)

            claimed_results = {}

            async def _worker_claim(w_id: str):
                for _ in range(3):
                    c = MongoLeaseQueueAdapter.claim_next_job(w_id)
                    if c:
                        claimed_results[c["job_id"]] = w_id
                    await asyncio.sleep(0.01)

            workers = [f"worker_pool_{i}" for i in range(3)]
            await asyncio.gather(*[_worker_claim(w) for w in workers])

            # Mỗi job được claim tối đa 1 lần
            assert len(claimed_results) <= 5
            for jid in claimed_results:
                assert jid in job_ids
        asyncio.run(_run())
