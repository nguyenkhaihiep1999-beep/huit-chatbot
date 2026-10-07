"""
test_jev_evaluation.py
Bộ kiểm thử toàn diện cho hệ thống đánh giá JEV (Evaluation Suite):
1. Dataset contract: Số lượng case >= 60, rubric, schema, nhóm, tính đa dạng.
2. Logic tính toán metric: Intent Accuracy, Macro-F1, Confusion handling, Zero division.
3. Evidence Sufficiency & Needs Clarification riêng biệt.
4. Loại trừ Fallback/Skipped khỏi dự đoán đúng (không bao giờ coi fallback là True Positive).
5. Phân tách rạch ròi giữa Baseline Agreement và Ground Truth Accuracy.
6. Quy tắc thống kê P99 (chỉ tính khi N >= 100, bỏ qua khi N < 100).
7. Đo lường hiệu năng chat (TTFT tới token đầu tiên, total time, shadow overhead, NDJSON sequence).
8. Tính an toàn bảo mật của Report (không chứa secret, không chứa raw user data).
"""
import json
import os
import pytest
from typing import Any, Dict, List

from backend.app.decision_engine.contracts import DecisionItem, DecisionResult, DecisionUsage
from backend.app.decision_engine.policies import INTENT_CHOICES, SUFFICIENCY_CHOICES
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
    run_evaluation_suite,
    MockEvaluationDecisionProvider,
)


# ---------------------------------------------------------------------------
# 1. KIỂM THỬ BỘ DỮ LIỆU SYNTHETIC VÀ RUBRIC GÁN NHÃN
# ---------------------------------------------------------------------------
def test_evaluation_dataset_contract():
    """Kiểm tra hợp đồng của bộ dữ liệu synthetic:

    - Số lượng >= 60 tình huống (hiện tại là 68).
    - Có đầy đủ các nhóm bắt buộc: clear, ambiguous, multiple, needs_clarification, evidence, out_of_scope, privacy, guardrail.
    - Không trùng ID.
    - Có đầy đủ expected_intent hợp lệ và label_reasoning.
    - Có phân định rõ requires_human_review (True vs False).
    """
    assert len(EVALUATION_DATASET) >= 60, f"Dataset phải có ít nhất 60 case, thực tế: {len(EVALUATION_DATASET)}"

    ids = set()
    groups = set()
    human_review_count = 0
    accepted_count = 0

    for case in EVALUATION_DATASET:
        c_id = case.get("id")
        assert c_id is not None and c_id not in ids, f"Trùng lặp hoặc thiếu ID: {c_id}"
        ids.add(c_id)

        group = case.get("group")
        assert group is not None, f"Thiếu group tại case {c_id}"
        groups.add(group)

        assert "question" in case and len(case["question"].strip()) > 0
        assert "expected_intent" in case
        assert case["expected_intent"] in INTENT_CHOICES, f"Intent không hợp lệ: {case['expected_intent']} tại {c_id}"
        assert "expected_needs_clarification" in case
        assert isinstance(case["expected_needs_clarification"], bool)
        assert "label_reasoning" in case and len(case["label_reasoning"].strip()) > 0
        assert "requires_human_review" in case
        assert isinstance(case["requires_human_review"], bool)

        if case["requires_human_review"]:
            human_review_count += 1
        else:
            accepted_count += 1

        if "docs" in case:
            assert "expected_sufficiency" in case
            assert case["expected_sufficiency"] in SUFFICIENCY_CHOICES

    # Kiểm tra tính đa dạng của nhóm
    required_groups = {
        "clear_intent",
        "ambiguous_intent",
        "multiple_intents",
        "needs_clarification",
        "evidence_sufficiency",
        "out_of_scope",
        "privacy_redaction",
        "guardrail_safety",
    }
    assert required_groups.issubset(groups), f"Thiếu các nhóm bắt buộc: {required_groups - groups}"

    # Có cả case chắc chắn (accepted) và case cần duyệt (human review)
    assert human_review_count > 0, "Phải có case được đánh dấu requires_human_review=True"
    assert accepted_count >= 50, f"Phải có ít nhất 50 case ground-truth được chấp nhận, thực tế: {accepted_count}"

    # Kiểm tra Rubric
    assert "intent_criteria" in LABELING_RUBRIC
    assert "needs_clarification_criteria" in LABELING_RUBRIC
    assert "evidence_sufficiency_criteria" in LABELING_RUBRIC
    assert "acceptance_policy" in LABELING_RUBRIC


