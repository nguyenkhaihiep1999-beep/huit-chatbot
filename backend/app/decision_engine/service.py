"""
service.py
Decision Engine Orchestrator Service.
Điều phối:
- Provider giao tiếp (TypeSafe Jev hoặc Mock/Alternative);
- Chế độ vận hành (off / shadow / assist);
- Circuit Breaker và Giới hạn đồng thời (Concurrency Limiter);
- Cơ chế Fallback an toàn, bảo đảm không bao giờ phá vỡ luồng RAG hoặc NDJSON stream;
- Metric và Telemetry đã khử dữ liệu nhạy cảm (Sanitized Metrics);
- Trạng thái sức khỏe (disabled / configured / healthy / degraded / circuit_open).
"""
import asyncio
import logging
import time
from typing import Any, Dict, List, Optional

from backend.app.config import settings
from backend.app.decision_engine.contracts import (
    DecisionItem,
    DecisionRequest,
    DecisionResult,
    DecisionUsage,
)
from backend.app.decision_engine.policies import (
    get_evidence_sufficiency_questions,
    get_intent_decision_questions,
)
from backend.app.decision_engine.providers.base import (
    BaseDecisionProvider,
    DecisionAuthenticationError,
    DecisionProviderError,
    DecisionQuotaExhaustedError,
    DecisionRateLimitError,
    DecisionServerError,
    DecisionTimeoutError,
    DecisionValidationError,
    observe_api_calls,
)
from backend.app.decision_engine.providers.typesafe_jev import TypeSafeJevProvider
from backend.app.decision_engine.redaction import (
    anonymize_request_hash,
    build_evidence_decision_state,
    build_intent_decision_state,
)

import concurrent.futures
import os
import threading

logger = logging.getLogger("decision_engine")

_SYNC_EXECUTOR: Optional[concurrent.futures.ThreadPoolExecutor] = None
_SYNC_EXECUTOR_LOCK = threading.Lock()


def _get_sync_executor() -> concurrent.futures.ThreadPoolExecutor:
    global _SYNC_EXECUTOR
    if _SYNC_EXECUTOR is None:
        with _SYNC_EXECUTOR_LOCK:
            if _SYNC_EXECUTOR is None:
                _SYNC_EXECUTOR = concurrent.futures.ThreadPoolExecutor(
                    max_workers=min(32, (os.cpu_count() or 4) * 2),
                    thread_name_prefix="jev_sync_runner",
                )
    return _SYNC_EXECUTOR


class CircuitBreaker:
    """Circuit Breaker bảo vệ hệ thống khỏi sự cố liên tiếp của nhà cung cấp bên ngoài.

    Đặc tính:
    - Thread-safe bảo vệ trạng thái với threading.Lock.
    - Trạng thái half_open chỉ cho phép DUY NHẤT một probe request tại một thời điểm.
      Các request khác đồng thời hoặc đến sau khi probe đang chạy đều fallback nhanh (allow_request() == False).
    - Sau khi probe thành công -> chuyển về closed.
    - Nếu probe thất bại -> chuyển về open với cooldown mới.
    """

    def __init__(self, failure_threshold: int = 3, cooldown_seconds: float = 30.0):
        self.failure_threshold = failure_threshold
        self.cooldown_seconds = cooldown_seconds
        self.consecutive_failures = 0
        self.state = "closed"  # "closed" | "open" | "half_open"
        self.last_state_change = time.monotonic()
        self._lock = threading.Lock()
        self._probe_in_flight = False

    def allow_request(self) -> bool:
        with self._lock:
            now = time.monotonic()
            if self.state == "closed":
                return True
            if self.state == "open":
                if (now - self.last_state_change) > self.cooldown_seconds:
                    self.state = "half_open"
                    self.last_state_change = now
                    self._probe_in_flight = True
                    return True
                return False
            if self.state == "half_open":
                # Chỉ cho phép đúng 1 probe request tại một thời điểm
                if not self._probe_in_flight:
                    self._probe_in_flight = True
                    return True
                return False
            return False

    def record_success(self) -> None:
        with self._lock:
            self.consecutive_failures = 0
            self.state = "closed"
            self._probe_in_flight = False
            self.last_state_change = time.monotonic()

    def record_failure(self) -> None:
        with self._lock:
            self.consecutive_failures += 1
            if self.state == "half_open":
                self.state = "open"
                self._probe_in_flight = False
                self.last_state_change = time.monotonic()
            elif self.consecutive_failures >= self.failure_threshold:
                if self.state != "open":
                    self.state = "open"
                    self._probe_in_flight = False
                    self.last_state_change = time.monotonic()

    def abandon_request(self) -> None:
        """Nhả reservation half-open khi request chưa tới provider hoặc bị hủy."""
        with self._lock:
            if self.state == "half_open":
                self._probe_in_flight = False


