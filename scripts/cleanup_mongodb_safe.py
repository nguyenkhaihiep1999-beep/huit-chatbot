"""Safely remove verified MongoDB noise without touching application data.

Targets are intentionally narrow:
- successful jobs.atomic_claim audit records whose serialized result is the
  known no-op payload (31 bytes: no job was claimed);
- six development-only test collections that have no runtime references.

The script never touches huit_kb, RAG events, user artifacts, generated
images, jobs, cache entries, backups, validators, or indexes.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


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

from backend.app.repositories.mongo_repository import MongoRepository


EXPECTED_DATABASE = "huit_chatbot"
BATCH_SIZE = 10_000
NOOP_AUDIT_FILTER = {
    "operation_key": "jobs.atomic_claim",
    "status": "success",
    "output_bytes": 31,
}
TEST_COLLECTIONS = (
    "test_rag_chunks",
    "test_categorized_data",
    "test_clean_data",
    "test_quality_ranked",
    "test_search_results",
    "test_kb_stats",
)


def _collection_stats(db: Any, name: str) -> dict[str, Any]:
    if name not in db.list_collection_names():
        return {"name": name, "exists": False, "count": 0}
    stats = db.command("collStats", name)
    return {
        "name": name,
        "exists": True,
        "count": int(stats.get("count", 0)),
        "size": int(stats.get("size", 0)),
        "storage_size": int(stats.get("storageSize", 0)),
        "index_size": int(stats.get("totalIndexSize", 0)),
    }


def _delete_noop_audits_in_batches(collection: Any) -> int:
    deleted = 0
    while True:
        ids = [
            row["_id"]
            for row in collection.find(NOOP_AUDIT_FILTER, {"_id": 1}).limit(BATCH_SIZE)
        ]
        if not ids:
            break
        result = collection.delete_many({"_id": {"$in": ids}})
        deleted += int(result.deleted_count)
        print(f"Deleted {deleted:,} no-op audit records...", flush=True)
    return deleted


def run(*, apply: bool) -> dict[str, Any]:
    client = MongoRepository.get_client()
    db = MongoRepository.get_db()
    if db.name != EXPECTED_DATABASE:
        raise RuntimeError(f"Từ chối thao tác trên database không mong đợi: {db.name}")

    audit = db["operation_audit"]
    before_total = audit.count_documents({})
    noop_count = audit.count_documents(NOOP_AUDIT_FILTER)
    real_claim_count = audit.count_documents(
        {"operation_key": "jobs.atomic_claim", "status": "success", "output_bytes": {"$ne": 31}}
    )
    failed_claim_count = audit.count_documents(
        {"operation_key": "jobs.atomic_claim", "status": "failed"}
    )
    test_before = [_collection_stats(db, name) for name in TEST_COLLECTIONS]

    report: dict[str, Any] = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "database": db.name,
        "mode": "APPLY" if apply else "DRY_RUN",
        "operation_audit": {
            "before_total": before_total,
            "verified_noop_count": noop_count,
            "real_successful_claims_preserved": real_claim_count,
            "failed_claims_preserved": failed_claim_count,
            "deleted_noop_count": 0,
        },
        "test_collections": test_before,
        "dropped_test_collections": [],
        "protected_collections": [
            "huit_kb",
            "rag_events",
            "chat_logs",
            "query_cache",
            "jobs",
            "assets",
            "artifacts",
            "generated_images",
            "admission_visuals",
        ],
    }

    try:
        if apply:
            report["operation_audit"]["deleted_noop_count"] = _delete_noop_audits_in_batches(audit)
            for item in test_before:
                if item["exists"]:
                    db.drop_collection(item["name"])
                    report["dropped_test_collections"].append(item["name"])

        report["operation_audit"]["after_total"] = audit.count_documents({})
        report["operation_audit"]["remaining_verified_noops"] = audit.count_documents(NOOP_AUDIT_FILTER)
        report["operation_audit"]["real_successful_claims_after"] = audit.count_documents(
            {"operation_key": "jobs.atomic_claim", "status": "success", "output_bytes": {"$ne": 31}}
        )
        report["operation_audit"]["failed_claims_after"] = audit.count_documents(
            {"operation_key": "jobs.atomic_claim", "status": "failed"}
        )
        report["remaining_test_collections"] = [
            name for name in TEST_COLLECTIONS if name in db.list_collection_names()
        ]
        return report
    finally:
        client.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Dọn MongoDB no-op audit và collection test đã xác minh")
    parser.add_argument("--apply", action="store_true", help="Thực hiện xóa; mặc định chỉ dry-run")
    parser.add_argument("--confirm", action="store_true", help="Bắt buộc khi dùng --apply")
    args = parser.parse_args()
    if args.apply and not args.confirm:
        parser.error("--apply yêu cầu --confirm")

    report = run(apply=args.apply)
    out_dir = ROOT_DIR / "audit_outputs"
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out_file = out_dir / f"mongodb_safe_cleanup_{stamp}.json"
    out_file.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps(report, ensure_ascii=False, indent=2))
    print(f"Báo cáo: {out_file}")


if __name__ == "__main__":
    main()
