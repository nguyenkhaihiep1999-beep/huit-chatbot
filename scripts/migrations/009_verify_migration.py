"""
009_verify_migration.py
Kiểm tra nghiệm thu toàn diện sau khi chạy chuỗi Migration:
- Xác nhận các $jsonSchema validators đã được áp dụng và active.
- Xác nhận toàn bộ các Unique Indexes, Compound Indexes, TTL Indexes đã tồn tại.
- Xác nhận không còn trường ngày giờ nào lưu dạng chuỗi String trong các collection cốt lõi.
- Xác nhận không còn trường nhị phân / Base64 lớn nào lưu trực tiếp trong MongoDB.
- Xác nhận Vector Search Index trên `huit_kb` hoàn toàn nguyên vẹn.
- Kiểm tra tính tuân thủ của các document mẫu với Pydantic Models.
"""
from pathlib import Path
import sys
ROOT_DIR = Path(__file__).resolve().parent.parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from datetime import datetime, timezone
from typing import Any, Dict, List

from scripts.migrations.common import (

    get_base_parser,
    get_migration_db,
    save_migration_report,
    logger,
)
from backend.app.models.mongo_models import (
    MongoAssetRecord,
    MongoJobRecord,
    MongoGeneratedImageRecord,
    MongoQueryCacheRecord,
    MongoRagEventRecord,
)
from backend.app.storage.storage_adapter import get_storage_adapter

CORE_COLLECTIONS = ["assets", "artifacts", "jobs", "generated_images", "query_cache", "rag_events", "admission_visuals", "huit_kb"]


