/**
 * adminApi.ts
 * API Service cho trang quản trị (Admin Portal):
 * - Xác thực thông qua HttpOnly cookies và CSRF token.
 * - Tuyệt đối không lưu token nhạy cảm trong localStorage.
 * - Khử khuẩn dữ liệu, không trả raw question, secret, hay stacktrace.
 */
import { http } from '../../../shared/api/httpClient';
import { setSessionCredentials } from '../../../shared/auth/csrfStore';
import {
  SystemHealthData,
  AdminMetricsData,
  ClearCacheResult,
  AdminJobListResponse,
  AdminJobDetailResponse,
  AdminWorkersResponse,
  AdminQueueStatsResponse,
  AdminErrorLogsResponse,
  AdminMigrationsResponse,
  AdminBackupsResponse,
  AdminAlertSummaryResponse,
} from '../types/admin.types';

export async function loginAdmin(username: string, password: string): Promise<{ success: boolean; message: string; csrf_token?: string }> {
  const res = await http.post('/api/admin/login', { username, password });
  if (!res.ok) {
    const errorData = await res.json().catch(() => ({}));
    throw new Error(errorData.detail || 'Tài khoản hoặc mật khẩu không chính xác.');
  }
  const data = await res.json();
  if (data?.csrf_token) {
    setSessionCredentials({
      sessionId: 'admin',
      csrfToken: data.csrf_token,
    });
  }
  return data;
}

export async function verifyAdminSession(): Promise<boolean> {
  try {
    const res = await http.get('/api/admin/verify');
    if (!res.ok) return false;
    const data = await res.json();
    return Boolean(data?.valid);
  } catch {
    return false;
  }
}

export async function logoutAdmin(): Promise<boolean> {
  try {
    const res = await http.post('/api/admin/logout', {});
    setSessionCredentials({
      sessionId: '',
      csrfToken: '',
    });
    return res.ok;
  } catch {
    setSessionCredentials({
      sessionId: '',
      csrfToken: '',
    });
    return false;
  }
}

export async function fetchHealthReady(): Promise<SystemHealthData> {
  const res = await http.get('/api/health/ready');
  if (!res.ok && res.status !== 503) {
    throw new Error(`HTTP ${res.status}: Không thể đọc trạng thái sức khỏe hệ thống`);
  }
  return res.json();
}

export async function fetchAdminMetrics(): Promise<AdminMetricsData> {
  const res = await http.get('/api/admin/metrics');
  if (!res.ok) {
    if (res.status === 401 || res.status === 403) {
      throw new Error('UNAUTHORIZED');
    }
    throw new Error(`HTTP ${res.status}: Không thể tải dữ liệu chỉ số quản trị`);
  }
  const raw = await res.json();

  // Khử khuẩn dữ liệu: Tuyệt đối không để lộ prompt đầy đủ, API keys hay secrets
  const sanitizedRecent: AdminMetricsData['recent_events'] = (raw.recent_events || []).map((e: any) => ({
    request_id: e.request_id || e.id || 'N/A',
    intent: e.intent || 'TuVanChung',
    cached: Boolean(e.cached),
    latency_ms: typeof e.latency_ms === 'number' ? Math.round(e.latency_ms) : 0,
    model: e.meta?.model || e.model || 'Gemini 2.5 Flash',
    created_at: e.created_at || e.timestamp || '',
    status: e.status || (e.latency_ms ? 'Thành công' : 'Đang xử lý'),
  }));

  return {
    total_events: Number(raw.total_events || 0),
    total_cached_queries: Number(raw.total_cached_queries || 0),
    total_kb_documents: Number(raw.total_kb_documents || 0),
    recent_events: sanitizedRecent,
  };
}

export async function requestClearCache(): Promise<ClearCacheResult> {
  const res = await http.post('/api/admin/clear-cache', { confirm: true });
  if (!res.ok) {
    throw new Error(`HTTP ${res.status}: Thao tác xóa cache thất bại`);
  }
  return res.json();
}

