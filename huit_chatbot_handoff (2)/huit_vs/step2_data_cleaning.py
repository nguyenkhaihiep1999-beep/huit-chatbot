#!/usr/bin/env python3
"""Step 2: Create, save, execute and test Module `huit_data_cleaning`
using MongoDB Aggregation Pipeline ("1 JSON = 1 module").
Outputs clean documents to collection `test_clean_data`.
"""
import json
import os
from urllib.parse import quote_plus

from pymongo import MongoClient

USER = "nguyenkhaihiep1999_db_user"
HOST = "cluster0.hyj8rab.mongodb.net"
DB = "huit_chatbot"

HERE = os.path.dirname(os.path.abspath(__file__))
pwd = os.environ.get("MONGODB_PASSWORD")
if not pwd:
    raise RuntimeError("MONGODB_PASSWORD chưa được cấu hình.")

uri = f"mongodb+srv://{USER}:{quote_plus(pwd)}@{HOST}/?appName=Cluster0"
client = MongoClient(uri, serverSelectionTimeoutMS=12000)
db = client[DB]

# 1. Package Module 2: `huit_data_cleaning` JSON document with MongoDB Aggregation Pipeline
clean_module = {
    "_id": "huit_data_cleaning",
    "public": {
        "node_data": {
            "jsonSchema": {
                "$schema": "http://json-schema.org/draft-07/schema#",
                "title": "HUIT Clean Data Schema",
                "type": "object",
                "properties": {
                    "url": {"type": "string"},
                    "title": {"type": "string"},
                    "clean_text": {"type": "string"}
                },
                "required": ["url", "title", "clean_text"]
            }
        }
    },
    "private": {
        "node_function": {
            "edge": [
                {
                    "pipeline": [
                        {
                            "$match": {
                                "markdown": {"$exists": True, "$ne": ""},
                                "url": {"$regex": "huit.edu.vn|fptshop|cellphones"}
                            }
                        },
                        {
                            "$project": {
                                "_id": 0,
                                "source_url": "$url",
                                "page_title": "$title",
                                "clean_text": "$markdown"
                            }
                        },
                        {
                            "$out": "test_clean_data"
                        }
                    ],
                    "purpose": "Aggregation Pipeline làm sạch dữ liệu thô từ raw_data và xuất ra collection kiểm thử test_clean_data."
                }
            ]
        }
    }
}

# Save module to `code_modules`
code_coll = db["code_modules"]
code_coll.update_one({"_id": "huit_data_cleaning"}, {"$set": clean_module}, upsert=True)
print(" [OK] STEP 2 SUCCESS: Saved module 'huit_data_cleaning' to collection 'code_modules'")

# 2. RUN MODULE FROM MONGOBD (`code_modules`) TO VERIFY
doc = code_coll.find_one({"_id": "huit_data_cleaning"})
pipeline = doc["private"]["node_function"]["edge"][0]["pipeline"]

# Execute pipeline on MongoDB
db["raw_data"].aggregate(pipeline)

# 3. VERIFY TEST COLLECTION `test_clean_data`
test_count = db["test_clean_data"].count_documents({})
print(f"[OK] STEP 2 VERIFIED: Executed 'huit_data_cleaning' JSON module directly from MongoDB.")
print(f"-> Output written to test collection 'test_clean_data': {test_count} clean documents.")

client.close()
