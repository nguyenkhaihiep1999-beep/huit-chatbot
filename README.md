# 🎓 HUIT CHATBOT - HỆ THỐNG TRỢ LÝ AI TƯ VẤN TUYỂN SINH TRƯỜNG ĐẠI HỌC CÔNG THƯƠNG TP.HCM

Dự án Chatbot RAG thông minh phục vụ tư vấn tuyển sinh, tra cứu ngành học, điểm sàn, điểm chuẩn, học phí và chính sách học bổng cho Trường Đại học Công Thương TP.HCM (HUIT).

Dự án đã được tái cấu trúc toàn diện theo kiến trúc **Modular Clean Architecture** cho Backend và **React + TypeScript (Feature-based Custom Hooks)** cho Frontend.

---

## 📁 Cấu Trúc Dự Án Sau Tái Cấu Trúc

```text
D:\chatbot2\
├── backend/                         # Backend Python FastAPI (Modular Architecture)
│   ├── app/
│   │   ├── main.py                  # Entrypoint chính: backend.app.main:app
│   │   ├── config.py                # Quản lý cấu hình tập trung từ .env (Hoàn toàn độc lập)
│   │   ├── api/
│   │   │   ├── routes/              # Endpoints: chat, visuals, images, admin, auth, health
│   │   │   └── schemas/             # Pydantic models xác thực dữ liệu & streaming v2 canonical
│   │   ├── rag/                     # Lõi RAG phân tách theo trách nhiệm
│   │   │   ├── pipeline.py          # stream_answer() NDJSON canonical v2 & answer()
│   │   │   ├── intent.py            # Phân loại ý định, query expansion, chuẩn hóa telex
│   │   │   ├── guardrails.py        # Guardrails chào hỏi, cá nhân, catalog (độc lập DB)
│   │   │   ├── embedding.py         # FastEmbed multilingual-e5-large (1024D)
│   │   │   ├── retrieval.py         # Hybrid Vector Search (MongoDB Atlas) + Sparse Regex
│   │   │   ├── reranker.py          # RRF scoring, Heuristic overrides, latency spans
│   │   │   └── generation.py        # Multi-provider LLM (Gemini -> Groq -> OpenRouter)
│   │   ├── services/                # Nghiệp vụ: artifact_service, asset_store, job_queue, visual_service, image_service
│   │   ├── middleware/              # RateLimiter middleware, Request ID context
│   │   ├── repositories/            # Kết nối MongoDB Atlas singleton & unique indexes
│   │   ├── data_access/             # Registered Operations Gateway v2 (100% zero raw calls)
│   │   ├── cache/                   # Bộ nhớ đệm 2 cấp: RAM Cache (0ms) & Mongo Cache
│   │   └── telemetry/               # Gắn Request ID, 10 số đo Latency breakdown, structured logger
│   └── tests/                       # 184 Pytest tests (100% PASSED)
│
├── frontend/                        # Frontend React + TypeScript (Vite)
│   ├── src/
│   │   ├── app/App.tsx              # Entrypoint ứng dụng chính & routing SPA (/ và /admin)
│   │   ├── main.tsx                 # Khởi tạo React DOM client
│   │   ├── features/                # Chia module theo Feature nghiệp vụ
│   │   │   ├── chat/                # ChatWindow, useChatStream (NDJSON Protocol v2, buffer 35ms), useConversation
│   │   │   ├── admin/               # Trang quản trị /admin: useAdminAuth (HttpOnly cookie), useAdminDashboard
│   │   │   ├── history/             # Quản lý lịch sử phiên (useChatHistory, HistoryDrawer)
│   │   │   ├── voice/               # Web Speech API (STT / TTS)
│   │   │   ├── admission-visuals/   # Sơ đồ SVG tuyển sinh & Lightbox (Upscale On-Demand, Export Word/Excel/PDF)
│   │   │   ├── image-generation/    # Modal sinh ảnh AI mascot
│   │   │   └── theme/               # Dark / Light theme tokens
│   │   ├── shared/                  # Components, hooks, lib (markdown.ts sanitized, idGenerator)
│   │   ├── observability/           # Telemetry tracker đo Content TTFT, flushes, render cost
│   │   └── styles/                  # Design tokens HUIT, admin.css, visuals.css, chat.css
│   ├── tests/                       # 67 Vitest tests trên 9 test suites (100% PASSED, 0 lint warnings)
│   ├── public/                      # Robot mascot robot_huit.webp (2.3KB) & robot_huit.png (12.4KB)
│   └── package.json
│
├── data/                            # File tài nguyên JSON chuẩn hóa (centroids, modules, artifact store)
├── docs/
│   ├── CODE_MAP.md                  # Bản đồ điều hướng mã nguồn & "Muốn sửa gì vào đâu"
│   ├── PERFORMANCE.md               # Báo cáo đo lường hiệu năng & phân tích bottleneck
│   └── PRODUCT_RELEASE_READINESS_2026-09-15.md
├── .github/workflows/ci.yml         # CI: backend, frontend và hợp đồng Docker Compose
├── deploy/nginx.conf                # SPA fallback + reverse proxy không buffer NDJSON
├── Dockerfile.frontend              # Build React và phục vụ bằng Nginx unprivileged
├── docker-compose.yml               # Frontend + API + worker + MongoDB + Redis
├── requirements.txt                 # Danh mục thư viện phụ thuộc backend
├── vercel.json                      # Cấu hình tham chiếu; không đủ worker nếu deploy full-stack đơn lẻ
└── README.md
```

