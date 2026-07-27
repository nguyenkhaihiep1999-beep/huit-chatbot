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

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import rag_core

app = FastAPI(title="HUIT Chatbot API", version="1.0")


from typing import List, Dict, Optional, Any

class ChatRequest(BaseModel):
    question: str
    history: Optional[List[Dict[str, Any]]] = None


@app.on_event("startup")
def _warmup():
    try:
        rag_core._init()
    except Exception as e:  # noqa: BLE001
        print("Warmup warning:", e)


@app.get("/health")
def health():
    return {"status": "ok"}


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


from fastapi.responses import FileResponse, StreamingResponse

@app.post("/api/chat")
def chat(req: ChatRequest):
    q = (req.question or "").strip()
    if not q:
        return {"answer": "Vui lòng nhập câu hỏi.", "sources": []}
    try:
        return rag_core.answer(q, chat_history=req.history)
    except Exception as e:  # noqa: BLE001
        return {"answer": f"Lỗi xử lý: {e}", "sources": []}


@app.get("/api/chat-stream")
def chat_stream(question: str):
    q = (question or "").strip()
    if not q:
        def empty_gen():
            yield '{"type": "token", "token": "Vui lòng nhập câu hỏi."}\n'
        return StreamingResponse(empty_gen(), media_type="application/x-ndjson")
    
    return StreamingResponse(rag_core.stream_answer(q), media_type="application/x-ndjson")


@app.post("/api/clear-cache")
def clear_cache():
    try:
        if rag_core._mongo is not None:
            rag_core._mongo[rag_core.DB]["query_cache"].delete_many({})
            return {"status": "success", "message": "Đã xóa toàn bộ bộ nhớ đệm Semantic Cache thành công."}
    except Exception as e:
        return {"status": "error", "message": str(e)}
    return {"status": "success", "message": "Cache empty."}




@app.post("/api/sync-data")
def sync_data():
    """Trigger real-time dataset update and rebuild KB on MongoDB Atlas."""
    try:
        import build_full_huit_dataset
        import build_real_kb
        count = build_full_huit_dataset.build_full_dataset()
        build_real_kb.run_rebuild()
        return {"status": "success", "message": "Đã cập nhật dữ liệu 39 ngành & tin tuyển sinh thời gian thực!", "documents_count": count}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.get("/")
def index():
    return FileResponse(os.path.join(HERE, "static", "index.html"))


app.mount("/static", StaticFiles(directory=os.path.join(HERE, "static")), name="static")
