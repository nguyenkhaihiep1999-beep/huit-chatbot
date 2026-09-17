"""Registered MongoDB operations for admin sessions management (v2.0.0)."""
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, ConfigDict, Field

from backend.app.data_access.operation_gateway import OperationSpec, register_operation
from backend.app.models.mongo_models import ensure_utc_datetime

ADMIN_SESSION_PROJECTION = {"_id": 0}


# Models
class CreateAdminSessionParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    session_hash: str = Field(min_length=64, max_length=64, pattern=r"^[a-f0-9]{64}$")
    session_id: str = Field(min_length=1, max_length=128)
    admin_id: str = Field(min_length=1, max_length=128)
    expires_at: datetime
    ip_address: Optional[str] = Field(default=None, max_length=128)
    user_agent: Optional[str] = Field(default=None, max_length=512)


class CreateAdminSessionOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    created: bool
    session_hash: str


class FindValidAdminSessionParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    session_hash: str = Field(min_length=64, max_length=64, pattern=r"^[a-f0-9]{64}$")


class FindValidAdminSessionOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    found: bool
    session_id: Optional[str] = None
    admin_id: Optional[str] = None
    expires_at: Optional[datetime] = None


class RevokeAdminSessionParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    session_hash: str = Field(min_length=64, max_length=64, pattern=r"^[a-f0-9]{64}$")


class RevokeAdminSessionOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revoked: bool


class PurgeExpiredAdminSessionsParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    before: Optional[datetime] = None


class PurgeExpiredAdminSessionsOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    deleted_count: int


# Handlers
def _handle_create_session(context, params: CreateAdminSessionParams) -> CreateAdminSessionOutput:
    col = context.collection("admin_sessions")
    now_utc = datetime.now(timezone.utc)
    doc = {
        "session_hash": params.session_hash,
        "session_id": params.session_id,
        "admin_id": params.admin_id,
        "created_at": now_utc,
        "expires_at": ensure_utc_datetime(params.expires_at),
        "revoked": False,
        "ip_address": params.ip_address,
        "user_agent": params.user_agent,
        "last_seen_at": now_utc,
    }
    col.insert_one(doc)
    return CreateAdminSessionOutput(created=True, session_hash=params.session_hash)


def _handle_find_valid_session(context, params: FindValidAdminSessionParams) -> FindValidAdminSessionOutput:
    col = context.collection("admin_sessions")
    now_utc = datetime.now(timezone.utc)
    doc = col.find_one(
        {
            "session_hash": params.session_hash,
            "revoked": False,
            "expires_at": {"$gt": now_utc},
        },
        ADMIN_SESSION_PROJECTION,
    )
    if not doc:
        return FindValidAdminSessionOutput(found=False)

    # Cập nhật last_seen_at
    try:
        col.update_one(
            {"session_hash": params.session_hash},
            {"$set": {"last_seen_at": now_utc}},
        )
    except Exception:
        pass

    return FindValidAdminSessionOutput(
        found=True,
        session_id=str(doc.get("session_id")),
        admin_id=str(doc.get("admin_id")),
        expires_at=doc.get("expires_at"),
    )


def _handle_revoke_session(context, params: RevokeAdminSessionParams) -> RevokeAdminSessionOutput:
    col = context.collection("admin_sessions")
    res = col.update_one(
        {"session_hash": params.session_hash},
        {"$set": {"revoked": True}},
    )
    return RevokeAdminSessionOutput(revoked=res.modified_count > 0 or res.matched_count > 0)


def _handle_purge_expired_sessions(context, params: PurgeExpiredAdminSessionsParams) -> PurgeExpiredAdminSessionsOutput:
    col = context.collection("admin_sessions")
    cutoff = ensure_utc_datetime(params.before) if params.before else datetime.now(timezone.utc)
    res = col.delete_many({"expires_at": {"$lte": cutoff}})
    return PurgeExpiredAdminSessionsOutput(deleted_count=res.deleted_count)


# Specifications with fixed literal checksums (LTX-RULE-1 compliance)
_SPECS: tuple[OperationSpec, ...] = (
    OperationSpec(
        key="admin_session.create",
        version="2.0.0",
        operation_type="command",
        allowed_collections=("admin_sessions",),
        parameter_model=CreateAdminSessionParams,
        output_model=CreateAdminSessionOutput,
        handler=_handle_create_session,
        mutation_policy="insert_only",
        max_time_ms=3000,
        max_results=1,
        max_output_bytes=16_000,
        max_parameter_bytes=64_000,
        audit_policy="mutations_and_failures",
        audit_fail_policy="fail_open",
        declared_checksum="85314079b5aa0da9796532b06aa09062c61489bc91924fa12527eeb121f391e4",
    ),
    OperationSpec(
        key="admin_session.find_valid",
        version="2.0.0",
        operation_type="command",
        allowed_collections=("admin_sessions",),
        parameter_model=FindValidAdminSessionParams,
        output_model=FindValidAdminSessionOutput,
        handler=_handle_find_valid_session,
        mutation_policy="update_only",
        max_time_ms=3000,
        max_results=1,
        max_output_bytes=16_000,
        max_parameter_bytes=64_000,
        audit_policy="failures_only",
        audit_fail_policy="fail_open",
        declared_checksum="9a85112ce6e7c0cfda2e3edad580343a2c5ea72cb76d1d00ba01ecc5401ba8b4",
    ),
    OperationSpec(
        key="admin_session.revoke",
        version="2.0.0",
        operation_type="command",
        allowed_collections=("admin_sessions",),
        parameter_model=RevokeAdminSessionParams,
        output_model=RevokeAdminSessionOutput,
        handler=_handle_revoke_session,
        mutation_policy="update_only",
        max_time_ms=3000,
        max_results=1,
        max_output_bytes=16_000,
        max_parameter_bytes=64_000,
        audit_policy="mutations_and_failures",
        audit_fail_policy="fail_open",
        declared_checksum="67e0d1e6b02a429fb37f453eed5f8be0d2a02295342e34c3001e4ee4f55b8883",
    ),
    OperationSpec(
        key="admin_session.purge_expired",
        version="2.0.0",
        operation_type="command",
        allowed_collections=("admin_sessions",),
        parameter_model=PurgeExpiredAdminSessionsParams,
        output_model=PurgeExpiredAdminSessionsOutput,
        handler=_handle_purge_expired_sessions,
        mutation_policy="delete_only",
        max_time_ms=5000,
        max_results=1000,
        max_output_bytes=16_000,
        max_parameter_bytes=64_000,
        audit_policy="mutations_and_failures",
        audit_fail_policy="fail_open",
        declared_checksum="e66c963e1c6cc61603f1277037eff71c49cd800ba437d872a4c439ad2db8d1c3",
    ),
)

for spec in _SPECS:
    register_operation(spec)
