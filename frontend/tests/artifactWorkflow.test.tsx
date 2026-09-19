import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { useArtifactUpscale } from '../src/features/artifacts/hooks/useArtifactUpscale';
import { useArtifactExport } from '../src/features/artifacts/hooks/useArtifactExport';
import { useArtifactWorkflow } from '../src/features/artifacts/hooks/useArtifactWorkflow';
import * as artifactApi from '../src/features/artifacts/api/artifactApi';
import type { ArtifactSummary } from '../src/shared/types/common.types';
import { getSessionScope, setSessionCredentials } from '../src/shared/auth/csrfStore';

const mockArtifactA: ArtifactSummary = {
  artifact_id: 'art-demo-001',
  type: 'chart',
  title: 'Chỉ tiêu Tuyển sinh HUIT 2025',
  preview_url: 'https://cdn.huit.edu.vn/visuals/art-demo-001.svg',
  available_formats: ['svg', 'png', 'pdf', 'xlsx', 'docx'],
  status: 'ready',
};

const mockArtifactB: ArtifactSummary = {
  artifact_id: 'art-demo-002',
  type: 'image',
  title: 'Khuôn viên Cơ sở Chính HUIT',
  preview_url: 'https://cdn.huit.edu.vn/visuals/art-demo-002.png',
  available_formats: ['png', 'pdf'],
  status: 'ready',
};

