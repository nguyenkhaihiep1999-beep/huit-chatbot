"""Versioned MongoDB operations for generated-image metadata.

Large binary payloads are never returned by these operations.  Services work
with bounded metadata and storage keys; bytes remain behind StorageAdapter.
"""
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field

from backend.app.data_access.operation_gateway import OperationSpec, register_operation


LIGHT_PROJECTION = {"image_data": 0, "image_base64": 0, "binary": 0, "blob": 0}


class ImageStoreAvailabilityParams(BaseModel):
    check: bool = True


class OwnerFingerprintParams(BaseModel):
    owner_id: Optional[str] = Field(default=None, max_length=256)
    request_fingerprint: str = Field(min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$")


class FingerprintParams(BaseModel):
    request_fingerprint: str = Field(min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$")


class ImageIdParams(BaseModel):
    image_id: str = Field(min_length=24, max_length=64, pattern=r"^[0-9a-f]{24,64}$")


class InsertGeneratedImageParams(BaseModel):
    document: Dict[str, Any]


class RecentGeneratedImagesParams(BaseModel):
    owner_id: Optional[str] = Field(default=None, max_length=256)
    is_admin: bool = False
    is_authenticated: bool = False
    limit: int = Field(default=20, ge=1, le=50)


def _fingerprint_filter(fingerprint: str) -> Dict[str, Any]:
    return {
        "$or": [
            {"request_fingerprint": fingerprint},
            {"canonical_content_hash": fingerprint},
            # Compatibility for legacy records created before the split between
            # request fingerprints and physical content hashes.
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
    document = dict(params.document)
    for heavy_field in LIGHT_PROJECTION:
        document.pop(heavy_field, None)
    result = ctx.collection("generated_images").insert_one(document)
    return {
        "inserted": bool(getattr(result, "acknowledged", True)),
        "image_id": document.get("image_id"),
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
    version="1.0.0",
    operation_type="read",
    parameter_model=ImageStoreAvailabilityParams,
    allowed_collections=(),
    handler=_availability,
    max_results=1,
    max_output_bytes=1_000,
    max_time_ms=2_000,
    declared_checksum="249a2b4b54f192094c51f787b4adafbe40d95b0c72f7850ddd505c6ca87cd4aa",
))

FIND_OWNER_GENERATED_IMAGE = register_operation(OperationSpec(
    key="generated_image.find_for_owner",
    version="1.0.0",
    operation_type="read",
    parameter_model=OwnerFingerprintParams,
    allowed_collections=("generated_images",),
    handler=_find_for_owner,
    max_results=1,
    max_output_bytes=128_000,
    max_time_ms=2_000,
    declared_checksum="fee3d88ec23193bd3cf7591dfb9afcd51deaa6b62485466f20a5a0a028093677",
))

FIND_ANY_GENERATED_IMAGE = register_operation(OperationSpec(
    key="generated_image.find_any",
    version="1.0.0",
    operation_type="read",
    parameter_model=FingerprintParams,
    allowed_collections=("generated_images",),
    handler=_find_any,
    max_results=1,
    max_output_bytes=128_000,
    max_time_ms=2_000,
    declared_checksum="d1a5703e46f44341019efcf3c2747d57567fc5841e8a996adb1f73d711a7a5d1",
))

GET_GENERATED_IMAGE = register_operation(OperationSpec(
    key="generated_image.get",
    version="1.0.0",
    operation_type="read",
    parameter_model=ImageIdParams,
    allowed_collections=("generated_images",),
    handler=_get,
    max_results=1,
    max_output_bytes=256_000,
    max_time_ms=2_000,
    declared_checksum="ef2fbc037e8e21810373e65e197b2bc508e8f0374766b30652d3ba67deebc794",
))

INSERT_GENERATED_IMAGE = register_operation(OperationSpec(
    key="generated_image.insert",
    version="1.0.0",
    operation_type="command",
    parameter_model=InsertGeneratedImageParams,
    allowed_collections=("generated_images",),
    handler=_insert,
    max_results=1,
    max_output_bytes=2_000,
    max_time_ms=2_000,
    declared_checksum="5c5f89b2c4ab117c29f3fe5fe445fe3b624e691d1c823cd6b0545dbdef41c0c5",
))

LIST_RECENT_GENERATED_IMAGES = register_operation(OperationSpec(
    key="generated_image.list_recent",
    version="1.0.0",
    operation_type="read",
    parameter_model=RecentGeneratedImagesParams,
    allowed_collections=("generated_images",),
    handler=_recent,
    max_results=50,
    max_output_bytes=128_000,
    max_time_ms=2_000,
    declared_checksum="bfcc811b5d57d593d1dc66858f193addc6408a66c52d5bb13e88208586d3f1b6",
))
