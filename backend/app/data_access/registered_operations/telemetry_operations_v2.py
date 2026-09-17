"""Registered MongoDB operations for anonymized telemetry events (v2.0.0)."""
from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, ConfigDict, Field

from backend.app.data_access.operation_gateway import OperationSpec, register_operation

TELEMETRY_PROJECTION = {"_id": 0}


# Models
class TelemetryEventPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: str = Field(min_length=1, max_length=128)
    created_at: datetime
    question_hash: str = Field(min_length=32, max_length=64)
    question_length: int = Field(ge=0)
    intent: str = Field(max_length=64)
    cached: bool
    fallback: bool
    source_count: int = Field(ge=0)
    source_titles: List[str] = Field(default_factory=list)
    answer_length: int = Field(ge=0)
    elapsed_ms: float = Field(ge=0.0)
    timings: Dict[str, float] = Field(default_factory=dict)
    model: str = Field(max_length=128)
    kb_version: str = Field(max_length=64)
    rag_version: str = Field(max_length=64)
    error: Optional[str] = Field(default=None, max_length=500)


class AppendTelemetryEventParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    event: TelemetryEventPayload


class AppendTelemetryEventOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    inserted: bool
    request_id: str


class GetRecentTelemetryParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    limit: int = Field(default=50, ge=1, le=500)
    since: Optional[datetime] = None


class GetRecentTelemetryOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    events: List[TelemetryEventPayload]


class BatchAppendTelemetryParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    events: List[TelemetryEventPayload] = Field(min_length=1, max_length=100)


class BatchAppendTelemetryOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    inserted_count: int


# Handlers
def _handle_append_event(context, params: AppendTelemetryEventParams) -> AppendTelemetryEventOutput:
    col = context.collection("rag_events")
    doc = params.event.model_dump()
    col.insert_one(doc)
    return AppendTelemetryEventOutput(inserted=True, request_id=params.event.request_id)


def _handle_get_recent_events(context, params: GetRecentTelemetryParams) -> GetRecentTelemetryOutput:
    col = context.collection("rag_events")
    query = {}
    if params.since:
        query["created_at"] = {"$gte": params.since}

    raw_docs = list(
        col.find(query, TELEMETRY_PROJECTION)
        .sort("created_at", -1)
        .limit(params.limit)
    )
    items = []
    for doc in raw_docs:
        try:
            items.append(TelemetryEventPayload(**doc))
        except Exception:
            continue
    return GetRecentTelemetryOutput(events=items)


def _handle_batch_append_events(context, params: BatchAppendTelemetryParams) -> BatchAppendTelemetryOutput:
    col = context.collection("rag_events")
    docs = [ev.model_dump() for ev in params.events]
    res = col.insert_many(docs)
    count = len(getattr(res, "inserted_ids", []))
    return BatchAppendTelemetryOutput(inserted_count=count)


# Declarations with placeholder checksum
_SPECS = (
    OperationSpec(
        key="telemetry.append_event",
        version="2.0.0",
        operation_type="command",
        allowed_collections=("rag_events",),
        parameter_model=AppendTelemetryEventParams,
        output_model=AppendTelemetryEventOutput,
        handler=_handle_append_event,
        mutation_policy="insert_only",
        max_time_ms=3000,
        max_results=1,
        max_output_bytes=16_000,
        audit_policy="mutations_and_failures",
        audit_fail_policy="fail_open",
        declared_checksum="e6ec0278a2b6f4dc26003489d39d52b7d7b3dbb183fc00d6ba2364c43a460287",
    ),
    OperationSpec(
        key="telemetry.get_recent_events",
        version="2.0.0",
        operation_type="read",
        allowed_collections=("rag_events",),
        parameter_model=GetRecentTelemetryParams,
        output_model=GetRecentTelemetryOutput,
        handler=_handle_get_recent_events,
        mutation_policy="none",
        max_time_ms=5000,
        max_results=500,
        max_output_bytes=512_000,
        audit_policy="never",
        audit_fail_policy="fail_open",
        declared_checksum="af6755a05e645d58a8d6d1afc96deb4de8f1fcb7fd98087a17af837d9745dabb",
    ),
    OperationSpec(
        key="telemetry.batch_append_events",
        version="2.0.0",
        operation_type="command",
        allowed_collections=("rag_events",),
        parameter_model=BatchAppendTelemetryParams,
        output_model=BatchAppendTelemetryOutput,
        handler=_handle_batch_append_events,
        mutation_policy="insert_only",
        max_time_ms=5000,
        max_results=100,
        max_output_bytes=32_000,
        audit_policy="mutations_and_failures",
        audit_fail_policy="fail_open",
        declared_checksum="6979e1eb9404401d4907cd153dba128d11d0b0f1d184a9f7b2c77086ab9f95ce",
    ),
)

for spec in _SPECS:
    register_operation(spec)
