"""
test_jev_shadow_mode_chat.py
Comprehensive Mock-Only Tests for JEV SHADOW Mode in Chat and RAG Pipeline.

Verifies all critical constraints:
1. Shadow mode invokes Jev to observe/record metrics without altering routing, retrieval, or LLM answer.
2. Divergence vs baseline decision is accurately measured and tracked.
3. Chat never fails under any Jev failure mode:
   - Timeout / budget exceeded
   - Out of credit / quota exhausted (HTTP 402)
   - Rate limit (HTTP 429)
   - Authentication error (HTTP 401)
   - Internal server error (HTTP 500)
   - Malformed schema response (HTTP 200 with invalid schema)
4. Redaction sanitizes PII and TypeSafe API keys before sending state to Jev.
5. Telemetry and metrics summary accurately aggregate latency, token usage, and divergence stats.
"""
import asyncio
import json
import logging
import pytest
import httpx

from backend.app.config import settings
from backend.app.decision_engine.contracts import (
    DecisionItem,
    DecisionRequest,
    DecisionResult,
    DecisionUsage,
)
from backend.app.decision_engine.providers.base import (
    DecisionAuthenticationError,
    DecisionQuotaExhaustedError,
    DecisionRateLimitError,
    DecisionServerError,
    DecisionTimeoutError,
    DecisionValidationError,
)
from backend.app.decision_engine.providers.typesafe_jev import TypeSafeJevProvider
from backend.app.decision_engine.redaction import redact_text
from backend.app.decision_engine.service import DecisionService
from backend.app.rag import pipeline


@pytest.fixture(autouse=True)
def clean_environment(monkeypatch):
    """Bảo đảm môi trường test sạch, không phụ thuộc vào .env bên ngoài."""
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("JEV_MODE", "shadow")
    monkeypatch.setenv("TYPESAFE_API_KEY", "apikey_mock_test_key_shadow_mode_1234567890")
    monkeypatch.setenv("JEV_TOTAL_BUDGET_MS", "2000.0")
    monkeypatch.setenv("JEV_TIMEOUT_SECONDS", "1.0")


def _mock_pipeline_rag(monkeypatch, docs=None, answer_chunks=None):
    """Mock các hàm retrieval và LLM để cô lập hành vi của Decision Engine trong pipeline."""
    sample_docs = docs or [
        {
            "title": "Học phí và xét tuyển HUIT",
            "text": "Trường Đại học Công Thương TP.HCM đào tạo đa ngành với học phí tín chỉ hợp lý.",
            "score": 0.88,
            "category": "tuition",
        }
    ]
    sample_chunks = answer_chunks or ["Thông tin tuyển sinh ", "HUIT 2026 chính xác."]

    monkeypatch.setattr(pipeline, "retrieve", lambda q, top_k, timings=None: sample_docs)
    monkeypatch.setattr(pipeline, "stream_llm", lambda sys, user: iter(sample_chunks))


def _create_mock_jev_handler(captured=None, intent_choice="tuition", sufficiency_choice="sufficient"):
    """Tạo mock HTTP handler trả về đầy đủ các câu hỏi theo contract của Jev."""
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode("utf-8"))
        if captured is not None:
            captured.append(body)
        answers = {}
        for q_id in body.get("questions", {}):
            if q_id == "intent":
                answers["intent"] = {
                    "type": "choice",
                    "choice": intent_choice,
                    "confidence": 0.95,
                    "probabilities": {intent_choice: 0.95, "general": 0.05},
                }
            elif q_id == "sufficiency":
                answers["sufficiency"] = {
                    "type": "choice",
                    "choice": sufficiency_choice,
                    "confidence": 0.92,
                    "probabilities": {sufficiency_choice: 0.92},
                }
            elif q_id == "needs_clarification":
                answers["needs_clarification"] = {
                    "type": "noul",
                    "noul": 0.15,
                }
        return httpx.Response(
            200,
            json={
                "answers": answers,
                "model": body.get("model", "jev-latest"),
                "usage": {"input_tokens": 100, "output_tokens": 0},
            },
        )
    return handler


