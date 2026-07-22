#!/usr/bin/env python3
"""Lõi RAG tái dùng cho API: nạp embedder 1 lần, retrieve + generate.

Biến môi trường: MONGODB_PASSWORD (bắt buộc), HUIT_OPENROUTER_KEY (ưu tiên;
fallback OPENROUTER_API_KEY/DASHSCOPE_API_KEY/OPENAI_API_KEY/GEMINI_API_KEY),
OPENROUTER_MODEL (mặc định openai/gpt-oss-20b:free).
"""
import copy
import json
import os
from urllib.parse import quote_plus

from pymongo import MongoClient

USER = "nguyenkhaihiep1999_db_user"
HOST = "cluster0.hyj8rab.mongodb.net"
DB = "huit_chatbot"
COLL = "huit_kb"
MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
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


os.environ.setdefault("FASTEMBED_CACHE_DIR", "/tmp/fastembed_cache")

_embedder = None
_mongo = None
_retrieval_pipeline = None
_rag_cfg = None


def _init():
    global _embedder, _mongo, _retrieval_pipeline, _rag_cfg
    if _embedder is None:
        from fastembed import TextEmbedding
        _embedder = TextEmbedding(MODEL, cache_dir=os.environ.get("FASTEMBED_CACHE_DIR", "/tmp/fastembed_cache"))
    if _retrieval_pipeline is None:
        mod = json.load(open(RETRIEVAL_MODULE, encoding="utf-8"))
        _retrieval_pipeline = mod["private"]["node_function"]["edge"][0]["pipeline"]
    if _rag_cfg is None:
        rag = json.load(open(RAG_MODULE, encoding="utf-8"))
        _rag_cfg = rag["private"]["node_function"]["edge"][0]["config"]
    if _mongo is None:
        pwd = os.environ.get("MONGODB_PASSWORD", "qwertyuio12A")
        uri = f"mongodb+srv://{USER}:{quote_plus(pwd)}@{HOST}/?appName=Cluster0"
        _mongo = MongoClient(uri, serverSelectionTimeoutMS=15000)


def retrieve(question, top_k):
    _init()
    pipeline = copy.deepcopy(_retrieval_pipeline)
    qv = list(_embedder.embed([question]))[0].tolist()
    for stage in pipeline:
        vs = stage.get("$vectorSearch")
        if vs and vs.get("queryVector") == "<<QUERY_VECTOR_384>>":
            vs["queryVector"] = qv
            vs["limit"] = top_k
            vs["numCandidates"] = max(100, top_k * 20)
    return list(_mongo[DB][COLL].aggregate(pipeline))


def _call_llm(system_prompt, user_prompt):
    msgs = [{"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}]
    
    # 1. Ưu tiên OpenRouter API Key nếu được cấu hình
    or_key = os.environ.get("HUIT_OPENROUTER_KEY") or os.environ.get("OPENROUTER_API_KEY")
    if or_key:
        from openai import OpenAI
        client = OpenAI(api_key=or_key, base_url="https://openrouter.ai/api/v1")
        models_to_try = [
            os.environ.get("OPENROUTER_MODEL", "qwen/qwen-2.5-72b-instruct"),
            "meta-llama/llama-3.3-70b-instruct",
            "deepseek/deepseek-chat",
            "google/gemini-flash-1.5",
            "openai/gpt-3.5-turbo"
        ]
        for model_name in models_to_try:
            try:
                r = client.chat.completions.create(model=model_name, messages=msgs, temperature=0.2)
                if r and r.choices and r.choices[0].message.content:
                    return r.choices[0].message.content
            except Exception as e:
                print(f"OpenRouter model '{model_name}' fallback warning:", e)


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


def answer(question):
    _init()
    docs = retrieve(question, _rag_cfg["top_k"])
    sources = [{"i": i, "title": d.get("title") or "Cổng tuyển sinh chính thức HUIT", "url": d.get("url") or d.get("link") or "https://ts.huit.edu.vn", "score": round(d.get("score", 0), 3),
                "text": d.get("text", "")[:300]} for i, d in enumerate(docs, 1)]
    
    if not docs:
        return {"answer": "Không tìm thấy dữ liệu liên quan trong kho tri thức tuyển sinh HUIT.", "sources": []}

    context = "\n\n".join(f"[{i}] {d.get('title')} — {d.get('text','')}"
                          for i, d in enumerate(docs, 1))
    
    try:
        user_prompt = _rag_cfg["answer_template"].format(context=context, question=question)
        text = _call_llm(_rag_cfg["system_prompt"], user_prompt)
    except Exception as e:
        # Trong trường hợp không gọi được LLM, hiển thị kết quả trích xuất trực tiếp sạch sẽ
        best_doc = docs[0]
        text = (
            f"**Thông tin tuyển sinh HUIT được tìm thấy:**\n\n"
            f"> {best_doc.get('text')}\n\n"
            f"*(Nguồn trích dẫn: {best_doc.get('page_title', 'HUIT Admission')})*"
        )
    return {"answer": text, "sources": sources}

