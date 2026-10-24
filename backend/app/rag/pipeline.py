from datetime import datetime, timezone
import json
import time
import re
from typing import Generator, List, Dict, Any, Optional
from backend.app.config import settings
from backend.app.rag.intent import classify_intent, expand_query, extract_admission_entities
from backend.app.rag.guardrails import check_intent_guardrail, is_major_catalog_question, get_major_catalog_response
from backend.app.rag.retrieval import HybridRetriever
from backend.app.rag.reranker import retrieve
from backend.app.rag.generation import stream_llm, call_llm, clean_llm_text, fallback_answer, verify_and_clean_citations
from backend.app.rag.evidence_policy import EvidencePolicyEvaluator
from backend.app.decision_engine.redaction import create_canonical_evidence_bundle
from backend.app.cache.mongo_cache import CacheManager
from backend.app.services.visual_service import resolve_visual_for_query
from backend.app.services.artifact_service import resolve_artifact_for_chat
from backend.app.telemetry.metrics import LatencyBreakdown, log_event
from backend.app.telemetry.logger import get_current_request_id, set_current_request_id, logger
from backend.app.decision_engine.service import decision_service, is_intent_ambiguous
from backend.app.decision_engine.policies import INTENT_CHOICES
from backend.app.rag.profile import get_profile, KnowledgeProfile


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

def _clean_doc_title(title: Optional[str], default_title: str = "Tài liệu chính thức") -> str:
    if not title or any(k in title for k in ["FPT Shop", "CellphoneS", "Znews"]):
        return default_title
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


def log_decision_application(
    req_id: str,
    decision_type: str,
    mode: str,
    api_called: bool,
    result_accepted: bool,
    decision_applied: bool,
    apply_reason: str,
    baseline_choice: Optional[str] = None,
    selected_choice: Optional[str] = None,
    confidence: Optional[float] = None,
) -> Dict[str, Any]:
    """Ghi nhận telemetry mức pipeline khi xem xét và áp dụng quyết định Jev.

    Bảo mật & Quyền riêng tư:
    - Tuyệt đối KHÔNG ghi câu hỏi thô, tài liệu thô hoặc PII vào log.
    - Phân biệt rõ: đã gọi API (api_called), kết quả được chấp nhận (result_accepted),
      và quyết định thực sự được áp dụng vào luồng chat (decision_applied).
    """
    payload = {
        "event": "decision_application",
        "request_id": req_id,
        "decision_type": decision_type,
        "mode": mode,
        "api_called": api_called,
        "result_accepted": result_accepted,
        "decision_applied": decision_applied,
        "apply_reason": apply_reason,
        "baseline_choice": baseline_choice,
        "selected_choice": selected_choice,
        "confidence": round(confidence, 3) if confidence is not None else None,
    }
    logger.info("[DECISION_APPLICATION] %s", payload)
    return payload


def _decision_not_applied_reason(result) -> str:
    """Use structured execution evidence, not sanitized exception text."""
    if result.status == "skipped":
        return "skipped"
    reason = result._fallback_reason
    if reason == "timeout" and not result._api_called:
        return "budget_exhausted_before_call"
    return reason or "provider_fallback"


def _safe_retrieve(
    retriever_fn,
    query: str,
    top_k: int,
    timings: Optional[Any] = None,
    intent: Optional[str] = None,
    context_entities: Optional[Dict[str, Any]] = None,
    profile_id: Optional[str] = None,
) -> List[dict]:
    """Gọi hàm retrieve một cách an toàn, tự động thích ứng với signature của cả hàm thật lẫn test mock."""
    import inspect
    try:
        sig = inspect.signature(retriever_fn)
        params = sig.parameters
        accepts_var_keyword = any(p.kind == inspect.Parameter.VAR_KEYWORD for p in params.values())
        kwargs = {}
        if "timings" in params or accepts_var_keyword:
            kwargs["timings"] = timings
        if "intent" in params or accepts_var_keyword:
            kwargs["intent"] = intent
        if "context_entities" in params or accepts_var_keyword:
            kwargs["context_entities"] = context_entities
        if "profile_id" in params or accepts_var_keyword:
            kwargs["profile_id"] = profile_id
        return retriever_fn(query, top_k, **kwargs)
    except Exception:
        try:
            return retriever_fn(query, top_k, timings=timings)
        except Exception:
            return retriever_fn(query, top_k)


