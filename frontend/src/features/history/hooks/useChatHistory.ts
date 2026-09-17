import { useCallback } from 'react';
import { useLocalStorage } from '../../../shared/hooks/useLocalStorage';
import { ConversationSession, ChatMessage } from '../../../shared/types/common.types';

/**
 * Làm sạch dữ liệu trước khi lưu vào LocalStorage:
 * - TUYỆT ĐỐI KHÔNG lưu signed URL (tránh URL hết hạn lưu lâu ngày).
 * - TUYỆT ĐỐI KHÔNG lưu token/session secret.
 * - TUYỆT ĐỐI KHÔNG lưu manifest/raw lớn.
 * - Chỉ lưu artifact_id và metadata cần thiết để tải lại khi mở lịch sử.
 */
function sanitizeMessageForStorage(msg: ChatMessage): ChatMessage {
  const sanitized: ChatMessage = {
    id: msg.id,
    role: msg.role,
    content: msg.content,
    timestamp: msg.timestamp,
    isStreaming: false,
    isStopped: Boolean(msg.isStopped),
    cached: msg.cached,
  };

  if (msg.sources && msg.sources.length > 0) {
    sanitized.sources = msg.sources;
  }

  if (msg.artifact) {
    sanitized.artifact = {
      artifact_id: msg.artifact.artifact_id,
      type: msg.artifact.type,
      title: msg.artifact.title,
      status: msg.artifact.status,
      available_formats: msg.artifact.available_formats,
    };
  }

  if (msg.visual) {
    sanitized.visual = {
      visual_id: msg.visual.visual_id,
      artifact_id: msg.visual.artifact_id,
      type: msg.visual.type,
      title: msg.visual.title,
      svg_url: '', // Loại bỏ URL ký số
      png_url: '',
      json_url: '',
    };
  }

  return sanitized;
}

export function useChatHistory() {
  const [sessions, setSessions] = useLocalStorage<ConversationSession[]>('huit_chat_sessions', []);

  const saveSession = useCallback(
    (sessionId: string, messages: ChatMessage[]) => {
      if (!messages || messages.length === 0) return;

      const firstUserMsg = messages.find((m) => m.role === 'user');
      const title = firstUserMsg
        ? firstUserMsg.content.slice(0, 36) + (firstUserMsg.content.length > 36 ? '...' : '')
        : 'Cuộc trò chuyện mới';

      const sanitizedMessages = messages.map(sanitizeMessageForStorage);

      setSessions((prev) => {
        const existingIdx = prev.findIndex((s) => s.sessionId === sessionId);
        const updatedSession: ConversationSession = {
          sessionId,
          title,
          messages: sanitizedMessages,
          createdAt: existingIdx >= 0 ? prev[existingIdx].createdAt : Date.now(),
          updatedAt: Date.now(),
        };

        if (existingIdx >= 0) {
          const next = [...prev];
          next[existingIdx] = updatedSession;
          return next;
        } else {
          return [updatedSession, ...prev];
        }
      });
    },
    [setSessions]
  );

  const deleteSession = useCallback(
    (sessionId: string) => {
      setSessions((prev) => prev.filter((s) => s.sessionId !== sessionId));
    },
    [setSessions]
  );

  const clearAllSessions = useCallback(() => {
    setSessions([]);
  }, [setSessions]);

  return {
    sessions,
    saveSession,
    deleteSession,
    clearAllSessions,
  };
}
