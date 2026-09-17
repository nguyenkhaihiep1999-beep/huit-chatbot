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

export interface ArtifactSummary {
  artifact_id: string;
  type: 'spreadsheet' | 'document' | 'chart' | 'image' | 'infographic' | string;
  title: string;
  preview_url?: string;
  manifest_url?: string;
  available_formats?: string[];
  preview_bytes?: number;
  status?: 'planned' | 'rendering' | 'ready' | 'failed' | 'unavailable';
  error_message?: string;
  owner_id?: string | null;
}

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
  status?: 'planned' | 'rendering' | 'ready' | 'failed' | 'unavailable';
  error_message?: string;
}

export interface AppError {
  code: string;
  message: string;
  status?: number;
  retryAfterSeconds?: number;
  canRetry?: boolean;
}

export interface JobStatusResponse {
  job_id: string;
  action: string;
  status: 'queued' | 'pending' | 'processing' | 'completed' | 'failed' | 'cancelled';
  progress?: number;
  result_url?: string | null;
  download_url?: string | null;
  error?: string | null;
  error_code?: string | null;
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
  title: string;
  createdAt: number;
  updatedAt: number;
  messages: ChatMessage[];
}
