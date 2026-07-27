# HƯỚNG DẪN TẠO LINK CHÍNH THỨC DỰ ÁN HUIT AI CHATBOT (MIỄN PHÍ VĨNH VIỄN)

Nếu tài khoản Render của bạn đã hết hạn lượt dùng (free tier exhausted), dưới đây là **3 nền tảng Cloud MIỄN PHÍ VĨNH VIỄN 100% (Free Forever)** không lo hết hạn lượt dùng!

---

## 🌟 NỀN TẢNG 1: KOYEB.COM (MIỄN PHÍ VĨNH VIỄN - KHUYÊN DÙNG HÀNG ĐẦU)

**Koyeb.com** cung cấp 1 Micro Instance miễn phí vĩnh viễn (Free Forever), hỗ trợ Python FastAPI và tự động cấp tên miền HTTPS bảo mật.

### Các bước thực hiện:
1. Đưa code lên kho **GitHub** của bạn (`git push origin main`).
2. Truy cập [https://www.koyeb.com](https://www.koyeb.com) -> Bấm **Sign Up** (Đăng nhập bằng tài khoản GitHub).
3. Tại trang điều khiển, bấm **Create Service** -> Chọn nguồn **GitHub**.
4. Chọn repository `huit-chatbot` của bạn.
5. Cấu hình cài đặt:
   - **Builder**: `Buildpacks` (hoặc Python).
   - **Run Command**: 
     ```bash
     uvicorn api:app --host 0.0.0.0 --port 8000
     ```
   - **Instance Type**: Chọn **Free Nano**.
6. Thêm biến môi trường (**Environment Variables**):
   - Key: `MONGODB_PASSWORD` | Value: `<mật khẩu MongoDB mới của bạn>`
   - Key: `OPENROUTER_API_KEY` | Value: `your_openrouter_api_key_here`
   - Key: `ADMIN_TOKEN` | Value: `<chuỗi bí mật ngẫu nhiên dài>`
7. Bấm **Deploy**. Sau 1-2 phút bạn sẽ nhận được đường link cố định chạy 24/7 vĩnh viễn:  
   👉 **`https://huit-chatbot-yourname.koyeb.app`**

---

## 🌟 NỀN TẢNG 2: HUGGING FACE SPACES (MIỄN PHÍ VĨNH VIỄN - SIÊU BỀN VỮNG)

Hugging Face Spaces là nền tảng số 1 về AI, cung cấp máy chủ CPU cơ bản miễn phí vĩnh viễn 24/7.

### Các bước thực hiện:
1. Truy cập [https://huggingface.co](https://huggingface.co) và đăng tạo tài khoản miễn phí.
2. Bấm vào ảnh đại diện góc phải -> chọn **New Space**.
3. Điền thông tin:
   - **Space name**: `huit-chatbot-ai`
   - **License**: `mit`
   - **Space SDK**: Chọn **Docker** (hoặc **Blank**).
4. Tạo file `Dockerfile` trong thư mục dự án:
   ```dockerfile
   FROM python:3.10-slim
   WORKDIR /app
   COPY . .
   RUN pip install --no-cache-dir -r requirements.txt
   CMD ["uvicorn", "api:app", "--host", "0.0.0.0", "--port", "7860"]
   ```
5. Trong phần **Settings** của Space -> mục **Variables and secrets**, thêm 2 Secret:
   - `MONGODB_PASSWORD`
   - `OPENROUTER_API_KEY`
6. Push code lên Hugging Face Space qua Git.
7. Nhận đường link chính thức 24/7:  
   👉 **`https://huggingface.co/spaces/TênTàiKhoản/huit-chatbot-ai`** (hoặc link nhúng `.hf.space`).

---

## 🌟 NỀN TẢNG 3: VERCEL (MIỄN PHÍ VĨNH VIỄN)

Vercel là hạ tầng Serverless hàng đầu thế giới, tốc độ truy cập cực nhanh về Việt Nam.

### Các bước thực hiện:
1. Tạo file `vercel.json` ở thư mục gốc dự án:
   ```json
   {
     "version": 2,
     "builds": [
       { "src": "api.py", "use": "@vercel/python" },
       { "src": "static/**", "use": "@vercel/static" }
     ],
     "routes": [
       { "src": "/api/(.*)", "dest": "api.py" },
       { "src": "/(.*)", "dest": "static/$1" }
     ]
   }
   ```
2. Truy cập [https://vercel.com](https://vercel.com) -> Đăng nhập bằng GitHub -> Chọn **Add New Project**.
3. Import kho code GitHub `huit-chatbot`.
4. Điền Environment Variables (`MONGODB_PASSWORD`, `OPENROUTER_API_KEY`).
5. Bấm **Deploy** -> Nhận đường link HTTPS chính thức:  
   👉 **`https://huit-chatbot.vercel.app`**

---

## 💻 NỀN TẢNG 4: CHẠY DEMO TỨC THÌ QUA LOCALTUNNEL (TỪ MÁY BẠN)

Nếu cần gửi link cho ai xem gấp ngay lúc này:
```cmd
cmd /c "npx -y localtunnel --port 8000"
```
👉 Bạn có ngay link chia sẻ HTTPS tức thì: `https://small-trams-tap.loca.lt`
