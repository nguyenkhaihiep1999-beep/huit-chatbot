"""Versioned MongoDB operations for generated-image metadata (v2.0.0).

Large binary payloads are never returned by these operations. Services work
with bounded metadata and storage keys; bytes remain behind StorageAdapter.
"""
from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator

from backend.app.data_access.operation_gateway import OperationSpec, register_operation
from backend.app.models.mongo_models import Scene

LIGHT_PROJECTION = {"image_data": 0, "image_base64": 0, "binary": 0, "blob": 0}


class GeneratedImageDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")
    image_id: str = Field(min_length=24, max_length=64, pattern=r"^[0-9a-f]{24,64}$")
    blob_id: Optional[str] = Field(default=None, max_length=64)
    owner_id: Optional[str] = Field(default=None, max_length=256)
    access_scope: Literal["public", "private", "legacy_public"] = Field(default="public")
    backend: Literal["flux", "svg"] = Field(default="flux")
    content_hash: str = Field(max_length=128)
    canonical_content_hash: Optional[str] = Field(default=None, max_length=128)
    request_fingerprint: Optional[str] = Field(default=None, max_length=128)
    generation_key: Optional[str] = Field(default=None, max_length=128)
    model: str = Field(default="FLUX.1-schnell", max_length=100)
    seed: Optional[int] = None
    style: Optional[str] = Field(default="photorealistic", max_length=50)
    prompt: Optional[str] = Field(default="", max_length=1000)
    width: int = Field(default=512, ge=64, le=4096)
    height: int = Field(default=512, ge=64, le=4096)
    storage_key: Optional[str] = Field(default=None, max_length=255)
    thumbnail_key: Optional[str] = Field(default=None, max_length=255)
    content_type: Optional[str] = Field(default=None, max_length=50)
    byte_size: Optional[int] = Field(default=None, ge=0)
    thumb_size: Optional[int] = Field(default=None, ge=0)
    scene: Optional[Scene] = None
    scene_bytes: Optional[int] = None
    created_at: Optional[datetime] = None
    is_archived_duplicate: Optional[bool] = False
    schema_version: Optional[int] = 1

    @field_validator("created_at", mode="before")
    @classmethod
    def forbid_string_datetime(cls, v: Any) -> Optional[datetime]:
        if v is None:
            return None
        if isinstance(v, str):
            raise ValueError("created_at phải là datetime (BSON Date), không chấp nhận chuỗi (string) trong write operation")
        if isinstance(v, datetime):
            return v
        raise ValueError("created_at không đúng định dạng datetime")


# Parameter Models
class ImageStoreAvailabilityParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    check: bool = True


class OwnerFingerprintParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    owner_id: Optional[str] = Field(default=None, max_length=256)
    request_fingerprint: str = Field(min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$")


class FingerprintParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_fingerprint: str = Field(min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$")


class ImageIdParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    image_id: str = Field(min_length=24, max_length=64, pattern=r"^[0-9a-f]{24,64}$")


class InsertGeneratedImageParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    document: GeneratedImageDocument


class RecentGeneratedImagesParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    owner_id: Optional[str] = Field(default=None, max_length=256)
    is_admin: bool = False
    is_authenticated: bool = False
    limit: int = Field(default=20, ge=1, le=50)


# Output Models
class StoreAvailabilityOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    available: bool


class GeneratedImageRecordOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    __nullable__ = True
    image_id: Optional[str] = None
    blob_id: Optional[str] = None
    owner_id: Optional[str] = None
    access_scope: Optional[str] = "public"
    backend: Optional[str] = "flux"
    content_hash: Optional[str] = None
    canonical_content_hash: Optional[str] = None
    request_fingerprint: Optional[str] = None
    generation_key: Optional[str] = None
    model: Optional[str] = None
    seed: Optional[int] = None
    style: Optional[str] = None
    prompt: Optional[str] = None
    width: Optional[int] = None
    height: Optional[int] = None
    storage_key: Optional[str] = None
    thumbnail_key: Optional[str] = None
    content_type: Optional[str] = None
    byte_size: Optional[int] = None
    thumb_size: Optional[int] = None
    scene: Optional[Scene] = None
    scene_bytes: Optional[int] = None
    created_at: Optional[Union[datetime, str]] = None
    is_archived_duplicate: Optional[bool] = False
    schema_version: Optional[int] = 1


class InsertGeneratedImageOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    inserted: bool
    image_id: Optional[str] = None


class RecentGeneratedImageItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    image_id: str
    width: Optional[int] = None
    height: Optional[int] = None
    byte_size: Optional[int] = None
    access_scope: Optional[str] = None
    owner_id: Optional[str] = None
    created_at: Optional[Union[datetime, str]] = None


def _fingerprint_filter(fingerprint: str) -> Dict[str, Any]:
    return {
        "$or": [
            {"request_fingerprint": fingerprint},
            {"canonical_content_hash": fingerprint},
            {"content_hash": fingerprint},
        ]
    }


def _availability(ctx, _params: ImageStoreAvailabilityParams):
    ctx.ping()
    return {"available": True}


def _find_for_owner(ctx, params: OwnerFingerprintParams):
    query = _fingerprint_filter(params.request_fingerprint)
    query["owner_id"] = params.owner_id
    return ctx.collection("generated_images").find_one(query, LIGHT_PROJECTION)


def _find_any(ctx, params: FingerprintParams):
    return ctx.collection("generated_images").find_one(
        _fingerprint_filter(params.request_fingerprint), LIGHT_PROJECTION
    )


def _get(ctx, params: ImageIdParams):
    return ctx.collection("generated_images").find_one(
        {"$or": [{"_id": params.image_id}, {"image_id": params.image_id}]},
        LIGHT_PROJECTION,
    )


def _insert(ctx, params: InsertGeneratedImageParams):
    doc_dict = params.document.model_dump(mode="json")
    for heavy_field in LIGHT_PROJECTION:
        doc_dict.pop(heavy_field, None)
    result = ctx.collection("generated_images").insert_one(doc_dict)
    return {
        "inserted": bool(getattr(result, "acknowledged", True)),
        "image_id": doc_dict.get("image_id"),
    }


def _recent(ctx, params: RecentGeneratedImagesParams):
    query: Dict[str, Any] = {}
    if not params.is_admin:
        public_clauses = [
            {"owner_id": None},
            {"access_scope": "public"},
            {"access_scope": "legacy_public"},
        ]
        if params.is_authenticated and params.owner_id:
            public_clauses.insert(0, {"owner_id": params.owner_id})
        query = {"$or": public_clauses}
    projection = {
        "_id": 0,
        "image_id": 1,
        "width": 1,
        "height": 1,
        "byte_size": 1,
        "access_scope": 1,
        "owner_id": 1,
        "created_at": 1,
    }
    return list(
        ctx.collection("generated_images")
        .find(query, projection)
        .sort("created_at", -1)
        .limit(params.limit)
    )


ENSURE_GENERATED_IMAGE_STORE = register_operation(OperationSpec(
    key="generated_image.ensure_store",
    version="2.0.0",
    operation_type="read",
    parameter_model=ImageStoreAvailabilityParams,
    output_model=StoreAvailabilityOutput,
    allowed_collections=(),
    mutation_policy="none",
    handler=_availability,
    max_results=1,
    max_output_bytes=1_000,
    max_time_ms=2_000,
    audit_policy="always",
    audit_fail_policy="fail_open",
    declared_checksum="c88b261f3e4a4121ae1bfcdab4a74d7d0c1e58350d35b88cd77ac887ae2c3bc7",
))

FIND_OWNER_GENERATED_IMAGE = register_operation(OperationSpec(
    key="generated_image.find_for_owner",
    version="2.0.0",
    operation_type="read",
    parameter_model=OwnerFingerprintParams,
    output_model=GeneratedImageRecordOutput,
    allowed_collections=("generated_images",),
    mutation_policy="none",
    handler=_find_for_owner,
    max_results=1,
    max_output_bytes=64_000,
    max_time_ms=2_000,
    audit_policy="always",
    audit_fail_policy="fail_open",
    declared_checksum="2adf8d925436b2361d9093d366f1ff3b6b3edd4f8cacded35e6d4d21dcd4df54",
))

FIND_ANY_GENERATED_IMAGE = register_operation(OperationSpec(
    key="generated_image.find_any",
    version="2.0.0",
    operation_type="read",
    parameter_model=FingerprintParams,
    output_model=GeneratedImageRecordOutput,
    allowed_collections=("generated_images",),
    mutation_policy="none",
    handler=_find_any,
    max_results=1,
    max_output_bytes=64_000,
    max_time_ms=2_000,
    audit_policy="always",
    audit_fail_policy="fail_open",
    declared_checksum="7a75b1fcb2ee6535e8a20fd557dc215f85dcca16f8486ddd42424bfbd252502e",
))

GET_GENERATED_IMAGE = register_operation(OperationSpec(
    key="generated_image.get",
    version="2.0.0",
    operation_type="read",
    parameter_model=ImageIdParams,
    output_model=GeneratedImageRecordOutput,
    allowed_collections=("generated_images",),
    mutation_policy="none",
    handler=_get,
    max_results=1,
    max_output_bytes=64_000,
    max_time_ms=2_000,
    audit_policy="always",
    audit_fail_policy="fail_open",
    declared_checksum="1f69ab654ec316d0375b8a79e9df1b761397b68c66c9378d41cd9382c5dfb870",
))

INSERT_GENERATED_IMAGE = register_operation(OperationSpec(
    key="generated_image.insert",
    version="2.0.0",
    operation_type="command",
    parameter_model=InsertGeneratedImageParams,
    output_model=InsertGeneratedImageOutput,
    allowed_collections=("generated_images",),
    mutation_policy="insert_only",
    handler=_insert,
    max_results=1,
    max_output_bytes=4_000,
    max_time_ms=3_000,
    audit_policy="always",
    audit_fail_policy="fail_open",
    declared_checksum="cc87c20f85f4d986162e812b95e16ffb1ce92262007f974490184a3b6b390ff4",
))

LIST_RECENT_GENERATED_IMAGES = register_operation(OperationSpec(
    key="generated_image.list_recent",
    version="2.0.0",
    operation_type="read",
    parameter_model=RecentGeneratedImagesParams,
    output_model=RecentGeneratedImageItem,
    allowed_collections=("generated_images",),
    mutation_policy="none",
    handler=_recent,
    max_results=50,
    max_output_bytes=128_000,
    max_time_ms=2_500,
    audit_policy="always",
    audit_fail_policy="fail_open",
    declared_checksum="90e2b47f3b8a9f9b29625c76d36808161fd8f116756810f2c7b341c2b40e6539",
))
