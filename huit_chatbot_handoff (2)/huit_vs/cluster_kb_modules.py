#!/usr/bin/env python3
"""Module Học máy: Phân cụm Tri thức HUIT (K-Means Clustering).

Script này gom cụm toàn bộ vector tri thức 1024D trong MongoDB Atlas thành K=5 cụm chủ đề:
- Cluster 0: Thông tin Ngành học & Mã ngành
- Cluster 1: Điểm sàn & Phương thức xét tuyển
- Cluster 2: Chính sách Học phí & Học bổng
- Cluster 3: Tư vấn Hướng nghiệp & Cơ hội việc làm
- Cluster 4: Quy chế Đào tạo & Khác

Kết quả:
1. Cập nhật `cluster_id` và `cluster_name` vào từng document trong MongoDB `huit_kb`.
2. Lưu các tâm cụm (Centroids) ra file `huit_cluster_centroids.json` phục vụ RAG search.
"""

import json
import os
import re
import sys
import time
from urllib.parse import quote_plus
import numpy as np
from sklearn.cluster import KMeans
from pymongo import MongoClient

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

HERE = os.path.dirname(os.path.abspath(__file__))
USER = "nguyenkhaihiep1999_db_user"
HOST = "cluster0.hyj8rab.mongodb.net"
DB = "huit_chatbot"
COLL = "huit_kb"
CENTROIDS_FILE = os.path.join(HERE, "huit_cluster_centroids.json")

# Nạp .env
_env_path = os.path.join(HERE, ".env")
if os.path.exists(_env_path):
    with open(_env_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ[k.strip()] = v.strip().strip('"\'')

CLUSTER_NAMES = {
    0: "Thông tin Ngành học & Mã ngành",
    1: "Điểm sàn & Phương thức xét tuyển",
    2: "Chính sách Học phí & Học bổng",
    3: "Tư vấn Hướng nghiệp & Cơ hội việc làm",
    4: "Quy chế Đào tạo & Khác"
}


def run_clustering(n_clusters=5):
    pwd = os.environ.get("MONGODB_PASSWORD")
    if not pwd:
        raise RuntimeError("MONGODB_PASSWORD chưa được cấu hình trong .env!")

    uri = f"mongodb+srv://{USER}:{quote_plus(pwd)}@{HOST}/?appName=Cluster0"
    mongo = MongoClient(uri, serverSelectionTimeoutMS=15000)
    coll = mongo[DB][COLL]

    print(f"🔄 Đang nạp dữ liệu từ collection '{COLL}'...")
    docs = list(coll.find({}, {"_id": 1, "title": 1, "text": 1, "category": 1, "vector": 1}))
    print(f"📊 Tổng số văn bản tìm thấy: {len(docs)}")

    if not docs:
        print("⚠️ Không có văn bản nào trong collection.")
        return

    # Lấy hoặc tạo vector cho các văn bản
    valid_docs = []
    vectors = []

    need_embed_docs = [d for d in docs if not d.get("vector") or len(d.get("vector", [])) != 1024]
    
    if need_embed_docs:
        print(f"⚙️ Cần tạo vector mới cho {len(need_embed_docs)} văn bản bằng FastEmbed...")
        from fastembed import TextEmbedding
        embedder = TextEmbedding("intfloat/multilingual-e5-large")
        texts = [f"{d.get('title', '')} {d.get('text', '')}"[:1000] for d in need_embed_docs]
        gen_vecs = list(embedder.embed(texts))
        for idx, d in enumerate(need_embed_docs):
            vec = gen_vecs[idx].tolist()
            d["vector"] = vec
            coll.update_one({"_id": d["_id"]}, {"$set": {"vector": vec}})

    for d in docs:
        vec = d.get("vector")
        if vec and len(vec) == 1024:
            valid_docs.append(d)
            vectors.append(vec)

    X = np.array(vectors, dtype=np.float32)
    print(f"✅ Ma trận đặc trưng Vector: {X.shape}")

    # Chạy K-Means Clustering
    print(f"🧠 Đang chạy thuật toán K-Means Clustering (K={n_clusters})...")
    kmeans = KMeans(n_clusters=n_clusters, random_state=42, n_init=10)
    labels = kmeans.fit_predict(X)
    centroids = kmeans.cluster_centers_

    # Gán tên cụm thông minh dựa trên phân bố category
    cluster_mapping = {}
    for c_id in range(n_clusters):
        c_docs = [valid_docs[i] for i, lbl in enumerate(labels) if lbl == c_id]
        cat_counts = {}
        for d in c_docs:
            cat = d.get("category", "general")
            cat_counts[cat] = cat_counts.get(cat, 0) + 1
        top_cat = max(cat_counts.items(), key=lambda x: x[1])[0] if cat_counts else "general"
        
        name_map = {
            "major": "Thông tin Ngành học & Mã ngành",
            "cutoff": "Điểm sàn & Phương thức xét tuyển",
            "tuition": "Chính sách Học phí & Học bổng",
            "career": "Tư vấn Hướng nghiệp & Cơ hội việc làm",
            "admission": "Phương thức xét tuyển Đại học"
        }
        cluster_name = name_map.get(top_cat, f"Cụm chủ đề {c_id + 1}")
        cluster_mapping[c_id] = {
            "name": cluster_name,
            "count": len(c_docs),
            "top_category": top_cat
        }
        print(f"   📌 Cluster {c_id}: '{cluster_name}' ({len(c_docs)} văn bản, top category: {top_cat})")

    # Cập nhật cluster_id và cluster_name vào MongoDB Atlas
    print("💾 Đang cập nhật nhãn cụm vào MongoDB Atlas...")
    for idx, d in enumerate(valid_docs):
        c_id = int(labels[idx])
        c_name = cluster_mapping[c_id]["name"]
        coll.update_one(
            {"_id": d["_id"]},
            {"$set": {"cluster_id": c_id, "cluster_name": c_name}}
        )

    # Lưu Centroids vào JSON để RAG engine nạp trực tiếp
    centroid_data = {
        "n_clusters": n_clusters,
        "clusters": {
            str(c_id): {
                "name": cluster_mapping[c_id]["name"],
                "centroid": centroids[c_id].tolist(),
                "count": cluster_mapping[c_id]["count"]
            }
            for c_id in range(n_clusters)
        },
        "updated_at": time.strftime("%Y-%m-%d %H:%M:%S")
    }

    with open(CENTROIDS_FILE, "w", encoding="utf-8") as f:
        json.dump(centroid_data, f, ensure_ascii=False, indent=2)

    print(f"🎉 Đã phân cụm thành công và lưu centroids tại '{CENTROIDS_FILE}'!")


if __name__ == "__main__":
    run_clustering()
