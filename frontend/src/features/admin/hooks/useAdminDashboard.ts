import { useState, useEffect, useCallback } from 'react';
import { fetchHealthReady, fetchAdminMetrics, requestClearCache } from '../api/adminApi';
import { SystemHealthData, AdminMetricsData, ClearCacheResult } from '../types/admin.types';

export interface UseAdminDashboardReturn {
  health: SystemHealthData | null;
  metrics: AdminMetricsData | null;
  isLoading: boolean;
  error: string | null;
  isClearingCache: boolean;
  clearCacheResult: ClearCacheResult | null;
  refresh: () => Promise<void>;
  clearCache: () => Promise<void>;
  dismissCacheResult: () => void;
}

export function useAdminDashboard(): UseAdminDashboardReturn {
  const [health, setHealth] = useState<SystemHealthData | null>(null);
  const [metrics, setMetrics] = useState<AdminMetricsData | null>(null);
  const [isLoading, setIsLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const [isClearingCache, setIsClearingCache] = useState<boolean>(false);
  const [clearCacheResult, setClearCacheResult] = useState<ClearCacheResult | null>(null);

  const refresh = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const [healthData, metricsData] = await Promise.all([
        fetchHealthReady().catch((err) => {
          console.warn('Lỗi đọc health/ready:', err);
          return null;
        }),
        fetchAdminMetrics(),
      ]);

      if (healthData) setHealth(healthData);
      setMetrics(metricsData);
    } catch (err: any) {
      setError(err?.message || 'Không thể tải dữ liệu chỉ số quản trị');
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    let isMounted = true;
    Promise.all([
      fetchHealthReady().catch((err) => {
        console.warn('Lỗi đọc health/ready:', err);
        return null;
      }),
      fetchAdminMetrics().catch((err) => {
        if (isMounted) {
          setError(err?.message || 'Không thể tải dữ liệu chỉ số quản trị');
        }
        return null;
      }),
    ]).then(([healthData, metricsData]) => {
      if (isMounted) {
        if (healthData) setHealth(healthData);
        if (metricsData) setMetrics(metricsData);
        setIsLoading(false);
      }
    });

    return () => {
      isMounted = false;
    };
  }, []);

  const clearCache = useCallback(async () => {
    setIsClearingCache(true);
    try {
      const res = await requestClearCache();
      setClearCacheResult(res);
      // Tải lại metrics sau khi xóa cache
      await refresh();
    } catch (err: any) {
      setClearCacheResult({
        success: false,
        message: err?.message || 'Lỗi khi xóa bộ nhớ đệm',
      });
    } finally {
      setIsClearingCache(false);
    }
  }, [refresh]);

  const dismissCacheResult = useCallback(() => {
    setClearCacheResult(null);
  }, []);

  return {
    health,
    metrics,
    isLoading,
    error,
    isClearingCache,
    clearCacheResult,
    refresh,
    clearCache,
    dismissCacheResult,
  };
}