class DecisionTracker:
    """Điều phối và đảm bảo mỗi quyết định chỉ được hoàn tất (ghi nhận metric, cập nhật circuit breaker,
    cập nhật recent successes/errors) đúng 1 lần duy nhất:

    - Ngăn chặn ghi nhận trùng lặp giữa execute_decision, provider và sync wrapper;
    - Bảo vệ circuit breaker và metrics khỏi các tác vụ hoàn tất muộn sau khi đã timeout;
    - Phân biệt rõ giữa timeout thực sự và cancellation do client ngắt kết nối;
    - Toàn bộ việc cập nhật trạng thái kết thúc (success, timeout, error) được thực hiện
      nguyên tử dưới threading.Lock, không giải phóng lock giữa các bước, bảo đảm nhánh thua race
      tuyệt đối không làm thay đổi metric, circuit breaker hoặc bộ đếm recent successes/errors.
    """

    def __init__(
        self,
        request: DecisionRequest,
        service: "DecisionService",
        budget_ms: float,
        deadline: Optional[float] = None,
    ):
        self.request = request
        self.service = service
        self.budget_ms = budget_ms
        self.start_time = time.perf_counter()
        self.start_monotonic = time.monotonic()
        self.deadline = deadline if deadline is not None else (self.start_monotonic + (budget_ms / 1000.0))
        self._lock = threading.Lock()
        self.recorded = False
        self.aborted = False
        self.is_timeout = False
        self.is_cancelled = False
        self._fallback_res: Optional[DecisionResult] = None
        self.api_called = False

    def mark_api_called(self) -> None:
        """Record an actual HTTP attempt, or stop one after terminal timeout."""
        with self._lock:
            if self.aborted or self.recorded or time.monotonic() >= self.deadline:
                raise DecisionTimeoutError("Budget exhausted before HTTP attempt")
            self.api_called = True

    def sync_result(self, result: Optional[DecisionResult]) -> Optional[DecisionResult]:
        """Preserve timeout evidence when the sync bridge returns no result."""
        with self._lock:
            final_result = result if result is not None else self._fallback_res
            if final_result is not None:
                final_result._api_called = self.api_called
            return final_result

    def mark_aborted(self, is_timeout: bool = True) -> None:
        with self._lock:
            if self.is_cancelled and is_timeout:
                # Tuyệt đối không chuyển client cancellation thành timeout
                return
            if self.recorded and not self.is_timeout and is_timeout:
                # Nếu request đã hoàn tất thành công, không bị ghi đè thành timeout
                return
            self.aborted = True
            if is_timeout:
                self.is_timeout = True
                self.is_cancelled = False
            else:
                self.is_cancelled = True
                self.is_timeout = False

    def mark_cancelled(self) -> None:
        with self._lock:
            if self.recorded and not self.is_cancelled:
                # Nếu đã hoàn tất trước đó, giữ nguyên trạng thái kết quả
                return
            self.aborted = True
            self.is_cancelled = True
            self.is_timeout = False

    def record_success(
        self,
        result: DecisionResult,
        status_group: str = "2xx",
        latency_ms: Optional[float] = None,
        provider_latency_ms: float = 0.0,
        queue_wait_ms: float = 0.0,
        retry_count: int = 0,
        fallback_reason: Optional[str] = None,
    ) -> bool:
        """Ghi nhận thành công nguyên tử và cập nhật circuit breaker đúng 1 lần duy nhất."""
        with self._lock:
            if self.is_cancelled:
                return False
            if self.recorded or self.aborted or self.is_timeout:
                return False

            now_m = time.monotonic()
            if now_m >= self.deadline:
                # Response hoàn tất sau deadline: ghi timeout/fallback đúng 1 lần nếu chưa có kết quả cuối
                elapsed = (now_m - self.start_monotonic) * 1000.0
                self._record_timeout_locked(latency_ms=elapsed)
                return False

            self.recorded = True
            self._fallback_res = result
            result._api_called = self.api_called
            result._fallback_reason = fallback_reason

            self.service.circuit_breaker.record_success()
            self.service._recent_successes += 1

            calc_latency = (
                latency_ms
                if latency_ms is not None
                else (now_m - self.start_monotonic) * 1000.0
            )

            self.service._record_metric(
                self.request,
                result,
                status_group=status_group,
                latency_ms=calc_latency,
                provider_latency_ms=provider_latency_ms,
                queue_wait_ms=queue_wait_ms,
                retry_count=retry_count,
                fallback_reason=fallback_reason,
            )
            return True

    def record_failure_once(
        self,
        fallback_res: DecisionResult,
        status_group: str,
        latency_ms: float,
        provider_latency_ms: float = 0.0,
        queue_wait_ms: float = 0.0,
        retry_count: int = 0,
        fallback_reason: Optional[str] = None,
    ) -> bool:
        """Ghi nhận thất bại / lỗi provider nguyên tử và cập nhật circuit breaker đúng 1 lần."""
        with self._lock:
            if self.is_cancelled:
                return False
            if self.recorded:
                return False

            self.recorded = True
            self._fallback_res = fallback_res
            fallback_res._api_called = self.api_called
            fallback_res._fallback_reason = fallback_reason
            if fallback_reason == "timeout":
                self.aborted = True
                self.is_timeout = True

            if fallback_reason not in ("circuit_open", "concurrency_limit_exceeded"):
                self.service.circuit_breaker.record_failure()
                self.service._recent_errors += 1

            self.service._record_metric(
                self.request,
                fallback_res,
                status_group=status_group,
                latency_ms=latency_ms,
                provider_latency_ms=provider_latency_ms,
                queue_wait_ms=queue_wait_ms,
                retry_count=retry_count,
                fallback_reason=fallback_reason,
            )
            return True

    def record_once(
        self,
        result: DecisionResult,
        status_group: str,
        latency_ms: float,
        provider_latency_ms: float = 0.0,
        queue_wait_ms: float = 0.0,
        retry_count: int = 0,
        fallback_reason: Optional[str] = None,
    ) -> bool:
        """Ghi nhận metric đúng một lần cho các trường hợp đặc biệt (circuit open, concurrency limit, v.v.)."""
        with self._lock:
            if self.is_cancelled:
                return False
            if self.recorded:
                return False
            if self.aborted and result.status == "success":
                logger.warning("Bỏ qua metric thành công muộn từ provider sau khi quyết định đã bị hủy/timeout")
                return False
            now_m = time.monotonic()
            if result.status == "success" and now_m >= self.deadline:
                logger.warning("Bỏ qua metric thành công muộn vì đã vượt deadline, chuyển sang timeout")
                self._record_timeout_locked(latency_ms=latency_ms)
                return False

            self.recorded = True
            self._fallback_res = result
            result._api_called = self.api_called
            result._fallback_reason = fallback_reason

            if result.status == "success":
                self.service.circuit_breaker.record_success()
                self.service._recent_successes += 1
            elif fallback_reason not in ("circuit_open", "concurrency_limit_exceeded"):
                self.service.circuit_breaker.record_failure()
                self.service._recent_errors += 1

            self.service._record_metric(
                self.request,
                result,
                status_group=status_group,
                latency_ms=latency_ms,
                provider_latency_ms=provider_latency_ms,
                queue_wait_ms=queue_wait_ms,
                retry_count=retry_count,
                fallback_reason=fallback_reason,
            )
            return True

    def _record_timeout_locked(self, latency_ms: Optional[float] = None) -> DecisionResult:
        """Hàm nội bộ ghi nhận timeout dưới lock - KHÔNG giải phóng lock giữa các bước."""
        if self.is_cancelled:
            if self._fallback_res is not None:
                return self._fallback_res
            elapsed = latency_ms if latency_ms is not None else (time.monotonic() - self.start_monotonic) * 1000.0
            fallback = DecisionResult(
                decision_type=self.request.decision_type,
                status="fallback",
                provider=self.service._provider.get_name(),
                model=self.request.model,
                decisions={},
                usage=DecisionUsage(),
                latency_ms=round(elapsed, 2),
                error_message="CancelledError: cancelled by client",
            )
            self._fallback_res = fallback
            return fallback

        if self.recorded:
            if self._fallback_res is not None:
                return self._fallback_res
            elapsed = latency_ms if latency_ms is not None else (time.monotonic() - self.start_monotonic) * 1000.0
            fallback = DecisionResult(
                decision_type=self.request.decision_type,
                status="fallback",
                provider=self.service._provider.get_name(),
                model=self.request.model,
                decisions={},
                usage=DecisionUsage(),
                latency_ms=round(elapsed, 2),
                error_message="DecisionTimeoutError: timeout",
            )
            self._fallback_res = fallback
            return fallback

        self.aborted = True
        self.is_timeout = True
        self.recorded = True

        elapsed_ms = (
            latency_ms
            if latency_ms is not None
            else (time.monotonic() - self.start_monotonic) * 1000.0
        )
        self.service.circuit_breaker.record_failure()
        self.service._recent_errors += 1

        fallback_res = DecisionResult(
            decision_type=self.request.decision_type,
            status="fallback",
            provider=self.service._provider.get_name(),
            model=self.request.model,
            decisions={},
            usage=DecisionUsage(),
            latency_ms=round(elapsed_ms, 2),
            error_message="DecisionTimeoutError: timeout",
        )
        self._fallback_res = fallback_res
        fallback_res._api_called = self.api_called
        fallback_res._fallback_reason = "timeout"

        self.service._record_metric(
            self.request,
            fallback_res,
            status_group="5xx",
            latency_ms=elapsed_ms,
            provider_latency_ms=elapsed_ms if self.api_called else 0.0,
            queue_wait_ms=0.0,
            retry_count=0,
            fallback_reason="timeout",
        )
        return fallback_res

    def record_timeout_if_not_recorded(self, latency_ms: Optional[float] = None) -> DecisionResult:
        with self._lock:
            return self._record_timeout_locked(latency_ms=latency_ms)


