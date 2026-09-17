import React, { useRef, useEffect } from 'react';
import {
  Sparkles,
  GraduationCap,
  DollarSign,
  BookOpen,
  Award,
  ShieldCheck,
  FileOutput,
  Zap,
} from 'lucide-react';
import { ChatMessage, VisualMetadata } from '../../../shared/types/common.types';
import { ChatMessageItem } from './ChatMessageItem';

interface ChatMessageListProps {
  messages: ChatMessage[];
  onOpenLightbox?: (visual: VisualMetadata) => void;
  onSelectSuggestion?: (question: string) => void;
  onSpeak?: (text: string) => void;
  isSpeaking?: boolean;
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
}) => {
  const bottomRef = useRef<HTMLDivElement>(null);
  const safeMessages = Array.isArray(messages) ? messages : [];

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
              <GraduationCap size={30} />
            </div>
            <div className="empty-state-eyebrow">
              <span className="status-dot online" aria-hidden="true" />
              Trợ lý tuyển sinh chính thức 2026
            </div>

            <h2 className="empty-state-title">
              Chào mừng bạn đến với HUIT! <span aria-hidden="true">🎓</span>
            </h2>
            <p className="empty-state-description">
              Tra cứu thông tin tuyển sinh, so sánh ngành học và tạo tài liệu trực quan
              từ nguồn dữ liệu của <strong>Trường Đại học Công Thương TP.HCM</strong>.
            </p>
          </div>

          <div className="capability-strip" aria-label="Tiện ích nổi bật">
            <span><ShieldCheck size={14} /> Nguồn có kiểm chứng</span>
            <span><FileOutput size={14} /> Excel · Word · PDF · Ảnh</span>
            <span><Zap size={14} /> Trả lời trực tuyến</span>
          </div>

          <div className="suggestions-heading">
            <span>Bắt đầu nhanh</span>
            <small>Chọn một nhu cầu phổ biến</small>
          </div>
          <div className="empty-state-suggestions" role="group" aria-label="Câu hỏi gợi ý">
            {PRACTICAL_SUGGESTIONS.map((item) => {
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
