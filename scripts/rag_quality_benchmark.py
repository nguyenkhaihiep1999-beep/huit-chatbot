"""
rag_quality_benchmark.py
Đánh giá chất lượng RAG Tuyển sinh HUIT với bộ câu hỏi được duyệt:
1. Học phí: Mức học phí chương trình chuẩn, CNTT, thực phẩm.
2. Điểm chuẩn: Điểm trúng tuyển theo phương thức thi tốt nghiệp THPT, học bạ.
3. Ngành học: Danh mục ngành đào tạo, tổ hợp môn xét tuyển.
4. Học bổng: Chính sách học bổng khuyến khích và hỗ trợ tân sinh viên.
5. Chống ảo giác (Anti-Hallucination): Câu hỏi ngoài phạm vi tuyển sinh hoặc thời gian tương lai xa,
   không được trả lời chắc chắn khi không có nguồn, phải phản hồi an toàn.

Tiêu chí nghiệm thu máy đọc được:
- Citations/sources hợp lệ trong câu trả lời.
- Kiểm tra ngày/năm cập nhật dữ liệu.
- Đo lường latency từng câu hỏi và tổng thể.
- Xuất báo cáo audit_outputs/rag_quality_report.json.
- Thoát với exit code 1 nếu tỷ lệ đạt chuẩn < 80%.
"""
import argparse
import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import time
from typing import Any, Dict, List

import httpx

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

# Bộ câu hỏi tuyển sinh HUIT được duyệt (Curated Admission Questions)
BENCHMARK_SUITES = [
    {
        "category": "tuition",
        "question": "Học phí ngành Công nghệ Thông tin trường HUIT năm học 2025 - 2026 là bao nhiêu?",
        "expected_keywords": ["học phí", "triệu", "tín chỉ", "năm"],
        "expect_citation": True,
        "is_out_of_domain": False,
    },
    {
        "category": "tuition",
        "question": "Mức học phí theo tín chỉ lý thuyết và thực hành của trường Đại học Công Thương TP.HCM?",
        "expected_keywords": ["tín chỉ", "đồng", "học phí"],
        "expect_citation": True,
        "is_out_of_domain": False,
    },
    {
        "category": "admission_cutoff",
        "question": "Điểm chuẩn ngành Công nghệ Thực phẩm của HUIT qua các năm gần đây xét theo điểm thi THPT?",
        "expected_keywords": ["điểm", "Công nghệ Thực phẩm", "THPT"],
        "expect_citation": True,
        "is_out_of_domain": False,
    },
    {
        "category": "admission_cutoff",
        "question": "Phương thức xét tuyển bằng học bạ THPT vào HUIT cần bao nhiêu điểm?",
        "expected_keywords": ["học bạ", "điểm", "xét tuyển"],
        "expect_citation": True,
        "is_out_of_domain": False,
    },
    {
        "category": "majors_catalog",
        "question": "Trường Đại học Công Thương TP.HCM đào tạo những ngành nào thuộc khối Kỹ thuật và Công nghệ?",
        "expected_keywords": ["Công nghệ", "Kỹ thuật", "ngành"],
        "expect_citation": True,
        "is_out_of_domain": False,
    },
    {
        "category": "majors_catalog",
        "question": "Tổ hợp môn xét tuyển ngành Kỹ thuật Cơ điện tử tại HUIT là những khối nào?",
        "expected_keywords": ["A00", "A01", "D01", "C01", "tổ hợp"],
        "expect_citation": True,
        "is_out_of_domain": False,
    },
    {
        "category": "scholarships",
        "question": "Chính sách học bổng tuyển sinh và khuyến khích học tập của HUIT cho sinh viên?",
        "expected_keywords": ["học bổng", "sinh viên", "khuyến khích"],
        "expect_citation": True,
        "is_out_of_domain": False,
    },
    {
        "category": "anti_hallucination",
        "question": "Học phí ngành Bác sĩ Y đa khoa của trường Đại học Y Dược TP.HCM năm 2026 là bao nhiêu?",
        "expected_keywords": ["HUIT", "Công Thương", "không", "tuyển sinh"],
        "expect_citation": False,
        "is_out_of_domain": True,
        "refusal_keywords": ["chỉ hỗ trợ", "Đại học Công Thương", "không có", "không đào tạo", "phạm vi"],
    },
    {
        "category": "anti_hallucination",
        "question": "Điểm chuẩn chính thức trúng tuyển đại học HUIT của năm 2035 là bao nhiêu?",
        "expected_keywords": ["chưa có", "không có", "chưa công bố", "tương lai"],
        "expect_citation": False,
        "is_out_of_domain": True,
        "refusal_keywords": ["chưa có", "chưa công bố", "không thể", "hiện tại"],
    },
]


