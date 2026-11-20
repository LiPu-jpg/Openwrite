import type { ISessions } from '@deepseek-ai/dsh-api-session-controller/client';
import type { SessionId } from '@deepseek-ai/dsh-session';
import type { IWorkspaces, WorkspaceSnapshot, WorkspaceView } from '@deepseek-ai/dsh-api-workspace-controller/client';
import type { SnapshotSelectorHook } from '@deepseek-ai/dsh-client-ui-slots';
import type { UiWorkspace } from '@deepseek-ai/dsh-client-ui-workspace/client';
import type { StudioApiInjected } from './api.ts';
/** The framework standard-kit members the Workspace helpers consume. */
export interface WorkspaceStandardKit {
    sessionId: SessionId | undefined;
    useWorkspaces: SnapshotSelectorHook<WorkspaceSnapshot>;
}
/**
 * Showing a session. dsh 0.2 moved this out of the Session Controller
 * (`ISessions` has no `open`) and into `UiWorkspace.openSession`; 0.1.x never
 * had the latter. The injected face carries whichever one this host provides.
 */
export interface SessionOpener {
    openSession(target: SessionId): void;
}
/**
 * Build the opener once per profile so one build serves both host generations:
 * probe at call time rather than binding to either API shape.
 * @param sources - the client services that may own session navigation.
 * @returns an opener that throws only when the host offers neither API.
 */
export declare function sessionOpener(sources: {
    uiWorkspace: unknown;
    sessions: unknown;
}): SessionOpener;
/**
 * The full inject face for the conversation views: the Studio API trio plus
 * the dsh domain services the new-work flow drives (directory pick →
 * workspace create → session connect).
 */
export interface StudioPanelInjected extends StudioApiInjected {
    workspaces: IWorkspaces & Pick<UiWorkspace, 'pickDirectory' | 'connectWorkspace'> & SessionOpener;
    sessions: ISessions;
}
/** The Workspace the current session is accounted under, if any. */
export declare function useCurrentWorkspace(kit: WorkspaceStandardKit): WorkspaceView | undefined;
/**
 * Reflect the session's Workspace binding into the WorkbenchStore context
 * barrier. Idempotent (setContext no-ops on an identical context), so every
 * always-mounted session-scope component may call it. Returns the current
 * Workspace for display.
 */
export declare function useBindStudioContext(kit: WorkspaceStandardKit): WorkspaceView | undefined;
export type CreateNovelResult = 'created' | 'cancelled';
/**
 * Initialize the OpenWrite project at a bound Workspace's canonical absolute
 * path (contract §5: init pins the context root) and refresh the store.
 * Throws on failure — callers surface the message.
 */
export declare function initWorkspaceProject(postStudioApi: StudioApiInjected['postStudioApi'], workspacePath: string, input: {
    novelId: string;
    title: string;
}): Promise<void>;
/**
 * The new-work flow (contract §9): pick a directory through the host's native
 * picker → register it as a dsh Workspace → bind the panel context (the proxy
 * resolves the id from this point) → context-mode `/project/init` with the
 * Workspace's canonical absolute path → connect a session and open it.
 *
 * Every failure throws to the caller for surfacing — no silent fallback. A
 * cancelled picker aborts the flow quietly ('cancelled').
 */
export declare function createNovelWorkspace(services: Pick<StudioPanelInjected, 'workspaces' | 'sessions'>, postStudioApi: StudioApiInjected['postStudioApi'], input: {
    novelId: string;
    title: string;
}): Promise<CreateNovelResult>;
