import re
import time
from concurrent.futures import ThreadPoolExecutor
from typing import List, Dict, Any, Optional
from backend.app.config import settings
from backend.app.data_access.operations import rag_operations
from backend.app.rag.intent import normalize_text, expand_query, classify_intent, infer_metadata, candidate_id, TITLE_STOP_WORDS
from backend.app.rag.embedding import EmbeddingManager
from backend.app.rag.retrieval import HybridRetriever

def rerank_and_filter(
    candidate_map: Dict[str, dict],
    vector_ranks: Dict[str, int],
    keyword_ranks: Dict[str, int],
    question: str,
    intent: str,
    top_cluster_id: Optional[int],
    requested_years: set,
    top_k: int = 3
) -> List[dict]:
    rrf_k = 60
    scored_candidates = []
    q_words = set(re.findall(r'\w+', question.lower()))
    q_normalized = normalize_text(question)
    code_matches = re.findall(r'\b7\d{6}\b', question)

    for doc_id, doc in candidate_map.items():
        metadata = infer_metadata(doc)
        doc.update({key: doc.get(key) or value for key, value in metadata.items()})
        v_rank = vector_ranks.get(doc_id, 999)
        k_rank = keyword_ranks.get(doc_id, 999)
        rrf_score = (1.0 / (rrf_k + v_rank)) + (1.0 / (rrf_k + k_rank))

        # Re-ranker scoring features
        text_content = (str(doc.get("title", "")) + " " + str(doc.get("text", ""))).lower()
        overlap_count = sum(1 for w in q_words if len(w) > 2 and w in text_content)
        normalized_title = normalize_text(doc.get("title", ""))
        title_overlap = sum(
            1 for word in {normalize_text(w) for w in q_words}
            if len(word) >= 5
            and word not in TITLE_STOP_WORDS
            and word in normalized_title
        )

        # Exact course code boost
        code_boost = 0.0
        for code in code_matches:
            if code in text_content:
                code_boost += 0.5

        intent_boost = 0.35 if intent != "general" and metadata["category"] == intent else 0.0
        
        # Extract pure major name from document title
        pure_major_name = re.sub(r"\s*\(mã ngành.*$", "", normalized_title, flags=re.IGNORECASE)
        pure_major_name = re.sub(r"\s*\(ma nganh.*$", "", pure_major_name, flags=re.IGNORECASE)
        pure_major_name = re.sub(r"^nganh\s+", "", pure_major_name, flags=re.IGNORECASE).strip()
        pure_major_name = re.sub(r"\s*-.*$", "", pure_major_name).strip()

        exact_major_boost = 0.0
        if metadata["category"] == "major" and len(pure_major_name) >= 3:
            if pure_major_name in q_normalized or (len(q_normalized) >= 5 and q_normalized in pure_major_name):
                exact_major_boost = 3.5  # Massive boost ensuring exact major match ALWAYS wins #1 spot!
            elif pure_major_name == "cong nghe thong tin" and any(alias in q_normalized for alias in ["cntt", "cn thong tin", "cong nghe thong tin"]):
                exact_major_boost = 3.5

        # Career alignment boost to match user intent to proper faculty/program docs
        career_boost = 0.0
        norm_text = normalize_text(text_content)
        if intent == "career" or any(term in q_normalized for term in ["thiet ke", "vay", "dam", "may mac", "thoi trang", "nau an", "my pham", "lap trinh"]):
            if any(k in q_normalized for k in ["vay", "dam", "may mac", "thoi trang", "trang phuc", "may rap"]):
                if any(m in norm_text for m in ["det, may", "thoi trang", "7540204", "7340123", "khoa may"]):
                    career_boost += 0.8
            elif any(k in q_normalized for k in ["nau an", "lam banh", "am thuc", "dau bep"]):
                if any(m in norm_text for m in ["che bien mon an", "dich vu an uong", "7810202", "am thuc"]):
                    career_boost += 0.8
            elif any(k in q_normalized for k in ["lap trinh", "game", "code", "app"]):
                if any(m in norm_text for m in ["cong nghe thong tin", "ky thuat phan mem", "tri tue nhan tao", "7480101", "7480107"]):
                    career_boost += 0.8
            elif any(k in q_normalized for k in ["my pham", "son", "kem duong", "hoa chat"]):
                if any(m in norm_text for m in ["hoa hoc", "hoa my pham", "7510401"]):
                    career_boost += 0.8

        year_boost = 0.2 if requested_years and metadata["year"] in requested_years else 0.0
        year_penalty = -0.12 if requested_years and metadata["year"] and metadata["year"] not in requested_years else 0.0
        cluster_boost = 0.35 if (top_cluster_id is not None and doc.get("cluster_id") == top_cluster_id) else 0.0
        final_score = (
            (rrf_score * 10)
            + (overlap_count * 0.05)
            + (title_overlap * 0.15)
            + code_boost
            + intent_boost
            + exact_major_boost
            + career_boost
            + cluster_boost
            + year_boost
            + year_penalty
        )
        doc["score"] = round(doc.get("score") or final_score, 4)
        doc["rrf_score"] = round(final_score, 4)
        scored_candidates.append((final_score, doc))

    scored_candidates.sort(key=lambda x: x[0], reverse=True)
    return [item[1] for item in scored_candidates if item[0] >= 0.15][:top_k]

