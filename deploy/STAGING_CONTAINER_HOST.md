# Staging: Vercel frontend + container backend/worker

Tài liệu này mô tả điều kiện tối thiểu để đưa staging lên mạng mà không chạy toàn bộ FastAPI/worker trên Vercel Serverless.

## Trạng thái bắt buộc trước khi nối Vercel

1. Có một dịch vụ container cấp URL HTTPS công khai cho backend.
2. Dịch vụ đó chạy được `Dockerfile`, truyền biến `PORT`, và hỗ trợ health check `GET /health/ready`.
3. Có một background worker chạy cùng image/code với lệnh `python -m backend.app.workers.artifact_worker`; worker không mở public port.
4. Backend và worker dùng chung MongoDB, Redis và object storage thông qua environment variables.
5. MongoDB/Redis/object storage không mở public unauthenticated access.

Nếu chưa đáp ứng các điều kiện trên, trạng thái phát hành là `BLOCKED_NEEDS_BACKEND_HOST`.

## Biến môi trường tối thiểu

Giá trị thật chỉ được nhập trong secret manager của nhà cung cấp. Không tạo hoặc commit file `.env`.

- `APP_ENV=staging`
- `PORT`: host tự cấp hoặc `8000`
- `CORS_ALLOWED_ORIGINS=https://<URL_VERCEL_DA_XAC_MINH>`
- `MONGODB_URI`, `MONGODB_DB`, `MONGODB_COLL`
- `REDIS_URL`, `RATE_LIMIT_REDIS_URL`, `STREAM_RESUME_REDIS_URL`
- `STORAGE_BACKEND=s3` (hoặc `r2`/`minio`)
- `STORAGE_ENDPOINT`, `STORAGE_ACCESS_KEY`, `STORAGE_SECRET_KEY`, `STORAGE_BUCKET`, `STORAGE_REGION`, `STORAGE_USE_SSL`
- `ADMIN_USERNAME`, `ADMIN_PASSWORD`, `ADMIN_TOKEN`
- Ít nhất một khóa LLM: `GEMINI_API_KEY`, `GROQ_API_KEY` hoặc `HUIT_OPENROUTER_KEY`

## Release gate

Chỉ sau khi backend có URL HTTPS thật mới thực hiện theo thứ tự:

1. `GET <BACKEND_URL>/health/live` trả HTTP 200.
2. `GET <BACKEND_URL>/health/ready` trả HTTP 200 và MongoDB, Redis, storage đều ready.
3. `POST <BACKEND_URL>/api/auth/session` trả `session_id`, `csrf_token` và cookie HttpOnly.
4. Chat NDJSON stream trả chuỗi event hợp lệ từ `start` đến `done`.
5. Tạo một job artifact, quan sát worker nhận job và hoàn tất file trên object storage.
6. Điền chính xác backend URL vào root `vercel.json`; đặt rewrite `/api/:path*` trước SPA fallback.
7. Chạy smoke test qua URL Vercel, bao gồm `POST /api/auth/session`.

Không được tuyên bố `FIXED` nếu bước 7 chưa đạt.
