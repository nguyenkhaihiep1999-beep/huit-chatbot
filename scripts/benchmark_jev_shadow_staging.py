"""
benchmark_jev_shadow_staging.py
Bộ công cụ chuẩn bị và kiểm chứng JEV AI trên môi trường Staging bằng Shadow Mode.

Mục tiêu:
- Đánh giá chất lượng phân loại (Intent, Evidence Sufficiency, Needs Clarification) trên bộ dữ liệu synthetic 68 tình huống.
- Tính toán chính xác Ground Truth Accuracy & Macro-F1 trên các case được chấp nhận (requires_human_review == False).
- Tách rạch ròi tỷ lệ đồng thuận (Baseline Agreement) khỏi độ chính xác thực tế (Ground Truth Accuracy).
- Đo lường ảnh hưởng của Shadow Mode tới tốc độ chat (TTFT tới token đầu tiên, tổng thời gian, overhead) qua 5 profile.
- Xác nhận Shadow Mode không bao giờ thay đổi intent, context, hoặc câu trả lời của chatbot (Non-interference).
- Tuyệt đối giữ JEV_MODE=shadow; không bật assist mode và không tác động đến production.
- Không ghi đè report lịch sử; báo cáo chỉ chứa ID và dữ liệu tổng hợp ẩn danh, không chứa key hoặc dữ liệu người dùng.
- Tách rõ kết quả mock, baseline và live: Mock runner chỉ kiểm chứng công cụ, không chứng minh năng lực Jev.
"""
import argparse
import asyncio
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import random
import sys
import time
from typing import Any, Dict, List, Optional

# Add project root to sys.path
ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

import httpx

from backend.app.config import settings
from backend.app.decision_engine.contracts import (
    DecisionItem,
    DecisionRequest,
    DecisionResult,
    DecisionUsage,
    QuestionDefinition,
)
from backend.app.decision_engine.policies import (
    INTENT_CHOICES,
    SUFFICIENCY_CHOICES,
    get_evidence_sufficiency_questions,
    get_intent_decision_questions,
)
from backend.app.decision_engine.providers.base import (
    BaseDecisionProvider,
    DecisionAuthenticationError,
    DecisionRateLimitError,
    DecisionServerError,
    DecisionTimeoutError,
    DecisionValidationError,
)
from backend.app.decision_engine.providers.typesafe_jev import TypeSafeJevProvider
from backend.app.decision_engine.redaction import (
    anonymize_request_hash,
    build_evidence_decision_state,
    build_intent_decision_state,
    redact_text,
)
from backend.app.decision_engine.service import (
    CircuitBreaker,
    DecisionService,
    is_intent_ambiguous,
)
from backend.app.decision_engine.evaluation import (
    EVALUATION_DATASET,
    LABELING_RUBRIC,
    calculate_baseline_agreement,
    calculate_clarification_metrics,
    calculate_coverage_and_status,
    calculate_evidence_metrics,
    calculate_intent_metrics,
    calculate_latency_percentiles,
    measure_chat_performance,
)
from backend.app.rag.intent import classify_intent

# Giữ alias cho backward-compatibility
BENCHMARK_CASES = EVALUATION_DATASET


