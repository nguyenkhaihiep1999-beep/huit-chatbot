import { useState, useEffect, useCallback } from 'react';
import { loginAdmin, logoutAdmin, verifyAdminSession } from '../api/adminApi';

export interface UseAdminAuthReturn {
  isAuthenticated: boolean;
  isChecking: boolean;
  isLoggingIn: boolean;
  error: string | null;
  login: (username: string, password: string) => Promise<boolean>;
  logout: () => Promise<void>;
  checkSession: () => Promise<boolean>;
}

/**
 * Hook quản lý trạng thái đăng nhập của Admin.
 * Lưu ý quan trọng:
 * - KHÔNG LƯU TOKEN VÀO LOCALSTORAGE HOẶC SESSIONSTORAGE.
 * - Trình duyệt tự động gửi và nhận HttpOnly Cookie (huit_admin_token) qua same-origin.
 */
export function useAdminAuth(): UseAdminAuthReturn {
  const [isAuthenticated, setIsAuthenticated] = useState<boolean>(false);
  const [isChecking, setIsChecking] = useState<boolean>(true);
  const [isLoggingIn, setIsLoggingIn] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);

  const checkSession = useCallback(async (): Promise<boolean> => {
    setIsChecking(true);
    try {
      const valid = await verifyAdminSession();
      setIsAuthenticated(valid);
      return valid;
    } catch {
      setIsAuthenticated(false);
      return false;
    } finally {
      setIsChecking(false);
    }
  }, []);

  useEffect(() => {
    let isMounted = true;
    verifyAdminSession()
      .then((valid) => {
        if (isMounted) {
          setIsAuthenticated(valid);
          setIsChecking(false);
        }
      })
      .catch(() => {
        if (isMounted) {
          setIsAuthenticated(false);
          setIsChecking(false);
        }
      });

    return () => {
      isMounted = false;
    };
  }, []);

  const login = useCallback(async (username: string, password: string): Promise<boolean> => {
    setIsLoggingIn(true);
    setError(null);
    try {
      const result = await loginAdmin(username, password);
      if (result.success) {
        setIsAuthenticated(true);
        return true;
      }
      setError('Đăng nhập không thành công.');
      return false;
    } catch (err: any) {
      setError(err?.message || 'Tài khoản hoặc mật khẩu không hợp lệ.');
      return false;
    } finally {
      setIsLoggingIn(false);
    }
  }, []);

  const logout = useCallback(async (): Promise<void> => {
    await logoutAdmin();
    setIsAuthenticated(false);
    setError(null);
  }, []);

  return {
    isAuthenticated,
    isChecking,
    isLoggingIn,
    error,
    login,
    logout,
    checkSession,
  };
}
