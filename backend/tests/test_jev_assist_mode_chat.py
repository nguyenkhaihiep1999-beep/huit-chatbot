"""Offline end-to-end guards for enabling Jev decisions in the real chat pipeline."""
import asyncio
import hashlib
import json
import time
from unittest.mock import MagicMock

import httpx
import pymongo
import pytest

from backend.app.cache.memory_cache import MemoryCache, compute_cache_key
from backend.app.cache.mongo_cache import CacheManager
from backend.app.config import settings
from backend.app.decision_engine.providers.typesafe_jev import TypeSafeJevProvider
from backend.app.decision_engine.service import DecisionService
from backend.app.rag import pipeline
from backend.app.rag.intent import normalize_text


QUESTION = "Em muốn hỏi thông tin"
BASELINE_ANSWER = "Thông tin tuyển sinh từ nguồn fixture của hệ thống."
CLARIFY_ANSWER = "Bạn vui lòng cho biết ngành học và năm xét tuyển cần tư vấn."
EVIDENCE_HINT = "[LƯU Ý ĐÁNH GIÁ MINH CHỨNG]"


@pytest.fixture
def assist_chat(monkeypatch):
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("JEV_MODE", "assist")
    monkeypatch.setenv("TYPESAFE_API_KEY", "test-key")
    monkeypatch.setenv("JEV_CONFIDENCE_THRESHOLD", "0.80")
    monkeypatch.setenv("JEV_TOTAL_BUDGET_MS", "2000")
    monkeypatch.setenv("JEV_TIMEOUT_SECONDS", "1.0")
    monkeypatch.setenv("JEV_MODEL", "jev-latest")

    def forbid_network(*args, **kwargs):
        raise AssertionError("Assist rollout tests must never access the network")

    # Windows asyncio uses loopback sockets internally. Block real HTTP/DB
    # transports instead, leaving the event loop's own wake-up pipe intact.
    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", forbid_network)
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", forbid_network)
    monkeypatch.setattr(pymongo, "MongoClient", forbid_network)
    monkeypatch.setattr(pipeline, "classify_intent", lambda q: "general")
    monkeypatch.setattr(pipeline, "check_intent_guardrail", lambda *args, **kwargs: {"is_handled": False})
    monkeypatch.setattr(pipeline, "is_major_catalog_question", lambda q: False)
    monkeypatch.setattr(pipeline, "retrieve", lambda *args, **kwargs: [
        {"id": "assist_fixture", "title": "Fixture tuyển sinh", "text": "Dữ liệu kiểm thử cục bộ.", "score": 0.9}
    ])
    artifact_lookup = MagicMock(return_value=None)
    monkeypatch.setattr(pipeline, "resolve_artifact_for_chat", artifact_lookup)
    monkeypatch.setattr(pipeline, "resolve_visual_for_query", lambda *args: None)
    monkeypatch.setattr(pipeline, "log_event", MagicMock())
    prompts = []

    def mock_llm(system_prompt, user_prompt):
        prompts.append(user_prompt)
        yield CLARIFY_ANSWER if EVIDENCE_HINT in user_prompt else BASELINE_ANSWER

    monkeypatch.setattr(pipeline, "stream_llm", mock_llm)
    clients = []
    MemoryCache.clear()

    def install_provider(intent="tuition", confidence=0.95, sufficiency="sufficient", clarification=0.1, failure=None):
        requests = []

        def handler(request):
            body = json.loads(request.content)
            requests.append(body)
            if failure == "timeout":
                raise httpx.ReadTimeout("Synthetic timeout")
            if isinstance(failure, int):
                return httpx.Response(failure, json={"error": "Synthetic provider failure"})
            if failure == "malformed":
                return httpx.Response(200, json={"answers": {"unexpected": {"type": "choice", "choice": "invalid"}}})
            answers = {}
            for qid in body["questions"]:
                if qid == "intent":
                    answers[qid] = {"type": "choice", "choice": intent, "confidence": confidence}
                elif qid == "sufficiency":
                    answers[qid] = {"type": "choice", "choice": sufficiency, "confidence": confidence}
                elif qid == "needs_clarification":
                    answers[qid] = {"type": "noul", "noul": clarification}
            return httpx.Response(200, json={"answers": answers, "model": "jev-latest"})

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        clients.append(client)
        service = DecisionService(provider=TypeSafeJevProvider(api_key="test-key", client=client), mode="assist")
        monkeypatch.setattr(pipeline, "decision_service", service)
        return service, requests

    yield install_provider, prompts, artifact_lookup
    for client in clients:
        asyncio.run(client.aclose())
    MemoryCache.clear()