class DecisionService:
    """Dịch vụ điều phối ra quyết định độc lập của Backend."""

    def __init__(
        self,
        provider: Optional[BaseDecisionProvider] = None,
        circuit_breaker: Optional[CircuitBreaker] = None,
        max_concurrency: Optional[int] = None,
        mode: Optional[str] = None,
        executor: Optional[concurrent.futures.ThreadPoolExecutor] = None,
    ):
        self._provider = provider or TypeSafeJevProvider()
        self.circuit_breaker = circuit_breaker or CircuitBreaker()
        self._max_concurrency = max_concurrency or settings.JEV_MAX_CONCURRENCY
        self._mode = mode
        self._executor = executor
        # Dùng threading.Semaphore để bảo đảm an toàn trên nhiều event loop và sync worker thread
        self._concurrency_limiter = threading.Semaphore(self._max_concurrency)
        self._recent_successes = 0
        self._recent_errors = 0
        self._stats_lock = threading.Lock()
        self._metrics_stats: Dict[str, Any] = {
            "total_requests": 0,
            "success_count": 0,
            "fallback_count": 0,
            "error_count": 0,
            "timeout_count": 0,
            "rate_limit_count": 0,
            "quota_exhausted_count": 0,
            "auth_error_count": 0,
            "circuit_open_count": 0,
            "concurrency_limit_count": 0,
            "total_latency_ms": 0.0,
            "total_input_tokens": 0,
            "total_output_tokens": 0,
            "intent_comparisons": 0,
            "intent_divergences": 0,
            "intent_agreements": 0,
            "evidence_comparisons": 0,
            "evidence_divergences": 0,
            "evidence_agreements": 0,
        }

    def get_metrics_summary(self) -> Dict[str, Any]:
        """Tổng hợp số liệu thống kê (không nhạy cảm) về hiệu năng và chất lượng quyết định."""
        with self._stats_lock:
            s = dict(self._metrics_stats)
        total_req = s["total_requests"]
        avg_lat = round(s["total_latency_ms"] / total_req, 2) if total_req > 0 else 0.0
        intent_div_rate = (
            round(s["intent_divergences"] / s["intent_comparisons"], 4)
            if s["intent_comparisons"] > 0
            else 0.0
        )
        evidence_div_rate = (
            round(s["evidence_divergences"] / s["evidence_comparisons"], 4)
            if s["evidence_comparisons"] > 0
            else 0.0
        )
        return {
            "mode": self.mode,
            "total_requests": total_req,
            "success_count": s["success_count"],
            "fallback_count": s["fallback_count"],
            "error_count": s["error_count"],
            "timeout_count": s["timeout_count"],
            "rate_limit_count": s["rate_limit_count"],
            "quota_exhausted_count": s["quota_exhausted_count"],
            "circuit_open_count": s["circuit_open_count"],
            "concurrency_limit_count": s["concurrency_limit_count"],
            "avg_latency_ms": avg_lat,
            "total_latency_ms": round(s["total_latency_ms"], 2),
            "tokens": {
                "input_tokens": s["total_input_tokens"],
                "output_tokens": s["total_output_tokens"],
                "total_tokens": s["total_input_tokens"] + s["total_output_tokens"],
            },
            "divergence": {
                "intent": {
                    "comparisons": s["intent_comparisons"],
                    "divergences": s["intent_divergences"],
                    "agreements": s["intent_agreements"],
                    "divergence_rate": intent_div_rate,
                },
                "evidence": {
                    "comparisons": s["evidence_comparisons"],
                    "divergences": s["evidence_divergences"],
                    "agreements": s["evidence_agreements"],
                    "divergence_rate": evidence_div_rate,
                },
            },
        }

    def reset_metrics(self) -> None:
        """Đặt lại bộ đếm thống kê phục vụ kiểm thử cô lập."""
        with self._stats_lock:
            for k in self._metrics_stats:
                if isinstance(self._metrics_stats[k], float):
                    self._metrics_stats[k] = 0.0
                else:
                    self._metrics_stats[k] = 0
            self._recent_successes = 0
            self._recent_errors = 0

    @property
    def mode(self) -> str:
        return self._mode or settings.JEV_MODE

    def get_health_status(self) -> Dict[str, Any]:
        """Báo cáo trạng thái theo chuẩn: disabled | configured | healthy | degraded | circuit_open.

        Không thực hiện paid API request nào và không làm lộ secret.
        """
        if self.mode == "off":
            return {
                "status": "disabled",
                "mode": "off",
                "provider": self._provider.get_name(),
                "circuit_state": self.circuit_breaker.state,
            }

        if self.circuit_breaker.state == "open":
            return {
                "status": "circuit_open",
                "mode": self.mode,
                "provider": self._provider.get_name(),
                "circuit_state": "open",
                "failures": self.circuit_breaker.consecutive_failures,
            }

        if not settings.TYPESAFE_API_KEY:
            return {
                "status": "degraded",
                "mode": self.mode,
                "provider": self._provider.get_name(),
                "error": "MISSING_TYPESAFE_API_KEY",
            }

        if self._recent_errors > 0 and self.circuit_breaker.consecutive_failures > 0:
            return {
                "status": "degraded",
                "mode": self.mode,
                "provider": self._provider.get_name(),
                "circuit_state": self.circuit_breaker.state,
                "failures": self.circuit_breaker.consecutive_failures,
            }

        if self._recent_successes > 0:
            return {
                "status": "healthy",
                "mode": self.mode,
                "provider": self._provider.get_name(),
                "circuit_state": self.circuit_breaker.state,
            }

        return {
            "status": "configured",
            "mode": self.mode,
            "provider": self._provider.get_name(),
            "circuit_state": self.circuit_breaker.state,
        }

    def _record_metric(
        self,
        request: DecisionRequest,
        result: DecisionResult,
        status_group: str,
        latency_ms: float,
        provider_latency_ms: float = 0.0,
        queue_wait_ms: float = 0.0,
        retry_count: int = 0,
        fallback_reason: Optional[str] = None,
    ) -> None:
        """Ghi metric ẩn danh, tuyệt đối không chứa API key, raw question hay raw user state."""
        selected_choice = None
        confidence: Optional[float] = None
        for item in result.decisions.values():
            if item.choice:
                selected_choice = item.choice
                confidence = item.confidence
                break
            if confidence is None and item.confidence is not None:
                confidence = item.confidence

        anon_hash = anonymize_request_hash(request.state)
        input_tokens = result.usage.input_tokens if result.usage else 0
        output_tokens = result.usage.output_tokens if result.usage else 0

        baseline_decision = (
            request.context_metadata.get("baseline_decision")
            if request.context_metadata
            else None
        )
        diverged_from_baseline: Optional[bool] = None
        agreement: Optional[bool] = None
        if baseline_decision is not None and result.status == "success" and selected_choice is not None:
            diverged_from_baseline = (selected_choice != baseline_decision)
            agreement = (selected_choice == baseline_decision)

        metric_payload = {
            "event": "decision_engine_telemetry",
            "mode": self.mode,
            "provider": result.provider,
            "model": result.model,
            "decision_type": request.decision_type,
            "status": result.status,
            "api_called": result._api_called,
            "status_group": status_group,
            "latency_ms": round(latency_ms, 2),
            "provider_latency_ms": round(provider_latency_ms, 2),
            "queue_wait_ms": round(queue_wait_ms, 2),
            "retry_count": retry_count,
            "fallback_reason": fallback_reason,
            "circuit_state": self.circuit_breaker.state,
            "selected_choice": selected_choice,
            "confidence": round(confidence, 3) if confidence is not None else None,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "state_hash": anon_hash,
        }
        if baseline_decision is not None:
            metric_payload["baseline_decision"] = baseline_decision
            metric_payload["diverged_from_baseline"] = diverged_from_baseline
            metric_payload["agreement"] = agreement

        if request.decision_type == "intent":
            metric_payload["jev_intent_ms"] = round(latency_ms, 2)
        elif request.decision_type == "evidence_sufficiency":
            metric_payload["jev_evidence_ms"] = round(latency_ms, 2)

        # Cập nhật số liệu tích lũy an toàn trong bộ nhớ
        with self._stats_lock:
            self._metrics_stats["total_requests"] += 1
            if result.status == "success":
                self._metrics_stats["success_count"] += 1
            else:
                self._metrics_stats["fallback_count"] += 1

            if fallback_reason == "timeout":
                self._metrics_stats["timeout_count"] += 1
            elif fallback_reason == "rate_limit":
                self._metrics_stats["rate_limit_count"] += 1
            elif fallback_reason == "quota_exhausted":
                self._metrics_stats["quota_exhausted_count"] += 1
            elif fallback_reason == "auth_error":
                self._metrics_stats["auth_error_count"] += 1
            elif fallback_reason == "circuit_open":
                self._metrics_stats["circuit_open_count"] += 1
            elif fallback_reason == "concurrency_limit_exceeded":
                self._metrics_stats["concurrency_limit_count"] += 1
            elif fallback_reason is not None:
                self._metrics_stats["error_count"] += 1

            self._metrics_stats["total_latency_ms"] += max(0.0, latency_ms)
            self._metrics_stats["total_input_tokens"] += input_tokens
            self._metrics_stats["total_output_tokens"] += output_tokens

            if request.decision_type == "intent" and baseline_decision is not None and result.status == "success" and selected_choice is not None:
                self._metrics_stats["intent_comparisons"] += 1
                if diverged_from_baseline:
                    self._metrics_stats["intent_divergences"] += 1
                else:
                    self._metrics_stats["intent_agreements"] += 1
            elif request.decision_type == "evidence_sufficiency" and baseline_decision is not None and result.status == "success" and selected_choice is not None:
                self._metrics_stats["evidence_comparisons"] += 1
                if diverged_from_baseline:
                    self._metrics_stats["evidence_divergences"] += 1
                else:
                    self._metrics_stats["evidence_agreements"] += 1

        # In structured JSON log không nhạy cảm
        logger.info("[DECISION_METRIC] %s", metric_payload)

    async def execute_decision(
        self,
        request: DecisionRequest,
        total_budget_ms: Optional[float] = None,
        budget_ms: Optional[float] = None,
        tracker: Optional[DecisionTracker] = None,
        deadline: Optional[float] = None,
    ) -> DecisionResult:
        """Thực thi quyết định với đầy đủ bảo vệ:

        - Kiểm tra JEV_MODE (off / shadow / assist);
        - Concurrency Limiter (luồng an toàn);
        - Circuit Breaker (1 probe duy nhất trong half_open);
        - Giới hạn tổng latency budget tuyệt đối theo monotonic clock;
        - Fallback an toàn khi lỗi hoặc timeout;
        - Metric đã khử nhạy cảm (jev_intent_ms, jev_evidence_ms, retry_count, fallback_reason, v.v.).
        """
        # 1. Mode OFF: Bỏ qua hoàn toàn, 0 HTTP calls
        if self.mode == "off":
            return DecisionResult(
                decision_type=request.decision_type,
                status="skipped",
                provider=self._provider.get_name(),
                model=request.model,
                decisions={},
                usage=DecisionUsage(),
                latency_ms=0.0,
                error_message="JEV_MODE is off",
            )

        eff_budget_ms = budget_ms if budget_ms is not None else (
            total_budget_ms if total_budget_ms is not None else settings.JEV_TOTAL_BUDGET_MS
        )
        budget_ms = eff_budget_ms
        start_monotonic = time.monotonic()
        if deadline is None:
            deadline = start_monotonic + (budget_ms / 1000.0)

        if tracker is None:
            tracker = DecisionTracker(request=request, service=self, budget_ms=budget_ms, deadline=deadline)
        else:
            if not getattr(tracker, "deadline", None):
                tracker.deadline = deadline
            if not getattr(tracker, "start_monotonic", None):
                tracker.start_monotonic = start_monotonic

        # Kiểm tra trước khi thực thi: nếu đã bị hủy hoặc hết hạn deadline
        if tracker.aborted:
            self.circuit_breaker.abandon_request()
            if tracker.is_cancelled:
                raise asyncio.CancelledError()
            return tracker._fallback_res or tracker.record_timeout_if_not_recorded(
                latency_ms=(time.monotonic() - tracker.start_monotonic) * 1000.0
            )

        if time.monotonic() >= deadline:
            self.circuit_breaker.abandon_request()
            return tracker.record_timeout_if_not_recorded(
                latency_ms=(time.monotonic() - tracker.start_monotonic) * 1000.0
            )

        # 2. Circuit Breaker check
        if not self.circuit_breaker.allow_request():
            fallback_res = DecisionResult(
                decision_type=request.decision_type,
                status="fallback",
                provider=self._provider.get_name(),
                model=request.model,
                decisions={},
                usage=DecisionUsage(),
                latency_ms=0.0,
                error_message="Circuit breaker is open; fallen back safely.",
            )
            tracker.record_once(
                fallback_res,
                status_group="circuit_open",
                latency_ms=0.0,
                fallback_reason="circuit_open",
            )
            return fallback_res

        # 3. Concurrency limiter check
        q_start = time.monotonic()
        remaining_before_q = deadline - q_start
        if remaining_before_q <= 0.0:
            self.circuit_breaker.abandon_request()
            return tracker.record_timeout_if_not_recorded(
                latency_ms=(time.monotonic() - tracker.start_monotonic) * 1000.0
            )

        wait_timeout = min(0.05, max(0.005, (budget_ms / 1000.0) * 0.1), remaining_before_q)
        acquired = self._concurrency_limiter.acquire(blocking=True, timeout=wait_timeout)
        now_after_q = time.monotonic()
        queue_wait_ms = (now_after_q - q_start) * 1000.0

        if not acquired:
            self.circuit_breaker.abandon_request()
            if now_after_q >= deadline:
                # Đã hết hạn deadline trong lúc chờ concurrency queue
                return tracker.record_timeout_if_not_recorded(
                    latency_ms=(now_after_q - tracker.start_monotonic) * 1000.0
                )
            fallback_res = DecisionResult(
                decision_type=request.decision_type,
                status="fallback",
                provider=self._provider.get_name(),
                model=request.model,
                decisions={},
                usage=DecisionUsage(),
                latency_ms=round(queue_wait_ms, 2),
                error_message="Concurrency limit exceeded; fallen back safely.",
            )
            tracker.record_once(
                fallback_res,
                status_group="concurrency_limit",
                latency_ms=queue_wait_ms,
                queue_wait_ms=queue_wait_ms,
                fallback_reason="concurrency_limit_exceeded",
            )
            return fallback_res

        start_time = time.perf_counter()
        try:
            # KIỂM TRA NGAY TRƯỚC KHI GỌI PROVIDER:
            now_m = time.monotonic()
            remaining_s = deadline - now_m
            remaining_budget_ms = remaining_s * 1000.0

            if tracker.aborted:
                self.circuit_breaker.abandon_request()
                if tracker.is_cancelled:
                    raise asyncio.CancelledError()
                return tracker._fallback_res or tracker.record_timeout_if_not_recorded(
                    latency_ms=(now_m - tracker.start_monotonic) * 1000.0
                )

            if remaining_budget_ms < 50.0:
                self.circuit_breaker.abandon_request()
                raise DecisionTimeoutError("Budget exhausted during concurrency queue wait")

            call_timeout_s = remaining_s
            try:
                with observe_api_calls(tracker.mark_api_called):
                    result = await asyncio.wait_for(
                        self._provider.decide(request, total_budget_ms=remaining_budget_ms),
                        timeout=call_timeout_s,
                    )
            except asyncio.TimeoutError as exc:
                raise DecisionTimeoutError("Total latency budget exceeded in decision engine") from exc

            now_after = time.monotonic()
            latency_ms = (now_after - tracker.start_monotonic) * 1000.0
            provider_lat = getattr(result, "_provider_latency_ms", (time.perf_counter() - start_time) * 1000.0)
            retry_cnt = getattr(result, "_retry_count", 0)

            # KIỂM TRA SAU KHI PROVIDER HOÀN TẤT:
            if tracker.is_cancelled:
                self.circuit_breaker.abandon_request()
                raise asyncio.CancelledError()

            final_res = result
            status_group = "2xx"
            fallback_reason = None

            # Trong assist mode: kiểm tra ngưỡng tin cậy
            if self.mode == "assist":
                for q_id, dec in result.decisions.items():
                    if dec.confidence is not None and dec.confidence < settings.JEV_CONFIDENCE_THRESHOLD:
                        # Hạ xuống fallback an toàn khi độ tin cậy thấp
                        final_res = DecisionResult(
                            decision_type=request.decision_type,
                            status="fallback",
                            provider=result.provider,
                            model=result.model,
                            decisions=result.decisions,
                            usage=result.usage,
                            latency_ms=round(latency_ms, 2),
                            error_message="Confidence below threshold; fallback advised.",
                        )
                        status_group = "low_confidence"
                        fallback_reason = "confidence_below_threshold"
                        break

            # Hoàn tất request nguyên tử:
            # - Kiểm tra deadline/abort và cập nhật circuit breaker + metric đúng 1 lần
            # - Nếu timeout thắng hoặc response muộn quá deadline: trả về fallback timeout và không tăng _recent_successes
            success = tracker.record_success(
                final_res,
                status_group=status_group,
                latency_ms=latency_ms,
                provider_latency_ms=provider_lat,
                queue_wait_ms=queue_wait_ms,
                retry_count=retry_cnt,
                fallback_reason=fallback_reason,
            )
            if not success:
                logger.warning("Bỏ qua kết quả quyết định thành công vì tác vụ đã bị đánh dấu timeout/hủy hoặc quá deadline")
                if tracker.is_cancelled:
                    self.circuit_breaker.abandon_request()
                    raise asyncio.CancelledError()
                return tracker._fallback_res or tracker.record_timeout_if_not_recorded(
                    latency_ms=latency_ms
                )

            return final_res

        except asyncio.CancelledError:
            now_m = time.monotonic()
            elapsed_ms = (now_m - tracker.start_monotonic) * 1000.0

            # Phân biệt rõ ràng giữa timeout thực sự và client cancellation:
            if tracker.is_cancelled:
                is_timeout = False
            elif tracker.is_timeout:
                is_timeout = True
            elif now_m < deadline:
                is_timeout = False
            else:
                is_timeout = True

            if is_timeout:
                logger.warning(
                    "execute_decision cancelled due to timeout (elapsed: %.1fms / budget: %.1fms)",
                    elapsed_ms,
                    budget_ms,
                )
                tracker.record_timeout_if_not_recorded(latency_ms=elapsed_ms)
                raise
            else:
                logger.info(
                    "execute_decision cancelled by client/shutdown (elapsed: %.1fms / budget: %.1fms)",
                    elapsed_ms,
                    budget_ms,
                )
                tracker.mark_cancelled()
                self.circuit_breaker.abandon_request()
                raise

        except Exception as exc:
            now_m = time.monotonic()
            latency_ms = (now_m - tracker.start_monotonic) * 1000.0

            if tracker.is_cancelled:
                self.circuit_breaker.abandon_request()
                raise asyncio.CancelledError()

            if tracker.recorded:
                return tracker._fallback_res or DecisionResult(
                    decision_type=request.decision_type,
                    status="fallback",
                    provider=self._provider.get_name(),
                    model=request.model,
                    decisions={},
                    usage=DecisionUsage(),
                    latency_ms=round(latency_ms, 2),
                    error_message=f"{type(exc).__name__}: already recorded",
                )

            status_code = getattr(exc, "status_code", 500)
            status_group = f"{status_code // 100}xx" if isinstance(status_code, int) else "error"
            fallback_reason = "provider_error"
            if isinstance(exc, DecisionTimeoutError):
                fallback_reason = "timeout"
            elif isinstance(exc, DecisionRateLimitError):
                fallback_reason = "rate_limit"
            elif isinstance(exc, DecisionQuotaExhaustedError):
                fallback_reason = "quota_exhausted"
            elif isinstance(exc, DecisionAuthenticationError):
                fallback_reason = "auth_error"
            elif isinstance(exc, DecisionValidationError):
                fallback_reason = "validation_error"
            elif isinstance(exc, DecisionServerError):
                fallback_reason = "server_error"

            # Không phản chiếu message từ provider/custom implementation vì có thể chứa
            # raw state hoặc secret. Chỉ trả về phân loại lỗi an toàn.
            error_msg = f"{type(exc).__name__}: {fallback_reason}"
            retry_count = int(getattr(exc, "retry_count", 0) or 0)

            fallback_res = DecisionResult(
                decision_type=request.decision_type,
                status="fallback",
                provider=self._provider.get_name(),
                model=request.model,
                decisions={},
                usage=DecisionUsage(),
                latency_ms=round(latency_ms, 2),
                error_message=error_msg,
            )
            tracker.record_failure_once(
                fallback_res,
                status_group=status_group,
                latency_ms=latency_ms,
                provider_latency_ms=latency_ms if tracker.api_called else 0.0,
                queue_wait_ms=queue_wait_ms,
                retry_count=retry_count,
                fallback_reason=fallback_reason,
            )
            return tracker._fallback_res or fallback_res

        finally:
            self._concurrency_limiter.release()

    async def decide_intent(
        self,
        question: str,
        current_intent: str,
        remaining_budget_ms: Optional[float] = None,
        tracker: Optional[DecisionTracker] = None,
    ) -> Optional[DecisionResult]:
        """Tác vụ A: Hỗ trợ quyết định Intent tuyển sinh HUIT.

        Chỉ gọi khi intent là 'general', mơ hồ hoặc có nhiều intent cạnh tranh.
        """
        if self.mode == "off":
            return None

        eff_budget_ms = (
            remaining_budget_ms
            if remaining_budget_ms is not None
            else settings.JEV_TOTAL_BUDGET_MS
        )
        state = build_intent_decision_state(
            question=question,
            current_intent=current_intent,
            max_bytes=settings.JEV_MAX_STATE_BYTES,
        )
        questions = get_intent_decision_questions()
        request = DecisionRequest(
            decision_type="intent",
            state=state,
            model=settings.JEV_MODEL,
            questions=questions,
            context_metadata={"baseline_decision": current_intent},
        )
        start_mono = time.monotonic()
        dl = start_mono + (eff_budget_ms / 1000.0)
        if tracker is None:
            tracker = DecisionTracker(request=request, service=self, budget_ms=eff_budget_ms, deadline=dl)
        else:
            if not getattr(tracker, "deadline", None):
                tracker.deadline = dl
            if not getattr(tracker, "start_monotonic", None):
                tracker.start_monotonic = start_mono

        return await self.execute_decision(
            request,
            total_budget_ms=eff_budget_ms,
            budget_ms=eff_budget_ms,
            tracker=tracker,
            deadline=dl,
        )

    async def decide_evidence_sufficiency(
        self,
        question: str,
        docs: List[Dict[str, Any]],
        remaining_budget_ms: Optional[float] = None,
        tracker: Optional[DecisionTracker] = None,
    ) -> Optional[DecisionResult]:
        """Tác vụ B: Hỗ trợ đánh giá tính đầy đủ của tài liệu minh chứng (Evidence Sufficiency)."""
        if self.mode == "off":
            return None

        eff_budget_ms = (
            remaining_budget_ms
            if remaining_budget_ms is not None
            else settings.JEV_TOTAL_BUDGET_MS
        )
        state = build_evidence_decision_state(
            question=question,
            docs=docs,
            max_bytes=settings.JEV_MAX_STATE_BYTES,
        )
        questions = get_evidence_sufficiency_questions()
        request = DecisionRequest(
            decision_type="evidence_sufficiency",
            state=state,
            model=settings.JEV_MODEL,
            questions=questions,
            context_metadata={"baseline_decision": "sufficient"},
        )
        start_mono = time.monotonic()
        dl = start_mono + (eff_budget_ms / 1000.0)
        if tracker is None:
            tracker = DecisionTracker(request=request, service=self, budget_ms=eff_budget_ms, deadline=dl)
        else:
            if not getattr(tracker, "deadline", None):
                tracker.deadline = dl
            if not getattr(tracker, "start_monotonic", None):
                tracker.start_monotonic = start_mono

        return await self.execute_decision(
            request,
            total_budget_ms=eff_budget_ms,
            budget_ms=eff_budget_ms,
            tracker=tracker,
            deadline=dl,
        )

    def decide_intent_sync(
        self,
        question: str,
        current_intent: str,
        remaining_budget_ms: Optional[float] = None,
    ) -> Optional[DecisionResult]:
        """Phiên bản đồng bộ của decide_intent phục vụ stream generator trong executor."""
        if self.mode == "off":
            return None
        eff_budget_ms = (
            remaining_budget_ms
            if remaining_budget_ms is not None
            else settings.JEV_TOTAL_BUDGET_MS
        )
        state = build_intent_decision_state(
            question=question,
            current_intent=current_intent,
            max_bytes=settings.JEV_MAX_STATE_BYTES,
        )
        questions = get_intent_decision_questions()
        request = DecisionRequest(
            decision_type="intent",
            state=state,
            model=settings.JEV_MODEL,
            questions=questions,
            context_metadata={"baseline_decision": current_intent},
        )
        start_mono = time.monotonic()
        timeout_s = eff_budget_ms / 1000.0
        dl = start_mono + timeout_s
        tracker = DecisionTracker(request=request, service=self, budget_ms=eff_budget_ms, deadline=dl)
        coro = self.execute_decision(
            request,
            total_budget_ms=eff_budget_ms,
            budget_ms=eff_budget_ms,
            tracker=tracker,
            deadline=dl,
        )
        return tracker.sync_result(run_coro_sync(
            coro, timeout_seconds=timeout_s, tracker=tracker, executor=self._executor, deadline=dl
        ))

    def decide_evidence_sufficiency_sync(
        self,
        question: str,
        docs: List[Dict[str, Any]],
        remaining_budget_ms: Optional[float] = None,
    ) -> Optional[DecisionResult]:
        """Phiên bản đồng bộ của decide_evidence_sufficiency phục vụ stream generator trong executor."""
        if self.mode == "off":
            return None
        eff_budget_ms = (
            remaining_budget_ms
            if remaining_budget_ms is not None
            else settings.JEV_TOTAL_BUDGET_MS
        )
        state = build_evidence_decision_state(
            question=question,
            docs=docs,
            max_bytes=settings.JEV_MAX_STATE_BYTES,
        )
        questions = get_evidence_sufficiency_questions()
        request = DecisionRequest(
            decision_type="evidence_sufficiency",
            state=state,
            model=settings.JEV_MODEL,
            questions=questions,
            context_metadata={"baseline_decision": "sufficient"},
        )
        start_mono = time.monotonic()
        timeout_s = eff_budget_ms / 1000.0
        dl = start_mono + timeout_s
        tracker = DecisionTracker(request=request, service=self, budget_ms=eff_budget_ms, deadline=dl)
        coro = self.execute_decision(
            request,
            total_budget_ms=eff_budget_ms,
            budget_ms=eff_budget_ms,
            tracker=tracker,
            deadline=dl,
        )
        return tracker.sync_result(run_coro_sync(
            coro, timeout_seconds=timeout_s, tracker=tracker, executor=self._executor, deadline=dl
        ))


