#!/usr/bin/env python3
"""
Kaggle HUIT Data Miner & Dataset Synchronizer.
Cào dữ liệu tuyển sinh HUIT, định dạng và tải/đồng bộ lên Kaggle Datasets & MongoDB Atlas.
"""
import os
import sys
import json
import csv
import urllib.request
from urllib.parse import quote_plus
from pymongo import MongoClient

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

HERE = os.path.dirname(os.path.abspath(__file__))
SCAPED_JSON = os.path.join(HERE, "scraped_pages.json")
KAGGLE_CSV = os.path.join(HERE, "huit_kaggle_dataset.csv")

# Database Connection Settings
USER = "nguyenkhaihiep1999_db_user"
HOST = "cluster0.hyj8rab.mongodb.net"
DB_NAME = "huit_chatbot"

pwd = os.environ.get("MONGODB_PASSWORD")
if not pwd:
    env_file = os.path.join(HERE, ".env")
    if os.path.exists(env_file):
        with open(env_file, encoding="utf-8") as f:
            for line in f:
                if line.startswith("MONGODB_PASSWORD="):
                    pwd = line.split("=", 1)[1].strip().strip('"\'')

if not pwd:
    raise RuntimeError("MONGODB_PASSWORD chưa được cấu hình.")

# Load Kaggle credentials from .env
kaggle_user = os.environ.get("KAGGLE_USERNAME")
kaggle_key = os.environ.get("KAGGLE_KEY")
env_file = os.path.join(HERE, ".env")
if os.path.exists(env_file):
    with open(env_file, encoding="utf-8") as f:
        for line in f:
            if line.startswith("KAGGLE_USERNAME=") and not kaggle_user:
                kaggle_user = line.split("=", 1)[1].strip().strip('"\'')
            elif line.startswith("KAGGLE_KEY=") and not kaggle_key:
                kaggle_key = line.split("=", 1)[1].strip().strip('"\'')

if kaggle_user:
    os.environ["KAGGLE_USERNAME"] = kaggle_user
if kaggle_key:
    os.environ["KAGGLE_KEY"] = kaggle_key


def load_local_scraped_data():
    """Load scraped HUIT pages from JSON."""
    if os.path.exists(SCAPED_JSON):
        with open(SCAPED_JSON, encoding="utf-8") as f:
            return json.load(f)
    return []

def export_to_kaggle_csv(data):
    """Export HUIT data to CSV format for Kaggle Datasets upload."""
    if not data:
        print("[WARN] No data available to export to Kaggle CSV.")
        return False
    
    with open(KAGGLE_CSV, mode="w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["id", "url", "title", "content_markdown", "character_count"])
        for idx, doc in enumerate(data, 1):
            url = doc.get("url", "")
            title = doc.get("title", "")
            markdown = doc.get("markdown", "")
            writer.writerow([idx, url, title, markdown, len(markdown)])
            
    print(f"[SUCCESS] Exported {len(data)} documents to Kaggle CSV: {KAGGLE_CSV}")
    return True

def sync_to_mongodb_raw(data):
    """Sync raw scraped documents to MongoDB collection 'raw_data'."""
    if not data:
        return 0
    uri = f"mongodb+srv://{USER}:{quote_plus(pwd)}@{HOST}/?appName=Cluster0"
    client = MongoClient(uri, serverSelectionTimeoutMS=15000)
    db = client[DB_NAME]
    raw_coll = db["raw_data"]
    
    # Refresh raw_data collection
    raw_coll.delete_many({})
    raw_coll.insert_many(data)
    count = raw_coll.count_documents({})
    client.close()
    print(f"[SUCCESS] Synced {count} documents to MongoDB collection '{DB_NAME}.raw_data'")
    return count

def trigger_kaggle_sync():
    """Attempt Kaggle API dataset update if credentials exist."""
    kaggle_user = os.environ.get("KAGGLE_USERNAME")
    kaggle_key = os.environ.get("KAGGLE_KEY")
    
    if not (kaggle_user and kaggle_key):
        return {
            "status": "skipped",
            "message": "Kaggle credentials not configured in environment. Local CSV dataset generated successfully."
        }
        
    try:
        from kaggle.api.kaggle_api_extended import KaggleApi
        api = KaggleApi()
        api.authenticate()
        print(f"[KAGGLE] Authenticated successfully as user '{kaggle_user}'.")
        
        # Prepare upload folder & metadata
        upload_dir = os.path.join(HERE, "kaggle_dataset_dir")
        os.makedirs(upload_dir, exist_ok=True)
        
        # Copy CSV file into upload folder
        dest_csv = os.path.join(upload_dir, "huit_admissions_kb.csv")
        import shutil
        shutil.copyfile(KAGGLE_CSV, dest_csv)
        
        # Create dataset-metadata.json
        meta = {
            "title": "HUIT Admissions Knowledge Base",
            "id": f"{kaggle_user}/huit-admissions-kb",
            "licenses": [{"name": "CC0-1.0"}]
        }
        with open(os.path.join(upload_dir, "dataset-metadata.json"), "w", encoding="utf-8") as f:
            json.dump(meta, f, indent=2)
            
        print(f"[KAGGLE] Pushing dataset '{meta['id']}' to Kaggle...")
        try:
            api.dataset_create_new(upload_dir, dir_mode="zip", public=True)
            msg = f"Kaggle Dataset created successfully: https://www.kaggle.com/datasets/{meta['id']}"
        except Exception as create_err:
            if "already exists" in str(create_err).lower() or "400" in str(create_err):
                api.dataset_create_version(upload_dir, version_notes="Updated HUIT Data", dir_mode="zip")
                msg = f"Kaggle Dataset updated successfully: https://www.kaggle.com/datasets/{meta['id']}"
            else:
                msg = f"Kaggle Upload response: {create_err}"

        return {"status": "success", "message": msg}
    except Exception as e:
        return {
            "status": "error",
            "message": f"Kaggle API note: {e}"
        }

def run_miner():
    print("[1/3] Loading HUIT scraped web data...")
    data = load_local_scraped_data()
    print(f"      Loaded {len(data)} raw web pages.")
    
    print("[2/3] Syncing raw documents to MongoDB Atlas...")
    count = sync_to_mongodb_raw(data)
    
    print("[3/3] Exporting dataset for Kaggle...")
    export_to_kaggle_csv(data)
    
    res = trigger_kaggle_sync()
    print(f"[STATUS] {res['message']}")
    return count

if __name__ == "__main__":
    run_miner()