def run_chat(use_cache=False):
    events = [json.loads(line) for line in pipeline.stream_answer(QUESTION, use_cache=use_cache)]
    assert events[0]["type"] == "start"
    assert events[-1]["type"] == "done"
    assert not any(e["type"] == "error" for e in events)
    assert [e["sequence"] for e in events] == list(range(1, len(events) + 1))
    text = "".join(e["payload"]["token"] for e in events if e["type"] == "token")
    assert text
    return events, text


def test_assist_applies_trusted_intent_to_chat_routing_and_trace(assist_chat):
    install, prompts, artifact_lookup = assist_chat
    service, requests = install()
    events, text = run_chat()
    assert artifact_lookup.call_args.args[0] == "tuition"
    progress = next(e for e in events if e["type"] == "progress")
    assert progress["payload"]["trace"][0]["detail"] == "Ý định: tuition"
    assert len(requests) == 2
    assert service.get_metrics_summary()["success_count"] == 2
    assert text == BASELINE_ANSWER


def test_assist_clear_intent_skips_intent_call_but_checks_evidence(assist_chat, monkeypatch):
    install, _, artifact_lookup = assist_chat
    _, requests = install()
    monkeypatch.setattr(pipeline, "classify_intent", lambda q: "tuition")
    run_chat()
    assert artifact_lookup.call_args.args[0] == "tuition"
    assert len(requests) == 1
    assert "sufficiency" in requests[0]["questions"]
    assert "intent" not in requests[0]["questions"]


def test_assist_guardrail_response_never_calls_provider(assist_chat, monkeypatch):
    install, prompts, artifact_lookup = assist_chat
    _, requests = install()
    monkeypatch.setattr(pipeline, "check_intent_guardrail", lambda *args, **kwargs: {
        "is_handled": True, "answer": BASELINE_ANSWER, "sources": [], "trace": []
    })
    _, text = run_chat()
    assert text == BASELINE_ANSWER
    assert requests == []
    assert prompts == []
    artifact_lookup.assert_not_called()


@pytest.mark.parametrize("sufficiency", ["insufficient", "conflicting"])
def test_assist_uses_evidence_decision_to_request_clarification(assist_chat, sufficiency):
    install, prompts, _ = assist_chat
    install(sufficiency=sufficiency, clarification=0.9)
    _, text = run_chat()
    assert EVIDENCE_HINT in prompts[0]
    assert text == CLARIFY_ANSWER


@pytest.mark.parametrize("sufficiency", ["sufficient", "partial"])
def test_assist_does_not_add_clarification_hint_for_other_verdicts(assist_chat, sufficiency):
    install, prompts, _ = assist_chat
    install(sufficiency=sufficiency, clarification=0.9)
    _, text = run_chat()
    assert EVIDENCE_HINT not in prompts[0]
    assert text == BASELINE_ANSWER


def test_assist_low_confidence_keeps_baseline_routing_and_prompt(assist_chat):
    install, prompts, artifact_lookup = assist_chat
    service, _ = install(confidence=0.79, sufficiency="insufficient", clarification=0.9)
    _, text = run_chat()
    assert artifact_lookup.call_args.args[0] == "general"
    assert EVIDENCE_HINT not in prompts[0]
    assert text == BASELINE_ANSWER
    assert service.get_metrics_summary()["fallback_count"] == 2


