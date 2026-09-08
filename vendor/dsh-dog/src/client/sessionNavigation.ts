import type { SessionId } from '@deepseek-ai/dsh-session'
/** Reliable navigation from persisted DoG invocation metadata into the canonical DSH session stage. */

import type { ISessions } from '@deepseek-ai/dsh-api-session-controller/client'

const DEFAULT_SELECTION_TIMEOUT_MS = 2_000

type SessionNavigator = Pick<
  ISessions,
  'list' | 'open' | 'openSubagent' | 'subagentAddress' | 'refreshSubagents'
>

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
): Promise<boolean> {
  const sessionId = rawSessionId as SessionId
  if (sessions.list.getSnapshot().current === sessionId) return true

  if (sessions.list.getSnapshot().ids.includes(sessionId)) {
    await selectAndConfirm(sessions, sessionId, () => sessions.open(sessionId), timeoutMs)
    return true
  }

  let address = sessions.subagentAddress(sessionId)
  if (address === undefined && rawParentSessionId !== undefined) {
    await sessions.refreshSubagents(rawParentSessionId as SessionId)
    address = sessions.subagentAddress(sessionId)
  }
  if (address === undefined) return false

  await selectAndConfirm(sessions, sessionId, () => sessions.openSubagent(address), timeoutMs)
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
      if (sessions.list.getSnapshot().current === sessionId) finish()
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
