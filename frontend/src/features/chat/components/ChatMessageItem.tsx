import React, { useMemo, useState } from 'react';
import { Volume2, VolumeX, User, Copy, Check, AlertCircle } from 'lucide-react';
import { ChatMessage, VisualMetadata, ArtifactSummary } from '../../../shared/types/common.types';
import { renderMarkdown } from '../../../shared/lib/markdown';
import { SourceCitations } from './SourceCitations';
import { TraceTimeline } from './TraceTimeline';
import { ArtifactCard } from '../../artifacts/components/ArtifactCard';

interface ChatMessageItemProps {
  message: ChatMessage;
  onOpenLightbox?: (visual: VisualMetadata) => void;
  onSpeak?: (text: string) => void;
  isSpeaking?: boolean;
}

export const ChatMessageItem: React.FC<ChatMessageItemProps> = React.memo(
  ({ message, onOpenLightbox, onSpeak, isSpeaking }) => {
    const isUser = message.role === 'user';
    const [copied, setCopied] = useState(false);

    const renderedHtml = useMemo(() => {
      if (message.isStreaming || !message.content) {
        return '';
      }
      return renderMarkdown(message.content);
    }, [message.content, message.isStreaming]);

    const handleCopy = () => {
      if (!message.content) return;
      navigator.clipboard.writeText(message.content).then(() => {
        setCopied(true);
        setTimeout(() => setCopied(false), 2000);
      });
    };

    // Chuẩn hóa artifact summary từ visual hoặc artifact
    const artifactData: ArtifactSummary | null = useMemo(() => {
      if (message.artifact) {
        return message.artifact;
      }
      if (message.visual) {
        return {
          artifact_id: message.visual.artifact_id || message.visual.visual_id,
          type: message.visual.type || 'chart',
          title: message.visual.title || 'Đồ họa & Dữ liệu Tuyển sinh HUIT',
          preview_url: message.visual.svg_url,
          manifest_url: message.visual.json_url,
          available_formats: message.visual.available_formats || ['svg', 'png', 'pdf', 'xlsx', 'docx'],
          status: message.visual.status || 'ready',
        };
      }
      return null;
    }, [message.artifact, message.visual]);

    const formattedTime = useMemo(() => {
      if (!message.timestamp) return '';
      const d = new Date(message.timestamp);
      return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    }, [message.timestamp]);

    return (
      <div className={`message-item ${message.role}`}>
        <div className={`message-avatar ${isUser ? 'user-avatar' : 'ai-avatar'}`} aria-hidden="true">
          {isUser ? (
            <User size={18} />
          ) : (
            <img src="/huit-ai-mark.svg" alt="" width={30} height={30} className="message-brand-mark" />
          )}
        </div>

        <div className="message-body-wrapper">
          <div className="message-bubble">
            {/* Trường hợp Streaming */}
            {message.isStreaming ? (
              message.content ? (
                <div className="streaming-text-block" role="status" aria-live="polite" aria-atomic="false">
                  {message.content}
                  <span className="streaming-cursor" aria-hidden="true" />
                </div>
              ) : (
                <div className="streaming-placeholder">
                  <span className="mascot-floating">✨</span>
                  <span>Đang tổng hợp thông tin tuyển sinh chính thức...</span>
                </div>
              )
            ) : message.content && (!message.error || message.content !== message.error.message) ? (
              <div
                className="markdown-content"
                dangerouslySetInnerHTML={{ __html: renderedHtml }}
              />
            ) : null}

            {/* Nhãn nếu đã dừng sinh */}
            {message.isStopped && (
              <div className="message-stopped-badge">
                <span>Đã dừng</span>
              </div>
            )}

            {/* Thông báo lỗi nếu có */}
            {message.error && (
              <div className="message-inline-error">
                <AlertCircle size={15} />
                <span>{message.error.message}</span>
              </div>
            )}

            {/* Thẻ Artifact siêu nhẹ (<2KB) */}
            {artifactData && (
              <ArtifactCard
                artifact={artifactData}
                onOpenLightbox={
                  onOpenLightbox
                    ? () =>
                        onOpenLightbox({
                          visual_id: artifactData.artifact_id,
                          artifact_id: artifactData.artifact_id,
                          type: artifactData.type,
                          title: artifactData.title,
                          svg_url: artifactData.preview_url || '',
                          png_url: '',
                          json_url: artifactData.manifest_url || '',
                          available_formats: artifactData.available_formats,
                          status: artifactData.status,
                        })
                    : undefined
                }
              />
            )}

            {/* Trích dẫn Nguồn chính thức */}
            {message.sources && message.sources.length > 0 && (
              <SourceCitations sources={message.sources} />
            )}

            {/* Timeline Tiến trình RAG */}
            {message.trace && message.trace.length > 0 && (
              <TraceTimeline trace={message.trace} cached={message.cached} />
            )}
          </div>

          {/* Footer nhỏ của tin nhắn: Timestamp & Action buttons */}
          <div className="message-meta-footer">
            {formattedTime && <span className="message-timestamp">{formattedTime}</span>}

            {!isUser && !message.isStreaming && message.content && (
              <div className="message-actions">
                <button
                  type="button"
                  onClick={handleCopy}
                  className="msg-action-btn"
                  title="Sao chép câu trả lời"
                  aria-label="Sao chép câu trả lời"
                >
                  {copied ? <Check size={13} color="var(--color-success)" /> : <Copy size={13} />}
                </button>

                {onSpeak && (
                  <button
                    type="button"
                    onClick={() => onSpeak(message.content)}
                    className="msg-action-btn"
                    title={isSpeaking ? 'Dừng đọc' : 'Đọc bằng giọng nói'}
                    aria-label={isSpeaking ? 'Dừng đọc' : 'Đọc bằng giọng nói'}
                  >
                    {isSpeaking ? <VolumeX size={13} /> : <Volume2 size={13} />}
                  </button>
                )}
              </div>
            )}
          </div>
        </div>
      </div>
    );
  }
);
