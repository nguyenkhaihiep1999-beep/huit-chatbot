export interface SessionCredentials {
  sessionId: string;
  csrfToken: string;
}

let csrfToken: string | null = null;
let sessionId: string | null = null;

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
