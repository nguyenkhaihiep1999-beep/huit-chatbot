import { useState, useCallback, useMemo, useEffect, useRef } from 'react';
import { ArtifactSummary } from '../../../shared/types/common.types';
import { getArtifactPreviewUrl } from '../api/artifactApi';
import { useArtifactUpscale, UseArtifactUpscaleOptions } from './useArtifactUpscale';
import { useArtifactExport } from './useArtifactExport';

export interface UseArtifactWorkflowOptions extends UseArtifactUpscaleOptions {}

export interface UseArtifactWorkflowReturn {
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
  const upscale = useArtifactUpscale(artifact, options);
  const exportOps = useArtifactExport(artifact?.artifact_id);
  const [previewError, setPreviewError] = useState<string | null>(null);

  const prevArtifactIdRef = useRef<string | undefined>(artifact?.artifact_id);
  useEffect(() => {
    if (artifact?.artifact_id !== prevArtifactIdRef.current) {
      prevArtifactIdRef.current = artifact?.artifact_id;
      setPreviewError(null);
    }
  }, [artifact?.artifact_id]);

  const defaultPreviewUrl = useMemo(() => {
    if (!artifact) return '';
    return (
      artifact.preview_url ||
      (artifact.artifact_id ? getArtifactPreviewUrl(artifact.artifact_id) : '')
    );
  }, [artifact]);

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
