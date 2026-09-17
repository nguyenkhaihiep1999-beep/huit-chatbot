"""
storage_adapter.py
Bộ điều hợp lưu trữ bền vững (Durable Storage Adapter) cho HUIT Chatbot:
- Trừu tượng hóa việc lưu trữ file nhị phân (Excel, Word, PDF, hình ảnh).
- Loại trừ sự phụ thuộc vào filesystem tạm thời (ephemeral) trên môi trường serverless (như Vercel).
- Bảo vệ an toàn tuyệt đối chống tấn công Path Traversal.
- Tính toán và xác thực mã băm SHA-256 (Checksum) cho mọi file lưu trữ.
- Hỗ trợ LocalStorageAdapter (cho local development/testing) và ObjectStorageAdapter (cho production S3/Blob).
"""
from abc import ABC, abstractmethod
import hashlib
import os
from pathlib import Path
import re
from typing import Any, Dict, Iterable, Optional
from uuid import uuid4

from backend.app.config import settings
from backend.app.telemetry.errors import (
    ArtifactException,
    ERROR_STORAGE_TRAVERSAL_ATTEMPT,
    ERROR_ASSET_STORAGE_FAILED,
)

SAFE_KEY_PATTERN = re.compile(r"^[a-zA-Z0-9_\-\.]+$")


def validate_safe_storage_key(key: str) -> str:
    """Kiểm tra và ngăn chặn tấn công Path Traversal."""
    if not key or not isinstance(key, str):
        raise ArtifactException(
            error_code=ERROR_STORAGE_TRAVERSAL_ATTEMPT,
            message="Storage key không được để trống hoặc sai kiểu dữ liệu"
        )
    key_clean = key.strip()
    if ".." in key_clean or "/" in key_clean or "\\" in key_clean:
        raise ArtifactException(
            error_code=ERROR_STORAGE_TRAVERSAL_ATTEMPT,
            message=f"Phát hiện ký tự nguy hiểm trong storage key: {key_clean}"
        )
    if not SAFE_KEY_PATTERN.match(key_clean):
        raise ArtifactException(
            error_code=ERROR_STORAGE_TRAVERSAL_ATTEMPT,
            message=f"Storage key chứa ký tự không hợp lệ: {key_clean}"
        )
    return key_clean


class StorageAdapter(ABC):
    """Lớp cơ sở trừu tượng cho tất cả các storage backend."""

    @abstractmethod
    def put(self, key: str, data: bytes, media_type: str = "application/octet-stream") -> Dict[str, Any]:
        """Ghi dữ liệu nhị phân vào storage."""
        pass

    @abstractmethod
    def get(self, key: str) -> Optional[bytes]:
        """Đọc dữ liệu nhị phân từ storage."""
        pass

    @abstractmethod
    def exists(self, key: str) -> bool:
        """Kiểm tra file có tồn tại hay không."""
        pass

    @abstractmethod
    def delete(self, key: str) -> bool:
        """Xóa file khỏi storage."""
        pass

    @abstractmethod
    def get_checksum(self, key: str) -> Optional[str]:
        """Lấy mã băm SHA-256 của file."""
        pass

    @abstractmethod
    def get_size(self, key: str) -> Optional[int]:
        """Return object size without downloading it when the backend supports metadata."""
        pass

    @abstractmethod
    def list_keys(self) -> Iterable[str]:
        """Iterate storage keys using a paginated backend listing."""
        pass

    @abstractmethod
    def get_url(self, key: str) -> str:
        """Lấy URL truy cập file."""
        pass

    @abstractmethod
    def get_signed_url(self, key: str, expires_in: int = 3600) -> str:
        """Lấy Signed URL có chữ ký bảo mật và thời hạn sử dụng."""
        pass

    @abstractmethod
    def check_health(self) -> Dict[str, Any]:
        """Kiểm tra tình trạng hoạt động của bộ lưu trữ."""
        pass


