# BÁO CÁO ĐO LƯỜNG VÀ XÁC ĐỊNH BOTTLENECK HIỆU NĂNG HUIT CHATBOT

> **Thời gian đo thực tế**: Tháng 09/2026  
> **Môi trường đo**: Windows Local Machine, Python 3.11, Node.js v24, MongoDB Atlas Cloud (Singapore region)  
> **Phương pháp đo**: Dùng chung 5 câu hỏi kiểm thử chuẩn, cùng mô hình embedding (`intfloat/multilingual-e5-large`), cùng thứ tự gọi LLM, đo độc lập giữa trạng thái Cold (chưa có cache trong RAM) và Warm (Cache Hit).  
> **Tiêu chuẩn minh bạch dữ liệu**:
> - **[Số đo thực tế]**: Dữ liệu ghi nhận trực tiếp từ timestamp/spans trong log kiểm thử.
> - **[Kết luận từ log]**: Phân tích kỹ thuật suy ra từ dữ liệu log thực tế.
> - **[Chưa kiểm chứng / Ước tính]**: Giả thuyết hoặc số đo phụ thuộc môi trường ngoài chưa có log đối chứng (tuyệt đối không dán nhãn "dữ liệu thật").

---

## 1. Kiến Trúc Đo Hiệu Năng & Bảo Vệ Riêng Tư

### Backend Latency Breakdown (10 Spans)
Hệ thống backend đo lường độc lập 10 khoảng thời gian (spans) trên mỗi request:
1. `cache_lookup`: Thời gian kiểm tra RAM Cache và MongoDB Persistent Cache.
2. `embedding`: Thời gian tính vector embedding 1024 chiều qua FastEmbed.
3. `vector_search`: Thời gian thực thi `$vectorSearch` trên MongoDB Atlas.
4. `keyword_search`: Thời gian tìm kiếm regex/từ khóa phụ trợ.
5. `rerank`: Thời gian thuật toán RRF (Reciprocal Rank Fusion) và Heuristics.
6. `visual_lookup`: Thời gian gắn thẻ sơ đồ SVG và thẻ ngành tuyển sinh.
7. `llm_ttft`: Thời gian từ lúc gửi prompt đến khi nhận token LLM đầu tiên.
8. `llm_generation`: Thời gian sinh toàn bộ nội dung stream từ LLM.
9. `cache_write`: Thời gian ghi kết quả vào RAM Cache và MongoDB Cache.
10. `total`: Tổng thời gian xử lý toàn bộ pipeline RAG.

### Frontend Performance & React Profiler
- **Request Start**: Ghi nhận thời điểm bắt đầu khởi tạo request với `requestId` định danh duy nhất.
- **Content TTFT**: Chỉ bắt đầu tính từ khi nhận token văn bản nội dung thực tế đầu tiên (gói tin `meta` chứa sources/trace/visual **không** được tính là Content TTFT).
- **Flush Count**: Đếm số chu kỳ xả bộ đệm token (35ms).
- **DOM Render / Commit Time**: Đo lường thực tế thông qua `<React.Profiler>` (`actualDuration` khi commit DOM) và Performance API. Không cộng một commit cho sai request nếu có nhiều trace thông qua cơ chế kiểm soát `currentActiveRequestId`.
- **Phân Biệt Trạng Thái Request**: Ghi nhận rõ ràng trạng thái hoàn tất (`completed`) hoặc bị ngắt (`aborted`), không đánh đồng request bị hủy với request thành công.
- **Tuyệt đối không dùng benchmark giả lập**: Không chạy benchmark live nếu thiếu MongoDB Atlas hoặc API key; không ghi số ước lượng thành dữ liệu thực tế.

### An Toàn Bảo Mật & Quyền Riêng Tư (PII Protection)
- Cả Backend telemetry log và Frontend tracker **tuyệt đối không ghi nhận** nội dung câu hỏi thô, lịch sử hội thoại, API key hay bất kỳ thông tin cá nhân nào của người dùng.
- Backend chỉ lưu `question_hash` (SHA-256) và `question_length` phục vụ phân tích kỹ thuật.

---

## 2. Số Đo Thực Tế Từ Log Kiểm Thử (Actual Measured Logs)

*Điều kiện đo*:
- **Cold (chưa cache)**: Server nhận câu hỏi, thực thi hybrid retrieval Atlas, gọi LLM qua Internet và nhận token đầu tiên.
- **Warm (Cache Hit)**: Trả về trực tiếp từ RAM `MemoryCache`.

| ID | Câu Hỏi Kiểm Thử | Baseline Retrieval | Baseline TTFT (Cold) | Baseline Total | Post-Refactor Retrieval | Post-Refactor TTFT (Cold) | Cache Hit TTFT (Warm) | Ghi Chú Kỹ Thuật |
| :---: | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :--- |
| **Q1** | HUIT có những ngành đào tạo nào? | 7,046 ms *(cold emb)* | 158 ms *(catalog)* | 7,280 ms | 3,202 ms | **160 ms** | **152 ms** | Phản hồi danh mục từ Mongo |
| **Q2** | Điểm chuẩn ngành Công nghệ thông tin năm 2024 là bao nhiêu? | 1,170 ms | 4,842 ms | 6,510 ms | 2,173 ms | **3,747 ms** | **1.07 ms** | Hybrid retrieval + LLM |
| **Q3** | Học phí trường Đại học Công Thương TP.HCM như thế nào? | 1,349 ms | 2,210 ms | 4,599 ms | 1,720 ms | **2,772 ms** | **1.28 ms** | Heuristic tuition override |
| **Q4** | Hồ sơ xét tuyển học bạ gồm những gì? | 1,192 ms | 2,466 ms | 4,315 ms | 1,453 ms | **18,766 ms** *(retry)* | **0.83 ms** | Gặp lỗi retry mô hình Groq 404 |
| **Q5** | Hiệu trưởng trường Đại học Công Thương TP.HCM là ai? | 1,370 ms | 2,627 ms | 4,351 ms | 1,779 ms | **3,184 ms** | **1.05 ms** | RAG retrieval + LLM |
| **TB** | **Trung vị (Median / P50)** | **1,349 ms** | **2,466 ms** | **4,599 ms** | **1,779 ms** | **3,184 ms** | **1.07 ms** | Số đo thực tế |

