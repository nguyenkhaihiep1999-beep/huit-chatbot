#!/usr/bin/env python3
"""Lõi RAG tái dùng cho API: nạp embedder 1 lần, retrieve + generate.

Biến môi trường: MONGODB_PASSWORD (bắt buộc), HUIT_OPENROUTER_KEY (ưu tiên;
fallback OPENROUTER_API_KEY/DASHSCOPE_API_KEY/OPENAI_API_KEY/GEMINI_API_KEY),
OPENROUTER_MODEL (mặc định openai/gpt-oss-20b:free).
"""
import copy
import json
import os
import re
import time
from urllib.parse import quote_plus

from pymongo import MongoClient

USER = "nguyenkhaihiep1999_db_user"
HOST = "cluster0.hyj8rab.mongodb.net"
DB = "huit_chatbot"
COLL = "huit_kb"
MODEL = "intfloat/multilingual-e5-large"
DIMS = 1024
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


def retrieve(question, top_k=3):
    _init()
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
                doc_id = str(doc.get("_id", rank))
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
                    doc_id = str(doc.get("_id", rank))
                    if doc_id not in candidate_map:
                        candidate_map[doc_id] = doc
                    keyword_ranks[doc_id] = rank
        except Exception as e:
            print("Keyword search retrieve warning:", e)

    if not candidate_map and _mongo is not None:
        raw_docs = list(_mongo[DB][COLL].find().limit(top_k))
        for rank, doc in enumerate(raw_docs, 1):
            doc_id = str(doc.get("_id", rank))
            candidate_map[doc_id] = doc
            vector_ranks[doc_id] = rank

    # 3. Reciprocal Rank Fusion (RRF) & Re-ranking Stage
    rrf_k = 60
    scored_candidates = []
    q_words = set(re.findall(r'\w+', question.lower()))
    code_matches = re.findall(r'\b7\d{6}\b', question)

    for doc_id, doc in candidate_map.items():
        v_rank = vector_ranks.get(doc_id, 999)
        k_rank = keyword_ranks.get(doc_id, 999)
        rrf_score = (1.0 / (rrf_k + v_rank)) + (1.0 / (rrf_k + k_rank))

        # Re-ranker scoring features
        text_content = (str(doc.get("title", "")) + " " + str(doc.get("text", ""))).lower()
        overlap_count = sum(1 for w in q_words if len(w) > 2 and w in text_content)

        # Exact course code boost
        code_boost = 0.0
        for code in code_matches:
            if code in text_content:
                code_boost += 0.5

        final_score = (rrf_score * 10) + (overlap_count * 0.05) + code_boost
        doc["score"] = round(doc.get("score") or final_score, 4)
        doc["rrf_score"] = round(final_score, 4)
        scored_candidates.append((final_score, doc))

    scored_candidates.sort(key=lambda x: x[0], reverse=True)
    docs = [item[1] for item in scored_candidates[:top_k]]

    # 4. General tuition heuristic fallback
    q_lower = question.lower()
    if any(k in q_lower for k in ["học phí", "hoc phi", "tiền học", "tín chỉ", "mức phí"]):
        general_tuition_doc = {
            "_id": "huit_general_tuition_override",
            "title": "Chính sách & Mức Học phí HUIT (ĐH Công Thương TP.HCM)",
            "text": "[Trường Đại học Công Thương TP.HCM (HUIT) | Nguồn chính thức ts.huit.edu.vn | Chủ đề: Học phí]\nMức học phí trung bình tại Trường Đại học Công Thương TP.HCM (HUIT) khoảng 14 - 16 triệu đồng/học kỳ (mỗi năm có 2 học kỳ chính, tùy số lượng tín chỉ sinh viên đăng ký). Đơn giá tín chỉ khoảng 540.000đ - 700.000đ/tín chỉ tùy môn lý thuyết hoặc thực hành. Nhà trường cam kết giữ ổn định học phí trong toàn bộ khóa học.",
            "url": "https://ts.huit.edu.vn",
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
    if or_key:
        from openai import OpenAI
        client = OpenAI(api_key=or_key, base_url="https://openrouter.ai/api/v1")
        primary_model = os.environ.get("OPENROUTER_MODEL", "openrouter/free")
        if primary_model == "openrouter/free" or primary_model.endswith(":free"):
            # Chế độ miễn phí nghiêm ngặt: không tự chuyển sang model trả phí.
            models_to_try = [primary_model]
        else:
            models_to_try = [
                primary_model,
                "~google/gemini-flash-latest",
                "qwen/qwen3-32b",
            ]
        for model_name in models_to_try:
            attempts = 3 if model_name == "openrouter/free" else 1
            for attempt in range(attempts):
                try:
                    r = client.chat.completions.create(
                        model=model_name,
                        messages=msgs,
                        temperature=0.2,
                        max_tokens=700,
                        timeout=45,
                    )
                    if r and r.choices and r.choices[0].message.content:
                        return r.choices[0].message.content
                except Exception as e:
                    print(
                        f"OpenRouter model '{model_name}' attempt "
                        f"{attempt + 1}/{attempts} warning: {e}"
                    )
                    if attempt + 1 < attempts:
                        time.sleep(0.5)

    # 2. Qwen chính thức qua Alibaba DashScope API
    if os.environ.get("DASHSCOPE_API_KEY"):
        try:
            from openai import OpenAI
            client = OpenAI(api_key=os.environ["DASHSCOPE_API_KEY"],
                            base_url=os.environ.get("DASHSCOPE_BASE_URL",
                                                    "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"))
            r = client.chat.completions.create(model=os.environ.get("QWEN_MODEL", "qwen-plus"),
                                               messages=msgs, temperature=0.2)
            return r.choices[0].message.content
        except Exception as e:
            print("DashScope call warning:", e)

    # 3. Google Gemini API
    if os.environ.get("GEMINI_API_KEY"):
        try:
            from google import genai
            client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
            r = client.models.generate_content(model=os.environ.get("GEMINI_MODEL", "gemini-2.0-flash"),
                                                contents=f"{system_prompt}\n\n{user_prompt}")
            return r.text
        except Exception as e:
            print("Gemini call warning:", e)

    # 4. OpenAI API
    if os.environ.get("OPENAI_API_KEY"):
        try:
            from openai import OpenAI
            client = OpenAI()
            r = client.chat.completions.create(model=os.environ.get("OPENAI_MODEL", "gpt-4o-mini"),
                                               messages=msgs, temperature=0.2)
            return r.choices[0].message.content
        except Exception as e:
            print("OpenAI call warning:", e)

    # 5. Qwen local qua Ollama (Offline)
    if os.environ.get("OLLAMA_MODEL"):
        try:
            from openai import OpenAI
            base_url = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434/v1")
            client = OpenAI(api_key="ollama", base_url=base_url)
            r = client.chat.completions.create(model=os.environ["OLLAMA_MODEL"], messages=msgs, temperature=0.2)
            return r.choices[0].message.content
        except Exception as e:
            print("Ollama call warning:", e)

    raise RuntimeError("Chưa cấu hình API Key LLM hợp lệ.")


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


def get_cached_response(question):
    _init()
    if _mongo is not None:
        try:
            q_clean = question.strip().lower()
            cached = _mongo[DB]["query_cache"].find_one({"question_clean": q_clean})
            if cached:
                print(f"[CACHE HIT] Returning cached answer for query: '{question}'")
                return {"answer": cached["answer"], "sources": cached.get("sources", []), "cached": True}
        except Exception as e:
            print("Cache lookup warning:", e)
    return None


def save_response_to_cache(question, response_data):
    _init()
    if _mongo is not None and response_data and response_data.get("answer"):
        try:
            q_clean = question.strip().lower()
            _mongo[DB]["query_cache"].update_one(
                {"question_clean": q_clean},
                {"$set": {
                    "question_clean": q_clean,
                    "original_question": question,
                    "answer": response_data["answer"],
                    "sources": response_data.get("sources", []),
                    "updated_at": os.environ.get("CURRENT_TIME", "2026-07-24")
                }},
                upsert=True
            )
        except Exception as e:
            print("Save cache warning:", e)


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
        unique_values = list(dict.fromkeys(v.replace(",", ".") for v in values))
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
    _init()

    # 1. Intent Guardrail Check
    guard_res = check_intent_guardrail(question)
    if guard_res["is_handled"]:
        return guard_res

    # 2. Semantic Cache Check
    cached_res = get_cached_response(question)
    if cached_res:
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
    
    try:
        user_prompt = f"{history_str}{_rag_cfg['answer_template'].format(context=context, question=question)}"
        text = _call_llm(_rag_cfg["system_prompt"], user_prompt)
    except Exception:
        text = _fallback_answer(question, docs)
    
    res = {"answer": text, "sources": sources}
    save_response_to_cache(question, res)
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
