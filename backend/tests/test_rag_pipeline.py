import pytest
from unittest.mock import MagicMock, patch
from backend.app.config import settings
from backend.app.rag.intent import normalize_text, classify_intent, expand_query
from backend.app.rag.guardrails import check_intent_guardrail, is_major_catalog_question
from backend.app.cache.memory_cache import MemoryCache, compute_cache_key
from backend.app.services.auth_service import verify_admin_credentials, verify_admin_token, generate_admin_token
from backend.app.telemetry.metrics import LatencyBreakdown, log_event
from backend.app.repositories.mongo_repository import MongoRepository

def test_normalize_text():
    raw = "Học phí ngành CNTT và ĐIỂM CHUẨN năm 2026?"
    norm = normalize_text(raw)
    assert "hoc phi" in norm
    assert "cntt" in norm
    assert "diem chuan" in norm

def test_classify_intent():
    assert classify_intent("Học phí HUIT năm 2026 là bao nhiêu?") == "tuition"
    assert classify_intent("Điểm chuẩn ngành Công nghệ thông tin") == "cutoff"
    assert classify_intent("Hồ sơ thủ tục nhập học") == "admission_procedure"
    assert classify_intent("Chính sách học bổng cho tân sinh viên") == "scholarship"

def test_expand_query():
    expanded = expand_query("Điểm chuẩn ngành cntt và attt")
    assert "công nghệ thông tin" in expanded
    assert "an toàn thông tin" in expanded

def test_guardrails_greeting():
    res = check_intent_guardrail("Xin chào ad")
    assert res["is_handled"] is True
    assert "Chào bạn!" in res["answer"]

def test_guardrails_identity():
    res = check_intent_guardrail("Bạn có biết tôi là ai không?")
    assert res["is_handled"] is True
    assert "không biết thông tin cá nhân" in res["answer"]

def test_guardrails_out_of_scope():
    res = check_intent_guardrail("Dự báo thời tiết hôm nay thế nào?")
    assert res["is_handled"] is True
    assert "nằm ngoài phần thông tin" in res["answer"]

def test_major_catalog_detection():
    assert is_major_catalog_question("HUIT có những ngành đào tạo nào?") is True
    assert is_major_catalog_question("Danh sách các ngành đại học chính quy") is True
    assert is_major_catalog_question("Điểm chuẩn ngành CNTT") is False

def test_memory_cache():
    key = compute_cache_key("test question")
    val = {"answer": "test answer", "meta": {"test": True}}
    MemoryCache.set(key, val, ttl_hours=1)
    retrieved = MemoryCache.get(key)
    assert retrieved is not None
    assert retrieved["answer"] == "test answer"

def test_admin_auth():
    assert verify_admin_credentials(settings.ADMIN_USERNAME, settings.ADMIN_PASSWORD) is True
    assert verify_admin_credentials(settings.ADMIN_USERNAME, "wrongpass") is False
    token = generate_admin_token()
    assert verify_admin_token(token) is True
    assert verify_admin_token("invalid-token") is False

def test_latency_breakdown_metrics():
    """Kiểm tra LatencyBreakdown phân tách đầy đủ 10 số đo bắt buộc."""
    lb = LatencyBreakdown(request_id="test-req-123")
    required_keys = [
        "cache_lookup", "embedding", "vector_search", "keyword_search",
        "rerank", "visual_lookup", "llm_ttft", "llm_generation",
        "cache_write", "total"
    ]
    data = lb.to_dict()
    for k in required_keys:
        assert k in data, f"Thiếu metric '{k}' trong LatencyBreakdown"

def test_log_event_privacy_sanitization():
    """Kiểm tra log_event tuyệt đối KHÔNG lưu nội dung câu hỏi dạng plain text."""
    with patch("backend.app.telemetry.metrics.telemetry_operations.record_telemetry_event") as mock_record:
        log_event(
            question="Bí mật riêng tư của thí sinh",
            response_data={"answer": "Câu trả lời mẫu"},
            elapsed_ms=120.5,
            intent="general",
            request_id="req-privacy-test"
        )
        assert mock_record.called
        event_doc = mock_record.call_args[0][0]
        # Không có trường 'question' lưu chuỗi thô
        assert "question" not in event_doc, "Vi phạm bảo mật: Không được lưu văn bản thô câu hỏi!"
        # Bắt buộc có mã hash và độ dài
        assert "question_hash" in event_doc
        assert "question_length" in event_doc
        assert event_doc["question_length"] == len("Bí mật riêng tư của thí sinh")


def test_rag_architecture_equivalence():
    """Kiểm tra tính tương đương RAG với bản gốc kiến trúc."""
    assert settings.EMBEDDING_MODEL == "intfloat/multilingual-e5-large"
    assert settings.EMBEDDING_DIMS == 1024
    assert settings.KB_VERSION == "huit-kb-2026-07-v4-semantic"
    assert settings.RAG_VERSION == "rag-v10-grounded-score-source"
    assert settings.TOP_K == 3

def test_llm_model_order_and_providers():
    """Kiểm tra danh sách endpoint và thứ tự model/provider được tạo đúng thứ tự mà không gọi API thật."""
    from backend.app.rag.generation import get_llm_endpoints

    with patch.object(settings, "GEMINI_API_KEY", "mock-gemini-key"), \
         patch.object(settings, "GROQ_API_KEY", "mock-groq-key"), \
         patch.object(settings, "OPENROUTER_KEY", "mock-openrouter-key"), \
         patch("backend.app.rag.generation.OpenAI") as mock_openai_cls:
        
        mock_openai_cls.return_value = MagicMock()
        endpoints = get_llm_endpoints()

        # Tổng số models phải là 3 (Gemini) + 5 (Groq) + 5 (OpenRouter) = 13 models
        assert len(endpoints) == 13

        providers = [ep[2] for ep in endpoints]
        model_names = [ep[1] for ep in endpoints]

        # 1. Gemini Direct đứng đầu tiên
        assert providers[0:3] == ["GeminiDirect", "GeminiDirect", "GeminiDirect"]
        assert model_names[0:3] == [settings.GEMINI_MODEL, "gemini-1.5-flash", "gemini-1.5-flash-8b"]

        # 2. Groq Direct đứng thứ hai
        assert providers[3:8] == ["GroqDirect"] * 5
        assert model_names[3:8] == [
            "openai/gpt-oss-120b",
            "openai/gpt-oss-20b",
            "qwen/qwen3.8-27b",
            "llama-3.3-70b-versatile",
            "llama-3.1-8b-instant"
        ]

        # 3. OpenRouter đứng thứ ba (fallback)
        assert providers[8:13] == ["OpenRouter"] * 5
        assert model_names[8:13] == [
            settings.OPENROUTER_MODEL,
            "qwen/qwen-2.5-72b-instruct",
            "google/gemma-4-26b-a4b-it:free",
            "google/gemma-4-31b-it:free",
            "openrouter/free",
        ]

