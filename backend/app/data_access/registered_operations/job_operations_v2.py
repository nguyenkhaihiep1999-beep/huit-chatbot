"""Registered MongoDB operations for durable background job queue (v2.0.0)."""
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, ConfigDict, Field, field_validator
from pymongo import ReturnDocument

from backend.app.data_access.operation_gateway import OperationSpec, register_operation
from backend.app.models.mongo_models import MongoJobRecord, JobErrorDetail


# Models
class CreateJobParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    job: MongoJobRecord

    @field_validator("job", mode="before")
    @classmethod
    def forbid_string_created_at(cls, v: Any) -> Any:
        if isinstance(v, dict) and isinstance(v.get("created_at"), str):
            raise ValueError("created_at phải là đối tượng datetime (BSON Date), không chấp nhận chuỗi (string) trong write operation")
        if hasattr(v, "created_at") and isinstance(getattr(v, "created_at"), str):
            raise ValueError("created_at phải là đối tượng datetime (BSON Date), không chấp nhận chuỗi (string) trong write operation")
        return v


class CreateJobOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    acknowledged: bool
    job_id: str


class FindJobByIdParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    job_id: str = Field(min_length=1, max_length=128)


class FindJobOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    found: bool
    job: Optional[MongoJobRecord] = None


class FindJobByIdempotencyParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    idempotency_key: str = Field(min_length=1, max_length=128)
    statuses: List[str] = Field(default_factory=lambda: ["queued", "processing", "completed"])


class FindJobByIdempotencyOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    found: bool
    job_id: Optional[str] = None


class AtomicClaimJobParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    worker_id: str = Field(min_length=1, max_length=128)
    lease_seconds: int = Field(default=120, ge=1, le=3600)
    specific_job_id: Optional[str] = Field(default=None, max_length=128)


class ClaimJobOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    claimed: bool
    job: Optional[MongoJobRecord] = None


class HeartbeatJobParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    job_id: str = Field(min_length=1, max_length=128)
    worker_id: str = Field(min_length=1, max_length=128)
    extend_seconds: int = Field(default=120, ge=1, le=3600)


class HeartbeatJobOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    extended: bool


class ReleaseLeaseParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    job_id: str = Field(min_length=1, max_length=128)
    worker_id: str = Field(min_length=1, max_length=128)


class ReleaseLeaseOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    released: bool


class UpdateJobParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    job_id: str = Field(min_length=1, max_length=128)
    status: Optional[str] = None
    progress: Optional[int] = Field(default=None, ge=0, le=100)
    retries: Optional[int] = Field(default=None, ge=0)
    attempt: Optional[int] = Field(default=None, ge=0)
    result_url: Optional[str] = None
    media_type: Optional[str] = None
    error: Optional[JobErrorDetail] = None
    sanitized_error: Optional[str] = None
    event_detail: Optional[str] = None
    available_at: Optional[datetime] = None
    worker_id: Optional[str] = None


class UpdateJobOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    updated: bool


class RecoverExpiredLeasesParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    max_jobs: int = Field(default=10, ge=1, le=100)


class RecoverExpiredLeasesOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    recovered_count: int


# Handlers
def _handle_create_job(context, params: CreateJobParams) -> CreateJobOutput:
    col = context.collection("jobs")
    doc = params.job.model_dump()
    doc["_id"] = params.job.job_id
    col.update_one({"_id": params.job.job_id}, {"$set": doc}, upsert=True)
    return CreateJobOutput(acknowledged=True, job_id=params.job.job_id)


def _handle_find_job_by_id(context, params: FindJobByIdParams) -> FindJobOutput:
    col = context.collection("jobs")
    doc = col.find_one({"$or": [{"job_id": params.job_id}, {"_id": params.job_id}]})
    if doc:
        doc.pop("_id", None)
        return FindJobOutput(found=True, job=doc)
    return FindJobOutput(found=False, job=None)


