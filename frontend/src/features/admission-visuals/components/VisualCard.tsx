import React from 'react';
import { VisualMetadata, ArtifactSummary } from '../../../shared/types/common.types';
import { ArtifactCard } from '../../artifacts/components/ArtifactCard';

interface VisualCardProps {
  visual: VisualMetadata;
  onOpenLightbox?: (visual: VisualMetadata) => void;
}

export const VisualCard: React.FC<VisualCardProps> = ({ visual, onOpenLightbox }) => {
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

  const handleLightbox = onOpenLightbox
    ? () => onOpenLightbox(visual)
    : undefined;

  return <ArtifactCard artifact={artifactSummary} onOpenLightbox={handleLightbox} />;
};
