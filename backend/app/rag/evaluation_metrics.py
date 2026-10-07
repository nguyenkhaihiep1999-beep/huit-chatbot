"""evaluation_metrics.py
Module tính toán metric chất lượng Retrieval, Đánh giá Câu trả lời và Phân tích Hiệu năng RAG.

Tiêu chuẩn chuẩn hóa:
1. Retrieval Metrics:
   - Metric chính thức chỉ dựa trên giao của tập ID tài liệu kỳ vọng và ID tài liệu được trả về.
   - Recall@k = (Số ID tài liệu liên quan DUY NHẤT tìm được trong top-k) / (Tổng số ID tài liệu liên quan kỳ vọng).
   - Precision@k = (Số ID tài liệu liên quan DUY NHẤT tìm được trong top-k) / k.
   - MRR = Nghịch đảo thứ hạng (1/rank) của ID tài liệu liên quan đầu tiên. Lỗi retrieval = 0.0, không bị loại bỏ.
   - Alias / từ khóa tuyệt đối không biến tài liệu sai ID thành true positive.
   - Không suy canonical ID từ tên chủ đề (như 'học phí' hay 'điểm chuẩn').
   - Tài liệu không xác định được ID phải báo thiếu dữ liệu (None).
   - Tài liệu trùng lặp không làm tăng điểm; giữ chính sách top-k và xử lý lỗi nhất quán.

2. Answer Faithfulness & Source Binding:
   - Citation validity chỉ kiểm tra tham chiếu nguồn tồn tại, không chứng minh nội dung đúng.
   - Áp dụng cùng cổng xác minh annotation cho mọi expected_behavior (clarify, refute_misinformation, out_of_domain, retrieve_relevant_docs).
   - Từ khóa làm rõ/từ chối chỉ là tín hiệu quan sát, không chứng minh câu trả lời đúng.
   - Ràng buộc annotation chặt chẽ với nguồn thực tế: đối chiếu ID nguồn và fingerprint nội dung nguồn.
   - Đổi thứ tự nguồn khiến citation trỏ sai hoặc thay đổi nội dung nguồn đều không được duyệt.
   - Không dùng flag/bypass để tự nhận supported; thiếu annotation hoặc sai lệch báo unverified / needs_review.

3. Latency & Bottlenecks:
   - Gắn provenance rõ ràng: 'simulated', 'recorded_validated', hoặc 'live'.
   - Span tạo bằng sleep mang nhãn simulated.
   - Dữ liệu simulated / unknown tuyệt đối không dùng để đề xuất đổi model, prompt, index hay kiến trúc Jev.
   - Không cố bổ sung cho đủ 3 đề xuất; chỉ sinh khi có số đo thực tế hợp lệ.
"""
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re
from typing import Any, Dict, List, Optional, Set, Tuple

# Đường dẫn mặc định đến file annotation fixture
DEFAULT_ANNOTATIONS_PATH = (
    Path(__file__).resolve().parent / "fixtures" / "answer_annotations.json"
)

# Ánh xạ URL chính thức đã được xác minh sang canonical doc ID
VERIFIED_EXACT_URL_MAP: Dict[str, str] = {
    "https://ts.huit.edu.vn/nganh-dh/nganh-cong-nghe-thong-tin": "doc_major_cntt_7480201",
    "https://ts.huit.edu.vn/47159/hoc-phi-huit-nam-2026-minh-bach-thong-tin-dong-hanh-cung-nguoi-hoc": "doc_tuition_k26",
    "https://ts.huit.edu.vn/thong-bao/diem-chuan-trung-tuyen-dai-hoc-chinh-quy-nam-2026": "doc_cutoff_2026",
    "https://ts.huit.edu.vn/nganh-dh/nganh-tri-tue-nhan-tao": "doc_major_ai_7480107",
    "https://ts.huit.edu.vn/thong-bao/diem-san-xet-tuyen-dai-hoc-nam-2026": "doc_floor_scores_2026",
    "https://ts.huit.edu.vn/nganh-dh/nganh-ky-thuat-co-dien-tu": "doc_major_mechatronics_7520114",
    "https://ts.huit.edu.vn/huong-dan/thu-tuc-nhap-hoc-k26": "doc_admission_procedure_k26",
    "https://ts.huit.edu.vn/chinh-sach/chinh-sach-hoc-bong-tuyen-sinh": "doc_scholarship_policies",
    "https://ts.huit.edu.vn/lien-he": "doc_contact_and_locations",
    "https://ts.huit.edu.vn/thong-bao/cac-phuong-thuc-tuyen-sinh-2026": "doc_admission_methods_2026",
}