---

## 🚀 Hướng Dẫn Cài Đặt & Chạy Ứng Dụng Cục Bộ

### 1. Cài Đặt Môi Trường

#### Yêu cầu:
- **Python**: 3.10+ (Đã kiểm thử ổn định trên Python 3.11.0)
- **Node.js**: 20+ (Đã kiểm thử ổn định trên Node.js v24.18.0)

#### Cài đặt thư viện:
```bash
# Cài đặt thư viện Backend
pip install -r requirements.txt

# Cài đặt thư viện Frontend
cd frontend
npm install
cd ..
```

---

### 2. Khởi Động Ứng Dụng (Local Development)

#### Backend (FastAPI):
- **Entrypoint**: `backend.app.main:app`
```bash
python -m uvicorn backend.app.main:app --host 0.0.0.0 --port 8000 --reload
```
- Swagger UI Documentation: `http://localhost:8000/docs`
- Health check endpoint: `http://localhost:8000/health`

#### Frontend (React + Vite):
- **Entrypoint**: `frontend/src/main.tsx` $\rightarrow$ `frontend/src/app/App.tsx`
```bash
cd frontend
npm run dev
```
- Truy cập giao diện tại: `http://localhost:3000` (Tất cả request `/api/*` được tự động proxy sang backend `localhost:8000`).

---

## 🧪 Kết Quả Kiểm Thử (Tests & Lint)

