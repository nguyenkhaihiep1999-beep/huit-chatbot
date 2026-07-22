#!/usr/bin/env python3
"""Rebuild HUIT KB (v2): combine official admission pages + tuition articles,
remove repeated boilerplate (banners/menus), chunk cleanly, embed, insert.
"""
import glob
import json
import os
import re
from collections import Counter
from urllib.parse import quote_plus

from pymongo import MongoClient

USER = "nguyenkhaihiep1999_db_user"
HOST = "cluster0.hyj8rab.mongodb.net"
DB = "huit_chatbot"
COLL = "huit_kb"
MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"


def newest(pat):
    fs = sorted(glob.glob(pat), key=os.path.getmtime)
    return fs[-1] if fs else None


def clean_md(md):
    md = re.sub(r'!\[[^\]]*\]\([^)]*\)', ' ', md)       # images
    md = re.sub(r'\[([^\]]*)\]\([^)]*\)', r'\1', md)      # links -> text
    md = re.sub(r'https?://\S+', ' ', md)
    md = md.replace("\\", "")
    md = re.sub(r'[ \t]{2,}', ' ', md)
    return md


def paras(text):
    return [p.strip(" #*->|\t") for p in text.split("\n") if p.strip()]


def label_for(url):
    if "ts.huit.edu.vn" in url or "huit.edu.vn" in url:
        return "HUIT (cổng tuyển sinh chính thức)"
    if "fptshop" in url:
        return "Bài viết học phí HUIT (FPT Shop)"
    if "cellphones" in url:
        return "Bài viết học phí HUIT (CellphoneS)"
    return "Nguồn khác"


# 1) gather docs from local scraped_pages.json (portable for handoff)
HERE = os.path.dirname(os.path.abspath(__file__))
docs = []
scraped = os.path.join(HERE, "scraped_pages.json")
if os.path.exists(scraped):
    for it in json.load(open(scraped, encoding="utf-8")):
        docs.append({"url": it.get("url", ""), "title": it.get("title", "HUIT"),
                     "text": clean_md(it.get("markdown", "") or "")})
else:
    # fallback: original dev environment (Firecrawl spillover)
    spillover_dir = os.path.join(os.path.expanduser("~"), ".spillover")
    for bf in sorted(glob.glob(os.path.join(spillover_dir, "batch_scrape_*.txt")), key=os.path.getmtime):
        for it in json.load(open(bf)):
            meta = it.get("metadata", {}) or {}
            docs.append({"url": meta.get("sourceURL") or meta.get("url", ""),
                         "title": meta.get("title", "") or "HUIT",
                         "text": clean_md(it.get("markdown", "") or "")})
    for sf in sorted(glob.glob(os.path.join(spillover_dir, "search_*.txt")), key=os.path.getmtime):
        for w in json.load(open(sf)).get("web", []):
            if any(k in w.get("url", "") for k in ["fptshop", "cellphones", "ts.huit.edu.vn/thong-bao"]):
                docs.append({"url": w["url"], "title": w.get("title", "HUIT"),
                             "text": clean_md(w.get("markdown", "") or "")})

print(f"Docs gathered: {len(docs)}")

# 2) boilerplate detection: paragraphs appearing across >=3 docs
freq = Counter()
for d in docs:
    for p in set(paras(d["text"])):
        freq[p] += 1
boiler = {p for p, c in freq.items() if c >= 3}
print(f"Boilerplate paragraphs removed: {len(boiler)}")


def chunk(text, min_len=140, max_len=650):
    out, buf = [], ""
    for p in paras(text):
        if p in boiler:
            continue
        words = p.split()
        if len(p) < 45 and not p.endswith((".", "?", ":", "%")):
            continue
        if len(words) < 6 and not any(ch.isdigit() for ch in p):
            continue
        if len(buf) + len(p) + 1 <= max_len:
            buf = (buf + " " + p).strip()
        else:
            if len(buf) >= min_len:
                out.append(buf)
            buf = p
    if len(buf) >= min_len:
        out.append(buf)
    return out


# 3) build records + dedup
records, seen = [], set()
for d in docs:
    for c in chunk(d["text"]):
        k = c[:90]
        if k in seen:
            continue
        seen.add(k)
        records.append({"title": label_for(d["url"]), "text": c,
                        "source_url": d["url"], "page_title": d["title"][:120]})

from collections import Counter as C2
print(f"Total clean chunks: {len(records)}")
for lbl, n in C2(r["title"] for r in records).items():
    print(f"  - {lbl}: {n}")

# 4) embed + insert
from fastembed import TextEmbedding
model = TextEmbedding(MODEL)
vecs = [v.tolist() for v in model.embed([r["text"] for r in records])]
for r, v in zip(records, vecs):
    r["embedding"] = v

pwd = os.environ.get("MONGODB_PASSWORD")
if not pwd:
    import sys
    sys.exit("MONGODB_PASSWORD missing")
uri = f"mongodb+srv://{USER}:{quote_plus(pwd)}@{HOST}/?appName=Cluster0"
client = MongoClient(uri, serverSelectionTimeoutMS=12000)
coll = client[DB][COLL]
coll.drop()
coll.insert_many(records)
print(f"\nInserted {coll.count_documents({})} clean chunks into {DB}.{COLL}")

# Recreate Vector Search Index
from pymongo.operations import SearchIndexModel
INDEX = "huit_vector_index"
DIMS = 384
idx = SearchIndexModel(
    definition={"fields": [{
        "type": "vector", "path": "embedding",
        "numDimensions": DIMS, "similarity": "cosine",
    }]},
    name=INDEX, type="vectorSearch",
)
coll.create_search_index(model=idx)
print(f"Vector index '{INDEX}' creation requested (builds in background).")

client.close()
print("DONE_REBUILD")
