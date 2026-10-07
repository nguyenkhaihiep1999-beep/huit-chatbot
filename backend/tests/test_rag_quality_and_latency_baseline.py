"""test_rag_quality_and_latency_baseline.py
Bộ kiểm thử chuẩn hóa và Regression Tests cho Phân hệ RAG Baseline:

Blocker 1: Loại bỏ Recall/Precision/MRR đúng giả
- Sai ID nhưng khớp alias → Recall/Precision/MRR bằng 0.
- Đúng ID, nhiều alias → chỉ tính một tài liệu.
- Cùng chủ đề nhưng khác năm/phương thức → không tự nhận đúng.
- Tài liệu trùng hoặc thiếu ID không nâng điểm.

Blocker 2: Không tự phong câu trả lời là supported & Ràng buộc Annotation với Nguồn thực tế
- Giữ nguyên answer, thay source ID → không supported.
- Giữ ID nhưng thay nội dung nguồn → annotation cũ không được tái sử dụng.
- Đổi thứ tự nguồn khiến citation trỏ sai → không được duyệt.
- Annotation thiếu, pending, sai phiên bản hoặc thiếu thông tin nguồn → chưa xác minh (unverified).
- Case pending có từ khóa làm rõ/từ chối nhưng không có annotation → không full_success.
- Annotation approved khớp đầy đủ → trả đúng verdict.
- Khẳng định không được nguồn hỗ trợ nhưng có [1] và đủ dài → không supported/full_success.
- Citation không tồn tại → invalid citation.

Blocker 3: Không chọn bottleneck production từ sleep giả lập
- Đổi thời gian sleep không tạo ưu tiên tối ưu production.
- Thiếu provenance → không được coi là số đo thực tế.
- Báo cáo simulated không chứa kết luận hiệu năng production.

Cùng các bài test hợp đồng, bảo mật và deterministic replay.
"""
import json
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import MagicMock, patch
import pytest

from backend.app.rag.evaluation_dataset import RAG_BENCHMARK_DATASET, EVALUATION_RUBRIC
from backend.app.rag.evaluation_metrics import (
    calculate_latency_percentiles,
    calculate_retrieval_case_metrics,
    classify_retrieval_error,
    compute_answer_hash,
    compute_source_fingerprint,
    evaluate_answer_faithfulness,
    generate_evidence_based_recommendations,
    get_document_id,
    is_doc_relevant,
    is_valid_source_version,
    load_answer_annotations,
    sanitize_report_data,
)
from backend.app.telemetry.metrics import LatencyBreakdown
from scripts.rag_quality_and_latency_baseline import (
    InMemoryFixtureRetriever,
    InMemoryReplayPipeline,
    generate_baseline_report,
    load_fixture_corpus,
    run_retrieval_benchmark_offline,
)


def test_rag_benchmark_dataset_contract():
    """Kiểm tra hợp đồng của bộ dữ liệu benchmark chuẩn hóa:
    - Số lượng case >= 30 (hiện tại là 36).
    - Có đầy đủ 6 nhóm bắt buộc.
    - Không trùng lặp ID.
    - Mỗi case có expected_relevant_doc_ids duy nhất.
    - Phân định rõ requires_human_review và status.
    """
    assert len(RAG_BENCHMARK_DATASET) >= 30, f"Dataset phải có ít nhất 30 case, thực tế: {len(RAG_BENCHMARK_DATASET)}"

    ids = set()
    categories = set()
    pending_count = 0
    accepted_count = 0

    for case in RAG_BENCHMARK_DATASET:
        c_id = case.get("id")
        assert c_id is not None and c_id not in ids, f"Trùng lặp hoặc thiếu ID: {c_id}"
        ids.add(c_id)

        cat = case.get("category")
        assert cat is not None, f"Thiếu category tại {c_id}"
        categories.add(cat)

        assert "query" in case and len(case["query"].strip()) > 0
        assert "expected_intent" in case
        assert "label_reasoning" in case and len(case["label_reasoning"].strip()) > 0
        assert "requires_human_review" in case
        assert isinstance(case["requires_human_review"], bool)
        assert "status" in case
        assert case["status"] in ("chấp nhận", "chưa được duyệt")

        assert "expected_relevant_doc_ids" in case, f"Thiếu expected_relevant_doc_ids tại {c_id}"
        assert isinstance(case["expected_relevant_doc_ids"], list)

        if case["requires_human_review"]:
            assert case["status"] == "chưa được duyệt"
            pending_count += 1
        else:
            assert case["status"] == "chấp nhận"
            accepted_count += 1

    required_categories = {
        "clear_intent",
        "missing_info",
        "multiple_intents",
        "out_of_scope",
        "wrong_year_or_method",
        "conflicting_or_unverified",
    }
    assert required_categories.issubset(categories), f"Thiếu các nhóm bắt buộc: {required_categories - categories}"
    assert accepted_count >= 15, "Phải có ít nhất 15 case ground truth được chấp nhận"
    assert pending_count >= 5, "Phải có các case dự thảo đánh dấu cần người dùng duyệt"


# =============================================================================
# BLOCKER 1 REGRESSION TESTS: Loại bỏ Recall/Precision/MRR đúng giả
# =============================================================================

