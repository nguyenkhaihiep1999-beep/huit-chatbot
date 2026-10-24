# Báo cáo Đánh giá Chất lượng RAG Baseline (Chế độ Offline Replay / Fixture)

> [!IMPORTANT]
> **THÔNG BÁO VỀ BẢN BÁO CÁO:**
> - **Chế độ:** `offline_replay` (Kiểm thử an toàn hoàn toàn cục bộ, KHÔNG kết nối cơ sở dữ liệu live và KHÔNG gọi API trả phí).
> - **Mã báo cáo:** `rag-baseline-20261006_051546`
> - **Thời gian lập:** `2026-10-06T05:15:46.957364+00:00`
> - **Mã băm Corpus (SHA-256):** `4d6c4db35e6574e0c03f968a9979b2adea503c961153e2797433c7d8b86f2969`
> - **Chế độ JEV:** `shadow` (Bảo toàn nghiêm ngặt)
> - **Tình trạng báo cáo cũ:** Các báo cáo trước (ví dụ `rag_baseline_report_20261006_044009`) được đánh dấu là **[CHƯA ĐỦ TIN CẬY / SUPERSEDED]** do phương pháp tính Recall trước đó chia cho số từ khóa, TTFT tính gộp vào llm_ttft và khuyến nghị chưa bám sát số đo.

---

## 1. Kết quả Đánh giá Retrieval Chuẩn hóa

> [!NOTE]
> **Công thức chuẩn hóa:**
> - Recall@k = Số ID tài liệu liên quan duy nhất trong top-k / Tổng số ID tài liệu liên quan kỳ vọng.
> - Precision@k = Số ID tài liệu liên quan duy nhất trong top-k / k.
> - Chỉ các câu hỏi đã được chấp nhận (`requires_human_review == False`) mới đưa vào chỉ số chính thức. Các tình huống còn lại giữ nguyên nhãn **"chưa được duyệt" (pending)**.

| Chỉ số Retrieval | Giá trị đo được | Số lượng mẫu |
| :--- | :--- | :--- |
| **MRR (Mean Reciprocal Rank)** | **1.0000** | 18 cases chấp nhận |
| **Recall@1** | **0.9722** | 18 cases chấp nhận |
| **Recall@3** | **1.0000** | 18 cases chấp nhận |
| **Precision@1** | **1.0000** | 18 cases chấp nhận |
| **Precision@3** | **0.7222** | 18 cases chấp nhận |
| **Tổng số case đánh giá** | **36** | (11 case chờ duyệt) |

### Phân bố Lỗi Tìm kiếm (Retrieval Error Taxonomy):
- **Thành công (success):** 29
- **Không tìm thấy tài liệu (retrieval_empty):** 0
- **Lấy nhầm chủ đề (wrong_topic):** 0
- **Sai ngữ cảnh / Sai năm (wrong_context):** 0
- **An toàn ngoài phạm vi (safe_empty):** 0
- **Ngoài phạm vi bị lấy tài liệu (out_of_domain_retrieved):** 7
- **Lỗi Timeout / Hệ thống:** 0

---

## 2. Kết quả Đánh giá Câu trả lời (Citation & Decoupling Matrix)

- **Số mẫu thử nghiệm End-to-End:** 10
- **Content TTFT toàn trình trung bình (e2e_content_ttft):** 178.32 ms (p50: 178.31 ms, p95: 179.02 ms)
- **Thời gian chờ LLM First Token (llm_ttft):** 65.39 ms (p50: 65.34 ms, p95: 65.66 ms)
- **Tổng thời gian trung bình:** 271.01 ms

### Ma trận Phân tách Lỗi (Decoupling Matrix):
1. **Type A (Thành công trọn vẹn - Có tài liệu & xác minh có căn cứ):** 8
2. **Type B (Lỗi Generation - Trích dẫn sai nguồn hoặc mâu thuẫn):** 2
3. **Type C (Phản hồi an toàn / Hỏi lại làm rõ đúng mực):** 0
4. **Type D (Ảo giác nghiêm trọng khi không có tài liệu):** 0
5. **Chưa thể xác minh (Pending Review):** 0

