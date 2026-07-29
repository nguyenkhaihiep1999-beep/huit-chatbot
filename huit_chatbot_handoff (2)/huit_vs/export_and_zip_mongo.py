#!/usr/bin/env python3
"""Script to export all MongoDB collections and modules into a clean ZIP file for Zalo transfer."""
import os
import sys
import json
import zipfile
from urllib.parse import quote_plus
from pymongo import MongoClient

HERE = os.path.dirname(os.path.abspath(__file__))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

# Auto-load .env
_env = os.path.join(HERE, ".env")
if os.path.exists(_env):
    for line in open(_env, encoding="utf-8"):
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ[k.strip()] = v.strip()

USER = "nguyenkhaihiep1999_db_user"
HOST = "cluster0.hyj8rab.mongodb.net"
DB = "huit_chatbot"

pwd = os.environ.get("MONGODB_PASSWORD")
if not pwd:
    sys.exit("MONGODB_PASSWORD missing")

uri = f"mongodb+srv://{USER}:{quote_plus(pwd)}@{HOST}/?appName=Cluster0"
client = MongoClient(uri, serverSelectionTimeoutMS=12000)

export_dir = os.path.join(HERE, "mongodb_export_temp")
os.makedirs(export_dir, exist_ok=True)

# 1. Export MongoDB collections
collections = client[DB].list_collection_names()
print(f"Connecting to MongoDB Atlas 'huit_chatbot'...")
print(f"Found collections: {collections}")

total_files = 0
for col_name in collections:
    docs = list(client[DB][col_name].find())
    col_file = os.path.join(export_dir, f"{col_name}.json")
    
    # Custom JSON serializer for BSON ObjectId and datetimes
    def bson_dumps(obj):
        if isinstance(obj, dict):
            return {k: bson_dumps(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [bson_dumps(x) for x in obj]
        elif hasattr(obj, "isoformat"):
            return obj.isoformat()
        elif hasattr(obj, "__str__") and type(obj).__name__ == "ObjectId":
            return str(obj)
        return obj

    clean_docs = [bson_dumps(d) for d in docs]
    with open(col_file, "w", encoding="utf-8") as f:
        json.dump(clean_docs, f, ensure_ascii=False, indent=2)
    print(f"  [OK] Exported {len(docs)} documents to {col_name}.json")
    total_files += 1

# 2. Also copy mongo_modules directory files if present
mongo_modules_dir = os.path.join(HERE, "mongo_modules")
modules_subfolder = os.path.join(export_dir, "code_modules_files")
os.makedirs(modules_subfolder, exist_ok=True)

if os.path.exists(mongo_modules_dir):
    for fname in os.listdir(mongo_modules_dir):
        if fname.endswith(".json"):
            src = os.path.join(mongo_modules_dir, fname)
            dst = os.path.join(modules_subfolder, fname)
            with open(src, encoding="utf-8") as f_in, open(dst, "w", encoding="utf-8") as f_out:
                f_out.write(f_in.read())
            total_files += 1

# 3. Create ZIP File
zip_name = "HUIT_MongoDB_Export_52_Parts.zip"
zip_path_vs = os.path.join(HERE, zip_name)
zip_path_root = os.path.abspath(os.path.join(HERE, "..", "..", zip_name))

def create_zip(target_zip):
    with zipfile.ZipFile(target_zip, "w", zipfile.ZIP_DEFLATED) as zipf:
        for root, dirs, files in os.walk(export_dir):
            for file in files:
                full_path = os.path.join(root, file)
                rel_path = os.path.relpath(full_path, export_dir)
                zipf.write(full_path, rel_path)

create_zip(zip_path_vs)
if os.path.exists(os.path.dirname(zip_path_root)):
    create_zip(zip_path_root)

print("\n" + "="*60)
print(f"[SUCCESS] Exported total {total_files} parts from MongoDB Atlas.")
print(f"[ZIP FILE CREATED]: {zip_path_vs}")
print(f"[ZIP COPY CREATED]: {zip_path_root}")
print("="*60)
client.close()
