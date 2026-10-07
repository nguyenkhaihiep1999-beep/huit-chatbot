import { describe, expect, it } from 'vitest';
import type {
  ArtifactSummary,
  JobStatusResponse,
  ImageResult,
  AdminLoginRequest,
  AdminLoginResponse,
  AdminSessionResponse,
  ArtifactType,
  ExportFormat,
  ArtifactStatus,
  JobStatus,
  ImageAccessScope,
} from '../src/shared/types/common.types';
import {
  parseArtifactSummary,
  parseJobStatusResponse,
  parseImageResult,
  assertAdminLoginRequest,
  parseAdminLoginResponse,
  parseAdminSessionResponse,
} from '../src/shared/contracts';

describe('Phase 4: TypeScript Contracts & Canonical Schema Compatibility', () => {
  it('strictly validates ArtifactSummary matches canonical schema and TypeScript contract', () => {
    const validSummary: ArtifactSummary = {
      artifact_id: 'art-demo-100',
      type: 'spreadsheet' as ArtifactType,
      title: 'Báo cáo Tuyển sinh 2026',
      preview_url: 'https://cdn.huit.edu.vn/preview.svg',
      manifest_url: '/api/artifacts/art-demo-100/manifest',
      available_formats: ['xlsx', 'docx', 'pdf', 'png', 'svg', 'webp'] as ExportFormat[],
      preview_bytes: 4096,
      checksum: 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855',
      chart_type: 'bar',
      status: 'ready' as ArtifactStatus,
      owner_id: 'user_123',
      error_message: null,
    };

    const parsed = parseArtifactSummary(validSummary);
    expect(parsed.artifact_id).toBe(validSummary.artifact_id);
    expect(parsed.type).toBe('spreadsheet');
    expect(parsed.available_formats).toContain('xlsx');

    // Reject invalid enum value
    expect(() => parseArtifactSummary({ ...validSummary, type: 'audio' })).toThrow('CONTRACT_VIOLATION');
    // Reject missing required field
    expect(() => parseArtifactSummary({ ...validSummary, manifest_url: undefined })).toThrow('CONTRACT_VIOLATION');
    // Reject unknown additional properties
    expect(() => parseArtifactSummary({ ...validSummary, extra_property: 'leaked' })).toThrow('CONTRACT_VIOLATION');
  });

  it('strictly validates JobStatusResponse without obsolete error_code', () => {
    const validJob: JobStatusResponse = {
      job_id: 'job-9876543210',
      action: 'export',
      status: 'processing' as JobStatus,
      progress: 55,
      artifact_id: 'art-demo-100',
      result_url: null,
      download_url: null,
      check_status_url: '/api/jobs/job-9876543210',
      media_type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
      error: null,
      created_at: '2026-09-22T00:00:00Z',
      updated_at: '2026-09-22T00:01:00Z',
    };

    const parsed = parseJobStatusResponse(validJob);
    expect(parsed.job_id).toBe('job-9876543210');
    expect(parsed.status).toBe('processing');

    // Canonical schema has additionalProperties: false - obsolete error_code must be rejected
    expect(() => parseJobStatusResponse({ ...validJob, error_code: 'RENDER_FAILED' })).toThrow('CONTRACT_VIOLATION');

    // Error as dictionary payload is valid
    const jobWithError: JobStatusResponse = {
      ...validJob,
      status: 'failed',
      error: { code: 'ERR_MEM', detail: 'Out of memory' },
    };
    expect(parseJobStatusResponse(jobWithError).status).toBe('failed');
  });

  it('strictly validates ImageResult matches canonical schema and TypeScript contract', () => {
    const validImage: ImageResult = {
      image_id: 'img_test_abc123',
      id: 'img_test_abc123',
      image_url: '/api/images/img_test_abc123/file',
      thumbnail_url: '/api/images/img_test_abc123/thumbnail',
      svg_url: '/api/images/img_test_abc123/svg',
      json_url: '/api/images/img_test_abc123',
      width: 512,
      height: 512,
      model: 'FLUX.1-schnell',
      style: 'photorealistic',
      byte_size: 15420,
      checksum: 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855',
      request_fingerprint: 'fp_abc123',
      billing: 'free',
      cached: false,
      access_scope: 'public' as ImageAccessScope,
      owner_id: null,
    };

    const parsed = parseImageResult(validImage);
    expect(parsed.image_id).toBe('img_test_abc123');
    expect(parsed.access_scope).toBe('public');

    // Reject unknown access scope
    expect(() => parseImageResult({ ...validImage, access_scope: 'confidential' })).toThrow('CONTRACT_VIOLATION');
    // Reject unknown field leaking from database
    expect(() => parseImageResult({ ...validImage, internal_prompt_hash: 'secret' })).toThrow('CONTRACT_VIOLATION');
  });

  it('strictly validates Admin login request and responses', () => {
    const validReq: AdminLoginRequest = {
      username: 'admin_test',
      password: 'correct_password',
    };
    expect(() => assertAdminLoginRequest(validReq)).not.toThrow();
    expect(() => assertAdminLoginRequest({ ...validReq, extra: 123 })).toThrow('CONTRACT_VIOLATION');

    const validResp: AdminLoginResponse = {
      success: true,
      csrf_token: 'valid_csrf_token_abcdef1234567890',
      message: 'Đăng nhập thành công',
    };
    expect(parseAdminLoginResponse(validResp).success).toBe(true);
    expect(() => parseAdminLoginResponse({ ...validResp, success: false })).toThrow('CONTRACT_VIOLATION');

    const validSession: AdminSessionResponse = {
      valid: true,
      role: 'admin',
    };
    expect(parseAdminSessionResponse(validSession).role).toBe('admin');
    expect(() => parseAdminSessionResponse({ valid: true, role: 'user' })).toThrow('CONTRACT_VIOLATION');
  });
});
