/**
 * Public Hook Facade - Admin Feature
 * Re-exports admin authentication, dashboard metrics, and operations hooks.
 */
export {
  useAdminAuth,
  type UseAdminAuthReturn,
} from '../src/features/admin/hooks/useAdminAuth';

export {
  useAdminDashboard,
  type UseAdminDashboardReturn,
} from '../src/features/admin/hooks/useAdminDashboard';

export { useAdminOps } from '../src/features/admin/hooks/useAdminOps';
