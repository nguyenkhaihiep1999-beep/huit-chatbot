import { apiClient, configureSessionRefresher } from '../../../shared/api/httpClient';
import {
  getSessionCredentials,
  setSessionCredentials,
  SessionCredentials,
} from '../../../shared/auth/csrfStore';

let pendingSession: Promise<SessionCredentials> | null = null;

export async function createSession(): Promise<SessionCredentials> {
  if (pendingSession) return pendingSession;
  pendingSession = (async () => {
    try {
      const response = await apiClient('/api/auth/session', {
        method: 'POST',
        headers: { Accept: 'application/json', 'Content-Type': 'application/json' },
        skipCsrf: true,
        skipAuthRetry: true,
      });
      if (!response.ok) throw new Error(`SESSION_BOOTSTRAP_${response.status}`);
      const data = await response.json();
      const credentials = {
        sessionId: data.session_id || '',
        csrfToken: data.csrf_token || '',
      };
      setSessionCredentials(credentials);
      return credentials;
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