def test_regression_blocker1_wrong_id_with_matching_alias_scores_zero():
    """Regression Test 1.1:
    Tài liệu SAI ID nhưng khớp alias/từ khóa → Recall, Precision, MRR BẮT BUỘC bằng 0.
    Alias/từ khóa tuyệt đối không biến tài liệu sai ID thành true positive.
    """
    expected_ids = ["doc_major_cntt_7480201"]

    wrong_id_doc = {
        "id": "doc_unrelated_random_999",
        "title": "Tài liệu thể thao phong trào",
        "text": "Đào tạo CNTT, IT, công nghệ thông tin tại câu lạc bộ 7480201",
        "aliases": ["cntt", "it", "7480201", "công nghệ thông tin"],
    }

    metrics = calculate_retrieval_case_metrics(
        [wrong_id_doc],
        expected_ids,
        k_list=[1, 3],
        expected_patterns=["cntt", "công nghệ thông tin"]
    )

    assert metrics["hit@1"] == 0.0
    assert metrics["recall@1"] == 0.0
    assert metrics["precision@1"] == 0.0
    assert metrics["reciprocal_rank"] == 0.0
    assert metrics["first_hit_rank"] is None
    assert metrics["relevant_count"] == 0


def test_regression_blocker1_correct_id_multiple_aliases_counts_once():
    """Regression Test 1.2:
    Đúng ID nhưng có nhiều alias → chỉ tính là MỘT tài liệu duy nhất trong tử số và mẫu số.
    """
    expected_ids = ["doc_major_cntt_7480201"]
    doc_cntt = {
        "id": "doc_major_cntt_7480201",
        "title": "Ngành Công nghệ thông tin",
        "aliases": ["cntt", "it", "7480201", "công nghệ thông tin", "ngành cntt"],
    }

    metrics = calculate_retrieval_case_metrics([doc_cntt], expected_ids, k_list=[1, 3])
    assert metrics["expected_count"] == 1
    assert metrics["relevant_count"] == 1
    assert metrics["recall@1"] == 1.0
    assert metrics["precision@1"] == 1.0
    assert metrics["reciprocal_rank"] == 1.0


def test_regression_blocker1_same_topic_different_year_not_matched():
    """Regression Test 1.3:
    Cùng chủ đề (học phí, điểm chuẩn) nhưng khác năm/phương thức → KHÔNG tự nhận đúng.
    Không suy đoán canonical ID chỉ từ tên chủ đề.
    """
    expected_ids = ["doc_tuition_k26"]

    doc_tuition_2024 = {
        "id": "doc_tuition_2024",
        "title": "Học phí HUIT năm 2024: Thông báo chính thức",
        "text": "Mức học phí năm 2024 là 12 triệu đồng/học kỳ",
        "source_url": "https://ts.huit.edu.vn/hoc-phi-2024",
    }

    extracted_id = get_document_id(doc_tuition_2024)
    assert extracted_id != "doc_tuition_k26"
    assert extracted_id == "doc_tuition_2024"

    metrics = calculate_retrieval_case_metrics([doc_tuition_2024], expected_ids, k_list=[1, 3])
    assert metrics["hit@1"] == 0.0
    assert metrics["recall@1"] == 0.0
    assert metrics["precision@1"] == 0.0
    assert metrics["reciprocal_rank"] == 0.0

    case_context = {
        "expected_relevant_doc_ids": expected_ids,
        "category": "tuition",
        "is_out_of_domain": False
    }
    err_type, _ = classify_retrieval_error([doc_tuition_2024], case_context)
    assert err_type == "wrong_topic" or err_type == "wrong_context"
    assert err_type != "success"


def test_regression_blocker1_duplicates_and_missing_id_do_not_inflate_score():
    """Regression Test 1.4:
    Tài liệu trùng lặp hoặc thiếu ID không nâng điểm.
    """
    expected_ids = ["doc_major_cntt_7480201"]
    doc_cntt = {
        "id": "doc_major_cntt_7480201",
        "title": "CNTT HUIT",
    }
    doc_no_id = {
        "title": "Tài liệu không có bất kỳ ID nào",
        "text": "Thông tin chung không định danh",
    }

    assert get_document_id(doc_no_id) is None

    docs = [doc_cntt, doc_cntt, doc_no_id]
    metrics = calculate_retrieval_case_metrics(docs, expected_ids, k_list=[1, 2, 3])

    assert metrics["recall@3"] == 1.0
    assert metrics["precision@3"] == round(1.0 / 3.0, 4)
    assert metrics["relevant_count"] == 1


# =============================================================================
# BLOCKER 2 REGRESSION TESTS: Ràng buộc Annotation với Nguồn & Bỏ Heuristic
# =============================================================================

def test_regression_keep_answer_change_source_id_not_supported():
    """Regression Test 2.1:
    Giữ nguyên câu trả lời, nhưng thay source ID bằng tài liệu khác → KHÔNG supported.
    """
    case = {
        "id": "ret_01",
        "category": "clear_intent",
        "expected_behavior": "retrieve_relevant_docs",
        "is_out_of_domain": False,
        "requires_human_review": False,
    }
    # Thay doc_major_cntt_7480201 bằng doc_tuition_k26
    wrong_source = [{
        "id": "doc_tuition_k26",
        "title": "Học phí HUIT",
        "text": "14 - 16 triệu đồng/học kỳ",
    }]
    ans = "Mã ngành Công nghệ thông tin của HUIT là 7480201 [1]."

    res = evaluate_answer_faithfulness(ans, wrong_source, case)
    assert res["citation_validity"] == "valid"
    # Sai ID nguồn so với annotation -> BẮT BUỘC unverified
    assert res["evidence_support"] == "unverified"
    assert res["decoupling_type"] == "unverified_needs_review"
    assert res["decoupling_type"] != "type_a_full_success"


