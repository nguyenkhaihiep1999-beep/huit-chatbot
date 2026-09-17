"""
scripts/audit_mongodb_readonly.py
Công cụ audit MongoDB Atlas chỉ đọc (Read-only), an toàn tuyệt đối:
- Không thay đổi bất kỳ document, index hoặc collection nào trên database.
- Không in/log connection string, mật khẩu, API key.
- Không in nội dung câu hỏi hoặc prompt thô của người dùng (chỉ in hash, ID che bớt và thống kê).
- Kiểm tra toàn bộ: validators, indexes, document count, kiểu dữ liệu, BSON Date vs string,
  dữ liệu trùng lặp (duplicates), binary/base64 lớn, storage_key thiếu file vật lý, collection legacy.
"""

import os
import sys
import json
import re
import io
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, List, Optional

# Đảm bảo import được backend modules
ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

try:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

from backend.app.repositories.mongo_repository import MongoRepository
from backend.app.services.asset_store import STORAGE_ROOT
from backend.app.config import settings

def mask_id(val: Any) -> str:
    s = str(val or "")
    if len(s) <= 8:
        return s[:2] + "***"
    return s[:4] + "***" + s[-4:]

def mask_hash(val: Any) -> str:
    s = str(val or "")
    if len(s) <= 12:
        return s[:3] + "***"
    return s[:6] + "..." + s[-6:]

