import { JobStatusResponse, ArtifactSummary } from '../../../shared/types/common.types';
import { apiClient } from '../../../shared/api/httpClient';
import {
  parseArtifactManifest,
  parseArtifactSummary,
  assertArtifactExportRequest,
  assertArtifactUpscaleRequest,
  parseJobStatusResponse,
  parseJobAcceptedResponse,
} from '../../../shared/contracts';

export const API_BASE = '';

/**
 * Lấy URL preview SVG cho artifact.
 */
export function getArtifactPreviewUrl(artifactId: string): string {
  return `${API_BASE}/api/artifacts/${encodeURIComponent(artifactId)}/preview`;
}

/**
 * Lấy URL thumbnail nhẹ (~256px) nếu có hoặc fallback về preview.
 */
export function getArtifactThumbnailUrl(artifactId: string): string {
  return `${API_BASE}/api/artifacts/${encodeURIComponent(artifactId)}/preview`;
}

/**
 * Lấy tóm tắt manifest của một artifact.
 */
export async function fetchArtifactSummary(artifactId: string): Promise<ArtifactSummary> {
  const res = await apiClient(`${API_BASE}/api/artifacts/${encodeURIComponent(artifactId)}/manifest`, {
    headers: { 'Accept': 'application/json' },
  });

  if (!res.ok) {
    throw new Error(`HTTP ${res.status}: Không thể tải thông tin artifact`);
  }

  const rawManifest = await res.json();
  const manifest = parseArtifactManifest(rawManifest);
  const summary: ArtifactSummary = {
    artifact_id: manifest.artifact_id || artifactId,
    type: manifest.type,
    title: manifest.title,
    preview_url: manifest.preview?.url || getArtifactPreviewUrl(artifactId),
    manifest_url: `/api/artifacts/${encodeURIComponent(artifactId)}/manifest`,
    available_formats: manifest.export_options || ['xlsx', 'docx', 'pdf', 'png', 'svg'],
    status: manifest.render?.status || 'ready',
    owner_id: manifest.owner_id,
  };
  return parseArtifactSummary(summary);
}

/**
 * Tải file export theo định dạng yêu cầu.
 * Sử dụng Blob nhị phân và tự động kích hoạt tải về trên trình duyệt,
 * hoặc nhận Signed URL và mở an toàn.
 */
/**
 * Yêu cầu xuất file qua Durable Background Queue.
 * POST /api/artifacts/{id}/export trả về HTTP 202 cùng job_id.
 */
export async function requestArtifactExport(
  artifactId: string,
  format: string
): Promise<{ success: boolean; job_id: string; status: string; check_status_url?: string }> {
  const cleanFmt = format.toLowerCase().replace('.', '');
  if (['mp3', 'mp4', 'audio', 'video'].includes(cleanFmt)) {
    throw new Error('Định dạng âm thanh/video chưa được hệ thống hỗ trợ.');
  }

  assertArtifactExportRequest({ format: cleanFmt as 'xlsx' | 'docx' | 'pdf' | 'png' | 'svg' | 'webp' });

  const endpoint = `${API_BASE}/api/artifacts/${encodeURIComponent(artifactId)}/export?format=${cleanFmt}`;
  const res = await apiClient(endpoint, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'Accept': 'application/json',
    },
    body: JSON.stringify({ format: cleanFmt }),
  });

  if (!res.ok) {
    const errText = await res.text().catch(() => '');
    throw new Error(`HTTP ${res.status}: ${errText || 'Không thể bắt đầu xuất tài liệu'}`);
  }

  const data = await res.json();
  const accepted = parseJobAcceptedResponse(data);

  return {
    success: true,
    job_id: accepted.job_id,
    status: accepted.status,
    check_status_url: accepted.check_status_url,
  };
}

/**
 * Kích hoạt tải file từ URL (Signed Download URL hoặc Blob).
 */
