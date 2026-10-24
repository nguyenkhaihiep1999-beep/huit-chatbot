/**
 * admin.types.ts
 * Kiểu dữ liệu cho module Quản trị viên (Admin Portal):
 * - Thống kê sức khỏe hệ thống và RAG metrics.
 * - Danh sách công việc nền bền vững (Jobs queue) và event timeline.
 * - Tiến trình Worker heartbeats và queue depth.
 * - Nhật ký lỗi đã khử khuẩn (Sanitized error logs).
 * - Trạng thái migrations và sao lưu database (CHỈ ĐỌC).
 * - Cảnh báo hệ thống (Alerts summary).
 */

export interface SystemComponentHealth {
  status: 'healthy' | 'unhealthy' | 'warning' | 'unknown';
  latency_ms?: number;
  database?: string;
  queued_jobs?: number;
  stuck_jobs?: number;
  documents_count?: number;
  kb_version?: string;
  ping_ms?: number;
  provider?: string;
  error?: string;
}

export interface SystemHealthData {
  status: 'ready' | 'degraded' | 'healthy';
  service: string;
  version: string;
  environment: string;
  timestamp: string;
  components: {
    mongodb?: SystemComponentHealth;
    job_queue?: SystemComponentHealth;
    knowledge_base?: SystemComponentHealth;
    redis?: SystemComponentHealth;
    storage?: SystemComponentHealth;
    [key: string]: SystemComponentHealth | undefined;
  };
}

export interface SanitizedRecentEvent {
  request_id?: string;
  intent?: string;
  cached?: boolean;
  latency_ms?: number;
  model?: string;
  created_at?: string;
  status?: string;
}

export interface AdminMetricsData {
  total_events: number;
  total_cached_queries: number;
  total_kb_documents: number;
  recent_events: SanitizedRecentEvent[];
}

export interface ClearCacheResult {
  success: boolean;
  message: string;
  details?: Record<string, unknown>;
}

export interface AdminJobItem {
  job_id: string;
  action: string;
  artifact_id?: string;
  format?: string;
  scale?: number;
  status: 'queued' | 'processing' | 'completed' | 'failed' | 'cancelled' | string;
  progress: number;
  retries: number;
  attempt: number;
  max_attempts: number;
  lease_owner?: string;
  created_at?: string;
  updated_at?: string;
  available_at?: string;
  lease_expires_at?: string;
  result_url?: string;
  download_url?: string;
  media_type?: string;
  sanitized_error?: string;
}

export interface AdminJobListResponse {
  jobs: AdminJobItem[];
  total: number;
  page: number;
  limit: number;
  total_pages: number;
}

export interface JobEventItem {
  timestamp?: string;
  status: string;
  progress: number;
  detail: string;
}

export interface AdminJobDetailResponse {
  job: AdminJobItem;
  events: JobEventItem[];
}

export interface AdminWorkerItem {
  worker_id: string;
  status: 'active' | 'idle' | 'offline' | 'stale';
  last_seen?: string;
  active_job_id?: string;
  active_jobs_count: number;
}

export interface AdminWorkersResponse {
  workers: AdminWorkerItem[];
  total_workers: number;
  healthy_count: number;
}

export interface AdminQueueStatsResponse {
  queued_count: number;
  processing_count: number;
  stuck_count: number;
  failed_count: number;
  completed_count: number;
  cancelled_count: number;
  total_jobs: number;
}

export interface SanitizedErrorLogItem {
  id: string;
  request_id?: string;
  timestamp?: string;
  source: string;
  error_code: string;
  message: string;
  intent?: string;
  question_hash?: string;
  question_length?: number;
  elapsed_ms?: number;
}

export interface AdminErrorLogsResponse {
  logs: SanitizedErrorLogItem[];
  total: number;
}

export interface AdminMigrationItem {
  version: string;
  name: string;
  description: string;
  status: 'applied' | 'verified' | 'pending' | string;
  is_read_only: boolean;
}

export interface AdminMigrationsResponse {
  migrations: AdminMigrationItem[];
  total: number;
  applied_count: number;
  can_execute_from_web: boolean;
}

export interface AdminBackupItem {
  collection_name: string;
  source_collection: string;
  created_at?: string;
  document_count: number;
  status: string;
  is_read_only: boolean;
}

export interface AdminBackupsResponse {
  backups: AdminBackupItem[];
  total: number;
  can_restore_from_web: boolean;
}

export interface AdminAlertItem {
  id: string;
  severity: 'info' | 'warning' | 'error';
  title: string;
  message: string;
  timestamp?: string;
}

export interface AdminAlertSummaryResponse {
  overall_status: 'healthy' | 'warning' | 'critical';
  alerts: AdminAlertItem[];
  stuck_jobs_count: number;
  failed_jobs_24h_count: number;
  worker_healthy_count: number;
  worker_total_count: number;
}
