from datetime import datetime, timezone
import json
import time
import re
from typing import Generator, List, Dict, Any, Optional
from backend.app.config import settings
from backend.app.rag.intent import classify_intent, expand_query
from backend.app.rag.guardrails import check_intent_guardrail, is_major_catalog_question, get_major_catalog_response
from backend.app.rag.retrieval import HybridRetriever
from backend.app.rag.reranker import retrieve
from backend.app.rag.generation import stream_llm, call_llm, clean_llm_text, fallback_answer
from backend.app.cache.mongo_cache import CacheManager
from backend.app.services.visual_service import resolve_visual_for_query
from backend.app.services.artifact_service import resolve_artifact_for_chat
from backend.app.telemetry.metrics import LatencyBreakdown, log_event
from backend.app.telemetry.logger import get_current_request_id, set_current_request_id


def _make_stream_event(
    event_type: str,
    sequence: int,
    request_id: str,
    payload: Optional[Dict[str, Any]] = None
) -> str:
    """Tạo envelope NDJSON v2 với strict schema validation."""
    from backend.app.api.schemas.streaming_v2 import create_ndjson_v2_event
    return create_ndjson_v2_event(
        event_type=event_type,
        sequence=sequence,
        stream_id=request_id,
        request_id=request_id,
        payload=payload
    )

SYSTEM_PROMPT = (
    "Bạn là AI Tư vấn Tuyển sinh thông minh và thân thiện của Trường Đại học Công Thương TP.HCM (HUIT). "
    "Bạn có khả năng trò chuyện tự nhiên, thấu hiểu ngữ cảnh và suy luận thông minh dựa trên nguyện vọng của thí sinh/phụ huynh. "
    "LƯU Ý ĐẶC BIỆT: Nhà trường đã CHÍNH THỨC CÔNG BỐ Điểm chuẩn trúng tuyển năm 2026 vào ngày 09/08/2026 "
    "(điểm thi THPT dao động 16.00 - 23.00 điểm, ngành cao nhất là Công nghệ kỹ thuật điều khiển và tự động hóa 23.00 điểm, "
    "Logistics 22.50đ, Công nghệ thực phẩm 22.00đ, Điện - Điện tử 22.00đ, Marketing 21.75đ, Thương mại điện tử 21.75đ, "
    "Luật kinh tế 21.75đ, CNTT 20.00đ, Trí tuệ nhân tạo 20.50đ). "
    "Thủ tục nhập học Tân sinh viên K2026 diễn ra từ 12/08/2026 đến hết 17h00 ngày 21/08/2026 tại nhaphoc.huit.edu.vn "
    "và xác nhận trên cổng Bộ GD&ĐT. Khi được hỏi về điểm chuẩn hay tuyển sinh, bạn hãy ưu tiên dùng dữ kiện trong "
    "NGỮ CẢNH HUIT và trích dẫn nguồn [n] chính xác, tuyệt đối không trả lời nhầm sang điểm sàn hay nói rằng trường chưa công bố điểm chuẩn."
)

ANSWER_TEMPLATE = (
    "NGỮ CẢNH TRÍ THỨC HUIT:\n{context}\n\n"
    "CÂU HỎI / YÊU CẦU: {question}\n\n"
    "Hãy trả lời bằng tiếng Việt tự nhiên, ấm áp và thông minh. Trích dẫn [n] ngay sau các dữ kiện chính xác từ ngữ cảnh. "
    "Nếu câu hỏi mang tính trò chuyện hoặc tư vấn cá nhân, hãy trả lời tự nhiên đúng tư cách là AI Tư vấn Tuyển sinh HUIT."
)

def _clean_doc_title(title: Optional[str]) -> str:
    if not title or any(k in title for k in ["FPT Shop", "CellphoneS", "Znews"]):
        return "Thông tin Tuyển sinh & Học phí HUIT (Cổng chính thức)"
    return title.strip()


