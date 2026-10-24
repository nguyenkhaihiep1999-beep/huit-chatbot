import { useState, useCallback, useRef, useEffect } from 'react';
import { ChatMessage } from '../../../shared/types/common.types';
import { generateUniqueId } from '../../../shared/utils/idGenerator';

export function useConversation(initialMessages: ChatMessage[] = []) {
  const [messages, setMessages] = useState<ChatMessage[]>(initialMessages);

  // Ref đồng bộ dữ liệu mới nhất, giải quyết triệt để lỗi Stale Closures trong React
  const messagesRef = useRef<ChatMessage[]>(initialMessages);

  useEffect(() => {
    messagesRef.current = messages;
  }, [messages]);

  const addUserMessage = useCallback((text: string): ChatMessage => {
    const userMsg: ChatMessage = {
      id: generateUniqueId('user'),
      role: 'user',
      content: text,
      timestamp: Date.now(),
    };
    const nextMessages = [...messagesRef.current, userMsg];
    messagesRef.current = nextMessages;
    setMessages(nextMessages);
    return userMsg;
  }, []);

  const addPendingAiMessage = useCallback((aiId: string): ChatMessage => {
    const pendingMsg: ChatMessage = {
      id: aiId,
      role: 'assistant',
      content: '',
      timestamp: Date.now(),
      isStreaming: true,
    };
    const nextMessages = [...messagesRef.current, pendingMsg];
    messagesRef.current = nextMessages;
    setMessages(nextMessages);
    return pendingMsg;
  }, []);

  const updateStreamingContent = useCallback((aiId: string, content: string) => {
    const nextMessages = messagesRef.current.map((msg) =>
      msg.id === aiId ? { ...msg, content } : msg
    );
    messagesRef.current = nextMessages;
    setMessages(nextMessages);
  }, []);

  const finalizeAiMessage = useCallback((finishedMsg: ChatMessage): ChatMessage[] => {
    const currentList = messagesRef.current;
    const exists = currentList.some((m) => m.id === finishedMsg.id);
    let nextMessages: ChatMessage[];
    if (exists) {
      nextMessages = currentList.map((m) =>
        m.id === finishedMsg.id ? finishedMsg : m
      );
    } else {
      nextMessages = [...currentList, finishedMsg];
    }
    messagesRef.current = nextMessages;
    setMessages(nextMessages);
    return nextMessages;
  }, []);

  const loadSession = useCallback((sessionMessages: ChatMessage[]) => {
    const safeMsgs = Array.isArray(sessionMessages) ? sessionMessages : [];
    messagesRef.current = safeMsgs;
    setMessages(safeMsgs);
  }, []);

  const getSnapshot = useCallback((): ChatMessage[] => {
    return [...messagesRef.current];
  }, []);

  return {
    messages,
    addUserMessage,
    addPendingAiMessage,
    updateStreamingContent,
    finalizeAiMessage,
    loadSession,
    setMessages,
    getSnapshot,
  };
}
