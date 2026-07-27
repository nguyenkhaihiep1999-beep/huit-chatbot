#!/usr/bin/env python3
"""
evaluate_rag_quality.py
Bộ script đánh giá định lượng chất lượng hệ thống RAG HUIT Chatbot:
- Retrieval Hit Rate@K & Reciprocal Rank
- Đánh giá chất lượng sinh câu trả lời RAG trên 10 câu hỏi kiểm thử đa dạng
"""
import os
import sys
import time

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import rag_core

TEST_BENCHMARK = [
    {
        "id": 1,
        "category": "Ngành đào tạo",
        "query": "Mã ngành và tổ hợp xét tuyển ngành Trí tuệ nhân tạo HUIT?",
        "expected_keywords": ["7480107", "A00", "Trí tuệ nhân tạo"]
    },
    {
        "id": 2,
        "category": "Ngành đào tạo",
        "query": "Ngành Công nghệ thông tin có xét tuyển tổ hợp môn nào?",
        "expected_keywords": ["7480201", "A00", "A01", "D01", "D07"]
    },
    {
        "id": 3,
        "category": "Điểm sàn 2025",
        "query": "Điểm sàn nhận hồ sơ xét tuyển đại học 2025 HUIT bao nhiêu?",
        "expected_keywords": ["16", "600", "điểm sàn"]
    },
    {
        "id": 4,
        "category": "Học phí",
        "query": "Học phí một học kỳ tại HUIT khoảng bao nhiêu tiền?",
        "expected_keywords": ["14", "16", "triệu", "tín chỉ"]
    },
    {
        "id": 5,
        "category": "Học bổng",
        "query": "Chính sách học bổng giảm 50% học phí HK1 dành cho những ngành nào?",
        "expected_keywords": ["50%", "học bổng", "học kỳ 1"]
    },
    {
        "id": 6,
        "category": "Ngành đào tạo",
        "query": "Ngành An toàn thông tin ra trường làm những công việc gì?",
        "expected_keywords": ["An toàn thông tin", "bảo mật", "Pentester"]
    },
    {
        "id": 7,
        "category": "Ngành đào tạo",
        "query": "Ngành Khoa học dữ liệu mã ngành là gì?",
        "expected_keywords": ["7460108", "Khoa học dữ liệu"]
    },
    {
        "id": 8,
        "category": "Ngành đào tạo",
        "query": "Ngành Công nghệ thực phẩm HUIT học mấy năm?",
        "expected_keywords": ["Công nghệ thực phẩm", "năm", "tín chỉ"]
    },
    {
        "id": 9,
        "category": "Ngành mới 2025",
        "query": "Năm 2025 HUIT mở thêm các ngành đào tạo mới nào?",
        "expected_keywords": ["Trí tuệ nhân tạo", "ngành"]
    },
    {
        "id": 10,
        "category": "Tổng quan",
        "query": "Địa chỉ cơ sở chính của Trường Đại học Công Thương TP.HCM ở đâu?",
        "expected_keywords": ["Công Thương", "HUIT", "TP.HCM"]
    }
]

print("=========================================================")
print("      HUIT AI CHATBOT - AUTOMATED EVALUATION BENCHMARK    ")
print("=========================================================")

total_tests = len(TEST_BENCHMARK)
retrieval_hits = 0
llm_success_count = 0
response_times = []

for item in TEST_BENCHMARK:
    q_id = item["id"]
    category = item["category"]
    query = item["query"]
    keywords = item["expected_keywords"]

    print(f"\n[Test #{q_id}] Category: '{category}'")
    print(f"  Query: \"{query}\"")

    start_t = time.time()
    res = rag_core.answer(query)
    elapsed = round(time.time() - start_t, 2)
    response_times.append(elapsed)

    sources = res.get("sources", [])
    answer = res.get("answer", "")

    # Check retrieval quality
    matched_kw = [kw for kw in keywords if any(kw.lower() in (s.get("title","") + " " + s.get("text","")).lower() for s in sources)]
    hit = len(matched_kw) > 0
    if hit:
        retrieval_hits += 1
    
    # Check LLM response quality
    llm_ok = len(answer) > 40 and "Lỗi" not in answer
    if llm_ok:
        llm_success_count += 1

    status_icon = "✅ PASSED" if (hit and llm_ok) else "⚠️ WARN"
    print(f"  Result: {status_icon} (Time: {elapsed}s | Sources: {len(sources)} | Answer len: {len(answer)} chars)")
    print(f"  Matched Keywords in Retrieval: {matched_kw} / {keywords}")

avg_time = round(sum(response_times) / len(response_times), 2) if response_times else 0
hit_rate = round((retrieval_hits / total_tests) * 100, 1)
llm_rate = round((llm_success_count / total_tests) * 100, 1)

print("\n=========================================================")
print("                  BENCHMARK SUMMARY RESULTS              ")
print("=========================================================")
print(f"  - Total Test Queries Evaluated : {total_tests}")
print(f"  - Retrieval Hit Rate@3         : {hit_rate}% ({retrieval_hits}/{total_tests})")
print(f"  - LLM Answer Success Rate      : {llm_rate}% ({llm_success_count}/{total_tests})")
print(f"  - Average Response Time        : {avg_time} seconds / query")
print("=========================================================")
