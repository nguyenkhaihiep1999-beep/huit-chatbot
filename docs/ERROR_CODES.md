# HỆ THỐNG MÃ LỖI TẬP TRUNG (ERROR CODES SPECIFICATION)

Tài liệu này định nghĩa toàn bộ danh mục mã lỗi có cấu trúc trong hệ thống Artifact Pipeline của HUIT Chatbot, giúp lập trình viên và hệ thống telemetry xác định chính xác nguyên nhân, vị trí và khả năng thử lại (retryable).

---

## 1. Cấu Trúc Lỗi Chuẩn (Structured Error Payload)

Mọi phản hồi lỗi trả về client hoặc ghi nhận vào hệ thống telemetry/logging đều tuân theo schema JSON:

```json
{
  "error_code": "ARTIFACT_RENDER_FAILED",
  "message": "Không thể tạo bản xem trước đồ họa tuyển sinh",
  "request_id": "req_8cf271ab9e10",
  "job_id": "job_3a8b29c0",
  "artifact_id": "art_2026_tuition_table",
  "stage": "preview_render",
  "module": "artifact_service",
  "retryable": true,
  "details": {
    "reason": "Temporary storage busy",
    "attempt": 1
  }
}
```

### Chi tiết các trường:
| Trường | Kiểu dữ liệu | Ý nghĩa |
| :--- | :--- | :--- |
| `error_code` | `string` | Mã lỗi định danh duy nhất trong danh mục |
| `message` | `string` | Thông điệp thông báo thân thiện cho người dùng |
| `request_id` | `string` | Mã tương quan request (`X-Request-ID`) để truy vết log |
| `job_id` | `string \| null` | Mã công việc nền nếu lỗi phát sinh từ background queue |
| `artifact_id` | `string \| null` | Mã định danh của artifact liên quan |
| `stage` | `string` | Giai đoạn xảy ra lỗi: `intent_parsing`, `manifest_validation`, `preview_render`, `job_execution`, `export` |
| `module` | `string` | Tên module hoặc service phát sinh lỗi |
| `retryable` | `boolean` | `true` nếu lỗi có tính tạm thời và có thể tự động thử lại |
| `details` | `object` | Thông tin kỹ thuật chi tiết (chỉ lưu server log, không rò rỉ dữ liệu nhạy cảm) |

---

## 2. Bảng Danh Mục Mã Lỗi Tập Trung

