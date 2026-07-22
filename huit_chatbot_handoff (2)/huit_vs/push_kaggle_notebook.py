#!/usr/bin/env python3
"""
Push Python Code & Notebook Pipeline directly to Kaggle Code Hub (https://www.kaggle.com/code).
"""
import os
import json
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))

# Read Kaggle Credentials
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
    os.environ["KAGGLE_API_TOKEN"] = kaggle_key

# Write kaggle.json & access_token to user home directory
user_home = os.path.expanduser("~")
kaggle_dir = os.path.join(user_home, ".kaggle")
os.makedirs(kaggle_dir, exist_ok=True)

if kaggle_user and kaggle_key:
    with open(os.path.join(kaggle_dir, "kaggle.json"), "w", encoding="utf-8") as f:
        json.dump({"username": kaggle_user, "key": kaggle_key}, f)
    with open(os.path.join(kaggle_dir, "access_token"), "w", encoding="utf-8") as f:
        f.write(kaggle_key.strip())

def push_notebook_to_kaggle():
    from kaggle.api.kaggle_api_extended import KaggleApi
    api = KaggleApi()
    api.authenticate()
    print(f"[KAGGLE] Authenticated as user '{kaggle_user}' for Notebook Push.")
    
    kernel_dir = os.path.join(HERE, "kaggle_kernel_dir")
    os.makedirs(kernel_dir, exist_ok=True)
    
    # Write Python Script Code File
    code_path = os.path.join(kernel_dir, "huit_chatbot_pipeline.py")
    python_code = '''# HUIT Chatbot Data Mining & MongoDB Aggregation Suite
# Auto-generated Kaggle Pipeline for HUIT Admission Data

import os
import json
import pandas as pd

print("=== HUIT ADMISSION DATA PIPELINE & MONGODB AGGREGATIONS ===")

# 1. Load HUIT Dataset
df = pd.read_csv('/kaggle/input/huit-admissions-kb/huit_admissions_kb.csv')
print(f"Loaded {len(df)} admission documents from Kaggle Dataset.")
print("Sample Titles:")
print(df[['id', 'title']].head())

# 2. Categorize HUIT Data
print("\\nCategorizing HUIT Data...")
categories = {
    'Hoc phi': df[df['content_markdown'].str.contains('hoc phi|tien hoc|le phi', case=False, na=False)],
    'Diem chuan': df[df['content_markdown'].str.contains('diem chuan|diem san', case=False, na=False)],
    'Hoc bong': df[df['content_markdown'].str.contains('hoc bong|khuyen hoc', case=False, na=False)],
    'Nganh dao tao': df[df['content_markdown'].str.contains('nganh|ky thuat', case=False, na=False)]
}

for cat, sub_df in categories.items():
    print(f"  - [{cat}]: {len(sub_df)} documents")

print("\\n[SUCCESS] Kaggle HUIT Admission Pipeline Execution Completed!")
'''
    with open(code_path, "w", encoding="ascii", errors="ignore") as f:
        f.write(python_code)
        
    # Write kernel-metadata.json matching slug
    slug_id = "huit-chatbot-data-mining-mongo-aggregation"
    kernel_meta = {
        "id": f"{kaggle_user}/{slug_id}",
        "title": "Huit Chatbot Data Mining Mongo Aggregation",
        "code_file": "huit_chatbot_pipeline.py",
        "language": "python",
        "kernel_type": "script",
        "is_private": "false",
        "enable_gpu": "false",
        "enable_internet": "true",
        "dataset_sources": [f"{kaggle_user}/huit-admissions-kb"],
        "competition_sources": [],
        "kernel_sources": []
    }
    
    meta_path = os.path.join(kernel_dir, "kernel-metadata.json")
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(kernel_meta, f, indent=2)
        
    print(f"[KAGGLE] Pushing Code Kernel '{kernel_meta['id']}' to Kaggle Code...")
    res = api.kernels_push(kernel_dir)
    web_url = f"https://www.kaggle.com/code/{kernel_meta['id']}"
    print(f"[SUCCESS] Code Kernel Pushed! Web URL: {web_url}")
    return web_url

if __name__ == "__main__":
    push_notebook_to_kaggle()