def _handle_find_job_by_idempotency(context, params: FindJobByIdempotencyParams) -> FindJobByIdempotencyOutput:
    col = context.collection("jobs")
    doc = col.find_one({
        "idempotency_key": params.idempotency_key,
        "status": {"$in": params.statuses}
    })
    if doc:
        j_id = doc.get("job_id") or str(doc.get("_id"))
        return FindJobByIdempotencyOutput(found=True, job_id=j_id)
    return FindJobByIdempotencyOutput(found=False, job_id=None)


def _handle_atomic_claim(context, params: AtomicClaimJobParams) -> ClaimJobOutput:
    col = context.collection("jobs")
    now_dt = datetime.now(timezone.utc)
    lease_expiry = now_dt + timedelta(seconds=params.lease_seconds)
    max_retries = 3

    base_or = [
        {
            "status": "queued",
            "available_at": {"$lte": now_dt},
            "$expr": {
                "$lt": [
                    {"$ifNull": ["$attempt", 0]},
                    {"$ifNull": ["$max_attempts", max_retries]},
                ]
            },
        },
        {
            "status": "processing",
            "lease_expires_at": {"$lte": now_dt},
            "$expr": {
                "$lt": [
                    {"$ifNull": ["$attempt", 0]},
                    {"$ifNull": ["$max_attempts", max_retries]},
                ]
            },
        }
    ]
    if params.specific_job_id:
        query = {"$and": [{"$or": [{"_id": params.specific_job_id}, {"job_id": params.specific_job_id}]}, {"$or": base_or}]}
    else:
        query = {"$or": base_or}

    update = {
        "$set": {
            "status": "processing",
            "lease_owner": params.worker_id,
            "lease_expires_at": lease_expiry,
            "heartbeat_at": now_dt,
            "updated_at": now_dt
        },
        "$inc": {"attempt": 1}
    }
    doc = col.find_one_and_update(query, update, return_document=ReturnDocument.AFTER)
    if doc:
        doc.pop("_id", None)
        return ClaimJobOutput(claimed=True, job=doc)
    return ClaimJobOutput(claimed=False, job=None)


def _handle_heartbeat(context, params: HeartbeatJobParams) -> HeartbeatJobOutput:
    col = context.collection("jobs")
    now_dt = datetime.now(timezone.utc)
    res = col.update_one(
        {
            "$or": [{"_id": params.job_id}, {"job_id": params.job_id}],
            "status": "processing",
            "lease_owner": params.worker_id
        },
        {"$set": {
            "heartbeat_at": now_dt,
            "lease_expires_at": now_dt + timedelta(seconds=params.extend_seconds),
            "updated_at": now_dt
        }}
    )
    modified = getattr(res, "modified_count", 0)
    matched = getattr(res, "matched_count", 0)
    return HeartbeatJobOutput(extended=bool(modified > 0 or matched > 0))


def _handle_release_lease(context, params: ReleaseLeaseParams) -> ReleaseLeaseOutput:
    col = context.collection("jobs")
    now_dt = datetime.now(timezone.utc)
    res = col.update_one(
        {
            "$or": [{"_id": params.job_id}, {"job_id": params.job_id}],
            "status": "processing",
            "lease_owner": params.worker_id
        },
        {"$set": {
            "status": "queued",
            "lease_owner": None,
            "lease_expires_at": None,
            "updated_at": now_dt
        }}
    )
    modified = getattr(res, "modified_count", 0)
    matched = getattr(res, "matched_count", 0)
    return ReleaseLeaseOutput(released=bool(modified > 0 or matched > 0))


