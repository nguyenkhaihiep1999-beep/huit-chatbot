"""
test_csrf_and_cookie_auth.py
Unit tests kiểm thử Session HttpOnly Cookie, CSRF Protection và Admin Auth (Phase 6):
1. POST /api/auth/session thiết lập HttpOnly cookie và KHÔNG trả về token trong body JSON.
2. Request có cookie session nhưng thiếu X-CSRF-Token bị từ chối 403 CSRF_TOKEN_INVALID.
3. Request có cookie session và có X-CSRF-Token hợp lệ được chấp nhận.
4. Route Admin được bảo vệ bởi dependency require_admin thống nhất, từ chối request không có token hợp lệ với 401.
"""
import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch

from backend.app.main import app
from backend.app.config import settings
from backend.app.services.auth_service import sign_session_id, generate_csrf_token, generate_admin_token

client = TestClient(app)


def test_session_creation_does_not_leak_token_in_body():
    """POST /api/auth/session phải trả về csrf_token, session_id nhưng KHÔNG có token trong body."""
    response = client.post("/api/auth/session")
    assert response.status_code == 200
    data = response.json()

    assert data["success"] is True
    assert "session_id" in data
    assert "csrf_token" in data
    # Tuyệt đối không trả signed token trong body JSON
    assert "token" not in data or data["token"] is None

    # Cookie huit_session_id phải tồn tại
    assert "huit_session_id" in response.cookies


def test_mutating_request_with_cookie_but_missing_csrf_rejected():
    """Request POST có session cookie nhưng thiếu header X-CSRF-Token bị từ chối 403."""
    raw_session = "sess_test_csrf_user"
    token = sign_session_id(raw_session, ttl_seconds=3600)

    # Gửi POST /api/chat có cookie nhưng không có X-CSRF-Token
    response = client.post(
        "/api/chat",
        json={"question": "Xin chào"},
        cookies={"huit_session_id": token}
    )
    assert response.status_code == 403
    data = response.json()
    assert data["error_code"] == "CSRF_TOKEN_INVALID"


def test_mutating_request_with_cookie_and_valid_csrf_accepted():
    """Request POST có session cookie và X-CSRF-Token hợp lệ được xử lý thành công."""
    raw_session = "sess_test_csrf_user_valid"
    token = sign_session_id(raw_session, ttl_seconds=3600)
    csrf_token = generate_csrf_token(raw_session)

    fresh_client = TestClient(app)
    with patch("backend.app.api.routes.chat.answer", return_value={"answer": "Chào bạn", "sources": []}):
        # Gửi POST /api/chat có cả cookie và header X-CSRF-Token
        response = fresh_client.post(
            "/api/chat",
            json={"question": "Xin chào ad"},
            cookies={"huit_session_id": token},
            headers={"X-CSRF-Token": csrf_token}
        )
        # Phải vượt qua tầng CSRF middleware (200 OK)
        assert response.status_code == 200


def test_admin_routes_require_valid_admin_token():
    """Các routes quản trị phải yêu cầu Bearer token admin hợp lệ và từ chối token giả mạo."""
    fresh_client = TestClient(app)

    # 1. Không có token và không có session -> 401 Unauthorized
    resp_no_auth = fresh_client.get("/api/admin/verify")
    assert resp_no_auth.status_code == 401

    # 2. Token không hợp lệ -> 401 Unauthorized
    resp_bad_auth = fresh_client.get(
        "/api/admin/verify",
        headers={"Authorization": "Bearer invalid_token_123"}
    )
    assert resp_bad_auth.status_code == 401

    # 3. User thường đã xác thực session nhưng không có role admin -> 403 Forbidden
    user_token = sign_session_id("sess_regular_student", ttl_seconds=3600)
    resp_forbidden = fresh_client.get(
        "/api/admin/verify",
        cookies={"huit_session_id": user_token}
    )
    assert resp_forbidden.status_code == 403

    # 4. Token admin hợp lệ -> 200 OK
    admin_token = generate_admin_token()
    resp_valid_auth = fresh_client.get(
        "/api/admin/verify",
        headers={"Authorization": f"Bearer {admin_token}"}
    )
    assert resp_valid_auth.status_code == 200
    assert resp_valid_auth.json()["role"] == "admin"


def test_chat_request_with_legacy_admin_cookie_and_valid_user_csrf_accepted():
    """Request POST /api/chat khi trình duyệt còn lưu cookie huit_admin_token cũ vẫn được chấp nhận với user CSRF."""
    raw_session = "sess_student_with_old_admin_cookie"
    user_token = sign_session_id(raw_session, ttl_seconds=3600)
    csrf_token = generate_csrf_token(raw_session)

    fresh_client = TestClient(app)
    with patch("backend.app.api.routes.chat.answer", return_value={"answer": "Chào bạn", "sources": []}):
        response = fresh_client.post(
            "/api/chat",
            json={"question": "Học phí HUIT năm 2026 là bao nhiêu?"},
            cookies={
                "huit_session_id": user_token,
                "huit_admin_token": "legacy_admin_cookie_or_token"
            },
            headers={"X-CSRF-Token": csrf_token}
        )
        assert response.status_code == 200
