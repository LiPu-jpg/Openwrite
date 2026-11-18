import type { FeedbackAgentDispatchResult } from './OpenWriteSettings.tsx'
import { sessionOpener, type StudioPanelInjected } from './workspace-context.ts'
import { displayedSessionId } from './writing-scope.ts'

function isOpenWriteAgentPreset(value: unknown): boolean {
  return typeof value === 'string' && (value === 'openwrite' || value.startsWith('openwrite-'))
}

async function resolveSessionFace(
  sessions: StudioPanelInjected['sessions'],
  targetId: Parameters<StudioPanelInjected['sessions']['scope']>[0],
  openSession: () => void,
) {
  const tryGet = () => {
    const scope = sessions.scope(targetId)
    return scope === undefined ? undefined : sessions.sessionOf(scope)
  }
  let session = tryGet()
  if (session !== undefined) return session

  openSession()
  if (typeof sessions.refresh === 'function') {
    await sessions.refresh().catch(() => undefined)
  }
  for (let i = 0; i < 20; i += 1) {
    session = tryGet()
    if (session !== undefined) return session
    await new Promise(resolve => setTimeout(resolve, 100))
  }
  return undefined
}

/**
 * Dispatch a sanitized `/feedback` prompt directly into the host Agent Loop.
 *
 * Reuses the currently displayed OpenWrite session (or any existing OpenWrite
 * session), otherwise creates a fresh OpenWrite session, queues the prompt,
 * and navigates the UI to that session. Falls back cleanly if the host API is
 * unavailable or rejects the prompt.
 */
export async function dispatchFeedbackToHostAgent(
  sources: { sessions: StudioPanelInjected['sessions']; uiWorkspace: unknown },
  prompt: string,
): Promise<FeedbackAgentDispatchResult> {
  try {
    const state = sources.sessions.list.getSnapshot()
    const displayed = displayedSessionId(state)
    let targetId = displayed !== undefined && isOpenWriteAgentPreset(state.byId[displayed]?.projectionValues?.agentPreset)
      ? displayed
      : state.ids.find(id => isOpenWriteAgentPreset(state.byId[id]?.projectionValues?.agentPreset))

    if (targetId === undefined) {
      const createOpts = { agentPreset: 'openwrite' } as Parameters<StudioPanelInjected['sessions']['create']>[0]
      targetId = await sources.sessions.create(createOpts)
    }

    const openTarget = () => {
      try {
        sessionOpener({ uiWorkspace: sources.uiWorkspace, sessions: sources.sessions }).openSession(targetId!)
      } catch {
        // Opening the session tab is best-effort.
      }
    }

    const session = await resolveSessionFace(sources.sessions, targetId, openTarget)
    if (session === undefined) {
      return { status: 'fallback', reason: 'session-unavailable' }
    }

    const result = await session.prompt([{ type: 'text', text: prompt }], 'queue')
    if (result !== undefined && typeof result === 'object' && 'ok' in result && result.ok === false) {
      return { status: 'fallback', reason: 'prompt-rejected' }
    }

    openTarget()
    return { status: 'dispatched', sessionId: String(targetId) }
  } catch (error) {
    return { status: 'fallback', reason: error instanceof Error ? error.message : String(error) }
  }
}