def test_regression_keep_id_change_source_content_not_reused():
    """Regression Test 2.2:
    Giữ nguyên ID nhưng thay đổi nội dung nguồn → annotation cũ không được tự động sử dụng lại.
    """
    case = {
        "id": "ret_01",
        "category": "clear_intent",
        "expected_behavior": "retrieve_relevant_docs",
        "is_out_of_domain": False,
        "requires_human_review": False,
    }
    # Giữ ID doc_major_cntt_7480201 nhưng thay đổi text thành nội dung khác
    tampered_source = [{
        "id": "doc_major_cntt_7480201",
        "title": "Ngành Công nghệ thông tin",
        "text": "Nội dung đã bị sửa đổi: Trường HUIT không đào tạo CNTT từ năm 2026.",
    }]
    ans = "Mã ngành Công nghệ thông tin của HUIT là 7480201 [1]."

    res = evaluate_answer_faithfulness(ans, tampered_source, case)
    assert res["citation_validity"] == "valid"
    # Fingerprint nội dung bị lệch -> annotation cũ không được dùng lại -> unverified
    assert res["evidence_support"] == "unverified"
    assert res["decoupling_type"] == "unverified_needs_review"


def test_regression_swap_source_order_misaligns_citation_not_approved():
    """Regression Test 2.3:
    Đổi thứ tự nguồn khiến citation [1] trỏ sai nguồn → không được duyệt.
    """
    corpus_docs, _ = load_fixture_corpus()
    doc_cntt = next(d for d in corpus_docs if d["id"] == "doc_major_cntt_7480201")
    doc_tuition = next(d for d in corpus_docs if d["id"] == "doc_tuition_k26")

    case = {
        "id": "ret_01",
        "category": "clear_intent",
        "expected_behavior": "retrieve_relevant_docs",
        "is_out_of_domain": False,
        "requires_human_review": False,
    }
    # Đổi thứ tự: nguồn 1 là học phí, nguồn 2 là CNTT
    # Trong khi câu trả lời trích dẫn [1] (đang trỏ vào học phí thay vì CNTT)
    swapped_sources = [doc_tuition, doc_cntt]
    ans = "Mã ngành Công nghệ thông tin của HUIT là 7480201 [1]."

    res = evaluate_answer_faithfulness(ans, swapped_sources, case)
    assert res["citation_validity"] == "valid"
    # Citation [1] trỏ sai nguồn tại vị trí 1 -> BẮT BUỘC unverified
    assert res["evidence_support"] == "unverified"
    assert res["decoupling_type"] == "unverified_needs_review"


def test_regression_annotation_missing_pending_or_wrong_version():
    """Regression Test 2.4:
    Annotation thiếu, pending, sai phiên bản hoặc nguồn thiếu ID → chưa xác minh (unverified).
    """
    case = {
        "id": "ret_pending_clarify",
        "category": "missing_info",
        "expected_behavior": "clarify",
        "is_out_of_domain": False,
        "requires_human_review": True,
    }
    sources = [{"id": "doc_tuition_k26", "title": "Học phí", "text": "Học phí HUIT"}]

    # Case A: Không có annotation
    res_no_ann = evaluate_answer_faithfulness(
        "Vui lòng cung cấp ngành học để biết học phí chi tiết [1].", sources, case, annotations_map={}
    )
    assert res_no_ann["evidence_support"] == "unverified"
    assert res_no_ann["decoupling_type"] == "unverified_needs_review"

    # Case B: Annotation ở trạng thái pending
    ans_text = "Vui lòng cung cấp ngành học [1]."
    a_hash = compute_answer_hash(ans_text)
    pending_map = {
        f"ret_pending_clarify::1.1.0-standardized-fixture::{a_hash}": {
            "case_id": "ret_pending_clarify",
            "source_version": "1.1.0-standardized-fixture",
            "answer_hash": a_hash,
            "source_ids": ["doc_tuition_k26"],
            "source_fingerprints": [compute_source_fingerprint(sources[0])],
            "status": "pending",
            "verdict": "supported",
        }
    }
    res_pending = evaluate_answer_faithfulness(ans_text, sources, case, annotations_map=pending_map)
    assert res_pending["evidence_support"] == "unverified"
    assert res_pending["decoupling_type"] == "unverified_needs_review"

    # Case C: Nguồn thiếu ID hoàn toàn
    source_no_id = [{"title": "Tài liệu", "text": "Không có id"}]
    res_no_id = evaluate_answer_faithfulness(ans_text, source_no_id, case, annotations_map=pending_map)
    assert res_no_id["evidence_support"] == "unverified"
    assert res_no_id["decoupling_type"] == "unverified_needs_review"


def test_regression_pending_case_with_clarify_keywords_not_full_success():
    """Regression Test 2.5:
    Case pending có từ khóa làm rõ ('vui lòng cung cấp') hoặc từ chối nhưng không có annotation
    → TUYỆT ĐỐI KHÔNG tự nhận full_success hay supported.
    """
    case = {
        "id": "ret_09",
        "category": "missing_info",
        "expected_behavior": "clarify",
        "is_out_of_domain": False,
        "requires_human_review": True,
    }
    sources = [{"id": "doc_tuition_k26", "title": "Học phí", "text": "Học phí"}]

    ans_clarify = "Vui lòng cung cấp cụ thể ngành đào tạo và phương thức bạn quan tâm [1]."

    res = evaluate_answer_faithfulness(ans_clarify, sources, case, annotations_map={})
    assert res["has_clarification_prompt"] is True
    # Từ khóa chỉ là tín hiệu quan sát; không có annotation approved -> BẮT BUỘC unverified
    assert res["evidence_support"] == "unverified"
    assert res["decoupling_type"] == "unverified_needs_review"
    assert res["decoupling_type"] != "type_a_full_success"


