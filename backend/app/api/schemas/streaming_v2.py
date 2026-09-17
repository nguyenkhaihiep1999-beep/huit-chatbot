"""
backend/app/api/schemas/streaming_v2.py
Định nghĩa Envelope và Payload Schemas chuẩn NDJSON Protocol v2:
- Canonical Event Set: start, token, progress, artifact, error, done, cancelled, heartbeat.
- Envelope thống nhất cho mọi event: protocol_version, stream_id, request_id, sequence, type, timestamp, payload.
- Sequence đơn điệu tăng dần (monotonically increasing: 1, 2, 3...).
- Strict Payload Schemas: mọi payload đều được validate chặt chẽ theo event type (extra="forbid").
- Giới hạn payload artifact < 2048 bytes (siêu nhẹ, chỉ mang manifest tóm tắt và URL).
- Tuyệt đối cấm Base64 và binary lớn trong payload stream.
- Compatibility Boundary: chuyển đổi hai chiều an toàn giữa Canonical v2 và Legacy Events (text_delta, completed, artifact_planned, meta, stream_started...).
- Core Producer tuyệt đối chỉ phát Canonical Events; không phát song song canonical và legacy.
"""
from datetime import datetime, timezone
import json
import re
from typing import Any, Dict, List, Literal, Optional, Union
from pydantic import BaseModel, ConfigDict, Field, model_validator

PROTOCOL_VERSION_V2 = 2
MAX_ARTIFACT_EVENT_BYTES = 2048

# Tập hợp các event types canonical duy nhất của NDJSON Protocol v2
CanonicalStreamEventType = Literal[
    "start",
    "token",
    "progress",
    "artifact",
    "error",
    "done",
    "cancelled",
    "heartbeat",
]

# Tập hợp các event types legacy để hỗ trợ tại Compatibility Boundary
LegacyStreamEventType = Literal[
    "stream_started",
    "text_delta",
    "artifact_planned",
    "preview_ready",
    "text_completed",
    "completed",
    "meta",
    "sources",
]

StreamEventType = Union[CanonicalStreamEventType, LegacyStreamEventType]

CANONICAL_EVENT_TYPES = {"start", "token", "progress", "artifact", "error", "done", "cancelled", "heartbeat"}
TERMINAL_EVENT_TYPES = {"done", "completed", "error", "cancelled"}

# Bảng ánh xạ hai chiều tại Compatibility Boundary
CANONICAL_TO_LEGACY_MAP: Dict[str, str] = {
    "start": "stream_started",
    "progress": "meta",
    "token": "text_delta",
    "artifact": "artifact_planned",
    "done": "completed",
    "error": "error",
    "cancelled": "cancelled",
    "heartbeat": "heartbeat",
}

LEGACY_TO_CANONICAL_MAP: Dict[str, str] = {
    "stream_started": "start",
    "meta": "progress",
    "sources": "progress",
    "artifact_planned": "artifact",
    "preview_ready": "artifact",
    "text_delta": "token",
    "text_completed": "token",
    "completed": "done",
    "done": "done",
    "error": "error",
    "cancelled": "cancelled",
    "heartbeat": "heartbeat",
}


def _check_no_base64_in_payload(val: Any):
    """Kiểm tra đệ quy chặn Base64 lớn trong payload."""
    if isinstance(val, str):
        if len(val) > 300 and ("data:image/" in val or "base64," in val):
            raise ValueError("Phát hiện Data URI Base64 trong payload stream!")
        if len(val) > 1000 and re.match(r"^[A-Za-z0-9+/=]{1000,}$", val):
            raise ValueError("Phát hiện chuỗi Base64 lớn trong payload stream!")
    elif isinstance(val, dict):
        for v in val.values():
            _check_no_base64_in_payload(v)
    elif isinstance(val, list):
        for item in val:
            _check_no_base64_in_payload(item)


# ---------------------------------------------------------------------------
# Strict Payload Models cho Canonical Events (extra="forbid")
# ---------------------------------------------------------------------------

