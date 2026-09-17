"""
Mã lỗi có cấu trúc và xử lý ngoại lệ tập trung cho Artifact Pipeline.
Đảm bảo mọi lỗi đều có thể truy vết được nguồn gốc, request_id, job_id, stage.
"""
from typing import Optional, Dict, Any

# ==============================================================================
# DANH MỤC MÃ LỖI TẬP TRUNG (CENTRAL ERROR CODES)
# ==============================================================================
ERROR_ARTIFACT_INVALID_MANIFEST = "ARTIFACT_INVALID_MANIFEST"
ERROR_ARTIFACT_NOT_FOUND = "ARTIFACT_NOT_FOUND"
ERROR_ARTIFACT_ACCESS_DENIED = "ARTIFACT_ACCESS_DENIED"
ERROR_ARTIFACT_RENDER_FAILED = "ARTIFACT_RENDER_FAILED"
ERROR_ARTIFACT_UPSCALE_FAILED = "ARTIFACT_UPSCALE_FAILED"
ERROR_ASSET_STORAGE_FAILED = "ASSET_STORAGE_FAILED"
ERROR_ASSET_DUPLICATE_DETECTED = "ASSET_DUPLICATE_DETECTED"
ERROR_EXPORT_FAILED = "EXPORT_FAILED"
ERROR_JOB_TIMEOUT = "JOB_TIMEOUT"
ERROR_FILE_TOO_LARGE = "FILE_TOO_LARGE"
ERROR_UNSUPPORTED_FILE_TYPE = "UNSUPPORTED_FILE_TYPE"

# Database & Migration Errors
ERROR_DATABASE_INDEX_CONFLICT = "DATABASE_INDEX_CONFLICT"
ERROR_DATABASE_DUPLICATE_KEY = "DATABASE_DUPLICATE_KEY"
ERROR_DATABASE_VALIDATION_FAILED = "DATABASE_VALIDATION_FAILED"
ERROR_DATABASE_NOT_READY = "DATABASE_NOT_READY"

# Storage Errors
ERROR_STORAGE_TRAVERSAL_ATTEMPT = "STORAGE_TRAVERSAL_ATTEMPT"
ERROR_STORAGE_INTEGRITY_MISMATCH = "STORAGE_INTEGRITY_MISMATCH"
ERROR_STORAGE_BLOB_IN_USE = "STORAGE_BLOB_IN_USE"
ERROR_STORAGE_NOT_CONFIGURED = "STORAGE_NOT_CONFIGURED"
ERROR_DATABASE_QUERY_FAILED = "DATABASE_QUERY_FAILED"


class ArtifactException(Exception):
    """
    Ngoại lệ chuẩn cho toàn bộ quy trình sinh & xuất tài nguyên Artifact.
    """
    def __init__(
        self,
        error_code: str,
        message: str,
        request_id: Optional[str] = None,
        job_id: Optional[str] = None,
        artifact_id: Optional[str] = None,
        stage: str = "general",
        module: str = "artifact_pipeline",
        retryable: bool = False,
        details: Optional[Dict[str, Any]] = None
    ):
        super().__init__(message)
        self.error_code = error_code
        self.message = message
        self.request_id = request_id
        self.job_id = job_id
        self.artifact_id = artifact_id
        self.stage = stage
        self.module = module
        self.retryable = retryable
        self.details = details or {}

    def to_dict(self) -> Dict[str, Any]:
        """Chuyển đổi thành cấu trúc JSON chuẩn."""
        d = {
            "error_code": self.error_code,
            "message": self.message,
            "request_id": self.request_id,
            "job_id": self.job_id,
            "artifact_id": self.artifact_id,
            "stage": self.stage,
            "module": self.module,
            "retryable": self.retryable,
        }
        if self.details and isinstance(self.details, dict):
            # Sanitize details: never leak traceback or internal system paths
            clean_details = {k: v for k, v in self.details.items() if k not in ("traceback", "stack_trace", "exception")}
            if clean_details:
                d["details"] = clean_details
        return d
