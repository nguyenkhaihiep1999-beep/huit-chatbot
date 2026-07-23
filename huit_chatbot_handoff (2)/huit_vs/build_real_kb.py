#!/usr/bin/env python3
"""
build_real_kb.py
Rebuild HUIT Knowledge Base (KB v3):
- Extract clean Markdown chunks from 39 majors + real-time admissions notices.
- Remove external non-HUIT boilerplate.
- Embed chunks using fastembed (sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2).
- Upload clean records to MongoDB Atlas `huit_chatbot.huit_kb`.
- Recreate Vector Search Index `huit_vector_index`.
"""

import glob
import json
import os
import re
import sys
from urllib.parse import quote_plus
from pymongo import MongoClient
from pymongo.operations import SearchIndexModel

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

USER = "nguyenkhaihiep1999_db_user"
HOST = "cluster0.hyj8rab.mongodb.net"
DB = "huit_chatbot"
COLL = "huit_kb"
MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
HERE = os.path.dirname(os.path.abspath(__file__))


def clean_markdown(text):
    """Remove HTML tags and unwanted links while keeping structural markdown."""
    text = re.sub(r'!\[[^\]]*\]\([^)]*\)', ' ', text)  # images
    text = re.sub(r'\[([^\]]*)\]\([^)]*\)', r'\1', text)  # links -> text
    text = re.sub(r'https?://\S+', ' ', text)
    text = text.replace("\\", "")
    text = re.sub(r'[ \t]{2,}', ' ', text)
    return text.strip()


def chunk_document(doc, max_chunk_size=750):
    """Chunk document cleanly by markdown sections and paragraphs."""
    url = doc.get("url", "")
    page_title = doc.get("title", "Tuyển sinh HUIT")
    raw_md = doc.get("markdown", "") or ""

    # Skip external non-official retail ads
    if any(k in url.lower() for k in ["fptshop", "cellphones"]):
        return []

    cleaned = clean_markdown(raw_md)
    paragraphs = [p.strip() for p in cleaned.split("\n") if p.strip()]

    chunks = []
    current_buf = []
    current_len = 0

    for p in paragraphs:
        # Ignore repetitive web navigation footers
        if any(skip in p for skip in ["Trang chủ HUIT", "Thống kê truy cập", "DOFA TECH", "Chatbot Button"]):
            continue

        p_len = len(p)
        if current_len + p_len > max_chunk_size and current_buf:
            chunk_text = "\n".join(current_buf).strip()
            if len(chunk_text) >= 80:
                chunks.append(chunk_text)
            current_buf = [p]
            current_len = p_len
        else:
            current_buf.append(p)
            current_len += p_len + 1

    if current_buf:
        chunk_text = "\n".join(current_buf).strip()
        if len(chunk_text) >= 80:
            chunks.append(chunk_text)

    # Attach document metadata
    records = []
    for c in chunks:
        records.append({
            "title": f"{page_title[:100]} (HUIT Cổng tuyển sinh chính thức)",
            "text": c,
            "source_url": url,
            "page_title": page_title[:120]
        })
    return records


def run_rebuild():
    print("=========================================================")
    print("   REBUILDING HUIT KB VECTOR DATABASE ON MONGODB ATLAS")
    print("=========================================================")

    scraped_file = os.path.join(HERE, "scraped_pages.json")
    if not os.path.exists(scraped_file):
        sys.exit(f"Error: Scraped file {scraped_file} not found.")

    with open(scraped_file, encoding="utf-8") as f:
        docs = json.load(f)

    print(f"[1/4] Loaded {len(docs)} raw documents from scraped_pages.json")

    all_records = []
    seen = set()
    for d in docs:
        doc_chunks = chunk_document(d)
        for r in doc_chunks:
            k = r["text"][:100]
            if k not in seen:
                seen.add(k)
                all_records.append(r)

    print(f"[2/4] Generated {len(all_records)} unique clean knowledge chunks.")

    print(f"[3/4] Embedding {len(all_records)} chunks with FastEmbed model '{MODEL}'...")
    from fastembed import TextEmbedding
    embedder = TextEmbedding(MODEL)
    vectors = [v.tolist() for v in embedder.embed([r["text"] for r in all_records])]

    for r, v in zip(all_records, vectors):
        r["embedding"] = v

    print(f"[4/4] Uploading {len(all_records)} embedded chunks to MongoDB Atlas...")
    pwd = os.environ.get("MONGODB_PASSWORD", "qwertyuio12A")
    uri = f"mongodb+srv://{USER}:{quote_plus(pwd)}@{HOST}/?appName=Cluster0"
    client = MongoClient(uri, serverSelectionTimeoutMS=15000)
    db = client[DB]
    coll = db[COLL]

    coll.drop()
    coll.insert_many(all_records)
    count = coll.count_documents({})
    print(f"[SUCCESS] Uploaded {count} chunks to collection '{DB}.{COLL}'")

    # Recreate Vector Search Index
    print("Recreating Atlas Vector Search Index 'huit_vector_index'...")
    index_model = SearchIndexModel(
        definition={
            "fields": [
                {
                    "type": "vector",
                    "path": "embedding",
                    "numDimensions": 384,
                    "similarity": "cosine"
                }
            ]
        },
        name="huit_vector_index",
        type="vectorSearch"
    )
    try:
        coll.create_search_index(model=index_model)
        print("[SUCCESS] Vector index 'huit_vector_index' creation requested on Atlas.")
    except Exception as e:
        print(f"[WARN] Index creation note: {e}")

    client.close()
    print("=========================================================")
    print("   HUIT REBUILD KB COMPLETE!")
    print("=========================================================")


if __name__ == "__main__":
    run_rebuild()
