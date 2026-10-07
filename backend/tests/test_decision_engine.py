"""
test_decision_engine.py
Comprehensive Mock-Only Unit and Integration Tests for Jev Decision Engine (TypeSafe AI).
Tất cả 16 yêu cầu kiểm thử bắt buộc:
1. JEV_MODE=off không tạo HTTP request.
2. Shadow mode không thay đổi kết quả RAG.
3. Assist mode chỉ gọi Jev với câu hỏi mơ hồ.
4. Intent rõ ràng không gọi Jev.
5. Guardrail bị chặn không gọi Jev.
6. Redaction email, điện thoại, CCCD, token và secret.
7. Response choice/score/noul hợp lệ.
8. Response sai schema bị từ chối.
9. Timeout fallback an toàn.
10. 401/403 không retry.
11. 429/5xx retry có giới hạn (tối đa 1 retry).
12. Circuit breaker mở và tự phục hồi.
13. Không log API key hoặc raw state.
14. Canonical JSON Schema và Pydantic không drift.
15. Luồng NDJSON hiện tại không bị thay đổi.
16. Gemini/Groq/OpenRouter vẫn hoạt động khi Jev bị tắt hoặc lỗi.
"""
import asyncio
import json
import time
import pytest
import httpx

from backend.app.config import settings
from backend.app.contracts.schema_registry import load_schema, validate_contract
from backend.app.decision_engine.contracts import (
    DecisionItem,
    DecisionRequest,
    DecisionResult,
    DecisionUsage,
    QuestionDefinition,
)
from backend.app.decision_engine.policies import (
    get_evidence_sufficiency_questions,
    get_intent_decision_questions,
)
from backend.app.decision_engine.providers.base import (
    BaseDecisionProvider,
    DecisionAuthenticationError,
    DecisionRateLimitError,
    DecisionServerError,
    DecisionTimeoutError,
    DecisionValidationError,
)
from backend.app.decision_engine.providers.typesafe_jev import TypeSafeJevProvider
from backend.app.decision_engine.redaction import (
    anonymize_request_hash,
    build_evidence_decision_state,
    build_intent_decision_state,
    redact_text,
)
from backend.app.decision_engine.service import (
    CircuitBreaker,
    DecisionService,
    DecisionTracker,
    is_intent_ambiguous,
)
from backend.app.rag.pipeline import stream_answer


# ---------------------------------------------------------------------------
# TEST 1: JEV_MODE=off không tạo HTTP request
# ---------------------------------------------------------------------------
def test_01_jev_mode_off_does_not_make_http_requests(monkeypatch):
    monkeypatch.setenv("JEV_MODE", "off")

    call_count = 0

    def mock_handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        return httpx.Response(200, json={"status": "unexpected"})

    mock_client = httpx.AsyncClient(transport=httpx.MockTransport(mock_handler))
    provider = TypeSafeJevProvider(api_key="test-key", client=mock_client)
    service = DecisionService(provider=provider)

    req = DecisionRequest(
        decision_type="intent",
        state="Test state",
        model="jev-latest",
        questions=get_intent_decision_questions(),
    )
    result = asyncio.run(service.execute_decision(req))
    assert result.status == "skipped"
    assert call_count == 0

    intent_res = asyncio.run(service.decide_intent("Hỏi chung chung", "general"))
    assert intent_res is None
    assert call_count == 0


# ---------------------------------------------------------------------------
# TEST 2: Shadow mode không thay đổi kết quả RAG
# ---------------------------------------------------------------------------
def test_02_shadow_mode_does_not_alter_rag_result(monkeypatch):
    monkeypatch.setenv("JEV_MODE", "shadow")
    monkeypatch.setenv("TYPESAFE_API_KEY", "test-jev-key-shadow")

    call_count = 0

    def mock_handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        return httpx.Response(
            200,
            json={
                "answers": {
                    "intent": {
                        "type": "choice",
                        "choice": "scholarship",
                        "confidence": 0.99,
                        "probabilities": {"scholarship": 0.99},
                    }
                },
                "model": "jev-latest",
                "usage": {"input_tokens": 50, "output_tokens": 0},
            },
        )

    mock_client = httpx.AsyncClient(transport=httpx.MockTransport(mock_handler))
    provider = TypeSafeJevProvider(api_key="test-jev-key-shadow", client=mock_client)
    shadow_service = DecisionService(provider=provider)

    from backend.app.rag import pipeline
    monkeypatch.setattr(pipeline, "decision_service", shadow_service)

    # Mock retrieval và LLM để cô lập test
    monkeypatch.setattr(
        pipeline,
        "retrieve",
        lambda query, top_k, timings=None: [
            {"title": "Tổng quan tuyển sinh HUIT", "text": "Trường tuyển sinh 2026...", "score": 0.85}
        ],
    )
    monkeypatch.setattr(
        pipeline,
        "stream_llm",
        lambda sys, user: iter(["Chào bạn, ", "đây là ", "thông tin tuyển sinh HUIT."]),
    )

    events = list(pipeline.stream_answer("Em muốn hỏi thông tin chung", use_cache=False))
    parsed_events = [json.loads(line) for line in events if line.strip()]

    # Kiểm tra stream thành công và không bị vỡ cấu trúc
    event_types = [e["type"] for e in parsed_events]
    assert "start" in event_types
    assert "done" in event_types

    done_event = [e for e in parsed_events if e["type"] == "done"][0]
    assert done_event["payload"]["cached"] is False
    assert call_count >= 1


# ---------------------------------------------------------------------------
# TEST 3: Assist mode chỉ gọi Jev với câu hỏi mơ hồ
# ---------------------------------------------------------------------------
def test_03_assist_mode_invokes_jev_for_ambiguous_question(monkeypatch):
    monkeypatch.setenv("JEV_MODE", "assist")
    monkeypatch.setenv("TYPESAFE_API_KEY", "test-key-assist")

    called_payload = None

    def mock_handler(request: httpx.Request) -> httpx.Response:
        nonlocal called_payload
        called_payload = json.loads(request.content.decode("utf-8"))
        return httpx.Response(
            200,
            json={
                "answers": {
                    "intent": {
                        "type": "choice",
                        "choice": "tuition",
                        "confidence": 0.95,
                        "probabilities": {"tuition": 0.95, "admission": 0.05},
                    },
                    "needs_clarification": {
                        "type": "noul",
                        "noul": 0.1,
                        "confidence": 0.9,
                    },
                },
                "model": "jev-latest",
                "usage": {"input_tokens": 60, "output_tokens": 0},
            },
        )

    mock_client = httpx.AsyncClient(transport=httpx.MockTransport(mock_handler))
    provider = TypeSafeJevProvider(api_key="test-key-assist", client=mock_client)
    service = DecisionService(provider=provider)

    # "Em muốn tìm hiểu thông tin" là câu hỏi mơ hồ (classify_intent = general)
    assert is_intent_ambiguous("Em muốn tìm hiểu thông tin", "general") is True

    result = asyncio.run(service.decide_intent("Em muốn tìm hiểu thông tin", "general"))
    assert result is not None
    assert result.status == "success"
    assert result.decisions["intent"].choice == "tuition"
    assert result.decisions["intent"].confidence == 0.95
    assert called_payload is not None
    assert "task" in called_payload["state"]


# ---------------------------------------------------------------------------
# TEST 4: Intent rõ ràng không gọi Jev
# ---------------------------------------------------------------------------
def test_04_clear_intent_does_not_call_jev():
    # Câu hỏi học phí rõ ràng
    q1 = "Học phí ngành Công nghệ thông tin là bao nhiêu một tín chỉ?"
    assert is_intent_ambiguous(q1, "tuition") is False

    # Câu hỏi điểm chuẩn rõ ràng
    q2 = "Điểm chuẩn ngành Kỹ thuật phần mềm năm 2026 là bao nhiêu?"
    assert is_intent_ambiguous(q2, "cutoff") is False

    # Câu hỏi học bổng rõ ràng
    q3 = "Chính sách học bổng miễn giảm học phí cho tân sinh viên?"
    assert is_intent_ambiguous(q3, "scholarship") is False


# ---------------------------------------------------------------------------
# TEST 5: Guardrail bị chặn không gọi Jev
# ---------------------------------------------------------------------------
def test_05_blocked_guardrail_does_not_call_jev(monkeypatch):
    monkeypatch.setenv("JEV_MODE", "assist")
    monkeypatch.setenv("TYPESAFE_API_KEY", "test-key")

    call_count = 0

    def mock_handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        return httpx.Response(200, json={})

    mock_client = httpx.AsyncClient(transport=httpx.MockTransport(mock_handler))
    provider = TypeSafeJevProvider(api_key="test-key", client=mock_client)
    service = DecisionService(provider=provider)

    from backend.app.rag import pipeline
    monkeypatch.setattr(pipeline, "decision_service", service)

    # Câu hỏi riêng tư rơi vào Intent Guardrail 0 (Personal Identity)
    personal_q = "Bạn có biết tôi là ai không?"
    events = list(pipeline.stream_answer(personal_q, use_cache=False))

    parsed = [json.loads(line) for line in events if line.strip()]
    assert any(e.get("payload", {}).get("stage") == "guardrails" for e in parsed)
    # Jev tuyệt đối không được gọi khi guardrail đã chặn
    assert call_count == 0


# ---------------------------------------------------------------------------
# TEST 6: Redaction email, điện thoại, CCCD, token và secret
# ---------------------------------------------------------------------------
def test_06_redaction_email_phone_cccd_token_secret():
    raw_text = (
        "Chào em, email của thầy là admin.huit@gmail.com, số điện thoại 0912345678 và +84987654321. "
        "Số CCCD là 079201012345. "
        "Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.e30.t-IDc95ffORHHHM "
        "Khóa bí mật sk-1234567890abcdef123456 và admin_token: huit_super_secret_token_2026. "
        "Database mongodb+srv://admin:pass123@cluster0.hyj8rab.mongodb.net/test."
    )

    redacted = redact_text(raw_text)

    # Xác nhận các dữ liệu nhạy cảm đã bị thay thế hoàn toàn
    assert "admin.huit@gmail.com" not in redacted
    assert "[REDACTED_EMAIL]" in redacted

    assert "0912345678" not in redacted
    assert "+84987654321" not in redacted
    assert "[REDACTED_PHONE]" in redacted

    assert "079201012345" not in redacted
    assert "[REDACTED_ID]" in redacted

    assert "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9" not in redacted
    assert "[REDACTED_TOKEN]" in redacted

    assert "sk-1234567890abcdef123456" not in redacted
    assert "[REDACTED_KEY]" in redacted

    assert "huit_super_secret_token_2026" not in redacted
    assert "[REDACTED_SECRET]" in redacted

    assert "mongodb+srv://" not in redacted
    assert "[REDACTED_MONGODB_URI]" in redacted

    # Kiểm tra build_intent_decision_state
    state = build_intent_decision_state("Số điện thoại 0909123456", "contact")
    assert "0909123456" not in state
    assert "[REDACTED_PHONE]" in state


