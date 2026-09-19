import { describe, expect, it } from 'vitest';
import {
  assertChatRequest,
  parseChatStreamEvent,
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
});