---

## 3. Đo lường Hiệu năng & Xếp hạng Bottleneck (Đo trên 1 lần chạy)

### Phân bố độ trễ các thành phần (Cold Cache Miss):
| Thành phần | p50 (ms) | p90 (ms) | p95 (ms) | Trung bình (ms) |
| :--- | :--- | :--- | :--- | :--- |
| **Cache Lookup** | 5.48 | 5.65 | 5.69 | 5.39 |
| **Embedding (FastEmbed local)** | 15.51 | 15.64 | 15.67 | 15.54 |
| **Vector Search (Semantic Search)** | 20.48 | 20.9 | 21.0 | 20.54 |
| **Keyword Search (Từ khóa)** | 15.44 | 15.59 | 15.63 | 15.48 |
| **Reranker** | 10.63 | 10.79 | 10.82 | 10.61 |
| **Jev Shadow Overhead** | 45.35 | 45.48 | 45.49 | 45.35 |
| **LLM TTFT (Chờ LLM)** | 65.48 | 65.56 | 65.57 | 65.42 |
| **Content TTFT Toàn trình** | 178.74 | 179.22 | 179.3 | 178.59 |
| **Toàn trình (Total Chat)** | 267.02 | 294.84 | 299.35 | 271.26 |

### Xếp hạng Điểm nghẽn (Dựa trên số đo trung bình):
1. **llm_ttft (Thời gian chờ mô hình phản hồi)**: 65.42 ms
2. **jev_evidence (Shadow evaluation)**: 45.35 ms
3. **vector_search (Tìm kiếm ngữ nghĩa)**: 20.54 ms
4. **embedding (FastEmbed local)**: 15.54 ms
5. **keyword_search (Tìm kiếm từ khóa)**: 15.48 ms
6. **rerank (Sắp xếp và lọc tài liệu)**: 10.61 ms
7. **cache_lookup**: 5.39 ms

### So sánh Profiles Đặc thù:
- **Warm Cache Hit TTFT:** p50 = 5.56 ms, avg = 5.56 ms (Xác minh trạng thái cache thật).
- **Shadow Mode Overhead:** 44.36 ms so với Jev Off.

---

## 4. Đề xuất Cải tiến Có bằng chứng (Tối đa 3 đề xuất)

### [ƯU TIÊN 1] Tối ưu hóa thời gian chờ LLM First Token (LLM TTFT)
- **Tác động:** Rất cao (Điểm nghẽn lớn nhất chiếm 65.4ms trung bình)
- **Rủi ro:** Thấp (Có thể thử nghiệm streaming prompt rút gọn hoặc model provider nhanh hơn)
- **Bằng chứng từ số đo:** Số đo thực tế ghi nhận llm_ttft trung bình đạt 65.4ms, là thành phần tiêu tốn thời gian dài nhất.

### [ƯU TIÊN 3] Bổ sung Guardrail xác thực Citation Marker trước khi stream câu trả lời
- **Tác động:** Trung bình (Ngăn chặn 2 lỗi trích dẫn không hợp lệ)
- **Rủi ro:** Thấp (Kiểm tra chỉ số [n] nằm trong phạm vi nguồn trước khi hiển thị)
- **Bằng chứng từ số đo:** Ghi nhận 2 trường hợp trích dẫn sai nguồn hoặc mâu thuẫn dữ kiện trong benchmark.

### [ƯU TIÊN 3] Duyệt bộ nhãn Ground Truth cho các câu hỏi còn ở trạng thái Pending
- **Tác động:** Nâng cao độ bao phủ benchmark (11 tình huống đang chờ duyệt)
- **Rủi ro:** Không có rủi ro hệ thống
- **Bằng chứng từ số đo:** Hiện có 11 trường hợp đang được gắn nhãn pending để bảo đảm an toàn đo lường.

