#!/usr/bin/env python3
"""Script to generate PDF report for HUIT Chatbot Vector Search Audit & Upgrade Roadmap."""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
html_path = os.path.join(HERE, "huit_vector_search_audit.html")
pdf_path = os.path.join(HERE, "HUIT_Vector_Search_Audit_Report.pdf")

html_content = """<!DOCTYPE html>
<html lang="vi">
<head>
<meta charset="UTF-8">
<title>HUIT AI Chatbot - Báo Cáo Kiểm Duyệt Vector Search & Lộ Trình Cải Tiến</title>
<style>
  @page {
    size: A4;
    margin: 18mm 16mm 18mm 16mm;
    @bottom-right {
      content: counter(page);
      font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
      font-size: 8.5pt;
      color: #64748b;
    }
    @bottom-left {
      content: "HUIT AI Chatbot — Vector Search Audit & SOTA Upgrade Roadmap";
      font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
      font-size: 8.5pt;
      color: #64748b;
    }
  }

  body {
    font-family: 'Segoe UI', Arial, sans-serif;
    font-size: 10.5pt;
    line-height: 1.6;
    color: #0f172a;
    background: #ffffff;
  }

  h1, h2, h3, h4 {
    font-family: 'Segoe UI', Arial, sans-serif;
    color: #004b93;
  }

  .header-banner {
    border-bottom: 3px solid #0072ce;
    padding-bottom: 12px;
    margin-bottom: 25px;
  }

  .doc-tag {
    font-size: 8.5pt;
    font-weight: 700;
    color: #0072ce;
    text-transform: uppercase;
    letter-spacing: 1.2px;
  }

  .main-title {
    font-size: 22pt;
    font-weight: 800;
    color: #0f172a;
    margin: 8px 0;
    line-height: 1.25;
  }

  .main-subtitle {
    font-size: 11pt;
    color: #475569;
    font-weight: 400;
  }

  .meta-grid {
    display: table;
    width: 100%;
    background: #f8fafc;
    border: 1px solid #cbd5e1;
    border-radius: 6px;
    padding: 12px 16px;
    margin-bottom: 25px;
    font-size: 9.5pt;
  }

  .meta-row {
    display: table-row;
  }

  .meta-cell {
    display: table-cell;
    padding: 4px 10px;
  }

  .section-title {
    font-size: 14pt;
    font-weight: 700;
    color: #004b93;
    border-bottom: 1.5px solid #0072ce;
    padding-bottom: 4px;
    margin-top: 22px;
    margin-bottom: 12px;
  }

  .subsection-title {
    font-size: 11.5pt;
    font-weight: 700;
    color: #1e293b;
    margin-top: 14px;
    margin-bottom: 6px;
  }

  p { margin-bottom: 10px; text-align: justify; }

  ul, ol { margin: 6px 0 12px 20px; }
  li { margin-bottom: 4px; }

  table {
    width: 100%;
    border-collapse: collapse;
    margin: 14px 0;
    font-size: 9.5pt;
  }

  th, td {
    border: 1px solid #cbd5e1;
    padding: 7px 10px;
    text-align: left;
  }

  th {
    background: #0072ce;
    color: #ffffff;
    font-weight: 700;
  }

  tr:nth-child(even) {
    background-color: #f8fafc;
  }

  .callout-box {
    background: #eff6ff;
    border-left: 4px solid #0072ce;
    padding: 10px 14px;
    margin: 12px 0;
    border-radius: 0 4px 4px 0;
    font-size: 9.5pt;
  }

  .badge-success {
    background: #dcfce7;
    color: #166534;
    padding: 2px 6px;
    border-radius: 4px;
    font-size: 8.5pt;
    font-weight: 700;
  }

  .badge-warning {
    background: #fef9c3;
    color: #854d0e;
    padding: 2px 6px;
    border-radius: 4px;
    font-size: 8.5pt;
    font-weight: 700;
  }

  .badge-danger {
    background: #fee2e2;
    color: #991b1b;
    padding: 2px 6px;
    border-radius: 4px;
    font-size: 8.5pt;
    font-weight: 700;
  }

  code {
    font-family: 'Consolas', 'Courier New', monospace;
    background: #f1f5f9;
    padding: 2px 4px;
    border-radius: 3px;
    font-size: 9pt;
    color: #0f172a;
  }
</style>
</head>
<body>

  <div class="header-banner">
    <div class="doc-tag">Tài Liệu Kiểm Duyệt Kỹ Thuật</div>
    <div class="main-title">BÁO CÁO KIỂM DUYỆT VECTOR SEARCH & LỘ TRÌNH CẢI TIẾN HỆ THỐNG HUIT CHATBOT</div>
    <div class="main-subtitle">Phân tích chuyên sâu khâu Vector Search, so sánh độ phức tạp với chuẩn SOTA 2025–2026 và kế hoạch nâng cấp mô hình.</div>
  </div>

  <div class="meta-grid">
    <div class="meta-row">
      <div class="meta-cell"><strong>Dự án:</strong> HUIT AI Chatbot</div>
      <div class="meta-cell"><strong>Đối tượng kiểm duyệt:</strong> Subsystem Vector Search & RAG Core</div>
    </div>
    <div class="meta-row">
      <div class="meta-cell"><strong>Cơ sở dữ liệu:</strong> MongoDB Atlas (huit_chatbot)</div>
      <div class="meta-cell"><strong>Embedding Model:</strong> FastEmbed MiniLM-L12-v2 (384D)</div>
    </div>
    <div class="meta-row">
      <div class="meta-cell"><strong>Phiên bản:</strong> v3.1 (Audit Report)</div>
      <div class="meta-cell"><strong>Ngày lập:</strong> 24/07/2026</div>
    </div>
  </div>

  <div class="section-title">1. Tổng Quan Kiểm Duyệt Hệ Thống HUIT Chatbot</div>
  <p>Dự án được xây dựng theo kiến trúc <strong>Modular RAG</strong> kết hợp triết lý <strong>"1 JSON = 1 Module Code"</strong> và giao thức <strong>MCP (Model Context Protocol)</strong>. Hệ thống quản lý tri thức của 39 ngành đào tạo chính quy HUIT cùng các dữ liệu học phí, điểm sàn, học bổng từ cổng tuyển sinh <code>ts.huit.edu.vn</code>.</p>
  <ul>
    <li><strong>RAG Orchestrator:</strong> <code>api.py</code> (FastAPI) & <code>rag_core.py</code>.</li>
    <li><strong>MCP Server:</strong> <code>mcp_server.py</code> triển khai chuẩn Stdio cung cấp công cụ <code>ask_huit_admission</code> và <code>search_huit_kb</code>.</li>
    <li><strong>Kiến trúc Module JSON:</strong> <code>huit_semantic_search.module.json</code> và <code>huit_rag_answer.module.json</code> đóng gói đường ống truy vấn MongoDB.</li>
    <li><strong>Multi-LLM Fallback:</strong> Qwen 2.5 72B &rarr; Llama 3.3 70B &rarr; Gemini 2.0 Flash &rarr; GPT-3.5 Turbo.</li>
  </ul>

  <div class="section-title">2. Kiểm Duyệt Chi Tiết Khâu Vector Search (Vector Search Subsystem)</div>
  <p>Khâu Vector Search chịu trách nhiệm nhúng (embed) câu hỏi người dùng và tìm kiếm đoạn văn bản tương đồng ngữ nghĩa nhất trong MongoDB Collection <code>huit_kb</code>.</p>

  <div class="subsection-title">2.1 Thông số cấu hình hiện tại:</div>
  <ul>
    <li><strong>Embedding Model:</strong> <code>sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2</code> chạy offline qua thư viện <code>fastembed</code> (ONNX).</li>
    <li><strong>Vector Dimension:</strong> 384 chiều.</li>
    <li><strong>Distance Metric:</strong> Cosine Similarity.</li>
    <li><strong>Vector Store:</strong> MongoDB Atlas Vector Search index <code>huit_vector_index</code>.</li>
    <li><strong>Retrieval Strategy:</strong> Dense Vector Search (<code>numCandidates=100</code>, <code>limit=top_k</code>) + Regex Keyword Fallback + Heuristic Document Injection.</li>
  </ul>

  <div class="subsection-title">2.2 Nhược điểm & Điểm nghẽn kỹ thuật trong khâu Vector Search:</div>
  <ol>
    <li><span class="badge-warning">Hạn chế Không gian Vector (384D)</span>: Mô hình 384 chiều có dung lượng nhẹ nhưng khoảng không gian biểu diễn ngữ nghĩa bị hạn chế đối với câu hỏi tiếng Việt phức tạp, nhiều từ ghép hoặc từ viết tắt.</li>
    <li><span class="badge-warning">Chiến lược Cắt đoạn (Chunking) cố định</span>: Đang dùng cắt đoạn theo ký tự (<code>max_chunk_size = 750</code>). Chưa có <em>Contextual Chunking</em> nên một số chunk bị mất ngữ cảnh ngành học gốc.</li>
    <li><span class="badge-danger">Thiếu Khâu Re-ranking</span>: Chưa có mô hình Cross-Encoder Re-ranker để đánh giá lại điểm số relevance giữa câu hỏi và Top-K chunks.</li>
    <li><span class="badge-danger">Thiếu Hybrid Search chuẩn hóa</span>: Tìm kiếm vector và regex đang chạy nối tiếp chứ chưa được kết hợp điểm số bằng thuật toán <strong>Reciprocal Rank Fusion (RRF)</strong>.</li>
  </ol>

  <div class="section-title">3. Đánh Giá Độ Cải Tiến & So Sánh Với Chuẩn SOTA (2025–2026)</div>
  <p>Hệ thống hiện đạt mức <strong>Intermediate Modular RAG (RAG Trung Cấp)</strong> với độ phức tạp đạt <strong>6.5 / 10</strong>. Dưới đây là bảng đối sánh với tiêu chuẩn công nghệ RAG doanh nghiệp hiện tại:</p>

  <table>
    <thead>
      <tr>
        <th>Tiêu chí kỹ thuật</th>
        <th>Hệ thống HUIT hiện tại</th>
        <th>Chuẩn SOTA 2025–2026</th>
        <th>Đánh giá nâng cấp</th>
      </tr>
    </thead>
    <tbody>
      <tr>
        <td><strong>Embedding Model</strong></td>
        <td>FastEmbed MiniLM-L12 (384D)</td>
        <td><code>BAAI/bge-m3</code> (1024D) / <code>multilingual-e5-large</code></td>
        <td><span class="badge-warning">Nâng cấp 1024D (+30% recall)</span></td>
      </tr>
      <tr>
        <td><strong>Retrieval Pipeline</strong></td>
        <td>Dense Search + Fallback Regex</td>
        <td><strong>Hybrid Search (Dense + Sparse BM25) + RRF</strong></td>
        <td><span class="badge-danger">Bắt chính xác mã ngành/số liệu</span></td>
      </tr>
      <tr>
        <td><strong>Chunking Strategy</strong></td>
        <td>Cắt ký tự cố định (~750 chars)</td>
        <td><strong>Contextual Retrieval</strong> (Gắn Metadata & Title)</td>
        <td><span class="badge-warning">Loại bỏ chunk mất ngữ cảnh</span></td>
      </tr>
      <tr>
        <td><strong>Re-ranking Stage</strong></td>
        <td>Không có</td>
        <td><strong>Cross-Encoder Reranker</strong> (bge-reranker-v2-m3)</td>
        <td><span class="badge-danger">Rất quan trọng (Giảm hallucination)</span></td>
      </tr>
      <tr>
        <td><strong>Evaluation Framework</strong></td>
        <td>Script test thủ công</td>
        <td>Khung đánh giá tự động <strong>RAGAS / TruLens</strong></td>
        <td><span class="badge-success">Đo lường định lượng cụ thể</span></td>
      </tr>
    </tbody>
  </table>

  <div class="section-title">4. Lộ Trình Cải Tiến Mô Hình (Model Upgrade Roadmap)</div>
  
  <div class="callout-box">
    <strong>Mục tiêu cải tiến:</strong> Đưa độ chính xác truy vấn (Context Recall) lên &gt;92%, giảm thiểu ảo giác của LLM xuống &lt;2%, tối ưu thời gian phản hồi &lt;1.2s.
  </div>

  <div class="subsection-title">Giai đoạn 1: Contextual Chunking & Upgrade Embedding 1024D</div>
  <ul>
    <li>Chuyển mô hình Embedding sang <code>BAAI/bge-m3</code> hoặc <code>intfloat/multilingual-e5-base</code> (tăng từ 384D lên 1024D).</li>
    <li>Cập nhật pipeline trong <code>build_real_kb.py</code>: Tự động chèn metadata <code>[Ngành: <Tên Ngành> | Mã: <Mã Ngành>]</code> vào đầu từng văn bản chunk trước khi tạo embedding.</li>
    <li>Khởi tạo lại Atlas Vector Search Index với <code>numDimensions: 1024</code>.</li>
  </ul>

  <div class="subsection-title">Giai đoạn 2: Tích hợp Re-ranker & Hybrid Search</div>
  <ul>
    <li>Thêm mô hình Re-ranker nhẹ (<code>bge-reranker-v2-m3</code> hoặc <code>ms-marco-MiniLM-L-6-v2</code>). Truy vấn 15 candidates từ MongoDB, sau đó re-rank lấy Top 3 cho LLM.</li>
    <li>Kết hợp thuật toán Reciprocal Rank Fusion (RRF) cho Dense Vector Search và Sparse Keyword Search.</li>
  </ul>

  <div class="subsection-title">Giai đoạn 3: Đánh giá tự động với RAGAS Framework</div>
  <ul>
    <li>Tạo dataset 50 câu hỏi benchmark kèm đáp án chuẩn (Ground Truth).</li>
    <li>Chạy RAGAS evaluator đo chỉ số Faithfulness, Answer Relevance, Context Recall và Context Precision.</li>
  </ul>

  <div class="callout-box" style="background: #f8fafc; border-left-color: #475569;">
    <strong>XÁC NHẬN CHUYỂN GIAO:</strong> File PDF này đóng vai trò bản báo cáo kiểm duyệt chính thức. Ngay sau đây, chúng ta sẽ bắt đầu bắt tay vào việc thực thi Giai đoạn 1 của Lộ trình Cải tiến.
  </div>

</body>
</html>
"""

with open(html_path, "w", encoding="utf-8") as f:
    f.write(html_content)

print("[OK] HTML Audit Report written to:", html_path)

# Convert to PDF via Microsoft Edge headless
edge_exe = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
if not os.path.exists(edge_exe):
    edge_exe = r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"

if not os.path.exists(edge_exe):
    print("[ERROR] Microsoft Edge executable not found for PDF printing.")
    sys.exit(1)

cmd = [
    edge_exe,
    "--headless",
    "--disable-gpu",
    f"--print-to-pdf={pdf_path}",
    f"file:///{html_path.replace(os.sep, '/')}"
]

print("Executing PDF generation command...")
res = subprocess.run(cmd, capture_output=True, text=True)

if os.path.exists(pdf_path):
    print(f"[SUCCESS] PDF successfully created at: {pdf_path} ({os.path.getsize(pdf_path)} bytes)")
else:
    print("[FAIL] PDF generation failed!")
    print("Stderr:", res.stderr)
