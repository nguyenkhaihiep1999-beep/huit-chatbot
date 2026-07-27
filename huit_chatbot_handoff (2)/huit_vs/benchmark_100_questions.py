#!/usr/bin/env python3
"""End-to-end benchmark: 80 HUIT questions + 20 out-of-scope questions."""

from __future__ import annotations

import argparse
import copy
import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import rag_core


TOPICS = [
    ("ai", "major", ["7480107"], [
        "Mã ngành Trí tuệ nhân tạo HUIT là gì?",
        "Cho mình xin mã ngành AI của HUIT.",
        "Trí tuệ nhân tạo ở HUIT mang mã ngành bao nhiêu?",
        "Tra cứu ngành AI HUIT giúp mình.",
        "Ngành trí tuệ nhân tạo xét tuyển thế nào?",
        "HUIT có đào tạo AI không, mã ngành gì?",
        "Mình muốn học AI tại HUIT, cho thông tin tuyển sinh.",
        "7480107 là ngành nào của HUIT?",
    ]),
    ("it", "major", ["7480201"], [
        "Mã ngành Công nghệ thông tin HUIT?",
        "CNTT tại HUIT có mã bao nhiêu?",
        "Cho em thông tin tuyển sinh ngành Công nghệ thông tin.",
        "Ngành IT HUIT xét tuyển như thế nào?",
        "HUIT có ngành CNTT không?",
        "Tra cứu mã ngành IT của trường.",
        "7480201 là ngành gì?",
        "Em muốn đăng ký Công nghệ thông tin HUIT.",
    ]),
    ("security", "major", ["7480202"], [
        "Mã ngành An toàn thông tin HUIT?",
        "An toàn thông tin tại HUIT có mã bao nhiêu?",
        "Cho thông tin tuyển sinh ngành an ninh mạng HUIT.",
        "HUIT có đào tạo An toàn thông tin không?",
        "Tra cứu ngành ATTT của HUIT.",
        "7480202 là ngành nào?",
        "Em muốn học bảo mật tại HUIT.",
        "Ngành An toàn thông tin xét tuyển ra sao?",
    ]),
    ("data", "major", ["7460108"], [
        "Mã ngành Khoa học dữ liệu HUIT?",
        "Data Science HUIT mang mã ngành gì?",
        "Cho thông tin ngành Khoa học dữ liệu.",
        "HUIT có đào tạo khoa học dữ liệu không?",
        "Tra cứu ngành data của HUIT.",
        "7460108 là ngành nào?",
        "Em muốn học Data Science tại HUIT.",
        "Ngành Khoa học dữ liệu xét tuyển thế nào?",
    ]),
    ("food", "major", ["7540101"], [
        "Mã ngành Công nghệ thực phẩm HUIT?",
        "Công nghệ thực phẩm ở HUIT học bao lâu?",
        "Cho thông tin tuyển sinh ngành Công nghệ thực phẩm.",
        "HUIT có ngành thực phẩm không?",
        "Tra cứu ngành CNTP của HUIT.",
        "7540101 là ngành gì?",
        "Em muốn học Công nghệ thực phẩm.",
        "Ngành Công nghệ thực phẩm xét tuyển ra sao?",
    ]),
    ("marketing", "major", ["marketing"], [
        "Ngành Marketing HUIT có mã gì?",
        "Cho thông tin tuyển sinh Marketing.",
        "HUIT có đào tạo marketing không?",
        "Marketing ở HUIT xét tuyển thế nào?",
        "Tra cứu ngành tiếp thị của HUIT.",
        "Em muốn đăng ký Marketing HUIT.",
        "Ngành marketing học tại khoa nào?",
        "Thông tin ngành Marketing trường Công Thương.",
    ]),
    ("logistics", "major", ["logistics"], [
        "Thông tin ngành Logistics HUIT?",
        "HUIT có đào tạo logistics không?",
        "Cho mã ngành Logistics và quản lý chuỗi cung ứng.",
        "Logistics HUIT xét tuyển như thế nào?",
        "Em muốn học logistics tại trường Công Thương.",
        "Tra cứu ngành chuỗi cung ứng HUIT.",
        "Ngành Logistics có những tổ hợp nào?",
        "Tư vấn tuyển sinh Logistics giúp mình.",
    ]),
    ("tuition", "tuition", ["học phí"], [
        "Học phí HUIT khoảng bao nhiêu?",
        "Một học kỳ ở HUIT đóng bao nhiêu tiền?",
        "Đơn giá tín chỉ HUIT là bao nhiêu?",
        "Cho em hỏi tiền học trường Công Thương.",
        "Học phí HUIT có ổn định toàn khóa không?",
        "Một năm học HUIT tốn khoảng bao nhiêu?",
        "Học phí năm 2026 đã có chính thức chưa?",
        "Chi phí học ngành CNTT tại HUIT?",
    ]),
    ("cutoff", "cutoff", ["16"], [
        "Điểm sàn HUIT năm 2025 bao nhiêu?",
        "Mức điểm nhận hồ sơ HUIT 2025?",
        "Bao nhiêu điểm thì được xét tuyển HUIT?",
        "Cho em hỏi điểm sàn trường Công Thương.",
        "Điểm xét tuyển HUIT năm 2025 là mấy?",
        "HUIT nhận hồ sơ từ bao nhiêu điểm?",
        "16 điểm có nộp HUIT được không?",
        "Tra cứu điểm sàn tuyển sinh HUIT.",
    ]),
    ("scholarship", "scholarship", ["50%"], [
        "HUIT có học bổng 50% học phí không?",
        "Chính sách học bổng HUIT thế nào?",
        "Tân sinh viên có được giảm học phí không?",
        "Cho thông tin học bổng học kỳ đầu.",
        "HUIT hỗ trợ học phí cho sinh viên thế nào?",
        "Học bổng tuyển sinh của trường Công Thương?",
        "Có chương trình miễn giảm 50 phần trăm không?",
        "Điều kiện nhận học bổng HUIT?",
    ]),
]

