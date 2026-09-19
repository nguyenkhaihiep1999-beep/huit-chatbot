/**
 * jobStorage.ts
 * Tiện ích quản lý lưu trữ trạng thái các tác vụ nền đang chạy (Active Jobs) trong localStorage.
 * Cho phép các React Hooks (export, upscale) tự động reattach tiến trình sau khi người dùng reload trang.
 */

import { getSessionScope } from '../../../shared/auth/csrfStore';

const STORAGE_KEY = 'huit_active_jobs';

export interface StoredActiveJob {
  jobId: string;
  type: 'export' | 'upscale';
  artifactId: string;
  sessionScope: string;
  meta?: Record<string, any>;
  timestamp: number;
}

function getStoredMap(): Record<string, StoredActiveJob> {
  try {
    if (typeof window === 'undefined' || !window.localStorage) {
      return {};
    }
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return {};
    return JSON.parse(raw);
  } catch {
    return {};
  }
}

function setStoredMap(map: Record<string, StoredActiveJob>): void {
  try {
    if (typeof window !== 'undefined' && window.localStorage) {
      window.localStorage.setItem(STORAGE_KEY, JSON.stringify(map));
    }
  } catch {
    // Bỏ qua lỗi hạn ngạch lưu trữ
  }
}

function makeKey(type: 'export' | 'upscale', artifactId: string, sessionScope: string): string {
  return `${sessionScope}:${type}:${artifactId}`;
}

/**
 * Lưu lại thông tin tác vụ nền đang chạy để reattach sau reload.
 */
export function saveActiveJob(
  type: 'export' | 'upscale',
  artifactId: string,
  jobId: string,
  meta?: Record<string, any>
): void {
  if (!artifactId || !jobId) return;
  const sessionScope = getSessionScope();
  if (!sessionScope) return;
  const map = getStoredMap();
  const key = makeKey(type, artifactId, sessionScope);
  map[key] = {
    jobId,
    type,
    artifactId,
    sessionScope,
    meta,
    timestamp: Date.now(),
  };
  setStoredMap(map);
}

/**
 * Lấy thông tin tác vụ nền đang chạy nếu có (bỏ qua nếu đã quá 24h).
 */
export function getActiveJob(
  type: 'export' | 'upscale',
  artifactId: string
): StoredActiveJob | null {
  if (!artifactId) return null;
  const sessionScope = getSessionScope();
  if (!sessionScope) return null;
  const map = getStoredMap();
  const key = makeKey(type, artifactId, sessionScope);
  const item = map[key];
  if (!item || item.sessionScope !== sessionScope) return null;

  // Bỏ qua tác vụ đã lưu quá 24 giờ
  if (Date.now() - item.timestamp > 24 * 60 * 60 * 1000) {
    clearActiveJob(type, artifactId);
    return null;
  }
  return item;
}

/**
 * Xóa thông tin tác vụ khi đã hoàn thành, bị hủy hoặc thất bại.
 */
export function clearActiveJob(type: 'export' | 'upscale', artifactId: string): void {
  if (!artifactId) return;
  const sessionScope = getSessionScope();
  if (!sessionScope) return;
  const map = getStoredMap();
  const key = makeKey(type, artifactId, sessionScope);
  const legacyKey = `${type}:${artifactId}`;
  if (key in map || legacyKey in map) {
    delete map[key];
    delete map[legacyKey];
    setStoredMap(map);
  }
}
