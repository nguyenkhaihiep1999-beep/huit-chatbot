import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import React from 'react';
import { mapApiError } from '../src/shared/utils/errorMapper';
import { createSession, SessionBootstrapError } from '../src/features/session/api/sessionApi';
import { ChatWindow } from '../src/features/chat/components/ChatWindow';

describe('Session Bootstrap & Error Handling Tests', () => {
  beforeEach(() => {
    sessionStorage.clear();
    localStorage.clear();
    vi.restoreAllMocks();
  });

  it('1. Frontend map SESSION_BOOTSTRAP_500 thành thông báo thân thiện chuyên nghiệp', () => {
    const rawError = new Error('SESSION_BOOTSTRAP_500');
    const mapped = mapApiError(rawError);

    expect(mapped.code).toBe('SESSION_BOOTSTRAP_FAILED');
    expect(mapped.message).toBe('Không thể khởi tạo phiên làm việc. Vui lòng thử lại.');
    expect(mapped.message).not.toContain('500');
    expect(mapped.message).not.toContain('SESSION_BOOTSTRAP');
  });

  it('2. Retry thất bại: createSession retry tối đa 3 lần khi backend 500, không retry vô hạn', async () => {
    let callCount = 0;
    vi.stubGlobal('fetch', vi.fn().mockImplementation(() => {
      callCount++;
      return Promise.resolve(new Response(JSON.stringify({ error: 'server error' }), {
        status: 500,
        headers: { 'Content-Type': 'application/json', 'X-Request-ID': 'req-mock-123' },
      }));
    }));

    await expect(createSession()).rejects.toThrow();
    // Bắt buộc retry đúng 3 lần (attempt 0, 1, 2) rồi dừng lại, không gọi vô hạn
    expect(callCount).toBe(3);
  });

  it('3. Retry thành công: lần 1 lỗi 500, lần 2 trả về 200 với credentials hợp lệ', async () => {
    let callCount = 0;
    vi.stubGlobal('fetch', vi.fn().mockImplementation(() => {
      callCount++;
      if (callCount === 1) {
        return Promise.resolve(new Response(JSON.stringify({ error: 'transient failure' }), {
          status: 500,
          headers: { 'Content-Type': 'application/json', 'X-Request-ID': 'req-retry-1' },
        }));
      }
      return Promise.resolve(new Response(JSON.stringify({
        success: true,
        session_id: 'sess_recovered_999',
        csrf_token: 'csrf_recovered_888',
        issued_at: 1000,
        expires_at: 2000,
        ttl_seconds: 1000,
      }), {
        status: 200,
        headers: { 'Content-Type': 'application/json', 'X-Request-ID': 'req-retry-2' },
      }));
    }));

    const creds = await createSession();
    expect(callCount).toBe(2);
    expect(creds.sessionId).toBe('sess_recovered_999');
    expect(creds.csrfToken).toBe('csrf_recovered_888');
  });

  it('4. Response thiếu session_id hoặc csrf_token: HTTP 200 nhưng dữ liệu không hợp lệ phải reject', async () => {
    // Trường hợp 1: Có csrf_token nhưng thiếu session_id
    vi.stubGlobal('fetch', vi.fn().mockImplementation(() => {
      return Promise.resolve(new Response(JSON.stringify({
        csrf_token: 'only_csrf_token',
      }), {
        status: 200,
        headers: { 'Content-Type': 'application/json', 'X-Request-ID': 'req-missing-session' },
      }));
    }));

    await expect(createSession()).rejects.toThrow();

    // Trường hợp 2: Có session_id nhưng thiếu csrf_token
    vi.stubGlobal('fetch', vi.fn().mockImplementation(() => {
      return Promise.resolve(new Response(JSON.stringify({
        session_id: 'sess_without_csrf',
      }), {
        status: 200,
        headers: { 'Content-Type': 'application/json', 'X-Request-ID': 'req-missing-csrf' },
      }));
    }));

    await expect(createSession()).rejects.toThrow();
  });

  it('5. Session loading state: hiển thị chỉ báo đang chuẩn bị và vô hiệu hóa ô nhập liệu', () => {
    render(
      <ChatWindow
        activeSessionId="sess_test"
        initialMessages={[]}
        onOpenLightbox={vi.fn()}
        onSaveSession={vi.fn()}
        isSessionReady={false}
        isSessionLoading={true}
        sessionError={null}
      />
    );

    // Hiển thị trạng thái loading
    expect(screen.getByText('Đang chuẩn bị phiên làm việc bảo mật...')).toBeDefined();
    // Khóa ô nhập liệu khi session đang tải
    const textarea = screen.getByPlaceholderText(/Đặt câu hỏi/i) as HTMLTextAreaElement;
    expect(textarea.disabled).toBe(true);
    const sendBtn = screen.getByTitle('Gửi câu hỏi') as HTMLButtonElement;
    expect(sendBtn.disabled).toBe(true);
  });

  it('6. Session not ready: không cho gửi chat khi session chưa sẵn sàng', () => {
    render(
      <ChatWindow
        activeSessionId="sess_test"
        initialMessages={[]}
        onOpenLightbox={vi.fn()}
        onSaveSession={vi.fn()}
        isSessionReady={false}
        isSessionLoading={false}
        sessionError={null}
      />
    );

    const textarea = screen.getByPlaceholderText(/Đặt câu hỏi/i) as HTMLTextAreaElement;
    expect(textarea.disabled).toBe(true);
    const sendBtn = screen.getByTitle('Gửi câu hỏi') as HTMLButtonElement;
    expect(sendBtn.disabled).toBe(true);
  });

  it('7. Nút Thử lại trên banner lỗi session hoạt động khi nhấn', () => {
    const mockRetry = vi.fn();
    const testError = new SessionBootstrapError({
      code: 'SERVER_ERROR',
      status: 500,
      requestId: 'req-fail-456',
      userFriendlyMessage: 'Không thể khởi tạo phiên làm việc. Vui lòng thử lại.',
    });

    render(
      <ChatWindow
        activeSessionId="sess_test"
        initialMessages={[]}
        onOpenLightbox={vi.fn()}
        onSaveSession={vi.fn()}
        isSessionReady={false}
        isSessionLoading={false}
        sessionError={testError}
        onRetrySession={mockRetry}
      />
    );

    // Xác nhận hiển thị thông báo thân thiện và mã yêu cầu rút gọn
    expect(screen.getByText('Không thể khởi tạo phiên làm việc. Vui lòng thử lại.')).toBeDefined();
    expect(screen.getByText(/req-fail-456/)).toBeDefined();

    // Nhấn nút Thử lại
    const retryBtn = screen.getByRole('button', { name: /Thử lại/i });
    fireEvent.click(retryBtn);
    expect(mockRetry).toHaveBeenCalledTimes(1);
  });

  it('8. Không lưu lỗi bootstrap vào lịch sử hội thoại người dùng', async () => {
    const mockSaveSession = vi.fn();

    render(
      <ChatWindow
        activeSessionId="sess_test"
        initialMessages={[]}
        onOpenLightbox={vi.fn()}
        onSaveSession={mockSaveSession}
        isSessionReady={false}
        sessionError={new SessionBootstrapError({
          code: 'SESSION_BOOTSTRAP_FAILED',
          userFriendlyMessage: 'Không thể khởi tạo phiên làm việc. Vui lòng thử lại.',
        })}
      />
    );

    // Lỗi bootstrap không bao giờ gọi hàm onSaveSession để ghi vào chat history
    await waitFor(() => {
      expect(mockSaveSession).not.toHaveBeenCalled();
      expect(screen.queryByText(/SESSION_BOOTSTRAP_500/)).toBeNull();
    });
  });
});
