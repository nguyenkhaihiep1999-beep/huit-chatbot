import adminLoginRequestSchema from './schemas/admin-login-request.v1.schema.json';
import adminLoginResponseSchema from './schemas/admin-login-response.v1.schema.json';
import adminSessionResponseSchema from './schemas/admin-session-response.v1.schema.json';
import artifactExportRequestSchema from './schemas/artifact-export-request.v1.schema.json';
import artifactManifestSchema from './schemas/artifact-manifest.v1.schema.json';
import artifactPlanRequestSchema from './schemas/artifact-plan-request.v1.schema.json';
import artifactRenderRequestSchema from './schemas/artifact-render-request.v1.schema.json';
import artifactSummarySchema from './schemas/artifact-summary.v1.schema.json';
import artifactUpscaleRequestSchema from './schemas/artifact-upscale-request.v1.schema.json';
import chatEventLegacyBoundarySchema from './schemas/chat-event-legacy-boundary.v1.schema.json';
import chatEventSchema from './schemas/chat-event.v2.schema.json';
import chatRequestSchema from './schemas/chat-request.v1.schema.json';
import errorResponseSchema from './schemas/error-response.v1.schema.json';
import imageCreateRequestSchema from './schemas/image-create-request.v1.schema.json';
import imageResultSchema from './schemas/image-result.v1.schema.json';
import jobStatusResponseSchema from './schemas/job-status-response.v1.schema.json';
import jobAcceptedResponseSchema from './schemas/job-accepted-response.v1.schema.json';
import sessionBootstrapSchema from './schemas/session-bootstrap-response.v1.schema.json';
import { assertJsonSchema } from './jsonSchema';

export interface SessionBootstrapContract {
  success: true;
  session_id: string;
  csrf_token: string;
  issued_at: number;
  expires_at: number;
  ttl_seconds: number;
}

export interface ChatRequestContract {
  question: string;
  history?: Array<{ role: 'user' | 'assistant'; content: string }>;
  enable_cache?: boolean;
  session_id?: string | null;
}

export interface CanonicalChatStreamEvent {
  protocol_version: 2;
  stream_id: string;
  request_id: string;
  sequence: number;
  type: 'start' | 'token' | 'progress' | 'artifact' | 'error' | 'done' | 'cancelled' | 'heartbeat';
  timestamp: string;
  payload: Record<string, unknown>;
}

export interface AdminLoginRequestContract {
  username: string;
  password: string;
}

export interface AdminLoginResponseContract {
  success: true;
  csrf_token: string;
  message: string;
}

export interface AdminSessionResponseContract {
  valid: boolean;
  role: 'admin';
}

export interface ApiErrorResponseContract {
  error_code?: string;
  message?: string;
  detail?: string | Record<string, unknown> | unknown[];
  request_id?: string | null;
  details?: unknown;
}

export interface ArtifactManifestContract {
  version?: number;
  artifact_id: string;
  type: 'spreadsheet' | 'document' | 'image';
  template_id: string;
  title: string;
  description?: string | null;
  content?: Record<string, unknown>;
  style?: Record<string, unknown>;
  assets?: string[];
  preview: {
    type?: string;
    url: string;
    thumbnail_url?: string | null;
    width?: number | null;
    height?: number | null;
  };
  render?: {
    status?: 'pending' | 'rendering' | 'ready' | 'failed';
    quality?: 'preview' | 'standard' | 'high' | 'retina' | '4k';
    scale?: number;
    progress?: number;
    error?: string | null;
  };
  export_options?: Array<'xlsx' | 'docx' | 'pdf' | 'png' | 'svg' | 'webp'>;
  content_hash?: string | null;
  created_at?: string | null;
  owner_id?: string | null;
}

export interface ArtifactSummaryContract {
  artifact_id: string;
  type: 'spreadsheet' | 'document' | 'image';
  title: string;
  preview_url: string;
  manifest_url: string;
  available_formats?: Array<'xlsx' | 'docx' | 'pdf' | 'png' | 'svg' | 'webp'>;
  checksum?: string | null;
  preview_bytes?: number | null;
  chart_type?: string | null;
  status?: 'planned' | 'rendering' | 'ready' | 'failed' | 'unavailable' | 'pending' | null;
  owner_id?: string | null;
  error_message?: string | null;
}

export interface ArtifactPlanRequestContract {
  prompt: string;
  type?: 'spreadsheet' | 'document' | 'image' | null;
  template_id?: string | null;
  content?: Record<string, unknown> | null;
  user_id?: string | null;
  session_id?: string | null;
}

export interface ArtifactRenderRequestContract {
  artifact_id: string;
  format?: 'xlsx' | 'docx' | 'pdf' | 'png' | 'svg' | 'webp';
  quality?: 'preview' | 'standard' | 'high' | 'retina' | '4k';
  scale?: number;
}

export interface ArtifactUpscaleRequestContract {
  scale?: number;
}

export interface ArtifactExportRequestContract {
  format: 'xlsx' | 'docx' | 'pdf' | 'png' | 'svg' | 'webp';
}

export interface JobStatusResponseContract {
  job_id: string;
  action?: string | null;
  status: 'queued' | 'pending' | 'processing' | 'completed' | 'failed' | 'cancelled';
  progress?: number;
  artifact_id?: string | null;
  result_url?: string | null;
  download_url?: string | null;
  check_status_url?: string | null;
  media_type?: string | null;
  error?: Record<string, unknown> | string | null;
  created_at?: string | null;
  updated_at?: string | null;
}

