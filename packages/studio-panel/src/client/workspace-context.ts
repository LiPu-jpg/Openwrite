/**
 * dsh Workspace ↔ panel context glue (docs/WORKSPACE_CONTEXT_CONTRACT.md §9).
 *
 * Slot components receive the framework standard kit (`sessionId`,
 * `useWorkspaces`) as props; these helpers derive the session's current
 * Workspace from them and bind it into the WorkbenchStore context barrier.
 * Project listing/switching is deliberately absent: workspace selection is a
 * dsh-native flow, the panel only ever reflects the session's binding.
 */
import { useEffect } from 'react'
import type {
  ISessions,
  IWorkspaces,
  SessionId,
  WorkspaceListState,
  WorkspaceView,
} from '@deepseek-ai/dsh-client-runtime/client'
import type { SnapshotSelectorHook } from '@deepseek-ai/dsh-client-ui-slots'
import type { StudioApiInjected } from './api.ts'
import { workbenchStore } from './WorkbenchStore.ts'

/** The framework standard-kit members the Workspace helpers consume. */
export interface WorkspaceStandardKit {
  sessionId: SessionId | undefined
  useWorkspaces: SnapshotSelectorHook<WorkspaceListState>
}

/**
 * The full inject face for the conversation views: the Studio API trio plus
 * the dsh domain services the new-work flow drives (directory pick →
 * workspace create → session connect).
 */
export interface StudioPanelInjected extends StudioApiInjected {
  workspaces: IWorkspaces
  sessions: ISessions
}

/** The Workspace the current session is accounted under, if any. */
export function useCurrentWorkspace(kit: WorkspaceStandardKit): WorkspaceView | undefined {
  const { sessionId, useWorkspaces } = kit
  return useWorkspaces(state => sessionId === undefined
    ? undefined
    : state.items.find(item => item.sessionIds.includes(sessionId)))
}

/**
 * Reflect the session's Workspace binding into the WorkbenchStore context
 * barrier. Idempotent (setContext no-ops on an identical context), so every
 * always-mounted session-scope component may call it. Returns the current
 * Workspace for display.
 */
export function useBindStudioContext(kit: WorkspaceStandardKit): WorkspaceView | undefined {
  const workspace = useCurrentWorkspace(kit)
  const workspaceId = workspace?.workspaceId
  const root = workspace?.path
  const sessionId = kit.sessionId
  useEffect(() => {
    workbenchStore.setContext(workspaceId === undefined || root === undefined
      ? null
      : { workspaceId, root, sessionId })
  }, [workspaceId, root, sessionId])
  return workspace
}

export type CreateNovelResult = 'created' | 'cancelled'

/**
 * Initialize the OpenWrite project at a bound Workspace's canonical absolute
 * path (contract §5: init pins the context root) and refresh the store.
 * Throws on failure — callers surface the message.
 */
export async function initWorkspaceProject(
  postStudioApi: StudioApiInjected['postStudioApi'],
  workspacePath: string,
  input: { novelId: string; title: string },
): Promise<void> {
  await postStudioApi('/project/init', {
    project_path: workspacePath,
    novel_id: input.novelId,
    title: input.title,
  })
  await workbenchStore.refresh()
}

/**
 * The new-work flow (contract §9): pick a directory through the host's native
 * picker → register it as a dsh Workspace → bind the panel context (the proxy
 * resolves the id from this point) → context-mode `/project/init` with the
 * Workspace's canonical absolute path → connect a session and open it.
 *
 * Every failure throws to the caller for surfacing — no silent fallback. A
 * cancelled picker aborts the flow quietly ('cancelled').
 */
export async function createNovelWorkspace(
  services: Pick<StudioPanelInjected, 'workspaces' | 'sessions'>,
  postStudioApi: StudioApiInjected['postStudioApi'],
  input: { novelId: string; title: string },
): Promise<CreateNovelResult> {
  const picked = await services.workspaces.pickDirectory()
  if (picked === null) return 'cancelled'
  const workspace = await services.workspaces.create({ path: picked })
  workbenchStore.setContext({ workspaceId: workspace.workspaceId, root: workspace.path })
  await postStudioApi('/project/init', {
    project_path: workspace.path,
    novel_id: input.novelId,
    title: input.title,
  })
  const sessionId = await services.workspaces.connectWorkspace(workspace.workspaceId)
  services.sessions.open(sessionId)
  // Re-affirm the binding with the connected session id, then pull fresh state.
  workbenchStore.setContext({ workspaceId: workspace.workspaceId, root: workspace.path, sessionId })
  await workbenchStore.refresh()
  return 'created'
}
