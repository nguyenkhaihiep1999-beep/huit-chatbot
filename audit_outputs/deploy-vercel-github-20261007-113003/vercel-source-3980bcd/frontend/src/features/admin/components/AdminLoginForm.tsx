import React, { useState } from 'react';
import { Lock, User, ShieldAlert, ArrowLeft, Loader2 } from 'lucide-react';

export interface AdminLoginFormProps {
  onLogin: (username: string, password: string) => Promise<boolean>;
  isLoggingIn: boolean;
  error: string | null;
  onBackToChat: () => void;
}

export const AdminLoginForm: React.FC<AdminLoginFormProps> = ({
  onLogin,
  isLoggingIn,
  error,
  onBackToChat,
}) => {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!username.trim() || !password.trim() || isLoggingIn) return;
    await onLogin(username.trim(), password.trim());
  };

  return (
    <div className="admin-login-wrapper">
      <div className="admin-login-card" role="region" aria-labelledby="admin-login-title">
        <button
          type="button"
          onClick={onBackToChat}
          className="admin-back-btn"
          aria-label="Quay lại giao diện trò chuyện"
        >
          <ArrowLeft size={16} />
          <span>Về trang chủ Chat</span>
        </button>

        <div className="admin-login-header">
          <div className="admin-brand-icon" aria-hidden="true">
            <img src="/huit-ai-mark.svg" alt="" width={44} height={44} />
          </div>
          <h1 id="admin-login-title" className="admin-login-title">Quản Trị Hệ Thống HUIT AI</h1>
          <p className="admin-login-desc">
            Vui lòng đăng nhập với thông tin quản trị viên được ủy quyền để quản lý hệ thống.
          </p>
        </div>

        {error && (
          <div className="admin-alert-error" role="alert">
            <ShieldAlert size={18} className="admin-alert-icon" />
            <span>{error}</span>
          </div>
        )}

        <form onSubmit={handleSubmit} className="admin-login-form" noValidate>
          <div className="admin-form-group">
            <label htmlFor="admin-username" className="admin-form-label">
              Tài khoản quản trị
            </label>
            <div className="admin-input-wrapper">
              <User size={16} className="admin-input-icon" aria-hidden="true" />
              <input
                id="admin-username"
                name="username"
                type="text"
                autoComplete="username"
                required
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                placeholder="Nhập tên tài khoản..."
                className="admin-form-input"
                disabled={isLoggingIn}
                autoFocus
              />
            </div>
          </div>

          <div className="admin-form-group">
            <label htmlFor="admin-password" className="admin-form-label">
              Mật khẩu bảo mật
            </label>
            <div className="admin-input-wrapper">
              <Lock size={16} className="admin-input-icon" aria-hidden="true" />
              <input
                id="admin-password"
                name="password"
                type="password"
                autoComplete="current-password"
                required
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="Nhập mật khẩu..."
                className="admin-form-input"
                disabled={isLoggingIn}
              />
            </div>
          </div>

          <div className="admin-login-notes">
            <span>Phiên đăng nhập được bảo vệ bởi HttpOnly Cookie và CSRF Token.</span>
          </div>

          <button
            type="submit"
            className="admin-submit-btn"
            disabled={isLoggingIn || !username.trim() || !password.trim()}
            aria-busy={isLoggingIn}
          >
            {isLoggingIn ? (
              <>
                <Loader2 size={16} className="spinner-rotate" aria-hidden="true" />
                <span>Đang xác thực...</span>
              </>
            ) : (
              <span>Đăng nhập Quản trị</span>
            )}
          </button>
        </form>
      </div>
    </div>
  );
};
