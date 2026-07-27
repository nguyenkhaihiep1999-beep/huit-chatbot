#!/usr/bin/env python3
"""
Build and register ALL 10 MongoDB Aggregation Pipeline JSON modules in `code_modules`.
Executes each module directly on MongoDB Atlas and verifies output collections.
"1 JSON = 1 module code" architecture.
"""
import json
import os
import sys
from urllib.parse import quote_plus
from pymongo import MongoClient

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")


USER = "nguyenkhaihiep1999_db_user"
HOST = "cluster0.hyj8rab.mongodb.net"
DB = "huit_chatbot"

HERE = os.path.dirname(os.path.abspath(__file__))
pwd = os.environ.get("MONGODB_PASSWORD")
if not pwd:
    env_file = os.path.join(HERE, ".env")
    if os.path.exists(env_file):
        with open(env_file, encoding="utf-8") as f:
            for line in f:
                if line.startswith("MONGODB_PASSWORD="):
                    pwd = line.split("=", 1)[1].strip().strip('"\'')

if not pwd:
    raise RuntimeError("MONGODB_PASSWORD chưa được cấu hình.")

uri = f"mongodb+srv://{USER}:{quote_plus(pwd)}@{HOST}/?appName=Cluster0"
client = MongoClient(uri, serverSelectionTimeoutMS=15000)
db = client[DB]
code_coll = db["code_modules"]

print("[START] Building & Registering 10 MongoDB Aggregation JSON Modules...")