def apply_heuristic_overrides(docs: List[dict], question: str, intent: str) -> List[dict]:
    q_normalized = normalize_text(question)

    # 1. General tuition heuristic override
    if intent == "tuition":
        general_tuition_doc = {
            "_id": "huit_general_tuition_override",
            "title": "Chính sách & Mức Học phí HUIT (ĐH Công Thương TP.HCM)",
            "text": "[Trường Đại học Công Thương TP.HCM (HUIT) | Nguồn chính thức ts.huit.edu.vn | Chủ đề: Học phí K26 năm 2026]\nHọc phí trung bình tại HUIT khoảng 14 - 16 triệu đồng/học kỳ (mỗi năm học có 2 học kỳ chính). Đơn giá tín chỉ khoảng 540.000đ - 700.000đ/tín chỉ (1.100.000đ/tín chỉ lý thuyết và 1.350.000đ/tín chỉ thực hành với các môn chuyên sâu K26). Nhà trường cam kết giữ ổn định mức học phí không tăng trong toàn bộ khóa học (3.5 - 4 năm).",
            "url": "https://ts.huit.edu.vn/47159/hoc-phi-huit-nam-2026-minh-bach-thong-tin-dong-hanh-cung-nguoi-hoc",
            "source_url": "https://ts.huit.edu.vn/47159/hoc-phi-huit-nam-2026-minh-bach-thong-tin-dong-hanh-cung-nguoi-hoc",
            "category": "tuition",
            "year": 2026,
            "score": 0.99
        }
        if not any(d.get("_id") == general_tuition_doc["_id"] for d in docs):
            docs.insert(0, general_tuition_doc)

    # 2. Cutoff & Floor score heuristic overrides
    if intent in ("cutoff", "floor_score") or any(k in q_normalized for k in ["diem san", "diem chuan", "diem trung tuyen", "diem nay"]):
        is_floor_query = (
            intent == "floor_score"
            or "diem san" in q_normalized
            or "nguong dam bao" in q_normalized
            or "nhan ho so" in q_normalized
        ) and not any(k in q_normalized for k in ["chuan", "trung tuyen"])

        if is_floor_query:
            floor_doc = {
                "_id": "huit_2026_floor_override",
                "title": "Điểm sàn xét tuyển đại học HUIT năm 2026",
                "text": (
                    "[Trường Đại học Công Thương TP.HCM (HUIT) | Nguồn chính thức "
                    "ts.huit.edu.vn | Chủ đề: Điểm sàn nhận hồ sơ năm 2026]\n"
                    "Điểm sàn nhận hồ sơ xét tuyển đại học HUIT năm 2026:\n"
                    "- Điểm thi tốt nghiệp THPT: Ngành Luật và Luật kinh tế 20 điểm; các ngành còn lại 16 điểm.\n"
                    "- Xét học bạ THPT: 20 điểm cho tất cả các ngành.\n"
                    "- Điểm Đánh giá năng lực ĐHQG-HCM: Nhóm Luật 720 điểm, các ngành còn lại 600 điểm."
                ),
                "url": "https://ts.huit.edu.vn/thong-bao/diem-san-xet-tuyen-dai-hoc-nam-2026-truong-dai-hoc-cong-thuong-tp-hcm",
                "source_url": "https://ts.huit.edu.vn/thong-bao/diem-san-xet-tuyen-dai-hoc-nam-2026-truong-dai-hoc-cong-thuong-tp-hcm",
                "category": "cutoff",
                "year": 2026,
                "score": 0.99,
            }
            if not any(d.get("_id") == floor_doc["_id"] for d in docs):
                docs.insert(0, floor_doc)
        else:
            official_cutoff_doc = {
                "_id": "huit_2026_official_cutoff_doc",
                "title": "Điểm chuẩn trúng tuyển chính thức Trường Đại học Công Thương TP.HCM năm 2026",
                "text": (
                    "[Trường Đại học Công Thương TP.HCM (HUIT) | Nguồn chính thức ts.huit.edu.vn | Chủ đề: Điểm chuẩn trúng tuyển năm 2026 (Công bố chính thức ngày 09/08/2026)]\n"
                    "Trường Đại học Công Thương TP.HCM đã CHÍNH THỨC CÔNG BỐ Điểm chuẩn trúng tuyển năm 2026 vào ngày 09/08/2026 cho 44 ngành và chương trình đào tạo:\n"
                    "- Phương thức Điểm thi tốt nghiệp THPT năm 2026: Dao động từ 16.00 đến 23.00 điểm. "
                    "Ngành lấy điểm chuẩn cao nhất: Công nghệ kỹ thuật điều khiển và tự động hóa (23.00 điểm). "
                    "Logistics và Quản lý chuỗi cung ứng: 22.50 điểm; Công nghệ thực phẩm: 22.00 điểm; "
                    "Công nghệ kỹ thuật điện - điện tử: 22.00 điểm; Marketing, Thương mại điện tử, Luật kinh tế: 21.75 điểm; "
                    "Quản trị kinh doanh, Cơ điện tử: 21.50 điểm; Luật, Kế toán, Tài chính - ngân hàng: 21.25 điểm; "
                    "Trí tuệ nhân tạo: 20.50 điểm; Công nghệ thông tin, Khoa học dữ liệu, An toàn thông tin: 20.00 điểm. "
                    "Các ngành điểm chuẩn thấp nhất: Công nghệ dệt, may (18.00 điểm), Công nghệ chế biến thủy sản (16.00 điểm).\n"
                    "- Phương thức Xét học bạ THPT: Từ 20.00 đến 25.63 điểm (Tự động hóa 25.63đ, Logistics 25.00đ, CNTT 24.50đ).\n"
                    "- Phương thức Đánh giá năng lực ĐHQG-HCM: Từ 600 đến 825 điểm (Tự động hóa 825đ, Logistics 800đ, Ngôn ngữ 800đ)."
                ),
                "url": "https://ts.huit.edu.vn/tin-tuyen-sinh/diem-chuan-truong-dai-hoc-cong-thuong-tp-hcm-nam-2026",
                "source_url": "https://ts.huit.edu.vn/tin-tuyen-sinh/diem-chuan-truong-dai-hoc-cong-thuong-tp-hcm-nam-2026",
                "category": "cutoff",
                "year": 2026,
                "score": 0.999,
            }
            if not any(d.get("_id") == official_cutoff_doc["_id"] for d in docs):
                docs.insert(0, official_cutoff_doc)

    # 3. Admission procedure & Tuition refund overrides
    if intent == "admission_procedure" or any(k in q_normalized for k in ["nhap hoc", "thu tuc nhap hoc", "thoi gian nhap hoc", "ho so nhap hoc", "xac nhan nhap hoc", "rut hoc phi"]):
        if any(k in q_normalized for k in ["rut hoc phi", "hoan hoc phi"]):
            refund_doc = {
                "_id": "huit_2026_tuition_refund_doc",
                "title": "Thông báo rút học phí đối với sinh viên nhập học năm học 2026 - 2027 - HUIT",
                "text": (
                    "[Trường Đại học Công Thương TP.HCM (HUIT) | Nguồn chính thức ts.huit.edu.vn | Chủ đề: Quy định rút học phí sinh viên nhập học 2026 - 2027 (Ban hành ngày 14/08/2026)]\n"
                    "Nhà trường quy định điều kiện và thủ tục giải quyết rút học phí đối với tân sinh viên đã nộp học phí nhập học nhưng có nguyện vọng rút hồ sơ:\n"
                    "- Hồ sơ gồm: Đơn xin rút học phí (theo mẫu của HUIT), Phiếu thu/Biên lai nộp tiền hoặc sao kê chuyển khoản hợp lệ, Bản sao CCCD, Giấy tờ minh chứng lý do chính đáng.\n"
                    "- Địa điểm nộp và xử lý hồ sơ: Phòng Tài chính - Kế toán phối hợp Phòng Công tác Sinh viên (140 Lê Trọng Tấn, P. Tây Thạnh, Q. Tân Phú, TP.HCM). Hotline: 096 205 1080."
                ),
                "url": "https://ts.huit.edu.vn/thong-bao/thong-bao-rut-hoc-phi-sinh-vien-nhap-hoc-nam-hoc-2026-2027",
                "source_url": "https://ts.huit.edu.vn/thong-bao/thong-bao-rut-hoc-phi-sinh-vien-nhap-hoc-nam-hoc-2026-2027",
                "category": "tuition",
                "year": 2026,
                "score": 0.995,
            }
            if not any(d.get("_id") == refund_doc["_id"] for d in docs):
                docs.insert(0, refund_doc)
        else:
            admission_proc_doc = {
                "_id": "huit_2026_admission_proc_doc",
                "title": "Thông báo hướng dẫn làm thủ tục nhập học Khóa 15 Đại học chính quy năm 2026",
                "text": (
                    "[Trường Đại học Công Thương TP.HCM (HUIT) | Nguồn chính thức ts.huit.edu.vn | Chủ đề: Quy trình nhập học Khóa 15 năm 2026]\n"
                    "Quy trình nhập học chính thức gồm 2 giai đoạn:\n"
                    "1. Xác nhận nhập học trực tuyến: Thí sinh trúng tuyển phải xác nhận nhập học trực tuyến trên Hệ thống hỗ trợ tuyển sinh chung của Bộ GD&ĐT.\n"
                    "2. Làm thủ tục nhập học tại Trường Đại học Công Thương TP.HCM: Khai báo hồ sơ sinh viên trực tuyến tại cổng nhaphoc.huit.edu.vn, nộp học phí tạm thu và nộp hồ sơ trực tiếp tại Cơ sở chính 140 Lê Trọng Tấn, P. Tây Thạnh, Q. Tân Phú, TP.HCM."
                ),
                "url": "https://ts.huit.edu.vn/thong-bao/thong-bao-nhap-hoc-khoa-15-dai-hoc-chinh-quy-nam-2026",
                "source_url": "https://ts.huit.edu.vn/thong-bao/thong-bao-nhap-hoc-khoa-15-dai-hoc-chinh-quy-nam-2026",
                "category": "admission_procedure",
                "year": 2026,
                "score": 0.995,
            }
            if not any(d.get("_id") == admission_proc_doc["_id"] for d in docs):
                docs.insert(0, admission_proc_doc)

    return docs