PRIMARY_INTENTS = (
    "admission_procedure",
    "scholarship",
    "cutoff",
    "floor_score",
    "tuition",
    "admission",
    "contact",
    "career",
)


def run_coro_sync(
    coro,
    timeout_seconds: Optional[float] = None,
    tracker: Optional[DecisionTracker] = None,
    executor: Optional[concurrent.futures.ThreadPoolExecutor] = None,
    deadline: Optional[float] = None,
):
    """Chạy an toàn một coroutine trong môi trường đồng bộ (sync generator/worker thread).

    - Tái sử dụng ThreadPoolExecutor dùng chung hoặc executor chỉ định, không tạo thread pool mới cho mỗi request.
    - Giới hạn thời gian chờ tối đa bằng deadline tuyệt đối monotonic để không bao giờ làm treo NDJSON streaming.
    - Ghi nhận timeout đúng một lần duy nhất vào DecisionTracker (nếu có).
    - Phân biệt rõ giữa timeout thực sự và cancellation do client ngắt kết nối.
    - Hủy tác vụ đang nằm trong hàng đợi khi caller hết hạn; đóng coroutine chưa await an toàn.
    """
    timeout = (
        timeout_seconds
        if timeout_seconds is not None
        else settings.JEV_TOTAL_BUDGET_MS / 1000.0
    )
    now_m = time.monotonic()
    if deadline is None:
        deadline = now_m + timeout
    if tracker:
        if not getattr(tracker, "deadline", None):
            tracker.deadline = deadline
        if not getattr(tracker, "start_monotonic", None):
            tracker.start_monotonic = now_m

    if timeout <= 0 or now_m >= deadline:
        try:
            coro.close()
        except Exception:
            pass
        if tracker:
            tracker.mark_aborted(is_timeout=True)
            tracker.record_timeout_if_not_recorded(latency_ms=0.0)
        return None

    try:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        pool = executor
        if pool is None and (loop and loop.is_running()):
            pool = _get_sync_executor()

        if pool is not None:
            def _run_with_deadline(c, dl, trk):
                start_w = time.monotonic()
                # Kiểm tra ngay khi worker bắt đầu: tác vụ đã hết hạn hoặc bị hủy khi chờ trong queue?
                if (trk and trk.aborted) or start_w >= dl:
                    logger.warning("Bỏ qua tác vụ Jev trong executor do đã hết hạn deadline hoặc bị hủy khi nằm trong hàng đợi")
                    try:
                        c.close()
                    except Exception:
                        pass
                    if trk and not trk.is_cancelled:
                        trk.mark_aborted(is_timeout=True)
                        trk.record_timeout_if_not_recorded(latency_ms=(start_w - trk.start_monotonic) * 1000.0)
                    return None

                rem_s = dl - start_w
                if rem_s <= 0.05:
                    logger.warning("Bỏ qua tác vụ Jev trong executor do thời gian còn lại (%.3fs) không đủ gọi API", rem_s)
                    try:
                        c.close()
                    except Exception:
                        pass
                    if trk:
                        trk.mark_aborted(is_timeout=True)
                        trk.record_timeout_if_not_recorded(latency_ms=(start_w - trk.start_monotonic) * 1000.0)
                    return None

                try:
                    return asyncio.run(asyncio.wait_for(c, timeout=rem_s + 0.02))
                except (asyncio.TimeoutError, concurrent.futures.TimeoutError):
                    logger.warning("run_coro_sync worker timed out after %.3fs", rem_s)
                    if trk:
                        trk.mark_aborted(is_timeout=True)
                        trk.record_timeout_if_not_recorded(latency_ms=(time.monotonic() - trk.start_monotonic) * 1000.0)
                    return None
                except asyncio.CancelledError:
                    if trk:
                        trk.mark_cancelled()
                    raise
                except Exception as exc:
                    logger.warning("run_coro_sync worker error: %s", type(exc).__name__)
                    return None

            future = pool.submit(_run_with_deadline, coro, deadline, tracker)
            try:
                rem_wait = max(0.0, deadline - time.monotonic())
                return future.result(timeout=rem_wait + 0.02)
            except (concurrent.futures.TimeoutError, asyncio.TimeoutError):
                logger.warning("run_coro_sync timed out after %.3fs", timeout)
                if tracker:
                    tracker.mark_aborted(is_timeout=True)
                    tracker.record_timeout_if_not_recorded(latency_ms=timeout * 1000.0)

                # Caller đã timeout, cố gắng hủy tác vụ trong hàng đợi executor
                cancelled = future.cancel()
                if cancelled:
                    # Task đã được hủy khỏi queue của executor; worker sẽ không bao giờ gọi _run_with_deadline.
                    # Phải đóng coro ở đây để tránh RuntimeWarning: coroutine was never awaited.
                    try:
                        coro.close()
                    except Exception:
                        pass
                return None
            except asyncio.CancelledError:
                future.cancel()
                try:
                    coro.close()
                except Exception:
                    pass
                if tracker:
                    tracker.mark_cancelled()
                raise
            except Exception as exc:
                logger.warning("run_coro_sync error: %s", type(exc).__name__)
                return None

        # Không dùng executor -> chạy trực tiếp trên thread hiện tại với deadline tuyệt đối
        rem_s = max(0.0, deadline - time.monotonic())
        if rem_s <= 0.05:
            try:
                coro.close()
            except Exception:
                pass
            if tracker:
                tracker.mark_aborted(is_timeout=True)
                tracker.record_timeout_if_not_recorded(latency_ms=timeout * 1000.0)
            return None

        return asyncio.run(asyncio.wait_for(coro, timeout=rem_s + 0.02))
    except (concurrent.futures.TimeoutError, asyncio.TimeoutError):
        logger.warning("run_coro_sync timed out after %.3fs", timeout)
        if tracker:
            tracker.mark_aborted(is_timeout=True)
            tracker.record_timeout_if_not_recorded(latency_ms=timeout * 1000.0)
        return None
    except asyncio.CancelledError:
        try:
            coro.close()
        except Exception:
            pass
        if tracker:
            tracker.mark_cancelled()
        raise
    except Exception as exc:
        logger.warning("run_coro_sync error: %s", type(exc).__name__)
        return None