def _handle_update_job(context, params: UpdateJobParams) -> UpdateJobOutput:
    col = context.collection("jobs")
    now_dt = datetime.now(timezone.utc)

    # Check existing doc to prevent overwriting cancelled jobs
    doc = col.find_one({"$or": [{"_id": params.job_id}, {"job_id": params.job_id}]})
    if not doc:
        return UpdateJobOutput(updated=False)

    current_status = doc.get("status")
    current_lease_owner = doc.get("lease_owner")

    if current_status == "cancelled" and params.status in ("processing", "completed"):
        return UpdateJobOutput(updated=False)

    if params.status == "completed" and params.worker_id and current_lease_owner and current_lease_owner != params.worker_id:
        return UpdateJobOutput(updated=False)

    update_fields: Dict[str, Any] = {"updated_at": now_dt}
    if params.status:
        update_fields["status"] = params.status
        if params.status in ("completed", "failed", "cancelled"):
            update_fields["lease_owner"] = None
            update_fields["lease_expires_at"] = None

    if params.progress is not None:
        update_fields["progress"] = params.progress
    if params.retries is not None:
        update_fields["retries"] = params.retries
    if params.attempt is not None:
        update_fields["attempt"] = params.attempt
    if params.available_at is not None:
        update_fields["available_at"] = params.available_at
    if params.result_url:
        update_fields["result_url"] = params.result_url
    if params.media_type:
        update_fields["media_type"] = params.media_type
    if params.error:
        update_fields["error"] = params.error.model_dump() if hasattr(params.error, "model_dump") else params.error
        error_msg = getattr(params.error, "message", None) or (params.error.get("message") if isinstance(params.error, dict) else str(params.error))
        update_fields["sanitized_error"] = params.sanitized_error or error_msg

    new_event = {
        "timestamp": now_dt,
        "status": params.status or current_status or "processing",
        "progress": params.progress if params.progress is not None else doc.get("progress", 0),
        "detail": params.event_detail or f"Trạng thái: {params.status or current_status}"
    }

    update_op: Dict[str, Any] = {
        "$set": update_fields,
        "$push": {"events": {"$each": [new_event], "$slice": -30}}
    }

    filter_q: Dict[str, Any] = {"$or": [{"_id": params.job_id}, {"job_id": params.job_id}]}
    if params.status == "completed" and params.worker_id:
        filter_q["lease_owner"] = params.worker_id
        filter_q["status"] = "processing"

    res = col.update_one(filter_q, update_op)
    matched = getattr(res, "matched_count", 0)
    modified = getattr(res, "modified_count", 0)
    return UpdateJobOutput(updated=bool(matched > 0 or modified > 0))


def _handle_recover_expired_leases(context, params: RecoverExpiredLeasesParams) -> RecoverExpiredLeasesOutput:
    col = context.collection("jobs")
    now_dt = datetime.now(timezone.utc)
    cursor = col.find({"status": "processing", "lease_expires_at": {"$lte": now_dt}}).limit(params.max_jobs)
    recovered = 0
    for doc in cursor:
        attempt = doc.get("attempt", 0)
        max_attempts = doc.get("max_attempts", 3)
        if attempt < max_attempts:
            col.update_one(
                {"_id": doc["_id"], "status": "processing"},
                {"$set": {"status": "queued", "lease_owner": None, "lease_expires_at": None, "updated_at": now_dt}}
            )
        else:
            col.update_one(
                {"_id": doc["_id"], "status": "processing"},
                {"$set": {
                    "status": "failed",
                    "lease_owner": None,
                    "lease_expires_at": None,
                    "error": {"error_code": "LEASE_EXPIRED_MAX_ATTEMPTS", "message": "Lease quá hạn và đã vượt số lần thử tối đa"},
                    "updated_at": now_dt
                }}
            )
        recovered += 1
    return RecoverExpiredLeasesOutput(recovered_count=recovered)


