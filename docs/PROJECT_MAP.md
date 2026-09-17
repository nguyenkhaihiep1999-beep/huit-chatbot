# HUIT CHATBOT - BẢN ĐỒ DỰ ÁN (PROJECT MAP)

Tài liệu này cung cấp bản đồ chi tiết toàn bộ các chức năng chính, điểm bắt đầu, route API, schema database, renderer, queue, storage, cache và kiểm thử của dự án Chatbot HUIT sau khi nâng cấp mô hình **"mô tả nhẹ – dựng nội dung khi cần"**.

---

## 1. Bảng Tra Cứu Chức Năng Chính & Vị Trí Code

| Chức năng | Thư mục / File hiện tại | Điểm bắt đầu (Entrypoint / Symbol) | Phụ thuộc chính | Muốn sửa thì đọc file nào? |
| :--- | :--- | :--- | :--- | :--- |
| **Frontend UI Chat** | `frontend/src/features/chat/` | `frontend/src/app/App.tsx`<br>`ChatWindow.tsx` | React 19, Marked, Lucide | [ChatWindow.tsx](../frontend/src/features/chat/components/ChatWindow.tsx)<br>[ChatMessageItem.tsx](../frontend/src/features/chat/components/ChatMessageItem.tsx) |
| **Trang Quản Trị Hệ Thống (/admin)** | `frontend/src/features/admin/`<br>`backend/app/api/routes/admin.py` | `AdminPage.tsx`<br>`useAdminAuth.ts`<br>`useAdminDashboard.ts` | HttpOnly Cookie, CSRF Token, Zero-Token LocalStorage, Audit Sanitizer | [AdminPage.tsx](../frontend/src/features/admin/components/AdminPage.tsx)<br>[useAdminAuth.ts](../frontend/src/features/admin/hooks/useAdminAuth.ts)<br>[admin.py](../backend/app/api/routes/admin.py) |
| **Thẻ Artifact & Lightbox** | `frontend/src/features/artifacts/` | `ArtifactCard.tsx`<br>`ArtifactLightbox.tsx` | Preview nhỏ mặc định, Upscale On-Demand, Export Word/Excel/PDF, Anti-Double-Click | [ArtifactCard.tsx](../frontend/src/features/artifacts/components/ArtifactCard.tsx)<br>[ArtifactLightbox.tsx](../frontend/src/features/artifacts/components/ArtifactLightbox.tsx) |
| **NDJSON Streaming Canonical v2** | `backend/app/api/routes/chat.py`<br>`frontend/src/features/chat/` | `handle_chat_stream()` (`/api/chat-stream`)<br>`useChatStream.ts` | Tập event canonical (`start`, `token`, `progress`, `artifact`, `error`, `done`), Monotonic sequence, Resume Buffer | [chat.py](../backend/app/api/routes/chat.py)<br>[useChatStream.ts](../frontend/src/features/chat/hooks/useChatStream.ts)<br>[ndjsonParser.ts](../frontend/src/features/chat/utils/ndjsonParser.ts) |
| **Bảo mật & Phân quyền Principal** | `backend/app/api/dependencies/auth.py`<br>`backend/app/services/auth_service.py` | `get_current_principal()`<br>`generate_download_signature()` | Session signing, HMAC token, HttpOnly Cookie, No X-User-ID bypass | [auth.py](../backend/app/api/dependencies/auth.py)<br>[auth_service.py](../backend/app/services/auth_service.py) |
| **Giới hạn tần suất (Rate Limiter)** | `backend/app/middleware/rate_limiter.py` | `RateLimitMiddleware` | Redis / In-memory token bucket, 429 status code | [rate_limiter.py](../backend/app/middleware/rate_limiter.py) |
| **Artifact API & Export** | `backend/app/api/routes/artifacts.py` | `POST /api/artifacts/plan`<br>`POST /api/artifacts/render`<br>`GET /api/artifacts/{id}/preview`<br>`GET /api/artifacts/{id}/file`<br>`POST /api/artifacts/{id}/export` | `artifact_service.py`, `AssetStore` | [artifacts.py](../backend/app/api/routes/artifacts.py) |
| **Registered Operations Gateway v2** | `backend/app/data_access/` | `operation_gateway.py`<br>`registered_operations/` | 50 Registered Operations v2, 100% Zero raw MongoDB calls, checksum, timeout max_time_ms, read/write isolation, Pydantic strict schemas (extra="forbid"), BSON Date validation | [operation_gateway.py](../backend/app/data_access/operation_gateway.py) |
| **Nhận diện ý định sinh file** | `backend/app/rag/artifact_intent.py` | `detect_file_generation_intent()`<br>`should_attach_illustrative_infographic()` | `intent.py` | [artifact_intent.py](../backend/app/rag/artifact_intent.py) |
| **Điều phối Artifact** | `backend/app/services/artifact_service.py` | `create_artifact_plan()`<br>`resolve_artifact_for_chat()` | `AssetStore`, Renderers | [artifact_service.py](../backend/app/services/artifact_service.py) |
| **Asset Store & Deduplication** | `backend/app/services/asset_store.py` | `AssetStore.find_by_hash()`<br>`AssetStore.save_asset()`<br>`compute_canonical_hash()`<br>`compute_derivative_hash()` | MongoDB `assets`, `data/artifacts_store/` | [asset_store.py](../backend/app/services/asset_store.py) |
| **Hàng đợi tác vụ bền vững (Job Queue)** | `backend/app/services/job_queue.py` | `JobQueueManager.create_job()`<br>`JobQueueManager.get_job()`<br>`JobQueueManager.cancel_job()` | MongoDB Lease Queue, RAM fallback, Backoff retry | [job_queue.py](../backend/app/services/job_queue.py) |
| **Trình dựng Word (.docx)** | `backend/app/services/docx_renderer.py` | `render_manifest_to_docx()` | `python-docx` | [docx_renderer.py](../backend/app/services/docx_renderer.py) |
| **Trình dựng PDF (.pdf)** | `backend/app/services/pdf_renderer.py` | `render_manifest_to_pdf()` | `reportlab` | [pdf_renderer.py](../backend/app/services/pdf_renderer.py) |
| **Trình dựng Excel (.xlsx)** | `backend/app/services/visual_service.py` | `export_visual_to_excel()` | `openpyxl` | [visual_service.py](../backend/app/services/visual_service.py) |
| **Trình dựng SVG & Raster** | `backend/app/services/visual_service.py` | `render_svg_visual()`<br>`render_raster_visual()` | `Pillow (PIL)`, Vector template | [visual_service.py](../backend/app/services/visual_service.py) |
| **Mã lỗi & Tracing** | `backend/app/telemetry/errors.py` | `ArtifactException`<br>`ERROR_*` constants (Sanitized stack trace) | Request ID middleware | [errors.py](../backend/app/telemetry/errors.py)<br>[logger.py](../backend/app/telemetry/logger.py) |
| **MongoDB Document Models & Strict Validators** | `backend/app/models/mongo_models.py` | `MongoAssetRecord`, `MongoArtifactRecord`, `MongoJobRecord`, `MongoGeneratedImageRecord`... | Pydantic v2, Strict $jsonSchema, extra="forbid" | [mongo_models.py](../backend/app/models/mongo_models.py) |
| **Durable Storage Adapter** | `backend/app/storage/storage_adapter.py` | `LocalStorageAdapter`, `ObjectStorageAdapter`, `validate_safe_storage_key()` | Chống Path Traversal, SHA-256 Checksum, Không phụ thuộc Vercel tmp | [storage_adapter.py](../backend/app/storage/storage_adapter.py) |
| **Bộ nhớ đệm (Cache)** | `backend/app/cache/` | `MemoryCache` (RAM 0ms)<br>`CacheManager` (MongoDB Atlas) | `collections.OrderedDict`, PyMongo | [memory_cache.py](../backend/app/cache/memory_cache.py)<br>[mongo_cache.py](../backend/app/cache/mongo_cache.py) |
| **Kiểm thử tự động** | `backend/tests/`<br>`frontend/tests/` | Pytest (184 tests, 100% pass)<br>Vitest (67 tests, 100% pass) | `pytest`, `vitest`, `oxlint` | [test_final_architecture_hardening.py](../backend/tests/test_final_architecture_hardening.py)<br>[test_streaming_protocol_v2.py](../backend/tests/test_streaming_protocol_v2.py)<br>[adminWorkflow.test.tsx](../frontend/tests/adminWorkflow.test.tsx) |

