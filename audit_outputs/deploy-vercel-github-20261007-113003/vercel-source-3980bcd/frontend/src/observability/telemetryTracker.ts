import type { StreamPerformanceMetric, ActiveTrace } from './observability.types.ts';

class TelemetryTracker {
  private activeTraces: Map<string, ActiveTrace> = new Map();
  private completedMetrics: StreamPerformanceMetric[] = [];
  private readonly maxStoredMetrics = 50;
  private currentActiveRequestId: string | null = null;

  /**
   * Bắt đầu theo dõi một chu trình streaming request.
   * Sử dụng requestId chung giữa Frontend và Backend.
   */
  startTrace(requestId: string): ActiveTrace {
    this.currentActiveRequestId = requestId;
    const trace: ActiveTrace = {
      requestId,
      startTime: performance.now(),
      contentTtft: null,
      flushCount: 0,
      renderCount: 0,
      totalRenderTimeMs: 0,
      tokenCount: 0,
      cached: false,
      finished: false,
      status: 'completed',
    };
    this.activeTraces.set(requestId, trace);
    return trace;
  }

  /**
   * Ghi nhận thời điểm nhận token nội dung đầu tiên (Content TTFT).
   * LƯU Ý QUAN TRỌNG: Gói tin 'meta' (sources/trace/visual) KHÔNG được tính là Content TTFT!
   */
  recordContentToken(requestId: string, token: string): void {
    const trace = this.activeTraces.get(requestId);
    if (!trace || trace.finished) return;

    trace.tokenCount += 1;
    // Chỉ tính Content TTFT khi nhận token thực sự có nội dung văn bản
    if (trace.contentTtft === null && token.trim().length > 0) {
      trace.contentTtft = Math.round((performance.now() - trace.startTime) * 100) / 100;
    }
  }

  /**
   * Ghi nhận một lần xả buffer token ra giao diện.
   */
  recordFlush(requestId: string): void {
    const trace = this.activeTraces.get(requestId);
    if (!trace || trace.finished) return;
    trace.flushCount += 1;
  }

  /**
   * Đo lường thời gian thực thi render trên giao diện client.
   */
  recordRender(requestId: string, renderDurationMs: number): void {
    const trace = this.activeTraces.get(requestId);
    if (!trace || trace.finished) return;
    trace.renderCount += 1;
    trace.totalRenderTimeMs = Math.round((trace.totalRenderTimeMs + renderDurationMs) * 100) / 100;
  }

  /**
   * Đo lường thời gian commit/render DOM thực tế từ React Profiler.
   * Gắn chính xác cho request đang active, không cộng dồn sai vào nhiều trace.
   * Không coi thời gian gọi setState callback là thời gian render DOM.
   */
  recordCommitDuration(durationMs: number, targetRequestId?: string): void {
    const reqId = targetRequestId || this.currentActiveRequestId;
    if (reqId) {
      const trace = this.activeTraces.get(reqId);
      if (trace && !trace.finished) {
        trace.renderCount += 1;
        trace.totalRenderTimeMs = Math.round((trace.totalRenderTimeMs + durationMs) * 100) / 100;
        return;
      }
    }
  }

  /**
   * Đánh dấu request được phục vụ từ cache.
   */
  setCached(requestId: string, cached: boolean): void {
    const trace = this.activeTraces.get(requestId);
    if (trace) {
      trace.cached = cached;
    }
  }

  /**
   * Hoàn thành theo dõi và lưu trữ số đo ẩn danh (không chứa question hay PII).
   * Phân biệt rõ ràng giữa hoàn thành bình thường ('completed') và bị dừng/hủy ('aborted').
   */
  finishTrace(
    requestId: string,
    cachedOverride?: boolean,
    status: 'completed' | 'aborted' = 'completed'
  ): StreamPerformanceMetric | null {
    const trace = this.activeTraces.get(requestId);
    if (!trace || trace.finished) return null;

    trace.finished = true;
    trace.status = status;
    const now = performance.now();
    const totalDurationMs = Math.round((now - trace.startTime) * 100) / 100;
    const isCached = cachedOverride !== undefined ? cachedOverride : trace.cached;

    const metric: StreamPerformanceMetric = {
      requestId,
      requestStartTime: trace.startTime,
      contentTtftMs: trace.contentTtft,
      totalDurationMs,
      flushCount: trace.flushCount,
      renderCount: trace.renderCount,
      totalRenderTimeMs: trace.totalRenderTimeMs,
      cached: isCached,
      tokenCount: trace.tokenCount,
      status,
    };

    this.completedMetrics.push(metric);
    if (this.completedMetrics.length > this.maxStoredMetrics) {
      this.completedMetrics.shift();
    }

    this.activeTraces.delete(requestId);
    if (this.currentActiveRequestId === requestId) {
      this.currentActiveRequestId = null;
    }

    // Gắn vào window.__HUIT_METRICS__ an toàn để dev/qa kiểm tra mà không lộ câu hỏi
    if (typeof window !== 'undefined') {
      const w = window as unknown as { __HUIT_METRICS__?: StreamPerformanceMetric[] };
      w.__HUIT_METRICS__ = [...this.completedMetrics];
    }

    return metric;
  }

  /**
   * Hủy theo dõi khi request bị abort hoặc unmount, ghi nhận rõ status='aborted'.
   */
  abortTrace(requestId: string): void {
    this.finishTrace(requestId, undefined, 'aborted');
  }

  getMetrics(): StreamPerformanceMetric[] {
    return [...this.completedMetrics];
  }

  clearMetrics(): void {
    this.completedMetrics = [];
    this.activeTraces.clear();
    if (typeof window !== 'undefined') {
      const w = window as unknown as { __HUIT_METRICS__?: StreamPerformanceMetric[] };
      delete w.__HUIT_METRICS__;
    }
  }
}

export const telemetryTracker = new TelemetryTracker();