def test_regression_approved_annotation_exact_match_returns_verdict():
    """Regression Test 2.6:
    Annotation approved khớp đầy đủ case, answer_hash, source_ids, source_fingerprints
    → trả đúng verdict của annotation.
    """
    corpus_docs, _ = load_fixture_corpus()
    doc_cntt = next(d for d in corpus_docs if d["id"] == "doc_major_cntt_7480201")

    case = {
        "id": "ret_01",
        "category": "clear_intent",
        "expected_behavior": "retrieve_relevant_docs",
        "is_out_of_domain": False,
        "requires_human_review": False,
    }
    ans = "Mã ngành Công nghệ thông tin của HUIT là 7480201 [1]."

    # Nạp đúng fixture và truyền đúng nguồn từ fixture
    res = evaluate_answer_faithfulness(ans, [doc_cntt], case)
    assert res["citation_validity"] == "valid"
    assert res["evidence_support"] == "supported"
    assert res["decoupling_type"] == "type_a_full_success"


def test_regression_unsupported_assertion_with_valid_citation():
    """Regression Test 2.7:
    Khẳng định không được nguồn hỗ trợ nhưng có [1] và đủ dài → không supported/full_success.
    """
    case = {
        "id": "ret_02",
        "category": "clear_intent",
        "expected_behavior": "retrieve_relevant_docs",
        "is_out_of_domain": False,
        "requires_human_review": False,
    }
    sources = [{
        "id": "doc_tuition_k26",
        "title": "Học phí HUIT",
        "text": "14 - 16 triệu đồng/học kỳ",
    }]
    ans_unsupported = (
        "Theo tài liệu công bố chính thức số 1 [1], mức học phí của toàn bộ sinh viên HUIT "
        "được tài trợ 100% miễn phí hoàn toàn không phải đóng bất kỳ khoản tiền nào."
    )

    res = evaluate_answer_faithfulness(ans_unsupported, sources, case, annotations_map={})
    assert res["citation_validity"] == "valid"
    assert res["evidence_support"] == "unverified"
    assert res["decoupling_type"] == "unverified_needs_review"


def test_regression_nonexistent_citation_marker_invalid():
    """Regression Test 2.8:
    Citation không tồn tại [5] khi chỉ có 1 nguồn → invalid citation và contradicted.
    """
    case = {
        "id": "ret_02",
        "category": "clear_intent",
        "expected_behavior": "retrieve_relevant_docs",
        "is_out_of_domain": False,
        "requires_human_review": False,
    }
    sources = [{"id": "doc_tuition_k26", "title": "Học phí HUIT", "text": "14 - 16 triệu."}]
    ans_invalid_cite = "Mức học phí là 14 - 16 triệu đồng theo tài liệu [5]."

    res = evaluate_answer_faithfulness(ans_invalid_cite, sources, case)
    assert res["citation_validity"] == "invalid_citation"
    assert res["citation_faithfulness"] is False
    assert res["evidence_support"] == "contradicted"
    assert res["decoupling_type"] == "type_b_generation_failure"


def test_is_valid_source_version_contract():
    """Kiểm tra hợp đồng của hàm is_valid_source_version:
    - Bắt buộc là str, không chấp nhận None, int, float, list, dict.
    - Không chấp nhận chuỗi rỗng hoặc chỉ chứa khoảng trắng.
    """
    assert is_valid_source_version("1.1.0-standardized-fixture") is True
    assert is_valid_source_version("v1.0") is True
    assert is_valid_source_version("  v2.0-beta  ") is True

    # Giá trị không hợp lệ
    assert is_valid_source_version("") is False
    assert is_valid_source_version("   ") is False
    assert is_valid_source_version("\t\n") is False
    assert is_valid_source_version(None) is False
    assert is_valid_source_version(123) is False
    assert is_valid_source_version(1.1) is False
    assert is_valid_source_version([]) is False
    assert is_valid_source_version({}) is False
    assert is_valid_source_version(True) is False