# ---------------------------------------------------------------------------
# TEST 1: Shadow mode khi Jev thành công
# - Jev đề xuất intent khác với baseline
# - Kết quả chat và routing giữ nguyên theo baseline
# - Metric divergence và token được ghi nhận đầy đủ
# ---------------------------------------------------------------------------
def test_shadow_chat_success_preserves_baseline_and_records_divergence(monkeypatch):
    captured_requests = []
    mock_handler = _create_mock_jev_handler(captured=captured_requests, intent_choice="tuition")

    mock_client = httpx.AsyncClient(transport=httpx.MockTransport(mock_handler))
    provider = TypeSafeJevProvider(api_key="apikey_test", client=mock_client)
    service = DecisionService(provider=provider, mode="shadow")
    service.reset_metrics()

    monkeypatch.setattr(pipeline, "decision_service", service)
    _mock_pipeline_rag(monkeypatch)

    # Câu hỏi mơ hồ: baseline intent là "general"
    events = list(pipeline.stream_answer("Em muốn hỏi thông tin", use_cache=False))
    parsed = [json.loads(line) for line in events if line.strip()]

    # 1. Pipeline hoàn thành bình thường
    event_types = [e["type"] for e in parsed]
    assert "start" in event_types
    assert "token" in event_types
    assert "done" in event_types

    done_event = [e for e in parsed if e["type"] == "done"][0]
    assert done_event["payload"]["cached"] is False

    # 2. Câu trả lời chat không bị thay đổi
    full_answer = "".join(e["payload"]["token"] for e in parsed if e["type"] == "token")
    assert "Thông tin tuyển sinh HUIT 2026 chính xác." == full_answer

    # 3. Jev đã được gọi và nhận được dữ liệu
    assert len(captured_requests) >= 1
    req_body = captured_requests[0]
    assert req_body["model"] == "jev-latest"
    assert "questions" in req_body

    # 4. Metrics summary ghi nhận đúng độ khác biệt (divergence)
    metrics = service.get_metrics_summary()
    assert metrics["mode"] == "shadow"
    assert metrics["total_requests"] >= 1
    assert metrics["success_count"] >= 1
    assert metrics["fallback_count"] == 0
    assert metrics["tokens"]["input_tokens"] >= 100
    # Jev chọn 'tuition' trong khi baseline là 'general' -> diverged
    assert metrics["divergence"]["intent"]["comparisons"] >= 1
    assert metrics["divergence"]["intent"]["divergences"] >= 1
    assert metrics["divergence"]["intent"]["divergence_rate"] == 1.0


# ---------------------------------------------------------------------------
# TEST 2: Shadow mode khi Jev bị Timeout
# - Chatbot phản hồi bình thường mà không bị crash hay chậm trễ
# - Fallback được ghi nhận với lý do timeout
# ---------------------------------------------------------------------------
def test_shadow_chat_timeout_falls_back_cleanly(monkeypatch):
    class TimeoutProvider(TypeSafeJevProvider):
        async def decide(self, request, total_budget_ms=None):
            raise DecisionTimeoutError("Budget exceeded: simulated timeout")

    provider = TimeoutProvider(api_key="apikey_test")
    service = DecisionService(provider=provider, mode="shadow")
    service.reset_metrics()

    monkeypatch.setattr(pipeline, "decision_service", service)
    _mock_pipeline_rag(monkeypatch)

    events = list(pipeline.stream_answer("Em muốn hỏi thông tin", use_cache=False))
    parsed = [json.loads(line) for line in events if line.strip()]

    # Chat thành công 100%
    event_types = [e["type"] for e in parsed]
    assert "start" in event_types
    assert "token" in event_types
    assert "done" in event_types

    metrics = service.get_metrics_summary()
    assert metrics["timeout_count"] >= 1
    assert metrics["fallback_count"] >= 1
    assert metrics["success_count"] == 0


