"""
scripts/migrations/020_create_admin_sessions_collection.py
Migration Phase 8: Khởi tạo và Chuẩn hóa Collection admin_sessions:
- Hỗ trợ cờ --dry-run (mặc định kiểm tra an toàn) và --apply (thực thi thật sự).
- Thiết lập $jsonSchema validator ở mức strict (validationAction: "error", validationLevel: "strict").
- Tạo unique index trên session_hash.
- Tạo TTL index trên expires_at với expireAfterSeconds=0 để MongoDB tự động dọn dẹp các session hết hạn.
- Tạo compound index trên (admin_id, revoked) phục vụ truy vấn và thu hồi hàng loạt.
- Tương thích rollback và ghi nhật ký vào collection schema_migrations.
- Idempotent: chạy nhiều lần an toàn, không làm hỏng dữ liệu hiện có.
"""
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from typing import Any, Dict, List, Optional
import pymongo

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

from backend.app.config import settings
from scripts.migrations.common import (
    create_collection_backup,
    get_base_parser,
    get_migration_db,
    logger,
    save_migration_report,
)

COLLECTION_NAME = "admin_sessions"
MIGRATION_VERSION = "020"
MIGRATION_NAME = "020_create_admin_sessions_collection"

ADMIN_SESSIONS_SCHEMA = {
    "$jsonSchema": {
        "bsonType": "object",
        "required": ["session_hash", "session_id", "admin_id", "created_at", "expires_at", "revoked"],
        "additionalProperties": False,
        "properties": {
            "_id": {"bsonType": "objectId"},
            "session_hash": {
                "bsonType": "string",
                "pattern": "^[a-f0-9]{64}$",
                "description": "SHA-256 hash của token quản trị viên"
            },
            "session_id": {
                "bsonType": "string",
                "description": "Opaque public identifier của session"
            },
            "admin_id": {
                "bsonType": "string",
                "description": "Tên đăng nhập hoặc định danh của quản trị viên"
            },
            "created_at": {
                "bsonType": "date",
                "description": "Thời điểm tạo session (UTC Date)"
            },
            "expires_at": {
                "bsonType": "date",
                "description": "Thời điểm hết hạn session (UTC Date)"
            },
            "revoked": {
                "bsonType": "bool",
                "description": "Trạng thái thu hồi session"
            },
            "ip_address": {
                "bsonType": ["string", "null"],
                "description": "Địa chỉ IP khi đăng nhập"
            },
            "user_agent": {
                "bsonType": ["string", "null"],
                "description": "User Agent khi đăng nhập"
            },
            "last_seen_at": {
                "bsonType": ["date", "null"],
                "description": "Thời điểm hoạt động gần nhất"
            }
        }
    }
}


def post_verify_admin_sessions(db, col) -> Dict[str, Any]:
    """Kiểm tra xác minh nghiêm ngặt sau khi áp dụng migration 020."""
    verification: Dict[str, Any] = {
        "collection_exists": False,
        "validator_strict": False,
        "validator_action_error": False,
        "indexes_verified": {},
        "functional_rejection_verified": False,
    }

    # 1. Collection tồn tại
    existing = db.list_collection_names()
    if COLLECTION_NAME not in existing:
        raise RuntimeError(f"Post-verification thất bại: Collection '{COLLECTION_NAME}' không tồn tại.")
    verification["collection_exists"] = True

    # 2. Validator
    coll_info_list = db.command("listCollections", filter={"name": COLLECTION_NAME}).get("cursor", {}).get("firstBatch", [])
    if coll_info_list:
        options = coll_info_list[0].get("options", {})
        v_level = options.get("validationLevel")
        v_action = options.get("validationAction")
        verification["validator_level"] = v_level
        verification["validator_action"] = v_action
        if v_level == "strict":
            verification["validator_strict"] = True
        if v_action == "error":
            verification["validator_action_error"] = True

    # 3. Indexes
    idx_info = col.index_information()
    # uniq_session_hash
    if "uniq_session_hash" in idx_info:
        idx = idx_info["uniq_session_hash"]
        verification["indexes_verified"]["uniq_session_hash"] = {
            "key": idx.get("key"),
            "unique": idx.get("unique", False),
        }
    # ttl_expires_at
    if "ttl_expires_at" in idx_info:
        idx = idx_info["ttl_expires_at"]
        verification["indexes_verified"]["ttl_expires_at"] = {
            "key": idx.get("key"),
            "expireAfterSeconds": idx.get("expireAfterSeconds"),
        }
    # idx_admin_revoked
    if "idx_admin_revoked" in idx_info:
        idx = idx_info["idx_admin_revoked"]
        verification["indexes_verified"]["idx_admin_revoked"] = {
            "key": idx.get("key"),
        }

    # 4. Functional schema rejection test
    try:
        col.insert_one({"malicious_unauthorized_key": "fail_expected"})
        raise RuntimeError("Post-verification thất bại: Database cho phép chèn document vi phạm schema!")
    except pymongo.errors.PyMongoError:
        verification["functional_rejection_verified"] = True
        logger.info("Post-verification: Database chặn thành công document không hợp lệ theo strict schema.")

    return verification


