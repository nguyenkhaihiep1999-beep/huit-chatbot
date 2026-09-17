import React, { useState, useRef, useEffect, useCallback } from 'react';
import { Send, Square, Mic, MicOff, GraduationCap, Files, Scale } from 'lucide-react';
import { useSpeechRecognition } from '../../voice/hooks/useSpeechRecognition';

interface ChatInputProps {
  onSendMessage: (text: string) => void;
  onStopStreaming: () => void;
  isStreaming: boolean;
  disabled?: boolean;
}

const QUICK_ACTIONS = [
  { label: 'Tư vấn ngành', icon: GraduationCap, prompt: 'Tư vấn ngành học phù hợp với sở thích của tôi.' },
  { label: 'So sánh học phí', icon: Scale, prompt: 'So sánh học phí các ngành HUIT năm 2026.' },
  { label: 'Tạo tài liệu', icon: Files, prompt: 'Tạo bảng Excel thông tin tuyển sinh HUIT.' },
];

export const ChatInput: React.FC<ChatInputProps> = React.memo(({
  onSendMessage,
  onStopStreaming,
  isStreaming,
  disabled,
}) => {
  const [inputText, setInputText] = useState('');
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const { isListening, toggleListening, isSupported: isVoiceSupported } = useSpeechRecognition(
    (voiceText) => {
      setInputText((prev) => (prev ? `${prev} ${voiceText}` : voiceText));
    }
  );

  const handleSend = useCallback(() => {
    const trimmed = inputText.trim();
    if (!trimmed || isStreaming || disabled) return;
    onSendMessage(trimmed);
    setInputText('');
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto';
    }
  }, [inputText, isStreaming, disabled, onSendMessage]);

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const handleQuickAction = (prompt: string) => {
    if (isStreaming || disabled) return;
    onSendMessage(prompt);
  };

  // Tự động điều chỉnh chiều cao textarea theo nội dung
  useEffect(() => {
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto';
      textareaRef.current.style.height = `${Math.min(textareaRef.current.scrollHeight, 120)}px`;
    }
  }, [inputText]);

  return (
    <div className="chat-composer-wrapper" role="region" aria-label="Soạn tin nhắn">
      <div className="composer-quick-actions" role="group" aria-label="Thao tác nhanh">
        {QUICK_ACTIONS.map(({ label, icon: Icon, prompt }) => (
          <button
            key={label}
            type="button"
            className="composer-quick-action"
            onClick={() => handleQuickAction(prompt)}
            disabled={isStreaming || disabled}
          >
            <Icon size={14} />
            <span>{label}</span>
          </button>
        ))}
      </div>
      <div className="chat-composer-container">
        <textarea
          ref={textareaRef}
          value={inputText}
          onChange={(e) => setInputText(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={
            isListening
              ? '🎙️ Đang lắng nghe bạn nói...'
              : 'Đặt câu hỏi về ngành học, học phí hoặc điểm chuẩn HUIT 2026...'
          }
          className="chat-composer-textarea"
          rows={1}
          disabled={disabled}
          aria-label="Nội dung câu hỏi tuyển sinh HUIT"
        />

        <div className="chat-composer-actions">
          {isVoiceSupported && (
            <button
              type="button"
              className={`composer-btn voice-btn ${isListening ? 'listening' : ''}`}
              onClick={toggleListening}
              title={isListening ? 'Dừng thu âm' : 'Nói bằng giọng nói'}
              aria-label={isListening ? 'Dừng thu âm giọng nói' : 'Nói bằng giọng nói'}
            >
              {isListening ? <MicOff size={18} /> : <Mic size={18} />}
            </button>
          )}

          {isStreaming ? (
            <button
              type="button"
              className="composer-btn stop-stream-btn"
              onClick={onStopStreaming}
              title="Dừng sinh câu trả lời"
              aria-label="Dừng sinh câu trả lời"
            >
              <Square size={14} fill="currentColor" />
              <span className="btn-label-desktop">Dừng</span>
            </button>
          ) : (
            <button
              type="button"
              className="composer-btn send-stream-btn"
              onClick={handleSend}
              disabled={!inputText.trim() || disabled}
              title="Gửi câu hỏi"
              aria-label="Gửi câu hỏi"
            >
              <Send size={16} />
              <span className="send-label">Gửi</span>
            </button>
          )}
        </div>
      </div>
      <div className="composer-footer-hint">
        <span>Enter để gửi · Shift + Enter để xuống dòng · Luôn kiểm tra nguồn trích dẫn</span>
      </div>
    </div>
  );
});