def test_regression_source_version_empty_on_input_and_annotation():
    """Regression Test 2.9 (Tái hiện lỗi người dùng):
    Khi source_version="" và annotation approved cũng có source_version="",
    evaluate_answer_faithfulness TUYỆT ĐỐI KHÔNG trả supported/type_a_full_success.
    Phiên bản rỗng không được coi là bằng chứng xác minh hợp lệ.
    Hai giá trị không hợp lệ giống nhau không được coi là khớp.
    """
    corpus_docs, _ = load_fixture_corpus()
    doc_cntt = next(d for d in corpus_docs if d["id"] == "doc_major_cntt_7480201")

    case = {
        "id": "ret_01",
        "category": "clear_intent",
        "expected_behavior": "retrieve_relevant_docs",
        "is_out_of_domain": False,
        "requires_human_review": False,
    }
    ans = "Mã ngành Công nghệ thông tin của HUIT là 7480201 [1]."
    a_hash = compute_answer_hash(ans)
    fp = compute_source_fingerprint(doc_cntt)

    # Annotation có source_version=""
    empty_ver_ann = {
        "case_id": "ret_01",
        "source_version": "",
        "answer_hash": a_hash,
        "source_ids": ["doc_major_cntt_7480201"],
        "source_fingerprints": [fp],
        "status": "approved",
        "verdict": "supported",
    }

    # Test qua annotations_map truyền trực tiếp dạng dict
    direct_dict_map = {f"ret_01::::{a_hash}": [empty_ver_ann]}
    res_dict = evaluate_answer_faithfulness(
        ans, [doc_cntt], case, source_version="", annotations_map=direct_dict_map
    )
    assert res_dict["evidence_support"] == "unverified"
    assert res_dict["decoupling_type"] == "unverified_needs_review"
    assert res_dict["decoupling_type"] != "type_a_full_success"

    # Test qua annotations_map truyền trực tiếp dạng list
    res_list = evaluate_answer_faithfulness(
        ans, [doc_cntt], case, source_version="", annotations_map=[empty_ver_ann]
    )
    assert res_list["evidence_support"] == "unverified"
    assert res_list["decoupling_type"] == "unverified_needs_review"
    assert res_list["decoupling_type"] != "type_a_full_success"


def test_regression_source_version_whitespace_only():
    """Regression Test 2.10:
    source_version chỉ chứa khoảng trắng ở đầu vào hoặc annotation
    → đều trả unverified và unverified_needs_review.
    """
    corpus_docs, _ = load_fixture_corpus()
    doc_cntt = next(d for d in corpus_docs if d["id"] == "doc_major_cntt_7480201")

    case = {
        "id": "ret_01",
        "category": "clear_intent",
        "expected_behavior": "retrieve_relevant_docs",
        "is_out_of_domain": False,
        "requires_human_review": False,
    }
    ans = "Mã ngành Công nghệ thông tin của HUIT là 7480201 [1]."
    a_hash = compute_answer_hash(ans)
    fp = compute_source_fingerprint(doc_cntt)

    # 1. Cả input và annotation đều là khoảng trắng
    ws_ann = {
        "case_id": "ret_01",
        "source_version": "   ",
        "answer_hash": a_hash,
        "source_ids": ["doc_major_cntt_7480201"],
        "source_fingerprints": [fp],
        "status": "approved",
        "verdict": "supported",
    }
    ws_map = {f"ret_01::   ::{a_hash}": [ws_ann]}
    res_ws_both = evaluate_answer_faithfulness(
        ans, [doc_cntt], case, source_version="   ", annotations_map=ws_map
    )
    assert res_ws_both["evidence_support"] == "unverified"
    assert res_ws_both["decoupling_type"] == "unverified_needs_review"

    # 2. Input hợp lệ nhưng annotation là khoảng trắng
    valid_key_ws_ann_map = {
        f"ret_01::1.1.0-standardized-fixture::{a_hash}": [ws_ann]
    }
    res_ann_ws = evaluate_answer_faithfulness(
        ans,
        [doc_cntt],
        case,
        source_version="1.1.0-standardized-fixture",
        annotations_map=valid_key_ws_ann_map,
    )
    assert res_ann_ws["evidence_support"] == "unverified"
    assert res_ann_ws["decoupling_type"] == "unverified_needs_review"


def test_regression_source_version_none_missing_or_wrong_type():
    """Regression Test 2.11:
    source_version là None, thiếu hoặc sai kiểu (int, dict, list)
    ở input hoặc annotation → unverified và unverified_needs_review.
    """
    corpus_docs, _ = load_fixture_corpus()
    doc_cntt = next(d for d in corpus_docs if d["id"] == "doc_major_cntt_7480201")

    case = {
        "id": "ret_01",
        "category": "clear_intent",
        "expected_behavior": "retrieve_relevant_docs",
        "is_out_of_domain": False,
        "requires_human_review": False,
    }
    ans = "Mã ngành Công nghệ thông tin của HUIT là 7480201 [1]."
    a_hash = compute_answer_hash(ans)
    fp = compute_source_fingerprint(doc_cntt)

    # 1. Input sai kiểu (None, int, dict)
    for bad_input_ver in [None, 123, {"version": "1.0"}, ["1.0"]]:
        res_bad_input = evaluate_answer_faithfulness(
            ans, [doc_cntt], case, source_version=bad_input_ver, annotations_map={}
        )
        assert res_bad_input["evidence_support"] == "unverified"
        assert res_bad_input["decoupling_type"] == "unverified_needs_review"

    # 2. Annotation thiếu hoặc có source_version không hợp lệ (None, int)
    bad_annotations = [
        # Thiếu trường source_version
        {
            "case_id": "ret_01",
            "answer_hash": a_hash,
            "source_ids": ["doc_major_cntt_7480201"],
            "source_fingerprints": [fp],
            "status": "approved",
            "verdict": "supported",
        },
        # source_version là None
        {
            "case_id": "ret_01",
            "source_version": None,
            "answer_hash": a_hash,
            "source_ids": ["doc_major_cntt_7480201"],
            "source_fingerprints": [fp],
            "status": "approved",
            "verdict": "supported",
        },
        # source_version là int
        {
            "case_id": "ret_01",
            "source_version": 123,
            "answer_hash": a_hash,
            "source_ids": ["doc_major_cntt_7480201"],
            "source_fingerprints": [fp],
            "status": "approved",
            "verdict": "supported",
        },
    ]

    for bad_ann in bad_annotations:
        bad_map = {f"ret_01::1.1.0-standardized-fixture::{a_hash}": [bad_ann]}
        res_bad_ann = evaluate_answer_faithfulness(
            ans,
            [doc_cntt],
            case,
            source_version="1.1.0-standardized-fixture",
            annotations_map=bad_map,
        )
        assert res_bad_ann["evidence_support"] == "unverified"
        assert res_bad_ann["decoupling_type"] == "unverified_needs_review"


