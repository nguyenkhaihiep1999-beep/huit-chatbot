import React, { useState, useEffect, useCallback } from 'react';
import {
  Database,
  Archive,
  Shield,
  ShieldCheck,
  AlertTriangle,
  RefreshCw,
  CheckCircle2,
  FileCode,
  Lock,
} from 'lucide-react';
import {
  AdminMigrationItem,
  AdminBackupItem,
  AdminAlertSummaryResponse,
} from '../types/admin.types';
import { useAdminOps } from '../hooks/useAdminOps';

export const AdminSystemHealthPanel: React.FC = () => {
  const { fetchAdminMigrations, fetchAdminBackups, fetchAdminAlerts } = useAdminOps();
  const [migrations, setMigrations] = useState<AdminMigrationItem[]>([]);
  const [backups, setBackups] = useState<AdminBackupItem[]>([]);
  const [alertsSummary, setAlertsSummary] = useState<AdminAlertSummaryResponse | null>(null);

  const [isLoading, setIsLoading] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);

  const loadData = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const [mRes, bRes, aRes] = await Promise.all([
        fetchAdminMigrations(),
        fetchAdminBackups(),
        fetchAdminAlerts(),
      ]);
      setMigrations(mRes.migrations || []);
      setBackups(bRes.backups || []);
      setAlertsSummary(aRes);
    } catch (err: any) {
      setError(err.message || 'Không thể tải dữ liệu hệ thống');
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    loadData();
  }, [loadData]);

  return (
    <div className="admin-system-panel">
      {/* Security Assurance Banner */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: '10px',
          padding: '12px 16px',
          marginBottom: '20px',
          borderRadius: '8px',
          background: 'rgba(34, 197, 94, 0.08)',
          border: '1px solid rgba(34, 197, 94, 0.25)',
          color: '#16a34a',
          fontSize: '0.86rem',
        }}
      >
        <Lock size={18} style={{ flexShrink: 0 }} aria-hidden="true" />
        <span>
          <strong>Nguyên tắc bảo vệ an ninh hạ tầng:</strong> Toàn bộ dữ liệu migration và danh sách bản sao lưu (backup)
          ở chế độ <strong>CHỈ ĐỌC (Read-Only)</strong>. Không cung cấp nút Restart server hay thao tác thay đổi schema/restore
          từ xa qua Web để triệt tiêu bề mặt tấn công.
        </span>
      </div>

      {error && (
        <div className="admin-error-box" role="alert" style={{ marginBottom: '16px' }}>
          <AlertTriangle size={18} />
          <span>{error}</span>
          <button type="button" onClick={() => loadData()} className="admin-retry-btn">Thử lại</button>
        </div>
      )}

      {/* Alert Summary Section */}
      {alertsSummary && alertsSummary.alerts.length > 0 && (
        <div style={{ marginBottom: '24px' }}>
          <h4 style={{ margin: '0 0 12px', fontSize: '1rem', fontWeight: 600, display: 'flex', alignItems: 'center', gap: '8px' }}>
            <AlertTriangle size={18} color="#f59e0b" />
            <span>Cảnh báo hệ thống đang chú ý ({alertsSummary.alerts.length})</span>
          </h4>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
            {alertsSummary.alerts.map((alt) => (
              <div
                key={alt.id}
                style={{
                  padding: '12px 16px',
                  borderRadius: '8px',
                  background: alt.severity === 'error' ? 'rgba(239, 68, 68, 0.08)' : 'rgba(245, 158, 11, 0.08)',
                  border: `1px solid ${alt.severity === 'error' ? '#ef4444' : '#f59e0b'}`,
                  display: 'flex',
                  justifyContent: 'space-between',
                  alignItems: 'center',
                }}
              >
                <div>
                  <strong style={{ fontSize: '0.9rem', color: alt.severity === 'error' ? '#dc2626' : '#d97706' }}>
                    {alt.title}
                  </strong>
                  <p style={{ margin: '4px 0 0', fontSize: '0.84rem', color: 'var(--color-text-secondary)' }}>
                    {alt.message}
                  </p>
                </div>
                <span style={{ fontSize: '0.75rem', color: 'var(--color-text-muted)' }}>
                  {alt.timestamp ? new Date(alt.timestamp).toLocaleTimeString('vi-VN') : ''}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Grid: Migrations & Backups */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(360px, 1fr))', gap: '20px' }}>
        {/* Migrations Table (Read-only) */}
        <div style={{ background: 'var(--color-surface)', borderRadius: '10px', border: '1px solid var(--color-border)', padding: '16px' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '14px' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
              <FileCode size={18} color="var(--color-primary)" />
              <h4 style={{ margin: 0, fontSize: '0.95rem', fontWeight: 600 }}>Cấu trúc Schema Migrations ({migrations.length})</h4>
            </div>
            <span className="admin-status-badge badge-neutral" style={{ fontSize: '0.72rem' }}>
              <Lock size={10} style={{ marginRight: '3px' }} /> CHỈ ĐỌC
            </span>
          </div>

          <div style={{ maxHeight: '350px', overflowY: 'auto' }}>
            <table style={{ width: '100%', fontSize: '0.82rem', borderCollapse: 'collapse' }}>
              <thead>
                <tr style={{ borderBottom: '1px solid var(--color-border)', color: 'var(--color-text-muted)', textAlign: 'left' }}>
                  <th style={{ padding: '6px 8px' }}>Ver</th>
                  <th style={{ padding: '6px 8px' }}>Script</th>
                  <th style={{ padding: '6px 8px' }}>Trạng thái</th>
                </tr>
              </thead>
              <tbody>
                {migrations.map((m) => (
                  <tr key={m.name} style={{ borderBottom: '1px solid var(--color-border)' }}>
                    <td style={{ padding: '8px', fontWeight: 600 }}>{m.version}</td>
                    <td style={{ padding: '8px' }}>
                      <div style={{ fontWeight: 500 }}>{m.name}</div>
                      <div style={{ fontSize: '0.75rem', color: 'var(--color-text-muted)' }}>{m.description}</div>
                    </td>
                    <td style={{ padding: '8px' }}>
                      <span className="admin-status-badge badge-healthy" style={{ fontSize: '0.7rem' }}>
                        <CheckCircle2 size={10} style={{ marginRight: '2px' }} /> Đã áp dụng
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>

        {/* Backups Table (Read-only) */}
        <div style={{ background: 'var(--color-surface)', borderRadius: '10px', border: '1px solid var(--color-border)', padding: '16px' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '14px' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
              <Archive size={18} color="var(--color-primary)" />
              <h4 style={{ margin: 0, fontSize: '0.95rem', fontWeight: 600 }}>Bản sao lưu Database ({backups.length})</h4>
            </div>
            <span className="admin-status-badge badge-neutral" style={{ fontSize: '0.72rem' }}>
              <Lock size={10} style={{ marginRight: '3px' }} /> CHỈ ĐỌC
            </span>
          </div>

          <div style={{ maxHeight: '350px', overflowY: 'auto' }}>
            {backups.length === 0 ? (
              <p style={{ padding: '20px', textAlign: 'center', color: 'var(--color-text-muted)', fontSize: '0.85rem' }}>
                Không tìm thấy bản sao lưu snapshot nào trong cluster hiện tại.
              </p>
            ) : (
              <table style={{ width: '100%', fontSize: '0.82rem', borderCollapse: 'collapse' }}>
                <thead>
                  <tr style={{ borderBottom: '1px solid var(--color-border)', color: 'var(--color-text-muted)', textAlign: 'left' }}>
                    <th style={{ padding: '6px 8px' }}>Collection sao lưu</th>
                    <th style={{ padding: '6px 8px' }}>Số bản ghi</th>
                    <th style={{ padding: '6px 8px' }}>Thời gian</th>
                  </tr>
                </thead>
                <tbody>
                  {backups.map((b) => (
                    <tr key={b.collection_name} style={{ borderBottom: '1px solid var(--color-border)' }}>
                      <td style={{ padding: '8px' }}>
                        <code>{b.collection_name}</code>
                        <div style={{ fontSize: '0.75rem', color: 'var(--color-text-muted)' }}>Nguồn: {b.source_collection}</div>
                      </td>
                      <td style={{ padding: '8px', fontWeight: 600 }}>{b.document_count.toLocaleString()}</td>
                      <td style={{ padding: '8px', color: 'var(--color-text-muted)' }}>
                        {b.created_at ? new Date(b.created_at).toLocaleDateString('vi-VN') : '-'}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </div>
      </div>
    </div>
  );
};
