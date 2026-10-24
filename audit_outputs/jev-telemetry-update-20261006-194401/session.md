# Phiên cập nhật telemetry Jev — 06/10/2026

Phạm vi được yêu cầu: sửa lỗi telemetry đã được kiểm tra, bổ sung regression tests, cung cấp prompt bàn giao và báo cáo HTML. Không deploy, gọi API trả phí, ghi/xóa MongoDB hoặc thay đổi cấu hình model/threshold.

Trước khi sửa, ba regression cases (intent hết deadline, evidence hết deadline, thiếu key) đều thất bại vì `api_called=true` dù không có HTTP request. Sau sửa, nhóm Jev assist đạt 27 tests. Kết quả toàn bộ suite được ghi riêng vào JUnit và bằng chứng phiên.

Kết quả cuối: 557 backend tests đạt (thêm 6 ca), 126 frontend tests đạt, lint/build đạt, 18 frontend contracts + manifest đồng bộ. Secret scan 478 file: 0 leak thật trong phạm vi scan. Còn 34 warnings cũ của backend; không tự thay dependency hoặc vector KB.

Chạy lại probe cũ sau sửa: 0 request provider, `api_called=false`, `apply_reason=budget_exhausted_before_call`, chat kết thúc bình thường. Trước sửa probe tương ứng ghi `api_called=true` dù không gửi request.

HTML đã mở và xem bằng trình duyệt in-app; bố cục hai cột và màn hình nhỏ không tràn ngang ở các chiều rộng CSS quan sát được 1041/386/373 px. Nút sao chép prompt trả trạng thái thành công, không có console error quan sát được. Cả 7 file báo cáo/bằng chứng qua helper preview đều trả HTTP 200. Helper chỉ phục vụ loopback trong folder báo cáo; không phải frontend chatbot và không gọi API ứng dụng. Kích thước trình duyệt được trả về mặc định sau kiểm tra.

Backend `/health/live` trả HTTP 200, nhưng chưa xác minh process đã nạp bản sửa. Frontend :3000 và MongoDB runtime chưa xác minh thành công; không chạy browser chat E2E, container, live Jev hoặc deploy. Cấu hình model/mode và dữ liệu Mongo giữ nguyên.

Các báo cáo cũ được giữ nguyên như snapshot lịch sử, không ghi đè. Prompt bàn giao ở `prompt-tiep-theo.md`; HTML tự chứa ở `bao-cao-phien.html`; số liệu và SHA-256 source ở `evidence.json`.

Sau QA, đã đóng tab và dừng đúng helper preview do phiên này tạo. Không dừng backend/frontend của người dùng. Lượt secret scan cuối vẫn đạt: 478 file, 0 leak thật.

## Bổ sung theo yêu cầu tiếp theo: prompt Vercel/Railway

Đã tạo `prompt-deploy-vercel-railway.md`, thêm liên kết trong prompt nghiệm thu và HTML. Đọc cấu hình repo và đối chiếu tài liệu chính thức Vercel/Railway ngày 06/10/2026; không sửa `vercel.json`, Dockerfile, environment variables hoặc cloud. Không deploy, commit/push, gọi provider hoặc ghi Mongo trong lượt bổ sung tài liệu. Kết quả tests/scan ở trên là snapshot trước đó, không phải một lượt chạy lại cho phụ lục này.