# ---------------------------------------------------------------------------
# 2. KIỂM THỬ TÍNH TOÁN INTENT ACCURACY & MACRO-F1
# ---------------------------------------------------------------------------
def test_intent_metrics_calculation_perfect_match():
    """Kiểm tra khi tất cả case dự đoán đúng thì Accuracy và Macro-F1 đạt 100%."""
    records = [
        {"expected_intent": "tuition", "predicted_intent": "tuition", "status": "success", "requires_human_review": False},
        {"expected_intent": "cutoff", "predicted_intent": "cutoff", "status": "success", "requires_human_review": False},
        {"expected_intent": "scholarship", "predicted_intent": "scholarship", "status": "success", "requires_human_review": False},
    ]
    res = calculate_intent_metrics(records, accepted_only=True)
    assert res["evaluated_count"] == 3
    assert res["correct_count"] == 3
    assert res["accuracy"] == 100.0
    assert res["macro_f1"] == 100.0


def test_intent_metrics_fallback_and_skipped_never_count_as_correct():
    """Yêu cầu cốt lõi: Fallback, skipped hoặc error KHÔNG BAO GIỜ được tính là dự đoán đúng."""
    records = [
        # Dù predicted_intent tình cờ trùng, nhưng status là fallback -> KHÔNG được tính đúng
        {"expected_intent": "tuition", "predicted_intent": "tuition", "status": "fallback", "requires_human_review": False},
        {"expected_intent": "cutoff", "predicted_intent": "cutoff", "status": "error", "requires_human_review": False},
        {"expected_intent": "scholarship", "predicted_intent": "scholarship", "status": "skipped", "requires_human_review": False},
        # Chỉ case này là success và đúng
        {"expected_intent": "admission", "predicted_intent": "admission", "status": "success", "requires_human_review": False},
    ]
    res = calculate_intent_metrics(records, accepted_only=True)
    assert res["evaluated_count"] == 4
    assert res["correct_count"] == 1
    assert res["accuracy"] == 25.0


def test_intent_metrics_human_review_filtering():
    """Chỉ đánh giá trên các case có nhãn được chấp nhận (requires_human_review == False)."""
    records = [
        # Case chấp nhận: đúng
        {"expected_intent": "tuition", "predicted_intent": "tuition", "status": "success", "requires_human_review": False},
        # Case cần duyệt (chưa duyệt): sai, nhưng không được tính vào bộ đo chính thức khi accepted_only=True
        {"expected_intent": "cutoff", "predicted_intent": "tuition", "status": "success", "requires_human_review": True},
    ]
    res_accepted = calculate_intent_metrics(records, accepted_only=True)
    assert res_accepted["evaluated_count"] == 1
    assert res_accepted["accuracy"] == 100.0

    res_all = calculate_intent_metrics(records, accepted_only=False)
    assert res_all["evaluated_count"] == 2
    assert res_all["accuracy"] == 50.0


def test_intent_metrics_zero_division_safety():
    """Bảo đảm không crash ZeroDivisionError khi danh sách rỗng hoặc class không có dự đoán."""
    res_empty = calculate_intent_metrics([], accepted_only=True)
    assert res_empty["evaluated_count"] == 0
    assert res_empty["accuracy"] == 0.0
    assert res_empty["macro_f1"] == 0.0

    # Tất cả đều đoán nhầm sang 1 class duy nhất
    records = [
        {"expected_intent": "tuition", "predicted_intent": "general", "status": "success", "requires_human_review": False},
        {"expected_intent": "cutoff", "predicted_intent": "general", "status": "success", "requires_human_review": False},
    ]
    res = calculate_intent_metrics(records, accepted_only=True)
    assert res["accuracy"] == 0.0
    assert res["macro_f1"] == 0.0


