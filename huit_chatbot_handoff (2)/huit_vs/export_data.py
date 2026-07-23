#!/usr/bin/env python3
"""Xuất dữ liệu trong huit_kb ra file CSV dễ đọc (để xem không cần vào Atlas)."""
import csv
import os
import sys
from urllib.parse import quote_plus
from pymongo import MongoClient

USER = "nguyenkhaihiep1999_db_user"
HOST = "cluster0.hyj8rab.mongodb.net"
DB = "huit_chatbot"

HERE = os.path.dirname(os.path.abspath(__file__))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

pwd = os.environ.get("MONGODB_PASSWORD", "qwertyuio12A")
uri = f"mongodb+srv://{USER}:{quote_plus(pwd)}@{HOST}/?appName=Cluster0"
client = MongoClient(uri, serverSelectionTimeoutMS=12000)

out = os.path.join(HERE, "huit_kb_data.csv")
with open(out, "w", newline="", encoding="utf-8-sig") as f:
    w = csv.writer(f)
    w.writerow(["#", "title", "text", "embedding_dims", "embedding_preview (5 số đầu)"])
    for i, d in enumerate(client[DB]["huit_kb"].find(), 1):
        emb = d.get("embedding", [])
        w.writerow([i, d.get("title", ""), d.get("text", ""),
                    len(emb), ", ".join(f"{x:.4f}" for x in emb[:5]) + " ..."])
print("Saved:", out)
print("\nTổng quan database 'huit_chatbot':")
for c in client[DB].list_collection_names():
    print(f"  - {c}: {client[DB][c].count_documents({})} docs")
client.close()
