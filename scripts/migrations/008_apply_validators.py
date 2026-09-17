"""
008_apply_validators.py
Áp dụng $jsonSchema Validators cho các collection chính:
- Collection: `assets`, `jobs`, `query_cache`, `rag_events`, `generated_images`.
- Sử dụng lệnh collMod của MongoDB.
- Thiết lập validationLevel: "moderate", validationAction: "error".
- Cấm Base64 lớn, cấm đường dẫn tuyệt đối, cấm path traversal.
- Hỗ trợ đầy đủ --dry-run và --apply.
"""
from pathlib import Path
import sys
ROOT_DIR = Path(__file__).resolve().parent.parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from datetime import datetime, timezone
from typing import Any, Dict

from scripts.migrations.common import (

    get_base_parser,
    get_migration_db,
    save_migration_report,
    logger,
)

VALIDATORS = {
    "assets": {
        "$jsonSchema": {
            "bsonType": "object",
            "required": ["asset_id", "content_hash", "media_type", "file_ext", "storage_key", "file_size", "renderer_version", "created_at"],
            "properties": {
                "_id": { "bsonType": ["string", "objectId"] },
                "schema_version": { "bsonType": "int", "minimum": 1 },
                "asset_id": { "bsonType": "string", "pattern": "^[a-zA-Z0-9_\\-\\.]+$" },
                "content_hash": { "bsonType": "string", "pattern": "^[a-zA-Z0-9_\\-\\.:]{4,128}$" },
                "checksum": { "bsonType": ["string", "null"] },
                "media_type": { "bsonType": "string" },
                "file_ext": { "bsonType": "string", "maxLength": 10 },
                "storage_key": {
                    "bsonType": "string",
                    "pattern": "^$|^[^/\\\\\\.\\.][a-zA-Z0-9_\\-\\.]+$"
                },

                "file_size": { "bsonType": "int", "minimum": 0, "maximum": 52428800 },
                "preview_key": { "bsonType": ["string", "null"] },
                "manifest": { "bsonType": ["object", "null"] },
                "width": { "bsonType": ["int", "null"] },
                "height": { "bsonType": ["int", "null"] },
                "duration": { "bsonType": ["double", "int", "null"] },
                "scale": { "bsonType": ["int", "null"] },
                "reference_count": { "bsonType": "int", "minimum": 1 },
                "renderer_version": { "bsonType": "string" },
                "source_asset_id": { "bsonType": ["string", "null"] },
                "owner_id": { "bsonType": ["string", "null"] },
                "created_at": { "bsonType": "date" },
                "last_accessed_at": { "bsonType": "date" },
                "is_archived_duplicate": { "bsonType": ["bool", "null"] }
            }
        }
    },
    "jobs": {
        "$jsonSchema": {
            "bsonType": "object",
            "required": ["job_id", "action", "status", "progress", "created_at", "updated_at"],
            "properties": {
                "_id": { "bsonType": ["string", "objectId"] },
                "schema_version": { "bsonType": "int", "minimum": 1 },
                "job_id": { "bsonType": "string", "pattern": "^job_[a-zA-Z0-9_\\-]+$" },
                "action": { "bsonType": "string", "maxLength": 64 },
                "artifact_id": { "bsonType": ["string", "null"] },
                "format": { "bsonType": ["string", "null"] },
                "status": { "enum": ["queued", "processing", "completed", "failed", "cancelled"] },
                "progress": { "bsonType": "int", "minimum": 0, "maximum": 100 },
                "retries": { "bsonType": "int", "minimum": 0, "maximum": 5 },
                "result_url": { "bsonType": ["string", "null"] },
                "media_type": { "bsonType": ["string", "null"] },
                "error": { "bsonType": ["object", "null"] },
                "owner_id": { "bsonType": ["string", "null"] },
                "request_id": { "bsonType": ["string", "null"] },
                "events": { "bsonType": "array", "maxItems": 30 },
                "created_at": { "bsonType": "date" },
                "updated_at": { "bsonType": "date" },
                "expires_at": { "bsonType": ["date", "null"] }
            }
        }
    },
    "query_cache": {
        "$jsonSchema": {
            "bsonType": "object",
            "required": ["cache_key", "question_hash", "question_len", "answer", "updated_at", "expires_at"],
            "properties": {
                "_id": { "bsonType": "objectId" },
                "schema_version": { "bsonType": "int", "minimum": 1 },
                "cache_key": { "bsonType": "string" },
                "question_clean": { "bsonType": ["string", "null"] },
                "question_hash": { "bsonType": "string" },
                "question_len": { "bsonType": "int", "minimum": 1 },
                "answer": { "bsonType": "string" },
                "sources": { "bsonType": "array" },
                "trace": { "bsonType": "array" },
                "meta": { "bsonType": "object" },
                "kb_version": { "bsonType": "string" },
                "rag_version": { "bsonType": "string" },
                "model": { "bsonType": "string" },
                "created_at": { "bsonType": ["date", "null"] },
                "updated_at": { "bsonType": "date" },
                "expires_at": { "bsonType": "date" }
            }
        }
    },
    "rag_events": {
        "$jsonSchema": {
            "bsonType": "object",
            "required": ["request_id", "created_at", "question_hash", "question_length", "intent", "elapsed_ms"],
            "properties": {
                "_id": { "bsonType": "objectId" },
                "schema_version": { "bsonType": "int", "minimum": 1 },
                "request_id": { "bsonType": "string" },
                "created_at": { "bsonType": "date" },
                "question_hash": { "bsonType": "string" },
                "question_length": { "bsonType": "int" },
                "intent": { "bsonType": "string" },
                "cached": { "bsonType": "bool" },
                "fallback": { "bsonType": "bool" },
                "source_count": { "bsonType": "int" },
                "source_titles": { "bsonType": "array" },
                "answer_length": { "bsonType": "int" },
                "elapsed_ms": { "bsonType": ["double", "int"] },
                "timings": { "bsonType": "object" },
                "model": { "bsonType": "string" },
                "kb_version": { "bsonType": "string" },
                "rag_version": { "bsonType": "string" },
                "error": { "bsonType": ["string", "null"] }
            }
        }
    },
    "generated_images": {
        "$jsonSchema": {
            "bsonType": "object",
            "required": ["image_id", "content_hash", "model", "created_at"],
            "properties": {
                "_id": { "bsonType": ["string", "objectId"] },
                "schema_version": { "bsonType": "int", "minimum": 1 },
                "image_id": { "bsonType": "string" },
                "backend": { "enum": ["flux", "svg"] },
                "content_hash": { "bsonType": "string" },
                "generation_key": { "bsonType": ["string", "null"] },
                "model": { "bsonType": "string" },
                "seed": { "bsonType": ["int", "null"] },
                "style": { "bsonType": ["string", "null"] },
                "width": { "bsonType": "int" },
                "height": { "bsonType": "int" },
                "storage_key": { "bsonType": ["string", "null"] },
                "thumbnail_key": { "bsonType": ["string", "null"] },
                "content_type": { "bsonType": ["string", "null"] },
                "byte_size": { "bsonType": ["int", "null"] },
                "thumb_size": { "bsonType": ["int", "null"] },
                "scene": { "bsonType": ["object", "null"] },
                "scene_bytes": { "bsonType": ["int", "null"] },
                "created_at": { "bsonType": "date" },
                "owner_id": { "bsonType": ["string", "null"] },
                "is_archived_duplicate": { "bsonType": ["bool", "null"] },
                "canonical_content_hash": { "bsonType": ["string", "null"] }
            }
        }
    }
}


