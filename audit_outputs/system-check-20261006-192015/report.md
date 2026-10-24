# Kiểm tra hệ thống hiện tại — 06/10/2026

Kết luận: bản mã hiện tại đạt các kiểm tra offline đã chạy. Chưa đủ bằng chứng để nghiệm thu luồng chạy thật hoặc kết luận production-ready. Không tiếp tục thay đổi kiến trúc trong lượt kiểm tra này.

## Kết quả chạy lại độc lập

- Backend: **551 passed**, 0 failed/error/skipped; JUnit 94.613 giây, 34 warnings.
- Frontend: **126 passed / 16 file**, 0 failed/error/skipped; thời gian công cụ báo 9.45 giây.
- Frontend lint và production build: exit code 0.
- Schema sync: 18 hợp đồng frontend và manifest đồng bộ, chỉ chạy `--check`.
- Secret scan: xem `secret-scan.json` để lấy số file và số phát hiện chính xác. Không phát hiện secret thật trong phạm vi quét working tree; chưa kiểm tra lịch sử Git hay image đã deploy.
- Nhóm Jev assist: 21 ca đạt; nhóm production infrastructure: 6 ca đạt.
- Lỗi test mạng worker của lần trước đã được giải quyết: test hiện chấp nhận worker trên frontend_net + backend_net, vẫn kiểm tra worker không publish host port. Chưa chạy container thực tế.

## Một lỗi telemetry được tái hiện

**P2 — Có thể đếm nhầm số lần gọi API Jev.**

`backend/app/rag/pipeline.py:254` đặt `api_called=True` trước khi gọi service. Nếu thời gian chờ làm budget không còn đủ trước khi provider được gọi, service có thể trả `None`; nhánh tại dòng 314 ghi `provider_empty_response` mà không đổi cờ về false.

Probe `probe_jev_pre_call_budget.py` sử dụng fixture offline đang có của dự án, chặn transport HTTP/Mongo thật, dữ liệu tổng hợp và độ trễ lập lịch được chèn có kiểm soát:

- Budget hợp lệ: 100 ms; độ trễ lập lịch chèn: 65 ms.
- Request tới provider quan sát được: **0**.
- Telemetry pipeline: **api_called=true**, `apply_reason=provider_empty_response`.
- `decision_applied=false`; chat vẫn kết thúc bình thường bằng luồng baseline.

Đây là lỗi độ chính xác của bằng chứng vận hành, không phải bằng chứng chat bị hỏng. Nếu dùng telemetry để báo cáo mức tham gia của Jev hoặc chi phí, số liệu có thể cao hơn thực tế. Nên lấy cờ attempted/actual call từ tracker/provider thay vì suy luận từ chuỗi lỗi; bổ sung regression test cho trường hợp hết budget trước khi gọi. Chưa sửa mã trong lượt này.

## Trạng thái runtime và cấu hình

Probe lúc 19:26:52 +07:

- Backend `127.0.0.1:8000/health/live`: **HTTP 200**. Chỉ chứng minh process đang sống, không chứng minh Mongo/KB/Jev sẵn sàng.
- Frontend dev `127.0.0.1:3000`: chưa truy cập được từ môi trường kiểm tra; có thể dev server chưa bật hoặc đang dùng địa chỉ khác. Không kết luận frontend hỏng.
- MongoDB: chỉ thử direct `ping` với timeout ngắn, không qua operation gateway; chưa xác minh thành công, loại lỗi `ConfigurationError`. Chưa xác định nguyên nhân, không suy ra database của backend đang hỏng.
- Không gọi `/health/ready` vì handler có thể ghi `operation_audit` và tạo probe storage.
- Docker CLI không sẵn có trong môi trường kiểm tra; chưa build/run image hoặc xác minh mạng container thực tế.

Cấu hình đọc từ file hiện tại: development, Jev **assist**, model **jev-latest**, có key, chưa cấu hình Redis, local embeddings bật. Không in giá trị key/URI/password. Cấu hình file không chứng minh backend đang chạy đã reload bản mới; lần này không gọi API Jev thật.

## Việc nên làm tiếp

1. Sửa sai lệch `api_called` và thêm regression test cho pre-provider timeout/budget exhaustion.
2. Xác nhận frontend đang chạy ở URL/port nào; kiểm tra chat streaming và fallback end-to-end cùng backend hiện tại.
3. Kiểm tra Mongo/KB/worker tại môi trường chạy thực, rồi chạy một nhóm truy vấn Jev thật có giới hạn chi phí. Chỉ sau đó mới nghiệm thu release/deploy.

34 warnings của backend chủ yếu gồm deprecation và cảnh báo pooling của FastEmbed. Cảnh báo pooling cần đối chiếu với cách tạo vector KB trước release; chưa chứng minh có lỗi retrieval và không tự ý reindex.

## Bằng chứng và phạm vi

- `backend-tests.xml`, `frontend-tests.xml`: kết quả test thô.
- `secret-scan.json`: kết quả scan working tree.
- `evidence.json`: metadata, kết quả probe, hash SHA-256 của các file liên quan.
- `probe_jev_pre_call_budget.py`: ca tái hiện offline.
- `probe_runtime_readonly.py`: probe liveness HTTP và Mongo ping chỉ đọc.

HEAD: `3f338839fcbec4d1337ae10378d9c78c69350127`; working tree đang có nhiều thay đổi chưa commit. Báo cáo này đánh giá nội dung working tree tại thời điểm kiểm tra, không chỉ commit HEAD.

Không sửa application/test source, không ghi/xóa Mongo, không chạy migration, không gọi API trả phí, không restart server và không deploy. Chỉ tạo bằng chứng kiểm tra và chạy test/lint/build/schema/scan; frontend build output được tạo lại.
