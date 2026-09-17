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

interface ChatWindowProps {
  activeSessionId: string;
  initialMessages: ChatMessage[];
  onOpenLightbox: (visual: VisualMetadata) => void;
  onSaveSession: (sessionId: string, messages: ChatMessage[]) => void;
}

export const ChatWindow: React.FC<ChatWindowProps> = ({
  activeSessionId,
  initialMessages,
  onOpenLightbox,
  onSaveSession,
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

  const handleSendMessage = useCallback(
    (questionText: string) => {
      const historyPayload = messagesRef.current.map((m) => ({
        role: m.role,
        content: m.content,
      }));

      addUserMessage(questionText);
      sendQuery(questionText, historyPayload, activeSessionId);
    },
    [addUserMessage, sendQuery, activeSessionId]
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

      <ChatInput
        onSendMessage={handleSendMessage}
        onStopStreaming={stopStreaming}
        isStreaming={isStreaming}
      />
    </div>
  );
};
