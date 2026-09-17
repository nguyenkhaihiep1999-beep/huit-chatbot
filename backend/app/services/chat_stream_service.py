"""
Chat Stream Service facade module, providing backward and forward compatibility for stream coordination.
"""
from backend.app.services.stream_coordinator import (
    StreamCoordinator,
    StreamSession,
    get_stream_coordinator,
    compute_request_signature,
    canonical_control_event,
)

__all__ = [
    "StreamCoordinator",
    "StreamSession",
    "get_stream_coordinator",
    "compute_request_signature",
    "canonical_control_event",
]