class LocalStorageAdapter(StorageAdapter):
    """
    Storage adapter lưu file cục bộ trên filesystem máy chủ hoặc container volume.
    Thích hợp cho môi trường local development và chạy test tự động.
    """

    def __init__(self, root_dir: Optional[Path] = None):
        self.root_dir = (root_dir or settings.STORAGE_ROOT).resolve()
        self.root_dir.mkdir(parents=True, exist_ok=True)

    def _resolve_safe_path(self, key: str) -> Path:
        safe_key = validate_safe_storage_key(key)
        target = (self.root_dir / safe_key).resolve()
        # Đảm bảo target path nằm hoàn toàn bên trong root_dir
        try:
            target.relative_to(self.root_dir)
        except ValueError:
            raise ArtifactException(
                error_code=ERROR_STORAGE_TRAVERSAL_ATTEMPT,
                message=f"Đường dẫn vượt ngoài thư mục lưu trữ cho phép: {key}"
            )
        return target

    def put(self, key: str, data: bytes, media_type: str = "application/octet-stream") -> Dict[str, Any]:
        target_path = self._resolve_safe_path(key)
        temp_path = target_path.with_name(
            f".{target_path.name}.{os.getpid()}.{uuid4().hex}.tmp"
        )
        try:
            temp_path.write_bytes(data)
            temp_path.replace(target_path)
            checksum = hashlib.sha256(data).hexdigest()
            return {
                "storage_key": key,
                "byte_size": len(data),
                "checksum": checksum,
                "media_type": media_type,
                "backend": "local"
            }
        except Exception as e:
            try:
                temp_path.unlink(missing_ok=True)
            except Exception:
                pass
            raise ArtifactException(
                error_code=ERROR_ASSET_STORAGE_FAILED,
                message=f"Lỗi ghi file vào Local Storage: {str(e)}"
            )

    def get(self, key: str) -> Optional[bytes]:
        target_path = self._resolve_safe_path(key)
        if not target_path.exists() or not target_path.is_file():
            return None
        try:
            return target_path.read_bytes()
        except Exception:
            return None

    def exists(self, key: str) -> bool:
        target_path = self._resolve_safe_path(key)
        return target_path.exists() and target_path.is_file()

    def delete(self, key: str) -> bool:
        target_path = self._resolve_safe_path(key)
        if target_path.exists() and target_path.is_file():
            try:
                target_path.unlink()
                return True
            except Exception:
                return False
        return False

    def get_checksum(self, key: str) -> Optional[str]:
        data = self.get(key)
        if data is not None:
            return hashlib.sha256(data).hexdigest()
        return None

    def get_size(self, key: str) -> Optional[int]:
        target_path = self._resolve_safe_path(key)
        if not target_path.exists() or not target_path.is_file():
            return None
        return target_path.stat().st_size

    def list_keys(self) -> Iterable[str]:
        for path in self.root_dir.iterdir():
            if path.is_file() and not path.name.startswith(".healthcheck_probe"):
                yield path.name

    def get_url(self, key: str) -> str:
        safe_key = validate_safe_storage_key(key)
        return f"/api/artifacts/download/{safe_key}"

    def get_signed_url(self, key: str, expires_in: int = 3600) -> str:
        from backend.app.services.auth_service import create_download_signature
        safe_key = validate_safe_storage_key(key)
        sig, exp = create_download_signature(safe_key, expires_in=expires_in)
        return f"/api/artifacts/download/{safe_key}?sig={sig}&expires={exp}"

    def check_health(self) -> Dict[str, Any]:
        try:
            test_file = self.root_dir / ".healthcheck_probe"
            test_file.write_text("ok", encoding="utf-8")
            test_file.unlink()
            return {"status": "healthy", "type": "local", "root_dir": str(self.root_dir)}
        except Exception as e:
            return {"status": "unhealthy", "type": "local", "error": str(e)}


