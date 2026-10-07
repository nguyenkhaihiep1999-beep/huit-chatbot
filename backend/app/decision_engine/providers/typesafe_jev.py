"""
typesafe_jev.py
TypeSafe Jev API Provider implementation.
Endpoint chính thức: POST https://api.typesafe.ai/v1/systemone
Chỉ chịu trách nhiệm:
- Gọi TypeSafe API bằng httpx.AsyncClient;
- Bearer authentication;
- Timeout;
- Xử lý 401, 403, 422, 429, 5xx;
- Tối đa 1 retry với 429 hoặc 5xx; không retry 401, 403, 422;
- Validate response;
- Chuyển response sang internal DecisionResult contract;
- Tuyệt đối không để API key xuất hiện trong log, exception, response hoặc source code.
"""
import asyncio
import math
import random
import time
from typing import Any, Dict, Optional
import httpx

from backend.app.config import settings
from backend.app.decision_engine.contracts import (
    DecisionItem,
    DecisionRequest,
    DecisionResult,
    DecisionUsage,
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
    notify_api_call,
)


class TypeSafeJevProvider(BaseDecisionProvider):
    """Provider giao tiếp trực tiếp với TypeSafe AI (Jev Decision Engine)."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        timeout: Optional[float] = None,
        client: Optional[httpx.AsyncClient] = None,
    ):
        self._api_key = (api_key if api_key is not None else settings.TYPESAFE_API_KEY).strip()
        # Chống SSRF: trong production cố định https://api.typesafe.ai
        if settings.IS_PRODUCTION:
            self._base_url = "https://api.typesafe.ai"
        else:
            self._base_url = (base_url or settings.TYPESAFE_BASE_URL).rstrip("/")
        self._timeout = timeout if timeout is not None else settings.JEV_TIMEOUT_SECONDS
        self._client = client

    def get_name(self) -> str:
        return "typesafe_jev"

    def __repr__(self) -> str:
        configured = bool(self._api_key)
        return f"<TypeSafeJevProvider(configured={configured}, base_url='{self._base_url}')>"

    def _get_headers(self) -> Dict[str, str]:
        if not self._api_key:
            raise DecisionAuthenticationError("TYPESAFE_API_KEY chưa được cấu hình")
        return {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": f"HUIT-Chatbot-DecisionEngine/{settings.VERSION}",
        }

    def _serialize_request(self, request: DecisionRequest) -> Dict[str, Any]:
        questions_payload: Dict[str, Any] = {}
        for q_id, q_def in request.questions.items():
            item: Dict[str, Any] = {"type": q_def.type}
            if q_def.instructions:
                item["instructions"] = q_def.instructions
            if q_def.criteria:
                item["criteria"] = q_def.criteria
            questions_payload[q_id] = item

        return {
            "model": request.model or settings.JEV_MODEL,
            "state": request.state,
            "questions": questions_payload,
        }

    def _parse_response(
        self,
        raw_data: Dict[str, Any],
        request: DecisionRequest,
        latency_ms: float,
    ) -> DecisionResult:
        if not isinstance(raw_data, dict):
            raise DecisionValidationError("Phản hồi từ TypeSafe Jev không phải là JSON object")

        raw_answers = raw_data.get("answers")
        if raw_answers is None:
            raw_answers = raw_data.get("decisions")
        if not isinstance(raw_answers, dict):
            raise DecisionValidationError("Phản hồi từ TypeSafe Jev thiếu trường 'answers' hợp lệ")

        # 1. Kiểm tra 1-to-1: Mỗi câu hỏi gửi đi phải có đúng một answer tương ứng, từ chối answer lạ
        expected_keys = set(request.questions.keys())
        received_keys = set(raw_answers.keys())

        missing_keys = expected_keys - received_keys
        extra_keys = received_keys - expected_keys

        if missing_keys:
            raise DecisionValidationError(
                f"Phản hồi thiếu câu trả lời cho các câu hỏi: {sorted(missing_keys)}"
            )
        if extra_keys:
            raise DecisionValidationError(
                f"Phản hồi chứa câu trả lời lạ không có trong yêu cầu: {sorted(extra_keys)}"
            )

        decisions_map: Dict[str, DecisionItem] = {}
        for q_id, q_def in request.questions.items():
            raw_ans = raw_answers[q_id]
            if not isinstance(raw_ans, dict):
                raise DecisionValidationError(f"Câu trả lời cho '{q_id}' không phải là JSON object")

            # Tuyệt đối không tự động đoán question type khi response sai schema
            q_type = q_def.type
            if raw_ans.get("type") != q_type:
                raise DecisionValidationError(
                    f"Trường 'type' của câu trả lời '{q_id}' thiếu hoặc không khớp với câu hỏi"
                )

            # Confidence: Bắt buộc đối với choice và score (theo đặc tả TypeSafe API).
            # Đối với noul: API chính thức không trả về confidence. Nếu provider trả về thì validate
            # nghiêm ngặt [0.0, 1.0]; nếu không có thì giữ None tường minh, không tự gán 1.0.
            conf_val: Optional[float] = None
            if q_type in ("choice", "score"):
                if "confidence" not in raw_ans or raw_ans["confidence"] is None:
                    raise DecisionValidationError(f"Câu hỏi loại {q_type} '{q_id}' thiếu trường 'confidence'")
                conf_raw = raw_ans["confidence"]
                if not isinstance(conf_raw, (int, float)) or isinstance(conf_raw, bool):
                    raise DecisionValidationError(f"Trường 'confidence' của '{q_id}' không phải là kiểu số")
                conf_val = float(conf_raw)
                if math.isnan(conf_val) or math.isinf(conf_val) or conf_val < 0.0 or conf_val > 1.0:
                    raise DecisionValidationError(
                        f"Trường 'confidence' của '{q_id}' không hợp lệ hoặc ngoài phạm vi [0.0, 1.0]"
                    )
            elif q_type == "noul":
                if "confidence" in raw_ans and raw_ans["confidence"] is not None:
                    conf_raw = raw_ans["confidence"]
                    if not isinstance(conf_raw, (int, float)) or isinstance(conf_raw, bool):
                        raise DecisionValidationError(f"Trường 'confidence' của '{q_id}' không phải là kiểu số")
                    conf_val = float(conf_raw)
                    if math.isnan(conf_val) or math.isinf(conf_val) or conf_val < 0.0 or conf_val > 1.0:
                        raise DecisionValidationError(
                            f"Trường 'confidence' của '{q_id}' không hợp lệ hoặc ngoài phạm vi [0.0, 1.0]"
                        )
                else:
                    conf_val = None

            choice_val: Optional[str] = None
            score_val: Optional[float] = None
            noul_val: Optional[float] = None

            if q_type == "choice":
                if "choice" not in raw_ans or raw_ans["choice"] is None:
                    raise DecisionValidationError(f"Câu hỏi loại choice '{q_id}' thiếu trường 'choice'")
                if raw_ans.get("score") is not None or raw_ans.get("noul") is not None:
                    raise DecisionValidationError(f"Câu hỏi loại choice '{q_id}' không được chứa trường 'score' hoặc 'noul'")
                choice_raw = raw_ans["choice"]
                if not isinstance(choice_raw, str) or not choice_raw.strip():
                    raise DecisionValidationError(f"Trường 'choice' của '{q_id}' phải là chuỗi không rỗng")
                choice_val = choice_raw.strip()
                if q_def.criteria:
                    valid_criteria = q_def.criteria.keys() if isinstance(q_def.criteria, dict) else q_def.criteria
                    if choice_val not in valid_criteria:
                        raise DecisionValidationError(
                            f"Lựa chọn '{choice_val}' không thuộc danh sách criteria của câu hỏi '{q_id}'"
                        )

            elif q_type == "score":
                if "score" not in raw_ans or raw_ans["score"] is None:
                    raise DecisionValidationError(f"Câu hỏi loại score '{q_id}' thiếu trường 'score'")
                if raw_ans.get("choice") is not None or raw_ans.get("noul") is not None:
                    raise DecisionValidationError(f"Câu hỏi loại score '{q_id}' không được chứa trường 'choice' hoặc 'noul'")
                score_raw = raw_ans["score"]
                if not isinstance(score_raw, (int, float)) or isinstance(score_raw, bool):
                    raise DecisionValidationError(f"Trường 'score' của '{q_id}' phải là kiểu số")
                score_val = float(score_raw)
                if math.isnan(score_val) or math.isinf(score_val):
                    raise DecisionValidationError(f"Trường 'score' của '{q_id}' là NaN hoặc Infinity")
                if not 0.0 <= score_val <= len(q_def.criteria) - 1:
                    raise DecisionValidationError(f"Trường 'score' của '{q_id}' ngoài phạm vi các mức criteria")
                expected_legend = {str(i): label for i, label in enumerate(q_def.criteria)}
                legend = raw_ans.get("legend")
                if not isinstance(legend, dict) or legend != expected_legend:
                    raise DecisionValidationError(
                        f"Trường 'legend' của '{q_id}' thiếu hoặc không khớp các mức criteria"
                    )

            elif q_type == "noul":
                if "noul" not in raw_ans or raw_ans["noul"] is None:
                    raise DecisionValidationError(f"Câu hỏi loại noul '{q_id}' thiếu trường 'noul'")
                if raw_ans.get("choice") is not None or raw_ans.get("score") is not None:
                    raise DecisionValidationError(f"Câu hỏi loại noul '{q_id}' không được chứa trường 'choice' hoặc 'score'")
                noul_raw = raw_ans["noul"]
                if not isinstance(noul_raw, (int, float)) or isinstance(noul_raw, bool):
                    raise DecisionValidationError(f"Trường 'noul' của '{q_id}' phải là kiểu số")
                noul_val = float(noul_raw)
                if math.isnan(noul_val) or math.isinf(noul_val) or noul_val < 0.0 or noul_val > 1.0:
                    raise DecisionValidationError(
                        f"Trường 'noul' của '{q_id}' ngoài phạm vi [0.0, 1.0] hoặc không hữu hạn"
                    )

            # Validate probabilities nếu có
            probs = raw_ans.get("probabilities")
            expected_probability_keys = None
            if q_type == "score":
                expected_probability_keys = {str(i) for i in range(len(q_def.criteria))}
                if not isinstance(probs, dict) or set(probs) != expected_probability_keys:
                    raise DecisionValidationError(
                        f"Trường 'probabilities' của '{q_id}' phải chứa đủ chỉ số các mức criteria"
                    )
            elif q_def.criteria:
                expected_probability_keys = set(q_def.criteria)
            probabilities_dict: Optional[Dict[str, float]] = None
            if probs is not None:
                if not isinstance(probs, dict):
                    raise DecisionValidationError(f"Trường 'probabilities' của '{q_id}' phải là object")
                total_p = 0.0
                probabilities_dict = {}
                for k, v in probs.items():
                    if not isinstance(k, str):
                        raise DecisionValidationError(f"Key trong 'probabilities' của '{q_id}' phải là chuỗi")
                    if expected_probability_keys is not None and k not in expected_probability_keys:
                        raise DecisionValidationError(
                            f"Key '{k}' trong 'probabilities' không thuộc criteria của câu hỏi '{q_id}'"
                        )
                    if not isinstance(v, (int, float)) or isinstance(v, bool):
                        raise DecisionValidationError(
                            f"Giá trị xác suất '{k}' trong câu hỏi '{q_id}' không phải số"
                        )
                    p_val = float(v)
                    if math.isnan(p_val) or math.isinf(p_val) or p_val < 0.0 or p_val > 1.0:
                        raise DecisionValidationError(
                            f"Giá trị xác suất '{k}' trong câu hỏi '{q_id}' ngoài phạm vi [0.0, 1.0] hoặc không hữu hạn"
                        )
                    probabilities_dict[k] = p_val
                    total_p += p_val

                if probabilities_dict:
                    # Tổng xác suất phải xấp xỉ 1.0 (cho phép sai số làm tròn 0.90..1.10)
                    if total_p < 0.90 or total_p > 1.10:
                        raise DecisionValidationError(
                            f"Tổng phân phối xác suất ({total_p:.3f}) của '{q_id}' không hợp lý (phải xấp xỉ 1.0)"
                        )

            decisions_map[q_id] = DecisionItem(
                type=q_type,
                choice=choice_val,
                score=score_val,
                noul=noul_val,
                confidence=conf_val,
                probabilities=probabilities_dict,
            )

        raw_usage_value = raw_data.get("usage")
        if raw_usage_value is None:
            raw_usage: Dict[str, Any] = {}
        elif isinstance(raw_usage_value, dict):
            raw_usage = raw_usage_value
        else:
            raise DecisionValidationError("Trường 'usage' phải là JSON object")

        parsed_usage: Dict[str, int] = {}
        for field_name in ("input_tokens", "output_tokens"):
            value = raw_usage.get(field_name, 0)
            if isinstance(value, bool) or not isinstance(value, int):
                raise DecisionValidationError(
                    f"Trường usage.{field_name} phải là số nguyên không âm"
                )
            if value < 0 or value > 10_000_000:
                raise DecisionValidationError(
                    f"Trường usage.{field_name} nằm ngoài phạm vi an toàn"
                )
            parsed_usage[field_name] = value

        usage = DecisionUsage(
            input_tokens=parsed_usage["input_tokens"],
            output_tokens=parsed_usage["output_tokens"],
        )

        model_value = raw_data.get("model") or request.model
        if not isinstance(model_value, str) or not model_value.strip() or len(model_value) > 64:
            raise DecisionValidationError("Trường 'model' trong phản hồi không hợp lệ")

        return DecisionResult(
            decision_type=request.decision_type,
            status="success",
            provider=self.get_name(),
            model=model_value.strip(),
            decisions=decisions_map,
            usage=usage,
            latency_ms=round(latency_ms, 2),
            error_message=None,
        )

    async def _execute_single_http_call(
        self,
        client: httpx.AsyncClient,
        url: str,
        headers: Dict[str, str],
        payload: Dict[str, Any],
        timeout: Optional[float] = None,
    ) -> httpx.Response:
        """Gửi 1 request duy nhất tới TypeSafe Jev endpoint và chuyển mã lỗi thành exception cụ thể."""
        call_timeout = timeout if timeout is not None else self._timeout
        try:
            notify_api_call()
            resp = await client.post(
                url,
                json=payload,
                headers=headers,
                timeout=call_timeout,
            )
        except httpx.TimeoutException as exc:
            raise DecisionTimeoutError(f"Hết thời gian chờ {call_timeout:.2f}s tới TypeSafe Jev") from exc
        except httpx.ConnectError as exc:
            raise DecisionServerError("Không thể thiết lập kết nối tới TypeSafe API", status_code=503) from exc
        except httpx.RequestError as exc:
            raise DecisionServerError(f"Lỗi mạng HTTP: {type(exc).__name__}", status_code=502) from exc

        # Kiểm tra HTTP status codes theo đặc tả bảo mật (không đưa raw response vào message)
        if resp.status_code in (401, 403):
            raise DecisionAuthenticationError(
                f"Lỗi xác thực TypeSafe Jev (HTTP {resp.status_code})"
            )
        if resp.status_code == 402:
            raise DecisionQuotaExhaustedError(
                "Tài khoản TypeSafe Jev đã hết credit hoặc quota (HTTP 402)"
            )
        if resp.status_code == 422:
            raise DecisionValidationError(
                "Payload không hợp lệ đối với TypeSafe Jev (HTTP 422)"
            )
        if resp.status_code == 429:
            retry_after_val: Optional[float] = None
            raw_h = resp.headers.get("Retry-After")
            if raw_h:
                try:
                    retry_after_val = float(raw_h)
                    if not math.isfinite(retry_after_val) or retry_after_val < 0:
                        retry_after_val = None
                except ValueError:
                    retry_after_val = None
            raise DecisionRateLimitError(
                "Đã chạm ngưỡng giới hạn tần suất (HTTP 429 Too Many Requests) của TypeSafe.",
                retry_after=retry_after_val,
            )
        if resp.status_code >= 500:
            raise DecisionServerError(
                f"Máy chủ TypeSafe gặp sự cố (HTTP {resp.status_code})",
                status_code=resp.status_code,
            )
        if not resp.is_success:
            raise DecisionProviderError(
                f"Lỗi không mong muốn từ TypeSafe (HTTP {resp.status_code})",
                status_code=resp.status_code,
            )

        return resp

    async def _execute_call_with_budget(
        self,
        client: httpx.AsyncClient,
        url: str,
        headers: Dict[str, str],
        payload: Dict[str, Any],
        remaining_seconds: float,
    ) -> httpx.Response:
        """Cưỡng chế deadline ở ngoài transport, kể cả MockTransport bỏ qua httpx timeout."""
        if remaining_seconds < 0.05:
            raise DecisionTimeoutError("Tổng latency budget không còn đủ cho HTTP request")
        call_timeout = min(self._timeout, remaining_seconds)
        try:
            return await asyncio.wait_for(
                self._execute_single_http_call(
                    client,
                    url,
                    headers,
                    payload,
                    timeout=call_timeout,
                ),
                timeout=remaining_seconds,
            )
        except asyncio.TimeoutError as exc:
            raise DecisionTimeoutError("TypeSafe Jev vượt tổng latency budget") from exc

    async def decide(
        self,
        request: DecisionRequest,
        total_budget_ms: Optional[float] = None,
    ) -> DecisionResult:
        """Thực thi ra quyết định với tổng latency budget và tối đa 1 retry chỉ cho 429 hoặc 5xx."""
        url = f"{self._base_url}/v1/systemone"
        headers = self._get_headers()
        payload = self._serialize_request(request)

        eff_budget_ms = (
            total_budget_ms if total_budget_ms is not None else settings.JEV_TOTAL_BUDGET_MS
        )
        if (
            isinstance(eff_budget_ms, bool)
            or not isinstance(eff_budget_ms, (int, float))
            or not math.isfinite(float(eff_budget_ms))
            or eff_budget_ms < 50.0
            or eff_budget_ms > 10_000.0
        ):
            raise DecisionTimeoutError("Tổng latency budget nằm ngoài phạm vi an toàn")
        eff_budget_ms = float(eff_budget_ms)
        overall_start = time.perf_counter()
        deadline = overall_start + (eff_budget_ms / 1000.0)

        owns_client = self._client is None
        client = self._client or httpx.AsyncClient(timeout=self._timeout)
        retry_count = 0

        try:
            # Kiểm tra budget trước lần gọi 1
            remaining_s = deadline - time.perf_counter()
            if remaining_s < 0.05:
                raise DecisionTimeoutError("Tổng latency budget đã hết trước khi gửi yêu cầu ban đầu")

            # Lần gọi thứ 1
            try:
                response = await self._execute_call_with_budget(
                    client, url, headers, payload, remaining_s
                )
            except (DecisionRateLimitError, DecisionServerError) as retryable_err:
                remaining_s = deadline - time.perf_counter()

                # Tính toán retry delay dựa trên Retry-After và jitter
                base_delay = 0.15
                if isinstance(retryable_err, DecisionRateLimitError) and retryable_err.retry_after is not None:
                    # Giới hạn Retry-After tối đa 0.5s để không vượt budget
                    base_delay = min(retryable_err.retry_after, 0.5)

                jitter = random.uniform(0.01, 0.04)
                retry_delay = min(base_delay + jitter, 0.5)

                # Nếu budget còn lại không đủ cho thời gian delay + thời gian gọi tối thiểu (80ms), không retry!
                if remaining_s < (retry_delay + 0.08):
                    raise retryable_err

                await asyncio.sleep(retry_delay)
                retry_count = 1

                remaining_s = deadline - time.perf_counter()
                if remaining_s < 0.05:
                    raise DecisionTimeoutError("Tổng latency budget đã hết trước khi retry yêu cầu")

                response = await self._execute_call_with_budget(
                    client, url, headers, payload, remaining_s
                )

            latency_ms = (time.perf_counter() - overall_start) * 1000.0
            if time.perf_counter() > deadline:
                raise DecisionTimeoutError("TypeSafe Jev vượt tổng latency budget")
            try:
                raw_data = response.json()
            except Exception as json_err:
                raise DecisionValidationError("Không thể giải mã JSON từ phản hồi của TypeSafe Jev") from json_err

            result = self._parse_response(raw_data, request, latency_ms)
            result._retry_count = retry_count
            result._provider_latency_ms = latency_ms
            return result

        except Exception as exc:
            # Giữ metadata retry khi lần gọi thứ hai hoặc bước parse response thất bại.
            setattr(exc, "retry_count", retry_count)
            raise
        finally:
            if owns_client:
                await client.aclose()

    async def check_health(self) -> Dict[str, Any]:
        """Kiểm tra cấu hình tĩnh an toàn mà không thực hiện paid API request."""
        if not self._api_key:
            return {
                "status": "disabled",
                "configured": False,
                "provider": self.get_name(),
                "model": settings.JEV_MODEL,
            }
        return {
            "status": "configured",
            "configured": True,
            "provider": self.get_name(),
            "model": settings.JEV_MODEL,
            "endpoint": f"{self._base_url}/v1/systemone",
        }
