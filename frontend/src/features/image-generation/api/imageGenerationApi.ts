import { apiClient } from '../../../shared/api/httpClient';

export interface ImageGenerationResult {
  image_id: string;
  id?: string;
  backend?: 'flux' | 'svg';
  title?: string;
  image_url: string;
  thumbnail_url?: string;
  svg_url?: string;
  json_url?: string;
  width?: number;
  height?: number;
  model?: string;
  byte_size?: number;
  checksum?: string;
  cached?: boolean;
}

export async function createImage(
  prompt: string,
  backend: 'flux' | 'svg' = 'flux'
): Promise<ImageGenerationResult> {
  const response = await apiClient('/api/images', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ prompt, backend }),
  });
  if (!response.ok) throw new Error(`Lỗi máy chủ (${response.status})`);
  return response.json();
}
