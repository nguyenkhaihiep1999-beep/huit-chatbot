import { apiClient } from '../../../shared/api/httpClient';
import {
  assertImageCreateRequest,
  parseImageResult,
  ImageResultContract,
} from '../../../shared/contracts';

export type ImageGenerationResult = ImageResultContract;

export async function createImage(
  prompt: string,
  backend: 'flux' | 'svg' = 'flux'
): Promise<ImageResultContract> {
  const reqPayload = { prompt, backend };
  assertImageCreateRequest(reqPayload);
  const response = await apiClient('/api/images', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(reqPayload),
  });
  if (!response.ok) throw new Error(`Lỗi máy chủ (${response.status})`);
  const rawData = await response.json();
  return parseImageResult(rawData);
}