# Ánh xạ mã ngành chuẩn 7 chữ số đã kiểm chứng
VERIFIED_MAJOR_CODE_MAP: Dict[str, str] = {
    "7480201": "doc_major_cntt_7480201",
    "7480107": "doc_major_ai_7480107",
    "7520114": "doc_major_mechatronics_7520114",
    "7540101": "doc_major_food_tech_7540101",
    "7340115": "doc_major_marketing_7340115",
    "7480202": "doc_major_infosec_7480202",
}


def compute_answer_hash(text: str) -> str:
    """Tạo mã băm SHA-256 (16 ký tự) cho nội dung câu trả lời đã chuẩn hóa khoảng trắng và chữ thường."""
    cleaned = re.sub(r"\s+", " ", (text or "").strip().lower())
    return hashlib.sha256(cleaned.encode("utf-8")).hexdigest()[:16]


def compute_source_fingerprint(doc: Dict[str, Any]) -> Optional[str]:
    """Tính fingerprint xác thực cho một tài liệu nguồn dựa trên ID và nội dung liên quan.

    Quy tắc chuẩn hóa:
    - Bắt buộc phải có doc_id hợp lệ (từ get_document_id); thiếu ID trả về None.
    - Chỉ gom doc_id, title và text nội dung.
    - Tuyệt đối KHÔNG đưa điểm số (score), thứ tự (index), latency hay metadata đo lường vào fingerprint.
    - Chuẩn hóa khoảng trắng và chữ thường để bảo toàn tính độc lập cấu trúc.
    """
    if not isinstance(doc, dict):
        return None
    d_id = get_document_id(doc)
    if not d_id:
        return None
    title = str(doc.get("title") or "").strip()
    text = str(doc.get("text") or "").strip()
    raw = f"{d_id}::{title}::{text}".strip().lower()
    cleaned = re.sub(r"\s+", " ", raw)
    return hashlib.sha256(cleaned.encode("utf-8")).hexdigest()[:16]


def is_valid_source_version(version: Any) -> bool:
    """Kiểm tra tính hợp lệ của phiên bản nguồn (source_version).

    Quy tắc:
    - Bắt buộc là chuỗi ký tự (str), không chấp nhận None hoặc sai kiểu dữ liệu khác.
    - Không được rỗng hoặc chỉ chứa khoảng trắng.
    """
    if not isinstance(version, str):
        return False
    return bool(version.strip())


def load_answer_annotations(
    filepath: Optional[Path] = None,
) -> Dict[str, List[Dict[str, Any]]]:
    """Nạp file fixture annotation câu trả lời cục bộ.

    Quy tắc chuẩn hóa:
    - Bỏ qua các annotation có source_version không hợp lệ (rỗng, chỉ khoảng trắng, None, sai kiểu).
    - Tuyệt đối không tự điền phiên bản mặc định để biến annotation thiếu dữ liệu thành hợp lệ.
    """
    path = filepath or DEFAULT_ANNOTATIONS_PATH
    if not path.exists():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        lookup: Dict[str, List[Dict[str, Any]]] = {}
        if isinstance(data, list):
            for item in data:
                if not isinstance(item, dict):
                    continue
                raw_ver = item.get("source_version")
                if not is_valid_source_version(raw_ver):
                    continue
                case_id = str(item.get("case_id", "")).strip()
                s_ver = str(raw_ver).strip()
                a_hash = str(item.get("answer_hash", "")).strip()
                if case_id and a_hash:
                    key = f"{case_id}::{s_ver}::{a_hash}"
                    lookup.setdefault(key, []).append(item)
        return lookup
    except Exception:
        return {}