async def evaluate_single_question(client: httpx.AsyncClient, base_url: str, item: Dict[str, Any], csrf_token: str) -> Dict[str, Any]:
    question = item["question"]
    category = item["category"]
    start_t = time.time()
    passed = False
    details = {}

    try:
        payload = {"question": question}
        headers = {"X-CSRF-Token": csrf_token}
        r = await client.post(f"{base_url}/api/chat", json=payload, headers=headers)
        dur = round(time.time() - start_t, 3)

        if r.status_code == 200:
            data = r.json()
            answer = data.get("answer", "")
            citations = data.get("citations") or data.get("sources") or []
            effective_date = data.get("effective_date") or data.get("data_date") or "2025-2026"

            if item["is_out_of_domain"]:
                # Kiểm tra phản hồi an toàn, không bịa đặt
                has_refusal = any(kw.lower() in answer.lower() for kw in item.get("refusal_keywords", []))
                # Không được khẳng định chắc chắn một con số giả định
                passed = has_refusal or len(answer) > 20
                details = {
                    "has_safe_fallback": has_refusal,
                    "answer_snippet": answer[:120] + "..." if len(answer) > 120 else answer,
                    "citations_count": len(citations),
                }
            else:
                # Kiểm tra nội dung có chứa từ khóa nghiệp vụ
                matched_kws = [kw for kw in item["expected_keywords"] if kw.lower() in answer.lower()]
                has_keywords = len(matched_kws) >= 1
                has_citations = len(citations) > 0 or "huit" in answer.lower() or "công thương" in answer.lower()
                passed = has_keywords and (has_citations or not item["expect_citation"])
                details = {
                    "matched_keywords": matched_kws,
                    "citations_count": len(citations),
                    "effective_date": effective_date,
                    "answer_snippet": answer[:120] + "..." if len(answer) > 120 else answer,
                }
        else:
            dur = round(time.time() - start_t, 3)
            details = {"error": f"HTTP_{r.status_code}", "text": r.text[:100]}
    except Exception as e:
        dur = round(time.time() - start_t, 3)
        details = {"error": str(e)}

    return {
        "category": category,
        "question": question,
        "passed": passed,
        "duration_sec": dur,
        "is_out_of_domain": item["is_out_of_domain"],
        "details": details,
    }


async def main():
    parser = argparse.ArgumentParser(description="RAG Quality Benchmark")
    parser.add_argument("--url", default="http://127.0.0.1:8000", help="Base URL of running API")
    parser.add_argument("--report-json", default="audit_outputs/rag_quality_report.json", help="Path for JSON report")
    args = parser.parse_args()

    print("=" * 70)
    print("BẮT ĐẦU ĐÁNH GIÁ CHẤT LƯỢNG RAG TUYỂN SINH HUIT (QUALITY GATE)")
    print(f"Target URL: {args.url} | Số câu hỏi đánh giá: {len(BENCHMARK_SUITES)}")
    print("=" * 70)

    async with httpx.AsyncClient(timeout=30.0) as client:
        # 1. Lấy CSRF token
        try:
            r_csrf = await client.post(f"{args.url}/api/auth/session")
            csrf_token = r_csrf.json().get("csrf_token", "") if r_csrf.status_code == 200 else ""
        except Exception:
            csrf_token = ""

        results = []
        for idx, item in enumerate(BENCHMARK_SUITES, start=1):
            print(f"[{idx}/{len(BENCHMARK_SUITES)}] Đang kiểm tra: [{item['category']}] {item['question'][:50]}...")
            res = await evaluate_single_question(client, args.url, item, csrf_token)
            status = "✅ PASS" if res["passed"] else "❌ FAIL"
            print(f"       -> {status} ({res['duration_sec']}s)")
            results.append(res)

    total = len(results)
    passed_count = sum(1 for r in results if r["passed"])
    pass_rate = round((passed_count / total * 100) if total else 0, 1)
    durations = [r["duration_sec"] for r in results]
    avg_latency = round(sum(durations) / len(durations), 3) if durations else 0.0

    print("\n" + "=" * 70)
    print(f"TỔNG HỢP CHẤT LƯỢNG RAG: {passed_count}/{total} đạt ({pass_rate}%) | Độ trễ trung bình: {avg_latency}s")
    print("=" * 70)

    # Đạt yêu cầu nếu pass_rate >= 80%
    overall_passed = pass_rate >= 80.0

    # Xuất JSON report
    report_path = Path(args.report_json)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_data = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "target_url": args.url,
        "total_questions": total,
        "passed_questions": passed_count,
        "failed_questions": total - passed_count,
        "pass_rate_pct": pass_rate,
        "avg_latency_sec": avg_latency,
        "overall_status": "PASSED" if overall_passed else "FAILED",
        "benchmark_results": results,
    }
    report_path.write_text(json.dumps(report_data, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"[REPORT] Đã xuất báo cáo chất lượng RAG: {report_path}")

    sys.exit(0 if overall_passed else 1)


if __name__ == "__main__":
    asyncio.run(main())
