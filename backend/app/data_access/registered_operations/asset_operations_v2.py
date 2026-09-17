"""Registered MongoDB operations for physical assets and logical artifacts (v2.0.0)."""
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, ConfigDict, Field, field_validator

from backend.app.data_access.operation_gateway import OperationSpec, register_operation
from backend.app.models.mongo_models import MongoAssetRecord, MongoArtifactRecord


# Models
class FindAssetByIdParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    asset_id: str = Field(min_length=1, max_length=128)


class FindAssetOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    found: bool
    asset: Optional[MongoAssetRecord] = None


class FindAssetByContentHashParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    content_hash: str = Field(min_length=1, max_length=128)
    touch: bool = Field(default=False)


class FindDerivativeParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_asset_id: str = Field(min_length=1, max_length=128)
    scale: int = Field(ge=1, le=4)
    file_ext: str = Field(min_length=1, max_length=10)


class TouchAssetParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    asset_id: str = Field(min_length=1, max_length=128)


class TouchAssetOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    touched: bool


class UpsertAssetParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    asset: MongoAssetRecord

    @field_validator("asset", mode="before")
    @classmethod
    def forbid_string_created_at(cls, v: Any) -> Any:
        if isinstance(v, dict) and isinstance(v.get("created_at"), str):
            raise ValueError("created_at phải là đối tượng datetime (BSON Date), không chấp nhận chuỗi (string) trong write operation")
        if hasattr(v, "created_at") and isinstance(getattr(v, "created_at"), str):
            raise ValueError("created_at phải là đối tượng datetime (BSON Date), không chấp nhận chuỗi (string) trong write operation")
        return v


class UpsertAssetOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    acknowledged: bool
    asset_id: str


class DeleteAssetParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    asset_id: str = Field(min_length=1, max_length=128)


class DeleteAssetOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    deleted: bool
    asset_id: str


class FindArtifactByIdParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    artifact_id: str = Field(min_length=1, max_length=128)


class FindArtifactOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    found: bool
    artifact: Optional[MongoArtifactRecord] = None


class FindArtifactByOwnerAndHashParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    content_hash: str = Field(min_length=1, max_length=128)
    owner_id: Optional[str] = Field(default=None, max_length=128)


class UpsertArtifactParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    artifact: MongoArtifactRecord

    @field_validator("artifact", mode="before")
    @classmethod
    def forbid_string_created_at(cls, v: Any) -> Any:
        if isinstance(v, dict) and isinstance(v.get("created_at"), str):
            raise ValueError("created_at phải là đối tượng datetime (BSON Date), không chấp nhận chuỗi (string) trong write operation")
        if hasattr(v, "created_at") and isinstance(getattr(v, "created_at"), str):
            raise ValueError("created_at phải là đối tượng datetime (BSON Date), không chấp nhận chuỗi (string) trong write operation")
        return v


class UpsertArtifactOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    acknowledged: bool
    artifact_id: str


# Handlers
def _handle_find_asset_by_id(context, params: FindAssetByIdParams) -> FindAssetOutput:
    col = context.collection("assets")
    doc = col.find_one({"$or": [{"asset_id": params.asset_id}, {"_id": params.asset_id}]})
    if doc:
        doc.pop("_id", None)
        return FindAssetOutput(found=True, asset=doc)
    return FindAssetOutput(found=False, asset=None)


def _handle_find_asset_by_content_hash(context, params: FindAssetByContentHashParams) -> FindAssetOutput:
    col = context.collection("assets")
    doc = col.find_one({"content_hash": params.content_hash})
    if doc:
        doc.pop("_id", None)
        if params.touch:
            now_dt = datetime.now(timezone.utc)
            a_id = doc.get("asset_id", "")
            col.update_one(
                {"$or": [{"asset_id": a_id}, {"_id": a_id}]},
                {"$inc": {"reference_count": 1}, "$set": {"last_accessed_at": now_dt}}
            )
            doc["reference_count"] = doc.get("reference_count", 1) + 1
            doc["last_accessed_at"] = now_dt
        return FindAssetOutput(found=True, asset=doc)
    return FindAssetOutput(found=False, asset=None)


def _handle_find_derivative(context, params: FindDerivativeParams) -> FindAssetOutput:
    col = context.collection("assets")
    ext = params.file_ext.lower().strip().replace(".", "")
    doc = col.find_one({
        "source_asset_id": params.source_asset_id,
        "scale": params.scale,
        "file_ext": ext,
    })
    if doc:
        doc.pop("_id", None)
        return FindAssetOutput(found=True, asset=doc)
    return FindAssetOutput(found=False, asset=None)


