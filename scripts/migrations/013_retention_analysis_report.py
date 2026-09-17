"""
013_retention_analysis_report.py
Script phân tích dung lượng và chính sách lưu trữ (Data Retention & Cleanup Analysis):
- Thống kê toàn bộ collections trong MongoDB Atlas: Core, Backup, Test, Temporary.
- Sử dụng lệnh collStats để tính toán dung lượng dữ liệu (dataSize), dung lượng lưu trữ đĩa (storageSize), và dung lượng index.
- Ước tính tổng dung lượng có thể thu hồi (reclaimable storage).
- Đề xuất chính sách lưu trữ chi tiết:
  + Core collections: Giữ nguyên vẹn, duy trì TTL index tự động cho query_cache.
  + Backup collections: Lưu trữ tối đa 30 ngày, sau đó có thể nén hoặc giải phóng.
  + Test collections: Đề xuất dọn dẹp sau khi nghiệm thu hoàn tất.
- Xuất báo cáo chi tiết ra file JSON và Markdown trong audit_outputs/.
- Tuyệt đối KHÔNG xóa dữ liệu (chỉ phân tích và báo cáo).
"""
from pathlib import Path
import sys
ROOT_DIR = Path(__file__).resolve().parent.parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Tuple

from scripts.migrations.common import (
    get_base_parser,
    get_migration_db,
    save_migration_report,
    logger,
)

CORE_COLLECTIONS = {
    "huit_kb",
    "rag_events",
    "jobs",
    "assets",
    "artifacts",
    "generated_images",
    "query_cache",
    "admission_visuals",
}


def classify_collection(name: str) -> str:
    """Phân loại collection theo mục đích sử dụng."""
    if name in CORE_COLLECTIONS:
        return "core"
    if "backup" in name.lower() or name.startswith("bak_"):
        return "backup"
    if "test" in name.lower() or "tmp" in name.lower() or name.startswith("temp_"):
        return "test_or_temp"
    return "other"


def format_bytes(b: int) -> str:
    """Định dạng byte sang đơn vị KB, MB dễ đọc."""
    if b < 1024:
        return f"{b} B"
    elif b < 1024 * 1024:
        return f"{round(b / 1024, 2)} KB"
    else:
        return f"{round(b / (1024 * 1024), 2)} MB"


def analyze_retention(db) -> Dict[str, Any]:
    col_names = db.list_collection_names()
    logger.info(f"Đang phân tích {len(col_names)} collections trong cơ sở dữ liệu '{db.name}'...")

    categories = {
        "core": [],
        "backup": [],
        "test_or_temp": [],
        "other": []
    }

    total_storage_bytes = 0
    total_data_bytes = 0
    total_index_bytes = 0
    total_doc_count = 0

    reclaimable_storage_bytes = 0
    reclaimable_doc_count = 0

    for name in sorted(col_names):
        cat = classify_collection(name)
        try:
            stats = db.command("collStats", name)
            doc_count = stats.get("count", 0)
            data_size = stats.get("size", 0)
            storage_size = stats.get("storageSize", 0)
            total_idx_size = stats.get("totalIndexSize", 0)
            avg_obj_size = round(stats.get("avgObjSize", 0), 2)
        except Exception as e:
            logger.warning(f"Không thể lấy stats cho collection '{name}': {e}")
            doc_count = db[name].estimated_document_count()
            data_size = 0
            storage_size = 0
            total_idx_size = 0
            avg_obj_size = 0

        info = {
            "name": name,
            "category": cat,
            "doc_count": doc_count,
            "data_size_bytes": data_size,
            "data_size_formatted": format_bytes(data_size),
            "storage_size_bytes": storage_size,
            "storage_size_formatted": format_bytes(storage_size),
            "index_size_bytes": total_idx_size,
            "index_size_formatted": format_bytes(total_idx_size),
            "avg_obj_size_bytes": avg_obj_size
        }

        categories[cat].append(info)
        total_storage_bytes += storage_size
        total_data_bytes += data_size
        total_index_bytes += total_idx_size
        total_doc_count += doc_count

        if cat in ("backup", "test_or_temp"):
            reclaimable_storage_bytes += storage_size + total_idx_size
            reclaimable_doc_count += doc_count

    report = {
        "script": "013_retention_analysis_report",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "database": db.name,
        "summary": {
            "total_collections": len(col_names),
            "core_collections_count": len(categories["core"]),
            "backup_collections_count": len(categories["backup"]),
            "test_collections_count": len(categories["test_or_temp"]),
            "other_collections_count": len(categories["other"]),
            "total_documents": total_doc_count,
            "total_data_size": format_bytes(total_data_bytes),
            "total_storage_size": format_bytes(total_storage_bytes),
            "total_index_size": format_bytes(total_index_bytes),
            "estimated_reclaimable_storage": format_bytes(reclaimable_storage_bytes),
            "estimated_reclaimable_documents": reclaimable_doc_count
        },
        "retention_policies": [
            {
                "category": "core",
                "policy": "Lưu trữ dài hạn bền vững. TTL index 24h tự động cho query_cache. Deduplication SHA-256 cho assets.",
                "action": "Duy trì bảo vệ nguyên vẹn"
            },
            {
                "category": "backup",
                "policy": "Sao lưu phòng hộ trước khi áp dụng migration. Sau khi nghiệm thu thành công và ổn định 30 ngày, có thể lưu trữ lạnh (cold archive) hoặc dọn dẹp.",
                "action": "Giữ nguyên cho đến khi có xác nhận nghiệm thu từ quản trị viên"
            },
            {
                "category": "test_or_temp",
                "policy": "Tạo trong quá trình phát triển và kiểm thử tự động.",
                "action": "Có thể giải phóng an toàn khi hệ thống bước vào giai đoạn production"
            }
        ],
        "categories": categories
    }

    return report


