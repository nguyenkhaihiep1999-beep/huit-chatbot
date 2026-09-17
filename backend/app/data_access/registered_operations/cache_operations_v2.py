"""Registered MongoDB operations for query response cache (v2.0.0)."""
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Union
from pydantic import BaseModel, ConfigDict, Field, field_validator

from backend.app.data_access.operation_gateway import OperationSpec, register_operation
from backend.app.models.mongo_models import (
    QueryCacheSourceItem,
    QueryCacheTraceItem,
    QueryCacheMeta,
    QueryCacheVisual,
)

CACHE_PROJECTION = {"_id": 0}


# Models
class CacheEntryItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    cache_key: str
    answer: str
    sources: List[QueryCacheSourceItem] = Field(default_factory=list)
    trace: List[QueryCacheTraceItem] = Field(default_factory=list)
    meta: QueryCacheMeta = Field(default_factory=QueryCacheMeta)
    visual: Optional[QueryCacheVisual] = None
    kb_version: Optional[str] = None
    rag_version: Optional[str] = None
    model: Optional[str] = None
    expires_at: Optional[Union[datetime, str]] = None

    @field_validator("trace", mode="before")
    @classmethod
    def validate_trace_items(cls, v: Any) -> List[QueryCacheTraceItem]:
        if not v:
            return []
        if isinstance(v, list):
            res = []
            for item in v:
                if isinstance(item, str):
                    res.append(QueryCacheTraceItem(name=item))
                elif isinstance(item, dict):
                    res.append(QueryCacheTraceItem.model_validate(item))
                elif isinstance(item, QueryCacheTraceItem):
                    res.append(item)
            return res
        return []

    @field_validator("sources", mode="before")
    @classmethod
    def validate_sources(cls, v: Any) -> List[QueryCacheSourceItem]:
        if not v:
            return []
        if isinstance(v, list):
            res = []
            for item in v:
                if isinstance(item, dict):
                    res.append(QueryCacheSourceItem.model_validate(item))
                elif isinstance(item, QueryCacheSourceItem):
                    res.append(item)
            return res
        return []


class GetValidCacheParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    cache_key: str = Field(min_length=8, max_length=128)
    current_time: Optional[datetime] = None


class GetValidCacheOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    found: bool
    entry: Optional[CacheEntryItem] = None


class UpsertCacheParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    cache_key: str = Field(min_length=8, max_length=128)
    question_clean: str = Field(max_length=2000)
    question_hash: str = Field(min_length=32, max_length=64)
    question_len: int = Field(ge=0)
    answer: str = Field(min_length=1)
    sources: List[QueryCacheSourceItem] = Field(default_factory=list)
    trace: List[QueryCacheTraceItem] = Field(default_factory=list)
    meta: QueryCacheMeta = Field(default_factory=QueryCacheMeta)
    kb_version: str = Field(max_length=64)
    rag_version: str = Field(max_length=64)
    model: str = Field(max_length=64)
    updated_at: datetime
    expires_at: datetime

    @field_validator("updated_at", "expires_at", mode="before")
    @classmethod
    def forbid_string_dates(cls, v: Any, info) -> datetime:
        if isinstance(v, str):
            raise ValueError(f"{info.field_name} phải là datetime (BSON Date), không chấp nhận chuỗi (string) trong write operation")
        if isinstance(v, datetime):
            return v
        raise ValueError(f"{info.field_name} không đúng định dạng datetime")

    @field_validator("trace", mode="before")
    @classmethod
    def validate_trace_items(cls, v: Any) -> List[QueryCacheTraceItem]:
        if not v:
            return []
        if isinstance(v, list):
            res = []
            for item in v:
                if isinstance(item, str):
                    res.append(QueryCacheTraceItem(name=item))
                elif isinstance(item, dict):
                    res.append(QueryCacheTraceItem.model_validate(item))
                elif isinstance(item, QueryCacheTraceItem):
                    res.append(item)
            return res
        return []

    @field_validator("sources", mode="before")
    @classmethod
    def validate_sources(cls, v: Any) -> List[QueryCacheSourceItem]:
        if not v:
            return []
        if isinstance(v, list):
            res = []
            for item in v:
                if isinstance(item, dict):
                    res.append(QueryCacheSourceItem.model_validate(item))
                elif isinstance(item, QueryCacheSourceItem):
                    res.append(item)
            return res
        return []


class UpsertCacheOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    acknowledged: bool
    cache_key: str


class InvalidateCacheParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    cache_key: str = Field(min_length=8, max_length=128)


class InvalidateCacheOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    deleted_count: int


class ClearAllCacheParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    confirm: bool = True


class ClearAllCacheOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    deleted_count: int


