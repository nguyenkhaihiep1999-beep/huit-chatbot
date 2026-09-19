"""Release-blocking checks for the canonical JSON Schema architecture."""
from __future__ import annotations

import importlib
import json
import re
from typing import get_args
import pytest
from pydantic import ValidationError

from backend.app.api.routes.auth import SessionResponse
from backend.app.api.schemas.chat import ChatRequest, MessageItem
from backend.app.api.schemas.streaming_v2 import CANONICAL_EVENT_TYPES, StreamEventEnvelope
from backend.app.contracts.schema_registry import iter_schema_entries, load_schema, schema_sha256
from backend.app.data_access.operation_gateway import MutationPolicy


def test_registry_entries_are_unique_loadable_and_checksummed():
    entries = list(iter_schema_entries())
    identities = {(entry["schema_id"], entry["version"]) for entry in entries}
    assert len(entries) == len(identities)
    assert len(entries) >= 6
    for entry in entries:
        assert load_schema(entry["schema_id"], entry["version"])
        assert re.fullmatch(r"[a-f0-9]{64}", schema_sha256(entry["schema_id"], entry["version"]))


def test_session_response_pydantic_shape_matches_canonical_contract():
    canonical = load_schema("huit.api.session-bootstrap-response", "1.0.0")
    generated = SessionResponse.model_json_schema()
    assert generated["x-contract-id"] == "huit.api.session-bootstrap-response"
    assert generated["x-contract-version"] == "1.0.0"
    assert set(generated["properties"]) == set(canonical["properties"])
    assert set(generated["required"]) == set(canonical["required"])
    assert generated["properties"]["ttl_seconds"]["minimum"] == canonical["properties"]["ttl_seconds"]["minimum"]
    assert generated["properties"]["ttl_seconds"]["maximum"] == canonical["properties"]["ttl_seconds"]["maximum"]


def test_chat_request_pydantic_shape_matches_canonical_contract():
    canonical = load_schema("huit.api.chat-request", "1.0.0")
    generated = ChatRequest.model_json_schema()
    assert generated["x-contract-id"] == "huit.api.chat-request"
    assert generated["x-contract-version"] == "1.0.0"
    assert set(generated["properties"]) == set(canonical["properties"])
    assert set(generated["required"]) == set(canonical["required"])
    assert set(MessageItem.model_json_schema()["properties"]["role"]["enum"]) == {"user", "assistant"}
    with pytest.raises(ValidationError):
        ChatRequest(question="Học phí?", history=None)


def test_stream_and_gateway_enums_are_covered_by_canonical_schemas():
    stream = load_schema("huit.stream.chat-event", "2.0.0")
    assert set(stream["properties"]["type"]["enum"]) == CANONICAL_EVENT_TYPES
    generated_stream = StreamEventEnvelope.model_json_schema()
    assert generated_stream["x-contract-id"] == "huit.stream.chat-event"
    assert generated_stream["x-contract-version"] == "2.0.0"

    audit = load_schema("huit.mongo.operation-audit", "1.1.0")
    allowed = set(audit["$jsonSchema"]["properties"]["mutation_policy"]["enum"])
    assert set(get_args(MutationPolicy)) <= allowed


def test_migrations_consume_registry_instead_of_duplicating_operation_audit_schema():
    migration_018 = importlib.import_module("scripts.migrations.018_phase6_schema_sync_and_validators")
    assert migration_018.OPERATION_AUDIT_VALIDATOR == load_schema("huit.mongo.operation-audit", "1.1.0")

    migration_022 = importlib.import_module("scripts.migrations.022_backup_json_schema_registry")
    documents = migration_022.build_registry_documents()
    assert len(documents) == len(list(iter_schema_entries()))
    for document in documents:
        assert document["schema_document"] == load_schema(document["schema_id"], document["schema_version"])
        assert document["sha256"] == schema_sha256(document["schema_id"], document["schema_version"])
        json.dumps(document["schema_document"], ensure_ascii=False)
