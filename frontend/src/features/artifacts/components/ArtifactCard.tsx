import React, { useState, useRef } from 'react';
import {
  Maximize2,
  Download,
  FileSpreadsheet,
  FileText,
  RefreshCw,
  AlertCircle,
  FileCode,
  Image as ImageIcon,
  ChevronDown,
} from 'lucide-react';
import { ArtifactSummary } from '../../../shared/types/common.types';
import { useArtifactWorkflow } from '../hooks/useArtifactWorkflow';
import { ArtifactLightbox } from './ArtifactLightbox';

interface ArtifactCardProps {
  artifact: ArtifactSummary;
  onOpenLightbox?: (artifact: ArtifactSummary) => void;
}

export const ArtifactCard: React.FC<ArtifactCardProps> = ({
  artifact,
  onOpenLightbox,
}) => {
  const [showExportMenu, setShowExportMenu] = useState<boolean>(false);
  const [isInternalLightboxOpen, setIsInternalLightboxOpen] = useState<boolean>(false);
  const [imageError, setImageError] = useState<boolean>(false);

  const {
    defaultPreviewUrl: previewUrl,
    isExporting,
    errorMessage: exportError,
    downloadArtifactExport,
  } = useArtifactWorkflow(artifact);

  const cardRef = useRef<HTMLDivElement>(null);
  const viewBtnRef = useRef<HTMLButtonElement>(null);

  const isPlanned = artifact.status === 'planned';
  const isRendering = artifact.status === 'rendering';
  const isUnavailable = artifact.status === 'unavailable' || artifact.status === 'failed';
  const isReady = !isUnavailable && (!artifact.status || artifact.status === 'ready');

  // Lọc bỏ tuyệt đối audio/video
  const availableFormats = (artifact.available_formats || ['svg', 'png', 'pdf', 'xlsx', 'docx']).filter(
    (f) => !['mp3', 'mp4', 'audio', 'video'].includes(f.toLowerCase())
  );

  const handleOpenViewer = () => {
    if (onOpenLightbox) {
      onOpenLightbox(artifact);
    } else {
      setIsInternalLightboxOpen(true);
    }
  };

  const handleDownload = async (format: string, e?: React.MouseEvent) => {
    e?.stopPropagation();
    setShowExportMenu(false);
    await downloadArtifactExport(format);
  };

  // Icon biểu diễn theo loại tài liệu
  const typeLower = (artifact.type || '').toLowerCase();
  const isSpreadsheet = typeLower.includes('excel') || typeLower.includes('sheet') || typeLower.includes('table');
  const isDocument = typeLower.includes('doc') || typeLower.includes('word') || typeLower.includes('text');
  const isChartOrImage = typeLower.includes('chart') || typeLower.includes('image') || typeLower.includes('infographic') || typeLower.includes('vector');

  const PrimaryIcon = isSpreadsheet
    ? FileSpreadsheet
    : isDocument
    ? FileText
    : isChartOrImage
    ? ImageIcon
    : FileCode;

  const typeLabel = isSpreadsheet
    ? 'Bảng tính Excel'
    : isDocument
    ? 'Tài liệu Word'
    : isChartOrImage
    ? 'Đồ họa SVG'
    : 'Dữ liệu HUIT';

  return (
    <>
      <article
        ref={cardRef}
        className="visual-card-wrapper artifact-card animate-fade-in"
        style={{
          border: '1px solid var(--border-default)',
          backgroundColor: 'var(--surface-card)',
          borderRadius: 'var(--radius-md)',
          boxShadow: 'var(--shadow-sm)',
          overflow: 'hidden',
          marginTop: '12px',
          maxWidth: '520px',
        }}
      >
        {/* Header của thẻ Artifact */}
        <div
          className="visual-header"
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            padding: '10px 14px',
            backgroundColor: 'var(--surface-hover)',
            borderBottom: '1px solid var(--border-default)',
            gap: '8px',
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px', minWidth: 0 }}>
            <PrimaryIcon size={16} color="var(--color-primary)" style={{ flexShrink: 0 }} />
            <span
              style={{
                fontSize: 'var(--font-sm)',
                fontWeight: 700,
                color: 'var(--text-primary)',
                overflow: 'hidden',
                textOverflow: 'ellipsis',
                whiteSpace: 'nowrap',
              }}
            >
              {artifact.title || 'Tài liệu & Dữ liệu HUIT'}
            </span>
            {isUnavailable ? (
              <span
                style={{
                  fontSize: '0.68rem',
                  fontWeight: 700,
                  padding: '2px 6px',
                  borderRadius: 'var(--radius-xs)',
                  backgroundColor: 'var(--color-danger-subtle, rgba(239, 68, 68, 0.15))',
                  color: 'var(--color-danger, #ef4444)',
                  flexShrink: 0,
                  textTransform: 'uppercase',
                }}
              >
                Không khả dụng
              </span>
            ) : (
              <span
                style={{
                  fontSize: '0.68rem',
                  fontWeight: 700,
                  padding: '2px 6px',
                  borderRadius: 'var(--radius-xs)',
                  backgroundColor: 'var(--color-primary-subtle)',
                  color: 'var(--color-primary)',
                  flexShrink: 0,
                  textTransform: 'uppercase',
                }}
              >
                {typeLabel}
              </span>
            )}
          </div>

          {/* Action buttons */}
          <div style={{ display: 'flex', alignItems: 'center', gap: '6px', flexShrink: 0 }}>
            {isReady && (
              <button
                ref={viewBtnRef}
                type="button"
                className="visual-action-btn btn-artifact-view"
                onClick={handleOpenViewer}
                title="Xem chi tiết (Phóng to)"
              >
                <Maximize2 size={13} />
                <span>Xem</span>
              </button>
            )}

            {/* Menu Tải xuống */}
            {isReady && availableFormats.length > 0 && (
              <div style={{ position: 'relative' }}>
                <button
                  type="button"
                  className="visual-action-btn btn-artifact-action"
                  onClick={() => setShowExportMenu(!showExportMenu)}
                  disabled={isExporting}
                  title="Tải tệp tin về máy"
                >
                  {isExporting ? (
                    <RefreshCw size={13} className="animate-spin" />
                  ) : (
                    <Download size={13} />
                  )}
                  <span>Tải về</span>
                  <ChevronDown size={11} />
                </button>

                {showExportMenu && (
                  <div
                    style={{
                      position: 'absolute',
                      right: 0,
                      top: 'calc(100% + 4px)',
                      backgroundColor: 'var(--surface-elevated)',
                      border: '1px solid var(--border-default)',
                      borderRadius: 'var(--radius-sm)',
                      boxShadow: 'var(--shadow-lg)',
                      padding: '4px',
                      zIndex: 50,
                      minWidth: '130px',
                      display: 'flex',
                      flexDirection: 'column',
                      gap: '2px',
                    }}
                  >
                    {availableFormats.map((fmt) => (
                      <button
                        key={fmt}
                        type="button"
                        onClick={(e) => handleDownload(fmt, e)}
                        style={{
                          background: 'none',
                          border: 'none',
                          padding: '6px 10px',
                          textAlign: 'left',
                          fontSize: 'var(--font-xs)',
                          fontWeight: 600,
                          color: 'var(--text-primary)',
                          borderRadius: 'var(--radius-xs)',
                          cursor: 'pointer',
                          display: 'flex',
                          alignItems: 'center',
                          gap: '8px',
                          textTransform: 'uppercase',
                        }}
                        onMouseEnter={(e) => {
                          e.currentTarget.style.backgroundColor = 'var(--surface-hover)';
                        }}
                        onMouseLeave={(e) => {
                          e.currentTarget.style.backgroundColor = 'transparent';
                        }}
                      >
                        <Download size={12} color="var(--color-primary)" />
                        <span>.{fmt.toLowerCase()}</span>
                      </button>
                    ))}
                  </div>
                )}
              </div>
            )}
          </div>
        </div>

        {/* Thumbnail Preview Area */}
        <div
          style={{
            padding: '12px',
            backgroundColor: 'var(--surface-canvas)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            minHeight: '130px',
            cursor: isReady ? 'pointer' : 'default',
          }}
          onClick={isReady ? handleOpenViewer : undefined}
        >
          {isUnavailable ? (
            <div
              style={{
                display: 'flex',
                flexDirection: 'column',
                alignItems: 'center',
                gap: '8px',
                color: 'var(--color-danger, #ef4444)',
                padding: '16px',
                textAlign: 'center',
              }}
            >
              <AlertCircle size={28} />
              <span style={{ fontSize: 'var(--font-xs)', fontWeight: 600 }}>
                {artifact.error_message || 'Tài liệu không khả dụng hoặc đã hết hạn lưu trữ.'}
              </span>
            </div>
          ) : isPlanned || isRendering ? (
            <div
              style={{
                display: 'flex',
                flexDirection: 'column',
                alignItems: 'center',
                gap: '8px',
                color: 'var(--text-muted)',
                fontSize: 'var(--font-xs)',
              }}
            >
              <RefreshCw size={20} className="animate-spin" color="var(--color-primary)" />
              <span>Đang kết xuất bản xem trước nhẹ...</span>
            </div>
          ) : imageError || !previewUrl ? (
            <div
              style={{
                display: 'flex',
                flexDirection: 'column',
                alignItems: 'center',
                gap: '8px',
                color: 'var(--text-subtle)',
                fontSize: 'var(--font-xs)',
              }}
            >
              <PrimaryIcon size={24} />
              <span>Bản xem trước sẵn sàng tải về</span>
              {imageError && (
                <button
                  type="button"
                  onClick={(e) => {
                    e.stopPropagation();
                    setImageError(false);
                  }}
                  className="visual-action-btn"
                  style={{ marginTop: '4px' }}
                >
                  <RefreshCw size={12} />
                  <span>Tải lại xem trước</span>
                </button>
              )}
            </div>
          ) : (
            <img
              src={previewUrl}
              alt={artifact.title}
              loading="lazy"
              width={256}
              height={140}
              style={{
                maxWidth: '100%',
                maxHeight: '180px',
                objectFit: 'contain',
                borderRadius: 'var(--radius-xs)',
                transition: 'transform var(--transition-fast)',
              }}
              onError={() => setImageError(true)}
            />
          )}
        </div>

        {/* Lỗi xuất tệp nếu có */}
        {exportError && (
          <div
            style={{
              padding: '6px 12px',
              backgroundColor: 'var(--color-danger-subtle)',
              color: 'var(--color-danger)',
              fontSize: 'var(--font-xs)',
              display: 'flex',
              alignItems: 'center',
              gap: '6px',
            }}
          >
            <AlertCircle size={13} />
            <span>{exportError}</span>
          </div>
        )}
      </article>

      {/* Internal Lightbox nếu không có trigger từ parent */}
      {isInternalLightboxOpen && (
        <ArtifactLightbox
          artifact={artifact}
          onClose={() => setIsInternalLightboxOpen(false)}
          triggerRef={viewBtnRef}
        />
      )}
    </>
  );
};
