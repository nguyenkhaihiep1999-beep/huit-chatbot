"""
test_admin_auth_hardening.py
Bộ kiểm thử toàn diện cho hệ thống xác thực trang quản trị:
1. Login response không chứa token trong body JSON, có HttpOnly cookie.
2. Hai lần login tạo hai session ID ngẫu nhiên và session token khác nhau.
3. Thiếu hoặc sai X-CSRF-Token khi gọi clear-cache bị từ chối 403 CSRF_TOKEN_INVALID.
4. X-CSRF-Token đúng gắn với admin session được chấp nhận 200 OK.
5. Logout thu hồi session phía server, xóa cookie; token cũ bị từ chối 401 ngay sau logout.
6. Token giả mạo, token hết hạn hoặc token đã revoke đều bị từ chối 401.
7. Rate limit cho admin login (5 req / 60s) trả về 429 khi vượt ngưỡng.
8. Cookie production cấu hình đầy đủ HttpOnly=True, Secure=True khi APP_ENV=production, SameSite=Lax, Max-Age.
"""
import os
import time
import pytest
from unittest.mock import patch
from fastapi.testclient import TestClient

from backend.app.main import app
from backend.app.config import settings
from backend.app.services.auth_service import (
    create_admin_session,
    verify_admin_token,
    verify_admin_token_get_session,
    revoke_admin_token,
    AdminSessionStore
)
from backend.app.middleware.rate_limiter import get_rate_limit_store


@pytest.fixture(autouse=True)
def cleanup_stores():
    """Làm sạch session store và rate limit store trước mỗi test."""
    AdminSessionStore.clear_for_testing()
    rate_store = get_rate_limit_store()
    rate_store.clear()
    yield
    AdminSessionStore.clear_for_testing()
    rate_store.clear()


def test_login_response_no_token_in_body_and_sets_httponly_cookie():
    """1. Login response KHÔNG chứa token trong JSON; đặt cookie HttpOnly."""
    client = TestClient(app)
    response = client.post(
        "/api/admin/login",
        json={"username": settings.ADMIN_USERNAME, "password": settings.ADMIN_PASSWORD}
    )
    assert response.status_code == 200
    data = response.json()

    # Bất biến: Tuyệt đối không trả token trong JSON body
    assert "token" not in data
    assert data.get("success") is True
    assert "csrf_token" in data
    assert isinstance(data["csrf_token"], str) and len(data["csrf_token"]) > 10

    # Cookie huit_admin_token phải tồn tại
    assert "huit_admin_token" in response.cookies
    set_cookie_header = response.headers.get("set-cookie", "").lower()
    assert "httponly" in set_cookie_header
    assert "path=/api/admin" in set_cookie_header
    assert "samesite=lax" in set_cookie_header


def test_subsequent_logins_generate_different_sessions():
    """2. Hai lần login liên tiếp phải tạo hai session ID và cookie token khác nhau."""
    client = TestClient(app)

    # Lần login 1
    resp1 = client.post(
        "/api/admin/login",
        json={"username": settings.ADMIN_USERNAME, "password": settings.ADMIN_PASSWORD}
    )
    assert resp1.status_code == 200
    cookie1 = resp1.cookies.get("huit_admin_token")
    csrf1 = resp1.json()["csrf_token"]

    # Lần login 2
    resp2 = client.post(
        "/api/admin/login",
        json={"username": settings.ADMIN_USERNAME, "password": settings.ADMIN_PASSWORD}
    )
    assert resp2.status_code == 200
    cookie2 = resp2.cookies.get("huit_admin_token")
    csrf2 = resp2.json()["csrf_token"]

    # Hai cookie token và hai CSRF token phải hoàn toàn độc lập
    assert cookie1 != cookie2
    assert csrf1 != csrf2

    # Trích xuất session ID từ cookie token opaque
    parts1 = cookie1.split(".")
    parts2 = cookie2.split(".")
    assert len(parts1) == 5
    assert len(parts2) == 5
    session_id_1 = parts1[1]
    session_id_2 = parts2[1]
    assert session_id_1 != session_id_2