def save_markdown_summary(report: Dict[str, Any], filepath: Path):
    """Xuất bảng tóm tắt định dạng Markdown dễ đọc."""
    summary = report["summary"]
    lines = [
        f"# Báo Cáo Phân Tích Dung Lượng & Chính Sách Lưu Trữ ({report['database']})",
        f"**Thời gian thực hiện:** {report['timestamp']}\n",
        "## 1. Tổng Quan Hệ Thống Lưu Trữ",
        f"- **Tổng số collection:** {summary['total_collections']}",
        f"- **Core collections:** {summary['core_collections_count']}",
        f"- **Backup collections:** {summary['backup_collections_count']}",
        f"- **Test / Temp collections:** {summary['test_collections_count']}",
        f"- **Tổng số documents:** {summary['total_documents']:,}",
        f"- **Dung lượng lưu trữ đĩa:** {summary['total_storage_size']}",
        f"- **Dung lượng index:** {summary['total_index_size']}",
        f"- **Ước tính dung lượng có thể thu hồi:** {summary['estimated_reclaimable_storage']} ({summary['estimated_reclaimable_documents']} documents)\n",
        "## 2. Chi Tiết Các Bộ Sưu Tập",
        "| Collection | Loại | Số Docs | Data Size | Storage Size | Index Size |",
        "| :--- | :--- | :--- | :--- | :--- | :--- |"
    ]

    for cat_name, col_list in report["categories"].items():
        for item in col_list:
            lines.append(
                f"| `{item['name']}` | {item['category']} | {item['doc_count']:,} | {item['data_size_formatted']} | {item['storage_size_formatted']} | {item['index_size_formatted']} |"
            )

    lines.extend([
        "\n## 3. Khuyến Nghị Chính Sách Lưu Trữ",
        "1. **Bảo tồn Core Collections:** Không xóa bất kỳ bản ghi nào trong 8 collection cốt lõi.",
        "2. **Quản lý Backup Collections:** 13 collection backup tạo ra trong các đợt di chuyển dữ liệu đang bảo toàn trạng thái trước migration. Sau khi phiên bản production vận hành ổn định 30 ngày, có thể chạy lệnh dọn dẹp có kiểm soát.",
        "3. **An toàn Test Collections:** 6 collection thử nghiệm có thể thu hồi khi cần tối ưu hóa hạn mức đĩa MongoDB Atlas M0/Free Tier."
    ])

    filepath.write_text("\n".join(lines), encoding="utf-8")
    logger.info(f"Đã lưu báo cáo Markdown tại: {filepath.resolve()}")


def main():
    parser = get_base_parser("Script 013: Phân tích dung lượng & chính sách lưu trữ MongoDB Atlas")
    args = parser.parse_args()

    client, db = get_migration_db(args.database)
    try:
        report = analyze_retention(db)
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        out_dir = Path("audit_outputs")
        out_dir.mkdir(parents=True, exist_ok=True)

        json_file = out_dir / f"013_retention_analysis_{timestamp}_report.json"
        md_file = out_dir / f"013_retention_analysis_{timestamp}_report.md"

        save_migration_report(report, str(json_file))
        save_markdown_summary(report, md_file)

        logger.info(
            f"Hoàn thành phân tích lưu trữ: {report['summary']['total_collections']} collections, "
            f"Dung lượng lưu trữ: {report['summary']['total_storage_size']}, "
            f"Ước tính có thể thu hồi: {report['summary']['estimated_reclaimable_storage']}."
        )
    finally:
        client.close()


if __name__ == "__main__":
    main()
