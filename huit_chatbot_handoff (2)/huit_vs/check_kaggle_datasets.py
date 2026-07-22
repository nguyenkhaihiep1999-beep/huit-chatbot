#!/usr/bin/env python3
"""Check Kaggle API directly for any HUIT or admission datasets."""
import os
import json
import urllib.request
import urllib.parse

def search_kaggle(query):
    encoded_query = urllib.parse.quote(query)
    url = f"https://www.kaggle.com/api/v1/datasets/list?search={encoded_query}"
    
    # Kaggle API requires auth header if credentials exist, or public search
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    try:
        with urllib.request.urlopen(req) as response:
            data = json.loads(response.read().decode('utf-8'))
            return data
    except Exception as e:
        return f"Error: {e}"

queries = ["HUIT", "Cong Thuong", "tuyen sinh HUIT", "huit_chatbot"]
print("[CHECK] Searching Kaggle for HUIT datasets...")

found_any = False
for q in queries:
    res = search_kaggle(q)
    if isinstance(res, list):
        print(f"Query '{q}': found {len(res)} dataset(s)")
        for ds in res[:5]:
            found_any = True
            print(f"  - Title: {ds.get('title')}")
            print(f"    Ref: {ds.get('ref')}")
            print(f"    URL: https://www.kaggle.com/datasets/{ds.get('ref')}")
    else:
        print(f"Query '{q}': {res}")

if not found_any:
    print("\n[RESULT] Currently NO datasets found on Kaggle for HUIT (Trường Đại học Công Thương TP.HCM).")
