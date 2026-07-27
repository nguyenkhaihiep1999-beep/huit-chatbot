# HUIT-AI RAG SYSTEM
## Khung Kiến Trúc Trợ Lý AI Tuyển Sinh, MongoDB Vector Search & Giao Thức Đào Dữ Liệu MCP

---

### THÔNG TIN TÀI LIỆU

- **Mục tiêu**: Báo cáo toàn diện hệ thống AI tư vấn tuyển sinh HUIT: Cơ sở dữ liệu MongoDB Atlas, quy trình xây dựng & khai thác dữ liệu (Data Pipeline), triết lý đóng gói "1 JSON = 1 Module Code", giao thức đào dữ liệu MCP (Model Context Protocol) và giao diện Chatbot 3D HUIT Royal Blue.
- **Phạm vi**: Toàn bộ hệ thống Backend FastAPI (`api.py`), Lõi RAG (`rag_core.py`), MCP Server Stdio (`mcp_server.py`), MongoDB Collections (`huit_kb`, `code_modules`) và Giao diện Web (`static/index.html`).
- **Phiên bản**: v3.0 — Bản kiểm toán kỹ thuật toàn diện.

*Bản biên soạn hệ thống độc lập theo quy trình RAG-VectorSearch, MongoDB Code Modules & MCP Data Mining Protocol.*

---

## Mục lục

1. **Tuyên ngôn phương pháp & Triết lý kiến trúc**
2. **Cơ sở dữ liệu MongoDB Atlas & Cấu trúc Collection**
3. **Quy trình xây dựng & Khai thác dữ liệu (Data Pipeline & Mining)**
4. **Triết lý "1 JSON = 1 Module Code" & Mã nguồn JSON chi tiết**
5. **Giao thức đào dữ liệu qua MCP (Model Context Protocol)**
6. **Bảy lớp trạng thái nhận thức dữ liệu (Data Perception Layers)**
7. **Đơn vị vận hành: Hồ sơ tri thức của một câu hỏi**
8. **Máy trạng thái xử lý RAG & Multi-Model Fallback LLM**
9. **Kiến trúc nhiều vai trong hệ thống**
10. **Hạ tầng công cụ & Công nghệ cốt lõi**
11. **Quản trị cây tìm kiếm Vector Search & Điểm tương đồng**
12. **Thang kiểm chứng mức độ tin cậy & Completion Gate**
13. **Ba chế độ đầu ra hệ thống (Research, Exam, Audit/MCP)**
14. **Bản skill vận hành cô đặc & Kết luận**

---

## 1. Tuyên ngôn phương pháp & Triết lý kiến trúc

HUIT-AI System không phải là một câu lệnh prompt đơn thuần yêu cầu AI "hãy trả lời câu hỏi tuyển sinh". Nó là một **Hệ điều hành tư vấn tuyển sinh có trạng thái**, trong đó tri thức gốc, câu hỏi người dùng, bổ đề truy vấn, vector embedding, nguồn trích dẫn và mã JSON module được quản trị như các đối tượng minh bạch.

### Nguyên lý trung tâm

> **Dữ liệu thật từ MongoDB Atlas**: Dữ liệu tuyển sinh chính thức từ `ts.huit.edu.vn` được cào, làm sạch và lưu trữ thành 321 chunks chuẩn hóa trong MongoDB collection `huit_kb`. **Triết lý 1 JSON = 1 Module Code** đóng gói toàn bộ logic truy vấn vector và tổng hợp câu trả lời vào collection `code_modules`.

---

## 2. Cơ sở dữ liệu MongoDB Atlas & Cấu trúc Collection

Hệ thống sử dụng MongoDB Atlas Cluster Cloud bền vững:
- **Cluster**: `cluster0.hyj8rab.mongodb.net`
- **Database**: `huit_chatbot`
- **User**: `nguyenkhaihiep1999_db_user`

### 2.1 Collection `huit_kb` (Kho tri thức Vector 384D)
Chứa 321 tài liệu dạng JSON với cấu trúc:
```json
{
  "_id": "ObjectId(...)",
  "title": "Học phí ngành Công nghệ Thông tin HUIT 2026",
  "text": "Mức học phí trung bình ngành CNTT HUIT khoảng 14 - 16 triệu đồng/học kỳ...",
  "url": "https://ts.huit.edu.vn",
  "embedding": [-0.0245, 0.0812, 0.0119, ..., 384 dimensions],
  "page_title": "Cổng tuyển sinh chính thức HUIT"
}
```

### 2.2 Vector Search Index (`huit_vector_index`)
Đã khởi tạo sẵn trên MongoDB Atlas với cấu hình Cosine Similarity 384 chiều:
```json
{
  "fields": [
    {
      "numDimensions": 384,
      "path": "embedding",
      "similarity": "cosine",
      "type": "vector"
    }
  ]
}
```