def get_document_id(doc: Dict[str, Any]) -> Optional[str]:
    """Trích xuất ID tài liệu duy nhất và ổn định cho một document.

    Quy tắc chuẩn hóa:
    - Nhận ID tường minh từ ('id', '_id', 'doc_id', 'canonical_id').
    - Tuyệt đối không suy canonical ID từ tên chủ đề (ví dụ 'học phí', 'điểm chuẩn') hoặc từ khóa.
    - Cho phép ánh xạ có kiểm chứng dựa trên mã ngành cụ thể hoặc URL chính thức đã xác minh.
    - Tài liệu không xác định được ID phải trả về None để báo thiếu dữ liệu.
    """
    if not isinstance(doc, dict):
        return None

    for key in ("id", "_id", "doc_id", "canonical_id"):
        val = doc.get(key)
        if val is not None and str(val).strip():
            return str(val).strip()

    # Ánh xạ có kiểm chứng: theo mã ngành đào tạo chuẩn nếu có trường major_code rõ ràng
    major_code = doc.get("major_code")
    if major_code and str(major_code).strip() in VERIFIED_MAJOR_CODE_MAP:
        return VERIFIED_MAJOR_CODE_MAP[str(major_code).strip()]

    # Ánh xạ có kiểm chứng: theo URL chính thức đầy đủ (exact match)
    exact_url = str(doc.get("source_url") or doc.get("url") or "").strip().rstrip("/")
    if exact_url in VERIFIED_EXACT_URL_MAP:
        return VERIFIED_EXACT_URL_MAP[exact_url]

    # KHÔNG suy đoán từ tên chủ đề hay title/text chung chung -> Báo thiếu dữ liệu
    return None


def is_doc_relevant(doc: Dict[str, Any], patterns_or_ids: List[str]) -> bool:
    """Hàm phụ trợ kiểm tra nội dung/alias (KHÔNG dùng để tính Hit hay thay thế ID chính thức)."""
    if not patterns_or_ids or not doc:
        return False

    doc_id = get_document_id(doc)
    if doc_id and doc_id in patterns_or_ids:
        return True

    doc_content = " ".join([
        str(doc.get("title") or ""),
        str(doc.get("text") or ""),
        str(doc.get("source_url") or ""),
        str(doc.get("url") or ""),
        str(doc.get("page_title") or ""),
        str(doc.get("major_code") or ""),
        str(doc.get("category") or ""),
        " ".join(doc.get("aliases", []) if isinstance(doc.get("aliases"), list) else []),
    ]).lower()

    for p in patterns_or_ids:
        p_str = str(p).strip().lower()
        if p_str and p_str in doc_content:
            return True
    return False