# ---------------------------------------------------------------------------
# MOCK STAGING TRANSPORT VỚI PHÂN PHỐI ĐỘ TRỄ THỰC TẾ & MAPPING CHÍNH XÁC
# ---------------------------------------------------------------------------
class StagingRealisticMockTransport(httpx.AsyncBaseTransport):
    """Giả lập máy chủ TypeSafe Jev với phân phối độ trễ và tỷ lệ lỗi thực tế.

    Hỗ trợ toàn bộ 68 câu hỏi trong EVALUATION_DATASET.
    Dùng khi chạy staging benchmark ở chế độ mock hoặc khi chưa có live API key.
    """

    def __init__(self, failure_rate: float = 0.0, rate_limit_rate: float = 0.0):
        super().__init__()
        self.failure_rate = failure_rate
        self.rate_limit_rate = rate_limit_rate
        self.call_count = 0

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.call_count += 1
        body_bytes = await request.aread()
        payload = json.loads(body_bytes.decode("utf-8"))

        # Mô phỏng độ trễ mạng thực tế: P50 ~ 110ms, P95 ~ 220ms
        simulated_delay = random.uniform(0.08, 0.22)
        await asyncio.sleep(simulated_delay)

        if self.rate_limit_rate > 0 and random.random() < self.rate_limit_rate:
            return httpx.Response(429, headers={"Retry-After": "0.1"})

        if self.failure_rate > 0 and random.random() < self.failure_rate:
            return httpx.Response(503, json={"error": "Service temporarily degraded"})

        # Suy luận câu trả lời dựa trên payload câu hỏi
        questions = payload.get("questions", {})
        answers = {}

        state_str = payload.get("state", "").lower()
        for q_id, q_def in questions.items():
            q_type = q_def.get("type", "choice")

            if q_id == "intent":
                matched_choice = "general"
                if any(k in state_str for k in ("hoc phi", "học phí", "tín chỉ", "tin chi", "tuition")):
                    matched_choice = "tuition"
                elif any(k in state_str for k in ("diem chuan", "điểm chuẩn", "cutoff", "trúng tuyển", "trung tuyen", "diem xet tuyen", "điểm xét tuyển")):
                    matched_choice = "cutoff"
                elif any(k in state_str for k in ("điểm sàn", "diem san", "ngưỡng", "floor_score")):
                    matched_choice = "floor_score"
                elif any(k in state_str for k in ("hoc bong", "học bổng", "scholarship", "miễn giảm", "mien giam")):
                    matched_choice = "scholarship"
                elif any(k in state_str for k in ("xet tuyen", "xét tuyển", "admission", "tuyen sinh", "tuyển sinh", "chỉ tiêu", "chi tieu", "nộp hồ sơ")):
                    matched_choice = "admission"
                elif any(k in state_str for k in ("nganh", "ngành", "major", "mã ngành", "tổ hợp")):
                    matched_choice = "major"
                elif any(k in state_str for k in ("viec lam", "việc làm", "career", "ra trường", "đồ họa")):
                    matched_choice = "career"
                elif any(k in state_str for k in ("dia chi", "địa chỉ", "hotline", "liên hệ")):
                    matched_choice = "contact"
                elif any(k in state_str for k in ("nhập học", "nhap hoc", "giấy tờ", "hồ sơ nhập học")):
                    matched_choice = "admission_procedure"
                elif any(k in state_str for k in ("vang", "vàng", "thoi tiet", "thời tiết", "pho", "phở", "vinfast", "cổ phiếu", "bóng đá", "màn hình xanh", "prompt bí mật", "mã độc hại", "làm giả", "out_of_scope")):
                    matched_choice = "out_of_scope"

                alt_choice = "admission" if matched_choice != "admission" else "general"
                answers[q_id] = {
                    "type": "choice",
                    "choice": matched_choice,
                    "confidence": round(random.uniform(0.88, 0.98), 2),
                    "probabilities": {
                        matched_choice: 0.92,
                        alt_choice: 0.08,
                    },
                }

            elif q_id == "needs_clarification":
                is_ambig = any(k in state_str for k in ("tim hieu", "tư vấn", "tu van", "chung", "hỗ trợ", "ho tro", "chuong trinh", "chương trình", "bao nhiêu một học kỳ", "bao giờ thì hết hạn", "tổ hợp xét tuyển gồm những môn gì"))
                prob_yes = 0.85 if is_ambig else 0.15
                answers[q_id] = {
                    "type": "noul",
                    "noul": prob_yes,
                }

            elif q_id == "sufficiency":
                suff_choice = "sufficient"
                if any(k in state_str for k in ("mâu thuẫn", "22.50", "20.00", "750.000", "950.000", "30/06", "15/07", "conflicting")):
                    suff_choice = "conflicting"
                elif any(k in state_str for k in ("lạc đề", "câu lạc bộ", "học phần hè", "vay vốn", "insufficient", "ky tuc xa", "ký túc xá", '"evidence_count": 0', '"evidence": []', "không có tài liệu")):
                    suff_choice = "insufficient"
                elif any(k in state_str for k in ("một phần", "thiếu lộ trình", "chỉ có học phí", "khen thưởng", "partial", "luat kinh te", "luật kinh tế")):
                    suff_choice = "partial"

                alt_suff = "partial" if suff_choice != "partial" else "sufficient"
                answers[q_id] = {
                    "type": "choice",
                    "choice": suff_choice,
                    "confidence": round(random.uniform(0.85, 0.96), 2),
                    "probabilities": {
                        suff_choice: 0.90,
                        alt_suff: 0.10,
                    },
                }

            elif q_type == "score":
                levels = q_def.get("criteria", [])
                answers[q_id] = {
                    "type": "score",
                    "score": float(len(levels) - 1) if levels else 1.0,
                    "confidence": 1.0,
                }
            elif q_type == "noul":
                answers[q_id] = {
                    "type": "noul",
                    "noul": 0.5,
                }
            else:
                answers[q_id] = {
                    "type": "choice",
                    "choice": "general",
                    "confidence": 0.90,
                }

        return httpx.Response(
            200,
            json={
                "answers": answers,
                "model": payload.get("model", "jev-latest"),
                "usage": {"input_tokens": 64, "output_tokens": 12},
            },
        )


