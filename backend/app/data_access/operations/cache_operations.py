"""LTX domain adapter for persistent query response cache operations (v2.0.0)."""
from datetime import datetime
from typing import Any, Dict, List, Optional
from backend.app.data_access.operation_gateway import execute_registered_operation
import backend.app.data_access.registered_operations.cache_operations_v2  # ensure registered

GET_CACHE_CHECKSUM = "7617c6b276505eb11cafc1b6e57cfbfe74fac32703d14e444fdd32f7925c2cfa"
UPSERT_CACHE_CHECKSUM = "bf6b60bdceab1855c0666a54068c117c8ca1ab555313893167412fcc62a61811"
INVALIDATE_CACHE_CHECKSUM = "f501cdf05e5ca305cdda0472e021fc753862a94344acfe6953b3784df9cb95db"
CLEAR_CACHE_CHECKSUM = "2fc2b3b3bf739aa749b69bdbfa868240cc73f715974f002e8d1e7c2dd2879d1e"


def get_cached_query_response(
    cache_key: str,
    current_time: Optional[datetime] = None,
    *,
    principal_id: str = "system",
    request_id: str = "internal",
) -> Optional[Dict[str, Any]]:
    """Tra cứu câu trả lời đã lưu trong MongoDB Cache qua Registered Operation Gateway."""
    res = execute_registered_operation(
        key="cache.get_valid",
        version="2.0.0",
        checksum=GET_CACHE_CHECKSUM,
        parameters={
            "cache_key": cache_key,
            "current_time": current_time,
        },
        principal_id=principal_id,
        request_id=request_id,
    )
    if res and res.get("found") and res.get("entry"):
        entry = res["entry"]
        return {
            "answer": entry.get("answer"),
            "sources": entry.get("sources", []),
            "trace": entry.get("trace", []),
            "visual": entry.get("visual"),
            "cached": True,
            "meta": entry.get("meta", {}),
        }
    return None


def upsert_cached_query_response(
    cache_key: str,
    question_clean: str,
    question_hash: str,
    question_len: int,
    answer: str,
    sources: List[Dict[str, Any]],
    trace: List[Dict[str, Any]],
    meta: Dict[str, Any],
    kb_version: str,
    rag_version: str,
    model: str,
    updated_at: datetime,
    expires_at: datetime,
    *,
    principal_id: str = "system",
    request_id: str = "internal",
) -> bool:
    """Lưu/cập nhật câu trả lời vào MongoDB Cache có TTL qua Registered Operation Gateway."""
    res = execute_registered_operation(
        key="cache.upsert",
        version="2.0.0",
        checksum=UPSERT_CACHE_CHECKSUM,
        parameters={
            "cache_key": cache_key,
            "question_clean": question_clean,
            "question_hash": question_hash,
            "question_len": question_len,
            "answer": answer,
            "sources": sources,
            "trace": trace,
            "meta": meta,
            "kb_version": kb_version,
            "rag_version": rag_version,
            "model": model,
            "updated_at": updated_at,
            "expires_at": expires_at,
        },
        principal_id=principal_id,
        request_id=request_id,
    )
    return bool(res and res.get("acknowledged"))


def invalidate_cache_key(
    cache_key: str,
    *,
    principal_id: str = "system",
    request_id: str = "internal",
) -> int:
    """Hủy một cache key cụ thể qua Registered Operation Gateway."""
    res = execute_registered_operation(
        key="cache.invalidate",
        version="2.0.0",
        checksum=INVALIDATE_CACHE_CHECKSUM,
        parameters={"cache_key": cache_key},
        principal_id=principal_id,
        request_id=request_id,
    )
    return res.get("deleted_count", 0) if res else 0


def clear_mongo_cache(
    *,
    principal_id: str = "system",
    request_id: str = "internal",
) -> int:
    """Xóa toàn bộ cache trong MongoDB qua Registered Operation Gateway."""
    res = execute_registered_operation(
        key="cache.clear_all",
        version="2.0.0",
        checksum=CLEAR_CACHE_CHECKSUM,
        parameters={"confirm": True},
        principal_id=principal_id,
        request_id=request_id,
    )
    return res.get("deleted_count", 0) if res else 0
