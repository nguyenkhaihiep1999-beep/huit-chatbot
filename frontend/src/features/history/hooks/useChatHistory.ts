import { useCallback, useMemo } from 'react';
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
      error_message: msg.artifact.error_message,
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
      status: msg.visual.status,
      error_message: msg.visual.error_message,
    };
  }

  return sanitized;
}

const LEGACY_RESOURCE_MESSAGE = 'Tài liệu được tạo từ phiên trước. Hãy đặt lại yêu cầu trong phiên hiện tại để tạo bản mới.';

function sanitizeLegacyMessageForDisplay(msg: ChatMessage): ChatMessage {
  const next: ChatMessage = { ...msg };
  if (msg.artifact) {
    next.artifact = {
      ...msg.artifact,
      preview_url: undefined,
      manifest_url: undefined,
      owner_id: null,
      status: 'unavailable',
      error_message: LEGACY_RESOURCE_MESSAGE,
    };
  }
  if (msg.visual) {
    next.visual = {
      ...msg.visual,
      svg_url: '',
      png_url: '',
      xlsx_url: undefined,
      docx_url: undefined,
      pdf_url: undefined,
      json_url: '',
      status: 'unavailable',
      error_message: LEGACY_RESOURCE_MESSAGE,
    };
  }
  return next;
}

export function useChatHistory(ownerScope: string) {
  const [storedSessions, setStoredSessions] = useLocalStorage<ConversationSession[]>('huit_chat_sessions', []);

  const sessions = useMemo(() => {
    if (!ownerScope) return [];
    return storedSessions
      .filter((session) => !session.ownerScope || session.ownerScope === ownerScope)
      .map((session) => {
        if (session.ownerScope) return session;
        return {
          ...session,
          messages: session.messages.map(sanitizeLegacyMessageForDisplay),
        };
      });
  }, [ownerScope, storedSessions]);

  const saveSession = useCallback(
    (sessionId: string, messages: ChatMessage[]) => {
      if (!ownerScope || !messages || messages.length === 0) return;

      const firstUserMsg = messages.find((m) => m.role === 'user');
      const title = firstUserMsg
        ? firstUserMsg.content.slice(0, 36) + (firstUserMsg.content.length > 36 ? '...' : '')
        : 'Cuộc trò chuyện mới';

      const sanitizedMessages = messages.map(sanitizeMessageForStorage);

      setStoredSessions((prev) => {
        const existingIdx = prev.findIndex(
          (session) =>
            session.sessionId === sessionId &&
            (!session.ownerScope || session.ownerScope === ownerScope)
        );
        const updatedSession: ConversationSession = {
          sessionId,
          ownerScope,
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
    [ownerScope, setStoredSessions]
  );

  const deleteSession = useCallback(
    (sessionId: string) => {
      setStoredSessions((prev) =>
        prev.filter(
          (session) =>
            session.sessionId !== sessionId ||
            Boolean(session.ownerScope && session.ownerScope !== ownerScope)
        )
      );
    },
    [ownerScope, setStoredSessions]
  );

  const clearAllSessions = useCallback(() => {
    setStoredSessions((prev) =>
      prev.filter((session) => Boolean(session.ownerScope && session.ownerScope !== ownerScope))
    );
  }, [ownerScope, setStoredSessions]);

  return {
    sessions,
    saveSession,
    deleteSession,
    clearAllSessions,
  };
}
