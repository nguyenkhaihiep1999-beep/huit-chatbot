# JEV 2.0: Điều phối đa yêu cầu có kiểm chứng

Đây là đề xuất kiến trúc tiếp theo, chưa triển khai. Ngày: 22/10/2026.

Thay đổi nổi bật là chuyển JEV từ hai điểm hỗ trợ phân loại sang tham gia chọn hành động trong một vòng tư vấn có kiểm chứng. Người dùng có thể hỏi nhiều vấn đề trong một câu; hệ thống theo dõi độ đầy đủ của từng vấn đề, tìm bổ sung đúng phần thiếu và tổng hợp câu trả lời có nguồn cho từng phần.

## Ví dụ người dùng nhìn thấy

“Học phí, điểm chuẩn CNTT và học bổng năm 2026 thế nào?”

Hệ thống tạo ba tác vụ: học phí CNTT, điểm chuẩn CNTT và học bổng năm tương ứng. Mỗi tác vụ có điều kiện truy xuất riêng. Nếu học phí và điểm chuẩn đã có căn cứ nhưng chưa có chính sách học bổng phù hợp, hệ thống tìm bổ sung riêng phần học bổng trong giới hạn được cấu hình. Nếu vẫn thiếu, trả lời hai phần có căn cứ và nêu rõ phần học bổng chưa xác minh được. Không tự đặt số liệu và không yêu cầu người dùng lặp lại toàn bộ câu hỏi.

Đây là hành vi mong muốn, không phải kết quả đã đo được trên hệ thống hiện tại. Mã hiện tại chọn một intent chính, nhưng LLM vẫn có thể trả lời nhiều ý; điểm mới là có cấu trúc theo dõi và kiểm chứng từng yêu cầu.

## Vai trò từng thành phần

- Bộ lập kế hoạch dùng rule và/hoặc LLM để đề xuất các tác vụ có cấu trúc. Phải xác thực schema, giới hạn số tác vụ, không suy đoán ngành/năm khi chưa có căn cứ.
- JEV đánh giá các lựa chọn được định nghĩa trong policy: truy xuất thêm, hỏi lại, trả lời phần đã đủ hoặc trả lời đầy đủ. Cần mở rộng policy và tích hợp các quyết định này; không giả định API JEV đã có sẵn khả năng tạo kế hoạch tự do hay chạy công cụ.
- Bộ điều khiển bằng code xác thực mọi action, giữ quyền gọi công cụ, giới hạn thời gian/chi phí, số truy vấn song song và tối đa một vòng tìm bổ sung. Khi provider lỗi hoặc độ tin cậy thấp thì quay về luồng RAG hiện có.
- Bộ truy xuất nhận từng yêu cầu cùng ngành/năm/intent đã kiểm tra, trả về nguồn và đoạn minh chứng liên quan.
- Bảng kết luận gắn mỗi dữ kiện với document_id, URL, năm và đoạn trích. JEV đánh giá độ đủ trên cùng evidence bundle mà LLM được sử dụng. Code kiểm tra tham chiếu tồn tại và độ khớp của các trường/số liệu có thể kiểm tra bằng quy tắc. Sự tồn tại của URL không chứng minh kết luận đúng; cần đánh giá sự hỗ trợ về ngữ nghĩa và kiểm chứng bởi người duyệt trên tập đánh giá.
- LLM cuối tổng hợp những kết luận được cho phép, nêu phần còn thiếu và gắn nguồn cho từng phần. Không coi confidence của JEV là bảo đảm tính đúng.

## Điểm khác biệt so với đề xuất đầu

Đề xuất đầu tập trung sửa wiring, payload và độ trễ. Đề xuất mới thay đổi đơn vị xử lý từ “một câu hỏi/một intent chính” sang “một câu hỏi/nhiều yêu cầu có trạng thái bằng chứng riêng”, đồng thời thêm bước kiểm chứng trước khi phát câu trả lời. Các sửa lỗi cơ bản vẫn là điều kiện nền tảng cần thực hiện.

## Phạm vi triển khai đầu tiên

1. Chỉ mở luồng mới cho câu hỏi nhiều ý; giữ đường nhanh của guardrail, danh mục, cache và câu hỏi đơn giản.
2. Đề xuất cấu hình ban đầu: tối đa ba tác vụ, một vòng tìm bổ sung. Đây là giới hạn thiết kế để thử nghiệm, không phải cấu hình đang chạy hoặc con số tối ưu đã được chứng minh.
3. Tạo trạng thái phiên tối thiểu với ngành/năm/phương thức có căn cứ, TTL và giới hạn kích thước; che dữ liệu riêng tư trước khi gửi ra ngoài.
4. Bổ sung bộ kiểm chứng kết luận và nguồn. Chỉ stream sau khi qua cổng kiểm chứng; điều này có thể tăng TTFT và cần đo trước khi triển khai rộng.
5. Thay đổi hành vi phải có cache namespace/policy_version tương ứng. Đánh giá đối chiếu trên cùng tập câu hỏi có nhãn người duyệt, theo dõi độ phủ yêu cầu, độ đúng của kết luận, trích dẫn có thực sự hỗ trợ câu trả lời, tỷ lệ hỏi lại không cần thiết, TTFT và chi phí.

Chưa có số liệu để cam kết tăng độ chính xác hoặc giảm độ trễ. Chưa sửa backend, chưa gọi API JEV thật và chưa thay đổi môi trường triển khai. Sơ đồ được dựng thành PNG/SVG bằng code; không cần mô hình sinh ảnh.
