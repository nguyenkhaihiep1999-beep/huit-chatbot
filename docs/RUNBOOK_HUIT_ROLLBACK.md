# Runbook: Phục hồi Kho tri thức và Profile HUIT từ Gói Sao lưu `.bak`

Tài liệu này hướng dẫn quy trình vận hành chuẩn để khôi phục hoàn toàn kho tri thức, cấu hình phục vụ và dữ liệu phụ thuộc của **Trường Đại học Công Thương TP.HCM (HUIT)** trên hệ thống chatbot `D:\chatbot2`.

---

## 1. Thông tin Gói sao lưu Đã kiểm chứng (Verified Artifact)

- **Đường dẫn artifact**: `backups/huit-20261024_105842.bak`
- **Định dạng vật lý**: Container `tar.gz` tự chứa (self-contained BSON dump + metadata manifest + centroids + templates).
- **Kích thước file**: `5,702,560 bytes` (~5.44 MB)
- **SHA-256 Checksum**: `1cd9bd9f083c0a79e51deec3b3582b928b1aba64cdf22ec5b6e4e58c266e45b3`
- **Phạm vi dữ liệu tự chứa**:
  1. `huit_kb`: 399 tài liệu tri thức tuyển sinh, đầy đủ 1024 chiều embedding (`intfloat/multilingual-e5-large`), `_id` ObjectId, metadata ngành học, năm tuyển sinh, điểm sàn, học phí.
  2. `scraped_sources`: 284 bản ghi nguồn cào từ cổng thông tin `ts.huit.edu.vn`.
  3. `curated_sources`: 15 bản ghi nguồn đã biên tập chuẩn hóa.
  4. `admission_visuals`: 8 metadata đồ họa tuyển sinh trực quan.
  5. `audit_events`: 1 snapshot sự kiện kiểm toán vận hành.
  6. `system_snapshots`: Snapshot hệ thống phục vụ đối soát.
  7. `search_index_definitions`: Định nghĩa chuẩn của Atlas Vector Search Index (`huit_vector_index`) 1024 chiều Cosine.
  8. `assets/huit_cluster_centroids.json`: Tọa độ 8 cụm centroid K-Means HUIT.
  9. `assets/profile_config.json`: Toàn bộ system prompt, template trả lời và contact HUIT.
- **Chứng minh thực tế (Proof of Restoration)**: Đã thực hiện restore mẫu sang database Atlas thật với hậu tố `_restore_test`. Kết quả: 7/7 collections phục hồi đầy đủ 707 documents, BSON types và vector embeddings bảo toàn 100%, Search Index đạt trạng thái `READY` (queryable) sau 18 giây.

---

## 2. Phương án 1: Hot-Switch Zero-Downtime (Khuyên dùng khi hạ tầng Atlas còn nguyên)

Vì quá trình chuyển đổi sang ILT tuân thủ nguyên tắc **không ghi đè hoặc xóa kho tri thức HUIT**, collection `huit_kb` và Atlas Search Index `huit_vector_index` vẫn đang tồn tại song song và sẵn sàng phục vụ 100% trên MongoDB Atlas.

### Bước 1: Chuyển cấu hình Profile trong `backend/.env`
Mở file `backend/.env` và cập nhật:
```ini
ACTIVE_PROFILE=huit
PRIMARY_LLM_PROVIDER=gemini
JEV_MODE=assist
HUIT_JEV_INTENT_MODE=assist
HUIT_JEV_EVIDENCE_MODE=off
```

### Bước 2: Khởi động lại tiến trình backend
```powershell
# Nếu đang chạy local dev:
# Dừng terminal đang chạy uvicorn (Ctrl+C) và khởi động lại:
python -m uvicorn backend.app.main:app --host 0.0.0.0 --port 8000 --reload
```

### Bước 3: Xác minh Profile đang phục vụ
```powershell
python -c "from backend.app.rag.profile import get_profile; p = get_profile(); print('Active Profile:', p.id, '-', p.name)"
# Kết quả mong đợi: Active Profile: huit - HUIT Tuyển sinh
```

---

## 3. Phương án 2: Phục hồi Toàn diện từ Gói `.bak` (Disaster Recovery)

