import { useState, useRef, useEffect, useCallback } from 'react';
import {
  downloadArtifactExport,
  requestArtifactExport,
  fetchJobStatus,
  cancelJob,
  triggerFileDownload,
} from '../api/artifactApi';
import { mapApiError } from '../../../shared/utils/errorMapper';
import { saveActiveJob, getActiveJob, clearActiveJob } from '../utils/jobStorage';
import type { JobStatusResponse } from '../../../shared/types/common.types';

export interface UseArtifactExportReturn {
  exportingFormat: string | null;
  isExporting: boolean;
  exportJobId: string | null;
  exportProgress: number;
  exportError: string | null;
  exportArtifact: (format: string, filename?: string) => Promise<boolean>;
  cancelExport: () => Promise<void>;
  clearExportError: () => void;
  resetExport: () => void;
}

export function useArtifactExport(artifactId: string | undefined): UseArtifactExportReturn {
  const [exportingFormat, setExportingFormat] = useState<string | null>(null);
  const [exportJobId, setExportJobId] = useState<string | null>(null);
  const [exportProgress, setExportProgress] = useState<number>(0);
  const [exportError, setExportError] = useState<string | null>(null);

  const isMountedRef = useRef<boolean>(true);
  const activeIdRef = useRef<string | undefined>(artifactId);
  const inFlightRef = useRef<boolean>(false);
  const activeJobIdRef = useRef<string | null>(null);
  const pollTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const clearTimer = useCallback(() => {
    if (pollTimerRef.current) {
      clearTimeout(pollTimerRef.current);
      pollTimerRef.current = null;
    }
  }, []);

  const clearExportError = useCallback(() => {
    setExportError(null);
  }, []);

  const resetExport = useCallback(() => {
    clearTimer();
    inFlightRef.current = false;
    activeJobIdRef.current = null;
    setExportingFormat(null);
    setExportJobId(null);
    setExportProgress(0);
    setExportError(null);
  }, [clearTimer]);

  // Hủy tác vụ xuất file đang chạy
  const cancelExport = useCallback(async () => {
    const currentJobId = activeJobIdRef.current || exportJobId;
    clearTimer();
    inFlightRef.current = false;
    activeJobIdRef.current = null;

    if (artifactId) {
      clearActiveJob('export', artifactId);
    }

    if (isMountedRef.current) {
      setExportingFormat(null);
      setExportJobId(null);
      setExportProgress(0);
      setExportError('Đã hủy tác vụ xuất tài liệu.');
    }

    if (currentJobId) {
      try {
        await cancelJob(currentJobId);
      } catch {
        // Bỏ qua lỗi mạng khi hủy job
      }
    }
  }, [artifactId, clearTimer, exportJobId]);

  // Vòng lặp polling tác vụ xuất file (hỗ trợ tối đa 600 lần ~ 10 phút, không timeout sau 30s)
  const startPolling = useCallback(
    (jobId: string, format: string, filename?: string) => {
      activeJobIdRef.current = jobId;
      setExportJobId(jobId);
      setExportingFormat(format);
      let attempts = 0;
      const maxAttempts = 600; // Tối đa 10 phút

      const poll = async () => {
        if (!isMountedRef.current || activeIdRef.current !== artifactId) {
          return;
        }

        attempts++;
        try {
          const status: JobStatusResponse = await fetchJobStatus(jobId);
          if (!isMountedRef.current || activeIdRef.current !== artifactId) {
            return;
          }

          setExportProgress(status.progress || Math.min(attempts * 10, 95));

          if (status.status === 'completed') {
            inFlightRef.current = false;
            activeJobIdRef.current = null;
            if (artifactId) {
              clearActiveJob('export', artifactId);
            }

            const downloadUrl = status.download_url || status.result_url;
            if (downloadUrl) {
              triggerFileDownload(downloadUrl, filename || `${artifactId}.${format}`);
            }

            setExportProgress(100);
            setExportingFormat(null);
            setExportJobId(null);
          } else if (status.status === 'failed' || status.status === 'cancelled') {
            inFlightRef.current = false;
            activeJobIdRef.current = null;
            if (artifactId) {
              clearActiveJob('export', artifactId);
            }

            setExportingFormat(null);
            setExportJobId(null);
            setExportProgress(0);
            const errDetail =
              typeof status.error === 'object' && status.error !== null
                ? (status.error as any).message || (status.error as any).error_code
                : status.error;
            setExportError(errDetail || 'Xuất tài liệu không thành công.');
          } else if (attempts < maxAttempts) {
            // Khoảng cách polling 1000ms
            pollTimerRef.current = setTimeout(poll, 1000);
          } else {
            inFlightRef.current = false;
            activeJobIdRef.current = null;
            if (artifactId) {
              clearActiveJob('export', artifactId);
            }
            setExportingFormat(null);
            setExportJobId(null);
            setExportError('Quá thời gian xử lý xuất tài liệu. Vui lòng thử lại sau.');
          }
        } catch (pollErr) {
          if (isMountedRef.current && activeIdRef.current === artifactId) {
            // Không ngắt quãng ngay khi gặp 1 lỗi mạng tạm thời, thử lại sau 2 giây
            if (attempts < maxAttempts) {
              pollTimerRef.current = setTimeout(poll, 2000);
            } else {
              inFlightRef.current = false;
              activeJobIdRef.current = null;
              setExportingFormat(null);
              setExportJobId(null);
              setExportError(mapApiError(pollErr).message || 'Không thể kiểm tra tiến trình xuất file.');
            }
          }
        }
      };

      pollTimerRef.current = setTimeout(poll, 500);
    },
    [artifactId]
  );

  // Reattach active job sau khi reload trang từ localStorage
  useEffect(() => {
    if (artifactId !== activeIdRef.current) {
      activeIdRef.current = artifactId;
      resetExport();
    }

    if (artifactId) {
      const activeStored = getActiveJob('export', artifactId);
      if (activeStored && activeStored.jobId) {
        const fmt = activeStored.meta?.format || 'xlsx';
        const fn = activeStored.meta?.filename;
        inFlightRef.current = true;
        setExportingFormat(fmt);
        setExportJobId(activeStored.jobId);
        startPolling(activeStored.jobId, fmt, fn);
      }
    }
  }, [artifactId, resetExport, startPolling]);

  useEffect(() => {
    isMountedRef.current = true;
    return () => {
      isMountedRef.current = false;
      inFlightRef.current = false;
      clearTimer();
    };
  }, [clearTimer]);

  const exportArtifact = useCallback(
    async (format: string, filename?: string): Promise<boolean> => {
      if (!artifactId || inFlightRef.current) {
        return false; // Synchronous double-click & in-flight protection
      }

      inFlightRef.current = true;
      clearTimer();
      setExportingFormat(format);
      setExportError(null);
      setExportProgress(10);

      try {
        // Gửi yêu cầu qua downloadArtifactExport (nhận job_id trên server hoặc blob trong unit test)
        const res: any = filename
          ? await downloadArtifactExport(artifactId, format, filename)
          : await downloadArtifactExport(artifactId, format);

        if (!isMountedRef.current || activeIdRef.current !== artifactId) {
          inFlightRef.current = false;
          return false;
        }

        // Nếu máy chủ trả về job_id: bắt đầu quy trình polling bền bỉ!
        if (res && typeof res === 'object' && res.job_id) {
          saveActiveJob('export', artifactId, res.job_id, { format, filename });
          startPolling(res.job_id, format, filename);
          return true;
        }

        // Nếu tải thành công tức thì (Blob hoặc Signed URL)
        inFlightRef.current = false;
        if (artifactId) {
          clearActiveJob('export', artifactId);
        }
        setExportProgress(100);
        setExportingFormat(null);
        setExportJobId(null);
        return true;
      } catch (err) {
        inFlightRef.current = false;
        if (isMountedRef.current && activeIdRef.current === artifactId) {
          setExportingFormat(null);
          setExportJobId(null);
          setExportProgress(0);
          setExportError(mapApiError(err).message);
        }
        return false;
      }
    },
    [artifactId, clearTimer, startPolling]
  );

  return {
    exportingFormat,
    isExporting: Boolean(exportingFormat),
    exportJobId,
    exportProgress,
    exportError,
    exportArtifact,
    cancelExport,
    clearExportError,
    resetExport,
  };
}
