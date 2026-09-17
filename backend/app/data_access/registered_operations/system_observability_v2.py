"""Registered read operations for health and administrator observability (v2.0.0)."""
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Union

from pydantic import BaseModel, ConfigDict, Field

from backend.app.data_access.operation_gateway import OperationSpec, register_operation


class DatabaseSnapshotParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    include_job_counts: bool = True


class DatabaseSnapshotOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    database: str
    kb_documents: int
    queued_jobs: int
    stuck_jobs: int


class AdminMetricsParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    recent_limit: int = Field(default=20, ge=1, le=50)


class RecentEventItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: Optional[str] = None
    intent: Optional[str] = None
    created_at: Optional[Union[datetime, str]] = None
    question_hash: Optional[str] = None
    elapsed_ms: Optional[float] = None
    model: Optional[str] = None
    cached: Optional[bool] = None
    fallback: Optional[bool] = None
    source_count: Optional[int] = None


class AdminMetricsOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    total_events: int
    total_cached_queries: int
    total_kb_documents: int
    recent_events: List[RecentEventItem] = Field(default_factory=list)


def _database_snapshot(ctx, params: DatabaseSnapshotParams):
    ctx.ping()
    jobs = ctx.collection("jobs")
    kb = ctx.collection("huit_kb")
    now = datetime.now(timezone.utc)
    result = {
        "database": ctx.database_name,
        "kb_documents": kb.count_documents({}),
        "queued_jobs": 0,
        "stuck_jobs": 0,
    }
    if params.include_job_counts:
        result["queued_jobs"] = jobs.count_documents({"status": "queued"})
        result["stuck_jobs"] = jobs.count_documents({
            "status": "processing",
            "$or": [
                {"lease_owner": None},
                {"lease_expires_at": {"$exists": False}},
                {"lease_expires_at": None},
                {"lease_expires_at": {"$lte": now}},
            ],
        })
    return result


def _admin_metrics(ctx, params: AdminMetricsParams):
    events = ctx.collection("rag_events")
    cache = ctx.collection("query_cache")
    kb = ctx.collection("huit_kb")
    recent = list(events.find({}, {"_id": 0}).sort("created_at", -1).limit(params.recent_limit))
    for event in recent:
        if hasattr(event.get("created_at"), "isoformat"):
            event["created_at"] = event["created_at"].isoformat()
    return {
        "total_events": events.count_documents({}),
        "total_cached_queries": cache.count_documents({}),
        "total_kb_documents": kb.count_documents({}),
        "recent_events": recent,
    }


DATABASE_SNAPSHOT = register_operation(OperationSpec(
    key="system.database_snapshot",
    version="2.0.0",
    operation_type="read",
    parameter_model=DatabaseSnapshotParams,
    output_model=DatabaseSnapshotOutput,
    allowed_collections=("jobs", "huit_kb"),
    mutation_policy="none",
    handler=_database_snapshot,
    max_results=1,
    max_output_bytes=8_000,
    max_time_ms=3_000,
    audit_policy="always",
    audit_fail_policy="fail_open",
    declared_checksum="07ca7b33a72955cb8e6d2470f7bd26657ea7bebe1c9ce5deb1ace28f70162143",
))

ADMIN_METRICS = register_operation(OperationSpec(
    key="admin.metrics",
    version="2.0.0",
    operation_type="read",
    parameter_model=AdminMetricsParams,
    output_model=AdminMetricsOutput,
    allowed_collections=("rag_events", "query_cache", "huit_kb"),
    mutation_policy="none",
    handler=_admin_metrics,
    max_results=1,
    max_output_bytes=256_000,
    max_time_ms=3_000,
    audit_policy="always",
    audit_fail_policy="fail_open",
    declared_checksum="867a7b87a7b59b4e46646e736ba509459077cb524e2eaa72f8a1479248d6c327",
))
