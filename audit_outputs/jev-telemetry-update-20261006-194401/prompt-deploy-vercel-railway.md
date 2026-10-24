# Prompt cập nhật và triển khai Vercel + Railway

Dán phần dưới vào Antigravity hoặc agent đang phụ trách dự án. Đây là kế hoạch bàn giao, không phải xác nhận hệ thống đã deploy.

---

Bạn đang làm việc trong `D:\chatbot2`, dự án HUIT Chatbot. Mục tiêu: chuẩn bị và triển khai bản cập nhật đã kiểm chứng lên **Vercel cho frontend React/Vite** và **Railway cho API FastAPI cùng artifact worker**, theo từng bước có kiểm tra và rollback. Không tái cấu trúc folder, đổi thuật toán retrieval hay thay model chỉ để deploy.

Đọc `audit_outputs/jev-telemetry-update-20261006-194401/bao-cao-phien.html`, `evidence.json`, `prompt-tiep-theo.md`, hướng dẫn AGENTS.md nếu có và cấu hình deployment thực tế trước khi làm. Snapshot trước đó đạt 557 backend tests, 126 frontend tests, lint/build và 18 frontend contracts; phải chạy lại theo source mới, không dùng số liệu cũ như kết quả phiên này. Telemetry Jev đã được sửa nhưng chưa xác nhận server live nạp bản sửa.

## 1. Chốt đích và quyền trước khi tác động cloud

- Xác định đúng Vercel team/project, Railway workspace/project/environment, API service, worker service, branch/commit được deploy, frontend domain và backend URL. URL đang ghi trong `vercel.json` chỉ là cấu hình trên đĩa, không phải bằng chứng đó là môi trường cần cập nhật.
- Ưu tiên cập nhật project/service hiện có; không tự tạo tài nguyên, nâng plan, mua domain, thêm replicas hoặc dịch vụ tính phí.
- Nếu thiếu quyền, project ID, đích staging/production hoặc ngân sách, hỏi đúng thông tin còn thiếu; vẫn hoàn thành phần kiểm tra và chuẩn bị local an toàn.
- Việc nhận prompt không tự cho phép promote production, phát sinh phí, gửi dữ liệu thật sang provider hoặc thay đổi dữ liệu MongoDB. Trước bước tương ứng phải có xác nhận cụ thể của người dùng về môi trường, phạm vi và ngân sách.
- Kiểm tra Git autodeploy trước khi commit/push: push lên branch liên kết có thể triển khai ngay. Không push/redeploy/promote hoặc thay domain routing để vượt qua bước phê duyệt.

## 2. Chuẩn bị bản release có thể truy vết

- Kiểm tra dirty working tree, bảo toàn thay đổi của người dùng; không reset hoặc tự commit toàn bộ repository.
- Chạy backend tests, frontend tests/lint/build, schema sync `--check` và secret scan. Lưu kết quả vào folder audit mới có timestamp, ghi source hash/commit và số liệu thực tế.
- Kiểm tra `.dockerignore`, `.vercelignore` và build context: không tải lên `.env`, API key, `.testdeps`, cache, backup hay báo cáo chứa dữ liệu riêng không cần thiết. Không in giá trị secrets ra terminal/log/HTML.
- Kiểm tra runtime/package tương thích lockfile và Docker image; không tự nâng dependency hoặc reindex KB. Cảnh báo FastEmbed pooling cần được đối chiếu với vector hiện có, không xử lý bằng cách xóa dữ liệu.
- Chốt deployment ID/version khỏe trước đó, cấu hình môi trường không chứa secret và quy trình rollback trước khi cập nhật.

## 3. Railway: API và worker là hai service riêng

