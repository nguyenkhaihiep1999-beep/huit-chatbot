import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from backend.app.main import app
from backend.app.config import settings
from backend.app.repositories.mongo_repository import MongoRepository

client = TestClient(app)

def test_root():
    response = client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert "service" in data
    assert "version" in data

def test_health_with_database_connected():
    """Kiểm tra health endpoint khi MongoDB kết nối thành công (Status 200)."""
    mock_client = MagicMock()
    mock_client.admin.command.return_value = {"ok": 1}
    with patch.object(MongoRepository, "get_client", return_value=mock_client):
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert data["database"] == "connected"

def test_health_without_database_connection():
    """Kiểm tra health endpoint khi MongoDB không kết nối được hoặc thiếu cấu hình (Status 503)."""
    with patch.object(MongoRepository, "get_client", side_effect=RuntimeError("Database unavailable")):
        response = client.get("/health")
        assert response.status_code == 503
        data = response.json()
        assert data["status"] == "degraded"
        assert "error" in data["database"]

def test_suggested_questions():
    response = client.get("/api/suggested-questions")
    assert response.status_code == 200
    data = response.json()
    assert "questions" in data
    assert len(data["questions"]) > 0

def test_admin_login_fail():
    response = client.post("/api/admin/login", json={"username": "wrong", "password": "wrong"})
    assert response.status_code == 401

def test_admin_login_success():
    response = client.post("/api/admin/login", json={
        "username": settings.ADMIN_USERNAME,
        "password": settings.ADMIN_PASSWORD
    })
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert "token" not in data
    assert "csrf_token" in data
    assert "huit_admin_token" in response.cookies
    client.cookies.clear()

def test_chat_guardrail_without_mongo():
    """Kiểm tra API Guardrail xử lý câu hỏi chào hỏi/ngoài phạm vi mà hoàn toàn không cần kết nối MongoDB."""
    with patch.object(MongoRepository, "get_client", side_effect=RuntimeError("No MongoDB")):
        with patch.object(MongoRepository, "get_events_collection", side_effect=RuntimeError("No MongoDB")):
            response = client.post("/api/chat", json={"question": "Xin chào ad"})
            assert response.status_code == 200
            data = response.json()
            assert "answer" in data
            assert "Chào bạn!" in data["answer"]
            assert "request_id" in response.headers.get("x-request-id", "") or "request_id" in str(data)

def test_chat_guardrail_out_of_scope_without_mongo():
    """Kiểm tra API Guardrail từ chối câu hỏi ngoài ngữ cảnh mà không cần MongoDB."""
    with patch.object(MongoRepository, "get_client", side_effect=RuntimeError("No MongoDB")):
        with patch.object(MongoRepository, "get_events_collection", side_effect=RuntimeError("No MongoDB")):
            response = client.post("/api/chat", json={"question": "Giá vàng hôm nay bao nhiêu?"})
            assert response.status_code == 200
            data = response.json()
            assert "nằm ngoài phần thông tin" in data["answer"]

def test_chat_stream_guardrail():
    """Kiểm tra định dạng NDJSON streaming qua /api/chat-stream."""
    response = client.post("/api/chat-stream", json={"question": "Xin chào ad"})
    assert response.status_code == 200
    lines = [line for line in response.text.strip().split("\n") if line]
    assert len(lines) >= 3
    # Dòng 1 phải là start (hoặc stream_started legacy)
    assert any(t in lines[0] for t in ('"type": "start"', '"type": "stream_started"'))
    # Dòng 2 phải là progress (hoặc meta legacy)
    assert any(t in lines[1] for t in ('"type": "progress"', '"type": "meta"'))
    # Dòng 3 phải là token (hoặc text_delta legacy)
    assert any(t in lines[2] for t in ('"type": "token"', '"type": "text_delta"'))

def test_cors_headers():
    """Kiểm tra phản hồi CORS headers không cho phép kết hợp wildcard với credentials."""
    response = client.options(
        "/api/chat",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "POST",
        }
    )
    assert response.status_code == 200
    assert "access-control-allow-origin" in response.headers
    # Origin được phép cụ thể
    assert response.headers["access-control-allow-origin"] == "http://localhost:3000"
    # Khi origin cụ thể, allow-credentials phải là true
    assert response.headers.get("access-control-allow-credentials") == "true"

def test_development_config_defaults():
    """Kiểm tra cấu hình development cung cấp fallback an toàn."""
    from backend.app.config import Settings
    with patch.dict("os.environ", {"APP_ENV": "development"}, clear=True):
        dev_settings = Settings()
        assert dev_settings.APP_ENV == "development"
        assert dev_settings.ADMIN_USERNAME == "admin_dev"
        assert len(dev_settings.ADMIN_PASSWORD) > 0
        assert len(dev_settings.ADMIN_TOKEN) > 0

def test_production_config_missing_vars_raises_error():
    """Kiểm tra môi trường production báo lỗi rõ ràng nếu thiếu thông tin bảo mật."""
    from backend.app.config import Settings
    with patch.dict("os.environ", {"APP_ENV": "production"}, clear=True):
        prod_settings = Settings()
        assert prod_settings.APP_ENV == "production"
        assert prod_settings.IS_DEVELOPMENT is False
        with pytest.raises(RuntimeError, match="ADMIN_USERNAME"):
            _ = prod_settings.ADMIN_USERNAME
        with pytest.raises(RuntimeError, match="ADMIN_PASSWORD"):
            _ = prod_settings.ADMIN_PASSWORD
        with pytest.raises(RuntimeError, match="ADMIN_TOKEN"):
            _ = prod_settings.ADMIN_TOKEN
        with pytest.raises(RuntimeError, match="CORS_ALLOWED_ORIGINS"):
            _ = prod_settings.CORS_ALLOWED_ORIGINS
        with pytest.raises(RuntimeError, match="Lỗi cấu hình bảo mật"):
            prod_settings.validate_security_config()

def test_preview_and_staging_env_missing_vars_raises_error():
    """Kiểm tra môi trường staging và preview bắt buộc có đầy đủ biến bảo mật."""
    from backend.app.config import Settings
    for env_name in ["staging", "preview"]:
        with patch.dict("os.environ", {"APP_ENV": env_name}, clear=True):
            settings_obj = Settings()
            assert settings_obj.IS_DEVELOPMENT is False
            with pytest.raises(RuntimeError, match="Lỗi cấu hình bảo mật"):
                settings_obj.validate_security_config()

def test_vercel_env_detection_and_validation():
    """Kiểm tra nhận diện VERCEL_ENV khi APP_ENV chưa được đặt."""
    from backend.app.config import Settings
    # Khi VERCEL_ENV=production và APP_ENV không có
    with patch.dict("os.environ", {"VERCEL_ENV": "production"}, clear=True):
        vercel_settings = Settings()
        assert vercel_settings.APP_ENV == "production"
        assert vercel_settings.IS_DEVELOPMENT is False
        with pytest.raises(RuntimeError, match="Lỗi cấu hình bảo mật"):
            vercel_settings.validate_security_config()

