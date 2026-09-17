import React, { useCallback, useRef, useEffect, Profiler } from 'react';
import { useConversation } from '../hooks/useConversation';
import { useChatStream } from '../hooks/useChatStream';
import { useSpeechSynthesis } from '../../voice/hooks/useSpeechSynthesis';
import { ChatMessageList } from './ChatMessageList';
import { ChatInput } from './ChatInput';
import { ReconnectBanner } from './ReconnectBanner';
import { VisualMetadata, ChatMessage } from '../../../shared/types/common.types';
import { telemetryTracker } from '../../../observability/telemetryTracker';
import { mapApiError } from '../../../shared/utils/errorMapper';
import { SessionBootstrapError } from '../../session/types';
import { AlertCircle, RotateCcw, Loader2 } from 'lucide-react';

interface ChatWindowProps {
  activeSessionId: string;
  initialMessages: ChatMessage[];
  onOpenLightbox: (visual: VisualMetadata) => void;
  onSaveSession: (sessionId: string, messages: ChatMessage[]) => void;
  isSessionReady?: boolean;
  isSessionLoading?: boolean;
  sessionError?: SessionBootstrapError | null;
  onRetrySession?: () => void;
}

export const ChatWindow: React.FC<ChatWindowProps> = ({
  activeSessionId,
  initialMessages,
  onOpenLightbox,
  onSaveSession,
  isSessionReady = true,
  isSessionLoading = false,
  sessionError = null,
  onRetrySession,
}) => {
  const {
    messages,
    addUserMessage,
    addPendingAiMessage,
    updateStreamingContent,
    finalizeAiMessage,
    loadSession,
  } = useConversation(initialMessages);

  const { speak, isSpeaking } = useSpeechSynthesis();

  const currentSessionIdRef = useRef(activeSessionId);
  const onSaveSessionRef = useRef(onSaveSession);
  const sessionMessagesMapRef = useRef<Record<string, ChatMessage[]>>({});

  useEffect(() => {
    currentSessionIdRef.current = activeSessionId;
    onSaveSessionRef.current = onSaveSession;
    sessionMessagesMapRef.current[activeSessionId] = messages;
  }, [activeSessionId, messages, onSaveSession]);

  const { isStreaming, isReconnecting, reconnectAttempt, sendQuery, stopStreaming } = useChatStream({
    onMessageStart: (aiMsgId, sessionId) => {
      if (sessionId === currentSessionIdRef.current) {
        addPendingAiMessage(aiMsgId);
      }
    },
    onTokenChunk: (aiMsgId, fullContent, sessionId) => {
      if (sessionId === currentSessionIdRef.current) {
        updateStreamingContent(aiMsgId, fullContent);
      }
    },
    onMessageComplete: (finishedMsg, sessionId) => {
      if (sessionId === currentSessionIdRef.current) {
        const completeMessages = finalizeAiMessage(finishedMsg);
        sessionMessagesMapRef.current[sessionId] = completeMessages;
        onSaveSessionRef.current(sessionId, completeMessages);
      } else {
        const oldMessages = sessionMessagesMapRef.current[sessionId] || [];
        const exists = oldMessages.some((m) => m.id === finishedMsg.id);
        const updated = exists
          ? oldMessages.map((m) => (m.id === finishedMsg.id ? finishedMsg : m))
          : [...oldMessages, finishedMsg];
        sessionMessagesMapRef.current[sessionId] = updated;
        onSaveSessionRef.current(sessionId, updated);
      }
    },
    onError: (error, sessionId, aiMsgId) => {
      const mapped = mapApiError(error);

      // BẢO VỆ TUYỆT ĐỐI: Không ghi thông báo lỗi bootstrap vào lịch sử hội thoại người dùng
      if (mapped.code === 'SESSION_BOOTSTRAP_FAILED' || error?.message?.includes('SESSION_BOOTSTRAP')) {
        return;
      }

      const errAiMsg: ChatMessage = {
        id: aiMsgId,
        role: 'assistant',
        content: mapped.message,
        timestamp: Date.now(),
        isStreaming: false,
        error: mapped,
      };

      if (sessionId === currentSessionIdRef.current) {
        const completeMessages = finalizeAiMessage(errAiMsg);
        sessionMessagesMapRef.current[sessionId] = completeMessages;
        onSaveSessionRef.current(sessionId, completeMessages);
      } else {
        const oldMessages = sessionMessagesMapRef.current[sessionId] || [];
        const exists = oldMessages.some((m) => m.id === aiMsgId);
        const updated = exists
          ? oldMessages.map((m) => (m.id === aiMsgId ? errAiMsg : m))
          : [...oldMessages, errAiMsg];
        sessionMessagesMapRef.current[sessionId] = updated;
        onSaveSessionRef.current(sessionId, updated);
      }
    },
  });

  const prevSessionIdRef = useRef(activeSessionId);
  useEffect(() => {
    if (prevSessionIdRef.current !== activeSessionId) {
      stopStreaming();
      loadSession(initialMessages || []);
      prevSessionIdRef.current = activeSessionId;
    }
  }, [activeSessionId, initialMessages, stopStreaming, loadSession]);

  const messagesRef = useRef(messages);
  useEffect(() => {
    messagesRef.current = messages;
  }, [messages]);

  const isSendDisabled = isStreaming || !isSessionReady || isSessionLoading || Boolean(sessionError);

  const handleSendMessage = useCallback(
    (questionText: string) => {
      if (isSendDisabled) {
        return;
      }
      const historyPayload = messagesRef.current.map((m) => ({
        role: m.role,
        content: m.content,
      }));

      addUserMessage(questionText);
      sendQuery(questionText, historyPayload, activeSessionId);
    },
    [isSendDisabled, addUserMessage, sendQuery, activeSessionId]
  );

  return (
    <div className="chat-window-container">
      {/* Reconnect Banner */}
      <ReconnectBanner
        isReconnecting={isReconnecting}
        reconnectAttempt={reconnectAttempt}
        onCancel={stopStreaming}
      />

      <Profiler
        id="chat-message-list"
        onRender={(_id, _phase, actualDuration) => {
          telemetryTracker.recordCommitDuration(actualDuration);
        }}
      >
        <ChatMessageList
          messages={messages}
          onOpenLightbox={onOpenLightbox}
          onSelectSuggestion={handleSendMessage}
          onSpeak={speak}
          isSpeaking={isSpeaking}
        />
      </Profiler>

      {/* Session Bootstrap Status & Error Banner */}
      {sessionError && (
        <div
          role="alert"
          aria-live="assertive"
          className="session-error-banner"
        >
          <div className="session-status-copy">
            <span className="session-status-icon" aria-hidden="true">
              <AlertCircle size={18} />
            </span>
            <div className="session-status-text">
              <span className="session-status-title">
                {sessionError.userFriendlyMessage || 'Không thể khởi tạo phiên làm việc. Vui lòng thử lại.'}
              </span>
              {sessionError.requestId && (
                <span className="session-request-id">
                  Mã yêu cầu: <code>{sessionError.requestId.slice(0, 16)}</code>
                </span>
              )}
            </div>
          </div>
          {onRetrySession && (
            <button
              type="button"
              onClick={onRetrySession}
              className="session-retry-button"
              disabled={isSessionLoading}
            >
              {isSessionLoading ? <Loader2 size={14} className="spinner-rotate" aria-hidden="true" /> : <RotateCcw size={14} aria-hidden="true" />}
              <span>{isSessionLoading ? 'Đang thử lại' : 'Thử lại'}</span>
            </button>
          )}
        </div>
      )}

      {isSessionLoading && !sessionError && (
        <div
          role="status"
          aria-live="polite"
          className="session-loading-banner"
        >
          <Loader2 size={14} className="spinner-rotate" aria-hidden="true" />
          <span>Đang chuẩn bị phiên làm việc bảo mật...</span>
        </div>
      )}

      <ChatInput
        onSendMessage={handleSendMessage}
        onStopStreaming={stopStreaming}
        isStreaming={isStreaming}
        disabled={isSendDisabled}
      />
    </div>
  );
};
