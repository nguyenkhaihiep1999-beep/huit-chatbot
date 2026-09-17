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
          <picture>
            <source srcSet="/robot_huit.webp" type="image/webp" />
            <img
              src="/robot_huit.png"
              alt=""
              width={28}
              height={28}
              style={{ width: '100%', height: '100%', objectFit: 'contain' }}
              onError={(e) => {
                (e.currentTarget as HTMLElement).style.display = 'none';
              }}
            />
          </picture>
        </div>

        <div className="header-titles-group">
          <div className="brand-title-row">
            <h1 className="brand-title">
              <span className="brand-title-full">HUIT AI Tuyển Sinh</span>
              <span className="brand-title-compact">HUIT AI</span>
            </h1>
            <span className="brand-badge"><ShieldCheck size={12} /> Chính thức</span>
          </div>
          <span className="brand-subtitle">Trợ lý tuyển sinh và xuất bản tài liệu</span>
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
          title="Tạo ảnh AI Mascot HUIT"
          aria-label="Tạo ảnh AI Mascot HUIT"
        >
          <Sparkles size={14} />
          <span className="btn-label-desktop">Tạo ảnh</span>
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