def test_regression_load_answer_annotations_skips_invalid_source_versions(tmp_path: Path):
    """Regression Test 2.12:
    load_answer_annotations phải bỏ qua mọi annotation có source_version không hợp lệ.
    Tuyệt đối không tự điền phiên bản để biến annotation thiếu dữ liệu thành hợp lệ.
    """
    test_data = [
        {
            "case_id": "case_empty",
            "answer_hash": "hash_empty",
            "source_version": "",
            "status": "approved",
        },
        {
            "case_id": "case_whitespace",
            "answer_hash": "hash_ws",
            "source_version": "   ",
            "status": "approved",
        },
        {
            "case_id": "case_none",
            "answer_hash": "hash_none",
            "source_version": None,
            "status": "approved",
        },
        {
            "case_id": "case_missing",
            "answer_hash": "hash_missing",
            "status": "approved",
        },
        {
            "case_id": "case_int",
            "answer_hash": "hash_int",
            "source_version": 123,
            "status": "approved",
        },
        {
            "case_id": "case_list",
            "answer_hash": "hash_list",
            "source_version": ["1.0"],
            "status": "approved",
        },
        {
            "case_id": "case_valid",
            "answer_hash": "hash_valid",
            "source_version": "1.1.0-standardized-fixture",
            "status": "approved",
        },
    ]

    fixture_file = tmp_path / "test_annotations.json"
    with open(fixture_file, "w", encoding="utf-8") as f:
        json.dump(test_data, f)

    loaded_map = load_answer_annotations(fixture_file)

    # Chỉ duy nhất case_valid có source_version hợp lệ được nạp
    assert len(loaded_map) == 1
    expected_key = "case_valid::1.1.0-standardized-fixture::hash_valid"
    assert expected_key in loaded_map
    assert loaded_map[expected_key][0]["case_id"] == "case_valid"

    # Mọi trường hợp rỗng, khoảng trắng, None, missing, int, list đều bị bỏ qua
    assert not any("case_empty" in k for k in loaded_map)
    assert not any("case_whitespace" in k for k in loaded_map)
    assert not any("case_none" in k for k in loaded_map)
    assert not any("case_missing" in k for k in loaded_map)
    assert not any("case_int" in k for k in loaded_map)
    assert not any("case_list" in k for k in loaded_map)


def test_regression_valid_source_version_matching_approved_annotation_returns_verdict():
    """Regression Test 2.13:
    Khi source_version hợp lệ, case_id, answer_hash, nguồn và fingerprint khớp đầy đủ
    → evaluate_answer_faithfulness trả đúng verdict và decoupling_type.
    """
    corpus_docs, _ = load_fixture_corpus()
    doc_cntt = next(d for d in corpus_docs if d["id"] == "doc_major_cntt_7480201")

    case = {
        "id": "ret_01",
        "category": "clear_intent",
        "expected_behavior": "retrieve_relevant_docs",
        "is_out_of_domain": False,
        "requires_human_review": False,
    }
    ans = "Mã ngành Công nghệ thông tin của HUIT là 7480201 [1]."
    a_hash = compute_answer_hash(ans)
    fp = compute_source_fingerprint(doc_cntt)

    # 1. Kiểm tra với phiên bản mặc định của fixture
    res_default = evaluate_answer_faithfulness(ans, [doc_cntt], case)
    assert res_default["citation_validity"] == "valid"
    assert res_default["evidence_support"] == "supported"
    assert res_default["decoupling_type"] == "type_a_full_success"

    # 2. Kiểm tra với phiên bản tùy biến hợp lệ (truyền cả input và annotations_map)
    custom_ver = "2.5.0-release-audit"
    custom_ann = {
        "case_id": "ret_01",
        "source_version": custom_ver,
        "answer_hash": a_hash,
        "source_ids": ["doc_major_cntt_7480201"],
        "source_fingerprints": [fp],
        "status": "approved",
        "verdict": "supported",
    }
    custom_map = {f"ret_01::{custom_ver}::{a_hash}": [custom_ann]}
    res_custom = evaluate_answer_faithfulness(
        ans, [doc_cntt], case, source_version=custom_ver, annotations_map=custom_map
    )
    assert res_custom["citation_validity"] == "valid"
    assert res_custom["evidence_support"] == "supported"
    assert res_custom["decoupling_type"] == "type_a_full_success"


# =============================================================================
# BLOCKER 3 REGRESSION TESTS: Không chọn bottleneck production từ sleep giả lập
# =============================================================================

