"""Verify the live smoke runner with mock HTTP only; never use real credentials."""
import asyncio
import json

import httpx
import pytest

from backend.app.decision_engine.providers.typesafe_jev import TypeSafeJevProvider
from scripts import smoke_test_jev_live as smoke


def test_missing_live_key_blocks_before_provider_creation(monkeypatch):
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)

    def unexpected_provider(**kwargs):
        raise AssertionError("No provider or HTTP call is allowed without a key")

    monkeypatch.setattr(smoke, "TypeSafeJevProvider", unexpected_provider)
    report = asyncio.run(smoke.run_live_smoke_test())
    assert report["smoke_status"] == "BLOCKED"
    assert report["contract_verified"] is False
    assert report["verified_question_types"] == {}


@pytest.mark.parametrize("fault", [None, "wrong_type", "missing_score_answer"])
def test_smoke_checks_all_three_primitives_offline(monkeypatch, capsys, fault):
    monkeypatch.setenv("TYPESAFE_API_KEY", "test-key")
    sent_types = []

    def handler(request):
        questions = json.loads(request.content)["questions"]
        answers = {}
        for q_id, question in questions.items():
            q_type = question["type"]
            sent_types.append(q_type)
            if q_type == "choice":
                options = list(question["criteria"])
                answers[q_id] = {
                    "type": "choice", "choice": options[0], "confidence": 1.0,
                    "probabilities": {option: float(i == 0) for i, option in enumerate(options)},
                }
            elif q_type == "noul":
                answers[q_id] = {"type": "noul", "noul": 0.25}
            else:
                levels = question["criteria"]
                answers[q_id] = {
                    "type": "score", "score": 0.8, "confidence": 0.8,
                    "legend": {str(i): label for i, label in enumerate(levels)},
                    "probabilities": {"0": 0.2, "1": 0.8},
                }
        if fault == "wrong_type":
            answers["needs_clarification"]["type"] = "choice"
        elif fault == "missing_score_answer":
            del answers["urgency_score"]
        return httpx.Response(200, json={
            "model": "jev-latest", "answers": answers,
            "usage": {"input_tokens": 40, "output_tokens": 20},
        })

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            monkeypatch.setattr(smoke, "TypeSafeJevProvider", lambda **kwargs: TypeSafeJevProvider(client=client, **kwargs))
            return await smoke.run_live_smoke_test()

    report = asyncio.run(run())
    assert sorted(sent_types) == ["choice", "noul", "score"]
    assert report["request_contract_version"] == "2.0.0"
    assert "test-key" not in json.dumps(report)
    assert "test-key" not in capsys.readouterr().out
    if fault is None:
        assert report["smoke_status"] == "PASSED"
        assert report["contract_verified"] is True
        assert report["verified_question_types"] == {
            "intent": "choice", "needs_clarification": "noul", "urgency_score": "score",
        }
    else:
        assert report["smoke_status"] == "FAILED"
        assert report["contract_verified"] is False
