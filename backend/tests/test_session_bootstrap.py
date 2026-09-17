"""
test_session_bootstrap.py
Kiểm thử toàn diện quy trình Session Bootstrap và CSRF Protection:
1. Tạo session mới thành công (HTTP 200, session_id, csrf_token, Set-Cookie huit_session_id, X-Request-ID).
2. Refresh với cookie hợp lệ tái sử dụng session (idempotent / non-duplicating).
3. Cookie sai hoặc hết hạn tạo phiên an toàn mới.
4. Endpoint session được miễn CSRF bootstrap ban đầu.
5. Thiếu production secret làm startup fail-closed an toàn.
"""
import os
import pytest
from fastapi.testclient import TestClient
from backend.app.main import app
from backend.app.config import settings
from backend.app.services.auth_service import sign_session_id, generate_session_token


@pytest.fixture
def client():
    return TestClient(app)


def test_create_session_success(client):
    """1. Tạo session mới thành công với đầy đủ headers, cookies và body hợp lệ."""
    resp = client.post("/api/auth/session", json={})
    assert resp.status_code == 200
    data = resp.json()

    assert data["success"] is True
    assert data["session_id"].startswith("sess_")
    assert "csrf_token" in data
    assert data["issued_at"] > 0
    assert data["expires_at"] > data["issued_at"]

    # Kiểm tra Set-Cookie
    cookies = resp.cookies
    assert "huit_session_id" in cookies
    cookie_val = cookies["huit_session_id"]
    assert len(cookie_val.split(".")) == 3  # session_id.exp.sig

    # Kiểm tra X-Request-ID
    assert "X-Request-ID" in resp.headers


def test_refresh_session_reuses_valid_cookie(client):
    """2. Refresh với cookie hợp lệ tái sử dụng session hiện có."""
    # Bước 1: Tạo session đầu tiên
    r1 = client.post("/api/auth/session", json={})
    assert r1.status_code == 200
    sess_id_1 = r1.json()["session_id"]
    cookie_1 = r1.cookies["huit_session_id"]

    # Bước 2: Gọi lại kèm cookie_1
    client.cookies.set("huit_session_id", cookie_1)
    r2 = client.post("/api/auth/session", json={})
    assert r2.status_code == 200
    sess_id_2 = r2.json()["session_id"]

    # Xác nhận cùng session_id, không tạo session mới vô hạn
    assert sess_id_1 == sess_id_2


def test_invalid_or_expired_cookie_creates_safe_new_session(client):
    """3. Cookie sai hoặc giả mạo tạo phiên mới an toàn, không bị crash 500."""
    client.cookies.set("huit_session_id", "malformed.cookie.signature_tampered")
    resp = client.post("/api/auth/session", json={})
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["session_id"].startswith("sess_")
    assert "huit_session_id" in resp.cookies


def test_session_endpoint_exempt_from_csrf_bootstrap(client):
    """4. POST /api/auth/session được miễn trừ CSRF middleware khi chưa có token."""
    resp = client.post(
        "/api/auth/session",
        json={},
        headers={"User-Agent": "Mozilla/5.0"}
    )
    assert resp.status_code == 200
    assert "csrf_token" in resp.json()


def test_production_fails_closed_without_secrets():
    """5. Môi trường production bắt buộc fail-closed khi thiếu secret bảo mật."""
    old_env = os.environ.get("APP_ENV")
    old_cors = os.environ.get("CORS_ALLOWED_ORIGINS")
    try:
        os.environ["APP_ENV"] = "production"
        os.environ.pop("CORS_ALLOWED_ORIGINS", None)

        with pytest.raises(RuntimeError) as exc_info:
            _ = settings.CORS_ALLOWED_ORIGINS
        assert "CORS_ALLOWED_ORIGINS" in str(exc_info.value)
    finally:
        if old_env is not None:
            os.environ["APP_ENV"] = old_env
        else:
            os.environ.pop("APP_ENV", None)
        if old_cors is not None:
            os.environ["CORS_ALLOWED_ORIGINS"] = old_cors
        else:
            os.environ.pop("CORS_ALLOWED_ORIGINS", None)
