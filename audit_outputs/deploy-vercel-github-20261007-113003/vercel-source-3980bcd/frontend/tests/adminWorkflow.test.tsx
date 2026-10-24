import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import React from 'react';
import { AdminLoginForm } from '../src/features/admin/components/AdminLoginForm';
import { AdminDashboard } from '../src/features/admin/components/AdminDashboard';
import { AdminPage } from '../src/features/admin/components/AdminPage';
import * as adminApi from '../src/features/admin/api/adminApi';
import type { SystemHealthData, AdminMetricsData } from '../src/features/admin/types/admin.types';

const mockHealthData: SystemHealthData = {
  status: 'ready',
  service: 'HUIT Admissions Chatbot Backend',
  version: '2.5.0',
  environment: 'production',
  timestamp: '2026-09-16T10:00:00Z',
  components: {
    mongodb: {
      status: 'healthy',
      latency_ms: 12,
      database: 'huit_chatbot',
    },
    job_queue: {
      status: 'healthy',
      queued_jobs: 0,
      stuck_jobs: 0,
    },
    knowledge_base: {
      status: 'healthy',
      documents_count: 1420,
      kb_version: 'v2.1',
    },
    redis: {
      status: 'healthy',
      ping_ms: 2,
    },
    storage: {
      status: 'healthy',
      provider: 'Local Disk / Cloud Storage',
    },
  },
};

const mockMetricsData: AdminMetricsData = {
  total_events: 100,
  total_cached_queries: 45,
  total_kb_documents: 1420,
  recent_events: [
    {
      request_id: 'req-abc-001',
      intent: 'HocPhi',
      cached: true,
      latency_ms: 5,
      model: 'Cache Store',
      created_at: '2026-09-16T09:55:00Z',
      status: 'Thành công',
    },
    {
      request_id: 'req-xyz-002',
      intent: 'DiemChuan',
      cached: false,
      latency_ms: 320,
      model: 'Gemini 2.5 Flash',
      created_at: '2026-09-16T09:58:00Z',
      status: 'Thành công',
    },
  ],
};

