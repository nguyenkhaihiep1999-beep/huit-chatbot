import { describe, expect, it, vi } from 'vitest';
import * as httpClient from '../src/shared/api/httpClient';
import {
  downloadArtifactExport,
  requestArtifactExport,
} from '../src/features/artifacts/api/artifactApi';
import {
  assertAdminLoginRequest,
  assertArtifactExportRequest,
  assertArtifactPlanRequest,
  assertArtifactRenderRequest,
  assertArtifactUpscaleRequest,
  assertChatRequest,
  assertImageCreateRequest,
  parseAdminLoginResponse,
  parseAdminSessionResponse,
  parseApiErrorResponse,
  parseArtifactManifest,
  parseArtifactSummary,
  parseChatStreamEvent,
  parseImageResult,
  parseJobStatusResponse,
  parseJobAcceptedResponse,
  parseSessionBootstrapResponse,
} from '../src/shared/contracts';

function event(type: string, payload: Record<string, unknown>): Record<string, unknown> {
  return {
    protocol_version: 2,
    stream_id: 'stream_123',
    request_id: 'request_123',
    sequence: 1,
    type,
    timestamp: '2026-09-18T00:00:00Z',
    payload,
  };
}

describe('canonical JSON Schema runtime contracts', () => {
  it('accepts a valid session response and rejects drift', () => {
    const valid = {
      success: true,
      session_id: 'sess_12345678',
      csrf_token: 'csrf_token_1234567890',
      issued_at: 1,
      expires_at: 301,
      ttl_seconds: 300,
    };
    expect(parseSessionBootstrapResponse(valid).session_id).toBe('sess_12345678');
    expect(() => parseSessionBootstrapResponse({ ...valid, unknown: true })).toThrow('CONTRACT_VIOLATION');
    expect(() => parseSessionBootstrapResponse({ ...valid, csrf_token: '' })).toThrow('CONTRACT_VIOLATION');
  });

  it('validates chat requests before the transport sends them', () => {
    const valid: unknown = {
      question: 'Học phí HUIT năm nay?',
      history: [{ role: 'user', content: 'Xin chào' }],
      enable_cache: true,
    };
    expect(() => assertChatRequest(valid)).not.toThrow();
    expect(() => assertChatRequest({ question: '', history: [] })).toThrow('CONTRACT_VIOLATION');
    expect(() => assertChatRequest({ question: 'x', history: [{ role: 'system', content: 'x' }] })).toThrow('CONTRACT_VIOLATION');
  });

  it('accepts every canonical v2 event and rejects malformed envelopes', () => {
    const cases = [
      event('start', { version: '2.0.0' }),
      event('token', { token: 'HUIT', delta: 'HUIT' }),
      event('progress', { sources: [], trace: [], cached: false }),
      event('artifact', { artifact_id: 'art_1', title: 'Học phí', available_formats: ['xlsx'] }),
      event('error', { error_code: 'TEST', message: 'Test', retryable: false }),
      event('done', { latency_ms: 10, cached: false }),
      event('cancelled', { detail: 'Stopped' }),
      event('heartbeat', { status: 'alive' }),
    ];
    for (const value of cases) expect(parseChatStreamEvent(value).type).toBe(value.type);
    expect(() => parseChatStreamEvent({ ...event('token', {}), extra: true })).toThrow('CONTRACT_VIOLATION');
    expect(() => parseChatStreamEvent(event('unknown', {}))).toThrow('CONTRACT_VIOLATION');
  });

  it('keeps legacy events only at the declared compatibility boundary', () => {
    const legacy = { type: 'text_delta', protocol_version: 2, sequence: 1, payload: { delta: 'HUIT' } };
    expect(parseChatStreamEvent(legacy).type).toBe('text_delta');
  });

  it('validates admin login request and responses', () => {
    expect(() => assertAdminLoginRequest({ username: 'admin_user', password: 'secure_password' })).not.toThrow();
    expect(() => assertAdminLoginRequest({ username: 'admin_user' })).toThrow('CONTRACT_VIOLATION');

    const validLoginResp = {
      success: true,
      csrf_token: 'csrf_admin_token_123456',
      message: 'Đăng nhập thành công',
    };
    expect(parseAdminLoginResponse(validLoginResp).csrf_token).toBe('csrf_admin_token_123456');
    expect(() => parseAdminLoginResponse({ ...validLoginResp, success: false })).toThrow('CONTRACT_VIOLATION');

    const validSessionResp = { valid: true, role: 'admin' };
    expect(parseAdminSessionResponse(validSessionResp).role).toBe('admin');
    expect(() => parseAdminSessionResponse({ valid: true, role: 'editor' })).toThrow('CONTRACT_VIOLATION');
  });

  it('validates API error responses with both domain code and FastAPI detail envelopes', () => {
    // Trường hợp đạt
    expect(parseApiErrorResponse({ detail: 'Unauthorized' }).detail).toBe('Unauthorized');
    expect(parseApiErrorResponse({
      detail: {
        error_code: 'UNAUTHORIZED',
        message: 'Phiên không hợp lệ',
      },
    }).detail).toEqual({
      error_code: 'UNAUTHORIZED',
      message: 'Phiên không hợp lệ',
    });
    expect(parseApiErrorResponse({
      error_code: 'NOT_FOUND',
      message: 'Không tìm thấy',
    }).error_code).toBe('NOT_FOUND');

    // Các trường hợp bị từ chối
    expect(() => parseApiErrorResponse({ detail: 123 })).toThrow('CONTRACT_VIOLATION');
    expect(() => parseApiErrorResponse({ detail: null })).toThrow('CONTRACT_VIOLATION');
    expect(() => parseApiErrorResponse({ error_code: 'ERROR' })).toThrow('CONTRACT_VIOLATION');
    expect(() => parseApiErrorResponse({ message: 'Thiếu error_code' })).toThrow('CONTRACT_VIOLATION');
    expect(() => parseApiErrorResponse({ unexpected: true })).toThrow('CONTRACT_VIOLATION');
  });

  it('validates artifact manifest and summary contracts', () => {
    const validManifest = {
      artifact_id: 'art-001',
      type: 'spreadsheet',
      template_id: 'tpl_chart',
      title: 'Biểu đồ Tuyển sinh',
      preview: { url: 'https://cdn.huit.edu.vn/preview.svg' },
      render: { status: 'ready', quality: 'standard' },
    };
    expect(parseArtifactManifest(validManifest).artifact_id).toBe('art-001');
    expect(() => parseArtifactManifest({ ...validManifest, preview: {} })).toThrow('CONTRACT_VIOLATION');

    const validSummary = {
      artifact_id: 'art-001',
      type: 'spreadsheet',
      title: 'Biểu đồ Tuyển sinh',
      preview_url: 'https://cdn.huit.edu.vn/preview.svg',
      manifest_url: '/api/artifacts/art-001/manifest',
      available_formats: ['xlsx', 'docx', 'pdf', 'png', 'svg'],
      status: 'ready',
    };
    expect(parseArtifactSummary(validSummary).title).toBe('Biểu đồ Tuyển sinh');
    expect(() => parseArtifactSummary({ ...validSummary, type: 'video' })).toThrow('CONTRACT_VIOLATION');
    expect(() => parseArtifactSummary({ ...validSummary, preview_url: undefined })).toThrow('CONTRACT_VIOLATION');
  });

  it('validates artifact plan, render, upscale, and export requests', () => {
    expect(() => assertArtifactPlanRequest({ prompt: 'Tạo tài liệu học phí' })).not.toThrow();
    expect(() => assertArtifactPlanRequest({})).toThrow('CONTRACT_VIOLATION');

    expect(() => assertArtifactRenderRequest({ artifact_id: 'art-001', format: 'pdf', scale: 2 })).not.toThrow();
    expect(() => assertArtifactRenderRequest({ format: 'pdf' })).toThrow('CONTRACT_VIOLATION');

    expect(() => assertArtifactUpscaleRequest({ scale: 2 })).not.toThrow();
    expect(() => assertArtifactUpscaleRequest({})).not.toThrow(); // scale is optional with default
    expect(() => assertArtifactUpscaleRequest({ scale: 8 })).toThrow('CONTRACT_VIOLATION');

    expect(() => assertArtifactExportRequest({ format: 'xlsx' })).not.toThrow();
    expect(() => assertArtifactExportRequest({ format: 'mp4' })).toThrow('CONTRACT_VIOLATION');
  });

  it('validates background job status response with action, pending, and errors', () => {
    const validJob = {
      job_id: 'job_abcdef12345678',
      action: 'render',
      status: 'pending',
      progress: 40,
    };
    expect(parseJobStatusResponse(validJob).status).toBe('pending');

    const completedJob = {
      job_id: 'job_abcdef12345678',
      status: 'completed',
      result_url: 'https://cdn.huit.edu.vn/result.xlsx',
      download_url: 'https://cdn.huit.edu.vn/download.xlsx',
    };
    expect(parseJobStatusResponse(completedJob).status).toBe('completed');

    const failedJob = {
      job_id: 'job_abcdef12345678',
      status: 'failed',
      error: { error_code: 'RENDER_FAILED', message: 'Lỗi bộ nhớ' },
    };
    expect(parseJobStatusResponse(failedJob).status).toBe('failed');

    expect(() => parseJobStatusResponse({ status: 'queued' })).toThrow('CONTRACT_VIOLATION');
  });

  it('validates image generation request and result contracts', () => {
    expect(() => assertImageCreateRequest({ prompt: 'Ảnh cổng trường HUIT', backend: 'flux' })).not.toThrow();
    expect(() => assertImageCreateRequest({ prompt: '' })).toThrow('CONTRACT_VIOLATION');

    const validResult = {
      image_id: 'img_12345',
      image_url: 'https://cdn.huit.edu.vn/images/img_12345.png',
      width: 512,
      height: 512,
      model: 'flux-schnell',
      style: 'photorealistic',
      billing: 'included',
      cached: false,
    };
    expect(parseImageResult(validResult).image_id).toBe('img_12345');
    expect(() => parseImageResult({ image_id: 'img_12345' })).toThrow('CONTRACT_VIOLATION');
  });

  it('validates HTTP 202 Job Accepted response contract and negative paths', () => {
    const validAccepted = {
      job_id: 'job_12345678',
      status: 'queued',
      artifact_id: 'art-001',
      action: 'export',
      format: 'xlsx',
      scale: null,
      check_status_url: '/api/jobs/job_12345678',
    };
    expect(parseJobAcceptedResponse(validAccepted).job_id).toBe('job_12345678');

    // 1. Thiếu job_id
    expect(() => parseJobAcceptedResponse({
      status: 'queued',
      check_status_url: '/api/jobs/1',
    })).toThrow('CONTRACT_VIOLATION');

    // 2. Status khác queued
    expect(() => parseJobAcceptedResponse({
      ...validAccepted,
      status: 'completed',
    })).toThrow('CONTRACT_VIOLATION');

    // 3. Format không hỗ trợ
    expect(() => parseJobAcceptedResponse({
      ...validAccepted,
      format: 'unsupported_format',
    })).toThrow('CONTRACT_VIOLATION');

    // 4. Scale ngoài giới hạn (> 4)
    expect(() => parseJobAcceptedResponse({
      ...validAccepted,
      scale: 10,
    })).toThrow('CONTRACT_VIOLATION');

    // 5. Field thừa (additionalProperties: false)
    expect(() => parseJobAcceptedResponse({
      ...validAccepted,
      extra_unexpected_field: true,
    })).toThrow('CONTRACT_VIOLATION');
  });

  it('validates that download/export API routes pass JSON responses through parseJobAcceptedResponse', async () => {
    // 1. requestArtifactExport fails if server returns malformed JSON
    vi.spyOn(httpClient, 'apiClient').mockResolvedValueOnce({
      ok: true,
      headers: new Headers({ 'Content-Type': 'application/json' }),
      json: async () => ({ invalid_field: true, status: 'queued' }),
    } as unknown as Response);

    await expect(requestArtifactExport('art-001', 'xlsx')).rejects.toThrow('CONTRACT_VIOLATION');

    // 2. downloadArtifactExport fails if server returns malformed JSON
    vi.spyOn(httpClient, 'apiClient').mockResolvedValueOnce({
      ok: true,
      headers: new Headers({ 'Content-Type': 'application/json' }),
      json: async () => ({ job_id: 12345, status: 'not_queued' }),
    } as unknown as Response);

    await expect(downloadArtifactExport('art-001', 'xlsx')).rejects.toThrow('CONTRACT_VIOLATION');

    // 3. downloadArtifactExport succeeds when server returns canonical JobAcceptedResponse
    vi.spyOn(httpClient, 'apiClient').mockResolvedValueOnce({
      ok: true,
      headers: new Headers({ 'Content-Type': 'application/json' }),
      json: async () => ({
        job_id: 'job_export_999',
        status: 'queued',
        artifact_id: 'art-001',
        action: 'export',
        format: 'xlsx',
        scale: null,
        check_status_url: '/api/jobs/job_export_999',
      }),
    } as unknown as Response);

    const res = await downloadArtifactExport('art-001', 'xlsx');
    expect(res.success).toBe(true);
    expect(res.job_id).toBe('job_export_999');

    // 4. Blob response is NOT passed through JSON validator
    vi.spyOn(httpClient, 'apiClient').mockResolvedValueOnce({
      ok: true,
      headers: new Headers({ 'Content-Type': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' }),
      blob: async () => new Blob(['dummy content'], { type: 'application/vnd.openxmlformats' }),
    } as unknown as Response);

    // Mock URL.createObjectURL and revokeObjectURL
    const origCreateObjectURL = globalThis.URL.createObjectURL;
    const origRevokeObjectURL = globalThis.URL.revokeObjectURL;
    globalThis.URL.createObjectURL = vi.fn().mockReturnValue('blob:http://localhost/dummy');
    globalThis.URL.revokeObjectURL = vi.fn();

    try {
      const blobRes = await downloadArtifactExport('art-001', 'xlsx');
      expect(blobRes.success).toBe(true);
      expect(blobRes.url).toBe('blob:http://localhost/dummy');
      expect(blobRes.blob).toBeDefined();
    } finally {
      globalThis.URL.createObjectURL = origCreateObjectURL;
      globalThis.URL.revokeObjectURL = origRevokeObjectURL;
    }
  });
});
