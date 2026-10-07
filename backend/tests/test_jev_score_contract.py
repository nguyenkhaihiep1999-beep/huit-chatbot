"""Offline regressions for the TypeSafe Score wire contract and answer types."""
import asyncio
from copy import deepcopy
import json

import httpx
import jsonschema
from pydantic import ValidationError
import pytest

from backend.app.contracts.schema_registry import (
    get_schema_entry,
    schema_sha256,
    validate_contract,
)
from backend.app.decision_engine.contracts import DecisionRequest, QuestionDefinition
from backend.app.decision_engine.policies import (
    get_evidence_sufficiency_questions,
    get_intent_decision_questions,
)
from backend.app.decision_engine.providers.base import DecisionValidationError
from backend.app.decision_engine.providers.typesafe_jev import TypeSafeJevProvider
from backend.app.decision_engine.service import DecisionService


REQUEST_SCHEMA_ID = "huit.decision.decision-request"
REQUEST_VERSION = "2.0.0"


def score_request():
    return DecisionRequest(
        decision_type="custom",
        state="Synthetic urgency assessment; no personal data",
        questions={"urgency": QuestionDefinition(
            type="score", instructions="Rate urgency", criteria=["Calm", "Urgent"]
        )},
    )


def score_response():
    return {
        "model": "jev-latest",
        "answers": {"urgency": {
            "type": "score",
            "score": 0.8,
            "legend": {"0": "Calm", "1": "Urgent"},
            "probabilities": {"0": 0.2, "1": 0.8},
            "confidence": 0.8,
        }},
        "usage": {"input_tokens": 30, "output_tokens": 12},
    }


def test_score_round_trip_matches_canonical_and_wire_contracts():
    request = score_request()
    validate_contract(REQUEST_SCHEMA_ID, REQUEST_VERSION, request.model_dump())
    assert DecisionRequest.model_json_schema()["x-contract-version"] == REQUEST_VERSION
    called_payloads = []

    def handler(http_request):
        called_payloads.append(json.loads(http_request.content))
        return httpx.Response(200, json=score_response())

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await TypeSafeJevProvider(api_key="test-key", client=client).decide(request)

    result = asyncio.run(run())
    assert called_payloads == [{
        "state": request.state,
        "model": "jev-latest",
        "questions": {"urgency": {
            "type": "score", "instructions": "Rate urgency", "criteria": ["Calm", "Urgent"]
        }},
    }]
    assert result.status == "success"
    assert result.decisions["urgency"].score == 0.8
    assert result.decisions["urgency"].probabilities == {"0": 0.2, "1": 0.8}
    validate_contract("huit.decision.decision-result", "1.0.0", result.model_dump())


@pytest.mark.parametrize("level_count", [2, 10])
def test_score_criteria_boundaries_and_fractional_scores(level_count):
    levels = [f"Level {i}" for i in range(level_count)]
    request = score_request()
    request.questions["urgency"] = QuestionDefinition(type="score", criteria=levels)
    validate_contract(REQUEST_SCHEMA_ID, REQUEST_VERSION, request.model_dump())
    answer = score_response()
    answer["answers"]["urgency"].update({
        "score": (level_count - 1) / 2,
        "legend": {str(i): label for i, label in enumerate(levels)},
        "probabilities": {str(i): 1 / level_count for i in range(level_count)},
    })
    result = TypeSafeJevProvider(api_key="test-key")._parse_response(answer, request, 1.0)
    assert result.decisions["urgency"].score == (level_count - 1) / 2


@pytest.mark.parametrize("criteria", [
    None, {}, {"0": "Calm", "1": "Urgent"}, [], ["Calm"], ["Level"] * 11,
    "Calm,Urgent", ["Calm", True], ["Calm", 1], ["Calm", None],
    ["Calm", {"description": "Urgent"}], ["Calm", ["Urgent"]], ["Calm", "x" * 501],
])
def test_invalid_score_criteria_rejected_by_model_and_canonical_schema(criteria):
    question = {"type": "score", "criteria": criteria}
    payload = {"decision_type": "custom", "state": "synthetic", "questions": {"q": question}}
    with pytest.raises(ValidationError):
        DecisionRequest.model_validate(payload)
    with pytest.raises(jsonschema.ValidationError):
        validate_contract(REQUEST_SCHEMA_ID, REQUEST_VERSION, payload)


def test_missing_score_criteria_rejected_by_both_contracts():
    payload = {"decision_type": "custom", "state": "synthetic", "questions": {"q": {"type": "score"}}}
    with pytest.raises(ValidationError):
        DecisionRequest.model_validate(payload)
    with pytest.raises(jsonschema.ValidationError):
        validate_contract(REQUEST_SCHEMA_ID, REQUEST_VERSION, payload)


@pytest.mark.parametrize("question_type", ["choice", "noul"])
@pytest.mark.parametrize("criteria", [["Calm", "Urgent"], "invalid", {"true": 1}, {"true": "x" * 501}])
def test_non_score_criteria_remain_bounded_objects(question_type, criteria):
    question = {"type": question_type, "criteria": criteria}
    payload = {"decision_type": "custom", "state": "synthetic", "questions": {"q": question}}
    with pytest.raises(ValidationError):
        DecisionRequest.model_validate(payload)
    with pytest.raises(jsonschema.ValidationError):
        validate_contract(REQUEST_SCHEMA_ID, REQUEST_VERSION, payload)