# ---------------------------------------------------------------------------
# 3. KIỂM THỬ EVIDENCE SUFFICIENCY & NEEDS CLARIFICATION
# ---------------------------------------------------------------------------
def test_evidence_sufficiency_metrics():
    """Kiểm tra tính toán riêng biệt cho 4 mức độ minh chứng."""
    records = [
        {"expected_sufficiency": "sufficient", "predicted_sufficiency": "sufficient", "status": "success", "requires_human_review": False},
        {"expected_sufficiency": "partial", "predicted_sufficiency": "partial", "status": "success", "requires_human_review": False},
        {"expected_sufficiency": "insufficient", "predicted_sufficiency": "sufficient", "status": "success", "requires_human_review": False},  # Sai
        {"expected_sufficiency": "conflicting", "predicted_sufficiency": "conflicting", "status": "fallback", "requires_human_review": False},  # Fallback -> Sai
        # Case không có evidence (ví dụ câu hỏi thông thường) -> Phải bị bỏ qua
        {"expected_intent": "tuition", "status": "success", "requires_human_review": False},
    ]
    res = calculate_evidence_metrics(records, accepted_only=True)
    assert res["evaluated_count"] == 4
    assert res["correct_count"] == 2  # sufficient và partial
    assert res["accuracy"] == 50.0


def test_clarification_metrics():
    """Kiểm tra binary classification metrics cho needs_clarification."""
    records = [
        {"expected_needs_clarification": True, "predicted_needs_clarification": True, "status": "success", "requires_human_review": False},  # TP
        {"expected_needs_clarification": False, "predicted_needs_clarification": False, "status": "success", "requires_human_review": False},  # TN
        {"expected_needs_clarification": True, "predicted_needs_clarification": False, "status": "success", "requires_human_review": False},  # FN
        {"expected_needs_clarification": False, "predicted_needs_clarification": True, "status": "success", "requires_human_review": False},  # FP
    ]
    res = calculate_clarification_metrics(records, accepted_only=True)
    assert res["evaluated_count"] == 4
    assert res["accuracy"] == 50.0
    assert res["tp"] == 1
    assert res["tn"] == 1
    assert res["fp"] == 1
    assert res["fn"] == 1
    assert res["precision"] == 50.0
    assert res["recall"] == 50.0
    assert res["f1"] == 50.0


# ---------------------------------------------------------------------------
# 4. KIỂM THỬ COVERAGE VÀ TỶ LỆ TRẠNG THÁI
# ---------------------------------------------------------------------------
def test_coverage_and_status_breakdown():
    """Kiểm tra tính toán coverage, fallback, error, skipped."""
    records = [
        {"id": "c1", "status": "success", "requires_human_review": False},
        {"id": "c2", "status": "success", "requires_human_review": False},
        {"id": "c3", "status": "fallback", "requires_human_review": False},
        {"id": "c4", "status": "error", "requires_human_review": False},
        {"id": "c5", "status": "skipped", "requires_human_review": True},
    ]
    cov = calculate_coverage_and_status(records)
    assert cov["total_cases"] == 5
    assert cov["accepted_ground_truth_cases"] == 4
    assert cov["human_review_flagged_cases"] == 1
    assert cov["evaluated_count"] == 5
    assert cov["success_count"] == 2
    assert cov["fallback_count"] == 1
    assert cov["error_count"] == 1
    assert cov["skipped_count"] == 1
    assert cov["success_rate"] == 40.0
    assert cov["fallback_rate"] == 20.0
    assert cov["error_rate"] == 20.0


