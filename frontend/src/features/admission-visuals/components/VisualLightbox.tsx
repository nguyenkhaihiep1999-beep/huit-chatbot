import React from 'react';
import { VisualMetadata, ArtifactSummary } from '../../../shared/types/common.types';
import { ArtifactLightbox } from '../../artifacts/components/ArtifactLightbox';

interface VisualLightboxProps {
  visual: VisualMetadata | null;
  onClose: () => void;
}

export const VisualLightbox: React.FC<VisualLightboxProps> = ({ visual, onClose }) => {
  if (!visual) return null;

  const artifactSummary: ArtifactSummary = {
    artifact_id: visual.artifact_id || visual.visual_id,
    type: visual.type || 'chart',
    title: visual.title || 'Đồ họa & Dữ liệu Tuyển sinh HUIT',
    preview_url: visual.svg_url,
    manifest_url: visual.json_url,
    available_formats: visual.available_formats || ['svg', 'png', 'pdf', 'xlsx', 'docx'],
    status: visual.status || 'ready',
  };

  return <ArtifactLightbox artifact={artifactSummary} onClose={onClose} />;
};
