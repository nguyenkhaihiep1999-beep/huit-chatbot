"""
012_migrate_images_to_physical_assets.py
Migration chuẩn hóa dữ liệu ảnh sinh ra (generated_images) sang kiến trúc Physical Asset tách bạch:
- Ánh xạ các bản ghi logic trong `generated_images` sang các physical blob trong `assets`.
- Đảm bảo mỗi bản ghi `generated_images` có `blob_id`, `canonical_content_hash`, `access_scope`, và `schema_version: 1`.
- Thiết lập `access_scope = "legacy_public"` cho các ảnh legacy không có `owner_id`.
- Tự động tạo bản ghi `assets` tương ứng nếu chưa tồn tại (chứa storage_key, preview_key/thumbnail_key, file_size, media_type, width, height, reference_count).
- Hỗ trợ đầy đủ --dry-run (mặc định) và --apply (tự động sao lưu collection trước khi ghi).
- Ghi báo cáo chi tiết vào audit_outputs/.
"""
from pathlib import Path
import sys
ROOT_DIR = Path(__file__).resolve().parent.parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from pymongo import UpdateOne

from scripts.migrations.common import (
    get_base_parser,
    get_migration_db,
    create_collection_backup,
    save_migration_report,
    iterate_batches,
    logger,
)


def migrate_images_to_assets(db, args) -> Dict[str, Any]:
    images_col = db["generated_images"]
    assets_col = db["assets"]
    now_dt = datetime.now(timezone.utc)

    # Tìm các bản ghi cần chuẩn hóa: thiếu blob_id hoặc thiếu access_scope hoặc thiếu schema_version
    query = {
        "$or": [
            {"blob_id": {"$exists": False}},
            {"blob_id": None},
            {"access_scope": {"$exists": False}},
            {"schema_version": {"$exists": False}}
        ]
    }

    total_needing_migration = images_col.count_documents(query)
    total_images = images_col.count_documents({})
    logger.info(f"Tổng số ảnh trong 'generated_images': {total_images}. Số bản ghi cần migration: {total_needing_migration}.")

    report: Dict[str, Any] = {
        "script": "012_migrate_images_to_physical_assets",
        "started_at": now_dt.isoformat(),
        "mode": "apply" if args.apply else "dry-run",
        "total_images": total_images,
        "needing_migration": total_needing_migration,
        "migrated_count": 0,
        "skipped_count": 0,
        "assets_created": 0,
        "assets_existing": 0,
        "errors": 0,
        "backups": {},
        "details": []
    }

    if total_needing_migration == 0:
        logger.info("Tất cả bản ghi trong 'generated_images' đã đạt chuẩn kiến trúc Physical Asset.")
        report["completed_at"] = datetime.now(timezone.utc).isoformat()
        return report

    if args.apply:
        logger.info("Tiến hành sao lưu các collection trước khi áp dụng migration...")
        report["backups"]["generated_images"] = create_collection_backup(db, "generated_images")
        report["backups"]["assets"] = create_collection_backup(db, "assets")

    batch_generator = iterate_batches(
        col=images_col,
        filter_query=query,
        batch_size=args.batch_size,
        resume_from=args.resume_from
    )

    known_hash_to_blob: Dict[str, str] = {}

    for batch in batch_generator:
        assets_ops = []
        images_ops = []

        for doc in batch:
            doc_id = doc["_id"]
            image_id = doc.get("image_id", str(doc_id))
            backend = doc.get("backend", "flux")
            owner_id = doc.get("owner_id")
            
            # 1. Chuẩn hóa canonical_content_hash
            c_hash = (
                doc.get("canonical_content_hash")
                or doc.get("content_hash")
                or doc.get("generation_key")
                or doc.get("checksum")
                or str(doc_id)
            )

            # 2. Chuẩn hóa access_scope
            access_scope = doc.get("access_scope")
            if not access_scope:
                access_scope = "private" if (owner_id and owner_id != "anonymous") else "legacy_public"

            # 3. Xác định thông số physical asset
            if backend == "svg":
                media_type = "image/svg+xml"
                file_ext = "svg"
                file_size = int(doc.get("scene_bytes") or len(str(doc.get("scene", "")).encode("utf-8")))
                storage_key = doc.get("storage_key") or f"svg_{image_id}.json"
                preview_key = None
            else:
                media_type = doc.get("content_type", "image/jpeg")
                file_ext = "jpg"
                file_size = int(doc.get("byte_size") or doc.get("image_bytes") or 0)
                storage_key = doc.get("storage_key") or f"image_{image_id}.jpg"
                preview_key = doc.get("thumbnail_key") or doc.get("preview_key") or storage_key

            width = int(doc.get("width", 512))
            height = int(doc.get("height", 512))
            created_at = doc.get("created_at") or now_dt

            # 4. Deduplication: Kiểm tra xem physical blob cho content_hash này đã có chưa
            if c_hash in known_hash_to_blob:
                blob_id = known_hash_to_blob[c_hash]
                assets_ops.append(
                    UpdateOne({"_id": blob_id}, {"$inc": {"reference_count": 1}, "$set": {"last_accessed_at": now_dt}})
                )
                report["assets_existing"] += 1
            else:
                existing_asset = assets_col.find_one({"$or": [{"content_hash": c_hash}, {"checksum": c_hash}]})
                if existing_asset:
                    blob_id = existing_asset.get("asset_id") or existing_asset.get("_id")
                    known_hash_to_blob[c_hash] = blob_id
                    assets_ops.append(
                        UpdateOne({"_id": blob_id}, {"$inc": {"reference_count": 1}, "$set": {"last_accessed_at": now_dt}})
                    )
                    report["assets_existing"] += 1
                else:
                    blob_id = doc.get("blob_id") or f"blob_img_{doc_id}"
                    known_hash_to_blob[c_hash] = blob_id
                    asset_doc = {
                        "_id": blob_id,
                        "asset_id": blob_id,
                        "content_hash": c_hash,
                        "checksum": c_hash,
                        "media_type": media_type,
                        "storage_key": storage_key,
                        "preview_key": preview_key,
                        "file_size": file_size,
                        "file_ext": file_ext,
                        "width": width,
                        "height": height,
                        "reference_count": 1,
                        "renderer_version": "legacy_image_migration",
                        "created_at": created_at,
                        "last_accessed_at": now_dt,
                        "schema_version": 1
                    }
                    assets_ops.append(
                        UpdateOne({"_id": blob_id}, {"$set": asset_doc}, upsert=True)
                    )
                    report["assets_created"] += 1

            # 5. Update cho logical record trong generated_images
            img_update_fields = {
                "blob_id": blob_id,
                "canonical_content_hash": c_hash,
                "access_scope": access_scope,
                "schema_version": 1,
                "migrated_to_asset_at": now_dt
            }
            # Giữ nguyên content_hash hiện có để không vi phạm unique index content_hash_1
            if not doc.get("content_hash"):
                img_update_fields["content_hash"] = c_hash

            img_update = {"$set": img_update_fields}
            if "image_data" in doc:
                img_update["$unset"] = {"image_data": ""}

            images_ops.append(UpdateOne({"_id": doc_id}, img_update))
            report["migrated_count"] += 1
            report["details"].append({
                "image_id": image_id,
                "backend": backend,
                "blob_id": blob_id,
                "access_scope": access_scope,
                "storage_key": storage_key
            })

        if args.apply:
            try:
                if assets_ops:
                    assets_col.bulk_write(assets_ops, ordered=False)
                if images_ops:
                    images_col.bulk_write(images_ops, ordered=False)
            except Exception as e:
                logger.error(f"Lỗi khi thực thi batch: {e}")
                report["errors"] += 1

    report["completed_at"] = datetime.now(timezone.utc).isoformat()
    return report


def main():
    parser = get_base_parser("Migration 012: Chuẩn hóa generated_images sang Physical Asset kiến trúc tách bạch")
    args = parser.parse_args()

    client, db = get_migration_db(args.database)
    try:
        report = migrate_images_to_assets(db, args)
        save_migration_report(report, args.report_file)
        logger.info(
            f"Hoàn thành Migration 012 ({report['mode']}): "
            f"Đã xử lý {report['migrated_count']}/{report['total_images']} ảnh, "
            f"Tạo {report['assets_created']} physical assets, Lỗi: {report['errors']}."
        )
    finally:
        client.close()


if __name__ == "__main__":
    main()
