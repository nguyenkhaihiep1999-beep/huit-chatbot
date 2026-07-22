# HUIT Chatbot — Tài liệu bàn giao (HANDOFF)

Dự án: **Chatbot hỏi–đáp về Trường ĐH Công Thương TP.HCM (HUIT)** theo mô hình
**RAG (Retrieval-Augmented Generation)** trên **MongoDB Atlas Vector Search**,
kiến trúc **"1 JSON = 1 module"**.

---

## 1. Trạng thái hiện tại

✅ **Đã xong**
- Kho tri thức (KB): **107 chunk dữ liệu thật** — 66 từ cổng tuyển sinh chính thức
  `ts.huit.edu.vn` + 41 từ 2 bài về học phí.
- **MongoDB Atlas**: database `huit_chatbot`
  - `huit_kb` — 107 docs `{title, text, embedding[384], source_url, page_title}`
  - `code_modules` — 1 doc: module `huit_semantic_search`
- **Atlas Vector Search index** `huit_vector_index` (cosine, 384 chiều) — READY.
- **Embedding**: `fastembed`, model `paraphrase-multilingual-MiniLM-L12-v2`
  (ONNX, chạy offline, hỗ trợ tiếng Việt — KHÔNG cần API key).
- **Semantic search** hoạt động tốt (điểm 0.81–0.89 trên các câu hỏi thật:
  học phí 140–170 triệu, 37 ngành, điểm sàn 16–23, xét tuyển học bạ...).

⏳ **Chưa làm** (roadmap ở mục 7)
- Nối LLM để **sinh câu trả lời hoàn chỉnh** (RAG generation) — cần LLM API key.
- Mở rộng KB (cào thêm trang ngành/chương trình chi tiết).
- Khung multi-agent (chạy từng module, xuất kết quả ra collection kiểm thử).

---

## 2. Dữ liệu nằm ở đâu (QUAN TRỌNG NHẤT)

Toàn bộ dữ liệu đã ở trên **MongoDB Atlas** — bền vững, độc lập với môi trường code:
- Cluster: `cluster0.hyj8rab.mongodb.net`
- Database: `huit_chatbot`

=> Người mới **không cần dựng lại từ đầu**; chỉ cần quyền truy cập là query + chạy được ngay.

---

## 3. Checklist bàn giao

Để người mới tiếp tục, cần cung cấp:

1. **Quyền truy cập MongoDB Atlas** — chọn 1:
   - (a) Mời họ vào Atlas Project: Atlas → *Access Manager* → *Invite to Project*; hoặc
   - (b) Tạo DB user riêng cho họ: *Database & Network Access* → *Add New Database User*,
     rồi đưa họ username + password + host.
   - Nhớ **Network Access**: cho phép IP của họ (hoặc `0.0.0.0/0` khi test).
2. **Bộ code này** (thư mục trong file zip) + cài `requirements.txt`.
3. **API key họ TỰ tạo** (KHÔNG dùng chung key của bạn — an toàn hơn):
   - `MONGODB_PASSWORD` — mật khẩu DB user của họ. **(bắt buộc)**
   - `KAGGLE_USERNAME`, `KAGGLE_KEY` — chỉ khi cần tải dataset Kaggle. *(tùy chọn)*
   - Firecrawl — chỉ khi cào thêm web (dùng qua nền tảng, không phải pip). *(tùy chọn)*
   - `OPENAI_API_KEY` **hoặc** `GEMINI_API_KEY` — cho bước cuối (LLM trả lời). *(khi làm RAG)*

---

## 4. Danh sách file trong gói

| File | Vai trò |
|------|---------|
| `run_module.py` | **RUNNER** — chạy module vector search với 1 câu hỏi |
| `huit_semantic_search.module.json` | Module "1 JSON = 1 module" (schema + pipeline `$vectorSearch`) |
| `build_real_kb.py` | Dựng lại KB từ `scraped_pages.json` → embed → nạp Mongo |
| `ensure_index_and_search.py` | Tạo lại vector index + demo tìm kiếm |
| `embed_and_index.py` | (Tham khảo) tạo KB mẫu + index từ đầu |
| `export_data.py` | Xuất KB ra CSV để xem |
| `dump_module.py` | Lấy module JSON từ Mongo ra file |
| `scraped_pages.json` | Dữ liệu web thô đã cào (để tái dựng KB không cần Firecrawl) |
| `huit_kb_data.csv` | Ảnh chụp dữ liệu hiện tại (107 chunk) |
| `requirements.txt` | Thư viện cần cài |
| `HANDOFF.md` | File này |

---

## 5. Cách chạy (cho người mới)

```bash
pip install -r requirements.txt
export MONGODB_PASSWORD="<mật khẩu DB user>"

# Hỏi 1 câu, xem đoạn liên quan nhất:
python3 run_module.py "Học phí HUIT khoảng bao nhiêu?"

# Xem toàn bộ dữ liệu:
python3 export_data.py

# Dựng lại KB từ dữ liệu đã cào (nếu cần):
python3 build_real_kb.py
python3 ensure_index_and_search.py
```

> Nếu dùng cluster / DB user khác: sửa 2 hằng số `USER` và `HOST` ở đầu mỗi script.
> Mật khẩu KHÔNG nằm trong code — luôn đọc từ biến môi trường `MONGODB_PASSWORD`.

---

## 6. Kiến trúc "1 JSON = 1 module"

Mỗi module là 1 document:
```jsonc
{
  "_id": "huit_semantic_search",
  "public":  { "node_data": { "jsonSchema": { ... } } },   // HỢP ĐỒNG DỮ LIỆU
  "private": { "node_function": { "edge": [{
      "pipeline": [ { "$vectorSearch": { ... "queryVector": "<<QUERY_VECTOR_384>>" } },
                    { "$project":     { ... } } ],           // CODE chạy trên Mongo
      "purpose": "..."                                        // MÔ TẢ
  }]}}
}
```
`run_module.py` = bộ chạy: đọc module → nhúng câu hỏi thành vector 384 chiều →
thay `<<QUERY_VECTOR_384>>` → chạy `aggregate()` trên Atlas.

---

## 7. Roadmap các bước tiếp theo

1. **Nối LLM (RAG generation)** — mảnh ghép còn lại:
   `câu hỏi → vector search (đã có) → đưa top đoạn cho LLM → LLM viết câu trả lời + trích nguồn`.
   Cần `OPENAI_API_KEY` hoặc `GEMINI_API_KEY`.
2. **Mở rộng KB** — cào thêm trang ngành/chương trình đào tạo chi tiết; chunk theo mục.
3. **Đánh giá & tinh chỉnh** — bộ câu hỏi test, đo độ chính xác retrieval, chỉnh kích thước chunk.
4. **Khung multi-agent** — mỗi module chạy độc lập, xuất kết quả ra collection kiểm thử;
   đúng → mới phát triển module kế tiếp.

---

## 8. Ghi chú kỹ thuật

- Embedding 384 chiều, similarity = cosine. Nếu đổi model embedding → phải đổi
  `numDimensions` trong index và **tạo lại index**.
- `coll.drop()` sẽ **xóa luôn vector index** → sau khi rebuild KB phải chạy
  `ensure_index_and_search.py` để tạo lại index.
- Atlas M0 (free) có hỗ trợ Vector Search (giới hạn tối đa 3 search index).
