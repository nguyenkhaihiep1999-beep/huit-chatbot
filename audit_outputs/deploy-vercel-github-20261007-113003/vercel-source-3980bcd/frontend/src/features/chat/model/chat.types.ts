export * from '../../../shared/types/common.types';

export interface ChatStreamBaseChunk {
  protocol_version?: number;
  sequence?: number;
  stream_id?: string;
  request_id?: string;
  timestamp?: string;
  payload?: Record<string, any>;
}

export interface ChatStreamStartedChunk extends ChatStreamBaseChunk {
  type: 'stream_started';
}

export interface ChatStreamStartChunk extends ChatStreamBaseChunk {
  type: 'start';
  version?: string;
}

export interface ChatStreamMetaChunk extends ChatStreamBaseChunk {
  type: 'meta';
  sources?: Array<{
    i: number;
    title: string;
    url: string;
    score: number;
    text: string;
  }>;
  trace?: Array<{
    step: number;
    name: string;
    detail: string;
    status: 'success' | 'warning' | 'error' | 'pending';
  }>;
  visual?: any;
  artifact?: any;
  cached?: boolean;
}

export interface ChatStreamProgressChunk extends ChatStreamBaseChunk {
  type: 'progress';
  stage?: string;
  sources?: Array<{
    i: number;
    title: string;
    url: string;
    score: number;
    text: string;
  }>;
  trace?: Array<{
    step: number;
    name: string;
    detail: string;
    status: 'success' | 'warning' | 'error' | 'pending';
  }>;
  visual?: any;
  artifact?: any;
  cached?: boolean;
}

export interface ChatStreamTokenChunk extends ChatStreamBaseChunk {
  type: 'token' | 'text_delta';
  token?: string;
  delta?: string;
}

export interface ChatStreamArtifactPlannedChunk extends ChatStreamBaseChunk {
  type: 'artifact_planned';
  artifact_id?: string;
  title?: string;
  artifact_type?: string;
  file_type?: string;
  chart_type?: string;
  preview_url?: string;
  manifest_url?: string;
  available_formats?: string[];
  manifest?: any;
}

export interface ChatStreamPreviewReadyChunk extends ChatStreamBaseChunk {
  type: 'preview_ready';
  artifact_id?: string;
  preview_url?: string;
  visual?: any;
  preview_key?: string;
}

export interface ChatStreamTextCompletedChunk extends ChatStreamBaseChunk {
  type: 'text_completed';
  length?: number;
}

export interface ChatStreamHeartbeatChunk extends ChatStreamBaseChunk {
  type: 'heartbeat';
  status?: string;
}

export interface ChatStreamErrorChunk extends ChatStreamBaseChunk {
  type: 'error';
  error_code?: string;
  message?: string;
  retryable?: boolean;
}

export interface ChatStreamCompletedChunk extends ChatStreamBaseChunk {
  type: 'completed';
  latency_ms?: number;
  cached?: boolean;
  metrics?: Record<string, any>;
}

export interface ChatStreamDoneChunk extends ChatStreamBaseChunk {
  type: 'done';
  latency_ms?: number;
  cached?: boolean;
  metrics?: Record<string, any>;
}

export interface ChatStreamArtifactChunk extends ChatStreamBaseChunk {
  type: 'artifact';
  artifact_id?: string;
  title?: string;
  artifact_type?: string;
  file_type?: string;
  chart_type?: string;
  preview_url?: string;
  manifest_url?: string;
  available_formats?: string[];
  manifest?: any;
  status?: string;
}

export interface ChatStreamSourcesChunk extends ChatStreamBaseChunk {
  type: 'sources';
  sources?: Array<{
    i: number;
    title: string;
    url: string;
    score: number;
    text: string;
  }>;
}

export interface ChatStreamCancelledChunk extends ChatStreamBaseChunk {
  type: 'cancelled';
  detail?: string;
}

export type ChatStreamChunk =
  | ChatStreamStartedChunk
  | ChatStreamStartChunk
  | ChatStreamMetaChunk
  | ChatStreamProgressChunk
  | ChatStreamSourcesChunk
  | ChatStreamTokenChunk
  | ChatStreamArtifactPlannedChunk
  | ChatStreamArtifactChunk
  | ChatStreamPreviewReadyChunk
  | ChatStreamTextCompletedChunk
  | ChatStreamHeartbeatChunk
  | ChatStreamErrorChunk
  | ChatStreamCompletedChunk
  | ChatStreamDoneChunk
  | ChatStreamCancelledChunk;