class ObjectStorageAdapter(StorageAdapter):
    """
    Storage adapter thực sự cho S3 / Cloudflare R2 / Supabase Storage dựa trên boto3.
    Dành cho production bền vững (loại trừ rủi ro mất file khi serverless restart container).
    Fail-fast trên production nếu thiếu credentials!
    """

    def __init__(
        self,
        bucket_name: Optional[str] = None,
        endpoint_url: Optional[str] = None,
        access_key: Optional[str] = None,
        secret_key: Optional[str] = None,
        region_name: Optional[str] = None
    ):
        self.bucket_name = bucket_name or os.getenv("STORAGE_BUCKET", "huit-chatbot-artifacts")
        self.endpoint_url = endpoint_url or os.getenv("STORAGE_ENDPOINT", "")
        self.access_key = access_key or os.getenv("STORAGE_ACCESS_KEY", "")
        self.secret_key = secret_key or os.getenv("STORAGE_SECRET_KEY", "")
        self.region_name = region_name or os.getenv("STORAGE_REGION", "auto")
        self._s3_client = None

        if not self.is_configured:
            if not settings.IS_DEVELOPMENT:
                raise ArtifactException(
                    error_code="STORAGE_NOT_CONFIGURED",
                    message="Object Storage bắt buộc trên production nhưng thiếu STORAGE_ENDPOINT, STORAGE_ACCESS_KEY hoặc STORAGE_SECRET_KEY."
                )
            self._local_fallback = LocalStorageAdapter()
        else:
            self._local_fallback = None
            try:
                import boto3
                from botocore.config import Config
                self._s3_client = boto3.client(
                    "s3",
                    endpoint_url=self.endpoint_url,
                    aws_access_key_id=self.access_key,
                    aws_secret_access_key=self.secret_key,
                    region_name=self.region_name,
                    config=Config(signature_version="s3v4")
                )
            except Exception as e:
                raise ArtifactException(
                    error_code="STORAGE_INIT_FAILED",
                    message=f"Không thể khởi tạo kết nối S3 Object Storage: {str(e)}"
                )

    @property
    def is_configured(self) -> bool:
        return bool(self.access_key and self.secret_key and self.endpoint_url)

    def put(self, key: str, data: bytes, media_type: str = "application/octet-stream") -> Dict[str, Any]:
        safe_key = validate_safe_storage_key(key)
        if not self.is_configured:
            return self._local_fallback.put(safe_key, data, media_type)
        try:
            checksum = hashlib.sha256(data).hexdigest()
            self._s3_client.put_object(
                Bucket=self.bucket_name,
                Key=safe_key,
                Body=data,
                ContentType=media_type,
                Metadata={"sha256": checksum}
            )
            return {
                "storage_key": safe_key,
                "byte_size": len(data),
                "checksum": checksum,
                "media_type": media_type,
                "backend": "s3_object_storage"
            }
        except Exception as e:
            raise ArtifactException(
                error_code=ERROR_ASSET_STORAGE_FAILED,
                message=f"Lỗi ghi dữ liệu vào Remote Object Storage: {str(e)}"
            )

    def get(self, key: str) -> Optional[bytes]:
        safe_key = validate_safe_storage_key(key)
        if not self.is_configured:
            return self._local_fallback.get(safe_key)
        try:
            resp = self._s3_client.get_object(Bucket=self.bucket_name, Key=safe_key)
            return resp["Body"].read()
        except Exception:
            return None

    def exists(self, key: str) -> bool:
        safe_key = validate_safe_storage_key(key)
        if not self.is_configured:
            return self._local_fallback.exists(safe_key)
        try:
            self._s3_client.head_object(Bucket=self.bucket_name, Key=safe_key)
            return True
        except Exception:
            return False

    def delete(self, key: str) -> bool:
        safe_key = validate_safe_storage_key(key)
        if not self.is_configured:
            return self._local_fallback.delete(safe_key)
        try:
            self._s3_client.delete_object(Bucket=self.bucket_name, Key=safe_key)
            return True
        except Exception:
            return False

    def get_checksum(self, key: str) -> Optional[str]:
        data = self.get(key)
        if data is not None:
            return hashlib.sha256(data).hexdigest()
        return None

    def get_size(self, key: str) -> Optional[int]:
        safe_key = validate_safe_storage_key(key)
        if not self.is_configured:
            return self._local_fallback.get_size(safe_key)
        try:
            response = self._s3_client.head_object(Bucket=self.bucket_name, Key=safe_key)
            return int(response.get("ContentLength", 0))
        except Exception:
            return None

    def list_keys(self) -> Iterable[str]:
        if not self.is_configured:
            yield from self._local_fallback.list_keys()
            return
        paginator = self._s3_client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=self.bucket_name):
            for item in page.get("Contents", []):
                key = item.get("Key")
                if key:
                    yield key

    def get_url(self, key: str) -> str:
        safe_key = validate_safe_storage_key(key)
        if not self.is_configured:
            return self._local_fallback.get_url(safe_key)
        return f"{self.endpoint_url.rstrip('/')}/{self.bucket_name}/{safe_key}"

    def get_signed_url(self, key: str, expires_in: int = 3600) -> str:
        safe_key = validate_safe_storage_key(key)
        if not self.is_configured:
            return self._local_fallback.get_signed_url(safe_key, expires_in)
        try:
            url = self._s3_client.generate_presigned_url(
                "get_object",
                Params={"Bucket": self.bucket_name, "Key": safe_key},
                ExpiresIn=min(max(60, expires_in), 86400)
            )
            return url
        except Exception:
            from backend.app.services.auth_service import create_download_signature
            sig, exp = create_download_signature(safe_key, expires_in=expires_in)
            return f"/api/artifacts/download/{safe_key}?sig={sig}&expires={exp}"


    def check_health(self) -> Dict[str, Any]:
        if not self.is_configured:
            return {"status": "unconfigured", "type": "object_storage", "error": "Thiếu thông tin chứng thực S3/R2"}
        try:
            self._s3_client.head_bucket(Bucket=self.bucket_name)
            return {"status": "healthy", "type": "object_storage", "bucket": self.bucket_name}
        except Exception as e:
            return {"status": "unhealthy", "type": "object_storage", "error": str(e)}


# Singleton instance
_default_storage_adapter: Optional[StorageAdapter] = None


def get_storage_adapter() -> StorageAdapter:
    """Lấy thể hiện duy nhất của StorageAdapter."""
    global _default_storage_adapter
    if _default_storage_adapter is None:
        backend = settings.STORAGE_BACKEND
        if backend == "local":
            _default_storage_adapter = LocalStorageAdapter()
        elif backend in ("s3", "r2", "minio"):
            _default_storage_adapter = ObjectStorageAdapter()
        else:
            raise RuntimeError(f"STORAGE_BACKEND không được hỗ trợ: {backend}")
    return _default_storage_adapter


def reset_storage_adapter_for_testing(adapter: Optional[StorageAdapter] = None) -> None:
    """Đặt lại hoặc gán tạm StorageAdapter phục vụ Unit Test cô lập."""
    global _default_storage_adapter
    _default_storage_adapter = adapter