def is_intent_ambiguous(question: str, current_intent: str) -> bool:
    """Kiểm tra xem câu hỏi có ý định mơ hồ, cạnh tranh hoặc là 'general' hay không.

    Nếu intent đã rõ ràng (ví dụ rule match chính xác 1 danh mục), trả về False để không gọi Jev.
    """
    if current_intent == "general":
        return True

    from backend.app.rag.intent import normalize_text, INTENT_TERMS

    q_norm = normalize_text(question)

    # Khử các cụm từ ghép đặc thù trước khi đối chiếu chéo (ví dụ: 'miễn giảm học phí' là scholarship, không phải tuition)
    cleaned_norm = q_norm
    if "mien hoc phi" in cleaned_norm or "giam hoc phi" in cleaned_norm:
        cleaned_norm = cleaned_norm.replace("mien hoc phi", "").replace("giam hoc phi", "")

    matched_primary = set()
    for intent_name in PRIMARY_INTENTS:
        if any(term in cleaned_norm for term in INTENT_TERMS.get(intent_name, ())):
            matched_primary.add(intent_name)

    # Có từ 2 primary intent cạnh tranh trở lên (ví dụ: hỏi cả 'điểm chuẩn' và 'học phí')
    return len(matched_primary) >= 2


# Singleton instance toàn cục của DecisionService
decision_service = DecisionService()