OUT_OF_SCOPE = [
    "Thời tiết TP.HCM hôm nay thế nào?",
    "Viết code Python sắp xếp một danh sách.",
    "Giải bài tập toán 2x + 3 = 9.",
    "Tin bóng đá mới nhất hôm nay?",
    "Chơi game đoán số với tôi.",
    "Ai là tổng thống Hoa Kỳ?",
    "Giá Bitcoin hôm nay bao nhiêu?",
    "Viết cho tôi một bài thơ tình.",
    "Cách nấu phở bò ngon?",
    "Dịch câu hello world sang tiếng Pháp.",
    "Tư vấn mua laptop gaming.",
    "Kể một câu chuyện kinh dị.",
    "Dự báo thời tiết Hà Nội ngày mai.",
    "Viết JavaScript tạo máy tính.",
    "Giải phương trình bậc hai.",
    "Kết quả trận bóng đá tối qua?",
    "Hướng dẫn chơi Liên Minh Huyền Thoại.",
    "Chứng khoán nào nên mua?",
    "Cho thực đơn giảm cân 7 ngày.",
    "Ai phát minh ra bóng đèn?",
]


def normalized_contains(text: str, expected: list[str]) -> bool:
    value = rag_core._normalize(text)
    return all(rag_core._normalize(token) in value for token in expected)


