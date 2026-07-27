#!/usr/bin/env python3
"""API + giao diện chat cho Chatbot HUIT (RAG trên MongoDB Atlas Vector Search).

Chạy:
    pip install -r requirements.txt
    export MONGODB_PASSWORD="..."
    export HUIT_OPENROUTER_KEY="sk-or-v1-..."
    uvicorn api:app --host 0.0.0.0 --port 8000

Mở: http://localhost:8000   ·   API: POST /api/chat  {"question": "..."}
"""
import os
import sys
import hmac
import time
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from fastapi import FastAPI, Header, HTTPException, Request, status
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

import rag_core

app = FastAPI(title="HUIT Chatbot API", version="1.0")


from typing import List, Dict, Optional, Any

class ChatRequest(BaseModel):
    question: str = Field(min_length=1, max_length=800)
    history: Optional[List[Dict[str, Any]]] = None


RATE_LIMIT_PER_MINUTE = int(os.environ.get("RATE_LIMIT_PER_MINUTE", "20"))
_request_windows = defaultdict(deque)


def _client_ip(request: Request):
    forwarded = request.headers.get("x-forwarded-for", "")
    return forwarded.split(",", 1)[0].strip() or (request.client.host if request.client else "unknown")


def enforce_rate_limit(request: Request):
    now = time.monotonic()
    bucket = _request_windows[_client_ip(request)]
    while bucket and now - bucket[0] >= 60:
        bucket.popleft()
    if len(bucket) >= RATE_LIMIT_PER_MINUTE:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Bạn gửi yêu cầu quá nhanh. Vui lòng thử lại sau một phút.",
        )
    bucket.append(now)


def require_admin(x_admin_token: str = Header(default="")):
    expected = os.environ.get("ADMIN_TOKEN", "")
    if not expected:
        raise HTTPException(status_code=503, detail="Chức năng quản trị chưa được cấu hình.")
    if not hmac.compare_digest(x_admin_token, expected):
        raise HTTPException(status_code=401, detail="Không có quyền quản trị.")


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(), geolocation=()"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
        "font-src 'self' https://fonts.gstatic.com; "
        "img-src 'self' data: https://ts.huit.edu.vn; "
        "connect-src 'self'; base-uri 'self'; form-action 'self'"
    )
    return response


@app.on_event("startup")
def _warmup():
    try:
        rag_core._init()
    except Exception as e:  # noqa: BLE001
        print("Warmup warning:", e)


@app.get("/health")
def health():
    checks = {
        "mongodb": False,
        "knowledge_base": False,
        "openrouter": bool(
            os.environ.get("HUIT_OPENROUTER_KEY")
            or os.environ.get("OPENROUTER_API_KEY")
        ),
    }
    kb_documents = 0
    try:
        rag_core._init()
        rag_core._mongo.admin.command("ping")
        checks["mongodb"] = True
        kb_documents = rag_core._mongo[rag_core.DB][rag_core.COLL].estimated_document_count()
        checks["knowledge_base"] = kb_documents > 0
    except Exception:
        pass
    healthy = all(checks.values())
    return JSONResponse(
        {
            "status": "ok" if healthy else "degraded",
            "checks": checks,
            "kb_documents": kb_documents,
            "kb_version": rag_core.KB_VERSION,
            "model": rag_core.LLM_MODEL,
        },
        status_code=200 if healthy else 503,
    )


@app.get("/api/suggested-questions")
def get_suggested_questions():
    return {
        "questions": [
            "Mã ngành & tổ hợp xét tuyển ngành Trí tuệ nhân tạo HUIT?",
            "Học phí trung bình một học kỳ tại HUIT là bao nhiêu?",
            "Điểm sàn xét tuyển đại học chính quy 2025 HUIT bao nhiêu?",
            "Chính sách học bổng giảm 50% học phí HK1 dành cho các ngành nào?",
            "Ngành Công nghệ thông tin xét các tổ hợp môn nào?"
        ]
    }


