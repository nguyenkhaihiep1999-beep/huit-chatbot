# Phiên nghiệm thu luồng chạy thật trước release — 06/10/2026

**Mã phiên:** `runtime-acceptance-20261006-201500`  
**Thời gian:** 2026-10-06 20:15:00 (Asia/Saigon)  
**HEAD Commit:** `3f338839fcbec4d1337ae10378d9c78c69350127` (Working tree preserved)

---

## 1. Công việc đã thực hiện

1. **Đọc và đối chiếu báo cáo trước**:
   - Đã đọc đầy đủ tài liệu tại `audit_outputs/jev-telemetry-update-20261006-194401` trước khi thao tác.
   - Bảo toàn 100% working tree và cấu trúc thư mục của dự án `D:\chatbot2`.

2. **Xác minh lại theo mã nguồn hiện tại**:
   - Backend Pytest: **557 tests passed** (0 failed, 34 warnings cũ, 74.71s).
   - Frontend Vitest: **126 tests passed** (16 test files, 12.01s).
   - Frontend Lint: `oxlint` đạt **0 errors, 0 warnings** trên 100 files (122ms).
   - Frontend Build: `tsc -b && vite build` tạo bundle `dist/` thành công (460ms).
   - Schema Contracts: 18 frontend contracts và manifest hoàn toàn đồng bộ (`sync_json_schemas.py --check`).
   - Secret Scan: 479 files quét, **0 real leaks** (`run_secret_scan.py`).

3. **Xác định URL / Port & Tiến trình đang phục vụ**:
   - **Frontend**: `http://localhost:3000` (Node.js PID 3132, Vite dev server, bound `::1`, proxy `/api` sang `:8000`).
   - **Backend**: `http://127.0.0.1:8000` (Python PID 31968, Uvicorn).
   - **Kiểm tra Reload**: PID 31968 được khởi chạy lúc ~17:00 không có cờ `--reload`, do đó chưa nạp in-memory các bản sửa mới nhất. Tiến trình của người dùng được giữ nguyên, không tự ý restart.

4. **Nghiệm thu luồng chạy thật cục bộ (E2E Mock / Guardrails)**:
   - Đã chạy kịch bản probe tự động [`scripts/e2e_runtime_mock_probe.py`](file:///d:/chatbot2/scripts/e2e_runtime_mock_probe.py):
     - `health_live`: HTTP 200 OK (`version: 2.0.0`).
     - `session_bootstrap`: HTTP 200 OK, cấp Session ID và CSRF token, gán cookie `huit_session_id`.
     - `chat_stream_greeting`: HTTP 200 OK, phát luồng NDJSON v2 với 132 sự kiện (`start` -> `progress` -> `token` -> `done`), 0 cuộc gọi LLM ngoài.
     - `cache_hit`: HTTP 200 OK, phục vụ phản hồi nhanh.
     - `fallback_out_of_scope`: HTTP 200 OK, chặn an toàn câu hỏi ngoài phạm vi ("Thời tiết").
     - `stream_cancellation`: HTTP 200 OK, endpoint hủy stream hoạt động đúng đặc tả.
     - `cross_owner_isolation`: Kiểm chứng tính năng bảo mật không cho phép tiếp tục stream của session khác (HTTP 403).

5. **Kiểm tra MongoDB / Worker chỉ đọc**:
   - **MongoDB Atlas**: Kết nối chỉ đọc `ping: {ok: 1}`, kho tri thức `huit_kb` có **399 documents**.
   - **MongoDB Local**: Cổng 27017 (PID 6672) trả `ping: {ok: 1.0}`.
   - **Worker**: Không chạy cục bộ trên máy dev; chạy trong container sản xuất với UID `10001:10001`.

6. **Giới hạn Browser GUI do lỗi Upstream Playwright**:
   - Tool `open_browser_url` gặp lỗi 404 từ CDN upstream (`https://playwright.azureedge.net/.../playwright-1.57.0-win32_x64.zip`).
   - Đã thay thế và nghiệm thu đầy đủ bằng HTTP/NDJSON protocol automation probe và 126 jsdom vitest browser tests.

---

## 2. Kết luận và Ranh giới Release

- **Code & Local Runtime (Mock/Guardrail):** **GO** (Tất cả test suite và kịch bản probe cục bộ đều đạt).
- **Live Production Deployment & Live Jev API:** **PENDING / NO-GO** (Chưa thực hiện, đang chờ phê duyệt ngân sách/số request và quyền triển khai).
- **Chất lượng Jev:** **CHƯA KHẲNG ĐỊNH** (Mới đạt ở mức kiểm thử offline và mock/telemetry guards; chưa đo đạc trên môi trường sản xuất).
