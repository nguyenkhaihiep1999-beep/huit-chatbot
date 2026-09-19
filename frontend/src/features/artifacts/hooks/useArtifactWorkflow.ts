import { useState, useCallback, useMemo, useEffect, useRef } from 'react';
import { ArtifactSummary } from '../../../shared/types/common.types';
import { fetchArtifactSummary, getArtifactPreviewUrl } from '../api/artifactApi';
import { useArtifactUpscale, UseArtifactUpscaleOptions } from './useArtifactUpscale';
import { useArtifactExport } from './useArtifactExport';

export interface UseArtifactWorkflowOptions extends UseArtifactUpscaleOptions {
  manifestPollIntervalMs?: number;
  manifestMaxAttempts?: number;
}

export interface UseArtifactWorkflowReturn {
  resolvedArtifact: ArtifactSummary | null;
  activePreviewUrl: string;
  defaultPreviewUrl: string;
  upscaledUrl: string | null;
  scaleFactor: number;
  isUpscaling: boolean;
  upscaleJobId: string | null;
  jobProgress: number;
  exportingFormat: string | null;
  isExporting: boolean;
  errorMessage: string | null;
  requestUpscale: (scale: number) => Promise<void>;
  cancelUpscale: () => Promise<void>;
  downloadArtifactExport: (format: string, filename?: string) => Promise<boolean>;
  setPreviewError: (err: string | null) => void;
  clearError: () => void;
  reset: () => void;
}

export function useArtifactWorkflow(
  artifact: ArtifactSummary | null,
  options?: UseArtifactWorkflowOptions
): UseArtifactWorkflowReturn {
  const [manifestSummary, setManifestSummary] = useState<ArtifactSummary | null>(null);

  const resolvedArtifact = useMemo(() => {
    if (!artifact) return null;
    if (manifestSummary?.artifact_id !== artifact.artifact_id) return artifact;
    return { ...artifact, ...manifestSummary };
  }, [artifact, manifestSummary]);

  const upscale = useArtifactUpscale(resolvedArtifact, options);
  const exportOps = useArtifactExport(resolvedArtifact?.artifact_id);
  const [previewError, setPreviewError] = useState<string | null>(null);

  useEffect(() => {
    if (!artifact?.artifact_id || !['planned', 'rendering'].includes(artifact.status || '')) {
      return;
    }

    const artifactId = artifact.artifact_id;
    const intervalMs = Math.max(250, options?.manifestPollIntervalMs ?? 750);
    const maxAttempts = Math.max(1, options?.manifestMaxAttempts ?? 12);
    let attempts = 0;
    let disposed = false;
    let timer: ReturnType<typeof setTimeout> | null = null;

    const scheduleNext = () => {
      if (!disposed) timer = setTimeout(pollManifest, intervalMs);
    };

    const markUnavailable = () => {
      if (disposed) return;
      setManifestSummary({
        ...artifact,
        status: 'unavailable',
        error_message: 'Quá thời gian chờ bản xem trước. Vui lòng thử lại sau.',
      });
    };

    const pollManifest = async () => {
      attempts += 1;
      try {
        const latest = await fetchArtifactSummary(artifactId);
        if (disposed) return;
        setManifestSummary(latest);
        if (['ready', 'failed', 'unavailable'].includes(latest.status || '')) return;
      } catch {
        if (disposed) return;
      }

      if (attempts >= maxAttempts) {
        markUnavailable();
        return;
      }
      scheduleNext();
    };

    void pollManifest();
    return () => {
      disposed = true;
      if (timer !== null) clearTimeout(timer);
    };
  }, [artifact, options?.manifestMaxAttempts, options?.manifestPollIntervalMs]);

  const prevArtifactIdRef = useRef<string | undefined>(artifact?.artifact_id);
  useEffect(() => {
    if (artifact?.artifact_id !== prevArtifactIdRef.current) {
      prevArtifactIdRef.current = artifact?.artifact_id;
      setPreviewError(null);
    }
  }, [artifact?.artifact_id]);

  const defaultPreviewUrl = useMemo(() => {
    if (!resolvedArtifact) return '';
    return (
      resolvedArtifact.preview_url ||
      (resolvedArtifact.artifact_id ? getArtifactPreviewUrl(resolvedArtifact.artifact_id) : '')
    );
  }, [resolvedArtifact]);

  const activePreviewUrl = upscale.upscaledUrl || defaultPreviewUrl;
  const errorMessage = upscale.upscaleError || exportOps.exportError || previewError;

  const clearError = useCallback(() => {
    upscale.clearUpscaleError();
    exportOps.clearExportError();
    setPreviewError(null);
  }, [exportOps, upscale]);

  const reset = useCallback(() => {
    upscale.resetUpscale();
    exportOps.resetExport();
    setPreviewError(null);
  }, [exportOps, upscale]);

  return {
    resolvedArtifact,
    activePreviewUrl,
    defaultPreviewUrl,
    upscaledUrl: upscale.upscaledUrl,
    scaleFactor: upscale.scaleFactor,
    isUpscaling: upscale.isUpscaling,
    upscaleJobId: upscale.upscaleJobId,
    jobProgress: upscale.jobProgress,
    exportingFormat: exportOps.exportingFormat,
    isExporting: exportOps.isExporting,
    errorMessage,
    requestUpscale: upscale.requestUpscale,
    cancelUpscale: upscale.cancelUpscale,
    downloadArtifactExport: exportOps.exportArtifact,
    setPreviewError,
    clearError,
    reset,
  };
}
