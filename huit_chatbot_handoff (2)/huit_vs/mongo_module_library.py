"""Versioned MongoDB aggregation modules for the HUIT chatbot.

Each document is deliberately JSON-compatible so it can be exported as one
file, stored in ``code_modules``, validated, and executed by the safe runner.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def module(
    module_id: str,
    description: str,
    source: str,
    pipeline: list[dict[str, Any]],
    *,
    risk: str = "read",
    targets: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "_id": module_id,
        "module_version": "1.0.0",
        "kind": "mongodb_aggregation",
        "enabled": True,
        "description": description,
        "source_collection": source,
        "risk_level": risk,
        "allowed_targets": targets or [],
        "parameters": {
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
        "public": {
            "node_data": {
                "jsonSchema": {
                    "type": "object",
                    "required": [
                        "_id", "module_version", "kind", "enabled",
                        "source_collection", "risk_level",
                    ],
                }
            }
        },
        "private": {
            "node_function": {
                "edge": [{"purpose": description, "pipeline": pipeline}]
            }
        },
    }


def group_count(field: str, label: str = "value") -> list[dict[str, Any]]:
    return [
        {"$group": {"_id": f"${field}", "count": {"$sum": 1}}},
        {"$project": {"_id": 0, label: "$_id", "count": 1}},
        {"$sort": {"count": -1}},
    ]


def text_topic(pattern: str) -> list[dict[str, Any]]:
    return [
        {"$match": {"$or": [
            {"title": {"$regex": pattern, "$options": "i"}},
            {"text": {"$regex": pattern, "$options": "i"}},
        ]}},
        {"$project": {
            "_id": 0, "title": 1, "text": 1, "source_url": 1,
            "category": 1, "year": 1, "major_code": 1,
        }},
        {"$limit": 100},
    ]


MODULES: list[dict[str, Any]] = [
    module("raw_valid_pages", "Trang thô có URL và nội dung", "raw_data", [
        {"$match": {"url": {"$type": "string", "$ne": ""}, "markdown": {"$type": "string", "$ne": ""}}},
        {"$project": {"_id": 0, "url": 1, "title": 1, "markdown": 1}},
        {"$limit": 200},
    ]),
    module("raw_domain_stats", "Thống kê nguồn tên miền", "raw_data", [
        {"$project": {"domain": {"$arrayElemAt": [{"$split": ["$url", "/"]}, 2]}}},
        *group_count("domain", "domain"),
    ]),
    module("raw_missing_fields", "Phát hiện trang thô thiếu trường", "raw_data", [
        {"$match": {"$or": [{"url": {"$in": [None, ""]}}, {"markdown": {"$in": [None, ""]}}]}},
        {"$project": {"url": 1, "title": 1, "has_text": {"$ne": ["$markdown", ""]}}},
        {"$limit": 200},
    ]),
    module("raw_duplicate_urls", "Phát hiện URL trùng", "raw_data", [
        {"$match": {"url": {"$type": "string", "$ne": ""}}},
        {"$group": {"_id": "$url", "count": {"$sum": 1}, "ids": {"$push": "$_id"}}},
        {"$match": {"count": {"$gt": 1}}},
        {"$sort": {"count": -1}},
    ]),
    module("raw_content_length_stats", "Thống kê độ dài dữ liệu thô", "raw_data", [
        {"$match": {"markdown": {"$type": "string"}}},
        {"$project": {"chars": {"$strLenCP": "$markdown"}}},
        {"$group": {"_id": None, "documents": {"$sum": 1}, "avg_chars": {"$avg": "$chars"}, "min_chars": {"$min": "$chars"}, "max_chars": {"$max": "$chars"}}},
        {"$project": {"_id": 0}},
    ]),
    module("kb_overview", "Tổng quan kho tri thức", "huit_kb", [
        {"$facet": {
            "totals": [{"$count": "documents"}],
            "categories": [*group_count("category", "category"), {"$limit": 30}],
            "years": [*group_count("year", "year"), {"$limit": 20}],
        }},
    ]),
    module("kb_category_stats", "Số tài liệu theo danh mục", "huit_kb", group_count("category", "category")),
    module("kb_year_stats", "Số tài liệu theo năm", "huit_kb", group_count("year", "year")),
    module("kb_major_catalog", "Danh mục mã ngành", "huit_kb", [
        {"$match": {"major_code": {"$type": "string", "$ne": ""}}},
        {"$group": {"_id": "$major_code", "titles": {"$addToSet": "$title"}, "documents": {"$sum": 1}}},
        {"$project": {"_id": 0, "major_code": "$_id", "titles": 1, "documents": 1}},
        {"$sort": {"major_code": 1}},
    ]),
    module("kb_duplicate_major_codes", "Mã ngành có nhiều tên khác nhau", "huit_kb", [
        {"$match": {"major_code": {"$type": "string", "$ne": ""}}},
        {"$group": {"_id": "$major_code", "titles": {"$addToSet": "$title"}}},
        {"$project": {"major_code": "$_id", "titles": 1, "title_count": {"$size": "$titles"}}},
        {"$match": {"title_count": {"$gt": 1}}},
        {"$project": {"_id": 0}},
    ]),
    module("kb_missing_source_urls", "Tài liệu thiếu URL nguồn", "huit_kb", [
        {"$match": {"$or": [{"source_url": {"$exists": False}}, {"source_url": {"$in": [None, ""]}}]}},
        {"$project": {"title": 1, "category": 1, "year": 1}},
        {"$limit": 200},
    ]),
    module("kb_embedding_health", "Thống kê kích thước embedding", "huit_kb", [
        {"$project": {"dimension": {"$cond": [{"$isArray": "$embedding"}, {"$size": "$embedding"}, 0]}}},
        *group_count("dimension", "dimension"),
    ]),
    module("kb_missing_embeddings", "Tài liệu thiếu embedding", "huit_kb", [
        {"$match": {"$or": [{"embedding": {"$exists": False}}, {"embedding": None}, {"embedding": {"$size": 0}}]}},
        {"$project": {"title": 1, "source_url": 1, "category": 1}},
        {"$limit": 200},
    ]),
    module("kb_chunk_length_distribution", "Phân bố độ dài đoạn tri thức", "huit_kb", [
        {"$match": {"text": {"$type": "string"}}},
        {"$project": {"bucket": {"$switch": {"branches": [
            {"case": {"$lt": [{"$strLenCP": "$text"}, 300]}, "then": "short"},
            {"case": {"$lt": [{"$strLenCP": "$text"}, 1200]}, "then": "medium"},
            {"case": {"$lt": [{"$strLenCP": "$text"}, 3000]}, "then": "long"},
        ], "default": "very_long"}}}},
        *group_count("bucket", "length_bucket"),
    ]),
    module("kb_duplicate_text", "Phát hiện nội dung tri thức trùng", "huit_kb", [
        {"$match": {"text": {"$type": "string", "$ne": ""}}},
        {"$group": {"_id": "$text", "count": {"$sum": 1}, "sources": {"$addToSet": "$source_url"}}},
        {"$match": {"count": {"$gt": 1}}},
        {"$project": {"_id": 0, "text_preview": {"$substrCP": ["$_id", 0, 180]}, "count": 1, "sources": 1}},
        {"$sort": {"count": -1}},
    ]),
    module("kb_duplicate_titles", "Phát hiện tiêu đề trùng", "huit_kb", [
        {"$match": {"title": {"$type": "string", "$ne": ""}}},
        {"$group": {"_id": "$title", "count": {"$sum": 1}, "sources": {"$addToSet": "$source_url"}}},
        {"$match": {"count": {"$gt": 1}}},
        {"$sort": {"count": -1}},
    ]),
    module("kb_tuition_facts", "Trích tài liệu học phí", "huit_kb", text_topic("học phí|tín chỉ")),
    module("kb_cutoff_facts", "Trích tài liệu điểm chuẩn và điểm sàn", "huit_kb", text_topic("điểm chuẩn|điểm sàn|xét tuyển")),
    module("kb_scholarship_facts", "Trích tài liệu học bổng", "huit_kb", text_topic("học bổng|miễn giảm")),
    module("kb_admissions_facts", "Trích tài liệu tuyển sinh", "huit_kb", text_topic("tuyển sinh|phương thức|tổ hợp")),
    module("kb_source_coverage", "Mức phủ theo URL nguồn", "huit_kb", [
        {"$match": {"source_url": {"$type": "string", "$ne": ""}}},
        {"$group": {"_id": "$source_url", "documents": {"$sum": 1}, "categories": {"$addToSet": "$category"}}},
        {"$project": {"_id": 0, "source_url": "$_id", "documents": 1, "categories": 1}},
        {"$sort": {"documents": -1}},
    ]),
    module("kb_unknown_year", "Tài liệu thiếu hoặc không rõ năm", "huit_kb", [
        {"$match": {"$or": [{"year": {"$exists": False}}, {"year": {"$in": [None, "", "unknown"]}}]}},
        {"$project": {"title": 1, "source_url": 1, "category": 1}},
        {"$limit": 200},
    ]),
    module("kb_quality_preview", "Chấm điểm chất lượng tài liệu (chỉ đọc)", "huit_kb", [
        {"$addFields": {"quality_score": {"$add": [
            {"$cond": [{"$gt": [{"$strLenCP": {"$ifNull": ["$text", ""]}}, 300]}, 35, 0]},
            {"$cond": [{"$ne": [{"$ifNull": ["$source_url", ""]}, ""]}, 25, 0]},
            {"$cond": [{"$ne": [{"$ifNull": ["$title", ""]}, ""]}, 20, 0]},
            {"$cond": [{"$isArray": "$embedding"}, 20, 0]},
        ]}}},
        {"$project": {"title": 1, "source_url": 1, "category": 1, "quality_score": 1}},
        {"$sort": {"quality_score": 1}},
        {"$limit": 200},
    ]),
    module("kb_faceted_audit", "Kiểm toán nhiều chiều kho tri thức", "huit_kb", [
        {"$facet": {
            "missing_title": [{"$match": {"title": {"$in": [None, ""]}}}, {"$count": "count"}],
            "missing_text": [{"$match": {"text": {"$in": [None, ""]}}}, {"$count": "count"}],
            "missing_source": [{"$match": {"source_url": {"$in": [None, ""]}}}, {"$count": "count"}],
            "missing_embedding": [{"$match": {"embedding": {"$exists": False}}}, {"$count": "count"}],
        }},
    ]),
    module("cache_overview", "Tổng quan bộ nhớ đệm câu trả lời", "query_cache", [
        {"$group": {"_id": None, "entries": {"$sum": 1}, "oldest": {"$min": "$updated_at"}, "newest": {"$max": "$updated_at"}}},
        {"$project": {"_id": 0}},
    ]),
    module("cache_expired_entries", "Liệt kê cache hết hạn", "query_cache", [
        {"$match": {"expires_at": {"$lt": "$$NOW"}}},
        {"$project": {"cache_key": 1, "question_clean": 1, "expires_at": 1}},
        {"$sort": {"expires_at": 1}},
        {"$limit": 200},
    ]),
    module("cache_source_count", "Phân bố số nguồn trong cache", "query_cache", [
        {"$project": {"source_count": {"$cond": [{"$isArray": "$sources"}, {"$size": "$sources"}, 0]}}},
        *group_count("source_count", "source_count"),
    ]),
    module("rag_intent_stats", "Số truy vấn theo ý định", "rag_events", group_count("intent", "intent")),
    module("rag_latency_stats", "Độ trễ RAG tổng hợp", "rag_events", [
        {"$match": {"elapsed_ms": {"$type": "number"}}},
        {"$group": {"_id": None, "requests": {"$sum": 1}, "avg_ms": {"$avg": "$elapsed_ms"}, "min_ms": {"$min": "$elapsed_ms"}, "max_ms": {"$max": "$elapsed_ms"}}},
        {"$project": {"_id": 0}},
    ]),
    module("rag_fallback_stats", "Tỉ lệ trả lời fallback", "rag_events", group_count("fallback", "fallback")),
    module("rag_cache_hit_stats", "Tỉ lệ cache hit", "rag_events", group_count("cached", "cached")),
    module("rag_model_stats", "Số truy vấn theo model", "rag_events", group_count("model", "model")),
    module("rag_kb_version_stats", "Số truy vấn theo phiên bản KB", "rag_events", group_count("kb_version", "kb_version")),
    module("rag_source_distribution", "Phân bố số nguồn mỗi câu trả lời", "rag_events", group_count("source_count", "source_count")),
    module("rag_daily_volume", "Lưu lượng RAG theo ngày", "rag_events", [
        {"$match": {"created_at": {"$type": "date"}}},
        {"$group": {"_id": {"$dateToString": {"format": "%Y-%m-%d", "date": "$created_at"}}, "requests": {"$sum": 1}}},
        {"$project": {"_id": 0, "day": "$_id", "requests": 1}},
        {"$sort": {"day": -1}},
    ]),
    module("module_registry_overview", "Tổng quan kho module", "code_modules", [
        {"$group": {"_id": {"kind": "$kind", "risk": "$risk_level", "enabled": "$enabled"}, "count": {"$sum": 1}}},
        {"$sort": {"count": -1}},
    ]),
    module("module_write_audit", "Liệt kê module có quyền ghi", "code_modules", [
        {"$match": {"risk_level": "write"}},
        {"$project": {"_id": 1, "module_version": 1, "enabled": 1, "allowed_targets": 1}},
        {"$sort": {"_id": 1}},
    ]),
    module("clean_data_preview", "Xem trước dữ liệu đã làm sạch", "test_clean_data", [
        {"$match": {"clean_text": {"$type": "string", "$ne": ""}}},
        {"$project": {"clean_text": 1, "source_url": 1, "page_title": 1, "char_count": 1}},
        {"$sort": {"char_count": -1}},
        {"$limit": 200},
    ]),
    module("write_clean_pages_v2", "Tạo collection trang sạch phiên bản 2", "raw_data", [
        {"$match": {"url": {"$type": "string", "$ne": ""}, "markdown": {"$type": "string", "$ne": ""}}},
        {"$project": {"_id": 0, "source_url": "$url", "page_title": "$title", "clean_text": {"$trim": {"input": "$markdown"}}, "char_count": {"$strLenCP": "$markdown"}}},
        {"$out": "test_clean_data_v2"},
    ], risk="write", targets=["test_clean_data_v2"]),
    module("write_categorized_pages_v2", "Tạo collection phân loại phiên bản 2", "test_clean_data", [
        {"$addFields": {"category": {"$switch": {"branches": [
            {"case": {"$regexMatch": {"input": "$clean_text", "regex": "học phí|tín chỉ", "options": "i"}}, "then": "tuition"},
            {"case": {"$regexMatch": {"input": "$clean_text", "regex": "điểm chuẩn|điểm sàn", "options": "i"}}, "then": "cutoff"},
            {"case": {"$regexMatch": {"input": "$clean_text", "regex": "học bổng", "options": "i"}}, "then": "scholarship"},
        ], "default": "general"}}}},
        {"$out": "test_categorized_data_v2"},
    ], risk="write", targets=["test_categorized_data_v2"]),
    module("write_quality_ranked_v2", "Tạo collection xếp hạng chất lượng phiên bản 2", "huit_kb", [
        {"$addFields": {"quality_score": {"$add": [
            {"$cond": [{"$gt": [{"$strLenCP": {"$ifNull": ["$text", ""]}}, 300]}, 40, 0]},
            {"$cond": [{"$ne": [{"$ifNull": ["$source_url", ""]}, ""]}, 30, 0]},
            {"$cond": [{"$isArray": "$embedding"}, 30, 0]},
        ]}}},
        {"$sort": {"quality_score": -1}},
        {"$out": "test_quality_ranked_v2"},
    ], risk="write", targets=["test_quality_ranked_v2"]),
]


def export_module_files(directory: str | Path) -> int:
    output = Path(directory)
    output.mkdir(parents=True, exist_ok=True)
    for item in MODULES:
        (output / f"{item['_id']}.json").write_text(
            json.dumps(item, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    return len(MODULES)

