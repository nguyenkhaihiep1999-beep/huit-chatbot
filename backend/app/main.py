import time
import uuid
from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from backend.app.config import settings
from backend.app.middleware.rate_limiter import RateLimitMiddleware
from backend.app.telemetry.logger import set_current_request_id, logger
from backend.app.api.routes.chat import router as chat_router
from backend.app.api.routes.visuals import router as visuals_router
from backend.app.api.routes.images import router as images_router
from backend.app.api.routes.admin import router as admin_router
from backend.app.api.routes.health import router as health_router
from backend.app.api.routes.artifacts import router as artifacts_router
from backend.app.api.routes.auth import router as auth_router

from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Quản lý vòng đời khởi động và kết thúc ứng dụng (Lifespan Context Manager)."""
    # 1. Startup: Xác thực cấu hình và kiểm tra Storage Adapter
    logger.info("Khởi động ứng dụng HUIT Chatbot: Xác thực cấu hình bảo mật...")
    settings.validate_security_config()
    try:
        from backend.app.storage.storage_adapter import get_storage_adapter
        storage = get_storage_adapter()
        h = storage.check_health()
        logger.info(f"Storage Adapter [{h.get('backend')}]: Status {h.get('status')}")
    except Exception as e:
        logger.warning(f"Lỗi khởi tạo storage adapter: {e}")
        if settings.IS_PRODUCTION:
            raise RuntimeError(f"Storage không khả dụng trên production: {e}")

    yield

    # 2. Shutdown: Đóng an toàn các kết nối tài nguyên ngoại vi
    logger.info("Đang tắt ứng dụng HUIT Chatbot an toàn (Graceful Shutdown)...")
    try:
        from backend.app.repositories.mongo_repository import MongoRepository
        MongoRepository.close()
    except Exception:
        pass
    try:
        from backend.app.cache.redis_client import close_redis_connection
        await close_redis_connection()
    except Exception:
        pass


# Tắt tài liệu Swagger UI/OpenAPI ở môi trường production
docs_url = None if settings.IS_PRODUCTION else "/docs"
redoc_url = None if settings.IS_PRODUCTION else "/redoc"
openapi_url = None if settings.IS_PRODUCTION else "/openapi.json"

app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    description="Hệ thống RAG Chatbot Tuyển sinh Đại học Công Thương TP.HCM (HUIT)",
    docs_url=docs_url,
    redoc_url=redoc_url,
    openapi_url=openapi_url,
    lifespan=lifespan
)

# CORS Middleware: Cấu hình an toàn từ biến môi trường CORS_ALLOWED_ORIGINS
# Tuyệt đối không dùng allow_origins=["*"] cùng allow_credentials=True
cors_origins = settings.CORS_ALLOWED_ORIGINS
has_wildcard = "*" in cors_origins
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=not has_wildcard,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Rate Limiter Middleware: Bảo vệ tần suất request
app.add_middleware(RateLimitMiddleware)

# Middleware tự động cấp phát và gắn Request ID
@app.middleware("http")
async def request_id_middleware(request: Request, call_next):
    req_id = request.headers.get("X-Request-ID") or f"req-{uuid.uuid4().hex[:12]}"
    set_current_request_id(req_id)
    request.state.request_id = req_id

    start_time = time.perf_counter()
    response = await call_next(request)
    process_time = (time.perf_counter() - start_time) * 1000

    response.headers["X-Request-ID"] = req_id
    response.headers["X-Process-Time-MS"] = f"{process_time:.2f}"
    return response

# CSRF Protection Middleware cho các request thay đổi dữ liệu có dùng Session Cookie
@app.middleware("http")
async def csrf_middleware(request: Request, call_next):
    if request.method in ("POST", "PUT", "PATCH", "DELETE"):
        path = request.url.path
        is_exempt = (
            path == f"{settings.API_PREFIX}/auth/session" or
            path == f"{settings.API_PREFIX}/admin/login" or
            path in ("/docs", "/openapi.json", "/redoc")
        )
        if not is_exempt:
            from backend.app.services.auth_service import (
                verify_session_token,
                verify_csrf_token,
                verify_admin_token_get_session
            )
            from fastapi.responses import JSONResponse

            # Phân tách rõ ràng: Route Admin kiểm tra Admin Cookie; Route User kiểm tra User Cookie
            is_admin_path = path.startswith(f"{settings.API_PREFIX}/admin")

            # 1. Kiểm tra Admin Session Cookie ('huit_admin_token') cho các endpoint quản trị (/api/admin/*)
            if is_admin_path:
                cookie_admin = request.cookies.get("huit_admin_token")
                if cookie_admin:
                    admin_session_id = verify_admin_token_get_session(cookie_admin.strip())
                    if not admin_session_id:
                        return JSONResponse(
                            status_code=401,
                            content={
                                "error_code": "ADMIN_SESSION_INVALID",
                                "message": "Phiên quản trị viên không hợp lệ hoặc đã bị thu hồi/hết hạn."
                            }
                        )
                    csrf_token = request.headers.get("X-CSRF-Token")
                    if not csrf_token or not verify_csrf_token(admin_session_id, csrf_token):
                        return JSONResponse(
                            status_code=403,
                            content={
                                "error_code": "CSRF_TOKEN_INVALID",
                                "message": "CSRF token cho quản trị viên không hợp lệ hoặc đã hết hạn."
                            }
                        )

            # 2. Kiểm tra User Session Cookie ('huit_session_id') cho các endpoint người dùng (/api/chat, /api/chat-stream, ...)
            else:
                cookie_user = request.cookies.get("huit_session_id")
                if cookie_user:
                    verified_user = verify_session_token(cookie_user.strip())
                    if not verified_user:
                        return JSONResponse(
                            status_code=401,
                            content={
                                "error_code": "SESSION_INVALID",
                                "message": "Phiên làm việc không hợp lệ hoặc đã hết hạn."
                            }
                        )
                    if verified_user and verified_user != "anonymous":
                        csrf_token = request.headers.get("X-CSRF-Token")
                        if not csrf_token or not verify_csrf_token(verified_user, csrf_token):
                            return JSONResponse(
                                status_code=403,
                                content={
                                    "error_code": "CSRF_TOKEN_INVALID",
                                    "message": "CSRF token không hợp lệ hoặc đã hết hạn."
                                }
                            )
    return await call_next(request)

# Đăng ký các Routers (Toàn bộ API đặt dưới prefix /api hoặc /health)
app.include_router(chat_router, prefix=settings.API_PREFIX, tags=["Chat"])
app.include_router(visuals_router, prefix=settings.API_PREFIX, tags=["Admission Visuals"])
app.include_router(images_router, prefix=settings.API_PREFIX, tags=["Image Generation"])
app.include_router(admin_router, prefix=settings.API_PREFIX, tags=["Admin"])
app.include_router(artifacts_router, prefix=settings.API_PREFIX, tags=["Artifacts"])
app.include_router(auth_router, prefix=settings.API_PREFIX, tags=["Authentication & Session"])
app.include_router(health_router, tags=["Health"])

@app.get("/")
async def root():
    resp = {
        "service": settings.PROJECT_NAME,
        "version": settings.VERSION,
        "health": "/health"
    }
    if not settings.IS_PRODUCTION:
        resp["api_docs"] = "/docs"
    return resp

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("backend.app.main:app", host="0.0.0.0", port=8000, reload=True)
