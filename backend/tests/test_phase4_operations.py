"""Comprehensive tests for Phase 4 Registered Operations and Domain Adapters.

Covers:
1. RAG vector search, keyword search, guardrail major catalog, reranker fallback read.
2. Persistent MongoDB cache get, upsert (idempotency), invalidate, clear.
3. Telemetry event append, get recent, batch append, and privacy guarantees.
4. Gateway enforcement: extra="forbid", checksum validation, output limits.
"""
from datetime import datetime, timedelta, timezone
import pytest
from unittest.mock import patch, MagicMock

from backend.app.data_access.operation_gateway import (
    OperationContractError,
    execute_registered_operation,
)
from backend.app.data_access.operations import rag_operations, cache_operations, telemetry_operations
from backend.app.cache.mongo_cache import CacheManager
from backend.app.cache.memory_cache import MemoryCache
from backend.app.rag.guardrails import get_major_catalog_response
from backend.app.rag.retrieval import HybridRetriever
from backend.app.rag.reranker import retrieve
from backend.app.telemetry.metrics import log_event


class TestRagOperations:
    def test_vector_search_gateway_execution(self):
        query_vector = [0.05] * 1024
        docs = rag_operations.execute_vector_search(query_vector=query_vector, limit=5, num_candidates=50)
        assert isinstance(docs, list)

    def test_vector_search_rejects_forbidden_extra_param(self):
        with pytest.raises(OperationContractError):
            execute_registered_operation(
                key="rag.vector_search",
                version="2.0.0",
                checksum=rag_operations.VECTOR_SEARCH_CHECKSUM,
                parameters={
                    "query_vector": [0.1] * 10,
                    "unauthorized_field": "exploit",
                },
                principal_id="test",
                request_id="test",
            )

    def test_vector_search_rejects_invalid_checksum(self):
        with pytest.raises(OperationContractError):
            execute_registered_operation(
                key="rag.vector_search",
                version="2.0.0",
                checksum="0000000000000000000000000000000000000000000000000000000000000000",
                parameters={"query_vector": [0.1] * 10},
                principal_id="test",
                request_id="test",
            )

    def test_keyword_search_gateway_execution(self):
        docs = rag_operations.execute_keyword_search(keywords=["cntt", "hoc phi"], limit=10)
        assert isinstance(docs, list)

    def test_keyword_search_rejects_empty_keywords(self):
        with pytest.raises(OperationContractError):
            rag_operations.execute_keyword_search(keywords=[], limit=10)

    def test_guardrail_catalog_integration(self):
        # Insert mock major into mock collection
        from backend.app.repositories.mongo_repository import MongoRepository
        col = MongoRepository.get_collection("huit_kb")
        col.insert_one({
            "category": "major",
            "major_code": "7480201",
            "title": "Ngành Công nghệ thông tin (HUIT)",
            "page_title": "Công nghệ thông tin",
            "source_url": "https://ts.huit.edu.vn/cntt",
            "url": "https://ts.huit.edu.vn/cntt",
        })

        catalog_docs = rag_operations.get_major_catalog_docs()
        assert any(d.get("major_code") == "7480201" for d in catalog_docs)

        resp = get_major_catalog_response()
        assert resp is not None
        assert "7480201" in resp["answer"]
        assert resp["meta"]["intent"] == "major"

    def test_reranker_fallback_gateway_execution(self):
        docs = rag_operations.get_fallback_docs(limit=2)
        assert isinstance(docs, list)

    def test_hybrid_retriever_uses_rag_operations(self):
        qv = [0.01] * 1024
        v_docs = HybridRetriever.search_vector(qv)
        assert isinstance(v_docs, list)

        k_docs = HybridRetriever.search_keyword("Học phí ngành công nghệ thông tin")
        assert isinstance(k_docs, list)


