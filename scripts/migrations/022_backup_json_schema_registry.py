"""Back up canonical JSON Schemas to MongoDB with version and SHA-256.

Git remains authoritative. This migration is idempotent, never deletes older
schema versions, and writes only to ``schema_registry`` plus migration metadata.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import sys
from typing import Any, Dict, List, Optional

import pymongo

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

from backend.app.contracts.schema_registry import iter_schema_entries, load_schema, schema_sha256
from scripts.migrations.common import get_base_parser, get_migration_db, logger, save_migration_report


COLLECTION_NAME = "schema_registry"
MIGRATION_VERSION = "022"
MIGRATION_NAME = "022_backup_json_schema_registry"
REGISTRY_VALIDATOR = load_schema("huit.mongo.schema-registry-record", "1.0.0")


def build_registry_documents(now: Optional[datetime] = None) -> List[Dict[str, Any]]:
    timestamp = now or datetime.now(timezone.utc)
    documents = []
    for entry in iter_schema_entries():
        documents.append(
            {
                "schema_id": entry["schema_id"],
                "schema_version": entry["version"],
                "kind": entry["kind"],
                "file": entry["file"],
                "sha256": schema_sha256(entry["schema_id"], entry["version"]),
                "schema_document": load_schema(entry["schema_id"], entry["version"]),
                "consumers": entry["consumers"],
                "status": "active",
                "created_at": timestamp,
                "updated_at": timestamp,
            }
        )
    return documents


def run_migration(
    *,
    is_dry_run: bool = True,
    database_name: Optional[str] = None,
    report_file: Optional[str] = None,
) -> Dict[str, Any]:
    mode = "DRY_RUN" if is_dry_run else "APPLY"
    client, db = get_migration_db(database_name)
    documents = build_registry_documents()
    report: Dict[str, Any] = {
        "migration": MIGRATION_NAME,
        "version": MIGRATION_VERSION,
        "mode": mode,
        "database": db.name,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "status": "IN_PROGRESS",
        "contracts": [
            {
                "schema_id": doc["schema_id"],
                "schema_version": doc["schema_version"],
                "sha256": doc["sha256"],
            }
            for doc in documents
        ],
        "planned_upserts": len(documents),
        "applied_upserts": 0,
        "errors": [],
    }

    try:
        if db.name != "huit_chatbot":
            raise RuntimeError(f"Refusing to modify unexpected database: {db.name}")

        exists = COLLECTION_NAME in db.list_collection_names()
        report["collection_exists_before"] = exists
        if is_dry_run:
            report["status"] = "SUCCESS"
            return report

        if not exists:
            db.create_collection(
                COLLECTION_NAME,
                validator=REGISTRY_VALIDATOR,
                validationLevel="strict",
                validationAction="error",
            )
        else:
            db.command(
                {
                    "collMod": COLLECTION_NAME,
                    "validator": REGISTRY_VALIDATOR,
                    "validationLevel": "strict",
                    "validationAction": "error",
                }
            )

        collection = db[COLLECTION_NAME]
        collection.create_indexes(
            [
                pymongo.IndexModel(
                    [("schema_id", pymongo.ASCENDING), ("schema_version", pymongo.ASCENDING)],
                    unique=True,
                    name="uniq_schema_id_version",
                ),
                pymongo.IndexModel(
                    [("status", pymongo.ASCENDING), ("kind", pymongo.ASCENDING)],
                    name="idx_schema_status_kind",
                ),
                pymongo.IndexModel([("sha256", pymongo.ASCENDING)], name="idx_schema_sha256"),
            ]
        )

        for document in documents:
            created_at = document.pop("created_at")
            collection.update_one(
                {
                    "schema_id": document["schema_id"],
                    "schema_version": document["schema_version"],
                },
                {
                    "$set": document,
                    "$setOnInsert": {"created_at": created_at},
                },
                upsert=True,
            )
            report["applied_upserts"] += 1

        for expected in report["contracts"]:
            stored = collection.find_one(
                {
                    "schema_id": expected["schema_id"],
                    "schema_version": expected["schema_version"],
                },
                {"sha256": 1},
            )
            if not stored or stored.get("sha256") != expected["sha256"]:
                raise RuntimeError(
                    f"Post-verification checksum mismatch: {expected['schema_id']}@{expected['schema_version']}"
                )

        db["schema_migrations"].update_one(
            {"version": MIGRATION_VERSION},
            {
                "$set": {
                    "version": MIGRATION_VERSION,
                    "name": MIGRATION_NAME,
                    "applied_at": datetime.now(timezone.utc),
                    "status": "SUCCESS",
                }
            },
            upsert=True,
        )
        report["status"] = "SUCCESS"
        return report
    except Exception as exc:
        report["status"] = "FAILED"
        report["errors"].append(str(exc))
        raise
    finally:
        report["finished_at"] = datetime.now(timezone.utc).isoformat()
        save_migration_report(report, report_file)
        client.close()


if __name__ == "__main__":
    parser = get_base_parser("Migration 022: back up canonical JSON Schemas to MongoDB")
    parser.add_argument("--confirm", action="store_true", help="Required together with --apply")
    args = parser.parse_args()
    if args.apply and not args.confirm:
        parser.error("--apply requires --confirm")
    run_migration(
        is_dry_run=args.dry_run,
        database_name=args.database,
        report_file=args.report_file,
    )