# ---------------------------------------------------------------------------
# RUNNER CHÍNH: KIỂM CHỨNG STAGING BẰNG SHADOW MODE
# ---------------------------------------------------------------------------
class StagingShadowBenchmarkRunner:
    def __init__(self, mode: str = "mock", live_api_key: Optional[str] = None):
        self.mode = mode
        self.live_api_key = (live_api_key or os.getenv("TYPESAFE_API_KEY", "")).strip()
        self.records: List[Dict[str, Any]] = []

    def verify_staging_config(self) -> Dict[str, Any]:
        """Kiểm tra cấu hình staging và xác nhận an toàn."""
        saved_env = os.environ.get("APP_ENV")
        saved_mode = os.environ.get("JEV_MODE")
        prod_isolated = True
        try:
            os.environ["APP_ENV"] = "production"
            if "JEV_MODE" in os.environ:
                del os.environ["JEV_MODE"]
            test_prod_settings = settings.__class__()
            prod_isolated = (test_prod_settings.JEV_MODE == "off")
        finally:
            if saved_env is not None:
                os.environ["APP_ENV"] = saved_env
            elif "APP_ENV" in os.environ:
                del os.environ["APP_ENV"]
            if saved_mode is not None:
                os.environ["JEV_MODE"] = saved_mode
            elif "JEV_MODE" in os.environ:
                del os.environ["JEV_MODE"]

        # Kích hoạt JEV_MODE=shadow cho staging benchmark
        os.environ["JEV_MODE"] = "shadow"

        config_status = {
            "target_mode": "shadow",
            "active_mode": "shadow",
            "timeout_seconds": settings.JEV_TIMEOUT_SECONDS,
            "total_budget_ms": settings.JEV_TOTAL_BUDGET_MS,
            "max_concurrency": settings.JEV_MAX_CONCURRENCY,
            "confidence_threshold": settings.JEV_CONFIDENCE_THRESHOLD,
            "max_state_bytes": settings.JEV_MAX_STATE_BYTES,
            "production_default_is_off": prod_isolated,
            "api_key_configured": bool(self.live_api_key),
            "api_key_status": "CONFIGURED" if self.live_api_key else "NOT_CONFIGURED",
        }

        return config_status

    async def run_benchmark(self) -> Dict[str, Any]:
        """Thực thi đánh giá trên toàn bộ 68 câu hỏi synthetic và tính toán các chỉ số."""
        if self.mode == "live":
            if not self.live_api_key:
                raise RuntimeError(
                    "Không thể chạy live mode do thiếu TYPESAFE_API_KEY từ Secret Manager"
                )
            client = httpx.AsyncClient(timeout=settings.JEV_TIMEOUT_SECONDS)
            provider = TypeSafeJevProvider(api_key=self.live_api_key, client=client)
        else:
            mock_transport = StagingRealisticMockTransport()
            client = httpx.AsyncClient(transport=mock_transport)
            provider = TypeSafeJevProvider(api_key="mock-staging-key-safe", client=client)

        circuit_breaker = CircuitBreaker(failure_threshold=3, cooldown_seconds=10.0)
        service = DecisionService(
            provider=provider,
            circuit_breaker=circuit_breaker,
            max_concurrency=settings.JEV_MAX_CONCURRENCY,
            mode="shadow",
        )

        redaction_failures = 0
        latencies: List[float] = []

        for case in EVALUATION_DATASET:
            case_id = case["id"]
            group = case["group"]
            raw_q = case["question"]
            req_human = case.get("requires_human_review", False)

            # 1. Tính toán Baseline Intent từ Rule/Regex hiện tại
            baseline = classify_intent(raw_q)
            is_ambig = is_intent_ambiguous(raw_q, baseline)
            state_hash = anonymize_request_hash(raw_q)

            # 2. Kiểm tra Redaction an toàn
            state_json = build_intent_decision_state(
                question=raw_q,
                current_intent=baseline,
                max_bytes=settings.JEV_MAX_STATE_BYTES,
            )
            for token in case.get("sensitive_tokens", []):
                if token in state_json:
                    redaction_failures += 1

            # 3. Intent & Clarification workflow
            t_start = time.perf_counter()
            intent_status = "skipped"
            jev_choice = None
            confidence = 0.0
            predicted_clarify = None
            queue_wait_ms = 0.0
            retry_cnt = 0
            fallback_reason = None
            intent_tokens = 0

            clarification_status = "not_applicable"
            clarification_tokens = 0

            try:
                jev_res = await service.decide_intent(
                    question=raw_q,
                    current_intent=baseline,
                    remaining_budget_ms=settings.JEV_TOTAL_BUDGET_MS,
                )
                if jev_res:
                    intent_status = jev_res.status
                    queue_wait_ms = getattr(jev_res, "_queue_wait_ms", 0.0)
                    retry_cnt = getattr(jev_res, "_retry_count", 0)
                    fallback_reason = getattr(jev_res, "_fallback_reason", None)
                    if jev_res.usage:
                        intent_tokens = jev_res.usage.input_tokens + jev_res.usage.output_tokens
                    if intent_status == "success":
                        if "intent" in jev_res.decisions:
                            item = jev_res.decisions["intent"]
                            jev_choice = item.choice
                            confidence = item.confidence

                    if case.get("expected_needs_clarification") is not None:
                        if intent_status == "success":
                            if "needs_clarification" in jev_res.decisions:
                                clarify_item = jev_res.decisions["needs_clarification"]
                                if clarify_item.noul is not None:
                                    clarification_status = "success"
                                    predicted_clarify = (clarify_item.noul >= 0.50)
                                else:
                                    clarification_status = "missing"
                            else:
                                clarification_status = "missing"
                        else:
                            clarification_status = intent_status
                        clarification_tokens = intent_tokens
            except Exception:
                intent_status = "error"
                if case.get("expected_needs_clarification") is not None:
                    clarification_status = "error"

            jev_intent_ms = (time.perf_counter() - t_start) * 1000.0

            # 4. Evidence workflow (xử lý cả khi docs rỗng nếu case có nhãn expected_sufficiency)
            evidence_status = "not_applicable"
            jev_suff_choice = None
            evidence_tokens = 0
            jev_ev_ms = 0.0

            if case.get("expected_sufficiency") is not None:
                docs = case.get("docs") if case.get("docs") is not None else []
                t_ev_start = time.perf_counter()
                try:
                    ev_res = await service.decide_evidence_sufficiency(
                        question=raw_q,
                        docs=docs,
                        remaining_budget_ms=max(0.0, settings.JEV_TOTAL_BUDGET_MS - jev_intent_ms),
                    )
                    if ev_res:
                        evidence_status = ev_res.status
                        if ev_res.usage:
                            evidence_tokens = ev_res.usage.input_tokens + ev_res.usage.output_tokens
                        if evidence_status == "success":
                            item = ev_res.decisions.get("sufficiency")
                            if item:
                                jev_suff_choice = item.choice
                except Exception:
                    evidence_status = "error"
                jev_ev_ms = (time.perf_counter() - t_ev_start) * 1000.0

            total_lat = jev_intent_ms + jev_ev_ms
            latencies.append(total_lat)

            # Tính overall status an toàn cho case
            active_statuses = [st for st in (intent_status, evidence_status) if st != "not_applicable"]
            if any(st == "error" for st in active_statuses):
                overall_status = "error"
            elif any(st == "fallback" for st in active_statuses):
                overall_status = "fallback"
            elif all(st == "success" for st in active_statuses):
                overall_status = "success"
            else:
                overall_status = "skipped"

            agreement = (baseline == jev_choice) if (jev_choice and intent_status == "success") else False

            # Record hoàn toàn ẩn danh, an toàn
            record = {
                "id": case_id,
                "group": group,
                "state_hash": state_hash,
                "baseline_intent": baseline,
                "predicted_intent": jev_choice,
                "expected_intent": case.get("expected_intent"),
                "confidence": round(confidence, 3) if confidence is not None else None,
                "agreement": agreement,
                "is_ambiguous": is_ambig,

                "intent_status": intent_status,
                "intent_latency_ms": round(jev_intent_ms, 2),
                "intent_tokens_used": intent_tokens,

                "clarification_status": clarification_status,
                "predicted_needs_clarification": predicted_clarify,
                "expected_needs_clarification": case.get("expected_needs_clarification"),
                "clarification_latency_ms": round(jev_intent_ms, 2),
                "clarification_tokens_used": clarification_tokens,

                "evidence_status": evidence_status,
                "predicted_sufficiency": jev_suff_choice,
                "expected_sufficiency": case.get("expected_sufficiency"),
                "evidence_latency_ms": round(jev_ev_ms, 2),
                "evidence_tokens_used": evidence_tokens,

                "requires_human_review": req_human,
                "latency_ms": round(total_lat, 2),
                "queue_wait_ms": round(queue_wait_ms, 2),
                "retry_count": retry_cnt,
                "fallback_reason": fallback_reason,
                "circuit_state": circuit_breaker.state,
                "status": overall_status,
                "overall_status": overall_status,
                "tokens_used": intent_tokens + evidence_tokens,
            }
            self.records.append(record)


        await client.aclose()

        # Tính toán bộ metrics độc lập
        coverage_stats = calculate_coverage_and_status(self.records)
        intent_metrics = calculate_intent_metrics(self.records, accepted_only=True)
        evidence_metrics = calculate_evidence_metrics(self.records, accepted_only=True)
        clarification_metrics = calculate_clarification_metrics(self.records, accepted_only=True)
        agreement_stats = calculate_baseline_agreement(self.records)
        latency_stats = calculate_latency_percentiles(latencies)

        return {
            "total_queries": len(self.records),
            "coverage_and_status": coverage_stats,
            "intent_metrics": intent_metrics,
            "evidence_metrics": evidence_metrics,
            "clarification_metrics": clarification_metrics,
            "baseline_agreement": agreement_stats,
            "latency_stats": latency_stats,
            "redaction_failures": redaction_failures,
            "records": self.records,
        }

    def verify_shadow_non_interference(self) -> Dict[str, Any]:
        """Kiểm tra chatbot trong Shadow Mode không bao giờ thay đổi câu trả lời hoặc làm vỡ NDJSON stream."""
        from backend.app.rag import pipeline

        old_mode = os.environ.get("JEV_MODE")
        os.environ["JEV_MODE"] = "shadow"

        mock_retrieval_docs = [
            {"title": "Học phí HUIT", "text": "Học phí chuẩn HUIT 2026 là 850.000đ/tín chỉ.", "score": 0.9}
        ]
        mock_llm_tokens = ["Học phí ", "chuẩn HUIT ", "2026 ", "từ 18 đến 22 triệu/năm."]

        orig_retrieve = pipeline.retrieve
        orig_stream_llm = pipeline.stream_llm
        orig_resolve_artifact = getattr(pipeline, "resolve_artifact_for_chat", None)
        orig_resolve_visual = getattr(pipeline, "resolve_visual_for_query", None)
        orig_service = pipeline.decision_service

        pipeline.retrieve = lambda q, top_k, timings=None: mock_retrieval_docs
        pipeline.stream_llm = lambda sys, user: list(mock_llm_tokens)
        if orig_resolve_artifact:
            pipeline.resolve_artifact_for_chat = lambda *args, **kwargs: None
        if orig_resolve_visual:
            pipeline.resolve_visual_for_query = lambda *args, **kwargs: None

        try:
            mock_provider = TypeSafeJevProvider(
                api_key="mock-staging-key-safe",
                client=httpx.AsyncClient(transport=StagingRealisticMockTransport()),
            )
            pipeline.decision_service = DecisionService(provider=mock_provider, mode="shadow")

            # 1. Chạy với Shadow Mode
            os.environ["JEV_MODE"] = "shadow"
            shadow_events = list(pipeline.stream_answer("Em muốn hỏi học phí", use_cache=False))
            shadow_parsed = [json.loads(line) for line in shadow_events if line.strip()]
            shadow_text = "".join(
                (e.get("payload") or e.get("data") or {}).get("token", "")
                for e in shadow_parsed
                if e["type"] == "token"
            )

            # 2. Chạy với Off Mode (Baseline tham chiếu)
            os.environ["JEV_MODE"] = "off"
            off_events = list(pipeline.stream_answer("Em muốn hỏi học phí", use_cache=False))
            off_parsed = [json.loads(line) for line in off_events if line.strip()]
            off_text = "".join(
                (e.get("payload") or e.get("data") or {}).get("token", "")
                for e in off_parsed
                if e["type"] == "token"
            )

            # 3. Kiểm thử lỗi Provider không làm vỡ stream
            os.environ["JEV_MODE"] = "shadow"
            fault_scenarios_passed = True

            class FailingProvider(TypeSafeJevProvider):
                async def decide(self, request, **kwargs):
                    raise DecisionServerError("Simulated 503 error", status_code=503)

            pipeline.decision_service = DecisionService(provider=FailingProvider(api_key="k"), mode="shadow")
            try:
                fault_events = list(pipeline.stream_answer("Hỏi khi JEV lỗi", use_cache=False))
                fault_parsed = [json.loads(line) for line in fault_events if line.strip()]
                types = [e["type"] for e in fault_parsed]
                if "start" not in types or "token" not in types or "done" not in types:
                    fault_scenarios_passed = False
            finally:
                pipeline.decision_service = orig_service

            output_identical = (shadow_text == off_text and len(shadow_text) > 0)
            stream_protocol_intact = (
                len(shadow_parsed) > 0
                and all(shadow_parsed[i]["sequence"] == i + 1 for i in range(len(shadow_parsed)))
            )

            return {
                "output_identical": output_identical,
                "stream_protocol_intact": stream_protocol_intact,
                "fault_tolerance_intact": fault_scenarios_passed,
                "overall_pass": bool(output_identical and stream_protocol_intact and fault_scenarios_passed),
            }
        finally:
            pipeline.retrieve = orig_retrieve
            pipeline.stream_llm = orig_stream_llm
            if orig_resolve_artifact:
                pipeline.resolve_artifact_for_chat = orig_resolve_artifact
            if orig_resolve_visual:
                pipeline.resolve_visual_for_query = orig_resolve_visual
            pipeline.decision_service = orig_service
            if old_mode is not None:
                os.environ["JEV_MODE"] = old_mode
            elif "JEV_MODE" in os.environ:
                del os.environ["JEV_MODE"]


