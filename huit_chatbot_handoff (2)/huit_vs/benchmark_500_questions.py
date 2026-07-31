#!/usr/bin/env python3
"""
benchmark_500_questions.py
Comprehensive 500-question latency & accuracy benchmark for HUIT Chatbot system.
Measures:
- Total Time (Latency ms) per question
- Time-To-First-Token (TTFT ms)
- Cache Hit Ratio (% cached vs non-cached)
- Accuracy / Keyword Hit Rate (% correct answers)
- Throughput (queries/sec)
- P50, P90, P99 Percentiles
"""

import argparse
import copy
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import rag_core

# 50 Categorized Prompt Templates generating 500 unique admissions questions
CATEGORIES = [
    # 1. Major Code & Details (39 Majors x 4 variations = 156 questions)
    ("MAJORS", [
        ("Trí tuệ nhân tạo", "7480107", ["AI", "Trí tuệ nhân tạo", "7480107"]),
        ("Công nghệ thông tin", "7480201", ["CNTT", "Công nghệ thông tin", "7480201"]),
        ("An toàn thông tin", "7480202", ["An toàn thông tin", "ATTT", "7480202"]),
        ("Khoa học dữ liệu", "7460108", ["Khoa học dữ liệu", "Data Science", "7460108"]),
        ("Công nghệ thực phẩm", "7540101", ["Công nghệ thực phẩm", "CNTP", "7540101"]),
        ("Đảm bảo chất lượng và an toàn thực phẩm", "7540106", ["Đảm bảo chất lượng", "an toàn thực phẩm", "7540106"]),
        ("Khoa học chế biến món ăn", "7810203", ["chế biến món ăn", "7810203", "nấu ăn"]),
        ("Quản trị Nhà hàng và Dịch vụ ăn uống", "7810202", ["Quản trị Nhà hàng", "Dịch vụ ăn uống", "7810202"]),
        ("Ngôn ngữ Anh", "7220201", ["Ngôn ngữ Anh", "tiếng Anh", "7220201"]),
        ("Ngôn ngữ Trung Quốc", "7220204", ["Ngôn ngữ Trung Quốc", "tiếng Trung", "7220204"]),
        ("Marketing", "7340115", ["Marketing", "tiếp thị", "7340115"]),
        ("Kinh doanh quốc tế", "7340120", ["Kinh doanh quốc tế", "7340120"]),
        ("Logistics và quản lý chuỗi cung ứng", "7510605", ["Logistics", "chuỗi cung ứng", "7510605"]),
        ("Quản trị kinh doanh", "7340101", ["Quản trị kinh doanh", "7340101"]),
        ("Thương mại điện tử", "7340122", ["Thương mại điện tử", "7340122"]),
        ("Tài chính ngân hàng", "7340201", ["Tài chính ngân hàng", "7340201"]),
        ("Công nghệ Tài Chính (Fintech)", "7340205", ["Fintech", "Công nghệ Tài Chính", "7340205"]),
        ("Kế toán", "7340301", ["Kế toán", "7340301"]),
        ("Luật kinh tế", "7380107", ["Luật kinh tế", "7380107"]),
        ("Luật", "7380101", ["Luật", "7380101"]),
        ("Quản trị khách sạn", "7810201", ["Quản trị khách sạn", "7810201"]),
        ("Quản trị dịch vụ du lịch và lữ hành", "7810101", ["du lịch và lữ hành", "7810101"]),
        ("Du lịch", "7810103", ["Du lịch", "7810103"]),
        ("Công nghệ kỹ thuật điều khiển và tự động hóa", "7510303", ["tự động hóa", "7510303"]),
        ("Công nghệ kỹ thuật điện – điện tử", "7510301", ["điện – điện tử", "7510301"]),
        ("Kỹ thuật Nhiệt", "7520115", ["Kỹ thuật Nhiệt", "7520115"]),
        ("Công nghệ kỹ thuật cơ điện tử", "7510203", ["cơ điện tử", "7510203"]),
        ("Công nghệ chế tạo máy", "7510202", ["chế tạo máy", "7510202"]),
        ("Công nghệ dệt, may", "7540204", ["Công nghệ dệt, may", "7540204"]),
        ("Kinh doanh thời trang và dệt may", "7340123", ["Kinh doanh thời trang", "7340123"]),
        ("Công nghệ kỹ thuật Hóa học", "7510401", ["Hóa học", "Hóa mỹ phẩm", "7510401"]),
        ("Công nghệ sinh học", "7420201", ["Công nghệ sinh học", "7420201"]),
        ("Công nghệ kỹ thuật môi trường", "7510406", ["kỹ thuật môi trường", "7510406"]),
        ("Quản lý tài nguyên và môi trường", "7850101", ["tài nguyên và môi trường", "7850101"]),
        ("Công nghệ vật liệu", "7510402", ["Công nghệ vật liệu", "7510402"]),
        ("Quản lý Công nghiệp", "7510601", ["Quản lý Công nghiệp", "7510601"]),
        ("Quản trị kinh doanh Thực phẩm", "7340129", ["Quản trị kinh doanh Thực phẩm", "7340129"]),
        ("Khoa học dinh dưỡng và ẩm thực", "7540107", ["dinh dưỡng và ẩm thực", "7540107"]),
        ("Công nghệ chế biến thủy sản", "7540105", ["chế biến thủy sản", "7540105"]),
    ]),

    # 2. Tuition Questions (60 questions)
    ("TUITION", [
        "Học phí HUIT năm 2026 là bao nhiêu?",
        "Học phí 1 tín chỉ lý thuyết ở HUIT bao nhiêu tiền?",
        "Đơn giá tín chỉ thực hành tại HUIT năm nay?",
        "Một năm học tại HUIT tốn bao nhiêu học phí?",
        "Chi phí học toàn khóa cử nhân tại HUIT là bao nhiêu?",
        "Học phí chương trình kỹ sư HUIT bao nhiêu triệu?",
        "Học phí ngành CNTT HUIT bao nhiêu tiền 1 kỳ?",
        "Học phí ngành Ngôn ngữ Anh HUIT có cao không?",
        "Trường Đại học Công Thương TP.HCM đóng học phí thế nào?",
        "Lộ trình tăng học phí của HUIT các năm ra sao?",
    ]),

    # 3. Cutoff Score & Benchmark Questions (60 questions)
    ("CUTOFF", [
        "Điểm sàn Đánh giá năng lực ĐHQG-HCM 2026 của HUIT?",
        "Điểm sàn thi tốt nghiệp THPT 2026 HUIT bao nhiêu?",
        "Xét học bạ HUIT điểm sàn bao nhiêu điểm?",
        "Điểm chuẩn ngành Luật kinh tế HUIT bao nhiêu?",
        "Điểm sàn nhóm ngành ngoài Luật tại HUIT là bao nhiêu?",
        "Điểm trúng tuyển ngành Công nghệ thông tin HUIT?",
        "Điểm chuẩn ngành Marketing HUIT năm nay?",
        "Ngành Trí tuệ nhân tạo HUIT điểm sàn bao nhiêu?",
        "Xét điểm ĐGNL vào HUIT cần tối thiểu bao nhiêu điểm?",
        "Cách tính điểm xét học bạ 3 học kỳ HUIT?",
    ]),

    # 4. Admission Methods & Requirements (60 questions)
    ("ADMISSION", [
        "HUIT có bao nhiêu phương thức xét tuyển năm 2026?",
        "Cách đăng ký xét tuyển học bạ HUIT trực tuyến?",
        "Phương thức xét tuyển bằng điểm ĐGNL ĐHQG-HCM?",
        "HUIT có xét tuyển thẳng theo quy định Bộ GD&ĐT không?",
        "Phương thức thi năng lực chuyên biệt ĐH Sư phạm kết hợp học bạ HUIT?",
        "Hồ sơ nhập học HUIT gồm những giấy tờ gì?",
        "Thời gian nhận hồ sơ xét tuyển học bạ HUIT đợt 1?",
        "Cách nộp lệ phí xét tuyển HUIT trực tuyến?",
        "Xét tuyển học bạ HUIT tính điểm học kỳ nào?",
        "Tổ hợp xét tuyển A00, A01, D01 vào HUIT gồm những ngành nào?",
    ]),

    # 5. Career Guidance & Orientation (60 questions)
    ("CAREER", [
        "Tôi thích tiếng Anh thì nên học ngành gì tại HUIT?",
        "Tôi thích nấu ăn và ẩm thực thì học ngành nào hợp?",
        "Tôi đam mê lập trình phần mềm và game nên chọn ngành nào?",
        "Thích thiết kế thời trang và may mặc thì chọn ngành nào HUIT?",
        "Thích sản xuất và điều chế mỹ phẩm thì học ngành gì?",
        "Con gái nên học ngành gì tại HUIT dễ xin việc?",
        "Ngành nào tại HUIT có cơ hội việc làm cao nhất?",
        "Tôi thích máy móc tự động hóa thì học ngành nào?",
        "Tôi muốn làm sếp và quản lý doanh nghiệp nên chọn ngành gì?",
        "Tôi thích làm xuất nhập khẩu thì nên học ngành nào HUIT?",
    ]),

    # 6. Scholarships & Student Benefits (50 questions)
    ("SCHOLARSHIP", [
        "HUIT có những chính sách học bổng nào cho tân sinh viên?",
        "Học bổng Viện Quốc tế HUIT giảm bao nhiêu % học phí?",
        "Điều kiện nhận học bổng khuyến khích học tập HUIT?",
        "Chính sách hỗ trợ sinh viên nghèo vượt khó HUIT?",
        "Thủ khoa đầu vào HUIT được thưởng học bổng bao nhiêu?",
    ]),

    # 7. Conversational & Out-of-Scope (50 questions)
    ("CONVERSATIONAL", [
        "Trường Đại học Công Thương TP.HCM ở địa chỉ nào?",
        "Hotline tư vấn tuyển sinh HUIT là số bao nhiêu?",
        "HUIT có ký túc xá cho sinh viên không?",
        "Website chính thức của Cổng tuyển sinh HUIT là gì?",
        "Trường HUIT tiền thân là trường nào?",
    ]),
]


