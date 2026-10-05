import type { SessionId } from '@deepseek-ai/dsh-session'
/** Reliable navigation from persisted DoG invocation metadata into the canonical DSH session stage. */

import type { ISessions } from '@deepseek-ai/dsh-api-session-controller/client'

const DEFAULT_SELECTION_TIMEOUT_MS = 2_000

type SessionNavigator = Pick<ISessions, 'list'> & Partial<Pick<
  ISessions,
  'open' | 'openSubagent' | 'subagentAddress' | 'refreshSubagents'
>>
type Address = Parameters<ISessions['openSubagent']>[0]
type UiNavigator = { openSession(target: SessionId | Address): void }

function selected(sessions: SessionNavigator, id: SessionId): boolean {
  const snapshot = sessions.list.getSnapshot()
  if ('current' in snapshot) return snapshot.current === id
  const row = snapshot.byId?.[id] as { retainedBy?: { mainView?: number } } | undefined
  return (row?.retainedBy?.mainView ?? 0) > 0
}

export async function refreshInvocationCatalog(sessions: SessionNavigator, parent: string): Promise<void> {
  if (typeof sessions.refreshSubagents === 'function') await sessions.refreshSubagents(parent as SessionId)
}

/**
 * Select a persisted invocation session and confirm that DSH actually staged it.
 * Returns false only when neither the ordinary session list nor a refreshed
 * direct-parent catalog can address the target.
 */
export async function openInvocationSession(
  sessions: SessionNavigator,
  rawSessionId: string,
  rawParentSessionId?: string,
  timeoutMs = DEFAULT_SELECTION_TIMEOUT_MS,
  uiWorkspace?: UiNavigator,
): Promise<boolean> {
  const sessionId = rawSessionId as SessionId
  if (selected(sessions, sessionId)) return true

  if (sessions.list.getSnapshot().ids.includes(sessionId)) {
    await selectAndConfirm(sessions, sessionId, () => {
      if (uiWorkspace) uiWorkspace.openSession(sessionId)
      else if (sessions.open) sessions.open(sessionId)
      else throw new Error('DSH exposes no session navigation API')
    }, timeoutMs)
    return true
  }

  let address = sessions.subagentAddress?.(sessionId)
  if (address === undefined && rawParentSessionId !== undefined) {
    await refreshInvocationCatalog(sessions, rawParentSessionId)
    address = sessions.subagentAddress?.(sessionId)
    // DoG persists the direct parent of its continuable invocation. The new
    // navigator accepts this durable address without the removed catalog API.
    if (!address && uiWorkspace) address = {
      parentSessionId: rawParentSessionId as SessionId, childSessionId: sessionId, mode: 'continuable',
    }
  }
  if (address === undefined) return false

  const target = address
  await selectAndConfirm(sessions, sessionId, () => {
    if (uiWorkspace) uiWorkspace.openSession(target)
    else if (sessions.openSubagent) sessions.openSubagent(target)
    else throw new Error('DSH exposes no subagent navigation API')
  }, timeoutMs)
  return true
}

async function selectAndConfirm(
  sessions: SessionNavigator,
  sessionId: SessionId,
  select: () => void,
  timeoutMs: number,
): Promise<void> {
  await new Promise<void>((resolve, reject) => {
    let settled = false
    let unsubscribe = (): void => undefined
    const finish = (error?: Error): void => {
      if (settled) return
      settled = true
      clearTimeout(timer)
      unsubscribe()
      if (error === undefined) resolve()
      else reject(error)
    }
    const confirm = (): void => {
      if (selected(sessions, sessionId)) finish()
    }
    const timer = setTimeout(() => {
      finish(new Error(`DSH did not select session ${sessionId} within ${timeoutMs} ms`))
    }, timeoutMs)
    unsubscribe = sessions.list.subscribe(confirm)
    try {
      select()
      confirm()
    } catch (cause) {
      finish(cause instanceof Error ? cause : new Error(String(cause)))
    }
  })
}
