import React from 'react';

export interface ReconnectBannerProps {
  isReconnecting: boolean;
  reconnectAttempt: number;
  maxAttempts?: number;
  onCancel?: () => void;
}

export const ReconnectBanner: React.FC<ReconnectBannerProps> = ({
  isReconnecting,
  reconnectAttempt,
  maxAttempts = 5,
  onCancel,
}) => {
  if (!isReconnecting) return null;

  return (
    <div
      role="status"
      aria-live="assertive"
      className="reconnect-banner bg-amber-500/15 border-b border-amber-500/30 text-amber-200 px-4 py-2 flex items-center justify-between text-xs backdrop-blur animate-pulse z-20"
      style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        padding: '8px 16px',
        backgroundColor: 'rgba(245, 158, 11, 0.15)',
        borderBottom: '1px solid rgba(245, 158, 11, 0.3)',
        color: '#fef3c7',
        fontSize: '12px',
        fontWeight: 500,
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
        <span
          style={{
            display: 'inline-block',
            width: '8px',
            height: '8px',
            borderRadius: '50%',
            backgroundColor: '#f59e0b',
            boxShadow: '0 0 8px #f59e0b',
          }}
        />
        <span>
          Mất kết nối tạm thời. Đang phục hồi luồng chat (thử lần {reconnectAttempt}/{maxAttempts})...
        </span>
      </div>
      {onCancel && (
        <button
          type="button"
          onClick={onCancel}
          style={{
            background: 'transparent',
            border: '1px solid rgba(245, 158, 11, 0.4)',
            borderRadius: '4px',
            color: '#fef3c7',
            padding: '2px 8px',
            cursor: 'pointer',
            fontSize: '11px',
          }}
        >
          Dừng thử lại
        </button>
      )}
    </div>
  );
};