describe('Frontend LTX Hook Gate - Artifact Workflow & Architecture', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.restoreAllMocks();
    if (typeof window !== 'undefined' && window.localStorage) {
      window.localStorage.clear();
    }
    setSessionCredentials({
      sessionId: 'session-artifact-test',
      csrfToken: 'csrf-artifact-test-123456',
    });
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  // 1. Architecture dependency
  describe('1. Architecture Dependency & Boundary Contract', () => {
    it('ArtifactLightbox và ArtifactCard không import API module hoặc gọi fetch trực tiếp', () => {
      const frontendSrc = resolve(__dirname, '../src');
      const lightboxContent = readFileSync(
        resolve(frontendSrc, 'features/artifacts/components/ArtifactLightbox.tsx'),
        'utf8'
      );
      const cardContent = readFileSync(
        resolve(frontendSrc, 'features/artifacts/components/ArtifactCard.tsx'),
        'utf8'
      );

      // Không import /api/ hoặc shared/api
      expect(lightboxContent).not.toMatch(/from\s+["'][^"']*\/api\//);
      expect(lightboxContent).not.toMatch(/from\s+["'][^"']*shared\/api/);
      expect(cardContent).not.toMatch(/from\s+["'][^"']*\/api\//);
      expect(cardContent).not.toMatch(/from\s+["'][^"']*shared\/api/);

      // Không chứa fetch hoặc apiClient
      expect(lightboxContent).not.toMatch(/\bfetch\s*\(/);
      expect(lightboxContent).not.toMatch(/\bapiClient\b/);
      expect(cardContent).not.toMatch(/\bfetch\s*\(/);
      expect(cardContent).not.toMatch(/\bapiClient\b/);

      // Bắt buộc import domain workflow hook
      expect(lightboxContent).toMatch(/useArtifactWorkflow/);
      expect(cardContent).toMatch(/useArtifactWorkflow/);
    });

    it('Domain hooks không gọi fetch() hoặc import shared/api/httpClient trực tiếp', () => {
      const frontendSrc = resolve(__dirname, '../src');
      const hooks = [
        'features/artifacts/hooks/useArtifactUpscale.ts',
        'features/artifacts/hooks/useArtifactExport.ts',
        'features/artifacts/hooks/useArtifactWorkflow.ts',
      ];

      for (const hookFile of hooks) {
        const content = readFileSync(resolve(frontendSrc, hookFile), 'utf8');
        expect(content).not.toMatch(/\bfetch\s*\(/);
        expect(content).not.toMatch(/from\s+["'][^"']*shared\/api\/httpClient/);
      }
    });
  });

  // 2. Upscale trả kết quả tức thời
  describe('2. Upscale Immediate Result (Cached / Storage)', () => {
    it('nhận kết quả tức thời từ máy chủ và cập nhật state không cần polling', async () => {
      const spyUpscale = vi.spyOn(artifactApi, 'requestArtifactUpscale').mockResolvedValue({
        url: 'https://cdn.huit.edu.vn/visuals/art-demo-001-2x.png',
        scale: 2,
      });
      const spyPoll = vi.spyOn(artifactApi, 'fetchJobStatus');

      const { result } = renderHook(() => useArtifactUpscale(mockArtifactA));

      expect(result.current.upscaledUrl).toBeNull();
      expect(result.current.isUpscaling).toBe(false);

      await act(async () => {
        await result.current.requestUpscale(2);
      });

      expect(spyUpscale).toHaveBeenCalledWith('art-demo-001', 2);
      expect(spyPoll).not.toHaveBeenCalled(); // Không polling khi có url tức thời
      expect(result.current.upscaledUrl).toBe('https://cdn.huit.edu.vn/visuals/art-demo-001-2x.png');
      expect(result.current.scaleFactor).toBe(2);
      expect(result.current.isUpscaling).toBe(false);
      expect(result.current.jobProgress).toBe(100);
      expect(result.current.upscaleError).toBeNull();
    });
  });

  // 3. Background job hoàn thành
  describe('3. Background Job Polling Completion', () => {
    it('khởi tạo job_id, poll tiến trình và hoàn thành khi job status = completed', async () => {
      vi.spyOn(artifactApi, 'requestArtifactUpscale').mockResolvedValue({
        job_id: 'job-upscale-4x-001',
      });

      const spyPoll = vi
        .spyOn(artifactApi, 'fetchJobStatus')
        .mockResolvedValueOnce({
          job_id: 'job-upscale-4x-001',
          status: 'processing',
          progress: 55,
        })
        .mockResolvedValueOnce({
          job_id: 'job-upscale-4x-001',
          status: 'completed',
          progress: 100,
          result_url: 'https://cdn.huit.edu.vn/visuals/art-demo-001-4x.png',
        });

      const { result } = renderHook(() => useArtifactUpscale(mockArtifactA, { pollIntervalMs: 500 }));

      await act(async () => {
        await result.current.requestUpscale(4);
      });

      expect(result.current.isUpscaling).toBe(true);
      expect(result.current.upscaleJobId).toBe('job-upscale-4x-001');
      expect(result.current.jobProgress).toBe(10);

      // Poll lần 1
      await act(async () => {
        vi.advanceTimersByTime(500);
      });

      expect(spyPoll).toHaveBeenCalledTimes(1);
      expect(result.current.jobProgress).toBe(55);
      expect(result.current.isUpscaling).toBe(true);

      // Poll lần 2 -> hoàn tất
      await act(async () => {
        vi.advanceTimersByTime(500);
      });

      expect(spyPoll).toHaveBeenCalledTimes(2);
      expect(result.current.isUpscaling).toBe(false);
      expect(result.current.upscaleJobId).toBeNull();
      expect(result.current.upscaledUrl).toBe('https://cdn.huit.edu.vn/visuals/art-demo-001-4x.png');
      expect(result.current.scaleFactor).toBe(4);
      expect(result.current.jobProgress).toBe(100);
    });
  });

  // 4. Job failed / cancelled
  describe('4. Background Job Failed & Cancelled', () => {
    it('xử lý khi tác vụ nền thất bại với thông báo lỗi từ server', async () => {
      vi.spyOn(artifactApi, 'requestArtifactUpscale').mockResolvedValue({
        job_id: 'job-fail-002',
      });

      vi.spyOn(artifactApi, 'fetchJobStatus').mockResolvedValueOnce({
        job_id: 'job-fail-002',
        status: 'failed',
        error: 'Lỗi GPU render quá tải, vui lòng thử lại sau',
      });

      const { result } = renderHook(() => useArtifactUpscale(mockArtifactA, { pollIntervalMs: 200 }));

      await act(async () => {
        await result.current.requestUpscale(2);
      });

      await act(async () => {
        vi.advanceTimersByTime(200);
      });

      expect(result.current.isUpscaling).toBe(false);
      expect(result.current.upscaleJobId).toBeNull();
      expect(result.current.upscaleError).toBe('Lỗi GPU render quá tải, vui lòng thử lại sau');
      expect(result.current.upscaledUrl).toBeNull();
    });

    it('hủy tác vụ phóng to đang chạy: gọi cancelJob API, ngắt timer và báo hủy', async () => {
      vi.spyOn(artifactApi, 'requestArtifactUpscale').mockResolvedValue({
        job_id: 'job-cancel-003',
      });
      const spyCancel = vi.spyOn(artifactApi, 'cancelJob').mockResolvedValue(undefined);
      const spyPoll = vi.spyOn(artifactApi, 'fetchJobStatus').mockResolvedValue({
        job_id: 'job-cancel-003',
        status: 'processing',
        progress: 30,
      });

      const { result } = renderHook(() => useArtifactUpscale(mockArtifactA, { pollIntervalMs: 400 }));

      await act(async () => {
        await result.current.requestUpscale(2);
      });

      expect(result.current.upscaleJobId).toBe('job-cancel-003');

      // Người dùng nhấn Hủy
      await act(async () => {
        await result.current.cancelUpscale();
      });

      expect(spyCancel).toHaveBeenCalledWith('job-cancel-003');
      expect(result.current.isUpscaling).toBe(false);
      expect(result.current.upscaleJobId).toBeNull();
      expect(result.current.upscaleError).toBe('Đã hủy tác vụ phóng to ảnh.');

      // Tiến thêm thời gian: bảo đảm không có thêm lệnh poll nào được gọi
      await act(async () => {
        vi.advanceTimersByTime(1200);
      });
      expect(spyPoll).not.toHaveBeenCalled();
    });
  });

  // 5. Polling timeout
  describe('5. Polling Timeout Safeguard', () => {
    it('tự động dừng và báo lỗi timeout khi vượt quá số lần thử tối đa', async () => {
      vi.spyOn(artifactApi, 'requestArtifactUpscale').mockResolvedValue({
        job_id: 'job-timeout-004',
      });

      vi.spyOn(artifactApi, 'fetchJobStatus').mockResolvedValue({
        job_id: 'job-timeout-004',
        status: 'processing',
        progress: 25,
      });

      // Cấu hình tối đa 3 lần thử
      const { result } = renderHook(() =>
        useArtifactUpscale(mockArtifactA, { pollIntervalMs: 100, maxAttempts: 3 })
      );

      await act(async () => {
        await result.current.requestUpscale(2);
      });

      // Lần 1
      await act(async () => {
        vi.advanceTimersByTime(100);
      });
      // Lần 2
      await act(async () => {
        vi.advanceTimersByTime(100);
      });
      // Lần 3 (đạt ngưỡng)
      await act(async () => {
        vi.advanceTimersByTime(100);
      });

      expect(result.current.isUpscaling).toBe(false);
      expect(result.current.upscaleJobId).toBeNull();
      expect(result.current.upscaleError).toContain('Quá thời gian chờ phóng to ảnh');
    });
  });

  // 6. Cleanup & unmount safety
  describe('6. Timer Cleanup & Unmount Safety', () => {
    it('hủy timer khi unmount và không cập nhật state sau unmount', async () => {
      vi.spyOn(artifactApi, 'requestArtifactUpscale').mockResolvedValue({
        job_id: 'job-unmount-005',
      });
      const spyPoll = vi.spyOn(artifactApi, 'fetchJobStatus').mockResolvedValue({
        job_id: 'job-unmount-005',
        status: 'processing',
      });

      const { result, unmount } = renderHook(() =>
        useArtifactUpscale(mockArtifactA, { pollIntervalMs: 500 })
      );

      await act(async () => {
        await result.current.requestUpscale(2);
      });

      expect(result.current.isUpscaling).toBe(true);

      // Unmount hook
      unmount();

      // Cho timer chạy qua
      await act(async () => {
        vi.advanceTimersByTime(2000);
      });

      // Sau khi unmount, poll không được kích hoạt tiếp
      expect(spyPoll).not.toHaveBeenCalled();
    });
  });

  // 7. Double-click protection
  describe('7. Double-Click & In-Flight Protection', () => {
    it('chống double-click khi requestUpscale: chỉ gửi 1 request duy nhất dù bấm liên tiếp', async () => {
      let resolveUpscale: (val: any) => void;
      const upscalePromise = new Promise((res) => {
        resolveUpscale = res;
      });

      const spyUpscale = vi
        .spyOn(artifactApi, 'requestArtifactUpscale')
        .mockReturnValue(upscalePromise as any);

      const { result } = renderHook(() => useArtifactUpscale(mockArtifactA));

      // Bấm lần 1 và lần 2 đồng thời
      act(() => {
        result.current.requestUpscale(2);
        result.current.requestUpscale(2);
        result.current.requestUpscale(4);
      });

      expect(spyUpscale).toHaveBeenCalledTimes(1);

      // Hoàn thành promise
      await act(async () => {
        resolveUpscale!({ url: 'https://cdn.huit.edu.vn/visuals/art-demo-001-2x.png' });
        await upscalePromise;
      });

      expect(result.current.upscaledUrl).toBe('https://cdn.huit.edu.vn/visuals/art-demo-001-2x.png');
    });

    it('chống double-click khi exportArtifact: chỉ gửi 1 request duy nhất', async () => {
      let resolveExport: (val: any) => void;
      const exportPromise = new Promise((res) => {
        resolveExport = res;
      });

      const spyExport = vi
        .spyOn(artifactApi, 'downloadArtifactExport')
        .mockReturnValue(exportPromise as any);

      const { result } = renderHook(() => useArtifactExport('art-demo-001'));

      act(() => {
        result.current.exportArtifact('xlsx');
        result.current.exportArtifact('xlsx');
      });

      expect(spyExport).toHaveBeenCalledTimes(1);

      await act(async () => {
        resolveExport!(new Blob(['test-data']));
        await exportPromise;
      });

      expect(result.current.isExporting).toBe(false);
      expect(result.current.exportError).toBeNull();
    });
  });

  // 8. Export success / failure
  describe('8. Export Mutation Workflow (Success & Failure)', () => {
    it('xuất tệp thành công: trả về true, quản lý đúng isExporting và không có lỗi', async () => {
      const spyExport = vi
        .spyOn(artifactApi, 'downloadArtifactExport')
        .mockResolvedValue(new Blob(['data']));

      const { result } = renderHook(() => useArtifactExport('art-demo-001'));

      let success: boolean = false;
      await act(async () => {
        success = await result.current.exportArtifact('pdf');
      });

      expect(spyExport).toHaveBeenCalledWith('art-demo-001', 'pdf');
      expect(success).toBe(true);
      expect(result.current.isExporting).toBe(false);
      expect(result.current.exportError).toBeNull();
    });

    it('xuất tệp thất bại: bắt lỗi, ánh xạ message thân thiện và trả về false', async () => {
      vi.spyOn(artifactApi, 'downloadArtifactExport').mockRejectedValue(
        new Error('Mất kết nối mạng khi tải tệp')
      );

      const { result } = renderHook(() => useArtifactExport('art-demo-001'));

      let success: boolean = true;
      await act(async () => {
        success = await result.current.exportArtifact('docx');
      });

      expect(success).toBe(false);
      expect(result.current.isExporting).toBe(false);
      expect(result.current.exportError).toBe(
        'Hệ thống tư vấn đang bận hoặc gặp sự cố kết nối. Bạn vui lòng thử lại sau giây lát nhé!'
      );
    });
  });

  // 9. Đổi artifact trong lúc polling
  describe('9. Artifact Switch During Active Polling', () => {
    it('hủy timer, reset toàn bộ state khi prop artifact thay đổi', async () => {
      vi.spyOn(artifactApi, 'requestArtifactUpscale').mockResolvedValue({
        job_id: 'job-art-A-007',
      });
      const spyPoll = vi.spyOn(artifactApi, 'fetchJobStatus').mockResolvedValue({
        job_id: 'job-art-A-007',
        status: 'completed',
        result_url: 'https://cdn.huit.edu.vn/visuals/stale-result.png',
      });

      const { result, rerender } = renderHook(
        ({ art }) => useArtifactUpscale(art, { pollIntervalMs: 500 }),
        { initialProps: { art: mockArtifactA } }
      );

      await act(async () => {
        await result.current.requestUpscale(2);
      });

      expect(result.current.isUpscaling).toBe(true);
      expect(result.current.upscaleJobId).toBe('job-art-A-007');

      // Đổi sang artifact B trong khi đang poll artifact A
      rerender({ art: mockArtifactB });

      expect(result.current.isUpscaling).toBe(false);
      expect(result.current.upscaleJobId).toBeNull();
      expect(result.current.upscaledUrl).toBeNull();
      expect(result.current.scaleFactor).toBe(1);
      expect(result.current.jobProgress).toBe(0);

      // Thời gian trôi qua, response cũ của artifact A không được cập nhật vào artifact B
      await act(async () => {
        vi.advanceTimersByTime(1000);
      });

      expect(result.current.upscaledUrl).toBeNull();
      expect(spyPoll).not.toHaveBeenCalled();
    });
  });

  // 10. useArtifactWorkflow Orchestrator
  describe('10. useArtifactWorkflow Combined Orchestrator', () => {
    it('kết hợp preview URL, upscale và export trong một interface thống nhất', async () => {
      vi.spyOn(artifactApi, 'requestArtifactUpscale').mockResolvedValue({
        url: 'https://cdn.huit.edu.vn/visuals/art-demo-001-2x.png',
      });

      const { result } = renderHook(() => useArtifactWorkflow(mockArtifactA));

      // Preview URL ban đầu
      expect(result.current.defaultPreviewUrl).toBe(mockArtifactA.preview_url);
      expect(result.current.activePreviewUrl).toBe(mockArtifactA.preview_url);

      // Thực hiện upscale
      await act(async () => {
        await result.current.requestUpscale(2);
      });

      expect(result.current.activePreviewUrl).toBe(
        'https://cdn.huit.edu.vn/visuals/art-demo-001-2x.png'
      );
      expect(result.current.scaleFactor).toBe(2);

      // Xử lý lỗi preview tải ảnh
      act(() => {
        result.current.setPreviewError('Lỗi tải hình ảnh xem trước');
      });
      expect(result.current.errorMessage).toBe('Lỗi tải hình ảnh xem trước');

      act(() => {
        result.current.clearError();
      });
      expect(result.current.errorMessage).toBeNull();
    });

    it('tự đồng bộ manifest để planned artifact không quay vô hạn', async () => {
      const plannedArtifact: ArtifactSummary = {
        ...mockArtifactA,
        status: 'planned',
      };
      vi.spyOn(artifactApi, 'fetchArtifactSummary').mockResolvedValue({
        ...plannedArtifact,
        status: 'ready',
      });

      const { result } = renderHook(() => useArtifactWorkflow(plannedArtifact));

      await act(async () => {
        await Promise.resolve();
      });

      expect(artifactApi.fetchArtifactSummary).toHaveBeenCalledWith('art-demo-001');
      expect(result.current.resolvedArtifact?.status).toBe('ready');
      expect(result.current.defaultPreviewUrl).toBe(plannedArtifact.preview_url);
    });
  });

  // 11. Durable Background Queue & Reload Reattachment Contracts
  describe('11. Durable Background Queue & Reload Reattachment Contracts', () => {
    it('useArtifactExport nhận job_id, poll tiến trình và kích hoạt tải signed URL khi completed', async () => {
      vi.spyOn(artifactApi, 'downloadArtifactExport').mockResolvedValue({
        success: true,
        job_id: 'job-export-999',
      } as any);

      vi.spyOn(artifactApi, 'fetchJobStatus')
        .mockResolvedValueOnce({
          job_id: 'job-export-999',
          status: 'processing',
          progress: 50,
        })
        .mockResolvedValueOnce({
          job_id: 'job-export-999',
          status: 'completed',
          progress: 100,
          download_url: 'https://cdn.huit.edu.vn/artifacts/download/signed_export.xlsx',
        });

      const { result } = renderHook(() => useArtifactExport('art-demo-001'));

      let exportOk: boolean = false;
      await act(async () => {
        exportOk = await result.current.exportArtifact('xlsx');
      });

      expect(exportOk).toBe(true);
      expect(result.current.exportJobId).toBe('job-export-999');
      expect(result.current.isExporting).toBe(true);

      // Advance timer for poll 1 (processing)
      await act(async () => {
        vi.advanceTimersByTime(500);
      });
      expect(result.current.exportProgress).toBe(50);

      // Advance timer for poll 2 (completed)
      await act(async () => {
        vi.advanceTimersByTime(1000);
      });
      expect(result.current.isExporting).toBe(false);
      expect(result.current.exportJobId).toBeNull();
      expect(result.current.exportProgress).toBe(100);
    });

    it('useArtifactExport tự động reattach active job sau reload từ localStorage', async () => {
      const sessionScope = getSessionScope('session-artifact-test');
      // Giả lập localStorage có active job
      window.localStorage.setItem(
        'huit_active_jobs',
        JSON.stringify({
          [`${sessionScope}:export:art-demo-001`]: {
            jobId: 'job-reattach-111',
            type: 'export',
            artifactId: 'art-demo-001',
            sessionScope,
            meta: { format: 'docx' },
            timestamp: Date.now(),
          },
        })
      );

      vi.spyOn(artifactApi, 'fetchJobStatus').mockResolvedValue({
        job_id: 'job-reattach-111',
        status: 'completed',
        progress: 100,
        download_url: 'https://cdn.huit.edu.vn/artifacts/download/signed_reattach.docx',
      });

      const { result } = renderHook(() => useArtifactExport('art-demo-001'));

      // Reattach ngay lập tức
      expect(result.current.exportJobId).toBe('job-reattach-111');
      expect(result.current.exportingFormat).toBe('docx');

      await act(async () => {
        vi.advanceTimersByTime(500);
      });

      expect(result.current.isExporting).toBe(false);
      expect(result.current.exportJobId).toBeNull();
    });

    it('useArtifactUpscale tự động reattach active job sau reload từ localStorage', async () => {
      const sessionScope = getSessionScope('session-artifact-test');
      window.localStorage.setItem(
        'huit_active_jobs',
        JSON.stringify({
          [`${sessionScope}:upscale:art-demo-001`]: {
            jobId: 'job-up-reattach-222',
            type: 'upscale',
            artifactId: 'art-demo-001',
            sessionScope,
            meta: { scale: 4 },
            timestamp: Date.now(),
          },
        })
      );

      vi.spyOn(artifactApi, 'fetchJobStatus').mockResolvedValue({
        job_id: 'job-up-reattach-222',
        status: 'completed',
        progress: 100,
        result_url: 'https://cdn.huit.edu.vn/visuals/art-demo-001-4x.png',
      });

      const { result } = renderHook(() => useArtifactUpscale(mockArtifactA));

      expect(result.current.upscaleJobId).toBe('job-up-reattach-222');
      expect(result.current.scaleFactor).toBe(4);

      await act(async () => {
        vi.advanceTimersByTime(1000);
      });

      expect(result.current.isUpscaling).toBe(false);
      expect(result.current.upscaledUrl).toBe('https://cdn.huit.edu.vn/visuals/art-demo-001-4x.png');
    });

    it('useArtifactUpscale không timeout sau 30 giây (tiếp tục poll bền bỉ quá 30s)', async () => {
      vi.spyOn(artifactApi, 'requestArtifactUpscale').mockResolvedValue({
        job_id: 'job-long-run-333',
      });

      vi.spyOn(artifactApi, 'fetchJobStatus').mockResolvedValue({
        job_id: 'job-long-run-333',
        status: 'processing',
        progress: 60,
      });

      const { result } = renderHook(() => useArtifactUpscale(mockArtifactA, { pollIntervalMs: 1000 }));

      await act(async () => {
        await result.current.requestUpscale(2);
      });

      // Vượt qua mốc 30 giây cũ (35 giây = 35 lần 1000ms)
      for (let i = 0; i < 35; i++) {
        await act(async () => {
          vi.advanceTimersByTime(1000);
        });
      }

      // Vẫn đang polling bình thường, KHÔNG bị timeout bỏ rơi sau 30s
      expect(result.current.isUpscaling).toBe(true);
      expect(result.current.upscaleJobId).toBe('job-long-run-333');
      expect(result.current.upscaleError).toBeNull();
    });
  });
});
