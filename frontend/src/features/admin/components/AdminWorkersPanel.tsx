import React, { useState, useEffect, useCallback } from 'react';
import {
  Cpu,
  Layers,
  Activity,
  CheckCircle2,
  AlertTriangle,
  Clock,
  RefreshCw,
  Server,
  Zap,
} from 'lucide-react';
import { AdminWorkerItem, AdminQueueStatsResponse } from '../types/admin.types';
import { useAdminOps } from '../hooks/useAdminOps';

export const AdminWorkersPanel: React.FC = () => {
  const { fetchAdminWorkers, fetchAdminQueueStats } = useAdminOps();
  const [workers, setWorkers] = useState<AdminWorkerItem[]>([]);
  const [queueStats, setQueueStats] = useState<AdminQueueStatsResponse | null>(null);
  const [isLoading, setIsLoading] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);

  const loadData = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const [wData, qData] = await Promise.all([
        fetchAdminWorkers(),
        fetchAdminQueueStats(),
      ]);
      setWorkers(wData.workers || []);
      setQueueStats(qData);
    } catch (err: any) {
      setError(err.message || 'Không thể tải dữ liệu worker và hàng đợi');
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    loadData();
    const timer = setInterval(loadData, 15000); // Tự động làm mới mỗi 15s
    return () => clearInterval(timer);
  }, [loadData]);

  return (
    <div className="admin-workers-panel">
      {/* Top Header & Refresh */}
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          marginBottom: '20px',
        }}
      >
        <div>
          <h3 style={{ margin: 0, fontSize: '1.15rem', fontWeight: 600 }}>Giám sát Worker & Hàng đợi</h3>
          <p style={{ margin: '4px 0 0', fontSize: '0.85rem', color: 'var(--color-text-muted)' }}>
            Theo dõi dấu sống (Heartbeat) của các Worker nền và độ sâu hàng đợi bền vững.
          </p>
        </div>
        <button
          type="button"
          onClick={() => loadData()}
          disabled={isLoading}
          className="admin-action-btn btn-secondary"
          style={{ display: 'inline-flex', alignItems: 'center', gap: '6px', padding: '6px 14px', borderRadius: '6px' }}
        >
          <RefreshCw size={14} className={isLoading ? 'spin-icon' : ''} aria-hidden="true" />
          <span>Làm mới</span>
        </button>
      </div>

      {error && (
        <div className="admin-error-box" role="alert" style={{ marginBottom: '16px' }}>
          <AlertTriangle size={18} aria-hidden="true" />
          <span>{error}</span>
          <button type="button" onClick={() => loadData()} className="admin-retry-btn">
            Thử lại
          </button>
        </div>
      )}

      {/* Queue Depth Stat Grid */}
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fit, minmax(160px, 1fr))',
          gap: '14px',
          marginBottom: '24px',
        }}
      >
        <div className="admin-stat-card" style={{ padding: '16px', borderRadius: '10px', background: 'var(--color-surface)', border: '1px solid var(--color-border)' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px', color: 'var(--color-text-muted)', fontSize: '0.82rem' }}>
            <Clock size={16} />
            <span>Đang chờ (Queued)</span>
          </div>
          <div style={{ fontSize: '1.8rem', fontWeight: 700, marginTop: '8px' }}>
            {queueStats?.queued_count ?? 0}
          </div>
        </div>

        <div className="admin-stat-card" style={{ padding: '16px', borderRadius: '10px', background: 'var(--color-surface)', border: '1px solid var(--color-border)' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px', color: 'var(--color-text-muted)', fontSize: '0.82rem' }}>
            <Activity size={16} color="var(--color-primary)" />
            <span>Đang chạy (Processing)</span>
          </div>
          <div style={{ fontSize: '1.8rem', fontWeight: 700, marginTop: '8px', color: 'var(--color-primary)' }}>
            {queueStats?.processing_count ?? 0}
          </div>
        </div>

        <div className="admin-stat-card" style={{ padding: '16px', borderRadius: '10px', background: 'var(--color-surface)', border: '1px solid var(--color-border)' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px', color: 'var(--color-text-muted)', fontSize: '0.82rem' }}>
            <AlertTriangle size={16} color={queueStats && queueStats.stuck_count > 0 ? '#ef4444' : 'inherit'} />
            <span>Bị kẹt Lease (Stuck)</span>
          </div>
          <div
            style={{
              fontSize: '1.8rem',
              fontWeight: 700,
              marginTop: '8px',
              color: queueStats && queueStats.stuck_count > 0 ? '#ef4444' : 'inherit',
            }}
          >
            {queueStats?.stuck_count ?? 0}
          </div>
        </div>

        <div className="admin-stat-card" style={{ padding: '16px', borderRadius: '10px', background: 'var(--color-surface)', border: '1px solid var(--color-border)' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px', color: 'var(--color-text-muted)', fontSize: '0.82rem' }}>
            <AlertTriangle size={16} color="#f59e0b" />
            <span>Thất bại (Failed)</span>
          </div>
          <div style={{ fontSize: '1.8rem', fontWeight: 700, marginTop: '8px', color: '#f59e0b' }}>
            {queueStats?.failed_count ?? 0}
          </div>
        </div>

        <div className="admin-stat-card" style={{ padding: '16px', borderRadius: '10px', background: 'var(--color-surface)', border: '1px solid var(--color-border)' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px', color: 'var(--color-text-muted)', fontSize: '0.82rem' }}>
            <CheckCircle2 size={16} color="#22c55e" />
            <span>Hoàn tất (Completed)</span>
          </div>
          <div style={{ fontSize: '1.8rem', fontWeight: 700, marginTop: '8px', color: '#22c55e' }}>
            {queueStats?.completed_count ?? 0}
          </div>
        </div>
      </div>

      {/* Workers Grid */}
      <h4 style={{ margin: '0 0 12px', fontSize: '1rem', fontWeight: 600 }}>Danh sách Worker đang kết nối ({workers.length})</h4>
      {workers.length === 0 ? (
        <div style={{ padding: '40px', textAlign: 'center', background: 'var(--color-surface)', borderRadius: '10px', border: '1px solid var(--color-border)', color: 'var(--color-text-muted)' }}>
          Không phát hiện worker nào đang hoạt động.
        </div>
      ) : (
        <div
          style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))',
            gap: '16px',
          }}
        >
          {workers.map((w) => {
            const isActive = w.status === 'active' || w.status === 'idle';
            return (
              <div
                key={w.worker_id}
                style={{
                  padding: '16px',
                  borderRadius: '10px',
                  background: 'var(--color-surface)',
                  border: '1px solid var(--color-border)',
                  display: 'flex',
                  flexDirection: 'column',
                  gap: '10px',
                }}
              >
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                    <Cpu size={18} color="var(--color-primary)" />
                    <strong style={{ fontSize: '0.92rem' }}>{w.worker_id}</strong>
                  </div>
                  <span
                    style={{
                      display: 'inline-flex',
                      alignItems: 'center',
                      gap: '4px',
                      padding: '2px 8px',
                      borderRadius: '12px',
                      fontSize: '0.72rem',
                      fontWeight: 600,
                      background: isActive ? 'rgba(34, 197, 94, 0.1)' : 'rgba(239, 68, 68, 0.1)',
                      color: isActive ? '#16a34a' : '#dc2626',
                    }}
                  >
                    <span
                      style={{
                        width: '6px',
                        height: '6px',
                        borderRadius: '50%',
                        background: isActive ? '#22c55e' : '#ef4444',
                      }}
                    />
                    {w.status.toUpperCase()}
                  </span>
                </div>

                <div style={{ fontSize: '0.82rem', color: 'var(--color-text-secondary)', display: 'flex', flexDirection: 'column', gap: '4px' }}>
                  <div>
                    Heartbeat: <strong>{w.last_seen ? new Date(w.last_seen).toLocaleTimeString('vi-VN') : 'Vừa xong'}</strong>
                  </div>
                  <div>
                    Tác vụ đang xử lý: <strong>{w.active_jobs_count}</strong>
                  </div>
                  {w.active_job_id && (
                    <div style={{ wordBreak: 'break-all' }}>
                      Job ID: <code>{w.active_job_id}</code>
                    </div>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
};
