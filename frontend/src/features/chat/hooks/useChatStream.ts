import { useState, useRef, useCallback, useEffect } from 'react';
import { fetchChatStream, cancelChatStream } from '../api/chatApi';
import { parseNDJSONStream } from '../utils/ndjsonParser';
import { ChatMessage, SourceCitation, TraceStep, VisualMetadata, ArtifactSummary } from '../../../shared/types/common.types';
import { telemetryTracker } from '../../../observability/telemetryTracker';
import { generateUniqueId } from '../../../shared/utils/idGenerator';

export interface UseChatStreamProps {
  onMessageStart?: (aiMessageId: string, sessionId: string, requestId: string) => void;
  onTokenChunk?: (aiMessageId: string, fullContent: string, sessionId: string, requestId: string) => void;
  onMessageComplete?: (aiMessage: ChatMessage, sessionId: string, requestId: string) => void;
  onError?: (error: Error, sessionId: string, aiMessageId: string, requestId: string) => void;
}

export interface StreamRequestContext {
  requestId: string;
  sessionId: string;
  aiMsgId: string;
  controller: AbortController;
  tokenBuffer: string;
  flushTimer: ReturnType<typeof setInterval> | null;
  currentAiMsg: Partial<ChatMessage>;
  completed: boolean;
  aborted: boolean;
  callbackDispatched: boolean;
}