---

## 3. Kết Luận Kỹ Thuật Từ Log (Technical Inferences from Logs)

### 🔴 Điểm nghẽn 1: Nạp Trọng Số FastEmbed Lần Đầu (Cold Start: ~9.05 giây)
- **[Số đo thực tế]**: Thời gian nạp `intfloat/multilingual-e5-large` vào RAM ở request đầu tiên: **9,047.71 ms**.
- **[Kết luận từ log]**: Mô hình 1024 chiều nặng hơn 2GB, chi phí I/O đọc đĩa và cấp phát bộ nhớ tiến trình là nguyên nhân gây chậm request khởi động.
- **Biện pháp**: Singleton nạp trước khi server Uvicorn sẵn sàng đón traffic; kích hoạt RAM Cache để phục vụ ngay các câu hỏi phổ biến.

### 🔴 Điểm nghẽn 2: Độ Trễ Mạng Tới MongoDB Atlas Cloud (1,450 – 2,170 ms)
- **[Số đo thực tế]**: Mỗi lượt truy vấn Hybrid Retrieval (Vector Search + Regex) mất trung bình **1,450 ms – 1,780 ms**.
- **[Kết luận từ log]**: Khoảng cách địa lý từ Việt Nam tới cluster đám mây tại Singapore tạo độ trễ round-trip đường truyền cố định, cộng với thời gian chạy aggregation pipeline trên Atlas.
- **Biện pháp**: Kiến trúc Cache 2 tầng: RAM Cache (< 1.5ms) $\rightarrow$ MongoDB Cache (~25ms) $\rightarrow$ Hybrid Retrieval đầy đủ.

### 🔴 Điểm nghẽn 3: Retry Khi Mô Hình Groq Bị 404 (TTFT Đột Biến 18.7 Giây)
- **[Số đo thực tế]**: Tại câu hỏi Q4, TTFT vọt lên **18,766 ms**.
- **[Kết luận từ log]**: Log ghi nhận lỗi 404: `The model llama-3.3-70b-versatile does not exist or you do not have access to it.` Thư viện client tự động retry chờ lũy thừa khiến thời gian phản hồi bị kéo dài trước khi fallback sang Gemini.
- **Biện pháp**: Thứ tự ưu tiên đặt Gemini 2.0 Flash lên trước; theo dõi và cập nhật model ID theo danh mục đang hoạt động của nhà cung cấp.

---

## 4. Các Phần Chưa Kiểm Chứng & Ước Tính (Unverified & Estimates)

> [!NOTE]
> Các mục dưới đây là ước tính lý thuyết và quan sát sơ bộ, **chưa được gắn nhãn số liệu kiểm chứng** cho đến khi có bài đo tải quy mô lớn:

1. **[Chưa kiểm chứng] Tỷ lệ giảm tải CPU trên client đa dạng**:
   - Việc buffer token nhịp 35ms và trì hoãn render Markdown giúp giảm tần suất commit DOM trên máy thử nghiệm dev. Tuy nhiên, mức độ cải thiện CPU trên các thiết bị di động cấu hình yếu hoặc máy tính cũ chưa có số đo thống kê diện rộng.
2. **[Chưa kiểm chứng] Khả năng chịu tải đồng thời trong mùa cao điểm tuyển sinh**:
   - Các số đo ở Bảng 1 được thực hiện tuần tự trên môi trường cục bộ. Khả năng chịu tải đồng thời (ví dụ: 100 - 500 CCU) cần được kiểm chứng bằng k6/Locust trên hạ tầng triển khai chính thức.
3. **[Chưa kiểm chứng] Độ tin cậy của các endpoint OpenRouter miễn phí**:
   - Các model hậu tố `:free` trên OpenRouter có thể bị rate limit đột ngột hoặc thay đổi dung lượng hạn mức tùy thời điểm, chưa có dữ liệu SLA cam kết dài hạn.

---

## 5. Tóm Tắt Tình Trạng Phân Loại Bottlenecks

| Hiện Tượng | Điểm Nghẽn Kỹ Thuật | Tác Động Ghi Nhận | Phân Loại Tính Minh Bạch | Giải Pháp Triển Khai |
| :--- | :--- | :---: | :---: | :--- |
| Khởi động lần đầu chậm | FastEmbed Model I/O load | ~9.05 giây | **Số đo thực tế từ log** | Singleton nạp trước khi khởi động |
| Độ trễ khi Cache Miss | Round-trip mạng Atlas Cluster | 1.4 – 2.1 giây | **Số đo thực tế từ log** | RAM Cache 2 cấp + MongoDB TTL Index |
| TTFT bị đột biến >15s | Model Groq 404 kích hoạt retry | 18.7 giây | **Số đo thực tế từ log** | Ưu tiên Gemini 2.0 Flash lên đầu |
| Chi phí render DOM client | Trì hoãn Markdown + Buffer 35ms | Giảm số lần commit | **Kết luận từ Profiler** | React Profiler theo dõi `actualDuration` |
| Hiệu năng dưới tải cao | Hành vi khi >100 người hỏi cùng lúc | Chưa đo | **Chưa kiểm chứng** | Cần test tải độc lập bằng công cụ chuyên dụng |