@app.post("/api/chat")
def chat(req: ChatRequest, request: Request):
    enforce_rate_limit(request)
    q = (req.question or "").strip()
    if not q:
        raise HTTPException(status_code=422, detail="Vui lòng nhập câu hỏi.")
    history = req.history or []
    if len(history) > 12:
        raise HTTPException(status_code=422, detail="Lịch sử hội thoại quá dài.")
    for turn in history:
        if not isinstance(turn, dict) or len(str(turn.get("content", ""))) > 2000:
            raise HTTPException(status_code=422, detail="Lịch sử hội thoại không hợp lệ.")
    try:
        return rag_core.answer(q, chat_history=history)
    except Exception as e:  # noqa: BLE001
        print("Chat processing error:", type(e).__name__, e)
        raise HTTPException(
            status_code=503,
            detail="Hệ thống tư vấn đang tạm thời bận. Vui lòng thử lại sau.",
        ) from None


@app.get("/api/chat-stream")
def chat_stream(question: str, request: Request):
    enforce_rate_limit(request)
    q = (question or "").strip()
    if len(q) > 800:
        raise HTTPException(status_code=422, detail="Câu hỏi quá dài.")
    if not q:
        def empty_gen():
            yield '{"type": "token", "token": "Vui lòng nhập câu hỏi."}\n'
        return StreamingResponse(empty_gen(), media_type="application/x-ndjson")
    
    return StreamingResponse(rag_core.stream_answer(q), media_type="application/x-ndjson")


@app.post("/api/clear-cache")
def clear_cache(x_admin_token: str = Header(default="")):
    require_admin(x_admin_token)
    try:
        rag_core._init()
        result = rag_core._mongo[rag_core.DB]["query_cache"].delete_many({})
        return {
            "status": "success",
            "message": "Đã xóa bộ nhớ đệm.",
            "deleted": result.deleted_count,
        }
    except Exception as e:
        print("Clear cache error:", type(e).__name__, e)
        raise HTTPException(status_code=503, detail="Không thể xóa cache.") from None




@app.post("/api/sync-data")
def sync_data(x_admin_token: str = Header(default="")):
    require_admin(x_admin_token)
    """Trigger real-time dataset update and rebuild KB on MongoDB Atlas."""
    if os.environ.get("ENABLE_DATA_SYNC", "").lower() != "true":
        raise HTTPException(
            status_code=503,
            detail="Đồng bộ dữ liệu qua web đang tắt. Hãy chạy pipeline quản trị riêng.",
        )
    try:
        import build_full_huit_dataset
        import build_real_kb
        count = build_full_huit_dataset.build_full_dataset()
        build_real_kb.run_rebuild()
        return {"status": "success", "message": "Đã cập nhật dữ liệu 39 ngành & tin tuyển sinh thời gian thực!", "documents_count": count}
    except Exception as e:
        print("Data sync error:", type(e).__name__, e)
        raise HTTPException(status_code=503, detail="Không thể đồng bộ dữ liệu.") from None


@app.get("/api/admin/metrics")
def metrics(x_admin_token: str = Header(default="")):
    require_admin(x_admin_token)
    rag_core._init()
    since = datetime.now(timezone.utc) - timedelta(hours=24)
    events = list(rag_core._mongo[rag_core.DB]["rag_events"].find(
        {"created_at": {"$gte": since}},
        {"_id": 0, "elapsed_ms": 1, "cached": 1, "fallback": 1, "intent": 1},
    ).limit(5000))
    count = len(events)
    return {
        "window_hours": 24,
        "requests": count,
        "cache_hits": sum(1 for event in events if event.get("cached")),
        "fallbacks": sum(1 for event in events if event.get("fallback")),
        "average_latency_ms": round(
            sum(event.get("elapsed_ms", 0) for event in events) / count
        ) if count else 0,
        "intents": {
            intent: sum(1 for event in events if event.get("intent") == intent)
            for intent in sorted({event.get("intent") or "unknown" for event in events})
        },
    }


@app.get("/")
def index():
    return FileResponse(os.path.join(HERE, "static", "index.html"))


app.mount("/static", StaticFiles(directory=os.path.join(HERE, "static")), name="static")
