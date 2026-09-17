import { useState, useCallback } from 'react';
import { VisualMetadata } from '../../../shared/types/common.types';

export function useVisualLightbox() {
  const [activeVisual, setActiveVisual] = useState<VisualMetadata | null>(null);

  const openLightbox = useCallback((visual: VisualMetadata) => {
    setActiveVisual(visual);
  }, []);

  const closeLightbox = useCallback(() => {
    setActiveVisual(null);
  }, []);

  return {
    activeVisual,
    openLightbox,
    closeLightbox,
    isOpen: activeVisual !== null,
  };
}
