"""
010_create_artifacts_collection_and_migrate_ownership.py
Tách rời quyền sở hữu và manifest từ collection `assets` sang `artifacts`:
1. Tạo collection `artifacts` với $jsonSchema validator và indexes (artifact_id unique, owner_id, blob_id, content_hash).
2. Di trú manifest và owner_id từ `assets` sang `artifacts`.
3. Làm sạch `assets` (xóa $unset manifest, owner_id) để `assets` thuần túy là kho physical blob metadata.
4. Sửa index `query_cache.cache_key` thành `unique: True`.
5. Hỗ trợ đầy đủ --dry-run, --apply và tự động tạo backup trước khi mutate.
"""
from pathlib import Path
import sys
ROOT_DIR = Path(__file__).resolve().parent.parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import copy
from datetime import datetime, timezone
from typing import Any, Dict, List

from scripts.migrations.common import (
    get_base_parser,
    get_migration_db,
    create_collection_backup,
    save_migration_report,
    logger,
)
from backend.app.models.mongo_models import ensure_utc_datetime

ARTIFACTS_VALIDATOR = {
    "$jsonSchema": {
        "bsonType": "object",
        "required": ["artifact_id", "manifest", "created_at", "updated_at"],
        "properties": {
            "_id": { "bsonType": ["string", "objectId"] },
            "schema_version": { "bsonType": "int", "minimum": 1 },
            "artifact_id": { "bsonType": "string", "pattern": "^[a-zA-Z0-9_\\-\\.]+$" },
            "owner_id": { "bsonType": ["string", "null"], "maxLength": 64 },
            "access_scope": { "enum": ["public", "private"] },
            "blob_id": { "bsonType": ["string", "null"], "maxLength": 64 },
            "content_hash": { "bsonType": ["string", "null"], "pattern": "^[a-zA-Z0-9_\\-\\.:]{4,128}$" },
            "manifest": { "bsonType": "object" },
            "source_artifact_id": { "bsonType": ["string", "null"], "maxLength": 64 },
            "derivative_spec": { "bsonType": ["object", "null"] },
            "created_at": { "bsonType": "date" },
            "updated_at": { "bsonType": "date" }
        }
    }
}