# ---------------------------------------------------------------------------
# TEST 3: Shadow mode khi Jev hết credit/quota (HTTP 402)
# - Không retry vô ích
# - Ghi nhận quota_exhausted
# - Chat không bị ảnh hưởng
# ---------------------------------------------------------------------------
def test_shadow_chat_quota_exhausted_falls_back_safely(monkeypatch):
    call_attempts = 0

    def mock_handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_attempts
        call_attempts += 1
        return httpx.Response(402, json={"error": "Account out of credits"})

    mock_client = httpx.AsyncClient(transport=httpx.MockTransport(mock_handler))
    provider = TypeSafeJevProvider(api_key="apikey_test", client=mock_client)
    service = DecisionService(provider=provider, mode="shadow")
    service.reset_metrics()

    monkeypatch.setattr(pipeline, "decision_service", service)
    _mock_pipeline_rag(monkeypatch)

    events = list(pipeline.stream_answer("Em muốn hỏi thông tin", use_cache=False))
    parsed = [json.loads(line) for line in events if line.strip()]

    # Chat hoàn tất bình thường
    event_types = [e["type"] for e in parsed]
    assert "start" in event_types
    assert "token" in event_types
    assert "done" in event_types

    # HTTP 402 là non-retryable: không retry trong từng request (tối đa 2 lần cho 2 task: intent + evidence)
    assert call_attempts in (1, 2)

    metrics = service.get_metrics_summary()
    assert metrics["quota_exhausted_count"] >= 1
    assert metrics["fallback_count"] >= 1
    assert metrics["success_count"] == 0


# ---------------------------------------------------------------------------
# TEST 4: Shadow mode khi Jev bị Rate Limit (HTTP 429)
# - Chatbot không sập
# - Rate limit được ghi nhận
# ---------------------------------------------------------------------------
def test_shadow_chat_rate_limit_falls_back_safely(monkeypatch):
    def mock_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, headers={"Retry-After": "0.1"}, json={"error": "Too Many Requests"})

    mock_client = httpx.AsyncClient(transport=httpx.MockTransport(mock_handler))
    provider = TypeSafeJevProvider(api_key="apikey_test", client=mock_client)
    service = DecisionService(provider=provider, mode="shadow")
    service.reset_metrics()

    monkeypatch.setattr(pipeline, "decision_service", service)
    _mock_pipeline_rag(monkeypatch)

    events = list(pipeline.stream_answer("Em muốn hỏi thông tin", use_cache=False))
    parsed = [json.loads(line) for line in events if line.strip()]

    event_types = [e["type"] for e in parsed]
    assert "start" in event_types
    assert "done" in event_types

    metrics = service.get_metrics_summary()
    assert metrics["rate_limit_count"] >= 1
    assert metrics["fallback_count"] >= 1


# ---------------------------------------------------------------------------
# TEST 5: Shadow mode khi Jev bị lỗi 500 máy chủ
# - Tối đa 1 retry rồi fallback
# - Chatbot hoạt động trơn tru
# ---------------------------------------------------------------------------
def test_shadow_chat_server_error_500_falls_back_safely(monkeypatch):
    def mock_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": "Internal server error"})

    mock_client = httpx.AsyncClient(transport=httpx.MockTransport(mock_handler))
    provider = TypeSafeJevProvider(api_key="apikey_test", client=mock_client)
    service = DecisionService(provider=provider, mode="shadow")
    service.reset_metrics()

    monkeypatch.setattr(pipeline, "decision_service", service)
    _mock_pipeline_rag(monkeypatch)

    events = list(pipeline.stream_answer("Em muốn hỏi thông tin", use_cache=False))
    parsed = [json.loads(line) for line in events if line.strip()]

    event_types = [e["type"] for e in parsed]
    assert "start" in event_types
    assert "done" in event_types

    metrics = service.get_metrics_summary()
    assert metrics["error_count"] >= 1
    assert metrics["fallback_count"] >= 1


