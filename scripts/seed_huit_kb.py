"""
Seed HUIT Knowledge Base for Local / Staging Environment
Loads admission documents from data/scraped_pages.json and MongoDB chunks into huit_chatbot.huit_kb.
"""

import json
import os
import sys
from pathlib import Path
import pymongo

WORKSPACE = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DATA_PATH = os.path.join(WORKSPACE, "data", "scraped_pages.json")

def seed():
    mongo_uri = os.getenv("MONGODB_URI", "mongodb://127.0.0.1:27017/huit_chatbot")
    client = pymongo.MongoClient(mongo_uri)
    db = client.get_database()
    kb_col = db["huit_kb"]

    print(f"Target DB: {db.name}, Collection: {kb_col.name}")
    current_count = kb_col.count_documents({})
    print(f"Current document count: {current_count}")

    docs_to_insert = []

    # 1. Load from data/scraped_pages.json
    if os.path.exists(DATA_PATH):
        with open(DATA_PATH, "r", encoding="utf-8") as fp:
            scraped = json.load(fp)
        print(f"Loaded {len(scraped)} pages from {DATA_PATH}")
        for p in scraped:
            text = p.get("markdown") or p.get("text") or ""
            if not text:
                continue
            title = p.get("title", "Tuyển sinh HUIT")
            docs_to_insert.append({
                "title": title,
                "text": text,
                "source_url": p.get("url") or "https://ts.huit.edu.vn",
                "page_title": title,
                "category": "admission",
                "year": 2026,
            })

    # 2. Check if huit_compass_ai.chunks exists on local mongo
    try:
        compass_db = client["huit_compass_ai"]
        if "chunks" in compass_db.list_collection_names():
            chunks = list(compass_db["chunks"].find({}))
            print(f"Found {len(chunks)} chunks in huit_compass_ai.chunks")
            for c in chunks:
                docs_to_insert.append({
                    "title": c.get("title") or "Tuyển sinh HUIT",
                    "text": c.get("content") or "",
                    "source_url": c.get("source_url") or "https://ts.huit.edu.vn",
                    "page_title": c.get("title") or "Tuyển sinh HUIT",
                    "category": c.get("document_type") or "admission",
                    "year": c.get("academic_year") or 2026,
                    "embedding": c.get("embedding"),
                })
    except Exception as e:
        print(f"Could not load compass chunks: {e}")

    if docs_to_insert:
        # Avoid duplicate urls if possible
        print(f"Inserting {len(docs_to_insert)} documents into {kb_col.name}...")
        kb_col.insert_many(docs_to_insert)
        print(f"Seeding completed! New count: {kb_col.count_documents({})}")

        # Create indexes
        kb_col.create_index([("title", pymongo.TEXT), ("text", pymongo.TEXT)], name="text_search_idx")
        kb_col.create_index([("source_url", pymongo.ASCENDING)], name="idx_source_url")
        print("Indexes created.")
    else:
        print("No documents found to insert.")

if __name__ == "__main__":
    seed()
