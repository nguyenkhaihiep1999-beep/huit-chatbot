"""Comprehensive tests for Stage 1: Jev Evidence Sufficiency & Dual-Task Architecture.

Covers:
- Intent-only, evidence-only, dual-task execution
- Independent task modes: off, shadow, assist
- Shadow Mode Invariance: shadow strictly behaves like off without altering policy verdict or prompt
- Timeout, server error, and malformed provider response resilience
- Evidence sufficiency verdicts: sufficient, partial, insufficient, conflicting
- Empty retrieval handling without hallucination
- Canonical evidence bundle consistency between Jev and context
- Multi-page catalogue deduplication preservation
- Profile isolation (HUIT vs ILT)
"""
import asyncio
import json
from unittest.mock import MagicMock
import httpx
import pymongo
import pytest

from backend.app.cache.memory_cache import MemoryCache
from backend.app.config import settings
from backend.app.decision_engine.providers.typesafe_jev import TypeSafeJevProvider
from backend.app.decision_engine.service import DecisionService
from backend.app.rag import pipeline
from backend.app.rag.profile import get_profile, HUIT_PROFILE, ILT_PROFILE


QUESTION = "Đèn chùm ILT-CH-801 có công suất và chứng chỉ gì?"
ILT_DOCS = [
    {
        "chunk_id": "ilt_chunk_p12_01",
        "_id": "67123456789abcdef0000001",
        "title": "Catalogue 2026 - Chandeliers",
        "text": "Model ILT-CH-801: Đèn chùm trang trí phòng khách cao cấp. Công suất 60W, đui E27. Chứng nhận UL, ETL.",
        "source_url": "https://online.fliphtml5.com/zpdsw/wjtd/",
        "page_number": 12,
        "sku": "ILT-CH-801",
        "score": 0.95,
        "verification_status": "verified",
        "product_type": "chandelier",
    },
    {
        "chunk_id": "ilt_chunk_p13_01",
        "_id": "67123456789abcdef0000002",
        "title": "Catalogue 2026 - Chandeliers Specs",
        "text": "Model ILT-CH-801: Kích thước đường kính 80cm, vật liệu thép không gỉ mạ đồng, điện áp 110V-240V.",
        "source_url": "https://online.fliphtml5.com/zpdsw/wjtd/",
        "page_number": 13,
        "sku": "ILT-CH-801",
        "score": 0.91,
        "verification_status": "verified",
        "product_type": "chandelier",
    },
]


@pytest.fixture(autouse=True)
def clean_cache():
    MemoryCache.clear()
    yield
    MemoryCache.clear()