# ---------------------------------------------------------------------------
# TEST 7: Response choice/score/noul hợp lệ
# ---------------------------------------------------------------------------
def test_07_valid_response_choice_score_noul():
    def mock_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "answers": {
                    "question_choice": {
                        "type": "choice",
                        "choice": "cutoff",
                        "confidence": 0.94,
                        "probabilities": {"cutoff": 0.94, "floor_score": 0.06},
                    },
                    "question_score": {
                        "type": "score",
                        "score": 1.05,
                        "legend": {"0": "Calm", "1": "Frustrated", "2": "Very angry"},
                        "probabilities": {"0": 0.0, "1": 0.95, "2": 0.05},
                        "confidence": 0.88,
                    },
                    "question_noul": {
                        "type": "noul",
                        "noul": 0.85,
                        "confidence": 0.91,
                    },
                },
                "model": "jev-latest",
                "usage": {"input_tokens": 150, "output_tokens": 0},
            },
        )

    mock_client = httpx.AsyncClient(transport=httpx.MockTransport(mock_handler))
    provider = TypeSafeJevProvider(api_key="test-key", client=mock_client)

    req = DecisionRequest(
        decision_type="custom",
        state="Test decision state",
        model="jev-latest",
        questions={
            "question_choice": QuestionDefinition(type="choice"),
            "question_score": QuestionDefinition(type="score", criteria=["Calm", "Frustrated", "Very angry"]),
            "question_noul": QuestionDefinition(type="noul"),
        },
    )

    result = asyncio.run(provider.decide(req))
    assert result.status == "success"
    assert result.decisions["question_choice"].choice == "cutoff"
    assert result.decisions["question_score"].score == 1.05
    assert result.decisions["question_noul"].noul == 0.85
    assert result.usage.input_tokens == 150


# ---------------------------------------------------------------------------
# TEST 8: Response sai schema bị từ chối
# ---------------------------------------------------------------------------
def test_08_invalid_response_schema_rejected():
    # 1. Server trả về string thay vì json object
    def mock_handler_bad_type(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="not a json object")

    mock_client = httpx.AsyncClient(transport=httpx.MockTransport(mock_handler_bad_type))
    provider = TypeSafeJevProvider(api_key="test-key", client=mock_client)

    req = DecisionRequest(
        decision_type="intent",
        state="Test state",
        model="jev-latest",
        questions=get_intent_decision_questions(),
    )
    with pytest.raises(DecisionValidationError):
        asyncio.run(provider.decide(req))

    # 2. Server trả về thiếu trường answers
    def mock_handler_missing_answers(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": "missing_answers_field"})

    mock_client_missing = httpx.AsyncClient(transport=httpx.MockTransport(mock_handler_missing_answers))
    provider_missing = TypeSafeJevProvider(api_key="test-key", client=mock_client_missing)
    with pytest.raises(DecisionValidationError):
        asyncio.run(provider_missing.decide(req))


# ---------------------------------------------------------------------------
# TEST 9: Timeout fallback an toàn
# ---------------------------------------------------------------------------
def test_09_timeout_safe_fallback(monkeypatch):
    monkeypatch.setenv("JEV_MODE", "assist")

    def mock_timeout_handler(request: httpx.Request):
        raise httpx.ReadTimeout("Request timed out")

    mock_client = httpx.AsyncClient(transport=httpx.MockTransport(mock_timeout_handler))
    provider = TypeSafeJevProvider(api_key="test-key", timeout=0.1, client=mock_client)
    service = DecisionService(provider=provider)

    req = DecisionRequest(
        decision_type="intent",
        state="Test timeout state",
        model="jev-latest",
        questions=get_intent_decision_questions(),
    )
    result = asyncio.run(service.execute_decision(req))
    assert result.status == "fallback"
    assert "DecisionTimeoutError" in (result.error_message or "")


# ---------------------------------------------------------------------------
# TEST 10: 401/403 không retry
# ---------------------------------------------------------------------------
def test_10_401_403_do_not_retry():
    call_attempts = 0

    def mock_auth_fail(request: httpx.Request) -> httpx.Response:
        nonlocal call_attempts
        call_attempts += 1
        return httpx.Response(401, json={"error": "Unauthorized API key"})

    mock_client = httpx.AsyncClient(transport=httpx.MockTransport(mock_auth_fail))
    provider = TypeSafeJevProvider(api_key="invalid-key", client=mock_client)

    req = DecisionRequest(
        decision_type="intent",
        state="Test auth fail",
        model="jev-latest",
        questions=get_intent_decision_questions(),
    )
    with pytest.raises(DecisionAuthenticationError):
        asyncio.run(provider.decide(req))

    # Tuyệt đối không retry khi gặp 401/403
    assert call_attempts == 1


# ---------------------------------------------------------------------------
# TEST 11: 429/5xx retry có giới hạn (tối đa 1 retry)
# ---------------------------------------------------------------------------
def test_11_429_5xx_limited_retry():
    # Kịch bản 1: 429 lần 1 -> 200 lần 2 (thành công sau 1 retry)
    call_attempts_429 = 0

    def mock_handler_429_recover(request: httpx.Request) -> httpx.Response:
        nonlocal call_attempts_429
        call_attempts_429 += 1
        if call_attempts_429 == 1:
            return httpx.Response(429, json={"error": "Rate limit exceeded"})
        return httpx.Response(
            200,
            json={
                "answers": {
                    "intent": {"type": "choice", "choice": "tuition", "confidence": 0.9},
                    "needs_clarification": {"type": "noul", "noul": 0.05, "confidence": 0.9},
                },
                "model": "jev-latest",
            },
        )

    mock_client_429 = httpx.AsyncClient(transport=httpx.MockTransport(mock_handler_429_recover))
    provider_429 = TypeSafeJevProvider(api_key="test-key", client=mock_client_429)

    req = DecisionRequest(
        decision_type="intent",
        state="Test 429",
        model="jev-latest",
        questions=get_intent_decision_questions(),
    )
    res = asyncio.run(provider_429.decide(req))
    assert res.status == "success"
    assert call_attempts_429 == 2

    # Kịch bản 2: 503 liên tục -> chỉ retry 1 lần (tổng 2 lần) rồi dừng
    call_attempts_503 = 0

    def mock_handler_503_fail(request: httpx.Request) -> httpx.Response:
        nonlocal call_attempts_503
        call_attempts_503 += 1
        return httpx.Response(503, json={"error": "Service Unavailable"})

    mock_client_503 = httpx.AsyncClient(transport=httpx.MockTransport(mock_handler_503_fail))
    provider_503 = TypeSafeJevProvider(api_key="test-key", client=mock_client_503)

    with pytest.raises(DecisionServerError):
        asyncio.run(provider_503.decide(req))

    assert call_attempts_503 == 2


# ---------------------------------------------------------------------------
# TEST 12: Circuit breaker mở và tự phục hồi
# ---------------------------------------------------------------------------
def test_12_circuit_breaker_trips_and_recovers():
    cb = CircuitBreaker(failure_threshold=3, cooldown_seconds=0.1)

    assert cb.state == "closed"
    assert cb.allow_request() is True

    # 3 lần lỗi liên tiếp -> chuyển sang open
    cb.record_failure()
    cb.record_failure()
    cb.record_failure()
    assert cb.state == "open"
    assert cb.allow_request() is False

    # Chờ hết cooldown -> chuyển sang half_open
    time.sleep(0.15)
    assert cb.allow_request() is True
    assert cb.state == "half_open"

    # Gọi thành công -> hồi phục về closed
    cb.record_success()
    assert cb.state == "closed"
    assert cb.consecutive_failures == 0


# ---------------------------------------------------------------------------
# TEST 13: Không log API key hoặc raw state
# ---------------------------------------------------------------------------
def test_13_no_api_key_or_raw_state_in_logs():
    secret_key = "typesafe_super_secret_production_key_xyz987"
    provider = TypeSafeJevProvider(api_key=secret_key)

    repr_str = repr(provider)
    str_str = str(provider)

    assert secret_key not in repr_str
    assert secret_key not in str_str
    assert "typesafe_super_secret" not in repr_str

    # Request hash an toàn
    raw_user_question = "Tôi muốn tra cứu thông tin học bổng bí mật"
    anon_hash = anonymize_request_hash(raw_user_question)
    assert raw_user_question not in anon_hash
    assert len(anon_hash) == 16


# ---------------------------------------------------------------------------
# TEST 14: Canonical JSON Schema và Pydantic không drift
# ---------------------------------------------------------------------------
def test_14_canonical_schema_and_pydantic_no_drift():
    # 1. Validate DecisionRequest canonical schema
    req_schema = load_schema("huit.decision.decision-request", "2.0.0")
    assert req_schema["title"] == "HUIT decision engine request contract"

    sample_request = DecisionRequest(
        decision_type="intent",
        state="Dữ liệu trạng thái câu hỏi tuyển sinh HUIT",
        model="jev-latest",
        questions=get_intent_decision_questions(),
        context_metadata={"request_id": "req-123"},
    )
    # Kiểm tra payload của Pydantic khớp 100% với JSON Schema Draft 2020-12
    validate_contract("huit.decision.decision-request", "2.0.0", sample_request.model_dump())

    # 2. Validate DecisionResult canonical schema
    res_schema = load_schema("huit.decision.decision-result", "1.0.0")
    assert res_schema["title"] == "HUIT decision engine result contract"

    sample_result = DecisionResult(
        decision_type="intent",
        status="success",
        provider="typesafe_jev",
        model="jev-latest",
        decisions={
            "intent": DecisionItem(
                type="choice",
                choice="tuition",
                confidence=0.92,
                probabilities={"tuition": 0.92, "general": 0.08},
            )
        },
        usage=DecisionUsage(input_tokens=80, output_tokens=0),
        latency_ms=120.5,
    )
    validate_contract("huit.decision.decision-result", "1.0.0", sample_result.model_dump())


# ---------------------------------------------------------------------------
# TEST 15: Luồng NDJSON hiện tại không bị thay đổi
# ---------------------------------------------------------------------------
def test_15_ndjson_v2_stream_protocol_intact(monkeypatch):
    monkeypatch.setenv("JEV_MODE", "off")

    from backend.app.rag import pipeline
    monkeypatch.setattr(
        pipeline,
        "retrieve",
        lambda query, top_k, timings=None: [
            {"title": "Thông tin HUIT", "text": "HUIT công bố điểm chuẩn...", "score": 0.9}
        ],
    )
    monkeypatch.setattr(
        pipeline,
        "stream_llm",
        lambda sys, user: iter(["Điểm chuẩn ", "HUIT 2026 ", "từ 16 đến 23 điểm."]),
    )

    events = list(pipeline.stream_answer("Điểm chuẩn HUIT?", use_cache=False, request_id="stream-test-01"))

    assert len(events) >= 4
    prev_seq = 0
    for line in events:
        item = json.loads(line)
        assert "type" in item
        assert "sequence" in item
        assert "stream_id" in item
        assert "request_id" in item
        assert item["sequence"] == prev_seq + 1
        prev_seq = item["sequence"]


# ---------------------------------------------------------------------------
# TEST 16: Gemini/Groq/OpenRouter vẫn hoạt động khi Jev bị tắt hoặc lỗi
# ---------------------------------------------------------------------------
def test_16_generation_llm_works_when_jev_disabled_or_failed(monkeypatch):
    # Kịch bản: JEV gặp sự cố kết nối, LLM chính vẫn sinh câu trả lời bình thường
    monkeypatch.setenv("JEV_MODE", "assist")
    monkeypatch.setenv("TYPESAFE_API_KEY", "faulty-key")

    from backend.app.rag import pipeline

    class FailingProvider(TypeSafeJevProvider):
        async def decide(self, request, total_budget_ms=None):
            raise DecisionServerError("Jev cluster unavailable", status_code=503)

    failing_service = DecisionService(provider=FailingProvider(api_key="faulty-key"))
    monkeypatch.setattr(pipeline, "decision_service", failing_service)

    llm_chunks_yielded = []

    def mock_stream_llm(sys_prompt, user_prompt):
        for chunk in ["Trường Đại học Công Thương TP.HCM ", "đang nhận hồ sơ xét tuyển."]:
            llm_chunks_yielded.append(chunk)
            yield chunk

    monkeypatch.setattr(
        pipeline,
        "retrieve",
        lambda query, top_k, timings=None: [
            {"title": "Xét tuyển HUIT", "text": "Trường tuyển sinh 2026...", "score": 0.8}
        ],
    )
    monkeypatch.setattr(pipeline, "stream_llm", mock_stream_llm)
    monkeypatch.setattr(pipeline, "resolve_artifact_for_chat", lambda *args, **kwargs: None)

    events = list(pipeline.stream_answer("Em muốn hỏi về xét tuyển", use_cache=False))
    parsed = [json.loads(line) for line in events if line.strip()]

    # Xác nhận token của LLM được chuyển trọn vẹn tới client mà không bị đứt đoạn
    token_payloads = [e["payload"]["token"] for e in parsed if e["type"] == "token"]
    full_answer = "".join(token_payloads)

    assert "Trường Đại học Công Thương TP.HCM" in full_answer
    assert len(llm_chunks_yielded) == 2


# ---------------------------------------------------------------------------
# TEST 17: Health endpoint phản ánh đúng trạng thái Jev không lộ secret
# ---------------------------------------------------------------------------
def test_17_health_endpoint_decision_engine_status(monkeypatch):
    from fastapi.testclient import TestClient
    from backend.app.main import app

    client = TestClient(app)

    # 1. Khi JEV_MODE=off
    monkeypatch.setenv("JEV_MODE", "off")
    resp_off = client.get("/health/ready")
    assert resp_off.status_code in (200, 503)
    data_off = resp_off.json()
    assert "decision_engine" in data_off["components"]
    assert data_off["components"]["decision_engine"]["status"] == "disabled"
    assert "api_key" not in json.dumps(data_off)

    # 2. Khi JEV_MODE=assist với API key
    secret_key = "super_secret_test_key_for_health"
    monkeypatch.setenv("JEV_MODE", "assist")
    monkeypatch.setenv("TYPESAFE_API_KEY", secret_key)
    resp_assist = client.get("/health/ready")
    data_assist = resp_assist.json()
    assert data_assist["components"]["decision_engine"]["status"] in ("configured", "healthy")
    # Tuyệt đối không để lộ secret trong health response
    assert secret_key not in json.dumps(data_assist)

    # 3. Khi circuit breaker bị mở
    from backend.app.decision_engine.service import decision_service
    decision_service.circuit_breaker.state = "open"
    decision_service.circuit_breaker.consecutive_failures = 3
    resp_cb = client.get("/health/ready")
    data_cb = resp_cb.json()
    assert data_cb["components"]["decision_engine"]["status"] == "circuit_open"
    assert data_cb["components"]["decision_engine"]["circuit_state"] == "open"
    # Khôi phục trạng thái
    decision_service.circuit_breaker.state = "closed"
    decision_service.circuit_breaker.consecutive_failures = 0


# ---------------------------------------------------------------------------
# TEST 18: Missing answer bị từ chối với DecisionValidationError
# ---------------------------------------------------------------------------
def test_18_missing_answer_rejected():
    def mock_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "answers": {
                    "q1": {"type": "choice", "choice": "cutoff", "confidence": 0.95}
                },
                "model": "jev-latest",
            },
        )

    mock_client = httpx.AsyncClient(transport=httpx.MockTransport(mock_handler))
    provider = TypeSafeJevProvider(api_key="test-key", client=mock_client)

    req = DecisionRequest(
        decision_type="custom",
        state="Test state",
        model="jev-latest",
        questions={
            "q1": QuestionDefinition(type="choice"),
            "q2": QuestionDefinition(type="noul"),
        },
    )
    with pytest.raises(DecisionValidationError) as exc_info:
        asyncio.run(provider.decide(req))
    assert "thiếu câu trả lời" in str(exc_info.value).lower() or "missing" in str(exc_info.value).lower()


