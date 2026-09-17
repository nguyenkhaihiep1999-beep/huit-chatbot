/**
 * useAdminOps.ts
 * Hook trung gian tuân thủ LTX frontend architecture contract:
 * Tách biệt API transport khỏi presentation components.
 */
import * as adminApi from '../api/adminApi';

export function useAdminOps() {
  return {
    fetchAdminJobs: (...args: Parameters<typeof adminApi.fetchAdminJobs>) => adminApi.fetchAdminJobs(...args),
    fetchAdminJobDetail: (...args: Parameters<typeof adminApi.fetchAdminJobDetail>) => adminApi.fetchAdminJobDetail(...args),
    retryAdminJob: (...args: Parameters<typeof adminApi.retryAdminJob>) => adminApi.retryAdminJob(...args),
    cancelAdminJob: (...args: Parameters<typeof adminApi.cancelAdminJob>) => adminApi.cancelAdminJob(...args),
    fetchAdminWorkers: (...args: Parameters<typeof adminApi.fetchAdminWorkers>) => adminApi.fetchAdminWorkers(...args),
    fetchAdminQueueStats: (...args: Parameters<typeof adminApi.fetchAdminQueueStats>) => adminApi.fetchAdminQueueStats(...args),
    fetchAdminErrorLogs: (...args: Parameters<typeof adminApi.fetchAdminErrorLogs>) => adminApi.fetchAdminErrorLogs(...args),
    fetchAdminMigrations: (...args: Parameters<typeof adminApi.fetchAdminMigrations>) => adminApi.fetchAdminMigrations(...args),
    fetchAdminBackups: (...args: Parameters<typeof adminApi.fetchAdminBackups>) => adminApi.fetchAdminBackups(...args),
    fetchAdminAlerts: (...args: Parameters<typeof adminApi.fetchAdminAlerts>) => adminApi.fetchAdminAlerts(...args),
  };
}
