#!/usr/bin/env python3
"""Small production-like audit for verified facts, tone, and citations."""

import json
from pathlib import Path

import rag_core


CASES = [
    ("tuition", "Học phí HUIT năm 2026 bao nhiêu?", ["1.100.000", "1.350.000"]),
    ("tuition-natural", "Nhà mình cần chuẩn bị khoảng bao nhiêu tiền để học HUIT?", ["143", "148"]),
    ("cutoff", "Điểm sàn HUIT 2026 là bao nhiêu?", ["16"]),
    ("law-cutoff", "Điểm sàn ngành Luật năm 2026?", ["20"]),
    ("admission", "Năm nay HUIT xét tuyển bằng những cách nào?", ["5"]),
    ("scholarship", "Có phải ngành nào cũng được giảm 50% học phí không?", ["không"]),
    ("ai-code", "Mã ngành AI ở HUIT?", ["7480107"]),
    ("it-code", "Cho mình mã ngành CNTT.", ["7480201"]),
    ("contact", "Cho mình xin hotline tuyển sinh HUIT.", ["096"]),
    ("outside-weather", "Thời tiết hôm nay thế nào?", ["ngoài"]),
    ("outside-code", "Viết code Python giúp mình.", ["ngoài"]),
    ("outside-food", "Chỉ mình cách nấu phở bò.", ["ngoài"]),
]


def main():
    rows = []
    for case_id, question, expected in CASES:
        response = rag_core.answer(question, use_cache=False)
        answer = response.get("answer", "")
        sources = response.get("sources", [])
        rows.append({
            "id": case_id,
            "question": question,
            "answer": answer,
            "expected_hit": all(
                rag_core._normalize(token) in rag_core._normalize(answer)
                for token in expected
            ),
            "natural": not any(marker in answer.lower() for marker in [
                "we need to answer",
                "must end with",
                "hệ thống sinh câu trả lời đang tạm thời",
                "thông tin liên quan được tìm thấy",
            ]),
            "official_sources_only": all(
                str(source.get("url", "")).startswith("https://ts.huit.edu.vn")
                for source in sources
            ),
            "source_count": len(sources),
            "fallback": response.get("meta", {}).get("fallback"),
        })
    summary = {
        "total": len(rows),
        "expected_hit_rate": sum(row["expected_hit"] for row in rows) / len(rows),
        "natural_rate": sum(row["natural"] for row in rows) / len(rows),
        "official_source_rate": (
            sum(row["official_sources_only"] for row in rows) / len(rows)
        ),
        "outside_without_sources": all(
            row["source_count"] == 0
            for row in rows
            if row["id"].startswith("outside-")
        ),
    }
    payload = {"summary": summary, "results": rows}
    output = Path(__file__).resolve().parent / "verified_chat_audit_results.json"
    output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