# ---------------------------------------------------------------------------
# TEST 19: Unknown answer key bị từ chối với DecisionValidationError
# ---------------------------------------------------------------------------
def test_19_unknown_answer_key_rejected():
    def mock_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "answers": {
                    "q1": {"type": "choice", "choice": "cutoff", "confidence": 0.95},
                    "q_unexpected": {"type": "choice", "choice": "tuition", "confidence": 0.8},
                },
                "model": "jev-latest",
            },
        )

    mock_client = httpx.AsyncClient(transport=httpx.MockTransport(mock_handler))
    provider = TypeSafeJevProvider(api_key="test-key", client=mock_client)

    req = DecisionRequest(
        decision_type="custom",
        state="Test state",
        model="jev-latest",
        questions={
            "q1": QuestionDefinition(type="choice"),
        },
    )
    with pytest.raises(DecisionValidationError) as exc_info:
        asyncio.run(provider.decide(req))
    assert "lạ" in str(exc_info.value).lower() or "unexpected" in str(exc_info.value).lower()


# ---------------------------------------------------------------------------
# TEST 20: Choice ngoài criteria bị từ chối với DecisionValidationError
# ---------------------------------------------------------------------------
def test_20_choice_outside_criteria_rejected():
    def mock_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "answers": {
                    "intent": {"type": "choice", "choice": "alien_intent_not_in_criteria", "confidence": 0.95},
                },
                "model": "jev-latest",
            },
        )

    mock_client = httpx.AsyncClient(transport=httpx.MockTransport(mock_handler))
    provider = TypeSafeJevProvider(api_key="test-key", client=mock_client)

    req = DecisionRequest(
        decision_type="custom",
        state="Test state",
        model="jev-latest",
        questions={
            "intent": QuestionDefinition(
                type="choice",
                criteria={"cutoff": "Điểm chuẩn", "tuition": "Học phí"},
            ),
        },
    )
    with pytest.raises(DecisionValidationError) as exc_info:
        asyncio.run(provider.decide(req))
    assert "criteria" in str(exc_info.value).lower()


# ---------------------------------------------------------------------------
# TEST 21: Sai type giữa choice/score/noul bị từ chối
# ---------------------------------------------------------------------------
def test_21_type_mismatch_choice_score_noul():
    # 1. Câu hỏi type=choice nhưng không có trường choice (hoặc choice không phải string)
    def mock_bad_choice(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"answers": {"q1": {"type": "choice", "score": 4.5, "confidence": 0.9}}})

    c1 = httpx.AsyncClient(transport=httpx.MockTransport(mock_bad_choice))
    p1 = TypeSafeJevProvider(api_key="k", client=c1)
    req1 = DecisionRequest(
        decision_type="custom", state="s", questions={"q1": QuestionDefinition(type="choice")}
    )
    with pytest.raises(DecisionValidationError):
        asyncio.run(p1.decide(req1))

    # 2. Câu hỏi type=score nhưng score là chuỗi
    def mock_bad_score(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"answers": {"q1": {"type": "score", "score": "high_score", "confidence": 0.9}}})

    c2 = httpx.AsyncClient(transport=httpx.MockTransport(mock_bad_score))
    p2 = TypeSafeJevProvider(api_key="k", client=c2)
    req2 = DecisionRequest(
        decision_type="custom", state="s", questions={"q1": QuestionDefinition(type="score", criteria=["Low", "High"])}
    )
    with pytest.raises(DecisionValidationError):
        asyncio.run(p2.decide(req2))

    # 3. Câu hỏi type=noul nhưng noul ngoài phạm vi [0.0, 1.0] (ví dụ: 1.5)
    def mock_bad_noul(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"answers": {"q1": {"type": "noul", "noul": 1.5, "confidence": 0.9}}})

    c3 = httpx.AsyncClient(transport=httpx.MockTransport(mock_bad_noul))
    p3 = TypeSafeJevProvider(api_key="k", client=c3)
    req3 = DecisionRequest(
        decision_type="custom", state="s", questions={"q1": QuestionDefinition(type="noul")}
    )
    with pytest.raises(DecisionValidationError):
        asyncio.run(p3.decide(req3))


# ---------------------------------------------------------------------------
# TEST 22: NaN và Infinity bị từ chối
# ---------------------------------------------------------------------------
def test_22_nan_and_infinity_rejected():
    # Confidence là NaN
    def mock_nan_conf(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text='{"answers": {"q1": {"type": "choice", "choice": "cutoff", "confidence": NaN}}}')

    c1 = httpx.AsyncClient(transport=httpx.MockTransport(mock_nan_conf))
    p1 = TypeSafeJevProvider(api_key="k", client=c1)
    req1 = DecisionRequest(decision_type="custom", state="s", questions={"q1": QuestionDefinition(type="choice")})
    with pytest.raises(DecisionValidationError):
        asyncio.run(p1.decide(req1))

    # Score là Infinity
    def mock_inf_score(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text='{"answers": {"q1": {"type": "score", "score": Infinity, "confidence": 0.9}}}')

    c2 = httpx.AsyncClient(transport=httpx.MockTransport(mock_inf_score))
    p2 = TypeSafeJevProvider(api_key="k", client=c2)
    req2 = DecisionRequest(decision_type="custom", state="s", questions={"q1": QuestionDefinition(type="score", criteria=["Low", "High"])})
    with pytest.raises(DecisionValidationError):
        asyncio.run(p2.decide(req2))


# ---------------------------------------------------------------------------
# TEST 23: Probabilities không hợp lệ bị từ chối
# ---------------------------------------------------------------------------
def test_23_invalid_probabilities_rejected():
    # 1. Tổng xác suất không xấp xỉ 1.0 (ví dụ 0.3)
    def mock_bad_sum(req: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "answers": {
                    "q1": {
                        "type": "choice",
                        "choice": "cutoff",
                        "confidence": 0.9,
                        "probabilities": {"cutoff": 0.2, "tuition": 0.1},
                    }
                }
            },
        )

    c1 = httpx.AsyncClient(transport=httpx.MockTransport(mock_bad_sum))
    p1 = TypeSafeJevProvider(api_key="k", client=c1)
    req1 = DecisionRequest(
        decision_type="custom",
        state="s",
        questions={"q1": QuestionDefinition(type="choice", criteria={"cutoff": "A", "tuition": "B"})},
    )
    with pytest.raises(DecisionValidationError) as exc:
        asyncio.run(p1.decide(req1))
    assert "xác suất" in str(exc.value).lower()

    # 2. Key trong probabilities không thuộc criteria
    def mock_bad_key(req: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "answers": {
                    "q1": {
                        "type": "choice",
                        "choice": "cutoff",
                        "confidence": 0.9,
                        "probabilities": {"cutoff": 0.9, "unknown_key": 0.1},
                    }
                }
            },
        )

    c2 = httpx.AsyncClient(transport=httpx.MockTransport(mock_bad_key))
    p2 = TypeSafeJevProvider(api_key="k", client=c2)
    with pytest.raises(DecisionValidationError):
        asyncio.run(p2.decide(req1))


