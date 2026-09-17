"""
health.py
Đầu mối kiểm tra sức khỏe hệ thống (Health Check Probes) theo chuẩn Cloud-Native:
- /health/live (Liveness Probe): Kiểm tra tiến trình ứng dụng còn sống (0ms, không phụ thuộc ngoại vi).
- /health/ready (Readiness Probe): Kiểm tra toàn diện sự sẵn sàng của hệ thống:
  + Kết nối và độ trễ MongoDB Atlas
  + Kết nối Redis / Cache
  + Bộ điều hợp lưu trữ bền vững (StorageAdapter)
  + Tình trạng worker và số lượng job bị kẹt (stuck jobs)
  + Kho tri thức HUIT (huit_kb)
  + Trả về 200 nếu sẵn sàng nhận traffic, 503 nếu suy thoái nghiêm trọng.
"""
import time
from datetime import datetime, timezone
from typing import Any, Dict

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from backend.app.config import settings
from backend.app.data_access.operations.system_operations import read_database_snapshot
from backend.app.storage.storage_adapter import get_storage_adapter
from backend.app.cache.redis_client import check_redis_health

router = APIRouter()


@router.get("/health/live")
@router.get("/api/health/live")
async def liveness_probe():
    """Liveness Probe: Xác nhận tiến trình Python/FastAPI đang chạy và phản hồi sự kiện."""
    return JSONResponse(
        status_code=200,
        content={
            "status": "alive",
            "service": settings.PROJECT_NAME,
            "version": settings.VERSION,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
    )


@router.get("/health/ready")
@router.get("/api/health/ready")
async def readiness_probe():
    """
    Readiness Probe: Đánh giá toàn diện các thành phần phụ thuộc trước khi nhận tải.
    Kiểm tra MongoDB, Redis, Object Storage, Worker Leases, Stuck Jobs.
    """
    now_dt = datetime.now(timezone.utc)
    components: Dict[str, Any] = {}
    is_ready = True

    # 1. Kiểm tra MongoDB qua LTX registered operation boundary
    mongo_start = time.perf_counter()
    try:
        snapshot = read_database_snapshot(request_id="health-ready")
        mongo_latency_ms = round((time.perf_counter() - mongo_start) * 1000, 2)
        components["mongodb"] = {
            "status": "healthy",
            "latency_ms": mongo_latency_ms,
            "database": snapshot["database"]
        }
        components["job_queue"] = {
            "status": "healthy" if snapshot["stuck_jobs"] == 0 else "warning_stuck_jobs_detected",
            "queued_jobs": snapshot["queued_jobs"],
            "stuck_jobs": snapshot["stuck_jobs"],
        }
        components["knowledge_base"] = {
            "status": "healthy" if snapshot["kb_documents"] > 0 else "empty",
            "kb_version": settings.KB_VERSION,
            "documents_count": snapshot["kb_documents"],
        }
    except Exception as e:
        is_ready = False
        components["mongodb"] = {
            "status": "unhealthy",
            "error": type(e).__name__
        }
        components["job_queue"] = {"status": "unknown"}
        components["knowledge_base"] = {"status": "unknown"}

    # 2. Kiểm tra Redis
    try:
        redis_res = await check_redis_health()
        components["redis"] = redis_res
        if redis_res.get("status") == "unhealthy" and settings.IS_PRODUCTION:
            is_ready = False
    except Exception as e:
        components["redis"] = {"status": "unhealthy", "error": str(e)}
        if settings.IS_PRODUCTION:
            is_ready = False

    # 3. Kiểm tra Storage Adapter
    try:
        storage = get_storage_adapter()
        storage_health = storage.check_health()
        components["storage"] = storage_health
        if storage_health.get("status") in ("unhealthy", "unconfigured"):
            if settings.IS_PRODUCTION or storage_health.get("status") == "unhealthy":
                is_ready = False
    except Exception as e:
        is_ready = False
        components["storage"] = {"status": "unhealthy", "error": str(e)}

    status_str = "ready" if is_ready else "degraded"
    status_code = 200 if is_ready else 503

    return JSONResponse(
        status_code=status_code,
        content={
            "status": status_str,
            "service": settings.PROJECT_NAME,
            "version": settings.VERSION,
            "environment": "production" if settings.IS_PRODUCTION else "development",
            "timestamp": now_dt.isoformat(),
            "components": components
        }
    )


@router.get("/health")
@router.get("/api/health")
async def health_backward_compatibility():
    """Đầu mối tương thích ngược cho các bộ giám sát cũ."""
    resp = await readiness_probe()
    import json
    content = json.loads(resp.body.decode("utf-8"))
    mongo_comp = content.get("components", {}).get("mongodb", {})
    if mongo_comp.get("status") == "healthy":
        content["database"] = "connected"
    else:
        content["database"] = f"error: {mongo_comp.get('error', 'disconnected')}"

    if resp.status_code == 200:
        content["status"] = "healthy"
    else:
        content["status"] = "degraded"

    return JSONResponse(status_code=resp.status_code, content=content)


@router.get("/api/suggested-questions")
async def get_suggested_questions():
    """Gợi ý các câu hỏi tiêu biểu cho người dùng."""
    return {
        "questions": [
            "HUIT có những ngành đào tạo nào?",
            "Mã ngành & tổ hợp xét tuyển ngành Trí tuệ nhân tạo HUIT?",
            "Học phí trung bình một học kỳ tại HUIT là bao nhiêu?",
            "Điểm sàn xét tuyển đại học chính quy 2026 HUIT bao nhiêu?",
            "Chính sách học bổng giảm 50% học phí HK1 dành cho các ngành nào?",
            "Ngành Công nghệ thông tin xét các tổ hợp môn nào?",
            "Hồ sơ và thủ tục nhập học năm 2026 cần những gì?"
        ]
    }
