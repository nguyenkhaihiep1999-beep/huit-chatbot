"""Migration 017: đồng bộ validator `assets` với MongoAssetRecord.

Migration chỉ cập nhật collection validator. Mặc định là dry-run và từ chối
`--apply` nếu một document hiện hữu thiếu/sai kiểu ở trường bắt buộc.
"""
from datetime import datetime, timezone
from pathlib import Path
import sys

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from scripts.migrations.common import (
    get_base_parser,
    get_migration_db,
    logger,
    save_migration_report,
)


ASSETS_VALIDATOR = {
    "$jsonSchema": {
        "bsonType": "object",
        "required": [
            "asset_id",
            "content_hash",
            "media_type",
            "file_ext",
            "storage_key",
            "file_size",
            "renderer_version",
            "created_at",
        ],
        "properties": {
            "_id": {"bsonType": ["string", "objectId"]},
            "schema_version": {"bsonType": "int", "minimum": 1},
            "asset_id": {
                "bsonType": "string",
                "pattern": "^[a-zA-Z0-9_\\-\\.]+$",
            },
            "content_hash": {
                "bsonType": "string",
                "pattern": "^[a-zA-Z0-9_\\-\\.:]{4,128}$",
            },
            "checksum": {"bsonType": ["string", "null"]},
            "media_type": {"bsonType": "string"},
            "file_ext": {"bsonType": "string", "maxLength": 10},
            "storage_key": {
                "bsonType": "string",
                "pattern": "^$|^[^/\\\\\\.\\.][a-zA-Z0-9_\\-\\.]+$",
            },
            "file_size": {
                "bsonType": "int",
                "minimum": 0,
                "maximum": 52428800,
            },
            "preview_key": {"bsonType": ["string", "null"]},
            "manifest": {"bsonType": ["object", "null"]},
            "width": {"bsonType": ["int", "null"]},
            "height": {"bsonType": ["int", "null"]},
            "duration": {"bsonType": ["double", "int", "null"]},
            "scale": {"bsonType": ["int", "null"]},
            "reference_count": {"bsonType": "int", "minimum": 1},
            "renderer_version": {"bsonType": "string"},
            "source_asset_id": {"bsonType": ["string", "null"]},
            "owner_id": {"bsonType": ["string", "null"]},
            "created_at": {"bsonType": "date"},
            "last_accessed_at": {"bsonType": "date"},
            "is_archived_duplicate": {"bsonType": ["bool", "null"]},
            "status": {"bsonType": ["string", "null"]},
            "corrupted": {"bsonType": ["bool", "null"]},
        },
    }
}

REQUIRED_TYPES = {
    "asset_id": "string",
    "content_hash": "string",
    "media_type": "string",
    "file_ext": "string",
    "storage_key": "string",
    "file_size": "int",
    "renderer_version": "string",
    "created_at": "date",
}


def sync_assets_validator(db, args):
    assets = db["assets"]
    invalid_filter = {
        "$or": [
            {field: {"$not": {"$type": bson_type}}}
            for field, bson_type in REQUIRED_TYPES.items()
        ]
    }
    invalid_count = assets.count_documents(invalid_filter)
    report = {
        "script": "017_sync_assets_validator",
        "mode": "apply" if args.apply else "dry-run",
        "started_at": datetime.now(timezone.utc).isoformat(),
        "total_assets": assets.count_documents({}),
        "invalid_required_documents": invalid_count,
        "preflight_passed": invalid_count == 0,
        "validator_updated": False,
        "errors": 0,
    }

    if args.apply and invalid_count:
        report["errors"] += 1
        logger.error("Assets validator preflight không đạt; dừng trước mọi thay đổi.")
    elif args.apply:
        try:
            db.command({
                "collMod": "assets",
                "validator": ASSETS_VALIDATOR,
                "validationLevel": "moderate",
                "validationAction": "error",
            })
            report["validator_updated"] = True
        except Exception as exc:
            logger.error("Không thể cập nhật assets validator: %s", type(exc).__name__)
            report["errors"] += 1

    report["completed_at"] = datetime.now(timezone.utc).isoformat()
    return report


def main():
    parser = get_base_parser("Migration 017: đồng bộ assets validator")
    args = parser.parse_args()
    client, db = get_migration_db(args.database)
    try:
        report = sync_assets_validator(db, args)
        save_migration_report(report, args.report_file)
        logger.info(
            "Hoàn thành Migration 017 (%s): total=%s invalid=%s updated=%s errors=%s",
            report["mode"],
            report["total_assets"],
            report["invalid_required_documents"],
            report["validator_updated"],
            report["errors"],
        )
        if report["errors"] or not report["preflight_passed"]:
            raise SystemExit(2)
    finally:
        client.close()


if __name__ == "__main__":
    main()