class TestCacheOperations:
    def setup_method(self):
        MemoryCache.clear()

    def test_cache_upsert_and_get(self):
        now = datetime.now(timezone.utc)
        ckey = "test-query-cache-key-1"
        ok = cache_operations.upsert_cached_query_response(
            cache_key=ckey,
            question_clean="hoc phi huit",
            question_hash="a" * 64,
            question_len=12,
            answer="Học phí khoảng 14-16 triệu/học kỳ.",
            sources=[{"title": "Học phí HUIT", "url": "https://ts.huit.edu.vn"}],
            trace=[{"step": 1, "name": "Cache", "status": "success"}],
            meta={"intent": "tuition"},
            kb_version="2026",
            rag_version="v10",
            model="gemini",
            updated_at=now,
            expires_at=now + timedelta(hours=2),
        )
        assert ok is True

        # Retrieve valid cache
        res = cache_operations.get_cached_query_response(ckey, current_time=now)
        assert res is not None
        assert res["answer"] == "Học phí khoảng 14-16 triệu/học kỳ."
        assert res["cached"] is True
        assert len(res["sources"]) == 1

        # Expired cache check
        future = now + timedelta(hours=3)
        res_expired = cache_operations.get_cached_query_response(ckey, current_time=future)
        assert res_expired is None

    def test_cache_invalidate(self):
        now = datetime.now(timezone.utc)
        ckey = "test-query-cache-key-inv"
        cache_operations.upsert_cached_query_response(
            cache_key=ckey,
            question_clean="test",
            question_hash="b" * 64,
            question_len=4,
            answer="test answer",
            sources=[],
            trace=[],
            meta={},
            kb_version="2026",
            rag_version="v10",
            model="gemini",
            updated_at=now,
            expires_at=now + timedelta(hours=1),
        )
        deleted = cache_operations.invalidate_cache_key(ckey)
        assert deleted == 1
        res = cache_operations.get_cached_query_response(ckey)
        assert res is None

    def test_cache_clear_all(self):
        now = datetime.now(timezone.utc)
        for i in range(3):
            cache_operations.upsert_cached_query_response(
                cache_key=f"bulk-cache-{i}",
                question_clean="test",
                question_hash="c" * 64,
                question_len=4,
                answer="bulk",
                sources=[],
                trace=[],
                meta={},
                kb_version="2026",
                rag_version="v10",
                model="gemini",
                updated_at=now,
                expires_at=now + timedelta(hours=1),
            )
        cleared = cache_operations.clear_mongo_cache()
        assert cleared >= 3

    def test_cache_manager_integration(self):
        question = "Điểm chuẩn ngành IT HUIT năm 2026"
        data = {
            "answer": "Điểm chuẩn IT là 20.0 điểm.",
            "sources": [{"title": "Điểm chuẩn HUIT"}],
            "meta": {"intent": "cutoff"},
        }
        CacheManager.save_response(question, data)

        # Clear RAM to force MongoDB fallback
        MemoryCache.clear()

        cached = CacheManager.get_cached_response(question)
        assert cached is not None
        assert cached["answer"] == "Điểm chuẩn IT là 20.0 điểm."
        assert cached["cached"] is True

        # Clear all
        counts = CacheManager.clear_all_cache()
        assert counts["mongo_cleared"] >= 1
        assert CacheManager.get_cached_response(question) is None


class TestTelemetryOperations:
    def test_append_event_and_retrieve(self):
        now = datetime.now(timezone.utc)
        req_id = "req-test-telemetry-01"
        ev = {
            "request_id": req_id,
            "created_at": now,
            "question_hash": "f" * 64,
            "question_length": 25,
            "intent": "admission",
            "cached": False,
            "fallback": False,
            "source_count": 2,
            "source_titles": ["Doc A", "Doc B"],
            "answer_length": 150,
            "elapsed_ms": 320.5,
            "timings": {"embedding": 10.2, "vector_search": 15.4},
            "model": "google/gemini-2.0-flash",
            "kb_version": "huit-kb-2026",
            "rag_version": "v10",
            "error": None,
        }
        ok = telemetry_operations.record_telemetry_event(ev, request_id=req_id)
        assert ok is True

        recent = telemetry_operations.get_recent_telemetry_events(limit=10)
        assert any(e.get("request_id") == req_id for e in recent)

    def test_telemetry_rejects_raw_question_content(self):
        now = datetime.now(timezone.utc)
        ev = {
            "request_id": "req-illegal",
            "created_at": now,
            "question": "Plain text question must fail!",
            "question_hash": "e" * 64,
            "question_length": 30,
            "intent": "admission",
            "cached": False,
            "fallback": False,
            "source_count": 0,
            "source_titles": [],
            "answer_length": 0,
            "elapsed_ms": 10.0,
            "timings": {},
            "model": "model",
            "kb_version": "v1",
            "rag_version": "v1",
            "error": None,
        }
        with pytest.raises(OperationContractError):
            telemetry_operations.record_telemetry_event(ev)

    def test_batch_append_telemetry(self):
        now = datetime.now(timezone.utc)
        events = [
            {
                "request_id": f"req-batch-{i}",
                "created_at": now,
                "question_hash": "1" * 64,
                "question_length": 10,
                "intent": "general",
                "cached": False,
                "fallback": False,
                "source_count": 1,
                "source_titles": ["Title"],
                "answer_length": 50,
                "elapsed_ms": 100.0,
                "timings": {"total": 100.0},
                "model": "model",
                "kb_version": "v1",
                "rag_version": "v1",
                "error": None,
            }
            for i in range(3)
        ]
        count = telemetry_operations.batch_record_telemetry_events(events)
        assert count == 3

    def test_log_event_integration(self):
        req_id = "req-integration-telemetry"
        log_event(
            question="Cho em hỏi học phí?",
            response_data={"answer": "Học phí 15 triệu.", "sources": [{"title": "Học phí"}]},
            elapsed_ms=85.0,
            intent="tuition",
            request_id=req_id,
            timings={"cache_lookup": 1.2, "request_id": req_id},
        )
        recent = telemetry_operations.get_recent_telemetry_events(limit=5)
        matched = next((e for e in recent if e.get("request_id") == req_id), None)
        assert matched is not None
        assert "question" not in matched
        assert matched["question_hash"] != ""
        assert matched["question_length"] == len("Cho em hỏi học phí?")