---

## 3. Quy trình xây dựng & Khai thác dữ liệu (Data Pipeline & Mining)

### Bước 1: Cào dữ liệu thô (`step1_ingest_raw.py`)
Cào toàn bộ 66 trang tuyển sinh chính thức từ `ts.huit.edu.vn` và bài viết học phí, lưu vào `scraped_pages.json`.

### Bước 2: Làm sạch & Cắt nhỏ Chunks (`step2_data_cleaning.py`)
Phân chia văn bản thô thành 321 chunks sạch (~300-500 tokens), bổ sung tiêu đề và đường link trích dẫn `url`, xuất ra `huit_kb_data.csv`.

### Bước 3: Đánh chỉ mục Dense Vector 384D (`embed_and_index.py`)
Sử dụng mô hình FastEmbed `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` để chuyển đổi từng chunk thành vector 384 chiều và upload lên MongoDB collection `huit_kb`.

---

## 4. Triết lý "1 JSON = 1 Module Code" & Mã nguồn JSON chi tiết

Toàn bộ logic nghiệp vụ được lưu dưới dạng JSON trong MongoDB collection `code_modules`:

### Module 1: `huit_semantic_search.module.json`
```json
{
  "_id": "huit_semantic_search",
  "module_name": "huit_semantic_search",
  "version": "2.5.0",
  "private": {
    "node_function": {
      "edge": [
        {
          "config": {
            "vector_index": "huit_vector_index",
            "embedding_field": "embedding",
            "top_k": 3
          },
          "pipeline": [
            {
              "$vectorSearch": {
                "index": "huit_vector_index",
                "path": "embedding",
                "queryVector": "<<QUERY_VECTOR_384>>",
                "numCandidates": 100,
                "limit": 3
              }
            },
            {
              "$project": {
                "_id": 1,
                "title": 1,
                "text": 1,
                "url": 1,
                "score": { "$meta": "vectorSearchScore" }
              }
            }
          ]
        }
      ]
    }
  }
}
```

### Module 2: `huit_rag_answer.module.json`
```json
{
  "_id": "huit_rag_answer",
  "module_name": "huit_rag_answer",
  "version": "2.5.0",
  "private": {
    "node_function": {
      "edge": [
        {
          "config": {
            "system_prompt": "Bạn là Trợ Lý AI Tuyển Sinh HUIT (ĐH Công Thương TP.HCM). Trả lời dựa trên ngữ cảnh tri thức được cung cấp.",
            "answer_template": "Dữ liệu tri thức HUIT:\n{context}\n\nCâu hỏi: {question}\n\nTrả lời:",
            "top_k": 3
          }
        }
      ]
    }
  }
}
```

---

## 5. Giao thức đào dữ liệu qua MCP (Model Context Protocol)

