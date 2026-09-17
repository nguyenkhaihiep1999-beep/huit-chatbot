"""
015_sync_job_and_image_validators.py
Migration đồng bộ JSON Schema Validators và các trường resilience cho `jobs` và `generated_images`:
- Bổ sung schema validator cho `jobs`: attempt, max_attempts, idempotency_key, lease_owner, lease_expires_at, heartbeat_at, available_at, sanitized_error.
- Bổ sung schema validator cho `generated_images`: request_fingerprint, blob_id, access_scope.
- Backfill các trường thiếu cho 23 jobs hiện có:
    * attempt: doc.get("retries", 0)
    * max_attempts: 3
    * idempotency_key: None
    * available_at: doc.get("created_at") or now
    * lease_owner: None
    * lease_expires_at: None
    * heartbeat_at: None
    * sanitized_error: None
- Hỗ trợ đầy đủ --dry-run (mặc định) và --apply (tự động sao lưu collection trước khi cập nhật).
"""
from pathlib import Path
import sys
ROOT_DIR = Path(__file__).resolve().parent.parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from datetime import datetime, timezone
from typing import Any, Dict, List
from pymongo import UpdateOne

from scripts.migrations.common import (
    get_base_parser,
    get_migration_db,
    create_collection_backup,
    save_migration_report,
    logger,
)


JOBS_VALIDATOR_EXTENSION = {
    "$jsonSchema": {
        "bsonType": "object",
        "required": [
            "job_id", "action", "status", "progress", "attempt", "max_attempts",
            "idempotency_key", "lease_owner", "lease_expires_at", "heartbeat_at",
            "available_at", "created_at", "updated_at"
        ],
        "properties": {
            "_id": {"bsonType": ["string", "objectId"]},
            "schema_version": {"bsonType": "int", "minimum": 1},
            "job_id": {"bsonType": "string", "pattern": "^job_[a-zA-Z0-9_\\-]+$"},
            "action": {"bsonType": "string", "maxLength": 64},
            "artifact_id": {"bsonType": ["string", "null"]},
            "format": {"bsonType": ["string", "null"]},
            "status": {"enum": ["queued", "processing", "completed", "failed", "cancelled"]},
            "progress": {"bsonType": "int", "minimum": 0, "maximum": 100},
            "retries": {"bsonType": "int", "minimum": 0, "maximum": 10},
            "attempt": {"bsonType": "int", "minimum": 0, "maximum": 10},
            "max_attempts": {"bsonType": "int", "minimum": 1, "maximum": 10},
            "idempotency_key": {"bsonType": ["string", "null"]},
            "lease_owner": {"bsonType": ["string", "null"]},
            "lease_expires_at": {"bsonType": ["date", "null"]},
            "heartbeat_at": {"bsonType": ["date", "null"]},
            "available_at": {"bsonType": ["date", "null"]},
            "result_url": {"bsonType": ["string", "null"]},
            "media_type": {"bsonType": ["string", "null"]},
            "error": {"bsonType": ["object", "null"]},
            "sanitized_error": {"bsonType": ["string", "null"]},
            "owner_id": {"bsonType": ["string", "null"]},
            "request_id": {"bsonType": ["string", "null"]},
            "events": {"bsonType": "array", "maxItems": 50},
            "created_at": {"bsonType": "date"},
            "updated_at": {"bsonType": "date"},
            "expires_at": {"bsonType": ["date", "null"]}
        }
    }
}

IMAGES_VALIDATOR_EXTENSION = {
    "$jsonSchema": {
        "bsonType": "object",
        "required": [
            "image_id", "content_hash", "request_fingerprint", "blob_id",
            "access_scope", "model", "created_at"
        ],
        "properties": {
            "_id": {"bsonType": ["string", "objectId"]},
            "schema_version": {"bsonType": "int", "minimum": 1},
            "image_id": {"bsonType": "string"},
            "backend": {"enum": ["flux", "svg"]},
            "content_hash": {"bsonType": "string"},
            "generation_key": {"bsonType": ["string", "null"]},
            "request_fingerprint": {"bsonType": ["string", "null"]},
            "blob_id": {"bsonType": ["string", "null"]},
            "access_scope": {"enum": ["public", "private", "legacy_public"]},
            "model": {"bsonType": "string"},
            "seed": {"bsonType": ["int", "null"]},
            "style": {"bsonType": ["string", "null"]},
            "width": {"bsonType": "int"},
            "height": {"bsonType": "int"},
            "storage_key": {"bsonType": ["string", "null"]},
            "thumbnail_key": {"bsonType": ["string", "null"]},
            "content_type": {"bsonType": ["string", "null"]},
            "byte_size": {"bsonType": ["int", "null"]},
            "thumb_size": {"bsonType": ["int", "null"]},
            "scene": {"bsonType": ["object", "null"]},
            "scene_bytes": {"bsonType": ["int", "null"]},
            "created_at": {"bsonType": "date"},
            "owner_id": {"bsonType": ["string", "null"]},
            "is_archived_duplicate": {"bsonType": ["bool", "null"]},
            "canonical_content_hash": {"bsonType": ["string", "null"]}
        }
    }
}


