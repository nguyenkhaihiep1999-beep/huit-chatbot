import { AppError } from '../types/common.types';

/**
 * Ánh xạ lỗi tập trung theo HTTP status và error_code của hệ thống.
 * Tuyệt đối không hiển thị raw backend exception hay API secrets.
 */
export function mapApiError(error: unknown, defaultMessage = 'Hệ thống tư vấn đang bận hoặc gặp sự cố kết nối. Bạn vui lòng thử lại sau giây lát nhé!'): AppError {
  if (!error) {
    return {
      code: 'UNKNOWN_ERROR',
      message: defaultMessage,
      canRetry: true,
    };
  }

  // Nếu là chuỗi thông báo
  const errorMsg = error instanceof Error ? error.message : typeof error === 'string' ? error : '';

  // Kiểm tra mã trạng thái HTTP nếu có trong message "HTTP 429: ..."
  const httpStatusMatch = errorMsg.match(/HTTP\s+(\d{3})/i);
  const status = httpStatusMatch ? parseInt(httpStatusMatch[1], 10) : undefined;

  // Xử lý theo HTTP Status
  if (status === 401) {
    return {
      code: 'AUTH_SESSION_EXPIRED',
      status: 401,
      message: 'Phiên làm việc của bạn đã hết hạn. Vui lòng làm mới để tiếp tục trò chuyện.',
      canRetry: true,
    };
  }

  if (status === 403) {
    return {
      code: 'PERMISSION_DENIED',
      status: 403,
      message: 'Bạn không có quyền truy cập tài nguyên hoặc tài liệu riêng tư này.',
      canRetry: false,
    };
  }

  if (status === 404) {
    return {
      code: 'NOT_FOUND',
      status: 404,
      message: 'Tài liệu, hình ảnh hoặc công việc yêu cầu không tồn tại trên hệ thống.',
      canRetry: false,
    };
  }

  if (status === 409) {
    return {
      code: 'RESOURCE_CONFLICT',
      status: 409,
      message: 'Tài nguyên đang được xử lý hoặc có xung đột tiến trình. Bạn vui lòng đợi giây lát.',
      canRetry: true,
    };
  }

  if (status === 422) {
    return {
      code: 'INVALID_REQUEST',
      status: 422,
      message: 'Yêu cầu không hợp lệ hoặc dữ liệu đầu vào chưa đúng quy định.',
      canRetry: false,
    };
  }

  if (status === 429) {
    // Trích xuất Retry-After nếu có
    const retryMatch = errorMsg.match(/(\d+)\s*(?:s|giây|seconds)/i);
    const retrySeconds = retryMatch ? parseInt(retryMatch[1], 10) : 60;
    return {
      code: 'RATE_LIMIT_EXCEEDED',
      status: 429,
      retryAfterSeconds: retrySeconds,
      message: `Bạn đang gửi yêu cầu quá nhanh. Vui lòng đợi ${retrySeconds} giây trước khi thử lại nhé!`,
      canRetry: true,
    };
  }

  if (status && status >= 500) {
    return {
      code: 'SERVER_ERROR',
      status,
      message: 'Máy chủ tư vấn HUIT đang bảo trì hoặc quá tải tạm thời. Vui lòng thử lại sau ít phút.',
      canRetry: true,
    };
  }

  // Xử lý các mã lỗi cụ thể qua từ khóa (Error Code Mapping)
  const lower = errorMsg.toLowerCase();

  if (lower.includes('stream interrupted') || lower.includes('premature eof') || lower.includes('mất kết nối') || lower.includes('failed to fetch') || lower.includes('network error')) {
    return {
      code: 'STREAM_INTERRUPTED',
      message: 'Hệ thống tư vấn đang bận hoặc gặp sự cố kết nối. Bạn vui lòng thử lại sau giây lát nhé!',
      canRetry: true,
    };
  }

  if (lower.includes('expired') || lower.includes('signature expired') || lower.includes('url expired')) {
    return {
      code: 'SIGNED_URL_EXPIRED',
      message: 'Liên kết tải xuống đã hết hạn bảo mật. Vui lòng nhấn tải lại để nhận liên kết mới.',
      canRetry: true,
    };
  }

  if (lower.includes('unsupported') || lower.includes('unsupported_file_type')) {
    return {
      code: 'UNSUPPORTED_FORMAT',
      message: 'Định dạng tệp yêu cầu chưa được hỗ trợ bởi hệ thống.',
      canRetry: false,
    };
  }

  if (lower.includes('storage') && (lower.includes('unavailable') || lower.includes('error'))) {
    return {
      code: 'STORAGE_UNAVAILABLE',
      message: 'Kho lưu trữ tài liệu tạm thời không phản hồi. Vui lòng thử lại sau.',
      canRetry: true,
    };
  }

  if (lower.includes('queue') && (lower.includes('unavailable') || lower.includes('error'))) {
    return {
      code: 'QUEUE_UNAVAILABLE',
      message: 'Hàng đợi xử lý tác vụ đang bận. Vui lòng thử lại sau ít phút.',
      canRetry: true,
    };
  }

  if (lower.includes('upscale') && (lower.includes('fail') || lower.includes('error'))) {
    return {
      code: 'UPSCALE_FAILED',
      message: 'Không thể phóng to ảnh chất lượng cao. Bạn có thể tải ảnh kích thước tiêu chuẩn.',
      canRetry: true,
    };
  }

  return {
    code: 'GENERAL_ERROR',
    message: errorMsg && errorMsg.length < 150 ? errorMsg : defaultMessage,
    canRetry: true,
  };
}
