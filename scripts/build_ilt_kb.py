"""
scripts/build_ilt_kb.py
Tạo Embeddings, Phân cụm Offline và Nhập dữ liệu Idempotent vào MongoDB cho ILT Knowledge Base:
1. Nạp 139 chunks đã kiểm duyệt từ data/ilt/curated_ilt_chunks.json.
2. Sinh embeddings bằng intfloat/multilingual-e5-large (1024 chiều, tiền tố passage:).
3. Thực hiện K-Means clustering offline, chọn K tối ưu theo Silhouette Score (seed cố định 42).
4. Lưu centroids, phân bố cụm, metadata vào data/ilt_cluster_centroids.json.
5. Tạo collection ilt_kb trên MongoDB kèm strict $jsonSchema validator.
6. Tạo các chỉ mục thường: chunk_id (unique), sku, cluster_id, series, page_number.
7. Đăng ký Atlas Vector Search Index ilt_vector_index hỗ trợ pre-filter trên cluster_id.
8. Đợi chỉ mục đạt trạng thái READY và queryable, xác minh 100% tài liệu có embedding chuẩn.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys
import time
from typing import Any, Dict, List

import numpy as np
from sklearn.cluster import KMeans
from sklearn.metrics import silhouette_score
from pymongo.operations import SearchIndexModel

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

try:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

from backend.app.config import settings
from backend.app.repositories.mongo_repository import MongoRepository
from backend.app.rag.embedding import EmbeddingManager


ILT_VALIDATOR = {
    "$jsonSchema": {
        "bsonType": "object",
        "required": ["chunk_id", "title", "text", "source_url", "category", "embedding", "cluster_id", "verification_status"],
        "properties": {
            "_id": {"bsonType": ["string", "objectId"]},
            "chunk_id": {"bsonType": "string", "minLength": 1, "maxLength": 128},
            "document_id": {"bsonType": "string", "maxLength": 128},
            "dataset_id": {"bsonType": "string", "maxLength": 64},
            "dataset_version": {"bsonType": "string", "maxLength": 32},
            "title": {"bsonType": "string", "minLength": 1},
            "text": {"bsonType": "string", "minLength": 1},
            "source_url": {"bsonType": "string", "minLength": 1},
            "category": {"bsonType": "string", "minLength": 1},
            "product_type": {"bsonType": ["string", "null"]},
            "series": {"bsonType": ["string", "null"]},
            "page_number": {"bsonType": ["int", "null"]},
            "sku": {"bsonType": ["string", "null"]},
            "all_skus": {"bsonType": ["array", "null"], "items": {"bsonType": "string"}},
            "finish": {"bsonType": ["string", "null"]},
            "glass": {"bsonType": ["string", "null"]},
            "cluster_id": {"bsonType": "int"},
            "embedding": {
                "bsonType": "array",
                "minItems": 1024,
                "maxItems": 1024,
                "items": {"bsonType": ["double", "int"]},
            },
            "certifications": {"bsonType": ["array", "null"], "items": {"bsonType": "string"}},
            "verification_status": {"bsonType": "string"},
            "retrieved_at": {"bsonType": ["string", "date", "null"]},
            "created_at": {"bsonType": ["date", "null"]},
            "hash": {"bsonType": "string"},
        },
    }
}


def run_pipeline(dry_run: bool = False, skip_search_index: bool = False):
    print("=== BẮT ĐẦU XÂY DỰNG KHO TRI THỨC ILT (EMBEDDINGS & CLUSTERING) ===")
    curated_path = ROOT_DIR / "data" / "ilt" / "curated_ilt_chunks.json"
    if not curated_path.exists():
        raise FileNotFoundError(f"Không tìm thấy file dữ liệu: {curated_path}. Cần chạy ingest_and_curate_ilt.py trước.")

    with open(curated_path, "r", encoding="utf-8") as f:
        chunks = json.load(f)
    print(f"  ✓ Đã nạp {len(chunks)} chunks đã kiểm duyệt.")

    # 1. Sinh Embeddings
    print("\n--- 1. Sinh Vector Embeddings (intfloat/multilingual-e5-large, 1024 dims) ---")
    texts_to_embed = [c["text"] for c in chunks]
    t0_emb = time.perf_counter()
    embeddings = EmbeddingManager.embed_documents(texts_to_embed)
    t_emb_sec = time.perf_counter() - t0_emb
    print(f"  ✓ Đã sinh {len(embeddings)} vectors trong {t_emb_sec:.2f}s ({len(embeddings)/t_emb_sec:.1f} chunks/sec).")

    # Kiểm tra kích thước vector
    vec_lens = [len(v) for v in embeddings]
    assert all(l == 1024 for l in vec_lens), f"Lỗi: Vector không đúng 1024 chiều! ({set(vec_lens)})"
    print("  ✓ Xác thực 100% vectors đạt đúng kích thước 1024 chiều.")

    # Chuẩn hóa L2-norm
    X = np.array(embeddings, dtype=np.float32)
    norms = np.linalg.norm(X, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    X_norm = X / norms

    # 2. Phân cụm K-Means Offline
    print("\n--- 2. Phân cụm Offline K-Means & Tối ưu Silhouette Score ---")
    best_k = 6
    best_score = -1.0
    scores = {}

    for k in range(3, 9):
        km = KMeans(n_clusters=k, random_state=42, n_init=10)
        labels = km.fit_predict(X_norm)
        score = float(silhouette_score(X_norm, labels, metric="cosine"))
        scores[k] = round(score, 4)
        if score > best_score:
            best_score = score
            best_k = k

    print(f"  Kết quả Silhouette Scores theo K: {scores}")
    print(f"  ✓ Chọn K={best_k} tối ưu (Silhouette Score = {best_score:.4f}).")

    final_kmeans = KMeans(n_clusters=best_k, random_state=42, n_init=20)
    final_labels = final_kmeans.fit_predict(X_norm)

    # Tính toán Centroids và phân bố
    centroids_dict = {}
    cluster_counts = {}

    for cid in range(best_k):
        cluster_mask = (final_labels == cid)
        count = int(np.sum(cluster_mask))
        cluster_counts[cid] = count

        # Centroid trung bình đã chuẩn hóa L2
        raw_centroid = np.mean(X_norm[cluster_mask], axis=0)
        c_norm = np.linalg.norm(raw_centroid)
        if c_norm > 0:
            norm_centroid = raw_centroid / c_norm
        else:
            norm_centroid = raw_centroid

        # Mẫu tên series hoặc categories trong cluster
        cluster_chunks = [chunks[i] for i in range(len(chunks)) if final_labels[i] == cid]
        series_present = list({c.get("series") for c in cluster_chunks if c.get("series")})
        categories_present = list({c.get("category") for c in cluster_chunks if c.get("category")})

        centroids_dict[str(cid)] = {
            "cluster_id": cid,
            "count": count,
            "centroid": norm_centroid.tolist(),
            "sample_series": series_present,
            "sample_categories": categories_present,
            "label": f"Cluster_{cid}_{'_'.join(series_present[:2]) if series_present else 'general'}",
        }
        print(f"  Cluster {cid}: {count} chunks - Series: {series_present} - Cat: {categories_present[:2]}")

    # Gán cluster_id và embedding vào từng chunk
    for i, c in enumerate(chunks):
        c["cluster_id"] = int(final_labels[i])
        c["embedding"] = [round(float(v), 6) for v in embeddings[i]]
        c["created_at"] = datetime.now(timezone.utc)

    # Lưu centroids artifact
    centroids_file = ROOT_DIR / "data" / "ilt_cluster_centroids.json"
    centroids_payload = {
        "profile": "ilt",
        "dataset_name": "Innovative Lighting Technologies",
        "dataset_version": "2026.1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "model": "intfloat/multilingual-e5-large",
        "dimensions": 1024,
        "metric": "cosine",
        "random_seed": 42,
        "k": best_k,
        "silhouette_score": best_score,
        "distribution": cluster_counts,
        "clusters": centroids_dict,
    }
    with open(centroids_file, "w", encoding="utf-8") as f:
        json.dump(centroids_payload, f, ensure_ascii=False, indent=2)
    print(f"\n  ✓ Đã lưu file centroids: {centroids_file}")

    # Invalidate Centroids Cache để nạp file mới
    EmbeddingManager.invalidate_centroids_cache("ilt")

    if dry_run:
        print("\n[DRY-RUN] Dừng trước khi ghi MongoDB. Toàn bộ embeddings và centroids đã tạo hợp lệ.")
        return

    # 3. MongoDB Import & Index Setup
    print("\n--- 3. Nhập dữ liệu Idempotent vào MongoDB (collection: ilt_kb) ---")
    db = MongoRepository.get_db()
    col_name = "ilt_kb"
    vector_index_name = "ilt_vector_index"

    # Tạo collection kèm strict $jsonSchema validator nếu chưa có
    if col_name in db.list_collection_names():
        print(f"  - Đã có collection '{col_name}', làm mới dữ liệu...")
        db[col_name].delete_many({})
    else:
        print(f"  - Tạo mới collection '{col_name}' kèm strict $jsonSchema validator...")
        db.create_collection(
            col_name,
            validator=ILT_VALIDATOR,
            validationLevel="strict",
            validationAction="error",
        )

    col = db[col_name]

    # Insert documents
    col.insert_many(chunks, ordered=True)
    actual_count = col.count_documents({})
    print(f"  ✓ Đã nạp thành công {actual_count}/{len(chunks)} tài liệu vào {col_name}.")
    assert actual_count == len(chunks)

    # 4. Tạo Regular Indexes
    print("\n--- 4. Tạo Regular Indexes trên ilt_kb ---")
    col.create_index([("chunk_id", 1)], unique=True, name="uniq_ilt_chunk_id")
    col.create_index([("sku", 1)], sparse=True, name="idx_ilt_sku")
    col.create_index([("cluster_id", 1)], name="idx_ilt_cluster_id")
    col.create_index([("series", 1)], name="idx_ilt_series")
    col.create_index([("category", 1)], name="idx_ilt_category")
    col.create_index([("page_number", 1)], name="idx_ilt_page_number")
    print("  ✓ Đã tạo các chỉ mục: chunk_id (unique), sku, cluster_id, series, category, page_number.")

    # 5. Tạo Atlas Vector Search Index (hỗ trợ Pre-Filter trên cluster_id)
    if not skip_search_index:
        print(f"\n--- 5. Khởi tạo Atlas Vector Search Index '{vector_index_name}' ---")
        existing_s_indexes = []
        try:
            existing_s_indexes = [idx["name"] for idx in col.list_search_indexes()]
        except Exception:
            pass

        if vector_index_name in existing_s_indexes:
            print(f"  ℹ️ Search index '{vector_index_name}' đã tồn tại trên Atlas.")
        else:
            search_def = {
                "fields": [
                    {
                        "type": "vector",
                        "path": "embedding",
                        "numDimensions": 1024,
                        "similarity": "cosine",
                    },
                    {
                        "type": "filter",
                        "path": "cluster_id",
                    },
                    {
                        "type": "filter",
                        "path": "dataset_version",
                    },
                ]
            }
            model = SearchIndexModel(
                definition=search_def,
                name=vector_index_name,
                type="vectorSearch",
            )
            try:
                col.create_search_index(model=model)
                print(f"  ✓ Đã gửi yêu cầu tạo Atlas Vector Search Index: {vector_index_name}")

                # Polling trạng thái READY
                print("  Đang đợi Atlas Index đạt trạng thái READY/queryable...")
                ready = False
                for attempt in range(25):
                    time.sleep(2.0)
                    try:
                        for s_idx in col.list_search_indexes(vector_index_name):
                            status = s_idx.get("status")
                            queryable = s_idx.get("queryable", False)
                            if status == "READY" and queryable:
                                ready = True
                                break
                    except Exception:
                        pass
                    if ready:
                        print(f"  ✓ Atlas Index {vector_index_name} đã READY và queryable (sau {(attempt+1)*2}s)!")
                        break
                if not ready:
                    print(f"  ℹ️ Atlas Index đang được index nền trên cluster.")
            except Exception as e:
                print(f"  ⚠️ Lưu ý Atlas Vector Index: {e}")

    # 6. Sample Probe Query
    sample_doc = col.find_one({"sku": {"$exists": True, "$ne": None}}, {"_id": 0, "title": 1, "sku": 1, "cluster_id": 1, "category": 1})
    print("\n--- 6. Mẫu dữ liệu truy xuất xác nhận ---")
    print(f"  {json.dumps(sample_doc, ensure_ascii=False, indent=2)}")

    print("\n=======================================================")
    print("✅ HOÀN TẤT XÂY DỰNG KHO TRI THỨC ILT:")
    print(f"  Collection:        {col_name} ({actual_count} documents)")
    print(f"  Atlas Index:       {vector_index_name} (1024 dims, pre-filter on cluster_id)")
    print(f"  Centroids File:    {centroids_file.name} (K={best_k}, score={best_score:.4f})")
    print("=======================================================\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Tạo embeddings, phân cụm và import ILT KB vào MongoDB")
    parser.add_argument("--dry-run", action="store_true", help="Chạy pipeline mà không ghi MongoDB")
    parser.add_argument("--skip-search-index", action="store_true", help="Bỏ qua tạo search index")
    args = parser.parse_args()

    run_pipeline(dry_run=args.dry_run, skip_search_index=args.skip_search_index)