# ---------------------------------------------------------------------------
# 5. TÁCH RẠCH RÒI BASELINE AGREEMENT VÀ GROUND TRUTH ACCURACY
# ---------------------------------------------------------------------------
def test_baseline_agreement_independent_of_ground_truth():
    """Baseline agreement chỉ đo độ khớp rule cũ, không liên quan đến expected_intent."""
    records = [
        # Trường hợp 1: Jev khớp Baseline nhưng cả 2 đều SAI so với Ground Truth
        {
            "id": "c1",
            "group": "test",
            "baseline_intent": "general",
            "predicted_intent": "general",
            "expected_intent": "tuition",
            "status": "success",
            "requires_human_review": False,
        },
        # Trường hợp 2: Jev ĐÚNG theo Ground Truth nhưng KHÁC Baseline
        {
            "id": "c2",
            "group": "test",
            "baseline_intent": "general",
            "predicted_intent": "cutoff",
            "expected_intent": "cutoff",
            "status": "success",
            "requires_human_review": False,
        },
    ]
    agree = calculate_baseline_agreement(records)
    intent_m = calculate_intent_metrics(records, accepted_only=True)

    # Đồng thuận với baseline là 50% (c1 khớp general, c2 lệch)
    assert agree["agreement_rate"] == 50.0
    assert agree["agreement_count"] == 1
    # Độ chính xác theo ground truth cũng là 50% (c1 sai, c2 đúng)
    assert intent_m["accuracy"] == 50.0
    # Nhưng c1 được tính vào agreement dù là dự đoán SAI theo Ground Truth
    assert agree["total_compared"] == 2


# ---------------------------------------------------------------------------
# 6. KIỂM THỬ QUY TẮC THỐNG KÊ P99
# ---------------------------------------------------------------------------
def test_latency_percentiles_p99_omitted_when_n_under_100():
    """Khi N < 100 mẫu, P99 bắt buộc phải là None kèm ghi chú giải thích."""
    small_samples = [10.0, 20.0, 30.0, 40.0, 50.0]
    res_small = calculate_latency_percentiles(small_samples)
    assert res_small["sample_count"] == 5
    assert res_small["p50_ms"] == 30.0
    assert res_small["p99_ms"] is None
    assert "N=5 < 100" in res_small["p99_note"]

    # Khi N >= 100 mẫu, P99 được tính toán chính xác
    large_samples = [float(i) for i in range(1, 101)]  # 100 mẫu từ 1.0 đến 100.0
    res_large = calculate_latency_percentiles(large_samples)
    assert res_large["sample_count"] == 100
    assert res_large["p99_ms"] is not None
    assert res_large["p99_ms"] >= 99.0


# ---------------------------------------------------------------------------
# 7. KIỂM THỬ MOCK CHAT PERFORMANCE MEASUREMENT
# ---------------------------------------------------------------------------
def test_mock_chat_performance_measurement():
    """Kiểm tra hàm đo TTFT và tổng thời gian chat qua 5 profile."""
    # Chạy lặp 1 lần trên 2 profile cơ bản để kiểm chứng tốc độ nhanh
    res = measure_chat_performance(profiles=["success", "timeout"], repeat_count=1)

    assert "off_baseline" in res
    assert "shadow_profiles" in res
    assert "disclaimer" in res

    off_b = res["off_baseline"]
    assert off_b["sample_count"] == 1
    assert off_b["ttft_p50_ms"] >= 0.0
    assert off_b["total_p50_ms"] >= off_b["ttft_p50_ms"]

    shadow_succ = res["shadow_profiles"]["success"]
    assert shadow_succ["sample_count"] == 1
    assert shadow_succ["ttft_p50_ms"] >= 0.0
    assert shadow_succ["total_p50_ms"] >= shadow_succ["ttft_p50_ms"]
    assert shadow_succ["output_identical"] is True
    assert shadow_succ["protocol_intact"] is True

    shadow_timeout = res["shadow_profiles"]["timeout"]
    assert shadow_timeout["output_identical"] is True
    assert shadow_timeout["protocol_intact"] is True


def test_evaluation_suite_report_safety():
    """Kiểm tra báo cáo evaluation suite không chứa bí mật hay thông tin cá nhân."""
    import asyncio
    sample_cases = EVALUATION_DATASET[:6]
    provider = MockEvaluationDecisionProvider(profile="success", delay_ms=10.0)

    async def _run():
        return await run_evaluation_suite(
            dataset=sample_cases,
            provider=provider,
            runner_mode="mock",
            include_chat_perf=False,
        )

    report = asyncio.run(_run())

    assert report["runner_mode"] == "mock"
    assert "mock" in report["mode_disclaimer"].lower()
    assert report["security_and_redaction"]["status"] == "PASSED"
    assert report["security_and_redaction"]["redaction_violations"] == 0

    # Chuyển report sang chuỗi JSON và quét chuỗi cấm
    serialized = json.dumps(report, ensure_ascii=False)
    forbidden_terms = [
        "typesafe_api_key",
        "mongodb+srv://",
        "sk-",
        "AIza",
        "0903123456",
        "079201009988",
    ]
    for term in forbidden_terms:
        assert term not in serialized, f"Tìm thấy dữ liệu nhạy cảm trong report: {term}"


