#!/usr/bin/env python3
"""Main Entrypoint for Hugging Face Spaces (Gradio SDK compatible)."""
import os
import sys
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import uvicorn

# Ensure current directory is in sys.path
HERE = os.path.dirname(os.abspath(__file__)) if '__file__' in globals() else os.getcwd()
sys.path.insert(0, HERE)

import rag_core

app = FastAPI(title="HUIT AI Chatbot Admission System")

# Serve static directory
static_dir = os.path.join(HERE, "static")
if os.path.exists(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

@app.get("/")
def read_index():
    index_path = os.path.join(static_dir, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return {"status": "HUIT Chatbot Server Running"}

@app.post("/api/chat")
def chat_endpoint(payload: dict):
    q = payload.get("question", "").strip()
    if not q:
        return {"answer": "Vui lòng nhập câu hỏi.", "sources": []}
    return rag_core.answer(q)

# Entrypoint for Hugging Face Spaces port 7860
if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=7860)