def sync_validators_and_fields(db, args) -> Dict[str, Any]:
    now_dt = datetime.now(timezone.utc)
    jobs_col = db["jobs"]
    images_col = db["generated_images"]

    total_jobs = jobs_col.count_documents({})
    duplicate_idempotency = list(jobs_col.aggregate([
        {"$set": {"_effective_idempotency": {"$ifNull": [
            "$idempotency_key",
            {"$concat": ["legacy:", {"$toString": {"$ifNull": ["$job_id", "$_id"]}}]},
        ]}}},
        {"$group": {"_id": "$_effective_idempotency", "count": {"$sum": 1}}},
        {"$match": {"count": {"$gt": 1}}},
        {"$limit": 20},
    ]))
    jobs_needing_sync = jobs_col.count_documents({
        "$or": [
            {"attempt": {"$exists": False}},
            {"max_attempts": {"$exists": False}},
            {"available_at": {"$exists": False}},
            {"idempotency_key": {"$exists": False}},
            {"lease_owner": {"$exists": False}},
            {"lease_expires_at": {"$exists": False}},
            {"heartbeat_at": {"$exists": False}},
            {"sanitized_error": {"$exists": False}}
        ]
    })

    total_images = images_col.count_documents({})
    images_needing_sync = images_col.count_documents({
        "$or": [
            {"request_fingerprint": {"$exists": False}},
            {"request_fingerprint": None},
            {"blob_id": {"$exists": False}},
            {"blob_id": None},
            {"access_scope": {"$exists": False}}
        ]
    })

    assets_col = db["assets"]
    blob_resolution: Dict[Any, str] = {}
    unresolved_images = []
    for img in images_col.find({"$or": [{"blob_id": {"$exists": False}}, {"blob_id": None}]}):
        image_id = img.get("image_id") or str(img.get("_id"))
        storage_key = img.get("storage_key")
        lookup_terms = [{"asset_id": image_id}, {"_id": image_id}]
        if storage_key:
            lookup_terms.append({"storage_key": storage_key})
        asset = assets_col.find_one({"$or": lookup_terms})
        if asset and (asset.get("asset_id") or asset.get("_id")):
            blob_resolution[img["_id"]] = str(asset.get("asset_id") or asset.get("_id"))
        else:
            unresolved_images.append(str(img.get("_id")))

    report = {
        "script": "015_sync_job_and_image_validators",
        "started_at": now_dt.isoformat(),
        "mode": "apply" if args.apply else "dry-run",
        "jobs": {
            "total": total_jobs,
            "needing_sync": jobs_needing_sync,
            "updated": 0,
            "duplicate_idempotency_groups": len(duplicate_idempotency)
        },
        "generated_images": {
            "total": total_images,
            "needing_sync": images_needing_sync,
            "updated": 0,
            "unresolved_blob_ids": len(unresolved_images)
        },
        "validators_updated": [],
        "preflight_passed": not unresolved_images and not duplicate_idempotency,
        "errors": 0,
        "backups": {}
    }

    logger.info(f"Jobs: {total_jobs} total, {jobs_needing_sync} cần bổ sung trường.")
    logger.info(f"Generated Images: {total_images} total, {images_needing_sync} cần bổ sung trường.")

    if args.apply:
        if unresolved_images or duplicate_idempotency:
            report["errors"] += 1
            if unresolved_images:
                report["generated_images"]["unresolved_samples"] = unresolved_images[:20]
            if duplicate_idempotency:
                report["jobs"]["duplicate_idempotency_samples"] = [
                    {"key": row["_id"], "count": row["count"]} for row in duplicate_idempotency
                ]
            logger.error("Preflight migration 015 không đạt; dừng trước mọi thay đổi.")
            report["completed_at"] = datetime.now(timezone.utc).isoformat()
            return report
        logger.info("Chế độ APPLY: Tạo bản sao lưu và cập nhật documents + schema validators...")
        report["backups"]["jobs"] = create_collection_backup(db, "jobs")
        report["backups"]["generated_images"] = create_collection_backup(db, "generated_images")

        # 1. Backfill jobs
        job_ops = []
        for job in jobs_col.find({
            "$or": [
                {"attempt": {"$exists": False}},
                {"max_attempts": {"$exists": False}},
                {"available_at": {"$exists": False}},
                {"idempotency_key": {"$exists": False}},
                {"lease_owner": {"$exists": False}},
                {"lease_expires_at": {"$exists": False}},
                {"heartbeat_at": {"$exists": False}},
                {"sanitized_error": {"$exists": False}}
            ]
        }):
            update_fields: Dict[str, Any] = {}
            if "attempt" not in job:
                update_fields["attempt"] = int(job.get("retries", 0))
            if "max_attempts" not in job:
                update_fields["max_attempts"] = 3
            if "available_at" not in job:
                update_fields["available_at"] = job.get("created_at") or now_dt
            if "idempotency_key" not in job:
                update_fields["idempotency_key"] = f"legacy:{job.get('job_id') or job.get('_id')}"
            if "lease_owner" not in job:
                update_fields["lease_owner"] = None
            if "lease_expires_at" not in job:
                update_fields["lease_expires_at"] = None
            if "heartbeat_at" not in job:
                update_fields["heartbeat_at"] = None
            if "sanitized_error" not in job:
                err_dict = job.get("error")
                san_err = err_dict.get("message") if isinstance(err_dict, dict) else (str(err_dict) if err_dict else None)
                update_fields["sanitized_error"] = san_err

            if update_fields:
                job_ops.append(UpdateOne({"_id": job["_id"]}, {"$set": update_fields}))

        if job_ops:
            res_jobs = jobs_col.bulk_write(job_ops, ordered=False)
            report["jobs"]["updated"] = res_jobs.modified_count
            logger.info(f"Đã cập nhật {res_jobs.modified_count} jobs.")

        try:
            jobs_col.create_index(
                [("idempotency_key", 1)],
                name="idempotency_key_unique_v1",
                unique=True,
                partialFilterExpression={"idempotency_key": {"$type": "string"}},
            )
        except Exception as exc:
            report["errors"] += 1
            logger.error("Không thể tạo idempotency index: %s", type(exc).__name__)
            report["completed_at"] = datetime.now(timezone.utc).isoformat()
            return report

        # 2. Backfill images: request_fingerprint, blob_id
        img_ops = []
        for img in images_col.find({
            "$or": [
                {"request_fingerprint": {"$exists": False}},
                {"request_fingerprint": None},
                {"blob_id": {"$exists": False}},
                {"blob_id": None},
                {"access_scope": {"$exists": False}}
            ]
        }):
            update_fields: Dict[str, Any] = {}
            if "request_fingerprint" not in img or not img.get("request_fingerprint"):
                update_fields["request_fingerprint"] = img.get("canonical_content_hash") or img.get("content_hash") or str(img["_id"])
            if not img.get("blob_id"):
                update_fields["blob_id"] = blob_resolution[img["_id"]]
            if "access_scope" not in img:
                update_fields["access_scope"] = "private" if img.get("owner_id") else "public"

            if update_fields:
                img_ops.append(UpdateOne({"_id": img["_id"]}, {"$set": update_fields}))

        if img_ops:
            res_imgs = images_col.bulk_write(img_ops, ordered=False)
            report["generated_images"]["updated"] = res_imgs.modified_count
            logger.info(f"Đã cập nhật {res_imgs.modified_count} generated_images.")

        # 3. Áp dụng collMod cho jobs
        try:
            db.command({
                "collMod": "jobs",
                "validator": JOBS_VALIDATOR_EXTENSION,
                "validationLevel": "moderate"
            })
            report["validators_updated"].append("jobs")
            logger.info("Đã cập nhật validator cho collection 'jobs'.")
        except Exception as e:
            logger.error(f"Lỗi khi collMod jobs: {e}")
            report["errors"] += 1

        # 4. Áp dụng collMod cho generated_images
        try:
            db.command({
                "collMod": "generated_images",
                "validator": IMAGES_VALIDATOR_EXTENSION,
                "validationLevel": "moderate"
            })
            report["validators_updated"].append("generated_images")
            logger.info("Đã cập nhật validator cho collection 'generated_images'.")
        except Exception as e:
            logger.error(f"Lỗi khi collMod generated_images: {e}")
            report["errors"] += 1

    report["completed_at"] = datetime.now(timezone.utc).isoformat()
    return report


def main():
    parser = get_base_parser("Migration 015: Đồng bộ validators và fields cho jobs và generated_images")
    args = parser.parse_args()

    client, db = get_migration_db(args.database)
    try:
        report = sync_validators_and_fields(db, args)
        save_migration_report(report, args.report_file)
        logger.info(
            f"Hoàn thành Migration 015 ({report['mode']}): "
            f"Jobs needing sync: {report['jobs']['needing_sync']}, "
            f"Images needing sync: {report['generated_images']['needing_sync']}, "
            f"Validators updated: {report['validators_updated']}, Lỗi: {report['errors']}."
        )
        if report["errors"] or not report["preflight_passed"]:
            raise SystemExit(2)
    finally:
        client.close()


if __name__ == "__main__":
    main()
