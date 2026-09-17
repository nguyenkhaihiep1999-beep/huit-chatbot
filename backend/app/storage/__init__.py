"""
backend/app/storage/__init__.py
"""
from backend.app.storage.storage_adapter import (
    StorageAdapter,
    LocalStorageAdapter,
    ObjectStorageAdapter,
    get_storage_adapter,
    validate_safe_storage_key,
)

__all__ = [
    "StorageAdapter",
    "LocalStorageAdapter",
    "ObjectStorageAdapter",
    "get_storage_adapter",
    "validate_safe_storage_key",
]
