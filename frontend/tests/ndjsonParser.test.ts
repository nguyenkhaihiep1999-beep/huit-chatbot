import { describe, it, expect, vi } from 'vitest';
import { parseNDJSONStream } from '../src/features/chat/utils/ndjsonParser';

describe('NDJSON Stream Parser', () => {
  function createMockResponse(chunks: string[]): Response {
    const encoder = new TextEncoder();
    let index = 0;
    const stream = new ReadableStream<Uint8Array>({
      pull(controller) {
        if (index < chunks.length) {
          controller.enqueue(encoder.encode(chunks[index]));
          index++;
        } else {
          controller.close();
        }
      },
    });

    return new Response(stream, {
      status: 200,
      headers: { 'Content-Type': 'application/x-ndjson' },
    });
  }

  it('phân tích chính xác các dòng NDJSON hoàn chỉnh', async () => {
    const rawChunks = [
      '{"type":"meta","sources":[{"i":1,"title":"HUIT"}],"trace":[],"cached":false}\n',
      '{"type":"token","token":"Chào "}\n',
      '{"type":"token","token":"bạn!"}\n',
    ];
    const response = createMockResponse(rawChunks);
    const received: Record<string, unknown>[] = [];

    await parseNDJSONStream(response, (chunk) => {
      received.push(chunk);
    });

    expect(received).toHaveLength(3);
    expect(received[0].type).toBe('meta');
    expect(received[1].token).toBe('Chào ');
    expect(received[2].token).toBe('bạn!');
  });

  it('ghép đúng các chunk bị cắt đôi giữa dòng (partial chunks across boundaries)', async () => {
    // Dòng thứ hai bị cắt làm đôi giữa hai chunk mạng
    const rawChunks = [
      '{"type":"token","token":"Đại ',
      'học"}\n{"type":"token","token":" Công Thương"}\n',
    ];
    const response = createMockResponse(rawChunks);
    const received: Record<string, unknown>[] = [];

    await parseNDJSONStream(response, (chunk) => {
      received.push(chunk);
    });

    expect(received).toHaveLength(2);
    expect(received[0].token).toBe('Đại học');
    expect(received[1].token).toBe(' Công Thương');
  });

  it('xử lý abort signal mà không gây crash', async () => {
    const controller = new AbortController();
    const encoder = new TextEncoder();
    const stream = new ReadableStream<Uint8Array>({
      start(ctrl) {
        ctrl.enqueue(encoder.encode('{"type":"token","token":"Token 1"}\n'));
      },
      pull() {
        // stream giữ mở để chờ abort
      },
    });

    const response = new Response(stream);
    const received: Record<string, unknown>[] = [];

    const parsePromise = parseNDJSONStream(
      response,
      (chunk) => {
        received.push(chunk);
        controller.abort();
      },
      controller.signal
    );

    // Abort signal được kích hoạt trong callback
    await parsePromise;
    expect(received).toHaveLength(1);
    expect(received[0].token).toBe('Token 1');
  });

  it('bỏ qua dòng trống và JSON lỗi cú pháp an toàn', async () => {
    const rawChunks = [
      '\n\n',
      '{"type":"token","token":"Hợp lệ"}\n',
      'DONG_KHONG_PHAI_JSON\n',
      '{"type":"token","token":"Sau lỗi"}\n',
    ];
    const response = createMockResponse(rawChunks);
    const received: Record<string, unknown>[] = [];
    const consoleWarnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {});

    await parseNDJSONStream(response, (chunk) => {
      received.push(chunk);
    });

    expect(received).toHaveLength(2);
    expect(received[0].token).toBe('Hợp lệ');
    expect(received[1].token).toBe('Sau lỗi');
    consoleWarnSpy.mockRestore();
  });
});