def retrieve(question: str, top_k: int = 3, timings: Optional[Any] = None) -> List[dict]:
    """Quy trình retrieval hoàn chỉnh kết hợp Dense Vector, Sparse Keyword và Reranking."""
    expanded_q = expand_query(question)
    intent = classify_intent(expanded_q)
    requested_years = {int(val) for val in re.findall(r"\b20\d{2}\b", expanded_q)}

    candidate_map: Dict[str, dict] = {}
    vector_ranks: Dict[str, int] = {}
    keyword_ranks: Dict[str, int] = {}

    # 1 & 2. Concurrent Vector & Keyword Search (chạy song song để giảm độ trễ I/O mạng MongoDB Atlas)
    def _execute_vector_search():
        t0_emb = time.perf_counter()
        qv_res = EmbeddingManager.embed_query(expanded_q)
        t_emb = (time.perf_counter() - t0_emb) * 1000

        t0_vec = time.perf_counter()
        v_res = []
        if qv_res:
            v_res = HybridRetriever.search_vector(qv_res)
        t_vec = (time.perf_counter() - t0_vec) * 1000
        return qv_res, v_res, t_emb, t_vec

    def _execute_keyword_search():
        t0_kw = time.perf_counter()
        k_res = HybridRetriever.search_keyword(expanded_q)
        t_kw = (time.perf_counter() - t0_kw) * 1000
        return k_res, t_kw

    with ThreadPoolExecutor(max_workers=2) as executor:
        f_vec = executor.submit(_execute_vector_search)
        f_kw = executor.submit(_execute_keyword_search)
        qv, v_docs, t_emb_ms, t_vec_ms = f_vec.result()
        k_docs, t_kw_ms = f_kw.result()

    if timings:
        timings.record_metric("embedding", t_emb_ms)
        timings.record_metric("vector_search", t_vec_ms)
        timings.record_metric("keyword_search", t_kw_ms)

    top_cluster_id = HybridRetriever.get_top_cluster(qv) if qv else None

    if qv:
        for rank, doc in enumerate(v_docs, 1):
            doc_id = candidate_id(doc, rank, "v")
            candidate_map[doc_id] = doc
            vector_ranks[doc_id] = rank

    for rank, doc in enumerate(k_docs, 1):
        doc_id = candidate_id(doc, rank, "k")
        if doc_id not in candidate_map:
            candidate_map[doc_id] = doc
        keyword_ranks[doc_id] = rank

    # Fallback nếu không tìm thấy gì
    if not candidate_map:
        try:
            raw_docs = rag_operations.get_fallback_docs(limit=top_k)
            for rank, doc in enumerate(raw_docs, 1):
                doc_id = candidate_id(doc, rank, "r")
                candidate_map[doc_id] = doc
                vector_ranks[doc_id] = rank
        except Exception:
            pass

    # 3. Rerank & Score
    if timings:
        timings.start_span("rerank")
    docs = rerank_and_filter(
        candidate_map, vector_ranks, keyword_ranks,
        expanded_q, intent, top_cluster_id, requested_years, top_k
    )

    # 4. Heuristics overrides
    docs = apply_heuristic_overrides(docs, expanded_q, intent)
    if timings:
        timings.end_span("rerank")

    # 5. Deduplicate
    unique_docs = []
    seen = set()
    for d in docs:
        ident = (d.get("source_url") or d.get("url"), d.get("category"))
        if ident not in seen:
            seen.add(ident)
            unique_docs.append(d)

    return unique_docs[:top_k]
