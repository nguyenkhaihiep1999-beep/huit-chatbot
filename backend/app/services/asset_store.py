"""
Asset Store & Deduplication Engine cho HUIT Chatbot:
- Quản lý lưu trữ file an toàn thông qua StorageAdapter bền vững (Local hoặc S3/R2).
- Tách bạch tuyệt đối giữa Physical Blob (`assets`) và Logical Ownership (`artifacts`).
- Canonical Hash SHA-256 (chuẩn hóa prompt, content, template, style, renderer version).
- Deduplication: Tự động tái sử dụng physical asset nếu đã tồn tại, tạo bản ghi artifact riêng biệt cho từng người dùng.
- Concurrency Lock: Khóa per-hash chống race condition khi nhiều request giống nhau đến đồng thời.
- Hỗ trợ lưu trữ 2 cấp: RAM Cache + Registered Operation Gateway cho collections `assets` & `artifacts`.
"""
import asyncio
import copy
import hashlib
import json
import logging
import os
import re
import secrets
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from backend.app.config import settings
from backend.app.data_access.operations import asset_operations
from backend.app.storage.storage_adapter import get_storage_adapter, validate_safe_storage_key
from backend.app.models.mongo_models import MongoAssetRecord, MongoArtifactRecord
from backend.app.telemetry.errors import (
    ArtifactException,
    ERROR_ARTIFACT_ACCESS_DENIED,
    ERROR_ARTIFACT_NOT_FOUND,
    ERROR_ASSET_STORAGE_FAILED,
    ERROR_DATABASE_QUERY_FAILED,
    ERROR_FILE_TOO_LARGE,
    ERROR_UNSUPPORTED_FILE_TYPE,
)

logger = logging.getLogger("huit_chatbot.asset_store")

RENDERER_VERSION = "huit-renderer-v2.0"
MAX_FILE_SIZE_BYTES = 50 * 1024 * 1024  # 50MB max file size

SAFE_MIME_MAP = {
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "pdf": "application/pdf",
    "svg": "image/svg+xml",
    "png": "image/png",
    "webp": "image/webp",
    "json": "application/json",
}

# Thư mục lưu file an toàn
STORAGE_ROOT = settings.DATA_DIR / "artifacts_store"
STORAGE_ROOT.mkdir(parents=True, exist_ok=True)

# Bộ nhớ đệm RAM cho Assets & Artifacts
_in_memory_assets: Dict[str, Dict[str, Any]] = {}
_in_memory_artifacts: Dict[str, Dict[str, Any]] = {}
_hash_to_asset_id: Dict[str, str] = {}
_concurrency_locks: Dict[str, asyncio.Lock] = {}
_locks_meta_lock = asyncio.Lock()


