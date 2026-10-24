import { act, renderHook } from '@testing-library/react';
import { beforeEach, describe, expect, it } from 'vitest';
import { useChatHistory } from '../src/features/history/hooks/useChatHistory';
import {
  getSessionScope,
  setSessionCredentials,
} from '../src/shared/auth/csrfStore';
import {
  getActiveJob,
  saveActiveJob,
} from '../src/features/artifacts/utils/jobStorage';

describe('Session-scoped browser storage', () => {
  beforeEach(() => {
    localStorage.clear();
    sessionStorage.clear();
    setSessionCredentials({ sessionId: '', csrfToken: '' });
  });

  it('không lưu raw session id trong khóa scope và tách active job giữa hai phiên', () => {
    setSessionCredentials({
      sessionId: 'sess_owner_alpha',
      csrfToken: 'csrf-owner-alpha-123456',
    });
    const alphaScope = getSessionScope();
    expect(alphaScope).toMatch(/^scope_[a-f0-9]{16}$/);
    expect(alphaScope).not.toContain('sess_owner_alpha');

    saveActiveJob('export', 'art-private-001', 'job-alpha-001', { format: 'xlsx' });
    expect(getActiveJob('export', 'art-private-001')?.jobId).toBe('job-alpha-001');

    setSessionCredentials({
      sessionId: 'sess_owner_beta',
      csrfToken: 'csrf-owner-beta-123456',
    });
    expect(getActiveJob('export', 'art-private-001')).toBeNull();
  });

  it('chỉ hiển thị lịch sử đúng scope và vô hiệu hóa artifact legacy', () => {
    const alphaScope = getSessionScope('sess_owner_alpha');
    const betaScope = getSessionScope('sess_owner_beta');
    localStorage.setItem(
      'huit_chat_sessions',
      JSON.stringify([
        {
          sessionId: 'chat-alpha',
          ownerScope: alphaScope,
          title: 'Phiên A',
          createdAt: 1,
          updatedAt: 1,
          messages: [{ id: 'a', role: 'assistant', content: 'A', timestamp: 1 }],
        },
        {
          sessionId: 'chat-beta',
          ownerScope: betaScope,
          title: 'Phiên B',
          createdAt: 1,
          updatedAt: 1,
          messages: [{ id: 'b', role: 'assistant', content: 'B', timestamp: 1 }],
        },
        {
          sessionId: 'chat-legacy',
          title: 'Phiên cũ',
          createdAt: 1,
          updatedAt: 1,
          messages: [
            {
              id: 'legacy',
              role: 'assistant',
              content: 'Legacy',
              timestamp: 1,
              artifact: {
                artifact_id: 'art-legacy',
                type: 'spreadsheet',
                title: 'Tài liệu cũ',
                status: 'ready',
                preview_url: '/api/artifacts/art-legacy/preview',
              },
            },
          ],
        },
      ])
    );

    const { result } = renderHook(() => useChatHistory(alphaScope));
    expect(result.current.sessions.map((session) => session.sessionId)).toEqual([
      'chat-alpha',
      'chat-legacy',
    ]);
    expect(result.current.sessions[1].messages[0].artifact?.status).toBe('unavailable');
    expect(result.current.sessions[1].messages[0].artifact?.preview_url).toBeUndefined();

    act(() => {
      result.current.clearAllSessions();
    });
    const stored = JSON.parse(localStorage.getItem('huit_chat_sessions') || '[]');
    expect(stored).toHaveLength(1);
    expect(stored[0].sessionId).toBe('chat-beta');
  });
});