# Handlers
def _handle_get_valid_cache(context, params: GetValidCacheParams) -> GetValidCacheOutput:
    col = context.collection("query_cache")
    now = params.current_time or datetime.now(timezone.utc)
    doc = col.find_one({
        "cache_key": params.cache_key,
        "expires_at": {"$gt": now},
    }, CACHE_PROJECTION)

    if not doc:
        return GetValidCacheOutput(found=False, entry=None)

    vis = doc.get("visual") or (doc.get("meta", {}).get("visual") if isinstance(doc.get("meta"), dict) else None)
    meta_obj = doc.get("meta", {})
    if not isinstance(meta_obj, dict):
        meta_obj = {}
    if vis:
        meta_obj["visual"] = vis

    entry = CacheEntryItem(
        cache_key=doc.get("cache_key", params.cache_key),
        answer=doc.get("answer", ""),
        sources=doc.get("sources", []),
        trace=doc.get("trace", []),
        meta=meta_obj,
        visual=vis,
        kb_version=doc.get("kb_version"),
        rag_version=doc.get("rag_version"),
        model=doc.get("model"),
        expires_at=doc.get("expires_at"),
    )
    return GetValidCacheOutput(found=True, entry=entry)


def _handle_upsert_cache(context, params: UpsertCacheParams) -> UpsertCacheOutput:
    col = context.collection("query_cache")
    doc_payload = {
        "cache_key": params.cache_key,
        "question_clean": params.question_clean,
        "question_hash": params.question_hash,
        "question_len": params.question_len,
        "answer": params.answer,
        "sources": [s.model_dump() if hasattr(s, "model_dump") else s for s in params.sources],
        "trace": [t.model_dump() if hasattr(t, "model_dump") else t for t in params.trace],
        "meta": params.meta.model_dump() if hasattr(params.meta, "model_dump") else params.meta,
        "kb_version": params.kb_version,
        "rag_version": params.rag_version,
        "model": params.model,
        "updated_at": params.updated_at,
        "expires_at": params.expires_at,
    }
    col.update_one(
        {"cache_key": params.cache_key},
        {"$set": doc_payload},
        upsert=True,
    )
    return UpsertCacheOutput(acknowledged=True, cache_key=params.cache_key)


def _handle_invalidate_cache(context, params: InvalidateCacheParams) -> InvalidateCacheOutput:
    col = context.collection("query_cache")
    res = col.delete_one({"cache_key": params.cache_key})
    count = getattr(res, "deleted_count", 0)
    return InvalidateCacheOutput(deleted_count=count)


def _handle_clear_all_cache(context, params: ClearAllCacheParams) -> ClearAllCacheOutput:
    if not params.confirm:
        return ClearAllCacheOutput(deleted_count=0)
    col = context.collection("query_cache")
    res = col.delete_many({})
    count = getattr(res, "deleted_count", 0)
    return ClearAllCacheOutput(deleted_count=count)


# Declarations with placeholder checksum
_SPECS = (
    OperationSpec(
        key="cache.get_valid",
        version="2.0.0",
        operation_type="read",
        allowed_collections=("query_cache",),
        parameter_model=GetValidCacheParams,
        output_model=GetValidCacheOutput,
        handler=_handle_get_valid_cache,
        mutation_policy="none",
        max_time_ms=2000,
        max_results=1,
        max_output_bytes=256_000,
        audit_policy="never",
        audit_fail_policy="fail_open",
        declared_checksum="7617c6b276505eb11cafc1b6e57cfbfe74fac32703d14e444fdd32f7925c2cfa",
    ),
    OperationSpec(
        key="cache.upsert",
        version="2.0.0",
        operation_type="command",
        allowed_collections=("query_cache",),
        parameter_model=UpsertCacheParams,
        output_model=UpsertCacheOutput,
        handler=_handle_upsert_cache,
        mutation_policy="upsert",
        max_time_ms=3000,
        max_results=1,
        max_output_bytes=64_000,
        audit_policy="mutations_and_failures",
        audit_fail_policy="fail_open",
        declared_checksum="bf6b60bdceab1855c0666a54068c117c8ca1ab555313893167412fcc62a61811",
    ),
    OperationSpec(
        key="cache.invalidate",
        version="2.0.0",
        operation_type="command",
        allowed_collections=("query_cache",),
        parameter_model=InvalidateCacheParams,
        output_model=InvalidateCacheOutput,
        handler=_handle_invalidate_cache,
        mutation_policy="delete_only",
        max_time_ms=2000,
        max_results=1,
        max_output_bytes=16_000,
        audit_policy="mutations_and_failures",
        audit_fail_policy="fail_open",
        declared_checksum="f501cdf05e5ca305cdda0472e021fc753862a94344acfe6953b3784df9cb95db",
    ),
    OperationSpec(
        key="cache.clear_all",
        version="2.0.0",
        operation_type="command",
        allowed_collections=("query_cache",),
        parameter_model=ClearAllCacheParams,
        output_model=ClearAllCacheOutput,
        handler=_handle_clear_all_cache,
        mutation_policy="delete_only",
        max_time_ms=5000,
        max_results=1,
        max_output_bytes=16_000,
        audit_policy="mutations_and_failures",
        audit_fail_policy="fail_open",
        declared_checksum="2fc2b3b3bf739aa749b69bdbfa868240cc73f715974f002e8d1e7c2dd2879d1e",
    ),
)

for spec in _SPECS:
    register_operation(spec)
