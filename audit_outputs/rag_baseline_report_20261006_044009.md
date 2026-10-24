# Báo cáo Đánh giá Chất lượng RAG và Hiệu năng Chat Baseline

- **Mã báo cáo:** `rag-baseline-20261006_044009`
- **Thời gian lập:** `2026-10-06T04:40:09.989871+00:00`
- **Chế độ JEV:** `shadow` (Tuyệt đối giữ shadow mode)
- **Embedding Model:** `intfloat/multilingual-e5-large`
- **LLM Model:** `gemini-2.0-flash`

---

## 1. Kết quả Đánh giá Retrieval (Thực tế trên HUIT KB)

> [!NOTE]
> Phân định rạch ròi: Chỉ các câu hỏi đã được chấp nhận (`requires_human_review == False`) mới được đưa vào tính toán Accuracy & MRR chính thức. Các tình huống còn lại được gắn nhãn **"chưa được duyệt"**.

| Chỉ số Retrieval | Giá trị đo được | Số lượng mẫu |
| :--- | :--- | :--- |
| **MRR (Mean Reciprocal Rank)** | **0.9167** | 18 cases chấp nhận |
| **Recall@1** | **0.2917** | 18 cases chấp nhận |
| **Recall@3** | **0.5139** | 18 cases chấp nhận |
| **Precision@1** | **0.8889** | 18 cases chấp nhận |
| **Precision@3** | **0.5556** | 18 cases chấp nhận |
| **Tổng số case đánh giá** | **36** | (11 case chờ duyệt) |

### Phân bố Lỗi Tìm kiếm (Retrieval Error Taxonomy)
- **Thành công (success):** 27
- **Không tìm thấy tài liệu (retrieval_empty):** 0
- **Lấy nhầm chủ đề (wrong_topic):** 1
- **Sai ngữ cảnh / Sai năm (wrong_context):** 1
- **An toàn ngoài phạm vi (safe_empty):** 0
- **Lỗi Timeout / Gateway Contract:** 0

---

## 2. Kết quả Đánh giá Câu trả lời (Answer & Decoupling Matrix)

- **Số mẫu thử nghiệm End-to-End:** 10
- **TTFT trung bình:** 4719.83 ms (p50: 5014.61 ms, p95: 9380.56 ms)
- **Tổng thời gian trung bình:** 5370.76 ms (p50: 5679.02 ms, p95: 10486.09 ms)

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
| **Cache Lookup** | 77.6 | 81.63 | 81.89 | 77.58 |
| **Embedding (FastEmbed local)** | 139.43 | 141.62 | 142.27 | 125.7 |
| **Vector Search (Atlas)** | 649.56 | 668.58 | 674.2 | 571.06 |
| **Keyword Search (Regex)** | 328.74 | 454.5 | 460.37 | 373.06 |
| **Reranker** | 98.58 | 107.06 | 108.94 | 97.9 |
| **Jev Shadow Overhead** | 386.08 | 1615.4 | 1807.99 | 834.9 |
| **LLM TTFT (Thời gian chờ)** | 4839.78 | 6505.92 | 6718.54 | 4258.73 |
| **Toàn trình (Total Chat)** | 7080.63 | 9490.93 | 9903.55 | 6964.86 |

### Xếp hạng Điểm nghẽn (Bottleneck Ranking dựa trên số đo):
1. **llm_ttft (Chờ phản hồi mô hình)**: 4258.73 ms
2. **jev_evidence (Shadow evaluation)**: 834.90 ms
3. **vector_search (MongoDB $vectorSearch)**: 571.06 ms
4. **keyword_search (MongoDB Regex)**: 373.06 ms
5. **embedding (FastEmbed local)**: 125.70 ms
6. **rerank (RRF & Metadata Boost)**: 97.90 ms
7. **cache_lookup**: 77.58 ms

### So sánh Profiles Đặc thù:
- **Warm Cache Hit TTFT:** p50 = 1.0 ms (Tăng tốc gấp nhiều lần so với cold cache).
- **Shadow Mode Overhead:** 1182.26 ms so với Jev Off.
- **Tải đồng thời (3 concurrent requests):** p50 = 8253.14 ms, p95 = 20799.87 ms.

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