# Declarations
_SPECS = (
    OperationSpec(
        key="jobs.create",
        version="2.0.0",
        operation_type="command",
        allowed_collections=("jobs",),
        parameter_model=CreateJobParams,
        output_model=CreateJobOutput,
        handler=_handle_create_job,
        mutation_policy="upsert",
        max_time_ms=5000,
        max_results=1,
        max_output_bytes=16_000,
        audit_policy="always",
        audit_fail_policy="fail_open",
        declared_checksum="bcf0532e0cecb5ae2da288960fa5d37b38d9a45837ee5c1341830aa9b87f7227",
    ),
    OperationSpec(
        key="jobs.find_by_id",
        version="2.0.0",
        operation_type="read",
        allowed_collections=("jobs",),
        parameter_model=FindJobByIdParams,
        output_model=FindJobOutput,
        handler=_handle_find_job_by_id,
        mutation_policy="none",
        max_time_ms=3000,
        max_results=1,
        max_output_bytes=64_000,
        # Audit policy 'never': Pure read query with zero state mutations
        audit_policy="never",
        audit_fail_policy="fail_open",
        declared_checksum="ad6508e8a3a8f99604f052db6b731950a6ed45844e0910fb92a261ac7b8f8718",
    ),
    OperationSpec(
        key="jobs.find_by_idempotency",
        version="2.0.0",
        operation_type="read",
        allowed_collections=("jobs",),
        parameter_model=FindJobByIdempotencyParams,
        output_model=FindJobByIdempotencyOutput,
        handler=_handle_find_job_by_idempotency,
        mutation_policy="none",
        max_time_ms=3000,
        max_results=1,
        max_output_bytes=16_000,
        # Audit policy 'never': Pure read query with zero state mutations
        audit_policy="never",
        audit_fail_policy="fail_open",
        declared_checksum="f7508b914a54b1b2d33c9221676f7fdd6b48b9a36b97aad78d28af5157a25610",
    ),
    OperationSpec(
        key="jobs.atomic_claim",
        version="2.0.0",
        operation_type="command",
        allowed_collections=("jobs",),
        parameter_model=AtomicClaimJobParams,
        output_model=ClaimJobOutput,
        handler=_handle_atomic_claim,
        mutation_policy="update_only",
        max_time_ms=5000,
        max_results=1,
        max_output_bytes=64_000,
        audit_policy="always",
        audit_fail_policy="fail_open",
        declared_checksum="06cbed706ed6ea9d1b40e2f26eba172bb5d28af1bf98a16ae97d992778b40560",
    ),
    OperationSpec(
        key="jobs.heartbeat",
        version="2.0.0",
        operation_type="command",
        allowed_collections=("jobs",),
        parameter_model=HeartbeatJobParams,
        output_model=HeartbeatJobOutput,
        handler=_handle_heartbeat,
        mutation_policy="update_only",
        max_time_ms=3000,
        max_results=1,
        max_output_bytes=8_000,
        # Audit policy 'never': High-frequency ephemeral worker heartbeats (~every 5s). Auditing would flood database logs without audit benefit
        audit_policy="never",
        audit_fail_policy="fail_open",
        declared_checksum="8389b7af1c10cdd7f33733ddd082c1e80e34681aca58a4bad3ce7129182293dc",
    ),
    OperationSpec(
        key="jobs.release_lease",
        version="2.0.0",
        operation_type="command",
        allowed_collections=("jobs",),
        parameter_model=ReleaseLeaseParams,
        output_model=ReleaseLeaseOutput,
        handler=_handle_release_lease,
        mutation_policy="update_only",
        max_time_ms=3000,
        max_results=1,
        max_output_bytes=8_000,
        # Audit policy 'never': Ephemeral worker lease release upon graceful shutdown
        audit_policy="never",
        audit_fail_policy="fail_open",
        declared_checksum="de6f862708fc7e14b3de4c84d034fad8da77d3f148a570d0e2bcd7bebe9d352a",
    ),
    OperationSpec(
        key="jobs.update",
        version="2.0.0",
        operation_type="command",
        allowed_collections=("jobs",),
        parameter_model=UpdateJobParams,
        output_model=UpdateJobOutput,
        handler=_handle_update_job,
        mutation_policy="update_only",
        max_time_ms=5000,
        max_results=1,
        max_output_bytes=16_000,
        audit_policy="always",
        audit_fail_policy="fail_open",
        declared_checksum="42b5b6dcbb7bd7463c7798378186f6b47fe15bffd3857a7d157c4f49b71fe6b1",
    ),
    OperationSpec(
        key="jobs.recover_expired_leases",
        version="2.0.0",
        operation_type="command",
        allowed_collections=("jobs",),
        parameter_model=RecoverExpiredLeasesParams,
        output_model=RecoverExpiredLeasesOutput,
        handler=_handle_recover_expired_leases,
        mutation_policy="update_only",
        max_time_ms=5000,
        max_results=100,
        max_output_bytes=16_000,
        audit_policy="always",
        audit_fail_policy="fail_open",
        declared_checksum="c2686fe98cf554eac69f8035cae1daed5e7ab2b771fcbe26127122966268ed36",
    ),
)

for spec in _SPECS:
    register_operation(spec)
