import { describe, expect, it } from 'vitest';
import * as PublicHooks from '@hooks';
import { useChatStream as realChatStream } from '../src/features/chat/hooks/useChatStream';
import { useSessionBootstrap as realSessionBootstrap } from '../src/features/session/hooks/useSessionBootstrap';
import { useArtifactWorkflow as realArtifactWorkflow } from '../src/features/artifacts/hooks/useArtifactWorkflow';
import { useArtifactExport as sourceArtifactExport } from '../src/features/artifacts/hooks/useArtifactExport';
import { useArtifactUpscale as sourceArtifactUpscale } from '../src/features/artifacts/hooks/useArtifactUpscale';
import { useArtifactActions as sourceArtifactActions } from '../src/features/artifacts/hooks/useArtifactActions';
import { useAdminAuth as realAdminAuth } from '../src/features/admin/hooks/useAdminAuth';
import { useAdminDashboard as realAdminDashboard } from '../src/features/admin/hooks/useAdminDashboard';
import { useAdminOps as realAdminOps } from '../src/features/admin/hooks/useAdminOps';
import { useSpeechRecognition as realSpeechRecognition } from '../src/features/voice/hooks/useSpeechRecognition';
import { useSpeechSynthesis as realSpeechSynthesis } from '../src/features/voice/hooks/useSpeechSynthesis';
import { useDebounce as realDebounce } from '../src/shared/hooks/useDebounce';
import { useLocalStorage as realLocalStorage } from '../src/shared/hooks/useLocalStorage';
import { useTheme as realTheme } from '../src/features/theme/hooks/useTheme';
import { useChatHistory as realChatHistory } from '../src/features/history/hooks/useChatHistory';
import { useVisualLightbox as realVisualLightbox } from '../src/features/admission-visuals/hooks/useVisualLightbox';

describe('Public Hook Facade (@hooks)', () => {
  it('exports all designated public hooks through the @hooks alias with identical references', () => {
    // Chat hooks
    expect(PublicHooks.useChatStream).toBe(realChatStream);
    expect(typeof PublicHooks.useConversation).toBe('function');

    // Session hooks
    expect(PublicHooks.useSessionBootstrap).toBe(realSessionBootstrap);

    // Artifact hooks
    expect(PublicHooks.useArtifactWorkflow).toBe(realArtifactWorkflow);
    expect(PublicHooks.useArtifactExport).toBe(sourceArtifactExport);
    expect(PublicHooks.useArtifactUpscale).toBe(sourceArtifactUpscale);
    expect(PublicHooks.useArtifactActions).toBe(sourceArtifactActions);

    // Admin hooks
    expect(PublicHooks.useAdminAuth).toBe(realAdminAuth);
    expect(PublicHooks.useAdminDashboard).toBe(realAdminDashboard);
    expect(PublicHooks.useAdminOps).toBe(realAdminOps);

    // Voice hooks
    expect(PublicHooks.useSpeechRecognition).toBe(realSpeechRecognition);
    expect(PublicHooks.useSpeechSynthesis).toBe(realSpeechSynthesis);

    // Common & Shared hooks
    expect(PublicHooks.useDebounce).toBe(realDebounce);
    expect(PublicHooks.useLocalStorage).toBe(realLocalStorage);
    expect(PublicHooks.useTheme).toBe(realTheme);
    expect(PublicHooks.useChatHistory).toBe(realChatHistory);
    expect(PublicHooks.useVisualLightbox).toBe(realVisualLightbox);
  });

  it('keeps internal-only feature hooks strictly hidden from @hooks', () => {
    // useImageGeneration is internal to the modal implementation
    expect((PublicHooks as Record<string, unknown>).useImageGeneration).toBeUndefined();
  });

  it('allows importing from individual category facades in frontend/hooks/*', async () => {
    const chatFacade = await import('../hooks/chat');
    expect(chatFacade.useChatStream).toBe(realChatStream);

    const sessionFacade = await import('../hooks/session');
    expect(sessionFacade.useSessionBootstrap).toBe(realSessionBootstrap);

    const artifactsFacade = await import('../hooks/artifacts');
    expect(artifactsFacade.useArtifactWorkflow).toBe(realArtifactWorkflow);

    const adminFacade = await import('../hooks/admin');
    expect(adminFacade.useAdminAuth).toBe(realAdminAuth);

    const voiceFacade = await import('../hooks/voice');
    expect(voiceFacade.useSpeechRecognition).toBe(realSpeechRecognition);

    const commonFacade = await import('../hooks/common');
    expect(commonFacade.useDebounce).toBe(realDebounce);
  });
});
