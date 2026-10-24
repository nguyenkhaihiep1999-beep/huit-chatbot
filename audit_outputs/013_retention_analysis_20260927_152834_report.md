# Báo Cáo Phân Tích Dung Lượng & Chính Sách Lưu Trữ (huit_chatbot)
**Thời gian thực hiện:** 2026-09-27T15:28:34.808164+00:00

## 1. Tổng Quan Hệ Thống Lưu Trữ
- **Tổng số collection:** 56
- **Core collections:** 8
- **Backup collections:** 32
- **Test / Temp collections:** 6
- **Tổng số documents:** 573,771
- **Dung lượng lưu trữ đĩa:** 86.34 MB
- **Dung lượng index:** 41.16 MB
- **Ước tính dung lượng có thể thu hồi:** 42.62 MB (6225 documents)

## 2. Chi Tiết Các Bộ Sưu Tập
| Collection | Loại | Số Docs | Data Size | Storage Size | Index Size |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `admission_visuals` | core | 46 | 61.64 KB | 4.5 MB | 144.0 KB |
| `artifacts` | core | 78 | 181.72 KB | 80.0 KB | 252.0 KB |
| `assets` | core | 78 | 50.06 KB | 60.0 KB | 232.0 KB |
| `generated_images` | core | 43 | 49.46 KB | 120.0 KB | 156.0 KB |
| `huit_kb` | core | 399 | 6.98 MB | 10.44 MB | 40.0 KB |
| `jobs` | core | 6 | 6.54 KB | 36.0 KB | 288.0 KB |
| `query_cache` | core | 0 | 0 B | 48.0 KB | 132.0 KB |
| `rag_events` | core | 1,613 | 1.31 MB | 508.0 KB | 356.0 KB |
| `admin_sessions_backup_pre_migration_020_20260917_015343` | backup | 2 | 523 B | 36.0 KB | 36.0 KB |
| `admission_visuals_backup_20260914_041909` | backup | 46 | 2.1 MB | 4.29 MB | 36.0 KB |
| `admission_visuals_backup_20260915_084835` | backup | 46 | 2.1 MB | 4.28 MB | 36.0 KB |
| `artifacts_backup_20260915_085501` | backup | 19 | 46.57 KB | 44.0 KB | 36.0 KB |
| `assets_backup_20260914_041906` | backup | 14 | 36.69 KB | 44.0 KB | 36.0 KB |
| `assets_backup_20260914_042219` | backup | 14 | 36.1 KB | 44.0 KB | 36.0 KB |
| `assets_backup_20260914_093006` | backup | 14 | 36.44 KB | 44.0 KB | 36.0 KB |
| `assets_backup_20260915_024118` | backup | 19 | 9.54 KB | 36.0 KB | 36.0 KB |
| `assets_backup_20260915_041659` | backup | 58 | 31.81 KB | 52.0 KB | 36.0 KB |
| `assets_backup_20260915_042012` | backup | 58 | 31.81 KB | 52.0 KB | 36.0 KB |
| `assets_backup_20260915_043753` | backup | 58 | 31.81 KB | 52.0 KB | 36.0 KB |
| `assets_backup_20260915_085500` | backup | 58 | 31.81 KB | 52.0 KB | 36.0 KB |
| `generated_images_backup_20260914_042257` | backup | 42 | 1011.89 KB | 2.02 MB | 36.0 KB |
| `generated_images_backup_20260914_043005` | backup | 42 | 1021.86 KB | 2.03 MB | 36.0 KB |
| `generated_images_backup_20260914_043028` | backup | 42 | 1023.37 KB | 2.04 MB | 36.0 KB |
| `generated_images_backup_20260915_024118` | backup | 43 | 35.83 KB | 60.0 KB | 36.0 KB |
| `generated_images_backup_20260915_041658` | backup | 43 | 35.83 KB | 60.0 KB | 36.0 KB |
| `generated_images_backup_20260915_042011` | backup | 43 | 35.83 KB | 60.0 KB | 36.0 KB |
| `generated_images_backup_20260915_043752` | backup | 43 | 44.34 KB | 60.0 KB | 36.0 KB |
| `generated_images_backup_20260915_083140` | backup | 43 | 44.86 KB | 60.0 KB | 36.0 KB |
| `generated_images_backup_20260915_083208` | backup | 43 | 48.64 KB | 60.0 KB | 36.0 KB |
| `generated_images_backup_20260915_085501` | backup | 43 | 48.64 KB | 60.0 KB | 36.0 KB |
| `huit_kb_backup_20260914_041947` | backup | 399 | 6.99 MB | 11.18 MB | 44.0 KB |
| `huit_kb_backup_20260915_165658` | backup | 399 | 6.98 MB | 11.13 MB | 44.0 KB |
| `jobs_backup_20260914_041902` | backup | 23 | 18.83 KB | 36.0 KB | 36.0 KB |
| `jobs_backup_20260914_042231` | backup | 23 | 17.53 KB | 36.0 KB | 36.0 KB |
| `jobs_backup_20260915_024055` | backup | 23 | 16.48 KB | 36.0 KB | 36.0 KB |
| `jobs_backup_20260915_083207` | backup | 23 | 22.24 KB | 36.0 KB | 36.0 KB |
| `query_cache_backup_20260914_043044` | backup | 7 | 269.33 KB | 536.0 KB | 36.0 KB |
| `query_cache_backup_20260914_093007` | backup | 8 | 55.59 KB | 64.0 KB | 36.0 KB |
| `rag_events_backup_20260914_043048` | backup | 1,452 | 1.14 MB | 508.0 KB | 104.0 KB |
| `rag_events_backup_20260916_023301` | backup | 1,491 | 1.08 MB | 484.0 KB | 108.0 KB |
| `test_categorized_data` | test_or_temp | 27 | 414.04 KB | 348.0 KB | 36.0 KB |
| `test_clean_data` | test_or_temp | 27 | 413.06 KB | 348.0 KB | 36.0 KB |
| `test_kb_stats` | test_or_temp | 4 | 327 B | 36.0 KB | 36.0 KB |
| `test_quality_ranked` | test_or_temp | 27 | 414.54 KB | 348.0 KB | 36.0 KB |
| `test_rag_chunks` | test_or_temp | 1,454 | 769.95 KB | 492.0 KB | 76.0 KB |
| `test_search_results` | test_or_temp | 5 | 12.59 KB | 44.0 KB | 36.0 KB |
| `admin_sessions` | other | 0 | 0 B | 24.0 KB | 128.0 KB |
| `chat_history` | other | 32 | 67.91 KB | 60.0 KB | 36.0 KB |
| `chat_logs` | other | 0 | 0 B | 4.0 KB | 12.0 KB |
| `code_modules` | other | 52 | 44.21 KB | 60.0 KB | 36.0 KB |
| `crawler_hashes` | other | 41 | 11.78 KB | 44.0 KB | 36.0 KB |
| `livestream_state` | other | 1 | 1.4 KB | 36.0 KB | 36.0 KB |
| `operation_audit` | other | 565,108 | 260.84 MB | 29.08 MB | 37.58 MB |
| `raw_data` | other | 41 | 95.12 KB | 96.0 KB | 36.0 KB |
| `schema_migrations` | other | 2 | 253 B | 36.0 KB | 36.0 KB |
| `schema_registry` | other | 6 | 10.79 KB | 44.0 KB | 144.0 KB |

## 3. Khuyến Nghị Chính Sách Lưu Trữ
1. **Bảo tồn Core Collections:** Không xóa bất kỳ bản ghi nào trong 8 collection cốt lõi.
2. **Quản lý Backup Collections:** 13 collection backup tạo ra trong các đợt di chuyển dữ liệu đang bảo toàn trạng thái trước migration. Sau khi phiên bản production vận hành ổn định 30 ngày, có thể chạy lệnh dọn dẹp có kiểm soát.
3. **An toàn Test Collections:** 6 collection thử nghiệm có thể thu hồi khi cần tối ưu hóa hạn mức đĩa MongoDB Atlas M0/Free Tier.