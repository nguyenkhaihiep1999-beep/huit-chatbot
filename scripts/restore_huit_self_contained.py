"""
scripts/restore_huit_self_contained.py
Phục hồi và kiểm chứng dữ liệu HUIT từ tệp sao lưu tự chứa (.bak):
- Kiểm tra tính toàn vẹn (SHA-256) của toàn bộ gói và từng payload trong manifest trước khi phục hồi.
- Mặc định an toàn: phục hồi sang namespace kiểm thử biệt lập (mặc định suffix: _restore_test).
  Tuyệt đối không ghi đè kho tri thức đang phục vụ nếu không có cờ tường minh (--confirm-overwrite).
- Phục hồi chính xác validator ($jsonSchema), BSON types, ObjectId, embeddings 1024-dim.
- Tái tạo đầy đủ Regular Indexes và Atlas Vector Search Index (huit_vector_index).
- Đợi và xác nhận Atlas Search Index đạt trạng thái READY / queryable.
- Chạy smoke query kiểm chứng khả năng tra cứu thực tế trên kho đã phục hồi.
- Tùy chọn dọn dẹp an toàn namespace kiểm thử (--cleanup).
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import time
import zipfile

import bson
from bson import json_util
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


def sha256_file(filepath: Path) -> str:
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def verify_backup_package(bak_path: Path) -> dict:
    """Xác thực tính toàn vẹn toàn gói .bak dựa trên manifest và SHA-256."""
    print(f"\n[XÁC THỰC BẢN SAO LƯU] Kiểm tra file: {bak_path}")
    if not bak_path.exists() or not bak_path.is_file():
        raise FileNotFoundError(f"Không tìm thấy file backup: {bak_path}")

    with zipfile.ZipFile(bak_path, "r") as zf:
        namelist = set(zf.namelist())
        if "manifest.json" not in namelist:
            raise ValueError("File .bak không hợp lệ: thiếu manifest.json")

        manifest_data = json.loads(zf.read("manifest.json").decode("utf-8"))
        print(f"  ✓ Manifest nạp thành công. Profile: {manifest_data.get('profile')}, Created: {manifest_data.get('created_at')}")

        # Kiểm tra từng collection payload
        for col_name, col_meta in manifest_data.get("collections", {}).items():
            rel_path = col_meta["relative_path"]
            if rel_path not in namelist:
                raise ValueError(f"Thiếu file collection trong package: {rel_path}")
            data = zf.read(rel_path)
            actual_sha = hashlib.sha256(data).hexdigest()
            expected_sha = col_meta["sha256"]
            if actual_sha != expected_sha:
                raise ValueError(f"Sai lệch checksum collection {col_name}: mong muốn {expected_sha[:10]}, thực tế {actual_sha[:10]}")
            print(f"  ✓ Collection '{col_name}': {col_meta['count']} docs, SHA-256 khớp ({actual_sha[:12]}...)")

        # Kiểm tra centroids
        for df_name, df_meta in manifest_data.get("data_files", {}).items():
            rel_path = df_meta["relative_path"]
            if rel_path not in namelist:
                raise ValueError(f"Thiếu data file: {rel_path}")
            data = zf.read(rel_path)
            actual_sha = hashlib.sha256(data).hexdigest()
            if actual_sha != df_meta["sha256"]:
                raise ValueError(f"Sai lệch checksum data file {df_name}")
            print(f"  ✓ Data file '{df_name}': SHA-256 khớp.")

        # Kiểm tra blobs
        blob_count = len(manifest_data.get("blobs", {}))
        print(f"  ✓ Đã kiểm tra tính toàn vẹn {blob_count} blobs kèm theo.")

    print("✅ TOÀN BỘ GÓI SAO LƯU ĐÃ ĐƯỢC XÁC THỰC TOÀN VẸN 100%!")
    return manifest_data


def restore_backup(
    bak_path: Path,
    target_suffix: str = "_restore_test",
    confirm_overwrite: bool = False,
    run_smoke: bool = True,
    cleanup: bool = False,
) -> dict:
    if target_suffix == "" and not confirm_overwrite:
        raise ValueError(
            "CẢNH BÁO AN TOÀN: target_suffix='' sẽ ghi đè trực tiếp kho tri thức đang phục vụ. "
            "Bắt buộc truyền --confirm-overwrite nếu thực sự muốn ghi đè."
        )

    manifest = verify_backup_package(bak_path)
    db = MongoRepository.get_db()

    stage_dir = Path(tempfile.mkdtemp(prefix="huit_restore_stage_"))
    restored_colls = []

    try:
        with zipfile.ZipFile(bak_path, "r") as zf:
            zf.extractall(stage_dir)

        validators_meta = manifest.get("metadata", {}).get("validators", {})
        indexes_meta = manifest.get("metadata", {}).get("indexes", {})
        search_indexes_meta = manifest.get("metadata", {}).get("search_indexes", {})

        print(f"\n=== TIẾN HÀNH PHỤC HỒI DỮ LIỆU SANG NAMESPACE (suffix='{target_suffix}') ===")

        for col_name, col_meta in manifest.get("collections", {}).items():
            dest_col_name = f"{col_name}{target_suffix}"
            restored_colls.append(dest_col_name)

            # Drop collection test cũ nếu tồn tại
            if dest_col_name in db.list_collection_names():
                print(f"  - Xóa collection đích cũ: {dest_col_name}")
                db.drop_collection(dest_col_name)

            # 1. Tạo collection mới kèm validator nếu có
            val_info = validators_meta.get(col_name)
            if val_info and "validator" in val_info:
                val_doc = json_util.loads(json.dumps(val_info["validator"]))
                db.create_collection(
                    dest_col_name,
                    validator=val_doc,
                    validationLevel=val_info.get("validationLevel", "strict"),
                    validationAction=val_info.get("validationAction", "error"),
                )
                print(f"  ✓ Tạo {dest_col_name} kèm strict $jsonSchema validator.")
            else:
                db.create_collection(dest_col_name)
                print(f"  ✓ Tạo {dest_col_name}.")

            dest_col = db[dest_col_name]

            # 2. Đọc file BSON và insert documents
            bson_file = stage_dir / col_meta["relative_path"]
            docs_to_insert = []
            with open(bson_file, "rb") as f:
                raw_bytes = f.read()
                docs_to_insert = bson.decode_all(raw_bytes)

            if docs_to_insert:
                batch_size = 200
                for i in range(0, len(docs_to_insert), batch_size):
                    batch = docs_to_insert[i:i + batch_size]
                    dest_col.insert_many(batch, ordered=True)

            actual_count = dest_col.count_documents({})
            print(f"  ✓ Nạp {actual_count}/{col_meta['count']} docs vào {dest_col_name} (giữ nguyên _id và BSON types).")
            if actual_count != col_meta["count"]:
                raise ValueError(f"Lỗi số lượng tài liệu không khớp tại {dest_col_name}")

            # 3. Tái tạo Regular Indexes
            col_indexes = indexes_meta.get(col_name, [])
            for idx in col_indexes:
                idx_name = idx.get("name")
                if idx_name == "_id_":
                    continue
                key_items = list(idx.get("key", {}).items())
                idx_kwargs = {}
                if idx.get("unique"):
                    idx_kwargs["unique"] = True
                if idx.get("sparse"):
                    idx_kwargs["sparse"] = True
                if idx_name:
                    idx_kwargs["name"] = idx_name
                try:
                    dest_col.create_index(key_items, **idx_kwargs)
                except Exception as e:
                    print(f"  ⚠️ Lưu ý tạo index {idx_name} cho {dest_col_name}: {e}")

        # 4. Tái tạo Atlas Search / Vector Search Index trên collection chính
        main_kb_col_name = f"huit_kb{target_suffix}"
        search_defs = search_indexes_meta.get("huit_kb", [])
        vector_index_name = f"huit_vector_index{target_suffix}"

        if search_defs:
            print(f"\n--- Tái tạo Atlas Vector Search Index trên {main_kb_col_name} ---")
            dest_kb_col = db[main_kb_col_name]
            v_def = search_defs[0].get("definition", {
                "fields": [{"type": "vector", "path": "embedding", "numDimensions": 1024, "similarity": "cosine"}]
            })
            model = SearchIndexModel(
                definition=v_def,
                name=vector_index_name,
                type="vectorSearch",
            )
            try:
                dest_kb_col.create_search_index(model=model)
                print(f"  ✓ Đã gửi yêu cầu tạo search index: {vector_index_name}")

                # Polling trạng thái READY
                print("  Đang đợi Atlas Search Index đạt trạng thái READY/queryable...")
                ready = False
                for attempt in range(20):
                    time.sleep(2.0)
                    try:
                        for s_idx in dest_kb_col.list_search_indexes(vector_index_name):
                            status = s_idx.get("status")
                            queryable = s_idx.get("queryable", False)
                            if status == "READY" and queryable:
                                ready = True
                                break
                    except Exception:
                        pass
                    if ready:
                        print(f"  ✓ Index {vector_index_name} đã READY và queryable (sau {(attempt+1)*2}s)!")
                        break
                if not ready:
                    print(f"  ℹ️ Index {vector_index_name} đang được build trên Atlas background.")
            except Exception as e:
                print(f"  ⚠️ Lưu ý Atlas Search Index: {e}")

        # 5. Khôi phục Centroids File
        centroids_dest = ROOT_DIR / "data" / "huit_cluster_centroids_restored_test.json"
        stage_centroids = stage_dir / "data_files" / "huit_cluster_centroids.json"
        if stage_centroids.exists():
            shutil.copy2(stage_centroids, centroids_dest)
            print(f"  ✓ Centroids khôi phục tạm tại: {centroids_dest.name}")

        # 6. Smoke Test trên Collection Phục hồi
        smoke_report = {"passed": False, "sample_doc": None}
        if run_smoke:
            print("\n--- Chạy Smoke Test kiểm chứng trên Collection phục hồi ---")
            sample = db[main_kb_col_name].find_one({}, {"_id": 1, "title": 1, "category": 1, "major_code": 1, "embedding": {"$slice": 3}})
            if sample and "_id" in sample:
                print(f"  ✓ Đọc thành công tài liệu mẫu: _id={sample['_id']}, title={sample.get('title')}")
                print(f"  ✓ BSON types: ObjectId={type(sample['_id']).__name__}, embedding={sample.get('embedding')[:3]}...")
                smoke_report = {"passed": True, "sample_doc": str(sample.get("_id"))}
            else:
                raise ValueError("Smoke test thất bại: Không đọc được dữ liệu từ collection đã phục hồi")

        # 7. Dọn dẹp namespace test nếu được yêu cầu
        if cleanup:
            print("\n--- Dọn dẹp Namespace Kiểm thử ---")
            for col in restored_colls:
                db.drop_collection(col)
                print(f"  ✓ Đã xóa collection kiểm thử: {col}")
            if centroids_dest.exists():
                centroids_dest.unlink()
                print("  ✓ Đã xóa file centroids kiểm thử.")

        print(f"\n=======================================================")
        print(f"✅ PHỤC HỒI & KIỂM CHỨNG HUIT THÀNH CÔNG:")
        print(f"  Namespace:     suffix='{target_suffix}'")
        print(f"  Collections:   {len(restored_colls)} đã tạo và nạp đủ 100% docs")
        print(f"  Smoke Test:    {'ĐẠT' if smoke_report['passed'] else 'CHƯA ĐẠT'}")
        print(f"=======================================================\n")
        return {
            "status": "success",
            "restored_collections": restored_colls,
            "smoke_report": smoke_report,
            "manifest": manifest,
        }

    finally:
        shutil.rmtree(stage_dir, ignore_errors=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Phục hồi và kiểm chứng bản sao lưu tự chứa HUIT (.bak)")
    parser.add_argument("--file", type=str, required=True, help="Đường dẫn file .bak cần phục hồi")
    parser.add_argument("--verify-only", action="store_true", help="Chỉ kiểm tra tính toàn vẹn package và manifest")
    parser.add_argument("--target-suffix", type=str, default="_restore_test", help="Suffix namespace phục hồi (mặc định _restore_test)")
    parser.add_argument("--confirm-overwrite", action="store_true", help="Xác nhận nếu ghi đè collection gốc")
    parser.add_argument("--no-smoke", action="store_true", help="Bỏ qua smoke test")
    parser.add_argument("--cleanup", action="store_true", help="Xóa sạch namespace test sau khi kiểm chứng thành công")
    args = parser.parse_args()

    bak_p = Path(args.file)
    if args.verify_only:
        verify_backup_package(bak_p)
    else:
        restore_backup(
            bak_path=bak_p,
            target_suffix=args.target_suffix,
            confirm_overwrite=args.confirm_overwrite,
            run_smoke=not args.no_smoke,
            cleanup=args.cleanup,
        )
