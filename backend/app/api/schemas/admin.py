from typing import Optional, Dict, Any, List
from pydantic import BaseModel, Field


class AdminLoginRequest(BaseModel):
    username: str = Field(..., description="Tên đăng nhập")
    password: str = Field(..., description="Mật khẩu")


class AdminLoginResponse(BaseModel):
    success: bool = True
    csrf_token: str = Field(..., description="CSRF token gắn với session quản trị viên")
    message: str = "Đăng nhập quản trị viên thành công!"


class ClearCacheRequest(BaseModel):
    confirm: bool = Field(default=True)


class AdminJobItem(BaseModel):
    job_id: str
    action: str
    artifact_id: Optional[str] = None
    format: Optional[str] = None
    scale: Optional[int] = None
    status: str
    progress: int = 0
    retries: int = 0
    attempt: int = 0
    max_attempts: int = 3
    lease_owner: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    available_at: Optional[str] = None
    lease_expires_at: Optional[str] = None
    result_url: Optional[str] = None
    download_url: Optional[str] = None
    media_type: Optional[str] = None
    sanitized_error: Optional[str] = None


class AdminJobListResponse(BaseModel):
    jobs: List[AdminJobItem]
    total: int
    page: int
    limit: int
    total_pages: int


class JobEventItem(BaseModel):
    timestamp: Optional[str] = None
    status: str
    progress: int = 0
    detail: str


class AdminJobDetailResponse(BaseModel):
    job: AdminJobItem
    events: List[JobEventItem] = []


class AdminJobActionRequest(BaseModel):
    reason: Optional[str] = None


class AdminJobActionResponse(BaseModel):
    success: bool
    message: str
    job_id: str


class AdminWorkerItem(BaseModel):
    worker_id: str
    status: str = "active"  # active, idle, offline, stale
    last_seen: Optional[str] = None
    active_job_id: Optional[str] = None
    active_jobs_count: int = 0


class AdminWorkersResponse(BaseModel):
    workers: List[AdminWorkerItem]
    total_workers: int
    healthy_count: int


class AdminQueueStatsResponse(BaseModel):
    queued_count: int = 0
    processing_count: int = 0
    stuck_count: int = 0
    failed_count: int = 0
    completed_count: int = 0
    cancelled_count: int = 0
    total_jobs: int = 0


class SanitizedErrorLogItem(BaseModel):
    id: str
    request_id: Optional[str] = None
    timestamp: Optional[str] = None
    source: str  # rag_query, job_worker, system
    error_code: str
    message: str
    intent: Optional[str] = None
    question_hash: Optional[str] = None
    question_length: Optional[int] = None
    elapsed_ms: Optional[float] = None


class AdminErrorLogsResponse(BaseModel):
    logs: List[SanitizedErrorLogItem]
    total: int


class AdminMigrationItem(BaseModel):
    version: str
    name: str
    description: str
    status: str = "applied"  # applied, verified, pending
    is_read_only: bool = True


class AdminMigrationsResponse(BaseModel):
    migrations: List[AdminMigrationItem]
    total: int
    applied_count: int
    can_execute_from_web: bool = False


class AdminBackupItem(BaseModel):
    collection_name: str
    source_collection: str
    created_at: Optional[str] = None
    document_count: int = 0
    status: str = "available"
    is_read_only: bool = True


class AdminBackupsResponse(BaseModel):
    backups: List[AdminBackupItem]
    total: int
    can_restore_from_web: bool = False


class AdminAlertItem(BaseModel):
    id: str
    severity: str  # info, warning, error
    title: str
    message: str
    timestamp: Optional[str] = None


class AdminAlertSummaryResponse(BaseModel):
    overall_status: str  # healthy, warning, critical
    alerts: List[AdminAlertItem]
    stuck_jobs_count: int
    failed_jobs_24h_count: int
    worker_healthy_count: int
    worker_total_count: int
