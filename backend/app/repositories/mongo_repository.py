import logging
import os
from urllib.parse import quote_plus
from typing import Any, Dict, List, Optional, Tuple

from pymongo import MongoClient
from pymongo.database import Database
from pymongo.collection import Collection
from pymongo.errors import (
    PyMongoError,
    DuplicateKeyError,
    OperationFailure,
    ServerSelectionTimeoutError,
)

from backend.app.config import settings
from backend.app.telemetry.errors import (
    ERROR_DATABASE_INDEX_CONFLICT,
    ERROR_DATABASE_DUPLICATE_KEY,
    ERROR_DATABASE_NOT_READY,
)

logger = logging.getLogger("huit_chatbot.mongo_repository")


class MongoRepository:
    _instance = None
    _client: Optional[MongoClient] = None
    _db: Optional[Database] = None
    _index_status: Dict[str, Any] = {}

    @classmethod
    def _create_single_index(
        cls,
        coll: Collection,
        keys: Any,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Khởi tạo một index riêng biệt kèm theo bắt và phân loại chính xác các mã lỗi MongoDB:
        - Phân biệt: index đã tồn tại, conflict cấu hình, dữ liệu trùng (DuplicateKeyError), thiếu quyền hoặc timeout.
        - Tuyệt đối không nuốt ngoại lệ hay dùng pass thô.
        """
        col_name = coll.name
        index_name = kwargs.get("name") or str(keys)
        result = {
            "collection": col_name,
            "keys": str(keys),
            "status": "pending",
            "error_code": None,
            "message": ""
        }

        try:
            # 1. Kiểm tra xem index đã tồn tại với cùng cấu trúc và options chưa
            existing_indexes = coll.index_information()
            for name, info in existing_indexes.items():
                if info.get("key") == keys or (isinstance(keys, str) and info.get("key") == [(keys, 1)]):
                    options_match = True
                    for opt_k in ("unique", "sparse", "expireAfterSeconds", "partialFilterExpression"):
                        if opt_k in kwargs and info.get(opt_k) != kwargs[opt_k]:
                            options_match = False
                            break
                    if options_match:
                        result["status"] = "already_exists"
                        result["message"] = f"Index {name} đã tồn tại sẵn trên collection {col_name} với cùng cấu hình"
                        logger.debug(f"[MongoDB Index] {result['message']}")
                        return result
                    else:
                        result["status"] = "options_conflict"
                        result["message"] = (
                            f"Index {name} trên {col_name} đã tồn tại nhưng khác options. "
                            f"Hiện tại: {info}, Yêu cầu: {kwargs}. Không tự ý drop lúc runtime!"
                        )
                        logger.warning(f"[MongoDB Index Warning] {result['message']}")
                        return result

            # 2. Tạo index mới
            actual_name = coll.create_index(keys, **kwargs)
            result["status"] = "created"
            result["index_name"] = actual_name
            result["message"] = f"Tạo thành công index {actual_name} trên collection {col_name}"
            logger.info(f"[MongoDB Index] {result['message']}")
            return result

        except DuplicateKeyError as dke:
            result["status"] = "duplicate_key_error"
            result["error_code"] = 11000
            result["message"] = (
                f"LỖI DỮ LIỆU TRÙNG LẬP: Không thể tạo unique index {keys} trên collection '{col_name}' "
                f"vì cơ sở dữ liệu hiện có bản ghi trùng lặp. Cần chạy migration deduplication trước! Chi tiết: {dke}"
            )
            logger.error(f"[MongoDB Index Error {ERROR_DATABASE_DUPLICATE_KEY}] {result['message']}")
            return result

        except OperationFailure as of:
            code = getattr(of, "code", None)
            result["error_code"] = code
            if code in (85, 86):
                result["status"] = "options_conflict"
                result["message"] = (
                    f"XUNG ĐỘT CẤU HÌNH INDEX (Code {code}): Index trên {col_name} với khóa {keys} "
                    f"đã tồn tại nhưng khác thuộc tính (unique/sparse/ttl). Cần migration chuyên biệt để cập nhật!"
                )
                logger.warning(f"[MongoDB Index Warning {ERROR_DATABASE_INDEX_CONFLICT}] {result['message']}")
            elif code == 13:
                result["status"] = "unauthorized"
                result["message"] = (
                    f"LỖI PHÂN QUYỀN (Code 13): Tài khoản MongoDB không có quyền tạo index trên {col_name}. "
                    f"Vui lòng cấp quyền dbAdmin hoặc readWrite."
                )
                logger.error(f"[MongoDB Index Error] {result['message']}")
            else:
                result["status"] = "operation_failed"
                result["message"] = f"Lỗi thao tác MongoDB (Code {code}) khi tạo index trên {col_name}: {of}"
                logger.error(f"[MongoDB Index Error] {result['message']}")
            return result

        except ServerSelectionTimeoutError as sste:
            result["status"] = "timeout"
            result["error_code"] = "TIMEOUT"
            result["message"] = f"MẤT KẾT NỐI: Không thể kết nối tới cụm MongoDB Atlas để tạo index: {sste}"
            logger.critical(f"[MongoDB Index Critical] {result['message']}")
            return result

        except Exception as exc:
            result["status"] = "unknown_error"
            result["error_code"] = "UNKNOWN"
            result["message"] = f"Lỗi không xác định khi tạo index {keys} trên {col_name}: {exc}"
            logger.error(f"[MongoDB Index Error] {result['message']}", exc_info=True)
            return result

    @classmethod
    def init_indexes(cls) -> Dict[str, Any]:
        """
        Khởi tạo tuần tự và kiểm soát toàn bộ các index bắt buộc cho hệ thống.
        Không một ngoại lệ nào bị nuốt âm thầm.
        """
        if cls._db is None:
            return {"status": "error", "message": "Database chưa được kết nối"}

        results = []
        # 1. query_cache
        results.append(cls._create_single_index(cls._db["query_cache"], "cache_key", unique=True, sparse=True))
        results.append(cls._create_single_index(cls._db["query_cache"], "expires_at", expireAfterSeconds=0))
        results.append(cls._create_single_index(cls._db["query_cache"], [("updated_at", -1)]))

        # 2. rag_events & chat_logs
        results.append(cls._create_single_index(cls._db["rag_events"], [("created_at", -1)]))
        results.append(cls._create_single_index(cls._db["rag_events"], [("request_id", 1)], sparse=True))
        results.append(cls._create_single_index(cls._db["rag_events"], [("intent", 1), ("created_at", -1)]))
        results.append(cls._create_single_index(cls._db["chat_logs"], [("created_at", -1)]))

        # 3. assets (Physical Blob)
        results.append(cls._create_single_index(cls._db["assets"], "asset_id", unique=True))
        results.append(cls._create_single_index(cls._db["assets"], "content_hash", unique=True, sparse=True))
        results.append(cls._create_single_index(cls._db["assets"], "checksum", sparse=True))
        results.append(cls._create_single_index(cls._db["assets"], [("created_at", -1)]))
        results.append(cls._create_single_index(cls._db["assets"], [("last_accessed_at", -1)]))

        # 4. artifacts (Logical Ownership)
        results.append(cls._create_single_index(cls._db["artifacts"], "artifact_id", unique=True))
        results.append(cls._create_single_index(cls._db["artifacts"], "blob_id", sparse=True))
        results.append(cls._create_single_index(cls._db["artifacts"], [("owner_id", 1), ("created_at", -1)], sparse=True))
        results.append(cls._create_single_index(cls._db["artifacts"], [("created_at", -1)]))

        # 5. jobs
        results.append(cls._create_single_index(cls._db["jobs"], "job_id", unique=True))
        results.append(cls._create_single_index(cls._db["jobs"], [("owner_id", 1), ("updated_at", -1)], sparse=True))
        results.append(cls._create_single_index(cls._db["jobs"], [("status", 1), ("updated_at", -1)]))
        results.append(cls._create_single_index(cls._db["jobs"], "request_id", sparse=True))
        results.append(cls._create_single_index(cls._db["jobs"], "artifact_id", sparse=True))
        results.append(cls._create_single_index(cls._db["jobs"], "expires_at", expireAfterSeconds=0, sparse=True))

        # 6. generated_images
        results.append(cls._create_single_index(cls._db["generated_images"], "image_id", unique=True))
        results.append(cls._create_single_index(
            cls._db["generated_images"],
            [("content_hash", 1)],
            name="content_hash_lookup_v1",
            sparse=True,
        ))
        results.append(cls._create_single_index(
            cls._db["generated_images"],
            [("owner_id", 1), ("request_fingerprint", 1)],
            name="owner_request_fingerprint_unique_v1",
            unique=True,
            partialFilterExpression={
                "owner_id": {"$type": "string"},
                "request_fingerprint": {"$type": "string"},
            },
        ))
        results.append(cls._create_single_index(cls._db["generated_images"], "blob_id", sparse=True))
        results.append(cls._create_single_index(cls._db["generated_images"], [("created_at", -1)]))

        # 7. admission_visuals
        results.append(cls._create_single_index(cls._db["admission_visuals"], "visual_id", unique=True))
        results.append(cls._create_single_index(cls._db["admission_visuals"], "major_code"))
        results.append(cls._create_single_index(cls._db["admission_visuals"], "category"))

        # 8. operation_audit
        results.append(cls._create_single_index(cls._db["operation_audit"], [("created_at", -1)]))
        results.append(cls._create_single_index(cls._db["operation_audit"], [("operation_key", 1), ("operation_version", 1), ("created_at", -1)]))
        results.append(cls._create_single_index(cls._db["operation_audit"], [("request_id", 1)], sparse=True))
        results.append(cls._create_single_index(cls._db["operation_audit"], [("status", 1), ("created_at", -1)]))
        results.append(cls._create_single_index(cls._db["operation_audit"], [("principal_id", 1), ("created_at", -1)]))

        # Tổng kết trạng thái
        failed_count = sum(1 for r in results if r["status"] in ("duplicate_key_error", "options_conflict", "unauthorized", "timeout", "operation_failed", "unknown_error"))
        cls._index_status = {
            "total_indexes": len(results),
            "success": failed_count == 0,
            "failed_count": failed_count,
            "details": results
        }
        return cls._index_status

    @classmethod
    def get_client(cls) -> MongoClient:
        if cls._client is None:
            uri = settings.MONGODB_URI
            if not uri:
                pwd = settings.MONGODB_PASSWORD
                if not pwd:
                    raise RuntimeError(
                        "MONGODB_URI hoặc MONGODB_PASSWORD chưa được cấu hình. "
                        "Hãy kiểm tra biến môi trường."
                    )
                uri = f"mongodb+srv://{settings.MONGODB_USER}:{quote_plus(pwd)}@{settings.MONGODB_HOST}/?appName=Cluster0"
            cls._client = MongoClient(uri, serverSelectionTimeoutMS=settings.MONGODB_TIMEOUT_MS)
            cls._db = cls._client[settings.MONGODB_DB]
            # Tách riêng việc tạo index khỏi normal connection: chỉ chạy qua migration hoặc CLI explicit

        return cls._client

    @classmethod
    def get_db(cls) -> Database:
        if cls._db is None:
            cls.get_client()
        return cls._db

    @classmethod
    def get_collection(cls, name: str) -> Collection:
        return cls.get_db()[name]

    @classmethod
    def get_kb_collection(cls) -> Collection:
        return cls.get_collection(settings.MONGODB_COLL)

    @classmethod
    def get_cache_collection(cls) -> Collection:
        return cls.get_collection("query_cache")

    @classmethod
    def get_events_collection(cls) -> Collection:
        return cls.get_collection("rag_events")

    @classmethod
    def get_chat_logs_collection(cls) -> Collection:
        return cls.get_collection("chat_logs")

    @classmethod
    def get_artifacts_collection(cls) -> Collection:
        return cls.get_collection("artifacts")

    @classmethod
    def get_operation_audit_collection(cls) -> Collection:
        return cls.get_collection("operation_audit")

    @classmethod
    def check_database_readiness(cls) -> Dict[str, Any]:
        """
        Kiểm tra độ sẵn sàng của Database:
        1. Ping kết nối tới MongoDB Cluster.
        2. Kiểm tra sự tồn tại và thuộc tính chính xác của các index cốt lõi (unique, TTL).
        3. Kiểm tra sự hiện diện của validators trên các collection chính.
        """
        readiness = {
            "ready": False,
            "ping": False,
            "database_name": settings.MONGODB_DB,
            "missing_critical_indexes": [],
            "invalid_index_options": [],
            "missing_validators": [],
            "error": None
        }

        try:
            db = cls.get_db()
            # 1. Ping
            db.command("ping")
            readiness["ping"] = True

            # 2. Kiểm tra index cốt lõi và options
            critical_checks = [
                ("query_cache", "cache_key", {"unique": True}),
                ("query_cache", "expires_at", {"expireAfterSeconds": 0}),
                ("rag_events", "created_at", {}),
                ("assets", "asset_id", {"unique": True}),
                ("assets", "content_hash", {"unique": True}),
                ("jobs", "job_id", {"unique": True}),
                ("generated_images", "image_id", {"unique": True}),
                ("generated_images", "request_fingerprint", {
                    "unique": True,
                    "key": [("owner_id", 1), ("request_fingerprint", 1)],
                }),
            ]

            existing_colls = None
            try:
                colls = db.list_collection_names()
                if isinstance(colls, (list, set, tuple)):
                    existing_colls = set(colls)
            except Exception:
                pass

            missing = []
            invalid_opts = []
            for coll_name, field, expected_opts in critical_checks:
                try:
                    if existing_colls is not None and coll_name not in existing_colls:
                        try:
                            info = db[coll_name].index_information()
                            if not isinstance(info, dict):
                                missing.append(f"{coll_name}:{field}")
                                continue
                        except Exception:
                            missing.append(f"{coll_name}:{field}")
                            continue
                    else:
                        info = db[coll_name].index_information()

                    matched_idx = None
                    for idx_name, idx_spec in info.items():
                        keys = [k[0] for k in idx_spec.get("key", [])]
                        if field in keys:
                            matched_idx = idx_spec
                            break
                    if not matched_idx:
                        missing.append(f"{coll_name}:{field}")
                    else:
                        for opt_k, opt_v in expected_opts.items():
                            if matched_idx.get(opt_k) != opt_v:
                                invalid_opts.append(
                                    f"{coll_name}:{field} (cần {opt_k}={opt_v}, hiện tại: {matched_idx.get(opt_k)})"
                                )
                except Exception:
                    missing.append(f"{coll_name}:{field}")

            readiness["missing_critical_indexes"] = missing
            readiness["invalid_index_options"] = invalid_opts

            # 3. Kiểm tra validators
            missing_vals = []
            for c in ["assets", "jobs", "query_cache", "rag_events", "generated_images"]:
                if c in db.list_collection_names():
                    col_info = db.command({"listCollections": 1, "filter": {"name": c}})
                    batch = col_info.get("cursor", {}).get("firstBatch", [])
                    opts = batch[0].get("options", {}) if batch else {}
                    validator = opts.get("validator", {})
                    if not (validator and "$jsonSchema" in validator):
                        missing_vals.append(c)
                else:
                    missing_vals.append(c)

            readiness["missing_validators"] = missing_vals

            # Chỉ báo ready nếu ping thành công, không thiếu index, không sai options và có validator
            readiness["ready"] = (len(missing) == 0 and len(invalid_opts) == 0 and len(missing_vals) == 0)

        except Exception as exc:
            readiness["ready"] = False
            readiness["error"] = str(exc)
            logger.error(f"[Database Readiness Check Failed] {exc}")

        return readiness

    @classmethod
    def save_admin_session(cls, session_hash: str, session_id: str, expires_at: int) -> bool:
        """Lưu trữ session hash của quản trị viên qua LTX Gateway v2."""
        try:
            from backend.app.data_access.operations.admin_session_operations import save_admin_session_ltx
            from backend.app.config import settings
            from datetime import datetime, timezone
            exp_dt = datetime.fromtimestamp(expires_at, tz=timezone.utc)
            return save_admin_session_ltx(
                session_hash=session_hash,
                session_id=session_id,
                admin_id=settings.ADMIN_USERNAME,
                expires_at=exp_dt,
            )
        except Exception:
            return False

    @classmethod
    def get_admin_session(cls, session_hash: str) -> Optional[Dict[str, Any]]:
        """Tra cứu session của quản trị viên qua LTX Gateway v2."""
        try:
            from backend.app.data_access.operations.admin_session_operations import find_valid_admin_session_ltx
            return find_valid_admin_session_ltx(session_hash)
        except Exception:
            return None

    @classmethod
    def delete_admin_session(cls, session_hash: str) -> bool:
        """Thu hồi / xóa session quản trị viên qua LTX Gateway v2."""
        try:
            from backend.app.data_access.operations.admin_session_operations import revoke_admin_session_ltx
            return revoke_admin_session_ltx(session_hash)
        except Exception:
            return False

