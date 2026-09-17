import { useState, useEffect, useCallback } from 'react';
import { createSession, installSessionRefresh, readCachedSession, SessionBootstrapError } from '../api/sessionApi';

export interface UseSessionBootstrapReturn {
  isReady: boolean;
  isLoading: boolean;
  error: SessionBootstrapError | null;
  retry: () => Promise<void>;
}

export function useSessionBootstrap(): UseSessionBootstrapReturn {
  const cached = readCachedSession();
  const hasValidCached = Boolean(cached.sessionId && cached.csrfToken);
  const [isReady, setIsReady] = useState<boolean>(() => hasValidCached);
  const [isLoading, setIsLoading] = useState<boolean>(() => !hasValidCached);
  const [error, setError] = useState<SessionBootstrapError | null>(null);

  const initSession = useCallback(async () => {
    const currentCached = readCachedSession();
    if (!currentCached.sessionId || !currentCached.csrfToken) {
      setIsLoading(true);
    }
    setError(null);
    try {
      await createSession();
      setIsReady(true);
    } catch (err) {
      setIsReady(false);
      if (err instanceof SessionBootstrapError) {
        setError(err);
      } else {
        setError(
          new SessionBootstrapError({
            code: 'SESSION_BOOTSTRAP_FAILED',
            userFriendlyMessage: 'Không thể khởi tạo phiên làm việc. Vui lòng thử lại.',
          })
        );
      }
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    installSessionRefresh();
    const bootstrapTimer = window.setTimeout(() => {
      void initSession();
    }, 0);
    return () => window.clearTimeout(bootstrapTimer);
  }, [initSession]);

  return {
    isReady,
    isLoading,
    error,
    retry: initSession,
  };
}