def test_assist_does_not_request_clarification_below_noul_threshold(assist_chat):
    install, prompts, _ = assist_chat
    install(sufficiency="insufficient", clarification=0.69)
    _, text = run_chat()
    assert EVIDENCE_HINT not in prompts[0]
    assert text == BASELINE_ANSWER


@pytest.mark.parametrize("failure", ["timeout", 401, 402, 429, 500, "malformed"])
def test_assist_provider_failure_preserves_chat_and_stream(assist_chat, failure):
    install, prompts, artifact_lookup = assist_chat
    service, requests = install(failure=failure)
    _, text = run_chat()
    assert text == BASELINE_ANSWER
    assert EVIDENCE_HINT not in prompts[0]
    assert artifact_lookup.call_args.args[0] == "general"
    assert requests
    assert service.get_metrics_summary()["fallback_count"] >= 1


def test_assist_cache_isolated_from_shadow_and_reusable_without_extra_calls(assist_chat, monkeypatch):
    install, prompts, _ = assist_chat
    service, requests = install(sufficiency="insufficient", clarification=0.9)
    monkeypatch.setenv("JEV_MODE", "shadow")
    CacheManager.save_response(QUESTION, {"answer": BASELINE_ANSWER})
    baseline_key = compute_cache_key(QUESTION)
    monkeypatch.setenv("JEV_MODE", "assist")
    assert compute_cache_key(QUESTION) != baseline_key
    first_events, first_text = run_chat(use_cache=True)
    assert first_events[-1]["payload"]["cached"] is False
    assert first_text == CLARIFY_ANSWER
    count = len(requests)
    second_events, second_text = run_chat(use_cache=True)
    assert second_events[-1]["payload"]["cached"] is True
    assert second_text == first_text
    assert len(requests) == count
    monkeypatch.setenv("JEV_MODE", "shadow")
    assert CacheManager.get_cached_response(QUESTION)["answer"] == BASELINE_ANSWER


def test_assist_cache_config_changes_invalidate_only_assist_namespace(assist_chat, monkeypatch):
    baseline_payload = json.dumps({"question": normalize_text(QUESTION), "history": [], "kb_version": settings.KB_VERSION,
                                   "rag_version": settings.RAG_VERSION, "model": settings.OPENROUTER_MODEL},
                                  ensure_ascii=False, sort_keys=True)
    legacy_key = hashlib.sha256(baseline_payload.encode("utf-8")).hexdigest()
    monkeypatch.setenv("JEV_MODE", "off")
    assert compute_cache_key(QUESTION) == legacy_key
    monkeypatch.setenv("JEV_MODE", "shadow")
    assert compute_cache_key(QUESTION) == legacy_key
    monkeypatch.setenv("JEV_MODE", "assist")
    assist_key = compute_cache_key(QUESTION)
    assert assist_key != legacy_key
    monkeypatch.setenv("JEV_CONFIDENCE_THRESHOLD", "0.90")
    assert compute_cache_key(QUESTION) != assist_key
    monkeypatch.setenv("JEV_CONFIDENCE_THRESHOLD", "0.80")
    monkeypatch.setenv("JEV_MODEL", "synthetic-other-model")
    assert compute_cache_key(QUESTION) != assist_key


