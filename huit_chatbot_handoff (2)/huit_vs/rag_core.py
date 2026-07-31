#!/usr/bin/env python3
"""Lõi RAG tái dùng cho API: nạp embedder 1 lần, retrieve + generate.

Biến môi trường: MONGODB_PASSWORD (bắt buộc), HUIT_OPENROUTER_KEY (ưu tiên;
fallback OPENROUTER_API_KEY/DASHSCOPE_API_KEY/OPENAI_API_KEY/GEMINI_API_KEY),
OPENROUTER_MODEL (mặc định openai/gpt-oss-20b:free).
"""
import copy
import hashlib
import json
import os
import re
import time
import unicodedata
from datetime import datetime, timedelta, timezone
from urllib.parse import quote_plus
import numpy as np

from pymongo import MongoClient

USER = "nguyenkhaihiep1999_db_user"
HOST = "cluster0.hyj8rab.mongodb.net"
DB = "huit_chatbot"
COLL = "huit_kb"
MODEL = "intfloat/multilingual-e5-large"
DIMS = 1024
LLM_MODEL = os.environ.get("OPENROUTER_MODEL", "google/gemini-2.0-flash-exp:free")
LLM_MAX_TOKENS = int(os.environ.get("LLM_MAX_TOKENS", "750"))
_ram_cache = {}
_ram_cache_expiry = {}
# Version is coupled to the embeddings currently promoted in Atlas. Keeping it
# code-owned prevents a stale Vercel environment value from reusing old caches.
KB_VERSION = "huit-kb-2026-07-v4-semantic"
RAG_VERSION = "rag-v10-grounded-score-source"
CACHE_TTL_HOURS = int(os.environ.get("CACHE_TTL_HOURS", "24"))
HERE = os.path.dirname(os.path.abspath(__file__))
RETRIEVAL_MODULE = os.path.join(HERE, "huit_semantic_search.module.json")
RAG_MODULE = os.path.join(HERE, "huit_rag_answer.module.json")

# Tự động đọc cấu hình API từ file .env nếu có
_env_path = os.path.join(HERE, ".env")
if os.path.exists(_env_path):
    with open(_env_path, encoding="utf-8") as _f:
        for _line in _f:
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                _k, _v = _line.split("=", 1)
                _k = _k.strip()
                _v = _v.strip().strip('"\'')
                if _v or _k not in os.environ:
                    os.environ[_k] = _v


import tempfile

_tmp_dir = tempfile.gettempdir()
os.environ["HF_HOME"] = os.path.join(_tmp_dir, "huggingface")
os.environ["HF_HUB_CACHE"] = os.path.join(_tmp_dir, "huggingface", "hub")
os.environ["FASTEMBED_CACHE_DIR"] = os.path.join(_tmp_dir, "fastembed_cache")
os.environ["XDG_CACHE_HOME"] = os.path.join(_tmp_dir, "cache")
os.environ["TORCH_HOME"] = os.path.join(_tmp_dir, "torch")
os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"

_embedder = None
_mongo = None
_retrieval_pipeline = None
_rag_cfg = None
_cluster_centroids = None


def _init():
    global _embedder, _mongo, _retrieval_pipeline, _rag_cfg, _cluster_centroids
    if _mongo is None:
        pwd = os.environ.get("MONGODB_PASSWORD")
        if not pwd:
            raise RuntimeError(
                "MONGODB_PASSWORD chưa được cấu hình. "
                "Hãy điền biến này trong file .env cục bộ."
            )
        uri = f"mongodb+srv://{USER}:{quote_plus(pwd)}@{HOST}/?appName=Cluster0"
        _mongo = MongoClient(uri, serverSelectionTimeoutMS=15000)
        try:
            cache = _mongo[DB]["query_cache"]
            cache.create_index("cache_key")
            cache.create_index("expires_at", expireAfterSeconds=0)
            _mongo[DB]["rag_events"].create_index("created_at")
        except Exception as e:
            print("Mongo index initialization warning:", e)
    if _retrieval_pipeline is None:
        mod = json.load(open(RETRIEVAL_MODULE, encoding="utf-8"))
        _retrieval_pipeline = mod["private"]["node_function"]["edge"][0]["pipeline"]
    if _rag_cfg is None:
        rag = json.load(open(RAG_MODULE, encoding="utf-8"))
        _rag_cfg = rag["private"]["node_function"]["edge"][0]["config"]
    if _cluster_centroids is None:
        c_path = os.path.join(HERE, "huit_cluster_centroids.json")
        if os.path.exists(c_path):
            try:
                _cluster_centroids = json.load(open(c_path, encoding="utf-8"))
            except Exception as e:
                print("Centroids load warning:", e)
    if _embedder is None:
        try:
            from fastembed import TextEmbedding
            cache_path = os.environ.get("FASTEMBED_CACHE_DIR", os.path.join(_tmp_dir, "fastembed_cache"))
            os.makedirs(cache_path, exist_ok=True)
            _embedder = TextEmbedding(MODEL, cache_dir=cache_path)
        except Exception as e:
            print("FastEmbed init warning (falling back to MongoDB keyword search):", e)
            _embedder = False


def _clean_doc_title(title):
    if not title or "FPT Shop" in title or "CellphoneS" in title or "Znews" in title:
        return "Thông tin Tuyển sinh & Học phí HUIT (Cổng chính thức)"
    return title.strip()


def _normalize(text):
    text = str(text or "").lower()
    telex_map = [
        (r"\bngnah\b", "nganh"),
        (r"\bnganhj\b", "nganh"),
        (r"\bhocj\b", "hoc"),
        (r"\bphij\b", "phi"),
        (r"\bxetj\b", "xet"),
        (r"\bdiemj\b", "diem"),
        (r"\bdiems\b", "diem"),
        (r"\bdiemd\b", "diem"),
        (r"\bchuanj\b", "chuan"),
        (r"\bsanj\b", "san"),
        (r"\bhocjba\b", "hoc ba"),
        (r"\bhocj ba\b", "hoc ba"),
    ]
    for pattern, repl in telex_map:
        text = re.sub(pattern, repl, text)
    text = unicodedata.normalize("NFD", text)
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
    text = text.replace("đ", "d")
    return re.sub(r"\s+", " ", text).strip()


