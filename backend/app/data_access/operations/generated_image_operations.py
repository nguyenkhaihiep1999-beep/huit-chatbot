"""LTX domain adapters for generated-image metadata operations (v2.0.0)."""
from typing import Any, Dict, Optional

from backend.app.data_access.operation_gateway import execute_registered_operation
from backend.app.data_access.registered_operations.generated_images_v2 import (
    ENSURE_GENERATED_IMAGE_STORE,
    FIND_ANY_GENERATED_IMAGE,
    FIND_OWNER_GENERATED_IMAGE,
    GET_GENERATED_IMAGE,
    INSERT_GENERATED_IMAGE,
    LIST_RECENT_GENERATED_IMAGES,
    GeneratedImageDocument,
)

PINNED_CHECKSUMS = {
    "generated_image.ensure_store": "c88b261f3e4a4121ae1bfcdab4a74d7d0c1e58350d35b88cd77ac887ae2c3bc7",
    "generated_image.find_for_owner": "2adf8d925436b2361d9093d366f1ff3b6b3edd4f8cacded35e6d4d21dcd4df54",
    "generated_image.find_any": "7a75b1fcb2ee6535e8a20fd557dc215f85dcca16f8486ddd42424bfbd252502e",
    "generated_image.get": "1f69ab654ec316d0375b8a79e9df1b761397b68c66c9378d41cd9382c5dfb870",
    "generated_image.insert": "cc87c20f85f4d986162e812b95e16ffb1ce92262007f974490184a3b6b390ff4",
    "generated_image.list_recent": "90e2b47f3b8a9f9b29625c76d36808161fd8f116756810f2c7b341c2b40e6539",
}


def _execute(spec, parameters: Dict[str, Any], *, principal_id: str, request_id: str):
    return execute_registered_operation(
        key=spec.key,
        version=spec.version,
        checksum=PINNED_CHECKSUMS[spec.key],
        parameters=parameters,
        principal_id=principal_id,
        request_id=request_id,
    )


def ensure_generated_image_store(*, request_id: str = "image-create") -> None:
    _execute(
        ENSURE_GENERATED_IMAGE_STORE,
        {"check": True},
        principal_id="system",
        request_id=request_id,
    )


def find_owner_generated_image(request_fingerprint: str, owner_id: Optional[str], *, request_id: str = "image-dedup"):
    return _execute(
        FIND_OWNER_GENERATED_IMAGE,
        {"request_fingerprint": request_fingerprint, "owner_id": owner_id},
        principal_id=owner_id or "anonymous",
        request_id=request_id,
    )


def find_any_generated_image(request_fingerprint: str, *, request_id: str = "image-dedup"):
    return _execute(
        FIND_ANY_GENERATED_IMAGE,
        {"request_fingerprint": request_fingerprint},
        principal_id="system",
        request_id=request_id,
    )


def read_generated_image(image_id: str, *, principal_id: str = "anonymous", request_id: str = "image-read"):
    return _execute(
        GET_GENERATED_IMAGE,
        {"image_id": image_id},
        principal_id=principal_id,
        request_id=request_id,
    )


def insert_generated_image(document: Dict[str, Any], *, principal_id: str = "anonymous", request_id: str = "image-write") -> None:
    doc_copy = dict(document)
    doc_copy.pop("_id", None)
    doc_copy.pop("image_data", None)
    doc_copy.pop("image_base64", None)
    doc_copy.pop("binary", None)
    doc_copy.pop("blob", None)
    allowed_fields = GeneratedImageDocument.model_fields.keys()
    cleaned = {k: v for k, v in doc_copy.items() if k in allowed_fields}
    result = _execute(
        INSERT_GENERATED_IMAGE,
        {"document": cleaned},
        principal_id=principal_id,
        request_id=request_id,
    )
    if not result or not result.get("inserted"):
        raise RuntimeError("Không thể lưu metadata hình ảnh")


def list_recent_generated_images(*, owner_id: Optional[str], is_admin: bool,
                                 is_authenticated: bool, limit: int,
                                 request_id: str = "image-list"):
    return _execute(
        LIST_RECENT_GENERATED_IMAGES,
        {
            "owner_id": owner_id,
            "is_admin": is_admin,
            "is_authenticated": is_authenticated,
            "limit": limit,
        },
        principal_id=owner_id or "anonymous",
        request_id=request_id,
    )