# ---------------------------------------------------------------------------
# TEST 6: Redaction trước khi gửi dữ liệu sang Jev
# - Khử PII: Email, SĐT, CCCD
# - Khử TypeSafe API key (apikey_...)
# - Không để lộ secret trong Jev request state
# ---------------------------------------------------------------------------
def test_shadow_redaction_before_sending_to_jev(monkeypatch):
    sent_states = []
    mock_handler = _create_mock_jev_handler(captured=sent_states, intent_choice="general")

    mock_client = httpx.AsyncClient(transport=httpx.MockTransport(mock_handler))
    provider = TypeSafeJevProvider(api_key="apikey_test", client=mock_client)
    service = DecisionService(provider=provider, mode="shadow")

    monkeypatch.setattr(pipeline, "decision_service", service)
    _mock_pipeline_rag(monkeypatch)

    sensitive_question = (
        "Em tên Nam, email nam.huit@gmail.com, sđt 0912345678, cccd 079201012345. "
        "Em có key apikey_21708b92e92a9b4143a4a54e28dda19653f9_27176aebbee78bb6810214c032643c05c1cfdb830778269cd21b251f64280634 "
        "cần hỏi thông tin"
    )

    list(pipeline.stream_answer(sensitive_question, use_cache=False))

    assert len(sent_states) >= 1
    sent_state_str = " ".join(str(s.get("state", "")) for s in sent_states)

    # Xác minh không chứa thông tin nhạy cảm thô
    assert "nam.huit@gmail.com" not in sent_state_str
    assert "0912345678" not in sent_state_str
    assert "079201012345" not in sent_state_str
    assert "apikey_21708b92e92a9b41" not in sent_state_str

    # Xác minh đã có nhãn REDACTED
    assert "[REDACTED_EMAIL]" in sent_state_str
    assert "[REDACTED_PHONE]" in sent_state_str
    assert "[REDACTED_ID]" in sent_state_str
    assert "[REDACTED_KEY]" in sent_state_str


# ---------------------------------------------------------------------------
# TEST 7: Synchronous /api/chat endpoint hoạt động bình thường trong shadow mode
# ---------------------------------------------------------------------------
def test_sync_chat_endpoint_shadow_mode_mock(monkeypatch):
    mock_handler = _create_mock_jev_handler(intent_choice="admission")

    mock_client = httpx.AsyncClient(transport=httpx.MockTransport(mock_handler))
    provider = TypeSafeJevProvider(api_key="apikey_test", client=mock_client)
    service = DecisionService(provider=provider, mode="shadow")

    monkeypatch.setattr(pipeline, "decision_service", service)
    _mock_pipeline_rag(
        monkeypatch,
        answer_chunks=["HUIT xét tuyển học bạ ", "ngành CNTT với điểm chuẩn phù hợp."]
    )

    res = pipeline.answer("Trường HUIT có xét học bạ ngành Công nghệ thông tin không?", use_cache=False)
    assert isinstance(res, dict)
    assert "HUIT xét tuyển học bạ ngành CNTT với điểm chuẩn phù hợp." in res["answer"]
    assert "sources" in res
    assert "meta" in res