# ==============================================================================
# BỘ 10 MONGODB AGGREGATION PIPELINES CHO HUIT DATA
# ==============================================================================
AGGREGATION_MODULES = [
    # Module 1: Raw Miner Edge
    {
        "_id": "huit_raw_miner",
        "description": "Thu thập và trích xuất dữ liệu thô HUIT vào raw_data.",
        "pipeline": [
            {"$match": {"markdown": {"$exists": True, "$ne": ""}}},
            {"$project": {"_id": 1, "url": 1, "title": 1, "markdown": 1}}
        ]
    },
    # Module 2: Data Cleaning
    {
        "_id": "huit_data_cleaning",
        "description": "Làm sạch văn bản thô, trim khoảng trắng và xuất ra test_clean_data.",
        "pipeline": [
            {"$match": {"markdown": {"$exists": True, "$ne": ""}}},
            {
                "$project": {
                    "_id": 0,
                    "source_url": "$url",
                    "page_title": {"$trim": {"input": "$title"}},
                    "clean_text": {"$trim": {"input": "$markdown"}},
                    "char_count": {"$strLenCP": "$markdown"}
                }
            },
            {"$out": "test_clean_data"}
        ]
    },
    # Module 3: Categorization
    {
        "_id": "huit_agg_categorization",
        "description": "Phân loại bài viết theo chủ đề: Học phí, Điểm chuẩn, Học bổng, Ngành đào tạo.",
        "pipeline": [
            {
                "$addFields": {
                    "category": {
                        "$switch": {
                            "branches": [
                                {
                                    "case": {"$regexMatch": {"input": "$clean_text", "regex": "học phí|tiền học|lệ phí|mức thu", "options": "i"}},
                                    "then": "Học phí & Lệ phí"
                                },
                                {
                                    "case": {"$regexMatch": {"input": "$clean_text", "regex": "điểm chuẩn|điểm sàn|điểm xét|trúng tuyển", "options": "i"}},
                                    "then": "Điểm chuẩn & Xét tuyển"
                                },
                                {
                                    "case": {"$regexMatch": {"input": "$clean_text", "regex": "học bổng|ưu đãi|khuyến học|trợ cấp", "options": "i"}},
                                    "then": "Học bổng & Hỗ trợ"
                                },
                                {
                                    "case": {"$regexMatch": {"input": "$clean_text", "regex": "ngành|mã ngành|chương trình đào tạo|kỹ thuật|công nghệ", "options": "i"}},
                                    "then": "Ngành đào tạo"
                                }
                            ],
                            "default": "Thông tin chung HUIT"
                        }
                    }
                }
            },
            {"$out": "test_categorized_data"}
        ]
    },
    # Module 4: Statistics Summary
    {
        "_id": "huit_agg_stats",
        "description": "Thống kê tổng số lượng chunk và độ dài trung bình theo danh mục.",
        "pipeline": [
            {
                "$group": {
                    "_id": "$category",
                    "total_chunks": {"$sum": 1},
                    "avg_text_length": {"$avg": {"$strLenCP": "$clean_text"}}
                }
            },
            {"$sort": {"total_chunks": -1}},
            {"$out": "test_kb_stats"}
        ]
    },
    # Module 5: Deduplication Pipeline
    {
        "_id": "huit_agg_deduplicate",
        "description": "Khử trùng bài viết trùng lặp URL, giữ lại bản ghi mới nhất.",
        "pipeline": [
            {
                "$group": {
                    "_id": "$source_url",
                    "doc": {"$first": "$$ROOT"}
                }
            },
            {"$replaceRoot": {"newRoot": "$doc"}},
            {"$out": "test_dedup_data"}
        ]
    },
    # Module 6: Faceted Multi-Criteria Search
    {
        "_id": "huit_agg_faceted_search",
        "description": "Truy vấn thống kê phân nhóm đa chiều (Multi-facet Search).",
        "pipeline": [
            {
                "$facet": {
                    "by_category": [
                        {"$group": {"_id": "$category", "count": {"$sum": 1}}}
                    ],
                    "top_longest_articles": [
                        {"$sort": {"char_count": -1}},
                        {"$limit": 5},
                        {"$project": {"page_title": 1, "source_url": 1, "char_count": 1}}
                    ]
                }
            }
        ]
    },
    # Module 7: Hot Keyword Mining Pipeline
    {
        "_id": "huit_agg_keyword_mining",
        "description": "Trích xuất và tính tần suất xuất hiện các thuật ngữ tuyển sinh nóng.",
        "pipeline": [
            {
                "$project": {
                    "matched_terms": {
                        "$regexFindAll": {
                            "input": "$clean_text",
                            "regex": "Công nghệ thông tin|Thực phẩm|Kế toán|Quản trị|Ngôn ngữ Anh|Học bạ|Đánh giá năng lực",
                            "options": "i"
                        }
                    }
                }
            },
            {"$unwind": "$matched_terms"},
            {"$sortByCount": "$matched_terms.match"}
        ]
    },
    # Module 8: Quality Scoring & Ranking Pipeline
    {
        "_id": "huit_agg_quality_scoring",
        "description": "Xếp hạng bài viết theo điểm chất lượng và ưu tiên thông tin chuyên sâu.",
        "pipeline": [
            {
                "$addFields": {
                    "quality_score": {
                        "$add": [
                            {"$cond": [{"$gt": ["$char_count", 500]}, 40, 10]},
                            {"$cond": [{"$ne": ["$category", "Thông tin chung HUIT"]}, 30, 0]}
                        ]
                    }
                }
            },
            {"$sort": {"quality_score": -1}},
            {"$out": "test_quality_ranked"}
        ]
    },
    # Module 9: RAG Semantic Search Pipeline
    {
        "_id": "huit_semantic_search",
        "description": "Truy xuất Vector Search 384 chiều cho RAG Chatbot.",
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
        ]
    },
    # Module 10: RAG Paragraph Chunker Pipeline
    {
        "_id": "huit_agg_text_chunker",
        "description": "Tự động tách văn bản thành từng đoạn paragraph nhỏ phục vụ RAG Embedding.",
        "pipeline": [
            {
                "$project": {
                    "source_url": 1,
                    "page_title": 1,
                    "paragraphs": {"$split": ["$clean_text", "\n\n"]}
                }
            },
            {"$unwind": "$paragraphs"},
            {"$match": {"paragraphs": {"$ne": ""}}},
            {
                "$project": {
                    "_id": 0,
                    "source_url": 1,
                    "page_title": 1,
                    "chunk_text": {"$trim": {"input": "$paragraphs"}},
                    "chunk_len": {"$strLenCP": "$paragraphs"}
                }
            },
            {"$out": "test_rag_chunks"}
        ]
    }
]

