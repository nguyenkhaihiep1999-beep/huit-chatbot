import { ChatStreamChunk } from '../model/chat.types';
import { parseChatStreamEvent } from '../../../shared/contracts';

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
          const parsed = parseChatStreamEvent(JSON.parse(trimmed));
          onChunk(parsed as ChatStreamChunk);
        } catch (err) {
          console.warn('NDJSON event rejected by canonical schema:', err instanceof Error ? err.message : 'unknown error');
        }
      }
    }

    // Xử lý nốt buffer còn lại nếu có
    if (buffer.trim()) {
      try {
        const parsed = parseChatStreamEvent(JSON.parse(buffer.trim()));
        onChunk(parsed as ChatStreamChunk);
      } catch {
        // ignore incomplete line
      }
    }
  } finally {
    reader.releaseLock();
  }
}
