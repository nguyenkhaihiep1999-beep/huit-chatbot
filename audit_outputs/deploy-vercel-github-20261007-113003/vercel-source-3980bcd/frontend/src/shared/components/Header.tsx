import React from 'react';
import { Menu, Sun, Moon, Sparkles, ShieldCheck, Shield } from 'lucide-react';
import { ThemeMode } from '../types/common.types';

interface HeaderProps {
  onToggleDrawer: () => void;
  isDrawerOpen: boolean;
  theme: ThemeMode;
  onToggleTheme: () => void;
  onOpenImageModal: () => void;
  isOnline: boolean;
  onNavigateAdmin?: () => void;
}

export const Header: React.FC<HeaderProps> = ({
  onToggleDrawer,
  isDrawerOpen,
  theme,
  onToggleTheme,
  onOpenImageModal,
  isOnline,
  onNavigateAdmin,
}) => {
  return (
    <header className="chat-header">
      <div className="brand-info">
        <button
          type="button"
          onClick={onToggleDrawer}
          className="header-icon-btn drawer-toggle-btn"
          title="Mở lịch sử hội thoại"
          aria-label="Mở lịch sử hội thoại"
          aria-expanded={isDrawerOpen}
          aria-controls="history-drawer"
        >
          <Menu size={20} />
        </button>

        <div className="mascot-avatar-small" aria-hidden="true">
          <img src="/huit-ai-mark.svg" alt="" width={40} height={40} className="brand-mark-image" />
        </div>

        <div className="header-titles-group">
          <div className="brand-title-row">
            <h1 className="brand-title">
              <span className="brand-title-full">HUIT Tuyển sinh AI</span>
              <span className="brand-title-compact">HUIT AI</span>
            </h1>
            <span className="brand-badge"><ShieldCheck size={12} /> Đã xác thực</span>
          </div>
          <span className="brand-subtitle">Thông tin tuyển sinh · Tài liệu trực quan</span>
        </div>
      </div>

      <div className="header-actions-group">
        <div
          className={`header-system-status ${isOnline ? 'online' : 'offline'}`}
          title={isOnline ? 'Hệ thống sẵn sàng' : 'Thiết bị đang ngoại tuyến'}
          role="status"
        >
          <span className="status-dot" aria-hidden="true" />
          <span className="status-label">{isOnline ? 'Sẵn sàng' : 'Ngoại tuyến'}</span>
        </div>

        <button
          type="button"
          onClick={onOpenImageModal}
          className="header-action-btn ai-image-btn"
          title="Tạo nội dung trực quan"
          aria-label="Tạo nội dung trực quan"
        >
          <Sparkles size={14} />
          <span className="btn-label-desktop">Tạo trực quan</span>
        </button>

        {onNavigateAdmin && (
          <button
            type="button"
            onClick={onNavigateAdmin}
            className="header-icon-btn admin-link-btn"
            title="Trang quản trị hệ thống HUIT AI"
            aria-label="Trang quản trị hệ thống"
          >
            <Shield size={18} />
          </button>
        )}

        <button
          type="button"
          onClick={onToggleTheme}
          className="header-icon-btn theme-toggle-btn"
          title={theme === 'light' ? 'Chuyển sang giao diện tối' : 'Chuyển sang giao diện sáng'}
          aria-label={theme === 'light' ? 'Chuyển sang giao diện tối' : 'Chuyển sang giao diện sáng'}
        >
          {theme === 'light' ? <Moon size={18} /> : <Sun size={18} />}
        </button>
      </div>
    </header>
  );
};