def test_clear_cache_missing_or_invalid_csrf_rejected():
    """3. Thiếu hoặc sai CSRF khi gọi clear-cache phải bị từ chối 403."""
    client = TestClient(app)
    login_resp = client.post(
        "/api/admin/login",
        json={"username": settings.ADMIN_USERNAME, "password": settings.ADMIN_PASSWORD}
    )
    admin_cookie = login_resp.cookies.get("huit_admin_token")

    # 3a. Thiếu header X-CSRF-Token -> 403 Forbidden
    resp_missing_csrf = client.post(
        "/api/admin/clear-cache",
        json={"confirm": True},
        cookies={"huit_admin_token": admin_cookie}
    )
    assert resp_missing_csrf.status_code == 403
    assert resp_missing_csrf.json().get("error_code") == "CSRF_TOKEN_INVALID"

    # 3b. Sai header X-CSRF-Token -> 403 Forbidden
    resp_bad_csrf = client.post(
        "/api/admin/clear-cache",
        json={"confirm": True},
        cookies={"huit_admin_token": admin_cookie},
        headers={"X-CSRF-Token": "bad_csrf_token_spoof"}
    )
    assert resp_bad_csrf.status_code == 403
    assert resp_bad_csrf.json().get("error_code") == "CSRF_TOKEN_INVALID"


