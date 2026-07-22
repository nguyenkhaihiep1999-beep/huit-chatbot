#!/usr/bin/env python3
"""Step 1: Ingest raw HUIT admission web data into MongoDB collection `raw_data`
and register module `huit_raw_miner` in `code_modules`.
"""
import json
import os
from urllib.parse import quote_plus

from pymongo import MongoClient

USER = "nguyenkhaihiep1999_db_user"
HOST = "cluster0.hyj8rab.mongodb.net"
DB = "huit_chatbot"

HERE = os.path.dirname(os.path.abspath(__file__))

# Read password from .env or environment
pwd = os.environ.get("MONGODB_PASSWORD")
if not pwd:
    env_file = os.path.join(HERE, ".env")
    if os.path.exists(env_file):
        with open(env_file, encoding="utf-8") as f:
            for line in f:
                if line.startswith("MONGODB_PASSWORD="):
                    pwd = line.split("=", 1)[1].strip().strip('"\'')

if not pwd:
    pwd = "qwertyuio12A"

uri = f"mongodb+srv://{USER}:{quote_plus(pwd)}@{HOST}/?appName=Cluster0"
client = MongoClient(uri, serverSelectionTimeoutMS=12000)
db = client[DB]

# 1. Ingest raw web data into `raw_data` collection
scraped_file = os.path.join(HERE, "scraped_pages.json")
if not os.path.exists(scraped_file):
    raise FileNotFoundError(f"File {scraped_file} not found")

with open(scraped_file, encoding="utf-8") as f:
    scraped_data = json.load(f)

raw_coll = db["raw_data"]
raw_coll.drop()
raw_coll.insert_many(scraped_data)
raw_count = raw_coll.count_documents({})
print(f"[OK] STEP 1 SUCCESS: Inserted {raw_count} raw web documents into collection '{DB}.raw_data'")

# 2. Package Module 1: `huit_raw_miner` JSON document into `code_modules`
raw_miner_module = {
    "_id": "huit_raw_miner",
    "public": {
        "node_data": {
            "jsonSchema": {
                "$schema": "http://json-schema.org/draft-07/schema#",
                "title": "HUIT Raw Web Page Schema",
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "URL trang web chính thức HUIT"},
                    "title": {"type": "string", "description": "Tiêu đề trang"},
                    "markdown": {"type": "string", "description": "Nội dung định dạng Markdown thô"}
                },
                "required": ["url", "title", "markdown"]
            }
        }
    },
    "private": {
        "node_function": {
            "edge": [
                {
                    "pipeline": [
                        {"$match": {"markdown": {"$ne": None}}},
                        {"$project": {"_id": 1, "url": 1, "title": 1, "text_length": {"$strLenCP": "$markdown"}}}
                    ],
                    "purpose": "Thu thập và lưu trữ toàn bộ dữ liệu web tuyển sinh HUIT thô vào collection raw_data."
                }
            ]
        }
    }
}

code_coll = db["code_modules"]
code_coll.update_one({"_id": "huit_raw_miner"}, {"$set": raw_miner_module}, upsert=True)
print(f"[OK] STEP 1 SUCCESS: Saved module 'huit_raw_miner' to collection '{DB}.code_modules'")
client.close()
