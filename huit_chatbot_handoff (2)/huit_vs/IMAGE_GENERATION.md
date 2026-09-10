# Tạo ảnh JSON miễn phí

Chọn **Tạo ảnh minh họa miễn phí**, kích thước và dung lượng JSON trong giao diện,
nhập mô tả rồi Gửi. Hoặc gõ `Tạo ảnh: phong cảnh núi và mặt trời` / `/anh mèo`.
Xem ảnh trước, tải SVG miễn phí hoặc mở JSON để dùng lại.

Luồng: API OpenRouter có sẵn → JSON hình học đã kiểm tra → collection
`huit_chatbot.generated_images` → chatbot đọc MongoDB → SVG hiển thị trong chat.
Phù hợp hình minh họa phẳng, poster và sơ đồ; không phải công cụ tạo ảnh chụp
chân thực. JSON chứa hình học và chữ, không chứa base64 hay URL ảnh bên ngoài.

## Cấu hình

Dùng `HUIT_OPENROUTER_KEY` hoặc `OPENROUTER_API_KEY` hiện có; MongoDB dùng
`MONGODB_URI` hoặc `MONGODB_PASSWORD` với cluster hiện có. Không đưa key vào UI.
Chỉ gọi `openrouter/free`, không dùng fallback tính phí của chatbot. Khi hết
quota, lỗi API hoặc JSON không hợp lệ, trả lỗi để người dùng thử lại. Không
tự gọi lại API hay phát sinh mua credit. Hạn mức và tính sẵn có do OpenRouter
quy định: https://openrouter.ai/docs/guides/routing/routers/free-router

Phần tạo ảnh không tải model, torch, CUDA hay embedder; SVG chỉ cần trình duyệt
vẽ hình. Khởi động/RAG cũ vẫn có warmup embedder riêng. MongoDB/hosting vẫn tuân
theo hạn mức gói tài khoản của bạn, không đảm bảo miễn phí lưu trữ vô hạn.
Ảnh được giữ trong MongoDB tới khi quản trị viên xóa; chưa có tự dọn dữ liệu.

## API

`POST /api/images`

```json
{"prompt":"Mèo cam trên đồng cỏ", "width":512, "height":512, "max_json_kb":8}
```

Kích thước 128–1024 mỗi chiều; JSON scene 2–24 KiB (mặc định 12).
Giới hạn tính trên UTF-8 JSON rút gọn của **scene**, không bao gồm metadata
MongoDB/API. Phản hồi có `id`, `url`, `json_url`, `scene_bytes`, kích thước.
JSON vượt giới hạn bị từ chối trước khi ghi MongoDB.

`GET /api/images/{id}` đọc lại scene; `GET /api/images/{id}/svg` dựng ảnh;
thêm `?download=true` để tải. ID ngẫu nhiên 192 bit; ai có link có thể đọc ảnh,
đây không phải cơ chế phân quyền theo tài khoản. Không có API liệt kê ảnh.

`POST /api/chat`, `POST /api/chat-stream`, `GET /api/chat-stream` cũng nhận lệnh
tạo ảnh, mặc định 512×512 và 12 KiB. Dùng endpoint ảnh để tùy chỉnh thông số.
Chưa tích hợp thanh toán; xem trước và tải ảnh hiện đều miễn phí.

## Kiểm thử

`python -m unittest test_image_service` trong thư mục này. Mock API/MongoDB để
kiểm tra không tính phí thật: giới hạn JSON, escaping SVG, chỉ gọi router free,
lưu–đọc MongoDB, tải ảnh, lỗi, rate limit và tích hợp chat/stream.
