import sys, os
from pathlib import Path
from datetime import datetime, timezone
import json

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

from scripts.migrations.common import get_migration_db

def run_audit():
    client, db = get_migration_db()
    
    collections = ['huit_kb', 'assets', 'artifacts', 'jobs', 'generated_images', 'query_cache', 'rag_events', 'admission_visuals']
    counts = {c: db[c].count_documents({}) for c in collections}
    
    # Jobs audit
    total_jobs = counts['jobs']
    jobs_missing_attempt = db['jobs'].count_documents({"attempt": {"$exists": False}})
    jobs_missing_idempotency = db['jobs'].count_documents({"idempotency_key": {"$exists": False}})
    jobs_missing_max_attempts = db['jobs'].count_documents({"max_attempts": {"$exists": False}})
    stuck_jobs = db['jobs'].count_documents({"status": "processing"})
    failed_jobs = db['jobs'].count_documents({"status": "failed"})
    completed_jobs = db['jobs'].count_documents({"status": "completed"})
    
    # Generated images audit
    total_images = counts['generated_images']
    images_no_owner = db['generated_images'].count_documents({"$or": [{"owner_id": {"$exists": False}}, {"owner_id": None}]})
    images_legacy_public = db['generated_images'].count_documents({"access_scope": "legacy_public"})
    images_private = db['generated_images'].count_documents({"access_scope": "private"})
    images_no_blob = db['generated_images'].count_documents({"$or": [{"blob_id": {"$exists": False}}, {"blob_id": None}]})
    
    # Assets and physical files
    storage_root = ROOT_DIR / "data" / "artifacts_store"
    assets = list(db['assets'].find({}))
    no_storage_key = []
    missing_physical = []
    valid_physical = []
    
    for a in assets:
        aid = a.get("asset_id") or str(a.get("_id"))
        s_key = a.get("storage_key")
        if not s_key:
            no_storage_key.append(aid)
        else:
            p = storage_root / s_key
            if not p.exists():
                missing_physical.append({"asset_id": aid, "storage_key": s_key})
            else:
                valid_physical.append({"asset_id": aid, "storage_key": s_key, "size": p.stat().st_size})
                
    existing_files = [f.name for f in storage_root.glob("*") if f.is_file()] if storage_root.exists() else []
    known_keys = {a.get("storage_key") for a in assets if a.get("storage_key")}
    orphan_files = [f for f in existing_files if f not in known_keys]
    
    # References to corrupted/missing assets
    problematic_asset_ids = set(no_storage_key) | {item["asset_id"] for item in missing_physical}
    
    # References from generated_images
    img_refs = list(db['generated_images'].find({"blob_id": {"$in": list(problematic_asset_ids)}}))
    art_refs = list(db['artifacts'].find({"blob_id": {"$in": list(problematic_asset_ids)}}))
    
    # Vector Search Index on huit_kb
    vector_search_status = "unknown"
    try:
        indexes = list(db['huit_kb'].list_search_indexes())
        vector_search_status = [idx.get("name") for idx in indexes]
    except Exception as e:
        vector_search_status = f"list_search_indexes error: {e}"
        
    report = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "counts": counts,
        "jobs": {
            "total": total_jobs,
            "stuck_processing": stuck_jobs,
            "failed": failed_jobs,
            "completed": completed_jobs,
            "missing_attempt": jobs_missing_attempt,
            "missing_idempotency_key": jobs_missing_idempotency,
            "missing_max_attempts": jobs_missing_max_attempts
        },
        "generated_images": {
            "total": total_images,
            "no_owner": images_no_owner,
            "legacy_public": images_legacy_public,
            "private": images_private,
            "missing_blob_id": images_no_blob
        },
        "storage": {
            "storage_root": str(storage_root),
            "total_assets": len(assets),
            "no_storage_key_count": len(no_storage_key),
            "no_storage_key_ids": no_storage_key,
            "missing_physical_count": len(missing_physical),
            "missing_physical_items": missing_physical,
            "valid_physical_count": len(valid_physical),
            "physical_files_on_disk": len(existing_files),
            "orphan_files_count": len(orphan_files),
            "orphan_files": orphan_files,
            "referenced_problematic_assets": {
                "generated_images_count": len(img_refs),
                "generated_images": [img.get("image_id") for img in img_refs],
                "artifacts_count": len(art_refs),
                "artifacts": [art.get("artifact_id") for art in art_refs]
            }
        },
        "vector_search_index": vector_search_status
    }
    
    out_path = ROOT_DIR / "audit_outputs" / "baseline_audit_report.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
        
    print(json.dumps(report, indent=2, ensure_ascii=False))

if __name__ == "__main__":
    run_audit()