def _handle_touch_asset(context, params: TouchAssetParams) -> TouchAssetOutput:
    col = context.collection("assets")
    now_dt = datetime.now(timezone.utc)
    res = col.update_one(
        {"$or": [{"asset_id": params.asset_id}, {"_id": params.asset_id}]},
        {"$inc": {"reference_count": 1}, "$set": {"last_accessed_at": now_dt}}
    )
    matched = getattr(res, "matched_count", 0)
    modified = getattr(res, "modified_count", 0)
    return TouchAssetOutput(touched=bool(matched > 0 or modified > 0))


def _handle_upsert_asset(context, params: UpsertAssetParams) -> UpsertAssetOutput:
    col = context.collection("assets")
    doc = params.asset.model_dump()
    doc["_id"] = params.asset.asset_id
    col.update_one({"_id": params.asset.asset_id}, {"$set": doc}, upsert=True)
    return UpsertAssetOutput(acknowledged=True, asset_id=params.asset.asset_id)


def _handle_delete_asset(context, params: DeleteAssetParams) -> DeleteAssetOutput:
    col = context.collection("assets")
    res = col.delete_one({"$or": [{"_id": params.asset_id}, {"asset_id": params.asset_id}]})
    deleted_count = getattr(res, "deleted_count", 0)
    return DeleteAssetOutput(deleted=bool(deleted_count > 0), asset_id=params.asset_id)


def _handle_find_artifact_by_id(context, params: FindArtifactByIdParams) -> FindArtifactOutput:
    col = context.collection("artifacts")
    doc = col.find_one({"$or": [{"artifact_id": params.artifact_id}, {"_id": params.artifact_id}]})
    if doc:
        doc.pop("_id", None)
        return FindArtifactOutput(found=True, artifact=doc)
    return FindArtifactOutput(found=False, artifact=None)


def _handle_find_artifact_by_owner_and_hash(context, params: FindArtifactByOwnerAndHashParams) -> FindArtifactOutput:
    col = context.collection("artifacts")
    clean_owner = params.owner_id if (params.owner_id and params.owner_id != "anonymous") else None
    doc = col.find_one({"content_hash": params.content_hash, "owner_id": clean_owner})
    if doc:
        doc.pop("_id", None)
        return FindArtifactOutput(found=True, artifact=doc)
    return FindArtifactOutput(found=False, artifact=None)


def _handle_upsert_artifact(context, params: UpsertArtifactParams) -> UpsertArtifactOutput:
    col = context.collection("artifacts")
    doc = params.artifact.model_dump()
    doc["_id"] = params.artifact.artifact_id
    col.update_one({"_id": params.artifact.artifact_id}, {"$set": doc}, upsert=True)
    return UpsertArtifactOutput(acknowledged=True, artifact_id=params.artifact.artifact_id)


