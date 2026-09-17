"""LTX domain adapter for physical assets and logical artifacts operations (v2.0.0)."""
from typing import Any, Dict, List, Optional

from backend.app.data_access.operation_gateway import execute_registered_operation
import backend.app.data_access.registered_operations.asset_operations_v2  # ensure registered

FIND_ASSET_BY_ID_CHECKSUM = "a53c2a6d537a80775d487ad29258cad947e57a770fbb25ba05e9d5461ac8bd17"
FIND_ASSET_BY_CONTENT_HASH_CHECKSUM = "2b97c97a39bfb1e95206909b40350a274942412b186ab11a7fd05e57f0886f5f"
FIND_DERIVATIVE_CHECKSUM = "4745fb464593cc2a4f113392f5613f56d48a7a949879b076cd96c5638a2ac077"
TOUCH_ASSET_CHECKSUM = "14c7e20b531da5687539fa391f53199e36ac77aad022b695ebdbecc75238cd3c"
UPSERT_ASSET_CHECKSUM = "85020532424df02ab316f39b81add06c8e145c5939db4cb7605702e784e35f4c"
DELETE_ASSET_CHECKSUM = "54b3bc072c0dbf8586b47d2f80fb2430173f262924679f3e85db29b89115be0f"
FIND_ARTIFACT_BY_ID_CHECKSUM = "240aa1a83ecd573268ee356345672e6167ef29acf1da2a69e18d89c5f593a6fe"
FIND_ARTIFACT_BY_OWNER_AND_HASH_CHECKSUM = "cc9e624450e9e38a2732b1b158bba8ef646e8491363e7057c8b84fc6ba39b5e6"
UPSERT_ARTIFACT_CHECKSUM = "f7acb48ec3a9ca6eb68233cf12f05108ebe84f69807532c0a406acf3d659cd1c"


def find_asset_by_id(
    asset_id: str,
    *,
    principal_id: str = "system",
    request_id: str = "internal",
) -> Optional[Dict[str, Any]]:
    """Tra cứu physical asset theo ID qua Registered Operation Gateway."""
    res = execute_registered_operation(
        key="assets.find_by_id",
        version="2.0.0",
        checksum=FIND_ASSET_BY_ID_CHECKSUM,
        parameters={"asset_id": asset_id},
        principal_id=principal_id,
        request_id=request_id,
    )
    if res and res.get("found"):
        return res.get("asset")
    return None


def find_asset_by_content_hash(
    content_hash: str,
    touch: bool = True,
    *,
    principal_id: str = "system",
    request_id: str = "internal",
) -> Optional[Dict[str, Any]]:
    """Tra cứu physical asset theo content hash có tùy chọn touch qua Registered Operation Gateway."""
    res = execute_registered_operation(
        key="assets.find_by_content_hash",
        version="2.0.0",
        checksum=FIND_ASSET_BY_CONTENT_HASH_CHECKSUM,
        parameters={"content_hash": content_hash, "touch": touch},
        principal_id=principal_id,
        request_id=request_id,
    )
    if res and res.get("found"):
        return res.get("asset")
    return None


def find_derivative_asset(
    source_asset_id: str,
    scale: int,
    file_ext: str,
    *,
    principal_id: str = "system",
    request_id: str = "internal",
) -> Optional[Dict[str, Any]]:
    """Tra cứu derivative asset đã tồn tại qua Registered Operation Gateway."""
    res = execute_registered_operation(
        key="assets.find_derivative",
        version="2.0.0",
        checksum=FIND_DERIVATIVE_CHECKSUM,
        parameters={
            "source_asset_id": source_asset_id,
            "scale": scale,
            "file_ext": file_ext,
        },
        principal_id=principal_id,
        request_id=request_id,
    )
    if res and res.get("found"):
        return res.get("asset")
    return None


def touch_asset(
    asset_id: str,
    *,
    principal_id: str = "system",
    request_id: str = "internal",
) -> bool:
    """Cập nhật last_accessed_at và reference_count cho asset qua Registered Operation Gateway."""
    res = execute_registered_operation(
        key="assets.touch",
        version="2.0.0",
        checksum=TOUCH_ASSET_CHECKSUM,
        parameters={"asset_id": asset_id},
        principal_id=principal_id,
        request_id=request_id,
    )
    return bool(res and res.get("touched"))


def upsert_asset_metadata(
    asset_doc: Dict[str, Any],
    *,
    principal_id: str = "system",
    request_id: str = "internal",
) -> bool:
    """Lưu/cập nhật metadata của physical asset qua Registered Operation Gateway."""
    res = execute_registered_operation(
        key="assets.upsert_metadata",
        version="2.0.0",
        checksum=UPSERT_ASSET_CHECKSUM,
        parameters={"asset": asset_doc},
        principal_id=principal_id,
        request_id=request_id,
    )
    return bool(res and res.get("acknowledged"))


def delete_asset_record(
    asset_id: str,
    *,
    principal_id: str = "system",
    request_id: str = "internal",
) -> bool:
    """Bồi hoàn/xóa bản ghi metadata asset chưa được tham chiếu qua Registered Operation Gateway."""
    res = execute_registered_operation(
        key="assets.delete_record",
        version="2.0.0",
        checksum=DELETE_ASSET_CHECKSUM,
        parameters={"asset_id": asset_id},
        principal_id=principal_id,
        request_id=request_id,
    )
    return bool(res and res.get("deleted"))


def find_artifact_by_id(
    artifact_id: str,
    *,
    principal_id: str = "system",
    request_id: str = "internal",
) -> Optional[Dict[str, Any]]:
    """Tra cứu logical artifact theo ID qua Registered Operation Gateway."""
    res = execute_registered_operation(
        key="artifacts.find_by_id",
        version="2.0.0",
        checksum=FIND_ARTIFACT_BY_ID_CHECKSUM,
        parameters={"artifact_id": artifact_id},
        principal_id=principal_id,
        request_id=request_id,
    )
    if res and res.get("found"):
        return res.get("artifact")
    return None


def find_artifact_by_owner_and_hash(
    content_hash: str,
    owner_id: Optional[str] = None,
    *,
    principal_id: str = "system",
    request_id: str = "internal",
) -> Optional[Dict[str, Any]]:
    """Tra cứu logical artifact theo content hash và owner_id qua Registered Operation Gateway."""
    res = execute_registered_operation(
        key="artifacts.find_by_owner_and_hash",
        version="2.0.0",
        checksum=FIND_ARTIFACT_BY_OWNER_AND_HASH_CHECKSUM,
        parameters={"content_hash": content_hash, "owner_id": owner_id},
        principal_id=principal_id,
        request_id=request_id,
    )
    if res and res.get("found"):
        return res.get("artifact")
    return None


def upsert_artifact_ownership(
    artifact_doc: Dict[str, Any],
    *,
    principal_id: str = "system",
    request_id: str = "internal",
) -> bool:
    """Lưu/cập nhật quyền sở hữu và manifest logical artifact qua Registered Operation Gateway."""
    res = execute_registered_operation(
        key="artifacts.upsert_ownership",
        version="2.0.0",
        checksum=UPSERT_ARTIFACT_CHECKSUM,
        parameters={"artifact": artifact_doc},
        principal_id=principal_id,
        request_id=request_id,
    )
    return bool(res and res.get("acknowledged"))
