import React from 'react';
import { useAdminAuth } from '../hooks/useAdminAuth';
import { useAdminDashboard } from '../hooks/useAdminDashboard';
import { AdminLoginForm } from './AdminLoginForm';
import { AdminDashboard } from './AdminDashboard';
import { Loader2 } from 'lucide-react';

export interface AdminPageProps {
  onNavigateChat: () => void;
}

export const AdminPage: React.FC<AdminPageProps> = ({ onNavigateChat }) => {
  const {
    isAuthenticated,
    isChecking,
    isLoggingIn,
    error: authError,
    login,
    logout,
  } = useAdminAuth();

  const {
    health,
    metrics,
    isLoading: isDashboardLoading,
    error: dashboardError,
    isClearingCache,
    clearCacheResult,
    refresh,
    clearCache,
    dismissCacheResult,
  } = useAdminDashboard();

  if (isChecking) {
    return (
      <div className="admin-loading-screen" role="status" aria-live="polite">
        <Loader2 size={36} className="spinner-rotate" aria-hidden="true" />
        <p>Đang kiểm tra quyền hạn quản trị...</p>
      </div>
    );
  }

  if (!isAuthenticated) {
    return (
      <AdminLoginForm
        onLogin={login}
        isLoggingIn={isLoggingIn}
        error={authError}
        onBackToChat={onNavigateChat}
      />
    );
  }

  return (
    <AdminDashboard
      health={health}
      metrics={metrics}
      isLoading={isDashboardLoading}
      error={dashboardError}
      isClearingCache={isClearingCache}
      clearCacheResult={clearCacheResult}
      onRefresh={refresh}
      onClearCache={clearCache}
      onDismissCacheResult={dismissCacheResult}
      onLogout={logout}
      onBackToChat={onNavigateChat}
    />
  );
};