def test_assist_application_telemetry_applied_and_not_needed(assist_chat, monkeypatch):
    """Kiểm tra telemetry mức pipeline:
    - Quyết định được áp dụng (decision_applied=True, apply_reason='intent_updated' / 'clarification_hint_injected')
    - Quyết định không cần áp dụng (decision_applied=False, apply_reason='intent_clear_no_call_needed' / 'evidence_sufficient_no_override_needed')
    """
    install, _, _ = assist_chat
    recorded_telemetry = []
    real_log_app = pipeline.log_decision_application

    def spy_log_app(*args, **kwargs):
        res = real_log_app(*args, **kwargs)
        recorded_telemetry.append(res)
        return res

    monkeypatch.setattr(pipeline, "log_decision_application", spy_log_app)

    # 1. Ca quyết định được áp dụng (intent mơ hồ -> tuition, evidence insufficient -> hint injected)
    service, requests = install(intent="tuition", confidence=0.95, sufficiency="insufficient", clarification=0.9)
    run_chat()

    intent_applied = next((t for t in recorded_telemetry if t["decision_type"] == "intent"), None)
    assert intent_applied is not None
    assert intent_applied["api_called"] is True
    assert intent_applied["result_accepted"] is True
    assert intent_applied["decision_applied"] is True
    assert intent_applied["apply_reason"] == "intent_updated"
    assert intent_applied["selected_choice"] == "tuition"
    assert intent_applied["request_id"]

    ev_applied = next((t for t in recorded_telemetry if t["decision_type"] == "evidence_sufficiency"), None)
    assert ev_applied is not None
    assert ev_applied["api_called"] is True
    assert ev_applied["result_accepted"] is True
    assert ev_applied["decision_applied"] is True
    assert ev_applied["apply_reason"] == "clarification_hint_injected"

    # 2. Ca không cần áp dụng (intent rõ ràng -> không gọi, evidence sufficient -> không ghi đè)
    recorded_telemetry.clear()
    monkeypatch.setattr(pipeline, "classify_intent", lambda q: "tuition")
    install(intent="tuition", confidence=0.95, sufficiency="sufficient", clarification=0.1)
    run_chat()

    intent_skip = next((t for t in recorded_telemetry if t["decision_type"] == "intent"), None)
    assert intent_skip is not None
    assert intent_skip["api_called"] is False
    assert intent_skip["result_accepted"] is False
    assert intent_skip["decision_applied"] is False
    assert intent_skip["apply_reason"] == "intent_clear_no_call_needed"

    ev_sufficient = next((t for t in recorded_telemetry if t["decision_type"] == "evidence_sufficiency"), None)
    assert ev_sufficient is not None
    assert ev_sufficient["api_called"] is True
    assert ev_sufficient["result_accepted"] is True
    assert ev_sufficient["decision_applied"] is False
    assert ev_sufficient["apply_reason"] == "evidence_sufficient_no_override_needed"


def test_assist_application_telemetry_low_confidence_and_timeout(assist_chat, monkeypatch):
    """Kiểm tra telemetry mức pipeline:
    - Độ tin cậy thấp (< 0.80) -> không áp dụng, apply_reason='confidence_below_threshold'
    - Timeout -> không áp dụng, apply_reason='timeout'
    """
    install, _, _ = assist_chat
    recorded_telemetry = []
    real_log_app = pipeline.log_decision_application

    def spy_log_app(*args, **kwargs):
        res = real_log_app(*args, **kwargs)
        recorded_telemetry.append(res)
        return res

    monkeypatch.setattr(pipeline, "log_decision_application", spy_log_app)

    # 1. Low confidence (< 0.80)
    install(confidence=0.40, sufficiency="partial")
    run_chat()

    intent_low = next((t for t in recorded_telemetry if t["decision_type"] == "intent"), None)
    assert intent_low is not None
    assert intent_low["api_called"] is True
    assert intent_low["decision_applied"] is False
    assert intent_low["apply_reason"] == "confidence_below_threshold"

    ev_low = next((t for t in recorded_telemetry if t["decision_type"] == "evidence_sufficiency"), None)
    assert ev_low is not None
    assert ev_low["api_called"] is True
    assert ev_low["decision_applied"] is False
    assert ev_low["apply_reason"] == "confidence_below_threshold"

    # 2. Timeout
    recorded_telemetry.clear()
    install(failure="timeout")
    run_chat()

    intent_to = next((t for t in recorded_telemetry if t["decision_type"] == "intent"), None)
    assert intent_to is not None
    assert intent_to["api_called"] is True
    assert intent_to["decision_applied"] is False
    assert intent_to["apply_reason"] == "timeout"