@pytest.mark.parametrize("questions", [get_intent_decision_questions(), get_evidence_sufficiency_questions()])
def test_current_workflows_still_match_both_request_versions(questions):
    request = DecisionRequest(decision_type="custom", state="synthetic", questions=questions)
    for version in ("1.0.0", REQUEST_VERSION):
        validate_contract(REQUEST_SCHEMA_ID, version, request.model_dump())


def test_legacy_schema_remains_immutable_and_new_version_is_active():
    legacy = get_schema_entry(REQUEST_SCHEMA_ID, "1.0.0")
    assert legacy["status"] == "deprecated"
    assert schema_sha256(REQUEST_SCHEMA_ID, "1.0.0") == "60604e8727f1518bff77f4a1427424025d047e9068723a4368b7f4709121f22d"
    assert get_schema_entry(REQUEST_SCHEMA_ID, REQUEST_VERSION)["status"] == "active"


@pytest.mark.parametrize("field, value", [
    ("legend", None), ("legend", []), ("legend", {}),
    ("legend", {"0": "Calm", "1": "Wrong label"}),
    ("legend", {"0": "Calm", "1": "Urgent", "2": "Extra"}),
    ("legend", {0: "Calm", 1: "Urgent"}),
    ("probabilities", None), ("probabilities", []), ("probabilities", {}),
    ("probabilities", {"1": 1.0}),
    ("probabilities", {"Calm": 0.2, "Urgent": 0.8}),
    ("probabilities", {"00": 0.2, "1": 0.8}),
    ("probabilities", {"0": 0.2, "2": 0.8}),
    ("probabilities", {0: 0.2, 1: 0.8}),
    ("probabilities", {"0": True, "1": 0.8}),
    ("probabilities", {"0": "0.2", "1": 0.8}),
    ("probabilities", {"0": float("nan"), "1": 0.8}),
    ("probabilities", {"0": float("inf"), "1": 0.8}),
    ("probabilities", {"0": -0.2, "1": 1.2}),
    ("probabilities", {"0": 0.2, "1": 0.2}),
    ("score", -0.01), ("score", 1.01), ("score", True), ("score", "0.8"),
])
def test_invalid_score_response_rejected(field, value):
    raw = score_response()
    raw["answers"]["urgency"][field] = value
    expected_error = "'probabilities'|xác suất" if field == "probabilities" else f"'{field}'"
    with pytest.raises(DecisionValidationError, match=expected_error):
        TypeSafeJevProvider(api_key="test-key")._parse_response(raw, score_request(), 1.0)


@pytest.mark.parametrize("field", ["legend", "probabilities"])
def test_missing_score_response_fields_rejected(field):
    raw = score_response()
    del raw["answers"]["urgency"][field]
    with pytest.raises(DecisionValidationError, match=f"'{field}'"):
        TypeSafeJevProvider(api_key="test-key")._parse_response(raw, score_request(), 1.0)


@pytest.mark.parametrize("requested_type, received_type", [
    (requested, received)
    for requested in ("choice", "score", "noul")
    for received in ("choice", "score", "noul", "unknown", None, True, {})
    if received != requested
])
def test_explicit_answer_type_must_match_question(requested_type, received_type):
    request = DecisionRequest(decision_type="custom", state="synthetic", questions={"q": QuestionDefinition(
        type=requested_type, criteria=["Calm", "Urgent"] if requested_type == "score" else None
    )})
    answer = {"type": received_type, "confidence": 0.8}
    if requested_type == "choice":
        answer["choice"] = "Calm"
    elif requested_type == "score":
        answer.update(deepcopy(score_response()["answers"]["urgency"]))
        answer["type"] = received_type
    else:
        answer["noul"] = 0.25
    with pytest.raises(DecisionValidationError, match="'type'"):
        TypeSafeJevProvider(api_key="test-key")._parse_response({"answers": {"q": answer}}, request, 1.0)


@pytest.mark.parametrize("requested_type", ["choice", "score", "noul"])
def test_missing_answer_type_rejected(requested_type):
    request = DecisionRequest(decision_type="custom", state="synthetic", questions={"q": QuestionDefinition(
        type=requested_type, criteria=["Calm", "Urgent"] if requested_type == "score" else None
    )})
    with pytest.raises(DecisionValidationError, match="'type'"):
        TypeSafeJevProvider(api_key="test-key")._parse_response({"answers": {"q": {}}}, request, 1.0)


@pytest.mark.parametrize("mode", ["shadow", "assist"])
def test_invalid_answer_type_falls_back_without_retry(mode, monkeypatch):
    # Isolate telemetry too: this test must never touch a real MongoDB instance.
    monkeypatch.setattr(DecisionService, "_record_metric", lambda *args, **kwargs: None)
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json={"answers": {"q": {"type": "choice", "noul": 0.25}}})

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            service = DecisionService(provider=TypeSafeJevProvider(api_key="test-key", client=client), mode=mode)
            request = DecisionRequest(decision_type="custom", state="synthetic", questions={"q": QuestionDefinition(type="noul")})
            return await service.execute_decision(request)

    result = asyncio.run(run())
    assert result.status == "fallback"
    assert result.decisions == {}
    assert len(calls) == 1