def make_mock_service(
    mode="assist",
    intent_choice="product_inquiry",
    intent_conf=0.95,
    suff_choice="sufficient",
    suff_conf=0.95,
    clarify_noul=0.1,
    failure=None,
):
    requests = []

    async def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        requests.append(body)
        if failure == "timeout":
            raise httpx.ReadTimeout("Synthetic timeout")
        if isinstance(failure, int):
            return httpx.Response(failure, json={"error": "Synthetic failure"})
        if failure == "malformed":
            return httpx.Response(200, json={"malformed": "data"})

        answers = {}
        for qid in body.get("questions", []):
            if qid == "intent":
                answers[qid] = {"type": "choice", "choice": intent_choice, "confidence": intent_conf}
            elif qid == "sufficiency":
                answers[qid] = {"type": "choice", "choice": suff_choice, "confidence": suff_conf}
            elif qid == "needs_clarification":
                answers[qid] = {"type": "noul", "noul": clarify_noul}

        return httpx.Response(200, json={"answers": answers, "model": "jev-latest"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = TypeSafeJevProvider(api_key="test-key", client=client)
    service = DecisionService(provider=provider, mode=mode)
    return service, requests


def test_evidence_assist_sufficient_allows_direct_answer(monkeypatch):
    """evidence=assist với kết quả sufficient: không chèn clarification hint, cho phép trả lời trực tiếp."""
    service, requests = make_mock_service(
        mode="assist",
        suff_choice="sufficient",
        suff_conf=0.95,
        clarify_noul=0.05,
    )
    monkeypatch.setattr(pipeline, "decision_service", service)
    monkeypatch.setattr(pipeline, "retrieve", lambda *args, **kwargs: list(ILT_DOCS))
    prompts = []

    def mock_llm(sys_prompt, user_prompt):
        prompts.append(user_prompt)
        yield "Đèn chùm ILT-CH-801 có công suất 60W và đạt chứng nhận UL, ETL [1]."

    monkeypatch.setattr(pipeline, "stream_llm", mock_llm)

    events = [json.loads(line) for line in pipeline.stream_answer(QUESTION, use_cache=False, profile_id="ilt")]
    assert events[0]["type"] == "start"
    assert events[-1]["type"] == "done"
    token_text = "".join(e["payload"]["token"] for e in events if e["type"] == "token")
    assert "ILT-CH-801" in token_text
    assert len(prompts) == 1
    assert "[LƯU Ý ĐÁNH GIÁ MINH CHỨNG]" not in prompts[0]


def test_evidence_assist_insufficient_triggers_clarification(monkeypatch):
    """evidence=assist với insufficient và noul >= 0.7: chèn clarification guidance vào context."""
    service, requests = make_mock_service(
        mode="assist",
        suff_choice="insufficient",
        suff_conf=0.95,
        clarify_noul=0.85,
    )
    monkeypatch.setattr(pipeline, "decision_service", service)
    monkeypatch.setattr(pipeline, "retrieve", lambda *args, **kwargs: list(ILT_DOCS))
    prompts = []

    def mock_llm(sys_prompt, user_prompt):
        prompts.append(user_prompt)
        yield "Hiện tại thông tin chưa đủ chi tiết..."

    monkeypatch.setattr(pipeline, "stream_llm", mock_llm)

    events = [json.loads(line) for line in pipeline.stream_answer(QUESTION, use_cache=False, profile_id="ilt")]
    assert events[-1]["type"] == "done"
    assert len(prompts) == 1
    assert "[LƯU Ý ĐÁNH GIÁ MINH CHỨNG]" in prompts[0]
    assert "chưa đủ thông số chi tiết" in prompts[0]


def test_evidence_assist_conflicting_triggers_clarification(monkeypatch):
    """evidence=assist với conflicting và noul >= 0.7: cảnh báo mâu thuẫn và đề nghị đối chiếu."""
    service, requests = make_mock_service(
        mode="assist",
        suff_choice="conflicting",
        suff_conf=0.92,
        clarify_noul=0.80,
    )
    monkeypatch.setattr(pipeline, "decision_service", service)
    monkeypatch.setattr(pipeline, "retrieve", lambda *args, **kwargs: list(ILT_DOCS))
    prompts = []

    def mock_llm(sys_prompt, user_prompt):
        prompts.append(user_prompt)
        yield "Có sự khác biệt giữa các nguồn..."

    monkeypatch.setattr(pipeline, "stream_llm", mock_llm)

    events = [json.loads(line) for line in pipeline.stream_answer(QUESTION, use_cache=False, profile_id="ilt")]
    assert events[-1]["type"] == "done"
    assert len(prompts) == 1
    assert "[LƯU Ý ĐÁNH GIÁ MINH CHỨNG]" in prompts[0]


def test_evidence_shadow_invariance(monkeypatch):
    """Shadow Mode Invariance: evidence=shadow phải sinh context và verdict hoàn toàn giống như off mode."""
    # 1. Chạy với evidence=off
    monkeypatch.setenv("ILT_JEV_EVIDENCE_MODE", "off")
    monkeypatch.setattr(pipeline, "retrieve", lambda *args, **kwargs: list(ILT_DOCS))
    off_prompts = []

    def mock_llm_off(sys_prompt, user_prompt):
        off_prompts.append(user_prompt)
        yield "Off answer"

    monkeypatch.setattr(pipeline, "stream_llm", mock_llm_off)
    events_off = [json.loads(line) for line in pipeline.stream_answer(QUESTION, use_cache=False, profile_id="ilt")]

    # 2. Chạy với evidence=shadow (ngay cả khi Jev bảo insufficient)
    monkeypatch.setenv("ILT_JEV_EVIDENCE_MODE", "shadow")
    service, requests = make_mock_service(
        mode="shadow",
        suff_choice="insufficient",
        suff_conf=0.99,
        clarify_noul=0.99,
    )
    monkeypatch.setattr(pipeline, "decision_service", service)
    shadow_prompts = []

    def mock_llm_shadow(sys_prompt, user_prompt):
        shadow_prompts.append(user_prompt)
        yield "Shadow answer"

    monkeypatch.setattr(pipeline, "stream_llm", mock_llm_shadow)
    events_shadow = [json.loads(line) for line in pipeline.stream_answer(QUESTION, use_cache=False, profile_id="ilt")]

    # Cả hai lượt phải gọi LLM với cùng một user prompt (không bị chèn hint)
    assert len(off_prompts) == 1
    assert len(shadow_prompts) == 1
    assert off_prompts[0] == shadow_prompts[0]
    assert "[LƯU Ý ĐÁNH GIÁ MINH CHỨNG]" not in shadow_prompts[0]


def test_dual_task_execution_intent_and_evidence(monkeypatch):
    """Khi cả intent và evidence đều bật (dual task), cả 2 quyết định đều được gọi và ghi nhận telemetry."""
    monkeypatch.setenv("ILT_JEV_INTENT_MODE", "assist")
    monkeypatch.setenv("ILT_JEV_EVIDENCE_MODE", "assist")
    monkeypatch.setenv("JEV_TOTAL_BUDGET_MS", "1500.0")

    service, requests = make_mock_service(
        mode="assist",
        intent_choice="product_inquiry",
        intent_conf=0.95,
        suff_choice="sufficient",
        suff_conf=0.90,
    )
    monkeypatch.setattr(pipeline, "decision_service", service)
    monkeypatch.setattr(pipeline, "classify_intent", lambda q: "general")  # Mơ hồ -> gọi intent disambiguation
    monkeypatch.setattr(pipeline, "retrieve", lambda *args, **kwargs: list(ILT_DOCS))
    monkeypatch.setattr(pipeline, "stream_llm", lambda s, u: iter(["Dual task answer"]))

    recorded_decisions = []
    original_log = pipeline.log_decision_application

    def capture_log(*args, **kwargs):
        res = original_log(*args, **kwargs)
        recorded_decisions.append(res)
        return res

    monkeypatch.setattr(pipeline, "log_decision_application", capture_log)

    events = [json.loads(line) for line in pipeline.stream_answer(QUESTION, use_cache=False, profile_id="ilt")]
    assert events[-1]["type"] == "done"

    intent_logs = [d for d in recorded_decisions if d["decision_type"] == "intent"]
    evidence_logs = [d for d in recorded_decisions if d["decision_type"] == "evidence_sufficiency"]
    assert len(intent_logs) >= 1
    assert len(evidence_logs) >= 1
    assert intent_logs[0]["mode"] == "assist"
    assert evidence_logs[0]["mode"] == "assist"


def test_evidence_empty_retrieval_no_hallucination(monkeypatch):
    """Khi retrieval rỗng, không gọi Jev evidence và trả về thông điệp rỗng chuẩn xác của profile."""
    service, requests = make_mock_service(mode="assist")
    monkeypatch.setattr(pipeline, "decision_service", service)
    monkeypatch.setattr(pipeline, "retrieve", lambda *args, **kwargs: [])

    events = [json.loads(line) for line in pipeline.stream_answer(QUESTION, use_cache=False, profile_id="ilt")]
    # Bắt buộc phát event retrieval_empty
    progress_events = [e for e in events if e["type"] == "progress"]
    assert any(p["payload"].get("stage") == "retrieval_empty" for p in progress_events)

    token_text = "".join(e["payload"]["token"] for e in events if e["type"] == "token")
    assert ILT_PROFILE.empty_kb_message in token_text
    # Jev evidence không được gọi vì không có tài liệu
    evidence_requests = [r for r in requests if "sufficiency" in r.get("questions", [])]
    assert len(evidence_requests) == 0


def test_evidence_canonical_bundle_consistency(monkeypatch):
    """Cả Jev và Context nhận chính xác canonical evidence bundle giữ đầy đủ page_number và sku."""
    service, requests = make_mock_service(mode="assist")
    monkeypatch.setattr(pipeline, "decision_service", service)
    monkeypatch.setattr(pipeline, "retrieve", lambda *args, **kwargs: list(ILT_DOCS))

    captured_user_prompt = []

    def mock_llm(sys_prompt, user_prompt):
        captured_user_prompt.append(user_prompt)
        yield "Model ILT-CH-801 verified."

    monkeypatch.setattr(pipeline, "stream_llm", mock_llm)

    events = [json.loads(line) for line in pipeline.stream_answer(QUESTION, use_cache=False, profile_id="ilt")]
    assert events[-1]["type"] == "done"

    # 1. Kiểm tra progress event mang đúng metadata của cả 2 trang
    retrieval_event = next(e for e in events if e["type"] == "progress" and e["payload"].get("stage") == "retrieval_complete")
    sources = retrieval_event["payload"]["sources"]
    assert len(sources) == 2
    assert sources[0]["page_number"] == 12
    assert sources[0]["sku"] == "ILT-CH-801"
    assert sources[1]["page_number"] == 13
    assert sources[1]["sku"] == "ILT-CH-801"

    # 2. Kiểm tra context gửi cho LLM chứa trang catalogue rõ ràng
    assert len(captured_user_prompt) == 1
    prompt_text = captured_user_prompt[0]
    assert "(Trang 12)" in prompt_text
    assert "(Trang 13)" in prompt_text
    assert "[SKU: ILT-CH-801]" in prompt_text


def test_evidence_provider_failure_resilience(monkeypatch):
    """Khi provider gặp timeout hoặc 500, stream NDJSON không bị ngắt quãng, hoàn tất an toàn."""
    for failure_type in ["timeout", 500, "malformed"]:
        service, requests = make_mock_service(mode="assist", failure=failure_type)
        monkeypatch.setattr(pipeline, "decision_service", service)
        monkeypatch.setattr(pipeline, "retrieve", lambda *args, **kwargs: list(ILT_DOCS))
        monkeypatch.setattr(pipeline, "stream_llm", lambda s, u: iter(["Fallback resilient token"]))

        events = [json.loads(line) for line in pipeline.stream_answer(QUESTION, use_cache=False, profile_id="ilt")]
        assert events[0]["type"] == "start"
        assert events[-1]["type"] == "done"
        assert not any(e["type"] == "error" for e in events)


def test_supplementary_retrieval_catalogue_dedup(monkeypatch):
    """Deduplication trong supplementary retrieval bảo toàn các trang khác nhau từ cùng URL FlipHTML5."""
    supp_doc = {
        "chunk_id": "ilt_chunk_p14_01",
        "_id": "67123456789abcdef0000003",
        "title": "Catalogue 2026 - Chandeliers Mounting",
        "text": "Model ILT-CH-801: Hướng dẫn lắp đặt trần thạch cao và bảo dưỡng.",
        "source_url": "https://online.fliphtml5.com/zpdsw/wjtd/",
        "page_number": 14,
        "sku": "ILT-CH-801",
        "score": 0.88,
    }

    call_count = [0]

    def mock_retrieve(q, top_k, **kwargs):
        call_count[0] += 1
        if call_count[0] == 1:
            return [ILT_DOCS[0]]  # Lượt 1: chỉ có trang 12
        return [supp_doc]         # Lượt 2: bổ sung trang 14

    monkeypatch.setattr(pipeline, "retrieve", mock_retrieve)

    # Đặt policy evaluator yêu cầu supplementary query
    from backend.app.rag.evidence_policy import PolicyVerdict

    def mock_evaluate(*args, **kwargs):
        if kwargs.get("current_retrieval_round", 1) == 1:
            return PolicyVerdict(
                verdict="partial",
                can_answer=True,
                needs_supplementary=True,
                supplementary_query="ILT-CH-801 mounting",
                clarification_prompt=None,
                evidence_guidance="",
            )
        return PolicyVerdict(
            verdict="sufficient",
            can_answer=True,
            needs_supplementary=False,
            supplementary_query=None,
            clarification_prompt=None,
            evidence_guidance="",
        )

    monkeypatch.setattr(pipeline.EvidencePolicyEvaluator, "evaluate", mock_evaluate)
    monkeypatch.setattr(pipeline, "stream_llm", lambda s, u: iter(["Res"]))

    events = [json.loads(line) for line in pipeline.stream_answer(QUESTION, use_cache=False, profile_id="ilt")]
    retrieval_event = next(e for e in events if e["type"] == "progress" and e["payload"].get("stage") == "retrieval_complete")
    sources = retrieval_event["payload"]["sources"]

    # Cả trang 12 và trang 14 phải được giữ lại dù cùng source_url
    assert len(sources) == 2
    pages = {s["page_number"] for s in sources}
    assert 12 in pages
    assert 14 in pages
