# HƯỚNG DẪN QUY TRÌNH MIGRATION MONGODB (MONGODB MIGRATIONS RUNBOOK)

Tài liệu này cung cấp hướng dẫn vận hành bộ migration lũy đẳng cho hệ thống HUIT Chatbot, đảm bảo tính toàn vẹn dữ liệu, kiểm tra điều kiện trước khi ghi, sao lưu và rollback có kiểm soát.

---

## 1. Nguyên Tắc An Toàn & Chuẩn Bị

> [!CAUTION]
> **Quy Tắc Vận Hành Bắt Buộc:**
> 1. **Dry-Run Đầu Tiên**: Luôn luôn chạy với cờ `--dry-run` trước để kiểm tra số lượng bản ghi bị ảnh hưởng.
> 2. **Không Chạy Trực Tiếp Khi Chưa Được Phê Duyệt**: Mọi thao tác `--apply` lên MongoDB Atlas production phải có sự xác nhận rõ ràng của Quản trị viên/Kỹ sư trưởng.
> 3. **Tự Động Sao Lưu (Automatic Backup)**: Các script sửa dữ liệu (`002`-`006`, `014`-`016`) phải sao lưu collection nguồn sang `{collection}_backup_{timestamp}` trước khi cập nhật.
> 4. **Bảo Vệ Credentials**: Tuyệt đối không hardcode mật khẩu hay connection string vào code hay in ra màn hình console/log.
> 5. **Idempotency (Tính Lũy Đẳng)**: Mọi script có thể chạy lặp lại nhiều lần mà không gây lỗi hoặc làm biến dạng dữ liệu.

---

## 2. Danh Mục Migration

| Thứ tự | Tên Script | Mục tiêu | Thao tác chính |
| :---: | :--- | :--- | :--- |
| **001** | `001_audit_mongodb_schema.py` | Khảo sát Read-only | Quét 19 collections, phát hiện string dates, Base64, duplicates, validators |
| **002** | `002_normalize_datetime_fields.py` | Chuẩn hóa BSON Date | Chuyển ISO string sang BSON Date UTC (`jobs`, `assets`, `admission_visuals`, `huit_kb`) |
| **003** | `003_migrate_asset_documents.py` | Deduplication Assets | Giải quyết 4 bản ghi trùng `content_hash`, thêm `schema_version = 1`, validate `MongoAssetRecord` |
| **004** | `004_migrate_job_documents.py` | Chuẩn hóa Jobs & TTL | Thêm `schema_version = 1`, giới hạn 30 events, tính `expires_at` phục vụ TTL dọn dẹp |
| **005** | `005_migrate_generated_images.py` | Chuẩn hóa Generated Images | Phân loại backend (`flux` / `svg`), sinh `generation_key`, thêm `schema_version = 1` |
| **006** | `006_remove_legacy_binary_fields.py` | Trích xuất Binary & Dọn rác | Đưa `image_data` ra `StorageAdapter`, xác thực checksum, xóa `original_question` & Base64 |
| **007** | `007_create_indexes.py` | Tạo Indexes bắt buộc | Kiểm tra pre-condition không còn trùng lặp rồi mới tạo Unique/TTL/Compound Indexes |
| **008** | `008_apply_validators.py` | Áp dụng `$jsonSchema` | Cấu hình `collMod` với `$jsonSchema`, `validationLevel: moderate`, `validationAction: error` |
| **009** | `009_verify_migration.py` | Nghiệm thu toàn diện | Kiểm tra 100% tiêu chuẩn nghiệm thu, đảm bảo Vector Search `huit_kb` nguyên vẹn |
| **014** | `014_fix_image_dedup_index.py` | Khắc phục Dedup Index | Drop index unique toàn cục `content_hash_1`, tạo partial compound index `owner_request_fingerprint_unique_v1` |
| **015** | `015_sync_job_and_image_validators.py` | Bổ sung Trường Bền bỉ | Backfill retry/lease/heartbeat/idempotency và cập nhật `$jsonSchema` |
| **016** | `016_remove_admission_visual_base64.py` | Thu gọn Admission Visual | Preflight schema, backup, xóa các trường Base64/binary và khóa bằng validator |
| **017** | `017_sync_assets_validator.py` | Đồng bộ Assets Validator | Preflight dữ liệu hiện hữu và bắt buộc `file_ext` trong `$jsonSchema` |
| **REC** | `storage_reconciliation.py` | Đối soát & Sửa chữa Storage | Quét chênh lệch MongoDB assets vs Storage vật lý, tái tạo SVG xác định và dọn dẹp rác |

### Trạng thái production ngày 2026-09-15