# Declarations
_SPECS = (
    OperationSpec(
        key="assets.find_by_id",
        version="2.0.0",
        operation_type="read",
        allowed_collections=("assets",),
        parameter_model=FindAssetByIdParams,
        output_model=FindAssetOutput,
        handler=_handle_find_asset_by_id,
        mutation_policy="none",
        max_time_ms=3000,
        max_results=1,
        max_output_bytes=32_000,
        # Audit policy 'never': Pure read lookup operation with high frequency and zero side-effects
        audit_policy="never",
        audit_fail_policy="fail_open",
        declared_checksum="a53c2a6d537a80775d487ad29258cad947e57a770fbb25ba05e9d5461ac8bd17",
    ),
    OperationSpec(
        key="assets.find_by_content_hash",
        version="2.0.0",
        operation_type="command",
        allowed_collections=("assets",),
        parameter_model=FindAssetByContentHashParams,
        output_model=FindAssetOutput,
        handler=_handle_find_asset_by_content_hash,
        mutation_policy="update_only",
        max_time_ms=3000,
        max_results=1,
        max_output_bytes=32_000,
        # Audit policy 'mutations_and_failures': Audited because it executes an update mutation when touch=True or on failure
        audit_policy="mutations_and_failures",
        audit_fail_policy="fail_open",
        declared_checksum="2b97c97a39bfb1e95206909b40350a274942412b186ab11a7fd05e57f0886f5f",
    ),
    OperationSpec(
        key="assets.find_derivative",
        version="2.0.0",
        operation_type="read",
        allowed_collections=("assets",),
        parameter_model=FindDerivativeParams,
        output_model=FindAssetOutput,
        handler=_handle_find_derivative,
        mutation_policy="none",
        max_time_ms=3000,
        max_results=1,
        max_output_bytes=32_000,
        # Audit policy 'never': Pure read lookup operation with zero side-effects
        audit_policy="never",
        audit_fail_policy="fail_open",
        declared_checksum="4745fb464593cc2a4f113392f5613f56d48a7a949879b076cd96c5638a2ac077",
    ),
    OperationSpec(
        key="assets.touch",
        version="2.0.0",
        operation_type="command",
        allowed_collections=("assets",),
        parameter_model=TouchAssetParams,
        output_model=TouchAssetOutput,
        handler=_handle_touch_asset,
        mutation_policy="update_only",
        max_time_ms=3000,
        max_results=1,
        max_output_bytes=8_000,
        # Audit policy 'always': Business mutation command modifying reference count and access timestamp
        audit_policy="always",
        audit_fail_policy="fail_open",
        declared_checksum="14c7e20b531da5687539fa391f53199e36ac77aad022b695ebdbecc75238cd3c",
    ),
    OperationSpec(
        key="assets.upsert_metadata",
        version="2.0.0",
        operation_type="command",
        allowed_collections=("assets",),
        parameter_model=UpsertAssetParams,
        output_model=UpsertAssetOutput,
        handler=_handle_upsert_asset,
        mutation_policy="upsert",
        max_time_ms=5000,
        max_results=1,
        max_output_bytes=16_000,
        audit_policy="always",
        audit_fail_policy="fail_open",
        declared_checksum="85020532424df02ab316f39b81add06c8e145c5939db4cb7605702e784e35f4c",
    ),
    OperationSpec(
        key="assets.delete_record",
        version="2.0.0",
        operation_type="command",
        allowed_collections=("assets",),
        parameter_model=DeleteAssetParams,
        output_model=DeleteAssetOutput,
        handler=_handle_delete_asset,
        mutation_policy="delete_only",
        max_time_ms=5000,
        max_results=1,
        max_output_bytes=8_000,
        audit_policy="always",
        audit_fail_policy="fail_open",
        declared_checksum="54b3bc072c0dbf8586b47d2f80fb2430173f262924679f3e85db29b89115be0f",
    ),
    OperationSpec(
        key="artifacts.find_by_id",
        version="2.0.0",
        operation_type="read",
        allowed_collections=("artifacts",),
        parameter_model=FindArtifactByIdParams,
        output_model=FindArtifactOutput,
        handler=_handle_find_artifact_by_id,
        mutation_policy="none",
        max_time_ms=3000,
        max_results=1,
        max_output_bytes=64_000,
        audit_policy="never",
        audit_fail_policy="fail_open",
        declared_checksum="240aa1a83ecd573268ee356345672e6167ef29acf1da2a69e18d89c5f593a6fe",
    ),
    OperationSpec(
        key="artifacts.find_by_owner_and_hash",
        version="2.0.0",
        operation_type="read",
        allowed_collections=("artifacts",),
        parameter_model=FindArtifactByOwnerAndHashParams,
        output_model=FindArtifactOutput,
        handler=_handle_find_artifact_by_owner_and_hash,
        mutation_policy="none",
        max_time_ms=3000,
        max_results=1,
        max_output_bytes=64_000,
        audit_policy="never",
        audit_fail_policy="fail_open",
        declared_checksum="cc9e624450e9e38a2732b1b158bba8ef646e8491363e7057c8b84fc6ba39b5e6",
    ),
    OperationSpec(
        key="artifacts.upsert_ownership",
        version="2.0.0",
        operation_type="command",
        allowed_collections=("artifacts",),
        parameter_model=UpsertArtifactParams,
        output_model=UpsertArtifactOutput,
        handler=_handle_upsert_artifact,
        mutation_policy="upsert",
        max_time_ms=5000,
        max_results=1,
        max_output_bytes=32_000,
        audit_policy="always",
        audit_fail_policy="fail_open",
        declared_checksum="f7acb48ec3a9ca6eb68233cf12f05108ebe84f69807532c0a406acf3d659cd1c",
    ),
)

for spec in _SPECS:
    register_operation(spec)
