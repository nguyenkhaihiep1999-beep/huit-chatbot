# Báo cáo Đánh giá Chất lượng RAG Baseline (Chế độ Offline Replay / Fixture)

> [!IMPORTANT]
> **THÔNG BÁO VỀ BẢN BÁO CÁO:**
> - **Chế độ:** `offline_replay` (Kiểm thử an toàn hoàn toàn cục bộ, KHÔNG kết nối cơ sở dữ liệu live và KHÔNG gọi API trả phí).
> - **Nguồn gốc số đo (Provenance):** `simulated` (Mô phỏng bằng thời gian sleep cục bộ).
> - **Mã báo cáo:** `rag-baseline-20261006_071542`
> - **Thời gian lập:** `2026-10-06T07:15:42.854799+00:00`
> - **Mã băm Corpus (SHA-256):** `4d6c4db35e6574e0c03f968a9979b2adea503c961153e2797433c7d8b86f2969`
> - **Chế độ JEV:** `shadow` (Bảo toàn nghiêm ngặt)
> - **Tình trạng báo cáo cũ:** Các báo cáo trước (ví dụ `rag_baseline_report_20261006_044009`) được đánh dấu là **[CHƯA ĐỦ TIN CẬY / SUPERSEDED]** do lấy bottleneck production từ sleep giả lập, tính Recall chia cho số từ khóa, và tự nhận supported bằng heuristic độ dài.

---

## 1. Kết quả Đánh giá Retrieval Chuẩn hóa

> [!NOTE]
> **Công thức chuẩn hóa:**
> - Recall@k = Số ID tài liệu liên quan duy nhất trong top-k / Tổng số ID tài liệu liên quan kỳ vọng.
> - Precision@k = Số ID tài liệu liên quan duy nhất trong top-k / k.
> - Chỉ các câu hỏi đã được chấp nhận (`requires_human_review == False`) mới đưa vào chỉ số chính thức. Các tình huống còn lại giữ nguyên nhãn **"chưa được duyệt" (pending)**.

| Chỉ số Retrieval | Giá trị đo được | Số lượng mẫu |
| :--- | :--- | :--- |
| **MRR (Mean Reciprocal Rank)** | **0.9722** | 18 cases chấp nhận |
| **Recall@1** | **0.9167** | 18 cases chấp nhận |
| **Recall@3** | **1.0000** | 18 cases chấp nhận |
| **Precision@1** | **0.9444** | 18 cases chấp nhận |
| **Precision@3** | **0.3518** | 18 cases chấp nhận |
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
- **Content TTFT toàn trình trung bình (e2e_content_ttft):** 178.37 ms (p50: 178.72 ms, p95: 178.89 ms)
- **Thời gian chờ LLM First Token (llm_ttft):** 65.45 ms (p50: 65.41 ms, p95: 65.87 ms)
- **Tổng thời gian trung bình:** 270.6 ms

### Ma trận Phân tách Lỗi (Decoupling Matrix):
1. **Type A (Thành công trọn vẹn - Có tài liệu & xác minh có căn cứ qua Annotation):** 4
2. **Type B (Lỗi Generation - Trích dẫn sai nguồn hoặc mâu thuẫn):** 0
3. **Type C (Phản hồi an toàn / Hỏi lại làm rõ đúng mực):** 0
4. **Type D (Ảo giác nghiêm trọng khi không có tài liệu):** 0
5. **Chưa thể xác minh (Unverified / Cần người duyệt):** 6

---

## 3. Đo lường Hiệu năng Harness (Chế độ Simulated Offline)

> [!WARNING]
> **LƯU Ý VỀ NGUỒN GỐC SỐ ĐO (PROVENANCE: SIMULATED):**
> - **Nguồn gốc số đo:** `simulated` (Mô phỏng thời gian bằng sleep cục bộ).
> - **Kết luận về bộ đo:** Bộ công cụ harness hoạt động chuẩn xác, phân tách đúng các span và ghi nhận TTFT/latency toàn trình.
> - **Hạn chế kết luận:** **CHƯA ĐỦ BẰNG CHỨNG để chọn bottleneck thực tế trong Production.** Báo cáo này TUYỆT ĐỐI KHÔNG đưa ra khuyến nghị thay đổi mô hình LLM, prompt, database index hay kiến trúc Jev dựa trên số đo sleep này.
> - **Báo cáo cũ bị ảnh hưởng:** Các kết luận trước đây từng coi LLM TTFT hay FastEmbed là bottleneck production dựa trên sleep giả lập đều bị bãi bỏ vì không đủ căn cứ thực tế.

### Phân bố độ trễ các thành phần (Cold Cache Miss):
| Thành phần | p50 (ms) | p90 (ms) | p95 (ms) | Trung bình (ms) |
| :--- | :--- | :--- | :--- | :--- |
| **Cache Lookup** | 5.33 | 5.49 | 5.49 | 5.37 |
| **Embedding (FastEmbed local)** | 15.54 | 15.66 | 15.67 | 15.49 |
| **Vector Search (Semantic Search)** | 20.38 | 20.64 | 20.64 | 20.4 |
| **Keyword Search (Từ khóa)** | 15.49 | 15.76 | 15.82 | 15.44 |
| **Reranker** | 10.71 | 10.79 | 10.82 | 10.67 |
| **Jev Shadow Overhead** | 45.36 | 45.56 | 45.59 | 45.38 |
| **LLM TTFT (Chờ LLM)** | 65.32 | 65.65 | 65.71 | 65.4 |
| **Content TTFT Toàn trình** | 178.64 | 178.96 | 179.0 | 178.35 |
| **Toàn trình (Total Chat)** | 266.19 | 293.11 | 296.99 | 270.34 |

### Xếp hạng Thời gian Đo lường Giả lập (Harness Benchmark):
1. **llm_ttft (Thời gian chờ mô hình phản hồi)**: 65.40 ms (simulated)
2. **jev_evidence (Shadow evaluation)**: 45.38 ms (simulated)
3. **vector_search (Tìm kiếm ngữ nghĩa)**: 20.40 ms (simulated)
4. **embedding (FastEmbed local)**: 15.49 ms (simulated)
5. **keyword_search (Tìm kiếm từ khóa)**: 15.44 ms (simulated)
6. **rerank (Sắp xếp và lọc tài liệu)**: 10.67 ms (simulated)
7. **cache_lookup**: 5.37 ms (simulated)

### So sánh Profiles Đặc thù:
- **Warm Cache Hit TTFT:** p50 = 5.51 ms, avg = 5.41 ms (Xác minh trạng thái cache thật).
- **Shadow Mode Overhead:** 46.51 ms so với Jev Off.

---

## 4. Đề xuất Dựa trên Bằng chứng Hợp lệ

### [ƯU TIÊN 1] Phê duyệt bộ nhãn Ground Truth và Annotation cho các trường hợp Pending
- **Tác động:** Nâng cao độ tin cậy và độ bao phủ của benchmark (11 tình huống đang chờ duyệt)
- **Rủi ro:** Thấp (Chuẩn hóa nhãn dữ liệu, không tác động vận hành)
- **Bằng chứng:** Hiện có 11 tình huống ở trạng thái pending cần được phê duyệt trước khi mở rộng benchmark.