| Mã lỗi (`error_code`) | HTTP Status | Retryable | Nguyên nhân thường gặp | Hành động xử lý |
| :--- | :---: | :---: | :--- | :--- |
| **`ARTIFACT_INVALID_MANIFEST`** | 400 | False | JSON manifest vượt quá 32KB, sai cấu trúc schema, chứa Base64 lớn hoặc vượt quá 100 dòng. | Kiểm tra lại validator tại `backend/app/api/schemas/artifact.py`. |
| **`ARTIFACT_NOT_FOUND`** | 404 | False | Không tìm thấy `artifact_id` trong cả RAM Cache và MongoDB Atlas. | Kiểm tra lại `artifact_id` hoặc tạo mới qua `/api/artifacts/plan`. |
| **`ARTIFACT_ACCESS_DENIED`** | 403 | False | Người dùng yêu cầu tài nguyên không thuộc quyền sở hữu của họ (`owner_id` không khớp). | Xác thực lại `user_id` / `session_id` hoặc cấp quyền qua token admin. |
| **`ARTIFACT_RENDER_FAILED`** | 500 | True | Quá trình render vector SVG hoặc raster gặp lỗi thư viện đồ họa hoặc thiếu font. | Kiểm tra đường dẫn font trong `visual_service.py` và retry tác vụ. |
| **`ARTIFACT_UPSCALE_FAILED`** | 500 | True | Upscale 2x/4x gặp lỗi phân bổ bộ nhớ hoặc xử lý ảnh PIL. | Kiểm tra dung lượng RAM server và hệ số `scale` (tối đa 4x). |
| **`ASSET_STORAGE_FAILED`** | 500 | True | Không thể ghi file nhị phân vào thư mục lưu trữ `artifacts_store` (hết đĩa, phân quyền). | Kiểm tra quyền ghi thư mục `data/artifacts_store/`. |
| **`ASSET_DUPLICATE_DETECTED`** | 200/409 | False | Phát hiện asset có `content_hash` trùng lặp trong kho lưu trữ. | Hệ thống tự động tái sử dụng `asset_id` cũ thay vì sinh mới. |
| **`EXPORT_FAILED`** | 500 | True | Lỗi trong quá trình build file Word (`python-docx`), Excel (`openpyxl`) hoặc PDF (`reportlab`). | Đọc stack trace server tại `docx_renderer.py`, `pdf_renderer.py`. |
| **`JOB_TIMEOUT`** | 504 | True | Tác vụ nền trong queue vượt quá thời gian xử lý tối đa (timeout). | Kiểm tra hàng đợi tại `job_queue.py` và giảm tải cho renderer. |
| **`FILE_TOO_LARGE`** | 413 | False | File xuất vượt quá ngưỡng an toàn tối đa cho phép (50MB). | Giới hạn số lượng hàng hoặc giảm độ phân giải raster. |
| **`UNSUPPORTED_FILE_TYPE`** | 400 | False | Yêu cầu định dạng xuất không nằm trong danh sách hỗ trợ (`xlsx`, `docx`, `pdf`, `png`, `svg`, `webp`). | Chỉ định định dạng hợp lệ theo schema. |
| **`DATABASE_INDEX_CONFLICT`** | 500 | False | Xung đột cấu hình Index cũ/mới (MongoDB Code 85/86) khi thay đổi options unique/TTL. | Kiểm tra lại index trên Atlas và chạy script drop index cũ trước khi cập nhật. |
| **`DATABASE_DUPLICATE_KEY`** | 409 | False | Phát hiện khóa trùng lặp (MongoDB Code 11000) khi tạo unique index hoặc insert document. | Chạy script deduplication (003) trước khi áp dụng unique index. |
| **`DATABASE_VALIDATION_FAILED`** | 400 | False | Document vi phạm MongoDB `$jsonSchema` validator (thiếu trường, sai kiểu ngày, chứa Base64). | Đối chiếu document với Pydantic model trong `mongo_models.py`. |
| **`DATABASE_NOT_READY`** | 503 | True | Cơ sở dữ liệu chưa sẵn sàng hoặc thiếu các unique indexes cốt lõi khi khởi động. | Kiểm tra kết nối cụm Atlas qua `check_database_readiness()`. |
| **`STORAGE_TRAVERSAL_ATTEMPT`** | 400 | False | Khóa storage chứa ký tự nguy hiểm (`..`, `/`, `\`) có nguy cơ tấn công Path Traversal. | Kiểm tra lại hàm `validate_safe_storage_key()`. |
| **`STORAGE_INTEGRITY_MISMATCH`** | 500 | False | Mã băm SHA-256 của file nhị phân lưu trữ không khớp với checksum đã đăng ký. | Kiểm tra tính toàn vẹn của tệp trong StorageAdapter. |
| **`STORAGE_BLOB_IN_USE`** | 409 | False | Cố gắng xóa file vật lý trong khi vẫn còn artifact hoặc job tham chiếu (`reference_count > 0`). | Chỉ xóa khi không còn bản ghi nào trỏ tới. |

---


## 3. Quy Trình Chẩn Đoán Lỗi Nhanh

1. Lấy `request_id` từ header phản hồi `X-Request-ID` hoặc trường `request_id` trong JSON lỗi.
2. Tìm kiếm trong server logs:
   ```bash
   grep "req_xxxx" backend_logs.txt
   ```
3. Xác định `stage` và `module` nơi phát sinh lỗi.
4. Đối chiếu mã lỗi với bảng trên để thực hiện biện pháp khắc phục nhỏ nhất.