export interface ImageCreateRequestContract {
  prompt: string;
  width?: number;
  height?: number;
  max_json_kb?: number;
  style?: string;
  backend?: 'flux' | 'svg';
  regenerate?: boolean;
}

export interface ImageResultContract {
  image_id: string;
  id?: string;
  image_url: string;
  thumbnail_url?: string | null;
  svg_url?: string | null;
  json_url?: string | null;
  width?: number;
  height?: number;
  model?: string;
  style?: string;
  byte_size?: number;
  checksum?: string | null;
  request_fingerprint?: string | null;
  billing?: string;
  cached?: boolean;
  access_scope?: 'public' | 'private' | 'legacy_public';
  owner_id?: string | null;
}

export function parseSessionBootstrapResponse(value: unknown): SessionBootstrapContract {
  assertJsonSchema(sessionBootstrapSchema, value, 'huit.api.session-bootstrap-response@1.0.0');
  return value as SessionBootstrapContract;
}

export function assertChatRequest(value: unknown): asserts value is ChatRequestContract {
  assertJsonSchema(chatRequestSchema, value, 'huit.api.chat-request@1.0.0');
}

export function parseChatStreamEvent(value: unknown): CanonicalChatStreamEvent {
  try {
    assertJsonSchema(chatEventSchema, value, 'huit.stream.chat-event@2.0.0');
  } catch (canonicalError) {
    const candidate = value && typeof value === 'object' ? value as Record<string, unknown> : null;
    const canonicalTypes = new Set(['start', 'token', 'progress', 'artifact', 'error', 'done', 'cancelled', 'heartbeat']);
    if (candidate?.protocol_version === 2 && canonicalTypes.has(String(candidate.type))) {
      throw canonicalError;
    }
    assertJsonSchema(
      chatEventLegacyBoundarySchema,
      value,
      'huit.stream.chat-event-legacy-boundary@1.0.0'
    );
  }
  return value as CanonicalChatStreamEvent;
}

export function assertAdminLoginRequest(value: unknown): asserts value is AdminLoginRequestContract {
  assertJsonSchema(adminLoginRequestSchema, value, 'huit.api.admin-login-request@1.0.0');
}

export function parseAdminLoginResponse(value: unknown): AdminLoginResponseContract {
  assertJsonSchema(adminLoginResponseSchema, value, 'huit.api.admin-login-response@1.0.0');
  return value as AdminLoginResponseContract;
}

export function parseAdminSessionResponse(value: unknown): AdminSessionResponseContract {
  assertJsonSchema(adminSessionResponseSchema, value, 'huit.api.admin-session-response@1.0.0');
  return value as AdminSessionResponseContract;
}

export function parseApiErrorResponse(value: unknown): ApiErrorResponseContract {
  assertJsonSchema(errorResponseSchema, value, 'huit.api.error-response@1.0.0');
  return value as ApiErrorResponseContract;
}

export function parseArtifactManifest(value: unknown): ArtifactManifestContract {
  assertJsonSchema(artifactManifestSchema, value, 'huit.api.artifact-manifest@1.0.0');
  return value as ArtifactManifestContract;
}

export function parseArtifactSummary(value: unknown): ArtifactSummaryContract {
  assertJsonSchema(artifactSummarySchema, value, 'huit.api.artifact-summary@1.0.0');
  return value as ArtifactSummaryContract;
}

export function assertArtifactPlanRequest(value: unknown): asserts value is ArtifactPlanRequestContract {
  assertJsonSchema(artifactPlanRequestSchema, value, 'huit.api.artifact-plan-request@1.0.0');
}

export function assertArtifactRenderRequest(value: unknown): asserts value is ArtifactRenderRequestContract {
  assertJsonSchema(artifactRenderRequestSchema, value, 'huit.api.artifact-render-request@1.0.0');
}

export function assertArtifactUpscaleRequest(value: unknown): asserts value is ArtifactUpscaleRequestContract {
  assertJsonSchema(artifactUpscaleRequestSchema, value, 'huit.api.artifact-upscale-request@1.0.0');
}

export function assertArtifactExportRequest(value: unknown): asserts value is ArtifactExportRequestContract {
  assertJsonSchema(artifactExportRequestSchema, value, 'huit.api.artifact-export-request@1.0.0');
}

export function parseJobStatusResponse(value: unknown): JobStatusResponseContract {
  assertJsonSchema(jobStatusResponseSchema, value, 'huit.api.job-status-response@1.0.0');
  return value as JobStatusResponseContract;
}

export interface JobAcceptedResponseContract {
  job_id: string;
  status: 'queued';
  artifact_id?: string | null;
  action?: 'render' | 'export' | 'upscale' | null;
  format?: 'xlsx' | 'docx' | 'pdf' | 'png' | 'svg' | 'webp' | 'html' | 'csv' | 'json' | null;
  scale?: number | null;
  check_status_url: string;
}

export function parseJobAcceptedResponse(value: unknown): JobAcceptedResponseContract {
  assertJsonSchema(jobAcceptedResponseSchema, value, 'huit.api.job-accepted-response@1.0.0');
  return value as JobAcceptedResponseContract;
}

export function assertImageCreateRequest(value: unknown): asserts value is ImageCreateRequestContract {
  assertJsonSchema(imageCreateRequestSchema, value, 'huit.api.image-create-request@1.0.0');
}

export function parseImageResult(value: unknown): ImageResultContract {
  assertJsonSchema(imageResultSchema, value, 'huit.api.image-result@1.0.0');
  return value as ImageResultContract;
}