# ---------------------------------------------------------------------------
# TEST 24: Tổng timeout budget và fallback ngay khi budget không đủ
# ---------------------------------------------------------------------------
def test_24_total_timeout_budget_enforcement(monkeypatch):
    monkeypatch.setenv("JEV_MODE", "assist")

    # Giả lập transport bỏ qua httpx timeout và giữ call 0.30s trong khi budget chỉ 0.08s.
    # Provider vẫn phải cưỡng chế deadline ở lớp ngoài transport.
    async def mock_slow_handler(request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(0.30)
        return httpx.Response(200, json={})

    mock_client = httpx.AsyncClient(transport=httpx.MockTransport(mock_slow_handler))
    provider = TypeSafeJevProvider(api_key="test-key", client=mock_client)
    service = DecisionService(provider=provider)

    req = DecisionRequest(
        decision_type="intent",
        state="Test budget",
        model="jev-latest",
        questions={"q1": QuestionDefinition(type="choice")},
    )
    # Budget 80ms
    start = time.perf_counter()
    result = asyncio.run(service.execute_decision(req, total_budget_ms=80.0))
    elapsed = time.perf_counter() - start

    assert result.status == "fallback"
    assert elapsed < 0.20  # Không được chờ transport đủ 300ms hay retry vượt budget


# ---------------------------------------------------------------------------
# TEST 25: Retry-After cho HTTP 429 bị giới hạn và có jitter
# ---------------------------------------------------------------------------
def test_25_retry_after_capped():
    call_count = 0

    def mock_handler_429(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            # Server trả về Retry-After: 999 giây vô lý
            return httpx.Response(429, headers={"Retry-After": "999"})
        return httpx.Response(
            200,
            json={
                "answers": {
                    "q1": {"type": "choice", "choice": "cutoff", "confidence": 0.95}
                },
                "model": "jev-latest",
            },
        )

    mock_client = httpx.AsyncClient(transport=httpx.MockTransport(mock_handler_429))
    provider = TypeSafeJevProvider(api_key="test-key", client=mock_client)

    req = DecisionRequest(
        decision_type="custom",
        state="Test 429 Retry-After",
        model="jev-latest",
        questions={"q1": QuestionDefinition(type="choice")},
    )

    start = time.perf_counter()
    # Provider tự động cap Retry-After xuống tối đa 0.5s (+jitter)
    res = asyncio.run(provider.decide(req, total_budget_ms=2000.0))
    elapsed = time.perf_counter() - start

    assert res.status == "success"
    assert call_count == 2
    # Tổng thời gian chờ chỉ xấp xỉ 0.5s - 0.7s, tuyệt đối không bị kẹt 999s!
    assert elapsed < 1.2


# ---------------------------------------------------------------------------
# TEST 26: Half-open chỉ cho đúng 1 probe khi có nhiều request đồng thời
# ---------------------------------------------------------------------------
def test_26_half_open_allows_single_probe_concurrently():
    cb = CircuitBreaker(failure_threshold=2, cooldown_seconds=0.10)
    cb.record_failure()
    cb.record_failure()
    assert cb.state == "open"
    assert cb.allow_request() is False

    # Chờ hết cooldown (0.18s an toàn cho độ phân giải clock Windows)
    time.sleep(0.18)

    # 10 thread đồng thời kiểm tra allow_request
    import concurrent.futures

    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        futures = [executor.submit(cb.allow_request) for _ in range(10)]
        for f in concurrent.futures.as_completed(futures):
            results.append(f.result())

    # Đúng 1 probe duy nhất được phép đi qua, 9 request còn lại bị từ chối
    assert results.count(True) == 1
    assert results.count(False) == 9
    assert cb.state == "half_open"

    # Khi probe thành công -> chuyển về closed
    cb.record_success()
    assert cb.state == "closed"
    assert cb.allow_request() is True


# ---------------------------------------------------------------------------
# TEST 27: Cross-event-loop và Thread safety không bị lỗi semaphore
# ---------------------------------------------------------------------------
def test_27_cross_event_loop_safety(monkeypatch):
    monkeypatch.setenv("JEV_MODE", "assist")
    monkeypatch.setenv("TYPESAFE_API_KEY", "test-key")

    def mock_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "answers": {
                    "q1": {"type": "choice", "choice": "cutoff", "confidence": 0.9}
                },
                "model": "jev-latest",
            },
        )

    mock_client = httpx.AsyncClient(transport=httpx.MockTransport(mock_handler))
    provider = TypeSafeJevProvider(api_key="test-key", client=mock_client)
    service = DecisionService(provider=provider, max_concurrency=5)

    req = DecisionRequest(
        decision_type="custom",
        state="Test cross loop",
        model="jev-latest",
        questions={"q1": QuestionDefinition(type="choice")},
    )

    import concurrent.futures

    def worker_in_new_thread():
        # Mỗi thread tạo một event loop riêng biệt hoàn toàn
        new_loop = asyncio.new_event_loop()
        try:
            return new_loop.run_until_complete(service.execute_decision(req))
        finally:
            new_loop.close()

    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(worker_in_new_thread) for _ in range(8)]
        for f in concurrent.futures.as_completed(futures):
            res = f.result()
            assert res is not None
            assert res.status == "success"
            results.append(res)

    assert len(results) == 8


# ---------------------------------------------------------------------------
# TEST 28: Hai lần gọi JEV chia sẻ budget, budget không đủ sẽ skip lượt 2
# ---------------------------------------------------------------------------
def test_28_insufficient_budget_skips_second_jev_call(monkeypatch):
    monkeypatch.setenv("JEV_MODE", "assist")
    monkeypatch.setenv("TYPESAFE_API_KEY", "test-key")
    # Đặt tổng budget nhỏ: 250ms
    monkeypatch.setenv("JEV_TOTAL_BUDGET_MS", "250.0")

    call_count = 0

    def mock_handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        # Mô phỏng lượt 1 tiêu tốn 100ms
        time.sleep(0.1)
        return httpx.Response(
            200,
            json={
                "answers": {
                    "intent": {"type": "choice", "choice": "tuition", "confidence": 0.95},
                    "needs_clarification": {"type": "noul", "noul": 0.05, "confidence": 0.95},
                },
                "model": "jev-latest",
            },
        )

    mock_client = httpx.AsyncClient(transport=httpx.MockTransport(mock_handler))
    provider = TypeSafeJevProvider(api_key="test-key", client=mock_client)
    custom_service = DecisionService(provider=provider)

    from backend.app.rag import pipeline
    monkeypatch.setattr(pipeline, "decision_service", custom_service)
    monkeypatch.setattr(
        pipeline,
        "retrieve",
        lambda q, top_k, timings=None: [
            {"title": "Học phí", "text": "Học phí HUIT...", "score": 0.9}
        ],
    )
    monkeypatch.setattr(
        pipeline,
        "stream_llm",
        lambda sys, user: iter(["Học phí ", "tính theo tín chỉ."]),
    )

    # Chạy pipeline với câu hỏi mơ hồ để kích hoạt cả intent và retrieval docs
    events = list(pipeline.stream_answer("Em muốn hỏi thông tin chung", use_cache=False))
    parsed = [json.loads(line) for line in events if line.strip()]

    assert any(e["type"] == "done" for e in parsed)
    # Lượt 1 (intent) chạy và tiêu tốn ~100ms.
    # Budget còn lại < 200ms -> lượt 2 (evidence sufficiency) bị skip ngay lập tức!
    # Do đó Jev chỉ bị gọi đúng 1 lần thay vì 2 lần!
    assert call_count == 1


# ---------------------------------------------------------------------------
# TEST 29: Boolean và trường xung đột (conflicting fields) bị từ chối
# ---------------------------------------------------------------------------
def test_29_boolean_and_conflicting_fields_rejected():
    # 1. Boolean trong confidence bị từ chối
    with pytest.raises(ValueError):
        DecisionItem(type="choice", choice="tuition", confidence=True)

    # 2. Boolean trong score bị từ chối
    with pytest.raises(ValueError):
        DecisionItem(type="score", score=False, confidence=0.9)

    # 3. Boolean trong noul bị từ chối
    with pytest.raises(ValueError):
        DecisionItem(type="noul", noul=True, confidence=0.9)

    # 4. Boolean trong probabilities bị từ chối
    with pytest.raises(ValueError):
        DecisionItem(
            type="choice",
            choice="tuition",
            confidence=0.9,
            probabilities={"tuition": True},
        )

    # 5. Type='choice' nhưng có chứa score bị từ chối
    def mock_conflicting_choice(req: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "answers": {
                    "q1": {"type": "choice", "choice": "cutoff", "score": 10.0, "confidence": 0.9}
                },
                "model": "jev-latest",
            },
        )

    c = httpx.AsyncClient(transport=httpx.MockTransport(mock_conflicting_choice))
    p = TypeSafeJevProvider(api_key="k", client=c)
    req = DecisionRequest(
        decision_type="custom",
        state="s",
        questions={"q1": QuestionDefinition(type="choice")},
    )
    with pytest.raises(DecisionValidationError):
        asyncio.run(p.decide(req))