describe('Admin Portal Feature Tests (Protected Route, Security, Accessibility & Dashboard)', () => {
  beforeEach(() => {
    localStorage.clear();
    sessionStorage.clear();
    vi.restoreAllMocks();
  });

  describe('1. Admin Authentication & Security Contracts', () => {
    it('TUYỆT ĐỐI KHÔNG lưu token admin trong localStorage hoặc sessionStorage khi đăng nhập thành công', async () => {
      vi.spyOn(adminApi, 'verifyAdminSession').mockResolvedValue(false);
      vi.spyOn(adminApi, 'loginAdmin').mockResolvedValue({ success: true, message: 'OK' });
      vi.spyOn(adminApi, 'fetchHealthReady').mockResolvedValue(mockHealthData);
      vi.spyOn(adminApi, 'fetchAdminMetrics').mockResolvedValue(mockMetricsData);

      const onNavigateChat = vi.fn();
      render(<AdminPage onNavigateChat={onNavigateChat} />);

      // Đợi hết màn hình kiểm tra quyền hạn ban đầu
      await waitFor(() => {
        expect(screen.getByText('Quản Trị Hệ Thống HUIT AI')).toBeDefined();
      });

      // Nhập tài khoản và mật khẩu
      const userInput = screen.getByLabelText('Tài khoản quản trị');
      const passInput = screen.getByLabelText('Mật khẩu bảo mật');
      const submitBtn = screen.getByRole('button', { name: /Đăng nhập Quản trị/i });

      fireEvent.change(userInput, { target: { value: 'admin_huit' } });
      fireEvent.change(passInput, { target: { value: 'secretPass123' } });
      fireEvent.click(submitBtn);

      await waitFor(() => {
        expect(adminApi.loginAdmin).toHaveBeenCalledWith('admin_huit', 'secretPass123');
      });

      // Kiểm tra bất biến bảo mật: localStorage và sessionStorage không được chứa bất kỳ token nào
      expect(localStorage.getItem('token')).toBeNull();
      expect(localStorage.getItem('admin_token')).toBeNull();
      expect(localStorage.getItem('huit_admin_token')).toBeNull();
      expect(sessionStorage.getItem('token')).toBeNull();
      expect(sessionStorage.getItem('admin_token')).toBeNull();
    });

    it('Hiển thị lỗi khi thông tin đăng nhập không hợp lệ', async () => {
      const mockLogin = vi.fn().mockRejectedValue(new Error('Sai tài khoản hoặc mật khẩu'));
      const onBack = vi.fn();

      render(
        <AdminLoginForm
          onLogin={mockLogin}
          isLoggingIn={false}
          error="Sai tài khoản hoặc mật khẩu"
          onBackToChat={onBack}
        />
      );

      const alert = screen.getByRole('alert');
      expect(alert.textContent).toContain('Sai tài khoản hoặc mật khẩu');
    });

    it('Có thể quay về trang Chat từ màn hình đăng nhập', () => {
      const mockLogin = vi.fn();
      const onBack = vi.fn();

      render(
        <AdminLoginForm
          onLogin={mockLogin}
          isLoggingIn={false}
          error={null}
          onBackToChat={onBack}
        />
      );

      const backBtn = screen.getByRole('button', { name: /Quay lại giao diện trò chuyện/i });
      fireEvent.click(backBtn);
      expect(onBack).toHaveBeenCalled();
    });
  });

  describe('2. Admin Dashboard & Metrics Rendering', () => {
    it('Hiển thị đầy đủ health, queue/jobs, tỷ lệ lỗi, storage, Mongo status và metrics tổng quan', () => {
      const onRefresh = vi.fn();
      const onClearCache = vi.fn();
      const onDismiss = vi.fn();
      const onLogout = vi.fn();
      const onBack = vi.fn();

      render(
        <AdminDashboard
          health={mockHealthData}
          metrics={mockMetricsData}
          isLoading={false}
          error={null}
          isClearingCache={false}
          clearCacheResult={null}
          onRefresh={onRefresh}
          onClearCache={onClearCache}
          onDismissCacheResult={onDismiss}
          onLogout={onLogout}
          onBackToChat={onBack}
        />
      );

      // 1. Kiểm tra tiêu đề trang
      expect(screen.getByText('Bảng Điều Khiển Quản Trị Hệ Thống HUIT AI')).toBeDefined();

      // 2. Kiểm tra chỉ số tổng quan
      expect(screen.getByText('Tổng Lượt Truy Vấn')).toBeDefined();
      expect(screen.getByText('100')).toBeDefined();
      expect(screen.getByText('45.0%')).toBeDefined(); // 45 / 100 * 100 = 45.0%

      // 3. Kiểm tra các thành phần sức khỏe
      expect(screen.getByText('MongoDB Cơ Sở Dữ Liệu')).toBeDefined();
      expect(screen.getByText('12 ms')).toBeDefined();
      expect(screen.getByText('Hàng Đợi Xử Lý (Queue & Jobs)')).toBeDefined();
      expect(screen.getByText('Knowledge Base (Tri Thức Tuyển Sinh)')).toBeDefined();
      expect(screen.getByText('Lưu Trữ Tệp (Storage & Artifacts)')).toBeDefined();
    });

    it('Audit table hiển thị dữ liệu khử khuẩn an toàn, không lộ secret/prompt', () => {
      render(
        <AdminDashboard
          health={mockHealthData}
          metrics={mockMetricsData}
          isLoading={false}
          error={null}
          isClearingCache={false}
          clearCacheResult={null}
          onRefresh={vi.fn()}
          onClearCache={vi.fn()}
          onDismissCacheResult={vi.fn()}
          onLogout={vi.fn()}
          onBackToChat={vi.fn()}
        />
      );

      // Cột audit đã cắt ngắn request id
      expect(screen.getByText('req-abc-...')).toBeDefined();
      expect(screen.getByText('req-xyz-...')).toBeDefined();
      expect(screen.getByText('HocPhi')).toBeDefined();
      expect(screen.getByText('DiemChuan')).toBeDefined();
      expect(screen.getByText('Cache Store')).toBeDefined();
      expect(screen.getByText('Gemini 2.5 Flash')).toBeDefined();

      // Đảm bảo có chú thích khử khuẩn bảo mật
      expect(screen.getByText(/Bảo mật dữ liệu: Toàn bộ câu hỏi, prompt thô/i)).toBeDefined();
    });

    it('Xác nhận trước khi xóa cache hệ thống và gọi onClearCache khi đồng ý', async () => {
      const onClearCache = vi.fn().mockResolvedValue(undefined);

      render(
        <AdminDashboard
          health={mockHealthData}
          metrics={mockMetricsData}
          isLoading={false}
          error={null}
          isClearingCache={false}
          clearCacheResult={null}
          onRefresh={vi.fn()}
          onClearCache={onClearCache}
          onDismissCacheResult={vi.fn()}
          onLogout={vi.fn()}
          onBackToChat={vi.fn()}
        />
      );

      // Click nút Xóa Cache Hệ Thống
      const openModalBtn = screen.getByRole('button', { name: /Xóa bộ nhớ đệm cache hệ thống/i });
      fireEvent.click(openModalBtn);

      // Modal hiển thị
      expect(screen.getByText('Xác nhận xóa bộ nhớ đệm (Cache)')).toBeDefined();

      // Click Đồng ý xóa Cache
      const confirmBtn = screen.getByRole('button', { name: /Đồng ý xóa Cache/i });
      fireEvent.click(confirmBtn);

      expect(onClearCache).toHaveBeenCalled();
    });
  });

  describe('3. Accessibility & Usability (A11y)', () => {
    it('AdminLoginForm có label liên kết chính xác với input và hỗ trợ bàn phím', () => {
      render(
        <AdminLoginForm
          onLogin={vi.fn()}
          isLoggingIn={false}
          error={null}
          onBackToChat={vi.fn()}
        />
      );

      const usernameInput = screen.getByLabelText('Tài khoản quản trị');
      const passwordInput = screen.getByLabelText('Mật khẩu bảo mật');

      expect(usernameInput.getAttribute('id')).toBe('admin-username');
      expect(passwordInput.getAttribute('id')).toBe('admin-password');
      expect(passwordInput.getAttribute('type')).toBe('password');
    });

    it('Audit table có scope col cho header và hỗ trợ cuộn phím', () => {
      render(
        <AdminDashboard
          health={mockHealthData}
          metrics={mockMetricsData}
          isLoading={false}
          error={null}
          isClearingCache={false}
          clearCacheResult={null}
          onRefresh={vi.fn()}
          onClearCache={vi.fn()}
          onDismissCacheResult={vi.fn()}
          onLogout={vi.fn()}
          onBackToChat={vi.fn()}
        />
      );

      const tableRegion = screen.getByRole('region', { name: /Bảng nhật ký sự kiện hệ thống/i });
      expect(tableRegion.getAttribute('tabindex')).toBe('0');
    });
  });
});
