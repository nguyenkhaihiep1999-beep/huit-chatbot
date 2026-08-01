#!/usr/bin/env python3
"""
test_system_accuracy.py
Script kiểm thử tự động độ chính xác của HUIT Chatbot.
Kiểm tra các câu hỏi trọng yếu:
- Học bổng Viện Quốc tế HUIT
- Tư vấn hướng nghiệp theo sở thích (may đồ, nấu ăn, lập trình...)
- Tra cứu thông tin ngành cụ thể (CNTT, Dệt may, Thực phẩm...)
- Học phí, điểm sàn, phương thức xét tuyển
"""

import sys
import os
import json
import time

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import rag_core

TEST_QUESTIONS = [
    {
        "id": 1,
        "question": "Chính sách học bổng của Viện Quốc tế HUIT?",
        "must_contain": ["viện quốc tế", "học bổng"],
        "must_not_contain": ["nếu bạn quan tâm đến công nghệ thông tin"]
    },
    {
        "id": 2,
        "question": "Thích may đồ thì nên học gì",
        "must_contain": ["dệt, may", "thời trang"],
        "must_not_contain": ["quản lý tài nguyên và môi trường"]
    },
    {
        "id": 3,
        "question": "Ngành cntt học gì",
        "must_contain": ["công nghệ thông tin", "lập trình"],
        "must_not_contain": ["quản lý tài nguyên"]
    },
    {
        "id": 4,
        "question": "Ngành may làm gì",
        "must_contain": ["dệt, may", "thời trang"],
        "must_not_contain": ["quản lý tài nguyên"]
    },
    {
        "id": 5,
        "question": "Có bao nhiêu thí sinh đăng kí nguyện vọng huit",
        "must_contain": ["bộ gd&đt", "chưa công bố"],
        "must_not_contain": ["ngành công nghệ thông tin (mã ngành: 7480201)"]
    },
    {
        "id": 6,
        "question": "Học phí HUIT năm 2026 bao nhiêu?",
        "must_contain": ["14", "16 triệu"],
        "must_not_contain": []
    },
    {
        "id": 7,
        "question": "Điểm sàn xét tuyển đại học 2026 HUIT?",
        "must_contain": ["16", "20", "600"],
        "must_not_contain": []
    },
    {
        "id": 8,
        "question": "Mã ngành và tổ hợp xét tuyển Trí tuệ nhân tạo?",
        "must_contain": ["7480107", "trí tuệ nhân tạo"],
        "must_not_contain": []
    }
]

def run_tests():
    print("=========================================================")
    print("   RUNNING ACCURACY & INTEGRITY VERIFICATION SUITE")
    print("=========================================================")
    
    passed = 0
    total = len(TEST_QUESTIONS)
    results = []

    for item in TEST_QUESTIONS:
        q = item["question"]
        print(f"\n[TEST #{item['id']}] Question: '{q}'")
        start = time.perf_counter()
        res = rag_core.answer(q, use_cache=False)
        elapsed = round((time.perf_counter() - start) * 1000)
        
        answer_text = res.get("answer", "")
        answer_lower = answer_text.lower()
        
        # Check requirements
        pass_must = all(term in answer_lower for term in item["must_contain"])
        pass_must_not = not any(term in answer_lower for term in item["must_not_contain"])
        
        is_ok = pass_must and pass_must_not
        if is_ok:
            passed += 1
            print(f"  --> RESULT: [PASSED] ({elapsed}ms)")
        else:
            print(f"  --> RESULT: [FAILED] ({elapsed}ms)")
            print(f"      Fail details: must_contain={pass_must}, must_not_contain={pass_must_not}")
            print(f"      Answer preview: {answer_text[:200]}...")

        results.append({
            "id": item["id"],
            "question": q,
            "passed": is_ok,
            "latency_ms": elapsed,
            "answer_preview": answer_text[:250]
        })

    print("\n=========================================================")
    print(f"   SUITE ACCURACY RATE: {passed}/{total} ({passed/total*100:.1f}%)")
    print("=========================================================")
    
    return passed == total

if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1)
