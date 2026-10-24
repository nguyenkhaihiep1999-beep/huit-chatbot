# Phiên cập nhật/deploy Vercel và GitHub — 07/10/2026

Người dùng đã cho phép sửa/cập nhật và deploy lại Vercel/GitHub để sản phẩm chạy được. Chỉ cập nhật đúng repo/project hiện có; không tạo tài nguyên, thay gói, sửa/xóa MongoDB hoặc gọi Jev trả phí.

Repo: nguyenkhaihiep1999-beep/huit-chatbot, nhánh production Vercel: main. Vercel project huit-chatbot đã được xác minh bằng API có auth sau khi CLI làm mới phiên đăng nhập. Deployment khỏe trước đó: dpl_3fCXyZU6goBxcVh3RzgcETrALYQR, commit 3f338839fcbec4d1337ae10378d9c78c69350127.

Kiểm tra HTTP thực: frontend https://huit-chatbot.vercel.app/ trả 200; backend https://bacsihiep-production.up.railway.app/health/live và /api/health/live qua Vercel trả 404 Application not found. Chưa kết luận sản phẩm hoạt động chỉ từ frontend HTTP 200.

Railway config trên máy đang chọn Redis. Đã xác minh project production và đọc domain service BacsiHiep bằng query, không redeploy Redis hoặc thay domain. Domain API trên cloud trùng địa chỉ trong vercel.json, cần kiểm tra tiếp deployment của service này.

Đã sửa local: install frontend bằng npm ci theo lockfile, tăng loại trừ upload Vercel để không gửi .testdeps/data/cache/archive; thêm regression tests cho cấu hình frontend deploy. Kết quả kiểm thử và tình trạng cloud cuối phiên sẽ được ghi riêng khi có bằng chứng.

## Kết quả cuối phiên: preview hoàn tất, production còn chờ khôi phục backend

Đã commit release `3980bcd` và bản vá bảo mật `ee23fdd4ccae6e0338159e22a21c1ce40fa74d19`. Đã push nhánh [codex/deploy-vercel-20261007](https://github.com/nguyenkhaihiep1999-beep/huit-chatbot/tree/codex/deploy-vercel-20261007). Remote `main` vẫn ở `3f338839fcbec4d1337ae10378d9c78c69350127`; chưa promote hoặc thay domain production.

DOMPurify đã cập nhật từ 3.4.15 lên 3.4.16 và source-map-js từ 1.2.1 lên 1.2.2, không đổi major version. Tham chiếu advisory: [DOMPurify](https://github.com/advisories/GHSA-p98j-92pf-mc4p), [DOMPurify raw-text](https://github.com/advisories/GHSA-6688-9rhm-gjv2), [source-map-js](https://github.com/advisories/GHSA-68fv-2mgg-jv7q). npm ci cài đúng lockfile và báo 0 lỗ hổng đã biết sau khi thử lại lỗi DNS tạm thời; không kết luận đây là chứng nhận bảo mật toàn diện.

Kiểm thử sau bản vá: **562 backend tests đạt** (34 cảnh báo dependency đã có), **126 frontend tests đạt** trong 16 files; lint/build exit 0; 18 frontend schema contracts và manifest đồng bộ. Secret scan 600 files: 8 matches gồm 5 placeholder và 3 synthetic fixtures, **0 secret thực rò rỉ**. Bằng chứng: `backend-tests-final.xml`, `frontend-tests-final.xml`, `secret-scan-final.json` và `evidence-final.json` trong cùng thư mục. Test dùng môi trường development/offline/mock, không phải bằng chứng live chat hay chất lượng Jev.

[Preview bản vá](https://huit-chatbot-2l811xqn8-nguyenkhaihiep1999-beeps-projects.vercel.app) ở trạng thái **READY**, deployment `dpl_4nKBDnZZRyE7YqaGN3wb697JSbjp`, đúng commit `ee23fdd`. Log cloud xác nhận npm báo 0 vulnerabilities, Vite build xong và Build Completed. Preview vẫn giữ Deployment Protection: HTTP không đăng nhập trả 302 sang Vercel. Không tắt bảo vệ; chưa có kiểm thử E2E bằng trình duyệt.

HTTP production frontend trả 200 nhưng `/api/health/live` qua Vercel và `/health/live` trực tiếp Railway đều trả 404. API `BacsiHiep` có latest deployment **FAILED**, không có active deployment. Cấu hình Dockerfile là `Dockerfile`; chỉ xác nhận build failed, chưa xác định nguyên nhân chi tiết. Không coi frontend 200 hay preview READY là sản phẩm chat đã hoạt động.

Đã gửi câu hỏi xin phép khôi phục/redeploy **đúng API BacsiHiep** trong project Railway hiện có; cuối phiên chưa nhận câu trả lời. Chưa sửa Railway, Redis, dữ liệu MongoDB, gói dịch vụ hay tạo tài nguyên mới. CLI Railway mặc định đang link Redis, tuyệt đối không redeploy bằng target mặc định. Cloud chưa có `TYPESAFE_API_KEY`/`JEV_MODE`; không tự sao chép key local, bật Jev hay gọi inference trả phí.

Bước tiếp theo cần xác nhận của người dùng: cho phép khôi phục API Railway BacsiHiep; sau đó đọc lỗi build chi tiết có khử secret, sửa đúng lỗi trong phạm vi được cho phép, xác nhận API liveness và các kiểm tra an toàn phù hợp rồi mới promote bản Vercel đã vá. Hiện trạng là **chưa nghiệm thu production/end-to-end**, không phải hoàn tất deploy sản phẩm.
