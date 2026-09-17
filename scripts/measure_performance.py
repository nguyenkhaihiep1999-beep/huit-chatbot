import os
import sys
import time
import json
from pathlib import Path

# Đảm bảo UTF-8 cho console Windows
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

from backend.app.rag.pipeline import stream_answer, answer
from backend.app.rag.retrieval import HybridRetriever
from backend.app.rag.reranker import retrieve
from backend.app.rag.embedding import EmbeddingManager
from backend.app.cache.mongo_cache import CacheManager

test_queries = [
    "HUIT có những ngành đào tạo nào?",
    "Điểm chuẩn ngành Công nghệ thông tin năm 2024 là bao nhiêu?",
    "Học phí trường Đại học Công Thương TP.HCM như thế nào?",
    "Hồ sơ xét tuyển học bạ gồm những gì?",
    "Hiệu trưởng trường Đại học Công Thương TP.HCM là ai?"
]

print("==========================================================")
print("     BENCHMARK HIỆU NĂNG BACKEND MỚI (MODULAR RAG)        ")
print("==========================================================")

# 1. Đo Embedder Warmup
t_emb_start = time.perf_counter()
EmbeddingManager.get_embedder()
t_emb_init = (time.perf_counter() - t_emb_start) * 1000
print(f"[Init] FastEmbed Model Warmup: {t_emb_init:.2f}ms\n")

results = []

for idx, q in enumerate(test_queries, 1):
    print(f"[{idx}/{len(test_queries)}] Query: '{q}'")

    # A. Đo Retrieval Đơn lẻ (Vector + Keyword + Rerank)
    t0_ret = time.perf_counter()
    docs = retrieve(q, top_k=3)
    t_retrieval = (time.perf_counter() - t0_ret) * 1000

    # B. Đo Streaming Cold (use_cache=False)
    t0_stream = time.perf_counter()
    first_token_time = None
    tokens = []
    metadata = {}
    
    for raw_line in stream_answer(q, chat_history=[], use_cache=False):
        t_now = time.perf_counter()
        try:
            line_str = raw_line.strip()
            if not line_str:
                continue
            item = json.loads(line_str)
            if item.get("type") == "meta":
                metadata = item
            elif item.get("type") == "token":
                tok = item.get("token", "")
                if first_token_time is None and tok.strip():
                    first_token_time = (t_now - t0_stream) * 1000
                tokens.append(tok)
        except Exception:
            pass

    t_total_stream = (time.perf_counter() - t0_stream) * 1000
    full_answer = "".join(tokens)

    # C. Đo Cache Hit (Warm TTFT)
    # Lưu vào cache để test
    CacheManager.save_response(q, {
        "answer": full_answer,
        "sources": metadata.get("sources", []),
        "trace": metadata.get("trace", []),
        "visual": metadata.get("visual"),
        "meta": {"intent": "test", "model": "test"}
    })

    t0_cache = time.perf_counter()
    cached_ttft = None
    for raw_line in stream_answer(q, chat_history=[], use_cache=True):
        t_now = time.perf_counter()
        try:
            item = json.loads(raw_line.strip())
            if item.get("type") == "token" and cached_ttft is None and item.get("token", "").strip():
                cached_ttft = (t_now - t0_cache) * 1000
                break
        except Exception:
            pass

    res_item = {
        "query": q,
        "retrieval_ms": round(t_retrieval, 2),
        "ttft_ms": round(first_token_time or 0, 2),
        "generation_ms": round(t_total_stream, 2),
        "total_ms": round(t_total_stream, 2),
        "cache_hit_ttft_ms": round(cached_ttft or 0, 2),
        "docs_count": len(docs),
        "answer_len": len(full_answer),
        "has_visual": metadata.get("visual") is not None,
    }
    print(f"   -> Retrieval: {res_item['retrieval_ms']}ms | TTFT: {res_item['ttft_ms']}ms | Total: {res_item['total_ms']}ms | Cache TTFT: {res_item['cache_hit_ttft_ms']}ms")
    results.append(res_item)

out_file = ROOT_DIR / "audit_outputs" / "post_refactor_benchmark.json"
with open(out_file, "w", encoding="utf-8") as f:
    json.dump({
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "model_warmup_ms": round(t_emb_init, 2),
        "results": results
    }, f, ensure_ascii=False, indent=2)

print(f"\n[DONE] Post-refactor benchmark saved to {out_file}")
