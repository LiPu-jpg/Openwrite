import { useEffect, useState } from 'react'
/** Browser half: a frame overlay that visualizes persisted DoG revisions and runs. */

import type { ConnectionHandle } from '@deepseek-ai/dsh-client-connection/client'
import type { Context as ClientContext } from '@deepseek-ai/cordis'
import type {} from '@deepseek-ai/dsh-client-ui-session/client'
import type { ISessions } from '@deepseek-ai/dsh-api-session-controller/client'
import type { SessionId } from '@deepseek-ai/dsh-session'
import type {} from '@deepseek-ai/dsh-client-ui-renderer/client'
import type {} from '@deepseek-ai/dsh-client-ui-layout/client'
import {
  DOG_DEBUG_RPC_CHANNEL,
  DOG_DEBUG_SNAPSHOT_ENDPOINT,
  DOG_RUNTIME_TRACE_ENDPOINT,
} from '../debug-contract.ts'
import { DogDebugger } from './DogDebugger.tsx'
import { openInvocationSession } from './sessionNavigation.ts'
import { DOG_DEBUG_CSS, DOG_DEBUG_STYLE_ID } from './styles.ts'

/** The overlay uses the shared trusted RPC transport and canonical session navigator. */
export const inject = ['slots', 'sessions', 'connection', 'uiSession']

/** Register the debugger beside other frame-wide overlays without replacing shipped UI. */
export function apply(ctx: ClientContext): void {
  const connection = ctx.get('connection') as unknown as ConnectionHandle
  const sessions = ctx.get('sessions') as unknown as ISessions
  const call = async (endpoint: string, payload: unknown, signal?: AbortSignal): Promise<unknown> => {
    const result = await connection.rpc.call(DOG_DEBUG_RPC_CHANNEL, endpoint, payload, signal)
    if (!result.ok) throw new Error(result.error.message)
    return result.value
  }
  const openSession = (sessionId: string, parentSessionId?: string): Promise<boolean> =>
    openInvocationSession(sessions, sessionId, parentSessionId)
  let lastSessions = sessions.list.getSnapshot()
  let lastPending = ctx.uiSession.pendingInteractions.getSnapshot()
  let combined = { ...lastSessions, pendingInteractions: lastPending }
  const getSessionState = () => {
    const next = sessions.list.getSnapshot()
    const pending = ctx.uiSession.pendingInteractions.getSnapshot()
    if (next !== lastSessions || pending !== lastPending) {
      lastSessions = next; lastPending = pending
      combined = { ...next, pendingInteractions: pending }
    }
    return combined
  }
  const subscribeSessions = (listener: () => void) => {
    const stopSession = sessions.list.subscribe(listener)
    const stopPending = ctx.uiSession.pendingInteractions.subscribe(listener)
    return () => { stopSession(); stopPending() }
  }
  const DogDebuggerHost = (): JSX.Element | null => {
    const [request, setRequest] = useState(0)
    useEffect(() => {
      const show = () => setRequest(value => value + 1)
      window.addEventListener('openwrite:dog-open', show)
      return () => window.removeEventListener('openwrite:dog-open', show)
    }, [])
    return request === 0 ? null : <DogDebugger key={request} initialOpen hideDock
    readSnapshot={signal => call(DOG_DEBUG_SNAPSHOT_ENDPOINT, {}, signal)}
    readGoalRuntime={(runId, goalId, signal) => call(DOG_RUNTIME_TRACE_ENDPOINT, { runId, goalId }, signal)}
    openSession={openSession}
    getSessionState={getSessionState}
    subscribeSessions={subscribeSessions}
    refreshAgentCatalog={parentSessionId => sessions.refreshSubagents(parentSessionId as SessionId)}
  />
  }
  ctx.effect(installStyles, 'dog-debugger: styles')
  ctx.slots.inject('shell.overlay', () => ctx.slots.register({
    name: 'shell.overlay',
    id: 'openwrite.dog-debugger',
    order: 80,
  }, DogDebuggerHost))
}

function installStyles(): () => void {
  const existing = document.querySelector<HTMLStyleElement>(`style[data-plugin-css="${DOG_DEBUG_STYLE_ID}"]`)
  if (existing !== null) return () => undefined
  const style = document.createElement('style')
  style.dataset.plugin = '@dsh-external/dsh-dog'
  style.dataset.pluginCss = DOG_DEBUG_STYLE_ID
  style.textContent = DOG_DEBUG_CSS
  document.head.appendChild(style)
  return () => style.remove()
}
