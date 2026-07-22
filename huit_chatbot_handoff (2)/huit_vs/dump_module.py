#!/usr/bin/env python3
"""Fetch the stored vector-search module from MongoDB, save as pretty JSON,
and print a summary of the huit_chatbot database state."""
import json
import os
import sys
from urllib.parse import quote_plus
from pymongo import MongoClient

USER = "nguyenkhaihiep1999_db_user"
HOST = "cluster0.hyj8rab.mongodb.net"
DB = "huit_chatbot"

pwd = os.environ.get("MONGODB_PASSWORD")
if not pwd:
    sys.exit("MONGODB_PASSWORD missing")
uri = f"mongodb+srv://{USER}:{quote_plus(pwd)}@{HOST}/?appName=Cluster0"
client = MongoClient(uri, serverSelectionTimeoutMS=12000)
db = client[DB]

print("Database:", DB)
for c in db.list_collection_names():
    print(f"  collection '{c}': {db[c].count_documents({})} docs")

mod = db["code_modules"].find_one({"_id": "huit_semantic_search"})
out = "/home/user/huit_vs/huit_semantic_search.module.json"
with open(out, "w", encoding="utf-8") as f:
    json.dump(mod, f, ensure_ascii=False, indent=2)
print("\nSaved module JSON ->", out)
print("\n--- module preview (private.node_function.edge[0].pipeline) ---")
print(json.dumps(mod["private"]["node_function"]["edge"][0]["pipeline"],
                 ensure_ascii=False, indent=2))
client.close()
