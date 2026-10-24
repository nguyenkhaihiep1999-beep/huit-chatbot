/**
 * Frontend Observability & Streaming Metrics Types
 * Ghi chú bảo mật: Tuyệt đối không lưu trữ nội dung câu hỏi, lịch sử hội thoại,
 * hay thông tin định danh cá nhân (PII).
 */

export interface StreamPerformanceMetric {
  requestId: string;
  requestStartTime: number; // DOMHighResTimeStamp
  contentTtftMs: number | null; // Content TTFT (loại trừ gói tin metadata)
  totalDurationMs: number; // Tổng thời gian từ lúc gửi request đến khi kết thúc stream
  flushCount: number; // Số lần xả bộ đệm buffer
  renderCount: number; // Số lần kích hoạt render UI
  totalRenderTimeMs: number; // Tổng thời gian CPU tiêu tốn cho các lần render
  cached: boolean;
  tokenCount: number;
  status: 'completed' | 'aborted';
}

export interface ActiveTrace {
  requestId: string;
  startTime: number;
  contentTtft: number | null;
  flushCount: number;
  renderCount: number;
  totalRenderTimeMs: number;
  tokenCount: number;
  cached: boolean;
  finished: boolean;
  status?: 'completed' | 'aborted';
}
