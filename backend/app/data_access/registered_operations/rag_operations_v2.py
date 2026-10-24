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


# ==============================================================================
# RAG Operations v2.1.0 (Multi-profile, Product & SKU Metadata, Cluster Pre-filter)
# ==============================================================================

class RetrievedDocumentItemV21(BaseModel):
    model_config = ConfigDict(extra="forbid")
    chunk_id: Optional[str] = None
    document_id: Optional[str] = None
    dataset_id: Optional[str] = None
    dataset_version: Optional[str] = None
    title: Optional[str] = None
    text: Optional[str] = None
    source_url: Optional[str] = None
    url: Optional[str] = None
    page_title: Optional[str] = None
    category: Optional[str] = None
    product_type: Optional[str] = None
    series: Optional[str] = None
    page_number: Optional[int] = None
    sku: Optional[str] = None
    all_skus: Optional[List[str]] = None
    finish: Optional[str] = None
    glass: Optional[str] = None
    cluster_id: Optional[int] = None
    certifications: Optional[List[str]] = None
    verification_status: Optional[str] = None
    year: Optional[Union[int, str]] = None
    major_code: Optional[str] = None
    score: Optional[float] = None


class VectorSearchParamsV21(BaseModel):
    model_config = ConfigDict(extra="forbid")
    collection: str = Field(default="huit_kb", max_length=64)
    index_name: str = Field(default="huit_vector_index", max_length=64)
    query_vector: List[float] = Field(min_length=1, max_length=4096)
    limit: int = Field(default=15, ge=1, le=100)
    num_candidates: int = Field(default=200, ge=1, le=1000)
    filter_cluster_ids: Optional[List[int]] = None
    dataset_version: Optional[str] = None


class VectorSearchOutputV21(BaseModel):
    model_config = ConfigDict(extra="forbid")
    documents: List[RetrievedDocumentItemV21]


class KeywordSearchParamsV21(BaseModel):
    model_config = ConfigDict(extra="forbid")
    collection: str = Field(default="huit_kb", max_length=64)
    keywords: List[str] = Field(min_length=1, max_length=50)
    limit: int = Field(default=100, ge=1, le=200)
    sku_query: Optional[str] = None


class KeywordSearchOutputV21(BaseModel):
    model_config = ConfigDict(extra="forbid")
    documents: List[RetrievedDocumentItemV21]


class SkuExactSearchParamsV21(BaseModel):
    model_config = ConfigDict(extra="forbid")
    collection: str = Field(default="ilt_kb", max_length=64)
    sku: str = Field(min_length=1, max_length=64)
    limit: int = Field(default=5, ge=1, le=20)


class SkuExactSearchOutputV21(BaseModel):
    model_config = ConfigDict(extra="forbid")
    documents: List[RetrievedDocumentItemV21]


class RerankerFallbackParamsV21(BaseModel):
    model_config = ConfigDict(extra="forbid")
    collection: str = Field(default="huit_kb", max_length=64)
    limit: int = Field(default=3, ge=1, le=50)


class RerankerFallbackOutputV21(BaseModel):
    model_config = ConfigDict(extra="forbid")
    documents: List[RetrievedDocumentItemV21]


