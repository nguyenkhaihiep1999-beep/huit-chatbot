import React, { useState } from 'react';
import {
  RefreshCw,
  LogOut,
  ArrowLeft,
  Database,
  Cpu,
  BookOpen,
  Server,
  HardDrive,
  Trash2,
  CheckCircle2,
  AlertTriangle,
  XCircle,
  Clock,
  Layers,
  Zap,
  Activity,
  FileText,
} from 'lucide-react';
import { SystemHealthData, AdminMetricsData, ClearCacheResult } from '../types/admin.types';
import { AdminJobsPanel } from './AdminJobsPanel';
import { AdminWorkersPanel } from './AdminWorkersPanel';
import { AdminErrorLogsPanel } from './AdminErrorLogsPanel';
import { AdminSystemHealthPanel } from './AdminSystemHealthPanel';
import { ConfirmActionModal } from './ConfirmActionModal';

export type AdminTab = 'overview' | 'jobs' | 'workers' | 'logs' | 'system';

export interface AdminDashboardProps {
  health: SystemHealthData | null;
  metrics: AdminMetricsData | null;
  isLoading: boolean;
  error: string | null;
  isClearingCache: boolean;
  clearCacheResult: ClearCacheResult | null;
  onRefresh: () => Promise<void>;
  onClearCache: () => Promise<void>;
  onDismissCacheResult: () => void;
  onLogout: () => Promise<void>;
  onBackToChat: () => void;
}