def test_assist_application_telemetry_provider_error_and_cache_hit(assist_chat, monkeypatch):
    """Kiểm tra telemetry mức pipeline:
    - Provider error (500) -> không áp dụng, fallback_reason thể hiện lỗi provider
    - Cache hit -> không gọi API Jev, apply_reason='cache_hit_bypassed'
    """
    install, _, _ = assist_chat
    recorded_telemetry = []
    real_log_app = pipeline.log_decision_application

    def spy_log_app(*args, **kwargs):
        res = real_log_app(*args, **kwargs)
        recorded_telemetry.append(res)
        return res

    monkeypatch.setattr(pipeline, "log_decision_application", spy_log_app)

    # 1. Provider error (500)
    install(failure=500)
    run_chat()

    intent_err = next((t for t in recorded_telemetry if t["decision_type"] == "intent"), None)
    assert intent_err is not None
    assert intent_err["api_called"] is True
    assert intent_err["result_accepted"] is False
    assert intent_err["decision_applied"] is False
    assert "error" in intent_err["apply_reason"].lower() or "fallback" in intent_err["apply_reason"].lower() or intent_err["apply_reason"] == "server_error"

    # 2. Cache hit
    recorded_telemetry.clear()
    install(intent="tuition", confidence=0.95)
    # Lần 1: cache miss
    run_chat(use_cache=True)
    recorded_telemetry.clear()

    # Lần 2: cache hit
    run_chat(use_cache=True)
    cache_tel = next((t for t in recorded_telemetry if t["apply_reason"] == "cache_hit_bypassed"), None)
    assert cache_tel is not None
    assert cache_tel["api_called"] is False
    assert cache_tel["result_accepted"] is False
    assert cache_tel["decision_applied"] is False


def test_assist_application_telemetry_circuit_open(assist_chat, monkeypatch):
    """Kiểm tra khi Circuit Breaker open:
    - Quyết định bị short-circuit bởi service guards
    - api_called = False (không phát sinh network call đến provider)
    - apply_reason = 'circuit_open'
    - decision_applied = False
    """
    install, _, _ = assist_chat
    recorded_telemetry = []
    real_log_app = pipeline.log_decision_application

    def spy_log_app(*args, **kwargs):
        res = real_log_app(*args, **kwargs)
        recorded_telemetry.append(res)
        return res

    monkeypatch.setattr(pipeline, "log_decision_application", spy_log_app)

    service, requests = install(intent="tuition", confidence=0.95)
    service.circuit_breaker.state = "open"
    service.circuit_breaker.last_state_change = time.monotonic()

    _, text = run_chat()
    assert text == BASELINE_ANSWER

    circuit_intent = next((t for t in recorded_telemetry if t["decision_type"] == "intent"), None)
    assert circuit_intent is not None
    assert circuit_intent["api_called"] is False
    assert circuit_intent["result_accepted"] is False
    assert circuit_intent["decision_applied"] is False
    assert circuit_intent["apply_reason"] == "circuit_open"


@pytest.mark.parametrize("decision_type", ["intent", "evidence_sufficiency"])
def test_assist_telemetry_pre_provider_budget_expiry(assist_chat, monkeypatch, decision_type):
    """An expired sync deadline must not be counted as an HTTP attempt."""
    from backend.app.decision_engine import service as service_module

    install, _, _ = assist_chat
    _, requests = install()
    recorded = []
    original_log = pipeline.log_decision_application
    original_run = service_module.run_coro_sync

    def expire_before_worker(coro, *args, **kwargs):
        # Deterministic fault injection: no sleep and no real transport.
        kwargs["deadline"] = time.monotonic() - 1.0
        return original_run(coro, *args, **kwargs)

    def capture(*args, **kwargs):
        payload = original_log(*args, **kwargs)
        recorded.append(payload)
        return payload

    if decision_type == "evidence_sufficiency":
        monkeypatch.setattr(pipeline, "classify_intent", lambda q: "tuition")
    monkeypatch.setattr(service_module, "run_coro_sync", expire_before_worker)
    monkeypatch.setattr(pipeline, "log_decision_application", capture)
    _, text = run_chat()
    event = next(item for item in recorded if item["decision_type"] == decision_type)
    assert requests == []
    assert event["api_called"] is False
    assert event["result_accepted"] is False
    assert event["decision_applied"] is False
    assert event["apply_reason"] == "budget_exhausted_before_call"
    assert text == BASELINE_ANSWER


