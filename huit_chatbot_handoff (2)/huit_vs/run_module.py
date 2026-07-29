#!/usr/bin/env python3
"""RUNNER: chạy một module '1 JSON = 1 module' (vector search) trên MongoDB.

Cách dùng:
    python3 run_module.py "<câu hỏi>"
    python3 run_module.py "<câu hỏi>" /đường/dẫn/module.json

Nó đọc file module JSON -> nhúng câu hỏi thành vector 384 chiều ->
thay vào chỗ <<QUERY_VECTOR_384>> -> chạy pipeline aggregate trên Atlas -> in kết quả.
"""
import copy
import json
import os
import sys
from urllib.parse import quote_plus

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from pymongo import MongoClient

USER = "nguyenkhaihiep1999_db_user"
HOST = "cluster0.hyj8rab.mongodb.net"
DB = "huit_chatbot"
COLL = "huit_kb"
MODEL = "intfloat/multilingual-e5-large"
HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_MODULE = os.path.join(HERE, "huit_semantic_search.module.json")

question = sys.argv[1] if len(sys.argv) > 1 else "Trường có đào tạo ngành công nghệ thông tin không?"
module_path = sys.argv[2] if len(sys.argv) > 2 else DEFAULT_MODULE

# 1) load the module JSON (the file you received)
mod = json.load(open(module_path, encoding="utf-8"))
pipeline = copy.deepcopy(mod["private"]["node_function"]["edge"][0]["pipeline"])

# 2) embed the question
from fastembed import TextEmbedding
emb = TextEmbedding(MODEL)
qv = list(emb.embed(["query: " + question]))[0].tolist()

# 3) substitute the placeholder query vector
for stage in pipeline:
    vs = stage.get("$vectorSearch")
    if vs and (vs.get("queryVector") == "<<QUERY_VECTOR_384>>" or vs.get("queryVector") == "<<QUERY_VECTOR_1024>>"):
        vs["queryVector"] = qv

# 4) run the pipeline on MongoDB Atlas
if not os.environ.get("MONGODB_PASSWORD"):
    _env = os.path.join(HERE, ".env")
    if os.path.exists(_env):
        for line in open(_env, encoding="utf-8"):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ[k.strip()] = v.strip()

pwd = os.environ.get("MONGODB_PASSWORD")
if not pwd:
    sys.exit("MONGODB_PASSWORD missing")
uri = f"mongodb+srv://{USER}:{quote_plus(pwd)}@{HOST}/?appName=Cluster0"
client = MongoClient(uri, serverSelectionTimeoutMS=12000)
results = list(client[DB][COLL].aggregate(pipeline))

print(f"Module   : {mod['_id']}")
print(f"Câu hỏi  : {question}")
print("-" * 60)
for i, r in enumerate(results, 1):
    print(f"{i}. [{r.get('score', 0):.3f}] {r.get('title')}")
    print(f"     {r.get('text', '')[:110]}...")
client.close()
