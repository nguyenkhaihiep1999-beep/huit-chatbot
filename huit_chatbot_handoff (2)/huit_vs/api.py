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


class ChatRequest(BaseModel):
    question: str


@app.on_event("startup")
def _warmup():
    try:
        rag_core._init()
    except Exception as e:  # noqa: BLE001
        print("Warmup warning:", e)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/api/chat")
def chat(req: ChatRequest):
    q = (req.question or "").strip()
    if not q:
        return {"answer": "Vui lòng nhập câu hỏi.", "sources": []}
    try:
        return rag_core.answer(q)
    except Exception as e:  # noqa: BLE001
        return {"answer": f"Lỗi xử lý: {e}", "sources": []}


@app.get("/")
def index():
    return FileResponse(os.path.join(HERE, "static", "index.html"))


app.mount("/static", StaticFiles(directory=os.path.join(HERE, "static")), name="static")