class StreamStartPayload(BaseModel):
    """Payload cho sự kiện khởi đầu luồng (start)."""
    model_config = ConfigDict(extra="forbid")

    version: str = Field(default="2.0.0", max_length=32)
    timestamp: Optional[str] = Field(default=None, max_length=64)


class StreamProgressPayload(BaseModel):
    """Payload cho sự kiện tiến trình RAG & tra cứu tri thức (progress)."""
    model_config = ConfigDict(extra="forbid")

    stage: Optional[str] = Field(default=None, max_length=64)
    sources: List[Dict[str, Any]] = Field(default_factory=list)
    trace: List[Dict[str, Any]] = Field(default_factory=list)
    visual: Optional[Dict[str, Any]] = Field(default=None)
    cached: bool = Field(default=False)


class StreamTokenPayload(BaseModel):
    """Payload cho sự kiện sinh token văn bản (token)."""
    model_config = ConfigDict(extra="forbid")

    token: str = Field(..., description="Nội dung token mới sinh")
    delta: Optional[str] = Field(default=None, description="Alias tương thích ngược cho token")

    @model_validator(mode="before")
    @classmethod
    def populate_alias(cls, data: Any) -> Any:
        if isinstance(data, dict):
            t = data.get("token") or data.get("delta") or ""
            data["token"] = t
            data["delta"] = t
        return data


class StreamArtifactPayload(BaseModel):
    """Payload siêu nhẹ cho sự kiện công bố Artifact (< 2KB, cấm Base64)."""
    model_config = ConfigDict(extra="forbid")

    artifact_id: str = Field(..., min_length=1, max_length=128)
    type: str = Field(default="document", max_length=64)
    title: str = Field(..., max_length=255)
    preview_url: Optional[str] = Field(default="", max_length=500)
    manifest_url: Optional[str] = Field(default="", max_length=500)
    available_formats: List[str] = Field(default_factory=list)
    chart_type: Optional[str] = Field(default=None, max_length=64)
    status: Optional[str] = Field(default="planned", max_length=32)

    @model_validator(mode="after")
    def validate_size_and_no_base64(self) -> "StreamArtifactPayload":
        raw = json.dumps(self.model_dump(), ensure_ascii=False)
        byte_len = len(raw.encode("utf-8"))
        if byte_len > MAX_ARTIFACT_EVENT_BYTES:
            raise ValueError(f"Artifact payload vượt quá giới hạn cho phép: {byte_len} > {MAX_ARTIFACT_EVENT_BYTES} bytes")
        _check_no_base64_in_payload(self.model_dump())
        return self


class StreamDonePayload(BaseModel):
    """Payload cho sự kiện kết thúc luồng thành công (done - terminal event)."""
    model_config = ConfigDict(extra="forbid")

    latency_ms: float = Field(default=0.0, ge=0.0)
    cached: bool = Field(default=False)
    metrics: Optional[Dict[str, Any]] = Field(default=None)


class StreamErrorPayload(BaseModel):
    """Payload cho sự kiện kết thúc luồng do lỗi (error - terminal event)."""
    model_config = ConfigDict(extra="forbid")

    error_code: str = Field(..., min_length=1, max_length=128)
    message: str = Field(..., min_length=1, max_length=500)
    retryable: bool = Field(default=True)


class StreamCancelledPayload(BaseModel):
    """Payload cho sự kiện hủy luồng theo yêu cầu (cancelled - terminal event)."""
    model_config = ConfigDict(extra="forbid")

    detail: str = Field(default="Yêu cầu đã được hủy bởi người dùng", max_length=500)


class StreamHeartbeatPayload(BaseModel):
    """Payload cho sự kiện nhịp tim duy trì kết nối (heartbeat)."""
    model_config = ConfigDict(extra="forbid")

    status: str = Field(default="alive", max_length=32)


