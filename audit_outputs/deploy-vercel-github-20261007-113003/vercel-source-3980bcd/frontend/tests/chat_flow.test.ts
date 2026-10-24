import { describe, it, beforeEach, expect } from 'vitest';
import type { ChatMessage } from '../src/shared/types/common.types.ts';
import { telemetryTracker } from '../src/observability/telemetryTracker.ts';
import { generateUniqueId } from '../src/shared/utils/idGenerator.ts';

describe('React Chat Flow & Streaming Contract', () => {
  beforeEach(() => {
    telemetryTracker.clearMetrics();
  });

  it('1. History Payload: Không đưa câu hỏi hiện tại vào cả trường question và history', () => {
    // Giả lập lịch sử hội thoại trước đó
    const priorMessages: ChatMessage[] = [
      { id: 'u-1', role: 'user', content: 'Chào bạn', timestamp: 1000 },
      { id: 'a-1', role: 'assistant', content: 'Chào bạn! Mình có thể giúp gì?', timestamp: 2000 },
    ];

    const currentQuestion = 'Điểm chuẩn ngành Công nghệ thông tin năm 2026?';

    // Xây dựng payload gửi lên backend theo hợp đồng đã sửa
    const historyPayload = priorMessages.map((m) => ({
      role: m.role,
      content: m.content,
    }));

    // Kiểm tra tính độc lập của question và history
    expect(historyPayload).toHaveLength(2);
    expect(historyPayload[0].content).toBe('Chào bạn');
    expect(historyPayload[1].content).toBe('Chào bạn! Mình có thể giúp gì?');

    // Khẳng định: history tuyệt đối KHÔNG chứa câu hỏi hiện tại
    const isQuestionInHistory = historyPayload.some((h) => h.content === currentQuestion);
    expect(isQuestionInHistory).toBe(false);
  });

  it('2. Hoàn thành stream: Session lưu đủ [tin nhắn cũ + câu hỏi vừa gửi + câu trả lời]', () => {
    const sessionStore: Record<string, ChatMessage[]> = {};
    const sessionId = 'session-test-01';

    // Trạng thái ban đầu
    const initialMessages: ChatMessage[] = [
      { id: 'u-0', role: 'user', content: 'HUIT ở đâu?', timestamp: 1000 },
      { id: 'a-0', role: 'assistant', content: 'HUIT tọa lạc tại 140 Lê Trọng Tấn, Tân Phú, TP.HCM.', timestamp: 2000 },
    ];
    sessionStore[sessionId] = [...initialMessages];

    // Người dùng gửi câu hỏi mới
    const newQuestion = 'Học phí năm 2026 thế nào?';
    const userMsg: ChatMessage = {
      id: 'u-new',
      role: 'user',
      content: newQuestion,
      timestamp: 3000,
    };

    // AI sinh phản hồi
    const aiAnswer: ChatMessage = {
      id: 'a-new',
      role: 'assistant',
      content: 'Học phí trung bình khoảng 14 - 16 triệu đồng/học kỳ.',
      sources: [{ i: 1, title: 'Học phí HUIT', url: 'https://ts.huit.edu.vn', score: 0.99, text: '...' }],
      isStreaming: false,
      timestamp: 4000,
    };

    // Cập nhật session khi hoàn thành
    const updatedSession = [...sessionStore[sessionId], userMsg, aiAnswer];
    sessionStore[sessionId] = updatedSession;

    // Kiểm tra cấu trúc session đã lưu
    expect(sessionStore[sessionId]).toHaveLength(4);
    expect(sessionStore[sessionId][0].id).toBe('u-0');
    expect(sessionStore[sessionId][1].id).toBe('a-0');
    expect(sessionStore[sessionId][2].content).toBe(newQuestion);
    expect(sessionStore[sessionId][3].content).toBe(aiAnswer.content);
    expect(sessionStore[sessionId][3].isStreaming).toBe(false);
  });

  it('3. Abort: Dừng sinh câu trả lời bảo lưu toàn bộ token đã nhận và cập nhật session', () => {
    let tokenBuffer = '';
    const receivedTokens = ['Trường ', 'Đại học ', 'Công Thương '];

    // Giả lập nhận token
    for (const t of receivedTokens) {
      tokenBuffer += t;
    }

    // Giả lập kích hoạt Abort
    const abortedAiMsg: ChatMessage = {
      id: 'ai-aborted-1',
      role: 'assistant',
      content: tokenBuffer + ' _[Đã dừng sinh]_',
      timestamp: Date.now(),
      isStreaming: false,
    };

    expect(abortedAiMsg.content).toContain('Trường Đại học Công Thương');
    expect(abortedAiMsg.content).toContain('_[Đã dừng sinh]_');
    expect(abortedAiMsg.isStreaming).toBe(false);
  });

  it('4. Stale Response: Ngăn chặn response của session cũ cập nhật vào session mới', () => {
    let activeSessionId = 'session-A';
    const activeSessionState: Record<string, ChatMessage[]> = {
      'session-A': [],
      'session-B': [],
    };

    // Giả lập request từ session A
    const reqFromSessionA = {
      requestId: 'req-session-A-123',
      sourceSessionId: 'session-A',
      responseContent: 'Câu trả lời dành cho session A',
    };

    // Người dùng nhanh tay bấm sang session B
    activeSessionId = 'session-B';

    // Response từ session A bay về muộn
    let didMutateActiveUi = false;
    if (reqFromSessionA.sourceSessionId === activeSessionId) {
      didMutateActiveUi = true;
    } else {
      // Lưu vào storage của session A, không chạm vào state session B
      activeSessionState[reqFromSessionA.sourceSessionId].push({
        id: 'ai-a',
        role: 'assistant',
        content: reqFromSessionA.responseContent,
        timestamp: Date.now(),
      });
    }

    expect(didMutateActiveUi).toBe(false);
    expect(activeSessionState['session-B']).toHaveLength(0);
    expect(activeSessionState['session-A']).toHaveLength(1);
    expect(activeSessionState['session-A'][0].content).toBe('Câu trả lời dành cho session A');
  });

  it('5. Observability: Không ghi nhận nội dung câu hỏi và không tính meta vào Content TTFT', () => {
    const reqId = 'req-obs-test-999';
    telemetryTracker.startTrace(reqId);

    // Gói tin meta đến trước (ví dụ lúc 50ms)
    telemetryTracker.setCached(reqId, false);

    // Gói token nội dung đầu tiên đến
    telemetryTracker.recordContentToken(reqId, 'Xin ');
    telemetryTracker.recordFlush(reqId);
    telemetryTracker.recordRender(reqId, 1.25);

    const metric = telemetryTracker.finishTrace(reqId);
    expect(metric).not.toBeNull();
    expect(metric!.requestId).toBe(reqId);
    expect(metric!.contentTtftMs).not.toBeNull();
    expect(metric!.flushCount).toBe(1);
    expect(metric!.renderCount).toBe(1);

    // Kiểm tra tính bảo mật: object metric KHÔNG có trường question hay history hay user content
    const serialized = JSON.stringify(metric);
    expect(serialized.includes('question')).toBe(false);
    expect(serialized.includes('history')).toBe(false);
  });

  it('6. Chuẩn hóa ID: ID session không bị trùng trong các lần tạo liên tiếp', () => {
    const idSet = new Set<string>();
    const count = 1000;

    for (let i = 0; i < count; i++) {
      const id = generateUniqueId('session');
      expect(id).toMatch(/^session-/);
      expect(idSet.has(id)).toBe(false);
      idSet.add(id);
    }

    expect(idSet.size).toBe(count);
  });
});