def test_regression_blocker3_changing_sleep_does_not_create_production_priority():
    """Regression Test 3.1:
    Đổi thời gian sleep không tạo ưu tiên tối ưu production.
    Dữ liệu simulated tuyệt đối không sinh đề xuất đổi model TTFT, prompt hay index.
    """
    ret_summary = {"pending_human_review_cases": 0, "error_distribution": {}}
    gen_summary = {"decoupling_matrix_counts": {}}

    lat_summary_sleep_10s = {
        "provenance": "simulated",
        "bottleneck_ranking": [
            {"rank": 1, "component": "llm_ttft (Thời gian chờ mô hình phản hồi)", "avg_duration_ms": 10000.0},
            {"rank": 2, "component": "vector_search", "avg_duration_ms": 5000.0},
        ],
        "jev_shadow_comparison": {"overhead_ms": 400.0},
    }

    recs_10s = generate_evidence_based_recommendations(ret_summary, gen_summary, lat_summary_sleep_10s)
    assert not any("llm_ttft" in str(r.get("evidence", "")).lower() for r in recs_10s)
    assert not any("tối ưu hóa thời gian chờ llm" in str(r.get("title", "")).lower() for r in recs_10s)

    lat_summary_sleep_keyword = {
        "provenance": "simulated",
        "bottleneck_ranking": [
            {"rank": 1, "component": "keyword_search", "avg_duration_ms": 20000.0},
            {"rank": 2, "component": "llm_ttft", "avg_duration_ms": 10.0},
        ],
    }
    recs_kw = generate_evidence_based_recommendations(ret_summary, gen_summary, lat_summary_sleep_keyword)
    assert not any("keyword_search" in str(r.get("evidence", "")).lower() for r in recs_kw)


def test_regression_blocker3_missing_provenance_not_treated_as_real_measurement():
    """Regression Test 3.2:
    Thiếu provenance hoặc provenance không hợp lệ → không được coi là số đo thực tế.
    """
    ret_summary = {"pending_human_review_cases": 0}
    gen_summary = {}

    lat_no_prov = {
        "bottleneck_ranking": [{"rank": 1, "component": "llm_ttft", "avg_duration_ms": 3500.0}],
    }
    recs_no_prov = generate_evidence_based_recommendations(ret_summary, gen_summary, lat_no_prov)
    assert len(recs_no_prov) == 0

    lat_unknown = {
        "provenance": "unknown",
        "bottleneck_ranking": [{"rank": 1, "component": "llm_ttft", "avg_duration_ms": 3500.0}],
    }
    recs_unk = generate_evidence_based_recommendations(ret_summary, gen_summary, lat_unknown)
    assert len(recs_unk) == 0


def test_regression_blocker3_simulated_report_contains_no_production_performance_claims(tmp_path):
    """Regression Test 3.3:
    Báo cáo simulated không chứa kết luận hiệu năng production.
    """
    ret_summary = {
        "mrr": 0.85,
        "recall_at_1": 0.8,
        "recall_at_3": 0.9,
        "precision_at_1": 0.8,
        "precision_at_3": 0.3,
        "total_cases": 10,
        "accepted_ground_truth_cases": 8,
        "pending_human_review_cases": 2,
        "error_distribution": {"success": 8, "wrong_topic": 2},
    }
    gen_summary = {
        "sample_count": 5,
        "e2e_ttft_percentiles_ms": {"avg": 120.0, "p50": 115.0, "p95": 130.0},
        "llm_ttft_percentiles_ms": {"avg": 65.0, "p50": 65.0, "p95": 70.0},
        "total_latency_percentiles_ms": {"avg": 200.0},
        "decoupling_matrix_counts": {"type_a_full_success": 4, "unverified_needs_review": 1},
    }
    lat_summary = {
        "provenance": "simulated",
        "is_live_measurement": False,
        "cache_miss_breakdown": {
            k: {"p50": 10.0, "p90": 15.0, "p95": 20.0, "avg": 12.0}
            for k in ["cache_lookup", "embedding", "vector_search", "keyword_search", "rerank", "jev_evidence", "llm_ttft", "e2e_content_ttft", "llm_generation", "total"]
        },
        "cache_hit_ttft": {"p50": 5.0, "avg": 5.0},
        "jev_shadow_comparison": {"overhead_ms": 40.0},
        "bottleneck_ranking": [{"rank": 1, "component": "llm_ttft", "avg_duration_ms": 65.0}],
    }

    json_path, md_path = generate_baseline_report(
        ret_summary, gen_summary, lat_summary, "dummy_hash_sha256", tmp_path
    )

    with open(md_path, "r", encoding="utf-8") as f:
        md_text = f.read()

    assert "PROVENANCE: SIMULATED" in md_text
    assert "CHƯA ĐỦ BẰNG CHỨNG để chọn bottleneck thực tế trong Production" in md_text
    assert "Tối ưu hóa thời gian chờ LLM First Token" not in md_text


# =============================================================================
# CÁC BÀI TEST BẢO TOÀN VÀ KIỂM CHỨNG LIÊN QUAN
# =============================================================================

def test_regression_retrieval_error_handling():
    """Kiểm tra retrieval error tính 0.0, không bị loại bỏ khỏi mẫu số."""
    case_good = {
        "id": "ret_01",
        "query": "CNTT",
        "expected_relevant_doc_ids": ["doc_major_cntt_7480201"],
        "category": "clear_intent",
        "is_out_of_domain": False,
        "requires_human_review": False,
    }
    case_bad = {
        "id": "ret_02",
        "query": "Học phí",
        "expected_relevant_doc_ids": ["doc_tuition_k26"],
        "category": "clear_intent",
        "is_out_of_domain": False,
        "requires_human_review": False,
    }

    mock_retriever = MagicMock()
    good_doc = {"id": "doc_major_cntt_7480201", "title": "CNTT"}
    mock_retriever.retrieve.side_effect = [
        [good_doc],
        TimeoutError("Connection to database timed out after 5000ms"),
    ]

    summary = run_retrieval_benchmark_offline([case_good, case_bad], mock_retriever, top_k=3)
    assert summary["error_distribution"]["timeout_or_error"] == 1
    assert summary["accepted_ground_truth_cases"] == 2
    assert summary["mrr"] == 0.5
    assert summary["recall@1"] == 0.5