def run_migration_admin_sessions(
    is_dry_run: bool = True,
    database_name: Optional[str] = None,
    rollback: bool = False,
    report_file: Optional[str] = None,
) -> Dict[str, Any]:
    mode_str = "ROLLBACK" if rollback else ("DRY-RUN (MÔ PHỎNG)" if is_dry_run else "APPLY (THỰC THI THẬT SỰ)")
    logger.info(f"=== BẮT ĐẦU MIGRATION {MIGRATION_VERSION}: CREATE ADMIN SESSIONS COLLECTION [{mode_str}] ===")

    client, db = get_migration_db(database_name)
    logger.info(f"Đã kết nối thành công tới Database: '{db.name}'")

    report: Dict[str, Any] = {
        "migration": MIGRATION_NAME,
        "version": MIGRATION_VERSION,
        "mode": mode_str,
        "database": db.name,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "status": "IN_PROGRESS",
        "actions": [],
        "errors": [],
        "post_verification": None,
    }

    try:
        existing_colls = db.list_collection_names()
        col = db[COLLECTION_NAME]

        if rollback:
            logger.info("Chế độ ROLLBACK: Bắt đầu hoàn tác migration 020...")
            if COLLECTION_NAME in existing_colls:
                # 1. Gỡ bỏ các indexes đã tạo
                idx_info = col.index_information()
                for idx_name in ("uniq_session_hash", "ttl_expires_at", "idx_admin_revoked"):
                    if idx_name in idx_info:
                        if not is_dry_run:
                            col.drop_index(idx_name)
                        report["actions"].append(f"Dropped index {idx_name}")
                        logger.info(f"Đã gỡ bỏ index: {idx_name}")

                # 2. Tắt validator
                if not is_dry_run:
                    db.command({
                        "collMod": COLLECTION_NAME,
                        "validator": {},
                        "validationLevel": "off"
                    })
                report["actions"].append(f"Disabled validator on {COLLECTION_NAME}")
                logger.info(f"Đã tắt validator cho {COLLECTION_NAME}.")

            # 3. Cập nhật schema_migrations
            if not is_dry_run and "schema_migrations" in existing_colls:
                db["schema_migrations"].update_one(
                    {"version": MIGRATION_VERSION},
                    {
                        "$set": {
                            "status": "ROLLED_BACK",
                            "rolled_back_at": datetime.now(timezone.utc),
                        }
                    },
                    upsert=True
                )
                report["actions"].append("Updated schema_migrations to ROLLED_BACK")

            report["status"] = "SUCCESS"
            logger.info("=== HOÀN TẤT ROLLBACK MIGRATION 020 THÀNH CÔNG ===")
            return report

        # 1. Kiểm tra / Tạo collection
        if COLLECTION_NAME not in existing_colls:
            logger.info(f"Collection '{COLLECTION_NAME}' chưa tồn tại. Đang lên kế hoạch tạo mới...")
            report["actions"].append(f"Create collection {COLLECTION_NAME}")
            if not is_dry_run:
                db.create_collection(
                    COLLECTION_NAME,
                    validator=ADMIN_SESSIONS_SCHEMA,
                    validationLevel="strict",
                    validationAction="error"
                )
                logger.info(f"Đã tạo mới collection '{COLLECTION_NAME}' kèm strict validator thành công.")
        else:
            logger.info(f"Collection '{COLLECTION_NAME}' đã tồn tại. Đang áp dụng strict validator...")
            report["actions"].append(f"Apply strict validator to {COLLECTION_NAME}")
            if not is_dry_run:
                # Sao lưu nếu đã có dữ liệu
                doc_count = db[COLLECTION_NAME].count_documents({})
                if doc_count > 0:
                    backup_name = create_collection_backup(db, COLLECTION_NAME, f"pre_migration_{MIGRATION_VERSION}")
                    report["actions"].append(f"Created backup {backup_name} ({doc_count} docs)")

                db.command({
                    "collMod": COLLECTION_NAME,
                    "validator": ADMIN_SESSIONS_SCHEMA,
                    "validationLevel": "strict",
                    "validationAction": "error"
                })
                logger.info(f"Đã cập nhật strict validator cho '{COLLECTION_NAME}'.")

        # 2. Tạo Indexes
        logger.info(f"Đang kiểm tra và tạo indexes cho '{COLLECTION_NAME}'...")
        indexes_to_create = [
            pymongo.IndexModel([("session_hash", pymongo.ASCENDING)], unique=True, name="uniq_session_hash"),
            pymongo.IndexModel([("expires_at", pymongo.ASCENDING)], expireAfterSeconds=0, name="ttl_expires_at"),
            pymongo.IndexModel([("admin_id", pymongo.ASCENDING), ("revoked", pymongo.ASCENDING)], name="idx_admin_revoked"),
        ]

        if not is_dry_run:
            result = col.create_indexes(indexes_to_create)
            logger.info(f"Đã tạo các index: {result}")
            report["actions"].append(f"Created indexes: {result}")
        else:
            logger.info("DRY-RUN: Sẽ tạo 3 indexes (uniq_session_hash, ttl_expires_at, idx_admin_revoked).")
            report["actions"].append("Planned 3 indexes creation")

        # 3. Ghi log migration vào schema_migrations
        if not is_dry_run:
            if "schema_migrations" in existing_colls or "schema_migrations" in db.list_collection_names():
                db["schema_migrations"].update_one(
                    {"version": MIGRATION_VERSION},
                    {
                        "$set": {
                            "version": MIGRATION_VERSION,
                            "name": MIGRATION_NAME,
                            "applied_at": datetime.now(timezone.utc),
                            "status": "SUCCESS"
                        }
                    },
                    upsert=True
                )
                logger.info("Đã cập nhật bản ghi thành công trong schema_migrations.")

            # 4. Post-verification sau khi apply
            logger.info("Bắt đầu Post-verification...")
            verification = post_verify_admin_sessions(db, col)
            report["post_verification"] = verification
            logger.info("Post-verification hoàn tất: %s", verification)

        report["status"] = "SUCCESS"
        logger.info(f"=== HOÀN TẤT MIGRATION {MIGRATION_VERSION} THÀNH CÔNG ===")
        return report

    except Exception as exc:
        report["status"] = "FAILED"
        report["errors"].append(str(exc))
        logger.error(f"Lỗi khi thực thi migration {MIGRATION_VERSION}: {exc}")
        raise
    finally:
        report["finished_at"] = datetime.now(timezone.utc).isoformat()
        target_report_file = report_file or str(Path("audit_outputs") / f"evidence_{MIGRATION_VERSION}_{COLLECTION_NAME}.json")
        save_migration_report(report, target_report_file)


if __name__ == "__main__":
    parser = get_base_parser("Migration 020: Create and Harden admin_sessions collection")
    parser.add_argument("--rollback", action="store_true", help="Chạy rollback bỏ validator và gỡ indexes")
    parser.add_argument("--confirm", action="store_true", help="Xác nhận thực thi thay đổi vào database thật")
    args = parser.parse_args()

    if args.apply and not args.confirm:
        # Kiểm tra chế độ tương tác
        if sys.stdin.isatty():
            confirm_input = input("BẠN CÓ CHẮC CHẮN MUỐN THỰC THI MIGRATION 020 TRÊN DATABASE THẬT? (yes/no): ").strip().lower()
            if confirm_input != "yes":
                print("Hủy thao tác migration theo yêu cầu của người dùng.")
                sys.exit(1)
        else:
            parser.error("--apply trên môi trường tự động/non-interactive bắt buộc phải có thêm cờ --confirm để xác nhận.")

    run_migration_admin_sessions(
        is_dry_run=args.dry_run,
        database_name=args.database,
        rollback=args.rollback,
        report_file=args.report_file,
    )
