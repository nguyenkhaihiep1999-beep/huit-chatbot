"""Registered MongoDB operations for RAG pipeline (v2.0.0)."""
import re
from typing import List, Optional, Union
from pydantic import BaseModel, ConfigDict, Field

from backend.app.data_access.operation_gateway import OperationSpec, register_operation

KB_PROJECTION = {"_id": 0, "embedding": 0}


# Models
class RetrievedDocumentItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: Optional[str] = None
    text: Optional[str] = None
    source_url: Optional[str] = None
    url: Optional[str] = None
    page_title: Optional[str] = None
    category: Optional[str] = None
    year: Optional[Union[int, str]] = None
    major_code: Optional[str] = None
    score: Optional[float] = None


class VectorSearchParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    query_vector: List[float] = Field(min_length=1, max_length=4096)
    limit: int = Field(default=15, ge=1, le=100)
    num_candidates: int = Field(default=200, ge=1, le=1000)


class VectorSearchOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    documents: List[RetrievedDocumentItem]


class KeywordSearchParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    keywords: List[str] = Field(min_length=1, max_length=50)
    limit: int = Field(default=100, ge=1, le=200)


class KeywordSearchOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    documents: List[RetrievedDocumentItem]


class MajorCatalogItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    major_code: str = Field(min_length=1, max_length=32)
    title: Optional[str] = None
    page_title: Optional[str] = None
    source_url: Optional[str] = None
    url: Optional[str] = None


class GuardrailMajorCatalogParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    category: str = Field(default="major", max_length=64)
    limit: int = Field(default=200, ge=1, le=500)


class GuardrailMajorCatalogOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    majors: List[MajorCatalogItem]


class RerankerFallbackParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    limit: int = Field(default=3, ge=1, le=50)


class RerankerFallbackOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    documents: List[RetrievedDocumentItem]


# Handlers
def _handle_vector_search(context, params: VectorSearchParams) -> VectorSearchOutput:
    col = context.collection("huit_kb")
    pipeline = [
        {
            "$vectorSearch": {
                "index": "huit_vector_index",
                "path": "embedding",
                "queryVector": params.query_vector,
                "numCandidates": params.num_candidates,
                "limit": params.limit,
            }
        },
        {
            "$project": {
                "_id": 0,
                "title": 1,
                "text": 1,
                "source_url": 1,
                "page_title": 1,
                "category": 1,
                "year": 1,
                "major_code": 1,
                "score": {"$meta": "vectorSearchScore"},
            }
        },
    ]
    try:
        raw_docs = list(col.aggregate(pipeline))
        items = []
        for doc in raw_docs:
            items.append(RetrievedDocumentItem(
                title=doc.get("title"),
                text=doc.get("text"),
                source_url=doc.get("source_url"),
                url=doc.get("url"),
                page_title=doc.get("page_title"),
                category=doc.get("category"),
                year=doc.get("year"),
                major_code=doc.get("major_code"),
                score=float(doc["score"]) if doc.get("score") is not None else None,
            ))
        return VectorSearchOutput(documents=items)
    except Exception:
        return VectorSearchOutput(documents=[])


def _handle_keyword_search(context, params: KeywordSearchParams) -> KeywordSearchOutput:
    col = context.collection("huit_kb")
    regex_pattern = "|".join([re.escape(k) for k in params.keywords])
    query = {
        "$or": [
            {"title": {"$regex": regex_pattern, "$options": "i"}},
            {"text": {"$regex": regex_pattern, "$options": "i"}},
        ]
    }
    raw_docs = list(col.find(query, KB_PROJECTION).limit(params.limit))
    items = []
    for doc in raw_docs:
        items.append(RetrievedDocumentItem(
            title=doc.get("title"),
            text=doc.get("text"),
            source_url=doc.get("source_url"),
            url=doc.get("url"),
            page_title=doc.get("page_title"),
            category=doc.get("category"),
            year=doc.get("year"),
            major_code=doc.get("major_code"),
            score=float(doc["score"]) if doc.get("score") is not None else None,
        ))
    return KeywordSearchOutput(documents=items)


