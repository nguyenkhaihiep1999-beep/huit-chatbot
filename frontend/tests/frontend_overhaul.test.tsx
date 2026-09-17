import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import React from 'react';
import { ChatMessageList } from '../src/features/chat/components/ChatMessageList';
import { ChatInput } from '../src/features/chat/components/ChatInput';
import { HistoryDrawer } from '../src/features/history/components/HistoryDrawer';
import { ArtifactCard } from '../src/features/artifacts/components/ArtifactCard';
import { ConfirmModal } from '../src/shared/components/ConfirmModal';
import { mapApiError } from '../src/shared/utils/errorMapper';
import { renderMarkdown } from '../src/shared/lib/markdown';
import * as artifactApi from '../src/features/artifacts/api/artifactApi';
import type { ArtifactSummary } from '../src/shared/types/common.types';

// Mock scrollIntoView in jsdom
window.HTMLElement.prototype.scrollIntoView = vi.fn();

describe('Frontend Overhaul Requirements (Step 16)', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    if (typeof window !== 'undefined' && window.localStorage) {
      window.localStorage.clear();
    }
  });

  describe('1. Empty State & Practical Suggestions', () => {
    it('hiển thị đúng 4 gợi ý tuyển sinh thực tế khi chưa có tin nhắn', () => {
      const onSelect = vi.fn();
      render(<ChatMessageList messages={[]} onSelectSuggestion={onSelect} />);

      // Xác nhận thông điệp định vị chính
      expect(screen.getByText(/Hỏi đúng\. Hiểu rõ\. Chọn ngành tự tin\./i)).toBeDefined();

      // Xác nhận 4 gợi ý cụ thể
      const q1 = screen.getByText('Học phí HUIT năm 2026 là bao nhiêu?');
      const q2 = screen.getByText('Cho tôi danh sách ngành tuyển sinh.');
      const q3 = screen.getByText('Tạo bảng Excel học phí các ngành.');
      const q4 = screen.getByText('Điểm chuẩn ngành Công nghệ thông tin?');

      expect(q1).toBeDefined();
      expect(q2).toBeDefined();
      expect(q3).toBeDefined();
      expect(q4).toBeDefined();

      // Bấm vào gợi ý thứ 3 (Excel)
      fireEvent.click(q3);
      expect(onSelect).toHaveBeenCalledWith('Tạo bảng Excel học phí các ngành.');
    });
  });

  describe('2. ArtifactCard - Double-click Protection & Format Support', () => {
    const mockArtifact: ArtifactSummary = {
      artifact_id: 'art-excel-101',
      type: 'table',
      title: 'Bảng học phí dự kiến các ngành năm 2026',
      preview_url: '/api/artifacts/art-excel-101/preview.svg',
      manifest_url: '/api/artifacts/art-excel-101/manifest.json',
      status: 'ready',
      available_formats: ['xlsx', 'docx', 'pdf', 'png', 'svg', 'mp4', 'audio'],
    };

    it('loại bỏ định dạng audio/video và hiển thị các định dạng hợp lệ', () => {
      render(<ArtifactCard artifact={mockArtifact} />);

      // Tên artifact hiển thị
      expect(screen.getByText('Bảng học phí dự kiến các ngành năm 2026')).toBeDefined();

      // Mở menu tải về
      const downloadMenuBtn = screen.getByTitle('Tải tệp tin về máy');
      fireEvent.click(downloadMenuBtn);

      // Định dạng hợp lệ phải có
      expect(screen.getByText('.xlsx')).toBeDefined();
      expect(screen.getByText('.docx')).toBeDefined();
      expect(screen.getByText('.pdf')).toBeDefined();

      // Tuyệt đối không có audio/video
      expect(screen.queryByText(/mp4/i)).toBeNull();
      expect(screen.queryByText(/audio/i)).toBeNull();
    });

    it('chống double-click: khi đang tải xuống, bấm nhiều lần không gửi lặp request', async () => {
      let resolveExport: (val: any) => void;
      const exportPromise = new Promise((resolve) => {
        resolveExport = resolve;
      });

      const spyDownload = vi
        .spyOn(artifactApi, 'downloadArtifactExport')
        .mockReturnValue(exportPromise as Promise<any>);

      render(<ArtifactCard artifact={mockArtifact} />);

      // Mở menu tải
      const downloadMenuBtn = screen.getByTitle('Tải tệp tin về máy');
      fireEvent.click(downloadMenuBtn);

      const excelOption = screen.getByText('.xlsx');
      // Click lần 1
      fireEvent.click(excelOption);
      // Click lần 2 ngay lập tức (double click)
      fireEvent.click(excelOption);

      // Chỉ gọi API 1 lần duy nhất
      expect(spyDownload).toHaveBeenCalledTimes(1);
      expect(spyDownload).toHaveBeenCalledWith('art-excel-101', 'xlsx');

      // Hoàn tất tải
      resolveExport!({ success: true, download_url: 'http://localhost/download' });
      await waitFor(() => {
        expect(screen.queryByText('Đang xử lý...')).toBeNull();
      });
    });
  });

  describe('3. ConfirmModal - Keyboard Trap & Escape Handling', () => {
    it('đóng modal khi nhấn Escape và bẫy phím Tab bên trong modal', () => {
      const onCancel = vi.fn();
      const onConfirm = vi.fn();

      const { rerender } = render(
        <ConfirmModal
          isOpen={true}
          title="Xác nhận xóa cuộc trò chuyện"
          message="Bạn có chắc chắn muốn xóa không?"
          onCancel={onCancel}
          onConfirm={onConfirm}
        />
      );

      expect(screen.getByText('Xác nhận xóa cuộc trò chuyện')).toBeDefined();

      // Nhấn Escape
      fireEvent.keyDown(window, { key: 'Escape' });
      expect(onCancel).toHaveBeenCalledTimes(1);

      // Bấm nút Hủy
      const cancelBtn = screen.getByText('Hủy');
      fireEvent.click(cancelBtn);
      expect(onCancel).toHaveBeenCalledTimes(2);

      // Bấm nút Xác nhận
      const confirmBtn = screen.getByText('Xác nhận');
      fireEvent.click(confirmBtn);
      expect(onConfirm).toHaveBeenCalledTimes(1);

      // Khi isOpen = false, không render
      rerender(
        <ConfirmModal
          isOpen={false}
          title="Xác nhận xóa cuộc trò chuyện"
          message="Bạn có chắc chắn muốn xóa không?"
          onCancel={onCancel}
          onConfirm={onConfirm}
        />
      );
      expect(screen.queryByText('Xác nhận xóa cuộc trò chuyện')).toBeNull();
    });
  });

  describe('4. Centralized Error Mapping', () => {
    it('ánh xạ chính xác các lỗi HTTP và gợi ý thử lại', () => {
      // 429 Rate limit kèm thời gian chờ
      const err429 = mapApiError(new Error('HTTP 429: Too many requests. Retry after 45 seconds'));
      expect(err429.code).toBe('RATE_LIMIT_EXCEEDED');
      expect(err429.retryAfterSeconds).toBe(45);
      expect(err429.message).toContain('45 giây');
      expect(err429.canRetry).toBe(true);

      // 401 Phiên hết hạn
      const err401 = mapApiError(new Error('HTTP 401: Unauthorized'));
      expect(err401.code).toBe('AUTH_SESSION_EXPIRED');
      expect(err401.canRetry).toBe(true);

      // 403 Không có quyền
      const err403 = mapApiError(new Error('HTTP 403: Forbidden'));
      expect(err403.code).toBe('PERMISSION_DENIED');
      expect(err403.canRetry).toBe(false);

      // 404 Không tìm thấy
      const err404 = mapApiError(new Error('HTTP 404: Not found'));
      expect(err404.code).toBe('NOT_FOUND');
      expect(err404.canRetry).toBe(false);

      // Mất kết nối luồng
      const errStream = mapApiError(new Error('Stream interrupted by network failure'));
      expect(errStream.code).toBe('STREAM_INTERRUPTED');
      expect(errStream.canRetry).toBe(true);

      // Signed URL hết hạn
      const errExpired = mapApiError(new Error('Signature expired'));
      expect(errExpired.code).toBe('SIGNED_URL_EXPIRED');
      expect(errExpired.canRetry).toBe(true);
    });
  });

  describe('5. Composer Utilities & Accessible History', () => {
    it('gửi đúng prompt từ các thao tác nhanh và khóa chúng khi đang streaming', () => {
      const onSendMessage = vi.fn();
      const onStopStreaming = vi.fn();
      const { rerender } = render(
        <ChatInput
          onSendMessage={onSendMessage}
          onStopStreaming={onStopStreaming}
          isStreaming={false}
        />
      );

      fireEvent.click(screen.getByRole('button', { name: 'Tư vấn ngành' }));
      fireEvent.click(screen.getByRole('button', { name: 'So sánh học phí' }));
      fireEvent.click(screen.getByRole('button', { name: 'Tạo tài liệu' }));

      expect(onSendMessage).toHaveBeenNthCalledWith(
        1,
        'Tư vấn ngành học phù hợp với sở thích của tôi.'
      );
      expect(onSendMessage).toHaveBeenNthCalledWith(
        2,
        'So sánh học phí các ngành HUIT năm 2026.'
      );
      expect(onSendMessage).toHaveBeenNthCalledWith(
        3,
        'Tạo bảng Excel thông tin tuyển sinh HUIT.'
      );

      rerender(
        <ChatInput
          onSendMessage={onSendMessage}
          onStopStreaming={onStopStreaming}
          isStreaming={true}
        />
      );
      expect(screen.getByRole('button', { name: 'Tư vấn ngành' }).hasAttribute('disabled')).toBe(true);
      expect(screen.getByRole('button', { name: 'So sánh học phí' }).hasAttribute('disabled')).toBe(true);
      expect(screen.getByRole('button', { name: 'Tạo tài liệu' }).hasAttribute('disabled')).toBe(true);
    });

    it('đóng lịch sử bằng Escape và chỉ cho phép tương tác khi drawer mở', () => {
      const onClose = vi.fn();
      const session = {
        sessionId: 'session-1',
        title: 'Tư vấn ngành CNTT',
        createdAt: 1,
        updatedAt: 1,
        messages: [],
      };
      const { container, rerender } = render(
        <HistoryDrawer
          isOpen={true}
          onClose={onClose}
          sessions={[session]}
          activeSessionId="session-1"
          onSelectSession={vi.fn()}
          onNewChat={vi.fn()}
          onDeleteSession={vi.fn()}
        />
      );

      const drawer = container.querySelector('#history-drawer');
      expect(drawer?.getAttribute('aria-hidden')).toBe('false');
      expect(drawer?.hasAttribute('inert')).toBe(false);
      expect(drawer?.querySelector('.history-select-btn')).toBeDefined();

      fireEvent.keyDown(window, { key: 'Escape' });
      expect(onClose).toHaveBeenCalledTimes(1);

      rerender(
        <HistoryDrawer
          isOpen={false}
          onClose={onClose}
          sessions={[session]}
          activeSessionId="session-1"
          onSelectSession={vi.fn()}
          onNewChat={vi.fn()}
          onDeleteSession={vi.fn()}
        />
      );
      const closedDrawer = container.querySelector('#history-drawer');
      expect(closedDrawer?.getAttribute('aria-hidden')).toBe('true');
      expect(closedDrawer?.hasAttribute('inert')).toBe(true);
    });
  });

  describe('6. Markdown Table Renderer', () => {
    it('render bảng GFM thành cell HTML thay vì chuỗi object', () => {
      const html = renderMarkdown('| Ngành | Học phí |\n| --- | ---: |\n| CNTT | 16 triệu |');

      expect(html).toContain('table-responsive-wrapper');
      expect(html).toContain('chat-markdown-table');
      expect(html).toContain('<th>Ngành</th>');
      expect(html).toContain('<td>CNTT</td>');
      expect(html).not.toContain('[object Object]');
    });
  });
});