- Kiểm tra Root Directory/build context có đủ `backend/`, `scripts/`, `data/` và `requirements.txt` như các Dockerfile hiện tại. Với cấu trúc này, chọn build context ở gốc repo; không đặt root là `backend/` mà vẫn dùng nguyên các lệnh COPY từ gốc.
- API dùng `Dockerfile`. Worker dùng `Dockerfile.worker`; nếu cần chọn Dockerfile tùy chỉnh, đối chiếu `RAILWAY_DOCKERFILE_PATH` với tài liệu Railway và cấu hình service hiện có.
- API chạy `uvicorn backend.app.main:app --host 0.0.0.0 --port ${PORT:-8000}` theo Docker CMD hiện tại. Để platform cấp PORT hoặc cấu hình nhất quán; không hardcode localhost hoặc đổi thành server frontend.
- Worker chạy `python -m backend.app.workers.artifact_worker`. Không gán start command của API cho worker, không mở public domain/port worker hoặc Redis nếu không có nhu cầu và phê duyệt riêng.
- Kiểm tra health path Railway cho API; `/health/live` chỉ là liveness và chưa bảo đảm Mongo/KB/storage/Jev sẵn sàng. `/health/ready` hiện có thể ghi operation audit và tạo storage probe: cần phê duyệt các tác động đó trước khi dùng. Worker không có HTTP health endpoint; kiểm tra process, heartbeat/logs và xử lý job bằng phương pháp phù hợp, không bịa health route.
- Kiểm tra RAM/CPU/startup/timeout/restart policy bằng số liệu thực. Không tự tắt embeddings hoặc tăng plan để vượt lỗi; nếu cần trade-off, báo rõ tác động tới retrieval và xin lựa chọn.

## 4. Biến môi trường và hạ tầng chung

- Kiểm tra tên biến theo `backend/app/config.py` và `.env.example`, không đoán tên hoặc giá trị. Tối thiểu đối chiếu `APP_ENV=production`, `CORS_ALLOWED_ORIGINS`, các biến admin bắt buộc, Mongo URI/credentials, LLM provider, Redis/queue và storage.
- Secrets chỉ nằm trong secret/variable store của platform ở đúng service/environment; không đưa Jev key, Mongo URI có auth hay admin token vào frontend hoặc biến `VITE_*`.
- API và worker phải trỏ tới cùng DB/queue và storage phù hợp. Không giả định filesystem local của hai service được chia sẻ hay bền vững qua deploy; đối chiếu object storage chung đang hỗ trợ S3/R2/MinIO, bucket và quyền tối thiểu. Không migration, seed, cleanup, drop index hoặc thay retention khi chưa được phép.
- Redis nếu được dùng phải kiểm tra auth, kết nối riêng và cấu hình resume/rate limit. Không dùng hostname Docker Compose `redis` cho Railway mà không kiểm chứng target thực tế; không tự tạo thêm Redis khi chưa chốt ngân sách.
- Giữ nguyên production Jev mode/model/threshold đang được phê duyệt. Nếu chưa cấu hình Jev ở môi trường đích, trình bày kế hoạch bật và chi phí trước, không tự chuyển sang assist. Nếu bật, kiểm tra `JEV_MODE`, `TYPESAFE_API_KEY`, `JEV_MODEL`, timeout/budget/concurrency theo config.

## 5. Vercel: giữ đúng root/build và proxy cùng origin

- Repo hiện có **`vercel.json` ở gốc**, install command `cd frontend && npm install`, build command `cd frontend && npm run build`, output `frontend/dist`. Kiểm tra dashboard Root Directory có khớp kiểu cấu hình này. Không vừa đặt root `frontend` vừa dùng `cd frontend` hoặc output `frontend/dist` như thể đang ở gốc repo.
- Nếu chuyển root project sang `frontend`, phải chủ động điều chỉnh vị trí config, các lệnh và output tương ứng trong một thay đổi được review; không dùng đồng thời hai phương án. Không chuyển root nếu cấu hình hiện tại đã đúng. Đối chiếu lockfile để đề xuất `npm ci` nếu phù hợp, không ghi là đã đổi khi chưa thực hiện.
- `frontend/src/features/chat/api/chatApi.ts` hiện có `API_BASE=''`, client dùng same-origin. Không tự thêm `VITE_API_URL` rồi giả định code sẽ đọc nó.
- Đối chiếu rewrite `/api/:path*` với **backend Railway đúng môi trường đã xác nhận**. Backend URL proxy cần public HTTPS hợp lệ để Vercel truy cập; không dùng địa chỉ private Railway cho proxy từ Vercel. Giữ nguyên prefix `/api`, tránh lặp hoặc mất prefix, và đặt routing API trước SPA fallback.
- Kiểm tra refresh/deep links, `/admin`, assets/static/previews/download và endpoint API không bị trả `index.html`. Chỉ bổ sung rewrite static nếu xác nhận ứng dụng thật cần và target đúng; không mở proxy tùy ý.
- Kiểm tra streaming NDJSON qua chính domain Vercel: nhận token tăng dần, đúng content type, không cache, timeout/cancel/resume hoạt động. Header `X-Accel-Buffering: no` không tự chứng minh proxy đã bỏ buffering; phải kiểm tra thực, đối chiếu giới hạn platform hiện hành.
- Kiểm tra cookie HttpOnly/Secure/SameSite, session bootstrap, CSRF, admin và Origin/CORS với domain Vercel thực. Không sửa lỗi bằng cách tắt CSRF/auth, bỏ Secure cookie hoặc mở CORS `*` cho request có credentials.

