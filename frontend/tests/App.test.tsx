import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import React from 'react';
import { App } from '../src/app/App';
import * as chatApi from '../src/features/chat/api/chatApi';

// Mock scrollIntoView cho jsdom
window.HTMLElement.prototype.scrollIntoView = vi.fn();

function createSlowNDJSONStream(initialTokens: string[]): {
  response: Response;
  pushToken: (token: string) => void;
  closeStream: () => void;
  controller: ReadableStreamDefaultController<Uint8Array>;
} {
  const encoder = new TextEncoder();
  let controller!: ReadableStreamDefaultController<Uint8Array>;

  const stream = new ReadableStream<Uint8Array>({
    start(ctrl) {
      controller = ctrl;
      for (const t of initialTokens) {
        ctrl.enqueue(encoder.encode(JSON.stringify({ type: 'token', token: t }) + '\n'));
      }
    },
  });

  return {
    response: new Response(stream, { headers: { 'Content-Type': 'application/x-ndjson' } }),
    pushToken: (token: string) => {
      try {
        controller.enqueue(encoder.encode(JSON.stringify({ type: 'token', token }) + '\n'));
      } catch {
        // stream may be canceled
      }
    },
    closeStream: () => {
      try {
        controller.close();
      } catch {
        // already closed
      }
    },
    controller,
  };
}

describe('App Component (Direct End-to-End Application Flow Tests)', () => {
  beforeEach(() => {
    localStorage.clear();
    vi.restoreAllMocks();
  });

  it('1. Bắt đầu stream và Tạo chat mới khi đang stream: request cũ bị abort, session cũ lưu đủ, session mới sạch', async () => {
    let abortSignalTriggered = false;
    const { response, pushToken } = createSlowNDJSONStream(['Đang trả lời câu 1 ']);

    vi.spyOn(chatApi, 'fetchChatStream').mockImplementation(({ signal }) => {
      signal.addEventListener('abort', () => {
        abortSignalTriggered = true;
      });
      return Promise.resolve(response);
    });

    render(<App />);

    // 1. Nhập câu hỏi và bấm gửi
    const input = screen.getByPlaceholderText(/Đặt câu hỏi/i);
    fireEvent.change(input, { target: { value: 'Hỏi câu 1' } });
    const sendBtn = screen.getByTitle('Gửi câu hỏi');
    fireEvent.click(sendBtn);

    // Chờ tin nhắn người dùng và token xuất hiện
    await waitFor(() => {
      expect(screen.getByText('Hỏi câu 1')).toBeDefined();
    });

    // 2. Mở Drawer và bấm "Cuộc trò chuyện mới" trong lúc đang stream
    const drawerBtn = screen.getByTitle('Mở lịch sử hội thoại');
    fireEvent.click(drawerBtn);

    const newChatBtn = screen.getByText('Cuộc trò chuyện mới');
    fireEvent.click(newChatBtn);

    // 3. Xác nhận request cũ bị abort
    await waitFor(() => {
      expect(abortSignalTriggered).toBe(true);
    });

    // 4. Đẩy thêm token từ request cũ trễ -> không được làm rò rỉ vào session mới
    pushToken('Token rò rỉ không được vào session mới');

    // 5. Xác nhận session mới sạch, không có token cũ và không có pending message rỗng
    await waitFor(() => {
      expect(screen.queryByText(/Token rò rỉ/i)).toBeNull();
      // Session mới hiển thị màn hình chào mừng
      expect(screen.getByText(/Chào mừng bạn đến với HUIT/i)).toBeDefined();
    });

    // 6. Kiểm tra localStorage: session cũ đã lưu đủ câu hỏi và phần câu trả lời đã nhận
    const stored = JSON.parse(localStorage.getItem('huit_chat_sessions') || '[]');
    expect(stored.length).toBeGreaterThanOrEqual(1);

    const oldSession = stored[0];
    expect(oldSession.messages).toHaveLength(2);
    expect(oldSession.messages[0].content).toBe('Hỏi câu 1');
    expect(oldSession.messages[1].content).toContain('Đang trả lời câu 1');
    expect(oldSession.messages[1].content).toContain('_[Đã dừng sinh]_');
    expect(oldSession.messages[1].isStreaming).toBe(false);
  });

  it('2. Chuyển session qua HistoryDrawer: abort request cũ và nạp đúng tin nhắn session đã chọn', async () => {
    // Tạo sẵn 1 session cũ trong localStorage
    const sampleSession = {
      sessionId: 'session-prev-001',
      title: 'Hỏi về học phí',
      messages: [
        { id: 'u-prev', role: 'user', content: 'Học phí thế nào?', timestamp: 1000 },
        { id: 'a-prev', role: 'assistant', content: 'Học phí 15 triệu/kỳ.', timestamp: 2000, isStreaming: false },
      ],
      createdAt: 1000,
      updatedAt: 2000,
    };
    localStorage.setItem('huit_chat_sessions', JSON.stringify([sampleSession]));

    let abortTriggered = false;
    const { response } = createSlowNDJSONStream(['Đang trả lời dở...']);
    vi.spyOn(chatApi, 'fetchChatStream').mockImplementation(({ signal }) => {
      signal.addEventListener('abort', () => {
        abortTriggered = true;
      });
      return Promise.resolve(response);
    });

    render(<App />);

    // Bắt đầu một câu hỏi ở session hiện tại
    const input = screen.getByPlaceholderText(/Đặt câu hỏi/i);
    fireEvent.change(input, { target: { value: 'Câu hỏi đang hỏi' } });
    fireEvent.click(screen.getByTitle('Gửi câu hỏi'));

    await waitFor(() => {
      expect(screen.getByText('Câu hỏi đang hỏi')).toBeDefined();
    });

    // Mở Drawer và chọn session cũ "Hỏi về học phí"
    fireEvent.click(screen.getByTitle('Mở lịch sử hội thoại'));
    const prevSessionItem = screen.getByText('Hỏi về học phí');
    fireEvent.click(prevSessionItem);

    // Request đang hỏi bị abort
    await waitFor(() => {
      expect(abortTriggered).toBe(true);
    });

    // Màn hình chuyển sang nội dung của session cũ
    await waitFor(() => {
      expect(screen.getByText('Học phí thế nào?')).toBeDefined();
      expect(screen.getByText('Học phí 15 triệu/kỳ.')).toBeDefined();
    });

    // Không còn pending message rỗng
    const stored = JSON.parse(localStorage.getItem('huit_chat_sessions') || '[]');
    expect(stored.length).toBe(2);
    // Cả 2 sessions đều có tin nhắn hoàn chỉnh, không session nào có message isStreaming: true
    for (const sess of stored) {
      for (const msg of sess.messages) {
        expect(msg.content.length).toBeGreaterThan(0);
        expect(msg.isStreaming).toBeFalsy();
      }
    }
  });
});