File [mcp_server.py](file:///d:/chatbot2/huit_chatbot_handoff%20%282%29/huit_vs/mcp_server.py) triển khai chuẩn giao thức MCP Stdio JSON-RPC:

### 5.1 Các công cụ đào dữ liệu (MCP Tools)
1. **`ask_huit_admission(question)`**:
   - **Chức năng**: Đào thông tin câu trả lời tư vấn hoàn chỉnh từ MongoDB Atlas RAG + LLM.
   - **Trả về**: Văn bản trả lời tự nhiên + Danh sách nguồn trích dẫn.
2. **`search_huit_kb(query, top_k)`**:
   - **Chức năng**: Khai thác trực tiếp các đoạn văn bản vector search từ collection `huit_kb`.
   - **Trả về**: Điểm tương đồng cosine, tiêu đề và nội dung thô.

### 5.2 Cấu hình kết nối MCP Client (Claude Desktop / Cursor / Antigravity)
Thêm vào file cấu hình `mcpServers`:
```json
{
  "mcpServers": {
    "huit-admission": {
      "command": "python",
      "args": ["d:/chatbot2/huit_chatbot_handoff (2)/huit_vs/mcp_server.py"],
      "env": {
        "MONGODB_PASSWORD": "<set-in-environment>",
        "OPENROUTER_API_KEY": "your_openrouter_api_key_here"
      }
    }
  }
}
```

---

## 6. Bảy lớp trạng thái nhận thức dữ liệu (Data Perception Layers)

| Nhãn | Ý nghĩa trong hệ thống HUIT Chatbot |
| :--- | :--- |
| **OBSERVATION** | Thông tin hiển nhiên trực tiếp từ website ts.huit.edu.vn. |
| **HEURISTIC** | Trực giác định hướng ngữ cảnh từ câu hỏi người dùng. |
| **CONJECTURE** | Dự đoán ý định của thí sinh (VD: hỏi "máy tính" -> CNTT). |
| **SUPPORTED CONJECTURE** | Thông tin được hỗ trợ bởi nhiều chunk dữ liệu liên quan. |
| **LEMMA-CANDIDATE** | Bổ đề dữ liệu trung gian (VD: tổng tín chỉ x đơn giá). |
| **VERIFIED LEMMA** | Dữ liệu học phí, điểm sàn đã được khóa đối soát chính xác 100%. |
| **THEOREM (SOLVED)** | Câu trả lời hoàn chỉnh đã trích dẫn đủ nguồn MongoDB Atlas. |

---

## 7. Đơn vị vận hành: Hồ sơ tri thức của một câu hỏi

### 7.1 Problem Specification
Ghi nhận đối tượng hỏi, ngành học, loại hình học phí, năm tuyển sinh.

### 7.2 Proof Obligation Graph
Gồm các nút nghĩa vụ `OPEN`, `PARTIAL`, `VERIFIED`, `REFUTED`.

---

## 8. Máy trạng thái xử lý RAG & Multi-Model Fallback LLM

Khi có request, hệ thống thực hiện qua các pha:
- **Pha 0: Intake** — Chuẩn hóa câu hỏi.
- **Pha 1: Classification** — Phân loại chuyên đề.
- **Pha 2: Vector Search** — Tạo embedding 384D & query `$vectorSearch` trên `huit_kb`.
- **Pha 3: Fallback Generation** — Gọi LLM theo chuỗi ưu tiên: Qwen 2.5 72B -> Llama 3.3 70B -> DeepSeek -> Gemini -> GPT-3.5 Turbo.
- **Pha 4: Formalization & Citation** — Đóng gói câu trả lời Markdown & đính kèm thẻ link Clickable `https://ts.huit.edu.vn`.

---

## 9. Kiến trúc nhiều vai trong hệ thống

- **Orchestrator (`api.py`)**: Web server FastAPI điều phối HTTP request.
- **Retriever (`rag_core.retrieve`)**: Chạy Vector Search 384D trên MongoDB.
- **Generator (`rag_core._call_llm`)**: Xử lý chuỗi Fallback LLM.
- **MCP Bridge (`mcp_server.py`)**: Phục vụ giao thức Stdio MCP cho các AI Agent.

---

## 10. Hạ tầng công cụ & Công nghệ cốt lõi

- **Backend**: Python 3.10+, FastAPI, PyMongo, FastEmbed.
- **Database**: MongoDB Atlas (`huit_kb`, `code_modules`).
- **Frontend**: Vanilla HTML5/CSS3 (HUIT Royal Blue `#0072ce`), Web Speech API `vi-VN`, Mascot 3D HUIT Robot với hiệu ứng `robotLiveMotion`, AbortController `🛑 Dừng`.

---

## 11. Quản trị cây tìm kiếm & Điểm tương đồng

Điểm đánh giá tương đồng ngữ nghĩa:

$$\text{Score} = \text{CosineSimilarity}(\vec{v}_{\text{query}}, \vec{v}_{\text{chunk}})$$

---

## 12. Thang kiểm chứng & Completion Gate

Một câu hỏi chỉ được gắn **SOLVED** khi:
1. Đã tìm thấy tài liệu gốc trên MongoDB Atlas `huit_kb`.
2. Đã đính kèm thẻ nguồn Clickable mở `https://ts.huit.edu.vn`.
3. Không vi phạm ảo giác thông tin.
4. Hỗ trợ nút `🛑 Dừng` ngắt lệnh tức thì.

---

## 13. Ba chế độ đầu ra

1. **Research Mode**: Giao diện Web Chatbot HUIT Blue cao cấp (Mascot 3D Robot, STT, TTS, Download).
2. **Exam Mode**: Endpoint REST API `/api/chat` trả về JSON chuẩn.
3. **Audit / MCP Mode**: Giao thức Stdio JSON-RPC phục vụ đào dữ liệu trực tiếp qua MCP.

---

## 14. Bản skill vận hành cô đặc & Kết luận

```markdown
HƯỚNG DẪN VẬN HÀNH RAG HUIT AI:
1. Chuẩn hóa câu hỏi tuyển sinh HUIT.
2. Truy vấn Vector Search 384D trên collection huit_kb (MongoDB Atlas).
3. Đóng gói câu trả lời kèm thẻ trích dẫn link https://ts.huit.edu.vn.
4. Phục vụ giao thức đào dữ liệu MCP Stdio qua mcp_server.py.
```

---

*Hệ thống Trợ lý AI Tuyển sinh HUIT đã hoàn chỉnh 100% về Cơ sở dữ liệu MongoDB Atlas, Mã JSON Modules, Giao thức đào dữ liệu MCP và Báo cáo PDF kỹ thuật.*