---

## 2. Điểm Bắt Đầu Của Ứng Dụng (Entrypoints)

### Backend (Python FastAPI):
- **Entrypoint**: `backend.app.main:app`
- Khởi động:
  ```bash
  python -m uvicorn backend.app.main:app --host 0.0.0.0 --port 8000 --reload
  ```
- **File cấu hình chính**: [backend/app/config.py](../backend/app/config.py) (đọc `.env` độc lập).
- **Routers**: Đăng ký tại [backend/app/main.py](../backend/app/main.py):
  - `/api/chat`, `/api/chat-stream` ([chat.py](../backend/app/api/routes/chat.py))
  - `/api/artifacts/*`, `/api/jobs/*` ([artifacts.py](../backend/app/api/routes/artifacts.py))
  - `/api/admission-visuals/*` ([visuals.py](../backend/app/api/routes/visuals.py))
  - `/api/images/*` ([images.py](../backend/app/api/routes/images.py))
  - `/api/admin/*` ([admin.py](../backend/app/api/routes/admin.py))
  - `/api/auth/*` ([auth.py](../backend/app/api/routes/auth.py))
  - `/health` ([health.py](../backend/app/api/routes/health.py))

### Frontend (React 19 + TypeScript + Vite):
- **Entrypoint**: `frontend/src/main.tsx` $\rightarrow$ `frontend/src/app/App.tsx`
- Khởi động:
  ```bash
  cd frontend
  npm run dev
  ```