# ---------------------------------------------------------------------------
# Strict Payload Models cho Legacy Events tại Boundary
# ---------------------------------------------------------------------------

class StreamMetaPayload(BaseModel):
    """Legacy meta payload: tương thích ngược tại boundary."""
    model_config = ConfigDict(extra="forbid")

    sources: List[Dict[str, Any]] = Field(default_factory=list)
    trace: List[Dict[str, Any]] = Field(default_factory=list)
    cached: bool = Field(default=False)
    visual: Optional[Dict[str, Any]] = Field(default=None)


class StreamSourcesPayload(BaseModel):
    """Legacy sources payload: tương thích ngược tại boundary."""
    model_config = ConfigDict(extra="forbid")

    sources: List[Dict[str, Any]] = Field(default_factory=list)


class StreamTextCompletedPayload(BaseModel):
    """Legacy text_completed payload: tương thích ngược tại boundary."""
    model_config = ConfigDict(extra="forbid")

    length: int = Field(default=0, ge=0)


# ---------------------------------------------------------------------------
# Payload Validation Dispatcher
# ---------------------------------------------------------------------------

def validate_payload_for_type(event_type: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    """Validate payload chặt chẽ theo event type (extra="forbid"), cấm Dict[str, Any] không kiểm soát."""
    p = dict(payload or {})

    if event_type == "start":
        return StreamStartPayload(**p).model_dump(exclude_none=True)
    elif event_type in ("progress", "meta"):
        return StreamProgressPayload(**p).model_dump(exclude_none=True)
    elif event_type in ("token", "text_delta"):
        return StreamTokenPayload(**p).model_dump(exclude_none=True)
    elif event_type in ("artifact", "artifact_planned", "preview_ready"):
        art_dict = {
            "artifact_id": p.get("artifact_id") or p.get("id") or "planned_artifact",
            "type": p.get("type") or p.get("artifact_type") or p.get("file_type") or "document",
            "title": p.get("title") or "Tài liệu Tuyển sinh HUIT",
            "preview_url": p.get("preview_url") or "",
            "manifest_url": p.get("manifest_url") or "",
            "available_formats": p.get("available_formats") or ["xlsx", "docx", "pdf", "png", "svg"],
            "chart_type": p.get("chart_type"),
            "status": p.get("status") or ("ready" if event_type == "preview_ready" else "planned"),
        }
        return StreamArtifactPayload(**art_dict).model_dump(exclude_none=True)
    elif event_type in ("done", "completed"):
        return StreamDonePayload(**p).model_dump(exclude_none=True)
    elif event_type == "error":
        err_dict = {
            "error_code": p.get("error_code") or "STREAM_ERROR",
            "message": p.get("message") or "Đã xảy ra sự cố trong quá trình xử lý luồng.",
            "retryable": p.get("retryable", True),
        }
        return StreamErrorPayload(**err_dict).model_dump(exclude_none=True)
    elif event_type == "cancelled":
        return StreamCancelledPayload(**p).model_dump(exclude_none=True)
    elif event_type == "heartbeat":
        return StreamHeartbeatPayload(**p).model_dump(exclude_none=True)
    elif event_type == "sources":
        return StreamSourcesPayload(**p).model_dump(exclude_none=True)
    elif event_type == "text_completed":
        return StreamTextCompletedPayload(**p).model_dump(exclude_none=True)
    elif event_type == "stream_started":
        # Legacy start
        version = p.get("version") or p.get("protocol_version") or "2.0.0"
        ts = p.get("timestamp")
        return StreamStartPayload(version=str(version), timestamp=ts).model_dump(exclude_none=True)
    else:
        raise ValueError(f"Không nhận diện được event type hợp lệ: '{event_type}'")


# ---------------------------------------------------------------------------
# Envelope Model
# ---------------------------------------------------------------------------

class StreamEventEnvelope(BaseModel):
    """Envelope chuẩn NDJSON Protocol v2 thống nhất cho mọi event."""
    model_config = ConfigDict(extra="forbid")

    protocol_version: int = Field(default=PROTOCOL_VERSION_V2, ge=2, le=2)
    stream_id: str = Field(..., min_length=1, max_length=128)
    request_id: str = Field(..., min_length=1, max_length=128)
    sequence: int = Field(..., ge=1)
    type: StreamEventType
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    payload: Dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_envelope_safety_and_payload(self) -> "StreamEventEnvelope":
        _check_no_base64_in_payload(self.payload)
        # Kiểm tra payload khớp schema của type tương ứng
        validate_payload_for_type(self.type, self.payload)
        return self


# ---------------------------------------------------------------------------
# Compatibility Boundary Functions
# ---------------------------------------------------------------------------

def convert_legacy_to_canonical(event_dict: Dict[str, Any]) -> Dict[str, Any]:
    """Chuyển đổi một event dạng legacy sang canonical format tại boundary."""
    raw_type = event_dict.get("type", "")
    canonical_type = LEGACY_TO_CANONICAL_MAP.get(raw_type, raw_type)

    raw_payload = event_dict.get("payload")
    if raw_payload is None:
        raw_payload = event_dict.get("data", {})

    validated_payload = validate_payload_for_type(canonical_type, raw_payload)

    return {
        "protocol_version": PROTOCOL_VERSION_V2,
        "stream_id": event_dict.get("stream_id") or event_dict.get("request_id") or "stream_unknown",
        "request_id": event_dict.get("request_id") or event_dict.get("stream_id") or "req_unknown",
        "sequence": int(event_dict.get("sequence", 1)),
        "type": canonical_type,
        "timestamp": event_dict.get("timestamp") or datetime.now(timezone.utc).isoformat(),
        "payload": validated_payload,
    }


def convert_canonical_to_legacy(event_dict: Dict[str, Any]) -> Dict[str, Any]:
    """Chuyển đổi một event canonical sang format legacy cho client cũ tại boundary."""
    c_type = event_dict.get("type", "")
    legacy_type = CANONICAL_TO_LEGACY_MAP.get(c_type, c_type)

    payload = dict(event_dict.get("payload") or {})
    # Bổ sung các alias cũ trong payload cho client legacy nếu cần
    if legacy_type == "text_delta" and "token" in payload and "delta" not in payload:
        payload["delta"] = payload["token"]
    elif legacy_type == "meta" and "sources" not in payload:
        payload["sources"] = []

    return {
        "protocol_version": event_dict.get("protocol_version", PROTOCOL_VERSION_V2),
        "stream_id": event_dict.get("stream_id", ""),
        "request_id": event_dict.get("request_id", ""),
        "sequence": event_dict.get("sequence", 1),
        "type": legacy_type,
        "timestamp": event_dict.get("timestamp") or datetime.now(timezone.utc).isoformat(),
        "payload": payload,
    }


def create_ndjson_v2_event(
    event_type: str,
    sequence: int,
    stream_id: str,
    request_id: str,
    payload: Optional[Dict[str, Any]] = None,
    canonical_only: bool = True,
) -> str:
    """
    Tạo chuỗi NDJSON v2 với envelope và strict payload validation:
    - Nếu canonical_only=True (mặc định), event_type được tự động chuẩn hóa sang canonical type duy nhất.
    - Payload được validate bằng strict Pydantic model theo type (cấm extra fields và Base64).
    """
    final_type = event_type
    if canonical_only:
        final_type = LEGACY_TO_CANONICAL_MAP.get(event_type, event_type)

    validated_payload = validate_payload_for_type(final_type, payload or {})

    envelope = StreamEventEnvelope(
        protocol_version=PROTOCOL_VERSION_V2,
        stream_id=stream_id,
        request_id=request_id,
        sequence=sequence,
        type=final_type,  # type: ignore
        timestamp=datetime.now(timezone.utc).isoformat(),
        payload=validated_payload,
    )

    return json.dumps(envelope.model_dump(), ensure_ascii=False) + "\n"
