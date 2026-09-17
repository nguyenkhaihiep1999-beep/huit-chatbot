"""Registered read operations for health and administrator observability."""
from datetime import datetime, timezone

from pydantic import BaseModel, Field

from backend.app.data_access.operation_gateway import OperationSpec, register_operation


class DatabaseSnapshotParams(BaseModel):
    include_job_counts: bool = True


class AdminMetricsParams(BaseModel):
    recent_limit: int = Field(default=20, ge=1, le=50)


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
    version="1.0.0",
    operation_type="read",
    parameter_model=DatabaseSnapshotParams,
    allowed_collections=("jobs", "huit_kb"),
    handler=_database_snapshot,
    max_results=1,
    max_output_bytes=8_000,
    max_time_ms=3_000,
    declared_checksum="5bfc007270d8ac51e6838d1c264d372c3f6ead14af744b340795bc1a6f96b91b",
))

ADMIN_METRICS = register_operation(OperationSpec(
    key="admin.metrics",
    version="1.0.0",
    operation_type="read",
    parameter_model=AdminMetricsParams,
    allowed_collections=("rag_events", "query_cache", "huit_kb"),
    handler=_admin_metrics,
    max_results=1,
    max_output_bytes=256_000,
    max_time_ms=3_000,
    declared_checksum="7586ad3a16058869ad07f30039eeaaac7486231e52d6eb6a29923a7852778a51",
))