def run_migration(is_dry_run: bool, database_name: str, batch_size: int, report_file: str = None):
    mode_str = "DRY-RUN (Mô phỏng)" if is_dry_run else "APPLY (Thực thi)"
    logger.info(f"=== Bắt đầu Migration 010: Tạo collection 'artifacts' & tách rời quyền sở hữu [{mode_str}] ===")

    client, db = get_migration_db(database_name)
    report = {
        "migration": "010_create_artifacts_collection_and_migrate_ownership",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "dry_run": is_dry_run,
        "database": db.name,
        "backup_collections": [],
        "artifacts_created": False,
        "migrated_count": 0,
        "assets_cleaned_count": 0,
        "query_cache_index_fixed": False,
        "errors": []
    }

    # 1. Tạo bản sao lưu nếu chạy --apply
    if not is_dry_run:
        logger.info("Đang tạo bản sao lưu dữ liệu trước khi thực thi...")
        bk_assets = create_collection_backup(db, "assets")
        if bk_assets:
            report["backup_collections"].append(bk_assets)
        bk_cache = create_collection_backup(db, "query_cache")
        if bk_cache:
            report["backup_collections"].append(bk_cache)

    # 2. Khởi tạo collection `artifacts` và validator
    existing_cols = db.list_collection_names()
    if "artifacts" not in existing_cols:
        logger.info("Collection 'artifacts' chưa tồn tại. Đang tạo mới...")
        if not is_dry_run:
            db.create_collection(
                "artifacts",
                validator=ARTIFACTS_VALIDATOR,
                validationLevel="moderate",
                validationAction="error"
            )
            report["artifacts_created"] = True
        else:
            logger.info("[DRY-RUN] Sẽ tạo collection 'artifacts' kèm $jsonSchema validator.")
            report["artifacts_created"] = True
    else:
        logger.info("Collection 'artifacts' đã tồn tại. Cập nhật validator...")
        if not is_dry_run:
            try:
                db.command({
                    "collMod": "artifacts",
                    "validator": ARTIFACTS_VALIDATOR,
                    "validationLevel": "moderate",
                    "validationAction": "error"
                })
            except Exception as e:
                logger.warning(f"Lỗi collMod artifacts validator: {e}")

    # 3. Tạo index cho `artifacts`
    if not is_dry_run:
        art_col = db["artifacts"]
        art_col.create_index([("artifact_id", 1)], unique=True, name="artifact_id_1")
        art_col.create_index([("owner_id", 1)], name="owner_id_1")
        art_col.create_index([("blob_id", 1)], name="blob_id_1")
        art_col.create_index([("content_hash", 1)], name="content_hash_1")
        logger.info("Đã tạo indexes cho collection 'artifacts'.")

    # 4. Di trú documents từ `assets` có chứa `manifest` sang `artifacts`
    assets_col = db["assets"]
    assets_with_manifest = list(assets_col.find({"manifest": {"$exists": True, "$ne": None}}))
    logger.info(f"Tìm thấy {len(assets_with_manifest)} assets có chứa manifest cần di trú sang 'artifacts'.")

    migrated = 0
    cleaned = 0
    for doc in assets_with_manifest:
        art_id = doc.get("asset_id") or str(doc.get("_id"))
        owner_id = doc.get("owner_id")
        clean_owner = owner_id if (owner_id and owner_id != "anonymous") else None
        scope = "private" if clean_owner else "public"
        created_at = doc.get("created_at") or datetime.now(timezone.utc)
        if isinstance(created_at, str):
            created_at = ensure_utc_datetime(created_at)

        artifact_doc = {
            "_id": art_id,
            "schema_version": 1,
            "artifact_id": art_id,
            "owner_id": clean_owner,
            "access_scope": scope,
            "blob_id": art_id,
            "content_hash": doc.get("content_hash"),
            "manifest": doc.get("manifest"),
            "source_artifact_id": doc.get("source_asset_id"),
            "derivative_spec": None,
            "created_at": created_at,
            "updated_at": created_at
        }

        if not is_dry_run:
            db["artifacts"].update_one(
                {"_id": art_id},
                {"$set": artifact_doc},
                upsert=True
            )
            # Làm sạch manifest và owner_id trong assets
            assets_col.update_one(
                {"_id": doc["_id"]},
                {"$unset": {"manifest": "", "owner_id": ""}}
            )
        migrated += 1
        cleaned += 1

    report["migrated_count"] = migrated
    report["assets_cleaned_count"] = cleaned
    logger.info(f"[{mode_str}] Đã xử lý di trú {migrated} artifacts, làm sạch {cleaned} assets.")

    # 5. Sửa index query_cache.cache_key thành unique=True
    cache_col = db["query_cache"]
    cache_indexes = cache_col.index_information()
    cache_key_idx = cache_indexes.get("cache_key_1")
    is_already_unique = cache_key_idx and cache_key_idx.get("unique") is True

    if not is_already_unique:
        logger.info("Index 'cache_key_1' trên query_cache chưa có thuộc tính unique=True. Đang sửa...")
        if not is_dry_run:
            try:
                if "cache_key_1" in cache_indexes:
                    cache_col.drop_index("cache_key_1")
                cache_col.create_index([("cache_key", 1)], unique=True, name="cache_key_1")
                report["query_cache_index_fixed"] = True
                logger.info("Đã tạo lại index 'cache_key_1' với unique=True thành công.")
            except Exception as e:
                err_msg = f"Lỗi tạo index unique cho query_cache: {e}"
                logger.error(err_msg)
                report["errors"].append(err_msg)
        else:
            logger.info("[DRY-RUN] Sẽ drop 'cache_key_1' hiện tại và tạo lại với unique=True.")
            report["query_cache_index_fixed"] = True
    else:
        logger.info("Index 'cache_key_1' trên query_cache đã là unique=True.")
        report["query_cache_index_fixed"] = True

    report["script"] = "010_create_artifacts_collection_and_migrate_ownership"
    save_migration_report(report, report_file)
    logger.info(f"=== Hoàn thành Migration 010 [{mode_str}] ===")
    return report


if __name__ == "__main__":
    parser = get_base_parser("Migration 010: Tạo collection 'artifacts' & tách rời quyền sở hữu")
    args = parser.parse_args()
    run_migration(
        is_dry_run=args.dry_run,
        database_name=args.database,
        batch_size=args.batch_size,
        report_file=args.report_file
    )