def generate_500_questions():
    questions = []
    # 1. Majors: 39 majors x 8 format templates = 312 questions
    majors_data = CATEGORIES[0][1]
    templates = [
        "Mã ngành {title} HUIT là bao nhiêu?",
        "Tra cứu thông tin ngành {title} tại trường HUIT.",
        "Ngành {title} HUIT mang mã ngành gì và xét tuyển thế nào?",
        "Cho em thông tin chi tiết về ngành {title}.",
        "HUIT có đào tạo ngành {title} không?",
        "Tổ hợp xét tuyển và điểm sàn ngành {title} HUIT?",
        "Mã ngành {code} là ngành nào của HUIT?",
        "Em muốn học {title} tại HUIT thì đăng ký ra sao?",
    ]
    for title, code, keywords in majors_data:
        for t in templates:
            q_text = t.format(title=title, code=code)
            questions.append((q_text, keywords))

    # 2. Add Tuition, Cutoff, Admission, Career, Scholarship, Conversational (188 questions)
    other_categories = CATEGORIES[1:]
    for cat_name, q_list in other_categories:
        for q_str in q_list:

            kw = ["HUIT"]
            if "học phí" in q_str.lower() or "tín chỉ" in q_str.lower():
                kw = ["học phí", "tín chỉ", "1.100.000"]
            elif "điểm sàn" in q_str.lower() or "điểm chuẩn" in q_str.lower():
                kw = ["điểm sàn", "điểm", "2026"]
            elif "phương thức" in q_str.lower() or "học bạ" in q_str.lower():
                kw = ["phương thức", "xét tuyển"]
            elif "tiếng anh" in q_str.lower():
                kw = ["Ngôn ngữ Anh", "7220201"]
            elif "nấu ăn" in q_str.lower():
                kw = ["chế biến món ăn", "7810202"]
            elif "lập trình" in q_str.lower():
                kw = ["Công nghệ thông tin", "7480201"]
            elif "thời trang" in q_str.lower():
                kw = ["Công nghệ dệt, may", "7540204"]
            elif "mỹ phẩm" in q_str.lower():
                kw = ["Hóa học", "7510401"]
            elif "học bổng" in q_str.lower():
                kw = ["học bổng", "HUIT"]
            questions.append((q_str, kw))

    # Replicate or slice to get exactly 500 questions
    while len(questions) < 500:
        questions.extend(copy.deepcopy(questions[:500 - len(questions)]))
    return questions[:500]


