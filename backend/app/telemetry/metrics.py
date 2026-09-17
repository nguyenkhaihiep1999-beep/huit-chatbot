import time
import hashlib
from datetime import datetime, timezone
from typing import Dict, Any, Optional
from backend.app.config import settings
from backend.app.data_access.operations import telemetry_operations
from backend.app.rag.intent import normalize_text
from backend.app.telemetry.logger import get_current_request_id, logger

class LatencyBreakdown:
    def __init__(self, request_id: Optional[str] = None):
        self.request_id = request_id or get_current_request_id()
        self.start_time = time.perf_counter()
        # Khởi tạo đầy đủ 10 số đo hiệu năng bắt buộc của hệ thống
        self.timings: Dict[str, float] = {
            "cache_lookup": 0.0,
            "embedding": 0.0,
            "vector_search": 0.0,
            "keyword_search": 0.0,
            "rerank": 0.0,
            "visual_lookup": 0.0,
            "llm_ttft": 0.0,
            "llm_generation": 0.0,
            "cache_write": 0.0,
        }
        self.active_spans: Dict[str, float] = {}

    def start_span(self, name: str):
        self.active_spans[name] = time.perf_counter()

    def end_span(self, name: str) -> float:
        if name in self.active_spans:
            elapsed = (time.perf_counter() - self.active_spans.pop(name)) * 1000
            self.timings[name] = round(elapsed, 2)
            return self.timings[name]
        return 0.0

    def record_metric(self, name: str, value_ms: float):
        self.timings[name] = round(value_ms, 2)

    def get_total_ms(self) -> float:
        return round((time.perf_counter() - self.start_time) * 1000, 2)

    def to_dict(self) -> Dict[str, Any]:
        data = dict(self.timings)
        total = self.get_total_ms()
        data["total"] = total
        data["total_ms"] = total
        data["request_id"] = self.request_id
        return data

def log_event(
    question: str,
    response_data: Dict[str, Any],
    elapsed_ms: float,
    intent: str,
    cached: bool = False,
    error: Optional[str] = None,
    timings: Optional[Dict[str, Any]] = None,
    request_id: Optional[str] = None
) -> None:
    """
    Ghi nhận log sự kiện ẩn danh (Anonymized telemetry log).
    BẢO MẬT & QUYỀN RIÊNG TƯ:
    - Tuyệt đối KHÔNG lưu nội dung văn bản thô của câu hỏi (plain text question).
    - Tuyệt đối KHÔNG lưu lịch sử hội thoại (chat history), API key hay thông tin nhạy cảm.
    - Chỉ lưu trữ mã băm SHA256 (question_hash), độ dài câu hỏi (question_length) và metadata vận hành.
    """
    req_id = request_id or get_current_request_id() or "internal"
    safe_timings: Dict[str, float] = {}
    if timings and isinstance(timings, dict):
        for k, v in timings.items():
            if isinstance(v, (int, float)):
                safe_timings[k] = float(v)

    try:
        telemetry_operations.record_telemetry_event({
            "request_id": req_id,
            "created_at": datetime.now(timezone.utc),
            "question_hash": hashlib.sha256(normalize_text(question).encode("utf-8")).hexdigest(),
            "question_length": len(question),
            "intent": intent,
            "cached": cached,
            "fallback": bool(response_data.get("meta", {}).get("fallback")),
            "source_count": len(response_data.get("sources", [])),
            "source_titles": [s.get("title", "")[:160] for s in response_data.get("sources", [])],
            "answer_length": len(response_data.get("answer", "")),
            "elapsed_ms": max(0.0, float(elapsed_ms)),
            "timings": safe_timings,
            "model": settings.OPENROUTER_MODEL,
            "kb_version": settings.KB_VERSION,
            "rag_version": settings.RAG_VERSION,
            "error": str(error)[:500] if error else None,
        }, request_id=req_id)
    except Exception as exc:
        logger.warning(f"Event logging warning: {exc}")

