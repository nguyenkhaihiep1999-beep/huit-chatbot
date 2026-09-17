"""LTX domain adapter for admin sessions operations (v2.0.0)."""
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from backend.app.data_access.operation_gateway import execute_registered_operation
import backend.app.data_access.registered_operations.admin_session_operations_v2 as admin_op_module


def save_admin_session_ltx(
    session_hash: str,
    session_id: str,
    admin_id: str,
    expires_at: datetime,
    ip_address: Optional[str] = None,
    user_agent: Optional[str] = None,
    *,
    principal_id: str = "system",
    request_id: str = "internal",
) -> bool:
    """Lưu session hash của admin qua Registered Operation Gateway."""
    spec = next(s for s in admin_op_module._SPECS if s.key == "admin_session.create")
    res = execute_registered_operation(
        key="admin_session.create",
        version="2.0.0",
        checksum=spec.checksum,
        parameters={
            "session_hash": session_hash,
            "session_id": session_id,
            "admin_id": admin_id,
            "expires_at": expires_at,
            "ip_address": ip_address,
            "user_agent": user_agent,
        },
        principal_id=principal_id,
        request_id=request_id,
    )
    return bool(res and res.get("created"))


def find_valid_admin_session_ltx(
    session_hash: str,
    *,
    principal_id: str = "system",
    request_id: str = "internal",
) -> Optional[Dict[str, Any]]:
    """Tra cứu session hợp lệ của admin qua Registered Operation Gateway."""
    spec = next(s for s in admin_op_module._SPECS if s.key == "admin_session.find_valid")
    res = execute_registered_operation(
        key="admin_session.find_valid",
        version="2.0.0",
        checksum=spec.checksum,
        parameters={"session_hash": session_hash},
        principal_id=principal_id,
        request_id=request_id,
    )
    if res and res.get("found"):
        return res
    return None


def revoke_admin_session_ltx(
    session_hash: str,
    *,
    principal_id: str = "system",
    request_id: str = "internal",
) -> bool:
    """Thu hồi session của admin qua Registered Operation Gateway."""
    spec = next(s for s in admin_op_module._SPECS if s.key == "admin_session.revoke")
    res = execute_registered_operation(
        key="admin_session.revoke",
        version="2.0.0",
        checksum=spec.checksum,
        parameters={"session_hash": session_hash},
        principal_id=principal_id,
        request_id=request_id,
    )
    return bool(res and res.get("revoked"))


def purge_expired_admin_sessions_ltx(
    before: Optional[datetime] = None,
    *,
    principal_id: str = "system",
    request_id: str = "internal",
) -> int:
    """Dọn dẹp các session đã hết hạn qua Registered Operation Gateway."""
    spec = next(s for s in admin_op_module._SPECS if s.key == "admin_session.purge_expired")
    res = execute_registered_operation(
        key="admin_session.purge_expired",
        version="2.0.0",
        checksum=spec.checksum,
        parameters={"before": before},
        principal_id=principal_id,
        request_id=request_id,
    )
    return int(res.get("deleted_count", 0)) if res else 0
