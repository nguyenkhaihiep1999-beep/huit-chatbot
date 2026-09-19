"""Synchronize the operation_audit validator with LTX Gateway policies.

This migration only changes collection validation metadata. It never deletes,
rewrites, or copies audit documents and is safe to run repeatedly.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import importlib
from pathlib import Path
import sys
from typing import Any, Dict, Optional

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

from backend.app.data_access.operation_gateway import MutationPolicy
from scripts.migrations.common import get_base_parser, get_migration_db, logger, save_migration_report


COLLECTION_NAME = "operation_audit"
MIGRATION_VERSION = "021"
MIGRATION_NAME = "021_sync_operation_audit_mutation_policies"

_migration_018 = importlib.import_module("scripts.migrations.018_phase6_schema_sync_and_validators")
OPERATION_AUDIT_VALIDATOR = deepcopy(_migration_018.OPERATION_AUDIT_VALIDATOR)
ALLOWED_POLICIES = set(
    OPERATION_AUDIT_VALIDATOR["$jsonSchema"]["properties"]["mutation_policy"]["enum"]
)


def run_migration(
    *,
    is_dry_run: bool = True,
    database_name: Optional[str] = None,
    report_file: Optional[str] = None,
) -> Dict[str, Any]:
    mode = "DRY_RUN" if is_dry_run else "APPLY"
    client, db = get_migration_db(database_name)
    report: Dict[str, Any] = {
        "migration": MIGRATION_NAME,
        "version": MIGRATION_VERSION,
        "mode": mode,
        "database": db.name,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "status": "IN_PROGRESS",
        "existing_policies": [],
        "allowed_policies": sorted(ALLOWED_POLICIES),
        "document_count": 0,
        "valid_document_count": 0,
        "validator_changed": False,
        "errors": [],
    }

    try:
        if db.name != "huit_chatbot":
            raise RuntimeError(f"Refusing to modify unexpected database: {db.name}")
        if COLLECTION_NAME not in db.list_collection_names():
            raise RuntimeError(f"Collection '{COLLECTION_NAME}' does not exist")

        collection = db[COLLECTION_NAME]
        existing_policies = sorted(
            value for value in collection.distinct("mutation_policy") if isinstance(value, str)
        )
        report["existing_policies"] = existing_policies
        unsupported = sorted(set(existing_policies) - ALLOWED_POLICIES)
        if unsupported:
            raise RuntimeError(f"Unsupported existing mutation policies: {unsupported}")

        total = collection.count_documents({})
        valid = collection.count_documents(OPERATION_AUDIT_VALIDATOR)
        report["document_count"] = total
        report["valid_document_count"] = valid
        if total != valid:
            raise RuntimeError(
                f"Proposed validator rejects {total - valid} existing operation_audit documents"
            )

        if not is_dry_run:
            db.command(
                {
                    "collMod": COLLECTION_NAME,
                    "validator": OPERATION_AUDIT_VALIDATOR,
                    "validationLevel": "strict",
                    "validationAction": "error",
                }
            )
            report["validator_changed"] = True
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

            info = db.command("listCollections", filter={"name": COLLECTION_NAME})
            options = info["cursor"]["firstBatch"][0].get("options", {})
            applied = options.get("validator", {}).get("$jsonSchema", {}).get("properties", {}).get(
                "mutation_policy", {}
            ).get("enum", [])
            if set(applied) != ALLOWED_POLICIES:
                raise RuntimeError("Post-verification failed: validator enum differs from migration")
            if options.get("validationLevel") != "strict" or options.get("validationAction") != "error":
                raise RuntimeError("Post-verification failed: validator is not strict/error")

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
    parser = get_base_parser("Migration 021: synchronize operation_audit mutation policies")
    parser.add_argument(
        "--confirm",
        action="store_true",
        help="Required together with --apply in non-interactive environments",
    )
    args = parser.parse_args()
    if args.apply and not args.confirm:
        parser.error("--apply requires --confirm")
    run_migration(
        is_dry_run=args.dry_run,
        database_name=args.database,
        report_file=args.report_file,
    )
