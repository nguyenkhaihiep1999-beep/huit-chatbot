/**
 * httpClient.ts
 * Unified HTTP Client cho toàn bộ Frontend:
 * - Tự động thiết lập credentials: 'same-origin' (truyền HttpOnly Cookie huit_session_id).
 * - Tự động đính kèm X-CSRF-Token cho các phương thức thay đổi dữ liệu (POST / PUT / PATCH / DELETE).
 * - Tự động xử lý lỗi 403 CSRF_TOKEN_INVALID: làm mới session 1 lần và thử lại request.
 */
import { getCsrfTokenForUrl, SessionCredentials } from '../auth/csrfStore';

export interface RequestOptions extends RequestInit {
  skipCsrf?: boolean;
  skipAuthRetry?: boolean;
}

type SessionRefresher = () => Promise<SessionCredentials>;
let sessionRefresher: SessionRefresher | null = null;

export function configureSessionRefresher(refresher: SessionRefresher): void {
  sessionRefresher = refresher;
}

export async function apiClient(url: string, options: RequestOptions = {}): Promise<Response> {
  const method = (options.method || 'GET').toUpperCase();
  const headers = new Headers(options.headers || {});
  const isAdminRequest = url.includes('/api/admin');

  // Đảm bảo có CSRF token cho các request thay đổi trạng thái
  if (!options.skipCsrf && ['POST', 'PUT', 'PATCH', 'DELETE'].includes(method)) {
    let csrf = getCsrfTokenForUrl(url);
    if (!csrf && !isAdminRequest && sessionRefresher) {
      const session = await sessionRefresher();
      csrf = session.csrfToken;
    }
    if (csrf && !headers.has('X-CSRF-Token')) {
      headers.set('X-CSRF-Token', csrf);
    }
  }

  const mergedOptions: RequestInit = {
    ...options,
    method,
    headers,
    credentials: options.credentials || 'same-origin',
  };

  let response = await fetch(url, mergedOptions);

  // Tự động bắt lỗi 403 do CSRF token hết hạn hoặc sai lệch và retry đúng 1 lần cho user session
  if (response.status === 403 && !options.skipAuthRetry && !isAdminRequest && sessionRefresher) {
    try {
      const clone = response.clone();
      const errData = await clone.json();
      const isCsrfError =
        errData?.error_code === 'CSRF_TOKEN_INVALID' ||
        errData?.detail?.error_code === 'CSRF_TOKEN_INVALID' ||
        (typeof errData?.detail === 'string' && errData.detail.toLowerCase().includes('csrf')) ||
        (typeof errData?.message === 'string' && errData.message.toLowerCase().includes('csrf'));

      if (isCsrfError) {
        const refreshed = await sessionRefresher();
        if (refreshed.csrfToken) {
          headers.set('X-CSRF-Token', refreshed.csrfToken);
          response = await fetch(url, {
            ...options,
            method,
            headers,
            credentials: options.credentials || 'same-origin',
          });
        }
      }
    } catch {
      // Bỏ qua nếu phản hồi lỗi không phải JSON
    }
  }

  return response;
}

export const http = {
  get: (url: string, options?: RequestOptions) => apiClient(url, { ...options, method: 'GET' }),
  post: (url: string, body?: any, options?: RequestOptions) => {
    const headers = new Headers(options?.headers || {});
    let serializedBody = body;
    if (body && typeof body === 'object' && !(body instanceof FormData) && !(body instanceof Blob)) {
      if (!headers.has('Content-Type')) {
        headers.set('Content-Type', 'application/json');
      }
      serializedBody = JSON.stringify(body);
    }
    return apiClient(url, { ...options, method: 'POST', headers, body: serializedBody });
  },
  put: (url: string, body?: any, options?: RequestOptions) => {
    const headers = new Headers(options?.headers || {});
    let serializedBody = body;
    if (body && typeof body === 'object' && !(body instanceof FormData) && !(body instanceof Blob)) {
      if (!headers.has('Content-Type')) {
        headers.set('Content-Type', 'application/json');
      }
      serializedBody = JSON.stringify(body);
    }
    return apiClient(url, { ...options, method: 'PUT', headers, body: serializedBody });
  },
  delete: (url: string, options?: RequestOptions) => apiClient(url, { ...options, method: 'DELETE' }),
};
