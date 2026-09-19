import chatRequestSchema from './schemas/chat-request.v1.schema.json';
import chatEventSchema from './schemas/chat-event.v2.schema.json';
import legacyChatEventSchema from './schemas/chat-event-legacy-boundary.v1.schema.json';
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
      legacyChatEventSchema,
      value,
      'huit.stream.chat-event-legacy-boundary@1.0.0'
    );
  }
  return value as CanonicalChatStreamEvent;
}
