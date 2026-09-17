/**
 * Sinh ID duy nhất an toàn với ưu tiên crypto.randomUUID() và fallback tương thích cao.
 */
export function generateUniqueId(prefix: string = 'id'): string {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    try {
      return `${prefix}-${crypto.randomUUID()}`;
    } catch {
      // fallback dự phòng khi môi trường không cấp quyền crypto
    }
  }
  const timestamp = Date.now();
  const randomPart = Math.random().toString(36).substring(2, 11);
  return `${prefix}-${timestamp}-${randomPart}`;
}
