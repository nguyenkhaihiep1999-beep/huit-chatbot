"""LTX domain adapter for RAG pipeline queries and catalog reads (v2.0.0)."""
from typing import Any, Dict, List, Optional
from backend.app.data_access.operation_gateway import execute_registered_operation
import backend.app.data_access.registered_operations.rag_operations_v2  # ensure registered

VECTOR_SEARCH_CHECKSUM = "cd93876d9f4c13c8a4fb91bbb283e9759c57717751bfa1d9ea0977ebd7c08021"
KEYWORD_SEARCH_CHECKSUM = "c99e0aa5809c886dc3b6b3c8d5a37e0423c7b2051c910894265c1d94fd01a793"
GUARDRAIL_CATALOG_CHECKSUM = "d8259fa58051f0dce0fed0291d781fb8345ee220ba433e01c152b4b299991978"
RERANKER_FALLBACK_CHECKSUM = "bb10ac595f7b62b5b4b733d4416f0c52870e57e44ee1c4954bcb29f50c190acd"


def execute_vector_search(
    query_vector: List[float],
    limit: int = 15,
    num_candidates: int = 200,
    *,
    principal_id: str = "system",
    request_id: str = "internal",
) -> List[Dict[str, Any]]:
    """Thực thi truy vấn tìm kiếm vector có kiểm soát giới hạn qua Registered Operation Gateway."""
    res = execute_registered_operation(
        key="rag.vector_search",
        version="2.0.0",
        checksum=VECTOR_SEARCH_CHECKSUM,
        parameters={
            "query_vector": query_vector,
            "limit": limit,
            "num_candidates": num_candidates,
        },
        principal_id=principal_id,
        request_id=request_id,
    )
    return res.get("documents", []) if res else []


def execute_keyword_search(
    keywords: List[str],
    limit: int = 100,
    *,
    principal_id: str = "system",
    request_id: str = "internal",
) -> List[Dict[str, Any]]:
    """Thực thi tìm kiếm từ khóa Regex có kiểm soát giới hạn qua Registered Operation Gateway."""
    res = execute_registered_operation(
        key="rag.keyword_search",
        version="2.0.0",
        checksum=KEYWORD_SEARCH_CHECKSUM,
        parameters={
            "keywords": keywords,
            "limit": limit,
        },
        principal_id=principal_id,
        request_id=request_id,
    )
    return res.get("documents", []) if res else []


def get_major_catalog_docs(
    category: str = "major",
    limit: int = 200,
    *,
    principal_id: str = "system",
    request_id: str = "internal",
) -> List[Dict[str, Any]]:
    """Truy vấn danh mục ngành chính thức từ HUIT KB qua Registered Operation Gateway."""
    res = execute_registered_operation(
        key="rag.guardrail_major_catalog",
        version="2.0.0",
        checksum=GUARDRAIL_CATALOG_CHECKSUM,
        parameters={
            "category": category,
            "limit": limit,
        },
        principal_id=principal_id,
        request_id=request_id,
    )
    return res.get("majors", []) if res else []


def get_fallback_docs(
    limit: int = 3,
    *,
    principal_id: str = "system",
    request_id: str = "internal",
) -> List[Dict[str, Any]]:
    """Truy vấn tài liệu dự phòng (fallback) qua Registered Operation Gateway."""
    res = execute_registered_operation(
        key="rag.reranker_fallback",
        version="2.0.0",
        checksum=RERANKER_FALLBACK_CHECKSUM,
        parameters={
            "limit": limit,
        },
        principal_id=principal_id,
        request_id=request_id,
    )
    return res.get("documents", []) if res else []
