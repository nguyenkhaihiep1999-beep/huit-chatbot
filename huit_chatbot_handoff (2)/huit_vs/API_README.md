# HUIT Chatbot — API & Giao diện chat

Đóng gói RAG (MongoDB Atlas Vector Search + LLM) thành **API FastAPI** kèm **giao diện chat web**.

## Cài đặt
```bash
pip install -r requirements.txt
```

## Cấu hình biến môi trường
```bash
export MONGODB_PASSWORD="<mật khẩu DB user Atlas>"
export HUIT_OPENROUTER_KEY="sk-or-v1-...."      # key OpenRouter (đầy đủ ~73 ký tự)
# (tùy chọn) đổi model:
export OPENROUTER_MODEL="openai/gpt-oss-20b:free"
```
LLM tự nhận key theo thứ tự: `HUIT_OPENROUTER_KEY` → `OPENROUTER_API_KEY`
→ `DASHSCOPE_API_KEY` (Qwen) → `OPENAI_API_KEY` → `GEMINI_API_KEY`.

## Chạy server
```bash
uvicorn api:app --host 0.0.0.0 --port 8000
```
- Giao diện chat: http://localhost:8000
- Health check : GET http://localhost:8000/health

## Gọi API trực tiếp
```bash
curl -X POST http://localhost:8000/api/chat \
  -H "Content-Type: application/json" \
  -d '{"question":"Học phí HUIT khoảng bao nhiêu một năm?"}'
```
Phản hồi:
```json
{
  "answer": "….(câu trả lời tiếng Việt có trích nguồn [n])",
  "sources": [{"i":1,"title":"…","score":0.85,"text":"…"}]
}
```

## Kiến trúc
```
Trình duyệt (static/index.html)
        │  POST /api/chat
        ▼
api.py (FastAPI)  ──►  rag_core.py
                          ├─ embed câu hỏi (fastembed, 384 chiều)
                          ├─ $vectorSearch trên Atlas (module huit_semantic_search)
                          └─ LLM sinh câu trả lời (module huit_rag_answer)
```

## File
| File | Vai trò |
|------|---------|
| `api.py` | FastAPI: phục vụ trang chat + endpoint `/api/chat` |
| `rag_core.py` | Lõi RAG tái dùng (nạp embedder 1 lần) |
| `static/index.html` | Giao diện chat web |
| `rag_answer.py` | Bản chạy RAG bằng dòng lệnh (CLI) |
| `huit_semantic_search.module.json` | Module retrieval ($vectorSearch) |
| `huit_rag_answer.module.json` | Module generation (prompt, top_k) |
