import type { SessionListState } from '@deepseek-ai/dsh-api-session-controller/client'

interface Source<T> {
  getSnapshot(): T
  subscribe(listener: () => void): () => void
}

interface SessionStatus {
  readonly pendingInteraction?: unknown
}

/** DSH 0.2 folds pending interactions into the unified session status source. */
export function debuggerSessionState(
  sessions: Source<SessionListState>,
  uiSession: {
    sessionStatus?: Source<ReadonlyMap<string, SessionStatus>>
    pendingInteractions?: Source<ReadonlyMap<string, unknown>>
  },
) {
  const status = uiSession.sessionStatus
  const source = status ?? uiSession.pendingInteractions
  if (!source || typeof source.getSnapshot !== 'function' || typeof source.subscribe !== 'function') {
    throw new Error('DSH session UI exposes neither sessionStatus nor pendingInteractions')
  }
  let lastSessions: SessionListState | undefined
  let lastStatus: unknown
  let combined: SessionListState & { pendingInteractions: ReadonlyMap<string, unknown> }
  return {
    getSnapshot() {
      const next = sessions.getSnapshot()
      const pending = source.getSnapshot()
      if (next !== lastSessions || pending !== lastStatus) {
        lastSessions = next
        lastStatus = pending
        const interactions = status
          ? new Map([...status.getSnapshot()].flatMap(([id, value]) =>
            value.pendingInteraction === undefined ? [] : [[id, value.pendingInteraction] as const]))
          : pending
        combined = { ...next, pendingInteractions: interactions }
      }
      return combined
    },
    subscribe(listener: () => void) {
      const stopSessions = sessions.subscribe(listener)
      try {
        const stopStatus = source.subscribe(listener)
        return () => { stopStatus(); stopSessions() }
      } catch (error) {
        stopSessions()
        throw error
      }
    },
  }
}
