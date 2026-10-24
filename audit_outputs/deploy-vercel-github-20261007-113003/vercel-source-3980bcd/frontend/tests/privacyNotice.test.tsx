import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import React from 'react';
import { PrivacyPolicyModal } from '../src/shared/components/PrivacyPolicyModal';
import { HistoryDrawer } from '../src/features/history/components/HistoryDrawer';
import { ConversationSession } from '../src/shared/types/common.types';

const mockSessions: ConversationSession[] = [
  {
    sessionId: 'session_test_01',
    title: 'Tìm hiểu học phí ngành Công nghệ Thông tin',
    messages: [
      {
        id: 'msg_01',
        role: 'user',
        content: 'Học phí ngành CNTT năm 2026 là bao nhiêu?',
        timestamp: 1710000000000,
      },
      {
        id: 'msg_02',
        role: 'assistant',
        content: 'Học phí ngành CNTT dự kiến khoảng 32 - 36 triệu/năm.',
        timestamp: 1710000005000,
      },
    ],
    createdAt: 1710000000000,
    updatedAt: 1710000005000,
  },
  {
    sessionId: 'session_test_02',
    title: 'Điểm chuẩn các ngành kỹ thuật',
    messages: [
      {
        id: 'msg_03',
        role: 'user',
        content: 'Điểm chuẩn năm ngoái',
        timestamp: 1710001000000,
      },
    ],
    createdAt: 1710001000000,
    updatedAt: 1710001000000,
  },
];

describe('User Privacy, Retention & History Management Contracts', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  describe('1. PrivacyPolicyModal Disclosure Contracts', () => {
    it('Minh bạch rõ ràng về LocalStorage, chế độ khách, LLM provider và chính sách lưu giữ', () => {
      const onClose = vi.fn();
      render(<PrivacyPolicyModal isOpen={true} onClose={onClose} />);

      const dialog = screen.getByRole('dialog');
      expect(dialog).toBeDefined();
      expect(dialog.getAttribute('aria-modal')).toBe('true');

      // 1. Khẳng định lưu trữ trong localStorage
      expect(screen.getByText(/Lưu trữ cục bộ trên thiết bị \(LocalStorage\)/i)).toBeDefined();
      expect(screen.getAllByText(/localStorage/i).length).toBeGreaterThanOrEqual(1);

      // 2. Mô tả rõ chế độ Khách / Ẩn danh (Guest mode - không tự ý thêm tài khoản)
      expect(screen.getByText(/Chế độ Khách \/ Ẩn danh \(Guest Mode\)/i)).toBeDefined();
      expect(screen.getByText(/không yêu cầu đăng ký hay đăng nhập tài khoản/i)).toBeDefined();

      // 3. Nêu rõ dữ liệu được gửi đến LLM provider (Google Gemini / Groq)
      expect(screen.getByText(/Nhà cung cấp Mô hình AI \(LLM Providers\)/i)).toBeDefined();
      expect(screen.getByText(/Google Gemini \/ Groq/i)).toBeDefined();

      // 4. Chính sách lưu giữ (Retention Policy) và liên kết hết hạn 24 giờ
      expect(screen.getByText(/Chính sách Lưu giữ & Khử khuẩn \(Retention Policy\)/i)).toBeDefined();
      expect(screen.getByText(/tự động hết hạn sau 24 giờ/i)).toBeDefined();

      // 5. Cam kết không lưu dữ liệu nhạy cảm (Zero Sensitive Storage)
      expect(screen.getByText(/Không lưu trữ nhạy cảm \(Zero Sensitive Storage\)/i)).toBeDefined();

      // Nút đóng "Tôi đã hiểu"
      const understandBtn = screen.getByRole('button', { name: /Tôi đã hiểu/i });
      fireEvent.click(understandBtn);
      expect(onClose).toHaveBeenCalled();
    });

    it('Đóng modal khi người dùng nhấn phím Escape', () => {
      const onClose = vi.fn();
      render(<PrivacyPolicyModal isOpen={true} onClose={onClose} />);

      fireEvent.keyDown(window, { key: 'Escape' });
      expect(onClose).toHaveBeenCalled();
    });
  });

  describe('2. HistoryDrawer Clear History & Privacy Actions', () => {
    it('Giữ nguyên chức năng xóa 1 phiên và xóa toàn bộ kèm modal xác nhận', () => {
      const onDeleteSession = vi.fn();
      const onClearAllSessions = vi.fn();
      const onSelectSession = vi.fn();
      const onNewChat = vi.fn();
      const onClose = vi.fn();

      render(
        <HistoryDrawer
          isOpen={true}
          onClose={onClose}
          sessions={mockSessions}
          activeSessionId="session_test_01"
          onSelectSession={onSelectSession}
          onNewChat={onNewChat}
          onDeleteSession={onDeleteSession}
          onClearAllSessions={onClearAllSessions}
        />
      );

      // Kiểm tra thông báo localStorage tại chân sidebar
      expect(screen.getByText(/lưu trữ cục bộ trong localStorage/i)).toBeDefined();

      // 1. Thử xóa một phiên chat
      const deleteItemBtns = screen.getAllByTitle(/Xóa cuộc trò chuyện này khỏi thiết bị/i);
      expect(deleteItemBtns.length).toBe(2);
      fireEvent.click(deleteItemBtns[0]);

      // Hộp thoại xác nhận xóa 1 phiên xuất hiện
      expect(screen.getByText('Xóa cuộc trò chuyện?')).toBeDefined();
      const confirmSingleBtn = screen.getByRole('button', { name: 'Xóa' });
      fireEvent.click(confirmSingleBtn);
      expect(onDeleteSession).toHaveBeenCalledWith('session_test_01');

      // 2. Thử xóa toàn bộ phiên chat
      const clearAllBtn = screen.getByRole('button', { name: /Xóa toàn bộ lịch sử trò chuyện/i });
      fireEvent.click(clearAllBtn);

      // Hộp thoại xác nhận xóa tất cả xuất hiện
      expect(screen.getByText('Xóa toàn bộ lịch sử trò chuyện?')).toBeDefined();
      const confirmAllBtn = screen.getByRole('button', { name: 'Xóa tất cả' });
      fireEvent.click(confirmAllBtn);
      expect(onClearAllSessions).toHaveBeenCalled();
    });

    it('Mở modal Chính sách quyền riêng tư từ liên kết tại footer HistoryDrawer', () => {
      render(
        <HistoryDrawer
          isOpen={true}
          onClose={vi.fn()}
          sessions={mockSessions}
          activeSessionId="session_test_01"
          onSelectSession={vi.fn()}
          onNewChat={vi.fn()}
          onDeleteSession={vi.fn()}
        />
      );

      const privacyLink = screen.getByRole('button', { name: /Chính sách quyền riêng tư & Lưu giữ dữ liệu/i });
      fireEvent.click(privacyLink);

      // Modal quyền riêng tư mở ra
      expect(screen.getByText('Quyền Riêng Tư & Chính Sách Lưu Giữ Dữ Liệu')).toBeDefined();
      expect(screen.getByText(/Google Gemini \/ Groq/i)).toBeDefined();
    });
  });
});
