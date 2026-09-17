"""
storage_reconciliation.py
Công cụ đối soát lưu trữ (Storage Reconciliation & File Integrity Tool):
- Kiểm tra tính toàn vẹn giữa MongoDB (assets, artifacts, generated_images) và hệ thống lưu trữ vật lý (local filesystem / S3).
- Phát hiện:
  + Asset thiếu storage_key hoặc rỗng.
  + File vật lý bị mất trên đĩa/storage.
  + Sai lệch checksum SHA-256 hoặc file_size.
  + Asset không có logical reference hoặc logical record trỏ tới asset không tồn tại.
  + Physical blob mồ côi (orphan file) không có record trong MongoDB.
- Phục hồi:
  + Re-render deterministic cho 6 ảnh SVG từ scene trong generated_images sang file .svg chuẩn.
  + Re-render deterministic cho bảng tính Excel từ manifest trong artifacts sang file .xlsx chuẩn.
  + Chuẩn hóa 12 artifacts ở trạng thái unrendered manifest (gán blob_id = None trong artifacts, dọn placeholder rỗng trong assets).
  + Đánh dấu unavailable/corrupted nếu tài nguyên không thể phục hồi.
- An toàn:
  + Mặc định --dry-run.
  + Chế độ --apply tự động sao lưu collection trước khi cập nhật.
  + Xuất báo cáo chi tiết ra audit_outputs/.
"""
import hashlib
import io
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from scripts.migrations.common import (
    get_base_parser,
    get_migration_db,
    create_collection_backup,
    save_migration_report,
    logger,
)
from backend.app.services.image_service import render_svg
from backend.app.services.visual_service import export_visual_to_excel
from backend.app.storage.storage_adapter import get_storage_adapter


def compute_bytes_sha256(data: bytes) -> str:
    """Tính mã SHA-256 của chuỗi bytes."""
    return hashlib.sha256(data).hexdigest()


def collect_referenced_storage_keys(
    assets: List[Dict[str, Any]],
    images: List[Dict[str, Any]],
    admission_visuals: List[Dict[str, Any]],
) -> Set[str]:
    """Collect every physical key referenced by supported Mongo documents."""
    keys: Set[str] = set()
    for document, fields in (
        *((asset, ("storage_key", "preview_key")) for asset in assets),
        *((image, ("storage_key", "thumbnail_key", "preview_key")) for image in images),
        *((visual, ("storage_key",)) for visual in admission_visuals),
    ):
        for field in fields:
            value = document.get(field)
            if isinstance(value, str) and value.strip():
                keys.add(value.strip())
    return keys