# ---------------------------------------------------------------------------
# 8. REGRESSION TESTS CHO CONTRACT, WORKFLOWS VÀ PERFORMANCE MEASUREMENT
# ---------------------------------------------------------------------------
def test_mock_evaluation_provider_contract_and_success_profile():
    """Regression test 1: MockEvaluationDecisionProvider nhận total_budget_ms và trả DecisionResult đầy đủ."""
    import asyncio
    from backend.app.decision_engine.contracts import DecisionRequest, QuestionDefinition

    provider = MockEvaluationDecisionProvider(profile="success", delay_ms=10.0)
    req = DecisionRequest(
        decision_type="intent",
        state="Học phí ngành Công nghệ thông tin một năm là bao nhiêu?",
        model="jev-latest",
        questions={
            "intent": QuestionDefinition(type="choice"),
            "needs_clarification": QuestionDefinition(type="noul"),
        },
    )

    async def _test():
        # Gọi decide với tham số total_budget_ms đúng giao diện BaseDecisionProvider
        result = await provider.decide(req, total_budget_ms=250.0)
        return result

    result = asyncio.run(_test())

    # Kiểm tra contract đầy đủ
    assert result.status == "success"
    assert result.decision_type == "intent"
    assert result.provider == provider.get_name()
    assert result.model == "mock-jev-evaluator-v1"
    assert result.error_message is None
    assert result.latency_ms > 0.0

    # DecisionUsage chỉ có input_tokens và output_tokens, tuyệt đối không có total_tokens
    assert result.usage is not None
    assert result.usage.input_tokens == 120
    assert result.usage.output_tokens == 15
    assert not hasattr(result.usage, "total_tokens")
    # Tính tổng bằng phép cộng
    assert (result.usage.input_tokens + result.usage.output_tokens) == 135

    # Nội dung quyết định thực sự thành công
    assert "intent" in result.decisions
    assert result.decisions["intent"].choice == "tuition"
    assert result.decisions["intent"].confidence >= 0.90
    assert "needs_clarification" in result.decisions
    assert result.decisions["needs_clarification"].noul is not None


def test_valid_provider_usage_does_not_turn_runner_into_error():
    """Regression test 2: Provider hợp lệ có usage không làm runner gặp AttributeError rồi chuyển thành error."""
    import asyncio

    sample_cases = EVALUATION_DATASET[:3]
    provider = MockEvaluationDecisionProvider(profile="success", delay_ms=5.0)

    async def _run():
        return await run_evaluation_suite(
            dataset=sample_cases,
            provider=provider,
            runner_mode="mock",
            include_chat_perf=False,
        )

    report = asyncio.run(_run())
    cov = report["coverage_and_status"]
    assert cov["error_count"] == 0
    assert cov["success_count"] == 3
    # Xác nhận token được tính toán đúng bằng phép cộng
    for rec in report["anonymized_telemetry_sample"][:3]:
        assert rec["status"] == "success"
        assert rec["tokens_used"] > 0


