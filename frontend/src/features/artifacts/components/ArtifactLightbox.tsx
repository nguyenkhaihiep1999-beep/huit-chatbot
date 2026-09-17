import React, { useEffect, useRef } from 'react';
import {
  X,
  Download,
  FileSpreadsheet,
  FileText,
  FileDown,
  Sparkles,
  RefreshCw,
  AlertCircle,
  ZoomIn,
} from 'lucide-react';
import { ArtifactSummary } from '../../../shared/types/common.types';
import { useArtifactWorkflow } from '../hooks/useArtifactWorkflow';

interface ArtifactLightboxProps {
  artifact: ArtifactSummary | null;
  onClose: () => void;
  triggerRef?: React.RefObject<HTMLElement | null>;
}

export const ArtifactLightbox: React.FC<ArtifactLightboxProps> = ({
  artifact,
  onClose,
  triggerRef,
}) => {
  const {
    activePreviewUrl,
    scaleFactor,
    isUpscaling,
    upscaleJobId,
    jobProgress,
    exportingFormat,
    isExporting,
    errorMessage,
    requestUpscale,
    cancelUpscale,
    downloadArtifactExport,
    setPreviewError,
  } = useArtifactWorkflow(artifact);

  const modalRef = useRef<HTMLDivElement>(null);
  const closeBtnRef = useRef<HTMLButtonElement>(null);

  // Focus trap và phím Escape
  useEffect(() => {
    if (!artifact) return;

    closeBtnRef.current?.focus();
    const triggerEl = triggerRef?.current;

    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.preventDefault();
        onClose();
      }
      if (e.key === 'Tab' && modalRef.current) {
        const focusables = modalRef.current.querySelectorAll<HTMLElement>(
          'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])'
        );
        if (focusables.length > 0) {
          const first = focusables[0];
          const last = focusables[focusables.length - 1];
          if (e.shiftKey && document.activeElement === first) {
            e.preventDefault();
            last.focus();
          } else if (!e.shiftKey && document.activeElement === last) {
            e.preventDefault();
            first.focus();
          }
        }
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => {
      window.removeEventListener('keydown', handleKeyDown);
      // Trả lại focus cho nút trigger ban đầu khi đóng lightbox
      if (triggerEl) {
        triggerEl.focus();
      }
    };
  }, [artifact, onClose, triggerRef]);

  if (!artifact) return null;

  const formats = (artifact.available_formats || ['svg', 'png', 'pdf', 'xlsx', 'docx']).filter(
    (fmt) => !['mp3', 'mp4', 'audio', 'video'].includes(fmt.toLowerCase())
  );

  const isImageOrChart = ['image', 'chart', 'infographic', 'vector'].includes(artifact.type.toLowerCase());

  return (
    <div
      className="lightbox-overlay"
      onClick={onClose}
      role="dialog"
      aria-modal="true"
      aria-label={`Xem chi tiết: ${artifact.title}`}
    >
      <div
        ref={modalRef}
        className="lightbox-content animate-fade-in"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Top bar */}
        <div className="lightbox-topbar">
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px', minWidth: 0 }}>
            <h3
              style={{
                fontSize: 'var(--font-md)',
                fontWeight: 700,
                color: 'var(--text-primary)',
                overflow: 'hidden',
                textOverflow: 'ellipsis',
                whiteSpace: 'nowrap',
              }}
            >
              {artifact.title}
            </h3>
            {scaleFactor > 1 && (
              <span
                style={{
                  fontSize: 'var(--font-xs)',
                  padding: '2px 8px',
                  borderRadius: 'var(--radius-full)',
                  backgroundColor: 'var(--color-primary-subtle)',
                  color: 'var(--color-primary)',
                  fontWeight: 700,
                }}
              >
                {scaleFactor}x HD
              </span>
            )}
          </div>

          <div style={{ display: 'flex', alignItems: 'center', gap: '8px', flexShrink: 0 }}>
            {/* Phóng to 2x / 4x */}
            {isImageOrChart && (
              <>
                <button
                  type="button"
                  className="visual-action-btn"
                  onClick={() => requestUpscale(2)}
                  disabled={isUpscaling || scaleFactor === 2}
                  title="Phóng to ảnh chất lượng nét 2x"
                >
                  <ZoomIn size={14} />
                  <span>2x Nét</span>
                </button>
                <button
                  type="button"
                  className="visual-action-btn"
                  onClick={() => requestUpscale(4)}
                  disabled={isUpscaling || scaleFactor === 4}
                  title="Phóng to ảnh siêu nét 4x"
                >
                  <Sparkles size={14} />
                  <span>4x Siêu nét</span>
                </button>
              </>
            )}

            {/* Nút đóng */}
            <button
              ref={closeBtnRef}
              type="button"
              className="visual-action-btn"
              onClick={onClose}
              aria-label="Đóng bản xem chi tiết (Phím Esc)"
              title="Đóng (Esc)"
              style={{ marginLeft: '4px' }}
            >
              <X size={16} />
            </button>
          </div>
        </div>

        {/* Tiến trình Upscale nếu có */}
        {isUpscaling && (
          <div
            style={{
              padding: '10px 16px',
              backgroundColor: 'var(--color-primary-subtle)',
              borderBottom: '1px solid var(--border-default)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              gap: '12px',
              fontSize: 'var(--font-sm)',
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: '10px', flex: 1 }}>
              <RefreshCw size={16} className="animate-spin" color="var(--color-primary)" />
              <span>Đang kết xuất ảnh chất lượng cao... {jobProgress > 0 ? `${jobProgress}%` : ''}</span>
              <div
                style={{
                  flex: 1,
                  maxWidth: '180px',
                  height: '6px',
                  backgroundColor: 'var(--border-default)',
                  borderRadius: 'var(--radius-full)',
                  overflow: 'hidden',
                }}
              >
                <div
                  style={{
                    height: '100%',
                    width: `${jobProgress}%`,
                    backgroundColor: 'var(--color-primary)',
                    transition: 'width 0.3s ease',
                  }}
                />
              </div>
            </div>
            {upscaleJobId && (
              <button
                type="button"
                onClick={cancelUpscale}
                style={{
                  background: 'none',
                  border: 'none',
                  color: 'var(--color-danger)',
                  fontWeight: 600,
                  fontSize: 'var(--font-xs)',
                  cursor: 'pointer',
                  padding: '2px 8px',
                }}
              >
                Hủy
              </button>
            )}
          </div>
        )}

        {/* Thông báo lỗi nếu có kèm nút thử lại */}
        {errorMessage && (
          <div
            style={{
              padding: '8px 16px',
              backgroundColor: 'var(--color-danger-subtle)',
              color: 'var(--color-danger)',
              fontSize: 'var(--font-sm)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              gap: '8px',
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
              <AlertCircle size={15} />
              <span>{errorMessage}</span>
            </div>
            {isImageOrChart && (
              <button
                type="button"
                onClick={() => requestUpscale(scaleFactor > 1 ? scaleFactor : 2)}
                disabled={isUpscaling}
                className="visual-action-btn"
                style={{ flexShrink: 0 }}
                title="Thử lại thao tác phóng to"
              >
                <RefreshCw size={12} />
                <span>Thử lại</span>
              </button>
            )}
          </div>
        )}

        {/* Khung hiển thị Preview */}
        <div
          style={{
            flex: 1,
            overflow: 'auto',
            padding: '20px',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            backgroundColor: 'var(--surface-canvas)',
            minHeight: '320px',
          }}
        >
          {activePreviewUrl ? (
            <img
              src={activePreviewUrl}
              alt={artifact.title}
              style={{
                maxWidth: '100%',
                maxHeight: '70vh',
                objectFit: 'contain',
                borderRadius: 'var(--radius-sm)',
                boxShadow: 'var(--shadow-md)',
              }}
              onError={() => {
                setPreviewError('Không thể tải hình ảnh preview.');
              }}
            />
          ) : (
            <div style={{ color: 'var(--text-muted)', fontSize: 'var(--font-sm)' }}>
              Đang chuẩn bị bản xem trước...
            </div>
          )}
        </div>

        {/* Thanh công cụ định dạng tải xuống phía dưới */}
        <div
          style={{
            padding: '12px 20px',
            borderTop: '1px solid var(--border-default)',
            backgroundColor: 'var(--surface-card)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            flexWrap: 'wrap',
            gap: '12px',
          }}
        >
          <div style={{ fontSize: 'var(--font-sm)', color: 'var(--text-secondary)' }}>
            Định dạng có thể tải về:
          </div>

          <div style={{ display: 'flex', alignItems: 'center', gap: '8px', flexWrap: 'wrap' }}>
            {formats.map((fmt) => {
              const upper = fmt.toUpperCase();
              const isXlsx = upper.includes('XLS');
              const isDocx = upper.includes('DOC');
              const isPdf = upper.includes('PDF');
              const isCurrentExporting = exportingFormat === fmt;

              const icon = isXlsx ? (
                <FileSpreadsheet size={14} />
              ) : isDocx ? (
                <FileText size={14} />
              ) : isPdf ? (
                <FileDown size={14} />
              ) : (
                <Download size={14} />
              );

              return (
                <button
                  key={fmt}
                  type="button"
                  className="visual-action-btn"
                  onClick={() => downloadArtifactExport(fmt)}
                  disabled={isExporting}
                  title={`Tải xuống định dạng ${upper}`}
                >
                  {isCurrentExporting ? <RefreshCw size={14} className="animate-spin" /> : icon}
                  <span>{upper}</span>
                </button>
              );
            })}
          </div>
        </div>
      </div>
    </div>
  );
};
