#!/usr/bin/env python3
"""HUIT Vector Search - demo queries + persist the reusable module JSON.

1) Wait until the Atlas vector index is queryable.
2) Run semantic ($vectorSearch) queries in Vietnamese.
3) Store the search logic as a '1 JSON = 1 module' document in code_modules
   (following the thesis form: _id / public.node_data.jsonSchema / private.node_function).
"""
import os
import sys
import time
from urllib.parse import quote_plus

from pymongo import MongoClient

USER = "nguyenkhaihiep1999_db_user"
HOST = "cluster0.hyj8rab.mongodb.net"
DB = "huit_chatbot"
COLL = "huit_kb"
INDEX = "huit_vector_index"
MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
DIMS = 384

QUERIES = [
    "Trường có những ngành nào để học?",
    "Chi phí học một năm khoảng bao nhiêu?",
    "Làm sao để đăng ký xét tuyển vào trường?",
    "Ở xa có chỗ ở cho sinh viên không?",
]

# The reusable module, in the thesis "1 JSON = 1 module" form.
VECTOR_SEARCH_MODULE = {
    "_id": "huit_semantic_search",
    "public": {"node_data": {"jsonSchema": {
        "$schema": "http://json-schema.org/draft-07/schema#",
        "title": "HUIT Knowledge Base Entry",
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "Tiêu đề mục tri thức"},
            "text": {"type": "string", "description": "Nội dung văn bản"},
            "embedding": {"type": "array", "items": {"type": "number"},
                           "description": f"Vector embedding {DIMS} chiều (multilingual MiniLM)"},
        },
        "required": ["title", "text", "embedding"],
    }}},
    "private": {"node_function": {"edge": [{
        "pipeline": [
            {"$vectorSearch": {
                "index": INDEX, "path": "embedding",
                "queryVector": "<<QUERY_VECTOR_384>>",  # runtime replaces with embedded query
                "numCandidates": 100, "limit": 3,
            }},
            {"$project": {"_id": 0, "title": 1, "text": 1,
                          "score": {"$meta": "vectorSearchScore"}}},
        ],
        "purpose": ("Tìm kiếm ngữ nghĩa trên kho tri thức HUIT bằng Atlas Vector Search. "
                    "Nhận query vector 384 chiều, trả về top tài liệu liên quan nhất kèm điểm cosine. "
                    "Đây là module lõi cho phần retrieval của chatbot (RAG)."),
    }]}},
}


def wait_index_ready(coll, timeout=180):
    print("Waiting for vector index to become queryable ...")
    t0 = time.time()
    while time.time() - t0 < timeout:
        for ix in coll.list_search_indexes():
            if ix["name"] == INDEX:
                if ix.get("queryable"):
                    print(f"  index status: {ix.get('status')} (queryable) after {int(time.time()-t0)}s")
                    return True
                print(f"  index status: {ix.get('status')} ... waiting")
        time.sleep(10)
    return False


def main():
    pwd = os.environ.get("MONGODB_PASSWORD")
    if not pwd:
        sys.exit("MONGODB_PASSWORD missing")
    uri = f"mongodb+srv://{USER}:{quote_plus(pwd)}@{HOST}/?appName=Cluster0"

    client = MongoClient(uri, serverSelectionTimeoutMS=12000)
    coll = client[DB][COLL]

    if not wait_index_ready(coll):
        sys.exit("Index not ready in time - re-run this script in a minute.")

    from fastembed import TextEmbedding
    model = TextEmbedding(MODEL)

    print("\n" + "=" * 66)
    print("SEMANTIC SEARCH DEMO (Vietnamese, no keyword overlap needed)")
    print("=" * 66)
    for q in QUERIES:
        qv = list(model.embed([q]))[0].tolist()
        pipeline = [
            {"$vectorSearch": {"index": INDEX, "path": "embedding",
                                "queryVector": qv, "numCandidates": 100, "limit": 3}},
            {"$project": {"_id": 0, "title": 1,
                          "score": {"$meta": "vectorSearchScore"}}},
        ]
        results = list(coll.aggregate(pipeline))
        print(f"\n❓ {q}")
        for r in results:
            print(f"   → [{r['score']:.3f}] {r['title']}")

    # persist the reusable module (1 JSON = 1 module)
    cm = client[DB]["code_modules"]
    cm.replace_one({"_id": VECTOR_SEARCH_MODULE["_id"]}, VECTOR_SEARCH_MODULE, upsert=True)
    print(f"\nStored module '{VECTOR_SEARCH_MODULE['_id']}' in {DB}.code_modules")
    print("Modules now in code_modules:", [d["_id"] for d in cm.find({}, {"_id": 1})])
    client.close()
    print("DONE_DEMO")


if __name__ == "__main__":
    main()