def reconcile_storage(db, args) -> Dict[str, Any]:
    storage = get_storage_adapter()

    assets_col = db["assets"]
    artifacts_col = db["artifacts"]
    images_col = db["generated_images"]
    now_dt = datetime.now(timezone.utc)

    report = {
        "script": "storage_reconciliation",
        "started_at": now_dt.isoformat(),
        "mode": "apply" if args.apply else "dry-run",
        "storage_backend": type(storage).__name__,
        "storage_root": str(getattr(storage, "root_dir", "remote-object-storage")),
        "total_assets_scanned": 0,
        "valid_assets_count": 0,
        "repaired_svg_count": 0,
        "repaired_excel_count": 0,
        "unrendered_manifests_cleaned": 0,
        "unavailable_marked_count": 0,
        "checksum_corrected_count": 0,
        "size_corrected_count": 0,
        "dangling_logical_refs_count": 0,
        "orphan_files_count": 0,
        "errors": 0,
        "backups": {},
        "details": []
    }

    all_assets = list(assets_col.find({}))
    report["total_assets_scanned"] = len(all_assets)
    logger.info(f"Bắt đầu đối soát {len(all_assets)} assets trong collection 'assets'...")

    # Thu thập logical references
    artifact_blob_ids: Set[str] = set()
    for art in artifacts_col.find({}, {"_id": 1, "artifact_id": 1, "blob_id": 1}):
        b = art.get("blob_id")
        if b:
            artifact_blob_ids.add(b)

    all_images = list(images_col.find(
        {},
        {
            "_id": 1,
            "image_id": 1,
            "blob_id": 1,
            "storage_key": 1,
            "thumbnail_key": 1,
            "preview_key": 1,
        },
    ))
    admission_visuals = list(db["admission_visuals"].find({}, {"storage_key": 1}))
    image_blob_ids: Set[str] = set()
    for img in all_images:
        b = img.get("blob_id")
        if b:
            image_blob_ids.add(b)

    all_logical_blob_ids = artifact_blob_ids | image_blob_ids

    # Chuẩn bị danh sách thao tác
    assets_to_update = []
    artifacts_to_update = []
    images_to_update = []
    restorations = []
    placeholder_cleanups = []

    # 1. Quét từng asset
    for a in all_assets:
        aid = a.get("asset_id") or str(a.get("_id"))
        s_key = a.get("storage_key") or ""
        media_type = a.get("media_type") or ""

        # Trường hợp 1: Không có storage_key (hoặc chuỗi rỗng)
        if not s_key.strip():
            # Kiểm tra xem có phải unrendered manifest trong artifacts không
            art_match = artifacts_col.find_one({"blob_id": aid})
            if art_match:
                # Đây là artifact ở dạng manifest sơ khởi, chưa từng export ra file
                report["unrendered_manifests_cleaned"] += 1
                report["details"].append({
                    "asset_id": aid,
                    "action": "clean_unrendered_manifest",
                    "reason": "Artifact ở dạng JSON manifest sơ khởi, gán blob_id=null trong artifacts và gỡ bỏ asset placeholder rỗng"
                })
                placeholder_cleanups.append({
                    "artifact_doc_id": art_match["_id"],
                    "asset_doc_id": a["_id"],
                    "asset_id": aid,
                })
                continue
            else:
                report["unavailable_marked_count"] += 1
                report["details"].append({
                    "asset_id": aid,
                    "action": "mark_unavailable",
                    "reason": "Asset rỗng không có storage_key và không có manifest phục hồi"
                })
                assets_to_update.append((a["_id"], {"$set": {"status": "unavailable", "corrupted": True}}))
                continue

        # Trường hợp 2: Có storage_key -> Kiểm tra file vật lý
        if not storage.exists(s_key):
            # Thử phục hồi deterministic
            # A. Kiểm tra nếu là SVG image từ generated_images
            img_match = images_col.find_one({"$or": [{"blob_id": aid}, {"storage_key": s_key}]})
            if img_match and img_match.get("backend") == "svg" and img_match.get("scene"):
                try:
                    svg_xml = render_svg(img_match)
                    svg_bytes = svg_xml.encode("utf-8")
                    new_filename = f"svg_{img_match.get('image_id', aid)}.svg"
                    real_sha = compute_bytes_sha256(svg_bytes)
                    real_size = len(svg_bytes)

                    report["repaired_svg_count"] += 1
                    report["details"].append({
                        "asset_id": aid,
                        "action": "restore_svg_deterministic",
                        "storage_key": new_filename,
                        "size": real_size,
                        "sha256": real_sha
                    })

                    restorations.append({
                        "key": new_filename,
                        "content": svg_bytes,
                        "media_type": "image/svg+xml",
                        "asset_id": a["_id"],
                        "asset_update": {"$set": {
                            "storage_key": new_filename,
                            "media_type": "image/svg+xml",
                            "file_ext": "svg",
                            "file_size": real_size,
                            "checksum": real_sha,
                            "content_hash": real_sha,
                            "status": "ready",
                            "corrupted": False
                        }},
                        "image_id": img_match["_id"],
                        "image_update": {"$set": {
                            "storage_key": new_filename,
                            "byte_size": real_size,
                            "content_type": "image/svg+xml",
                            "status": "ready"
                        }},
                    })
                    continue
                except Exception as e:
                    logger.error(f"Lỗi render SVG deterministic cho {aid}: {e}")
                    report["errors"] += 1

            # B. Kiểm tra nếu là Artifact bảng tính có manifest đầy đủ
            art_match = artifacts_col.find_one({"$or": [{"blob_id": aid}, {"artifact_id": aid}]})
            if art_match and art_match.get("manifest", {}).get("content"):
                manifest = art_match["manifest"]
                try:
                    excel_buf = export_visual_to_excel(manifest)
                    excel_bytes = excel_buf.getvalue()
                    excel_filename = s_key if s_key.endswith(".xlsx") else f"asset_{aid}.xlsx"
                    real_sha = compute_bytes_sha256(excel_bytes)
                    real_size = len(excel_bytes)

                    report["repaired_excel_count"] += 1
                    report["details"].append({
                        "asset_id": aid,
                        "action": "restore_excel_deterministic",
                        "storage_key": excel_filename,
                        "size": real_size,
                        "sha256": real_sha
                    })

                    restorations.append({
                        "key": excel_filename,
                        "content": excel_bytes,
                        "media_type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        "asset_id": a["_id"],
                        "asset_update": {"$set": {
                            "storage_key": excel_filename,
                            "media_type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                            "file_ext": "xlsx",
                            "file_size": real_size,
                            "checksum": real_sha,
                            "status": "ready",
                            "corrupted": False
                        }},
                    })
                    continue
                except Exception as e:
                    logger.error(f"Lỗi render Excel deterministic cho {aid}: {e}")
                    report["errors"] += 1

            # C. Không thể phục hồi deterministic -> Đánh dấu unavailable/corrupted
            report["unavailable_marked_count"] += 1
            report["details"].append({
                "asset_id": aid,
                "storage_key": s_key,
                "action": "mark_unavailable",
                "reason": "File vật lý không tồn tại và không đủ manifest phục hồi"
            })
            assets_to_update.append((a["_id"], {"$set": {"status": "unavailable", "corrupted": True}}))
            if art_match:
                artifacts_to_update.append((art_match["_id"], {"$set": {"status": "unavailable"}}))
            continue

        # Trường hợp 3: File vật lý tồn tại -> Kiểm tra size và checksum
        actual_size = storage.get_size(s_key)
        actual_sha = storage.get_checksum(s_key)
        if actual_size is None or actual_sha is None:
            report["errors"] += 1
            report["details"].append({
                "asset_id": aid,
                "storage_key": s_key,
                "action": "metadata_read_failed",
            })
            continue

        up_fields = {}
        if a.get("file_size") != actual_size:
            up_fields["file_size"] = actual_size
            report["size_corrected_count"] += 1

        if a.get("checksum") != actual_sha:
            up_fields["checksum"] = actual_sha
            report["checksum_corrected_count"] += 1

        if not a.get("status") or a.get("corrupted"):
            up_fields["status"] = "ready"
            up_fields["corrupted"] = False

        if up_fields:
            assets_to_update.append((a["_id"], {"$set": up_fields}))
            report["details"].append({
                "asset_id": aid,
                "storage_key": s_key,
                "action": "correct_metadata",
                "corrected_fields": list(up_fields.keys())
            })
        else:
            report["valid_assets_count"] += 1

    # 2. Quét physical orphan files
    known_storage_keys = collect_referenced_storage_keys(
        all_assets,
        all_images,
        admission_visuals,
    )
    # Bổ sung các keys dự kiến restore
    for restoration in restorations:
        known_storage_keys.add(restoration["key"])

    orphan_files = []
    for key in storage.list_keys():
        if key not in known_storage_keys:
            orphan_files.append({
                "name": key,
                "size": storage.get_size(key),
                "sha256": storage.get_checksum(key),
            })

    report["orphan_files_count"] = len(orphan_files)
    report["orphan_files"] = orphan_files

    # 3. Quét Dangling Logical References
    for b_id in all_logical_blob_ids:
        if not any((a.get("asset_id") == b_id or a.get("_id") == b_id) for a in all_assets):
            report["dangling_logical_refs_count"] += 1
            report["details"].append({
                "blob_id": b_id,
                "action": "dangling_logical_ref_detected"
            })

    report["planned_operations"] = {
        "restorations": len(restorations),
        "placeholder_cleanups": len(placeholder_cleanups),
        "asset_updates": len(assets_to_update),
        "artifact_updates": len(artifacts_to_update),
        "image_updates": len(images_to_update),
    }
    report["preflight_passed"] = (
        report["errors"] == 0 and report["dangling_logical_refs_count"] == 0
    )

    # 4. Thực thi nếu --apply
    if args.apply:
        if not report["preflight_passed"]:
            logger.error("Storage reconciliation preflight không đạt; dừng trước mọi thay đổi.")
            report["completed_at"] = datetime.now(timezone.utc).isoformat()
            return report

        logger.info("Chế độ APPLY: Tiến hành ghi file vật lý và sao lưu MongoDB...")
        
        # Sao lưu collections
        report["backups"]["assets"] = create_collection_backup(db, "assets")
        report["backups"]["artifacts"] = create_collection_backup(db, "artifacts")
        report["backups"]["generated_images"] = create_collection_backup(db, "generated_images")

        # Ghi qua StorageAdapter và chỉ cập nhật Mongo sau khi xác minh object.
        for restoration in restorations:
            key = restoration["key"]
            content = restoration["content"]
            try:
                expected_sha = compute_bytes_sha256(content)
                storage.put(key, content, media_type=restoration["media_type"])
                if (
                    not storage.exists(key)
                    or storage.get_checksum(key) != expected_sha
                    or storage.get_size(key) != len(content)
                ):
                    raise RuntimeError("storage verification failed")
                assets_col.update_one(
                    {"_id": restoration["asset_id"]}, restoration["asset_update"]
                )
                if restoration.get("image_id") is not None:
                    images_col.update_one(
                        {"_id": restoration["image_id"]}, restoration["image_update"]
                    )
                logger.info(f"Đã ghi và xác minh file phục hồi: {key} ({len(content)} bytes)")
            except Exception as e:
                logger.error("Lỗi phục hồi storage key %s: %s", key, type(e).__name__)
                report["errors"] += 1

        # Cập nhật MongoDB. Với placeholder, gỡ logical reference thành công trước
        # rồi mới xóa physical record để không tạo dangling reference nếu bị gián đoạn.
        for cleanup in placeholder_cleanups:
            try:
                result = artifacts_col.update_one(
                    {
                        "_id": cleanup["artifact_doc_id"],
                        "blob_id": cleanup["asset_id"],
                    },
                    {"$set": {"blob_id": None}},
                )
                if result.matched_count != 1:
                    raise RuntimeError("artifact placeholder changed after preflight")
                assets_col.delete_one({"_id": cleanup["asset_doc_id"]})
            except Exception as e:
                logger.error(
                    "Lỗi dọn placeholder asset %s: %s",
                    cleanup["asset_id"],
                    type(e).__name__,
                )
                report["errors"] += 1

        for doc_id, u in assets_to_update:
            try:
                assets_col.update_one({"_id": doc_id}, u)
            except Exception as e:
                logger.error("Lỗi cập nhật asset metadata: %s", type(e).__name__)
                report["errors"] += 1
        for doc_id, u in artifacts_to_update:
            try:
                artifacts_col.update_one({"_id": doc_id}, u)
            except Exception as e:
                logger.error("Lỗi cập nhật artifact metadata: %s", type(e).__name__)
                report["errors"] += 1
        for doc_id, u in images_to_update:
            try:
                images_col.update_one({"_id": doc_id}, u)
            except Exception as e:
                logger.error("Lỗi cập nhật image metadata: %s", type(e).__name__)
                report["errors"] += 1

        missing_key_filter = {
            "$or": [
                {"storage_key": {"$exists": False}},
                {"storage_key": None},
                {"storage_key": ""},
            ]
        }
        post_assets = list(assets_col.find({}, {"asset_id": 1, "storage_key": 1}))
        missing_physical_after = [
            a.get("asset_id") or str(a.get("_id"))
            for a in post_assets
            if a.get("storage_key") and not storage.exists(a["storage_key"])
        ]
        report["post_apply"] = {
            "assets_without_storage_key": assets_col.count_documents(missing_key_filter),
            "assets_missing_physical_object": len(missing_physical_after),
            "missing_physical_asset_ids": missing_physical_after,
        }
        if (
            report["post_apply"]["assets_without_storage_key"]
            or report["post_apply"]["assets_missing_physical_object"]
        ):
            report["errors"] += 1

        logger.info("Cập nhật MongoDB hoàn tất thành công.")

    report["completed_at"] = datetime.now(timezone.utc).isoformat()
    return report


def main():
    parser = get_base_parser("Storage Reconciliation & File Integrity Tool")
    args = parser.parse_args()

    client, db = get_migration_db(args.database)
    try:
        report = reconcile_storage(db, args)
        save_migration_report(report, args.report_file)
        logger.info(
            f"Hoàn thành Storage Reconciliation ({report['mode']}): "
            f"Phục hồi {report['repaired_svg_count']} SVG, {report['repaired_excel_count']} Excel, "
            f"Dọn {report['unrendered_manifests_cleaned']} manifest rỗng, "
            f"Sửa {report['size_corrected_count']} size, {report['checksum_corrected_count']} checksum, "
            f"Orphans: {report['orphan_files_count']}, Lỗi: {report['errors']}."
        )
        if report["errors"] or not report["preflight_passed"]:
            raise SystemExit(2)
    finally:
        client.close()


if __name__ == "__main__":
    main()
