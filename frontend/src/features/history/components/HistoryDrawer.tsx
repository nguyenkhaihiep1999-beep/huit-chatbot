import React, { useState, useMemo, useEffect } from 'react';
import {
  Plus,
  MessageSquare,
  Trash2,
  Search,
  ChevronLeft,
  Sun,
  Moon,
  Sparkles,
  Shield,
} from 'lucide-react';
import { ConversationSession, ThemeMode } from '../../../shared/types/common.types';
import { ConfirmModal } from '../../../shared/components/ConfirmModal';
import { PrivacyPolicyModal } from '../../../shared/components/PrivacyPolicyModal';

interface HistoryDrawerProps {
  isOpen: boolean;
  onClose: () => void;
  sessions: ConversationSession[];
  activeSessionId: string;
  onSelectSession: (session: ConversationSession) => void;
  onNewChat: () => void;
  onDeleteSession: (sessionId: string) => void;
  onClearAllSessions?: () => void;
  theme?: ThemeMode;
  onToggleTheme?: () => void;
  isOnline?: boolean;
  onNavigateAdmin?: () => void;
}

export const HistoryDrawer: React.FC<HistoryDrawerProps> = ({
  isOpen,
  onClose,
  sessions,
  activeSessionId,
  onSelectSession,
  onNewChat,
  onDeleteSession,
  onClearAllSessions,
  theme = 'light',
  onToggleTheme,
  isOnline = true,
  onNavigateAdmin,
}) => {
  const [searchQuery, setSearchQuery] = useState<string>('');
  const [sessionToDelete, setSessionToDelete] = useState<string | null>(null);
  const [showClearAllConfirm, setShowClearAllConfirm] = useState<boolean>(false);
  const [showPrivacyModal, setShowPrivacyModal] = useState<boolean>(false);

  useEffect(() => {
    if (!isOpen) return;
    const handleEscape = (event: KeyboardEvent) => {
      if (showPrivacyModal || Boolean(sessionToDelete) || showClearAllConfirm) {
        return;
      }
      if (event.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', handleEscape);
    return () => window.removeEventListener('keydown', handleEscape);
  }, [isOpen, onClose, showPrivacyModal, sessionToDelete, showClearAllConfirm]);

  // Lọc tìm kiếm lịch sử
  const filteredSessions = useMemo(() => {
    if (!searchQuery.trim()) return sessions;
    const q = searchQuery.toLowerCase().trim();
    return sessions.filter((s) => s.title.toLowerCase().includes(q));
  }, [sessions, searchQuery]);

  const handleDeleteClick = (sessionId: string, e: React.MouseEvent) => {
    e.stopPropagation();
    setSessionToDelete(sessionId);
  };

  const handleConfirmDelete = () => {
    if (sessionToDelete) {
      onDeleteSession(sessionToDelete);
      setSessionToDelete(null);
    }
  };

  return (
    <>
      {/* Backdrop trên màn hình Mobile */}
      {isOpen && (
        <div
          className="mobile-drawer-backdrop"
          onClick={onClose}
          aria-hidden="true"
        />
      )}

      <aside
        id="history-drawer"
        className={`history-drawer ${isOpen ? 'open' : ''}`}
        aria-label="Lịch sử cuộc trò chuyện"
        aria-hidden={!isOpen}
        inert={!isOpen ? true : undefined}
      >
        {/* Header của Sidebar */}
        <div className="history-sidebar-header">
          <div className="brand-badge-wrapper">
            <div className="brand-icon-box">
              <Sparkles size={16} color="var(--color-primary)" />
            </div>
            <div className="sidebar-brand-copy">
              <span className="brand-name-text">Không gian tư vấn</span>
              <small>Lịch sử hội thoại</small>
            </div>
          </div>

          <button
            type="button"
            onClick={onClose}
            className="sidebar-close-btn"
            aria-label="Thu gọn danh mục lịch sử"
            title="Thu gọn (Esc)"
          >
            <ChevronLeft size={18} />
          </button>
        </div>

        {/* Nút Cuộc trò chuyện mới */}
        <div style={{ padding: '0 var(--space-4)', marginTop: 'var(--space-3)' }}>
          <button
            type="button"
            className="new-chat-btn"
            onClick={onNewChat}
            aria-label="Tạo cuộc trò chuyện mới"
          >
            <Plus size={16} />
            <span>Cuộc trò chuyện mới</span>
          </button>
        </div>

        {/* Ô Tìm kiếm lịch sử nếu có từ 2 phiên trở lên */}
        {sessions.length >= 2 && (
          <div className="history-search-box">
            <Search size={14} className="search-icon" />
            <input
              type="text"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="Tìm kiếm cuộc trò chuyện..."
              className="history-search-input"
              aria-label="Tìm kiếm cuộc trò chuyện"
            />
          </div>
        )}

        {/* Thanh công cụ quản trị lịch sử: Đếm số lượng & Xóa tất cả */}
        {sessions.length > 0 && onClearAllSessions && (
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: 'var(--space-2) var(--space-4)' }}>
            <span style={{ fontSize: '0.75rem', color: 'var(--color-text-muted)' }}>
              {sessions.length} cuộc trò chuyện
            </span>
            <button
              type="button"
              onClick={() => setShowClearAllConfirm(true)}
              style={{
                background: 'none',
                border: 'none',
                color: 'var(--color-danger, #ef4444)',
                fontSize: '0.75rem',
                cursor: 'pointer',
                display: 'inline-flex',
                alignItems: 'center',
                gap: '4px',
                padding: '2px 6px',
                borderRadius: '4px',
              }}
              aria-label="Xóa toàn bộ lịch sử trò chuyện"
            >
              <Trash2 size={12} />
              <span>Xóa tất cả</span>
            </button>
          </div>
        )}

        {/* Danh sách các phiên trò chuyện */}
        <div className="history-list" role={filteredSessions.length > 0 ? 'list' : undefined}>
          {filteredSessions.length === 0 ? (
            <div className="history-empty-text" role="status">
              {searchQuery ? 'Không tìm thấy cuộc trò chuyện nào.' : 'Chưa có lịch sử trò chuyện.'}
            </div>
          ) : (
            filteredSessions.map((s) => (
              <div
                key={s.sessionId}
                role="listitem"
                className={`history-item ${s.sessionId === activeSessionId ? 'active' : ''}`}
              >
                <button
                  type="button"
                  className="history-select-btn"
                  aria-current={s.sessionId === activeSessionId ? 'page' : undefined}
                  onClick={() => {
                    onSelectSession(s);
                    if (window.innerWidth < 768) onClose();
                  }}
                >
                  <MessageSquare size={15} className="history-item-icon" />
                  <span className="history-item-title">{s.title}</span>
                </button>

                <button
                  type="button"
                  onClick={(e) => handleDeleteClick(s.sessionId, e)}
                  className="history-delete-btn"
                  title="Xóa cuộc trò chuyện này khỏi thiết bị"
                  aria-label={`Xóa cuộc trò chuyện: ${s.title}`}
                >
                  <Trash2 size={13} />
                </button>
              </div>
            ))
          )}
        </div>

        {/* Thông báo quyền riêng tư dữ liệu người dùng */}
        <div style={{ padding: 'var(--space-3) var(--space-4)', borderTop: '1px solid var(--color-border)', fontSize: '0.74rem', color: 'var(--color-text-muted)', display: 'flex', flexDirection: 'column', gap: '6px' }}>
          <div style={{ display: 'flex', alignItems: 'flex-start', gap: '6px' }}>
            <Shield size={14} style={{ flexShrink: 0, marginTop: '2px', color: 'var(--color-primary)' }} aria-hidden="true" />
            <span>Lịch sử hội thoại được lưu trữ cục bộ trong localStorage trên thiết bị của bạn. Chế độ khách không thu thập định danh cá nhân.</span>
          </div>
          <button
            type="button"
            onClick={() => setShowPrivacyModal(true)}
            style={{
              background: 'none',
              border: 'none',
              padding: 0,
              color: 'var(--color-primary)',
              fontSize: '0.74rem',
              textAlign: 'left',
              cursor: 'pointer',
              textDecoration: 'underline',
              display: 'inline-block',
            }}
          >
            Chính sách quyền riêng tư & Lưu giữ dữ liệu
          </button>
        </div>

        {/* Footer của Sidebar: Theme Switch & Connection Status */}
        <div className="history-sidebar-footer">
          {/* Trạng thái kết nối */}
          <div className="connection-status-indicator" title={isOnline ? 'Máy chủ trực tuyến' : 'Mất kết nối máy chủ'}>
            <span
              className={`status-dot ${isOnline ? 'online' : 'offline'}`}
              aria-hidden="true"
            />
            <span className="status-text">{isOnline ? 'Kết nối an toàn' : 'Ngoại tuyến'}</span>
          </div>

          {/* Nút truy cập Quản trị */}
          {onNavigateAdmin && (
            <button
              type="button"
              onClick={() => {
                onNavigateAdmin();
                if (window.innerWidth < 768) onClose();
              }}
              className="theme-toggle-sidebar-btn"
              aria-label="Mở trang Quản trị hệ thống HUIT AI"
              title="Quản trị hệ thống"
            >
              <Shield size={16} />
            </button>
          )}

          {/* Nút chuyển đổi Theme */}
          {onToggleTheme && (
            <button
              type="button"
              onClick={onToggleTheme}
              className="theme-toggle-sidebar-btn"
              aria-label={`Chuyển sang giao diện ${theme === 'dark' ? 'sáng' : 'tối'}`}
              title={`Giao diện: ${theme === 'dark' ? 'Tối' : 'Sáng'}`}
            >
              {theme === 'dark' ? <Sun size={16} /> : <Moon size={16} />}
            </button>
          )}
        </div>
      </aside>

      {/* Hộp thoại xác nhận xóa một phiên chat */}
      <ConfirmModal
        isOpen={Boolean(sessionToDelete)}
        title="Xóa cuộc trò chuyện?"
        message="Cuộc trò chuyện này sẽ được xóa vĩnh viễn khỏi bộ nhớ trình duyệt trên thiết bị của bạn. Dữ liệu tài liệu trên máy chủ không bị ảnh hưởng."
        confirmLabel="Xóa"
        cancelLabel="Hủy"
        isDanger={true}
        onConfirm={handleConfirmDelete}
        onCancel={() => setSessionToDelete(null)}
      />

      {/* Hộp thoại xác nhận xóa toàn bộ phiên chat */}
      <ConfirmModal
        isOpen={showClearAllConfirm}
        title="Xóa toàn bộ lịch sử trò chuyện?"
        message="Toàn bộ lịch sử các cuộc trò chuyện sẽ được xóa vĩnh viễn khỏi thiết bị này. Hành động này không thể hoàn tác."
        confirmLabel="Xóa tất cả"
        cancelLabel="Hủy"
        isDanger={true}
        onConfirm={() => {
          if (onClearAllSessions) onClearAllSessions();
          setShowClearAllConfirm(false);
        }}
        onCancel={() => setShowClearAllConfirm(false)}
      />

      {/* Hộp thoại Chính sách quyền riêng tư & Lưu giữ dữ liệu */}
      <PrivacyPolicyModal
        isOpen={showPrivacyModal}
        onClose={() => setShowPrivacyModal(false)}
      />
    </>
  );
};
