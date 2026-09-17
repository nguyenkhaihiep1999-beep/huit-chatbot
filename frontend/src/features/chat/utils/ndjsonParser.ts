import { ChatStreamChunk } from '../model/chat.types';

export async function parseNDJSONStream(
  response: Response,
  onChunk: (chunk: ChatStreamChunk) => void,
  signal?: AbortSignal
): Promise<void> {
  const reader = response.body?.getReader();
  if (!reader) {
    throw new Error('Response body is not readable.');
  }

  const decoder = new TextDecoder('utf-8');
  let buffer = '';

  try {
    while (true) {
      if (signal?.aborted) {
        await reader.cancel();
        break;
      }

      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split('\n');
      buffer = lines.pop() || ''; // Giữ lại phần dư chưa kết thúc bằng \n

      for (const line of lines) {
        const trimmed = line.trim();
        if (!trimmed) continue;
        try {
          const parsed = JSON.parse(trimmed) as ChatStreamChunk;
          onChunk(parsed);
        } catch (err) {
          console.warn('Malformed NDJSON line skipped:', trimmed, err);
        }
      }
    }

    // Xử lý nốt buffer còn lại nếu có
    if (buffer.trim()) {
      try {
        const parsed = JSON.parse(buffer.trim()) as ChatStreamChunk;
        onChunk(parsed);
      } catch {
        // ignore incomplete line
      }
    }
  } finally {
    reader.releaseLock();
  }
}