def raw_vector_docs(query: str, limit: int = 5) -> list[dict]:
    rag_core._init()
    if not rag_core._embedder:
        return []
    vector = list(rag_core._embedder.embed([query]))[0].tolist()
    pipeline = copy.deepcopy(rag_core._retrieval_pipeline)
    for stage in pipeline:
        spec = stage.get("$vectorSearch")
        if spec:
            spec["queryVector"] = vector
            spec["limit"] = limit
            spec["numCandidates"] = 200
    return list(rag_core._mongo[rag_core.DB][rag_core.COLL].aggregate(pipeline))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="benchmark_100_results.json")
    parser.add_argument("--retrieval-only", action="store_true")
    args = parser.parse_args()
    cases = [
        {
            "id": f"{topic}-{index + 1}",
            "scope": "huit",
            "category": category,
            "query": query,
            "expected": expected,
        }
        for topic, category, expected, queries in TOPICS
        for index, query in enumerate(queries)
    ]
    cases += [
        {
            "id": f"oos-{index + 1}",
            "scope": "outside",
            "category": "outside",
            "query": query,
            "expected": [],
        }
        for index, query in enumerate(OUT_OF_SCOPE)
    ]
    assert len(cases) == 100

    output = HERE / args.output
    results = []
    for index, case in enumerate(cases, 1):
        started = time.perf_counter()
        row = {**case}
        try:
            if case["scope"] == "huit":
                vector_docs = raw_vector_docs(case["query"])
                hybrid_docs = rag_core.retrieve(case["query"], top_k=5)
                vector_text = " ".join(
                    f"{doc.get('title', '')} {doc.get('text', '')}"
                    for doc in vector_docs
                )
                hybrid_text = " ".join(
                    f"{doc.get('title', '')} {doc.get('text', '')}"
                    for doc in hybrid_docs
                )
                row["vector_hit"] = normalized_contains(vector_text, case["expected"])
                row["hybrid_hit"] = normalized_contains(hybrid_text, case["expected"])
                row["vector_sources"] = [
                    str(doc.get("title", ""))[:120] for doc in vector_docs
                ]
                row["hybrid_sources"] = [
                    str(doc.get("title", ""))[:120] for doc in hybrid_docs
                ]
                if not args.retrieval_only:
                    response = rag_core.answer(case["query"], use_cache=False)
                    row["answer_hit"] = normalized_contains(
                        response.get("answer", ""), case["expected"]
                    )
                    row["answer"] = response.get("answer", "")
                    row["source_count"] = len(response.get("sources", []))
                    row["fallback"] = bool(response.get("meta", {}).get("fallback"))
            else:
                response = rag_core.answer(case["query"], use_cache=False)
                answer_norm = rag_core._normalize(response.get("answer", ""))
                row["guardrail_hit"] = (
                    "chuyen trach tuyen sinh huit" in answer_norm
                    or "chi co the tu van" in answer_norm
                )
                row["no_fake_sources"] = len(response.get("sources", [])) == 0
                row["answer"] = response.get("answer", "")
        except Exception as exc:
            row["error"] = str(exc)
        row["elapsed_seconds"] = round(time.perf_counter() - started, 2)
        results.append(row)
        output.write_text(
            json.dumps({"results": results}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"[{index:03d}/100] {case['id']} {row.get('error', 'OK')}", flush=True)

    huit = [row for row in results if row["scope"] == "huit"]
    outside = [row for row in results if row["scope"] == "outside"]
    summary = {
        "total": len(results),
        "huit_questions": len(huit),
        "outside_questions": len(outside),
        "vector_hit_rate": round(sum(bool(r.get("vector_hit")) for r in huit) / len(huit), 4),
        "hybrid_hit_rate": round(sum(bool(r.get("hybrid_hit")) for r in huit) / len(huit), 4),
        "answer_hit_rate": (
            None if args.retrieval_only
            else round(sum(bool(r.get("answer_hit")) for r in huit) / len(huit), 4)
        ),
        "out_of_scope_guardrail_rate": round(
            sum(bool(r.get("guardrail_hit")) for r in outside) / len(outside), 4
        ),
        "out_of_scope_no_fake_source_rate": round(
            sum(bool(r.get("no_fake_sources")) for r in outside) / len(outside), 4
        ),
        "fallback_rate": (
            None if args.retrieval_only
            else round(sum(bool(r.get("fallback")) for r in huit) / len(huit), 4)
        ),
        "error_count": sum("error" in row for row in results),
        "average_seconds": round(
            sum(row["elapsed_seconds"] for row in results) / len(results), 2
        ),
    }
    output.write_text(
        json.dumps({"summary": summary, "results": results}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