def _handle_vector_search_v21(context, params: VectorSearchParamsV21) -> VectorSearchOutputV21:
    col = context.collection(params.collection)
    vsearch_stage: Dict[str, Any] = {
        "index": params.index_name,
        "path": "embedding",
        "queryVector": params.query_vector,
        "numCandidates": params.num_candidates,
        "limit": params.limit,
    }
    filters: Dict[str, Any] = {}
    if params.filter_cluster_ids:
        if len(params.filter_cluster_ids) == 1:
            filters["cluster_id"] = params.filter_cluster_ids[0]
        else:
            filters["cluster_id"] = {"$in": params.filter_cluster_ids}
    if params.dataset_version:
        filters["dataset_version"] = params.dataset_version

    if filters:
        vsearch_stage["filter"] = filters

    pipeline = [
        {"$vectorSearch": vsearch_stage},
        {
            "$project": {
                "_id": 0,
                "chunk_id": 1,
                "document_id": 1,
                "dataset_id": 1,
                "dataset_version": 1,
                "title": 1,
                "text": 1,
                "source_url": 1,
                "url": 1,
                "page_title": 1,
                "category": 1,
                "product_type": 1,
                "series": 1,
                "page_number": 1,
                "sku": 1,
                "all_skus": 1,
                "finish": 1,
                "glass": 1,
                "cluster_id": 1,
                "certifications": 1,
                "verification_status": 1,
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
            items.append(RetrievedDocumentItemV21(
                chunk_id=doc.get("chunk_id"),
                document_id=doc.get("document_id"),
                dataset_id=doc.get("dataset_id"),
                dataset_version=doc.get("dataset_version"),
                title=doc.get("title"),
                text=doc.get("text"),
                source_url=doc.get("source_url"),
                url=doc.get("url"),
                page_title=doc.get("page_title"),
                category=doc.get("category"),
                product_type=doc.get("product_type"),
                series=doc.get("series"),
                page_number=doc.get("page_number"),
                sku=doc.get("sku"),
                all_skus=doc.get("all_skus"),
                finish=doc.get("finish"),
                glass=doc.get("glass"),
                cluster_id=doc.get("cluster_id"),
                certifications=doc.get("certifications"),
                verification_status=doc.get("verification_status"),
                year=doc.get("year"),
                major_code=doc.get("major_code"),
                score=float(doc["score"]) if doc.get("score") is not None else None,
            ))
        return VectorSearchOutputV21(documents=items)
    except Exception:
        return VectorSearchOutputV21(documents=[])


def _handle_keyword_search_v21(context, params: KeywordSearchParamsV21) -> KeywordSearchOutputV21:
    col = context.collection(params.collection)
    regex_pattern = "|".join([re.escape(k) for k in params.keywords])
    clauses: List[Dict[str, Any]] = [
        {"title": {"$regex": regex_pattern, "$options": "i"}},
        {"text": {"$regex": regex_pattern, "$options": "i"}},
    ]
    if params.sku_query:
        clean_sku = params.sku_query.strip()
        clauses.append({"sku": {"$regex": re.escape(clean_sku), "$options": "i"}})
        clauses.append({"all_skus": {"$regex": re.escape(clean_sku), "$options": "i"}})

    query = {"$or": clauses}
    projection = {
        "_id": 0,
        "chunk_id": 1,
        "document_id": 1,
        "dataset_id": 1,
        "dataset_version": 1,
        "title": 1,
        "text": 1,
        "source_url": 1,
        "url": 1,
        "page_title": 1,
        "category": 1,
        "product_type": 1,
        "series": 1,
        "page_number": 1,
        "sku": 1,
        "all_skus": 1,
        "finish": 1,
        "glass": 1,
        "cluster_id": 1,
        "certifications": 1,
        "verification_status": 1,
        "year": 1,
        "major_code": 1,
    }
    raw_docs = list(col.find(query, projection).limit(params.limit))
    items = []
    for doc in raw_docs:
        items.append(RetrievedDocumentItemV21(
            chunk_id=doc.get("chunk_id"),
            document_id=doc.get("document_id"),
            dataset_id=doc.get("dataset_id"),
            dataset_version=doc.get("dataset_version"),
            title=doc.get("title"),
            text=doc.get("text"),
            source_url=doc.get("source_url"),
            url=doc.get("url"),
            page_title=doc.get("page_title"),
            category=doc.get("category"),
            product_type=doc.get("product_type"),
            series=doc.get("series"),
            page_number=doc.get("page_number"),
            sku=doc.get("sku"),
            all_skus=doc.get("all_skus"),
            finish=doc.get("finish"),
            glass=doc.get("glass"),
            cluster_id=doc.get("cluster_id"),
            certifications=doc.get("certifications"),
            verification_status=doc.get("verification_status"),
            year=doc.get("year"),
            major_code=doc.get("major_code"),
            score=float(doc["score"]) if doc.get("score") is not None else None,
        ))
    return KeywordSearchOutputV21(documents=items)


def _handle_sku_exact_search_v21(context, params: SkuExactSearchParamsV21) -> SkuExactSearchOutputV21:
    col = context.collection(params.collection)
    sku_clean = params.sku.strip()
    query = {
        "$or": [
            {"sku": sku_clean},
            {"all_skus": sku_clean},
            {"sku": {"$regex": f"^{re.escape(sku_clean)}$", "$options": "i"}},
            {"all_skus": {"$regex": f"^{re.escape(sku_clean)}$", "$options": "i"}},
        ]
    }
    projection = {
        "_id": 0,
        "chunk_id": 1,
        "document_id": 1,
        "dataset_id": 1,
        "dataset_version": 1,
        "title": 1,
        "text": 1,
        "source_url": 1,
        "url": 1,
        "page_title": 1,
        "category": 1,
        "product_type": 1,
        "series": 1,
        "page_number": 1,
        "sku": 1,
        "all_skus": 1,
        "finish": 1,
        "glass": 1,
        "cluster_id": 1,
        "certifications": 1,
        "verification_status": 1,
        "year": 1,
        "major_code": 1,
    }
    raw_docs = list(col.find(query, projection).limit(params.limit))
    items = []
    for doc in raw_docs:
        items.append(RetrievedDocumentItemV21(
            chunk_id=doc.get("chunk_id"),
            document_id=doc.get("document_id"),
            dataset_id=doc.get("dataset_id"),
            dataset_version=doc.get("dataset_version"),
            title=doc.get("title"),
            text=doc.get("text"),
            source_url=doc.get("source_url"),
            url=doc.get("url"),
            page_title=doc.get("page_title"),
            category=doc.get("category"),
            product_type=doc.get("product_type"),
            series=doc.get("series"),
            page_number=doc.get("page_number"),
            sku=doc.get("sku"),
            all_skus=doc.get("all_skus"),
            finish=doc.get("finish"),
            glass=doc.get("glass"),
            cluster_id=doc.get("cluster_id"),
            certifications=doc.get("certifications"),
            verification_status=doc.get("verification_status"),
            year=doc.get("year"),
            major_code=doc.get("major_code"),
            score=1.0,
        ))
    return SkuExactSearchOutputV21(documents=items)


def _handle_reranker_fallback_v21(context, params: RerankerFallbackParamsV21) -> RerankerFallbackOutputV21:
    col = context.collection(params.collection)
    projection = {
        "_id": 0,
        "chunk_id": 1,
        "document_id": 1,
        "dataset_id": 1,
        "dataset_version": 1,
        "title": 1,
        "text": 1,
        "source_url": 1,
        "url": 1,
        "page_title": 1,
        "category": 1,
        "product_type": 1,
        "series": 1,
        "page_number": 1,
        "sku": 1,
        "all_skus": 1,
        "finish": 1,
        "glass": 1,
        "cluster_id": 1,
        "certifications": 1,
        "verification_status": 1,
        "year": 1,
        "major_code": 1,
    }
    raw_docs = list(col.find({}, projection).limit(params.limit))
    items = []
    for doc in raw_docs:
        items.append(RetrievedDocumentItemV21(
            chunk_id=doc.get("chunk_id"),
            document_id=doc.get("document_id"),
            dataset_id=doc.get("dataset_id"),
            dataset_version=doc.get("dataset_version"),
            title=doc.get("title"),
            text=doc.get("text"),
            source_url=doc.get("source_url"),
            url=doc.get("url"),
            page_title=doc.get("page_title"),
            category=doc.get("category"),
            product_type=doc.get("product_type"),
            series=doc.get("series"),
            page_number=doc.get("page_number"),
            sku=doc.get("sku"),
            all_skus=doc.get("all_skus"),
            finish=doc.get("finish"),
            glass=doc.get("glass"),
            cluster_id=doc.get("cluster_id"),
            certifications=doc.get("certifications"),
            verification_status=doc.get("verification_status"),
            year=doc.get("year"),
            major_code=doc.get("major_code"),
            score=float(doc["score"]) if doc.get("score") is not None else None,
        ))
    return RerankerFallbackOutputV21(documents=items)


# Declarations with pinned checksums
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
        audit_policy="never",
        audit_fail_policy="fail_open",
        declared_checksum="bb10ac595f7b62b5b4b733d4416f0c52870e57e44ee1c4954bcb29f50c190acd",
    ),
    OperationSpec(
        key="rag.vector_search",
        version="2.1.0",
        operation_type="read",
        allowed_collections=("huit_kb", "ilt_kb"),
        parameter_model=VectorSearchParamsV21,
        output_model=VectorSearchOutputV21,
        handler=_handle_vector_search_v21,
        mutation_policy="none",
        max_time_ms=8000,
        max_results=100,
        max_output_bytes=512_000,
        audit_policy="never",
        audit_fail_policy="fail_open",
        declared_checksum="bb113972294573210201039b02cd75a464ed323981966ba5b6d3a82e7c4e8aa7",
    ),
    OperationSpec(
        key="rag.keyword_search",
        version="2.1.0",
        operation_type="read",
        allowed_collections=("huit_kb", "ilt_kb"),
        parameter_model=KeywordSearchParamsV21,
        output_model=KeywordSearchOutputV21,
        handler=_handle_keyword_search_v21,
        mutation_policy="none",
        max_time_ms=5000,
        max_results=200,
        max_output_bytes=512_000,
        audit_policy="never",
        audit_fail_policy="fail_open",
        declared_checksum="9473512d6256bc28ac7c71ee20c2e10a6434faf3e796ab9d55ea757518a22c28",
    ),
    OperationSpec(
        key="rag.sku_exact_search",
        version="2.1.0",
        operation_type="read",
        allowed_collections=("ilt_kb",),
        parameter_model=SkuExactSearchParamsV21,
        output_model=SkuExactSearchOutputV21,
        handler=_handle_sku_exact_search_v21,
        mutation_policy="none",
        max_time_ms=3000,
        max_results=20,
        max_output_bytes=128_000,
        audit_policy="never",
        audit_fail_policy="fail_open",
        declared_checksum="6c97c5cb988547f71f75aea2f18c6729d06d896eab3572bdd8b738f028c085ae",
    ),
    OperationSpec(
        key="rag.reranker_fallback",
        version="2.1.0",
        operation_type="read",
        allowed_collections=("huit_kb", "ilt_kb"),
        parameter_model=RerankerFallbackParamsV21,
        output_model=RerankerFallbackOutputV21,
        handler=_handle_reranker_fallback_v21,
        mutation_policy="none",
        max_time_ms=2000,
        max_results=50,
        max_output_bytes=128_000,
        audit_policy="never",
        audit_fail_policy="fail_open",
        declared_checksum="bfd7437a8d27ceaddef0e26c20af60f163cb7e13a62d99da9bcecaa0ea1ae66f",
    ),
)

for spec in _SPECS:
    register_operation(spec)
