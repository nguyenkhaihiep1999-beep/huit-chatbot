import { useCallback } from 'react';
import { ArtifactSummary } from '../../../shared/types/common.types';
import {
  cancelJob,
  downloadArtifactExport,
  fetchJobStatus,
  getArtifactPreviewUrl,
  requestArtifactUpscale,
} from '../api/artifactApi';

export function useArtifactActions() {
  const resolvePreviewUrl = useCallback((artifact: ArtifactSummary | null): string => {
    if (!artifact) return '';
    return artifact.preview_url ||
      (artifact.artifact_id ? getArtifactPreviewUrl(artifact.artifact_id) : '');
  }, []);

  return {
    cancelJob,
    downloadArtifactExport,
    fetchJobStatus,
    requestArtifactUpscale,
    resolvePreviewUrl,
  };
}