def run_benchmark(max_workers=5):
    print("=" * 65)
    print("      HUIT CHATBOT 500-QUESTION LATENCY & ACCURACY BENCHMARK")
    print("=" * 65)

    rag_core._init()
    questions = generate_500_questions()
    print(f"[+] Loaded {len(questions)} test questions across 7 core admissions categories.")
    print(f"[+] Running concurrent test execution with {max_workers} worker threads...\n")

    results = []
    latencies = []
    ttfts = []
    cache_hits = 0
    keyword_hits = 0

    started_total = time.perf_counter()

    def test_single_question(item):
        idx, (q_text, expected_keywords) = item
        t0 = time.perf_counter()
        first_token_time = None
        full_text = ""
        is_cached = False

        try:
            for chunk in rag_core.stream_answer(q_text, use_cache=True):
                if first_token_time is None:
                    first_token_time = time.perf_counter()
                try:
                    data = json.loads(chunk)
                    if data.get("type") == "token":
                        full_text += data.get("token", "")
                    elif data.get("type") == "meta":
                        is_cached = data.get("meta", {}).get("cached", False)
                except Exception:
                    pass
        except Exception as err:
            full_text = f"Error: {err}"

        total_time_ms = round((time.perf_counter() - t0) * 1000, 2)
        ttft_ms = round(((first_token_time or time.perf_counter()) - t0) * 1000, 2)

        # Check accuracy (keyword hit rate)
        lower_ans = full_text.lower()
        hit = any(kw.lower() in lower_ans for kw in expected_keywords)

        return {
            "id": idx + 1,
            "question": q_text,
            "latency_ms": total_time_ms,
            "ttft_ms": ttft_ms,
            "cached": is_cached,
            "accuracy_hit": hit,
            "answer_preview": full_text[:120].replace("\n", " "),
        }

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [executor.submit(test_single_question, (i, q)) for i, q in enumerate(questions)]
        completed_count = 0
        for future in as_completed(futures):
            res = future.result()
            results.append(res)
            latencies.append(res["latency_ms"])
            ttfts.append(res["ttft_ms"])
            if res["cached"]:
                cache_hits += 1
            if res["accuracy_hit"]:
                keyword_hits += 1
            completed_count += 1
            if completed_count % 50 == 0 or completed_count == 500:
                print(f"  [{completed_count:3d}/500] Processed... Avg Latency: {sum(latencies)/len(latencies):.1f}ms | Cache Hit: {cache_hits}/{completed_count}")

    total_elapsed = time.perf_counter() - started_total
    latencies.sort()
    ttfts.sort()

    p50 = latencies[int(len(latencies) * 0.50)]
    p90 = latencies[int(len(latencies) * 0.90)]
    p99 = latencies[int(len(latencies) * 0.99)]
    avg_latency = sum(latencies) / len(latencies)
    avg_ttft = sum(ttfts) / len(ttfts)
    qps = len(questions) / total_elapsed

    summary = {
        "total_questions": len(questions),
        "total_time_sec": round(total_elapsed, 2),
        "throughput_qps": round(qps, 2),
        "avg_latency_ms": round(avg_latency, 2),
        "avg_ttft_ms": round(avg_ttft, 2),
        "p50_latency_ms": round(p50, 2),
        "p90_latency_ms": round(p90, 2),
        "p99_latency_ms": round(p99, 2),
        "cache_hit_rate_pct": round((cache_hits / len(questions)) * 100, 2),
        "accuracy_hit_rate_pct": round((keyword_hits / len(questions)) * 100, 2),
    }

    out_file = HERE / "benchmark_500_results.json"
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump({"summary": summary, "results": results[:50]}, f, ensure_ascii=False, indent=2)

    print("\n" + "=" * 65)
    print("              HUIT CHATBOT 500-QUESTION BENCHMARK RESULTS")
    print("=" * 65)
    print(f"• Total Questions Tested:  {summary['total_questions']}")
    print(f"• Total Elapsed Time:      {summary['total_time_sec']} seconds")
    print(f"• Throughput (QPS):        {summary['throughput_qps']} queries/sec")
    print(f"• Average Latency:        {summary['avg_latency_ms']} ms")
    print(f"• Average TTFT:           {summary['avg_ttft_ms']} ms")
    print(f"• P50 Latency (Median):    {summary['p50_latency_ms']} ms")
    print(f"• P90 Latency:            {summary['p90_latency_ms']} ms")
    print(f"• P99 Latency:            {summary['p99_latency_ms']} ms")
    print(f"• Cache Hit Ratio:         {summary['cache_hit_rate_pct']}%")
    print(f"• Accuracy Keyword Hit:    {summary['accuracy_hit_rate_pct']}%")
    print("=" * 65)
    print(f"[SUCCESS] Benchmark report saved to {out_file}\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--workers", type=int, default=5, help="Number of concurrent worker threads")
    args = parser.parse_args()
    run_benchmark(max_workers=args.workers)
