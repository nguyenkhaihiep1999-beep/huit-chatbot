"""LTX domain adapter for durable background job queue operations (v2.0.0)."""
from datetime import datetime
from typing import Any, Dict, List, Optional

from backend.app.data_access.operation_gateway import execute_registered_operation
import backend.app.data_access.registered_operations.job_operations_v2  # ensure registered

CREATE_JOB_CHECKSUM = "bcf0532e0cecb5ae2da288960fa5d37b38d9a45837ee5c1341830aa9b87f7227"
FIND_JOB_BY_ID_CHECKSUM = "ad6508e8a3a8f99604f052db6b731950a6ed45844e0910fb92a261ac7b8f8718"
FIND_JOB_BY_IDEMPOTENCY_CHECKSUM = "f7508b914a54b1b2d33c9221676f7fdd6b48b9a36b97aad78d28af5157a25610"
ATOMIC_CLAIM_JOB_CHECKSUM = "06cbed706ed6ea9d1b40e2f26eba172bb5d28af1bf98a16ae97d992778b40560"
HEARTBEAT_JOB_CHECKSUM = "8389b7af1c10cdd7f33733ddd082c1e80e34681aca58a4bad3ce7129182293dc"
RELEASE_LEASE_CHECKSUM = "de6f862708fc7e14b3de4c84d034fad8da77d3f148a570d0e2bcd7bebe9d352a"
UPDATE_JOB_CHECKSUM = "42b5b6dcbb7bd7463c7798378186f6b47fe15bffd3857a7d157c4f49b71fe6b1"
RECOVER_EXPIRED_LEASES_CHECKSUM = "c2686fe98cf554eac69f8035cae1daed5e7ab2b771fcbe26127122966268ed36"


def create_job_record(
    job_doc: Dict[str, Any],
    *,
    principal_id: str = "system",
    request_id: str = "internal",
) -> str:
    """Tạo mới một job trong collection jobs bền vững qua Registered Operation Gateway."""
    res = execute_registered_operation(
        key="jobs.create",
        version="2.0.0",
        checksum=CREATE_JOB_CHECKSUM,
        parameters={"job": job_doc},
        principal_id=principal_id,
        request_id=request_id,
    )
    if res and res.get("acknowledged"):
        return res.get("job_id", "")
    return ""


def get_job_by_id(
    job_id: str,
    *,
    principal_id: str = "system",
    request_id: str = "internal",
) -> Optional[Dict[str, Any]]:
    """Lấy thông tin job từ collection jobs qua Registered Operation Gateway."""
    res = execute_registered_operation(
        key="jobs.find_by_id",
        version="2.0.0",
        checksum=FIND_JOB_BY_ID_CHECKSUM,
        parameters={"job_id": job_id},
        principal_id=principal_id,
        request_id=request_id,
    )
    if res and res.get("found"):
        return res.get("job")
    return None


def find_job_by_idempotency(
    idempotency_key: str,
    statuses: Optional[List[str]] = None,
    *,
    principal_id: str = "system",
    request_id: str = "internal",
) -> Optional[str]:
    """Kiểm tra idempotency key đã tồn tại trong jobs qua Registered Operation Gateway."""
    params: Dict[str, Any] = {"idempotency_key": idempotency_key}
    if statuses:
        params["statuses"] = statuses
    res = execute_registered_operation(
        key="jobs.find_by_idempotency",
        version="2.0.0",
        checksum=FIND_JOB_BY_IDEMPOTENCY_CHECKSUM,
        parameters=params,
        principal_id=principal_id,
        request_id=request_id,
    )
    if res and res.get("found"):
        return res.get("job_id")
    return None


def atomic_claim_next_job(
    worker_id: str,
    lease_seconds: int = 120,
    specific_job_id: Optional[str] = None,
    *,
    principal_id: str = "system",
    request_id: str = "internal",
) -> Optional[Dict[str, Any]]:
    """Nhận quyền thực thi (lease) job nguyên tử qua Registered Operation Gateway."""
    res = execute_registered_operation(
        key="jobs.atomic_claim",
        version="2.0.0",
        checksum=ATOMIC_CLAIM_JOB_CHECKSUM,
        parameters={
            "worker_id": worker_id,
            "lease_seconds": lease_seconds,
            "specific_job_id": specific_job_id,
        },
        principal_id=principal_id,
        request_id=request_id,
    )
    if res and res.get("claimed"):
        return res.get("job")
    return None


def heartbeat_job_lease(
    job_id: str,
    worker_id: str,
    extend_seconds: int = 120,
    *,
    principal_id: str = "system",
    request_id: str = "internal",
) -> bool:
    """Gia hạn lease job qua Registered Operation Gateway."""
    res = execute_registered_operation(
        key="jobs.heartbeat",
        version="2.0.0",
        checksum=HEARTBEAT_JOB_CHECKSUM,
        parameters={
            "job_id": job_id,
            "worker_id": worker_id,
            "extend_seconds": extend_seconds,
        },
        principal_id=principal_id,
        request_id=request_id,
    )
    return bool(res and res.get("extended"))


def release_job_lease(
    job_id: str,
    worker_id: str,
    *,
    principal_id: str = "system",
    request_id: str = "internal",
) -> bool:
    """Giải phóng lease job khi worker dừng qua Registered Operation Gateway."""
    res = execute_registered_operation(
        key="jobs.release_lease",
        version="2.0.0",
        checksum=RELEASE_LEASE_CHECKSUM,
        parameters={
            "job_id": job_id,
            "worker_id": worker_id,
        },
        principal_id=principal_id,
        request_id=request_id,
    )
    return bool(res and res.get("released"))


def update_job_record(
    job_id: str,
    *,
    status: Optional[str] = None,
    progress: Optional[int] = None,
    retries: Optional[int] = None,
    attempt: Optional[int] = None,
    result_url: Optional[str] = None,
    media_type: Optional[str] = None,
    error: Optional[Dict[str, Any]] = None,
    sanitized_error: Optional[str] = None,
    event_detail: Optional[str] = None,
    available_at: Optional[datetime] = None,
    worker_id: Optional[str] = None,
    principal_id: str = "system",
    request_id: str = "internal",
) -> bool:
    """Cập nhật tiến trình/kết quả job có kiểm soát lease qua Registered Operation Gateway."""
    params: Dict[str, Any] = {
        "job_id": job_id,
        "status": status,
        "progress": progress,
        "retries": retries,
        "attempt": attempt,
        "result_url": result_url,
        "media_type": media_type,
        "error": error,
        "sanitized_error": sanitized_error,
        "event_detail": event_detail,
        "available_at": available_at,
        "worker_id": worker_id,
    }
    res = execute_registered_operation(
        key="jobs.update",
        version="2.0.0",
        checksum=UPDATE_JOB_CHECKSUM,
        parameters=params,
        principal_id=principal_id,
        request_id=request_id,
    )
    return bool(res and res.get("updated"))


def recover_expired_leases(
    max_jobs: int = 10,
    *,
    principal_id: str = "system",
    request_id: str = "internal",
) -> int:
    """Thu hồi các lease job đã quá hạn qua Registered Operation Gateway."""
    res = execute_registered_operation(
        key="jobs.recover_expired_leases",
        version="2.0.0",
        checksum=RECOVER_EXPIRED_LEASES_CHECKSUM,
        parameters={"max_jobs": max_jobs},
        principal_id=principal_id,
        request_id=request_id,
    )
    return res.get("recovered_count", 0) if res else 0