def normalize_string_for_hash(text: str) -> str:
    """Chuẩn hóa chuỗi văn bản: chữ thường, bỏ dấu tiếng Việt, loại bỏ khoảng trắng thừa."""
    text = str(text or "").lower().strip()
    text = unicodedata.normalize("NFD", text)
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
    text = text.replace("đ", "d")
    text = re.sub(r"[^\w\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def compute_canonical_hash(
    prompt: str = "",
    template_id: str = "",
    content: Optional[Dict[str, Any]] = None,
    style: Optional[Dict[str, Any]] = None,
    renderer_version: str = RENDERER_VERSION
) -> str:
    """
    Tính mã băm chuẩn hóa (Canonical Hash) từ các tham số sinh tài nguyên.
    Đảm bảo tính xác định (deterministic) dù thứ tự key trong JSON có khác nhau.
    """
    p_norm = normalize_string_for_hash(prompt)
    t_norm = (template_id or "").lower().strip()

    def sort_obj(obj: Any) -> Any:
        if isinstance(obj, dict):
            return {k: sort_obj(v) for k, v in sorted(obj.items()) if v not in (None, "", [], {})}
        elif isinstance(obj, list):
            return [sort_obj(x) for x in obj]
        elif isinstance(obj, str):
            return obj.strip()
        return obj

    cleaned_content = sort_obj(content or {})
    cleaned_style = sort_obj(style or {})

    canonical_payload = {
        "p": p_norm,
        "t": t_norm,
        "c": cleaned_content,
        "s": cleaned_style,
        "v": renderer_version
    }

    serialized = json.dumps(canonical_payload, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def compute_derivative_hash(source_asset_id: str, scale: int, file_ext: str, quality: str = "standard") -> str:
    """Tính composite canonical hash cho các bản phái sinh / upscale / export để chống trùng tuyệt đối."""
    ext = file_ext.lower().strip().replace(".", "")
    payload = f"derivative:{source_asset_id.strip()}:scale_{scale}:{quality}:{ext}:{RENDERER_VERSION}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


async def get_hash_lock(content_hash: str) -> asyncio.Lock:
    """Lấy hoặc tạo Lock riêng biệt cho từng mã hash (chống race condition đồng thời)."""
    async with _locks_meta_lock:
        if content_hash not in _concurrency_locks:
            _concurrency_locks[content_hash] = asyncio.Lock()
        return _concurrency_locks[content_hash]


class AssetStore:
    """
    Quản lý tệp vật lý (Physical Asset / Blob) trong collection `assets`.
    Không bao giờ chứa manifest nghiệp vụ hoặc owner_id người dùng.
    """

    @staticmethod
    def find_by_hash(content_hash: str) -> Optional[Dict[str, Any]]:
        """Tìm kiếm physical asset theo content_hash (RAM -> Gateway)."""
        if not content_hash:
            return None

        # 1. Kiểm tra RAM Cache
        asset_id = _hash_to_asset_id.get(content_hash)
        if asset_id and asset_id in _in_memory_assets:
            rec = _in_memory_assets[asset_id]
            rec["last_accessed_at"] = datetime.now(timezone.utc)
            rec["reference_count"] = rec.get("reference_count", 1) + 1
            return copy.deepcopy(rec)

        # 2. Kiểm tra Registered Operation Gateway
        try:
            doc = asset_operations.find_asset_by_content_hash(content_hash, touch=True)
            if doc:
                _in_memory_assets[doc["asset_id"]] = doc
                _hash_to_asset_id[content_hash] = doc["asset_id"]
                return copy.deepcopy(doc)
        except Exception as e:
            logger.error(f"Lỗi truy vấn asset theo content_hash: {e}")
            raise ArtifactException(
                error_code=ERROR_DATABASE_QUERY_FAILED,
                message=f"Lỗi truy vấn cơ sở dữ liệu: {str(e)}"
            )
        return None

    @staticmethod
    def find_derivative(source_asset_id: str, scale: int, file_ext: str, quality: str = "standard") -> Optional[Dict[str, Any]]:
        """Tìm derivative (ảnh upscale, bản chuyển đổi) đã tồn tại của một source asset."""
        d_hash = compute_derivative_hash(source_asset_id, scale, file_ext, quality)
        existing = AssetStore.find_by_hash(d_hash)
        if existing:
            return existing

        ext = file_ext.lower().strip().replace(".", "")
        for item in _in_memory_assets.values():
            if item.get("source_asset_id") == source_asset_id and item.get("scale") == scale and item.get("file_ext") == ext:
                return copy.deepcopy(item)

        try:
            doc = asset_operations.find_derivative_asset(source_asset_id, scale, ext)
            if doc:
                _in_memory_assets[doc["asset_id"]] = doc
                return copy.deepcopy(doc)
        except Exception as e:
            logger.error(f"Lỗi tìm derivative: {e}")
        return None

    @staticmethod
    def touch_asset(asset_id: str) -> None:
        """Cập nhật thời gian truy cập gần nhất và tăng reference count cho physical asset."""
        if not asset_id:
            return
        now_dt = datetime.now(timezone.utc)
        if asset_id in _in_memory_assets:
            _in_memory_assets[asset_id]["last_accessed_at"] = now_dt
            _in_memory_assets[asset_id]["reference_count"] = _in_memory_assets[asset_id].get("reference_count", 1) + 1

        try:
            asset_operations.touch_asset(asset_id)
        except Exception:
            pass

    @staticmethod
    def get_by_id(asset_id: str) -> Optional[Dict[str, Any]]:
        """Lấy physical asset theo asset_id (hoặc phân giải qua logical artifact nếu cần)."""
        if not asset_id:
            return None

        # Kiểm tra RAM Cache asset
        if asset_id in _in_memory_assets:
            return copy.deepcopy(_in_memory_assets[asset_id])

        # Kiểm tra Gateway assets
        try:
            doc = asset_operations.find_asset_by_id(asset_id)
            if doc:
                _in_memory_assets[asset_id] = doc
                if doc.get("content_hash"):
                    _hash_to_asset_id[doc["content_hash"]] = asset_id
                return copy.deepcopy(doc)
        except Exception as e:
            logger.error(f"Lỗi lấy asset theo ID: {e}")
            raise ArtifactException(
                error_code=ERROR_DATABASE_QUERY_FAILED,
                message=f"Lỗi truy vấn cơ sở dữ liệu: {str(e)}",
                artifact_id=asset_id
            )

        # Fallback phân giải: nếu caller truyền vào artifact_id thay vì asset_id
        art = ArtifactStore.get_by_id(asset_id)
        if art and art.get("blob_id") and art["blob_id"] != asset_id:
            return AssetStore.get_by_id(art["blob_id"])

        return None

    @staticmethod
    def save_asset(
        asset_id: str,
        media_type: str,
        content_hash: str,
        manifest: Optional[Dict[str, Any]] = None,
        raw_bytes: Optional[bytes] = None,
        file_ext: str = "bin",
        preview_key: Optional[str] = None,
        width: Optional[int] = None,
        height: Optional[int] = None,
        duration: Optional[float] = None,
        renderer_version: str = RENDERER_VERSION,
        source_asset_id: Optional[str] = None,
        owner_id: Optional[str] = None,
        scale: Optional[int] = None,
        storage_key: Optional[str] = None,
        file_size: Optional[int] = None,
        checksum: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Lưu tệp vật lý vào StorageAdapter và metadata thuần vào collection `assets`.
        Nếu caller truyền manifest và owner_id (legacy call), tự động tách và lưu sang ArtifactStore!
        """
        ext = file_ext.lower().replace(".", "")
        expected_mime = SAFE_MIME_MAP.get(ext, "application/octet-stream")
        if media_type != expected_mime and expected_mime != "application/octet-stream":
            media_type = expected_mime

        actual_storage_key = storage_key or ""
        actual_file_size = file_size or 0
        actual_file_checksum = checksum or ""

        # Ghi dữ liệu nhị phân qua StorageAdapter
        if raw_bytes is not None:
            actual_file_size = len(raw_bytes)
            if actual_file_size > MAX_FILE_SIZE_BYTES:
                raise ArtifactException(
                    error_code=ERROR_FILE_TOO_LARGE,
                    message=f"Dung lượng file {actual_file_size} bytes vượt quá giới hạn {MAX_FILE_SIZE_BYTES} bytes",
                    artifact_id=asset_id
                )

            actual_file_checksum = hashlib.sha256(raw_bytes).hexdigest()

            # Chống trùng vật lý qua checksum
            existing_storage_key = None
            for item in _in_memory_assets.values():
                if item.get("checksum") == actual_file_checksum and item.get("storage_key"):
                    if get_storage_adapter().exists(item["storage_key"]):
                        existing_storage_key = item["storage_key"]
                        break

            if existing_storage_key:
                actual_storage_key = existing_storage_key
            else:
                safe_filename = f"asset_{asset_id}.{ext}"
                try:
                    res = get_storage_adapter().put(safe_filename, raw_bytes, media_type=media_type)
                    actual_storage_key = res.get("storage_key", safe_filename)
                except Exception as e:
                    raise ArtifactException(
                        error_code=ERROR_ASSET_STORAGE_FAILED,
                        message=f"Lỗi ghi file vào StorageAdapter: {str(e)}",
                        artifact_id=asset_id
                    )
        elif not actual_storage_key:
            actual_storage_key = f"asset_{asset_id}.{ext}"
            actual_file_checksum = actual_file_checksum or content_hash

        storage_key = actual_storage_key
        file_size = actual_file_size
        file_checksum = actual_file_checksum

        now_dt = datetime.now(timezone.utc)

        # Validate qua Pydantic MongoAssetRecord (Physical blob only)
        asset_record = MongoAssetRecord(
            schema_version=1,
            asset_id=asset_id,
            content_hash=content_hash,
            checksum=file_checksum,
            storage_key=storage_key,
            media_type=media_type,
            file_ext=ext,
            file_size=file_size,
            preview_key=preview_key or "",
            width=width,
            height=height,
            duration=duration,
            scale=scale,
            reference_count=1,
            renderer_version=renderer_version,
            source_asset_id=source_asset_id,
            created_at=now_dt,
            last_accessed_at=now_dt
        )

        doc = asset_record.model_dump()

        # Lưu RAM Cache
        _in_memory_assets[asset_id] = copy.deepcopy(doc)
        if content_hash:
            _hash_to_asset_id[content_hash] = asset_id

        # Lưu MongoDB qua Registered Operation Gateway
        try:
            asset_operations.upsert_asset_metadata(doc)
        except Exception as e:
            logger.error(f"Lỗi lưu asset vào MongoDB: {e}")
            raise ArtifactException(
                error_code=ERROR_DATABASE_QUERY_FAILED,
                message=f"Lỗi ghi dữ liệu asset vào cơ sở dữ liệu: {str(e)}",
                artifact_id=asset_id
            )

        # Nếu có manifest và owner_id (caller legacy), lưu độc lập sang ArtifactStore
        if manifest:
            ArtifactStore.save_artifact(
                artifact_id=asset_id,
                manifest=manifest,
                owner_id=owner_id,
                blob_id=asset_id,
                access_scope="public" if not owner_id else "private",
                content_hash=content_hash,
                source_artifact_id=source_asset_id
            )
            doc["manifest"] = manifest
            doc["owner_id"] = owner_id

        return doc

    @staticmethod
    def delete_asset_record(asset_id: str) -> bool:
        """Bồi hoàn metadata của một physical blob chưa được logical record nào tham chiếu."""
        cached = _in_memory_assets.pop(asset_id, None)
        if cached and cached.get("content_hash"):
            if _hash_to_asset_id.get(cached["content_hash"]) == asset_id:
                _hash_to_asset_id.pop(cached["content_hash"], None)
        try:
            res = asset_operations.delete_asset_record(asset_id)
            return res or cached is not None
        except Exception as exc:
            logger.error("Không thể bồi hoàn metadata asset %s: %s", asset_id, type(exc).__name__)
            return False

    @staticmethod
    def get_asset_file_bytes(asset_id: str) -> Optional[bytes]:
        """Đọc dữ liệu nhị phân của file asset đã lưu thông qua StorageAdapter."""
        asset = AssetStore.get_by_id(asset_id)
        if not asset or not asset.get("storage_key"):
            return None
        storage = get_storage_adapter()
        return storage.get(asset["storage_key"])

    @staticmethod
    def get_asset_file_path(asset_id: str) -> Optional[Path]:
        """Lấy đường dẫn tệp trên đĩa cục bộ nếu có (hỗ trợ tương thích ngược)."""
        asset = AssetStore.get_by_id(asset_id)
        if not asset or not asset.get("storage_key"):
            return None
        storage = get_storage_adapter()
        if hasattr(storage, "_resolve_safe_path"):
            try:
                p = storage._resolve_safe_path(asset["storage_key"])
                return p if p.exists() else None
            except Exception:
                return None
        return None

    @staticmethod
    def check_ownership(asset_id: str, requester_id: Optional[str] = None, is_admin: bool = False, principal: Any = None) -> bool:
        """Kiểm tra quyền sở hữu đối với tài nguyên (ủy quyền cho ArtifactStore)."""
        return ArtifactStore.check_ownership(asset_id, requester_id=requester_id, is_admin=is_admin, principal=principal)

    @staticmethod
    def clear_memory_cache_for_testing():
        """Dọn dẹp bộ nhớ đệm RAM phục vụ viết Unit Test."""
        _in_memory_assets.clear()
        _in_memory_artifacts.clear()
        _hash_to_asset_id.clear()
        _concurrency_locks.clear()


class ArtifactStore:
    """
    Quản lý bản ghi quyền sở hữu (Logical Artifact Record) trong collection `artifacts`.
    Tách rời hoàn toàn với file vật lý.
    """

    @staticmethod
    def get_by_id(artifact_id: str) -> Optional[Dict[str, Any]]:
        """Lấy logical artifact theo ID (RAM -> Gateway)."""
        if not artifact_id:
            return None

        if artifact_id in _in_memory_artifacts:
            return copy.deepcopy(_in_memory_artifacts[artifact_id])

        try:
            doc = asset_operations.find_artifact_by_id(artifact_id)
            if doc:
                _in_memory_artifacts[artifact_id] = doc
                return copy.deepcopy(doc)
        except Exception as e:
            logger.error(f"Lỗi lấy artifact theo ID: {e}")
            raise ArtifactException(
                error_code=ERROR_DATABASE_QUERY_FAILED,
                message=f"Lỗi truy vấn cơ sở dữ liệu: {str(e)}",
                artifact_id=artifact_id
            )
        return None

    @staticmethod
    def save_artifact(
        artifact_id: str,
        manifest: Dict[str, Any],
        owner_id: Optional[str] = None,
        blob_id: Optional[str] = None,
        access_scope: str = "public",
        content_hash: Optional[str] = None,
        source_artifact_id: Optional[str] = None,
        derivative_spec: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Lưu bản ghi logical ownership và manifest vào collection `artifacts` qua Gateway."""
        now_dt = datetime.now(timezone.utc)
        clean_owner = owner_id if (owner_id and owner_id != "anonymous") else None
        scope = "private" if clean_owner else (access_scope or "public")

        art_record = MongoArtifactRecord(
            schema_version=1,
            artifact_id=artifact_id,
            owner_id=clean_owner,
            access_scope=scope,
            blob_id=blob_id,
            content_hash=content_hash,
            manifest=manifest,
            source_artifact_id=source_artifact_id,
            derivative_spec=derivative_spec,
            created_at=now_dt,
            updated_at=now_dt
        )

        doc = art_record.model_dump()
        _in_memory_artifacts[artifact_id] = copy.deepcopy(doc)

        try:
            asset_operations.upsert_artifact_ownership(doc)
        except Exception as e:
            logger.error(f"Lỗi lưu artifact vào MongoDB: {e}")
            raise ArtifactException(
                error_code=ERROR_DATABASE_QUERY_FAILED,
                message=f"Lỗi ghi dữ liệu artifact vào cơ sở dữ liệu: {str(e)}",
                artifact_id=artifact_id
            )

        return doc

    @staticmethod
    def find_by_owner_and_hash(owner_id: Optional[str], content_hash: str) -> Optional[Dict[str, Any]]:
        """Tìm logical artifact theo owner_id và content_hash (chống trùng lặp cho cùng một user mà không rò rỉ user khác)."""
        if not content_hash:
            return None
        clean_owner = owner_id if (owner_id and owner_id != "anonymous") else None
        # 1. Kiểm tra RAM cache
        for art in _in_memory_artifacts.values():
            if art.get("content_hash") == content_hash and art.get("owner_id") == clean_owner:
                return copy.deepcopy(art)
        # 2. Kiểm tra Gateway
        try:
            doc = asset_operations.find_artifact_by_owner_and_hash(content_hash, clean_owner)
            if doc:
                _in_memory_artifacts[doc["artifact_id"]] = doc
                return copy.deepcopy(doc)
        except Exception as e:
            logger.error(f"Lỗi tìm artifact theo owner và hash: {e}")
        return None

    @staticmethod
    def check_ownership(
        artifact_id: str,
        requester_id: Optional[str] = None,
        is_admin: bool = False,
        principal: Any = None
    ) -> bool:
        """
        Kiểm tra quyền sở hữu artifact:
        - Admin luôn được truy cập.
        - Public artifact mọi người đều truy cập được.
        - Private artifact: Bắt buộc đã xác thực và requester khớp owner_id.
        - Tuyệt đối không dùng chuỗi thô 'admin' từ requester_id để bypass!
        """
        art = ArtifactStore.get_by_id(artifact_id)
        if not art:
            raise ArtifactException(
                error_code=ERROR_ARTIFACT_NOT_FOUND,
                message=f"Không tìm thấy tài nguyên {artifact_id}",
                artifact_id=artifact_id
            )

        if principal:
            return principal.can_access(art.get("owner_id"), art.get("access_scope", "public"))

        owner = art.get("owner_id")
        scope = art.get("access_scope", "public")

        if not owner or scope == "public":
            return True
        if is_admin or requester_id == "admin":
            return True
        if requester_id and requester_id != "anonymous" and requester_id == owner:
            return True
        return False