- Proxy API: Tất cả request `/api/*` từ `http://localhost:3000` được proxy sang backend FastAPI `http://localhost:8000`.

---

## 3. Schema Database & Lưu Trữ (Storage Layout)

### Collections trên MongoDB Atlas (`huit_chatbot`):
1. **`assets`**:
   - `_id` / `asset_id`: Mã định danh asset (`art_xxx`).
   - `content_hash`: SHA-256 canonical hash chống trùng. Unique index.
   - `media_type`: MIME type chuẩn (`application/pdf`, `image/svg+xml`, `application/vnd.openxmlformats-officedocument.wordprocessingml.document`...).
   - `storage_key`: Tên file vật lý an toàn trong `StorageAdapter` (mặc định `artifacts_store/`).
   - `reference_count`: Số lần tái sử dụng.
   - `created_at`, `last_accessed_at`: BSON Date UTC.
2. **`jobs`**:
   - `_id` / `job_id`: Mã định danh công việc nền. Unique index.
   - `action`: render, upscale, export...
   - `artifact_id`, `format`, `status` (`queued`, `processing`, `completed`, `failed`, `cancelled`).
   - `progress`: 0..100%.
   - `events`: Danh sách tối đa 30 mốc trạng thái kèm timestamp UTC và chi tiết.
   - `owner_id`: Chủ sở hữu job.
   - `expires_at`: TTL BSON Date (sau 7 ngày).
3. **`generated_images`**: Metadata ảnh sinh AI (FLUX/SVG, không chứa Base64 hay binary lớn).
4. **`huit_kb`**: Tri thức tuyển sinh HUIT (Vector 1024D `intfloat/multilingual-e5-large` + Text chunks).
5. **`admission_visuals`**: Danh mục đồ họa tuyển sinh 39 ngành đào tạo.
6. **`rag_events`**: Nhật ký truy vấn bảo mật (SHA-256 câu hỏi, latency 10 số đo).

### Thư mục lưu trữ vật lý an toàn:
- `data/artifacts_store/`: Lưu trữ các file nhị phân (`.xlsx`, `.docx`, `.pdf`, `.png`, `.webp`) được đặt tên theo quy ước `asset_{asset_id}.{ext}` thông qua `StorageAdapter`. Tuyệt đối không dùng tên file do người dùng nhập làm path để loại trừ rủi ro Path Traversal. Khử trùng vật lý (Deduplication byte-level) bằng SHA-256.
