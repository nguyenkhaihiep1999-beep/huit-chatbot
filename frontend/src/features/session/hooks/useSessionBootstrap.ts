import { useEffect } from 'react';
import { createSession, installSessionRefresh } from '../api/sessionApi';

export function useSessionBootstrap(): void {
  useEffect(() => {
    installSessionRefresh();
    createSession().catch(() => {
      // Requests that require CSRF will retry session creation through the client.
    });
  }, []);
}