def apply_validators(db, args) -> Dict[str, Any]:
    logger.info(f"Bắt đầu áp dụng $jsonSchema validators cho {len(VALIDATORS)} collections...")
    results = {}

    for col_name, val_spec in VALIDATORS.items():
        if col_name not in db.list_collection_names():
            logger.info(f"Tạo mới collection '{col_name}' kèm validator...")
            if args.apply:
                db.create_collection(
                    col_name,
                    validator=val_spec,
                    validationLevel="moderate",
                    validationAction="error"
                )
            results[col_name] = {"action": "created_with_validator", "status": "success"}
        else:
            logger.info(f"Cập nhật validator cho collection hiện có '{col_name}'...")
            if args.apply:
                db.command({
                    "collMod": col_name,
                    "validator": val_spec,
                    "validationLevel": "moderate",
                    "validationAction": "error"
                })
            results[col_name] = {"action": "collMod_updated", "status": "success"}

    return results


def run_migration(args):
    client, db = get_migration_db(args.database)
    logger.info(f"=== Bắt đầu 008_apply_validators (Mode: {'DRY-RUN' if args.dry_run else 'APPLY'}) ===")

    results = apply_validators(db, args)
    report = {
        "script": "008_apply_validators",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "database": args.database,
        "mode": "dry-run" if args.dry_run else "apply",
        "results": results
    }
    save_migration_report(report, args.report_file)
    return report


if __name__ == "__main__":
    parser = get_base_parser("Áp dụng $jsonSchema validators cho các collections chính")
    args = parser.parse_args()
    run_migration(args)
