import { useState, useEffect, useCallback } from 'react';
import { createSession, installSessionRefresh, SessionBootstrapError } from '../api/sessionApi';
import { getSessionScope } from '../../../shared/auth/csrfStore';

export interface UseSessionBootstrapReturn {
  isReady: boolean;
  isLoading: boolean;
  error: SessionBootstrapError | null;
  sessionScope: string;
  retry: () => Promise<void>;
}

export function useSessionBootstrap(): UseSessionBootstrapReturn {
  // Luôn xác nhận cookie với backend trước khi mở khóa UI. Dữ liệu sessionStorage
  // chỉ là cache giao diện và không chứng minh cookie HttpOnly vẫn còn hợp lệ.
  const [isReady, setIsReady] = useState(false);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<SessionBootstrapError | null>(null);
  const [sessionScope, setSessionScope] = useState('');

  const initSession = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const credentials = await createSession();
      setSessionScope(getSessionScope(credentials.sessionId));
      setIsReady(true);
    } catch (err) {
      setIsReady(false);
      setSessionScope('');
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
    sessionScope,
    retry: initSession,
  };
}
