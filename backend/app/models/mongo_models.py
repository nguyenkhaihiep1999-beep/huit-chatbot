"""
mongo_models.py
Pydantic Models chuẩn hóa cho các document lưu trữ trong MongoDB Atlas:
- Quản lý schema_version cho từng collection.
- Ép kiểu datetime UTC (BSON Date) nhất quán, loại bỏ lưu trữ string ISO date.
- extra="forbid" ngăn chặn các trường tùy ý và dữ liệu rác.
- Loại trừ Base64 và binary lớn khỏi MongoDB documents.
- Hỗ trợ chuyển đổi từ document legacy sang model chuẩn và serialize BSON.
"""
from datetime import datetime, timezone
import re
from typing import Annotated, Any, Dict, List, Literal, Optional, Union
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# Hằng số giới hạn
MAX_FILE_SIZE = 52428800  # 50 MB
MAX_MANIFEST_SIZE = 32768  # 32 KB
MAX_EVENTS_COUNT = 30
MAX_SOURCE_TITLES = 20

# Safe regex patterns
SAFE_STORAGE_KEY_REGEX = r"^[^/\\\.][a-zA-Z0-9_\-\.]+$"
SAFE_ID_REGEX = r"^[a-zA-Z0-9_\-\.]+$"
SHA256_HEX_REGEX = r"^[a-f0-9]{64}(:scale_[1-4]:[a-z0-9]+)?$"


def ensure_utc_datetime(v: Any) -> datetime:
    """Chuyển đổi chuỗi ISO hoặc timestamp thành datetime UTC chuẩn."""
    if isinstance(v, datetime):
        if v.tzinfo is None:
            return v.replace(tzinfo=timezone.utc)
        return v.astimezone(timezone.utc)
    if isinstance(v, str):
        # Parse ISO string
        s = v.replace("Z", "+00:00")
        try:
            dt = datetime.fromisoformat(s)
            if dt.tzinfo is None:
                return dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
        except ValueError:
            raise ValueError(f"Không thể parse chuỗi ngày giờ: {v}")
    if isinstance(v, (int, float)):
        return datetime.fromtimestamp(v, tz=timezone.utc)
    raise ValueError(f"Giá trị ngày giờ không hợp lệ: {v}")


def check_no_large_base64(val: Any, max_len: int = 1000):
    """Đệ quy kiểm tra và chặn các chuỗi Base64 lớn."""
    if isinstance(val, str):
        if len(val) > 400 and re.search(r"data:[a-zA-Z0-9/]+;base64,", val):
            raise ValueError("Phát hiện Data URI Base64 trong MongoDB document!")
        if len(val) > max_len and re.match(r"^[A-Za-z0-9+/=]{1000,}$", val):
            raise ValueError("Phát hiện chuỗi Base64 lớn trong MongoDB document!")
    elif isinstance(val, dict):
        for k, v in val.items():
            check_no_large_base64(v, max_len)
    elif isinstance(val, list):
        for item in val:
            check_no_large_base64(item, max_len)


# ==============================================================================
# 0. CHUẨN HÓA CÁC NESTED MODELS RÕ RÀNG (EXTRA='FORBID')
# ==============================================================================
Color = Annotated[str, Field(pattern=r"^#[0-9a-fA-F]{6}$")]
Coord = Annotated[int, Field(ge=0, le=1024)]

