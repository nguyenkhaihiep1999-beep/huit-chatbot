import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import React from 'react';
import { ChatWindow } from '../src/features/chat/components/ChatWindow';
import * as chatApi from '../src/features/chat/api/chatApi';
import type { ChatMessage } from '../src/shared/types/common.types';

// Mock scrollIntoView trong jsdom
window.HTMLElement.prototype.scrollIntoView = vi.fn();

function createNDJSONResponse(lines: string[]): Response {
  const encoder = new TextEncoder();
  let idx = 0;
  const stream = new ReadableStream<Uint8Array>({
    pull(controller) {
      if (idx < lines.length) {
        controller.enqueue(encoder.encode(lines[idx] + '\n'));
        idx++;
      } else {
        controller.close();
      }
    },
  });

  return new Response(stream, {
    status: 200,
    headers: { 'Content-Type': 'application/x-ndjson' },
  });
}

describe('ChatWindow Component (Direct Integration Tests)', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it('1. History Payload: Không đưa câu hỏi hiện tại vào cả trường question và history', async () => {
    const initialMessages: ChatMessage[] = [
      { id: 'u-1', role: 'user', content: 'Câu hỏi cũ', timestamp: 1000 },
      { id: 'a-1', role: 'assistant', content: 'Câu trả lời cũ', timestamp: 2000 },
    ];

    let capturedPayload: { question: string; history: Array<{ role: string; content: string }> } | null = null;

    vi.spyOn(chatApi, 'fetchChatStream').mockImplementation((params) => {
      capturedPayload = { question: params.question, history: params.history };
      return Promise.resolve(createNDJSONResponse([
        JSON.stringify({ type: 'token', token: 'Phản hồi mới' }),
      ]));
    });

    const onSaveSession = vi.fn();

    render(
      <ChatWindow
        activeSessionId="session-test-history"
        initialMessages={initialMessages}
        onOpenLightbox={vi.fn()}
        onSaveSession={onSaveSession}
      />
    );

    const input = screen.getByPlaceholderText(/Đặt câu hỏi/i);
    fireEvent.change(input, { target: { value: 'Điểm chuẩn CNTT 2026?' } });

    const sendBtn = screen.getByTitle('Gửi câu hỏi');
    fireEvent.click(sendBtn);

    await waitFor(() => {
      expect(capturedPayload).not.toBeNull();
    });

    expect(capturedPayload!.question).toBe('Điểm chuẩn CNTT 2026?');
    // History chỉ gồm 2 tin nhắn trước đó
    expect(capturedPayload!.history).toHaveLength(2);
    expect(capturedPayload!.history[0].content).toBe('Câu hỏi cũ');
    expect(capturedPayload!.history[1].content).toBe('Câu trả lời cũ');
    // Khẳng định: history không chứa câu hỏi hiện tại!
    const questionInHistory = capturedPayload!.history.some(
      (h) => h.content === 'Điểm chuẩn CNTT 2026?'
    );
    expect(questionInHistory).toBe(false);
  });

  it('2. Session phải lưu đủ: tin nhắn cũ + câu hỏi vừa gửi + câu trả lời hoàn chỉnh', async () => {
    const initialMessages: ChatMessage[] = [
      { id: 'u-1', role: 'user', content: 'Học phí thế nào?', timestamp: 1000 },
      { id: 'a-1', role: 'assistant', content: 'Khoảng 15 triệu/học kỳ.', timestamp: 2000 },
    ];

    const lines = [
      JSON.stringify({ type: 'token', token: 'Có nhiều học bổng khuyến khích học tập.' }),
    ];
    vi.spyOn(chatApi, 'fetchChatStream').mockResolvedValue(createNDJSONResponse(lines));

    const onSaveSession = vi.fn();

    render(
      <ChatWindow
        activeSessionId="session-save-full"
        initialMessages={initialMessages}
        onOpenLightbox={vi.fn()}
        onSaveSession={onSaveSession}
      />
    );

    const input = screen.getByPlaceholderText(/Đặt câu hỏi/i);
    fireEvent.change(input, { target: { value: 'Có học bổng không?' } });

    const sendBtn = screen.getByTitle('Gửi câu hỏi');
    fireEvent.click(sendBtn);

    await waitFor(() => {
      expect(onSaveSession).toHaveBeenCalled();
    });

    const savedSessionMessages: ChatMessage[] = onSaveSession.mock.calls[onSaveSession.mock.calls.length - 1][1];
    expect(savedSessionMessages).toHaveLength(4);
    expect(savedSessionMessages[0].content).toBe('Học phí thế nào?');
    expect(savedSessionMessages[1].content).toBe('Khoảng 15 triệu/học kỳ.');
    expect(savedSessionMessages[2].content).toBe('Có học bổng không?');
    expect(savedSessionMessages[3].content).toBe('Có nhiều học bổng khuyến khích học tập.');
    expect(savedSessionMessages[3].isStreaming).toBe(false);
  });

  it('3. Khi chuyển session, abort ngay request đang chạy', async () => {
    let abortTriggered = false;
    const stream = new ReadableStream<Uint8Array>({
      start() {
        // Giữ kết nối mở
      },
      cancel() {
        abortTriggered = true;
      },
    });

    vi.spyOn(chatApi, 'fetchChatStream').mockImplementation(({ signal }) => {
      signal.addEventListener('abort', () => {
        abortTriggered = true;
      });
      return Promise.resolve(new Response(stream));
    });

    const { rerender } = render(
      <ChatWindow
        activeSessionId="session-1"
        initialMessages={[]}
        onOpenLightbox={vi.fn()}
        onSaveSession={vi.fn()}
      />
    );

    const input = screen.getByPlaceholderText(/Đặt câu hỏi/i);
    fireEvent.change(input, { target: { value: 'Đang gửi câu 1' } });

    const sendBtn = screen.getByTitle('Gửi câu hỏi');
    fireEvent.click(sendBtn);

    // Chuyển sang session-2
    rerender(
      <ChatWindow
        activeSessionId="session-2"
        initialMessages={[]}
        onOpenLightbox={vi.fn()}
        onSaveSession={vi.fn()}
      />
    );

    await waitFor(() => {
      expect(abortTriggered).toBe(true);
    });
  });

  it('4. Lỗi mạng: không để pending message trống, thay bằng thông báo lỗi', async () => {
    vi.spyOn(chatApi, 'fetchChatStream').mockRejectedValue(new Error('Mất kết nối mạng'));

    const onSaveSession = vi.fn();

    render(
      <ChatWindow
        activeSessionId="session-error-handling"
        initialMessages={[]}
        onOpenLightbox={vi.fn()}
        onSaveSession={onSaveSession}
      />
    );

    const input = screen.getByPlaceholderText(/Đặt câu hỏi/i);
    fireEvent.change(input, { target: { value: 'Thử nghiệm mạng hỏng' } });

    const sendBtn = screen.getByTitle('Gửi câu hỏi');
    fireEvent.click(sendBtn);

    // Kiểm tra tin nhắn lỗi xuất hiện trên màn hình
    await waitFor(() => {
      expect(
        screen.getByText(/Hệ thống tư vấn đang bận hoặc gặp sự cố kết nối/i)
      ).toBeDefined();
    });

    // Session lưu lại tin nhắn lỗi, không có tin nhắn rỗng nào
    const savedMessages: ChatMessage[] = onSaveSession.mock.calls[onSaveSession.mock.calls.length - 1][1];
    expect(savedMessages).toHaveLength(2);
    expect(savedMessages[0].content).toBe('Thử nghiệm mạng hỏng');
    expect(savedMessages[1].content).toContain('Hệ thống tư vấn đang bận');
    expect(savedMessages[1].isStreaming).toBe(false);
  });
});