def is_iso_date_string(val: Any) -> bool:
    if not isinstance(val, str):
        return False
    # Check ISO 8601 pattern like 2026-09-14T...
    return bool(re.match(r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}", val))

def check_large_binary_or_base64(obj: Any, path: str = "") -> List[Dict[str, Any]]:
    findings = []
    if isinstance(obj, bytes):
        findings.append({"path": path, "type": "bytes", "size": len(obj)})
    elif isinstance(obj, str):
        if len(obj) > 500 and ("data:image/" in obj or "base64," in obj):
            findings.append({"path": path, "type": "base64_uri", "size": len(obj)})
        elif len(obj) > 10000 and re.match(r"^[A-Za-z0-9+/=]{10000,}$", obj):
            findings.append({"path": path, "type": "base64_raw", "size": len(obj)})
    elif isinstance(obj, dict):
        for k, v in obj.items():
            findings.extend(check_large_binary_or_base64(v, f"{path}.{k}" if path else k))
    elif isinstance(obj, list):
        for i, item in enumerate(obj[:20]): # sample first 20
            findings.extend(check_large_binary_or_base64(item, f"{path}[{i}]"))
    return findings

def audit_database() -> Dict[str, Any]:
    db = MongoRepository.get_db()
    all_colls = db.list_collection_names()
    
    # Phân loại collection
    core_chatbot_collections = [
        "assets", "jobs", "generated_images", "query_cache",
        "rag_events", "chat_logs", "admission_visuals", "huit_kb"
    ]
    legacy_or_test_collections = [c for c in all_colls if c not in core_chatbot_collections]

    report = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "database_name": db.name,
        "total_collections": len(all_colls),
        "core_collections": {},
        "legacy_or_test_collections": {},
        "summary": {
            "collections_with_validator": 0,
            "collections_without_validator": 0,
            "total_documents_analyzed": 0,
            "total_string_date_fields_found": 0,
            "duplicate_records_found": 0,
            "missing_physical_files": 0,
            "documents_with_large_binary": 0
        }
    }

    # Lấy thông tin validator cho tất cả collection
    coll_infos = {c["name"]: c for c in db.list_collections()}

    print(f"Bắt đầu phân tích {len(all_colls)} collections...", flush=True)

    for idx_num, coll_name in enumerate(all_colls, 1):
        is_core = coll_name in core_chatbot_collections
        coll = db[coll_name]
        try:
            doc_count = coll.estimated_document_count()
        except Exception:
            doc_count = coll.count_documents({})

        print(f"[{idx_num}/{len(all_colls)}] Đang quét {'[CORE]' if is_core else '[LEGACY/TEST]'} {coll_name} ({doc_count} docs)...", flush=True)

        c_info = coll_infos.get(coll_name, {})
        options = c_info.get("options", {})
        validator = options.get("validator")
        validation_level = options.get("validationLevel", "off" if not validator else "strict")
        validation_action = options.get("validationAction", "off" if not validator else "error")

        if validator:
            report["summary"]["collections_with_validator"] += 1
        else:
            report["summary"]["collections_without_validator"] += 1

        # Lấy indexes
        indexes_raw = list(coll.list_indexes())
        indexes = []
        for idx in indexes_raw:
            key_spec = list(idx.get("key", {}).items())
            indexes.append({
                "name": idx.get("name"),
                "key": key_spec,
                "unique": idx.get("unique", False),
                "sparse": idx.get("sparse", False),
                "ttl_expire_after_seconds": idx.get("expireAfterSeconds")
            })

        # Phân tích schema trên mẫu: core lấy tối đa 100 docs, non-core lấy 5 docs
        sample_size = min(doc_count, 100 if is_core else 5)
        docs = list(coll.find({}).limit(sample_size)) if sample_size > 0 else []
        report["summary"]["total_documents_analyzed"] += len(docs)

        # Thống kê trường và kiểu dữ liệu
        field_types = {}
        string_date_fields = set()
        missing_storage_files = []
        large_binary_docs = []

        for d in docs:
            # Check large binary / base64
            large_findings = check_large_binary_or_base64(d)
            if large_findings:
                large_binary_docs.append({
                    "doc_id": mask_id(d.get("_id") or d.get("id")),
                    "findings": large_findings
                })
                report["summary"]["documents_with_large_binary"] += 1

            # Check string dates & storage files
            for k, v in d.items():
                t_name = type(v).__name__
                field_types.setdefault(k, set()).add(t_name)
                if isinstance(v, str) and ("date" in k or "time" in k or k.endswith("_at")):
                    if is_iso_date_string(v):
                        string_date_fields.add(k)

            # Nếu là collection assets hoặc generated_images, kiểm tra storage_key
            if coll_name in ("assets", "generated_images"):
                s_key = d.get("storage_key")
                if s_key:
                    target_path = STORAGE_ROOT / s_key
                    if not target_path.exists():
                        missing_storage_files.append({
                            "id": mask_id(d.get("asset_id") or d.get("_id") or d.get("image_id")),
                            "storage_key": s_key
                        })
                        report["summary"]["missing_physical_files"] += 1

        # Đếm duplicates cho các collection quan trọng
        duplicate_details = {}
        if coll_name == "assets":
            # Group by content_hash
            p = coll.aggregate([
                {"$match": {"content_hash": {"$exists": True, "$ne": None, "$ne": ""}}},
                {"$group": {"_id": "$content_hash", "count": {"$sum": 1}, "ids": {"$push": "$asset_id"}}},
                {"$match": {"count": {"$gt": 1}}}
            ])
            dups = list(p)
            duplicate_details["content_hash"] = [{"hash": mask_hash(x["_id"]), "count": x["count"]} for x in dups]
            report["summary"]["duplicate_records_found"] += sum(x["count"] - 1 for x in dups)

            # Group by asset_id
            p_aid = coll.aggregate([
                {"$group": {"_id": "$asset_id", "count": {"$sum": 1}}},
                {"$match": {"count": {"$gt": 1}}}
            ])
            duplicate_details["asset_id"] = list(p_aid)

        elif coll_name == "jobs":
            p_jid = coll.aggregate([
                {"$group": {"_id": "$job_id", "count": {"$sum": 1}}},
                {"$match": {"count": {"$gt": 1}}}
            ])
            dups_job = list(p_jid)
            duplicate_details["job_id"] = dups_job
            report["summary"]["duplicate_records_found"] += sum(x["count"] - 1 for x in dups_job)

        elif coll_name == "generated_images":
            p_img = coll.aggregate([
                {"$match": {"content_hash": {"$exists": True, "$ne": None, "$ne": ""}}},
                {"$group": {"_id": "$content_hash", "count": {"$sum": 1}}},
                {"$match": {"count": {"$gt": 1}}}
            ])
            dups_img = list(p_img)
            duplicate_details["content_hash"] = [{"hash": mask_hash(x["_id"]), "count": x["count"]} for x in dups_img]
            report["summary"]["duplicate_records_found"] += sum(x["count"] - 1 for x in dups_img)

        elif coll_name == "query_cache":
            p_cache = coll.aggregate([
                {"$group": {"_id": "$cache_key", "count": {"$sum": 1}}},
                {"$match": {"count": {"$gt": 1}}}
            ])
            dups_cache = list(p_cache)
            duplicate_details["cache_key"] = [{"key": mask_hash(x["_id"]), "count": x["count"]} for x in dups_cache]
            report["summary"]["duplicate_records_found"] += sum(x["count"] - 1 for x in dups_cache)

        coll_data = {
            "name": coll_name,
            "document_count": doc_count,
            "has_validator": bool(validator),
            "validation_level": validation_level,
            "validation_action": validation_action,
            "indexes_count": len(indexes),
            "indexes": indexes,
            "field_types": {k: list(v) for k, v in field_types.items()},
            "string_date_fields": list(string_date_fields),
            "missing_storage_files_count": len(missing_storage_files),
            "missing_storage_files": missing_storage_files[:10],
            "large_binary_docs_count": len(large_binary_docs),
            "large_binary_docs_sample": large_binary_docs[:5],
            "duplicates": duplicate_details
        }

        report["summary"]["total_string_date_fields_found"] += len(string_date_fields)

        if is_core:
            report["core_collections"][coll_name] = coll_data
        else:
            report["legacy_or_test_collections"][coll_name] = coll_data

    return report