class Shape(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    x: Coord
    y: Coord
    fill: Color

class Rect(Shape):
    type: Literal["rect"]
    width: Coord
    height: Coord

class Circle(Shape):
    type: Literal["circle"]
    radius: Annotated[int, Field(ge=1, le=512)]

class Text(Shape):
    type: Literal["text"]
    text: Annotated[str, Field(min_length=1, max_length=160)]
    size: Annotated[int, Field(ge=8, le=120)]

class Polygon(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    type: Literal["polygon"]
    fill: Color
    points: Annotated[list[Annotated[list[Coord], Field(min_length=2, max_length=2)]], Field(min_length=3, max_length=32)]

class Scene(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    background: Color
    shapes: Annotated[list[Annotated[Union[Rect, Circle, Text, Polygon], Field(discriminator="type")]], Field(min_length=1, max_length=100)]


class CutoffBoxItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    year: Optional[Union[int, str]] = None
    method: Optional[str] = None
    score: Optional[Union[float, str]] = None
    note: Optional[str] = None


class JobErrorDetail(BaseModel):
    model_config = ConfigDict(extra="forbid")
    error_code: str = Field(default="UNKNOWN_ERROR", max_length=128)
    message: str = Field(default="", max_length=1000)
    request_id: Optional[str] = Field(default=None, max_length=64)
    job_id: Optional[str] = Field(default=None, max_length=128)
    artifact_id: Optional[str] = Field(default=None, max_length=128)
    stage: Optional[str] = Field(default=None, max_length=64)
    module: Optional[str] = Field(default=None, max_length=64)
    retryable: Optional[bool] = False
    details: Optional[str] = Field(default=None, max_length=1000)

    @field_validator("details", mode="before")
    @classmethod
    def serialize_details(cls, v: Any) -> Optional[str]:
        if v is None:
            return None
        if isinstance(v, str):
            return v[:1000]
        import json
        try:
            return json.dumps(v, ensure_ascii=False)[:1000]
        except Exception:
            return str(v)[:1000]


class QueryCacheSourceItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    i: Optional[int] = None
    title: str = Field(default="", max_length=500)
    url: Optional[str] = Field(default="", max_length=1000)
    score: Optional[float] = None
    text: Optional[str] = Field(default=None, max_length=5000)


class QueryCacheTraceItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    step: Optional[int] = None
    name: str = Field(default="", max_length=200)
    detail: Optional[str] = Field(default=None, max_length=1000)
    status: Optional[str] = Field(default="success", max_length=50)
    elapsed_ms: Optional[float] = None


class QueryCacheTimings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    cache_lookup: Optional[float] = None
    embedding: Optional[float] = None
    vector_search: Optional[float] = None
    keyword_search: Optional[float] = None
    rerank: Optional[float] = None
    visual_lookup: Optional[float] = None
    llm_ttft: Optional[float] = None
    llm_generation: Optional[float] = None
    cache_write: Optional[float] = None
    total: Optional[float] = None


class QueryCacheVisual(BaseModel):
    model_config = ConfigDict(extra="forbid")
    visual_id: Optional[str] = None
    major_code: Optional[str] = None
    category: Optional[str] = None
    title: Optional[str] = None
    faculty: Optional[str] = None
    duration: Optional[str] = None
    tuition: Optional[str] = None
    subject_combinations: List[str] = Field(default_factory=list)
    career_highlights: List[str] = Field(default_factory=list)
    cutoff_boxes: List[CutoffBoxItem] = Field(default_factory=list)
    scholarship_highlight: Optional[str] = None
    source_url: Optional[str] = None
    type: Optional[str] = "admission_visual"
    storage_key: Optional[str] = None
    artifact_id: Optional[str] = None
    view_url: Optional[str] = None
    download_url: Optional[str] = None


class QueryCacheMeta(BaseModel):
    model_config = ConfigDict(extra="forbid")
    intent: Optional[str] = None
    cached: Optional[bool] = False
    latency_ms: Optional[float] = None
    model: Optional[str] = None
    timings: Optional[QueryCacheTimings] = None
    sources: Optional[List[QueryCacheSourceItem]] = None
    visual: Optional[QueryCacheVisual] = None
    ram_cached: Optional[bool] = False
    test: Optional[bool] = None
    rewritten_query: Optional[str] = None
    classification: Optional[str] = None
    confidence: Optional[float] = None
    rag_mode: Optional[str] = None


# ==============================================================================
# 1. PHYSICAL ASSET / BLOB RECORD
# ==============================================================================
class MongoAssetRecord(BaseModel):
    """
    Physical Asset / Blob Document lưu trong collection `assets`.
    Chỉ lưu thông tin file vật lý đã chuẩn hóa, độc lập với người dùng sở hữu.
    """
    model_config = ConfigDict(extra="forbid")

    schema_version: int = Field(default=1, ge=1)
    asset_id: str = Field(..., pattern=SAFE_ID_REGEX, min_length=4, max_length=64)
    content_hash: str = Field(..., pattern=r"^[a-zA-Z0-9_\-\.:]{4,128}$")
    checksum: Optional[str] = Field(default="", max_length=128)
    storage_key: str = Field(default="", pattern=r"^$|^[^/\\\.][a-zA-Z0-9_\-\.]+$", max_length=255)
    media_type: str = Field(..., pattern=r"^(application|image|audio|video)/[a-zA-Z0-9\.\-\+]+$")

    file_ext: str = Field(..., min_length=1, max_length=10)
    file_size: int = Field(..., ge=0, le=MAX_FILE_SIZE)
    preview_key: Optional[str] = Field(default="", max_length=255)
    width: Optional[int] = Field(default=None, ge=1, le=8192)
    height: Optional[int] = Field(default=None, ge=1, le=8192)
    duration: Optional[float] = Field(default=None, ge=0.0)
    scale: Optional[int] = Field(default=None, ge=1, le=4)
    reference_count: int = Field(default=1, ge=1)
    renderer_version: str = Field(..., min_length=1, max_length=64)
    source_asset_id: Optional[str] = Field(default=None, max_length=64)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    last_accessed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    is_archived_duplicate: Optional[bool] = Field(default=False)

    @field_validator("created_at", "last_accessed_at", mode="before")
    @classmethod
    def validate_dates(cls, v: Any) -> datetime:
        return ensure_utc_datetime(v)

    @field_validator("storage_key")
    @classmethod
    def validate_storage_key_safety(cls, v: str) -> str:
        if ".." in v or "/" in v or "\\" in v:
            raise ValueError(f"storage_key chứa ký tự không an toàn (path traversal): {v}")
        return v

    @classmethod
    def from_legacy(cls, doc: Dict[str, Any]) -> "MongoAssetRecord":
        """Chuyển đổi từ document legacy sang MongoAssetRecord (loại bỏ manifest/owner sang artifacts)."""
        d = dict(doc)
        d.pop("_id", None)
        d.pop("owner_id", None)
        d.pop("manifest", None)
        d["schema_version"] = d.get("schema_version", 1)
        if "created_at" in d:
            d["created_at"] = ensure_utc_datetime(d["created_at"])
        if "last_accessed_at" in d:
            d["last_accessed_at"] = ensure_utc_datetime(d["last_accessed_at"])
        allowed_keys = cls.model_fields.keys()
        cleaned = {k: v for k, v in d.items() if k in allowed_keys}
        return cls(**cleaned)


# ==============================================================================
# 2. LOGICAL ARTIFACT / OWNERSHIP RECORD
# ==============================================================================
class MongoArtifactRecord(BaseModel):
    """
    Logical Artifact Record quản lý quyền sở hữu (Ownership) và manifest nghiệp vụ trong collection `artifacts`.
    Tách biệt hoàn toàn với file vật lý, tránh rò rỉ quyền riêng tư khi deduplication.
    """
    model_config = ConfigDict(extra="forbid")

    schema_version: int = Field(default=1, ge=1)
    artifact_id: str = Field(..., pattern=SAFE_ID_REGEX, min_length=4, max_length=64)
    owner_id: Optional[str] = Field(default=None, max_length=64)
    access_scope: Literal["public", "private"] = Field(default="public")
    blob_id: Optional[str] = Field(default=None, max_length=64, description="ID của physical asset blob")
    content_hash: Optional[str] = Field(default=None, pattern=r"^[a-zA-Z0-9_\-\.:]{4,128}$")
    manifest: Dict[str, Any] = Field(..., description="Ultralight JSON Manifest")
    source_artifact_id: Optional[str] = Field(default=None, max_length=64)
    derivative_spec: Optional[Dict[str, Any]] = Field(default=None)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @field_validator("created_at", "updated_at", mode="before")
    @classmethod
    def validate_dates(cls, v: Any) -> datetime:
        return ensure_utc_datetime(v)

    @model_validator(mode="after")
    def validate_manifest_safety(self) -> "MongoArtifactRecord":
        check_no_large_base64(self.manifest)
        import json
        size = len(json.dumps(self.manifest, ensure_ascii=False).encode("utf-8"))
        if size > MAX_MANIFEST_SIZE:
            raise ValueError(f"Manifest kích thước {size} bytes vượt quá ngưỡng {MAX_MANIFEST_SIZE} bytes")
        return self

    @classmethod
    def from_legacy(cls, doc: Dict[str, Any]) -> "MongoArtifactRecord":
        """Chuyển đổi từ document legacy (assets hoặc manifest) sang MongoArtifactRecord."""
        d = dict(doc)
        d.pop("_id", None)
        d["schema_version"] = d.get("schema_version", 1)
        art_id = d.get("artifact_id") or d.get("asset_id") or ""
        d["artifact_id"] = art_id
        d["blob_id"] = d.get("blob_id") or d.get("asset_id") or art_id
        d["owner_id"] = d.get("owner_id")
        d["manifest"] = d.get("manifest") or {}
        d["access_scope"] = d.get("access_scope", "public" if not d["owner_id"] else "private")
        if "created_at" in d:
            d["created_at"] = ensure_utc_datetime(d["created_at"])
        if "updated_at" in d:
            d["updated_at"] = ensure_utc_datetime(d["updated_at"])
        elif "created_at" in d:
            d["updated_at"] = d["created_at"]
        allowed_keys = cls.model_fields.keys()
        cleaned = {k: v for k, v in d.items() if k in allowed_keys}
        return cls(**cleaned)


# ==============================================================================
# 3. BACKGROUND JOB & EVENTS
# ==============================================================================
class MongoJobEvent(BaseModel):
    """Sự kiện tiến trình của một job."""
    model_config = ConfigDict(extra="forbid")

    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    status: Literal["queued", "processing", "completed", "failed", "cancelled"]
    progress: int = Field(..., ge=0, le=100)
    detail: str = Field(..., max_length=500)

    @field_validator("timestamp", mode="before")
    @classmethod
    def validate_timestamp(cls, v: Any) -> datetime:
        return ensure_utc_datetime(v)


class MongoJobRecord(BaseModel):
    """Document lưu trữ công việc nền trong collection `jobs`."""
    model_config = ConfigDict(extra="forbid")

    schema_version: int = Field(default=1, ge=1)
    job_id: str = Field(..., pattern=r"^job_[a-zA-Z0-9_\-]+$", min_length=8, max_length=64)
    owner_id: Optional[str] = Field(default=None, max_length=64)
    request_id: Optional[str] = Field(default=None, max_length=64)
    idempotency_key: Optional[str] = Field(default=None, max_length=128)
    action: str = Field(..., min_length=1, max_length=64)
    artifact_id: Optional[str] = Field(default=None, max_length=64)
    format: Optional[str] = Field(default=None, max_length=16)
    status: Literal["queued", "processing", "completed", "failed", "cancelled"] = Field(default="queued")
    progress: int = Field(default=0, ge=0, le=100)
    attempt: int = Field(default=0, ge=0)
    max_attempts: int = Field(default=3, ge=1, le=10)
    retries: int = Field(default=0, ge=0, le=10)
    lease_owner: Optional[str] = Field(default=None, max_length=128)
    lease_expires_at: Optional[datetime] = Field(default=None)
    heartbeat_at: Optional[datetime] = Field(default=None)
    available_at: Optional[datetime] = Field(default=None)
    sanitized_error: Optional[str] = Field(default=None, max_length=500)
    result_url: Optional[str] = Field(default=None, max_length=500)
    media_type: Optional[str] = Field(default=None, max_length=100)
    error: Optional[JobErrorDetail] = Field(default=None)
    events: List[MongoJobEvent] = Field(default_factory=list, max_length=MAX_EVENTS_COUNT)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    expires_at: Optional[datetime] = Field(default=None)

    @field_validator("created_at", "updated_at", "expires_at", "lease_expires_at", "heartbeat_at", "available_at", mode="before")
    @classmethod
    def validate_dates(cls, v: Any) -> Optional[datetime]:
        if v is None:
            return None
        return ensure_utc_datetime(v)

    @classmethod
    def from_legacy(cls, doc: Dict[str, Any]) -> "MongoJobRecord":
        d = dict(doc)
        d.pop("_id", None)
        d["schema_version"] = d.get("schema_version", 1)
        if "created_at" in d:
            d["created_at"] = ensure_utc_datetime(d["created_at"])
        if "updated_at" in d:
            d["updated_at"] = ensure_utc_datetime(d["updated_at"])
        d["attempt"] = d.get("attempt", d.get("retries", 0))
        d["max_attempts"] = d.get("max_attempts", 3)
        d["idempotency_key"] = d.get("idempotency_key", d.get("job_id"))
        d["available_at"] = ensure_utc_datetime(d.get("available_at", d.get("created_at", datetime.now(timezone.utc))))
        # Format events
        raw_events = d.get("events", [])
        cleaned_events = []
        for e in raw_events:
            if isinstance(e, dict):
                cleaned_events.append(MongoJobEvent(
                    timestamp=ensure_utc_datetime(e.get("timestamp", datetime.now(timezone.utc))),
                    status=e.get("status", "processing"),
                    progress=int(e.get("progress", 0)),
                    detail=str(e.get("detail", ""))[:500]
                ))
        d["events"] = cleaned_events[-MAX_EVENTS_COUNT:]
        allowed_keys = cls.model_fields.keys()
        cleaned = {k: v for k, v in d.items() if k in allowed_keys}
        return cls(**cleaned)


# ==============================================================================
# 4. GENERATED IMAGES (RASTER & VECTOR)
# ==============================================================================
class MongoGeneratedImageRecord(BaseModel):
    """Document metadata hình ảnh sinh bởi FLUX hoặc SVG trong collection `generated_images`."""
    model_config = ConfigDict(extra="forbid")

    schema_version: int = Field(default=1, ge=1)
    image_id: str = Field(..., pattern=r"^[a-f0-9]{24,64}$", min_length=24, max_length=64)
    blob_id: Optional[str] = Field(default=None, max_length=64)
    owner_id: Optional[str] = Field(default=None, max_length=64)
    access_scope: Literal["public", "private", "legacy_public"] = Field(default="public")
    backend: Literal["flux", "svg"]
    content_hash: str = Field(..., max_length=128)
    canonical_content_hash: Optional[str] = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    request_fingerprint: Optional[str] = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    generation_key: Optional[str] = Field(default=None, max_length=128)
    model: str = Field(..., max_length=100)
    seed: Optional[int] = Field(default=None)
    style: Optional[str] = Field(default="photorealistic", max_length=50)
    width: int = Field(default=512, ge=64, le=4096)
    height: int = Field(default=512, ge=64, le=4096)
    storage_key: Optional[str] = Field(default=None, pattern=SAFE_STORAGE_KEY_REGEX, max_length=255)
    thumbnail_key: Optional[str] = Field(default=None, pattern=SAFE_STORAGE_KEY_REGEX, max_length=255)
    content_type: Optional[str] = Field(default=None, max_length=50)
    byte_size: Optional[int] = Field(default=None, ge=0, le=MAX_FILE_SIZE)
    thumb_size: Optional[int] = Field(default=None, ge=0, le=1048576)
    scene: Optional[Scene] = Field(default=None)
    scene_bytes: Optional[int] = Field(default=None, ge=0)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    is_archived_duplicate: Optional[bool] = Field(default=False)

    @field_validator("created_at", mode="before")
    @classmethod
    def validate_created_at(cls, v: Any) -> datetime:
        return ensure_utc_datetime(v)

    @model_validator(mode="after")
    def validate_no_raw_binary(self) -> "MongoGeneratedImageRecord":
        if self.scene:
            check_no_large_base64(self.scene)
        return self

    @classmethod
    def from_legacy(cls, doc: Dict[str, Any]) -> "MongoGeneratedImageRecord":
        import hashlib
        d = dict(doc)
        doc_id = str(doc.get("_id", ""))
        d.pop("_id", None)
        # Bỏ qua raw binary nếu có (sẽ được trích xuất sang file vật lý trước)
        d.pop("image_data", None)
        d["schema_version"] = d.get("schema_version", 1)
        d["image_id"] = d.get("image_id") or doc_id
        if not d.get("content_hash"):
            p = d.get("prompt") or doc_id
            d["content_hash"] = hashlib.sha256(p.encode("utf-8")).hexdigest()
        d["generation_key"] = d.get("generation_key") or d["content_hash"]
        d["model"] = d.get("model") or ("openrouter/free" if d.get("scene") else "FLUX.1-schnell")
        backend = "svg" if d.get("scene") else "flux"
        d["backend"] = d.get("backend", backend)
        if "created_at" in d:
            d["created_at"] = ensure_utc_datetime(d["created_at"])
        allowed_keys = cls.model_fields.keys()
        cleaned = {k: v for k, v in d.items() if k in allowed_keys}
        return cls(**cleaned)



# ==============================================================================
# 5. QUERY CACHE RECORD
# ==============================================================================
class MongoQueryCacheRecord(BaseModel):
    """Document bộ nhớ đệm câu trả lời RAG trong collection `query_cache`."""
    model_config = ConfigDict(extra="forbid")

    schema_version: int = Field(default=1, ge=1)
    cache_key: str = Field(..., pattern=r"^[a-f0-9]{64}$")
    question_hash: str = Field(..., pattern=r"^[a-f0-9]{64}$")
    question_len: int = Field(..., ge=1, le=5000)
    question_clean: Optional[str] = Field(default=None, max_length=500)
    answer: str = Field(..., min_length=1)
    sources: List[QueryCacheSourceItem] = Field(default_factory=list)
    trace: List[QueryCacheTraceItem] = Field(default_factory=list)
    meta: QueryCacheMeta = Field(default_factory=QueryCacheMeta)
    visual: Optional[QueryCacheVisual] = None
    kb_version: str = Field(..., max_length=100)
    rag_version: str = Field(..., max_length=100)
    model: str = Field(..., max_length=100)
    created_at: Optional[datetime] = Field(default=None)
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    expires_at: datetime

    @field_validator("created_at", "updated_at", "expires_at", mode="before")
    @classmethod
    def validate_dates(cls, v: Any) -> Optional[datetime]:
        if v is None:
            return None
        return ensure_utc_datetime(v)

    @field_validator("trace", mode="before")
    @classmethod
    def validate_trace_items(cls, v: Any) -> List[Any]:
        if not isinstance(v, list):
            return []
        cleaned = []
        for item in v:
            if isinstance(item, str):
                cleaned.append({"name": item})
            else:
                cleaned.append(item)
        return cleaned

    @model_validator(mode="after")
    def validate_no_raw_privacy_or_base64(self) -> "MongoQueryCacheRecord":
        check_no_large_base64(self.meta)
        return self

    @classmethod
    def from_legacy(cls, doc: Dict[str, Any]) -> "MongoQueryCacheRecord":
        d = dict(doc)
        d.pop("_id", None)
        # Loại bỏ trường nhạy cảm lộ privacy
        d.pop("original_question", None)
        d["schema_version"] = d.get("schema_version", 1)
        if "created_at" in d and d["created_at"]:
            d["created_at"] = ensure_utc_datetime(d["created_at"])
        if "updated_at" in d:
            d["updated_at"] = ensure_utc_datetime(d["updated_at"])
        if "expires_at" in d:
            d["expires_at"] = ensure_utc_datetime(d["expires_at"])
        # Làm sạch meta nếu có image_base64
        meta = d.get("meta", {})
        if isinstance(meta, dict) and "visual" in meta and isinstance(meta["visual"], dict):
            raw = meta["visual"].get("raw", {})
            if isinstance(raw, dict) and "image_base64" in raw:
                raw.pop("image_base64", None)
        allowed_keys = cls.model_fields.keys()
        cleaned = {k: v for k, v in d.items() if k in allowed_keys}
        return cls(**cleaned)


# ==============================================================================
# 6. RAG TELEMETRY EVENT RECORD
# ==============================================================================
class MongoRagEventRecord(BaseModel):
    """Document nhật ký sự kiện ẩn danh trong collection `rag_events`."""
    model_config = ConfigDict(extra="forbid")

    schema_version: int = Field(default=1, ge=1)
    request_id: str = Field(..., max_length=64)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    question_hash: str = Field(..., pattern=r"^[a-f0-9]{64}$")
    question_length: int = Field(..., ge=1, le=5000)
    intent: str = Field(..., max_length=50)
    cached: bool = Field(default=False)
    fallback: bool = Field(default=False)
    source_count: int = Field(default=0, ge=0)
    source_titles: List[str] = Field(default_factory=list, max_length=MAX_SOURCE_TITLES)
    answer_length: int = Field(default=0, ge=0)
    elapsed_ms: float = Field(default=0.0, ge=0.0)
    timings: Dict[str, float] = Field(default_factory=dict)
    model: str = Field(..., max_length=100)
    kb_version: str = Field(..., max_length=100)
    rag_version: str = Field(..., max_length=100)
    error: Optional[str] = Field(default=None, max_length=500)

    @field_validator("created_at", mode="before")
    @classmethod
    def validate_created_at(cls, v: Any) -> datetime:
        return ensure_utc_datetime(v)

    @classmethod
    def from_legacy(cls, doc: Dict[str, Any]) -> "MongoRagEventRecord":
        d = dict(doc)
        d.pop("_id", None)
        # Loại bỏ trường câu hỏi thô nếu có
        d.pop("question", None)
        d["schema_version"] = d.get("schema_version", 1)
        if "created_at" in d:
            d["created_at"] = ensure_utc_datetime(d["created_at"])
        if "source_titles" in d and isinstance(d["source_titles"], list):
            d["source_titles"] = [str(t)[:160] for t in d["source_titles"]][:MAX_SOURCE_TITLES]
        allowed_keys = cls.model_fields.keys()
        cleaned = {k: v for k, v in d.items() if k in allowed_keys}
        return cls(**cleaned)


# ==============================================================================
# 7. ADMISSION VISUAL RECORD
# ==============================================================================
class MongoAdmissionVisualRecord(BaseModel):
    """Document đồ họa tuyển sinh trong collection `admission_visuals`."""
    model_config = ConfigDict(extra="forbid")

    schema_version: int = Field(default=1, ge=1)
    visual_id: str = Field(..., pattern=SAFE_ID_REGEX, max_length=64)
    major_code: str = Field(..., max_length=20)
    category: str = Field(..., max_length=50)
    title: str = Field(..., max_length=200)
    faculty: Optional[str] = Field(default="", max_length=100)
    duration: Optional[str] = Field(default="", max_length=50)
    tuition: Optional[str] = Field(default="", max_length=100)
    subject_combinations: List[str] = Field(default_factory=list)
    career_highlights: List[str] = Field(default_factory=list)
    cutoff_boxes: List[CutoffBoxItem] = Field(default_factory=list)
    scholarship_highlight: Optional[str] = Field(default=None, max_length=300)
    source_url: Optional[str] = Field(default=None, max_length=500)
    type: str = Field(default="admission_visual", max_length=50)
    storage_key: Optional[str] = Field(default=None, max_length=255)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @field_validator("created_at", mode="before")
    @classmethod
    def validate_created_at(cls, v: Any) -> datetime:
        return ensure_utc_datetime(v)

    @classmethod
    def from_legacy(cls, doc: Dict[str, Any]) -> "MongoAdmissionVisualRecord":
        d = dict(doc)
        d.pop("_id", None)
        # Loại bỏ image_base64 nhúng lớn (>45KB)
        d.pop("image_base64", None)
        d.pop("image_size_bytes", None)
        d.pop("baked_at", None)
        d["schema_version"] = d.get("schema_version", 1)
        if "created_at" in d:
            d["created_at"] = ensure_utc_datetime(d["created_at"])
        allowed_keys = cls.model_fields.keys()
        cleaned = {k: v for k, v in d.items() if k in allowed_keys}
        return cls(**cleaned)


# ==============================================================================
# 8. OPERATION GATEWAY AUDIT RECORD
# ==============================================================================
class MongoOperationAuditRecord(BaseModel):
    """
    Document kiểm toán hoạt động Gateway lưu trong collection `operation_audit`.
    Ghi nhận mỗi lần gọi registered operation một cách có cấu trúc, an toàn và bảo mật.
    """
    model_config = ConfigDict(extra="forbid")

    schema_version: int = Field(default=1, ge=1)
    operation_key: str = Field(..., min_length=1, max_length=128)
    operation_version: str = Field(..., min_length=1, max_length=32)
    operation_checksum: str = Field(..., min_length=1, max_length=128)
    operation_type: Literal["read", "command", "transaction"]
    # Keep legacy values readable while accepting every policy emitted by the
    # current LTX Operation Gateway. Removing the legacy values would make old
    # audit records unreadable after a rolling deployment.
    mutation_policy: Literal[
        "none",
        "insert_only",
        "update_only",
        "upsert",
        "delete_only",
        "any_mutation",
        "read_only",
        "append_only",
        "idempotent_write",
        "destructive_mutation",
    ]
    principal_id: str = Field(..., min_length=1, max_length=64)
    request_id: str = Field(..., min_length=1, max_length=64)
    status: Literal["success", "failed", "rejected"]
    duration_ms: float = Field(..., ge=0.0)
    output_bytes: int = Field(..., ge=0)
    parameter_hash: str = Field(..., min_length=1, max_length=128)
    error_type: Optional[str] = Field(default=None, max_length=128)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @field_validator("created_at", mode="before")
    @classmethod
    def validate_created_at(cls, v: Any) -> datetime:
        return ensure_utc_datetime(v)

    @classmethod
    def from_doc(cls, doc: Dict[str, Any]) -> "MongoOperationAuditRecord":
        d = dict(doc)
        d.pop("_id", None)
        d["schema_version"] = d.get("schema_version", 1)
        if "created_at" in d:
            d["created_at"] = ensure_utc_datetime(d["created_at"])
        allowed_keys = cls.model_fields.keys()
        cleaned = {k: v for k, v in d.items() if k in allowed_keys}
        return cls(**cleaned)


# ==============================================================================
# 9. HUIT KNOWLEDGE BASE RECORD
# ==============================================================================
class MongoHuitKbRecord(BaseModel):
    """
    Document kho tri thức tuyển sinh HUIT lưu trong collection `huit_kb`.
    Bao gồm vector embedding 1024D và các trường ngữ nghĩa / metadata truy xuất.
    """
    model_config = ConfigDict(extra="forbid")

    schema_version: int = Field(default=1, ge=1)
    title: str = Field(..., min_length=1)
    text: str = Field(..., min_length=1)
    source_url: str = Field(..., min_length=1)
    category: str = Field(..., min_length=1)
    embedding: List[float] = Field(..., min_length=1024, max_length=1024)

    raw_text: Optional[str] = Field(default=None)
    page_title: Optional[str] = Field(default=None)
    source_domain: Optional[str] = Field(default=None)
    official: Optional[bool] = Field(default=True)
    retrieved_at: Optional[datetime] = Field(default=None)
    updated_at: Optional[datetime] = Field(default=None)
    created_at: Optional[datetime] = Field(default=None)
    verification_status: Optional[str] = Field(default=None)
    major_code: Optional[str] = Field(default=None)
    year: Optional[int] = Field(default=None)
    visual_id: Optional[str] = Field(default=None)

    # Legacy fields hỗ trợ tương thích
    chunk_hash: Optional[str] = Field(default=None)
    url: Optional[str] = Field(default=None)
    date: Optional[str] = Field(default=None)
    cluster_id: Optional[int] = Field(default=None)

    @field_validator("retrieved_at", "updated_at", "created_at", mode="before")
    @classmethod
    def validate_dates(cls, v: Any) -> Optional[datetime]:
        if v is None:
            return None
        return ensure_utc_datetime(v)

    @model_validator(mode="after")
    def validate_content_safety(self) -> "MongoHuitKbRecord":
        check_no_large_base64(self.text)
        if self.raw_text:
            check_no_large_base64(self.raw_text)
        return self

    @classmethod
    def from_legacy(cls, doc: Dict[str, Any]) -> "MongoHuitKbRecord":
        d = dict(doc)
        d.pop("_id", None)
        d["schema_version"] = d.get("schema_version", 1)

        # Chuẩn hóa ngày giờ sang BSON Date UTC
        if "created_at" in d and d["created_at"]:
            d["created_at"] = ensure_utc_datetime(d["created_at"])
        if "retrieved_at" in d and d["retrieved_at"]:
            d["retrieved_at"] = ensure_utc_datetime(d["retrieved_at"])
        elif d.get("created_at"):
            d["retrieved_at"] = d["created_at"]

        if "updated_at" in d and d["updated_at"]:
            d["updated_at"] = ensure_utc_datetime(d["updated_at"])
        elif d.get("created_at"):
            d["updated_at"] = d["created_at"]

        # Backfill giá trị mặc định cho metadata nếu thiếu
        if not d.get("source_domain") and d.get("source_url"):
            from urllib.parse import urlparse
            d["source_domain"] = urlparse(d["source_url"]).netloc or "ts.huit.edu.vn"
        if "official" not in d:
            d["official"] = True
        if not d.get("verification_status"):
            d["verification_status"] = "verified"
        if not d.get("page_title") and d.get("title"):
            d["page_title"] = d["title"]

        allowed_keys = cls.model_fields.keys()
        cleaned = {k: v for k, v in d.items() if k in allowed_keys}
        return cls(**cleaned)


class AdminSessionDocument(BaseModel):
    """Document model cho collection admin_sessions với schema nghiêm ngặt."""
    model_config = ConfigDict(extra="forbid")

    session_hash: str = Field(min_length=64, max_length=64, pattern=r"^[a-f0-9]{64}$")
    session_id: str = Field(min_length=1, max_length=128)
    admin_id: str = Field(min_length=1, max_length=128)
    created_at: datetime
    expires_at: datetime
    revoked: bool = False
    ip_address: Optional[str] = Field(default=None, max_length=128)
    user_agent: Optional[str] = Field(default=None, max_length=512)
    last_seen_at: Optional[datetime] = None

    @field_validator("created_at", "expires_at", "last_seen_at", mode="before")
    @classmethod
    def validate_dates(cls, v: Any) -> Optional[datetime]:
        if v is None:
            return None
        return ensure_utc_datetime(v)

    def to_bson(self) -> Dict[str, Any]:
        return self.model_dump()

