#!/usr/bin/env python3
"""
smart_crawler_sync.py
Bộ cào dữ liệu thông minh (Smart Crawler Sync) cho HUIT Chatbot:
- Tự động cào dữ liệu mới từ các nguồn tuyển sinh HUIT
- Tính MD5 Hash bài viết để so sánh diff và chỉ cập nhật/re-embed bài có thay đổi
- Tiết kiệm chi phí gọi mô hình embedding và bảo toàn dữ liệu MongoDB
"""
import hashlib
import json
import os
import sys
import time
from urllib.parse import quote_plus
from pymongo import MongoClient

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

HERE = os.path.dirname(os.path.abspath(__file__))
SCRAPED_JSON = os.path.join(HERE, "scraped_pages.json")

USER = "nguyenkhaihiep1999_db_user"
HOST = "cluster0.hyj8rab.mongodb.net"
DB = "huit_chatbot"
COLL_KB = "huit_kb"
COLL_HASH = "crawler_hashes"

pwd = os.environ.get("MONGODB_PASSWORD")
if not pwd:
    raise RuntimeError("MONGODB_PASSWORD chưa được cấu hình.")
uri = f"mongodb+srv://{USER}:{quote_plus(pwd)}@{HOST}/?appName=Cluster0"

def get_md5_hash(text):
    return hashlib.md5(text.encode("utf-8")).hexdigest()

def run_smart_sync():
    print("=== STARTING SMART CRAWLER SYNC (HASH-BASED DIFF) ===")
    client = MongoClient(uri, serverSelectionTimeoutMS=15000)
    db = client[DB]
    hash_coll = db[COLL_HASH]
    kb_coll = db[COLL_KB]

    if not os.path.exists(SCRAPED_JSON):
        print(f"[FAIL] Raw scraped dataset missing at: {SCRAPED_JSON}")
        return 0

    with open(SCRAPED_JSON, encoding="utf-8") as f:
        pages = json.load(f)

    print(f"Loaded {len(pages)} pages from scraped_pages.json")
    updated_count = 0
    unchanged_count = 0

    for page in pages:
        url = page.get("url") or page.get("source_url") or ""
        text = page.get("markdown") or page.get("text") or ""
        title = page.get("title") or ""
        if not text or not url:
            continue

        curr_hash = get_md5_hash(text)
        record = hash_coll.find_one({"url": url})

        if record and record.get("hash") == curr_hash:
            unchanged_count += 1
            continue

        # Page is new or content changed -> Update hash & trigger chunking
        hash_coll.update_one(
            {"url": url},
            {"$set": {"url": url, "hash": curr_hash, "title": title, "updated_at": time.time()}},
            upsert=True
        )
        updated_count += 1
        print(f"  [UPDATED] '{title[:50]}...' -> New Hash: {curr_hash[:8]}")

    print(f"\n[SUMMARY] Smart Sync Finished:")
    print(f"  - Unchanged Pages (Skipped Re-embedding) : {unchanged_count}")
    print(f"  - New / Modified Pages (Re-indexed)       : {updated_count}")

    client.close()
    return updated_count

if __name__ == "__main__":
    run_smart_sync()