if __name__ == "__main__":
    print("Bắt đầu audit MongoDB Atlas ở chế độ READ-ONLY (an toàn tuyệt đối)...")
    try:
        report = audit_database()
        out_dir = ROOT_DIR / "audit_outputs"
        out_dir.mkdir(exist_ok=True)
        out_file = out_dir / "mongodb_readonly_audit_report.json"
        with open(out_file, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        print(f"Hoàn thành audit! Báo cáo đã lưu tại: {out_file}")
        
        # In tóm tắt kết quả
        print("\n=== TÓM TẮT KẾT QUẢ AUDIT MONGODB ATLAS ===")
        print(f"Tổng số collections: {report['total_collections']}")
        print(f"Collections có $jsonSchema validator: {report['summary']['collections_with_validator']}")
        print(f"Collections CHƯA CÓ validator: {report['summary']['collections_without_validator']}")
        print(f"Tổng số document đã kiểm tra: {report['summary']['total_documents_analyzed']}")
        print(f"Trường ngày giờ đang lưu dạng string (thay vì BSON Date): {report['summary']['total_string_date_fields_found']}")
        print(f"Dữ liệu trùng lặp tìm thấy: {report['summary']['duplicate_records_found']}")
        print(f"Số file vật lý thiếu trên disk: {report['summary']['missing_physical_files']}")
        print(f"Số document có binary/base64 lớn: {report['summary']['documents_with_large_binary']}")
        
        print("\n--- CHI TIẾT CÁC CORE COLLECTIONS ---")
        for name, data in report["core_collections"].items():
            idx_names = [i["name"] for i in data["indexes"]]
            unique_idxs = [i["name"] for i in data["indexes"] if i["unique"]]
            ttl_idxs = [i["name"] for i in data["indexes"] if i.get("ttl_expire_after_seconds") is not None]
            print(f"- [{name}]: {data['document_count']} docs | Validator: {'CÓ' if data['has_validator'] else 'CHƯA'} | Indexes: {idx_names} | Unique: {unique_idxs} | TTL: {ttl_idxs} | StringDates: {data['string_date_fields']}")
    except Exception as e:
        print(f"Lỗi khi chạy audit: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
