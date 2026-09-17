# Báo Cáo Khảo Sát Baseline Hiện Trạng Dự Án HUIT Chatbot

**Thời gian khảo sát:** 2026-09-15T05:09:26Z  
**Thư mục làm việc:** `D:\chatbot2`  
**Môi trường:** Python 3.11.0, Node.js v24.18.0, MongoDB Atlas (`huit_chatbot`)

---

## 1. Số Liệu Baseline Chính Xác

### 1.1. Bộ Kiểm Thử
- **Backend Unit Tests (pytest):** 74/74 passed (100% offline, 0 failures) trong 15.39s.
- **Frontend Unit Tests (vitest):** 36/36 passed (100% offline) trong 3.04s.
- **Frontend Linter (oxlint):** 0 warnings, 0 errors trên 46 files.
- **Frontend Build (vite build):** Thành công trong 367ms.
- **Git diff whitespace (`git diff --check`):** Sạch (0 lỗi).

### 1.2. Thống Kê Collections MongoDB Atlas
| Collection | Số documents | Ghi chú |
| :--- | :---: | :--- |
| `huit_kb` | 399 | Knowledge base 1024 chiều, vector search index `huit_vector_index` đang READY |
| `assets` | 58 | Physical blob records |
| `artifacts` | 19 | Logical artifact ownership records |
| `jobs` | 23 | Background jobs (12 failed, 11 completed, 0 processing) |
| `generated_images` | 43 | Logical image records |
| `query_cache` | 7 | Cache câu trả lời RAG |
| `rag_events` | 1467 | Nhật ký sự kiện RAG |
| `admission_visuals`| 46 | Sơ đồ tuyển sinh tĩnh |

### 1.3. Khảo Sát Lưu Trữ Vật Lý (`D:\chatbot2\data\artifacts_store`)
- Tổng số assets trong MongoDB: **58**
- **12 assets** không có `storage_key` (chuỗi rỗng `""`): Đều là artifacts ở trạng thái JSON Manifest chưa export.
- **7 assets** có `storage_key` nhưng file vật lý **không tồn tại** trên đĩa:
  - 1 file Excel: `asset_art_ada124a417536719.xlsx`
  - 6 ảnh SVG: `svg_010c7550e6dd76319defe8597a975a3a876ee0ccdc903309.json`, `svg_67fa8cb1aa37326f3831c99c92e18671ae39cd1c25b3473c.json`, `svg_a236bbb2b02fee932a13dc24065bfa7c0a2134a48561c857.json`, `svg_b46df57e14e443d806a9a5fb8f31173693dedf0337dc4d5e.json`, `svg_ef98841cc6d4ef4d782d1f9912bef4d85c50e1aeb147177c.json`, `svg_f6675ccdfda635ac5cc94d4e3e3d13237e23746f01ed7a7c.json`
- **9 orphan files** nằm trên đĩa nhưng không được ánh xạ trong collection `assets`.
- **23/23 jobs** thiếu các trường lease bền vững: `attempt`, `max_attempts`, `idempotency_key`, `available_at`.
- **43/43 ảnh legacy** chưa có `owner_id`, hiện đang mang `access_scope: "legacy_public"`.

---

## 2. Bảng Phân Loại Vấn Đề (P0 / P1 / P2)

| STT | Vấn đề | File & Dòng liên quan | Mức độ | Hướng xử lý |
| :-: | :--- | :--- | :-: | :--- |
| 1 | 19 assets lỗi (12 thiếu key, 7 mất file vật lý) | `backend/app/services/asset_store.py`<br>`data/artifacts_store/` | **P0** | Xây dựng công cụ `storage_reconciliation.py`: re-render deterministic 6 SVG từ `scene`, đánh dấu `unavailable` cho file xlsx mất, chuẩn hóa manifest. |
| 2 | Index `content_hash_1` trên `generated_images` là unique toàn cục, ngăn User B tạo ảnh trùng User A | MongoDB Atlas index `generated_images.content_hash_1`<br>`backend/app/services/image_service.py:440` | **P0** | Gỡ unique toàn cục, chuyển sang compound index `[("owner_id", 1), ("canonical_content_hash", 1)]`. User B tái sử dụng physical `blob_id`. |
| 3 | 23 jobs legacy thiếu `attempt`, `idempotency_key`, `max_attempts`; query claim cho phép bypass retry qua điều kiện OR | `backend/app/services/job_queue.py:70-80`<br>`backend/app/models/mongo_models.py:207` | **P0** | Cập nhật Pydantic `MongoJobRecord`, chuẩn hóa điều kiện claim bắt buộc `attempt < max_attempts`, migration 015 bổ sung field. |
| 4 | Endpoint `/api/auth/session` trả về token trong body JSON thay vì chỉ lưu trong HttpOnly cookie | `backend/app/api/routes/auth.py:28,87` | **P0** | Xóa trường `token` khỏi `SessionResponse`. Token xác thực chỉ lưu trong HttpOnly cookie `huit_session_id`. |
| 5 | Hai hàm `require_admin` phân tán và định nghĩa khác nhau | `backend/app/api/routes/admin.py:10`<br>`backend/app/api/dependencies/auth.py:118` | **P1** | Hợp nhất về `backend.app.api.dependencies.auth.require_admin`. |
| 6 | Streaming response phụ thuộc HTTP connection, reconnect có nguy cơ gọi LLM lần 2 | `backend/app/api/routes/chat.py:62-120`<br>`backend/app/rag/pipeline.py` | **P1** | Tách Producer chạy background, ghi sự kiện vào Redis/Store; reconnect chỉ replay sequence đã sinh, không gọi LLM lại. |
| 7 | Frontend còn các lời gọi `fetch` rải rác không tự động đính kèm CSRF hoặc credentials | `frontend/src/features/artifacts/api/artifactApi.ts`<br>`frontend/src/shared/utils/auth.ts` | **P1** | Tạo `httpClient.ts` dùng chung toàn frontend, tự động quản lý CSRF và cookie session. |
| 8 | Endpoint `/health/ready` chưa kiểm tra worker heartbeat | `backend/app/api/routes/health.py:94-115` | **P1** | Bổ sung kiểm tra worker heartbeat, fail-fast 503 khi thiếu dependencies trong production. |
| 9 | 9 orphan files trên đĩa chưa được dọn dẹp hoặc đối soát | `data/artifacts_store/` | **P2** | Đối soát hash trong `storage_reconciliation.py`. |
| 10 | `README.md` còn ghi số lượng test cũ (27-42 tests) | `README.md:33,112` | **P2** | Cập nhật lại số liệu chính xác sau khi hoàn thiện. |
