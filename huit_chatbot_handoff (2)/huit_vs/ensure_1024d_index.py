#!/usr/bin/env python3
"""
ensure_1024d_index.py
Script kiểm tra và khởi tạo Vector Search Index 1024D (Cosine) trên MongoDB Atlas cho collection `huit_kb`.
Đảm bảo đồng bộ tuyệt đối với mô hình embedding `intfloat/multilingual-e5-large`.
"""
import os
import sys
import time
from urllib.parse import quote_plus
from pymongo import MongoClient
from pymongo.operations import SearchIndexModel

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

USER = "nguyenkhaihiep1999_db_user"
HOST = "cluster0.hyj8rab.mongodb.net"
DB = "huit_chatbot"
COLL = "huit_kb"
INDEX_NAME = "huit_vector_index"
DIMS = 1024

pwd = os.environ.get("MONGODB_PASSWORD")
if not pwd:
    raise RuntimeError("MONGODB_PASSWORD chưa được cấu hình.")
uri = f"mongodb+srv://{USER}:{quote_plus(pwd)}@{HOST}/?appName=Cluster0"

print(f"=== ENSURING MONGO ATLAS VECTOR SEARCH INDEX ({DIMS}D) ===")
client = MongoClient(uri, serverSelectionTimeoutMS=15000)
db = client[DB]
coll = db[COLL]

try:
    existing_indexes = list(coll.list_search_indexes())
    print(f"Found {len(existing_indexes)} existing search index(es):")
    idx_exists = False
    for idx in existing_indexes:
        name = idx.get("name")
        status = idx.get("status")
        print(f"  - Index '{name}': Status={status}")
        if name == INDEX_NAME:
            idx_exists = True

    if not idx_exists:
        print(f"\nCreating new SearchIndexModel '{INDEX_NAME}' with {DIMS} dimensions (cosine)...")
        search_index_model = SearchIndexModel(
            definition={
                "fields": [
                    {
                        "type": "vector",
                        "path": "embedding",
                        "numDimensions": DIMS,
                        "similarity": "cosine"
                    }
                ]
            },
            name=INDEX_NAME,
            type="vectorSearch"
        )
        result = coll.create_search_index(model=search_index_model)
        print(f"[OK] Search index creation requested: {result}")
        print("Waiting for index building (may take 1-2 minutes on Atlas)...")
    else:
        print(f"\n[OK] Vector Search Index '{INDEX_NAME}' already exists.")

except Exception as e:
    print("Warning during search index check:", e)

client.close()
print("=== INDEX CHECK COMPLETE ===")
