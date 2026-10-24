import { useState, useCallback } from 'react';
import { createImage, ImageGenerationResult } from '../api/imageGenerationApi';

export type { ImageGenerationResult } from '../api/imageGenerationApi';

export function useImageGeneration() {
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<ImageGenerationResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  const generateImage = useCallback(async (prompt: string, backend: 'flux' | 'svg' = 'flux') => {
    setLoading(true);
    setError(null);
    try {
      const data = await createImage(prompt, backend);
      setResult(data);
      return data;
    } catch (err: any) {
      setError(err.message || 'Không thể tạo ảnh.');
      return null;
    } finally {
      setLoading(false);
    }
  }, []);

  const reset = useCallback(() => {
    setResult(null);
    setError(null);
    setLoading(false);
  }, []);

  return {
    loading,
    result,
    error,
    generateImage,
    reset,
  };
}
