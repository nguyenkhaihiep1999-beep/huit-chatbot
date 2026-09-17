import { useState, useRef, useEffect, useCallback } from 'react';
import { ArtifactSummary, JobStatusResponse } from '../../../shared/types/common.types';
import { requestArtifactUpscale, fetchJobStatus, cancelJob } from '../api/artifactApi';
import { mapApiError } from '../../../shared/utils/errorMapper';
import { saveActiveJob, getActiveJob, clearActiveJob } from '../utils/jobStorage';

export interface UseArtifactUpscaleOptions {
  pollIntervalMs?: number;
  maxAttempts?: number;
}

export interface UseArtifactUpscaleReturn {
  upscaledUrl: string | null;
  scaleFactor: number;
  isUpscaling: boolean;
  upscaleJobId: string | null;
  jobProgress: number;
  upscaleError: string | null;
  requestUpscale: (targetScale: number) => Promise<void>;
  cancelUpscale: () => Promise<void>;
  resetUpscale: () => void;
  clearUpscaleError: () => void;
}

export function useArtifactUpscale(
  artifact: ArtifactSummary | null,
  options?: UseArtifactUpscaleOptions
): UseArtifactUpscaleReturn {
  const pollIntervalMs = options?.pollIntervalMs ?? 1000;
  // Cho phép chạy tới 600 lần polling (~10 phút), KHÔNG timeout cứng 30s
  const maxAttempts = options?.maxAttempts ?? 600;

  const [upscaledUrl, setUpscaledUrl] = useState<string | null>(null);
  const [scaleFactor, setScaleFactor] = useState<number>(1);
  const [isUpscaling, setIsUpscaling] = useState<boolean>(false);
  const [upscaleJobId, setUpscaleJobId] = useState<string | null>(null);
  const [jobProgress, setJobProgress] = useState<number>(0);
  const [upscaleError, setUpscaleError] = useState<string | null>(null);

  const pollTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const isMountedRef = useRef<boolean>(true);
  const activeArtifactIdRef = useRef<string | undefined>(artifact?.artifact_id);
  const activeJobIdRef = useRef<string | null>(null);
  const inFlightRef = useRef<boolean>(false);

  const clearTimer = useCallback(() => {
    if (pollTimerRef.current) {
      clearTimeout(pollTimerRef.current);
      pollTimerRef.current = null;
    }
  }, []);

  const resetUpscale = useCallback(() => {
    clearTimer();
    activeJobIdRef.current = null;
    inFlightRef.current = false;
    setUpscaledUrl(null);
    setScaleFactor(1);
    setIsUpscaling(false);
    setUpscaleJobId(null);
    setJobProgress(0);
    setUpscaleError(null);
  }, [clearTimer]);

  const clearUpscaleError = useCallback(() => {
    setUpscaleError(null);
  }, []);

  const cancelUpscale = useCallback(async () => {
    const currentJobId = activeJobIdRef.current || upscaleJobId;
    const currentArtifactId = activeArtifactIdRef.current;
    clearTimer();
    activeJobIdRef.current = null;
    inFlightRef.current = false;

    if (currentArtifactId) {
      clearActiveJob('upscale', currentArtifactId);
    }

    if (isMountedRef.current) {
      setIsUpscaling(false);
      setUpscaleJobId(null);
      setUpscaleError('Đã hủy tác vụ phóng to ảnh.');
    }

    if (currentJobId) {
      try {
        await cancelJob(currentJobId);
      } catch {
        // Bỏ qua lỗi hủy job nền
      }
    }
  }, [clearTimer, upscaleJobId]);

  // Vòng lặp polling tác vụ upscale
  const startPolling = useCallback(
    (jobId: string, targetScale: number) => {
      activeJobIdRef.current = jobId;
      setUpscaleJobId(jobId);
      setIsUpscaling(true);
      let attempts = 0;

      const poll = async () => {
        const artifactId = activeArtifactIdRef.current;
        if (!isMountedRef.current || !artifactId) {
          return;
        }

        attempts++;
        try {
          const status: JobStatusResponse = await fetchJobStatus(jobId);
          if (!isMountedRef.current || activeArtifactIdRef.current !== artifactId) {
            return;
          }

          setJobProgress(status.progress || Math.min(attempts * 10, 95));

          if (status.status === 'completed' && (status.result_url || status.download_url)) {
            inFlightRef.current = false;
            activeJobIdRef.current = null;
            clearActiveJob('upscale', artifactId);

            setUpscaledUrl(status.result_url || status.download_url || null);
            setScaleFactor(targetScale);
            setIsUpscaling(false);
            setUpscaleJobId(null);
            setJobProgress(100);
          } else if (status.status === 'failed' || status.status === 'cancelled') {
            inFlightRef.current = false;
            activeJobIdRef.current = null;
            clearActiveJob('upscale', artifactId);

            setIsUpscaling(false);
            setUpscaleJobId(null);
            setJobProgress(0);
            const errDetail =
              typeof status.error === 'object' && status.error !== null
                ? (status.error as any).message || (status.error as any).error_code
                : status.error;
            setUpscaleError(errDetail || 'Tác vụ phóng to ảnh không thành công');
          } else if (attempts < maxAttempts) {
            pollTimerRef.current = setTimeout(poll, pollIntervalMs);
          } else {
            inFlightRef.current = false;
            activeJobIdRef.current = null;
            clearActiveJob('upscale', artifactId);

            setIsUpscaling(false);
            setUpscaleJobId(null);
            setUpscaleError('Quá thời gian chờ phóng to ảnh. Bạn vui lòng thử lại.');
          }
        } catch (pollErr) {
          if (isMountedRef.current && activeArtifactIdRef.current === artifactId) {
            if (attempts < maxAttempts) {
              pollTimerRef.current = setTimeout(poll, pollIntervalMs * 2);
            } else {
              inFlightRef.current = false;
              activeJobIdRef.current = null;
              setIsUpscaling(false);
              setUpscaleJobId(null);
              setUpscaleError(mapApiError(pollErr).message || 'Không thể kiểm tra tiến trình phóng to.');
            }
          }
        }
      };

      pollTimerRef.current = setTimeout(poll, pollIntervalMs);
    },
    [maxAttempts, pollIntervalMs]
  );

  // Đặt lại state hoặc reattach job khi đổi artifact
  useEffect(() => {
    const artifactId = artifact?.artifact_id;
    if (artifactId !== activeArtifactIdRef.current) {
      activeArtifactIdRef.current = artifactId;
      resetUpscale();
    }

    if (artifactId && !activeJobIdRef.current) {
      const activeStored = getActiveJob('upscale', artifactId);
      if (activeStored && activeStored.jobId) {
        const scale = activeStored.meta?.scale || 2;
        inFlightRef.current = true;
        setScaleFactor(scale);
        startPolling(activeStored.jobId, scale);
      }
    }
  }, [artifact?.artifact_id, resetUpscale, startPolling]);

  // Quản lý unmount và timer cleanup
  useEffect(() => {
    isMountedRef.current = true;
    return () => {
      isMountedRef.current = false;
      inFlightRef.current = false;
      clearTimer();
    };
  }, [clearTimer]);

  const requestUpscale = useCallback(
    async (targetScale: number) => {
      const artifactId = artifact?.artifact_id;
      if (!artifactId || inFlightRef.current) {
        return; // Synchronous double-click & in-flight protection
      }

      inFlightRef.current = true;
      clearTimer();
      setIsUpscaling(true);
      setUpscaleError(null);
      setJobProgress(10);

      try {
        const res = await requestArtifactUpscale(artifactId, targetScale);

        if (!isMountedRef.current || activeArtifactIdRef.current !== artifactId) {
          inFlightRef.current = false;
          return;
        }

        // Trả kết quả tức thời từ cache/storage nếu có
        if (res.url) {
          inFlightRef.current = false;
          setUpscaledUrl(res.url);
          setScaleFactor(targetScale);
          setIsUpscaling(false);
          setJobProgress(100);
          return;
        }

        // Bắt đầu quy trình polling tác vụ nền bền bỉ
        if (res.job_id) {
          saveActiveJob('upscale', artifactId, res.job_id, { scale: targetScale });
          startPolling(res.job_id, targetScale);
        } else {
          inFlightRef.current = false;
          setIsUpscaling(false);
          setUpscaleError('Không nhận được thông tin tác vụ từ máy chủ.');
        }
      } catch (err) {
        inFlightRef.current = false;
        if (isMountedRef.current && activeArtifactIdRef.current === artifactId) {
          setIsUpscaling(false);
          setUpscaleJobId(null);
          setUpscaleError(mapApiError(err).message);
        }
      }
    },
    [artifact?.artifact_id, clearTimer, startPolling]
  );

  return {
    upscaledUrl,
    scaleFactor,
    isUpscaling,
    upscaleJobId,
    jobProgress,
    upscaleError,
    requestUpscale,
    cancelUpscale,
    resetUpscale,
    clearUpscaleError,
  };
}
