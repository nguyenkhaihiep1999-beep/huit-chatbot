import type {
  ArtifactSummaryContract,
  JobStatusResponseContract,
  ImageResultContract,
  AdminLoginRequestContract,
  AdminLoginResponseContract,
  AdminSessionResponseContract,
  ArtifactManifestContract,
  ArtifactPlanRequestContract,
  ArtifactRenderRequestContract,
  ArtifactUpscaleRequestContract,
  ArtifactExportRequestContract,
  ImageCreateRequestContract,
  ApiErrorResponseContract,
  SessionBootstrapContract,
  ChatRequestContract,
  CanonicalChatStreamEvent,
} from '../contracts';

export type ThemeMode = 'light' | 'dark';

export interface SourceCitation {
  i: number;
  title: string;
  url: string;
  score: number;
  text: string;
}

export interface TraceStep {
  step: number;
  name: string;
  detail: string;
  status: 'success' | 'warning' | 'error' | 'pending';
}

export type ArtifactType = 'spreadsheet' | 'document' | 'image';
export type ExportFormat = 'xlsx' | 'docx' | 'pdf' | 'png' | 'svg' | 'webp';
export type ArtifactStatus = 'planned' | 'rendering' | 'ready' | 'failed' | 'unavailable' | 'pending';
export type JobStatus = 'queued' | 'pending' | 'processing' | 'completed' | 'failed' | 'cancelled';
export type ImageAccessScope = 'public' | 'private' | 'legacy_public';

export type ArtifactSummary = ArtifactSummaryContract;
export type JobStatusResponse = JobStatusResponseContract;
export type ImageResult = ImageResultContract;
export type AdminLoginRequest = AdminLoginRequestContract;
export type AdminLoginResponse = AdminLoginResponseContract;
export type AdminSessionResponse = AdminSessionResponseContract;

export type ArtifactManifest = ArtifactManifestContract;
export type ArtifactPlanRequest = ArtifactPlanRequestContract;
export type ArtifactRenderRequest = ArtifactRenderRequestContract;
export type ArtifactUpscaleRequest = ArtifactUpscaleRequestContract;
export type ArtifactExportRequest = ArtifactExportRequestContract;
export type ImageCreateRequest = ImageCreateRequestContract;
export type ApiErrorResponse = ApiErrorResponseContract;
export type SessionBootstrapResponse = SessionBootstrapContract;
export type ChatRequest = ChatRequestContract;
export type ChatStreamEvent = CanonicalChatStreamEvent;

export interface VisualMetadata {
  visual_id: string;
  artifact_id?: string;
  type: string;
  title: string;
  svg_url: string;
  png_url: string;
  xlsx_url?: string;
  docx_url?: string;
  pdf_url?: string;
  json_url: string;
  available_formats?: string[];
  status?: ArtifactStatus;
  error_message?: string;
}

export interface AppError {
  code: string;
  message: string;
  status?: number;
  retryAfterSeconds?: number;
  canRetry?: boolean;
}

export interface ChatMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  sources?: SourceCitation[];
  trace?: TraceStep[];
  visual?: VisualMetadata | null;
  artifact?: ArtifactSummary | null;
  cached?: boolean;
  timestamp: number;
  isStreaming?: boolean;
  isStopped?: boolean;
  error?: AppError | null;
}

export interface ConversationSession {
  sessionId: string;
  /** Hash cục bộ của phiên backend; không phải token và không dùng để phân quyền. */
  ownerScope?: string;
  title: string;
  createdAt: number;
  updatedAt: number;
  messages: ChatMessage[];
}
