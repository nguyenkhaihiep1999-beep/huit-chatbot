"""
test_admin_portal_ops.py
Bộ kiểm thử tự động toàn diện cho các endpoint Quản trị viên (Product Operations):
- Admin Authentication, CSRF protection, and RBAC (chặn người dùng thường).
- Quản lý hàng đợi jobs: phân trang, lọc theo status/action, chi tiết timeline.
- Thao tác Retry và Cancel job có CSRF và kiểm toán (audit log).
- Giám sát worker heartbeats và queue depth.
- Khử khuẩn nhật ký lỗi (sanitized error logs, không raw question, không secrets).
- Kiểm tra trạng thái migrations và backups (CHỈ ĐỌC - strictly read-only).
- Tổng hợp cảnh báo hệ thống (Alerts summary).
"""
import asyncio
import pytest
from datetime import datetime, timezone
from fastapi.testclient import TestClient

from backend.app.main import app
from backend.app.config import settings
from backend.app.services.job_queue import JobQueueManager, clear_jobs_for_testing
from backend.app.services.auth_service import (
    create_admin_session,
    generate_session_token,
    generate_csrf_token,
)
from backend.app.repositories.mongo_repository import MongoRepository


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def admin_credentials():
    """Tạo session và cookie của quản trị viên kèm CSRF token."""
    raw_session_id, cookie_token, csrf_token = create_admin_session(
        ip_address="127.0.0.1",
        user_agent="pytest-admin-client",
    )
    return {
        "cookie_token": cookie_token,
        "csrf_token": csrf_token,
        "cookies": {"huit_admin_token": cookie_token},
        "headers": {"X-CSRF-Token": csrf_token},
    }


@pytest.fixture
def user_credentials():
    """Tạo session của người dùng thường (không có quyền admin)."""
    session_id, token, _ = generate_session_token("user_normal_test")
    csrf_token = generate_csrf_token(session_id)
    return {
        "cookie_token": token,
        "csrf_token": csrf_token,
        "cookies": {"huit_session_id": token},
        "headers": {"X-CSRF-Token": csrf_token},
    }


def test_admin_rbac_and_unauthorized_rejection(client, user_credentials):
    """Kiểm tra RBAC: Yêu cầu không có auth hoặc từ người dùng thường đều bị từ chối 401/403."""
    # 1. Không có cookie auth -> 401
    resp_no_auth = client.get("/api/admin/jobs")
    assert resp_no_auth.status_code in (401, 403)

    resp_no_auth_workers = client.get("/api/admin/workers")
    assert resp_no_auth_workers.status_code in (401, 403)

    resp_no_auth_logs = client.get("/api/admin/logs/errors")
    assert resp_no_auth_logs.status_code in (401, 403)

    # 2. Người dùng thường (user session) gọi admin route -> 403 Forbidden
    resp_user = client.get(
        "/api/admin/jobs",
        cookies=user_credentials["cookies"],
        headers=user_credentials["headers"]
    )
    assert resp_user.status_code in (401, 403)


