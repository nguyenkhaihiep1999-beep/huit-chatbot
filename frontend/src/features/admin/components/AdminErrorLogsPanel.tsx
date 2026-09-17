import React, { useState, useEffect, useCallback } from 'react';
import {
  AlertTriangle,
  Search,
  ShieldCheck,
  RefreshCw,
  Clock,
  Calendar,
  Layers,
  Activity,
} from 'lucide-react';
import { SanitizedErrorLogItem } from '../types/admin.types';
import { useAdminOps } from '../hooks/useAdminOps';

export const AdminErrorLogsPanel: React.FC = () => {
  const { fetchAdminErrorLogs } = useAdminOps();
  const [logs, setLogs] = useState<SanitizedErrorLogItem[]>([]);
  const [requestIdInput, setRequestIdInput] = useState<string>('');
  const [searchedRequestId, setSearchedRequestId] = useState<string>('');
  const [timeRange, setTimeRange] = useState<string>('24h');
  const [isLoading, setIsLoading] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);

  const loadLogs = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const data = await fetchAdminErrorLogs({
        requestId: searchedRequestId,
        timeRange,
        limit: 50,
      });
      setLogs(data.logs || []);
    } catch (err: any) {
      setError(err.message || 'Không thể tải nhật ký lỗi hệ thống');
    } finally {
      setIsLoading(false);
    }
  }, [searchedRequestId, timeRange]);

  useEffect(() => {
    loadLogs();
  }, [loadLogs]);

  const handleSearch = (e: React.FormEvent) => {
    e.preventDefault();
    setSearchedRequestId(requestIdInput.trim());
  };

  return (
    <div className="admin-error-logs-panel">
      {/* Privacy Sanitization Banner */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: '10px',
          padding: '12px 16px',
          marginBottom: '20px',
          borderRadius: '8px',
          background: 'rgba(59, 130, 246, 0.08)',
          border: '1px solid rgba(59, 130, 246, 0.25)',
          color: 'var(--color-primary)',
          fontSize: '0.86rem',
        }}
      >
        <ShieldCheck size={18} style={{ flexShrink: 0 }} aria-hidden="true" />
        <span>
          <strong>Khử khuẩn bảo mật dữ liệu:</strong> Toàn bộ nhật ký lỗi được lọc tự động.
          Tuyệt đối không lưu trữ hay hiển thị câu hỏi thô của người dùng, token bí mật, API key,
          hoặc stacktrace nội bộ.
        </span>
      </div>

      {/* Search & Filter Toolbar */}
      <div
        className="admin-controls-card"
        style={{
          display: 'flex',
          flexWrap: 'wrap',
          gap: '12px',
          alignItems: 'center',
          justifyContent: 'space-between',
          padding: '16px',
          marginBottom: '20px',
          background: 'var(--color-surface)',
          border: '1px solid var(--color-border)',
          borderRadius: '10px',
        }}
      >
        <form onSubmit={handleSearch} style={{ display: 'flex', gap: '8px', alignItems: 'center', flex: 1, minWidth: '280px' }}>
          <div style={{ position: 'relative', flex: 1 }}>
            <Search size={15} style={{ position: 'absolute', left: '10px', top: '50%', transform: 'translateY(-50%)', color: 'var(--color-text-muted)' }} />
            <input
              type="text"
              value={requestIdInput}
              onChange={(e) => setRequestIdInput(e.target.value)}
              placeholder="Tra cứu theo Request ID (ví dụ: req_...)"
              className="admin-search-input"
              style={{ width: '100%', padding: '7px 12px 7px 32px', borderRadius: '6px', border: '1px solid var(--color-border)' }}
            />
          </div>
          <button
            type="submit"
            className="admin-action-btn btn-primary"
            style={{ padding: '7px 14px', borderRadius: '6px', border: 'none', background: 'var(--color-primary)', color: '#fff', cursor: 'pointer' }}
          >
            Tìm kiếm
          </button>
          {searchedRequestId && (
            <button
              type="button"
              onClick={() => {
                setRequestIdInput('');
                setSearchedRequestId('');
              }}
              className="admin-action-btn btn-secondary"
              style={{ padding: '7px 12px', borderRadius: '6px', border: '1px solid var(--color-border)' }}
            >
              Xóa lọc
            </button>
          )}
        </form>

        <div style={{ display: 'flex', gap: '12px', alignItems: 'center' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
            <Calendar size={15} color="var(--color-text-muted)" />
            <select
              value={timeRange}
              onChange={(e) => setTimeRange(e.target.value)}
              style={{ padding: '7px 10px', borderRadius: '6px', border: '1px solid var(--color-border)' }}
            >
              <option value="1h">1 giờ qua</option>
              <option value="24h">24 giờ qua</option>
              <option value="7d">7 ngày qua</option>
              <option value="all">Tất cả</option>
            </select>
          </div>

          <button
            type="button"
            onClick={() => loadLogs()}
            disabled={isLoading}
            className="admin-action-btn btn-secondary"
            style={{ display: 'inline-flex', alignItems: 'center', gap: '6px', padding: '7px 12px', borderRadius: '6px', border: '1px solid var(--color-border)' }}
            aria-label="Tải lại nhật ký lỗi"
          >
            <RefreshCw size={14} className={isLoading ? 'spin-icon' : ''} />
            <span>Làm mới</span>
          </button>
        </div>
      </div>

      {error && (
        <div className="admin-error-box" role="alert" style={{ marginBottom: '16px' }}>
          <AlertTriangle size={18} />
          <span>{error}</span>
          <button type="button" onClick={() => loadLogs()} className="admin-retry-btn">Thử lại</button>
        </div>
      )}

      {/* Error Logs Table */}
      <div className="admin-table-wrapper" style={{ overflowX: 'auto', background: 'var(--color-surface)', borderRadius: '10px', border: '1px solid var(--color-border)' }}>
        <table className="admin-events-table" style={{ width: '100%', borderCollapse: 'collapse' }}>
          <thead>
            <tr>
              <th scope="col">Thời gian</th>
              <th scope="col">Request ID</th>
              <th scope="col">Nguồn</th>
              <th scope="col">Mã lỗi</th>
              <th scope="col">Thông điệp đã sanitize</th>
              <th scope="col">Hash câu hỏi (SHA-256)</th>
            </tr>
          </thead>
          <tbody>
            {isLoading ? (
              <tr>
                <td colSpan={6} style={{ textAlign: 'center', padding: '40px' }}>
                  <div style={{ display: 'inline-flex', alignItems: 'center', gap: '8px', color: 'var(--color-text-muted)' }}>
                    <RefreshCw size={18} className="spin-icon" />
                    <span>Đang tải nhật ký lỗi...</span>
                  </div>
                </td>
              </tr>
            ) : logs.length === 0 ? (
              <tr>
                <td colSpan={6} style={{ textAlign: 'center', padding: '40px', color: 'var(--color-text-muted)' }}>
                  Không phát hiện bản ghi sự cố nào trong khoảng thời gian đã chọn.
                </td>
              </tr>
            ) : (
              logs.map((log) => (
                <tr key={log.id}>
                  <td>
                    <span className="admin-time-text">
                      {log.timestamp ? new Date(log.timestamp).toLocaleTimeString('vi-VN') : '-'}
                    </span>
                  </td>
                  <td>
                    <code className="admin-request-id" title={log.request_id}>
                      {log.request_id ? (log.request_id.length > 16 ? log.request_id.slice(0, 16) + '...' : log.request_id) : 'N/A'}
                    </code>
                  </td>
                  <td>
                    <span style={{ fontSize: '0.78rem', textTransform: 'uppercase', color: 'var(--color-text-muted)' }}>
                      {log.source === 'rag_query' ? 'Hỏi đáp RAG' : 'Tác vụ Worker'}
                    </span>
                  </td>
                  <td>
                    <span className="admin-status-badge badge-danger" style={{ fontSize: '0.72rem' }}>
                      {log.error_code}
                    </span>
                  </td>
                  <td style={{ maxWidth: '320px', fontSize: '0.82rem' }}>
                    <span title={log.message}>{log.message}</span>
                  </td>
                  <td>
                    {log.question_hash ? (
                      <code style={{ fontSize: '0.72rem', color: 'var(--color-text-muted)' }} title={`SHA-256: ${log.question_hash}`}>
                        {log.question_hash.slice(0, 12)}... ({log.question_length} ký tự)
                      </code>
                    ) : (
                      <span style={{ fontSize: '0.75rem', color: 'var(--color-text-muted)' }}>-</span>
                    )}
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
};
