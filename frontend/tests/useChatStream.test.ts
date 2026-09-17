import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import { useChatStream } from '../src/features/chat/hooks/useChatStream';
import * as chatApi from '../src/features/chat/api/chatApi';
import { telemetryTracker } from '../src/observability/telemetryTracker';
import type { ChatMessage } from '../src/shared/types/common.types';

// Helper tạo mock Response chứa các dòng NDJSON
function createNDJSONResponse(lines: string[], delayMs: number = 0): Response {
  const encoder = new TextEncoder();
  let idx = 0;
  const stream = new ReadableStream<Uint8Array>({
    async pull(controller) {
      if (delayMs > 0) {
        await new Promise((resolve) => setTimeout(resolve, delayMs));
      }
      if (idx < lines.length) {
        controller.enqueue(encoder.encode(lines[idx] + '\n'));
        idx++;
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

describe('useChatStream Hook (Full Production Flow Tests)', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    telemetryTracker.clearMetrics();
    vi.restoreAllMocks();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('1. Stream hoàn thành: nhận đủ callbacks onMessageStart, onTokenChunk và onMessageComplete', async () => {
    const lines = [
      JSON.stringify({ type: 'meta', sources: [{ i: 1, title: 'HUIT', url: 'https://huit.edu.vn' }], trace: [], cached: false }),
      JSON.stringify({ type: 'token', token: 'Chào ' }),
      JSON.stringify({ type: 'token', token: 'bạn!' }),
    ];
    vi.spyOn(chatApi, 'fetchChatStream').mockResolvedValue(createNDJSONResponse(lines));

    const onMessageStart = vi.fn();
    const onTokenChunk = vi.fn();
    const onMessageComplete = vi.fn();
    const onError = vi.fn();

    const { result } = renderHook(() =>
      useChatStream({ onMessageStart, onTokenChunk, onMessageComplete, onError })
    );

    let p: Promise<void>;
    act(() => {
      p = result.current.sendQuery('Xin chào', [], 'session-01');
    });

    expect(result.current.isStreaming).toBe(true);
    expect(onMessageStart).toHaveBeenCalledWith(
      expect.stringMatching(/^ai-/),
      'session-01',
      expect.stringMatching(/^req-fe-/)
    );

    await act(async () => {
      vi.advanceTimersByTime(100);
      await p!;
    });

    expect(result.current.isStreaming).toBe(false);
    expect(onMessageComplete).toHaveBeenCalledTimes(1);
    const finishedMsg: ChatMessage = onMessageComplete.mock.calls[0][0];
    expect(finishedMsg.content).toBe('Chào bạn!');
    expect(finishedMsg.sources).toHaveLength(1);
    expect(finishedMsg.isStreaming).toBe(false);
  });

  it('2. Abort trước token đầu tiên: không crash, lưu thông báo dừng với nội dung rỗng', async () => {
    let _streamCtrl: ReadableStreamDefaultController<Uint8Array>;
    const stream = new ReadableStream<Uint8Array>({
      start(ctrl) {
        _streamCtrl = ctrl;
      },
    });
    vi.spyOn(chatApi, 'fetchChatStream').mockResolvedValue(new Response(stream));

    const onMessageComplete = vi.fn();
    const { result } = renderHook(() =>
      useChatStream({ onMessageComplete })
    );

    act(() => {
      result.current.sendQuery('Hỏi dở', [], 'session-01');
    });

    // Bấm dừng ngay lập tức trước khi server trả về token nào
    act(() => {
      result.current.stopStreaming();
    });

    expect(result.current.isStreaming).toBe(false);
    expect(onMessageComplete).toHaveBeenCalledTimes(1);
    const stoppedMsg: ChatMessage = onMessageComplete.mock.calls[0][0];
    expect(stoppedMsg.content).toBe(' _[Đã dừng sinh]_');
    expect(stoppedMsg.isStreaming).toBe(false);
  });

  it('3. Abort sau một số token: giữ trọn vẹn các token đã nhận và nối hậu tố đã dừng', async () => {
    const encoder = new TextEncoder();
    const stream = new ReadableStream<Uint8Array>({
      start(ctrl) {
        ctrl.enqueue(encoder.encode(JSON.stringify({ type: 'token', token: 'Trường Đại học ' }) + '\n'));
        ctrl.enqueue(encoder.encode(JSON.stringify({ type: 'token', token: 'Công Thương ' }) + '\n'));
      },
    });
    vi.spyOn(chatApi, 'fetchChatStream').mockResolvedValue(new Response(stream));

    const onMessageComplete = vi.fn();
    const { result } = renderHook(() =>
      useChatStream({ onMessageComplete })
    );

    act(() => {
      result.current.sendQuery('Hỏi dở', [], 'session-01');
    });

    await act(async () => {
      vi.advanceTimersByTime(40);
    });

    act(() => {
      result.current.stopStreaming();
    });

    expect(onMessageComplete).toHaveBeenCalledTimes(1);
    const stoppedMsg: ChatMessage = onMessageComplete.mock.calls[0][0];
    expect(stoppedMsg.content).toContain('Trường Đại học Công Thương ');
    expect(stoppedMsg.content).toContain('_[Đã dừng sinh]_');
  });

  it('4. Gọi stopStreaming hai lần (Idempotent): chỉ chốt đúng 1 lần, không sinh message trùng lặp', async () => {
    const stream = new ReadableStream<Uint8Array>({
      start(ctrl) {
        const enc = new TextEncoder();
        ctrl.enqueue(enc.encode(JSON.stringify({ type: 'token', token: 'Nội dung dở' }) + '\n'));
      },
    });
    vi.spyOn(chatApi, 'fetchChatStream').mockResolvedValue(new Response(stream));

    const onMessageComplete = vi.fn();
    const { result } = renderHook(() =>
      useChatStream({ onMessageComplete })
    );

    act(() => {
      result.current.sendQuery('Hỏi', [], 'session-01');
    });

    await act(async () => {
      vi.advanceTimersByTime(40);
    });

    // Gọi lần 1
    act(() => {
      result.current.stopStreaming();
    });

    // Gọi lần 2
    act(() => {
      result.current.stopStreaming();
    });

    expect(onMessageComplete).toHaveBeenCalledTimes(1);
  });

  it('5. Dừng rồi gửi request mới ngay: finally của request cũ không xóa timer hay isStreaming của request mới', async () => {
    let req1Resolve: (val: Response) => void;
    const req1Promise = new Promise<Response>((res) => {
      req1Resolve = res;
    });

    const linesReq2 = [JSON.stringify({ type: 'token', token: 'Kết quả request 2' })];
    vi.spyOn(chatApi, 'fetchChatStream')
      .mockImplementationOnce(() => req1Promise)
      .mockImplementationOnce(() => Promise.resolve(createNDJSONResponse(linesReq2)));

    const onMessageComplete = vi.fn();
    const { result } = renderHook(() =>
      useChatStream({ onMessageComplete })
    );

    act(() => {
      result.current.sendQuery('Câu 1', [], 'session-01');
    });
    expect(result.current.isStreaming).toBe(true);

    let req2Promise: Promise<void>;
    act(() => {
      result.current.stopStreaming();
      req2Promise = result.current.sendQuery('Câu 2', [], 'session-01');
    });
    expect(result.current.isStreaming).toBe(true);

    // Kích hoạt abort của req 1
    req1Resolve!(new Response(new ReadableStream({
      start(ctrl) {
        ctrl.error(new DOMException('Aborted', 'AbortError'));
      },
    })));

    await act(async () => {
      vi.advanceTimersByTime(100);
      await req2Promise!;
    });

    const finalCalls = onMessageComplete.mock.calls;
    const lastCall = finalCalls[finalCalls.length - 1];
    expect(lastCall[0].content).toBe('Kết quả request 2');
    expect(result.current.isStreaming).toBe(false);
  });

  it('6. sendQuery thay thế request cũ mà không gọi stop trước: request cũ chốt đúng 1 lần', async () => {
    let _req1Resolve: (val: Response) => void;
    const req1Promise = new Promise<Response>((res) => {
      _req1Resolve = res;
    });

    const linesReq2 = [JSON.stringify({ type: 'token', token: 'Câu trả lời mới thay thế' })];
    vi.spyOn(chatApi, 'fetchChatStream')
      .mockImplementationOnce(() => req1Promise)
      .mockImplementationOnce(() => Promise.resolve(createNDJSONResponse(linesReq2)));

    const onMessageComplete = vi.fn();
    const { result } = renderHook(() =>
      useChatStream({ onMessageComplete })
    );

    // Gửi request 1 (đang chờ)
    act(() => {
      result.current.sendQuery('Request 1', [], 'session-01');
    });

    // Thay thế trực tiếp bằng request 2 mà KHÔNG gọi stopStreaming trước
    let p2: Promise<void>;
    act(() => {
      p2 = result.current.sendQuery('Request 2', [], 'session-01');
    });

    await act(async () => {
      vi.advanceTimersByTime(100);
      await p2!;
    });

    // Request 1 được chốt với [Đã dừng sinh], Request 2 hoàn thành
    expect(onMessageComplete).toHaveBeenCalledTimes(2);
    expect(onMessageComplete.mock.calls[0][0].content).toContain('_[Đã dừng sinh]_');
    expect(onMessageComplete.mock.calls[1][0].content).toBe('Câu trả lời mới thay thế');
  });

  it('7. Response cũ trả về muộn (Stale Response): bị loại bỏ và không ghi đè context mới', async () => {
    let lateResolve: (val: Response) => void;
    const latePromise = new Promise<Response>((res) => {
      lateResolve = res;
    });

    const linesNew = [JSON.stringify({ type: 'token', token: 'Tin nhắn mới nhất' })];
    vi.spyOn(chatApi, 'fetchChatStream')
      .mockImplementationOnce(() => latePromise)
      .mockImplementationOnce(() => Promise.resolve(createNDJSONResponse(linesNew)));

    const onMessageComplete = vi.fn();
    const { result } = renderHook(() =>
      useChatStream({ onMessageComplete })
    );

    act(() => {
      result.current.sendQuery('Cũ', [], 'session-01');
    });

    let p2: Promise<void>;
    act(() => {
      p2 = result.current.sendQuery('Mới', [], 'session-01');
    });

    // Response cũ trả về trễ
    lateResolve!(createNDJSONResponse([JSON.stringify({ type: 'token', token: 'Rò rỉ cũ' })]));

    await act(async () => {
      vi.advanceTimersByTime(100);
      await p2!;
    });

    const calls = onMessageComplete.mock.calls;
    const lastMsg = calls[calls.length - 1][0];
    expect(lastMsg.content).toBe('Tin nhắn mới nhất');
  });

  it('8. Lỗi mạng: gọi onError kèm aiMsgId, không để pending message rỗng', async () => {
    vi.spyOn(chatApi, 'fetchChatStream').mockRejectedValue(new Error('Network offline'));

    const onMessageStart = vi.fn();
    const onError = vi.fn();
    const { result } = renderHook(() =>
      useChatStream({ onMessageStart, onError })
    );

    await act(async () => {
      const p = result.current.sendQuery('Test error', [], 'session-01');
      await p;
    });

    expect(onMessageStart).toHaveBeenCalledTimes(1);
    const aiId = onMessageStart.mock.calls[0][0];

    expect(onError).toHaveBeenCalledTimes(1);
    expect(onError).toHaveBeenCalledWith(
      expect.any(Error),
      'session-01',
      aiId,
      expect.stringMatching(/^req-fe-/)
    );
    expect(result.current.isStreaming).toBe(false);
  });

  it('9. NDJSON bị chia nhỏ giữa các chunk: parser ghép dòng chính xác', async () => {
    const encoder = new TextEncoder();
    const stream = new ReadableStream<Uint8Array>({
      start(ctrl) {
        // Chunk 1 bị cắt dở
        ctrl.enqueue(encoder.encode('{"type":"token","to'));
        // Chunk 2 hoàn tất dòng
        ctrl.enqueue(encoder.encode('ken":"Ghép thành công"}\n'));
        ctrl.close();
      },
    });
    vi.spyOn(chatApi, 'fetchChatStream').mockResolvedValue(new Response(stream));

    const onMessageComplete = vi.fn();
    const { result } = renderHook(() =>
      useChatStream({ onMessageComplete })
    );

    await act(async () => {
      const p = result.current.sendQuery('Test split', [], 'session-01');
      vi.advanceTimersByTime(50);
      await p;
    });

    expect(onMessageComplete).toHaveBeenCalledTimes(1);
    expect(onMessageComplete.mock.calls[0][0].content).toBe('Ghép thành công');
  });

  it('10. Token cuối không có ký tự xuống dòng: vẫn xử lý và xả trọn vẹn', async () => {
    const encoder = new TextEncoder();
    const stream = new ReadableStream<Uint8Array>({
      start(ctrl) {
        // Dòng cuối KHÔNG có ký tự \n
        ctrl.enqueue(encoder.encode('{"type":"token","token":"Không có xuống dòng"}'));
        ctrl.close();
      },
    });
    vi.spyOn(chatApi, 'fetchChatStream').mockResolvedValue(new Response(stream));

    const onMessageComplete = vi.fn();
    const { result } = renderHook(() =>
      useChatStream({ onMessageComplete })
    );

    await act(async () => {
      const p = result.current.sendQuery('Test no newline', [], 'session-01');
      vi.advanceTimersByTime(50);
      await p;
    });

    expect(onMessageComplete).toHaveBeenCalledTimes(1);
    expect(onMessageComplete.mock.calls[0][0].content).toBe('Không có xuống dòng');
  });

  it('11. Cleanup khi unmount: bảo lưu token và abort controller an toàn', () => {
    const stream = new ReadableStream<Uint8Array>({
      start(ctrl) {
        const enc = new TextEncoder();
        ctrl.enqueue(enc.encode(JSON.stringify({ type: 'token', token: 'Token trước unmount' }) + '\n'));
      },
    });
    vi.spyOn(chatApi, 'fetchChatStream').mockResolvedValue(new Response(stream));

    const onMessageComplete = vi.fn();
    const { result, unmount } = renderHook(() =>
      useChatStream({ onMessageComplete })
    );

    act(() => {
      result.current.sendQuery('Unmount test', [], 'session-01');
    });

    // Unmount hook khi stream đang chạy
    unmount();

    // Callback hoàn tất được gọi để bảo lưu tin nhắn trước khi unmount
    expect(onMessageComplete).toHaveBeenCalledTimes(1);
    const stoppedMsg: ChatMessage = onMessageComplete.mock.calls[0][0];
    expect(stoppedMsg.content).toContain('_[Đã dừng sinh]_');
  });

  it('12. Metadata không được tính là Content TTFT', async () => {
    const lines = [
      JSON.stringify({ type: 'meta', sources: [{ i: 1, title: 'HUIT' }], trace: [], cached: false }),
      JSON.stringify({ type: 'token', token: 'Token thực đầu tiên' }),
    ];
    vi.spyOn(chatApi, 'fetchChatStream').mockResolvedValue(createNDJSONResponse(lines));

    const { result } = renderHook(() => useChatStream({}));
    const recordTokenSpy = vi.spyOn(telemetryTracker, 'recordContentToken');

    await act(async () => {
      const p = result.current.sendQuery('Đo TTFT', [], 'session-01');
      vi.advanceTimersByTime(50);
      await p;
    });

    expect(recordTokenSpy).toHaveBeenCalledTimes(1);
    expect(recordTokenSpy).toHaveBeenCalledWith(expect.any(String), 'Token thực đầu tiên');
  });

  it('13. NDJSON v2: Hoàn thành bình thường khi có sự kiện completed', async () => {
    const lines = [
      JSON.stringify({ type: 'meta', protocol_version: 2, sequence: 1, payload: { sources: [], trace: [] } }),
      JSON.stringify({ type: 'text_delta', protocol_version: 2, sequence: 2, payload: { delta: 'Nội dung v2' } }),
      JSON.stringify({ type: 'text_completed', protocol_version: 2, sequence: 3, payload: { length: 11 } }),
      JSON.stringify({ type: 'completed', protocol_version: 2, sequence: 4, payload: { latency_ms: 120, cached: false } }),
    ];
    vi.spyOn(chatApi, 'fetchChatStream').mockResolvedValue(createNDJSONResponse(lines));

    const onMessageComplete = vi.fn();
    const { result } = renderHook(() => useChatStream({ onMessageComplete }));

    await act(async () => {
      const p = result.current.sendQuery('Test v2', [], 'session-01');
      vi.advanceTimersByTime(100);
      await p;
    });

    expect(onMessageComplete).toHaveBeenCalledTimes(1);
    const msg: ChatMessage = onMessageComplete.mock.calls[0][0];
    expect(msg.content).toBe('Nội dung v2');
    expect(msg.isStreaming).toBe(false);
  });

  it('14. NDJSON v2: Ngắt luồng giữa chừng (premature EOF không có completed) gọi onError', async () => {
    // Luồng v2 bị đứt đột ngột khi chỉ mới gửi token, không có sự kiện completed
    const lines = [
      JSON.stringify({ type: 'meta', protocol_version: 2, sequence: 1, payload: { sources: [], trace: [] } }),
      JSON.stringify({ type: 'text_delta', protocol_version: 2, sequence: 2, payload: { delta: 'Nội dung dở dang...' } }),
    ];
    vi.spyOn(chatApi, 'fetchChatStream').mockResolvedValue(createNDJSONResponse(lines));
    vi.spyOn(Math, 'random').mockReturnValue(0);

    const onMessageComplete = vi.fn();
    const onError = vi.fn();
    const { result } = renderHook(() => useChatStream({ onMessageComplete, onError }));

    await act(async () => {
      const p = result.current.sendQuery('Test v2 drop', [], 'session-01');
      await vi.advanceTimersByTimeAsync(2_000);
      await p;
    });

    // Không được báo thành công
    expect(onMessageComplete).not.toHaveBeenCalled();
    // Phải báo lỗi stream interrupted
    expect(onError).toHaveBeenCalledTimes(1);
    const err: Error = onError.mock.calls[0][0];
    expect(err.message).toContain('Stream interrupted');
  });

  it('15. NDJSON v2: Nhận artifact_planned lập tức nạp visual metadata dự kiến', async () => {
    const lines = [
      JSON.stringify({ type: 'meta', protocol_version: 2, sequence: 1, payload: { sources: [], trace: [] } }),
      JSON.stringify({
        type: 'artifact_planned',
        protocol_version: 2,
        sequence: 2,
        payload: {
          artifact_id: 'art_123',
          title: 'Biểu đồ Học phí 2026',
          file_type: 'chart',
          chart_type: 'bar',
        },
      }),
      JSON.stringify({ type: 'text_delta', protocol_version: 2, sequence: 3, payload: { delta: 'Xem biểu đồ bên dưới' } }),
      JSON.stringify({ type: 'completed', protocol_version: 2, sequence: 4, payload: {} }),
    ];
    vi.spyOn(chatApi, 'fetchChatStream').mockResolvedValue(createNDJSONResponse(lines));

    const onMessageComplete = vi.fn();
    const { result } = renderHook(() => useChatStream({ onMessageComplete }));

    await act(async () => {
      const p = result.current.sendQuery('Xem học phí', [], 'session-01');
      vi.advanceTimersByTime(100);
      await p;
    });

    expect(onMessageComplete).toHaveBeenCalledTimes(1);
    const msg: ChatMessage = onMessageComplete.mock.calls[0][0];
    expect(msg.visual).not.toBeNull();
    expect(msg.visual?.title).toBe('Biểu đồ Học phí 2026');
  });

  it('16. NDJSON v2 Canonical Event Set: nhận đủ start -> progress -> artifact -> token -> done', async () => {
    const lines = [
      JSON.stringify({
        type: 'start',
        protocol_version: 2,
        sequence: 1,
        payload: { version: '2.0.0' },
      }),
      JSON.stringify({
        type: 'progress',
        protocol_version: 2,
        sequence: 2,
        payload: {
          stage: 'retrieval_complete',
          sources: [{ i: 1, title: 'HUIT Tuyển sinh', url: 'https://ts.huit.edu.vn', score: 0.95, text: 'Thông tin học phí' }],
          trace: [{ step: 1, name: 'NLU', detail: 'Học phí', status: 'success' }],
          cached: false,
        },
      }),
      JSON.stringify({
        type: 'artifact',
        protocol_version: 2,
        sequence: 3,
        payload: {
          artifact_id: 'art_tuition_canon',
          title: 'Bảng học phí HUIT 2026',
          type: 'document',
          preview_url: '/api/artifacts/art_tuition_canon/preview',
        },
      }),
      JSON.stringify({
        type: 'token',
        protocol_version: 2,
        sequence: 4,
        payload: { token: 'Học phí HUIT dao động 30-34 triệu.' },
      }),
      JSON.stringify({
        type: 'done',
        protocol_version: 2,
        sequence: 5,
        payload: { latency_ms: 150.0, cached: false },
      }),
    ];
    vi.spyOn(chatApi, 'fetchChatStream').mockResolvedValue(createNDJSONResponse(lines));

    const onMessageComplete = vi.fn();
    const { result } = renderHook(() => useChatStream({ onMessageComplete }));

    await act(async () => {
      const p = result.current.sendQuery('Hỏi học phí canonical', [], 'session-01');
      vi.advanceTimersByTime(100);
      await p;
    });

    expect(onMessageComplete).toHaveBeenCalledTimes(1);
    const msg: ChatMessage = onMessageComplete.mock.calls[0][0];
    expect(msg.content).toBe('Học phí HUIT dao động 30-34 triệu.');
    expect(msg.sources).toHaveLength(1);
    expect(msg.sources[0].title).toBe('HUIT Tuyển sinh');
    expect(msg.artifact).toBeDefined();
    expect(msg.artifact?.artifact_id).toBe('art_tuition_canon');
    expect(msg.isStreaming).toBe(false);
  });
});
