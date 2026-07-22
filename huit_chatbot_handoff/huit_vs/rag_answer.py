#!/usr/bin/env python3
"""RAG RUNNER: câu hỏi -> vector search (retrieval) -> LLM sinh câu trả lời + trích nguồn.

Cách dùng:
    python3 rag_answer.py "<câu hỏi>"

Kiến trúc "1 JSON = 1 module":
- huit_semantic_search.module.json  : tầng retrieval ($vectorSearch trên Atlas)
- huit_rag_answer.module.json       : cấu hình tầng generation (prompt, top_k, model)

LLM: tự nhận key sẵn có — ưu tiên OPENAI_API_KEY, nếu không có thì GEMINI_API_KEY.
"""
import copy
import json
import os
import sys
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

question = sys.argv[1] if len(sys.argv) > 1 else "Học phí HUIT khoảng bao nhiêu một năm?"


def get_context(question, top_k):
    """Chạy module retrieval (vector search) trên Atlas, trả về list đoạn văn."""
    mod = json.load(open(RETRIEVAL_MODULE, encoding="utf-8"))
    pipeline = copy.deepcopy(mod["private"]["node_function"]["edge"][0]["pipeline"])

    from fastembed import TextEmbedding
    emb = TextEmbedding(MODEL)
    qv = list(emb.embed([question]))[0].tolist()
    for stage in pipeline:
        vs = stage.get("$vectorSearch")
        if vs and vs.get("queryVector") == "<<QUERY_VECTOR_384>>":
            vs["queryVector"] = qv
            vs["limit"] = top_k
            vs["numCandidates"] = max(100, top_k * 20)

    pwd = os.environ.get("MONGODB_PASSWORD")
    if not pwd:
        sys.exit("MONGODB_PASSWORD missing")
    uri = f"mongodb+srv://{USER}:{quote_plus(pwd)}@{HOST}/?appName=Cluster0"
    client = MongoClient(uri, serverSelectionTimeoutMS=15000)
    docs = list(client[DB][COLL].aggregate(pipeline))
    client.close()
    return docs


def call_llm(system_prompt, user_prompt):
    """Gọi LLM: OpenRouter (Qwen free) -> Qwen DashScope -> OpenAI -> Gemini."""
    msgs = [{"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}]
    # OpenRouter (Qwen free) — OpenAI-compatible. Ưu tiên HUIT_OPENROUTER_KEY để
    # tránh đụng secret 'hiep' đang gắn sẵn vào OPENROUTER_API_KEY.
    _or_key = os.environ.get("HUIT_OPENROUTER_KEY") or os.environ.get("OPENROUTER_API_KEY")
    if _or_key:
        from openai import OpenAI
        client = OpenAI(api_key=_or_key,
                        base_url="https://openrouter.ai/api/v1")
        resp = client.chat.completions.create(
            model=os.environ.get("OPENROUTER_MODEL", "openai/gpt-oss-20b:free"),
            messages=msgs, temperature=0.2)
        return resp.choices[0].message.content
    # Qwen qua DashScope (OpenAI-compatible endpoint)
    if os.environ.get("DASHSCOPE_API_KEY"):
        from openai import OpenAI
        client = OpenAI(
            api_key=os.environ["DASHSCOPE_API_KEY"],
            base_url=os.environ.get(
                "DASHSCOPE_BASE_URL",
                "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"))
        resp = client.chat.completions.create(
            model=os.environ.get("QWEN_MODEL", "qwen-plus"),
            messages=msgs, temperature=0.2)
        return resp.choices[0].message.content
    if os.environ.get("OPENAI_API_KEY"):
        from openai import OpenAI
        client = OpenAI()
        resp = client.chat.completions.create(
            model=os.environ.get("OPENAI_MODEL", "gpt-4o-mini"),
            messages=msgs, temperature=0.2)
        return resp.choices[0].message.content
    if os.environ.get("GEMINI_API_KEY"):
        from google import genai
        client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
        resp = client.models.generate_content(
            model=os.environ.get("GEMINI_MODEL", "gemini-2.0-flash"),
            contents=f"{system_prompt}\n\n{user_prompt}")
        return resp.text
    sys.exit("Chưa có OPENROUTER_API_KEY / DASHSCOPE_API_KEY / OPENAI_API_KEY / GEMINI_API_KEY.")


def main():
    rag = json.load(open(RAG_MODULE, encoding="utf-8"))
    cfg = rag["private"]["node_function"]["edge"][0]["config"]

    docs = get_context(question, cfg["top_k"])
    context = "\n\n".join(
        f"[{i}] {d.get('title')} — {d.get('text', '')}" for i, d in enumerate(docs, 1)
    )
    user_prompt = cfg["answer_template"].format(context=context, question=question)
    answer = call_llm(cfg["system_prompt"], user_prompt)

    print(f"❓ Câu hỏi: {question}")
    print("=" * 70)
    print(answer)
    print("=" * 70)
    print("Nguồn tham khảo (retrieval):")
    for i, d in enumerate(docs, 1):
        print(f"  [{i}] ({d.get('score', 0):.3f}) {d.get('title')}")


if __name__ == "__main__":
    main()