QUERY_ALIASES = {
    "attt": "an toàn thông tin",
    "cntt": "công nghệ thông tin",
    "data science": "khoa học dữ liệu",
    "data": "khoa học dữ liệu",
    "tiếp thị": "marketing",
    "chuỗi cung ứng": "logistics quản lý chuỗi cung ứng",
    "hỗ trợ học phí": "học bổng hỗ trợ học phí",
    # Natural career-orientation language -> official program vocabulary.
    "xử lý nước thải": "công nghệ kỹ thuật môi trường xử lý nước thải kiểm soát ô nhiễm",
    "kiểm soát ô nhiễm": "công nghệ kỹ thuật môi trường kiểm soát ô nhiễm",
    "máy tự động": "công nghệ kỹ thuật điều khiển và tự động hóa robot công nghiệp",
    "dây chuyền tự động": "công nghệ kỹ thuật điều khiển và tự động hóa",
    "phân tích dữ liệu": "khoa học dữ liệu phân tích khai phá dữ liệu thống kê",
    "dữ liệu lớn": "khoa học dữ liệu big data khai phá dữ liệu",
    # Mở rộng hướng nghiệp & các ngành đào tạo HUIT
    "thiết kế váy": "công nghệ dệt may kinh doanh thời trang và dệt may thiết kế rập trang phục",
    "thiết kế áo": "công nghệ dệt may kinh doanh thời trang và dệt may trang phục",
    "thiết kế đầm": "công nghệ dệt may kinh doanh thời trang và dệt may trang phục",
    "thiết kế trang phục": "công nghệ dệt may kinh doanh thời trang và dệt may",
    "thiết kế thời trang": "công nghệ dệt may kinh doanh thời trang và dệt may",
    "may mặc": "công nghệ dệt may thiết kế rập may công nghiệp",
    "may rập": "công nghệ dệt may kỹ sư thiết kế rập",
    "bán hàng thời trang": "kinh doanh thời trang và dệt may marketing thời trang",
    "thời trang": "công nghệ dệt may kinh doanh thời trang và dệt may",
    "lập trình game": "công nghệ thông tin kỹ thuật phần mềm trí tuệ nhân tạo",
    "lập trình app": "công nghệ thông tin kỹ thuật phần mềm",
    "viết app": "công nghệ thông tin kỹ thuật phần mềm",
    "viết code": "công nghệ thông tin kỹ thuật phần mềm",
    "lập trình viên": "công nghệ thông tin kỹ thuật phần mềm",
    "nấu ăn": "quản trị dịch vụ ăn uống và kỹ thuật chế biến món ăn",
    "làm bánh": "quản trị dịch vụ ăn uống và kỹ thuật chế biến món ăn công nghệ thực phẩm",
    "ẩm thực": "quản trị dịch vụ ăn uống và kỹ thuật chế biến món ăn",
    "đầu bếp": "quản trị dịch vụ ăn uống và kỹ thuật chế biến món ăn",
    "mỹ phẩm": "công nghệ kỹ thuật hóa học hóa mỹ phẩm",
    "son môi": "công nghệ kỹ thuật hóa học hóa mỹ phẩm",
    "hóa chất": "công nghệ kỹ thuật hóa học",
    "thiết kế đồ họa": "truyền thông đa phương tiện đồ họa",
    "truyền thông": "truyền thông đa phương tiện marketing",
    "sếp": "quản trị kinh doanh",
    "quản lý": "quản trị kinh doanh",
    "khởi nghiệp": "quản trị kinh doanh kinh doanh thương mại",
    "xuất nhập khẩu": "logistics và quản lý chuỗi cung ứng thương mại quốc tế",
    "con gái nên học": "công nghệ dệt may kinh doanh thời trang quản trị kinh doanh kế toán ngôn ngữ anh ngôn ngữ trung công nghệ thực phẩm công nghệ kỹ thuật hóa học",
    "nữ nên học": "công nghệ dệt may kinh doanh thời trang quản trị kinh doanh kế toán ngôn ngữ anh ngôn ngữ trung công nghệ thực phẩm công nghệ kỹ thuật hóa học",
    "dễ xin việc": "công nghệ thông tin công nghệ thực phẩm logistics và quản lý chuỗi cung ứng marketing kế toán công nghệ dệt may",
}


def expand_query(question):
    """Add canonical admissions terms without removing the user's wording."""
    normalized = _normalize(question)
    expansions = [
        canonical
        for alias, canonical in QUERY_ALIASES.items()
        if re.search(rf"\b{re.escape(_normalize(alias))}\b", normalized)
    ]
    return f"{question} {' '.join(expansions)}".strip()


INTENT_TERMS = {
    "tuition": (
        "hoc phi", "tin chi", "tien hoc", "muc phi", "chi phi hoc",
        "tien de hoc", "bao nhieu tien de hoc",
    ),
    "cutoff": (
        "diem san", "diem chuan", "diem trung tuyen", "diem nganh",
        "diem cntt", "diem it", "diem nay", "diem xet tuyen",
    ),
    "scholarship": ("hoc bong", "giam hoc phi", "mien hoc phi"),
    "admission": (
        "phuong thuc xet tuyen", "xet tuyen", "xet hoc ba",
        "danh gia nang luc",
    ),
    "career": (
        "chon nganh", "hoc nganh", "hoc ngnah", "hoc gi", "phu hop",
        "huong nghiep", "nghe nghiep", "thich", "muon hoc", "muon lam",
        "dam me", "con gai nen hoc", "nu nen hoc", "de xin viec",
        "thiet ke", "vay", "dam", "may mac", "lap trinh", "nau an",
        "my pham", "game", "truyen thong", "logistics", "xuat nhap khau",
    ),
    "major": ("ma nganh", "to hop", "nganh hoc", "co hoi viec lam", "nganh"),
    "contact": ("dia chi", "co so", "hotline", "lien he"),
}
TITLE_STOP_WORDS = {
    "thong", "tin", "tuyen", "sinh", "nganh", "huit", "truong",
    "dai", "hoc", "cong", "thuong", "thanh", "pho",
}


def classify_intent(question):
    normalized = _normalize(question)
    for intent in ("scholarship", "cutoff", "tuition", "admission", "contact", "career"):
        if any(term in normalized for term in INTENT_TERMS[intent]):
            return intent
    scores = {
        intent: sum(1 for term in terms if term in normalized)
        for intent, terms in INTENT_TERMS.items()
    }
    intent, score = max(scores.items(), key=lambda item: item[1])
    return intent if score else "general"


def infer_metadata(doc):
    title = str(doc.get("title", ""))
    text = str(doc.get("text", ""))
    combined = f"{title} {text}"
    normalized = _normalize(combined)
    category = doc.get("category")
    if not category:
        normalized_title = _normalize(title)
        if "hoc bong" in normalized_title:
            category = "scholarship"
        elif "hoc phi" in normalized_title:
            category = "tuition"
        elif "diem san" in normalized_title or "diem chuan" in normalized_title:
            category = "cutoff"
        elif "nganh" in normalized_title or re.search(r"\b7\d{6}\b", title):
            category = "major"
    if not category:
        category_scores = {
            intent: sum(1 for term in terms if term in normalized)
            for intent, terms in INTENT_TERMS.items()
        }
        category, score = max(category_scores.items(), key=lambda item: item[1])
        category = category if score else "general"
    years = [int(value) for value in re.findall(r"\b20(?:2[4-9]|3\d)\b", combined)]
    major_match = re.search(r"\b7\d{6}\b", combined)
    return {
        "category": category,
        "year": doc.get("year") or (max(years) if years else None),
        "major_code": doc.get("major_code") or (major_match.group(0) if major_match else None),
    }


def _candidate_id(doc, rank, prefix):
    if doc.get("_id") is not None:
        return str(doc["_id"])
    fingerprint = f"{doc.get('title', '')}|{doc.get('text', '')[:180]}"
    return f"{prefix}:{hashlib.sha1(fingerprint.encode('utf-8')).hexdigest()}:{rank}"