async def main():
    parser = argparse.ArgumentParser(description="JEV Staging Shadow Benchmark & Quality Evaluation Suite")
    parser.add_argument("--mode", choices=["mock", "live"], default="mock", help="Chế độ chạy (mock hoặc live)")
    parser.add_argument("--output", default=None, help="Đường dẫn file báo cáo JSON (mặc định timestamped để không ghi đè lịch sử)")
    parser.add_argument("--run-chat-perf", action="store_true", help="Chạy benchmark đo hiệu năng chat (TTFT, total time, shadow overhead)")
    args = parser.parse_args()

    # Tạo đường dẫn output an toàn, mặc định có timestamp để không ghi đè báo cáo cũ
    timestamp_str = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    default_output = (
        f"audit_outputs/jev_evaluation_report_{timestamp_str}.json"
        if args.mode == "mock"
        else f"audit_outputs/jev_evaluation_live_report_{timestamp_str}.json"
    )
    output_target = args.output or default_output

    print(f"🚀 BẮT ĐẦU ĐÁNH GIÁ CHẤT LƯỢNG & ĐO LƯỜNG HIỆU NĂNG JEV AI (Mode: {args.mode.upper()})...")
    if args.mode == "mock":
        print("  ⚠️ LƯU Ý MÔI TRƯỜNG: Chế độ MOCK chỉ kiểm chứng công cụ đánh giá, runner và tính toàn vẹn của stream.")
        print("  Tuyệt đối KHÔNG sử dụng kết quả mock để chứng minh hay khẳng định năng lực thực tế của JEV AI.")

    runner = StagingShadowBenchmarkRunner(mode=args.mode)

    # 1. Kiểm tra cấu hình staging
    print("\n[BƯỚC 1] Kiểm tra cấu hình Staging & Xác nhận an toàn:")
    cfg = runner.verify_staging_config()
    print(f"  - Target Mode: {cfg['target_mode']}")
    print(f"  - Timeout: {cfg['timeout_seconds']}s | Budget: {cfg['total_budget_ms']}ms | Concurrency: {cfg['max_concurrency']}")
    print(f"  - Production default JEV_MODE=off: {'✅ PASS' if cfg['production_default_is_off'] else '❌ FAIL'}")
    print(f"  - Staging API Key configured: {'✅ CÓ (CONFIGURED)' if cfg['api_key_configured'] else '⚠️ CHƯA CÓ (MOCK ONLY)'}")

    if args.mode == "live" and not cfg["api_key_configured"]:
        print("\n⛔ DỪNG: Cần cung cấp TYPESAFE_API_KEY từ Secret Manager để chạy live mode!")
        sys.exit(1)

    # 2. Đánh giá trên bộ dữ liệu synthetic
    print(f"\n[BƯỚC 2] Thực thi đánh giá trên bộ dữ liệu {len(EVALUATION_DATASET)} tình huống tuyển sinh:")
    results = await runner.run_benchmark()
    cov = results["coverage_and_status"]
    intent_m = results["intent_metrics"]
    ev_m = results["evidence_metrics"]
    clar_m = results["clarification_metrics"]
    agree = results["baseline_agreement"]
    lat = results["latency_stats"]

    print(f"  - Tổng số tình huống: {cov['total_cases']}")
    print(f"  - Số case Ground Truth được chấp nhận: {cov['accepted_ground_truth_cases']} | Case cần duyệt: {cov['human_review_flagged_cases']}")
    print(f"  - Coverage: {cov['coverage_rate']}% | Thành công: {cov['success_rate']}% | Fallback: {cov['fallback_rate']}% | Error: {cov['error_rate']}%")
    print(f"\n  🎯 KẾT QUẢ ĐỘ CHÍNH XÁC THEO NHÃN GROUND TRUTH (Chỉ trên case được duyệt, không tính fallback):")
    print(f"    + Intent Accuracy: {intent_m['accuracy']}% | Macro-F1: {intent_m['macro_f1']}% ({intent_m['evaluated_count']} cases)")
    print(f"    + Evidence Sufficiency Accuracy: {ev_m['accuracy']}% | Macro-F1: {ev_m['macro_f1']}% ({ev_m['evaluated_count']} cases)")
    print(f"    + Needs Clarification F1: {clar_m['f1']}% | Accuracy: {clar_m['accuracy']}% ({clar_m['evaluated_count']} cases)")
    print(f"\n  📊 ĐỒNG THUẬN VỚI BASELINE (Rule/Regex cũ):")
    print(f"    + Agreement Rate: {agree['agreement_rate']}% ({agree['agreement_count']}/{agree['total_compared']})")
    print(f"    + Ghi chú: {agree['agreement_note']}")
    print(f"\n  ⏱️ ĐỘ TRỄ PHẢN HỒI (LATENCY):")
    print(f"    + P50: {lat['p50_ms']}ms | P95: {lat['p95_ms']}ms")
    print(f"    + P99: {lat['p99_ms'] if lat['p99_ms'] is not None else 'N/A'} ({lat['p99_note']})")
    print(f"    + Vi phạm Redaction: {results['redaction_failures']} (Bắt buộc = 0)")

    # 3. Kiểm chứng Non-Interference của Chatbot
    print("\n[BƯỚC 3] Kiểm chứng Chatbot trong Shadow Mode:")
    interference = runner.verify_shadow_non_interference()
    print(f"  - Output không đổi so với baseline: {'✅ PASS' if interference['output_identical'] else '❌ FAIL'}")
    print(f"  - Chuẩn NDJSON Stream v2 toàn vẹn: {'✅ PASS' if interference['stream_protocol_intact'] else '❌ FAIL'}")
    print(f"  - Khả năng chống chịu lỗi (Fault tolerance): {'✅ PASS' if interference['fault_tolerance_intact'] else '❌ FAIL'}")

    # 4. Đo lường hiệu năng chat (nếu được yêu cầu hoặc mặc định khi benchmark hoàn chỉnh)
    chat_perf_data = None
    if args.run_chat_perf:
        print("\n[BƯỚC 4] Đo lường chi tiết hiệu năng chat (TTFT, Total Time, Shadow Overhead):")
        chat_perf_data = measure_chat_performance()
        off_b = chat_perf_data["off_baseline"]
        print(f"  - Baseline OFF mode: TTFT P50={off_b['ttft_p50_ms']}ms, Total P50={off_b['total_p50_ms']}ms")
        for prof, pstats in chat_perf_data["shadow_profiles"].items():
            print(f"  - Shadow Profile [{prof}]:")
            print(f"      TTFT P50: {pstats['ttft_p50_ms']}ms (Overhead: +{pstats['overhead_ttft_p50_ms']}ms)")
            print(f"      Total P50: {pstats['total_p50_ms']}ms (Overhead: +{pstats['overhead_total_p50_ms']}ms)")
            print(f"      Output khớp 100%: {'✅' if pstats['output_identical'] else '❌'} | Giao thức: {'✅' if pstats['protocol_intact'] else '❌'}")

    # 5. Đánh giá Go / No-Go cho Shadow Mode
    is_go = (
        cov["success_rate"] >= 95.0
        and results["redaction_failures"] == 0
        and lat["p95_ms"] <= 600.0
        and interference["overall_pass"]
    )
    recommendation = "TIẾP TỤC SHADOW TRÊN STAGING; CHƯA BẬT ASSIST CHO PRODUCTION" if is_go else "GIỮ OFF"

    print("\n[BƯỚC 5] Đánh giá Quyết định Go / No-Go:")
    print(f"  - Đánh giá tổng thể: {'🟢 GO' if is_go else '🔴 NO-GO'}")
    print(f"  - Khuyến nghị: {recommendation}")

    # 6. Lưu báo cáo JSON (không chứa raw text hay secret)
    output_path = ROOT_DIR / output_target
    output_path.parent.mkdir(parents=True, exist_ok=True)

    report_payload = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "runner_mode": args.mode,
        "mode_disclaimer": (
            "Kết quả chế độ mock chỉ kiểm chứng tính đúng đắn của công cụ runner và logic tính metric, "
            "tuyệt đối không dùng để chứng minh năng lực thực tế của mô hình Jev."
            if args.mode == "mock"
            else "Báo cáo thử nghiệm live với TypeSafe Jev API."
        ),
        "staging_config": cfg,
        "rubric_summary": {
            "version": LABELING_RUBRIC["version"],
            "total_dataset_cases": len(EVALUATION_DATASET),
            "accepted_ground_truth_cases": cov["accepted_ground_truth_cases"],
            "human_review_flagged_cases": cov["human_review_flagged_cases"],
        },
        "coverage_and_status": cov,
        "ground_truth_metrics": {
            "intent_evaluation": intent_m,
            "evidence_sufficiency_evaluation": ev_m,
            "needs_clarification_evaluation": clar_m,
        },
        "baseline_agreement": agree,
        "latency_percentiles": lat,
        "shadow_non_interference": interference,
        "chat_performance": chat_perf_data,
        "go_no_go": {
            "decision": "GO" if is_go else "NO-GO",
            "recommendation": recommendation,
        },
        "anonymized_telemetry_records": [
            {
                "id": r["id"],
                "group": r["group"],
                "state_hash": r["state_hash"],
                "status": r["status"],
                "latency_ms": r["latency_ms"],
                "requires_human_review": r["requires_human_review"],
            }
            for r in results["records"]
        ],
    }

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(report_payload, f, ensure_ascii=False, indent=2)

    print(f"\n📄 Báo cáo đánh giá đã được lưu an toàn tại: {output_path}")


if __name__ == "__main__":
    asyncio.run(main())
