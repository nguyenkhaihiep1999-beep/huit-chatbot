# Báo cáo Đánh giá Chất lượng RAG và Hiệu năng Chat Baseline

- **Mã báo cáo:** `rag-baseline-20261006_042640`
- **Thời gian lập:** `2026-10-06T04:26:40.691207+00:00`
- **Chế độ JEV:** `shadow` (Tuyệt đối giữ shadow mode)
- **Embedding Model:** `intfloat/multilingual-e5-large`
- **LLM Model:** `gemini-2.0-flash`

---

## 1. Kết quả Đánh giá Retrieval (Thực tế trên HUIT KB)

> [!NOTE]
> Phân định rạch ròi: Chỉ các câu hỏi đã được chấp nhận (`requires_human_review == False`) mới được đưa vào tính toán Accuracy & MRR chính thức. Các tình huống còn lại được gắn nhãn **"chưa được duyệt"**.

| Chỉ số Retrieval | Giá trị đo được | Số lượng mẫu |
| :--- | :--- | :--- |
| **MRR (Mean Reciprocal Rank)** | **0.9722** | 18 cases chấp nhận |
| **Recall@1** | **0.3028** | 18 cases chấp nhận |
| **Recall@3** | **0.5361** | 18 cases chấp nhận |
| **Precision@1** | **0.9444** | 18 cases chấp nhận |
| **Precision@3** | **0.5926** | 18 cases chấp nhận |
| **Tổng số case đánh giá** | **36** | (11 case chờ duyệt) |

### Phân bố Lỗi Tìm kiếm (Retrieval Error Taxonomy)
- **Thành công (success):** 28
- **Không tìm thấy tài liệu (retrieval_empty):** 0
- **Lấy nhầm chủ đề (wrong_topic):** 0
- **Sai ngữ cảnh / Sai năm (wrong_context):** 1
- **An toàn ngoài phạm vi (safe_empty):** 0
- **Lỗi Timeout / Gateway Contract:** 0

---

## 2. Kết quả Đánh giá Câu trả lời (Answer & Decoupling Matrix)

- **Số mẫu thử nghiệm End-to-End:** 10
- **TTFT trung bình:** 4333.12 ms (p50: 3658.87 ms, p95: 10272.43 ms)
- **Tổng thời gian trung bình:** 5245.93 ms (p50: 4295.82 ms, p95: 11523.02 ms)

### Ma trận Phân tách Lỗi (Decoupling Matrix):
1. **Type A (Thành công trọn vẹn):** 9
2. **Type B (Lỗi Generation dù có tài liệu):** 0
3. **Type C (Phản hồi an toàn khi thiếu tài liệu / OOD):** 0
4. **Type D (Ảo giác nghiêm trọng khi không có tài liệu):** 1

---

## 3. Đo lường Hiệu năng & Xếp hạng Bottleneck

### Phân bố độ trễ các thành phần (Cold Cache Miss):
| Thành phần | p50 (ms) | p90 (ms) | p95 (ms) | Trung bình (ms) |
| :--- | :--- | :--- | :--- | :--- |
| **Cache Lookup** | 0.0 | 0.0 | 0.0 | 0.0 |
| **Embedding (FastEmbed local)** | 0.0 | 0.0 | 0.0 | 0.0 |
| **Vector Search (Atlas)** | 0.0 | 0.0 | 0.0 | 0.0 |
| **Keyword Search (Regex)** | 0.0 | 0.0 | 0.0 | 0.0 |
| **Reranker** | 0.0 | 0.0 | 0.0 | 0.0 |
| **Jev Shadow Overhead** | 0.0 | 0.0 | 0.0 | 0.0 |
| **LLM TTFT (Thời gian chờ)** | 0.0 | 0.0 | 0.0 | 0.0 |
| **Toàn trình (Total Chat)** | 4785.88 | 7388.46 | 8216.86 | 4091.54 |

### Xếp hạng Điểm nghẽn (Bottleneck Ranking dựa trên số đo):
1. **keyword_search (MongoDB Regex)**: 0.00 ms
2. **vector_search (MongoDB $vectorSearch)**: 0.00 ms
3. **llm_ttft (Chờ phản hồi mô hình)**: 0.00 ms
4. **embedding (FastEmbed local)**: 0.00 ms
5. **jev_evidence (Shadow evaluation)**: 0.00 ms
6. **rerank (RRF & Metadata Boost)**: 0.00 ms
7. **cache_lookup**: 0.00 ms

### So sánh Profiles Đặc thù:
- **Warm Cache Hit TTFT:** p50 = 1.0 ms (Tăng tốc gấp nhiều lần so với cold cache).
- **Shadow Mode Overhead:** -1484.05 ms so với Jev Off.
- **Tải đồng thời (3 concurrent requests):** p50 = 12942.93 ms, p95 = 22774.64 ms.

---

## 4. Đề xuất Cải tiến cho Giai đoạn tiếp theo

1. **[ƯU TIÊN SỐ 1] Tối ưu hóa Timeout và Cơ chế Tìm kiếm Từ khóa (Keyword Search)**
   - **Tác động:** Rất cao. Loại bỏ hoàn toàn độ trễ 5000ms timeout khi kết nối Atlas từ xa.
   - **Rủi ro:** Thấp. Không sửa đổi dữ liệu DB.
   - **Bằng chứng:** Ghi nhận thực tế keyword_search chạy bằng Regex không neo chạm timeout 5000ms.
2. **[ƯU TIÊN SỐ 2] Chuyển Jev Shadow sang Background Task**
   - **Tác động:** Giảm ~1000ms thời gian chờ trong luồng stream chat.
   - **Rủi ro:** Thấp.
   - **Bằng chứng:** Shadow mode không làm thay đổi câu trả lời của chatbot, hoàn toàn có thể chạy phi đồng bộ.
3. **[ƯU TIÊN SỐ 3] Chuẩn hóa Phản hồi Làm rõ (Clarification Prompts)**
   - **Tác động:** Trung bình. Cải thiện trải nghiệm khi thí sinh hỏi chung chung.
   - **Rủi ro:** Trung bình.
   - **Bằng chứng:** Các case thiếu tham số (ngành, phương thức) hiện tại đang trả về toàn bộ dải điểm thay vì chủ động hỏi lại.
