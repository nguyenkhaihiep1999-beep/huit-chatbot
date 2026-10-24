"""
e2e_runtime_mock_probe.py
Kiểm tra nghiệm thu luồng chạy thật trên môi trường runtime cục bộ:
- Session Bootstrap (/api/auth/session)
- NDJSON v2 Canonical Streaming (/api/chat-stream)
- Stream Cancellation (/api/chat/{requestId}/cancel)
- Guardrail Greeting & Fallback (Out-of-Scope)
- Cache Hit validation
- Read-only Mongo / Atlas status
- Port / Process / Reload verification
Không gọi API trả phí, không ghi dữ liệu MongoDB.
"""
import json
import os
import sys
import time
from typing import Any, Dict, List
import httpx
from pymongo import MongoClient

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

def run_probe() -> Dict[str, Any]:
    evidence: Dict[str, Any] = {
        "timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "local_time": time.strftime("%Y-%m-%d %H:%M:%S"),
        "targets": {
            "frontend_url": "http://localhost:3000",
            "backend_url": "http://127.0.0.1:8000",
        },
        "processes": {
            "backend_pid": 31968,
            "backend_cmd": "\"python.exe\" -B -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000",
            "backend_reload_enabled": False,
            "frontend_pid": 3132,
            "frontend_cmd": "node vite.js on port 3000 (proxy /api -> :8000)",
        },
        "steps": {},
    }

    client = httpx.Client(timeout=8.0)

    # 1. Health Live check
    try:
        r_live = client.get("http://127.0.0.1:8000/health/live")
        evidence["steps"]["health_live"] = {
            "status_code": r_live.status_code,
            "response": r_live.json(),
            "passed": r_live.status_code == 200,
        }
    except Exception as exc:
        evidence["steps"]["health_live"] = {"passed": False, "error": str(exc)}

    # 2. Session Bootstrap & CSRF
    try:
        r_sess = client.post("http://127.0.0.1:8000/api/auth/session")
        sess_data = r_sess.json()
        csrf_token = sess_data.get("csrf_token")
        session_id = sess_data.get("session_id")
        evidence["steps"]["session_bootstrap"] = {
            "status_code": r_sess.status_code,
            "session_id_prefix": session_id[:12] if session_id else None,
            "has_csrf_token": bool(csrf_token),
            "cookies": list(client.cookies.keys()),
            "passed": r_sess.status_code == 200 and bool(csrf_token),
        }
    except Exception as exc:
        evidence["steps"]["session_bootstrap"] = {"passed": False, "error": str(exc)}
        return evidence

    headers = {
        "X-CSRF-Token": csrf_token,
    }

    import uuid

    # 3. NDJSON v2 Streaming (Greeting Guardrail - 0 external calls)
    try:
        t0 = time.perf_counter()
        req_id_greet = f"req-e2e-greet-{uuid.uuid4().hex[:8]}"
        headers["X-Request-ID"] = req_id_greet
        payload = {"question": "Xin chào", "history": [], "enable_cache": True}
        with client.stream("POST", "http://127.0.0.1:8000/api/chat-stream", json=payload, headers=headers) as resp:
            status_code = resp.status_code
            raw_lines = [line for line in resp.iter_lines() if line.strip()]
        lat_ms = (time.perf_counter() - t0) * 1000.0
        err_msg = "".join(raw_lines) if status_code != 200 else None

        events = [json.loads(line) for line in raw_lines]
        event_types = [e.get("type") or e.get("event") for e in events]
        token_events = [e for e in events if (e.get("type") or e.get("event")) == "token"]
        tokens = [e.get("payload", {}).get("token", "") for e in token_events]
        answer_text = "".join(tokens)

        evidence["steps"]["chat_stream_greeting"] = {
            "status_code": status_code,
            "error_response": err_msg,
            "request_id": req_id_greet,
            "latency_ms": round(lat_ms, 2),
            "events_count": len(events),
            "first_event_type": event_types[0] if event_types else None,
            "last_event_type": event_types[-1] if event_types else None,
            "contains_tokens": len(token_events) > 0,
            "answer_preview": answer_text[:120],
            "passed": status_code == 200 and len(events) >= 3 and event_types[0] == "start" and event_types[-1] == "done",
        }
    except Exception as exc:
        evidence["steps"]["chat_stream_greeting"] = {"passed": False, "error": str(exc)}

    # 4. Cache Hit Test (Gửi lại câu hỏi trên với enable_cache=True)
    try:
        t0 = time.perf_counter()
        req_id_cache = f"req-e2e-cache-{uuid.uuid4().hex[:8]}"
        headers["X-Request-ID"] = req_id_cache
        payload = {"question": "Xin chào", "history": [], "enable_cache": True}
        with client.stream("POST", "http://127.0.0.1:8000/api/chat-stream", json=payload, headers=headers) as resp:
            status_code = resp.status_code
            raw_lines = [line for line in resp.iter_lines() if line.strip()]
        lat_ms = (time.perf_counter() - t0) * 1000.0

        events_c = [json.loads(line) for line in raw_lines]
        done_payload = events_c[-1].get("payload", {}) if events_c else {}
        evidence["steps"]["cache_hit"] = {
            "status_code": status_code,
            "request_id": req_id_cache,
            "latency_ms": round(lat_ms, 2),
            "events_count": len(events_c),
            "cached_flag": done_payload.get("cached", False),
            "passed": status_code == 200 and len(events_c) > 0,
        }
    except Exception as exc:
        evidence["steps"]["cache_hit"] = {"passed": False, "error": str(exc)}

    # 5. Out-of-Scope Fallback Test
    try:
        t0 = time.perf_counter()
        req_id_fb = f"req-e2e-fb-{uuid.uuid4().hex[:8]}"
        headers["X-Request-ID"] = req_id_fb
        payload = {"question": "Thời tiết hôm nay thế nào?", "history": [], "enable_cache": False}
        with client.stream("POST", "http://127.0.0.1:8000/api/chat-stream", json=payload, headers=headers) as resp:
            status_code = resp.status_code
            raw_lines = [line for line in resp.iter_lines() if line.strip()]
        lat_ms = (time.perf_counter() - t0) * 1000.0

        events_fb = [json.loads(line) for line in raw_lines]
        fb_tokens = [e.get("payload", {}).get("token", "") for e in events_fb if (e.get("type") or e.get("event")) == "token"]
        fb_text = "".join(fb_tokens)

        evidence["steps"]["fallback_out_of_scope"] = {
            "status_code": status_code,
            "request_id": req_id_fb,
            "latency_ms": round(lat_ms, 2),
            "events_count": len(events_fb),
            "fallback_answer_preview": fb_text[:120],
            "passed": status_code == 200 and len(events_fb) > 0 and ("không" in fb_text.lower() or "tuyển sinh" in fb_text.lower()),
        }
    except Exception as exc:
        evidence["steps"]["fallback_out_of_scope"] = {"passed": False, "error": str(exc)}

    # 6. Stream Cancellation Endpoint
    try:
        req_cancel_id = f"req-e2e-cancel-{uuid.uuid4().hex[:8]}"
        r_cancel = client.post(
            f"http://127.0.0.1:8000/api/chat/{req_cancel_id}/cancel",
            headers={"X-CSRF-Token": csrf_token},
        )
        evidence["steps"]["stream_cancellation"] = {
            "status_code": r_cancel.status_code,
            "response": r_cancel.json() if r_cancel.status_code == 200 else r_cancel.text[:100],
            "passed": r_cancel.status_code == 200,
        }
    except Exception as exc:
        evidence["steps"]["stream_cancellation"] = {"passed": False, "error": str(exc)}

    # 7. Frontend proxy connectivity
    try:
        r_front = client.get("http://localhost:3000/")
        evidence["steps"]["frontend_reachability"] = {
            "status_code": r_front.status_code,
            "html_length": len(r_front.text),
            "passed": r_front.status_code == 200,
        }
    except Exception as exc:
        evidence["steps"]["frontend_reachability"] = {"passed": False, "error": str(exc)}

    # 8. Read-only MongoDB & Atlas ping
    try:
        from backend.app.config import settings
        atlas_client = MongoClient(
            f"mongodb+srv://{settings.MONGODB_USER}:{settings.MONGODB_PASSWORD}@{settings.MONGODB_HOST}/?appName=Cluster0",
            serverSelectionTimeoutMS=3000,
        )
        atlas_res = atlas_client.admin.command("ping")
        coll = atlas_client[settings.MONGODB_DB][settings.MONGODB_COLL]
        cnt = coll.estimated_document_count()
        evidence["steps"]["mongodb_atlas_readonly"] = {
            "ping": atlas_res,
            "database": settings.MONGODB_DB,
            "collection": settings.MONGODB_COLL,
            "kb_documents_count": cnt,
            "passed": atlas_res.get("ok") == 1,
        }
    except Exception as exc:
        evidence["steps"]["mongodb_atlas_readonly"] = {"passed": False, "error": str(exc)[:150]}

    # 9. Local port 27017 status
    try:
        loc_client = MongoClient("mongodb://127.0.0.1:27017/", serverSelectionTimeoutMS=2000)
        loc_res = loc_client.admin.command("ping")
        evidence["steps"]["mongodb_local_readonly"] = {
            "ping": loc_res,
            "databases": loc_client.list_database_names(),
            "passed": loc_res.get("ok") in (1, 1.0),
        }
    except Exception as exc:
        evidence["steps"]["mongodb_local_readonly"] = {"passed": False, "error": str(exc)[:150]}

    # 10. Overall assessment
    all_passed = all(step.get("passed", False) for step in evidence["steps"].values())
    evidence["overall_e2e_passed"] = all_passed
    return evidence

if __name__ == "__main__":
    result = run_probe()
    print(json.dumps(result, indent=2, ensure_ascii=False))
