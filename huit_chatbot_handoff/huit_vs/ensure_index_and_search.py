#!/usr/bin/env python3
"""Ensure the vector index exists (recreate after collection drop), wait until
queryable, then run semantic search demo on the REAL HUIT knowledge base."""
import os
import sys
import time
from urllib.parse import quote_plus

from pymongo import MongoClient
from pymongo.operations import SearchIndexModel

USER = "nguyenkhaihiep1999_db_user"
HOST = "cluster0.hyj8rab.mongodb.net"
DB = "huit_chatbot"
COLL = "huit_kb"
INDEX = "huit_vector_index"
MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
DIMS = 384

QUERIES = [
    "Có những phương thức xét tuyển nào vào trường?",
    "Xét tuyển bằng học bạ cần điều kiện gì?",
    "Điểm sàn xét tuyển năm 2025 là bao nhiêu?",
    "Trường đào tạo khoảng bao nhiêu ngành?",
    "Học phí khóa 2026 bao nhiêu tiền?",
]


def main():
    pwd = os.environ.get("MONGODB_PASSWORD")
    uri = f"mongodb+srv://{USER}:{quote_plus(pwd)}@{HOST}/?appName=Cluster0"
    client = MongoClient(uri, serverSelectionTimeoutMS=12000)
    coll = client[DB][COLL]

    names = [ix["name"] for ix in coll.list_search_indexes()]
    if INDEX not in names:
        print("Recreating vector index (was dropped with the collection) ...")
        coll.create_search_index(model=SearchIndexModel(
            definition={"fields": [{"type": "vector", "path": "embedding",
                                     "numDimensions": DIMS, "similarity": "cosine"}]},
            name=INDEX, type="vectorSearch"))
    # wait until queryable
    t0 = time.time()
    while time.time() - t0 < 180:
        for ix in coll.list_search_indexes():
            if ix["name"] == INDEX and ix.get("queryable"):
                print(f"Index queryable after {int(time.time()-t0)}s")
                break
        else:
            time.sleep(10); continue
        break
    else:
        sys.exit("Index not ready in time.")

    from fastembed import TextEmbedding
    model = TextEmbedding(MODEL)
    print("\n" + "=" * 66)
    print("SEMANTIC SEARCH on REAL HUIT data (58 chunks)")
    print("=" * 66)
    for q in QUERIES:
        qv = list(model.embed([q]))[0].tolist()
        pipe = [
            {"$vectorSearch": {"index": INDEX, "path": "embedding",
                                "queryVector": qv, "numCandidates": 100, "limit": 2}},
            {"$project": {"_id": 0, "title": 1, "text": 1,
                          "score": {"$meta": "vectorSearchScore"}}},
        ]
        res = list(coll.aggregate(pipe))
        print(f"\n❓ {q}")
        for r in res:
            print(f"   → [{r['score']:.3f}] ({r['title']})")
            print(f"      {r['text'][:170]}...")
    client.close()
    print("\nDONE_SEARCH")


if __name__ == "__main__":
    main()
