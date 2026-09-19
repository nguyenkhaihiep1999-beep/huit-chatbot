export interface SessionCredentials {
  sessionId: string;
  csrfToken: string;
}

let csrfToken: string | null = null;
let sessionId: string | null = null;

let adminCsrfToken: string | null = null;
let adminSessionId: string | null = null;

function readSessionValue(key: string): string | null {
  if (typeof sessionStorage === 'undefined') return null;
  try {
    return sessionStorage.getItem(key);
  } catch {
    return null;
  }
}

export function getCsrfToken(): string | null {
  csrfToken ||= readSessionValue('huit_csrf_token');
  return csrfToken;
}

export function getSessionCredentials(): SessionCredentials {
  sessionId ||= readSessionValue('huit_session_id');
  return { sessionId: sessionId || '', csrfToken: getCsrfToken() || '' };
}

export function setSessionCredentials(credentials: SessionCredentials): void {
  sessionId = credentials.sessionId || null;
  csrfToken = credentials.csrfToken || null;
  if (typeof sessionStorage === 'undefined') return;
  try {
    if (sessionId) sessionStorage.setItem('huit_session_id', sessionId);
    else sessionStorage.removeItem('huit_session_id');
    if (csrfToken) sessionStorage.setItem('huit_csrf_token', csrfToken);
    else sessionStorage.removeItem('huit_csrf_token');
  } catch {
    // In-memory credentials remain available when browser storage is blocked.
  }
}

export function getAdminCsrfToken(): string | null {
  return adminCsrfToken;
}

export function setAdminCredentials(credentials: { sessionId?: string; csrfToken?: string } | null): void {
  adminSessionId = credentials?.sessionId || null;
  adminCsrfToken = credentials?.csrfToken || null;
}

export function getCsrfTokenForUrl(url: string): string | null {
  if (url.includes('/api/admin')) {
    return getAdminCsrfToken() || getCsrfToken();
  }
  return getCsrfToken();
}

/**
 * Tạo khóa phạm vi ổn định từ raw session id để namespace dữ liệu cục bộ.
 * Đây không phải cơ chế phân quyền; backend cookie vẫn là nguồn xác thực duy nhất.
 * Không lưu raw session id vào localStorage.
 */
export function getSessionScope(rawSessionId?: string): string {
  const value = (rawSessionId ?? getSessionCredentials().sessionId).trim();
  if (!value) return '';

  let first = 0xdeadbeef ^ value.length;
  let second = 0x41c6ce57 ^ value.length;
  for (let index = 0; index < value.length; index += 1) {
    const code = value.charCodeAt(index);
    first = Math.imul(first ^ code, 2654435761);
    second = Math.imul(second ^ code, 1597334677);
  }
  first = Math.imul(first ^ (first >>> 16), 2246822507) ^ Math.imul(second ^ (second >>> 13), 3266489909);
  second = Math.imul(second ^ (second >>> 16), 2246822507) ^ Math.imul(first ^ (first >>> 13), 3266489909);

  const digest = `${(first >>> 0).toString(16).padStart(8, '0')}${(second >>> 0)
    .toString(16)
    .padStart(8, '0')}`;
  return `scope_${digest}`;
}
