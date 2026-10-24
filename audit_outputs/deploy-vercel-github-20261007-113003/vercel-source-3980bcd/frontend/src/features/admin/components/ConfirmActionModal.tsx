import React, { useEffect, useRef } from 'react';
import { AlertTriangle, AlertCircle, X } from 'lucide-react';

export interface ConfirmActionModalProps {
  isOpen: boolean;
  title: string;
  message: string;
  confirmLabel?: string;
  cancelLabel?: string;
  isDanger?: boolean;
  isLoading?: boolean;
  onConfirm: () => void | Promise<void>;
  onCancel: () => void;
}

export const ConfirmActionModal: React.FC<ConfirmActionModalProps> = ({
  isOpen,
  title,
  message,
  confirmLabel = 'Xác nhận',
  cancelLabel = 'Hủy bỏ',
  isDanger = false,
  isLoading = false,
  onConfirm,
  onCancel,
}) => {
  const cancelBtnRef = useRef<HTMLButtonElement>(null);
  const confirmBtnRef = useRef<HTMLButtonElement>(null);
  const modalCardRef = useRef<HTMLDivElement>(null);

  // Focus trap & Escape key
  useEffect(() => {
    if (!isOpen) return;

    // Default focus on cancel button to prevent accidental clicks on dangerous actions
    const timer = setTimeout(() => {
      cancelBtnRef.current?.focus();
    }, 50);

    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.preventDefault();
        onCancel();
      } else if (e.key === 'Tab') {
        // Focus trap
        if (!modalCardRef.current) return;
        const focusable = modalCardRef.current.querySelectorAll<HTMLElement>(
          'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])'
        );
        if (focusable.length === 0) return;

        const first = focusable[0];
        const last = focusable[focusable.length - 1];

        if (e.shiftKey && document.activeElement === first) {
          e.preventDefault();
          last.focus();
        } else if (!e.shiftKey && document.activeElement === last) {
          e.preventDefault();
          first.focus();
        }
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => {
      clearTimeout(timer);
      window.removeEventListener('keydown', handleKeyDown);
    };
  }, [isOpen, onCancel]);

  if (!isOpen) return null;

  return (
    <div
      className="admin-modal-backdrop"
      role="dialog"
      aria-modal="true"
      aria-labelledby="confirm-action-title"
      aria-describedby="confirm-action-desc"
      onClick={(e) => {
        if (e.target === e.currentTarget && !isLoading) onCancel();
      }}
    >
      <div className="admin-modal-card" ref={modalCardRef}>
        <div className="admin-modal-header">
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            {isDanger ? (
              <AlertTriangle size={22} className="text-danger" aria-hidden="true" style={{ color: 'var(--color-danger, #ef4444)' }} />
            ) : (
              <AlertCircle size={22} className="text-warning" aria-hidden="true" style={{ color: 'var(--color-warning, #f59e0b)' }} />
            )}
            <h3 id="confirm-action-title" style={{ margin: 0, fontSize: '1.1rem', fontWeight: 600 }}>
              {title}
            </h3>
          </div>
          <button
            type="button"
            onClick={onCancel}
            disabled={isLoading}
            className="sidebar-close-btn"
            aria-label="Đóng hộp thoại"
            style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'var(--color-text-muted)' }}
          >
            <X size={18} />
          </button>
        </div>

        <p id="confirm-action-desc" className="admin-modal-body" style={{ margin: 'var(--space-3) 0 var(--space-4)', fontSize: '0.9rem', color: 'var(--color-text-secondary)', lineHeight: 1.5 }}>
          {message}
        </p>

        <div className="admin-modal-actions" style={{ display: 'flex', justifyContent: 'flex-end', gap: '8px' }}>
          <button
            ref={cancelBtnRef}
            type="button"
            onClick={onCancel}
            className="admin-action-btn btn-secondary"
            disabled={isLoading}
            style={{
              padding: '6px 14px',
              borderRadius: '6px',
              border: '1px solid var(--color-border)',
              background: 'var(--color-surface)',
              cursor: 'pointer',
            }}
          >
            {cancelLabel}
          </button>
          <button
            ref={confirmBtnRef}
            type="button"
            onClick={onConfirm}
            className={`admin-action-btn ${isDanger ? 'btn-danger' : 'btn-primary'}`}
            disabled={isLoading}
            style={{
              padding: '6px 14px',
              borderRadius: '6px',
              border: 'none',
              background: isDanger ? 'var(--color-danger, #ef4444)' : 'var(--color-primary)',
              color: '#ffffff',
              fontWeight: 500,
              cursor: 'pointer',
            }}
          >
            {isLoading ? 'Đang xử lý...' : confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
};