// ==============================================================================
// JOBS QUEUE MANAGEMENT
// ==============================================================================
export async function fetchAdminJobs(params: {
  page?: number;
  limit?: number;
  status?: string;
  action?: string;
  timeRange?: string;
} = {}): Promise<AdminJobListResponse> {
  const q = new URLSearchParams();
  if (params.page) q.set('page', String(params.page));
  if (params.limit) q.set('limit', String(params.limit));
  if (params.status && params.status !== 'all') q.set('status', params.status);
  if (params.action && params.action !== 'all') q.set('action', params.action);
  if (params.timeRange && params.timeRange !== 'all') q.set('time_range', params.timeRange);

  const url = `/api/admin/jobs${q.toString() ? `?${q.toString()}` : ''}`;
  const res = await http.get(url);
  if (!res.ok) {
    if (res.status === 401 || res.status === 403) throw new Error('UNAUTHORIZED');
    throw new Error(`HTTP ${res.status}: Không thể tải danh sách tác vụ`);
  }
  return res.json();
}

export async function fetchAdminJobDetail(jobId: string): Promise<AdminJobDetailResponse> {
  const res = await http.get(`/api/admin/jobs/${encodeURIComponent(jobId)}`);
  if (!res.ok) {
    if (res.status === 404) throw new Error('Không tìm thấy công việc');
    throw new Error(`HTTP ${res.status}: Không thể tải chi tiết công việc`);
  }
  return res.json();
}

export async function retryAdminJob(jobId: string, reason?: string): Promise<{ success: boolean; message: string }> {
  const res = await http.post(`/api/admin/jobs/${encodeURIComponent(jobId)}/retry`, { reason });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || `HTTP ${res.status}: Thử lại tác vụ thất bại`);
  }
  return res.json();
}

export async function cancelAdminJob(jobId: string, reason?: string): Promise<{ success: boolean; message: string }> {
  const res = await http.post(`/api/admin/jobs/${encodeURIComponent(jobId)}/cancel`, { reason });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || `HTTP ${res.status}: Hủy tác vụ thất bại`);
  }
  return res.json();
}

// ==============================================================================
// WORKERS & QUEUE OBSERVABILITY
// ==============================================================================
export async function fetchAdminWorkers(): Promise<AdminWorkersResponse> {
  const res = await http.get('/api/admin/workers');
  if (!res.ok) {
    throw new Error(`HTTP ${res.status}: Không thể tải trạng thái worker`);
  }
  return res.json();
}

export async function fetchAdminQueueStats(): Promise<AdminQueueStatsResponse> {
  const res = await http.get('/api/admin/queue/stats');
  if (!res.ok) {
    throw new Error(`HTTP ${res.status}: Không thể tải số liệu hàng đợi`);
  }
  return res.json();
}

// ==============================================================================
// SANITIZED ERROR LOGS
// ==============================================================================
export async function fetchAdminErrorLogs(params: {
  requestId?: string;
  timeRange?: string;
  limit?: number;
} = {}): Promise<AdminErrorLogsResponse> {
  const q = new URLSearchParams();
  if (params.requestId) q.set('request_id', params.requestId.trim());
  if (params.timeRange) q.set('time_range', params.timeRange);
  if (params.limit) q.set('limit', String(params.limit));

  const url = `/api/admin/logs/errors${q.toString() ? `?${q.toString()}` : ''}`;
  const res = await http.get(url);
  if (!res.ok) {
    throw new Error(`HTTP ${res.status}: Không thể tải nhật ký lỗi`);
  }
  return res.json();
}

// ==============================================================================
// READ-ONLY MIGRATIONS & BACKUPS
// ==============================================================================
export async function fetchAdminMigrations(): Promise<AdminMigrationsResponse> {
  const res = await http.get('/api/admin/migrations');
  if (!res.ok) {
    throw new Error(`HTTP ${res.status}: Không thể tải trạng thái migrations`);
  }
  return res.json();
}

export async function fetchAdminBackups(): Promise<AdminBackupsResponse> {
  const res = await http.get('/api/admin/backups');
  if (!res.ok) {
    throw new Error(`HTTP ${res.status}: Không thể tải danh sách sao lưu`);
  }
  return res.json();
}

// ==============================================================================
// ALERTS SUMMARY
// ==============================================================================
export async function fetchAdminAlerts(): Promise<AdminAlertSummaryResponse> {
  const res = await http.get('/api/admin/alerts');
  if (!res.ok) {
    throw new Error(`HTTP ${res.status}: Không thể tải thông tin cảnh báo`);
  }
  return res.json();
}