def _make_artifact_summary(visual_meta: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Tạo tóm tắt siêu nhẹ (<2KB) cho Artifact phục vụ stream và chat UI."""
    if not visual_meta or not isinstance(visual_meta, dict):
        return None
    art_id = visual_meta.get("id") or visual_meta.get("artifact_id") or visual_meta.get("visual_id")
    if not art_id:
        return None
    manifest = visual_meta.get("manifest") if isinstance(visual_meta.get("manifest"), dict) else {}
    render = manifest.get("render") if isinstance(manifest.get("render"), dict) else {}
    preview_url = (
        visual_meta.get("preview_url")
        or visual_meta.get("svg_url")
        or f"/api/artifacts/{art_id}/preview"
    )
    # Artifact tạo trong chat hiện được render preview đồng bộ. Ưu tiên trạng thái
    # tường minh/manifest; dữ liệu cache cũ có preview URL nhưng thiếu status được
    # xem là ready để UI không mắc kẹt ở trạng thái planned vô hạn.
    status = visual_meta.get("status") or render.get("status")
    if not status and preview_url:
        status = "ready"
    return {
        "artifact_id": str(art_id),
        "type": visual_meta.get("type", "document"),
        "title": visual_meta.get("title", "Tài liệu Tuyển sinh HUIT"),
        "preview_url": preview_url,
        "manifest_url": visual_meta.get("manifest_url") or visual_meta.get("json_url") or f"/api/artifacts/{art_id}",
        "available_formats": visual_meta.get("available_formats") or ["xlsx", "docx", "pdf", "png", "svg"],
        "chart_type": visual_meta.get("chart_type"),
        "status": status,
    }


def stream_answer(
    question: str,
    chat_history: Optional[List[dict]] = None,
    use_cache: bool = True,
    request_id: Optional[str] = None,
    owner_id: Optional[str] = None
) -> Generator[str, None, None]:
    """Phát luồng NDJSON Protocol v2 chuẩn Canonical duy nhất cho frontend."""
    req_id = set_current_request_id(request_id)
    timings = LatencyBreakdown(request_id=req_id)
    intent = classify_intent(question)
    seq = 1

    try:
        # 0. Khởi động phiên stream (Canonical Event 1: start)
        yield _make_stream_event("start", seq, req_id, {
            "version": "2.0.0",
            "timestamp": datetime.now(timezone.utc).isoformat()
        })
        seq += 1

        # 1. Intent Guardrail Check
        timings.start_span("guardrails")
        guard_res = check_intent_guardrail(question, chat_history=chat_history)
        timings.end_span("guardrails")
        
        if guard_res.get("is_handled"):
            answer_text = guard_res.get("answer", "")
            sources = guard_res.get("sources", [])
            trace = guard_res.get("trace", [])
            yield _make_stream_event("progress", seq, req_id, {
                "stage": "guardrails",
                "sources": sources,
                "trace": trace,
                "cached": False,
            })
            for word in re.findall(r'\S+|\s+', answer_text):
                seq += 1
                yield _make_stream_event("token", seq, req_id, {"token": word})
            seq += 1
            yield _make_stream_event("done", seq, req_id, {"latency_ms": timings.get_total_ms(), "cached": False})
            log_event(question, guard_res, timings.get_total_ms(), intent, timings=timings.to_dict(), request_id=req_id)
            return

        # 2. Major Catalog Check
        if is_major_catalog_question(question):
            timings.start_span("catalog_lookup")
            catalog_res = get_major_catalog_response()
            timings.end_span("catalog_lookup")
            if catalog_res:
                answer_text = catalog_res.get("answer", "")
                sources = catalog_res.get("sources", [])
                trace = catalog_res.get("trace", [])
                catalog_visual = resolve_visual_for_query("catalog", question, [])
                catalog_summary = _make_artifact_summary(catalog_visual)
                yield _make_stream_event("progress", seq, req_id, {
                    "stage": "catalog",
                    "sources": sources,
                    "trace": trace,
                    "visual": catalog_summary or catalog_visual,
                    "cached": False,
                })
                if catalog_summary:
                    seq += 1
                    yield _make_stream_event("artifact", seq, req_id, catalog_summary)

                for word in re.findall(r'\S+|\s+', answer_text):
                    seq += 1
                    yield _make_stream_event("token", seq, req_id, {"token": word})
                seq += 1
                yield _make_stream_event("done", seq, req_id, {"latency_ms": timings.get_total_ms(), "cached": False})
                log_event(question, catalog_res, timings.get_total_ms(), intent, timings=timings.to_dict(), request_id=req_id)
                return

        # 3. Cache Hit Check (0ms TTFT)
        timings.start_span("cache_lookup")
        cached_res = CacheManager.get_cached_response(question, chat_history) if use_cache else None
        timings.end_span("cache_lookup")

        if cached_res:
            answer_text = cached_res.get("answer", "")
            sources = cached_res.get("sources", [])
            trace = cached_res.get("trace", [])
            visual_meta = cached_res.get("visual") or cached_res.get("meta", {}).get("visual")
            visual_summary = _make_artifact_summary(visual_meta)
            yield _make_stream_event("progress", seq, req_id, {
                "stage": "cache",
                "sources": sources,
                "trace": trace,
                "visual": visual_summary or visual_meta,
                "cached": True
            })
            if visual_summary:
                seq += 1
                yield _make_stream_event("artifact", seq, req_id, visual_summary)

            for word in re.findall(r'\S+|\s+', answer_text):
                seq += 1
                yield _make_stream_event("token", seq, req_id, {"token": word})
            seq += 1
            yield _make_stream_event("done", seq, req_id, {"latency_ms": timings.get_total_ms(), "cached": True})
            log_event(question, cached_res, timings.get_total_ms(), intent, cached=True, timings=timings.to_dict(), request_id=req_id)
            return

        # 4. Retrieval Phase
        retrieval_query = question
        if chat_history and isinstance(chat_history, list) and len(question.split()) <= 8:
            user_msgs = [
                m.get("content", "") for m in chat_history
                if isinstance(m, dict) and m.get("role") in ("user", "human") and m.get("content")
            ]
            if user_msgs:
                retrieval_query = f"{user_msgs[-1]} {question}"

        docs = retrieve(retrieval_query, settings.TOP_K, timings=timings)

        if not docs:
            res = {"answer": "Không tìm thấy dữ liệu liên quan trong kho tri thức tuyển sinh HUIT.", "sources": []}
            yield _make_stream_event("progress", seq, req_id, {"stage": "retrieval_empty", "sources": [], "trace": [], "visual": None, "cached": False})
            seq += 1
            yield _make_stream_event("token", seq, req_id, {"token": res["answer"]})
            seq += 1
            yield _make_stream_event("done", seq, req_id, {"latency_ms": timings.get_total_ms(), "cached": False})
            return

        source_limit = min(3, len(docs))
        sources = [{
            "i": i,
            "title": _clean_doc_title(d.get("title")),
            "url": d.get("source_url") or d.get("url") or "https://ts.huit.edu.vn",
            "score": round(d.get("score", 0), 3),
            "text": d.get("text", "")[:300]
        } for i, d in enumerate(docs[:source_limit], 1)]

        context = "\n\n".join(
            f"[{i}] {_clean_doc_title(d.get('title'))} — {str(d.get('text', ''))[:1100]}"
            for i, d in enumerate(docs[:source_limit], 1)
        )

        history_str = ""
        if chat_history and isinstance(chat_history, list):
            formatted_turns = []
            for turn in chat_history[-6:]:
                role = "Người dùng" if turn.get("role") == "user" else "Trợ lý AI"
                formatted_turns.append(f"{role}: {turn.get('content', '')}")
            if formatted_turns:
                history_str = "\n\n[LỊCH SỬ HỘI THOẠI TRƯỚC ĐÓ]:\n" + "\n".join(formatted_turns) + "\n"

        trace = [
            {"step": 1, "name": "Nhận diện Ý định (NLU)", "detail": f"Ý định: {intent}", "status": "success"},
            {"step": 2, "name": "Truy vấn Kho tri thức HUIT", "detail": f"Vector Search & Keyword: Lấy {len(docs)} đoạn tri thức", "status": "success"},
            {"step": 3, "name": "Tối ưu & Xếp hạng Ngữ cảnh", "detail": f"Lọc {len(sources)} nguồn minh chứng khớp nhất", "status": "success"},
            {"step": 4, "name": "Tổng hợp qua LLM", "detail": f"Mô hình: {settings.GEMINI_MODEL} (Phát luồng thời gian thực)", "status": "success"}
        ]

        timings.start_span("visual_lookup")
        visual_meta = resolve_artifact_for_chat(intent, question, docs, owner_id=owner_id)
        if not visual_meta:
            visual_meta = resolve_visual_for_query(intent, question, docs)
        timings.end_span("visual_lookup")

        artifact_manifest = visual_meta.get("manifest") if (visual_meta and isinstance(visual_meta, dict)) else None
        visual_summary = _make_artifact_summary(visual_meta)

        # Phát progress ngay sau khi retrieval xong (~200ms)
        yield _make_stream_event("progress", seq, req_id, {
            "stage": "retrieval_complete",
            "sources": sources,
            "trace": trace,
            "visual": visual_summary or visual_meta,
            "cached": False,
        })

        if visual_summary:
            seq += 1
            yield _make_stream_event("artifact", seq, req_id, visual_summary)

        # 5. Stream Real LLM Tokens
        user_prompt = f"{history_str}{ANSWER_TEMPLATE.format(context=context, question=question)}"
        accumulated_text = ""
        used_fallback = False

        timings.start_span("llm_generation")
        llm_start_time = time.perf_counter()
        first_token_recorded = False
        try:
            for token_chunk in stream_llm(SYSTEM_PROMPT, user_prompt):
                if not first_token_recorded and token_chunk.strip():
                    ttft_ms = (time.perf_counter() - llm_start_time) * 1000
                    timings.record_metric("llm_ttft", ttft_ms)
                    first_token_recorded = True
                accumulated_text += token_chunk
                seq += 1
                yield _make_stream_event("token", seq, req_id, {"token": token_chunk})
        except Exception as exc:
            print("Streaming LLM error:", exc)
        timings.end_span("llm_generation")

        cleaned_acc = clean_llm_text(accumulated_text)
        if not cleaned_acc or len(cleaned_acc) < 25:
            used_fallback = True
            fallback_text = fallback_answer(question, docs)
            accumulated_text = fallback_text
            for word in re.findall(r'\S+|\s+', fallback_text):
                seq += 1
                yield _make_stream_event("token", seq, req_id, {"token": word})
        else:
            accumulated_text = cleaned_acc

        elapsed_ms = timings.get_total_ms()
        res_obj = {
            "answer": accumulated_text,
            "sources": sources,
            "trace": trace,
            "visual": visual_summary,
            "artifact": artifact_manifest,
            "meta": {
                "intent": intent,
                "fallback": used_fallback,
                "model": settings.GEMINI_MODEL,
                "kb_version": settings.KB_VERSION,
                "rag_version": settings.RAG_VERSION,
                "latency_ms": elapsed_ms,
                "visual": visual_summary,
                "artifact": artifact_manifest,
                "request_id": req_id
            }
        }

        if use_cache and accumulated_text:
            timings.start_span("cache_write")
            CacheManager.save_response(question, res_obj, chat_history)
            timings.end_span("cache_write")

        seq += 1
        yield _make_stream_event("done", seq, req_id, {"latency_ms": elapsed_ms, "cached": False})
        log_event(question, res_obj, elapsed_ms, intent, timings=timings.to_dict(), request_id=req_id)

    except Exception as exc:
        seq += 1
        yield _make_stream_event("error", seq, req_id, {
            "error_code": "RAG_STREAM_ERROR",
            "message": "Đã xảy ra sự cố trong quá trình xử lý phản hồi.",
            "retryable": True
        })


def answer(
    question: str,
    chat_history: Optional[List[dict]] = None,
    use_cache: bool = True,
    request_id: Optional[str] = None,
    owner_id: Optional[str] = None
) -> Dict[str, Any]:
    """Phản hồi đồng bộ (synchronous)."""
    full_tokens = []
    metadata = {}
    visual_meta = None
    artifact_manifest = None
    for line in stream_answer(question, chat_history=chat_history, use_cache=use_cache, request_id=request_id, owner_id=owner_id):
        try:
            item = json.loads(line.strip())
            item_type = item.get("type")
            payload = item.get("payload") if isinstance(item.get("payload"), dict) else item
            if item_type in ("progress", "meta"):
                metadata = {**payload, "request_id": item.get("request_id")}
                if payload.get("visual"):
                    visual_meta = payload.get("visual")
                if payload.get("artifact"):
                    artifact_manifest = payload.get("artifact")
            elif item_type in ("artifact", "artifact_planned"):
                if not visual_meta:
                    visual_meta = {
                        "id": payload.get("artifact_id"),
                        "title": payload.get("title"),
                        "type": payload.get("file_type") or payload.get("type"),
                        "chart_type": payload.get("chart_type")
                    }
            elif item_type == "preview_ready":
                if payload.get("visual"):
                    visual_meta = payload.get("visual")
            elif item_type in ("token", "text_delta"):
                full_tokens.append(payload.get("token") or payload.get("delta") or "")
        except Exception:
            pass

    return {
        "answer": "".join(full_tokens),
        "sources": metadata.get("sources", []),
        "trace": metadata.get("trace", []),
        "visual": visual_meta or metadata.get("visual"),
        "artifact": artifact_manifest or metadata.get("artifact"),
        "meta": {
            "model": settings.GEMINI_MODEL,
            "kb_version": settings.KB_VERSION,
            "rag_version": settings.RAG_VERSION,
            "request_id": metadata.get("request_id")
        }
    }