| Migration | Trạng thái | Kết quả |
| :---: | :--- | :--- |
| **014** | Đã áp dụng | Backfill 43 `request_fingerprint`; tạo `owner_request_fingerprint_unique_v1` và `content_hash_lookup_v1`; backup `generated_images_backup_20260915_083140` |
| **015** | Đã áp dụng | Backfill 23 jobs; tạo idempotency index; cập nhật validator `jobs` và `generated_images`; backups `jobs_backup_20260915_083207`, `generated_images_backup_20260915_083208` |
| **016** | Đã áp dụng | Xóa trường nặng khỏi 46/46 `admission_visuals`, còn sót 0; backup `admission_visuals_backup_20260915_084835`; validator đã bật |
| **017** | Đã áp dụng | Preflight 46/46 assets hợp lệ; validator bắt buộc `file_ext` đã bật, 0 lỗi |
| **REC** | Đã áp dụng | Phục hồi 6 SVG + 1 Excel; dọn 12 placeholder; sửa 36 checksum; 4 orphan thật chuyển vào quarantine; hậu kiểm không còn sai lệch |

Các báo cáo áp dụng nằm trong `audit_outputs/014_apply_latest.json`, `015_apply_latest.json`, `016_apply_latest.json`, `017_apply_latest.json` và `storage_reconciliation_apply_latest.json`. Báo cáo nghiệm thu cuối là `audit_outputs/009_verify_post_cleanup.json` với `overall_passed = true`.

---

## 3. Quy Trình Thực Thi Chi Tiết

### Bước 1: Khảo sát hiện trạng (Read-Only)
```bash
python scripts/migrations/001_audit_mongodb_schema.py --dry-run
```

### Bước 2: Chạy thử nghiệm mô phỏng toàn bộ chuỗi (Dry-Run Phase)
```bash
python scripts/migrations/002_normalize_datetime_fields.py --dry-run
python scripts/migrations/003_migrate_asset_documents.py --dry-run
python scripts/migrations/004_migrate_job_documents.py --dry-run
python scripts/migrations/005_migrate_generated_images.py --dry-run
python scripts/migrations/006_remove_legacy_binary_fields.py --dry-run
python scripts/migrations/007_create_indexes.py --dry-run
python scripts/migrations/008_apply_validators.py --dry-run
python scripts/migrations/014_fix_image_dedup_index.py --dry-run
python scripts/migrations/015_sync_job_and_image_validators.py --dry-run
python scripts/migrations/016_remove_admission_visual_base64.py --dry-run
python scripts/migrations/017_sync_assets_validator.py --dry-run
```
*Đọc các file báo cáo JSON trong thư mục `audit_outputs/` để xác nhận số lượng bản ghi cần xử lý.*

### Bước 3: Thực thi Migration (Apply Phase - Chỉ chạy sau khi có phê duyệt)
```bash
# 1. Chuẩn hóa ngày giờ
python scripts/migrations/002_normalize_datetime_fields.py --apply

# 2. Khử trùng lặp và chuẩn hóa assets
python scripts/migrations/003_migrate_asset_documents.py --apply

# 3. Chuẩn hóa jobs và gắn hạn TTL
python scripts/migrations/004_migrate_job_documents.py --apply

# 4. Chuẩn hóa generated images
python scripts/migrations/005_migrate_generated_images.py --apply

# 5. Trích xuất binary sang Storage và làm sạch Base64/Privacy
python scripts/migrations/006_remove_legacy_binary_fields.py --apply

# 6. Tạo toàn bộ indexes
python scripts/migrations/007_create_indexes.py --apply

# 7. Kích hoạt $jsonSchema validators
python scripts/migrations/008_apply_validators.py --apply

# 8. Sửa dedup ảnh theo owner/request
python scripts/migrations/014_fix_image_dedup_index.py --apply

# 9. Đồng bộ trường bền bỉ và validators
python scripts/migrations/015_sync_job_and_image_validators.py --apply

# 10. Xóa Base64/binary khỏi admission_visuals
python scripts/migrations/016_remove_admission_visual_base64.py --apply

# 11. Đối soát và sửa storage sau khi dry-run đã được phê duyệt
python scripts/storage_reconciliation.py --apply

# 12. Đồng bộ assets validator sau khi storage đã sạch
python scripts/migrations/017_sync_assets_validator.py --apply

# 13. Nghiệm thu tổng thể (read-only; không cần --apply)
python scripts/migrations/009_verify_migration.py --dry-run
```

---

## 4. Quy Trình Khôi Phục Dữ Liệu (Rollback Procedure)

Nếu có sự cố phát sinh tại bất kỳ bước nào trong quá trình `--apply`:
1. Mỗi script tự động tạo bản sao lưu dạng `{collection}_backup_{timestamp}` (ví dụ: `assets_backup_20260914_110000`).
2. Để khôi phục dữ liệu nguyên trạng của một collection:
   ```python
   # Chạy script khôi phục nhanh qua mongosh hoặc Python:
   from scripts.migrations.common import get_migration_db
   _, db = get_migration_db()

   # Xóa collection lỗi và đổi tên backup về ban đầu:
   db["assets"].drop()
   db["assets_backup_20260914_110000"].rename("assets")
   print("Đã khôi phục hoàn tất collection 'assets' từ bản backup!")
   ```
3. Khôi phục trạng thái index cũ:
   ```bash
   # Nếu cần drop index vừa tạo:
   db.assets.dropIndex("content_hash_1")
   ```
