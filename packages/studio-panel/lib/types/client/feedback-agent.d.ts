import type { FeedbackAgentDispatchResult } from './OpenWriteSettings.tsx';
import { type StudioPanelInjected } from './workspace-context.ts';
/**
 * Dispatch a sanitized `/feedback` prompt directly into the host Agent Loop.
 *
 * Reuses the currently displayed OpenWrite session (or any existing OpenWrite
 * session), otherwise creates a fresh OpenWrite session, queues the prompt,
 * and navigates the UI to that session. Falls back cleanly if the host API is
 * unavailable or rejects the prompt.
 */
export declare function dispatchFeedbackToHostAgent(sources: {
    sessions: StudioPanelInjected['sessions'];
    uiWorkspace: unknown;
}, prompt: string): Promise<FeedbackAgentDispatchResult>;