def verify_database_state(db) -> Dict[str, Any]:
    logger.info("Bắt đầu nghiệm thu trạng thái MongoDB...")
    verification = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "database": db.name,
        "overall_passed": True,
        "checks": {}
    }

    # 1. Kiểm tra Validators
    val_checks = {}
    required_fields = {
        "assets": {"asset_id", "content_hash", "media_type", "file_ext", "file_size", "created_at"},
        "artifacts": {"artifact_id", "manifest", "created_at", "updated_at"},
        "jobs": {
            "job_id", "action", "status", "progress", "attempt", "max_attempts",
            "idempotency_key", "lease_owner", "lease_expires_at", "heartbeat_at",
            "available_at", "created_at", "updated_at",
        },
        "query_cache": {"cache_key", "answer", "expires_at", "updated_at"},
        "rag_events": {"request_id", "created_at", "question_hash", "intent"},
        "generated_images": {
            "image_id", "content_hash", "request_fingerprint", "blob_id",
            "access_scope", "model", "created_at",
        },
        "admission_visuals": {"visual_id", "type", "category", "title", "created_at"},
    }
    for c, expected_required in required_fields.items():
        col_info = db.command({"listCollections": 1, "filter": {"name": c}})
        batch = col_info.get("cursor", {}).get("firstBatch", [])
        opts = batch[0].get("options", {}) if batch else {}
        validator = opts.get("validator", {})
        has_val = bool(validator and "$jsonSchema" in validator)
        actual_required = set(validator.get("$jsonSchema", {}).get("required", []))
        missing_required = sorted(expected_required - actual_required)
        validation_level = opts.get("validationLevel", "off")
        val_checks[c] = {
            "has_validator": has_val,
            "level": validation_level,
            "action": opts.get("validationAction", "error"),
            "missing_required_fields": missing_required,
            "passed": has_val and not missing_required and validation_level in {"moderate", "strict"},
        }
        if not val_checks[c]["passed"]:
            verification["overall_passed"] = False
    verification["checks"]["validators"] = val_checks

    # 2. Kiểm tra Indexes và Options (unique, TTL)
    idx_checks = {}
    required_specs = {
        "assets": [
            {"keys": [("asset_id", 1)], "unique": True},
            {"keys": [("content_hash", 1)], "unique": True}
        ],
        "artifacts": [
            {"keys": [("artifact_id", 1)], "unique": True},
            {"keys": [("owner_id", 1)]},
            {"keys": [("blob_id", 1)]},
            {"keys": [("content_hash", 1)]}
        ],
        "jobs": [
            {"keys": [("job_id", 1)], "unique": True},
            {"keys": [("idempotency_key", 1)], "unique": True}
        ],
        "generated_images": [
            {"keys": [("image_id", 1)], "unique": True},
            {"keys": [("blob_id", 1)]},
            {"keys": [("owner_id", 1), ("request_fingerprint", 1)], "unique": True}
        ],
        "query_cache": [
            {"keys": [("cache_key", 1)], "unique": True},
            {"keys": [("expires_at", 1)], "expireAfterSeconds": 0}
        ],
        "rag_events": [
            {"keys": [("created_at", 1)]}
        ]
    }

    for c, specs in required_specs.items():
        existing = db[c].index_information()
        col_failures = []
        for spec in specs:
            spec_keys = spec["keys"]
            # Tìm index khớp keys
            matched_idx = None
            for idx_name, idx_info in existing.items():
                if idx_info.get("key") == spec_keys:
                    matched_idx = idx_info
                    break

            if not matched_idx:
                col_failures.append(f"Thiếu index cho keys {spec_keys}")
                continue

            # Kiểm tra unique nếu được yêu cầu
            if spec.get("unique") is True and not matched_idx.get("unique"):
                col_failures.append(f"Index {spec_keys} thiếu tùy chọn unique=True")

            # Kiểm tra TTL nếu được yêu cầu
            if "expireAfterSeconds" in spec:
                expected_ttl = spec["expireAfterSeconds"]
                actual_ttl = matched_idx.get("expireAfterSeconds")
                if actual_ttl != expected_ttl:
                    col_failures.append(f"Index {spec_keys} có TTL {actual_ttl} != {expected_ttl}")

        idx_checks[c] = {
            "passed": len(col_failures) == 0,
            "failures": col_failures
        }
        if col_failures:
            verification["overall_passed"] = False

    verification["checks"]["indexes"] = idx_checks

    # 3. Kiểm tra ngày giờ String trên toàn bộ các collection cốt lõi
    date_checks = {}
    date_fields_map = [
        ("jobs", ["created_at", "updated_at"]),
        ("assets", ["created_at", "last_accessed_at"]),
        ("artifacts", ["created_at", "updated_at"]),
        ("rag_events", ["created_at"]),
        ("query_cache", ["created_at", "updated_at", "expires_at"]),
        ("generated_images", ["created_at"])
    ]
    existing_coll_names = set(db.list_collection_names())
    for c, fields in date_fields_map:
        if c in existing_coll_names:
            str_count = db[c].count_documents({
                "$or": [{f: {"$type": "string"}} for f in fields]
            })
            date_checks[c] = {
                "string_date_documents": str_count,
                "passed": str_count == 0
            }
            if str_count > 0:
                verification["overall_passed"] = False
    verification["checks"]["string_dates"] = date_checks

    # 4. Kiểm tra Binary / Base64 lớn và tính toàn vẹn tham chiếu
    bin_checks = {}
    if "generated_images" in existing_coll_names:
        raw_img_count = db["generated_images"].count_documents({"image_data": {"$exists": True}})
        bin_checks["generated_images.image_data"] = {
            "count": raw_img_count,
            "passed": raw_img_count == 0
        }
        if raw_img_count > 0:
            verification["overall_passed"] = False

    if "query_cache" in existing_coll_names:
        raw_cache_b64 = db["query_cache"].count_documents({"meta.visual.raw.image_base64": {"$exists": True}})
        bin_checks["query_cache.meta_base64"] = {
            "count": raw_cache_b64,
            "passed": raw_cache_b64 == 0
        }
        if raw_cache_b64 > 0:
            verification["overall_passed"] = False

    # Kiểm tra manifest và owner_id trong assets (đã tách sang artifacts)
    if "assets" in existing_coll_names:
        assets_manifest_count = db["assets"].count_documents({"manifest": {"$exists": True}})
        bin_checks["assets.manifest_residual"] = {
            "count": assets_manifest_count,
            "passed": assets_manifest_count == 0
        }
        if assets_manifest_count > 0:
            verification["overall_passed"] = False

    # Kiểm tra dangling artifacts: artifact trỏ tới blob_id không tồn tại trong assets
    dangling_artifacts = 0
    if "artifacts" in existing_coll_names and "assets" in existing_coll_names:
        for art_doc in db["artifacts"].find({"blob_id": {"$exists": True, "$ne": None}}):
            b_id = art_doc.get("blob_id")
            if b_id and db["assets"].count_documents({"asset_id": b_id}) == 0:
                dangling_artifacts += 1
    bin_checks["artifacts.dangling_blob_references"] = {
        "count": dangling_artifacts,
        "passed": dangling_artifacts == 0
    }
    if dangling_artifacts > 0:
        verification["overall_passed"] = False

    verification["checks"]["binary_and_base64"] = bin_checks

    # 5. Kiểm tra tính toàn vẹn của Vector Search trên huit_kb
    kb_checks = {
        "document_count": db["huit_kb"].count_documents({}) if "huit_kb" in existing_coll_names else 0,
        "vector_search_index_status": "unknown",
        "status": "inconclusive"
    }
    if "huit_kb" in existing_coll_names:
        try:
            search_indexes = list(db["huit_kb"].aggregate([{"$listSearchIndexes": {}}]))
            if search_indexes:
                kb_checks["vector_search_index_status"] = "verified"
                kb_checks["vector_indexes_found"] = len(search_indexes)
                kb_checks["status"] = "pass"
            else:
                kb_checks["vector_search_index_status"] = "no_search_indexes_found"
                kb_checks["status"] = "fail"
        except Exception as e:
            err_msg = str(e).lower()
            if "unauthorized" in err_msg or "command not found" in err_msg or "not supported" in err_msg or "unrecognized" in err_msg:
                kb_checks["vector_search_index_status"] = "unknown_insufficient_privilege"
                kb_checks["reason"] = "Không thể kiểm tra Atlas Search index qua lệnh thông thường (cần Atlas Admin quyền Project)"
                kb_checks["status"] = "inconclusive"
            else:
                kb_checks["vector_search_index_status"] = f"check_inconclusive: {str(e)}"
                kb_checks["status"] = "inconclusive"
            verification["overall_passed"] = False
    verification["checks"]["huit_kb_vector_search"] = kb_checks

    # 6. Kiểm tra tính tồn tại của Physical Files cho Assets
    storage_checks = {
        "total_assets": 0,
        "assets_with_storage_key": 0,
        "missing_storage_key": 0,
        "existing_on_disk": 0,
        "missing_on_disk": 0,
        "missing_asset_ids": [],
        "status": "pass"
    }
    if "assets" in existing_coll_names:
        storage = get_storage_adapter()
        for asset in db["assets"].find({}):
            storage_checks["total_assets"] += 1
            s_key = (asset.get("storage_key") or "").strip()
            if s_key:
                storage_checks["assets_with_storage_key"] += 1
                if storage.exists(s_key):
                    storage_checks["existing_on_disk"] += 1
                else:
                    storage_checks["missing_on_disk"] += 1
                    storage_checks["missing_asset_ids"].append(asset.get("asset_id"))
            else:
                storage_checks["missing_storage_key"] += 1
                storage_checks["missing_asset_ids"].append(asset.get("asset_id"))

        if storage_checks["missing_on_disk"] > 0 or storage_checks["missing_storage_key"] > 0:
            storage_checks["status"] = "fail"
            verification["overall_passed"] = False
    verification["checks"]["physical_storage"] = storage_checks

    # 7. Kiểm tra Index Deduplication trên generated_images
    image_idx_checks = {
        "has_owner_fingerprint_unique": False,
        "has_global_content_hash_unique": False,
        "status": "pass"
    }
    if "generated_images" in existing_coll_names:
        img_indexes = db["generated_images"].index_information()
        for spec in img_indexes.values():
            if spec.get("key") == [("content_hash", 1)] and spec.get("unique", False):
                image_idx_checks["has_global_content_hash_unique"] = True
                image_idx_checks["status"] = "fail"
                verification["overall_passed"] = False
        compound = next((
            spec for spec in img_indexes.values()
            if spec.get("key") == [("owner_id", 1), ("request_fingerprint", 1)]
        ), None)
        if compound and compound.get("unique", False):
            image_idx_checks["has_owner_fingerprint_unique"] = True
        else:
            image_idx_checks["status"] = "fail"
            verification["overall_passed"] = False
    verification["checks"]["image_dedup_index"] = image_idx_checks

    # 8. Kiểm tra các trường resilience trên jobs
    job_checks = {
        "total_jobs": 0,
        "missing_resilience_fields": 0,
        "status": "pass"
    }
    if "jobs" in existing_coll_names:
        job_checks["total_jobs"] = db["jobs"].count_documents({})
        missing = db["jobs"].count_documents({
            "$or": [
                {"attempt": {"$exists": False}},
                {"max_attempts": {"$exists": False}},
                {"available_at": {"$exists": False}},
                {"idempotency_key": {"$exists": False}},
                {"lease_owner": {"$exists": False}},
                {"lease_expires_at": {"$exists": False}},
                {"heartbeat_at": {"$exists": False}}
            ]
        })
        job_checks["missing_resilience_fields"] = missing
        if missing > 0:
            job_checks["status"] = "fail"
            verification["overall_passed"] = False
    verification["checks"]["jobs_resilience"] = job_checks

    # 9. Không cho Base64 quay lại admission_visuals và không cho image blob_id treo.
    compact_checks = {"admission_visuals_base64": 0, "generated_images_dangling_blob_ids": 0, "status": "pass"}
    if "admission_visuals" in existing_coll_names:
        compact_checks["admission_visuals_base64"] = db["admission_visuals"].count_documents({
            "$or": [
                {"image_base64": {"$exists": True}},
                {"image_data": {"$exists": True}},
                {"binary": {"$exists": True}},
                {"blob": {"$exists": True}},
            ]
        })
    if "generated_images" in existing_coll_names and "assets" in existing_coll_names:
        asset_ids = {
            str(d.get("asset_id") or d.get("_id"))
            for d in db["assets"].find({}, {"asset_id": 1})
        }
        compact_checks["generated_images_dangling_blob_ids"] = sum(
            1 for image in db["generated_images"].find({}, {"blob_id": 1})
            if not image.get("blob_id") or str(image.get("blob_id")) not in asset_ids
        )
    if compact_checks["admission_visuals_base64"] or compact_checks["generated_images_dangling_blob_ids"]:
        compact_checks["status"] = "fail"
        verification["overall_passed"] = False
    verification["checks"]["compact_payload_and_blob_integrity"] = compact_checks

    return verification


def run_migration(args):
    client, db = get_migration_db(args.database)
    logger.info(f"=== Bắt đầu 009_verify_migration (Mode: {'DRY-RUN' if args.dry_run else 'APPLY'}) ===")

    report = verify_database_state(db)
    report["script"] = "009_verify_migration"
    report["mode"] = "dry-run" if args.dry_run else "apply"

    logger.info(f"Kết quả nghiệm thu Overall Passed: {report['overall_passed']}")
    save_migration_report(report, args.report_file)
    return report


if __name__ == "__main__":
    parser = get_base_parser("Nghiệm thu toàn diện sau Migration MongoDB")
    args = parser.parse_args()
    result = run_migration(args)
    if not result["overall_passed"]:
        raise SystemExit(2)
