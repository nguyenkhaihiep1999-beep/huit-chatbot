import React, { useEffect, useRef } from 'react';
import { Shield, Lock, Trash2, Cpu, HardDrive, X, Check } from 'lucide-react';

export interface PrivacyPolicyModalProps {
  isOpen: boolean;
  onClose: () => void;
}

export const PrivacyPolicyModal: React.FC<PrivacyPolicyModalProps> = ({ isOpen, onClose }) => {
  const closeBtnRef = useRef<HTMLButtonElement>(null);
  const modalRef = useRef<HTMLDivElement>(null);
  const onCloseRef = useRef(onClose);

  useEffect(() => {
    onCloseRef.current = onClose;
  }, [onClose]);

  useEffect(() => {
    if (!isOpen) return;

    const timer = setTimeout(() => {
      closeBtnRef.current?.focus();
    }, 50);

    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.preventDefault();
        e.stopPropagation();
        onCloseRef.current();
      } else if (e.key === 'Tab') {
        if (!modalRef.current) return;
        const focusable = modalRef.current.querySelectorAll<HTMLElement>(
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
  }, [isOpen]);

  if (!isOpen) return null;

  return (
    <div
      className="admin-modal-backdrop"
      role="dialog"
      aria-modal="true"
      aria-labelledby="privacy-modal-title"
      aria-describedby="privacy-modal-desc"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
      style={{
        position: 'fixed',
        inset: 0,
        backgroundColor: 'rgba(0, 0, 0, 0.65)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        zIndex: 9999,
        padding: '16px',
      }}
    >
      <div
        className="admin-modal-card"
        ref={modalRef}
        style={{
          background: 'var(--color-surface, #ffffff)',
          color: 'var(--color-text, #1e293b)',
          borderRadius: '12px',
          maxWidth: '620px',
          width: '100%',
          maxHeight: '85vh',
          display: 'flex',
          flexDirection: 'column',
          boxShadow: '0 20px 25px -5px rgba(0, 0, 0, 0.2)',
          border: '1px solid var(--color-border, #e2e8f0)',
        }}
      >
        {/* Header */}
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            padding: '16px 20px',
            borderBottom: '1px solid var(--color-border, #e2e8f0)',
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
            <div
              style={{
                width: '32px',
                height: '32px',
                borderRadius: '8px',
                background: 'rgba(59, 130, 246, 0.1)',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
              }}
            >
              <Shield size={18} color="var(--color-primary, #2563eb)" aria-hidden="true" />
            </div>
            <h3 id="privacy-modal-title" style={{ margin: 0, fontSize: '1.1rem', fontWeight: 600 }}>
              Quyền Riêng Tư & Chính Sách Lưu Giữ Dữ Liệu
            </h3>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Đóng chính sách quyền riêng tư"
            style={{
              background: 'none',
              border: 'none',
              cursor: 'pointer',
              color: 'var(--color-text-muted, #64748b)',
              padding: '4px',
              borderRadius: '6px',
            }}
          >
            <X size={20} />
          </button>
        </div>

        {/* Body Content */}
        <div
          id="privacy-modal-desc"
          style={{
            padding: '20px',
            overflowY: 'auto',
            fontSize: '0.88rem',
            lineHeight: 1.6,
            display: 'flex',
            flexDirection: 'column',
            gap: '16px',
          }}
        >
          {/* Section 1: LocalStorage */}
          <div style={{ display: 'flex', gap: '12px', alignItems: 'flex-start' }}>
            <HardDrive size={20} color="var(--color-primary, #2563eb)" style={{ flexShrink: 0, marginTop: '2px' }} aria-hidden="true" />
            <div>
              <strong style={{ fontSize: '0.92rem' }}>1. Lưu trữ cục bộ trên thiết bị (LocalStorage)</strong>
              <p style={{ margin: '4px 0 0', color: 'var(--color-text-secondary, #475569)' }}>
                Toàn bộ lịch sử các phiên trò chuyện của bạn được lưu trữ hoàn toàn trong <code>localStorage</code> trên
                trình duyệt của bạn. Bạn có toàn quyền xóa từng phiên hoặc xóa toàn bộ lịch sử trò chuyện bất kỳ lúc nào.
                Khi xóa, dữ liệu sẽ lập tức bị xóa vĩnh viễn khỏi thiết bị.
              </p>
            </div>
          </div>

          {/* Section 2: Anonymous / Guest Mode */}
          <div style={{ display: 'flex', gap: '12px', alignItems: 'flex-start' }}>
            <Lock size={20} color="#16a34a" style={{ flexShrink: 0, marginTop: '2px' }} aria-hidden="true" />
            <div>
              <strong style={{ fontSize: '0.92rem' }}>2. Chế độ Khách / Ẩn danh (Guest Mode)</strong>
              <p style={{ margin: '4px 0 0', color: 'var(--color-text-secondary, #475569)' }}>
                Hệ thống hoạt động ở chế độ khách không yêu cầu đăng ký hay đăng nhập tài khoản người dùng cá nhân.
                Chúng tôi không lưu trữ thông tin định danh cá nhân (PII) như Họ tên, Email, hay Số điện thoại.
              </p>
            </div>
          </div>

          {/* Section 3: LLM Providers */}
          <div style={{ display: 'flex', gap: '12px', alignItems: 'flex-start' }}>
            <Cpu size={20} color="#d97706" style={{ flexShrink: 0, marginTop: '2px' }} aria-hidden="true" />
            <div>
              <strong style={{ fontSize: '0.92rem' }}>3. Xử lý qua Nhà cung cấp Mô hình AI (LLM Providers)</strong>
              <p style={{ margin: '4px 0 0', color: 'var(--color-text-secondary, #475569)' }}>
                Để sinh câu trả lời tư vấn tuyển sinh và quy chế đào tạo, câu hỏi của bạn sẽ được chuyển đến API của
                các nhà cung cấp mô hình ngôn ngữ lớn (Google Gemini / Groq) qua đường truyền bảo mật mã hóa HTTPS.
                Vui lòng không gửi các thông tin bí mật cá nhân trong nội dung trò chuyện.
              </p>
            </div>
          </div>

          {/* Section 4: Data Retention & Sanitization */}
          <div style={{ display: 'flex', gap: '12px', alignItems: 'flex-start' }}>
            <Shield size={20} color="#9333ea" style={{ flexShrink: 0, marginTop: '2px' }} aria-hidden="true" />
            <div>
              <strong style={{ fontSize: '0.92rem' }}>4. Chính sách Lưu giữ & Khử khuẩn (Retention Policy)</strong>
              <p style={{ margin: '4px 0 0', color: 'var(--color-text-secondary, #475569)' }}>
                Máy chủ chỉ lưu trữ mã băm an toàn SHA-256 (<code>question_hash</code>) cùng thời gian phản hồi để
                đo lường chất lượng hệ thống; không lưu câu hỏi thô vào nhật ký quản trị. Các tệp xuất tải về
                (Excel, Word, PDF, hình ảnh) được tạo qua hàng đợi nền sử dụng liên kết ký số tạm thời và tự động hết hạn sau 24 giờ.
              </p>
            </div>
          </div>

          {/* Section 5: Zero Sensitive Storage in Browser */}
          <div style={{ display: 'flex', gap: '12px', alignItems: 'flex-start' }}>
            <Trash2 size={20} color="#dc2626" style={{ flexShrink: 0, marginTop: '2px' }} aria-hidden="true" />
            <div>
              <strong style={{ fontSize: '0.92rem' }}>5. Không lưu trữ nhạy cảm (Zero Sensitive Storage)</strong>
              <p style={{ margin: '4px 0 0', color: 'var(--color-text-secondary, #475569)' }}>
                Trình duyệt của bạn tuyệt đối không lưu trữ signed download URL dài hạn, token bí mật, hoặc chuỗi Base64
                lớn trong bộ nhớ để bảo vệ an toàn và ngăn ngừa tràn dung lượng.
              </p>
            </div>
          </div>
        </div>

        {/* Footer */}
        <div
          style={{
            padding: '14px 20px',
            borderTop: '1px solid var(--color-border, #e2e8f0)',
            display: 'flex',
            justifyContent: 'flex-end',
            background: 'var(--color-surface-hover, #f8fafc)',
            borderBottomLeftRadius: '12px',
            borderBottomRightRadius: '12px',
          }}
        >
          <button
            ref={closeBtnRef}
            type="button"
            onClick={onClose}
            className="admin-action-btn btn-primary"
            style={{
              display: 'inline-flex',
              alignItems: 'center',
              gap: '6px',
              padding: '8px 18px',
              borderRadius: '6px',
              border: 'none',
              background: 'var(--color-primary, #2563eb)',
              color: '#ffffff',
              fontWeight: 500,
              cursor: 'pointer',
            }}
          >
            <Check size={16} aria-hidden="true" />
            <span>Tôi đã hiểu</span>
          </button>
        </div>
      </div>
    </div>
  );
};