# ---------------------------------------------------------------------------
# TEST 30: Retry thất bại vẫn bảo toàn retry_count cho telemetry
# ---------------------------------------------------------------------------
def test_30_failed_retry_preserves_retry_count():
    attempts = 0

    def always_unavailable(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(503, json={"error": "unavailable"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(always_unavailable))
    provider = TypeSafeJevProvider(api_key="test-key", client=client)
    req = DecisionRequest(
        decision_type="custom",
        state="retry metadata",
        questions={"q1": QuestionDefinition(type="choice")},
    )

    with pytest.raises(DecisionServerError) as exc_info:
        asyncio.run(provider.decide(req, total_budget_ms=1000.0))

    assert attempts == 2
    assert getattr(exc_info.value, "retry_count", None) == 1


# ---------------------------------------------------------------------------
# TEST 31: Usage sai kiểu hoặc vượt giới hạn bị từ chối
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "usage",
    [
        {"input_tokens": True, "output_tokens": 0},
        {"input_tokens": 1.5, "output_tokens": 0},
        {"input_tokens": -1, "output_tokens": 0},
        {"input_tokens": 10_000_001, "output_tokens": 0},
    ],
)
def test_31_invalid_usage_rejected(usage):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "answers": {"q1": {"type": "choice", "choice": "cutoff", "confidence": 0.9}},
                "usage": usage,
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = TypeSafeJevProvider(api_key="test-key", client=client)
    req = DecisionRequest(
        decision_type="custom",
        state="usage validation",
        questions={"q1": QuestionDefinition(type="choice")},
    )

    with pytest.raises(DecisionValidationError):
        asyncio.run(provider.decide(req))


# ---------------------------------------------------------------------------
# TEST 32: Hủy half-open probe phải nhả reservation
# ---------------------------------------------------------------------------
def test_32_cancelled_half_open_probe_is_released(monkeypatch):
    monkeypatch.setenv("JEV_MODE", "assist")
    import threading

    provider_started = threading.Event()

    class SlowProvider(TypeSafeJevProvider):
        async def decide(self, request, total_budget_ms=None):
            provider_started.set()
            await asyncio.sleep(10)
            raise AssertionError("cancelled probe must not finish")

    breaker = CircuitBreaker(failure_threshold=1, cooldown_seconds=0.0)
    breaker.record_failure()
    breaker.last_state_change -= 1.0
    assert breaker.state == "open"
    service = DecisionService(
        provider=SlowProvider(api_key="test-key"),
        circuit_breaker=breaker,
    )
    req = DecisionRequest(
        decision_type="custom",
        state="cancel half-open probe",
        questions={"q1": QuestionDefinition(type="choice")},
    )

    async def run_and_cancel():
        task = asyncio.create_task(service.execute_decision(req, total_budget_ms=1000.0))
        for _ in range(50):
            if provider_started.is_set():
                break
            await asyncio.sleep(0.005)
        assert provider_started.is_set()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(run_and_cancel())

    assert breaker.state == "half_open"
    assert breaker.allow_request() is True


# ---------------------------------------------------------------------------
# TEST 33: Noul hợp lệ không có confidence (Official Response) được chấp nhận
# ---------------------------------------------------------------------------
def test_33_valid_noul_without_confidence_accepted():
    """Hợp đồng chính thức TypeSafe System One cho noul không có trường confidence."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "answers": {
                    "needs_clarification": {
                        "type": "noul",
                        "noul": 0.25,
                    }
                },
                "model": "jev-latest",
                "usage": {"input_tokens": 40, "output_tokens": 10},
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = TypeSafeJevProvider(api_key="test-key", client=client)
    req = DecisionRequest(
        decision_type="custom",
        state="kiem tra noul khong confidence",
        questions={"needs_clarification": QuestionDefinition(type="noul")},
    )

    res = asyncio.run(provider.decide(req))
    assert res.status == "success"
    item = res.decisions["needs_clarification"]
    assert item.type == "noul"
    assert item.noul == 0.25
    assert item.confidence is None
    assert item.choice is None
    assert item.score is None

    # Xác thực với canonical JSON schema Draft 2020-12
    validate_contract("huit.decision.decision-result", "1.0.0", res.model_dump())


# ---------------------------------------------------------------------------
# TEST 34: Noul có confidence hợp lệ vẫn được chấp nhận
# ---------------------------------------------------------------------------
def test_34_valid_noul_with_confidence_accepted():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "answers": {
                    "clarity": {
                        "type": "noul",
                        "noul": 0.85,
                        "confidence": 0.92,
                    }
                },
                "model": "jev-latest",
                "usage": {"input_tokens": 50, "output_tokens": 10},
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = TypeSafeJevProvider(api_key="test-key", client=client)
    req = DecisionRequest(
        decision_type="custom",
        state="kiem tra noul co confidence",
        questions={"clarity": QuestionDefinition(type="noul")},
    )

    res = asyncio.run(provider.decide(req))
    assert res.status == "success"
    item = res.decisions["clarity"]
    assert item.type == "noul"
    assert item.noul == 0.85
    assert item.confidence == 0.92
    validate_contract("huit.decision.decision-result", "1.0.0", res.model_dump())


# ---------------------------------------------------------------------------
# TEST 35: Noul không hợp lệ bị từ chối
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "invalid_ans",
    [
        {"type": "noul", "noul": True},                     # Boolean
        {"type": "noul", "noul": "0.5"},                    # String
        {"type": "noul", "noul": float("nan")},             # NaN
        {"type": "noul", "noul": float("inf")},             # Infinity
        {"type": "noul", "noul": -0.01},                    # Dưới 0
        {"type": "noul", "noul": 1.01},                     # Trên 1
        {"type": "noul"},                                   # Thiếu trường noul
        {"type": "noul", "noul": None},                     # None
        {"type": "noul", "noul": 0.5, "choice": "abc"},     # Chứa trường lạ choice
        {"type": "noul", "noul": 0.5, "score": 2.0},       # Chứa trường lạ score
        {"type": "noul", "noul": 0.5, "confidence": True},  # Confidence boolean
        {"type": "noul", "noul": 0.5, "confidence": "0.9"}, # Confidence string
        {"type": "noul", "noul": 0.5, "confidence": -0.1},  # Confidence ngoài [0,1]
        {"type": "noul", "noul": 0.5, "confidence": 1.5},   # Confidence ngoài [0,1]
    ],
)
def test_35_invalid_noul_rejected(invalid_ans):
    provider = TypeSafeJevProvider(api_key="test-key")
    req = DecisionRequest(
        decision_type="custom",
        state="invalid noul test",
        questions={"q_noul": QuestionDefinition(type="noul")},
    )

    with pytest.raises(DecisionValidationError):
        provider._parse_response(
            {
                "answers": {"q_noul": invalid_ans},
                "model": "jev-latest",
                "usage": {"input_tokens": 10, "output_tokens": 5},
            },
            req,
            latency_ms=10.0,
        )


# ---------------------------------------------------------------------------
# TEST 36: Choice và Score thiếu trường bắt buộc vẫn bị từ chối
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "q_type, ans_payload",
    [
        ("choice", {"type": "choice", "choice": "tuition"}),                       # Choice thiếu confidence
        ("choice", {"type": "choice", "confidence": 0.9}),                         # Choice thiếu choice
        ("choice", {"type": "choice", "choice": "", "confidence": 0.9}),           # Choice rỗng
        ("choice", {"type": "choice", "choice": "tuition", "confidence": "0.9"}),   # Confidence không phải số
        ("choice", {"type": "choice", "choice": "tuition", "confidence": -0.1}),   # Confidence < 0
        ("choice", {"type": "choice", "choice": "tuition", "confidence": 1.2}),    # Confidence > 1
        ("choice", {"type": "choice", "choice": "tuition", "confidence": 0.9, "score": 2.0}), # Choice chứa score
        ("score", {"type": "score", "score": 3.0}),                                # Score thiếu confidence
        ("score", {"type": "score", "confidence": 0.9}),                           # Score thiếu score
        ("score", {"type": "score", "score": "high", "confidence": 0.9}),          # Score không phải số
        ("score", {"type": "score", "score": float("nan"), "confidence": 0.9}),    # Score là NaN
        ("score", {"type": "score", "score": 3.0, "confidence": 0.9, "noul": 0.5}), # Score chứa noul
    ],
)
def test_36_choice_and_score_missing_required_rejected(q_type, ans_payload):
    provider = TypeSafeJevProvider(api_key="test-key")
    req = DecisionRequest(
        decision_type="custom",
        state="choice score validation",
        questions={"q1": QuestionDefinition(
            type=q_type,
            criteria=["Low", "Medium", "High", "Very high"] if q_type == "score" else None,
        )},
    )

    with pytest.raises(DecisionValidationError):
        provider._parse_response(
            {
                "answers": {"q1": ans_payload},
                "model": "jev-latest",
                "usage": {"input_tokens": 20, "output_tokens": 5},
            },
            req,
            latency_ms=10.0,
        )


# ---------------------------------------------------------------------------
# TEST 37: Workflow Intent & Evidence xử lý chuẩn phản hồi chính thức (Choice + Noul)
# ---------------------------------------------------------------------------
def test_37_official_intent_and_evidence_workflows_succeed(monkeypatch):
    """Xác nhận cả hai workflow chính thức (Intent và Evidence) đều phân tích thành công."""
    monkeypatch.setenv("JEV_MODE", "shadow")
    monkeypatch.setenv("TYPESAFE_API_KEY", "test-official-key")

    # 1. Official Intent response
    def intent_handler(request: httpx.Request) -> httpx.Response:
        data = json.loads(request.content)
        assert "questions" in data
        assert "intent" in data["questions"]
        assert "needs_clarification" in data["questions"]
        return httpx.Response(
            200,
            json={
                "answers": {
                    "intent": {
                        "type": "choice",
                        "choice": "tuition",
                        "confidence": 0.96,
                        "probabilities": {"tuition": 0.96, "general": 0.04},
                    },
                    "needs_clarification": {
                        "type": "noul",
                        "noul": 0.08,
                    },
                },
                "model": "typesafe-systemone-2026-03",
                "usage": {"input_tokens": 85, "output_tokens": 20},
            },
        )

    intent_client = httpx.AsyncClient(transport=httpx.MockTransport(intent_handler))
    intent_provider = TypeSafeJevProvider(api_key="test-official-key", client=intent_client)
    intent_service = DecisionService(provider=intent_provider, mode="shadow")

    res_intent = asyncio.run(
        intent_service.decide_intent("Học phí ngành CNTT?", current_intent="general")
    )
    assert res_intent.status == "success"
    assert res_intent.decisions["intent"].choice == "tuition"
    assert res_intent.decisions["intent"].confidence == 0.96
    assert res_intent.decisions["needs_clarification"].noul == 0.08
    assert res_intent.decisions["needs_clarification"].confidence is None
    validate_contract("huit.decision.decision-result", "1.0.0", res_intent.model_dump())

    # 2. Official Evidence Sufficiency response
    def evidence_handler(request: httpx.Request) -> httpx.Response:
        data = json.loads(request.content)
        assert "sufficiency" in data["questions"]
        assert "needs_clarification" in data["questions"]
        return httpx.Response(
            200,
            json={
                "answers": {
                    "sufficiency": {
                        "type": "choice",
                        "choice": "sufficient",
                        "confidence": 0.93,
                        "probabilities": {"sufficient": 0.93, "partial": 0.07},
                    },
                    "needs_clarification": {
                        "type": "noul",
                        "noul": 0.12,
                    },
                },
                "model": "typesafe-systemone-2026-03",
                "usage": {"input_tokens": 120, "output_tokens": 22},
            },
        )

    ev_client = httpx.AsyncClient(transport=httpx.MockTransport(evidence_handler))
    ev_provider = TypeSafeJevProvider(api_key="test-official-key", client=ev_client)
    ev_service = DecisionService(provider=ev_provider, mode="shadow")

    sample_docs = [{"title": "Học phí HUIT", "text": "Học phí CNTT là 850k/tín chỉ.", "score": 0.95}]
    res_ev = asyncio.run(
        ev_service.decide_evidence_sufficiency("Học phí ngành CNTT?", sample_docs)
    )
    assert res_ev.status == "success"
    assert res_ev.decisions["sufficiency"].choice == "sufficient"
    assert res_ev.decisions["sufficiency"].confidence == 0.93
    assert res_ev.decisions["needs_clarification"].noul == 0.12
    assert res_ev.decisions["needs_clarification"].confidence is None
    validate_contract("huit.decision.decision-result", "1.0.0", res_ev.model_dump())


# ---------------------------------------------------------------------------
# TEST 38: JEV lỗi vẫn fallback và Shadow mode giữ nguyên nội dung & streaming
# ---------------------------------------------------------------------------
def test_38_jev_error_fallback_shadow_preserves_content_and_streaming(monkeypatch):
    """Khi JEV gặp lỗi server hoặc timeout trong Shadow Mode:
    - Trả fallback result an toàn, không gián đoạn.
    - Chatbot pipeline tạo đúng đầy đủ sequence token stream NDJSON v2.
    - Nội dung trả lời của chatbot hoàn toàn trùng khớp với khi JEV tắt (off).
    """
    from backend.app.rag import pipeline

    # Mock retrieval & LLM
    docs = [{"title": "HUIT", "text": "Đại học Công Thương TP.HCM", "score": 0.9}]
    monkeypatch.setattr(pipeline, "retrieve", lambda q, top_k, timings=None: docs)
    monkeypatch.setattr(pipeline, "stream_llm", lambda s, u: iter(["HUIT ", "tuyển sinh ", "2026."]))

    # Baseline: Off mode
    monkeypatch.setenv("JEV_MODE", "off")
    off_events = list(pipeline.stream_answer("HUIT ở đâu?", use_cache=False))
    off_tokens = [json.loads(line) for line in off_events if line.strip()]
    off_text = "".join(e["payload"]["token"] for e in off_tokens if e["type"] == "token")

    # Shadow mode with failing provider
    class FailingJevProvider(TypeSafeJevProvider):
        async def decide(self, request, **kwargs):
            raise DecisionServerError("Internal Jev 500 error", status_code=500)

    monkeypatch.setenv("JEV_MODE", "shadow")
    monkeypatch.setenv("TYPESAFE_API_KEY", "test-key")
    failing_service = DecisionService(provider=FailingJevProvider(api_key="test-key"), mode="shadow")
    monkeypatch.setattr(pipeline, "decision_service", failing_service)

    shadow_events = list(pipeline.stream_answer("HUIT ở đâu?", use_cache=False))
    shadow_tokens = [json.loads(line) for line in shadow_events if line.strip()]
    shadow_text = "".join(e["payload"]["token"] for e in shadow_tokens if e["type"] == "token")

    # 1. Output giống hệt baseline off
    assert shadow_text == off_text
    assert len(shadow_text) > 0

    # 2. Sequence NDJSON hoàn toàn nguyên vẹn
    for i, item in enumerate(shadow_tokens):
        assert item["sequence"] == i + 1

    event_types = [e["type"] for e in shadow_tokens]
    assert event_types[0] == "start"
    assert "token" in event_types
    assert event_types[-1] == "done"


# ---------------------------------------------------------------------------
# TEST 39: Shadow fallback toàn diện trên timeout, lỗi xác thực, rate limit và response sai
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "injected_error, expected_reason",
    [
        (DecisionTimeoutError("Deadline exceeded"), "timeout"),
        (DecisionAuthenticationError("401 Unauthorized"), "auth_error"),
        (DecisionRateLimitError("429 Too Many Requests"), "rate_limit"),
        (DecisionValidationError("Invalid JSON schema"), "validation_error"),
    ],
)
def test_39_shadow_fallback_on_all_error_types(monkeypatch, injected_error, expected_reason):
    """Xác minh mọi loại lỗi (timeout, auth, rate limit, validation) trong shadow mode:
    - Service trả fallback an toàn với đúng fallback_reason.
    - Chatbot pipeline duy trì nguyên vẹn stream NDJSON và câu trả lời.
    """
    from backend.app.rag import pipeline

    class InjectedErrorProvider(TypeSafeJevProvider):
        async def decide(self, request, **kwargs):
            raise injected_error

    provider = InjectedErrorProvider(api_key="test-key")
    service = DecisionService(provider=provider, mode="shadow")

    req = DecisionRequest(
        decision_type="intent",
        state="Kiem tra loi fallback",
        questions=get_intent_decision_questions(),
    )
    result = asyncio.run(service.execute_decision(req))
    assert result.status == "fallback"
    assert expected_reason in result.error_message

    # Chatbot streaming non-interference
    monkeypatch.setenv("JEV_MODE", "shadow")
    monkeypatch.setenv("TYPESAFE_API_KEY", "test-key")
    monkeypatch.setattr(pipeline, "decision_service", service)

    docs = [{"title": "HUIT", "text": "Đại học Công Thương TP.HCM", "score": 0.9}]
    monkeypatch.setattr(pipeline, "retrieve", lambda q, top_k, timings=None: docs)
    monkeypatch.setattr(pipeline, "stream_llm", lambda s, u: iter(["Thông tin ", "tuyển sinh."]))

    events = list(pipeline.stream_answer("Xét tuyển thế nào?", use_cache=False))
    parsed = [json.loads(line) for line in events if line.strip()]
    text = "".join(e["payload"]["token"] for e in parsed if e["type"] == "token")

    assert len(text) > 0
    assert all(parsed[i]["sequence"] == i + 1 for i in range(len(parsed)))
    types = [e["type"] for e in parsed]
    assert "start" in types and "token" in types and "done" in types


# ---------------------------------------------------------------------------
# TEST 40: REGRESSION 1 - Executor bị chiếm worker, caller timeout trong queue,
# sau khi giải phóng worker thì provider TUYỆT ĐỐI KHÔNG ĐƯỢC GỌI.
# ---------------------------------------------------------------------------
def test_40_regression_executor_saturated_queue_timeout_provider_never_called(monkeypatch):
    """Regression Test 1:
    Executor bị chiếm hết worker: request hết deadline trong hàng đợi;
    sau khi giải phóng worker, provider tuyệt đối không được gọi.
    """
    import concurrent.futures
    import threading
    import warnings

    worker_barrier = threading.Event()
    provider_called = threading.Event()
    call_count = 0

    class GuardedProvider(BaseDecisionProvider):
        def get_name(self) -> str:
            return "guarded_provider"

        async def decide(self, request, total_budget_ms=None):
            nonlocal call_count
            call_count += 1
            provider_called.set()
            return DecisionResult(
                decision_type=request.decision_type,
                status="success",
                provider="guarded_provider",
                model="jev-latest",
                decisions={},
                usage=DecisionUsage(),
                latency_ms=10.0,
            )

        async def check_health(self):
            return {"status": "ok"}

    # Tạo executor với đúng 1 worker duy nhất
    test_executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    try:
        # Chiếm worker bằng tác vụ chờ worker_barrier
        test_executor.submit(worker_barrier.wait)

        provider = GuardedProvider()
        service = DecisionService(provider=provider, executor=test_executor, mode="shadow")
        service.reset_metrics()

        # Bắt warnings để đảm bảo không rò rỉ RuntimeWarning: coroutine was never awaited
        with warnings.catch_warnings(record=True) as captured_warnings:
            warnings.simplefilter("always")

            # Gọi decide_intent_sync với budget ngắn (80ms).
            # Tác vụ buộc phải nằm chờ trong queue của test_executor vì worker 1 đang bận.
            res = service.decide_intent_sync(
                question="Học phí ngành CNTT năm 2026?",
                current_intent="general",
                remaining_budget_ms=80.0,
            )

            # 1. Caller timeout sau 80ms và nhận None / fallback
            assert res is None or res.status == "fallback"

            # 2. Timeout được ghi nhận vào metrics
            metrics = service.get_metrics_summary()
            assert metrics["total_requests"] == 1
            assert metrics["timeout_count"] == 1
            assert metrics["fallback_count"] == 1

            # 3. Provider CHƯA hề được gọi
            assert call_count == 0
            assert not provider_called.is_set()

            # 4. Bây giờ giải phóng worker đang bị chiếm
            worker_barrier.set()

            # Đợi executor xử lý hết task trong queue
            test_executor.shutdown(wait=True)

            # 5. Sau khi worker được cấp lại, tác vụ trong queue PHẢI bị hủy/bỏ qua,
            # PROVIDER TUYỆT ĐỐI KHÔNG ĐƯỢC GỌI!
            assert call_count == 0
            assert not provider_called.is_set()

            # 6. Kiểm tra không có RuntimeWarning về coroutine chưa await
            coro_warnings = [
                w for w in captured_warnings
                if issubclass(w.category, RuntimeWarning) and "coroutine" in str(w.message).lower()
            ]
            assert len(coro_warnings) == 0, f"Rò rỉ coroutine warning: {coro_warnings}"
    finally:
        worker_barrier.set()


# ---------------------------------------------------------------------------
# TEST 41: REGRESSION 2 - Client hủy sát deadline nhưng trước khi hết:
# Cancellation được truyền lên (CancelledError), không tính timeout hay circuit failure.
# ---------------------------------------------------------------------------
def test_41_regression_client_cancel_near_deadline_not_counted_as_timeout():
    """Regression Test 2:
    Client hủy sát deadline (ở 187ms với budget 200ms):
    Cancellation được truyền lên (CancelledError), KHÔNG tính là timeout hay circuit failure.
    """
    import threading

    class SlowCancelProvider(BaseDecisionProvider):
        def __init__(self):
            self.started = threading.Event()

        def get_name(self) -> str:
            return "slow_cancel_provider"

        async def decide(self, request, total_budget_ms=None):
            self.started.set()
            # Giữ tác vụ lâu để client kịp cancel
            await asyncio.sleep(5.0)
            return DecisionResult(
                decision_type=request.decision_type,
                status="success",
                provider="slow_cancel_provider",
                model="jev-latest",
                decisions={},
                usage=DecisionUsage(),
                latency_ms=10.0,
            )

        async def check_health(self):
            return {"status": "ok"}

    breaker = CircuitBreaker(failure_threshold=2)
    provider = SlowCancelProvider()
    service = DecisionService(provider=provider, circuit_breaker=breaker, mode="shadow")
    service.reset_metrics()

    req = DecisionRequest(
        decision_type="intent",
        state="Test cancel near deadline",
        questions=get_intent_decision_questions(),
    )

    async def run_and_cancel_at_187ms():
        start_m = time.monotonic()
        # Ngân sách 200ms
        task = asyncio.create_task(service.execute_decision(req, budget_ms=200.0))

        # Chờ provider bắt đầu
        while not provider.started.is_set():
            await asyncio.sleep(0.002)

        # Chờ đến khoảng 185-188ms (sát ngưỡng 200ms và nằm trong dải -15ms của bug cũ nhưng CHƯA chạm 200ms)
        while time.monotonic() < start_m + 0.185:
            await asyncio.sleep(0.002)

        elapsed = (time.monotonic() - start_m) * 1000.0
        assert elapsed < 200.0, f"Hủy quá muộn: {elapsed}ms >= 200ms"
        assert elapsed >= 185.0, f"Hủy quá sớm: {elapsed}ms < 185ms (vùng lỗi cũ)"

        # Client hủy trước khi deadline 200ms chạm ngưỡng
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(run_and_cancel_at_187ms())

    # Kiểm tra:
    # 1. KHÔNG được tính timeout
    metrics = service.get_metrics_summary()
    assert metrics["timeout_count"] == 0
    assert metrics["fallback_count"] == 0
    assert metrics["error_count"] == 0
    assert metrics["total_requests"] == 0

    # 2. KHÔNG được tính circuit breaker failure
    assert breaker.consecutive_failures == 0
    assert breaker.state == "closed"


# ---------------------------------------------------------------------------
# TEST 42: REGRESSION 3 - Timeout thật vẫn ghi total_requests/timeout/fallback đúng một lần
# ---------------------------------------------------------------------------
def test_42_regression_true_timeout_recorded_exactly_once():
    """Regression Test 3:
    Timeout thật ghi total_requests/timeout/fallback đúng một lần duy nhất.
    """
    class HardTimeoutProvider(BaseDecisionProvider):
        def get_name(self) -> str:
            return "hard_timeout_provider"

        async def decide(self, request, total_budget_ms=None):
            # Ngủ 500ms trong khi budget chỉ 100ms
            await asyncio.sleep(0.50)
            return DecisionResult(
                decision_type=request.decision_type,
                status="success",
                provider="hard_timeout_provider",
                model="jev-latest",
                decisions={},
                usage=DecisionUsage(),
                latency_ms=500.0,
            )

        async def check_health(self):
            return {"status": "ok"}

    breaker = CircuitBreaker(failure_threshold=3)
    provider = HardTimeoutProvider()
    service = DecisionService(provider=provider, circuit_breaker=breaker, mode="shadow")
    service.reset_metrics()

    req = DecisionRequest(
        decision_type="intent",
        state="Test true timeout",
        questions=get_intent_decision_questions(),
    )

    # 1. Async call với budget 100ms
    res = asyncio.run(service.execute_decision(req, budget_ms=100.0))
    assert res.status == "fallback"
    assert "DecisionTimeoutError" in (res.error_message or "")

    metrics = service.get_metrics_summary()
    assert metrics["total_requests"] == 1
    assert metrics["timeout_count"] == 1
    assert metrics["fallback_count"] == 1
    assert metrics["success_count"] == 0
    assert breaker.consecutive_failures == 1

    # 2. Sync call với budget 100ms
    res_sync = service.decide_intent_sync(
        question="Học phí?",
        current_intent="general",
        remaining_budget_ms=100.0,
    )
    assert res_sync is None or res_sync.status == "fallback"

    # Mỗi call timeout chỉ ghi nhận tăng đúng 1 lần
    metrics2 = service.get_metrics_summary()
    assert metrics2["total_requests"] == 2
    assert metrics2["timeout_count"] == 2
    assert metrics2["fallback_count"] == 2
    assert metrics2["success_count"] == 0
    assert breaker.consecutive_failures == 2


# ---------------------------------------------------------------------------
# TEST 43: REGRESSION 4 - Provider trả kết quả muộn không ghi success
# ---------------------------------------------------------------------------
def test_43_regression_late_provider_result_does_not_record_success():
    """Regression Test 4:
    Provider trả kết quả muộn sau khi tác vụ đã timeout/aborted:
    Tuyệt đối không ghi nhận success và không làm thay đổi trạng thái circuit breaker.
    """
    provider_gate = asyncio.Event()

    class DelayedProvider(BaseDecisionProvider):
        def get_name(self) -> str:
            return "delayed_provider"

        async def decide(self, request, total_budget_ms=None):
            await provider_gate.wait()
            return DecisionResult(
                decision_type=request.decision_type,
                status="success",
                provider="delayed_provider",
                model="jev-latest",
                decisions={"intent": DecisionItem(type="choice", choice="scholarship", confidence=0.99)},
                usage=DecisionUsage(input_tokens=10, output_tokens=10),
                latency_ms=250.0,
            )

        async def check_health(self):
            return {"status": "ok"}

    breaker = CircuitBreaker(failure_threshold=1)
    provider = DelayedProvider()
    service = DecisionService(provider=provider, circuit_breaker=breaker, mode="shadow")
    service.reset_metrics()

    req = DecisionRequest(
        decision_type="intent",
        state="Test late success",
        questions=get_intent_decision_questions(),
    )

    async def scenario():
        # Bắt đầu với tracker và budget ngắn (60ms)
        tracker = DecisionTracker(request=req, service=service, budget_ms=60.0)

        task = asyncio.create_task(service.execute_decision(req, budget_ms=60.0, tracker=tracker))

        # Đợi 100ms để caller hết hạn timeout
        await asyncio.sleep(0.10)

        # Giả lập caller đã timeout và ghi nhận timeout
        tracker.record_timeout_if_not_recorded(latency_ms=60.0)
        assert breaker.state == "open"

        # Mở cổng cho provider hoàn tất muộn
        provider_gate.set()

        # Chờ task hoàn tất
        res = await task
        # Task trả về fallback, không trả success
        assert res.status == "fallback"

    asyncio.run(scenario())

    # Kiểm tra metric:
    metrics = service.get_metrics_summary()
    assert metrics["success_count"] == 0
    assert metrics["timeout_count"] == 1
    assert service._recent_successes == 0

    # Circuit breaker vẫn ở trạng thái open, không bị thành công muộn làm chuyển về closed!
    assert breaker.state == "open"


# ---------------------------------------------------------------------------
# TEST 44: REGRESSION 5 - Sau timeout/cancellation, request tiếp theo vẫn hoạt động;
# không rò rỉ semaphore hoặc coroutine.
# ---------------------------------------------------------------------------
def test_44_regression_no_semaphore_or_coroutine_leak_after_timeout_and_cancellation():
    """Regression Test 5:
    Sau timeout và cancellation, request tiếp theo vẫn hoạt động bình thường;
    không rò rỉ semaphore capacity hay unawaited coroutine.
    """
    import warnings

    class DualProvider(BaseDecisionProvider):
        def __init__(self):
            self.mode_op = "normal"

        def get_name(self) -> str:
            return "dual_provider"

        async def decide(self, request, total_budget_ms=None):
            if self.mode_op == "timeout":
                await asyncio.sleep(2.0)
            elif self.mode_op == "cancel":
                await asyncio.sleep(2.0)
            return DecisionResult(
                decision_type=request.decision_type,
                status="success",
                provider="dual_provider",
                model="jev-latest",
                decisions={"intent": DecisionItem(type="choice", choice="tuition", confidence=0.95)},
                usage=DecisionUsage(input_tokens=15, output_tokens=5),
                latency_ms=15.0,
            )

        async def check_health(self):
            return {"status": "ok"}

    provider = DualProvider()
    breaker = CircuitBreaker(failure_threshold=5)
    max_c = 3
    service = DecisionService(
        provider=provider,
        circuit_breaker=breaker,
        max_concurrency=max_c,
        mode="shadow",
    )
    service.reset_metrics()

    initial_semaphore_val = service._concurrency_limiter._value

    with warnings.catch_warnings(record=True) as captured_warnings:
        warnings.simplefilter("always")

        # 1. Gây ra 1 timeout
        provider.mode_op = "timeout"
        res_timeout = service.decide_intent_sync("Học phí?", "general", remaining_budget_ms=70.0)
        assert res_timeout is None or res_timeout.status == "fallback"

        # Kiểm tra semaphore sau timeout
        assert service._concurrency_limiter._value == initial_semaphore_val

        # 2. Gây ra 1 client cancellation
        provider.mode_op = "cancel"

        async def cancel_job():
            req = DecisionRequest(
                decision_type="intent",
                state="Cancel state",
                questions=get_intent_decision_questions(),
            )
            t = asyncio.create_task(service.execute_decision(req, budget_ms=1000.0))
            await asyncio.sleep(0.02)
            t.cancel()
            with pytest.raises(asyncio.CancelledError):
                await t

        asyncio.run(cancel_job())

        # Kiểm tra semaphore sau cancellation
        assert service._concurrency_limiter._value == initial_semaphore_val

        # 3. Thực hiện request tiếp theo ở trạng thái bình thường (normal)
        provider.mode_op = "normal"
        req_normal = DecisionRequest(
            decision_type="intent",
            state="Normal state",
            questions=get_intent_decision_questions(),
        )
        res_normal = asyncio.run(service.execute_decision(req_normal, budget_ms=500.0))

        # Yêu cầu tiếp theo thành công mỹ mãn
        assert res_normal.status == "success"
        assert res_normal.decisions["intent"].choice == "tuition"
        assert service._concurrency_limiter._value == initial_semaphore_val

        # 4. Kiểm tra không có coroutine warning nào bị rò rỉ
        coro_warnings = [
            w for w in captured_warnings
            if issubclass(w.category, RuntimeWarning) and "coroutine" in str(w.message).lower()
        ]
        assert len(coro_warnings) == 0, f"Rò rỉ coroutine warning: {coro_warnings}"


# ---------------------------------------------------------------------------
# TEST 45: REGRESSION - Response TypeSafe hợp lệ, mock parse chậm vượt deadline
# ---------------------------------------------------------------------------
def test_45_regression_valid_response_slow_parse_exceeds_deadline_records_timeout_once(monkeypatch):
    """Regression Test 1:
    Response TypeSafe hợp lệ, mock parse chậm vượt deadline:
    total_requests=1, timeout=1, fallback=1, success=0.
    """
    def mock_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "answers": {
                    "intent": {
                        "type": "choice",
                        "choice": "tuition",
                        "confidence": 0.95,
                    },
                    "needs_clarification": {
                        "type": "noul",
                        "noul": 0.05,
                        "confidence": 0.95,
                    },
                },
                "model": "jev-latest",
                "usage": {"input_tokens": 20, "output_tokens": 10},
            },
        )

    mock_client = httpx.AsyncClient(transport=httpx.MockTransport(mock_handler))
    provider = TypeSafeJevProvider(api_key="test-key", client=mock_client)

    # Mock parse chậm vượt deadline (ngủ 120ms trong khi budget_ms=60ms)
    orig_parse = provider._parse_response

    def slow_parse(*args, **kwargs):
        time.sleep(0.12)
        return orig_parse(*args, **kwargs)

    monkeypatch.setattr(provider, "_parse_response", slow_parse)

    breaker = CircuitBreaker(failure_threshold=3)
    service = DecisionService(provider=provider, circuit_breaker=breaker, mode="shadow")
    service.reset_metrics()

    req = DecisionRequest(
        decision_type="intent",
        state="Test slow parse beyond deadline",
        questions=get_intent_decision_questions(),
    )

    res = asyncio.run(service.execute_decision(req, budget_ms=60.0))

    # Kiểm tra kết quả trả về: fallback với timeout
    assert res.status == "fallback"
    assert "timeout" in (res.error_message or "").lower() or "timeout" in (res.status or "").lower()

    # Kiểm tra metrics: total=1, timeout=1, fallback=1, success=0
    metrics = service.get_metrics_summary()
    assert metrics["total_requests"] == 1
    assert metrics["timeout_count"] == 1
    assert metrics["fallback_count"] == 1
    assert metrics["success_count"] == 0

    # Circuit breaker ghi nhận failure, không ghi nhận recent successes
    assert breaker.consecutive_failures == 1
    assert service._recent_successes == 0
    assert service._recent_errors == 1


# ---------------------------------------------------------------------------
# TEST 46: REGRESSION - Race giữa success và outer timeout kiểm soát bằng event/barrier
# ---------------------------------------------------------------------------
def test_46_regression_race_between_success_and_outer_timeout_event_controlled():
    """Regression Test 2:
    Dùng event/barrier kiểm soát race giữa success và outer timeout:
    Nếu timeout thắng, success muộn không đóng breaker hoặc tăng recent successes.
    """
    provider_arrived = asyncio.Event()
    timeout_settled = asyncio.Event()

    class ControlledRaceProvider(BaseDecisionProvider):
        def get_name(self) -> str:
            return "controlled_race_provider"

        async def decide(self, request, total_budget_ms=None):
            # 1. Báo cho test controller biết provider đã chuẩn bị response
            provider_arrived.set()
            # 2. Đợi timeout_settled từ test controller (timeout thắng trước)
            await timeout_settled.wait()
            # 3. Trả về response hợp lệ
            return DecisionResult(
                decision_type=request.decision_type,
                status="success",
                provider="controlled_race_provider",
                model="jev-latest",
                decisions={"intent": DecisionItem(type="choice", choice="tuition", confidence=0.95)},
                usage=DecisionUsage(input_tokens=10, output_tokens=5),
                latency_ms=30.0,
            )

        async def check_health(self):
            return {"status": "ok"}

    breaker = CircuitBreaker(failure_threshold=1)
    provider = ControlledRaceProvider()
    service = DecisionService(provider=provider, circuit_breaker=breaker, mode="shadow")
    service.reset_metrics()

    req = DecisionRequest(
        decision_type="intent",
        state="Race condition test with event barrier",
        questions=get_intent_decision_questions(),
    )

    async def scenario():
        tracker = DecisionTracker(request=req, service=service, budget_ms=100.0)
        task = asyncio.create_task(service.execute_decision(req, budget_ms=100.0, tracker=tracker))

        # Đợi provider bắt đầu và chạm barrier (kiểm soát 100% bằng event)
        await provider_arrived.wait()

        # Giả lập outer timeout xảy ra trước và thắng race:
        tracker.mark_aborted(is_timeout=True)
        timeout_res = tracker.record_timeout_if_not_recorded(latency_ms=100.0)
        assert breaker.state == "open"
        assert breaker.consecutive_failures == 1
        assert service._recent_errors == 1

        # Bây giờ mở barrier cho provider thành công muộn chạy tiếp
        timeout_settled.set()

        res = await task
        # Kết quả trả về phải là fallback timeout của nhánh thắng
        assert res.status == "fallback"
        assert res.error_message == timeout_res.error_message

    asyncio.run(scenario())

    # Kiểm tra metric & circuit breaker:
    metrics = service.get_metrics_summary()
    assert metrics["total_requests"] == 1
    assert metrics["timeout_count"] == 1
    assert metrics["fallback_count"] == 1
    assert metrics["success_count"] == 0

    # Circuit breaker tuyệt đối không bị đóng lại, không tăng _recent_successes
    assert breaker.state == "open"
    assert breaker.consecutive_failures == 1
    assert service._recent_successes == 0
    assert service._recent_errors == 1


# ---------------------------------------------------------------------------
# TEST 47: REGRESSION - Success thắng trước deadline không bị ghi thêm timeout
# ---------------------------------------------------------------------------
def test_47_regression_success_wins_before_deadline_no_extra_timeout_recorded():
    """Regression Test 3:
    Success thắng trước deadline: không bị ghi thêm timeout.
    """
    class QuickSuccessProvider(BaseDecisionProvider):
        def get_name(self) -> str:
            return "quick_success_provider"

        async def decide(self, request, total_budget_ms=None):
            return DecisionResult(
                decision_type=request.decision_type,
                status="success",
                provider="quick_success_provider",
                model="jev-latest",
                decisions={"intent": DecisionItem(type="choice", choice="cutoff", confidence=0.98)},
                usage=DecisionUsage(input_tokens=15, output_tokens=10),
                latency_ms=15.0,
            )

        async def check_health(self):
            return {"status": "ok"}

    breaker = CircuitBreaker(failure_threshold=2)
    provider = QuickSuccessProvider()
    service = DecisionService(provider=provider, circuit_breaker=breaker, mode="shadow")
    service.reset_metrics()

    req = DecisionRequest(
        decision_type="intent",
        state="Test success wins before deadline",
        questions=get_intent_decision_questions(),
    )

    async def scenario():
        tracker = DecisionTracker(request=req, service=service, budget_ms=500.0)
        res = await service.execute_decision(req, budget_ms=500.0, tracker=tracker)

        assert res.status == "success"
        assert res.decisions["intent"].choice == "cutoff"

        # Sau khi success đã thắng trước deadline, mô phỏng outer timeout hoặc watcher bắn timeout muộn
        tracker.mark_aborted(is_timeout=True)
        timeout_res = tracker.record_timeout_if_not_recorded(latency_ms=500.0)

        # Kết quả trả về từ record_timeout_if_not_recorded không ghi đè kết quả success đã hoàn tất
        assert timeout_res.status == "success"

    asyncio.run(scenario())

    # Kiểm tra metric & circuit breaker:
    metrics = service.get_metrics_summary()
    assert metrics["total_requests"] == 1
    assert metrics["success_count"] == 1
    assert metrics["timeout_count"] == 0
    assert metrics["fallback_count"] == 0
    assert metrics["error_count"] == 0

    assert breaker.consecutive_failures == 0
    assert breaker.state == "closed"
    assert service._recent_successes == 1
    assert service._recent_errors == 0


# ---------------------------------------------------------------------------
# TEST 48: REGRESSION - Client cancellation vẫn không tính lỗi provider
# ---------------------------------------------------------------------------
def test_48_regression_client_cancellation_never_counted_as_provider_error():
    """Regression Test 4:
    Client cancellation vẫn không tính lỗi provider:
    total_requests=0, timeout=0, fallback=0, breaker không tăng failures.
    """
    cancel_barrier = asyncio.Event()

    class StalledCancelProvider(BaseDecisionProvider):
        def get_name(self) -> str:
            return "stalled_cancel_provider"

        async def decide(self, request, total_budget_ms=None):
            cancel_barrier.set()
            await asyncio.sleep(10.0)
            return DecisionResult(
                decision_type=request.decision_type,
                status="success",
                provider="stalled_cancel_provider",
                model="jev-latest",
                decisions={},
                usage=DecisionUsage(),
                latency_ms=10.0,
            )

        async def check_health(self):
            return {"status": "ok"}

    breaker = CircuitBreaker(failure_threshold=1)
    provider = StalledCancelProvider()
    service = DecisionService(provider=provider, circuit_breaker=breaker, mode="shadow")
    service.reset_metrics()

    req = DecisionRequest(
        decision_type="intent",
        state="Test client cancellation isolation",
        questions=get_intent_decision_questions(),
    )

    async def scenario():
        tracker = DecisionTracker(request=req, service=service, budget_ms=2000.0)
        task = asyncio.create_task(service.execute_decision(req, budget_ms=2000.0, tracker=tracker))

        # Đợi provider bắt đầu nhận tác vụ (kiểm soát bằng event, không sleep)
        await cancel_barrier.wait()

        # Client chủ động hủy
        tracker.mark_cancelled()
        task.cancel()

        with pytest.raises(asyncio.CancelledError):
            await task

        # Thử gọi record_timeout_if_not_recorded sau khi client đã hủy -> tuyệt đối không chuyển thành timeout
        res_after = tracker.record_timeout_if_not_recorded(latency_ms=2000.0)
        assert "CancelledError" in (res_after.error_message or "")
        assert res_after.status == "fallback"

    asyncio.run(scenario())

    metrics = service.get_metrics_summary()
    assert metrics["total_requests"] == 0
    assert metrics["timeout_count"] == 0
    assert metrics["fallback_count"] == 0
    assert metrics["error_count"] == 0
    assert metrics["success_count"] == 0

    assert breaker.consecutive_failures == 0
    assert breaker.state == "closed"
    assert service._recent_errors == 0
    assert service._recent_successes == 0


# ---------------------------------------------------------------------------
# TEST 49: REGRESSION - Request tiếp theo hoạt động bình thường, không rò tài nguyên
# ---------------------------------------------------------------------------
def test_49_regression_consecutive_requests_healthy_no_resource_leak():
    """Regression Test 5:
    Request tiếp theo hoạt động bình thường, không rò rỉ semaphore hay coroutine.
    """
    import warnings

    breaker = CircuitBreaker(failure_threshold=3)
    max_c = 2

    class MultiModeProvider(BaseDecisionProvider):
        def __init__(self):
            self.mode_op = "normal"
            self.barrier = asyncio.Event()

        def get_name(self) -> str:
            return "multimode_provider"

        async def decide(self, request, total_budget_ms=None):
            if self.mode_op == "timeout":
                await asyncio.sleep(0.50)
            elif self.mode_op == "cancel":
                self.barrier.set()
                await asyncio.sleep(10.0)
            return DecisionResult(
                decision_type=request.decision_type,
                status="success",
                provider="multimode_provider",
                model="jev-latest",
                decisions={"intent": DecisionItem(type="choice", choice="tuition", confidence=0.96)},
                usage=DecisionUsage(input_tokens=12, output_tokens=8),
                latency_ms=10.0,
            )

        async def check_health(self):
            return {"status": "ok"}

    provider = MultiModeProvider()
    service = DecisionService(
        provider=provider,
        circuit_breaker=breaker,
        max_concurrency=max_c,
        mode="shadow",
    )
    service.reset_metrics()

    initial_semaphore_val = service._concurrency_limiter._value

    with warnings.catch_warnings(record=True) as captured:
        warnings.simplefilter("always")

        # Bước 1: 1 request bị timeout
        provider.mode_op = "timeout"
        req1 = DecisionRequest(
            decision_type="intent",
            state="Req 1 timeout",
            questions=get_intent_decision_questions(),
        )
        res1 = asyncio.run(service.execute_decision(req1, budget_ms=50.0))
        assert res1.status == "fallback"
        assert service._concurrency_limiter._value == initial_semaphore_val

        # Bước 2: 1 request bị cancel
        provider.mode_op = "cancel"

        async def cancel_job():
            req2 = DecisionRequest(
                decision_type="intent",
                state="Req 2 cancel",
                questions=get_intent_decision_questions(),
            )
            t = asyncio.create_task(service.execute_decision(req2, budget_ms=1000.0))
            await provider.barrier.wait()
            t.cancel()
            with pytest.raises(asyncio.CancelledError):
                await t

        asyncio.run(cancel_job())
        assert service._concurrency_limiter._value == initial_semaphore_val

        # Bước 3: Request tiếp theo hoàn toàn bình thường
        provider.mode_op = "normal"
        req3 = DecisionRequest(
            decision_type="intent",
            state="Req 3 normal",
            questions=get_intent_decision_questions(),
        )
        res3 = asyncio.run(service.execute_decision(req3, budget_ms=300.0))
        assert res3.status == "success"
        assert res3.decisions["intent"].choice == "tuition"
        assert service._concurrency_limiter._value == initial_semaphore_val

        # Bước 4: Kiểm tra không có rò rỉ unawaited coroutine warning
        coro_warnings = [
            w for w in captured
            if issubclass(w.category, RuntimeWarning) and "coroutine" in str(w.message).lower()
        ]
        assert len(coro_warnings) == 0

    # Kiểm tra metric tích lũy chính xác:
    metrics = service.get_metrics_summary()
    assert metrics["total_requests"] == 2
    assert metrics["timeout_count"] == 1
    assert metrics["fallback_count"] == 1
    assert metrics["success_count"] == 1