### 1. Backend Tests (Pytest)
```bash
python -m pytest backend/tests -q
```
**Kết quả thực tế ngày 2026-09-16**: `184 passed, 0 failed` trong 25,87 giây (test mặc định chạy offline bằng mock).
> [!NOTE]
> **Phân loại kiểm thử**: 100% test backend là unit/mock test, hoàn toàn không gọi database MongoDB live hay external LLM API thật trong quá trình chạy test mặc định.
- **Root & Health Check**: Trạng thái hệ thống chi tiết (MongoDB, Storage, Memory), trả về mã 200 khi healthy và 503 khi degraded kèm cấu trúc JSON nhất quán.
- **CSRF & HttpOnly Cookie Session**: Session ID lưu trong HttpOnly cookie, CSRF token truyền qua header `X-CSRF-Token` cho mọi mutating request (`POST`/`PUT`/`DELETE`). Chặn rò rỉ token qua JSON body.
- **Admin Authentication Hardening**: HttpOnly cookie session với opaque random token, server-side hashed session storage, cấm rò rỉ token trong JSON response. Phân quyền chuẩn xác (401 cho unauthenticated, 403 cho authenticated non-admin).
- **LTX Gateway & Registered Operations v2**: 50 registered operations có chữ ký SHA-256 xác thực bản quyền, schema strictly typed (Pydantic models with `extra="forbid"`, cấm `Any`/`Dict[str, Any]` tại ranh giới, sanitize chặn bytes/unsupported/DoS), BSON Date chuẩn cho timestamp ghi mới.
- **Multi-User Deduplication**: Chia sẻ physical blob SVG/ảnh dùng chung dưới storage nhưng tách rời hoàn toàn quyền sở hữu `owner_id` trong MongoDB. Index compound `(owner_id, request_fingerprint)` ngăn ngừa đụng độ giữa các user khác nhau sinh cùng một nội dung.
- **Durable Job Queue & Worker**: Hàng đợi MongoDB lease-claiming (`attempt < max_attempts`), timeout xử lý 120s, heartbeat tự động gia hạn lease, hủy bỏ an toàn checkpoint, tự động cách ly job lỗi vĩnh viễn (poison job).
- **NDJSON Streaming Protocol v2**: Kiến trúc Producer-Consumer tách rời (`StreamSession`), hỗ trợ phục hồi luồng rớt mạng qua `X-Last-Sequence` (không gọi LLM trùng lặp), endpoint hủy phát luồng tức thì `POST /api/chat/{request_id}/cancel`.
- **Storage Reconciliation**: Tự động đối soát MongoDB `asset_key` và tệp vật lý, tái tạo SVG xác định và dọn dẹp các manifest chưa render.

### 2. Frontend Unit & Integration Tests (Vitest + React Testing Library)
```bash
cd frontend
npm test
```
**Kết quả thực tế ngày 2026-09-16**: `67 passed, 0 failed` trên 9 test suites trong 4,01 giây. Phạm vi gồm parser/khôi phục NDJSON v2, chat flow, session/history, artifact export/upscale, bảng Markdown, bảo vệ double-click, thao tác nhanh, bàn phím/ARIA, hợp đồng kiến trúc frontend và admin auth hardening.

### 3. Frontend Linter & Build
```bash
cd frontend
npm run lint    # 0 lỗi (Oxlint)
npm run build   # TypeScript + Vite hoàn tất; JS gzip 116,56 kB, CSS gzip 6,73 kB
```

### 4. Biên Dịch Cú Pháp Python
```bash
python -m compileall backend scripts   # 0 lỗi cú pháp
```

---

## 🗄️ Kiến Trúc MongoDB & Quy Trình Migrations

Hệ thống sử dụng MongoDB Atlas (`huit_chatbot`) với Pydantic Models chuẩn hóa, `$jsonSchema` validators và StorageAdapter:
- **Phân tách Blob & Ownership**: `assets` lưu Physical Blob; `artifacts` lưu quyền sở hữu nghiệp vụ (ngăn ngừa rò rỉ khi deduplication).
- **Loại trừ Base64/Binary lớn**: Toàn bộ file Word, Excel, PDF và hình ảnh được lưu trữ an toàn qua `StorageAdapter` (hỗ trợ Local và Object Storage S3).
- **Bộ công cụ Migration 9 bước**: Hỗ trợ `--dry-run`, `--apply`, tự động backup và rollback an toàn.
- Chi tiết tài liệu:
  - [docs/MONGODB_SCHEMA.md](docs/MONGODB_SCHEMA.md): Đặc tả Schema, Validators, Indexes, TTL và ERD.
  - [docs/MONGODB_MIGRATIONS.md](docs/MONGODB_MIGRATIONS.md): Hướng dẫn vận hành và quy trình 9 bước Migration.

### Lệnh chạy kiểm tra Migration (Dry-Run):
```bash
python scripts/migrations/001_audit_mongodb_schema.py --dry-run
python scripts/migrations/007_create_indexes.py --dry-run
python scripts/migrations/009_verify_migration.py --dry-run
```

---

## 🚀 Cấu Hình Triển Khai


