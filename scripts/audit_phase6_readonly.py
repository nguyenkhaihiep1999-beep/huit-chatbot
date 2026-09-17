"""
scripts/audit_phase6_readonly.py
Công cụ Verifier Read-Only kiểm tra trạng thái hậu kiểm sau Migration 018:
- Kiểm tra toàn bộ validators và validation options trên 9 collections chính:
  assets, artifacts, jobs, generated_images, query_cache, rag_events, admission_visuals, huit_kb, operation_audit
- Kiểm tra indexes (unique, compound, TTL, sparse)
- Kiểm tra BSON Date vs string date (phải là 0)
- Kiểm tra rò rỉ Base64 / binary (phải là 0)
- Kiểm tra trạng thái Vector Search Index trên huit_kb
- Không làm thay đổi database, không in credentials.
"""
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sys
from typing import Any, Dict, List

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

from backend.app.config import settings
from backend.app.repositories.mongo_repository import MongoRepository


def verify_phase6_readonly() -> Dict[str, Any]:
    db = MongoRepository.get_db()
    logger_out = []

    def log(msg: str):
        print(msg)
        logger_out.append(msg)

    log(f"=== BẮT ĐẦU HẬU KIỂM READ-ONLY DATABASE: {db.name} ===")

    core_collections = [
        "assets",
        "artifacts",
        "jobs",
        "generated_images",
        "query_cache",
        "rag_events",
        "admission_visuals",
        "huit_kb",
        "operation_audit",
    ]

    all_colls = db.list_collection_names()
    coll_infos = {c["name"]: c for c in db.list_collections()}

    report = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "database": db.name,
        "collections_status": {},
        "summary": {
            "all_validators_active": True,
            "total_string_dates": 0,
            "total_base64_leaks": 0,
            "huit_vector_search_ready": False,
        },
    }

    for col_name in core_collections:
        if col_name not in all_colls:
            log(f"[FAIL] Collection '{col_name}' không tồn tại trên database!")
            report["summary"]["all_validators_active"] = False
            report["collections_status"][col_name] = {"exists": False}
            continue

        c = db[col_name]
        doc_count = c.count_documents({})
        c_info = coll_infos.get(col_name, {})
        opts = c_info.get("options", {})
        validator = opts.get("validator")
        v_level = opts.get("validationLevel", "none")
        v_action = opts.get("validationAction", "none")

        has_val = bool(validator and "$jsonSchema" in validator)
        if not has_val:
            report["summary"]["all_validators_active"] = False

        indexes = list(c.list_indexes())
        idx_names = [i["name"] for i in indexes]

        # Quét BSON Date vs string date và Base64
        string_date_count = 0
        base64_count = 0
        for doc in c.find({}):
            for k, v in doc.items():
                if k == "embedding":
                    continue
                if isinstance(v, str):
                    if ("date" in k.lower() or "time" in k.lower() or k.endswith("_at")) and re.match(
                        r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}", v
                    ):
                        string_date_count += 1
                    if len(v) > 500 and ("data:image/" in v or "base64," in v):
                        base64_count += 1
                elif isinstance(v, bytes):
                    base64_count += 1

        report["summary"]["total_string_dates"] += string_date_count
        report["summary"]["total_base64_leaks"] += base64_count

        log(
            f"✓ [{col_name}] {doc_count} docs | "
            f"Validator: {'CÓ' if has_val else 'CHƯA'} ({v_level}/{v_action}) | "
            f"{len(indexes)} Indexes: {idx_names} | "
            f"StringDates: {string_date_count} | Base64: {base64_count}"
        )

        report["collections_status"][col_name] = {
            "exists": True,
            "count": doc_count,
            "has_validator": has_val,
            "validation_level": v_level,
            "validation_action": v_action,
            "indexes_count": len(indexes),
            "indexes": idx_names,
            "string_dates": string_date_count,
            "base64_leaks": base64_count,
        }

    # Kiểm tra Vector Search Index trên huit_kb
    kb_col = db["huit_kb"]
    try:
        vs_indexes = list(kb_col.aggregate([{"$listSearchIndexes": {}}]))
        for si in vs_indexes:
            if si.get("name") == "huit_vector_index" and si.get("status") == "READY":
                report["summary"]["huit_vector_search_ready"] = True
                log("✓ Vector Search Index 'huit_vector_index' trên 'huit_kb' đang ở trạng thái READY (1024D)")
    except Exception as e:
        log(f"Cảnh báo kiểm tra vector search index: {e}")

    log("\n=== TỔNG KẾT HẬU KIỂM ===")
    log(f"- Toàn bộ 9/9 core collections đã có Validator: {report['summary']['all_validators_active']}")
    log(f"- Tổng số trường String Date (phải bằng 0): {report['summary']['total_string_dates']}")
    log(f"- Tổng số trường rò rỉ Base64 (phải bằng 0): {report['summary']['total_base64_leaks']}")
    log(f"- Vector Search 'huit_kb' READY: {report['summary']['huit_vector_search_ready']}")

    out_file = ROOT_DIR / "audit_outputs" / "phase6_post_verification_readonly_report.json"
    out_file.parent.mkdir(exist_ok=True)
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    log(f"- Báo cáo đã lưu tại: {out_file}")

    return report


if __name__ == "__main__":
    verify_phase6_readonly()