def test_assist_telemetry_missing_key_does_not_count_http(assist_chat, monkeypatch):
    install, _, _ = assist_chat
    service, requests = install()
    service._provider._api_key = ""
    recorded = []
    original_log = pipeline.log_decision_application

    def capture(*args, **kwargs):
        payload = original_log(*args, **kwargs)
        recorded.append(payload)
        return payload

    monkeypatch.setattr(pipeline, "log_decision_application", capture)
    _, text = run_chat()
    assert requests == []
    assert all(item["api_called"] is False for item in recorded)
    assert all(item["decision_applied"] is False for item in recorded)
    assert any(item["apply_reason"] == "auth_error" for item in recorded)
    assert text == BASELINE_ANSWER


def test_assist_telemetry_concurrency_guard_does_not_count_http(assist_chat, monkeypatch):
    import threading

    install, _, _ = assist_chat
    service, requests = install()
    monkeypatch.setattr(service, "_concurrency_limiter", threading.BoundedSemaphore(0))
    recorded = []
    original_log = pipeline.log_decision_application

    def capture(*args, **kwargs):
        payload = original_log(*args, **kwargs)
        recorded.append(payload)
        return payload

    monkeypatch.setattr(pipeline, "log_decision_application", capture)
    _, text = run_chat()
    assert requests == []
    assert all(item["api_called"] is False for item in recorded)
    assert all(item["apply_reason"] == "concurrency_limit_exceeded" for item in recorded)
    assert text == BASELINE_ANSWER


def test_assist_telemetry_sync_timeout_after_http_attempt(assist_chat, monkeypatch):
    install, _, _ = assist_chat
    service, _ = install()
    requests = []
    recorded = []
    original_log = pipeline.log_decision_application

    async def delayed_handler(request):
        requests.append(request)
        await asyncio.sleep(0.5)
        return httpx.Response(500, json={"error": "Synthetic late response"})

    monkeypatch.setattr(service._provider._client, "_transport", httpx.MockTransport(delayed_handler))
    monkeypatch.setenv("JEV_TOTAL_BUDGET_MS", "100")

    def capture(*args, **kwargs):
        payload = original_log(*args, **kwargs)
        recorded.append(payload)
        return payload

    monkeypatch.setattr(pipeline, "log_decision_application", capture)
    _, text = run_chat()
    intent = next(item for item in recorded if item["decision_type"] == "intent")
    assert len(requests) == 1
    assert intent["api_called"] is True
    assert intent["apply_reason"] == "timeout"
    assert intent["decision_applied"] is False
    assert text == BASELINE_ANSWER


def test_assist_http_evidence_is_request_scoped_and_not_serialized(assist_chat):
    from backend.app.contracts.schema_registry import validate_contract
    from backend.app.decision_engine.providers.base import notify_api_call

    install, _, _ = assist_chat
    service, requests = install()

    async def concurrent_calls():
        return await asyncio.gather(
            service.decide_intent("Synthetic request with budget", "general", remaining_budget_ms=1000),
            service.decide_intent("Synthetic request without budget", "general", remaining_budget_ms=1),
        )

    called, skipped = asyncio.run(concurrent_calls())
    assert len(requests) == 1
    assert called._api_called is True
    assert skipped._api_called is False
    assert skipped._fallback_reason == "timeout"
    for result in (called, skipped):
        payload = result.model_dump()
        assert "_api_called" not in payload and "api_called" not in payload
        assert "_fallback_reason" not in payload
        validate_contract("huit.decision.decision-result", "1.0.0", payload)
    # The observer must be reset; a later unrelated call cannot reach a finished tracker.
    notify_api_call()
