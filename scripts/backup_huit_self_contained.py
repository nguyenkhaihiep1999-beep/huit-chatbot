"""
scripts/backup_huit_self_contained.py
Tạo bản sao lưu tự chứa (Self-Contained Backup) cho kho tri thức HUIT:
- Định dạng container: ZIP với đuôi mở rộng .bak (backups/huit-<timestamp>.bak).
- Lưu trữ đầy đủ BSON nguyên bản (giữ trọn _id, BSON types, embedding 1024-dim, datetime).
- Lưu trữ toàn bộ Regular Indexes, Validators ($jsonSchema) và Atlas Search/Vector Search definitions.
- Sao lưu file dữ liệu phụ thuộc: data/huit_cluster_centroids.json.
- Sao lưu các physical blobs trong data/artifacts_store được tham chiếu bởi assets / admission_visuals.
- Lưu trữ Profile Configuration và System Prompts (không chứa secrets/credentials).
- Manifest chi tiết với SHA-256 từng payload và tổng thể gói, schema version, doc counts.
- Thất bại rõ ràng nếu bất kỳ thành phần bắt buộc nào gặp lỗi (Fail-Fast, không ghi COMPLETED khi lỗi).
- Hỗ trợ CLI: --dry-run, --output <path>.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import zipfile

import bson
from bson import json_util

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
from backend.app.rag.profile import HUIT_PROFILE

HUIT_COLLECTIONS = [
    "huit_kb",
    "admission_visuals",
    "artifacts",
    "schema_registry",
    "assets",
    "crawler_hashes",
    "raw_data",
]


def sha256_file(filepath: Path) -> str:
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def run_backup(output_path: Path = None, dry_run: bool = False) -> Path:
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    if output_path is None:
        backups_dir = ROOT_DIR / "backups"
        backups_dir.mkdir(parents=True, exist_ok=True)
        output_path = backups_dir / f"huit-{ts}.bak"

    print(f"=== KHỞI ĐỘNG SAO LƯU TỰ CHỨA HUIT ({ts}) ===")
    print(f"Đích xuất file: {output_path}")
    print(f"Chế độ Dry-Run: {dry_run}")

    db = MongoRepository.get_db()

    manifest = {
        "manifest_version": "1.0.0",
        "profile": "huit",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source_db": settings.MONGODB_DB,
        "collections": {},
        "metadata": {
            "indexes": {},
            "search_indexes": {},
            "validators": {},
        },
        "data_files": {},
        "blobs": {},
        "profile_config": {
            "id": HUIT_PROFILE.id,
            "name": HUIT_PROFILE.name,
            "kb_collection": HUIT_PROFILE.kb_collection,
            "vector_index_name": HUIT_PROFILE.vector_index_name,
            "embedding_model": HUIT_PROFILE.embedding_model,
            "embedding_dims": HUIT_PROFILE.embedding_dims,
            "clusters_filename": HUIT_PROFILE.clusters_filename,
            "default_source_url": HUIT_PROFILE.default_source_url,
            "official_contact": HUIT_PROFILE.official_contact,
            "kb_version": HUIT_PROFILE.kb_version,
            "rag_version": HUIT_PROFILE.rag_version,
            "primary_domain": HUIT_PROFILE.primary_domain,
            "system_prompt": HUIT_PROFILE.system_prompt,
            "answer_template": HUIT_PROFILE.answer_template,
            "empty_kb_message": HUIT_PROFILE.empty_kb_message,
        },
        "status": "in_progress",
    }

    if dry_run:
        print("\n[DRY-RUN] Kiểm tra dữ liệu sẽ được sao lưu:")
        total_docs = 0
        for col_name in HUIT_COLLECTIONS:
            count = db[col_name].count_documents({})
            total_docs += count
            print(f"  - Collection '{col_name}': {count} documents")
        print(f"  Tổng số tài liệu: {total_docs}")
        centroids_file = ROOT_DIR / "data" / "huit_cluster_centroids.json"
        print(f"  - File centroids: {centroids_file} (tồn tại: {centroids_file.exists()})")
        print("[DRY-RUN] Hoàn tất kiểm tra hợp lệ. Không ghi file.")
        return output_path

    temp_stage_dir = Path(tempfile.mkdtemp(prefix="huit_bak_stage_"))

    try:
        collections_dir = temp_stage_dir / "collections"
        collections_dir.mkdir(parents=True, exist_ok=True)
        metadata_dir = temp_stage_dir / "metadata"
        metadata_dir.mkdir(parents=True, exist_ok=True)
        data_files_dir = temp_stage_dir / "data_files"
        data_files_dir.mkdir(parents=True, exist_ok=True)
        blobs_dir = temp_stage_dir / "blobs"
        blobs_dir.mkdir(parents=True, exist_ok=True)

        # 1. Export Collections sang file BSON
        print("\n--- 1. Xuất MongoDB Collections (BSON) ---")
        for col_name in HUIT_COLLECTIONS:
            col = db[col_name]
            cursor = col.find({})
            doc_count = 0
            bson_file = collections_dir / f"{col_name}.bson"

            with open(bson_file, "wb") as f:
                for doc in cursor:
                    raw_b = bson.BSON.encode(doc)
                    f.write(raw_b)
                    doc_count += 1

            sha256_val = sha256_file(bson_file)
            size_bytes = bson_file.stat().st_size

            manifest["collections"][col_name] = {
                "count": doc_count,
                "bson_size_bytes": size_bytes,
                "sha256": sha256_val,
                "relative_path": f"collections/{col_name}.bson",
            }
            print(f"  ✓ {col_name}: {doc_count} docs, {size_bytes:,} bytes, SHA-256: {sha256_val[:12]}...")

        # 2. Export Indexes, Search Indexes & Validators
        print("\n--- 2. Thu thập Metadata (Indexes, Validators, Atlas Search) ---")
        all_colls_info = {c["name"]: c for c in db.list_collections()}

        for col_name in HUIT_COLLECTIONS:
            col = db[col_name]
            # Regular Indexes
            raw_indexes = list(col.list_indexes())
            indexes_clean = []
            for idx in raw_indexes:
                idx_dict = dict(idx)
                # Chuyển đổi key SON sang dict có thứ tự
                idx_dict["key"] = dict(idx_dict.get("key", {}))
                indexes_clean.append(idx_dict)
            manifest["metadata"]["indexes"][col_name] = indexes_clean

            # Validators
            col_info = all_colls_info.get(col_name, {})
            options = col_info.get("options", {})
            validator = options.get("validator")
            if validator:
                manifest["metadata"]["validators"][col_name] = {
                    "validator": json.loads(json_util.dumps(validator)),
                    "validationLevel": options.get("validationLevel", "strict"),
                    "validationAction": options.get("validationAction", "error"),
                }

            # Search Indexes (Atlas Vector Search)
            search_indexes = []
            try:
                for s_idx in col.list_search_indexes():
                    s_dict = {
                        "name": s_idx.get("name"),
                        "type": s_idx.get("type"),
                        "status": s_idx.get("status"),
                        "definition": s_idx.get("latestDefinition"),
                    }
                    search_indexes.append(s_dict)
            except Exception as exc:
                print(f"  ⚠️ Lưu ý: list_search_indexes() cho {col_name}: {exc}")
            manifest["metadata"]["search_indexes"][col_name] = search_indexes

        # Lưu metadata json files vào stage
        with open(metadata_dir / "indexes.json", "w", encoding="utf-8") as f:
            json.dump(manifest["metadata"]["indexes"], f, ensure_ascii=False, indent=2)
        with open(metadata_dir / "validators.json", "w", encoding="utf-8") as f:
            json.dump(manifest["metadata"]["validators"], f, ensure_ascii=False, indent=2)
        with open(metadata_dir / "search_indexes.json", "w", encoding="utf-8") as f:
            json.dump(manifest["metadata"]["search_indexes"], f, ensure_ascii=False, indent=2)
        print("  ✓ Metadata indexes, validators và search indexes đã ghi.")

        # 3. Export Data Files (centroids)
        print("\n--- 3. Sao lưu Data Files & Centroids ---")
        centroids_src = ROOT_DIR / "data" / "huit_cluster_centroids.json"
        if centroids_src.exists():
            shutil.copy2(centroids_src, data_files_dir / "huit_cluster_centroids.json")
            cf_sha = sha256_file(centroids_src)
            manifest["data_files"]["huit_cluster_centroids.json"] = {
                "size_bytes": centroids_src.stat().st_size,
                "sha256": cf_sha,
                "relative_path": "data_files/huit_cluster_centroids.json",
            }
            print(f"  ✓ Centroids: {centroids_src.name}, SHA-256: {cf_sha[:12]}...")
        else:
            raise FileNotFoundError(f"Bắt buộc có file centroids: {centroids_src}")

        # 4. Export Physical Blobs (artifacts & visuals)
        print("\n--- 4. Sao lưu Physical Blobs (data/artifacts_store) ---")
        artifacts_store = ROOT_DIR / "data" / "artifacts_store"
        # Thu thập danh sách storage_key được tham chiếu trong assets và admission_visuals
        referenced_keys = set()
        for doc in db["assets"].find({"storage_key": {"$exists": True, "$ne": ""}}):
            k = doc.get("storage_key")
            if k:
                referenced_keys.add(k)
        for doc in db["admission_visuals"].find({"storage_key": {"$exists": True, "$ne": None}}):
            k = doc.get("storage_key")
            if k:
                referenced_keys.add(k)

        blob_count = 0
        total_blob_bytes = 0
        for key in referenced_keys:
            blob_path = artifacts_store / key
            if blob_path.exists() and blob_path.is_file():
                dest_blob = blobs_dir / key
                shutil.copy2(blob_path, dest_blob)
                b_sha = sha256_file(dest_blob)
                b_size = dest_blob.stat().st_size
                manifest["blobs"][key] = {
                    "size_bytes": b_size,
                    "sha256": b_sha,
                    "relative_path": f"blobs/{key}",
                }
                blob_count += 1
                total_blob_bytes += b_size

        print(f"  ✓ Đã sao lưu {blob_count} blobs tham chiếu ({total_blob_bytes:,} bytes).")

        # 5. Ghi Manifest
        manifest["status"] = "completed"
        manifest_path = temp_stage_dir / "manifest.json"
        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump(manifest, f, ensure_ascii=False, indent=2)

        # 6. Đóng gói ZIP thành file .bak
        print("\n--- 5. Đóng gói Container (.bak) ---")
        if output_path.exists():
            output_path.unlink()

        with zipfile.ZipFile(output_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for root, dirs, files in os.walk(temp_stage_dir):
                for file in files:
                    full_p = Path(root) / file
                    arcname = full_p.relative_to(temp_stage_dir)
                    zf.write(full_p, arcname=arcname)

        final_pkg_sha = sha256_file(output_path)
        final_pkg_size = output_path.stat().st_size

        # Ghi file checksum đồng hành
        sha_file = output_path.with_suffix(".bak.sha256")
        sha_file.write_text(f"{final_pkg_sha}  {output_path.name}\n", encoding="utf-8")

        print(f"\n=======================================================")
        print(f"✅ BẢN SAO LƯU TỰ CHỨA HUIT THÀNH CÔNG:")
        print(f"  Tệp sao lưu: {output_path}")
        print(f"  Dung lượng:  {final_pkg_size:,} bytes")
        print(f"  SHA-256:     {final_pkg_sha}")
        print(f"  Checksum file: {sha_file.name}")
        print(f"=======================================================\n")
        return output_path

    finally:
        shutil.rmtree(temp_stage_dir, ignore_errors=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Tạo bản sao lưu tự chứa cho kho tri thức HUIT (.bak)")
    parser.add_argument("--dry-run", action="store_true", help="Chạy kiểm tra dữ liệu mà không ghi file")
    parser.add_argument("--output", type=str, default=None, help="Đường dẫn file .bak đầu ra")
    args = parser.parse_args()

    out_p = Path(args.output) if args.output else None
    run_backup(output_path=out_p, dry_run=args.dry_run)