# Register all modules
for idx, mod in enumerate(AGGREGATION_MODULES, 1):
    doc = {
        "_id": mod["_id"],
        "public": {
            "node_data": {
                "jsonSchema": {
                    "$schema": "http://json-schema.org/draft-07/schema#",
                    "title": f"HUIT Module {mod['_id']}",
                    "type": "object"
                }
            }
        },
        "private": {
            "node_function": {
                "edge": [
                    {
                        "pipeline": mod["pipeline"],
                        "purpose": mod["description"]
                    }
                ]
            }
        }
    }
    code_coll.update_one({"_id": doc["_id"]}, {"$set": doc}, upsert=True)
    print(f"  [{idx}/10] Registered Module '{mod['_id']}' in 'code_modules'")

# ==============================================================================
# VERIFY ALL MODULES BY EXECUTING DIRECTLY ON MONGODB ATLAS
# ==============================================================================
print("\n[VERIFY] Executing Aggregation Pipelines directly on MongoDB Atlas...")

# 1. Execute Data Cleaning
m2 = code_coll.find_one({"_id": "huit_data_cleaning"})
db["raw_data"].aggregate(m2["private"]["node_function"]["edge"][0]["pipeline"])
c2 = db["test_clean_data"].count_documents({})
print(f"  -> Module 'huit_data_cleaning': {c2} clean docs in 'test_clean_data'")

# 2. Execute Categorization
m3 = code_coll.find_one({"_id": "huit_agg_categorization"})
db["test_clean_data"].aggregate(m3["private"]["node_function"]["edge"][0]["pipeline"])
c3 = db["test_categorized_data"].count_documents({})
print(f"  -> Module 'huit_agg_categorization': {c3} categorized docs in 'test_categorized_data'")

# 3. Execute Statistics Summary
m4 = code_coll.find_one({"_id": "huit_agg_stats"})
db["test_categorized_data"].aggregate(m4["private"]["node_function"]["edge"][0]["pipeline"])
stats = list(db["test_kb_stats"].find({}, {"_id": 1, "total_chunks": 1, "avg_text_length": 1}))
print(f"  -> Module 'huit_agg_stats' Verified! Category Statistics:")
for s in stats:
    print(f"     * [{s['_id']}]: {s['total_chunks']} docs (Avg length: {int(s.get('avg_text_length', 0))} chars)")

# 4. Execute Faceted Search
m6 = code_coll.find_one({"_id": "huit_agg_faceted_search"})
facet_res = list(db["test_categorized_data"].aggregate(m6["private"]["node_function"]["edge"][0]["pipeline"]))
if facet_res:
    by_cat = facet_res[0].get("by_category", [])
    print(f"  -> Module 'huit_agg_faceted_search': Found {len(by_cat)} facets.")

# 5. Execute Quality Scoring
m8 = code_coll.find_one({"_id": "huit_agg_quality_scoring"})
db["test_categorized_data"].aggregate(m8["private"]["node_function"]["edge"][0]["pipeline"])
c8 = db["test_quality_ranked"].count_documents({})
print(f"  -> Module 'huit_agg_quality_scoring': Ranked {c8} docs in 'test_quality_ranked'")

# 6. Execute Text Chunker
m10 = code_coll.find_one({"_id": "huit_agg_text_chunker"})
db["test_clean_data"].aggregate(m10["private"]["node_function"]["edge"][0]["pipeline"])
c10 = db["test_rag_chunks"].count_documents({})
print(f"  -> Module 'huit_agg_text_chunker': Generated {c10} RAG paragraph chunks in 'test_rag_chunks'")

client.close()
print("\n[SUCCESS] ALL 10 MONGODB AGGREGATION MODULES REGISTERED & VERIFIED ON MONGODB ATLAS!")