Sử dụng công cụ `scripts/manage_huit_backup.py` khi dữ liệu HUIT trên Atlas bị mất hoặc cần phục hồi sang một cluster/database mới.

### Bước 1: Kiểm tra tính toàn vẹn gói sao lưu (Verify Checksum)
```powershell
python scripts/manage_huit_backup.py verify --backup-file backups/huit-20261024_105842.bak
```
**Kết quả mong đợi**:
```text
[VERIFY] Checking integrity of backups/huit-20261024_105842.bak...
[VERIFY] Computed SHA-256: 1cd9bd9f083c0a79e51deec3b3582b928b1aba64cdf22ec5b6e4e58c266e45b3
[VERIFY] Manifest collections: 7, total docs: 707
[VERIFY] STATUS: VALID
```

### Bước 2: Chạy thử nghiệm không ghi (Dry-run Restore)
```powershell
python scripts/manage_huit_backup.py restore --backup-file backups/huit-20261024_105842.bak --target-suffix restore_test --dry-run
```
Lệnh này phân tích toàn bộ BSON trong package, đối chiếu schema và in ra kế hoạch phục hồi mà không ghi bất kỳ dữ liệu nào vào MongoDB.

### Bước 3: Phục hồi thực tế sang MongoDB Atlas
```powershell
# Phục hồi vào namespace kiểm thử để thẩm định:
python scripts/manage_huit_backup.py restore --backup-file backups/huit-20261024_105842.bak --target-suffix restore_test

# HOẶC phục hồi trực tiếp vào production namespace (nếu collection cũ bị mất):
python scripts/manage_huit_backup.py restore --backup-file backups/huit-20261024_105842.bak
```

Script sẽ tự động:
1. Nạp lại 7 collection BSON vào MongoDB Atlas (`huit_kb`, `scraped_sources`, ...).
2. Tạo lại các Regular Indexes (Unique Index trên `chunk_id`, Index trên `category`, `year`, `major_code`).
3. Gửi Search Index Definition lên Atlas Search Management API để tạo `huit_vector_index`.
4. Poll trạng thái Search Index qua vòng lặp thông minh cho đến khi đạt trạng thái `READY` (queryable).
5. Trích xuất file centroids `data/huit_cluster_centroids.json`.

---

## 4. Bộ lệnh Kiểm tra Nghiệm thu sau khi Phục hồi (Post-Rollback Verification)

### Kiểm tra 1: Chạy toàn bộ Test Suites HUIT Hướng 1 & Hướng 2
```powershell
python -m pytest backend/tests/test_jev_assist_mode_chat.py backend/tests/test_jev_shadow_mode_chat.py backend/tests/test_jev_evidence_and_dual_task.py -v
```
**Tiêu chí đạt**: 48/48 tests PASSED (không có lỗi rớt mạng, schema hoặc routing).

### Kiểm tra 2: Chạy Smoke Test Trực tiếp RAG Pipeline
```powershell
python -c "from backend.app.rag.pipeline import answer; res = answer('Học phí ngành Công nghệ thông tin HUIT năm 2026 là bao nhiêu?', use_cache=False); print('Status:', res.get('status')); print('Sources:', len(res.get('sources', []))); print('Preview:', res.get('answer', '')[:200])"
```
**Tiêu chí đạt**:
- Phản hồi chứa thông tin học phí HUIT (khoảng 14 - 16 triệu đồng/học kỳ hoặc 30 - 34 triệu đồng/năm).
- Nguồn trích dẫn `[1]` trỏ về `https://ts.huit.edu.vn`.
- Hoàn toàn không lẫn dữ liệu đèn chiếu sáng của ILT.

### Kiểm tra 3: Xác minh Frontend Chatbot UI
1. Mở trình duyệt tại `http://localhost:5173`.
2. Tiêu đề hiển thị: **HUIT Tuyển sinh AI** (compact: **HUIT AI**).
3. 4 gợi ý hiển thị:
   - *Học phí HUIT năm 2026 là bao nhiêu?*
   - *Cho tôi danh sách ngành tuyển sinh.*
   - *Tạo bảng Excel học phí các ngành.*
   - *Điểm chuẩn ngành Công nghệ thông tin?*
4. Giao diện sẵn sàng nhận tin nhắn và phát luồng NDJSON v2.
