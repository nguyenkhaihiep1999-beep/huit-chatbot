# HUIT AI Chatbot - Frontend Client

Ứng dụng giao diện web hiện đại cho Hệ thống Trợ lý AI Tư vấn Tuyển sinh Đại học Công Thương TP.HCM (HUIT).

## 🚀 Công Nghệ Sử Dụng

- **Framework**: React 19 (Strict Mode, Concurrent Features)
- **Công cụ build**: Vite 8 & TypeScript ~6.0.2 (Strict type checking)
- **Linter**: Oxlint (High-performance JS/TS linter)
- **Style**: Modern Vanilla CSS, CSS Variables Design System (Hỗ trợ Dark/Light Theme)
- **Biểu tượng**: Lucide React
- **Xử lý luồng dữ liệu**: Real-time NDJSON Streaming parser, Token buffer (nhịp 35ms)
- **Bảo mật**: DOMPurify & Marked (chỉ sanitize khi hoàn tất streaming)
- **Giám sát hiệu năng**: Custom Telemetry Tracker (không lưu nội dung câu hỏi hay thông tin nhạy cảm)

## 📁 Cấu Trúc Thư Mục `src/`

```
src/
├── app/
│   └── App.tsx                 # Entrypoint chính của ứng dụng
├── features/
│   ├── admission-visuals/      # Sơ đồ SVG & Thẻ ngành tuyển sinh
│   ├── chat/                   # Cửa sổ chat, input, danh sách tin nhắn, NDJSON streaming
│   ├── history/                # Lịch sử phiên trò chuyện (Drawer & LocalStorage)
│   ├── image-generation/       # Modal sinh ảnh AI (FLUX.1 / SVG)
│   ├── theme/                  # Quản lý giao diện Sáng / Tối
│   └── voice/                  # Nhận diện giọng nói (STT) & Đọc câu trả lời (TTS)
├── observability/              # Đo lường TTFT, Latency, Buffer flushes ẩn danh
├── shared/                     # Components, hooks, thư viện và types dùng chung
├── styles/                     # Biến CSS tokens, giao diện chat và thẻ đồ họa
└── main.tsx                    # File khởi tạo React DOM
```

## 🛠️ Hướng Dẫn Phát Triển

### 1. Cài đặt thư viện
```bash
npm install
```

### 2. Khởi chạy môi trường phát triển (Dev Server)
```bash
npm run dev
```
Mặc định ứng dụng chạy tại `http://localhost:3000`. Các request `/api` được cấu hình proxy sang backend `http://localhost:8000`.

### 3. Kiểm tra mã nguồn (Linter & Typecheck)
```bash
npm run lint    # Oxlint kiểm tra cú pháp và quy tắc mã nguồn (0 errors, 0 warnings)
```

### 4. Chạy kiểm thử tự động (Unit & Integration Tests)
```bash
npm test        # Vitest chạy 28 tests trên 5 test suites (100% passed)
```
Danh sách test suites:
- `tests/ndjsonParser.test.ts` (4 tests): Parser NDJSON phân tích stream từng dòng, ghép chunk cắt đôi.
- `tests/chat_flow.test.ts` (6 tests): Cô lập history payload, session lưu đủ, abort, telemetry privacy, chuẩn hóa ID duy nhất không trùng lặp.
- `tests/useChatStream.test.ts` (12 tests): Kiểm thử hook useChatStream toàn diện (idempotent stop, replacement, token trailing, unmount cleanup...).
- `tests/ChatWindow.test.tsx` (4 tests): Testing Library tích hợp ChatWindow.
- `tests/App.test.tsx` (2 tests): Testing Library tích hợp App (đổi session & tạo chat mới khi đang stream).

### 5. Đóng gói ứng dụng (Build Production)
```bash
npm run build   # tsc -b && vite build
```
Thư mục xuất bản: `dist/`.

