import React, { useRef, useEffect } from 'react';
import {
  Sparkles,
  DollarSign,
  BookOpen,
  Award,
  ShieldCheck,
  FileOutput,
  Zap,
} from 'lucide-react';
import { ChatMessage, VisualMetadata, KnowledgeProfileUI } from '../../../shared/types/common.types';
import { ChatMessageItem } from './ChatMessageItem';

interface ChatMessageListProps {
  messages: ChatMessage[];
  onOpenLightbox?: (visual: VisualMetadata) => void;
  onSelectSuggestion?: (question: string) => void;
  onSpeak?: (text: string) => void;
  isSpeaking?: boolean;
  profile?: KnowledgeProfileUI | null;
}

const PRACTICAL_SUGGESTIONS = [
  {
    icon: DollarSign,
    text: 'Học phí HUIT năm 2026 là bao nhiêu?',
    badge: 'Học phí',
  },
  {
    icon: BookOpen,
    text: 'Cho tôi danh sách ngành tuyển sinh.',
    badge: '39 Ngành học',
  },
  {
    icon: Sparkles,
    text: 'Tạo bảng Excel học phí các ngành.',
    badge: 'Xuất file Excel',
  },
  {
    icon: Award,
    text: 'Điểm chuẩn ngành Công nghệ thông tin?',
    badge: 'Điểm sàn & chuẩn',
  },
];

export const ChatMessageList: React.FC<ChatMessageListProps> = ({
  messages,
  onOpenLightbox,
  onSelectSuggestion,
  onSpeak,
  isSpeaking,
  profile,
}) => {
  const bottomRef = useRef<HTMLDivElement>(null);
  const safeMessages = Array.isArray(messages) ? messages : [];

  const isIlt = profile?.profile_id === 'ilt';
  const eyebrowText = isIlt ? (profile?.eyebrow || 'Dữ liệu Catalogue ILT 2026') : 'Dữ liệu tuyển sinh HUIT 2026';
  const heroTitle = isIlt ? (profile?.empty_title || 'Chiếu sáng kiến trúc. Chuẩn mực quốc tế.') : 'Hỏi đúng. Hiểu rõ. Chọn ngành tự tin.';
  const heroDesc = isIlt
    ? (profile?.empty_description || 'Tra cứu thông số kỹ thuật đèn bàn, đèn sàn, đèn thả, đèn chùm, năng lực OEM/ODM và tiêu chuẩn xuất khẩu từ Innovative Lighting Technologies.')
    : null;

  const suggestionsToDisplay = isIlt && profile?.suggestions?.length
    ? profile.suggestions.map((s, idx) => ({
        icon: [BookOpen, Sparkles, ShieldCheck, Zap][idx % 4] || Sparkles,
        text: s.text,
        badge: s.badge,
      }))
    : PRACTICAL_SUGGESTIONS;

  useEffect(() => {
    const list = Array.isArray(messages) ? messages : [];
    const lastMsg = list[list.length - 1];
    const isStreaming = Boolean(lastMsg?.isStreaming);
    bottomRef.current?.scrollIntoView({ behavior: isStreaming ? 'auto' : 'smooth' });
  }, [messages]);

  if (safeMessages.length === 0) {
    return (
      <div className="chat-messages-container empty-state-container" role="region" aria-label="Khu vực tin nhắn">
        <div className="empty-state-content animate-fade-in">
          <div className="empty-state-hero">
            <div className="empty-state-icon-box" aria-hidden="true">
              <img src={isIlt ? '/ilt-brand-mark.svg' : '/huit-ai-mark.svg'} alt="" width={64} height={64} className="empty-state-brand-mark" />
            </div>
            <div className="empty-state-eyebrow">
              <span className="status-dot online" aria-hidden="true" />
              {eyebrowText}
            </div>

            <h2 className="empty-state-title">
              {heroTitle}
            </h2>
            {heroDesc ? (
              <p className="empty-state-description">{heroDesc}</p>
            ) : (
              <p className="empty-state-description">
                Tra cứu học phí, điểm chuẩn, ngành học và tạo tài liệu trực quan từ
                nguồn dữ liệu của <strong>Trường Đại học Công Thương TP.HCM</strong>.
              </p>
            )}
          </div>

          {isIlt ? (
            <div className="capability-strip ilt-capability-strip" aria-label="Chứng nhận & năng lực xuất khẩu">
              <span><ShieldCheck size={14} /> Tiêu chuẩn UL · ETL · CE · ISO 9001</span>
              <span><Sparkles size={14} /> OEM/ODM Bắc Mỹ & Châu Âu</span>
              <span><Zap size={14} /> Tra cứu Catalogue 2026</span>
            </div>
          ) : (
            <div className="capability-strip" aria-label="Tiện ích nổi bật">
              <span><ShieldCheck size={14} /> Nguồn có kiểm chứng</span>
              <span><FileOutput size={14} /> Excel · Word · PDF · Ảnh</span>
              <span><Zap size={14} /> Trả lời trực tuyến</span>
            </div>
          )}

          <div className="suggestions-heading">
            <span>Bắt đầu nhanh</span>
            <small>Chọn một nhu cầu phổ biến</small>
          </div>
          <div className="empty-state-suggestions" role="group" aria-label="Câu hỏi gợi ý">
            {suggestionsToDisplay.map((item) => {
              const Icon = item.icon;
              return (
                <button
                  key={item.text}
                  type="button"
                  className="suggestion-chip-btn"
                  onClick={() => onSelectSuggestion && onSelectSuggestion(item.text)}
                  aria-label={`Hỏi gợi ý: ${item.text}`}
                >
                  <div className="suggestion-icon-wrapper">
                    <Icon size={16} />
                  </div>
                  <div className="suggestion-text-wrapper">
                    <span className="suggestion-text">{item.text}</span>
                    <span className="suggestion-badge">{item.badge}</span>
                  </div>
                  <span className="suggestion-arrow" aria-hidden="true">→</span>
                </button>
              );
            })}
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="chat-messages-container" role="log" aria-live="polite" aria-label="Cuộc trò chuyện">
      {safeMessages.map((msg) => (
        <ChatMessageItem
          key={msg.id}
          message={msg}
          onOpenLightbox={onOpenLightbox}
          onSpeak={onSpeak}
          isSpeaking={isSpeaking}
        />
      ))}
      <div ref={bottomRef} style={{ height: '4px' }} />
    </div>
  );
};
