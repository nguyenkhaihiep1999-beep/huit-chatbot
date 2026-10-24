# Kiểm tra JEV và kiến trúc cải tiến đề xuất

Ngày kiểm tra: 22/10/2026. Phạm vi: mã nguồn cục bộ trong D:\chatbot2; không thay đổi backend, cấu hình hoặc môi trường triển khai. Chưa nhận được ảnh sơ đồ gốc, vì vậy sơ đồ mới là đề xuất độc lập theo mã nguồn, chưa thể xác nhận nối tiếp đúng bố cục ảnh.

## Kết luận

Nên cải tiến JEV ở cách áp dụng quyết định vào retrieval và policy trả lời trước khi bổ sung thêm lượt gọi mô hình. Cơ chế off/shadow/assist, fallback, circuit breaker, giới hạn đồng thời và cache assist riêng đã có; cần giữ lại. JEV tiếp tục làm lớp hỗ trợ quyết định, LLM chính tạo câu trả lời.

## Ưu tiên thực hiện

### 1. Sửa giới hạn payload và tính nhất quán evidence_count — ưu tiên cao

Trong [redaction.py](D:/chatbot2/backend/app/decision_engine/redaction.py:128), vòng lặp chỉ rút gọn evidence. Khi question riêng đã quá dài, hàm vẫn có thể trả payload vượt max_bytes, đồng thời evidence_count không được cập nhật sau khi pop tài liệu.

Đã tái hiện cục bộ với question gồm 10.000 ký tự ASCII và một tài liệu: payload **10.096 byte** với giới hạn mặc định **8.192 byte**; evidence_count = 1 nhưng evidence thực tế có 0 phần tử. Đây là lỗi ở builder; schema hoặc provider phía sau có thể từ chối hoặc fallback, không có nghĩa API chắc chắn nhận payload đó.

Đề xuất: phân bổ byte cho question, metadata và excerpt; cắt theo UTF-8; cập nhật count sau mỗi thay đổi; kiểm tra cuối cùng trước khi tạo DecisionRequest. Khi không thể giữ payload hợp lệ thì bỏ qua JEV có mã lý do rõ ràng. Che dữ liệu trên toàn bộ văn bản trước khi cắt excerpt để tránh giữ mảnh thông tin nhạy cảm tại ranh giới cắt; whitelist/sanitize metadata.

### 2. Dùng intent của JEV trong retrieval thật — ưu tiên cao

[pipeline.py](D:/chatbot2/backend/app/rag/pipeline.py:293) cập nhật intent khi assist chấp nhận kết quả, nhưng [lượt gọi retrieve](D:/chatbot2/backend/app/rag/pipeline.py:345) chỉ truyền câu hỏi, top_k và timings. Trong [reranker.py](D:/chatbot2/backend/app/rag/reranker.py:219), retrieve lại tự gọi classify_intent(expanded_q). Do đó intent JEV đã duyệt chưa trực tiếp điều khiển retrieval/reranking; hiện chủ yếu ảnh hưởng trace và chọn artifact.

Đề xuất: truyền effective_intent đã kiểm tra vào retrieve và rerank. Nếu off/shadow hoặc kết quả không đạt điều kiện thì dùng baseline. Ưu tiên boost mềm và ràng buộc ngành/năm có căn cứ; tránh lọc cứng làm mất nguồn đúng. Kiểm chứng bằng ca có baseline sai nhưng JEV chọn đúng và thứ hạng tài liệu thực sự thay đổi.

### 3. Biến đánh giá minh chứng thành policy hành động — ưu tiên cao

Trong [pipeline.py](D:/chatbot2/backend/app/rag/pipeline.py:410), insufficient/conflicting chỉ được áp dụng nếu confidence đạt ngưỡng và needs_clarification >= 0,70, sau đó thêm lời nhắc hỏi lại vào context. Partial đi chung nhánh không can thiệp với sufficient. Kết quả needs_clarification từ tác vụ intent chưa được sử dụng trong đoạn áp dụng intent.

Điều này chưa phân biệt thiếu thông tin từ người hỏi với thiếu hoặc mâu thuẫn trong kho tri thức. Hỏi lại ngành/năm không giải quyết được trường hợp nguồn đã mâu thuẫn dù câu hỏi rõ.

Đề xuất policy tường minh:

- Sufficient: cho phép sinh câu trả lời dựa trên nguồn.
- Partial: trả lời phần có căn cứ, chỉ rõ phần chưa có thông tin.
- Thiếu ngành/năm/phương thức cần thiết: hỏi lại một câu cụ thể.
- Insufficient/conflicting do nguồn: truy xuất bổ sung tối đa một lượt nếu còn budget; ưu tiên nguồn chính thức, đúng năm, có thông tin hiệu lực.
- Vẫn không đủ: nói rõ giới hạn, cung cấp nguồn/liên hệ phù hợp; không khẳng định số liệu thiếu căn cứ.

Policy nên giới hạn dữ kiện gửi cho LLM và kiểm tra trích dẫn sau sinh, thay vì chỉ trông chờ một lời nhắc trong prompt. Quy tắc cần thử nghiệm trên dữ liệu thật trước khi kích hoạt rộng.

### 4. Cho JEV đánh giá đúng dữ kiện LLM sẽ sử dụng — ưu tiên tiếp theo

