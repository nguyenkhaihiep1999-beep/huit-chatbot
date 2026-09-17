import React, { useState, useEffect, useCallback } from 'react';
import {
  Layers,
  RotateCcw,
  Ban,
  Eye,
  RefreshCw,
  CheckCircle2,
  Clock,
  AlertTriangle,
  XCircle,
  X,
  Calendar,
  Filter,
} from 'lucide-react';
import { AdminJobItem, JobEventItem } from '../types/admin.types';
import { useAdminOps } from '../hooks/useAdminOps';
import { ConfirmActionModal } from './ConfirmActionModal';

export const AdminJobsPanel: React.FC = () => {
  const { fetchAdminJobs, fetchAdminJobDetail, retryAdminJob, cancelAdminJob } = useAdminOps();
  const [jobs, setJobs] = useState<AdminJobItem[]>([]);
  const [total, setTotal] = useState<number>(0);
  const [page, setPage] = useState<number>(1);
  const [totalPages, setTotalPages] = useState<number>(1);
  const [limit] = useState<number>(15);

  // Filters
  const [statusFilter, setStatusFilter] = useState<string>('all');
  const [actionFilter, setActionFilter] = useState<string>('all');
  const [timeRange, setTimeRange] = useState<string>('all');

  // Loading & Error states
  const [isLoading, setIsLoading] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);

  // Detail Modal state
  const [selectedJobId, setSelectedJobId] = useState<string | null>(null);
  const [jobDetail, setJobDetail] = useState<AdminJobItem | null>(null);
  const [jobEvents, setJobEvents] = useState<JobEventItem[]>([]);
  const [isLoadingDetail, setIsLoadingDetail] = useState<boolean>(false);

  // Action confirmation states
  const [retryTargetJob, setRetryTargetJob] = useState<AdminJobItem | null>(null);
  const [cancelTargetJob, setCancelTargetJob] = useState<AdminJobItem | null>(null);
  const [isPerformingAction, setIsPerformingAction] = useState<boolean>(false);
  const [actionFeedback, setActionFeedback] = useState<{ type: 'success' | 'error'; message: string } | null>(null);

  const loadJobs = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const data = await fetchAdminJobs({
        page,
        limit,
        status: statusFilter,
        action: actionFilter,
        timeRange,
      });
      setJobs(data.jobs || []);
      setTotal(data.total || 0);
      setTotalPages(data.total_pages || 1);
    } catch (err: any) {
      setError(err.message || 'Không thể tải danh sách tác vụ');
    } finally {
      setIsLoading(false);
    }
  }, [actionFilter, fetchAdminJobs, limit, page, statusFilter, timeRange]);

  useEffect(() => {
    const initialTimer = window.setTimeout(() => {
      void loadJobs();
    }, 0);
    return () => window.clearTimeout(initialTimer);
  }, [loadJobs]);

  const handleOpenDetail = async (jobId: string) => {
    setSelectedJobId(jobId);
    setIsLoadingDetail(true);
    try {
      const data = await fetchAdminJobDetail(jobId);
      setJobDetail(data.job);
      setJobEvents(data.events || []);
    } catch (err: any) {
      setError(err.message || 'Không thể tải chi tiết công việc');
    } finally {
      setIsLoadingDetail(false);
    }
  };

  const handleConfirmRetry = async () => {
    if (!retryTargetJob) return;
    setIsPerformingAction(true);
    try {
      const res = await retryAdminJob(retryTargetJob.job_id, 'Admin manual retry');
      setActionFeedback({ type: 'success', message: res.message });
      setRetryTargetJob(null);
      await loadJobs();
    } catch (err: any) {
      setActionFeedback({ type: 'error', message: err.message || 'Lỗi khi thử lại tác vụ' });
    } finally {
      setIsPerformingAction(false);
    }
  };

  const handleConfirmCancel = async () => {
    if (!cancelTargetJob) return;
    setIsPerformingAction(true);
    try {
      const res = await cancelAdminJob(cancelTargetJob.job_id, 'Admin manual cancellation');
      setActionFeedback({ type: 'success', message: res.message });
      setCancelTargetJob(null);
      await loadJobs();
    } catch (err: any) {
      setActionFeedback({ type: 'error', message: err.message || 'Lỗi khi hủy tác vụ' });
    } finally {
      setIsPerformingAction(false);
    }
  };

  const renderStatusBadge = (status: string) => {
    switch (status) {
      case 'completed':
        return (
          <span className="admin-status-badge badge-healthy">
            <CheckCircle2 size={12} aria-hidden="true" /> Hoàn tất
          </span>
        );
      case 'processing':
        return (
          <span className="admin-status-badge badge-warning">
            <RefreshCw size={12} className="spin-icon" aria-hidden="true" /> Đang chạy
          </span>
        );
      case 'queued':
        return (
          <span className="admin-status-badge badge-neutral">
            <Clock size={12} aria-hidden="true" /> Đang chờ
          </span>
        );
      case 'failed':
        return (
          <span className="admin-status-badge badge-danger">
            <XCircle size={12} aria-hidden="true" /> Thất bại
          </span>
        );
      case 'cancelled':
        return (
          <span className="admin-status-badge" style={{ background: 'var(--color-surface-hover)', color: 'var(--color-text-muted)' }}>
            <Ban size={12} aria-hidden="true" /> Đã hủy
          </span>
        );
      default:
        return <span className="admin-status-badge badge-neutral">{status}</span>;
    }
  };

  return (
    <div className="admin-jobs-panel">
      {/* Action Notification Banner */}
      {actionFeedback && (
        <div
          role="alert"
          style={{
            padding: '10px 16px',
            marginBottom: '16px',
            borderRadius: '8px',
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
            background: actionFeedback.type === 'success' ? 'rgba(34, 197, 94, 0.1)' : 'rgba(239, 68, 68, 0.1)',
            border: `1px solid ${actionFeedback.type === 'success' ? '#22c55e' : '#ef4444'}`,
            color: actionFeedback.type === 'success' ? '#16a34a' : '#dc2626',
            fontSize: '0.88rem',
          }}
        >
          <span>{actionFeedback.message}</span>
          <button
            type="button"
            onClick={() => setActionFeedback(null)}
            style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'inherit' }}
            aria-label="Đóng thông báo"
          >
            <X size={16} />
          </button>
        </div>
      )}

      {/* Filter Toolbar */}
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
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: '12px', alignItems: 'center' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
            <Filter size={15} color="var(--color-text-muted)" aria-hidden="true" />
            <label htmlFor="filter-status" style={{ fontSize: '0.85rem', fontWeight: 500 }}>
              Trạng thái:
            </label>
            <select
              id="filter-status"
              value={statusFilter}
              onChange={(e) => {
                setStatusFilter(e.target.value);
                setPage(1);
              }}
              className="admin-filter-select"
              style={{ padding: '6px 10px', borderRadius: '6px', border: '1px solid var(--color-border)' }}
            >
              <option value="all">Tất cả</option>
              <option value="queued">Đang chờ (Queued)</option>
              <option value="processing">Đang chạy (Processing)</option>
              <option value="completed">Hoàn tất (Completed)</option>
              <option value="failed">Thất bại (Failed)</option>
              <option value="cancelled">Đã hủy (Cancelled)</option>
            </select>
          </div>

          <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
            <label htmlFor="filter-action" style={{ fontSize: '0.85rem', fontWeight: 500 }}>
              Hành động:
            </label>
            <select
              id="filter-action"
              value={actionFilter}
              onChange={(e) => {
                setActionFilter(e.target.value);
                setPage(1);
              }}
              className="admin-filter-select"
              style={{ padding: '6px 10px', borderRadius: '6px', border: '1px solid var(--color-border)' }}
            >
              <option value="all">Tất cả</option>
              <option value="render">Dựng tài liệu (render)</option>
              <option value="export">Xuất định dạng (export)</option>
              <option value="upscale">Phóng to ảnh (upscale)</option>
            </select>
          </div>

          <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
            <Calendar size={15} color="var(--color-text-muted)" aria-hidden="true" />
            <label htmlFor="filter-timerange" style={{ fontSize: '0.85rem', fontWeight: 500 }}>
              Thời gian:
            </label>
            <select
              id="filter-timerange"
              value={timeRange}
              onChange={(e) => {
                setTimeRange(e.target.value);
                setPage(1);
              }}
              className="admin-filter-select"
              style={{ padding: '6px 10px', borderRadius: '6px', border: '1px solid var(--color-border)' }}
            >
              <option value="all">Tất cả</option>
              <option value="1h">1 giờ qua</option>
              <option value="24h">24 giờ qua</option>
              <option value="7d">7 ngày qua</option>
            </select>
          </div>
        </div>

        <button
          type="button"
          onClick={() => loadJobs()}
          disabled={isLoading}
          className="admin-action-btn btn-secondary"
          style={{
            display: 'inline-flex',
            alignItems: 'center',
            gap: '6px',
            padding: '6px 12px',
            borderRadius: '6px',
            border: '1px solid var(--color-border)',
            cursor: 'pointer',
          }}
          aria-label="Tải lại danh sách tác vụ"
        >
          <RefreshCw size={14} className={isLoading ? 'spin-icon' : ''} aria-hidden="true" />
          <span>Làm mới</span>
        </button>
      </div>

      {/* Error state */}
      {error && (
        <div className="admin-error-box" role="alert" style={{ marginBottom: '16px' }}>
          <AlertTriangle size={18} aria-hidden="true" />
          <span>{error}</span>
          <button type="button" onClick={() => loadJobs()} className="admin-retry-btn">
            Thử lại
          </button>
        </div>
      )}

      {/* Jobs Table */}
      <div className="admin-table-wrapper" style={{ overflowX: 'auto', background: 'var(--color-surface)', borderRadius: '10px', border: '1px solid var(--color-border)' }}>
        <table className="admin-events-table" style={{ width: '100%', borderCollapse: 'collapse' }}>
          <thead>
            <tr>
              <th scope="col">Job ID</th>
              <th scope="col">Hành động</th>
              <th scope="col">Trạng thái</th>
              <th scope="col">Tiến độ</th>
              <th scope="col">Worker</th>
              <th scope="col">Khởi tạo</th>
              <th scope="col" style={{ textAlign: 'right' }}>Thao tác</th>
            </tr>
          </thead>
          <tbody>
            {isLoading ? (
              <tr>
                <td colSpan={7} style={{ textAlign: 'center', padding: '40px' }}>
                  <div style={{ display: 'inline-flex', alignItems: 'center', gap: '8px', color: 'var(--color-text-muted)' }}>
                    <RefreshCw size={18} className="spin-icon" aria-hidden="true" />
                    <span>Đang tải danh sách tác vụ...</span>
                  </div>
                </td>
              </tr>
            ) : jobs.length === 0 ? (
              <tr>
                <td colSpan={7} style={{ textAlign: 'center', padding: '40px', color: 'var(--color-text-muted)' }}>
                  Không tìm thấy tác vụ nào phù hợp với bộ lọc hiện tại.
                </td>
              </tr>
            ) : (
              jobs.map((job) => (
                <tr key={job.job_id}>
                  <td>
                    <code className="admin-request-id" title={job.job_id}>
                      {job.job_id.length > 24 ? job.job_id.slice(0, 24) + '...' : job.job_id}
                    </code>
                  </td>
                  <td>
                    <span className="admin-intent-tag" style={{ textTransform: 'uppercase', fontSize: '0.75rem' }}>
                      {job.action} {job.format ? `(${job.format})` : ''} {job.scale ? `${job.scale}x` : ''}
                    </span>
                  </td>
                  <td>{renderStatusBadge(job.status)}</td>
                  <td style={{ minWidth: '120px' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                      <div
                        style={{
                          flex: 1,
                          height: '6px',
                          background: 'var(--color-border)',
                          borderRadius: '3px',
                          overflow: 'hidden',
                        }}
                      >
                        <div
                          style={{
                            width: `${job.progress}%`,
                            height: '100%',
                            background: job.status === 'failed' ? 'var(--color-danger, #ef4444)' : 'var(--color-primary)',
                            borderRadius: '3px',
                            transition: 'width 0.3s ease',
                          }}
                        />
                      </div>
                      <span style={{ fontSize: '0.75rem', minWidth: '32px', color: 'var(--color-text-muted)' }}>
                        {job.progress}%
                      </span>
                    </div>
                  </td>
                  <td>
                    <span style={{ fontSize: '0.8rem', color: job.lease_owner ? 'inherit' : 'var(--color-text-muted)' }}>
                      {job.lease_owner || 'Chưa gán'}
                    </span>
                  </td>
                  <td>
                    <span className="admin-time-text">
                      {job.created_at ? new Date(job.created_at).toLocaleTimeString('vi-VN') : '-'}
                    </span>
                  </td>
                  <td style={{ textAlign: 'right' }}>
                    <div style={{ display: 'inline-flex', gap: '6px' }}>
                      <button
                        type="button"
                        onClick={() => handleOpenDetail(job.job_id)}
                        className="admin-action-btn btn-secondary"
                        title="Xem dòng thời gian sự kiện"
                        aria-label={`Xem chi tiết tác vụ ${job.job_id}`}
                        style={{ padding: '4px 8px', fontSize: '0.78rem', borderRadius: '4px' }}
                      >
                        <Eye size={13} aria-hidden="true" />
                        <span>Chi tiết</span>
                      </button>

                      {job.status === 'failed' && (
                        <button
                          type="button"
                          onClick={() => setRetryTargetJob(job)}
                          className="admin-action-btn btn-secondary"
                          title="Đưa vào hàng đợi thử lại"
                          aria-label={`Thử lại tác vụ ${job.job_id}`}
                          style={{ padding: '4px 8px', fontSize: '0.78rem', borderRadius: '4px', color: 'var(--color-primary)' }}
                        >
                          <RotateCcw size={13} aria-hidden="true" />
                          <span>Thử lại</span>
                        </button>
                      )}

                      {(job.status === 'queued' || job.status === 'processing') && (
                        <button
                          type="button"
                          onClick={() => setCancelTargetJob(job)}
                          className="admin-action-btn btn-secondary"
                          title="Hủy bỏ tác vụ này"
                          aria-label={`Hủy tác vụ ${job.job_id}`}
                          style={{ padding: '4px 8px', fontSize: '0.78rem', borderRadius: '4px', color: 'var(--color-danger, #ef4444)' }}
                        >
                          <Ban size={13} aria-hidden="true" />
                          <span>Hủy</span>
                        </button>
                      )}
                    </div>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      {/* Pagination Footer */}
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          marginTop: '16px',
          fontSize: '0.85rem',
          color: 'var(--color-text-muted)',
        }}
      >
        <span>
          Tổng số: <strong>{total}</strong> tác vụ
        </span>
        <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
          <button
            type="button"
            onClick={() => setPage((p) => Math.max(1, p - 1))}
            disabled={page <= 1 || isLoading}
            className="admin-action-btn btn-secondary"
            style={{ padding: '4px 10px', borderRadius: '4px' }}
          >
            Trang trước
          </button>
          <span>
            Trang <strong>{page}</strong> / {totalPages}
          </span>
          <button
            type="button"
            onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
            disabled={page >= totalPages || isLoading}
            className="admin-action-btn btn-secondary"
            style={{ padding: '4px 10px', borderRadius: '4px' }}
          >
            Trang sau
          </button>
        </div>
      </div>

      {/* Job Detail & Timeline Modal */}
      {selectedJobId && (
        <div
          className="admin-modal-backdrop"
          role="dialog"
          aria-modal="true"
          aria-labelledby="job-detail-modal-title"
          onClick={(e) => {
            if (e.target === e.currentTarget) setSelectedJobId(null);
          }}
        >
          <div className="admin-modal-card" style={{ maxWidth: '650px', width: '90%' }}>
            <div className="admin-modal-header">
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                <Layers size={20} color="var(--color-primary)" aria-hidden="true" />
                <h3 id="job-detail-modal-title" style={{ margin: 0, fontSize: '1.1rem' }}>
                  Chi tiết tác vụ: <code>{selectedJobId.slice(0, 16)}...</code>
                </h3>
              </div>
              <button
                type="button"
                onClick={() => setSelectedJobId(null)}
                style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'var(--color-text-muted)' }}
                aria-label="Đóng hộp thoại chi tiết"
              >
                <X size={18} />
              </button>
            </div>

            <div className="admin-modal-body" style={{ maxHeight: '60vh', overflowY: 'auto', padding: '16px 0' }}>
              {isLoadingDetail ? (
                <div style={{ textAlign: 'center', padding: '30px', color: 'var(--color-text-muted)' }}>
                  <RefreshCw size={20} className="spin-icon" aria-hidden="true" />
                  <p>Đang tải chi tiết dòng thời gian...</p>
                </div>
              ) : jobDetail ? (
                <div>
                  <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: '10px', marginBottom: '16px', background: 'var(--color-surface-hover)', padding: '12px', borderRadius: '8px', fontSize: '0.85rem' }}>
                    <div><strong>Hành động:</strong> {jobDetail.action}</div>
                    <div><strong>Định dạng / Scale:</strong> {jobDetail.format || (jobDetail.scale ? `${jobDetail.scale}x` : 'N/A')}</div>
                    <div><strong>Trạng thái:</strong> {renderStatusBadge(jobDetail.status)}</div>
                    <div><strong>Tiến độ:</strong> {jobDetail.progress}%</div>
                    <div><strong>Số lần thử (Attempt):</strong> {jobDetail.attempt} / {jobDetail.max_attempts}</div>
                    <div><strong>Worker phụ trách:</strong> {jobDetail.lease_owner || 'Chưa gán'}</div>
                  </div>

                  {jobDetail.sanitized_error && (
                    <div style={{ marginBottom: '16px', padding: '10px 14px', borderRadius: '6px', background: 'rgba(239, 68, 68, 0.1)', border: '1px solid #ef4444', color: '#dc2626', fontSize: '0.85rem' }}>
                      <strong>Thông điệp lỗi đã khử khuẩn:</strong>
                      <p style={{ margin: '4px 0 0' }}>{jobDetail.sanitized_error}</p>
                    </div>
                  )}

                  <h4 style={{ margin: '16px 0 8px', fontSize: '0.95rem', fontWeight: 600 }}>Dòng thời gian sự kiện (Event Timeline)</h4>
                  {jobEvents.length === 0 ? (
                    <p style={{ fontSize: '0.85rem', color: 'var(--color-text-muted)' }}>Chưa có sự kiện nào được ghi nhận.</p>
                  ) : (
                    <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                      {jobEvents.map((evt, idx) => (
                        <div
                          key={idx}
                          style={{
                            display: 'flex',
                            gap: '12px',
                            padding: '8px 12px',
                            borderRadius: '6px',
                            background: 'var(--color-surface)',
                            border: '1px solid var(--color-border)',
                            fontSize: '0.82rem',
                          }}
                        >
                          <span style={{ color: 'var(--color-text-muted)', minWidth: '65px' }}>
                            {evt.timestamp ? new Date(evt.timestamp).toLocaleTimeString('vi-VN') : 'Vừa xong'}
                          </span>
                          <div style={{ flex: 1 }}>
                            <strong>[{evt.status}]</strong> {evt.detail}
                          </div>
                          <span style={{ color: 'var(--color-primary)', fontWeight: 600 }}>
                            {evt.progress}%
                          </span>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              ) : null}
            </div>

            <div style={{ display: 'flex', justifyContent: 'flex-end', paddingTop: '12px', borderTop: '1px solid var(--color-border)' }}>
              <button
                type="button"
                onClick={() => setSelectedJobId(null)}
                className="admin-action-btn btn-secondary"
                style={{ padding: '6px 14px', borderRadius: '6px' }}
              >
                Đóng
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Confirmation Modal: Retry Job */}
      <ConfirmActionModal
        isOpen={Boolean(retryTargetJob)}
        title="Xác nhận thử lại tác vụ?"
        message={`Bạn có chắc chắn muốn đưa tác vụ ${retryTargetJob?.job_id} về trạng thái đang chờ (queued) để Worker xử lý lại không? Thao tác này sẽ ghi nhận vào nhật ký kiểm toán (audit log).`}
        confirmLabel="Thử lại ngay"
        cancelLabel="Hủy bỏ"
        isDanger={false}
        isLoading={isPerformingAction}
        onConfirm={handleConfirmRetry}
        onCancel={() => setRetryTargetJob(null)}
      />

      {/* Confirmation Modal: Cancel Job */}
      <ConfirmActionModal
        isOpen={Boolean(cancelTargetJob)}
        title="Xác nhận hủy tác vụ?"
        message={`Bạn có chắc chắn muốn hủy tác vụ ${cancelTargetJob?.job_id}? Worker sẽ lập tức dừng xử lý và giải phóng tài nguyên. Hành động này không thể hoàn tác.`}
        confirmLabel="Đồng ý hủy"
        cancelLabel="Đóng"
        isDanger={true}
        isLoading={isPerformingAction}
        onConfirm={handleConfirmCancel}
        onCancel={() => setCancelTargetJob(null)}
      />
    </div>
  );
};