def test_intent_correct_and_evidence_error_keeps_intent_score():
    """Regression test 3: Evidence fallback/error không làm intent đã dự đoán đúng mất điểm, và ngược lại."""
    # Case 1: Intent đúng (tuition == tuition), nhưng Evidence lỗi
    records_1 = [
        {
            "id": "c1",
            "group": "test",
            "expected_intent": "tuition",
            "predicted_intent": "tuition",
            "intent_status": "success",
            "expected_sufficiency": "sufficient",
            "predicted_sufficiency": None,
            "evidence_status": "error",
            "status": "error",  # overall status là error
            "requires_human_review": False,
        }
    ]
    intent_m = calculate_intent_metrics(records_1, accepted_only=True)
    evidence_m = calculate_evidence_metrics(records_1, accepted_only=True)

    # Intent giữ nguyên điểm đúng 100%
    assert intent_m["correct_count"] == 1
    assert intent_m["accuracy"] == 100.0
    # Evidence tính đúng 0%
    assert evidence_m["correct_count"] == 0
    assert evidence_m["accuracy"] == 0.0

    # Case 2: Intent lỗi (status error), nhưng Evidence đúng (sufficient == sufficient)
    records_2 = [
        {
            "id": "c2",
            "group": "test",
            "expected_intent": "cutoff",
            "predicted_intent": None,
            "intent_status": "error",
            "expected_sufficiency": "sufficient",
            "predicted_sufficiency": "sufficient",
            "evidence_status": "success",
            "status": "error",
            "requires_human_review": False,
        }
    ]
    intent_m2 = calculate_intent_metrics(records_2, accepted_only=True)
    evidence_m2 = calculate_evidence_metrics(records_2, accepted_only=True)

    assert intent_m2["correct_count"] == 0
    assert intent_m2["accuracy"] == 0.0
    # Evidence giữ nguyên điểm đúng 100%
    assert evidence_m2["correct_count"] == 1
    assert evidence_m2["accuracy"] == 100.0


def test_clarification_none_not_counted_as_correct():
    """Regression test 4: Prediction thiếu/None tuyệt đối không được ép thành False rồi tính đúng True Negative."""
    records = [
        {
            "id": "c_missing",
            "group": "test",
            "expected_needs_clarification": False,
            "predicted_needs_clarification": None,  # Model không đưa ra phán đoán (hoặc None)
            "clarification_status": "missing",
            "status": "fallback",
            "requires_human_review": False,
        }
    ]
    clar_m = calculate_clarification_metrics(records, accepted_only=True)

    # Không được cộng True Negative
    assert clar_m["tn"] == 0
    assert clar_m["correct_count"] == 0
    assert clar_m["accuracy"] == 0.0
    assert clar_m["missing_count"] == 1


def test_empty_tokens_before_content_token_ttft():
    """Regression test 5: TTFT chỉ tính tại token nội dung không rỗng; token rỗng hoặc whitespace không được tính."""
    # Case 1: Token rỗng xuất hiện trước token nội dung -> TTFT đo đúng từ token có nội dung đầu tiên
    tokens_with_empty = ["", "   ", "Đại học ", "HUIT."]
    res = measure_chat_performance(profiles=["success"], repeat_count=1, custom_tokens=tokens_with_empty)
    succ = res["shadow_profiles"]["success"]

    assert succ["sample_count"] == 1
    assert succ["content_token_samples"] == 1
    assert succ["missing_content_tokens"] == 0
    assert succ["ttft_p50_ms"] > 0.0

    # Case 2: Toàn bộ stream chỉ có token rỗng/whitespace -> báo missing_content_tokens và không ghi TTFT giả (0.0)
    res_empty = measure_chat_performance(
        profiles=["success"],
        repeat_count=1,
        custom_tokens=["", "   ", "\t"],
    )
    succ_empty = res_empty["shadow_profiles"]["success"]
    assert succ_empty["missing_content_tokens"] == 1
    assert succ_empty["content_token_samples"] == 0
    assert succ_empty["ttft_p50_ms"] == 0.0


def test_concurrent_chat_performance_creates_real_in_flight():
    """Regression test 6: Profile concurrent tạo tải đồng thời thật với barrier kiểm chứng, peak_in_flight > 1."""
    res = measure_chat_performance(profiles=["concurrent"], repeat_count=3)
    conc = res["shadow_profiles"]["concurrent"]

    assert conc["target_concurrency"] >= 3
    assert conc["peak_in_flight"] > 1, f"Yêu cầu peak_in_flight > 1, thực tế: {conc['peak_in_flight']}"
    assert conc["branch_verified"] is True
    assert conc["output_identical"] is True
    assert conc["protocol_intact"] is True
