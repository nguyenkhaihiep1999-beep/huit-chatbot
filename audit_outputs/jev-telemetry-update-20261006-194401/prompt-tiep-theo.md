# Prompt bàn giao: nghiệm thu luồng chạy thật trước release

Bạn đang làm việc trong dự án HUIT Chatbot tại `D:\chatbot2`. Tiếp tục từ bản hiện tại, không tái cấu trúc folder hoặc đổi kiến trúc. Đọc báo cáo và bằng chứng tại `audit_outputs/jev-telemetry-update-20261006-194401/` trước khi thao tác; không dùng số liệu của báo cáo cũ để kết luận cho bản mới.

## Công việc đã thực hiện

- Telemetry Jev được ghi ở điểm provider thử gửi HTTP và truyền qua tracker riêng từng request. Không suy luận `api_called` bằng chuỗi lỗi.
- Hết budget trước provider: `api_called=false`, `apply_reason=budget_exhausted_before_call`; timeout sau khi đã thử gửi HTTP: `api_called=true`, `apply_reason=timeout`.
- Giữ nguyên API JSON/schema, câu trả lời baseline, chế độ Jev, model, ngưỡng confidence và thuật toán retrieval. Metadata nội bộ không xuất hiện trong JSON response.
- Có regression tests cho hai loại decision hết budget, thiếu key, concurrency guard, timeout sau HTTP và hai request đồng thời không trộn telemetry.

`api_called=true` chỉ chứng minh có thử gửi HTTP, không chứng minh provider nhận được request, trả kết quả tốt hoặc tính phí. Không dùng một log hay health `configured` để khẳng định chất lượng Jev.

## Nhiệm vụ tiếp theo — thực hiện theo từng bước

1. Kiểm tra AGENTS.md, working tree và báo cáo mới. Giữ nguyên thay đổi của người dùng. Chạy lại test/schema cần thiết; ghi số liệu thực tế cùng thời gian và phiên bản code, không đoán số test.
2. Xác định backend/frontend đang chạy ở URL và port nào. Chỉ probe endpoint không gây mutation. Không tự restart/stop process của người dùng. Nếu cần backend nạp code mới, báo rõ và thống nhất thời điểm reload. Có thể khởi chạy helper hoặc frontend local trên port trống, ghi PID/port và chỉ quản lý process do phiên này tạo.
3. Nghiệm thu browser E2E với backend/mock provider cục bộ trước: gửi câu hỏi, streaming NDJSON v2, kết thúc stream, hủy request, chuyển phiên/lịch sử, cache hit, provider timeout và fallback. Không dùng E2E mock để kết luận API Jev thật hoạt động hoặc chất lượng câu trả lời tăng.
4. MongoDB/KB/worker: kiểm tra kết nối và tình trạng thực tại môi trường đang chạy bằng thao tác chỉ đọc, giới hạn thời gian. Lưu ý `/health/ready` hiện có thể ghi `operation_audit` và tạo storage probe; không gọi endpoint này nếu phạm vi vẫn yêu cầu không ghi dữ liệu. Không migration, cleanup, reindex, xóa cache hay thay đổi dữ liệu khi chưa có phê duyệt riêng.
5. Chỉ khi người dùng xác nhận môi trường, dữ liệu được phép gửi, model và ngân sách/số request, mới chạy một nhóm truy vấn Jev thật giới hạn. Đối chiếu `request_id`, số HTTP attempt, response/usage, `result_accepted`, `decision_applied` và lý do fallback. So sánh OFF/ASSIST trên cùng tập câu hỏi có đáp án chuẩn; đo độ chính xác, căn cứ trích dẫn, tỷ lệ fallback, latency và chi phí thực tế nếu provider cung cấp. Không đổi mode/config hệ thống đang phục vụ người dùng chỉ để thử nghiệm.
6. Trước deploy, xác nhận đích triển khai, quyền thao tác và rollback. Kiểm tra cấu hình production, secrets, CORS/cookie/TLS, Mongo/Redis/storage/worker, build/run container thực và health của môi trường đích. Không deploy hoặc xoay key khi chưa có phê duyệt.

## Tiêu chí bàn giao

- Test/lint/build/schema mới chạy đạt và có file kết quả làm bằng chứng.
- Luồng chat E2E thực sự được thử trên môi trường ghi rõ; không đếm mock test thành live acceptance.
- Telemetry phân biệt được no-call / HTTP attempt / result accepted / decision applied.
- Không secret/PII trong log, prompt báo cáo, HTML hoặc ảnh chụp.
- Báo cáo rõ từng mục: đã kiểm chứng, chưa kiểm chứng, lỗi còn lại, thao tác đã làm, rủi ro/rollback và bước tiếp theo.
- Xuất một báo cáo HTML tự chứa và evidence JSON. Nếu thiếu quyền, ngân sách hay môi trường, hoàn thành phần offline an toàn rồi hỏi đúng thông tin còn thiếu; không ghi GO production khi chưa có bằng chứng.

## Bổ sung: Vercel + Railway

Khi chuyển sang triển khai, dùng [prompt-deploy-vercel-railway.md](prompt-deploy-vercel-railway.md). Prompt này bám cấu hình repo hiện tại: Vercel build frontend và proxy same-origin `/api`, Railway chạy API/worker riêng, có cổng nghiệm thu staging/production và rollback. Việc bổ sung prompt không có nghĩa hệ thống đã deploy hoặc đã được cấp quyền thao tác production.