def _handle_guardrail_major_catalog(context, params: GuardrailMajorCatalogParams) -> GuardrailMajorCatalogOutput:
    col = context.collection("huit_kb")
    query = {
        "category": params.category,
        "major_code": {"$exists": True, "$ne": None},
    }
    projection = {
        "_id": 0,
        "page_title": 1,
        "title": 1,
        "major_code": 1,
        "source_url": 1,
        "url": 1,
    }
    raw_docs = list(col.find(query, projection).limit(params.limit))
    items = []
    for doc in raw_docs:
        code = str(doc.get("major_code") or "").strip()
        if code:
            items.append(MajorCatalogItem(
                major_code=code,
                title=doc.get("title"),
                page_title=doc.get("page_title"),
                source_url=doc.get("source_url"),
                url=doc.get("url"),
            ))
    return GuardrailMajorCatalogOutput(majors=items)


def _handle_reranker_fallback(context, params: RerankerFallbackParams) -> RerankerFallbackOutput:
    col = context.collection("huit_kb")
    raw_docs = list(col.find({}, KB_PROJECTION).limit(params.limit))
    items = []
    for doc in raw_docs:
        items.append(RetrievedDocumentItem(
            title=doc.get("title"),
            text=doc.get("text"),
            source_url=doc.get("source_url"),
            url=doc.get("url"),
            page_title=doc.get("page_title"),
            category=doc.get("category"),
            year=doc.get("year"),
            major_code=doc.get("major_code"),
            score=float(doc["score"]) if doc.get("score") is not None else None,
        ))
    return RerankerFallbackOutput(documents=items)


# Declarations with placeholder checksum
_SPECS = (
    OperationSpec(
        key="rag.vector_search",
        version="2.0.0",
        operation_type="read",
        allowed_collections=("huit_kb",),
        parameter_model=VectorSearchParams,
        output_model=VectorSearchOutput,
        handler=_handle_vector_search,
        mutation_policy="none",
        max_time_ms=8000,
        max_results=100,
        max_output_bytes=512_000,
        # Audit policy 'never': Pure read query on knowledge base chunks with zero mutations
        audit_policy="never",
        audit_fail_policy="fail_open",
        declared_checksum="cd93876d9f4c13c8a4fb91bbb283e9759c57717751bfa1d9ea0977ebd7c08021",
    ),
    OperationSpec(
        key="rag.keyword_search",
        version="2.0.0",
        operation_type="read",
        allowed_collections=("huit_kb",),
        parameter_model=KeywordSearchParams,
        output_model=KeywordSearchOutput,
        handler=_handle_keyword_search,
        mutation_policy="none",
        max_time_ms=5000,
        max_results=200,
        max_output_bytes=512_000,
        # Audit policy 'never': Pure read query on knowledge base chunks with zero mutations
        audit_policy="never",
        audit_fail_policy="fail_open",
        declared_checksum="c99e0aa5809c886dc3b6b3c8d5a37e0423c7b2051c910894265c1d94fd01a793",
    ),
    OperationSpec(
        key="rag.guardrail_major_catalog",
        version="2.0.0",
        operation_type="read",
        allowed_collections=("huit_kb",),
        parameter_model=GuardrailMajorCatalogParams,
        output_model=GuardrailMajorCatalogOutput,
        handler=_handle_guardrail_major_catalog,
        mutation_policy="none",
        max_time_ms=3000,
        max_results=300,
        max_output_bytes=256_000,
        # Audit policy 'never': Pure read query on knowledge base chunks with zero mutations
        audit_policy="never",
        audit_fail_policy="fail_open",
        declared_checksum="d8259fa58051f0dce0fed0291d781fb8345ee220ba433e01c152b4b299991978",
    ),
    OperationSpec(
        key="rag.reranker_fallback",
        version="2.0.0",
        operation_type="read",
        allowed_collections=("huit_kb",),
        parameter_model=RerankerFallbackParams,
        output_model=RerankerFallbackOutput,
        handler=_handle_reranker_fallback,
        mutation_policy="none",
        max_time_ms=2000,
        max_results=50,
        max_output_bytes=128_000,
        # Audit policy 'never': Pure read query on knowledge base chunks with zero mutations
        audit_policy="never",
        audit_fail_policy="fail_open",
        declared_checksum="bb10ac595f7b62b5b4b733d4416f0c52870e57e44ee1c4954bcb29f50c190acd",
    ),
)

for spec in _SPECS:
    register_operation(spec)