export function useChatStream({
  onMessageStart,
  onTokenChunk,
  onMessageComplete,
  onError,
}: UseChatStreamProps) {
  const [isStreaming, setIsStreaming] = useState(false);
  const [isReconnecting, setIsReconnecting] = useState(false);
  const [reconnectAttempt, setReconnectAttempt] = useState(0);

  const callbacksRef = useRef({
    onMessageStart,
    onTokenChunk,
    onMessageComplete,
    onError,
  });

  useEffect(() => {
    callbacksRef.current = {
      onMessageStart,
      onTokenChunk,
      onMessageComplete,
      onError,
    };
  }, [onMessageStart, onTokenChunk, onMessageComplete, onError]);

  // Request context đang hoạt động duy nhất
  const activeContextRef = useRef<StreamRequestContext | null>(null);

  /**
   * Xả token buffer của một context cụ thể.
   * Xác nhận context này vẫn là active context và chưa hoàn tất.
   */
  const flushContextBuffer = useCallback((ctx: StreamRequestContext) => {
    if (ctx.tokenBuffer.length > 0) {
      const added = ctx.tokenBuffer;
      ctx.tokenBuffer = '';
      ctx.currentAiMsg.content = (ctx.currentAiMsg.content || '') + added;
      telemetryTracker.recordFlush(ctx.requestId);

      // Chỉ thông báo token chunk nếu context này vẫn là active context
      if (activeContextRef.current?.requestId === ctx.requestId && callbacksRef.current.onTokenChunk) {
        callbacksRef.current.onTokenChunk(ctx.aiMsgId, ctx.currentAiMsg.content || '', ctx.sessionId, ctx.requestId);
      }
    }
  }, []);

  /**
   * Dừng streaming đang chạy (Idempotent: gọi nhiều lần chỉ xử lý đúng 1 lần):
   * - Hủy timer của context hiện tại
   * - Xả toàn bộ token còn trong buffer để không bao giờ bị mất token
   * - Gửi tín hiệu abort đến AbortController
   * - Chốt AI message dừng sinh
   */
  const stopStreaming = useCallback(() => {
    const ctx = activeContextRef.current;
    if (!ctx || ctx.completed || ctx.aborted || ctx.callbackDispatched) {
      return;
    }

    ctx.aborted = true;
    if (ctx.flushTimer !== null) {
      clearInterval(ctx.flushTimer);
      ctx.flushTimer = null;
    }

    // Xả hết token buffer trước khi dừng
    flushContextBuffer(ctx);
    ctx.controller.abort();
    cancelChatStream(ctx.requestId).catch(() => {});

    // Chốt tin nhắn dừng duy nhất 1 lần
    if (!ctx.callbackDispatched) {
      ctx.callbackDispatched = true;
      ctx.completed = true;

      const stoppedContent = (ctx.currentAiMsg.content || '') + ' _[Đã dừng sinh]_';
      ctx.currentAiMsg.content = stoppedContent;

      telemetryTracker.abortTrace(ctx.requestId);

      const stoppedMsg: ChatMessage = {
        id: ctx.aiMsgId,
        role: 'assistant',
        content: stoppedContent,
        sources: ctx.currentAiMsg.sources || [],
        trace: ctx.currentAiMsg.trace || [],
        visual: ctx.currentAiMsg.visual || null,
        artifact: ctx.currentAiMsg.artifact || null,
        cached: ctx.currentAiMsg.cached,
        timestamp: Date.now(),
        isStreaming: false,
      };

      if (callbacksRef.current.onMessageComplete) {
        callbacksRef.current.onMessageComplete(stoppedMsg, ctx.sessionId, ctx.requestId);
      }
    }

    activeContextRef.current = null;
    setIsStreaming(false);
  }, [flushContextBuffer]);

  const sendQuery = useCallback(
    async (
      question: string,
      history: Array<{ role: 'user' | 'assistant'; content: string }> = [],
      sessionId: string
    ) => {
      // 1. Nếu có request cũ đang chạy, chốt đúng một lần và dọn dẹp an toàn
      const prevCtx = activeContextRef.current;
      if (prevCtx && !prevCtx.completed && !prevCtx.aborted) {
        prevCtx.aborted = true;
        if (prevCtx.flushTimer !== null) {
          clearInterval(prevCtx.flushTimer);
          prevCtx.flushTimer = null;
        }
        flushContextBuffer(prevCtx);
        prevCtx.controller.abort();

        if (!prevCtx.callbackDispatched) {
          prevCtx.callbackDispatched = true;
          prevCtx.completed = true;
          telemetryTracker.abortTrace(prevCtx.requestId);

          const stoppedMsg: ChatMessage = {
            id: prevCtx.aiMsgId,
            role: 'assistant',
            content: (prevCtx.currentAiMsg.content || '') + ' _[Đã dừng sinh]_',
            sources: prevCtx.currentAiMsg.sources || [],
            trace: prevCtx.currentAiMsg.trace || [],
            visual: prevCtx.currentAiMsg.visual || null,
            artifact: prevCtx.currentAiMsg.artifact || null,
            cached: prevCtx.currentAiMsg.cached,
            timestamp: Date.now(),
            isStreaming: false,
          };

          if (callbacksRef.current.onMessageComplete) {
            callbacksRef.current.onMessageComplete(stoppedMsg, prevCtx.sessionId, prevCtx.requestId);
          }
        }
      }

      // 2. Tạo context riêng biệt độc lập cho request mới này
      const aiMsgId = generateUniqueId('ai');
      const requestId = generateUniqueId('req-fe');
      const controller = new AbortController();

      const newCtx: StreamRequestContext = {
        requestId,
        sessionId,
        aiMsgId,
        controller,
        tokenBuffer: '',
        flushTimer: null,
        currentAiMsg: {
          id: aiMsgId,
          role: 'assistant',
          content: '',
          sources: [],
          trace: [],
          visual: null,
          timestamp: Date.now(),
          isStreaming: true,
        },
        completed: false,
        aborted: false,
        callbackDispatched: false,
      };

      activeContextRef.current = newCtx;
      setIsStreaming(true);

      // Khởi tạo telemetry trace (ẩn danh, không ghi lại câu hỏi)
      telemetryTracker.startTrace(requestId);

      // Thông báo tạo tin nhắn AI chờ phản hồi
      if (callbacksRef.current.onMessageStart) {
        callbacksRef.current.onMessageStart(aiMsgId, sessionId, requestId);
      }

      // Khởi tạo flush timer gắn riêng cho context này
      newCtx.flushTimer = setInterval(() => {
        // Chỉ flush nếu context này vẫn khớp active context
        if (activeContextRef.current?.requestId === newCtx.requestId && !newCtx.completed && !newCtx.aborted) {
          flushContextBuffer(newCtx);
        }
      }, 35);

      let protocolVersion = 1;
      let expectedSequence = 1;
      let lastReceivedSequence = 0;
      let hasCompletedEvent = false;
      let streamError: Error | null = null;
      let reconnectAttempt = 0;
      const MAX_RECONNECT_ATTEMPTS = 2;
      const seenEventKeys = new Set<string>();

      try {
        while (reconnectAttempt <= MAX_RECONNECT_ATTEMPTS && !hasCompletedEvent && !newCtx.aborted) {
          try {
            const response = await fetchChatStream({
              question,
              history,
              signal: controller.signal,
              requestId,
              lastSequence: lastReceivedSequence > 0 ? lastReceivedSequence : undefined,
            });

            await parseNDJSONStream(
              response,
              (chunk) => {
                // Xác nhận requestId vẫn khớp context hiện tại; loại bỏ mọi response cũ trả về muộn
                if (activeContextRef.current?.requestId !== requestId || newCtx.aborted) {
                  return;
                }

                if (chunk.protocol_version) {
                  protocolVersion = chunk.protocol_version;
                }

                // Protocol v2 đặt toàn bộ dữ liệu domain trong payload. Fallback giữ khả năng đọc v1.
                const payload: Record<string, any> =
                  chunk.payload ?? (chunk as unknown as Record<string, any>);

                if (chunk.sequence !== undefined) {
                  const eventKey = `${chunk.stream_id || requestId}:${chunk.sequence}`;
                  if (seenEventKeys.has(eventKey) || chunk.sequence <= lastReceivedSequence) {
                    // Bỏ qua các chunk trùng lặp hoặc replayed khi reconnect
                    return;
                  }
                  seenEventKeys.add(eventKey);

                  if (chunk.sequence > expectedSequence) {
                    console.warn(`[NDJSON v2] Phát hiện khoảng trống chuỗi (Sequence Gap): mong đợi ${expectedSequence}, nhận ${chunk.sequence}`);
                  }
                  expectedSequence = chunk.sequence + 1;
                  lastReceivedSequence = chunk.sequence;
                }

                if (chunk.type === 'start' || chunk.type === 'stream_started') {
                  // Phiên stream bắt đầu
                } else if (chunk.type === 'progress' || chunk.type === 'meta') {
                  // GÓI TIN TIẾN TRÌNH / META: Không tính dòng này là Content TTFT!
                  newCtx.currentAiMsg.sources = (payload.sources as SourceCitation[]) || [];
                  newCtx.currentAiMsg.trace = (payload.trace as TraceStep[]) || [];
                  if (payload.visual) {
                    newCtx.currentAiMsg.visual = payload.visual as VisualMetadata;
                  }
                  newCtx.currentAiMsg.cached = Boolean(payload.cached);
                  if (payload.cached) {
                    telemetryTracker.setCached(requestId, true);
                  }
                } else if (chunk.type === 'sources') {
                  newCtx.currentAiMsg.sources = (payload.sources as SourceCitation[]) || [];
                } else if (chunk.type === 'artifact' || chunk.type === 'artifact_planned') {
                  // Lập tức hiển thị thẻ artifact dự kiến cho người dùng
                  const plannedId = payload.artifact_id || 'planned_artifact';
                  const summary: ArtifactSummary = {
                    artifact_id: plannedId,
                    type: payload.type || payload.artifact_type || payload.file_type || 'chart',
                    title: payload.title || 'Biểu đồ Tuyển sinh & Học phí',
                    preview_url: payload.preview_url || '',
                    manifest_url: payload.manifest_url || '',
                    available_formats: payload.available_formats || ['svg', 'png', 'pdf', 'xlsx', 'docx'],
                    status: (payload.status as 'planned' | 'ready') || 'planned',
                  };
                  newCtx.currentAiMsg.artifact = summary;
                  if (!newCtx.currentAiMsg.visual) {
                    newCtx.currentAiMsg.visual = {
                      visual_id: plannedId,
                      artifact_id: plannedId,
                      title: summary.title,
                      type: summary.type,
                      svg_url: summary.preview_url || '',
                      png_url: '',
                      json_url: summary.manifest_url || '',
                      available_formats: summary.available_formats,
                      status: 'planned',
                    };
                  }
                } else if (chunk.type === 'preview_ready') {
                  if (newCtx.currentAiMsg.artifact) {
                    newCtx.currentAiMsg.artifact.status = 'ready';
                    if (payload.preview_url) {
                      newCtx.currentAiMsg.artifact.preview_url = payload.preview_url;
                    }
                  }
                  if (payload.visual) {
                    newCtx.currentAiMsg.visual = payload.visual as VisualMetadata;
                  } else if (newCtx.currentAiMsg.visual && payload.preview_url) {
                    newCtx.currentAiMsg.visual.svg_url = payload.preview_url;
                    newCtx.currentAiMsg.visual.status = 'ready';
                  }
                } else if (chunk.type === 'token' || chunk.type === 'text_delta') {
                  const tok = payload.token ?? payload.delta ?? '';
                  // Ghi nhận Content TTFT cho token văn bản đầu tiên
                  telemetryTracker.recordContentToken(requestId, tok);
                  newCtx.tokenBuffer += tok;
                } else if (chunk.type === 'text_completed') {
                  flushContextBuffer(newCtx);
                } else if (chunk.type === 'heartbeat') {
                  // Nhịp tim duy trì kết nối
                } else if (chunk.type === 'error') {
                  streamError = new Error(payload.message || `Lỗi máy chủ: ${payload.error_code}`);
                } else if (chunk.type === 'cancelled') {
                  newCtx.aborted = true;
                  streamError = new Error(payload.detail || 'Yêu cầu đã được hủy');
                } else if (chunk.type === 'done' || chunk.type === 'completed') {
                  hasCompletedEvent = true;
                }
              },
              controller.signal
            );


            // Quy tắc v2: Nếu luồng v2 kết thúc mà chưa nhận completed event
            if (protocolVersion === 2 && !hasCompletedEvent && !newCtx.aborted) {
              throw new Error('Mất kết nối với máy chủ trước khi hoàn thành luồng dữ liệu (Stream interrupted).');
            }

            break;
          } catch (innerErr: unknown) {
            const isAbort =
              (innerErr instanceof Error && innerErr.name === 'AbortError') ||
              (innerErr instanceof DOMException && innerErr.name === 'AbortError');
            if (isAbort || newCtx.aborted) {
              throw innerErr;
            }

            const errMsg = innerErr instanceof Error ? innerErr.message : String(innerErr);
            const isRetryableFailure =
              errMsg.includes('Stream interrupted') ||
              !/^HTTP 4\d\d:/.test(errMsg);

            if (protocolVersion === 2 && isRetryableFailure && reconnectAttempt < MAX_RECONNECT_ATTEMPTS) {
              reconnectAttempt++;
              setIsReconnecting(true);
              setReconnectAttempt(reconnectAttempt);
              const backoffMs = Math.min(300 * Math.pow(2, reconnectAttempt) + Math.random() * 200, 2000);
              console.warn(`[NDJSON v2] Sự cố gián đoạn (${errMsg}). Thử kết nối lại lần ${reconnectAttempt} sau ${Math.round(backoffMs)}ms với sequence > ${lastReceivedSequence}...`);
              await new Promise((res) => setTimeout(res, backoffMs));
              continue;
            }
            throw innerErr;
          }
        }

        // Kiểm tra lại tính hợp lệ trước khi hoàn tất
        if (activeContextRef.current?.requestId !== requestId || newCtx.aborted || newCtx.callbackDispatched) {
          return;
        }

        if (streamError) {
          throw streamError;
        }

        // Quy tắc v2: Không bao giờ coi EOF là hoàn thành nếu chưa nhận sự kiện completed
        if (protocolVersion === 2 && !hasCompletedEvent) {
          flushContextBuffer(newCtx);
          throw new Error('Mất kết nối với máy chủ trước khi hoàn thành luồng dữ liệu (Stream interrupted).');
        }

        // Xả toàn bộ token còn sót trong buffer để không bao giờ bị mất token cuối
        flushContextBuffer(newCtx);
        newCtx.completed = true;
        newCtx.callbackDispatched = true;

        telemetryTracker.finishTrace(requestId, newCtx.currentAiMsg.cached);

        const finishedMsg: ChatMessage = {
          id: aiMsgId,
          role: 'assistant',
          content: newCtx.currentAiMsg.content || '',
          sources: newCtx.currentAiMsg.sources || [],
          trace: newCtx.currentAiMsg.trace || [],
          visual: newCtx.currentAiMsg.visual || null,
          artifact: newCtx.currentAiMsg.artifact || null,
          cached: newCtx.currentAiMsg.cached,
          timestamp: Date.now(),
          isStreaming: false,
        };

        if (callbacksRef.current.onMessageComplete) {
          callbacksRef.current.onMessageComplete(finishedMsg, sessionId, requestId);
        }
      } catch (err: unknown) {
        if (newCtx.callbackDispatched) {
          return;
        }

        const isAbort =
          (err instanceof Error && err.name === 'AbortError') ||
          (err instanceof DOMException && err.name === 'AbortError');

        if (isAbort) {
          // Xả hết token buffer nếu có trước khi hoàn tất abort
          flushContextBuffer(newCtx);
          telemetryTracker.abortTrace(requestId);

          if (activeContextRef.current?.requestId === requestId && !newCtx.callbackDispatched) {
            newCtx.completed = true;
            newCtx.callbackDispatched = true;
            const stoppedMsg: ChatMessage = {
              id: aiMsgId,
              role: 'assistant',
              content: (newCtx.currentAiMsg.content || '') + ' _[Đã dừng sinh]_',
              sources: newCtx.currentAiMsg.sources || [],
              trace: newCtx.currentAiMsg.trace || [],
              visual: newCtx.currentAiMsg.visual || null,
              artifact: newCtx.currentAiMsg.artifact || null,
              timestamp: Date.now(),
              isStreaming: false,
            };
            if (callbacksRef.current.onMessageComplete) {
              callbacksRef.current.onMessageComplete(stoppedMsg, sessionId, requestId);
            }
          }
        } else {
          const errorObj = err instanceof Error ? err : new Error(String(err));
          telemetryTracker.abortTrace(requestId);
          if (activeContextRef.current?.requestId === requestId && !newCtx.callbackDispatched) {
            newCtx.completed = true;
            newCtx.callbackDispatched = true;
            if (callbacksRef.current.onError) {
              callbacksRef.current.onError(errorObj, sessionId, aiMsgId, requestId);
            }
          }
        }
      } finally {
        // DỌN DẸP AN TOÀN:
        // 1. Chỉ dọn timer của chính newCtx, không chạm timer của request mới nếu đã bị thay thế
        if (newCtx.flushTimer !== null) {
          clearInterval(newCtx.flushTimer);
          newCtx.flushTimer = null;
        }

        // 2. Chỉ cập nhật isStreaming và xóa activeContextRef nếu context này vẫn là active context!
        if (activeContextRef.current?.requestId === requestId) {
          activeContextRef.current = null;
          setIsStreaming(false);
          setIsReconnecting(false);
          setReconnectAttempt(0);
        }
      }
    },
    [flushContextBuffer]
  );

  // Dọn dẹp an toàn khi component unmount: không làm mất dữ liệu token đã nhận
  useEffect(() => {
    return () => {
      const ctx = activeContextRef.current;
      if (ctx && !ctx.completed && !ctx.aborted) {
        ctx.aborted = true;
        if (ctx.flushTimer !== null) {
          clearInterval(ctx.flushTimer);
          ctx.flushTimer = null;
        }
        flushContextBuffer(ctx);
        ctx.controller.abort();

        if (!ctx.callbackDispatched) {
          ctx.callbackDispatched = true;
          ctx.completed = true;
          telemetryTracker.abortTrace(ctx.requestId);

          const stoppedMsg: ChatMessage = {
            id: ctx.aiMsgId,
            role: 'assistant',
            content: (ctx.currentAiMsg.content || '') + ' _[Đã dừng sinh]_',
            sources: ctx.currentAiMsg.sources || [],
            trace: ctx.currentAiMsg.trace || [],
            visual: ctx.currentAiMsg.visual || null,
            artifact: ctx.currentAiMsg.artifact || null,
            timestamp: Date.now(),
            isStreaming: false,
          };

          if (callbacksRef.current.onMessageComplete) {
            callbacksRef.current.onMessageComplete(stoppedMsg, ctx.sessionId, ctx.requestId);
          }
        }
      }
      activeContextRef.current = null;
      callbacksRef.current = {
        onMessageStart: undefined,
        onTokenChunk: undefined,
        onMessageComplete: undefined,
        onError: undefined,
      };
    };
  }, [flushContextBuffer]);

  return {
    isStreaming,
    isReconnecting,
    reconnectAttempt,
    sendQuery,
    stopStreaming,
  };
}