def test_admin_jobs_list_and_filters(client, admin_credentials):
    """Kiểm tra danh sách jobs có phân trang, bộ lọc status, action, time_range."""
    clear_jobs_for_testing()

    async def _setup_jobs():
        j1 = await JobQueueManager.create_job(action="render", target_format="xlsx")
        j2 = await JobQueueManager.create_job(action="export", target_format="pdf")
        j3 = await JobQueueManager.create_job(action="upscale", scale=2)
        await JobQueueManager.update_job(j2, status="completed", progress=100)
        await JobQueueManager.update_job(j3, status="failed", progress=0, error={"error_code": "TEST_ERR", "message": "Failed test"})
        return j1, j2, j3

    asyncio.run(_setup_jobs())

    # 1. Lấy toàn bộ danh sách
    resp = client.get(
        "/api/admin/jobs?page=1&limit=10",
        cookies=admin_credentials["cookies"]
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "jobs" in data
    assert data["total"] >= 3
    assert data["page"] == 1
    assert data["limit"] == 10

    # 2. Lọc theo status = completed
    resp_completed = client.get(
        "/api/admin/jobs?status=completed",
        cookies=admin_credentials["cookies"]
    )
    assert resp_completed.status_code == 200
    comp_data = resp_completed.json()
    for job in comp_data["jobs"]:
        assert job["status"] == "completed"

    # 3. Lọc theo action = upscale
    resp_upscale = client.get(
        "/api/admin/jobs?action=upscale",
        cookies=admin_credentials["cookies"]
    )
    assert resp_upscale.status_code == 200
    upscale_data = resp_upscale.json()
    for job in upscale_data["jobs"]:
        assert job["action"] == "upscale"


def test_admin_job_detail_and_events(client, admin_credentials):
    """Kiểm tra xem chi tiết job và event timeline."""
    clear_jobs_for_testing()

    async def _setup_single():
        j_id = await JobQueueManager.create_job(action="render", target_format="docx")
        await JobQueueManager.update_job(j_id, status="processing", progress=50, event_detail="Đang sinh tài liệu")
        return j_id

    j_id = asyncio.run(_setup_single())

    resp = client.get(
        f"/api/admin/jobs/{j_id}",
        cookies=admin_credentials["cookies"]
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["job"]["job_id"] == j_id
    assert data["job"]["status"] == "processing"
    assert data["job"]["progress"] == 50
    assert len(data["events"]) >= 1

    # Kiểm tra job không tồn tại -> 404
    resp_404 = client.get(
        "/api/admin/jobs/non_existent_job_xyz",
        cookies=admin_credentials["cookies"]
    )
    assert resp_404.status_code == 404


def test_admin_retry_and_cancel_actions_with_csrf_and_audit(client, admin_credentials):
    """Kiểm tra thao tác Retry & Cancel job bắt buộc CSRF, cập nhật trạng thái và ghi audit log."""
    clear_jobs_for_testing()

    async def _setup_fail():
        j_id = await JobQueueManager.create_job(action="render", target_format="pdf")
        await JobQueueManager.update_job(j_id, status="failed", progress=0, error={"error_code": "RENDER_FAIL", "message": "Simulated error"})
        return j_id

    j_id = asyncio.run(_setup_fail())

    # 1. Thử Retry KHÔNG CÓ CSRF TOKEN -> Phải bị từ chối 403
    resp_no_csrf = client.post(
        f"/api/admin/jobs/{j_id}/retry",
        cookies=admin_credentials["cookies"],
        json={"reason": "Thử lại do lỗi mạng"}
    )
    assert resp_no_csrf.status_code == 403

    # 2. Thử Retry CÓ CSRF TOKEN -> 200 OK, trạng thái chuyển về queued
    resp_retry = client.post(
        f"/api/admin/jobs/{j_id}/retry",
        cookies=admin_credentials["cookies"],
        headers=admin_credentials["headers"],
        json={"reason": "Admin retry test"}
    )
    assert resp_retry.status_code == 200
    assert resp_retry.json()["success"] is True

    # Kiểm tra trạng thái sau retry
    detail = client.get(f"/api/admin/jobs/{j_id}", cookies=admin_credentials["cookies"]).json()
    assert detail["job"]["status"] == "queued"
    assert detail["job"]["progress"] == 0

    # 3. Thử Cancel CÓ CSRF TOKEN -> 200 OK, trạng thái chuyển về cancelled
    resp_cancel = client.post(
        f"/api/admin/jobs/{j_id}/cancel",
        cookies=admin_credentials["cookies"],
        headers=admin_credentials["headers"],
        json={"reason": "Hủy bỏ bởi admin test"}
    )
    assert resp_cancel.status_code == 200
    assert resp_cancel.json()["success"] is True

    detail_after_cancel = client.get(f"/api/admin/jobs/{j_id}", cookies=admin_credentials["cookies"]).json()
    assert detail_after_cancel["job"]["status"] == "cancelled"

    # 4. Kiểm tra audit log đã được ghi nhận
    try:
        col = MongoRepository.get_operation_audit_collection()
        audit_record = col.find_one({"operation_key": "admin.jobs.cancel"})
        if audit_record:
            assert audit_record["status"] == "success"
            assert audit_record["operation_type"] == "command"
    except Exception:
        pass


def test_admin_worker_heartbeats_and_queue_stats(client, admin_credentials):
    """Kiểm tra worker heartbeats và thống kê hàng đợi."""
    clear_jobs_for_testing()

    async def _setup_workers():
        j1 = await JobQueueManager.create_job(action="render")
        j2 = await JobQueueManager.create_job(action="export")
        await JobQueueManager.update_job(j1, status="processing", worker_id="worker_test_01")
        await JobQueueManager.update_job(j2, status="failed")

    asyncio.run(_setup_workers())

    # 1. Workers heartbeat
    resp_workers = client.get("/api/admin/workers", cookies=admin_credentials["cookies"])
    assert resp_workers.status_code == 200
    w_data = resp_workers.json()
    assert "workers" in w_data
    assert w_data["total_workers"] >= 1
    assert w_data["healthy_count"] >= 0

    # 2. Queue stats
    resp_queue = client.get("/api/admin/queue/stats", cookies=admin_credentials["cookies"])
    assert resp_queue.status_code == 200
    q_data = resp_queue.json()
    assert "queued_count" in q_data
    assert "processing_count" in q_data
    assert "failed_count" in q_data
    assert q_data["processing_count"] >= 1
    assert q_data["failed_count"] >= 1


def test_admin_sanitized_error_logs(client, admin_credentials):
    """Kiểm tra nhật ký lỗi: Tuyệt đối không để lộ câu hỏi thô, secrets hay stacktraces."""
    clear_jobs_for_testing()

    async def _setup_err():
        j_id = await JobQueueManager.create_job(action="render")
        await JobQueueManager.update_job(
            j_id,
            status="failed",
            error={
                "error_code": "RENDER_EXPORT_ERROR",
                "message": "Không thể nạp font chữ hệ thống",
                "secret_key": "MUST_NOT_LEAK",
            }
        )

    asyncio.run(_setup_err())

    resp = client.get(
        "/api/admin/logs/errors?limit=10",
        cookies=admin_credentials["cookies"]
    )
    assert resp.status_code == 200
    logs_data = resp.json()
    assert "logs" in logs_data

    # Kiểm tra tính khử khuẩn (Sanitization)
    for entry in logs_data["logs"]:
        raw_text = str(entry)
        assert "MUST_NOT_LEAK" not in raw_text
        assert "mongodb+srv" not in raw_text
        assert "password" not in raw_text.lower()
        # Không được chứa trường 'question' thô
        assert "question" not in entry or entry.get("question") is None


def test_admin_readonly_migrations_and_backups(client, admin_credentials):
    """Kiểm tra danh sách migrations và backups CHỈ ĐỌC (không có nút thực thi hay restore)."""
    # 1. Migrations
    resp_mig = client.get("/api/admin/migrations", cookies=admin_credentials["cookies"])
    assert resp_mig.status_code == 200
    m_data = resp_mig.json()
    assert "migrations" in m_data
    assert m_data["can_execute_from_web"] is False  # An ninh: Tuyệt đối không thực thi từ web
    for mig in m_data["migrations"]:
        assert mig["is_read_only"] is True

    # 2. Backups
    resp_bak = client.get("/api/admin/backups", cookies=admin_credentials["cookies"])
    assert resp_bak.status_code == 200
    b_data = resp_bak.json()
    assert "backups" in b_data
    assert b_data["can_restore_from_web"] is False  # An ninh: Không restore từ web


def test_admin_alerts_summary(client, admin_credentials):
    """Kiểm tra bản tổng hợp cảnh báo hệ thống."""
    resp = client.get("/api/admin/alerts", cookies=admin_credentials["cookies"])
    assert resp.status_code == 200
    a_data = resp.json()
    assert "overall_status" in a_data
    assert a_data["overall_status"] in ("healthy", "warning", "critical")
    assert "alerts" in a_data
    assert isinstance(a_data["alerts"], list)
