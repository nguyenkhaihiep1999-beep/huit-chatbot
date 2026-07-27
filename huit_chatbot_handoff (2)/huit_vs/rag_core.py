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

from pymongo import MongoClient

USER = "nguyenkhaihiep1999_db_user"
HOST = "cluster0.hyj8rab.mongodb.net"
DB = "huit_chatbot"
COLL = "huit_kb"
MODEL = "intfloat/multilingual-e5-large"
DIMS = 1024
LLM_MODEL = os.environ.get("OPENROUTER_MODEL", "qwen/qwen-2.5-72b-instruct")
LLM_MAX_TOKENS = int(os.environ.get("LLM_MAX_TOKENS", "350"))
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


def _init():
    global _embedder, _mongo, _retrieval_pipeline, _rag_cfg
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
    text = unicodedata.normalize("NFD", str(text or "").lower())
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
        "diem cntt", "diem it",
    ),
    "scholarship": ("hoc bong", "giam hoc phi", "mien hoc phi"),
    "admission": (
        "phuong thuc xet tuyen", "xet tuyen", "xet hoc ba",
        "danh gia nang luc",
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
    for intent in ("scholarship", "cutoff", "tuition", "admission", "contact"):
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

    # 1. Dense Vector Search (E5-Large 1024D)
    vector_docs = []
    if _embedder and _retrieval_pipeline and _mongo is not None:
        try:
            pipeline = copy.deepcopy(_retrieval_pipeline)
            # multilingual-e5-large expects the asymmetric "query:" prefix;
            # KB records are embedded with "passage:" during ingestion.
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
        year_boost = 0.2 if requested_years and metadata["year"] in requested_years else 0.0
        year_penalty = -0.12 if requested_years and metadata["year"] and metadata["year"] not in requested_years else 0.0
        final_score = (
            (rrf_score * 10)
            + (overlap_count * 0.05)
            + (title_overlap * 0.15)
            + code_boost
            + intent_boost
            + exact_major_boost
            + year_boost
            + year_penalty
        )
        doc["score"] = round(doc.get("score") or final_score, 4)
        doc["rrf_score"] = round(final_score, 4)
        scored_candidates.append((final_score, doc))

    scored_candidates.sort(key=lambda x: x[0], reverse=True)
    docs = [item[1] for item in scored_candidates if item[0] >= 0.18][:top_k]

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

    if intent == "cutoff":
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


def _call_llm(system_prompt, user_prompt):
    msgs = [{"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}]
    
    # 1. Ưu tiên OpenRouter API Key nếu được cấu hình
    or_key = os.environ.get("HUIT_OPENROUTER_KEY") or os.environ.get("OPENROUTER_API_KEY")
    if not or_key:
        raise RuntimeError("HUIT_OPENROUTER_KEY chưa được cấu hình.")
    from openai import OpenAI
    client = OpenAI(api_key=or_key, base_url="https://openrouter.ai/api/v1")
    
    # Chuỗi ưu tiên các mô hình Qwen 2.5 và fallback linh hoạt
    models_to_try = [
        LLM_MODEL,
        "qwen/qwen-2.5-72b-instruct",
        "qwen/qwen-2.5-coder-32b-instruct",
        "qwen/qwen-2.5-7b-instruct",
        "google/gemma-4-31b-it:free",
        "inclusionai/ling-3.0-flash:free",
        "openrouter/free",
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
                timeout=45,
            )
            if r and r.choices and r.choices[0].message.content:
                content = r.choices[0].message.content.strip()
                leaked_reasoning = (
                    content.lower().startswith(("we need to answer", "we need answer"))
                    or "must end with a short question" in content.lower()
                    or "provide answer in vietnamese" in content.lower()
                )
                if leaked_reasoning:
                    continue
                return content
        except Exception as e:
            print(f"OpenRouter model '{model_name}' warning:", e)
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
    if _mongo is not None:
        try:
            now = datetime.now(timezone.utc)
            cached = _mongo[DB]["query_cache"].find_one({
                "cache_key": _cache_key(question, chat_history),
                "expires_at": {"$gt": now},
            })
            if cached:
                return {
                    "answer": cached["answer"],
                    "sources": cached.get("sources", []),
                    "cached": True,
                    "meta": cached.get("meta", {}),
                }
        except Exception as e:
            print("Cache lookup warning:", e)
    return None


def save_response_to_cache(question, response_data, chat_history=None):
    _init()
    if _mongo is not None and response_data and response_data.get("answer"):
        try:
            now = datetime.now(timezone.utc)
            _mongo[DB]["query_cache"].update_one(
                {"cache_key": _cache_key(question, chat_history)},
                {"$set": {
                    "cache_key": _cache_key(question, chat_history),
                    "question_clean": _normalize(question),
                    "original_question": question,
                    "answer": response_data["answer"],
                    "sources": response_data.get("sources", []),
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
    """Create a concise grounded answer when every configured LLM is unavailable."""
    q_lower = question.lower()
    q_normalized = _normalize(question)
    intent = classify_intent(question)

    if any(k in q_lower for k in ["học phí", "hoc phi", "tiền học", "tín chỉ", "mức phí"]):
        return (
            "Theo công bố cho khóa K26 năm 2026, học phí HUIT là "
            "**1.100.000 đồng/tín chỉ lý thuyết** và **1.350.000 đồng/tín chỉ "
            "thực hành**. Các ngành cử nhân phổ biến khoảng **143–148 triệu "
            "đồng/toàn khóa**, còn chương trình kỹ sư khoảng **177–188 triệu "
            "đồng/toàn khóa**, tùy chương trình và cơ cấu tín chỉ. [1]"
        )

    if intent == "cutoff":
        is_law = "luat" in q_normalized
        if "danh gia nang luc" in q_normalized and "su pham" not in q_normalized:
            score = "720" if is_law else "600"
            return (
                f"Điểm sàn Đánh giá năng lực ĐHQG-HCM năm 2026 là **{score} "
                f"điểm** cho {'nhóm Luật và Luật kinh tế' if is_law else 'các ngành ngoài nhóm Luật'}. "
                "Đây là điểm sàn, chưa phải điểm trúng tuyển. [1]"
            )
        score = "20" if is_law else "16"
        return (
            f"Với điểm thi tốt nghiệp THPT năm 2026, điểm sàn là **{score} "
            f"điểm** cho {'Luật và Luật kinh tế' if is_law else 'các ngành ngoài nhóm Luật'}. "
            "Nếu bạn xét học bạ, mức sàn là 20 điểm; đây chưa phải điểm trúng tuyển. [1]"
        )

    if intent == "admission":
        return (
            "Năm 2026, HUIT có 5 phương thức: điểm thi tốt nghiệp THPT, học bạ "
            "lớp 10–12, Đánh giá năng lực ĐHQG-HCM, tuyển thẳng theo quy định "
            "của Bộ GD&ĐT, và bài thi năng lực chuyên biệt của ĐH Sư phạm "
            "TP.HCM kết hợp học bạ. [1] Bạn muốn mình giải thích phương thức nào?"
        )

    if intent == "scholarship":
        return (
            "Không có công bố chính thức về mức giảm **50% học phí học kỳ đầu "
            "áp dụng chung cho mọi ngành chính quy**. HUIT có nhiều nhóm học "
            "bổng như khuyến khích học tập, tiếp sức đến trường, thủ khoa–á "
            "khoa và hỗ trợ sinh viên vượt khó. [1] Chính sách của Viện Quốc tế "
            "là chương trình riêng, cần phân biệt với hệ chính quy. [2]"
        )

    if intent == "major" and docs:
        best = docs[0]
        code = best.get("major_code")
        title = str(best.get("page_title") or best.get("title") or "ngành này")
        title = re.sub(r"\s*\(HUIT.*$", "", title).strip()
        if code:
            return (
                f"HUIT có đào tạo **{title}**, mã ngành **{code}**, thuộc hệ "
                "đại học chính quy trong danh mục tuyển sinh 2026. [1] "
                "Bạn muốn xem thêm tổ hợp xét tuyển hay chương trình học?"
            )

    best_doc = docs[0]
    excerpt = str(best_doc.get("raw_text") or best_doc.get("text", "")).strip()
    excerpt = re.sub(r"^\[[^\]]+\]\s*", "", excerpt)
    excerpt = re.sub(r"[#*_`]+", "", excerpt)
    if len(excerpt) > 500:
        excerpt = excerpt[:500].rsplit(" ", 1)[0] + "…"
    return (
        f"Mình tìm thấy thông tin này trên nguồn tuyển sinh chính thức của HUIT: "
        f"{excerpt} [1]\n\nNếu bạn nói rõ ngành hoặc năm tuyển sinh, mình sẽ "
        "tra cứu chính xác hơn."
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
    if chat_history and isinstance(chat_history, list) and len(question.split()) <= 7:
        last_user_msgs = [m.get("content", "") for m in chat_history if isinstance(m, dict) and m.get("role") == "user"]
        if last_user_msgs:
            retrieval_query = f"{last_user_msgs[-1]} {question}"

    docs = retrieve(retrieval_query, _rag_cfg.get("top_k", 3))
    grounded_docs = (
        [doc for doc in docs if doc.get("category") == intent]
        if intent != "general"
        else docs
    )
    grounded_docs = grounded_docs or docs
    source_limit = 1 if intent == "major" else 3
    sources = [{
        "i": i,
        "title": _clean_doc_title(d.get("title")),
        "url": d.get("source_url") or d.get("url") or d.get("link") or "https://ts.huit.edu.vn",
        "score": round(d.get("score", 0), 3),
        "text": d.get("text", "")[:300]
    } for i, d in enumerate(grounded_docs[:source_limit], 1)]
    
    if not docs:
        res = {"answer": "Không tìm thấy dữ liệu liên quan trong kho tri thức tuyển sinh HUIT.", "sources": []}
        return res

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
    
    res = {
        "answer": text,
        "sources": sources,
        "meta": {
            "intent": intent,
            "fallback": used_fallback,
            "model": LLM_MODEL,
            "kb_version": KB_VERSION,
            "rag_version": RAG_VERSION,
        },
    }
    if use_cache:
        save_response_to_cache(question, res, chat_history)
    log_event(
        question,
        res,
        int((time.perf_counter() - started) * 1000),
        intent,
    )
    return res


def stream_answer(question, chat_history=None):
    """Generator function yielding chunks for SSE streaming."""
    res = answer(question, chat_history=chat_history)
    answer_text = res.get("answer", "")
    sources = res.get("sources", [])

    # First yield sources metadata
    yield json.dumps({"type": "sources", "sources": sources}, ensure_ascii=False) + "\n"

    # Stream answer words with smooth micro-delay
    words = re.findall(r'\S+|\s+', answer_text)
    for word in words:
        yield json.dumps({"type": "token", "token": word}, ensure_ascii=False) + "\n"