## 6. Triển khai theo cổng nghiệm thu

1. Chuẩn bị/kiểm tra local và build container khi có Docker. Nếu không chạy được, ghi rõ hạn chế, không kết luận image đã được kiểm chứng.
2. Khi môi trường preview/staging và quyền/chi phí đã được xác nhận, cập nhật Railway API/worker và kiểm tra liveness/cấu hình/connectivity; cập nhật Vercel preview tới backend staging phù hợp. Không nối preview chứa test lỗi vào production data chỉ vì tiện.
3. Nghiệm thu E2E ở đúng URL: session, chat streaming, hủy request, cache, lịch sử, admin auth, artifact/job/preview/download và fallback. Test tạo session/job, storage probe hoặc chat có thể ghi DB/gọi LLM; chỉ dùng dữ liệu tổng hợp và thực hiện các mutation/provider calls trong phạm vi đã phê duyệt.
4. Sau khi ngân sách và dữ liệu gửi provider được chốt, chạy nhóm truy vấn Jev thật có giới hạn. Đối chiếu request_id, HTTP attempts, response/usage, result_accepted, decision_applied và apply_reason. Cache hit hoặc no-call không chứng minh Jev đã trả inference; mock test không chứng minh chất lượng live.
5. Trình kết quả staging, release version và rollback cho người dùng. Chỉ promote/redeploy production sau xác nhận cụ thể. Sau release kiểm tra lại qua domain chính thức và theo dõi số liệu trong cửa sổ nghiệm thu được chốt; không tự tạo automation theo dõi dài hạn.
6. Nếu lỗi auth/session/stream/job tăng, áp dụng rollback theo kế hoạch và quyền đã được duyệt; không sửa bằng reset DB, xoay key, tắt guardrails hoặc tái cấu trúc giữa release.

## 7. Bằng chứng và điều kiện hoàn tất

Xuất **HTML báo cáo deployment** và **evidence JSON** mới gồm:

- Môi trường, project/service, URL, deployment ID, commit/source hash và thời gian thực.
- Thay đổi local/config/platform đã thực hiện; secrets chỉ ghi tên + present/missing.
- Kết quả test/build/container/health/E2E/Jev thực, phân biệt pass/fail/chưa kiểm chứng.
- RAM/CPU/error rate/latency và usage/cost thực nếu đo được; không bịa baseline hoặc số tiền.
- Trạng thái worker/queue/storage, các mutation test đã được cho phép, lỗi còn lại và rollback version.
- Kết luận riêng: local checks / staging acceptance / production acceptance. Không ghi “deploy thành công” chỉ vì build xanh, `/health/live=200` hoặc Jev health `configured`.

Chỉ kết thúc với production acceptance khi bản release đã được xác nhận chạy ở cả Vercel và Railway, E2E cần thiết đạt, worker/storage hoạt động và bằng chứng/rollback đầy đủ. Nếu còn thiếu quyền, budget, dữ liệu hoặc target, báo rõ phần đã hoàn thành và hỏi đúng quyết định còn thiếu; không giả định quyền.

---

## Nguồn nền tảng đã đối chiếu ngày 06/10/2026

- Root Directory, build/output: [Vercel — Configuring a Build](https://vercel.com/docs/builds/configure-a-build).
- Rewrite ra backend: [Vercel — Rewrites](https://vercel.com/docs/routing/rewrites).
- Dockerfile/build context: [Railway — Dockerfiles](https://docs.railway.com/builds/dockerfiles).
- Dockerfile path: [Railway — Variables Reference](https://docs.railway.com/variables/reference).
- PORT và health gate: [Railway — Healthchecks](https://docs.railway.com/deployments/healthchecks).

Các đường dẫn/start commands/biến riêng HUIT ở trên được lấy từ source hiện tại; phải đối chiếu lại nếu dự án thay đổi.
