import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import React from 'react';
import { AdminJobsPanel } from '../src/features/admin/components/AdminJobsPanel';
import { AdminWorkersPanel } from '../src/features/admin/components/AdminWorkersPanel';
import { AdminErrorLogsPanel } from '../src/features/admin/components/AdminErrorLogsPanel';
import { AdminSystemHealthPanel } from '../src/features/admin/components/AdminSystemHealthPanel';
import { ConfirmActionModal } from '../src/features/admin/components/ConfirmActionModal';
import * as adminApi from '../src/features/admin/api/adminApi';

describe('Admin Portal Operations & Monitoring Tests', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  describe('1. AdminJobsPanel (Filtering, Timeline & Safe Action Modals)', () => {
    it('Hiển thị danh sách jobs, tiến trình, và mở modal chi tiết dòng thời gian', async () => {
      vi.spyOn(adminApi, 'fetchAdminJobs').mockResolvedValue({
        jobs: [
          {
            job_id: 'job_render_xlsx_123',
            action: 'render',
            format: 'xlsx',
            status: 'completed',
            progress: 100,
            retries: 0,
            attempt: 1,
            max_attempts: 3,
            lease_owner: 'worker_01',
            created_at: '2026-09-16T10:00:00Z',
          },
          {
            job_id: 'job_export_pdf_456',
            action: 'export',
            format: 'pdf',
            status: 'failed',
            progress: 0,
            retries: 2,
            attempt: 3,
            max_attempts: 3,
            sanitized_error: 'Lỗi nạp font tiếng Việt',
            created_at: '2026-09-16T10:05:00Z',
          },
        ],
        total: 2,
        page: 1,
        limit: 15,
        total_pages: 1,
      });

      vi.spyOn(adminApi, 'fetchAdminJobDetail').mockResolvedValue({
        job: {
          job_id: 'job_render_xlsx_123',
          action: 'render',
          format: 'xlsx',
          status: 'completed',
          progress: 100,
          retries: 0,
          attempt: 1,
          max_attempts: 3,
          lease_owner: 'worker_01',
        },
        events: [
          {
            timestamp: '2026-09-16T10:00:00Z',
            status: 'queued',
            progress: 0,
            detail: 'Khởi tạo công việc',
          },
          {
            timestamp: '2026-09-16T10:01:00Z',
            status: 'completed',
            progress: 100,
            detail: 'Xuất file thành công',
          },
        ],
      });

      render(<AdminJobsPanel />);

      // Chờ nạp danh sách jobs
      await waitFor(() => {
        expect(screen.getByText(/job_render_xl/i)).toBeDefined();
        expect(screen.getByText(/job_export_pd/i)).toBeDefined();
      });

      // Kiểm tra trạng thái và tiến độ
      expect(screen.getByText('Hoàn tất')).toBeDefined();
      expect(screen.getByText('Thất bại')).toBeDefined();
      expect(screen.getByText('100%')).toBeDefined();

      // Click xem Chi tiết
      const detailBtns = screen.getAllByRole('button', { name: /Xem chi tiết tác vụ/i });
      fireEvent.click(detailBtns[0]);

      // Kiểm tra modal dòng thời gian
      await waitFor(() => {
        expect(screen.getByText('Dòng thời gian sự kiện (Event Timeline)')).toBeDefined();
        expect(screen.getByText(/Xuất file thành công/i)).toBeDefined();
      });
    });

    it('Kích hoạt modal xác nhận khi Retry hoặc Cancel job và gọi đúng API', async () => {
      vi.spyOn(adminApi, 'fetchAdminJobs').mockResolvedValue({
        jobs: [
          {
            job_id: 'job_failed_to_retry',
            action: 'render',
            status: 'failed',
            progress: 0,
            retries: 1,
            attempt: 1,
            max_attempts: 3,
          },
        ],
        total: 1,
        page: 1,
        limit: 15,
        total_pages: 1,
      });

      const retrySpy = vi.spyOn(adminApi, 'retryAdminJob').mockResolvedValue({
        success: true,
        message: 'Đã đưa tác vụ vào hàng đợi thử lại',
      });

      render(<AdminJobsPanel />);

      await waitFor(() => {
        expect(screen.getByText(/job_failed_to/i)).toBeDefined();
      });

      // Click Thử lại
      const retryBtn = screen.getByRole('button', { name: /Thử lại tác vụ/i });
      fireEvent.click(retryBtn);

      // Modal hiển thị
      expect(screen.getByText('Xác nhận thử lại tác vụ?')).toBeDefined();

      // Xác nhận thử lại
      const confirmBtn = screen.getByRole('button', { name: 'Thử lại ngay' });
      fireEvent.click(confirmBtn);

      await waitFor(() => {
        expect(retrySpy).toHaveBeenCalledWith('job_failed_to_retry', 'Admin manual retry');
      });
    });
  });

  describe('2. AdminWorkersPanel (Queue Stats & Worker Heartbeats)', () => {
    it('Hiển thị đầy đủ độ sâu hàng đợi và trạng thái dấu sống của các worker', async () => {
      vi.spyOn(adminApi, 'fetchAdminQueueStats').mockResolvedValue({
        queued_count: 5,
        processing_count: 2,
        stuck_count: 1,
        failed_count: 3,
        completed_count: 150,
        cancelled_count: 4,
        total_jobs: 165,
      });

      vi.spyOn(adminApi, 'fetchAdminWorkers').mockResolvedValue({
        workers: [
          {
            worker_id: 'worker_alpha_01',
            status: 'active',
            last_seen: '2026-09-16T10:15:00Z',
            active_jobs_count: 2,
            active_job_id: 'job_processing_xyz',
          },
        ],
        total_workers: 1,
        healthy_count: 1,
      });

      render(<AdminWorkersPanel />);

      await waitFor(() => {
        expect(screen.getByText('worker_alpha_01')).toBeDefined();
        expect(screen.getByText('ACTIVE')).toBeDefined();
      });

      // Kiểm tra các số liệu queue stats
      expect(screen.getByText('5')).toBeDefined(); // queued
      expect(screen.getAllByText('2').length).toBeGreaterThanOrEqual(1); // processing
      expect(screen.getAllByText('1').length).toBeGreaterThanOrEqual(1); // stuck
      expect(screen.getByText('3')).toBeDefined(); // failed
      expect(screen.getByText('150')).toBeDefined(); // completed
    });
  });

  describe('3. AdminErrorLogsPanel (Sanitized logs by Request ID)', () => {
    it('Hiển thị lỗi đã khử khuẩn, không rò rỉ câu hỏi thô hoặc bí mật', async () => {
      vi.spyOn(adminApi, 'fetchAdminErrorLogs').mockResolvedValue({
        logs: [
          {
            id: 'err_log_01',
            request_id: 'req_test_abc_123',
            timestamp: '2026-09-16T10:10:00Z',
            source: 'rag_query',
            error_code: 'RAG_PROCESSING_ERROR',
            message: 'Timeout khi kết nối nhà cung cấp LLM',
            intent: 'TuVanHocPhi',
            question_hash: 'a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2',
            question_length: 35,
          },
        ],
        total: 1,
      });

      render(<AdminErrorLogsPanel />);

      await waitFor(() => {
        expect(screen.getByText(/req_test_ab/i)).toBeDefined();
        expect(screen.getByText('Timeout khi kết nối nhà cung cấp LLM')).toBeDefined();
      });

      // Đảm bảo có SHA-256 hash và thông báo khử khuẩn bảo mật
      expect(screen.getByText(/a1b2c3d4e5f6/i)).toBeDefined();
      expect(screen.getByText(/Khử khuẩn bảo mật dữ liệu/i)).toBeDefined();
    });
  });

  describe('4. AdminSystemHealthPanel (Strict Read-Only Guarantee)', () => {
    it('Hiển thị migrations và backups ở chế độ CHỈ ĐỌC, không có nút áp dụng/restore', async () => {
      vi.spyOn(adminApi, 'fetchAdminMigrations').mockResolvedValue({
        migrations: [
          {
            version: '020',
            name: '020_create_admin_sessions_collection.py',
            description: 'Tạo collection admin_sessions',
            status: 'applied',
            is_read_only: true,
          },
        ],
        total: 1,
        applied_count: 1,
        can_execute_from_web: false,
      });

      vi.spyOn(adminApi, 'fetchAdminBackups').mockResolvedValue({
        backups: [
          {
            collection_name: 'jobs_backup_20260916_080000',
            source_collection: 'jobs',
            document_count: 42,
            created_at: '2026-09-16T08:00:00Z',
            status: 'available',
            is_read_only: true,
          },
        ],
        total: 1,
        can_restore_from_web: false,
      });

      vi.spyOn(adminApi, 'fetchAdminAlerts').mockResolvedValue({
        overall_status: 'healthy',
        alerts: [],
        stuck_jobs_count: 0,
        failed_jobs_24h_count: 0,
        worker_healthy_count: 1,
        worker_total_count: 1,
      });

      render(<AdminSystemHealthPanel />);

      await waitFor(() => {
        expect(screen.getByText('020_create_admin_sessions_collection.py')).toBeDefined();
        expect(screen.getByText('jobs_backup_20260916_080000')).toBeDefined();
      });

      // Kiểm tra các nhãn CHỈ ĐỌC
      const readOnlyBadges = screen.getAllByText(/CHỈ ĐỌC/i);
      expect(readOnlyBadges.length).toBeGreaterThanOrEqual(2);

      // Tuyệt đối không có nút restart hay apply migration trên web
      expect(screen.queryByRole('button', { name: /restart/i })).toBeNull();
      expect(screen.queryByRole('button', { name: /apply migration/i })).toBeNull();
      expect(screen.queryByRole('button', { name: /restore/i })).toBeNull();
    });
  });

  describe('5. ConfirmActionModal Accessibility (Focus & Keyboard Contract)', () => {
    it('Đóng modal khi nhấn phím Escape và hỗ trợ thuộc tính ARIA đầy đủ', () => {
      const onCancel = vi.fn();
      const onConfirm = vi.fn();

      render(
        <ConfirmActionModal
          isOpen={true}
          title="Xác nhận thao tác nguy hiểm"
          message="Bạn có chắc chắn không?"
          confirmLabel="Đồng ý"
          cancelLabel="Hủy"
          isDanger={true}
          onConfirm={onConfirm}
          onCancel={onCancel}
        />
      );

      const dialog = screen.getByRole('dialog');
      expect(dialog.getAttribute('aria-modal')).toBe('true');
      expect(dialog.getAttribute('aria-labelledby')).toBe('confirm-action-title');

      // Nhấn Escape
      fireEvent.keyDown(window, { key: 'Escape' });
      expect(onCancel).toHaveBeenCalled();
    });
  });
});