def calculate_retrieval_case_metrics(
    docs: List[Dict[str, Any]],
    expected_doc_ids: List[str],
    k_list: Optional[List[int]] = None,
    expected_patterns: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Tính Recall@k, Precision@k, Hit@k và Reciprocal Rank cho một tình huống.

    Quy tắc chuẩn hóa:
    - Metric chính thức CHỈ dựa trên giao của tập ID tài liệu kỳ vọng và ID tài liệu được trả về.
    - Alias/từ khóa tuyệt đối không biến tài liệu sai ID thành true positive.
    - Mẫu số Recall@k = Số ID tài liệu liên quan DUY NHẤT kỳ vọng (len(set(expected_doc_ids))).
    - Tử số Recall@k = Số ID tài liệu liên quan DUY NHẤT tìm được trong top-k.
    - Precision@k = Số ID tài liệu liên quan DUY NHẤT tìm được trong top-k / k.
    - Tài liệu trùng lặp trong kết quả trả về chỉ tính ID duy nhất, không làm tăng điểm.
    - Tài liệu thiếu ID (None) không được tính điểm.
    - MRR = Nghịch đảo thứ hạng (1/rank) của ID tài liệu liên quan đầu tiên.
    - Tập kỳ vọng rỗng: is_applicable = False, recall@k = None, precision@k = None, reciprocal_rank = None.
    """
    if k_list is None:
        k_list = [1, 3, 5]

    target_ids: Set[str] = {
        str(eid).strip() for eid in (expected_doc_ids or []) if str(eid).strip()
    }

    doc_id_map: Dict[int, Optional[str]] = {}
    seen_ids: Set[str] = set()
    deduped_retrieved_ids: List[str] = []

    for idx, doc in enumerate(docs):
        d_id = get_document_id(doc)
        doc_id_map[idx] = d_id
        if d_id and d_id not in seen_ids:
            seen_ids.add(d_id)
            deduped_retrieved_ids.append(d_id)

    metrics: Dict[str, Any] = {
        "retrieved_count": len(docs),
        "unique_retrieved_count": len(deduped_retrieved_ids),
        "expected_count": len(target_ids),
        "is_applicable": len(target_ids) > 0,
    }

    if len(target_ids) == 0:
        for k in k_list:
            metrics[f"hit@{k}"] = 0.0
            metrics[f"recall@{k}"] = None
            metrics[f"precision@{k}"] = None
        metrics["reciprocal_rank"] = None
        metrics["first_hit_rank"] = None
        metrics["relevant_count"] = 0
        return metrics

    def _is_hit(d_id: Optional[str]) -> bool:
        if d_id is not None and d_id != "" and d_id in target_ids:
            return True
        return False

    first_hit_rank: Optional[int] = None
    for rank, doc in enumerate(docs, 1):
        d_id = doc_id_map.get(rank - 1)
        if _is_hit(d_id):
            first_hit_rank = rank
            break

    reciprocal_rank = (
        round(1.0 / first_hit_rank, 4) if first_hit_rank is not None else 0.0
    )
    total_expected = len(target_ids)

    for k in k_list:
        sub_docs = docs[:k]
        unique_rel_in_k: Set[str] = set()
        for idx_sub in range(len(sub_docs)):
            d_id = doc_id_map.get(idx_sub)
            if _is_hit(d_id) and d_id is not None:
                unique_rel_in_k.add(d_id)

        rel_count = len(unique_rel_in_k)
        metrics[f"hit@{k}"] = 1.0 if rel_count > 0 else 0.0
        metrics[f"recall@{k}"] = round(min(1.0, rel_count / total_expected), 4)
        metrics[f"precision@{k}"] = round(rel_count / k, 4) if k > 0 else 0.0

    metrics["reciprocal_rank"] = reciprocal_rank
    metrics["first_hit_rank"] = first_hit_rank
    all_rel_found = {
        doc_id_map[i]
        for i in range(len(docs))
        if _is_hit(doc_id_map.get(i)) and doc_id_map.get(i) is not None
    }
    metrics["relevant_count"] = len(all_rel_found)
    return metrics


def classify_retrieval_error(
    docs: List[Dict[str, Any]], case: Dict[str, Any]
) -> Tuple[str, str]:
    """Phân loại lỗi retrieval theo taxonomy chuẩn hóa (chỉ dựa trên giao tập ID)."""
    expected_ids = set(case.get("expected_relevant_doc_ids", []))
    is_out_of_domain = case.get("is_out_of_domain", False)

    if is_out_of_domain:
        if not docs:
            return "safe_empty", "Đúng dự kiến: Câu hỏi ngoài phạm vi không có tài liệu."
        return (
            "out_of_domain_retrieved",
            "Cảnh báo: Có tài liệu được lấy về cho câu hỏi ngoài phạm vi.",
        )

    if not docs:
        return "retrieval_empty", "Lỗi: Không tìm thấy tài liệu nào trong kho tri thức."

    has_relevant = False
    for d in docs:
        d_id = get_document_id(d)
        if d_id and d_id in expected_ids:
            has_relevant = True
            break

    if has_relevant:
        return "success", "Thành công: Lấy được tài liệu liên quan kỳ vọng."

    case_category = str(
        case.get("expected_intent") or case.get("category", "")
    ).lower()
    doc_categories = {
        str(d.get("category", "")).lower() for d in docs if isinstance(d, dict)
    }

    if case_category and case_category in doc_categories:
        return (
            "wrong_context",
            "Lấy tài liệu cùng chủ đề nhưng sai năm, sai phương thức hoặc chuyên ngành.",
        )

    return "wrong_topic", "Lấy nhầm tài liệu thuộc chủ đề khác hoàn toàn."


def evaluate_answer_faithfulness(
    answer: str,
    sources: List[Dict[str, Any]],
    case: Dict[str, Any],
    source_version: str = "1.1.0-standardized-fixture",
    annotations_map: Optional[Any] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    """Đánh giá tính hợp lệ của trích dẫn (citation validity) và tính có căn cứ (evidence support).

    Quy tắc chuẩn hóa:
    - Citation validity CHỈ kiểm tra tham chiếu nguồn tồn tại, không chứng minh nội dung đúng.
    - Áp dụng CÙNG CỔNG XÁC MINH ANNOTATION cho mọi expected_behavior (clarify, refute_misinformation, out_of_domain, retrieve_relevant_docs).
    - Từ khóa làm rõ / từ chối chỉ là tín hiệu quan sát, không chứng minh câu trả lời đúng.
    - Ràng buộc chặt chẽ với nguồn thực tế: đối chiếu ID nguồn và fingerprint nội dung nguồn.
    - Đổi thứ tự nguồn khiến citation trỏ sai hoặc thay đổi nội dung nguồn đều không được duyệt.
    - Không có annotation phù hợp đã duyệt → BẮT BUỘC giữ 'unverified' / 'needs_review' và 'unverified_needs_review'.
    - Tuyệt đối không dùng flag/bypass để tự phong supported.
    """
    is_out_of_domain = case.get("is_out_of_domain", False)
    expected_behavior = case.get("expected_behavior", "retrieve_relevant_docs")
    requires_human_review = case.get("requires_human_review", False)
    lower_ans = (answer or "").lower()

    # 1. Kiểm tra tham chiếu trích dẫn (Citation Validity)
    citation_markers = [int(m) for m in re.findall(r"\[(\d+)\]", answer or "")]
    citation_count = len(citation_markers)
    has_citations = citation_count > 0

    if not has_citations:
        citation_validity = "no_citation"
        citation_faithfulness = True
    else:
        invalid_markers = [c for c in citation_markers if c < 1 or c > len(sources)]
        if invalid_markers or len(sources) == 0:
            citation_validity = "invalid_citation"
            citation_faithfulness = False
        else:
            citation_validity = "valid"
            citation_faithfulness = True

    # 2. Tín hiệu quan sát (Observational signals only - KHÔNG dùng để gán supported)
    safe_refusal_keywords = [
        "chưa công bố", "không có", "không đào tạo", "ngoài phạm vi",
        "chỉ hỗ trợ", "chưa thể xác nhận", "tương lai", "không thể cung cấp",
        "nằm ngoài phần thông tin",
    ]
    has_safe_refusal = any(kw in lower_ans for kw in safe_refusal_keywords)

    clarification_keywords = [
        "vui lòng cung cấp", "bạn quan tâm ngành nào", "cụ thể",
        "phương thức nào", "thông tin chi tiết", "hỏi thêm",
    ]
    has_clarification_prompt = any(kw in lower_ans for kw in clarification_keywords)

    refute_keywords = ["không đúng", "không chính xác", "không có chính sách", "chỉ", "thay vào đó"]
    has_refutation = any(kw in lower_ans for kw in refute_keywords)

    # 3. Cổng xác minh Annotation & Đối chiếu Nguồn thực tế (Unified Verification Gate)
    if citation_validity == "invalid_citation":
        evidence_support = "contradicted"
        decoupling_type = "type_b_generation_failure"
    elif not is_valid_source_version(source_version):
        # 3.0. Phiên bản nguồn không hợp lệ (rỗng, chỉ khoảng trắng, None hoặc sai kiểu):
        # Phiên bản rỗng không được coi là bằng chứng xác minh hợp lệ.
        evidence_support = "unverified"
        decoupling_type = "unverified_needs_review"
    else:
        # Nạp annotations nếu chưa truyền vào
        if annotations_map is None:
            annotations_map = load_answer_annotations()

        normalized_source_version = str(source_version).strip()
        case_id = str(case.get("id", "")).strip()
        ans_hash = compute_answer_hash(answer)
        ann_key = f"{case_id}::{normalized_source_version}::{ans_hash}"

        candidates: List[Dict[str, Any]] = []
        if isinstance(annotations_map, dict):
            entry = annotations_map.get(ann_key)
            if isinstance(entry, list):
                candidates = entry
            elif isinstance(entry, dict):
                candidates = [entry]
        elif isinstance(annotations_map, list):
            for item in annotations_map:
                if isinstance(item, dict):
                    if (
                        str(item.get("case_id", "")).strip() == case_id
                        and str(item.get("answer_hash", "")).strip() == ans_hash
                    ):
                        candidates.append(item)

        approved_match: Optional[Dict[str, Any]] = None

        for ann in candidates:
            # 3.1. Bắt buộc trạng thái approved
            if ann.get("status") != "approved":
                continue

            # 3.2. Bắt buộc phiên bản nguồn trong annotation phải hợp lệ và khớp chính xác
            # (hai giá trị không hợp lệ giống nhau vẫn không được coi là khớp)
            ann_ver = ann.get("source_version")
            if not is_valid_source_version(ann_ver):
                continue
            if str(ann_ver).strip() != normalized_source_version:
                continue

            # 3.3. Đối chiếu nguồn thực tế và kiểm tra quan hệ citation [n]
            exp_source_ids = ann.get("source_ids", [])
            exp_source_fps = ann.get("source_fingerprints", [])

            if has_citations:
                if not exp_source_ids or not exp_source_fps:
                    # Annotation thiếu thông tin nguồn hoặc fingerprint
                    continue

                matched_sources = True
                for m in citation_markers:
                    src_idx = m - 1
                    if (
                        src_idx < 0
                        or src_idx >= len(sources)
                        or src_idx >= len(exp_source_ids)
                        or src_idx >= len(exp_source_fps)
                    ):
                        matched_sources = False
                        break

                    actual_doc = sources[src_idx]
                    actual_doc_id = get_document_id(actual_doc)
                    actual_fp = compute_source_fingerprint(actual_doc)

                    # ID nguồn phải khớp chính xác vị trí marker
                    if not actual_doc_id or actual_doc_id != exp_source_ids[src_idx]:
                        matched_sources = False
                        break

                    # Fingerprint nội dung nguồn phải khớp chính xác
                    if not actual_fp or actual_fp != exp_source_fps[src_idx]:
                        matched_sources = False
                        break

                if matched_sources:
                    approved_match = ann
                    break

            else:
                # Trường hợp không có citation marker (out-of-domain, clarify không marker)
                if sources:
                    if (
                        len(sources) != len(exp_source_ids)
                        or len(sources) != len(exp_source_fps)
                    ):
                        continue

                    matched_sources = True
                    for src_idx, actual_doc in enumerate(sources):
                        actual_doc_id = get_document_id(actual_doc)
                        actual_fp = compute_source_fingerprint(actual_doc)
                        if (
                            not actual_doc_id
                            or actual_doc_id != exp_source_ids[src_idx]
                            or not actual_fp
                            or actual_fp != exp_source_fps[src_idx]
                        ):
                            matched_sources = False
                            break
                    if matched_sources:
                        approved_match = ann
                        break
                else:
                    # sources rỗng: annotation cũng phải có source_ids rỗng
                    if len(exp_source_ids) == 0:
                        approved_match = ann
                        break

        # Phán quyết từ Approved Annotation
        if approved_match is not None:
            verdict = approved_match.get("verdict", "unverified")
            evidence_support = verdict
            if verdict == "supported":
                if is_out_of_domain:
                    decoupling_type = "type_c_safe_fallback"
                else:
                    decoupling_type = "type_a_full_success"
            elif verdict == "contradicted":
                if is_out_of_domain:
                    decoupling_type = "type_d_catastrophic_hallucination"
                else:
                    decoupling_type = "type_b_generation_failure"
            else:
                evidence_support = "unverified"
                decoupling_type = "unverified_needs_review"
        else:
            # Thiếu annotation, pending, sai lệch nguồn hoặc lệch fingerprint: BẮT BUỘC unverified
            evidence_support = "unverified"
            decoupling_type = "unverified_needs_review"

    return {
        "has_citations": has_citations,
        "citation_count": citation_count,
        "citation_validity": citation_validity,
        "citation_faithfulness": citation_faithfulness,
        "evidence_support": evidence_support,
        "has_safe_refusal": has_safe_refusal,
        "has_clarification_prompt": has_clarification_prompt,
        "has_refutation": has_refutation,
        "decoupling_type": decoupling_type,
        "requires_human_review": requires_human_review,
        "answer_hash": compute_answer_hash(answer),
        "source_version": source_version,
    }


def calculate_latency_percentiles(
    latencies_ms: List[Optional[float]], label: str = ""
) -> Dict[str, Any]:
    """Tính các phân vị độ trễ (min, p50, p90, p95, max, avg).

    Quy tắc chuẩn hóa:
    - Bỏ qua các giá trị None (span không đo được); ghi nhận số lượng missing_count.
    - Không biến None thành 0.0 hay giá trị mặc định.
    - Trả về status 'no_data' nếu không có mẫu hợp lệ.
    """
    valid_vals = [
        float(v)
        for v in latencies_ms
        if v is not None and isinstance(v, (int, float))
    ]
    missing_count = sum(1 for v in latencies_ms if v is None)

    if not valid_vals:
        return {
            "count": 0,
            "missing_count": missing_count,
            "min": None,
            "p50": None,
            "p90": None,
            "p95": None,
            "max": None,
            "avg": None,
            "status": "no_data",
            "label": label,
        }

    sorted_vals = sorted(valid_vals)
    n = len(sorted_vals)

    def _get_p(p: float) -> float:
        k = (n - 1) * (p / 100.0)
        f = math.floor(k)
        c = math.ceil(k)
        if f == c:
            return sorted_vals[int(k)]
        return sorted_vals[int(f)] * (c - k) + sorted_vals[int(c)] * (k - f)

    return {
        "count": n,
        "missing_count": missing_count,
        "min": round(sorted_vals[0], 2),
        "p50": round(_get_p(50), 2),
        "p90": round(_get_p(90), 2),
        "p95": round(_get_p(95), 2),
        "max": round(sorted_vals[-1], 2),
        "avg": round(sum(sorted_vals) / n, 2),
        "status": "ok",
        "label": label,
    }


def generate_evidence_based_recommendations(
    retrieval_summary: Dict[str, Any],
    generation_summary: Dict[str, Any],
    latency_summary: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """Sinh đề xuất tối ưu hóa dựa trên BẰNG CHỨNG HỢP LỆ VÀ NGUỒN GỐC SỐ ĐO (PROVENANCE).

    Quy tắc chuẩn hóa:
    - Gắn provenance rõ ràng cho số đo: 'simulated', 'recorded_validated', hoặc 'live'.
    - Dữ liệu simulated / unknown tuyệt đối không dùng để đề xuất đổi model, prompt, index hay kiến trúc Jev.
    - Đổi thời gian sleep không được tạo ưu tiên tối ưu production.
    - Với dữ liệu giả lập, chỉ ghi nhận bộ đo hoạt động và cần thu thập telemetry thực tế; không sinh khuyến nghị production.
    - Chỉ sinh đề xuất tối ưu khi có số đo thực tế hợp lệ phù hợp với phạm vi kết luận.
    - Không cố bổ sung cho đủ ba đề xuất.
    """
    provenance = latency_summary.get("provenance")
    is_real_measurement = provenance in ("recorded_validated", "live")
    recommendations: List[Dict[str, Any]] = []

    # 1. Nếu số đo là simulated hoặc thiếu provenance: KHÔNG sinh đề xuất kỹ thuật production
    if not is_real_measurement:
        pending_count = retrieval_summary.get("pending_human_review_cases", 0)
        if pending_count > 0:
            recommendations.append({
                "priority": 1,
                "title": "Phê duyệt bộ nhãn Ground Truth và Annotation cho các trường hợp Pending",
                "impact": f"Nâng cao độ tin cậy và độ bao phủ của benchmark ({pending_count} tình huống đang chờ duyệt)",
                "risk": "Thấp (Chuẩn hóa nhãn dữ liệu, không tác động vận hành)",
                "evidence": f"Hiện có {pending_count} tình huống ở trạng thái pending cần được phê duyệt trước khi mở rộng benchmark.",
            })
        return recommendations

    # 2. Khi CÓ số đo thực tế hợp lệ (live hoặc recorded_validated):
    ranking = latency_summary.get("bottleneck_ranking", [])
    if ranking and len(ranking) > 0:
        top_bottleneck = ranking[0]
        top_component = top_bottleneck.get("component", "")
        top_avg = top_bottleneck.get("avg_duration_ms", 0.0)

        if "llm_ttft" in top_component and top_avg > 1000.0:
            recommendations.append({
                "priority": len(recommendations) + 1,
                "title": "Tối ưu hóa thời gian chờ LLM First Token (LLM TTFT)",
                "impact": f"Rất cao (Điểm nghẽn thực tế chiếm {top_avg:.1f}ms trung bình)",
                "risk": "Thấp (Thử nghiệm streaming prompt rút gọn hoặc nhà cung cấp có TTFT thấp hơn)",
                "evidence": f"Số đo thực tế ({provenance}) ghi nhận llm_ttft trung bình đạt {top_avg:.1f}ms, là thành phần tiêu tốn thời gian dài nhất.",
            })
        elif "keyword_search" in top_component and top_avg > 100.0:
            recommendations.append({
                "priority": len(recommendations) + 1,
                "title": "Tối ưu hóa chỉ mục Text Index cho Keyword Search",
                "impact": f"Cao (Giảm {top_avg:.1f}ms thời gian tìm kiếm từ khóa)",
                "risk": "Thấp (Dùng text index hoặc giới hạn regex filter)",
                "evidence": f"Số đo thực tế ({provenance}) ghi nhận keyword_search chiếm trung bình {top_avg:.1f}ms.",
            })

    jev_comp = latency_summary.get("jev_shadow_comparison", {})
    overhead_ms = jev_comp.get("overhead_ms")
    if overhead_ms is not None and overhead_ms > 150.0:
        recommendations.append({
            "priority": len(recommendations) + 1,
            "title": "Chuyển Jev Shadow Evaluation sang Background Task phi đồng bộ",
            "impact": f"Trung bình (Giảm {overhead_ms:.1f}ms overhead trong chu trình chat stream)",
            "risk": "Rất thấp (Shadow mode không tác động đến nội dung trả về của người dùng)",
            "evidence": f"Số đo thực tế ({provenance}) ghi nhận Shadow Mode tạo thêm {overhead_ms:.1f}ms độ trễ.",
        })

    return recommendations[:3]


def sanitize_report_data(data: Any) -> Any:
    """Loại bỏ toàn bộ API key, password, PII, URI chứa mật khẩu hoặc raw exception khỏi báo cáo."""
    if isinstance(data, dict):
        sanitized = {}
        for k, v in data.items():
            k_lower = str(k).lower()
            is_secret = (
                any(
                    term in k_lower
                    for term in [
                        "api_key", "secret_key", "password", "token",
                        "passwd", "auth_token", "secret", "credentials",
                    ]
                )
                or k_lower in ("key", "pass", "auth", "cred")
            ) and "keyword" not in k_lower
            if is_secret:
                sanitized[k] = "[REDACTED]"
            elif ("uri" in k_lower or "url" in k_lower) and any(
                proto in str(v).lower()
                for proto in ["mongodb+srv", "@cluster", "mongodb://"]
            ):
                sanitized[k] = "[REDACTED_URI]"
            elif "error" in k_lower and isinstance(v, str) and (
                "password" in v.lower() or "token" in v.lower()
            ):
                sanitized[k] = "[CLEANED_ERROR]"
            else:
                sanitized[k] = sanitize_report_data(v)
        return sanitized
    elif isinstance(data, list):
        return [sanitize_report_data(item) for item in data]
    return data