export function triggerFileDownload(url: string, filename?: string): void {
  if (!url || typeof document === 'undefined') return;
  const link = document.createElement('a');
  link.href = url;
  if (filename) {
    link.download = filename;
  }
  link.rel = 'noopener noreferrer';
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
}

/**
 * Yêu cầu xuất file qua Durable Background Queue hoặc tải file đã có.
 * Không coi job_id là URL.
 */
export async function downloadArtifactExport(
  artifactId: string,
  format: string,
  filename?: string
): Promise<{ success: boolean; url?: string; job_id?: string; blob?: Blob }> {
  const cleanFmt = format.toLowerCase().replace('.', '');
  if (['mp3', 'mp4', 'audio', 'video'].includes(cleanFmt)) {
    throw new Error('Định dạng âm thanh/video chưa được hệ thống hỗ trợ.');
  }

  assertArtifactExportRequest({ format: cleanFmt as 'xlsx' | 'docx' | 'pdf' | 'png' | 'svg' | 'webp' });

  const endpoint = `${API_BASE}/api/artifacts/${encodeURIComponent(artifactId)}/export?format=${cleanFmt}`;
  const res = await apiClient(endpoint, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'Accept': 'application/json',
    },
    body: JSON.stringify({ format: cleanFmt }),
  });

  if (!res.ok) {
    const errText = await res.text().catch(() => '');
    throw new Error(`HTTP ${res.status}: ${errText || 'Không thể xuất tài liệu'}`);
  }

  const contentType = res.headers.get('Content-Type') || '';

  if (contentType.includes('application/json')) {
    const data = await res.json();
    const accepted = parseJobAcceptedResponse(data);
    return { success: true, job_id: accepted.job_id };
  }

  const blob = await res.blob();
  const blobUrl = URL.createObjectURL(blob);
  triggerFileDownload(blobUrl, filename || `${artifactId}.${cleanFmt}`);

  setTimeout(() => {
    URL.revokeObjectURL(blobUrl);
  }, 10000);

  return { success: true, url: blobUrl, blob };
}

/**
 * Yêu cầu upscale ảnh/đồ họa 2x/4x qua Durable Queue.
 * POST /api/artifacts/{id}/upscale trả về HTTP 202 cùng job_id.
 * Tuyệt đối KHÔNG coi job_id là URL.
 */
export async function requestArtifactUpscale(
  artifactId: string,
  scale: number
): Promise<{ success: boolean; job_id?: string; url?: string }> {
  assertArtifactUpscaleRequest({ scale });
  const res = await apiClient(`${API_BASE}/api/artifacts/${encodeURIComponent(artifactId)}/upscale`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'Accept': 'application/json',
    },
    body: JSON.stringify({ scale }),
  });

  if (!res.ok) {
    const err = await res.text().catch(() => '');
    throw new Error(`HTTP ${res.status}: ${err || 'Không thể bắt đầu phóng to ảnh'}`);
  }

  const data = await res.json();
  const accepted = parseJobAcceptedResponse(data);
  return {
    success: true,
    job_id: accepted.job_id,
  };
}

/**
 * Thăm dò (Poll) trạng thái tác vụ nền.
 */
export async function fetchJobStatus(jobId: string): Promise<JobStatusResponse> {
  const res = await apiClient(`${API_BASE}/api/jobs/${encodeURIComponent(jobId)}`, {
    headers: { 'Accept': 'application/json' },
  });

  if (!res.ok) {
    throw new Error(`HTTP ${res.status}: Không thể kiểm tra trạng thái tác vụ`);
  }

  const rawData = await res.json();
  return parseJobStatusResponse(rawData);
}

/**
 * Hủy tác vụ nền.
 */
export async function cancelJob(jobId: string): Promise<boolean> {
  try {
    const res = await apiClient(`${API_BASE}/api/jobs/${encodeURIComponent(jobId)}/cancel`, {
      method: 'POST',
    });
    return res.ok;
  } catch {
    return false;
  }
}
