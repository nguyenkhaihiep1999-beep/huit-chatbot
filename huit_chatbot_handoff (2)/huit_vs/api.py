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
import json
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from fastapi import FastAPI, Header, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

import rag_core
import image_service
import admission_visuals_service as avs
import health_service

app = FastAPI(title="HUIT Chatbot API", version="1.0", docs_url=None, redoc_url=None)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


from typing import List, Dict, Optional, Any

class ChatRequest(BaseModel):
    question: str = Field(min_length=1, max_length=800)
    history: Optional[List[Dict[str, Any]]] = None


RATE_LIMIT_PER_MINUTE = int(os.environ.get("RATE_LIMIT_PER_MINUTE", "20"))
_request_windows = defaultdict(deque)
_login_windows = defaultdict(deque)


class LoginRequest(BaseModel):
    username: Optional[str] = None
    password: Optional[str] = None
    admin_token: Optional[str] = None


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


def enforce_login_rate_limit(request: Request):
    now = time.monotonic()
    bucket = _login_windows[_client_ip(request)]
    while bucket and now - bucket[0] >= 60:
        bucket.popleft()
    if len(bucket) >= 5:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Bạn đã thử đăng nhập quá nhiều lần thất bại. Vui lòng thử lại sau 1 phút.",
        )
    bucket.append(now)


def require_admin(x_admin_token: str = Header(default="")):
    expected_token = (os.environ.get("ADMIN_TOKEN", "") or "huit_admin_2026").strip()
    expected_pass = (os.environ.get("ADMIN_PASSWORD", "") or "123").strip()
    candidate = str(x_admin_token or "").strip()
    if not (hmac.compare_digest(candidate, expected_token) or hmac.compare_digest(candidate, expected_pass)):
        raise HTTPException(status_code=401, detail="Token quản trị không đúng hoặc phiên làm việc đã hết hạn.")



@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "SAMEORIGIN"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(), geolocation=()"
    if request.url.path.endswith(".html") or request.url.path in ("/", "/workflow", "/admin", "/docs"):
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response


@app.on_event("startup")
def _warmup():
    try:
        rag_core._init()
    except Exception as e:  # noqa: BLE001
        print("Warmup warning:", e)


@app.get("/health")
@app.get("/api/health")
def health(quick: bool = True):
    data = health_service.get_system_health(quick=quick)
    status_code = 200 if data.get("status") == "healthy" else 503
    return JSONResponse(data, status_code=status_code)


