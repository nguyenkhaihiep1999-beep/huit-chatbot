"""
smoke_test_jev_live.py
Script kiểm tra kết nối smoke test tới TypeSafe JEV AI API thật trên staging.

Quy tắc bảo mật:
- Tuyệt đối không hardcode, log, print hay ghi API key ra console, file hay exception.
- Chỉ đọc TYPESAFE_API_KEY từ biến môi trường của tiến trình hiện tại.
- Gửi payload tổng hợp/ẩn danh đã qua redaction, không chứa thông tin người dùng thật.
- Kiểm tra contract và tính toàn vẹn của phản hồi theo đặc tả System One.
"""

import asyncio
from datetime import datetime, timezone
import os
import sys
import time
from typing import Any, Dict

if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

# Ensure project root is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from backend.app.config import settings
from backend.app.contracts.schema_registry import validate_contract
from backend.app.decision_engine.contracts import DecisionRequest, QuestionDefinition
from backend.app.decision_engine.policies import get_intent_decision_questions
from backend.app.decision_engine.providers.typesafe_jev import TypeSafeJevProvider
from backend.app.decision_engine.redaction import build_intent_decision_state


async def run_live_smoke_test() -> Dict[str, Any]:
    api_key = os.getenv("TYPESAFE_API_KEY", "").strip()
    key_configured = bool(api_key)

    report: Dict[str, Any] = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "runner_mode": "live",
        "endpoint": f"{settings.TYPESAFE_BASE_URL}/v1/systemone",
        "model": settings.JEV_MODEL,
        "api_key_configured": key_configured,
        "api_key_status": "CONFIGURED" if key_configured else "NOT_CONFIGURED",
        "smoke_status": "SKIPPED",
        "blocker": None,
        "latency_ms": None,
        "contract_verified": False,
        "request_contract_version": "2.0.0",
        "verified_question_types": {},
        "token_usage": None,
        "result_status": None,
    }

    if not key_configured:
        report["smoke_status"] = "BLOCKED"
        report["blocker"] = (
            "Thiếu biến môi trường TYPESAFE_API_KEY trên môi trường Staging. "
            "Cần cấu hình TYPESAFE_API_KEY qua Secret Manager hoặc biến môi trường trước khi chạy kiểm chứng live."
        )
        print("=" * 60)
        print("🔍 JEV AI LIVE SMOKE TEST (Staging Verification)")
        print("=" * 60)
        print(f"Endpoint: {report['endpoint']}")
        print(f"Model: {report['model']}")
        print(f"API Key: ⚠️ {report['api_key_status']}")
        print(f"Trạng thái: ⛔ {report['smoke_status']}")
        print(f"Lý do: {report['blocker']}")
        print("=" * 60)
        return report

    print("=" * 60)
    print("🔍 JEV AI LIVE SMOKE TEST (Staging Verification)")
    print("=" * 60)
    print(f"Endpoint: {report['endpoint']}")
    print(f"Model: {report['model']}")
    print(f"API Key: ✅ {report['api_key_status']}")

    # Câu hỏi tổng hợp ẩn danh đã kiểm duyệt
    synthetic_question = "Học phí một năm ngành Kỹ thuật phần mềm là bao nhiêu?"
    state = build_intent_decision_state(
        question=synthetic_question,
        current_intent="general",
        max_bytes=settings.JEV_MAX_STATE_BYTES,
    )
    questions = get_intent_decision_questions()
    questions["urgency_score"] = QuestionDefinition(
        type="score",
        instructions="Rate the urgency expressed in the synthetic admission question.",
        criteria=["No urgency expressed", "Explicitly time-sensitive"],
    )
    request = DecisionRequest(
        decision_type="intent",
        state=state,
        model=settings.JEV_MODEL,
        questions=questions,
    )

    provider = TypeSafeJevProvider(api_key=api_key)
    start_t = time.perf_counter()

    try:
        validate_contract("huit.decision.decision-request", "2.0.0", request.model_dump())
        result = await provider.decide(request, total_budget_ms=settings.JEV_TOTAL_BUDGET_MS)
        validate_contract("huit.decision.decision-result", "1.0.0", result.model_dump())
        elapsed_ms = (time.perf_counter() - start_t) * 1000.0
        report["latency_ms"] = round(elapsed_ms, 2)
        report["result_status"] = result.status
        report["token_usage"] = {
            "input_tokens": result.usage.input_tokens,
            "output_tokens": result.usage.output_tokens,
        }
        report["verified_question_types"] = {
            q_id: item.type
            for q_id, item in result.decisions.items()
            if q_id in questions and item.type == questions[q_id].type
        }
        report["contract_verified"] = (
            result.status == "success"
            and set(result.decisions) == set(questions)
            and set(report["verified_question_types"]) == set(questions)
        )
        report["smoke_status"] = "PASSED" if report["contract_verified"] else "FAILED"

        print(f"Kết quả: ✅ {report['smoke_status']}")
        print(f"Độ trễ: {report['latency_ms']} ms")
        print(f"Contract verified: {report['contract_verified']}")
        print(f"Tokens: input={result.usage.input_tokens}, output={result.usage.output_tokens}")
    except Exception as exc:
        elapsed_ms = (time.perf_counter() - start_t) * 1000.0
        report["latency_ms"] = round(elapsed_ms, 2)
        report["smoke_status"] = "FAILED"
        report["blocker"] = f"{type(exc).__name__}: lỗi khi gọi live API"
        print(f"Kết quả: ❌ {report['smoke_status']}")
        print(f"Lỗi: {report['blocker']}")
        print(f"Độ trễ: {report['latency_ms']} ms")

    print("=" * 60)
    return report


if __name__ == "__main__":
    rep = asyncio.run(run_live_smoke_test())
    sys.exit(0 if rep["smoke_status"] == "PASSED" else (2 if rep["smoke_status"] == "BLOCKED" else 1))