export const AdminDashboard: React.FC<AdminDashboardProps> = ({
  health,
  metrics,
  isLoading,
  error,
  isClearingCache,
  clearCacheResult,
  onRefresh,
  onClearCache,
  onDismissCacheResult,
  onLogout,
  onBackToChat,
}) => {
  const [activeTab, setActiveTab] = useState<AdminTab>('overview');
  const [showClearConfirm, setShowClearConfirm] = useState(false);

  // Tính toán chỉ số phái sinh an toàn
  const totalEvents = metrics?.total_events || 0;
  const totalCached = metrics?.total_cached_queries || 0;
  const cacheHitRate = totalEvents > 0 ? ((totalCached / totalEvents) * 100).toFixed(1) : '0';

  const recentEvents = metrics?.recent_events || [];
  const errorCount = recentEvents.filter((e) => e.status && e.status.toLowerCase().includes('lỗi')).length;
  const errorRate = recentEvents.length > 0 ? ((errorCount / recentEvents.length) * 100).toFixed(1) : '0';

  const renderStatusBadge = (status?: string) => {
    switch (status) {
      case 'healthy':
      case 'ready':
        return (
          <span className="admin-status-badge badge-healthy">
            <CheckCircle2 size={13} aria-hidden="true" />
            <span>Khỏe mạnh</span>
          </span>
        );
      case 'degraded':
      case 'warning':
        return (
          <span className="admin-status-badge badge-warning">
            <AlertTriangle size={13} aria-hidden="true" />
            <span>Cảnh báo</span>
          </span>
        );
      case 'unhealthy':
      case 'error':
        return (
          <span className="admin-status-badge badge-danger">
            <XCircle size={13} aria-hidden="true" />
            <span>Lỗi</span>
          </span>
        );
      default:
        return (
          <span className="admin-status-badge badge-neutral">
            <Clock size={13} aria-hidden="true" />
            <span>Chờ kiểm tra</span>
          </span>
        );
    }
  };

  return (
    <div className="admin-dashboard-container">
      {/* Admin Top Navigation */}
      <header className="admin-topbar">
        <div className="admin-topbar-left">
          <button
            type="button"
            onClick={onBackToChat}
            className="admin-action-btn btn-secondary"
            aria-label="Quay lại giao diện trò chuyện sinh viên"
          >
            <ArrowLeft size={16} aria-hidden="true" />
            <span>Về Chat HUIT</span>
          </button>
          <div className="admin-topbar-title">
            <div className="admin-logo-badge" aria-hidden="true">
              <img src="/huit-ai-mark.svg" alt="" width={28} height={28} />
            </div>
            <h2>Bảng Điều Khiển Quản Trị Hệ Thống HUIT AI</h2>
          </div>
        </div>

        <div className="admin-topbar-actions">
          <button
            type="button"
            onClick={() => onRefresh()}
            className="admin-action-btn btn-outline"
            disabled={isLoading}
            aria-label="Làm mới toàn bộ chỉ số hệ thống"
          >
            <RefreshCw size={15} className={isLoading ? 'spinner-rotate' : ''} aria-hidden="true" />
            <span>{isLoading ? 'Đang tải...' : 'Làm mới'}</span>
          </button>

          <button
            type="button"
            onClick={() => onLogout()}
            className="admin-action-btn btn-danger-outline"
            aria-label="Đăng xuất khỏi phiên quản trị"
          >
            <LogOut size={15} aria-hidden="true" />
            <span>Đăng xuất</span>
          </button>
        </div>
      </header>

      {/* Tab Navigation */}
      <nav
        className="admin-nav-tabs"
        role="tablist"
        aria-label="Các phân hệ quản trị"
        style={{
          display: 'flex',
          gap: '8px',
          borderBottom: '1px solid var(--color-border)',
          padding: '0 24px',
          background: 'var(--color-surface)',
          overflowX: 'auto',
        }}
      >
        <button
          type="button"
          role="tab"
          id="tab-overview"
          aria-selected={activeTab === 'overview'}
          aria-controls="panel-overview"
          onClick={() => setActiveTab('overview')}
          className={`admin-tab-btn ${activeTab === 'overview' ? 'active' : ''}`}
          style={{
            display: 'inline-flex',
            alignItems: 'center',
            gap: '8px',
            padding: '12px 16px',
            background: 'none',
            border: 'none',
            borderBottom: activeTab === 'overview' ? '2px solid var(--color-primary)' : '2px solid transparent',
            color: activeTab === 'overview' ? 'var(--color-primary)' : 'var(--color-text-secondary)',
            fontWeight: activeTab === 'overview' ? 600 : 500,
            cursor: 'pointer',
            fontSize: '0.9rem',
          }}
        >
          <Activity size={16} aria-hidden="true" />
          <span>Tổng quan & Sức khỏe</span>
        </button>

        <button
          type="button"
          role="tab"
          id="tab-jobs"
          aria-selected={activeTab === 'jobs'}
          aria-controls="panel-jobs"
          onClick={() => setActiveTab('jobs')}
          className={`admin-tab-btn ${activeTab === 'jobs' ? 'active' : ''}`}
          style={{
            display: 'inline-flex',
            alignItems: 'center',
            gap: '8px',
            padding: '12px 16px',
            background: 'none',
            border: 'none',
            borderBottom: activeTab === 'jobs' ? '2px solid var(--color-primary)' : '2px solid transparent',
            color: activeTab === 'jobs' ? 'var(--color-primary)' : 'var(--color-text-secondary)',
            fontWeight: activeTab === 'jobs' ? 600 : 500,
            cursor: 'pointer',
            fontSize: '0.9rem',
          }}
        >
          <Layers size={16} aria-hidden="true" />
          <span>Hàng đợi Jobs</span>
        </button>

        <button
          type="button"
          role="tab"
          id="tab-workers"
          aria-selected={activeTab === 'workers'}
          aria-controls="panel-workers"
          onClick={() => setActiveTab('workers')}
          className={`admin-tab-btn ${activeTab === 'workers' ? 'active' : ''}`}
          style={{
            display: 'inline-flex',
            alignItems: 'center',
            gap: '8px',
            padding: '12px 16px',
            background: 'none',
            border: 'none',
            borderBottom: activeTab === 'workers' ? '2px solid var(--color-primary)' : '2px solid transparent',
            color: activeTab === 'workers' ? 'var(--color-primary)' : 'var(--color-text-secondary)',
            fontWeight: activeTab === 'workers' ? 600 : 500,
            cursor: 'pointer',
            fontSize: '0.9rem',
          }}
        >
          <Cpu size={16} aria-hidden="true" />
          <span>Tiến trình Worker</span>
        </button>

        <button
          type="button"
          role="tab"
          id="tab-logs"
          aria-selected={activeTab === 'logs'}
          aria-controls="panel-logs"
          onClick={() => setActiveTab('logs')}
          className={`admin-tab-btn ${activeTab === 'logs' ? 'active' : ''}`}
          style={{
            display: 'inline-flex',
            alignItems: 'center',
            gap: '8px',
            padding: '12px 16px',
            background: 'none',
            border: 'none',
            borderBottom: activeTab === 'logs' ? '2px solid var(--color-primary)' : '2px solid transparent',
            color: activeTab === 'logs' ? 'var(--color-primary)' : 'var(--color-text-secondary)',
            fontWeight: activeTab === 'logs' ? 600 : 500,
            cursor: 'pointer',
            fontSize: '0.9rem',
          }}
        >
          <FileText size={16} aria-hidden="true" />
          <span>Nhật ký lỗi (Sanitized)</span>
        </button>

        <button
          type="button"
          role="tab"
          id="tab-system"
          aria-selected={activeTab === 'system'}
          aria-controls="panel-system"
          onClick={() => setActiveTab('system')}
          className={`admin-tab-btn ${activeTab === 'system' ? 'active' : ''}`}
          style={{
            display: 'inline-flex',
            alignItems: 'center',
            gap: '8px',
            padding: '12px 16px',
            background: 'none',
            border: 'none',
            borderBottom: activeTab === 'system' ? '2px solid var(--color-primary)' : '2px solid transparent',
            color: activeTab === 'system' ? 'var(--color-primary)' : 'var(--color-text-secondary)',
            fontWeight: activeTab === 'system' ? 600 : 500,
            cursor: 'pointer',
            fontSize: '0.9rem',
          }}
        >
          <Database size={16} aria-hidden="true" />
          <span>Hệ thống & Sao lưu</span>
        </button>
      </nav>

      {/* Main Content Body */}
      <main className="admin-content" style={{ padding: '24px' }}>
        {/* Banner lỗi nếu có */}
        {error && (
          <div className="admin-alert-banner alert-error" role="alert">
            <AlertTriangle size={18} aria-hidden="true" />
            <div className="alert-content">
              <strong>Lỗi tải dữ liệu quản trị:</strong> {error}
            </div>
            <button
              type="button"
              onClick={() => onRefresh()}
              className="admin-action-btn btn-secondary btn-sm"
            >
              Thử lại
            </button>
          </div>
        )}

        {/* Kết quả xóa Cache nếu có */}
        {clearCacheResult && (
          <div
            className={`admin-alert-banner ${clearCacheResult.success ? 'alert-success' : 'alert-error'}`}
            role="status"
          >
            {clearCacheResult.success ? (
              <CheckCircle2 size={18} aria-hidden="true" />
            ) : (
              <AlertTriangle size={18} aria-hidden="true" />
            )}
            <div className="alert-content">
              <strong>{clearCacheResult.message}</strong>
              {clearCacheResult.details && (
                <span className="alert-details">
                  (Đã giải phóng bộ nhớ RAM & làm mới collection MongoDB)
                </span>
              )}
            </div>
            <button
              type="button"
              onClick={onDismissCacheResult}
              className="alert-dismiss-btn"
              aria-label="Đóng thông báo"
            >
              ✕
            </button>
          </div>
        )}

        {/* TAB 1: TỔNG QUAN & SỨC KHỎE */}
        {activeTab === 'overview' && (
          <div id="panel-overview" role="tabpanel" aria-labelledby="tab-overview">
            {/* Thống kê Tổng quan (KPI Grid) */}
            <section className="admin-stats-grid" aria-label="Các chỉ số hiệu năng">
              <div className="admin-stat-card">
                <div className="stat-card-header">
                  <span className="stat-card-title">Tổng Lượt Truy Vấn</span>
                  <div className="stat-card-icon icon-blue" aria-hidden="true">
                    <Activity size={18} />
                  </div>
                </div>
                <div className="stat-card-value">{totalEvents.toLocaleString('vi-VN')}</div>
                <div className="stat-card-footer">
                  <span className="stat-card-trend">Dữ liệu từ rag_events</span>
                </div>
              </div>

              <div className="admin-stat-card">
                <div className="stat-card-header">
                  <span className="stat-card-title">Truy vấn đã Cache</span>
                  <div className="stat-card-icon icon-emerald" aria-hidden="true">
                    <Zap size={18} />
                  </div>
                </div>
                <div className="stat-card-value">{totalCached.toLocaleString('vi-VN')}</div>
                <div className="stat-card-footer">
                  <span className="stat-card-trend trend-positive">
                    Tỷ lệ phản hồi nhanh: <span>{cacheHitRate}%</span>
                  </span>
                </div>
              </div>

              <div className="admin-stat-card">
                <div className="stat-card-header">
                  <span className="stat-card-title">Knowledge Base (Tri Thức Tuyển Sinh)</span>
                  <div className="stat-card-icon icon-violet" aria-hidden="true">
                    <BookOpen size={18} />
                  </div>
                </div>
                <div className="stat-card-value">
                  {(metrics?.total_kb_documents || 0).toLocaleString('vi-VN')}
                </div>
                <div className="stat-card-footer">
                  <span className="stat-card-trend">Chương trình & Quy chế HUIT</span>
                </div>
              </div>

              <div className="admin-stat-card">
                <div className="stat-card-header">
                  <span className="stat-card-title">Tỷ lệ Lỗi Stream</span>
                  <div className="stat-card-icon icon-amber" aria-hidden="true">
                    <AlertTriangle size={18} />
                  </div>
                </div>
                <div className="stat-card-value">{errorRate}%</div>
                <div className="stat-card-footer">
                  <span className="stat-card-trend">
                    {errorCount} lỗi / {recentEvents.length} phiên gần nhất
                  </span>
                </div>
              </div>
            </section>

            {/* Trạng thái Sức khỏe Thành phần & Quản trị Bộ nhớ */}
            <div className="admin-middle-row">
              {/* Card Trạng thái Sức khỏe Thành phần */}
              <section className="admin-panel-card" aria-labelledby="components-health-title">
                <div className="panel-card-header">
                  <div className="panel-card-title-group">
                    <Server size={18} className="panel-icon" aria-hidden="true" />
                    <h3 id="components-health-title">Trạng Thái Sức Khỏe Thành Phần</h3>
                  </div>
                  {renderStatusBadge(health?.status)}
                </div>

                <div className="component-health-list">
                  {/* MongoDB Atlas */}
                  <div className="component-health-item">
                    <div className="component-info">
                      <Database size={16} className="component-icon" aria-hidden="true" />
                      <div>
                        <div className="component-name">MongoDB Cơ Sở Dữ Liệu</div>
                        <div className="component-sub">
                          {health?.components?.mongodb?.database
                            ? `DB: ${health.components.mongodb.database}`
                            : 'Cơ sở dữ liệu chính'}
                        </div>
                      </div>
                    </div>
                    <div className="component-status">
                      {(health?.components?.mongodb?.latency_ms !== undefined || health?.components?.mongodb?.ping_ms !== undefined) && (
                        <span className="component-latency">
                          {health.components.mongodb.latency_ms ?? health.components.mongodb.ping_ms} ms
                        </span>
                      )}
                      {renderStatusBadge(health?.components?.mongodb?.status)}
                    </div>
                  </div>

                  {/* Redis Memory Cache */}
                  <div className="component-health-item">
                    <div className="component-info">
                      <Zap size={16} className="component-icon" aria-hidden="true" />
                      <div>
                        <div className="component-name">Redis In-Memory Cache</div>
                        <div className="component-sub">Lưu trữ session & TTL rate-limiting</div>
                      </div>
                    </div>
                    <div className="component-status">
                      {(health?.components?.redis?.latency_ms !== undefined || health?.components?.redis?.ping_ms !== undefined) && (
                        <span className="component-latency">
                          {health.components.redis.latency_ms ?? health.components.redis.ping_ms} ms
                        </span>
                      )}
                      {renderStatusBadge(health?.components?.redis?.status)}
                    </div>
                  </div>

                  {/* Durable Job Queue */}
                  <div className="component-health-item">
                    <div className="component-info">
                      <Layers size={16} className="component-icon" aria-hidden="true" />
                      <div>
                        <div className="component-name">Hàng Đợi Xử Lý (Queue & Jobs)</div>
                        <div className="component-sub">
                          {health?.components?.job_queue?.queued_jobs !== undefined
                            ? `${health.components.job_queue.queued_jobs} job đang chờ, ${health.components.job_queue.stuck_jobs || 0} bị kẹt`
                            : 'Tác vụ nặng & xuất file'}
                        </div>
                      </div>
                    </div>
                    <div className="component-status">
                      {renderStatusBadge(health?.components?.job_queue?.status)}
                    </div>
                  </div>

                  {/* Storage Adapter */}
                  <div className="component-health-item">
                    <div className="component-info">
                      <HardDrive size={16} className="component-icon" aria-hidden="true" />
                      <div>
                        <div className="component-name">Lưu Trữ Tệp (Storage & Artifacts)</div>
                        <div className="component-sub">
                          {health?.components?.storage?.provider
                            ? `Backend: ${health.components.storage.provider}`
                            : 'Tệp xuất Excel, Word, PDF'}
                        </div>
                      </div>
                    </div>
                    <div className="component-status">
                      {renderStatusBadge(health?.components?.storage?.status)}
                    </div>
                  </div>
                </div>
              </section>

              {/* Card Quản trị Bộ nhớ Đệm (Cache Management) */}
              <section className="admin-panel-card" aria-labelledby="cache-control-title">
                <div className="panel-card-header">
                  <div className="panel-card-title-group">
                    <Trash2 size={18} className="panel-icon" aria-hidden="true" />
                    <h3 id="cache-control-title">Quản Trị Bộ Nhớ Đệm (Cache)</h3>
                  </div>
                </div>

                <div className="cache-control-body">
                  <p className="cache-control-desc">
                    Xóa toàn bộ câu trả lời đã được nạp vào bộ nhớ đệm RAM và MongoDB query cache.
                    Sử dụng khi có cập nhật mới về thông tin tuyển sinh, điểm chuẩn hoặc quy chế đào tạo HUIT.
                  </p>

                  <div className="cache-stat-box">
                    <span className="cache-stat-label">Số mục truy vấn đã lưu cache:</span>
                    <span className="cache-stat-count">
                      {totalCached.toLocaleString('vi-VN')} bản ghi
                    </span>
                  </div>

                  <button
                    type="button"
                    onClick={() => setShowClearConfirm(true)}
                    className="admin-action-btn btn-danger"
                    disabled={isClearingCache || isLoading}
                    aria-label="Xóa bộ nhớ đệm cache hệ thống"
                  >
                    <Trash2 size={15} aria-hidden="true" />
                    <span>{isClearingCache ? 'Đang giải phóng...' : 'Xóa toàn bộ bộ nhớ đệm'}</span>
                  </button>
                </div>
              </section>
            </div>

            {/* Bảng Nhật ký sự kiện RAG gần nhất */}
            <section className="admin-panel-card" aria-labelledby="recent-events-title" style={{ marginTop: '20px' }}>
              <div className="panel-card-header">
                <div className="panel-card-title-group">
                  <Clock size={18} className="panel-icon" aria-hidden="true" />
                  <h3 id="recent-events-title">Nhật Ký Truy Vấn RAG Gần Đây (Khử Khuẩn An Ninh)</h3>
                </div>
                <span className="panel-subtitle">Hiển thị tối đa 20 sự kiện</span>
              </div>

              <div
                className="admin-table-wrapper"
                role="region"
                aria-label="Bảng nhật ký sự kiện hệ thống"
                tabIndex={0}
                style={{ overflowX: 'auto' }}
              >
                {recentEvents.length === 0 ? (
                  <div className="admin-table-empty">
                    {isLoading ? 'Đang tải dữ liệu nhật ký...' : 'Chưa có sự kiện nào được ghi nhận.'}
                  </div>
                ) : (
                  <table className="admin-events-table">
                    <thead>
                      <tr>
                        <th scope="col">Mã Request</th>
                        <th scope="col">Ý Đồ (Intent)</th>
                        <th scope="col">Mô Hình</th>
                        <th scope="col">Độ Trễ</th>
                        <th scope="col">Nguồn</th>
                        <th scope="col">Thời Gian</th>
                        <th scope="col">Trạng Thái</th>
                      </tr>
                    </thead>
                    <tbody>
                      {recentEvents.map((evt, idx) => (
                        <tr key={evt.request_id || idx}>
                          <td>
                            <code className="admin-request-id" title={evt.request_id}>
                              {evt.request_id ? evt.request_id.slice(0, 8) + '...' : 'N/A'}
                            </code>
                          </td>
                          <td>
                            <span className="admin-intent-tag">{evt.intent || 'TuVanChung'}</span>
                          </td>
                          <td>
                            <span className="admin-model-text">{evt.model || 'Gemini 2.5 Flash'}</span>
                          </td>
                          <td>
                            <span className="admin-latency-text">{evt.latency_ms ? `${evt.latency_ms} ms` : '-'}</span>
                          </td>
                          <td>
                            {evt.cached ? (
                              <span className="source-tag cached">
                                <Zap size={11} aria-hidden="true" /> Cache
                              </span>
                            ) : (
                              <span className="source-tag live">
                                <Activity size={11} aria-hidden="true" /> LLM Stream
                              </span>
                            )}
                          </td>
                          <td>
                            <span className="admin-time-text">
                              {evt.created_at ? new Date(evt.created_at).toLocaleTimeString('vi-VN') : 'Vừa xong'}
                            </span>
                          </td>
                          <td>
                            <span
                              className={`status-pill ${
                                evt.status && evt.status.toLowerCase().includes('lỗi') ? 'error' : 'success'
                              }`}
                            >
                              {evt.status || 'Thành công'}
                            </span>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
              </div>
              <p className="admin-privacy-notice" style={{ marginTop: '12px', fontSize: '0.78rem', color: 'var(--color-text-muted)' }}>
                * Bảo mật dữ liệu: Toàn bộ câu hỏi, prompt thô, token người dùng và API key được khử khuẩn tự động trước khi hiển thị trên trang quản trị.
              </p>
            </section>
          </div>
        )}

        {/* TAB 2: HÀNG ĐỢI JOBS */}
        {activeTab === 'jobs' && (
          <div id="panel-jobs" role="tabpanel" aria-labelledby="tab-jobs">
            <AdminJobsPanel />
          </div>
        )}

        {/* TAB 3: TIẾN TRÌNH WORKER */}
        {activeTab === 'workers' && (
          <div id="panel-workers" role="tabpanel" aria-labelledby="tab-workers">
            <AdminWorkersPanel />
          </div>
        )}

        {/* TAB 4: NHẬT KÝ LỖI */}
        {activeTab === 'logs' && (
          <div id="panel-logs" role="tabpanel" aria-labelledby="tab-logs">
            <AdminErrorLogsPanel />
          </div>
        )}

        {/* TAB 5: HỆ THỐNG & SAO LƯU */}
        {activeTab === 'system' && (
          <div id="panel-system" role="tabpanel" aria-labelledby="tab-system">
            <AdminSystemHealthPanel />
          </div>
        )}
      </main>

      {/* Accessible Confirmation Modal: Xóa Cache */}
      <ConfirmActionModal
        isOpen={showClearConfirm}
        title="Xác nhận xóa bộ nhớ đệm (Cache)"
        message="Bạn có chắc chắn muốn xóa toàn bộ bộ nhớ đệm câu trả lời trong RAM và MongoDB không? Sau khi xóa, các câu hỏi tương tự sẽ được gọi trực tiếp đến LLM. Thao tác này sẽ ghi nhận vào nhật ký kiểm toán."
        confirmLabel="Đồng ý xóa Cache"
        cancelLabel="Hủy bỏ"
        isDanger={true}
        isLoading={isClearingCache}
        onConfirm={async () => {
          setShowClearConfirm(false);
          await onClearCache();
        }}
        onCancel={() => setShowClearConfirm(false)}
      />
    </div>
  );
};