@app.get("/api/suggested-questions")
def get_suggested_questions():
    return {
        "questions": [
            "Mã ngành & tổ hợp xét tuyển ngành Trí tuệ nhân tạo HUIT?",
            "Học phí trung bình một học kỳ tại HUIT là bao nhiêu?",
            "Điểm sàn xét tuyển đại học chính quy 2026 HUIT bao nhiêu?",
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
    if image_service.image_prompt(q):
        return image_chat(q)
    history = req.history or []
    # Auto sliding-window: trim history to latest 10 messages (5 QA turns) to prevent payload bloat
    if len(history) > 10:
        history = history[-10:]
    for turn in history:
        if not isinstance(turn, dict) or len(str(turn.get("content", ""))) > 2000:
            turn["content"] = str(turn.get("content", ""))[:2000]
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
    
    if image_service.image_prompt(q):
        return image_chat_stream(q)
    return StreamingResponse(rag_core.stream_answer(q), media_type="application/x-ndjson")


@app.post("/api/chat-stream")
def chat_stream_post(req: ChatRequest, request: Request):
    enforce_rate_limit(request)
    q = (req.question or "").strip()
    if not q:
        raise HTTPException(status_code=422, detail="Vui lòng nhập câu hỏi.")
    if image_service.image_prompt(q):
        return image_chat_stream(q)
    history = req.history or []
    if len(history) > 10:
        history = history[-10:]
    return StreamingResponse(rag_core.stream_answer(q, chat_history=history), media_type="application/x-ndjson")


def save_generated_image(req):
    try:
        return image_service.create_image(req)
    except Exception as e:
        print("save_generated_image error:", type(e).__name__, str(e))
        raise HTTPException(status_code=503, detail="Chưa tạo được ảnh: kiểm tra MongoDB, API key OpenRouter hoặc hạn mức miễn phí. AI cũng có thể trả JSON không hợp lệ hoặc vượt dung lượng. Không chuyển sang model tính phí.") from None


def image_chat(question):
    raw_prompt = image_service.image_prompt(question) or question
    clean_prompt, detected_style, width, height = image_service.extract_image_options(raw_prompt)
    result = save_generated_image(image_service.ImageRequest(
        prompt=clean_prompt,
        width=width,
        height=height,
        style=detected_style,
        backend="flux"
    ))
    w = result.get('width', width)
    h = result.get('height', height)
    style_names = {
        "photorealistic": "📸 Chân thực 8K",
        "anime": "🌸 Anime Nghệ Thuật (Ghibli)",
        "3d": "🧊 3D Render (Pixar / Unreal 5)",
        "painting": "🖌️ Tranh Sơn Dầu (Fine Art)",
        "cyberpunk": "⚡ Cyberpunk Tương Lai",
        "cinematic": "🎬 Điện Ảnh (Cinematic Film)"
    }
    style_label = style_names.get(detected_style, detected_style.capitalize())
    answer = (
        f"🎨 **Ảnh nghệ thuật AI (Mô hình FLUX.1)** · *{style_label}* ({w} × {h}):\n\n"
        f"![Ảnh AI]({result['url']})\n\n"
        f"📥 [Tải ảnh gốc HD]({result['url']}?download=true) · 🔍 [Mở ảnh xem chi tiết]({result['url']})"
    )
    return {"answer": answer, "sources": [], "image": result}


def image_chat_stream(question):
    result = image_chat(question)
    img_info = result.get("image", {})
    style = img_info.get("style", "photorealistic")
    w = img_info.get("width", 512)
    h = img_info.get("height", 512)
    events = [
        {"type": "meta", "sources": [], "trace": [
            {"step": 1, "name": "Khởi tạo Yêu cầu AI", "detail": f"Phong cách: {style} · Kích thước: {w}×{h}", "status": "success"},
            {"step": 2, "name": "Vẽ tranh qua FLUX.1", "detail": "Mô hình khuếch tán FLUX cao cấp với Multi-Model Fallback", "status": "success"},
            {"step": 3, "name": "Lưu trữ CSDL", "detail": "Đã lưu ảnh HD vào MongoDB Atlas", "status": "success"}
        ]},
        {"type": "token", "token": result["answer"]},
    ]
    return StreamingResponse(iter([json.dumps(event, ensure_ascii=False) + "\n" for event in events]), media_type="application/x-ndjson")


@app.post("/api/images")
def generate_image(req: image_service.ImageRequest, request: Request):
    enforce_rate_limit(request)
    return save_generated_image(req)


def load_generated_image(image_id):
    try:
        doc = image_service.get_image(image_id)
    except Exception:
        raise HTTPException(status_code=503, detail="Không thể đọc ảnh từ MongoDB.") from None
    if doc is None:
        raise HTTPException(status_code=404, detail="Không tìm thấy ảnh.")
    return doc


@app.get("/api/images/{image_id}")
def image_json(image_id: str):
    doc = load_generated_image(image_id)
    if "scene" in doc:
        return {"id": doc["_id"], "width": doc["width"], "height": doc["height"], "scene_bytes": doc.get("scene_bytes", 0), "scene": doc["scene"]}
    return {
        "id": doc["_id"],
        "width": doc.get("width", 512),
        "height": doc.get("height", 512),
        "model": doc.get("model", "FLUX.1-schnell"),
        "style": doc.get("style", "photorealistic"),
        "prompt": doc.get("prompt", ""),
        "image_bytes": doc.get("image_bytes", len(doc.get("image_data", b""))),
        "created_at": str(doc.get("created_at", ""))
    }


@app.get("/api/images/{image_id}/file")
def image_file(image_id: str, download: bool = False):
    doc = load_generated_image(image_id)
    if "image_data" in doc:
        ctype = doc.get("content_type", "image/jpeg")
        ext = "jpg" if "jpeg" in ctype or "jpg" in ctype else "png"
        return Response(doc["image_data"], media_type=ctype, headers={
            "Content-Disposition": f"{'attachment' if download else 'inline'}; filename=ai-art-{image_id[:8]}.{ext}",
            "Cache-Control": "public, max-age=86400",
        })
    return Response(image_service.render_svg(doc), media_type="image/svg+xml", headers={
        "Content-Security-Policy": "default-src 'none'; sandbox",
        "Content-Disposition": f"{'attachment' if download else 'inline'}; filename=illustration-{image_id}.svg",
        "Cache-Control": "private, max-age=3600",
    })


@app.get("/api/images/{image_id}/svg")
def image_svg(image_id: str, download: bool = False):
    doc = load_generated_image(image_id)
    if "image_data" in doc:
        return image_file(image_id, download=download)
    return Response(image_service.render_svg(doc), media_type="image/svg+xml", headers={
        "Content-Security-Policy": "default-src 'none'; sandbox",
        "Content-Disposition": f"{'attachment' if download else 'inline'}; filename=illustration-{image_id}.svg",
        "Cache-Control": "private, max-age=3600",
    })


@app.get("/api/admission-visuals")
def list_admission_visuals(category: str = "", search: str = ""):
    return {"total": len(avs.list_all_visuals(category, search)), "items": avs.list_all_visuals(category, search)}


@app.get("/api/admission-visuals/{visual_id}")
def get_admission_visual_json(visual_id: str):
    data = avs.get_visual_by_id(visual_id)
    if not data:
        raise HTTPException(status_code=404, detail="Không tìm thấy visual JSON.")
    return data


@app.get("/api/admission-visuals/{visual_id}/render")
def render_admission_visual(visual_id: str, scale: int = 1, format: str = "svg", download: bool = False):
    data = avs.get_visual_by_id(visual_id)
    if not data:
        raise HTTPException(status_code=404, detail="Không tìm thấy visual JSON.")

    scale = max(1, min(int(scale), 4))
    fmt = str(format or "svg").lower().strip()

    if fmt == "webp":
        webp_bytes = avs.render_raster_visual(data, scale=scale, format="webp")
        return Response(
            webp_bytes,
            media_type="image/webp",
            headers={
                "Content-Disposition": f"{'attachment' if download else 'inline'}; filename={visual_id}@{scale}x.webp",
                "Cache-Control": "public, max-age=86400",
            }
        )

    if fmt == "png":
        png_bytes = avs.render_raster_visual(data, scale=scale, format="png")
        return Response(
            png_bytes,
            media_type="image/png",
            headers={
                "Content-Disposition": f"{'attachment' if download else 'inline'}; filename={visual_id}@{scale}x.png",
                "Cache-Control": "public, max-age=86400",
            }
        )

    svg_content = avs.render_svg_visual(data, scale=scale)
    return Response(
        svg_content,
        media_type="image/svg+xml",
        headers={
            "Content-Security-Policy": "default-src 'none'; sandbox",
            "Content-Disposition": f"{'attachment' if download else 'inline'}; filename={visual_id}@{scale}x.svg",
            "Cache-Control": "public, max-age=86400",
        }
    )


@app.get("/api/admission-visuals/{visual_id}/export-excel")
def export_admission_visual_excel(visual_id: str):
    data = avs.get_visual_by_id(visual_id)
    if not data:
        raise HTTPException(status_code=404, detail="Không tìm thấy visual để xuất Excel.")

    excel_buf = avs.export_visual_to_excel(data)
    safe_filename = f"{visual_id}_HUIT_2026.xlsx"
    return Response(
        excel_buf.getvalue(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": f"attachment; filename={safe_filename}",
            "Cache-Control": "no-cache",
        }
    )


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
    """Trigger real-time dataset scrape, KB rebuild, and visual sync on MongoDB Atlas."""
    try:
        import scrape_realtime_huit
        import build_real_kb
        import build_admission_visuals
        scraped_count = scrape_realtime_huit.run_realtime_scrape()
        build_real_kb.run_rebuild()
        visual_count = build_admission_visuals.build_all_visuals()
        return {
            "status": "success",
            "message": "Đã cào & đồng bộ thành công dữ liệu tuyển sinh HUIT thời gian thực!",
            "scraped_pages": scraped_count,
            "visuals_count": visual_count,
        }
    except Exception as e:
        print("Data sync error:", type(e).__name__, e)
        raise HTTPException(status_code=500, detail=f"Lỗi đồng bộ dữ liệu: {e}") from None


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


class VectorSearchTestRequest(BaseModel):
    query: str = Field(min_length=1, max_length=500)
    top_k: int = Field(default=5, ge=1, le=20)


@app.post("/api/admin/login")
def admin_login(req: LoginRequest, request: Request):
    expected_token = (os.environ.get("ADMIN_TOKEN", "") or "huit_admin_2026").strip()
    expected_user = (os.environ.get("ADMIN_USERNAME", "") or "khaihiep").strip()
    expected_pass = (os.environ.get("ADMIN_PASSWORD", "") or "123").strip()

    token_candidate = None
    if req.admin_token and req.admin_token.strip():
        t = req.admin_token.strip()
        if hmac.compare_digest(t, expected_token) or hmac.compare_digest(t, expected_pass):
            token_candidate = expected_token
    elif req.username and req.password:
        u = req.username.strip()
        p = req.password.strip()
        if hmac.compare_digest(u, expected_user) and hmac.compare_digest(p, expected_pass):
            token_candidate = expected_token

    if not token_candidate:
        enforce_login_rate_limit(request)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Tài khoản hoặc mật khẩu không chính xác. Vui lòng kiểm tra lại.",
        )

    return {
        "status": "success",
        "message": "Đăng nhập hệ thống quản trị HUIT thành công.",
        "token": expected_token,
        "username": expected_user,
    }


@app.post("/api/admin/verify-token")
def verify_admin_token(x_admin_token: str = Header(default="")):
    require_admin(x_admin_token)
    expected_user = (os.environ.get("ADMIN_USERNAME", "") or "khaihiep").strip()
    return {"status": "success", "message": "Token quản trị hợp lệ.", "username": expected_user}


@app.get("/api/admin/kb-list")
def list_kb_chunks(
    search: str = "",
    category: str = "",
    limit: int = 100,
    x_admin_token: str = Header(default="")
):
    require_admin(x_admin_token)
    rag_core._init()
    import re
    coll = rag_core._mongo[rag_core.DB][rag_core.COLL]
    
    filter_query = {}
    if category and category != "all":
        filter_query["category"] = category
    if search.strip():
        regex_pattern = re.escape(search.strip())
        filter_query["$or"] = [
            {"title": {"$regex": regex_pattern, "$options": "i"}},
            {"text": {"$regex": regex_pattern, "$options": "i"}},
            {"major_code": {"$regex": regex_pattern, "$options": "i"}}
        ]
        
    docs = list(coll.find(filter_query, {"_id": 0, "embedding": 0}).limit(limit))
    total_count = coll.count_documents(filter_query)
    
    return {
        "total": total_count,
        "returned": len(docs),
        "documents": docs
    }


@app.get("/api/admin/logs")
def get_query_logs(limit: int = 50, x_admin_token: str = Header(default="")):
    require_admin(x_admin_token)
    rag_core._init()
    coll = rag_core._mongo[rag_core.DB]["rag_events"]
    
    logs = list(coll.find({}, {"_id": 0}).sort("created_at", -1).limit(limit))
    for item in logs:
        if isinstance(item.get("created_at"), datetime):
            item["created_at"] = item["created_at"].isoformat()
            
    return {
        "count": len(logs),
        "logs": logs
    }


@app.post("/api/admin/test-vector-search")
def test_vector_search(req: VectorSearchTestRequest, x_admin_token: str = Header(default="")):
    require_admin(x_admin_token)
    started = time.perf_counter()
    docs = rag_core.retrieve(req.query, top_k=req.top_k)
    elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
    
    results = []
    for d in docs:
        results.append({
            "title": rag_core._clean_doc_title(d.get("title")),
            "category": d.get("category"),
            "year": d.get("year"),
            "major_code": d.get("major_code"),
            "score": round(d.get("score", 0), 4),
            "url": d.get("source_url") or d.get("url"),
            "text": d.get("text", "")[:400]
        })
        
    return {
        "query": req.query,
        "elapsed_ms": elapsed_ms,
        "retrieved_count": len(results),
        "results": results
    }


@app.get("/docs", include_in_schema=False)
async def custom_swagger_ui_html():
    return get_swagger_ui_html(
        openapi_url=app.openapi_url,
        title=app.title + " - Swagger UI",
        swagger_js_url="/static/swagger-ui/swagger-ui-bundle.js",
        swagger_css_url="/static/swagger-ui/swagger-ui.css",
    )


@app.get("/api/system/status")
def system_telemetry():
    return health_service.get_system_health(quick=False)


@app.get("/admin")
@app.get("/status")
@app.get("/command-center")
@app.get("/health/dashboard")
def command_center():
    return FileResponse(os.path.join(HERE, "static", "control_center.html"))


@app.get("/admin-portal")
@app.get("/admin-classic")
def admin_portal_page():
    return FileResponse(os.path.join(HERE, "static", "admin.html"))


@app.get("/workflow")
def workflow_page():
    return FileResponse(os.path.join(HERE, "static", "control_center.html"))


@app.get("/")
def index():
    return FileResponse(os.path.join(HERE, "static", "index.html"))


app.mount("/static", StaticFiles(directory=os.path.join(HERE, "static")), name="static")
