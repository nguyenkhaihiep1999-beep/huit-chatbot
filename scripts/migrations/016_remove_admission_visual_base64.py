"""Migration 016: loại bỏ binary/Base64 khỏi admission_visuals.

MongoDB chỉ giữ scene/data JSON nhỏ. SVG, PNG và Excel được render theo yêu cầu qua
endpoint riêng. Mặc định luôn dry-run và tạo backup trước khi --apply.
"""
from datetime import datetime, timezone
from pathlib import Path
import sys

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from scripts.migrations.common import (
    create_collection_backup,
    get_base_parser,
    get_migration_db,
    logger,
    save_migration_report,
)


HEAVY_FIELDS = ("image_base64", "image_data", "binary", "blob")
ADMISSION_VISUALS_VALIDATOR = {
    "$jsonSchema": {
        "bsonType": "object",
        "required": ["visual_id", "type", "category", "title", "created_at"],
        "properties": {
            "_id": {"bsonType": ["string", "objectId"]},
            "schema_version": {"bsonType": "int", "minimum": 1},
            "visual_id": {"bsonType": "string", "maxLength": 128},
            "type": {"bsonType": "string", "maxLength": 64},
            "category": {"bsonType": "string", "maxLength": 64},
            "major_code": {"bsonType": ["string", "null"], "maxLength": 32},
            "title": {"bsonType": "string", "maxLength": 240},
            "storage_key": {"bsonType": ["string", "null"], "maxLength": 255},
            "headers": {"bsonType": ["array", "null"], "maxItems": 100},
            "rows": {"bsonType": ["array", "null"], "maxItems": 500},
            "created_at": {"bsonType": "date"},
            "updated_at": {"bsonType": ["date", "null"]},
        },
    },
    "$and": [{field: {"$exists": False}} for field in HEAVY_FIELDS],
}


def remove_admission_visual_base64(db, args):
    coll = db["admission_visuals"]
    heavy_filter = {"$or": [{field: {"$exists": True}} for field in HEAVY_FIELDS]}
    affected = coll.count_documents(heavy_filter)
    invalid_required = coll.count_documents({
        "$or": [
            {"visual_id": {"$not": {"$type": "string"}}},
            {"type": {"$not": {"$type": "string"}}},
            {"category": {"$not": {"$type": "string"}}},
            {"title": {"$not": {"$type": "string"}}},
            {"created_at": {"$not": {"$type": "date"}}},
        ]
    })
    report = {
        "script": "016_remove_admission_visual_base64",
        "mode": "apply" if args.apply else "dry-run",
        "started_at": datetime.now(timezone.utc).isoformat(),
        "documents_with_heavy_fields": affected,
        "invalid_required_documents": invalid_required,
        "preflight_passed": invalid_required == 0,
        "updated": 0,
        "remaining": affected,
        "backups": {},
        "errors": 0,
    }
    if args.apply and invalid_required:
        report["errors"] += 1
        report["completed_at"] = datetime.now(timezone.utc).isoformat()
        logger.error("Preflight admission_visuals không đạt; dừng trước mọi thay đổi.")
        return report
    if args.apply:
        report["backups"]["admission_visuals"] = create_collection_backup(db, "admission_visuals")
        if affected:
            result = coll.update_many(heavy_filter, {"$unset": {field: "" for field in HEAVY_FIELDS}})
            report["updated"] = result.modified_count
        report["remaining"] = coll.count_documents(heavy_filter)
        if report["remaining"]:
            report["errors"] += 1
        else:
            try:
                db.command({
                    "collMod": "admission_visuals",
                    "validator": ADMISSION_VISUALS_VALIDATOR,
                    "validationLevel": "moderate",
                    "validationAction": "error",
                })
                report["validator_updated"] = True
            except Exception as exc:
                logger.error("Không thể cập nhật admission_visuals validator: %s", type(exc).__name__)
                report["validator_updated"] = False
                report["errors"] += 1
    report["completed_at"] = datetime.now(timezone.utc).isoformat()
    return report


def main():
    parser = get_base_parser("Migration 016: loại bỏ Base64 khỏi admission_visuals")
    args = parser.parse_args()
    client, db = get_migration_db(args.database)
    try:
        report = remove_admission_visual_base64(db, args)
        save_migration_report(report, args.report_file)
        logger.info(
            "Hoàn thành Migration 016 (%s): affected=%s updated=%s remaining=%s errors=%s",
            report["mode"],
            report["documents_with_heavy_fields"],
            report["updated"],
            report["remaining"],
            report["errors"],
        )
        if report["errors"] or not report["preflight_passed"]:
            raise SystemExit(2)
    finally:
        client.close()


if __name__ == "__main__":
    main()
