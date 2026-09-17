"""LTX domain adapter for anonymized telemetry operations (v2.0.0)."""
from datetime import datetime
from typing import Any, Dict, List, Optional

from backend.app.data_access.operation_gateway import execute_registered_operation
import backend.app.data_access.registered_operations.telemetry_operations_v2  # ensure registered

APPEND_EVENT_CHECKSUM = "e6ec0278a2b6f4dc26003489d39d52b7d7b3dbb183fc00d6ba2364c43a460287"
GET_RECENT_EVENTS_CHECKSUM = "af6755a05e645d58a8d6d1afc96deb4de8f1fcb7fd98087a17af837d9745dabb"
BATCH_APPEND_EVENTS_CHECKSUM = "6979e1eb9404401d4907cd153dba128d11d0b0f1d184a9f7b2c77086ab9f95ce"


def record_telemetry_event(
    event_data: Dict[str, Any],
    *,
    principal_id: str = "system",
    request_id: str = "internal",
) -> bool:
    """Ghi nhận một sự kiện telemetry ẩn danh qua Registered Operation Gateway."""
    res = execute_registered_operation(
        key="telemetry.append_event",
        version="2.0.0",
        checksum=APPEND_EVENT_CHECKSUM,
        parameters={"event": event_data},
        principal_id=principal_id,
        request_id=request_id,
    )
    return bool(res and res.get("inserted"))


def get_recent_telemetry_events(
    limit: int = 50,
    since: Optional[datetime] = None,
    *,
    principal_id: str = "system",
    request_id: str = "internal",
) -> List[Dict[str, Any]]:
    """Truy vấn các sự kiện telemetry gần nhất qua Registered Operation Gateway."""
    res = execute_registered_operation(
        key="telemetry.get_recent_events",
        version="2.0.0",
        checksum=GET_RECENT_EVENTS_CHECKSUM,
        parameters={
            "limit": limit,
            "since": since,
        },
        principal_id=principal_id,
        request_id=request_id,
    )
    if res and "events" in res:
        return res["events"]
    return []


def batch_record_telemetry_events(
    events: List[Dict[str, Any]],
    *,
    principal_id: str = "system",
    request_id: str = "internal",
) -> int:
    """Ghi nhận một lô sự kiện telemetry ẩn danh qua Registered Operation Gateway."""
    res = execute_registered_operation(
        key="telemetry.batch_append_events",
        version="2.0.0",
        checksum=BATCH_APPEND_EVENTS_CHECKSUM,
        parameters={"events": events},
        principal_id=principal_id,
        request_id=request_id,
    )
    return res.get("inserted_count", 0) if res else 0
