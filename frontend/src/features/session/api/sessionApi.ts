import { apiClient, configureSessionRefresher } from '../../../shared/api/httpClient';
import {
  getSessionCredentials,
  setSessionCredentials,
  SessionCredentials,
} from '../../../shared/auth/csrfStore';
import { SessionBootstrapError, SessionBootstrapErrorCode } from '../types';
import { parseSessionBootstrapResponse } from '../../../shared/contracts';

export { SessionBootstrapError };
export type { SessionBootstrapErrorCode };

let pendingSession: Promise<SessionCredentials> | null = null;
const MAX_RETRIES = 3;

/**
 * Khởi tạo hoặc làm mới phiên làm việc với cơ chế retry có exponential backoff (tối đa 3 lần).
 * Phân biệt rõ các loại lỗi: mất mạng, timeout, 5xx, CSRF, phiên hết hạn.
 * Tuyệt đối không hiển thị mã kỹ thuật thô cho người dùng.
 */
export async function createSession(): Promise<SessionCredentials> {
  if (pendingSession) return pendingSession;

  pendingSession = (async () => {
    try {
      let lastError: SessionBootstrapError | null = null;

      for (let attempt = 0; attempt < MAX_RETRIES; attempt++) {
        // Kiểm tra trạng thái mạng trước khi gửi request
        if (typeof navigator !== 'undefined' && !navigator.onLine) {
          throw new SessionBootstrapError({
            code: 'OFFLINE',
            userFriendlyMessage: 'Không có kết nối mạng. Vui lòng kiểm tra lại đường truyền internet của bạn.',
          });
        }

        const controller = new AbortController();
        const timeoutId = setTimeout(() => controller.abort(), 10000);

        try {
          const response = await apiClient('/api/auth/session', {
            method: 'POST',
            headers: { Accept: 'application/json', 'Content-Type': 'application/json' },
            skipCsrf: true,
            skipAuthRetry: true,
            signal: controller.signal,
          });

          clearTimeout(timeoutId);

          if (!response.ok) {
            const reqId = response.headers.get('X-Request-ID') || '';
            const status = response.status;
            let errBody: any = null;
            try {
              errBody = await response.json();
            } catch {
              // Non-JSON response
            }

            const effectiveReqId = errBody?.request_id || reqId;

            if (status === 401) {
              throw new SessionBootstrapError({
                code: 'SESSION_EXPIRED',
                status,
                requestId: effectiveReqId,
                userFriendlyMessage: 'Phiên làm việc đã hết hạn. Vui lòng nhấn Thử lại để tạo phiên mới.',
              });
            }

            if (status === 403) {
              throw new SessionBootstrapError({
                code: 'CSRF_ERROR',
                status,
                requestId: effectiveReqId,
                userFriendlyMessage: 'Lỗi xác thực phiên bảo mật (CSRF). Vui lòng nhấn Thử lại.',
              });
            }

            if (status >= 500) {
              const serverErr = new SessionBootstrapError({
                code: 'SERVER_ERROR',
                status,
                requestId: effectiveReqId,
                userFriendlyMessage: 'Không thể khởi tạo phiên làm việc. Vui lòng thử lại.',
              });

              // Có thể thử lại với exponential backoff nếu chưa hết lượt
              lastError = serverErr;
              if (attempt < MAX_RETRIES - 1) {
                const delayMs = Math.min(500 * Math.pow(2, attempt), 2500);
                await new Promise((r) => setTimeout(r, delayMs));
                continue;
              }
              throw serverErr;
            }

            throw new SessionBootstrapError({
              code: 'SESSION_BOOTSTRAP_FAILED',
              status,
              requestId: effectiveReqId,
              userFriendlyMessage: 'Không thể khởi tạo phiên làm việc. Vui lòng thử lại.',
            });
          }

          let data;
          try {
            data = parseSessionBootstrapResponse(await response.json());
          } catch (contractError) {
            const reqId = response.headers.get('X-Request-ID') || '';
            throw new SessionBootstrapError({
              code: 'SESSION_BOOTSTRAP_FAILED',
              status: response.status,
              requestId: reqId,
              message: contractError instanceof Error ? contractError.message : 'Invalid session contract',
              userFriendlyMessage: 'Không thể khởi tạo phiên làm việc. Vui lòng thử lại.',
            });
          }

          const credentials: SessionCredentials = {
            sessionId: data.session_id.trim(),
            csrfToken: data.csrf_token.trim(),
          };
          setSessionCredentials(credentials);
          return credentials;
        } catch (fetchErr: any) {
          clearTimeout(timeoutId);

          if (fetchErr instanceof SessionBootstrapError) {
            // Nếu là lỗi không nên retry (offline, 401, 403) hoặc đã hết số lần retry
            if (fetchErr.code === 'OFFLINE' || fetchErr.code === 'CSRF_ERROR' || fetchErr.code === 'SESSION_EXPIRED') {
              throw fetchErr;
            }
            lastError = fetchErr;
          } else if (fetchErr?.name === 'AbortError') {
            lastError = new SessionBootstrapError({
              code: 'TIMEOUT',
              userFriendlyMessage: 'Quá thời gian kết nối đến máy chủ. Vui lòng thử lại.',
            });
          } else {
            lastError = new SessionBootstrapError({
              code: 'SESSION_BOOTSTRAP_FAILED',
              message: fetchErr?.message,
              userFriendlyMessage: 'Không thể khởi tạo phiên làm việc. Vui lòng thử lại.',
            });
          }

          // Exponential backoff trước khi thử lại lần tiếp theo
          if (attempt < MAX_RETRIES - 1) {
            const delayMs = Math.min(500 * Math.pow(2, attempt), 2500);
            await new Promise((r) => setTimeout(r, delayMs));
            continue;
          }
        }
      }

      throw lastError || new SessionBootstrapError({
        code: 'SESSION_BOOTSTRAP_FAILED',
        userFriendlyMessage: 'Không thể khởi tạo phiên làm việc. Vui lòng thử lại.',
      });
    } finally {
      pendingSession = null;
    }
  })();

  return pendingSession;
}

export function installSessionRefresh(): void {
  configureSessionRefresher(createSession);
}

export function readCachedSession(): SessionCredentials {
  return getSessionCredentials();
}
