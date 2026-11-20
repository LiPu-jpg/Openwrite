import type { SessionListState } from '@deepseek-ai/dsh-api-session-controller/client';
import type { SessionId } from '@deepseek-ai/dsh-session';
/**
 * Presentation follows the session the main view is displaying; the host tool
 * catalog never follows UI navigation.
 *
 * dsh 0.2 removed `SessionListState.current` — showing a session moved to
 * `UiWorkspace.openSession` — so the displayed session is read from the row's
 * own main-view retention, the same criterion `dsh-client-ui-agent-preset`
 * uses. Hosts that still publish `current` keep their previous behaviour.
 */
export declare function displayedSessionId(state: SessionListState): SessionId | undefined;
export declare function isWritingSession(state: SessionListState): boolean;
export declare function watchWritingScope(source: {
    getSnapshot(): SessionListState;
    subscribe(listener: () => void): () => void;
}, mount: () => (() => void)): () => void;
