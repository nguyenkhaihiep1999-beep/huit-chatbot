import os
import sys
import time
from datetime import datetime, timezone
from typing import Dict, Any, Optional

import rag_core

_start_time = time.time()


def get_system_health(quick: bool = False) -> Dict[str, Any]:
    """
    Thu thập chỉ số sức khỏe hệ thống thời gian thực:
    - quick=True: Chỉ kiểm tra ping MongoDB (dùng cho Uptime probe, < 5ms nếu warm)
    - quick=False: Báo cáo toàn diện (DB latency, collections, AI models, RAM/CPU, traffic logs)
    """
    now = time.time()
    uptime_sec = int(now - _start_time)
    hours, rem = divmod(uptime_sec, 3600)
    mins, secs = divmod(rem, 60)
    uptime_str = f"{hours}h {mins}m {secs}s" if hours else f"{mins}m {secs}s"

    rag_core._init()
    db = rag_core._mongo[rag_core.DB]

    # 1. Ping MongoDB Atlas & đo độ trễ
    db_status = "unknown"
    latency_ms = -1.0
    try:
        t0 = time.perf_counter()
        res = db.command("ping")
        latency_ms = round((time.perf_counter() - t0) * 1000, 2)
        db_status = "healthy" if res.get("ok") == 1 else "degraded"
    except Exception as e:
        db_status = "down"
        latency_ms = -1.0

    if quick:
        return {
            "status": "healthy" if db_status == "healthy" else "degraded",
            "db_status": db_status,
            "latency_ms": latency_ms,
            "uptime": uptime_str,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    # 2. Thống kê collections
    collection_names = [
        "admission_visuals",
        "huit_kb",
        "test_rag_chunks",
        "rag_events",
        "query_cache",
        "generated_images",
    ]
    colls_stats = {}
    for c in collection_names:
        try:
            colls_stats[c] = db[c].estimated_document_count()
        except Exception:
            try:
                colls_stats[c] = db[c].count_documents({})
            except Exception:
                colls_stats[c] = 0

    # 3. Tài nguyên hệ thống (psutil)
    cpu_percent = 0.0
    ram_percent = 0.0
    ram_used_mb = 0.0
    ram_total_mb = 0.0
    process_rss_mb = 0.0
    threads_count = 1

    try:
        import psutil
        cpu_percent = psutil.cpu_percent(interval=0.05)
        vm = psutil.virtual_memory()
        ram_percent = vm.percent
        ram_used_mb = round(vm.used / (1024 * 1024), 1)
        ram_total_mb = round(vm.total / (1024 * 1024), 1)

        proc = psutil.Process()
        process_rss_mb = round(proc.memory_info().rss / (1024 * 1024), 1)
        threads_count = proc.num_threads()
    except Exception:
        pass

    # 4. Trạng thái AI Engine
    embedder_loaded = bool(rag_core._embedder)
    embedder_info = {
        "model": rag_core.MODEL,
        "loaded": embedder_loaded,
        "dimensions": rag_core.DIMS,
        "engine": "FastEmbed (ONNX Local)" if embedder_loaded else "Keyword Fallback",
    }

    llm_info = {
        "model": rag_core.LLM_MODEL,
        "max_tokens": rag_core.LLM_MAX_TOKENS,
        "provider": "OpenRouter API" if os.environ.get("HUIT_OPENROUTER_KEY") or os.environ.get("OPENROUTER_API_KEY") else "Direct API",
    }

    cache_info = {
        "ram_entries": len(rag_core._ram_cache),
        "mongo_entries": colls_stats.get("query_cache", 0),
        "ttl_hours": rag_core.CACHE_TTL_HOURS,
    }

    # 5. Thống kê 10 sự kiện / câu hỏi gần nhất từ rag_events
    recent_events = []
    try:
        evs = list(
            db["rag_events"]
            .find({}, {"_id": 0})
            .sort("created_at", -1)
            .limit(10)
        )
        for ev in evs:
            created = ev.get("created_at")
            if isinstance(created, datetime):
                created = created.strftime("%H:%M:%S %d/%m")
            recent_events.append({
                "question": str(ev.get("question", ""))[:75],
                "intent": ev.get("intent", "general"),
                "elapsed_ms": ev.get("elapsed_ms", 0),
                "cached": bool(ev.get("cached")),
                "fallback": bool(ev.get("fallback")),
                "created_at": str(created or ""),
            })
    except Exception:
        pass

    overall_status = "healthy"
    if db_status != "healthy":
        overall_status = "degraded" if db_status == "degraded" else "critical"

    return {
        "status": overall_status,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "uptime": {
            "seconds": uptime_sec,
            "human": uptime_str,
        },
        "database": {
            "status": db_status,
            "host": rag_core.HOST,
            "name": rag_core.DB,
            "latency_ms": latency_ms,
            "collections": colls_stats,
        },
        "ai_engine": {
            "embedder": embedder_info,
            "llm": llm_info,
            "cache": cache_info,
        },
        "system": {
            "cpu_percent": cpu_percent,
            "ram_percent": ram_percent,
            "ram_used_mb": ram_used_mb,
            "ram_total_mb": ram_total_mb,
            "process_rss_mb": process_rss_mb,
            "threads": threads_count,
            "python_version": sys.version.split()[0],
            "os": sys.platform,
        },
        "recent_traffic": recent_events,
    }
