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
import time
from datetime import datetime, timezone
from urllib.parse import quote_plus
from urllib.parse import urlparse
from pymongo import MongoClient
from pymongo.operations import SearchIndexModel

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

USER = "nguyenkhaihiep1999_db_user"
HOST = "cluster0.hyj8rab.mongodb.net"
DB = "huit_chatbot"
COLL = "huit_kb"
MODEL = "intfloat/multilingual-e5-large"
DIMS = 1024
HERE = os.path.dirname(os.path.abspath(__file__))


def load_mongodb_password():
    password = os.environ.get("MONGODB_PASSWORD", "").strip()
    env_file = os.path.join(HERE, ".env")
    if not password and os.path.exists(env_file):
        with open(env_file, encoding="utf-8") as handle:
            for line in handle:
                if line.startswith("MONGODB_PASSWORD="):
                    password = line.split("=", 1)[1].strip().strip("\"'")
                    break
    return password


def clean_markdown(text):
    """Remove HTML tags and unwanted links while keeping structural markdown."""
    text = re.sub(r'!\[[^\]]*\]\([^)]*\)', ' ', text)  # images
    text = re.sub(r'\[([^\]]*)\]\([^)]*\)', r'\1', text)  # links -> text
    text = re.sub(r'https?://\S+', ' ', text)
    text = text.replace("\\", "")
    text = re.sub(r'[ \t]{2,}', ' ', text)
    return text.strip()


def infer_record_metadata(page_title, text):
    combined = f"{page_title} {text}".lower()
    if "học phí" in page_title.lower():
        category = "tuition"
    elif "điểm sàn" in page_title.lower() or "điểm chuẩn" in page_title.lower():
        category = "cutoff"
    elif "học bổng" in page_title.lower():
        category = "scholarship"
    elif any(term in page_title.lower() for term in [
        "phương thức", "xét tuyển", "thông tin tuyển sinh"
    ]):
        category = "admission"
    elif "ngành" in page_title.lower() or re.search(r"\b7\d{6}\b", combined):
        category = "major"
    elif "địa chỉ" in combined or "liên hệ" in combined:
        category = "contact"
    else:
        category = "general"
    years = [int(value) for value in re.findall(r"\b20\d{2}\b", combined)]
    major_match = re.search(r"\b7\d{6}\b", combined)
    return {
        "category": category,
        "year": max(years) if years else None,
        "major_code": major_match.group(0) if major_match else None,
        "updated_at": datetime.now(timezone.utc),
    }


def chunk_document(doc, max_chunk_size=750):
    """Chunk document cleanly by markdown sections with Contextual Metadata Header."""
    url = doc.get("url", "")
    page_title = doc.get("title", "Tuyển sinh HUIT").strip()
    raw_md = doc.get("markdown", "") or ""

    # Only official HUIT admissions pages are allowed into the verified KB.
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname != "ts.huit.edu.vn":
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

    # Attach document metadata with Anthropic Contextual Retrieval Header
    records = []
    context_prefix = f"[Trường Đại học Công Thương TP.HCM (HUIT) | Nguồn chính thức ts.huit.edu.vn | Chủ đề: {page_title[:100]}]"
    document_metadata = infer_record_metadata(page_title, cleaned)
    for c in chunks:
        # Contextual Text combining header + chunk
        contextual_text = f"{context_prefix}\n{c}"
        record = {
            "title": f"{page_title[:100]} (HUIT Cổng tuyển sinh chính thức)",
            "text": contextual_text,
            "raw_text": c,
            "source_url": url,
            "page_title": page_title[:120],
            "source_domain": "ts.huit.edu.vn",
            "official": True,
            "retrieved_at": doc.get("retrieved_at"),
            "verification_status": "official_source",
        }
        record.update(document_metadata)
        records.append(record)
    return records


def run_rebuild():
    print("=========================================================")
    print("   REBUILDING HUIT KB VECTOR DATABASE ON MONGODB ATLAS")
    print("   CONTEXTUAL CHUNKING + E5-LARGE 1024D EMBEDDINGS")
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
            k = r["text"][:120]
            if k not in seen:
                seen.add(k)
                all_records.append(r)

    print(f"[2/4] Generated {len(all_records)} unique Contextual Knowledge Chunks.")

    print(f"[3/4] Embedding {len(all_records)} chunks with FastEmbed SOTA Model '{MODEL}' (1024D)...")
    from fastembed import TextEmbedding
    embedder = TextEmbedding(MODEL)
    vectors = [v.tolist() for v in embedder.embed([r["text"] for r in all_records])]

    for r, v in zip(all_records, vectors):
        r["embedding"] = v

    print(f"[4/4] Uploading {len(all_records)} embedded chunks to MongoDB Atlas...")
    pwd = load_mongodb_password()
    if not pwd:
        raise RuntimeError("MONGODB_PASSWORD chưa được cấu hình.")
    uri = f"mongodb+srv://{USER}:{quote_plus(pwd)}@{HOST}/?appName=Cluster0"
    client = MongoClient(uri, serverSelectionTimeoutMS=15000)
    db = client[DB]
    staging_name = f"{COLL}_build_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"
    staging = db[staging_name]
    staging.insert_many(all_records)
    count = staging.count_documents({})
    print(f"[SUCCESS] Uploaded {count} chunks to staging collection '{DB}.{staging_name}'")

    # Recreate Vector Search Index
    print("Recreating Atlas Vector Search Index 'huit_vector_index' (1024D)...")
    index_model = SearchIndexModel(
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
        name="huit_vector_index",
        type="vectorSearch"
    )
    try:
        staging.create_search_index(model=index_model)
        print("[SUCCESS] Vector index creation requested on staging collection.")
        deadline = time.time() + 180
        while time.time() < deadline:
            indexes = list(staging.list_search_indexes())
            if any(
                item.get("name") == "huit_vector_index" and item.get("queryable")
                for item in indexes
            ):
                break
            time.sleep(5)
        else:
            raise RuntimeError(
                "Vector index staging chưa sẵn sàng sau 180 giây; "
                "collection live được giữ nguyên."
            )

        staging.rename(COLL, dropTarget=True)
        print(
            f"[SUCCESS] Atomically promoted '{staging_name}' to '{DB}.{COLL}'."
        )
    except Exception as e:
        print(f"[ERROR] KB promotion aborted; live collection remains unchanged: {e}")
        client.close()
        raise

    client.close()
    print("=========================================================")
    print("   HUIT REBUILD KB COMPLETE!")
    print("=========================================================")


if __name__ == "__main__":
    run_rebuild()