def test_clear_cache_with_valid_csrf_accepted():
    """4. CSRF đúng gắn với admin session được chấp nhận 200 OK."""
    client = TestClient(app)
    login_resp = client.post(
        "/api/admin/login",
        json={"username": settings.ADMIN_USERNAME, "password": settings.ADMIN_PASSWORD}
    )
    admin_cookie = login_resp.cookies.get("huit_admin_token")
    csrf_token = login_resp.json()["csrf_token"]

    resp = client.post(
        "/api/admin/clear-cache",
        json={"confirm": True},
        cookies={"huit_admin_token": admin_cookie},
        headers={"X-CSRF-Token": csrf_token}
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert "Đã xóa toàn bộ cache" in data["message"]


def test_logout_revokes_session_and_old_token_rejected():
    """5. Logout thu hồi session server-side; xóa cookie; token cũ bị từ chối ngay lập tức."""
    client = TestClient(app)
    login_resp = client.post(
        "/api/admin/login",
        json={"username": settings.ADMIN_USERNAME, "password": settings.ADMIN_PASSWORD}
    )
    admin_cookie = login_resp.cookies.get("huit_admin_token")
    csrf_token = login_resp.json()["csrf_token"]

    # Xác thực rằng token đang active
    verify_before = client.get("/api/admin/verify", cookies={"huit_admin_token": admin_cookie})
    assert verify_before.status_code == 200

    # Thực hiện logout
    logout_resp = client.post(
        "/api/admin/logout",
        cookies={"huit_admin_token": admin_cookie},
        headers={"X-CSRF-Token": csrf_token}
    )
    assert logout_resp.status_code == 200
    assert logout_resp.json()["success"] is True

    # Kiểm tra cookie bị xóa trong Set-Cookie header
    set_cookie = logout_resp.headers.get("set-cookie", "")
    assert "huit_admin_token" in set_cookie
    # Starlette sets max-age=0 to delete cookie
    assert "max-age=0" in set_cookie.lower() or "expires=" in set_cookie.lower()

    # Thử tái sử dụng token cũ gọi GET /api/admin/verify -> 401 Unauthorized
    verify_after = client.get("/api/admin/verify", cookies={"huit_admin_token": admin_cookie})
    assert verify_after.status_code == 401

    # Thử tái sử dụng token cũ gọi POST /api/admin/clear-cache -> 401 Unauthorized
    clear_after = client.post(
        "/api/admin/clear-cache",
        json={"confirm": True},
        cookies={"huit_admin_token": admin_cookie},
        headers={"X-CSRF-Token": csrf_token}
    )
    assert clear_after.status_code == 401


def test_fake_expired_and_revoked_tokens_rejected():
    """6. Token giả, hết hạn hoặc đã revoke bị từ chối 401."""
    client = TestClient(app)

    # 6a. Token giả mạo hoàn toàn
    fake_token = "huit-adm-s.adm_sess_fake.secrets.9999999999.invalid_signature"
    resp_fake = client.get("/api/admin/verify", cookies={"huit_admin_token": fake_token})
    assert resp_fake.status_code == 401

    # 6b. Token đúng chữ ký nhưng đã hết hạn (exp trong quá khứ)
    import hashlib, hmac
    past_exp = int(time.time()) - 3600
    fake_id = "adm_sess_expired"
    fake_secret = "secret123"
    msg = f"adm-sess:{fake_id}:{fake_secret}:{past_exp}"
    sig = hmac.new(settings.ADMIN_TOKEN.encode("utf-8"), msg.encode("utf-8"), hashlib.sha256).hexdigest()[:24]
    expired_token = f"huit-adm-s.{fake_id}.{fake_secret}.{past_exp}.{sig}"
    # Đưa vào store nhưng đã hết hạn
    hash_val = hashlib.sha256(f"{fake_id}:{fake_secret}".encode("utf-8")).hexdigest()
    AdminSessionStore.save_session(hash_val, fake_id, past_exp)

    resp_expired = client.get("/api/admin/verify", cookies={"huit_admin_token": expired_token})
    assert resp_expired.status_code == 401

    # 6c. Token hợp lệ nhưng đã bị revoke thủ công
    _, valid_cookie, _ = create_admin_session(ttl_seconds=3600)
    assert verify_admin_token(valid_cookie) is True
    # Thu hồi token
    revoke_admin_token(valid_cookie)
    assert verify_admin_token(valid_cookie) is False
    resp_revoked = client.get("/api/admin/verify", cookies={"huit_admin_token": valid_cookie})
    assert resp_revoked.status_code == 401


def test_admin_login_rate_limiting():
    """7. Rate limit cho admin login (5 req / 60s) trả về 429 khi spam."""
    client = TestClient(app)

    # Gửi 5 request đăng nhập sai liên tiếp
    for _ in range(5):
        r = client.post(
            "/api/admin/login",
            json={"username": "wrong_user", "password": "wrong_password"}
        )
        assert r.status_code == 401

    # Request thứ 6 từ cùng IP phải bị chặn bởi Rate Limiter với mã 429
    r6 = client.post(
        "/api/admin/login",
        json={"username": "wrong_user", "password": "wrong_password"}
    )
    assert r6.status_code == 429
    data = r6.json()
    assert data.get("error_code") == "RATE_LIMIT_EXCEEDED"
    assert "thử lại sau" in data.get("message", "").lower()


def test_cookie_production_attributes_when_env_production():
    """8. Cookie production: Secure=True khi APP_ENV=production, HttpOnly=True, SameSite=Lax."""
    client = TestClient(app)
    mem_store = get_rate_limit_store()
    with patch("backend.app.middleware.rate_limiter.get_rate_limit_store", return_value=mem_store):
        with patch.dict(os.environ, {
            "ADMIN_USERNAME": "admin_prod",
            "ADMIN_PASSWORD": "admin_password_prod",
            "ADMIN_TOKEN": "admin_token_prod_secret_123456"
        }):
            with patch.object(type(settings), "APP_ENV", new_callable=lambda: property(lambda self: "production")):
                with patch.object(type(settings), "IS_PRODUCTION", new_callable=lambda: property(lambda self: True)):
                    with patch.object(type(settings), "IS_DEVELOPMENT", new_callable=lambda: property(lambda self: False)):
                        resp = client.post(
                            "/api/admin/login",
                            json={"username": settings.ADMIN_USERNAME, "password": settings.ADMIN_PASSWORD}
                        )
                        assert resp.status_code == 200
                        set_cookie = resp.headers.get("set-cookie", "")
                        cookie_lower = set_cookie.lower()
                        assert "secure" in cookie_lower
                        assert "httponly" in cookie_lower
                        assert "samesite=lax" in cookie_lower
                        assert "max-age=86400" in cookie_lower