[redaction.py](D:/chatbot2/backend/app/decision_engine/redaction.py:102) chỉ gửi ba tài liệu, mỗi excerpt tối đa 250 ký tự và không kèm source_url. Trong khi đó [context LLM](D:/chatbot2/backend/app/rag/pipeline.py:365) lấy tối đa 1.100 ký tự mỗi tài liệu. JEV có thể kết luận thiếu vì thông tin trả lời nằm ngoài 250 ký tự đầu, hoặc không thấy phần mâu thuẫn LLM vẫn nhận được.

Đề xuất xây dựng một evidence bundle chuẩn chung, chọn đoạn liên quan trực tiếp câu hỏi và có URL/năm/ngày hiệu lực nếu tồn tại trong nguồn. JEV và LLM cần nhận cùng các dữ kiện được xét duyệt; vẫn giữ giới hạn payload và che thông tin riêng tư. Không tự tạo metadata nguồn khi chưa có.

### 5. Giảm độ trễ shadow và phân bổ budget cho hai tác vụ

[pipeline.py](D:/chatbot2/backend/app/rag/pipeline.py:273) gọi intent đồng bộ trước retrieval, rồi evidence đồng bộ trước LLM. [Tài liệu kiến trúc](D:/chatbot2/docs/ARCHITECTURE.md:285) cũng xác nhận shadow inline làm tăng TTFT. Lượt intent nhận cả tổng ngân sách; evidence chỉ nhận phần còn lại, nên có thể thường xuyên bị bỏ qua nếu intent dùng gần hết budget.

Đề xuất: shadow lấy mẫu qua hàng đợi có giới hạn và worker được quản lý; đầy hàng đợi thì bỏ mẫu, có timeout, dọn tài nguyên và shutdown rõ ràng. Không tạo detached task không được quản lý. Assist vẫn cần chờ các quyết định sẽ áp dụng, nhưng dùng deadline chung và ngân sách từng giai đoạn có phần dành cho evidence. Chọn con số sau khi đo phân phối độ trễ thực tế.

### 6. Chứng minh giá trị bằng chất lượng câu trả lời thực tế

Hai báo cáo đã đọc, jev_staging_shadow_benchmark_report.json và jev_evaluation_report_20261004_080623.json, có runner_mode = mock. Các số liệu đó không chứng minh JEV thật làm tốt hơn baseline. Test tích hợp hiện có cũng giả lập provider/retrieval/LLM nhằm kiểm tra wiring và fallback.

Đề xuất bộ câu hỏi có nhãn người duyệt, có ca đa ý định, câu hỏi tiếp nối, thiếu ngữ cảnh, nhầm năm, nguồn mâu thuẫn và ngoài phạm vi. So sánh off/shadow/assist theo chất lượng câu trả lời, độ đúng và đủ của trích dẫn, hỏi lại đúng lúc, retrieval recall, TTFT p50/p95, timeout/fallback và chi phí. Hiệu chỉnh ngưỡng confidence theo nhóm câu hỏi; không coi 0,80 là bảo đảm độ chính xác. Chạy live có ngân sách là công việc riêng, chưa thực hiện trong lần kiểm tra này.

## Thứ tự triển khai đề nghị

1. Sửa payload/count, chuẩn hóa evidence và kiểm tra ranh giới cắt dữ liệu riêng tư.
2. Truyền intent vào retrieval, bổ sung ngữ cảnh ngành/năm/phương thức tối thiểu đã được che dữ liệu.
3. Thêm policy hành động cho sufficient/partial/insufficient/conflicting và clarification.
4. Đo baseline, cải tiến shadow và budget; tăng policy_version của cache assist khi đổi hành vi.
5. Đánh giá live có nhãn và ngân sách, mở rộng assist theo kết quả và điều kiện rollback đã xác định.

## Tệp sơ đồ

- jev-kien-truc-de-xuat.png: ảnh 2400 × 1880, lưu và chèn vào báo cáo.
- jev-kien-truc-de-xuat.svg: vector, phóng to không vỡ nét.
- build_diagram.py: dựng lại cả hai định dạng bằng Pillow, không dùng dịch vụ sinh ảnh.

Khối xanh là thay đổi đề xuất; các thay đổi này chưa được triển khai. Sơ đồ mô tả luồng chuẩn sau cache miss và các nhánh chính, không thay thế đặc tả chi tiết của toàn hệ thống.

## Kiểm chứng và giới hạn

- Đã đọc đường đi intent → retrieval → evidence → LLM và các fixture kiểm thử tích hợp liên quan.
- Đã chạy probe trực tiếp trên hàm builder và tái hiện lỗi 10.096 byte / evidence_count không nhất quán nêu trên.
- Đã mở ảnh để kiểm tra bố cục; PNG hợp lệ, SVG parse thành công bằng trình đọc XML.
- Chưa xác nhận bộ pytest tích hợp chạy thành công: lệnh thử trong môi trường hiện tại không hoàn tất với kết quả kiểm thử sử dụng được. Một lần thử nạp plugin bổ sung báo thiếu pytest_asyncio; các lần không nạp plugin cũng không trả kết quả pass. Vì vậy báo cáo không khẳng định suite đã pass và không suy từ fixture ra chất lượng mô hình thật.
- Không gọi API TypeSafe/JEV thật, không triển khai thay đổi; không đánh giá trạng thái runtime production.