- **Topology khuyến nghị**: `docker-compose.yml` chạy năm dịch vụ tách biệt: frontend Nginx, API, Artifact Worker, MongoDB và Redis; file vật lý dùng volume bền vững hoặc Object Storage. Reverse proxy tắt buffering cho `/api/*` để giữ NDJSON streaming thời gian thực.
- **Vercel**: `vercel.json` vẫn có thể dùng để thử frontend/API cơ bản, nhưng triển khai full-stack chỉ bằng file này **không được xem là production-ready** vì không có tiến trình worker liên tục cho export/upscale. Nếu dùng Vercel cho frontend, backend và worker phải được triển khai trên hạ tầng chạy tiến trình dài hạn riêng.
- **CI**: `.github/workflows/ci.yml` tự động chạy Pytest, compile Python, Vitest, Oxlint, Vite build và kiểm tra hợp đồng Docker Compose trên mỗi push/pull request.
- **Biến môi trường Production bắt buộc**:
  Khi triển khai production, bắt buộc khai báo các biến môi trường sau:
  - `APP_ENV=production`
  - `ADMIN_USERNAME=<tên_đăng_nhập_quản_trị>`
  - `ADMIN_PASSWORD=<mật_khẩu_quản_trị_mạnh>`
  - `ADMIN_TOKEN=<mã_bearer_token_bí_mật>`
  - `CORS_ALLOWED_ORIGINS=https://huit-chatbot.vercel.app,https://your-domain.edu.vn`
  - `MONGODB_PASSWORD=<mật_khẩu_mongodb_atlas>`
  - Tối thiểu một API Key: `GEMINI_API_KEY`, `GROQ_API_KEY`, hoặc `HUIT_OPENROUTER_KEY`.

---

## ⚠️ Giới Hạn, Điều Kiện Kiểm Chứng & Trạng Thái Phát Hành

1. **Tính độc lập của mã nguồn mới**:
   - Toàn bộ backend (`backend/`) và frontend (`frontend/`) hoạt động độc lập. Hai source handoff cũ và script baseline phụ thuộc chúng đã được loại khỏi workspace sau khi đối chiếu.
2. **Khả năng kết nối Live MongoDB Atlas**:
   - Nếu không có biến môi trường `MONGODB_PASSWORD` hoặc mất kết nối Internet, các truy vấn Guardrail (chào hỏi, từ chối ngoài phạm vi, catalog tuyển sinh) vẫn hoạt động bình thường nhờ kiến trúc độc lập.
   - Các truy vấn tìm kiếm RAG sâu yêu cầu kết nối mạng tới MongoDB Atlas cluster.
3. **Khả năng gọi LLM ngoài**:
   - Unit tests sử dụng mock để xác thực thứ tự 13 model provider (Gemini $\rightarrow$ Groq $\rightarrow$ OpenRouter). Việc gọi live LLM phụ thuộc vào tính khả dụng và quota của các API keys bên ngoài.
4. **Quyết định nghiệm thu các cổng phát hành (Release Gate Decisions)**:
   - **Local development**: **GO** (chạy tốt trong môi trường local in-memory/mock).
   - **Code review**: **GO có điều kiện** (đạt chuẩn kiến trúc mô-đun, nhưng tồn tại rủi ro secret trong Git history cần xử lý).
   - **Staging**: **NO-GO** (chặn cho tới khi hoàn tất Phase P0 xoay vòng bí mật và Phase P1 khóa hạ tầng mạng).
   - **Production**: **NO-GO** (nghiêm cấm phát hành; chỉ xem xét sau khi Staging thực tế đạt đầy đủ tiêu chuẩn).
   - **Vercel / Tên miền**: **Chưa triển khai**.
5. **Báo cáo nghiệm thu chi tiết**:
   - Xem [docs/PRODUCT_RELEASE_READINESS_2026-09-16.md](docs/PRODUCT_RELEASE_READINESS_2026-09-16.md) để biết báo cáo nghiệm thu phát hành chi tiết.