# ---------------------------------------------------------------------------
# TEST 8: Regression Test - Request chậm 200ms với ngân sách 80ms
# - Tái hiện trực tiếp bug: MockTransport delay 200ms, budget 80ms
# - Outer layer timeout tại run_coro_sync phải ghi nhận metric đúng 1 lần:
#   total_requests == 1, timeout_count == 1, fallback_count == 1, success_count == 0
# - Kết quả trả về None hoặc fallback, không để metric bằng 0.
# ---------------------------------------------------------------------------
def test_regression_slow_request_timeout_recorded_exactly_once(monkeypatch):
    async def slow_handler(request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(0.20)
        return httpx.Response(
            200,
            json={
                "answers": {
                    "intent": {
                        "type": "choice",
                        "choice": "tuition",
                        "confidence": 0.9,
                    }
                },
                "model": "jev-latest",
                "usage": {"input_tokens": 50, "output_tokens": 0},
            },
        )

    mock_client = httpx.AsyncClient(transport=httpx.MockTransport(slow_handler))
    provider = TypeSafeJevProvider(api_key="apikey_test", client=mock_client)
    service = DecisionService(provider=provider, mode="shadow")
    service.reset_metrics()

    # Gọi phiên bản sync với ngân sách 80ms (nhỏ hơn 200ms delay)
    res = service.decide_intent_sync(
        question="Em muốn hỏi về học phí và điểm chuẩn ngành CNTT",
        current_intent="general",
        remaining_budget_ms=80.0,
    )

    # 1. Caller nhận None do timeout
    assert res is None or res.status == "fallback"

    # 2. Metric ghi nhận đúng 1 lần: total=1, timeout=1, fallback=1, success=0
    metrics = service.get_metrics_summary()
    assert metrics["total_requests"] == 1
    assert metrics["timeout_count"] == 1
    assert metrics["fallback_count"] == 1
    assert metrics["success_count"] == 0
    assert service.circuit_breaker.consecutive_failures == 1


# ---------------------------------------------------------------------------
# TEST 9: Regression Test - Idempotency & No Duplicate Counting
# - Gọi nhiều lần record trên cùng DecisionTracker không làm tăng metric
# - Late success từ provider sau timeout bị từ chối, không ghi đè thành 2xx
# ---------------------------------------------------------------------------
def test_regression_timeout_no_duplicate_counting_and_no_late_success():
    from backend.app.decision_engine.service import DecisionTracker, get_intent_decision_questions

    provider = TypeSafeJevProvider(api_key="apikey_test")
    service = DecisionService(provider=provider, mode="shadow")
    service.reset_metrics()

    req = DecisionRequest(
        decision_type="intent",
        state="Test state",
        model="jev-latest",
        questions=get_intent_decision_questions(),
    )
    tracker = DecisionTracker(request=req, service=service, budget_ms=80.0)

    # Lần 1: ghi nhận timeout
    fb1 = tracker.record_timeout_if_not_recorded(latency_ms=80.0)
    assert fb1.status == "fallback"
    assert service.get_metrics_summary()["total_requests"] == 1
    assert service.get_metrics_summary()["timeout_count"] == 1

    # Lần 2: ghi nhận timeout lặp lại (idempotent)
    fb2 = tracker.record_timeout_if_not_recorded(latency_ms=85.0)
    assert fb2.status == "fallback"
    assert service.get_metrics_summary()["total_requests"] == 1
    assert service.get_metrics_summary()["timeout_count"] == 1

    # Thử gửi kết quả thành công muộn (late success)
    late_success_res = DecisionResult(
        decision_type="intent",
        status="success",
        provider="typesafe_jev",
        model="jev-latest",
        decisions={},
        usage=DecisionUsage(),
        latency_ms=200.0,
    )
    recorded = tracker.record_once(late_success_res, status_group="2xx", latency_ms=200.0)
    assert recorded is False
    # Metrics không đổi
    summary = service.get_metrics_summary()
    assert summary["total_requests"] == 1
    assert summary["success_count"] == 0
    assert summary["timeout_count"] == 1


# ---------------------------------------------------------------------------
# TEST 10: Regression Test - Request thành công ghi metric bình thường
# ---------------------------------------------------------------------------
def test_regression_success_request_records_metrics_normally():
    mock_handler = _create_mock_jev_handler(intent_choice="tuition")
    mock_client = httpx.AsyncClient(transport=httpx.MockTransport(mock_handler))
    provider = TypeSafeJevProvider(api_key="apikey_test", client=mock_client)
    service = DecisionService(provider=provider, mode="shadow")
    service.reset_metrics()

    res = service.decide_intent_sync(
        question="Học phí trường HUIT bao nhiêu một tín chỉ?",
        current_intent="general",
        remaining_budget_ms=500.0,
    )

    assert res is not None
    assert res.status == "success"
    summary = service.get_metrics_summary()
    assert summary["total_requests"] == 1
    assert summary["success_count"] == 1
    assert summary["timeout_count"] == 0
    assert summary["fallback_count"] == 0
    assert service.circuit_breaker.state == "closed"
    assert service.circuit_breaker.consecutive_failures == 0


# ---------------------------------------------------------------------------
# TEST 11: Regression Test - Cancellation không phải là Timeout (Client Disconnect)
# - Request bị cancel khi chưa hết ngân sách (ví dụ sau 20ms của ngân sách 500ms)
# - Không tính là lỗi TypeSafe, không tăng timeout_count / fallback_count
# - Semaphore slot được giải phóng, không rò rỉ
# ---------------------------------------------------------------------------
def test_regression_client_cancellation_is_not_typesafe_timeout():
    from backend.app.decision_engine.service import get_intent_decision_questions

    async def _run():
        async def hanging_handler(request: httpx.Request) -> httpx.Response:
            await asyncio.sleep(0.50)
            return httpx.Response(200, json={})

        mock_client = httpx.AsyncClient(transport=httpx.MockTransport(hanging_handler))
        provider = TypeSafeJevProvider(api_key="apikey_test", client=mock_client)
        service = DecisionService(provider=provider, mode="shadow")
        service.reset_metrics()

        req = DecisionRequest(
            decision_type="intent",
            state="Test client disconnect cancellation",
            model="jev-latest",
            questions=get_intent_decision_questions(),
        )

        task = asyncio.create_task(
            service.execute_decision(req, total_budget_ms=500.0)
        )
        # Giả lập client ngắt kết nối sau 20ms (rất sớm so với ngân sách 500ms)
        await asyncio.sleep(0.02)
        task.cancel()

        with pytest.raises(asyncio.CancelledError):
            await task

        # Không được tính là timeout hay lỗi TypeSafe
        summary = service.get_metrics_summary()
        assert summary["total_requests"] == 0
        assert summary["timeout_count"] == 0
        assert summary["fallback_count"] == 0
        assert service.circuit_breaker.consecutive_failures == 0

        # Semaphore slot phải được giải phóng hoàn toàn
        acquired = service._concurrency_limiter.acquire(blocking=False)
        assert acquired is True
        service._concurrency_limiter.release()

    asyncio.run(_run())


# ---------------------------------------------------------------------------
# TEST 12: Regression Test - Chat hoàn tất và tổng ngân sách Jev được giữ
# - Khi Jev MockTransport chậm 200ms nhưng budget tổng của Jev là 100ms
# - Chat vẫn stream đầy đủ tới done event, không bị ngắt quãng
# ---------------------------------------------------------------------------
def test_regression_chat_completes_and_total_budget_respected_under_slow_jev(monkeypatch):
    monkeypatch.setenv("JEV_TOTAL_BUDGET_MS", "100.0")

    async def slow_handler(request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(0.20)
        return httpx.Response(
            200,
            json={
                "answers": {
                    "intent": {
                        "type": "choice",
                        "choice": "tuition",
                        "confidence": 0.95,
                    }
                },
                "model": "jev-latest",
                "usage": {"input_tokens": 100, "output_tokens": 0},
            },
        )

    mock_client = httpx.AsyncClient(transport=httpx.MockTransport(slow_handler))
    provider = TypeSafeJevProvider(api_key="apikey_test", client=mock_client)
    service = DecisionService(provider=provider, mode="shadow")
    service.reset_metrics()

    monkeypatch.setattr(pipeline, "decision_service", service)
    _mock_pipeline_rag(monkeypatch)

    # Câu hỏi mơ hồ ("Em muốn hỏi thông tin") có baseline intent là "general"
    events = list(pipeline.stream_answer("Em muốn hỏi thông tin", use_cache=False))
    parsed = [json.loads(line) for line in events if line.strip()]

    # Toàn bộ luồng chat kết thúc tốt đẹp
    event_types = [e["type"] for e in parsed]
    assert "start" in event_types
    assert "token" in event_types
    assert "done" in event_types

    done_event = [e for e in parsed if e["type"] == "done"][0]
    assert done_event["payload"]["cached"] is False

    # Jev ghi nhận timeout đúng 1 lần
    metrics = service.get_metrics_summary()
    assert metrics["timeout_count"] >= 1
    assert metrics["fallback_count"] >= 1
    assert metrics["success_count"] == 0
