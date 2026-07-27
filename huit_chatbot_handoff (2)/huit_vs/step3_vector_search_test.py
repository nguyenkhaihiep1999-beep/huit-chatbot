#!/usr/bin/env python3
"""Step 3 & Core Task: Rebuild KB + Atlas Vector Search, package modules in `code_modules`,
run verification tests and output to `test_search_results`.
"""
import copy
import json
import os
import sys
from urllib.parse import quote_plus

from pymongo import MongoClient

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

USER = "nguyenkhaihiep1999_db_user"
HOST = "cluster0.hyj8rab.mongodb.net"
DB = "huit_chatbot"

HERE = os.path.dirname(os.path.abspath(__file__))
pwd = os.environ.get("MONGODB_PASSWORD")
if not pwd:
    raise RuntimeError("MONGODB_PASSWORD chưa được cấu hình.")

uri = f"mongodb+srv://{USER}:{quote_plus(pwd)}@{HOST}/?appName=Cluster0"
client = MongoClient(uri, serverSelectionTimeoutMS=15000)
db = client[DB]

# 1. Package Module 3: `huit_semantic_search` into `code_modules`
semantic_search_module = {
    "_id": "huit_semantic_search",
    "public": {
        "node_data": {
            "jsonSchema": {
                "$schema": "http://json-schema.org/draft-07/schema#",
                "title": "HUIT Vector Search Entry",
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "text": {"type": "string"},
                    "embedding": {
                        "type": "array",
                        "items": {"type": "number"},
                        "description": "Vector embedding 384 chiều"
                    }
                },
                "required": ["title", "text", "embedding"]
            }
        }
    },
    "private": {
        "node_function": {
            "edge": [
                {
                    "pipeline": [
                        {
                            "$vectorSearch": {
                                "index": "huit_vector_index",
                                "path": "embedding",
                                "queryVector": "<<QUERY_VECTOR_384>>",
                                "numCandidates": 100,
                                "limit": 3
                            }
                        },
                        {
                            "$project": {
                                "_id": 0,
                                "title": 1,
                                "text": 1,
                                "score": {"$meta": "vectorSearchScore"}
                            }
                        }
                    ],
                    "purpose": "Tìm kiếm ngữ nghĩa trên kho tri thức HUIT bằng Atlas Vector Search."
                }
            ]
        }
    }
}

code_coll = db["code_modules"]
code_coll.update_one({"_id": "huit_semantic_search"}, {"$set": semantic_search_module}, upsert=True)
print("[OK] STEP 3 SUCCESS: Saved module 'huit_semantic_search' to collection 'code_modules'")

# 2. RUN MODULE TEST: Execute `$vectorSearch` from `code_modules` and output test results to `test_search_results`
from fastembed import TextEmbedding

model = TextEmbedding("sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2")

test_questions = [
    "Mã ngành và tổ hợp xét tuyển ngành Trí tuệ nhân tạo HUIT?",
    "Học phí HUIT là bao nhiêu và có bị tăng hàng năm không?",
    "Điểm sàn xét tuyển năm 2025 HUIT bao nhiêu điểm?",
    "Ngành Công nghệ thực phẩm xét tuyển các tổ hợp môn nào?",
    "Danh sách các ngành được giảm 50% học phí học kỳ 1?"
]

mod_doc = code_coll.find_one({"_id": "huit_semantic_search"})
base_pipeline = mod_doc["private"]["node_function"]["edge"][0]["pipeline"]

test_out_coll = db["test_search_results"]
test_out_coll.drop()

test_logs = []
for q in test_questions:
    qv = list(model.embed([q]))[0].tolist()
    pipe = copy.deepcopy(base_pipeline)
    pipe[0]["$vectorSearch"]["queryVector"] = qv
    
    results = list(db["huit_kb"].aggregate(pipe))
    entry = {
        "question": q,
        "results_count": len(results),
        "top_match": results[0] if results else None
    }
    test_logs.append(entry)

test_out_coll.insert_many(test_logs)
print(f"[OK] STEP 3 VERIFIED: Vector Search executed for {len(test_questions)} sample questions.")
print(f"-> Verification output saved to test collection '{DB}.test_search_results': {test_out_coll.count_documents({})} records.")

for item in test_logs:
    print(f"\n[?] Question: {item['question']}")
    if item['top_match']:
        title_str = str(item['top_match'].get('title', '')).encode('ascii', 'ignore').decode('ascii')
        print(f"   Title: {title_str}")
        print(f"   Score: {round(item['top_match'].get('score', 0), 3)}")


client.close()
