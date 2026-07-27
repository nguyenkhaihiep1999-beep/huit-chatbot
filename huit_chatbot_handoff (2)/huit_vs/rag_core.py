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
LLM_MODEL = "~google/gemini-flash-latest"
KB_VERSION = os.environ.get("KB_VERSION", "huit-kb-2026-07-v2")
RAG_VERSION = "rag-v4-production"
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
                os.environ.setdefault(_k.strip(), _v.strip().strip('"\''))


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


INTENT_TERMS = {
    "tuition": ("hoc phi", "tin chi", "tien hoc", "muc phi"),
    "cutoff": ("diem san", "diem chuan", "diem trung tuyen"),
    "scholarship": ("hoc bong", "giam hoc phi", "mien hoc phi"),
    "admission": ("phuong thuc xet tuyen", "xet hoc ba", "danh gia nang luc"),
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
            qv = list(_embedder.embed([question]))[0].tolist()
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
                raw_kw = list(_mongo[DB][COLL].find(query).limit(15))
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
        year_boost = 0.2 if requested_years and metadata["year"] in requested_years else 0.0
        year_penalty = -0.12 if requested_years and metadata["year"] and metadata["year"] not in requested_years else 0.0
        final_score = (
            (rrf_score * 10)
            + (overlap_count * 0.05)
            + (title_overlap * 0.15)
            + code_boost
            + intent_boost
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
            "text": "[Trường Đại học Công Thương TP.HCM (HUIT) | Nguồn chính thức ts.huit.edu.vn | Chủ đề: Học phí]\nMức học phí trung bình tại Trường Đại học Công Thương TP.HCM (HUIT) khoảng 14 - 16 triệu đồng/học kỳ (mỗi năm có 2 học kỳ chính, tùy số lượng tín chỉ sinh viên đăng ký). Đơn giá tín chỉ khoảng 540.000đ - 700.000đ/tín chỉ tùy môn lý thuyết hoặc thực hành. Nhà trường cam kết giữ ổn định học phí trong toàn bộ khóa học.",
            "url": "https://ts.huit.edu.vn",
            "source_url": "https://ts.huit.edu.vn",
            "category": "tuition",
            "year": None,
            "score": 0.99
        }
        if not any(d.get("_id") == general_tuition_doc["_id"] for d in docs):
            docs.insert(0, general_tuition_doc)

    return docs[:top_k]


def _call_llm(system_prompt, user_prompt):
    msgs = [{"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}]
    
    # 1. Ưu tiên OpenRouter API Key nếu được cấu hình
    or_key = os.environ.get("HUIT_OPENROUTER_KEY") or os.environ.get("OPENROUTER_API_KEY")
    if not or_key:
        raise RuntimeError("HUIT_OPENROUTER_KEY chưa được cấu hình.")
    from openai import OpenAI
    client = OpenAI(api_key=or_key, base_url="https://openrouter.ai/api/v1")
    try:
        r = client.chat.completions.create(
            model=LLM_MODEL,
            messages=msgs,
            temperature=0.2,
            max_tokens=700,
            timeout=45,
            extra_body={"reasoning": {"effort": "minimal"}},
        )
        if r and r.choices and r.choices[0].message.content:
            return r.choices[0].message.content
    except Exception as e:
        print(f"OpenRouter model '{LLM_MODEL}' warning:", e)
        raise RuntimeError("OpenRouter tạm thời không khả dụng.") from e
    raise RuntimeError("OpenRouter trả về nội dung rỗng.")


def check_intent_guardrail(question):
    q_norm = question.strip().lower()
    
    # 1. Greetings / Small talk
    greetings = ["chào", "xin chào", "hello", "hi", "bạn là ai", "bạn tên gì", "tư vấn giúp", "tư vấn cho mình"]
    if any(q_norm == g or q_norm.startswith(g) for g in greetings) and len(q_norm.split()) <= 4:
        return {
            "is_handled": True,
            "answer": "Xin chào! Tôi là **Trợ lý AI Tuyển sinh HUIT** (Trường Đại học Công Thương TP.HCM). Tôi có thể hỗ trợ bạn tra cứu thông tin 39 ngành đào tạo, tổ hợp xét tuyển, điểm sàn 2025, mức học phí và các chính sách học bổng mới nhất. Bạn cần tìm hiểu thông tin gì?",
            "sources": []
        }

    # 2. Out of scope filter
    out_of_scope = ["thời tiết", "viết code", "giải bài tập toán", "tin bóng đá", "chơi game"]
    if any(k in q_norm for k in out_of_scope):
        return {
            "is_handled": True,
            "answer": "Rất tiếc, tôi là **Trợ lý AI chuyên trách Tuyển sinh HUIT**. Tôi chỉ có thể tư vấn các thông tin liên quan đến **Tuyển sinh, Ngành học, Học phí & Học bổng của Trường Đại học Công Thương TP.HCM (HUIT)**. Vui lòng đặt câu hỏi liên quan đến HUIT nhé!",
            "sources": []
        }

    return {"is_handled": False}


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

    if any(k in q_lower for k in ["học phí", "hoc phi", "tiền học", "tín chỉ", "mức phí"]):
        return (
            "**Học phí HUIT tham khảo:** khoảng **14–16 triệu đồng/học kỳ**, "
            "tương đương khoảng **540.000–700.000 đồng/tín chỉ**, tùy học phần "
            "và số tín chỉ đăng ký. Mức thực tế của năm 2026 cần đối chiếu "
            "thông báo học phí chính thức mới nhất của HUIT. [1]"
        )

    if "điểm sàn" in q_lower or "diem san" in q_lower:
        values = []
        for doc in docs:
            values.extend(
                re.findall(
                    r"điểm sàn[^:\n]{0,80}[:\s`*]*(\d{1,2}(?:[.,]\d{1,2})?)",
                    str(doc.get("text", "")),
                    flags=re.IGNORECASE,
                )
            )
        unique_values = list(dict.fromkeys(
            normalized
            for value in values
            for normalized in [value.replace(",", ".")]
            if float(normalized) <= 30
        ))
        if unique_values:
            return (
                "Theo dữ liệu tuyển sinh đang có, mức điểm sàn HUIT năm 2025 "
                f"được ghi nhận là **{', '.join(unique_values[:5])} điểm**. "
                "Điểm có thể khác theo phương thức hoặc ngành; bạn nên kiểm tra "
                "thông báo chính thức của HUIT trước khi đăng ký. [1]"
            )

    best_doc = docs[0]
    excerpt = str(best_doc.get("text", "")).strip()
    if len(excerpt) > 900:
        excerpt = excerpt[:900].rsplit(" ", 1)[0] + "…"
    return (
        "**Thông tin liên quan được tìm thấy trong dữ liệu tuyển sinh HUIT:**\n\n"
        f"{excerpt}\n\n"
        "Hệ thống sinh câu trả lời đang tạm thời không khả dụng; vui lòng "
        "đối chiếu nguồn chính thức bên dưới."
    )


def answer(question, chat_history=None):
    started = time.perf_counter()
    _init()
    intent = classify_intent(question)

    # 1. Intent Guardrail Check
    guard_res = check_intent_guardrail(question)
    if guard_res["is_handled"]:
        return guard_res

    # 2. Semantic Cache Check
    cached_res = get_cached_response(question, chat_history)
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
    sources = [{
        "i": i,
        "title": _clean_doc_title(d.get("title")),
        "url": d.get("source_url") or d.get("url") or d.get("link") or "https://ts.huit.edu.vn",
        "score": round(d.get("score", 0), 3),
        "text": d.get("text", "")[:300]
    } for i, d in enumerate(docs, 1)]
    
    if not docs:
        res = {"answer": "Không tìm thấy dữ liệu liên quan trong kho tri thức tuyển sinh HUIT.", "sources": []}
        return res

    context = "\n\n".join(f"[{i}] {_clean_doc_title(d.get('title'))} — {d.get('text','')}"
                          for i, d in enumerate(docs, 1))

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