def test_regression_empty_tokens_and_cache_miss_handling():
    """Kiểm tra calculate_latency_percentiles trên danh sách toàn None trả về no_data."""
    p = calculate_latency_percentiles([None, None, None])
    assert p["status"] == "no_data"
    assert p["count"] == 0
    assert p["missing_count"] == 3
    assert p["min"] is None
    assert p["p50"] is None

    p_mixed = calculate_latency_percentiles([50.0, None, 150.0])
    assert p_mixed["status"] == "ok"
    assert p_mixed["count"] == 2
    assert p_mixed["missing_count"] == 1
    assert p_mixed["p50"] == 100.0


def test_regression_span_isolation_llm_ttft():
    """Kiểm tra cô lập span llm_ttft và e2e_content_ttft."""
    timings = LatencyBreakdown(request_id="test-span-isolation", provenance="simulated")
    timings.start_span("retrieval")
    timings.record_metric("retrieval", 500.0)
    timings.start_span("jev_evidence")
    timings.record_metric("jev_evidence", 300.0)
    timings.record_metric("llm_ttft", 120.0)
    timings.record_metric("e2e_content_ttft", 920.0)

    strict_dict = timings.to_dict(strict_measured=True)
    assert strict_dict["llm_ttft"] == 120.0
    assert strict_dict["e2e_content_ttft"] == 920.0
    assert strict_dict["llm_ttft"] < strict_dict["e2e_content_ttft"]
    assert strict_dict["provenance"] == "simulated"
    assert strict_dict["cache_write"] is None


def test_regression_offline_replay_no_network_no_db():
    """Kiểm tra chạy replay hoàn toàn không gọi MongoClient hay kết nối mạng."""
    corpus_docs, corpus_hash = load_fixture_corpus()
    assert len(corpus_docs) >= 15
    assert len(corpus_hash) == 64

    retriever = InMemoryFixtureRetriever(corpus_docs)
    pipeline = InMemoryReplayPipeline(retriever)

    with patch("pymongo.MongoClient") as mock_mongo_client:
        res_obj, timings, tokens = pipeline.run_single_pipeline("Học phí HUIT là bao nhiêu?", use_cache=True)
        assert mock_mongo_client.called is False
        assert len(tokens) > 0
        assert "học phí" in res_obj["answer"].lower()
        assert timings.to_dict()["provenance"] == "simulated"


def test_regression_deterministic_replay_quality():
    """Chạy benchmark 2 lần trên cùng fixture cho kết quả giống hệt nhau deterministically."""
    corpus_docs, _ = load_fixture_corpus()
    retriever_1 = InMemoryFixtureRetriever(corpus_docs)
    retriever_2 = InMemoryFixtureRetriever(corpus_docs)
    cases_sample = RAG_BENCHMARK_DATASET[:10]

    sum_1 = run_retrieval_benchmark_offline(cases_sample, retriever_1, top_k=3)
    sum_2 = run_retrieval_benchmark_offline(cases_sample, retriever_2, top_k=3)

    assert sum_1["mrr"] == sum_2["mrr"]
    assert sum_1["recall@1"] == sum_2["recall@1"]
    assert sum_1["recall@3"] == sum_2["recall@3"]
    assert sum_1["precision@1"] == sum_2["precision@1"]
    assert sum_1["error_distribution"] == sum_2["error_distribution"]


def test_real_measurements_generate_recommendations():
    """Kiểm tra khi CÓ số đo thực tế (provenance='recorded_validated' hoặc 'live'), hệ thống mới sinh khuyến nghị."""
    ret_summary = {"pending_human_review_cases": 0, "error_distribution": {}}
    gen_summary = {"decoupling_matrix_counts": {}}
    lat_summary_live = {
        "provenance": "recorded_validated",
        "bottleneck_ranking": [
            {"rank": 1, "component": "llm_ttft (Thời gian chờ mô hình phản hồi)", "avg_duration_ms": 3250.5},
            {"rank": 2, "component": "jev_evidence (Shadow evaluation)", "avg_duration_ms": 420.0},
        ],
        "jev_shadow_comparison": {"overhead_ms": 410.0},
    }

    recs = generate_evidence_based_recommendations(ret_summary, gen_summary, lat_summary_live)
    assert len(recs) >= 1
    assert recs[0]["priority"] == 1
    assert "3250.5ms" in recs[0]["evidence"]
    assert "recorded_validated" in recs[0]["evidence"]


def test_sanitize_report_data():
    """Kiểm tra loại bỏ toàn bộ secret, connection string, password khỏi báo cáo."""
    raw = {
        "api_key": "dummy_secret_123456",
        "MONGODB_URI": "mongodb+srv://dummy_user:dummy_pass@cluster0.hyj8rab.mongodb.net",
        "normal_field": "HUIT Baseline",
        "nested": {
            "auth_token": "dummy_bearer_token",
            "score": 0.95,
        }
    }
    clean = sanitize_report_data(raw)
    assert clean["api_key"] == "[REDACTED]"
    assert clean["MONGODB_URI"] == "[REDACTED_URI]"
    assert clean["normal_field"] == "HUIT Baseline"
    assert clean["nested"]["auth_token"] == "[REDACTED]"
    assert clean["nested"]["score"] == 0.95