def stream_answer(
    question: str,
    chat_history: Optional[List[dict]] = None,
    use_cache: bool = True,
    request_id: Optional[str] = None,
    owner_id: Optional[str] = None,
    profile_id: Optional[str] = None,
) -> Generator[str, None, None]:
    """Phát luồng NDJSON Protocol v2 chuẩn Canonical duy nhất cho frontend."""
    profile = get_profile(profile_id)
    intent_mode = profile.jev_intent_mode
    evidence_mode = profile.jev_evidence_mode

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

        # 1. HUIT Admission Guardrail & Major Catalog Checks (Only for HUIT profile)
        if profile.id == "huit":
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
        cached_res = CacheManager.get_cached_response(question, chat_history, profile_id=profile.id) if use_cache else None
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

            first_cache_token = False
            for word in re.findall(r'\S+|\s+', answer_text):
                if not first_cache_token and word.strip():
                    timings.record_metric("e2e_content_ttft", timings.get_total_ms())
                    first_cache_token = True
                seq += 1
                yield _make_stream_event("token", seq, req_id, {"token": word})
            seq += 1
            yield _make_stream_event("done", seq, req_id, {"latency_ms": timings.get_total_ms(), "cached": True})
            log_event(question, cached_res, timings.get_total_ms(), intent, cached=True, timings=timings.to_dict(), request_id=req_id)
            if intent_mode != "off":
                log_decision_application(
                    req_id=req_id,
                    decision_type="intent",
                    mode=intent_mode,
                    api_called=False,
                    result_accepted=False,
                    decision_applied=False,
                    apply_reason="cache_hit_bypassed",
                    baseline_choice=intent,
                )
            if evidence_mode != "off":
                log_decision_application(
                    req_id=req_id,
                    decision_type="evidence_sufficiency",
                    mode=evidence_mode,
                    api_called=False,
                    result_accepted=False,
                    decision_applied=False,
                    apply_reason="cache_hit_bypassed",
                )
            return

        # 3.5 Jev Decision Engine: Intent Disambiguation (Chỉ gọi khi intent mơ hồ / general)
        jev_spent_ms = 0.0
        if intent_mode != "off":
            if is_intent_ambiguous(question, intent):
                timings.start_span("jev_intent")
                api_called = False
                result_accepted = False
                decision_applied = False
                apply_reason = "unknown"
                selected_choice = None
                confidence_val = None
                baseline_intent = intent
                try:
                    if evidence_mode != "off" and settings.JEV_TOTAL_BUDGET_MS >= 400.0:
                        budget_ms = min(settings.JEV_TOTAL_BUDGET_MS * 0.5, 1000.0)
                    else:
                        budget_ms = settings.JEV_TOTAL_BUDGET_MS
                    jev_intent_res = decision_service.decide_intent_sync(
                        question, intent, remaining_budget_ms=budget_ms, mode=intent_mode
                    )
                    if jev_intent_res:
                        api_called = jev_intent_res._api_called
                        intent_item = jev_intent_res.decisions.get("intent")
                        if intent_item:
                            selected_choice = intent_item.choice
                            confidence_val = intent_item.confidence

                        if jev_intent_res.status == "success":
                            result_accepted = True
                            if intent_mode == "assist":
                                if (
                                    intent_item
                                    and intent_item.choice
                                    and intent_item.choice != "out_of_scope"
                                    and intent_item.choice in INTENT_CHOICES
                                    and intent_item.confidence >= settings.JEV_CONFIDENCE_THRESHOLD
                                ):
                                    intent = intent_item.choice
                                    decision_applied = True
                                    apply_reason = "intent_updated"
                                elif intent_item and intent_item.confidence < settings.JEV_CONFIDENCE_THRESHOLD:
                                    apply_reason = "confidence_below_threshold"
                                else:
                                    apply_reason = "invalid_or_out_of_scope_choice"
                            else:
                                apply_reason = "shadow_mode_read_only"
                        else:
                            apply_reason = _decision_not_applied_reason(jev_intent_res)
                    else:
                        apply_reason = "provider_empty_response"
                except Exception as exc:
                    logger.warning("Jev intent disambiguation fallback: %s", type(exc).__name__)
                    apply_reason = f"exception_{type(exc).__name__}"
                finally:
                    jev_spent_ms += timings.end_span("jev_intent")
                    log_decision_application(
                        req_id=req_id,
                        decision_type="intent",
                        mode=intent_mode,
                        api_called=api_called,
                        result_accepted=result_accepted,
                        decision_applied=decision_applied,
                        apply_reason=apply_reason,
                        baseline_choice=baseline_intent,
                        selected_choice=selected_choice,
                        confidence=confidence_val,
                    )
            else:
                log_decision_application(
                    req_id=req_id,
                    decision_type="intent",
                    mode=intent_mode,
                    api_called=False,
                    result_accepted=False,
                    decision_applied=False,
                    apply_reason="intent_clear_no_call_needed",
                    baseline_choice=intent,
                )

        # 3.9 Entity Extraction & Clarification Check (HUIT profile only)
        if profile.id == "huit":
            admission_entities = extract_admission_entities(question, chat_history=chat_history)
            if admission_entities.get("missing_user_info") and admission_entities.get("clarification_prompt"):
                clarify_answer = admission_entities["clarification_prompt"]
                yield _make_stream_event("progress", seq, req_id, {
                    "stage": "clarification_needed",
                    "sources": [],
                    "trace": [{"step": 1, "name": "Đánh giá Yêu cầu", "detail": "Thiếu ngành học cụ thể để tra cứu", "status": "clarification"}],
                    "cached": False,
                })
                for word in re.findall(r'\S+|\s+', clarify_answer):
                    seq += 1
                    yield _make_stream_event("token", seq, req_id, {"token": word})
                seq += 1
                yield _make_stream_event("done", seq, req_id, {"latency_ms": timings.get_total_ms(), "cached": False})
                return
        else:
            admission_entities = {}


        # 4. Retrieval Phase (Sử dụng intent đã được JEV/baseline xác nhận, kèm context entities)
        retrieval_query = question
        if chat_history and isinstance(chat_history, list) and len(question.split()) <= 8:
            user_msgs = [
                m.get("content", "") for m in chat_history
                if isinstance(m, dict) and m.get("role") in ("user", "human") and m.get("content")
            ]
            if user_msgs:
                retrieval_query = f"{user_msgs[-1]} {question}"

        docs = _safe_retrieve(
            retrieve,
            retrieval_query,
            settings.TOP_K,
            timings=timings,
            intent=intent,
            context_entities=admission_entities,
            profile_id=profile.id,
        )


        if not docs:
            res = {"answer": profile.empty_kb_message, "sources": []}
            yield _make_stream_event("progress", seq, req_id, {"stage": "retrieval_empty", "sources": [], "trace": [], "visual": None, "cached": False})
            seq += 1
            yield _make_stream_event("token", seq, req_id, {"token": res["answer"]})
            seq += 1
            yield _make_stream_event("done", seq, req_id, {"latency_ms": timings.get_total_ms(), "cached": False})
            return

        # 4.5 Jev Decision Engine: Evidence Sufficiency Evaluation
        selected_choice = None
        confidence_val = None
        if evidence_mode != "off":
            if not docs:
                log_decision_application(
                    req_id=req_id,
                    decision_type="evidence_sufficiency",
                    mode=evidence_mode,
                    api_called=False,
                    result_accepted=False,
                    decision_applied=False,
                    apply_reason="no_docs_retrieved",
                )
            else:
                timings.start_span("jev_evidence")
                api_called = False
                result_accepted = False
                decision_applied = False
                apply_reason = "unknown"
                try:
                    remaining_budget_ms = max(0.0, settings.JEV_TOTAL_BUDGET_MS - jev_spent_ms)
                    if remaining_budget_ms < 200.0:
                        logger.warning(
                            "Jev evidence evaluation skipped: remaining budget insufficient (%.1f ms)",
                            remaining_budget_ms,
                        )
                        apply_reason = "budget_insufficient"
                    else:
                        jev_ev_res = decision_service.decide_evidence_sufficiency_sync(
                            question, docs, remaining_budget_ms=remaining_budget_ms, mode=evidence_mode
                        )
                        if jev_ev_res:
                            api_called = jev_ev_res._api_called
                            suff_item = jev_ev_res.decisions.get("sufficiency")
                            clarify_item = jev_ev_res.decisions.get("needs_clarification")
                            if suff_item:
                                selected_choice = suff_item.choice
                                confidence_val = suff_item.confidence

                            if jev_ev_res.status == "success":
                                result_accepted = True
                                if evidence_mode == "assist":
                                    if (
                                        suff_item
                                        and suff_item.choice in ("insufficient", "conflicting")
                                        and suff_item.confidence >= settings.JEV_CONFIDENCE_THRESHOLD
                                        and clarify_item
                                        and clarify_item.noul is not None
                                        and clarify_item.noul >= 0.70
                                    ):
                                        decision_applied = True
                                        apply_reason = "clarification_hint_injected"
                                    elif suff_item and suff_item.choice in ("sufficient", "partial"):
                                        apply_reason = "evidence_sufficient_no_override_needed"
                                    elif suff_item and suff_item.confidence < settings.JEV_CONFIDENCE_THRESHOLD:
                                        apply_reason = "confidence_below_threshold"
                                    elif clarify_item and (clarify_item.noul is None or clarify_item.noul < 0.70):
                                        apply_reason = "noul_below_threshold"
                                    else:
                                        apply_reason = "conditions_not_met"
                                else:
                                    apply_reason = "shadow_mode_read_only"
                            else:
                                apply_reason = _decision_not_applied_reason(jev_ev_res)
                        else:
                            apply_reason = "provider_empty_response"
                except Exception as exc:
                    logger.warning("Jev evidence evaluation fallback: %s", type(exc).__name__)
                    apply_reason = f"exception_{type(exc).__name__}"
                finally:
                    timings.end_span("jev_evidence")
                    log_decision_application(
                        req_id=req_id,
                        decision_type="evidence_sufficiency",
                        mode=evidence_mode,
                        api_called=api_called,
                        result_accepted=result_accepted,
                        decision_applied=decision_applied,
                        apply_reason=apply_reason,
                        selected_choice=selected_choice,
                        confidence=confidence_val,
                    )

        # 4.6 Evidence Policy & Supplementary Retrieval (Tối đa 1 lượt bổ sung trong ngân sách)
        policy_verdict = EvidencePolicyEvaluator.evaluate(
            question=question,
            docs=docs,
            intent=intent,
            entities=admission_entities,
            jev_sufficiency=selected_choice,
            jev_confidence=confidence_val,
            current_retrieval_round=1,
            max_retrieval_rounds=settings.MAX_RETRIEVAL_ROUNDS,
            profile=profile,
            jev_mode=evidence_mode,
        )

        rem_budget_for_supp = max(0.0, settings.JEV_TOTAL_BUDGET_MS - jev_spent_ms)
        if policy_verdict.needs_supplementary and policy_verdict.supplementary_query and rem_budget_for_supp >= 150.0:
            timings.start_span("supplementary_retrieval")
            try:
                supp_docs = _safe_retrieve(
                    retrieve,
                    policy_verdict.supplementary_query,
                    top_k=2,
                    timings=None,
                    intent=intent,
                    context_entities=admission_entities,
                    profile_id=profile.id,
                )

                if supp_docs:
                    seen_ids = set()
                    for d in docs:
                        dk = d.get("chunk_id") or str(d.get("_id")) or f"{d.get('source_url') or d.get('url')}::{d.get('page_number')}::{d.get('sku')}::{d.get('title')}"
                        seen_ids.add(dk)
                    added_any = False
                    for sd in supp_docs:
                        sdk = sd.get("chunk_id") or str(sd.get("_id")) or f"{sd.get('source_url') or sd.get('url')}::{sd.get('page_number')}::{sd.get('sku')}::{sd.get('title')}"
                        if sdk not in seen_ids:
                            docs.append(sd)
                            seen_ids.add(sdk)
                            added_any = True
                    if added_any:
                        policy_verdict = EvidencePolicyEvaluator.evaluate(
                            question=question,
                            docs=docs,
                            intent=intent,
                            entities=admission_entities,
                            jev_sufficiency=selected_choice,
                            jev_confidence=confidence_val,
                            current_retrieval_round=2,
                            max_retrieval_rounds=settings.MAX_RETRIEVAL_ROUNDS,
                            profile=profile,
                            jev_mode=evidence_mode,
                        )
            except Exception as e:
                logger.warning("Supplementary retrieval fallback: %s", type(e).__name__)
            finally:
                timings.end_span("supplementary_retrieval")

        source_limit = min(3, len(docs))
        canonical_bundle = create_canonical_evidence_bundle(docs, max_docs=source_limit, max_excerpt_chars=1100)

        sources = [{
            "i": item.get("idx", 1),
            "title": _clean_doc_title(item.get("title")),
            "url": item.get("url") or profile.default_source_url,
            "score": round(float(item.get("score", 0.0)), 3),
            "text": str(item.get("excerpt", ""))[:300],
            "year": item.get("year"),
            "category": item.get("category"),
            "major_code": item.get("major_code"),
            "effective_date": item.get("effective_date"),
            "page_number": item.get("page_number"),
            "sku": item.get("sku"),
            "chunk_id": item.get("chunk_id"),
            "product_type": item.get("product_type"),
            "verification_status": item.get("verification_status"),
        } for item in canonical_bundle]

        context_blocks = []
        for item in canonical_bundle:
            idx = item.get("idx", 1)
            t = _clean_doc_title(item.get("title"))
            page_info = f" (Trang {item['page_number']})" if item.get("page_number") else ""
            sku_info = f" [SKU: {item['sku']}]" if item.get("sku") else ""
            excerpt = item.get("excerpt", "")
            context_blocks.append(f"[{idx}] {t}{page_info}{sku_info} — {excerpt}")
        context = "\n\n".join(context_blocks)

        if evidence_mode == "assist" and decision_applied and apply_reason == "clarification_hint_injected":
            if profile.id == "ilt":
                context += (
                    "\n\n[LƯU Ý ĐÁNH GIÁ MINH CHỨNG]: Minh chứng hiện tại chưa đủ thông số chi tiết của sản phẩm hoặc yêu cầu đặt hàng. "
                    "Hãy cung cấp các thông số đã có căn cứ và lịch sự đề nghị khách hàng liên hệ trực tiếp phòng kinh doanh ILT (info@innovativelightingco.com hoặc (+84) 251 3514 366) hoặc cung cấp mã model/SKU cụ thể."
                )
            else:
                context += (
                    "\n\n[LƯU Ý ĐÁNH GIÁ MINH CHỨNG]: Minh chứng hiện tại chưa đủ dữ liệu chi tiết cho câu hỏi. "
                    "Hãy cung cấp thông tin hiện có và lịch sự đề nghị thí sinh cung cấp thêm chi tiết (ví dụ ngành học cụ thể hoặc năm xét tuyển)."
                )
        elif policy_verdict.evidence_guidance:
            context += f"\n\n{policy_verdict.evidence_guidance}"

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
            {"step": 2, "name": f"Truy vấn Kho tri thức {profile.name}", "detail": f"Vector Search & Keyword: Lấy {len(docs)} đoạn tri thức", "status": "success"},
            {"step": 3, "name": "Tối ưu & Xếp hạng Ngữ cảnh", "detail": f"Lọc {len(sources)} nguồn minh chứng khớp nhất", "status": "success"},
            {"step": 4, "name": "Tổng hợp qua LLM", "detail": f"Mô hình: {getattr(settings, 'QWEN_MODEL', 'qwen-2.5-72b-instruct') if getattr(settings, 'PRIMARY_LLM_PROVIDER', 'gemini') == 'qwen' else settings.GEMINI_MODEL} (Phát luồng thời gian thực)", "status": "success"}
        ]

        timings.start_span("visual_lookup")
        visual_meta = resolve_artifact_for_chat(intent, question, docs, owner_id=owner_id) if profile.id == "huit" else None
        if not visual_meta and profile.id == "huit":
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
        user_prompt = f"{history_str}{profile.answer_template.format(context=context, question=question)}"
        accumulated_text = ""
        used_fallback = False

        timings.start_span("llm_generation")
        llm_start_time = time.perf_counter()
        first_token_recorded = False
        try:
            for token_chunk in stream_llm(profile.system_prompt, user_prompt):
                if not first_token_recorded and token_chunk.strip():
                    ttft_ms = (time.perf_counter() - llm_start_time) * 1000
                    timings.record_metric("llm_ttft", ttft_ms)
                    timings.record_metric("e2e_content_ttft", timings.get_total_ms())
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

        # 5.5 Kiểm tra nguồn trích dẫn thuộc tập tài liệu đã truy xuất
        accumulated_text, citation_report = verify_and_clean_citations(accumulated_text, len(sources))

        elapsed_ms = timings.get_total_ms()
        current_model = (
            getattr(settings, "QWEN_MODEL", "qwen-2.5-72b-instruct")
            if getattr(settings, "PRIMARY_LLM_PROVIDER", "gemini") == "qwen"
            else settings.GEMINI_MODEL
        )
        res_obj = {
            "answer": accumulated_text,
            "sources": sources,
            "trace": trace,
            "visual": visual_summary,
            "artifact": artifact_manifest,
            "meta": {
                "profile_id": profile.id,
                "intent": intent,
                "fallback": used_fallback,
                "model": current_model,
                "provider": getattr(settings, "PRIMARY_LLM_PROVIDER", "gemini"),
                "policy_verdict": policy_verdict.verdict,
                "citations": citation_report,
                "kb_version": profile.kb_version,
                "rag_version": profile.rag_version,
                "latency_ms": elapsed_ms,
                "visual": visual_summary,
                "artifact": artifact_manifest,
                "request_id": req_id
            }
        }

        if use_cache and accumulated_text:
            timings.start_span("cache_write")
            CacheManager.save_response(question, res_obj, chat_history, profile_id=profile.id)
            timings.end_span("cache_write")

        seq += 1
        yield _make_stream_event("done", seq, req_id, {"latency_ms": elapsed_ms, "cached": False})
        log_event(question, res_obj, elapsed_ms, intent, timings=timings.to_dict(), request_id=req_id)

    except Exception as exc:
        logger.exception("Pipeline stream error: %s", exc)
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
    owner_id: Optional[str] = None,
    profile_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Phản hồi đồng bộ (synchronous)."""
    full_tokens = []
    metadata = {}
    visual_meta = None
    artifact_manifest = None
    for line in stream_answer(
        question,
        chat_history=chat_history,
        use_cache=use_cache,
        request_id=request_id,
        owner_id=owner_id,
        profile_id=profile_id,
    ):
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
            "profile_id": metadata.get("profile_id") or profile_id,
            "model": settings.GEMINI_MODEL,
            "kb_version": metadata.get("kb_version") or settings.KB_VERSION,
            "rag_version": metadata.get("rag_version") or settings.RAG_VERSION,
            "request_id": metadata.get("request_id")
        }
    }