def retrieve(question, top_k=3):
    _init()
    question = expand_query(question)
    intent = classify_intent(question)
    requested_years = {int(value) for value in re.findall(r"\b20\d{2}\b", question)}
    candidate_map = {}
    vector_ranks = {}
    keyword_ranks = {}

    # 0. Phân cụm Ý định & Chủ đề qua KMeans Centroids (Machine Learning Clustering)
    top_cluster_id = None
    qv = None
    if _embedder and _cluster_centroids and "clusters" in _cluster_centroids:
        try:
            qv_list = list(_embedder.embed([f"query: {question}"]))[0].tolist()
            qv = qv_list
            qv_arr = np.array(qv_list, dtype=np.float32)
            qv_norm = np.linalg.norm(qv_arr)
            best_sim = -1.0
            for cid_str, cinfo in _cluster_centroids["clusters"].items():
                c_arr = np.array(cinfo["centroid"], dtype=np.float32)
                c_norm = np.linalg.norm(c_arr)
                if qv_norm > 0 and c_norm > 0:
                    sim = float(np.dot(qv_arr, c_arr) / (qv_norm * c_norm))
                    if sim > best_sim:
                        best_sim = sim
                        top_cluster_id = int(cid_str)
        except Exception as e:
            print("Cluster matching warning:", e)

    # 1. Dense Vector Search (E5-Large 1024D)
    vector_docs = []
    if _embedder and _retrieval_pipeline and _mongo is not None:
        try:
            pipeline = copy.deepcopy(_retrieval_pipeline)
            if qv is None:
                qv = list(_embedder.embed([f"query: {question}"]))[0].tolist()
            for stage in pipeline:
                vs = stage.get("$vectorSearch")
                if vs and isinstance(vs.get("queryVector"), str) and vs["queryVector"].startswith("<<QUERY_VECTOR"):
                    vs["queryVector"] = qv
                    vs["limit"] = 15
                    vs["numCandidates"] = 200
            vector_docs = list(_mongo[DB][COLL].aggregate(pipeline))
            for rank, doc in enumerate(vector_docs, 1):
                doc_id = _candidate_id(doc, rank, "v")
                candidate_map[doc_id] = doc
                vector_ranks[doc_id] = rank
        except Exception as e:
            print("Vector search retrieve warning:", e)

    # 2. Sparse Keyword Search (Mongo Regex)
    keyword_docs = []
    if _mongo is not None:
        try:
            words = [w.strip() for w in re.split(r'[\s,\?\.\-\(\)]+', question) if len(w.strip()) >= 2]
            stop_words = {"cho", "các", "của", "với", "như", "nào", "bao", "nhiêu", "trường", "huit", "ngành", "được", "không"}
            keywords = [w for w in words if w.lower() not in stop_words or w.isdigit()]
            if keywords:
                regex_pattern = "|".join([re.escape(k) for k in keywords])
                query = {
                    "$or": [
                        {"title": {"$regex": regex_pattern, "$options": "i"}},
                        {"text": {"$regex": regex_pattern, "$options": "i"}}
                    ]
                }
                # The verified KB is intentionally small. Fetch all matching
                # records and rank them locally; Mongo's natural-order limit
                # previously excluded the correct environmental/automation
                # record before the reranker could see it on Vercel.
                raw_kw = list(_mongo[DB][COLL].find(query).limit(100))
                normalized_terms = {
                    _normalize(word)
                    for word in keywords
                    if len(_normalize(word)) >= 3
                }
                raw_kw.sort(
                    key=lambda item: sum(
                        1
                        for term in normalized_terms
                        if term in _normalize(
                            f"{item.get('title', '')} {item.get('text', '')}"
                        )
                    ),
                    reverse=True,
                )
                raw_kw = raw_kw[:30]
                keyword_docs = [d for d in raw_kw if "Di động Máy tính bảng" not in d.get("text", "") and "Pick the Right" not in d.get("text", "")]
                for rank, doc in enumerate(keyword_docs, 1):
                    doc_id = _candidate_id(doc, rank, "k")
                    if doc_id not in candidate_map:
                        candidate_map[doc_id] = doc
                    keyword_ranks[doc_id] = rank
        except Exception as e:
            print("Keyword search retrieve warning:", e)

    if not candidate_map and _mongo is not None:
        raw_docs = list(_mongo[DB][COLL].find().limit(top_k))
        for rank, doc in enumerate(raw_docs, 1):
            doc_id = _candidate_id(doc, rank, "r")
            candidate_map[doc_id] = doc
            vector_ranks[doc_id] = rank

    # 3. Reciprocal Rank Fusion (RRF) & Re-ranking Stage
    rrf_k = 60
    scored_candidates = []
    q_words = set(re.findall(r'\w+', question.lower()))
    q_normalized = _normalize(question)
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
        normalized_title = _normalize(doc.get("title", ""))
        title_overlap = sum(
            1 for word in {_normalize(w) for w in q_words}
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
        # A full major name in the query is stronger evidence than generic
        # overlaps such as "thông tin" (which also appears in An toàn thông tin).
        major_title = re.sub(r"^nganh\s+", "", normalized_title)
        major_title = re.sub(r"\s+huit cong tuyen sinh chinh thuc.*$", "", major_title)
        exact_major_boost = (
            0.8
            if metadata["category"] == "major"
            and len(major_title) >= 4
            and major_title in q_normalized
            else 0.0
        )
        # Career alignment boost to match user intent to proper faculty/program docs
        career_boost = 0.0
        norm_text = _normalize(text_content)
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
    docs = [item[1] for item in scored_candidates if item[0] >= 0.15][:top_k]

    # 4. General tuition heuristic fallback
    q_lower = question.lower()
    if intent == "tuition":
        general_tuition_doc = {
            "_id": "huit_general_tuition_override",
            "title": "Chính sách & Mức Học phí HUIT (ĐH Công Thương TP.HCM)",
            "text": "[Trường Đại học Công Thương TP.HCM (HUIT) | Nguồn chính thức ts.huit.edu.vn | Chủ đề: Học phí K26 năm 2026]\nHọc phí khóa K26 năm 2026 là 1.100.000 đồng/tín chỉ lý thuyết và 1.350.000 đồng/tín chỉ thực hành. Học phí toàn khóa của các ngành cử nhân phổ biến khoảng 143–148 triệu đồng; chương trình kỹ sư khoảng 177–188 triệu đồng, tùy chương trình và cơ cấu tín chỉ.",
            "url": "https://ts.huit.edu.vn/47159/hoc-phi-huit-nam-2026-minh-bach-thong-tin-dong-hanh-cung-nguoi-hoc",
            "source_url": "https://ts.huit.edu.vn/47159/hoc-phi-huit-nam-2026-minh-bach-thong-tin-dong-hanh-cung-nguoi-hoc",
            "category": "tuition",
            "year": 2026,
            "score": 0.99
        }
        if not any(d.get("_id") == general_tuition_doc["_id"] for d in docs):
            docs.insert(0, general_tuition_doc)

    if intent == "cutoff" or "diem nay" in q_normalized:
        cutoff_doc = {
            "_id": "huit_2026_cutoff_override",
            "title": "Điểm sàn xét tuyển đại học HUIT năm 2026",
            "text": (
                "[Trường Đại học Công Thương TP.HCM (HUIT) | Nguồn chính thức "
                "ts.huit.edu.vn | Chủ đề: Điểm sàn năm 2026]\n"
                "Điểm thi tốt nghiệp THPT: Luật và Luật kinh tế 20 điểm; "
                "các ngành còn lại 16 điểm. Xét học bạ: 20 điểm. "
                "Đánh giá năng lực ĐHQG-HCM: nhóm Luật 720 điểm, các ngành "
                "còn lại 600 điểm. Đây là điểm sàn, chưa phải điểm trúng tuyển."
            ),
            "url": (
                "https://ts.huit.edu.vn/thong-bao/"
                "diem-san-xet-tuyen-dai-hoc-nam-2026-"
                "truong-dai-hoc-cong-thuong-tp-hcm"
            ),
            "source_url": (
                "https://ts.huit.edu.vn/thong-bao/"
                "diem-san-xet-tuyen-dai-hoc-nam-2026-"
                "truong-dai-hoc-cong-thuong-tp-hcm"
            ),
            "category": "cutoff",
            "year": 2026,
            "score": 0.99,
        }
        docs = [
            doc for doc in docs
            if doc.get("_id") != cutoff_doc["_id"]
            and doc.get("category") != "cutoff"
        ]
        docs.insert(0, cutoff_doc)

    unique_docs = []
    seen_sources = set()
    for doc in docs:
        identity = (
            doc.get("source_url") or doc.get("url"),
            doc.get("category"),
        )
        if identity in seen_sources:
            continue
        seen_sources.add(identity)
        unique_docs.append(doc)
    return unique_docs[:top_k]


def _clean_llm_text(text):
    if not text:
        return ""
    # Strip unwanted system headers / preambles like "User Safety: safe", "<think>...", "Here is the answer:"
    text = re.sub(r"^(User Safety:\s*safe|User Safety:\s*\w+|Safety status:\s*\w+)\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"^<think>.*?</think>\s*", "", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"^(here is the answer|we need to answer|here's the response):\s*", "", text, flags=re.IGNORECASE)
    return text.strip()


def _call_llm(system_prompt, user_prompt):
    msgs = [{"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}]
    
    # 1. Ưu tiên OpenRouter API Key nếu được cấu hình
    or_key = os.environ.get("HUIT_OPENROUTER_KEY") or os.environ.get("OPENROUTER_API_KEY")
    if not or_key:
        raise RuntimeError("HUIT_OPENROUTER_KEY chưa được cấu hình.")
    from openai import OpenAI
    client = OpenAI(api_key=or_key, base_url="https://openrouter.ai/api/v1")
    
    # Chuỗi ưu tiên các mô hình siêu nhanh & hoạt động 100% trên OpenRouter
    models_to_try = [
        "google/gemma-4-26b-a4b-it:free",
        "google/gemma-4-31b-it:free",
        "openrouter/free",
        "nvidia/nemotron-3-nano-30b-a3b:free",
        "inclusionai/ling-3.0-flash:free",
        "openai/gpt-oss-20b:free",
        LLM_MODEL,
    ]
    unique_models = []
    for m in models_to_try:
        if m and m not in unique_models:
            unique_models.append(m)

    last_error = None
    for model_name in unique_models:
        try:
            r = client.chat.completions.create(
                model=model_name,
                messages=msgs,
                temperature=0.3,
                max_tokens=LLM_MAX_TOKENS,
                timeout=35,
            )
            if r and r.choices and r.choices[0].message.content:
                content = r.choices[0].message.content.strip()
                content = _clean_llm_text(content)
                leaked_reasoning = (
                    content.lower().startswith(("we need to answer", "we need answer"))
                    or "must end with a short question" in content.lower()
                    or "provide answer in vietnamese" in content.lower()
                )
                if leaked_reasoning or len(content) < 25:
                    continue
                return content
        except Exception as e:
            print(f"OpenRouter model '{model_name}' warning:", e)
            last_error = e
            continue

    raise RuntimeError(f"Tất cả mô hình OpenRouter đều tạm thời gián đoạn. Lỗi gần nhất: {last_error}")


def _stream_llm(system_prompt, user_prompt):
    msgs = [{"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}]
    
    or_key = os.environ.get("HUIT_OPENROUTER_KEY") or os.environ.get("OPENROUTER_API_KEY")
    if not or_key:
        raise RuntimeError("HUIT_OPENROUTER_KEY chưa được cấu hình.")
    from openai import OpenAI
    client = OpenAI(api_key=or_key, base_url="https://openrouter.ai/api/v1")
    
    models_to_try = [
        "google/gemma-4-26b-a4b-it:free",
        "google/gemma-4-31b-it:free",
        "openrouter/free",
        "nvidia/nemotron-3-nano-30b-a3b:free",
        "inclusionai/ling-3.0-flash:free",
        "openai/gpt-oss-20b:free",
        LLM_MODEL,
    ]
    unique_models = []
    for m in models_to_try:
        if m and m not in unique_models:
            unique_models.append(m)

    last_error = None
    for model_name in unique_models:
        try:
            stream = client.chat.completions.create(
                model=model_name,
                messages=msgs,
                temperature=0.3,
                max_tokens=LLM_MAX_TOKENS,
                timeout=25,
                stream=True,
            )
            
            buffer = ""
            header_cleaned = False
            token_yielded_count = 0

            for chunk in stream:
                if chunk.choices and len(chunk.choices) > 0 and chunk.choices[0].delta:
                    token = chunk.choices[0].delta.content or ""
                    if not token:
                        continue
                    
                    if not header_cleaned:
                        buffer += token
                        if len(buffer) >= 50 or "\n" in buffer:
                            cleaned_buffer = _clean_llm_text(buffer)
                            header_cleaned = True
                            if cleaned_buffer:
                                token_yielded_count += 1
                                yield cleaned_buffer
                        continue
                    else:
                        token_yielded_count += 1
                        yield token

            if not header_cleaned and buffer:
                cleaned_buffer = _clean_llm_text(buffer)
                if cleaned_buffer:
                    token_yielded_count += 1
                    yield cleaned_buffer

            if token_yielded_count > 0:
                return

        except Exception as e:
            print(f"OpenRouter streaming model '{model_name}' warning:", e)
            last_error = e
            continue

    raise RuntimeError(f"Tất cả mô hình OpenRouter đều tạm thời gián đoạn. Lỗi gần nhất: {last_error}")


def check_intent_guardrail(question, chat_history=None):
    q_norm = _normalize(question)
    words = [w for w in re.split(r'\s+', q_norm) if w]
    num_words = len(words)

    # 0. Personal Identity Questions (Nhận diện câu hỏi cá nhân / định danh)
    is_personal_identity = (
        ("la ai" in q_norm or "ten gi" in q_norm)
        and any(p in q_norm for p in ["toi", "em", "minh", "tui", "tao", "who", "i am", "my name"])
        and not any(k in q_norm for k in ["huit", "nganh", "truong", "khoa", "hieu truong", "bo truong", "giao su", "tien si"])
    ) or any(term in q_norm for term in ["ban biet toi", "ban biet em", "ban biet minh", "co biet toi", "co biet em", "co biet minh", "know who i am", "who am i"])
    
    if is_personal_identity:
        return {
            "is_handled": True,
            "answer": (
                "Tôi không biết thông tin cá nhân của bạn do hệ thống không lưu giữ dữ liệu riêng tư. "
                "Mình là AI Tư vấn Tuyển sinh chính thức của Trường Đại học Công Thương TP.HCM (HUIT). "
                "Mình có thể hỗ trợ bạn chọn ngành học, tra cứu phương thức xét tuyển, điểm sàn, học phí và học bổng. "
                "Bạn cần mình hỗ trợ thông tin gì hôm nay?"
            ),
            "sources": []
        }
    
    # 1. Greetings / Small talk (Xử lý các câu chào hỏi: alo, alo bạn, banj, chào, hi, hello, v.v.)
    greeting_tokens = {
        "chao", "xin chao", "hello", "hi", "hey", "helo", "heloo", "alo", "aloo", "aloooo", "alof",
        "banj", "ban", "ban oi", "banj oi", "ad oi", "bot oi", "chao ban", "chao b", "chai b",
        "chao ad", "hi ad", "hello ad", "hi ban", "hello ban", "da", "da chao", "tu van giup",
        "tu van cho minh", "cho em hoi", "cho minh hoi", "cho hoi", "ban la ai", "ban ten gi"
    }
    
    is_greeting = (
        q_norm in greeting_tokens
        or (num_words <= 5 and any(w in {"alo", "aloo", "aloooo", "chao", "hi", "hello", "banj", "ban", "ad"} for w in words))
        or (num_words <= 4 and any(g in q_norm for g in greeting_tokens if len(g) >= 3))
    )
    
    if is_greeting and not any(kw in q_norm for kw in ["huit", "nganh", "hoc phi", "diem san", "xet tuyen", "diem chuan", "hoc bong"]):
        return {
            "is_handled": True,
            "answer": (
                "Chào bạn! Mình là Trợ lý AI Tư vấn Tuyển sinh chính thức của Trường Đại học Công Thương TP.HCM (HUIT).\n\n"
                "Mình có thể giúp bạn tìm hiểu 39 ngành học đại học chính quy, phương thức xét tuyển 2026, điểm sàn, học phí và chính sách học bổng.\n\n"
                "Bạn đang quan tâm đến ngành học nào hoặc cần mình hỗ trợ thông tin gì?"
            ),
            "sources": []
        }

    # 2. Out of scope filter (chỉ chặn những chủ đề hoàn toàn không liên quan)
    out_of_scope = [
        "thoi tiet", "viet code", "javascript", "python", "giai bai",
        "phuong trinh", "bong da", "choi game", "lien minh", "bitcoin",
        "chung khoan", "tong thong", "bong den", "nau pho", "thuc don",
        "giam can", "tho tinh", "chuyen kinh di", "dich cau",
        "laptop gaming",
    ]
    in_scope = [
        "huit", "cong thuong", "tuyen sinh", "xet tuyen", "hoc ba",
        "diem san", "diem chuan", "nganh", "ma nganh", "to hop",
        "hoc phi", "tin chi", "hoc bong", "mien giam", "ky tuc xa",
        "dia chi truong", "co so", "hotline", "nhap hoc", "ho so",
        "thoi gian dao tao", "chuong trinh dao tao",
        "chon nganh", "hoc gi", "phu hop", "huong nghiep", "nghe nghiep",
        "viec lam", "lap trinh", "du lieu", "robot", "tu dong hoa",
        "moi truong", "o nhiem", "nuoc thai", "khach san", "marketing",
        "logistics", "ai", "cntt", "luat", "thuc pham", "kinh te",
        "con gai", "nam sinh", "so thich", "thich", "dam me",
    ]
    clearly_outside = any(term in q_norm for term in out_of_scope)
    has_huit_context = any(term in q_norm for term in in_scope)
    has_history = bool(chat_history)
    
    if clearly_outside:
        return {
            "is_handled": True,
            "answer": (
                "Câu này nằm ngoài phần thông tin tuyển sinh HUIT mà mình có thể kiểm chứng. "
                "Nếu bạn cần, mình có thể hỗ trợ tư vấn chọn ngành, xem phương thức xét tuyển, điểm sàn hoặc học phí HUIT nhé!"
            ),
            "sources": []
        }

    # 3. Short ambiguous phrase handling (Ví dụ từ gõ quá ngắn 1-2 từ không có ngữ cảnh)
    if num_words <= 2 and not has_huit_context and not has_history:
        return {
            "is_handled": True,
            "answer": (
                "Chào bạn! Mình là Trợ lý AI Tư vấn Tuyển sinh HUIT.\n\n"
                "Mình chưa hiểu rõ câu hỏi của bạn. Bạn có thể nhập câu hỏi chi tiết hơn "
                "(ví dụ: *'Mã ngành CNTT'*, *'Điểm sàn năm 2026'*, *'Học phí HUIT bao nhiêu?'*) "
                "để mình tư vấn chính xác nhất nhé!"
            ),
            "sources": []
        }

    return {"is_handled": False}


def _is_major_catalog_question(question):
    q_norm = _normalize(question)
    catalog_phrases = [
        "danh sach nganh",
        "nhung nganh",
        "cac nganh",
        "co nganh nao",
        "bao nhieu nganh",
        "nganh dao tao nao",
    ]
    return any(phrase in q_norm for phrase in catalog_phrases)


def _major_catalog_response():
    """Return the complete official catalog instead of asking vector search for one hit."""
    docs = list(
        _mongo[DB][COLL].find(
            {
                "category": "major",
                "major_code": {"$exists": True, "$ne": None},
            },
            {
                "_id": 0,
                "page_title": 1,
                "title": 1,
                "major_code": 1,
                "source_url": 1,
                "url": 1,
            },
        )
    )
    majors = {}
    for doc in docs:
        code = str(doc.get("major_code") or "").strip()
        title = str(doc.get("page_title") or doc.get("title") or "").strip()
        title = re.sub(r"^Ngành\s+", "", title, flags=re.IGNORECASE)
        title = re.sub(r"\s*\(HUIT.*$", "", title).strip()
        if code and title:
            majors[code] = title

    if not majors:
        return None

    ordered = sorted(majors.items(), key=lambda item: _normalize(item[1]))
    lines = "\n".join(
        f"{index}. **{title}** ({code})"
        for index, (code, title) in enumerate(ordered, 1)
    )
    return {
        "answer": (
            f"HUIT hiện công bố **{len(ordered)} ngành đào tạo đại học chính quy** "
            f"trong danh mục tuyển sinh 2026:\n\n{lines}\n\n"
            "Bạn muốn mình tư vấn sâu hơn về ngành nào?"
        ),
        "sources": [{
            "i": 1,
            "title": "Danh mục ngành đào tạo đại học chính quy HUIT",
            "url": "https://ts.huit.edu.vn/nganh-dao-tao/dai-hoc",
            "score": 1.0,
            "text": f"Danh mục {len(ordered)} ngành đào tạo đại học chính quy HUIT.",
        }],
        "meta": {
            "intent": "major",
            "fallback": False,
            "deterministic": True,
            "model": LLM_MODEL,
            "kb_version": KB_VERSION,
            "rag_version": RAG_VERSION,
        },
    }


def _cache_key(question, chat_history=None):
    relevant_history = []
    if isinstance(chat_history, list):
        for turn in chat_history[-4:]:
            if isinstance(turn, dict):
                relevant_history.append({
                    "role": turn.get("role"),
                    "content": str(turn.get("content", ""))[:500],
                })
    payload = json.dumps(
        {
            "question": _normalize(question),
            "history": relevant_history,
            "kb_version": KB_VERSION,
            "rag_version": RAG_VERSION,
            "model": LLM_MODEL,
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def get_cached_response(question, chat_history=None):
    _init()
    ckey = _cache_key(question, chat_history)
    now_ts = time.time()
    
    # 1. Kiểm tra RAM Cache tức thì (0ms)
    if ckey in _ram_cache and _ram_cache_expiry.get(ckey, 0) > now_ts:
        res = copy.deepcopy(_ram_cache[ckey])
        res["cached"] = True
        res["meta"]["ram_cached"] = True
        return res

    # 2. Fallback sang MongoDB Cache nếu RAM cache lỡ miss
    if _mongo is not None:
        try:
            now = datetime.now(timezone.utc)
            cached = _mongo[DB]["query_cache"].find_one({
                "cache_key": ckey,
                "expires_at": {"$gt": now},
            })
            if cached:
                res = {
                    "answer": cached["answer"],
                    "sources": cached.get("sources", []),
                    "trace": cached.get("trace", []),
                    "cached": True,
                    "meta": cached.get("meta", {}),
                }
                # Pre-fill RAM cache
                _ram_cache[ckey] = res
                _ram_cache_expiry[ckey] = now_ts + (CACHE_TTL_HOURS * 3600)
                return res
        except Exception as e:
            print("Cache lookup warning:", e)
    return None


def save_response_to_cache(question, response_data, chat_history=None):
    _init()
    if response_data and response_data.get("answer"):
        ckey = _cache_key(question, chat_history)
        now_ts = time.time()
        # Lưu RAM cache tức thì
        _ram_cache[ckey] = copy.deepcopy(response_data)
        _ram_cache_expiry[ckey] = now_ts + (CACHE_TTL_HOURS * 3600)

        # Lưu MongoDB persistent cache
        if _mongo is not None:
            try:
                now = datetime.now(timezone.utc)
                _mongo[DB]["query_cache"].update_one(
                    {"cache_key": ckey},
                    {"$set": {
                        "cache_key": ckey,
                        "question_clean": _normalize(question),
                        "original_question": question,
                        "answer": response_data["answer"],
                        "sources": response_data.get("sources", []),
                        "trace": response_data.get("trace", []),
                        "meta": response_data.get("meta", {}),
                        "kb_version": KB_VERSION,
                        "rag_version": RAG_VERSION,
                        "model": LLM_MODEL,
                        "updated_at": now,
                        "expires_at": now + timedelta(hours=CACHE_TTL_HOURS),
                    }},
                    upsert=True
                )
            except Exception as e:
                print("Save cache warning:", e)


def log_event(question, response_data, elapsed_ms, intent, cached=False, error=None):
    if _mongo is None:
        return
    try:
        _mongo[DB]["rag_events"].insert_one({
            "created_at": datetime.now(timezone.utc),
            "question": str(question)[:800],
            "question_hash": hashlib.sha256(_normalize(question).encode("utf-8")).hexdigest(),
            "intent": intent,
            "cached": cached,
            "fallback": bool(response_data.get("meta", {}).get("fallback")),
            "source_count": len(response_data.get("sources", [])),
            "source_titles": [s.get("title", "")[:160] for s in response_data.get("sources", [])],
            "answer_length": len(response_data.get("answer", "")),
            "elapsed_ms": elapsed_ms,
            "model": LLM_MODEL,
            "kb_version": KB_VERSION,
            "rag_version": RAG_VERSION,
            "error": str(error)[:500] if error else None,
        })
    except Exception as exc:
        print("Event logging warning:", exc)


def _fallback_answer(question, docs):
    """Create a concise grounded answer when LLM streaming is unavailable or truncated."""
    if not docs:
        return "Hiện chưa tìm thấy thông tin chi tiết phù hợp trong kho tri thức tuyển sinh HUIT. Bạn vui lòng đặt câu hỏi cụ thể hơn hoặc liên hệ hotline Cổng tuyển sinh HUIT nhé!"

    q_normalized = _normalize(question)
    intent = classify_intent(question)

    # 1. Tuition
    if intent == "tuition" or any(k in q_normalized for k in ["hoc phi", "tin chi", "tien hoc", "muc phi", "chi phi"]):
        return (
            "Theo công bố cho khóa K26 năm 2026, học phí HUIT là "
            "**1.100.000 đồng/tín chỉ lý thuyết** và **1.350.000 đồng/tín chỉ "
            "thực hành**. Các ngành cử nhân phổ biến khoảng **143–148 triệu "
            "đồng/toàn khóa**, chương trình kỹ sư khoảng **177–188 triệu đồng/toàn khóa**. [1]"
        )

    # 2. Cutoff Scores
    if intent == "cutoff" or any(k in q_normalized for k in ["diem san", "diem chuan", "diem trung tuyen"]):
        is_law = "luat" in q_normalized
        if "danh gia nang luc" in q_normalized:
            score = "720" if is_law else "600"
            return (
                f"Điểm sàn Đánh giá năng lực ĐHQG-HCM năm 2026 HUIT là **{score} điểm** "
                f"cho {'nhóm Luật và Luật kinh tế' if is_law else 'các ngành ngoài nhóm Luật'}. [1]"
            )
        score = "20" if is_law else "16"
        return (
            f"Điểm sàn xét điểm thi THPT năm 2026 HUIT là **{score} điểm** "
            f"cho {'nhóm Luật' if is_law else 'các ngành ngoài nhóm Luật'}. Điểm sàn xét học bạ là 20 điểm. [1]"
        )

    # 3. Admission methods
    if intent == "admission" or any(k in q_normalized for k in ["phuong thuc", "xet hoc ba", "tuyen thang"]):
        return (
            "Năm 2026, HUIT áp dụng 5 phương thức xét tuyển: 1) Điểm thi tốt nghiệp THPT, "
            "2) Học bạ THPT (lớp 10, 11 và HK1 lớp 12), 3) Đánh giá năng lực ĐHQG-HCM, "
            "4) Tuyển thẳng theo quy định Bộ GD&ĐT, 5) Bài thi năng lực chuyên biệt ĐH Sư phạm TP.HCM kết hợp học bạ. [1]"
        )

    # 4. Career Orientation Topic matching
    # A. English / Languages
    if any(k in q_normalized for k in ["tieng anh", "ngon ngu anh", "anh van", "ngoai ngu", "tieng trung"]):
        return (
            "Nếu bạn yêu thích tiếng Anh và ngôn ngữ, tại **Trường Đại học Công Thương TP.HCM (HUIT)** bạn có thể tham khảo 2 ngành đào tạo chuẩn mực:\n\n"
            "1. **Ngành Ngôn ngữ Anh** (Mã ngành: `7220201`): Đào tạo chuyên sâu về Tiếng Anh thương mại, biên - phiên dịch, giảng dạy và truyền thông doanh nghiệp.\n"
            "2. **Ngành Ngôn ngữ Trung Quốc** (Mã ngành: `7220204`): Đào tạo tiếng Trung thương mại, dịch thuật và thương mại quốc tế.\n\n"
            "Cả 2 ngành đều áp dụng các phương thức xét tuyển học bạ, điểm thi THPT và ĐGNL năm 2026. Bạn muốn xem chi tiết tổ hợp môn ngành nào? [1]"
        )

    # B. Cooking / Culinary / Food
    if any(k in q_normalized for k in ["nau an", "lam banh", "am thuc", "dau bep", "nha hang", "che bien"]):
        return (
            "Nếu bạn yêu thích ẩm thực, nấu ăn và kỹ thuật chế biến món ăn, HUIT đào tạo các ngành rất phù hợp:\n\n"
            "1. **Ngành Quản trị dịch vụ ăn uống và kỹ thuật chế biến món ăn** (Mã ngành: `7810202`): Đào tạo nghệ thuật ẩm thực Á - Âu, kỹ thuật chế biến món ăn và quản lý nhà hàng [1].\n"
            "2. **Ngành Quản trị nhà hàng và dịch vụ ăn uống** (Mã ngành: `7810206`)\n"
            "3. **Ngành Công nghệ thực phẩm** (Mã ngành: `7540101`)\n\n"
            "Bạn muốn tra cứu thêm thông tin về tổ hợp môn hay phương thức xét tuyển ngành nào?"
        )

    # C. IT / AI / Tech
    if any(k in q_normalized for k in ["cntt", "it", "lap trinh", "game", "ai", "tri tue nhan tao", "data", "an toan thong tin", "code"]):
        return (
            "Nếu bạn quan tâm đến công nghệ thông tin và lập trình, HUIT đào tạo các ngành thuộc khối ngành công nghệ cao:\n\n"
            "1. **Ngành Công nghệ thông tin** (Mã ngành: `7480201`): Lập trình phần mềm, ứng dụng di động, hệ thống mạng.\n"
            "2. **Ngành Trí tuệ nhân tạo** (Mã ngành: `7480107`): Học máy, xử lý dữ liệu lớn, phân tích dữ liệu thông minh và AI.\n"
            "3. **Ngành An toàn thông tin** (Mã ngành: `7480202`): Bảo mật thông tin, an ninh mạng.\n\n"
            "Bạn cần tư vấn chi tiết về điểm sàn hay tổ hợp xét tuyển của ngành nào? [1]"
        )

    # D. Fashion / Garments
    if any(k in q_normalized for k in ["vay", "dam", "may mac", "thoi trang", "trang phuc", "may rap"]):
        return (
            "Nếu bạn yêu thích thiết kế váy, quần áo hoặc thời trang, tại **Trường Đại học Công Thương TP.HCM (HUIT)** bạn có thể lựa chọn 2 ngành đào tạo phù hợp nhất:\n\n"
            "1. **Ngành Công nghệ dệt, may** (Mã ngành: `7540204`): Đào tạo chuyên sâu về thiết kế rập 2D/3D (Gerber, Lectra), quản lý dây chuyền sản xuất may công nghiệp.\n"
            "2. **Ngành Kinh doanh thời trang và dệt may** (Mã ngành: `7340123`): Đào tạo về kinh doanh chuỗi thời trang, Marketing thời trang và quản lý chuỗi cung ứng dệt may.\n\n"
            "Bạn muốn mình tư vấn thêm về tổ hợp xét tuyển hay chương trình học ngành nào? [1]"
        )

    # 5. Dynamic fallback matching TOP retrieved docs
    relevant_majors = []
    for d in docs[:3]:
        t = _clean_doc_title(d.get("title"))
        if t and t not in relevant_majors and "Thông tin Tuyển sinh" not in t:
            relevant_majors.append(f"• **{t}**")

    if relevant_majors:
        majors_list_str = "\n".join(relevant_majors)
        return (
            f"Dựa trên thông tin tuyển sinh chính thức của HUIT, dưới đây là các ngành đào tạo liên quan phù hợp nhất với yêu cầu của bạn:\n\n"
            f"{majors_list_str}\n\n"
            "Bạn muốn mình tư vấn chi tiết hơn về mã ngành, tổ hợp môn hay điểm sàn của ngành nào? [1]"
        )

    return (
        "Cổng thông tin tuyển sinh HUIT hiện công bố đầy đủ 39 ngành đào tạo đại học chính quy năm 2026. "
        "Bạn vui lòng cho biết rõ tên ngành hoặc câu hỏi cụ thể để mình tư vấn chính xác nhất nhé! [1]"
    )


def answer(question, chat_history=None, use_cache=True):
    started = time.perf_counter()
    _init()
    intent = classify_intent(question)

    # 1. Intent Guardrail Check
    guard_res = check_intent_guardrail(question, chat_history=chat_history)
    if guard_res["is_handled"]:
        return guard_res

    # Câu hỏi liệt kê cần toàn bộ danh mục; vector search chỉ phù hợp tìm vài
    # tài liệu gần nhất và từng khiến câu trả lời chỉ có một ngành.
    if _is_major_catalog_question(question):
        catalog_res = _major_catalog_response()
        if catalog_res:
            log_event(
                question,
                catalog_res,
                int((time.perf_counter() - started) * 1000),
                intent,
            )
            return catalog_res

    # 2. Semantic Cache Check
    cached_res = get_cached_response(question, chat_history) if use_cache else None
    if cached_res:
        log_event(
            question,
            cached_res,
            int((time.perf_counter() - started) * 1000),
            intent,
            cached=True,
        )
        return cached_res

    retrieval_query = question
    if chat_history and isinstance(chat_history, list) and len(question.split()) <= 8:
        user_msgs = [
            m.get("content", "") for m in chat_history
            if isinstance(m, dict) and m.get("role") in ("user", "human") and m.get("content")
        ]
        if user_msgs:
            last_user_msg = user_msgs[-1]
            retrieval_query = f"{last_user_msg} {question}"

    docs = retrieve(retrieval_query, _rag_cfg.get("top_k", 3))
    grounded_docs = docs
    
    if not docs:
        res = {"answer": "Không tìm thấy dữ liệu liên quan trong kho tri thức tuyển sinh HUIT.", "sources": []}
        return res

    source_limit = min(3, len(grounded_docs))
    sources = [{
        "i": i,
        "title": _clean_doc_title(d.get("title")),
        "url": d.get("source_url") or d.get("url") or d.get("link") or "https://ts.huit.edu.vn",
        "score": round(d.get("score", 0), 3),
        "text": d.get("text", "")[:300]
    } for i, d in enumerate(grounded_docs[:source_limit], 1)]

    # Use a few focused excerpts so the response can compare facts naturally.
    context = "\n\n".join(
        f"[{i}] {_clean_doc_title(d.get('title'))} — {str(d.get('text', ''))[:1100]}"
        for i, d in enumerate(grounded_docs[:source_limit], 1)
    )

    history_str = ""
    if chat_history and isinstance(chat_history, list):
        formatted_turns = []
        for turn in chat_history[-6:]:
            role = "Người dùng" if turn.get("role") == "user" else "Trợ lý AI"
            formatted_turns.append(f"{role}: {turn.get('content', '')}")
        if formatted_turns:
            history_str = "\n\n[LỊCH SỬ HỘI THOẠI TRƯỚC ĐÓ]:\n" + "\n".join(formatted_turns) + "\n"
    
    used_fallback = False
    try:
        user_prompt = f"{history_str}{_rag_cfg['answer_template'].format(context=context, question=question)}"
        text = _call_llm(_rag_cfg["system_prompt"], user_prompt)
    except Exception:
        used_fallback = True
        text = _fallback_answer(question, docs)
    
    elapsed_ms = round((time.perf_counter() - started) * 1000)
    trace = [
        {"step": 1, "name": "Nhận diện Ý định (NLU)", "detail": f"Ý định: {intent}", "status": "success"},
        {"step": 2, "name": "Truy vấn Kho tri thức HUIT", "detail": f"Vector Search & Keyword: Lấy {len(docs)} đoạn tri thức", "status": "success"},
        {"step": 3, "name": "Tối ưu & Xếp hạng Ngữ cảnh", "detail": f"Lọc {len(sources)} nguồn minh chứng khớp nhất", "status": "success"},
        {"step": 4, "name": "Tổng hợp qua LLM", "detail": f"Mô hình: {LLM_MODEL} ({'Chế độ fallback' if used_fallback else 'Hoàn tất'})", "status": "warning" if used_fallback else "success"}
    ]

    res = {
        "answer": text,
        "sources": sources,
        "trace": trace,
        "meta": {
            "intent": intent,
            "fallback": used_fallback,
            "model": LLM_MODEL,
            "kb_version": KB_VERSION,
            "rag_version": RAG_VERSION,
            "latency_ms": elapsed_ms,
        },
    }
    if use_cache:
        save_response_to_cache(question, res, chat_history)
    log_event(
        question,
        res,
        elapsed_ms,
        intent,
    )
    return res


def stream_answer(question, chat_history=None, use_cache=True):
    """Generator function yielding chunks for SSE real-time LLM streaming."""
    started = time.perf_counter()
    _init()
    intent = classify_intent(question)

    # 1. Intent Guardrail Check
    guard_res = check_intent_guardrail(question, chat_history=chat_history)
    if guard_res["is_handled"]:
        answer_text = guard_res.get("answer", "")
        sources = guard_res.get("sources", [])
        trace = guard_res.get("trace", [])
        yield json.dumps({"type": "meta", "sources": sources, "trace": trace}, ensure_ascii=False) + "\n"
        for word in re.findall(r'\S+|\s+', answer_text):
            yield json.dumps({"type": "token", "token": word}, ensure_ascii=False) + "\n"
        return

    # 2. Major Catalog Check
    if _is_major_catalog_question(question):
        catalog_res = _major_catalog_response()
        if catalog_res:
            answer_text = catalog_res.get("answer", "")
            sources = catalog_res.get("sources", [])
            trace = catalog_res.get("trace", [])
            yield json.dumps({"type": "meta", "sources": sources, "trace": trace}, ensure_ascii=False) + "\n"
            for word in re.findall(r'\S+|\s+', answer_text):
                yield json.dumps({"type": "token", "token": word}, ensure_ascii=False) + "\n"
            log_event(question, catalog_res, int((time.perf_counter() - started) * 1000), intent)
            return

    # 3. Cache Hit Check (Ultra fast 0ms TTFT response)
    cached_res = get_cached_response(question, chat_history) if use_cache else None
    if cached_res:
        answer_text = cached_res.get("answer", "")
        sources = cached_res.get("sources", [])
        trace = cached_res.get("trace", [])
        yield json.dumps({"type": "meta", "sources": sources, "trace": trace}, ensure_ascii=False) + "\n"
        for word in re.findall(r'\S+|\s+', answer_text):
            yield json.dumps({"type": "token", "token": word}, ensure_ascii=False) + "\n"
        log_event(question, cached_res, int((time.perf_counter() - started) * 1000), intent, cached=True)
        return

    # 4. Retrieval Phase
    retrieval_query = question
    if chat_history and isinstance(chat_history, list) and len(question.split()) <= 8:
        user_msgs = [
            m.get("content", "") for m in chat_history
            if isinstance(m, dict) and m.get("role") in ("user", "human") and m.get("content")
        ]
        if user_msgs:
            last_user_msg = user_msgs[-1]
            retrieval_query = f"{last_user_msg} {question}"

    docs = retrieve(retrieval_query, _rag_cfg.get("top_k", 3))
    if not docs:
        res = {"answer": "Không tìm thấy dữ liệu liên quan trong kho tri thức tuyển sinh HUIT.", "sources": []}
        yield json.dumps({"type": "meta", "sources": [], "trace": []}, ensure_ascii=False) + "\n"
        yield json.dumps({"type": "token", "token": res["answer"]}, ensure_ascii=False) + "\n"
        return

    source_limit = min(3, len(docs))
    sources = [{
        "i": i,
        "title": _clean_doc_title(d.get("title")),
        "url": d.get("source_url") or d.get("url") or d.get("link") or "https://ts.huit.edu.vn",
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
        {"step": 4, "name": "Tổng hợp qua LLM", "detail": f"Mô hình: {LLM_MODEL} (Phát luồng thời gian thực)", "status": "success"}
    ]

    # Send metadata to client immediately after retrieval (~200ms)
    yield json.dumps({"type": "meta", "sources": sources, "trace": trace}, ensure_ascii=False) + "\n"

    # 5. Stream Real LLM Tokens
    user_prompt = f"{history_str}{_rag_cfg['answer_template'].format(context=context, question=question)}"
    accumulated_text = ""
    used_fallback = False

    try:
        for token_chunk in _stream_llm(_rag_cfg["system_prompt"], user_prompt):
            accumulated_text += token_chunk
            yield json.dumps({"type": "token", "token": token_chunk}, ensure_ascii=False) + "\n"
    except Exception as exc:
        print("Streaming LLM error:", exc)

    cleaned_acc = _clean_llm_text(accumulated_text)
    if not cleaned_acc or len(cleaned_acc) < 25:
        used_fallback = True
        fallback_text = _fallback_answer(question, docs)
        accumulated_text = fallback_text
        for word in re.findall(r'\S+|\s+', fallback_text):
            yield json.dumps({"type": "token", "token": word}, ensure_ascii=False) + "\n"
    else:
        accumulated_text = cleaned_acc

    elapsed_ms = round((time.perf_counter() - started) * 1000)
    res_obj = {
        "answer": accumulated_text,
        "sources": sources,
        "trace": trace,
        "meta": {
            "intent": intent,
            "fallback": used_fallback,
            "model": LLM_MODEL,
            "kb_version": KB_VERSION,
            "rag_version": RAG_VERSION,
            "latency_ms": elapsed_ms,
        }
    }
    if use_cache and accumulated_text:
        save_response_to_cache(question, res_obj, chat_history)
    log_event(question, res_obj, elapsed_ms, intent)

