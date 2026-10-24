import { generateUniqueId } from '../../../shared/utils/idGenerator';
import { apiClient } from '../../../shared/api/httpClient';
import { assertChatRequest } from '../../../shared/contracts';

export const API_BASE = '';

export interface SendChatStreamOptions {
  question: string;
  history: Array<{ role: 'user' | 'assistant'; content: string }>;
  enableCache?: boolean;
  signal?: AbortSignal;
  requestId?: string;
  lastSequence?: number;
}

export async function fetchChatStream(options: SendChatStreamOptions): Promise<Response> {
  const reqId = options.requestId || generateUniqueId('client');
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    'X-Request-ID': reqId,
  };
  if (options.lastSequence !== undefined && options.lastSequence > 0) {
    headers['X-Last-Sequence'] = String(options.lastSequence);
  }

  const body = {
    question: options.question,
    history: options.history,
    enable_cache: options.enableCache !== false,
  };
  assertChatRequest(body);

  const response = await apiClient(`${API_BASE}/api/chat-stream`, {
    method: 'POST',
    headers,
    body: JSON.stringify(body),
    signal: options.signal,
  });

  if (!response.ok) {
    const errorText = await response.text();
    throw new Error(`HTTP ${response.status}: ${errorText || response.statusText}`);
  }

  return response;
}

export async function cancelChatStream(requestId: string): Promise<boolean> {
  try {
    const res = await apiClient(`${API_BASE}/api/chat/${encodeURIComponent(requestId)}/cancel`, {
      method: 'POST',
    });
    return res.ok;
  } catch {
    return false;
  }
}
