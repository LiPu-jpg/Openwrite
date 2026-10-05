import { useEffect, useState } from 'react'
/** Browser half: a frame overlay that visualizes persisted DoG revisions and runs. */

import type { ConnectionHandle } from '@deepseek-ai/dsh-client-connection/client'
import type { Context as ClientContext } from '@deepseek-ai/cordis'
import type {} from '@deepseek-ai/dsh-client-ui-session/client'
import type {} from '@deepseek-ai/dsh-client-ui-workspace/client'
import type { ISessions } from '@deepseek-ai/dsh-api-session-controller/client'
import type {} from '@deepseek-ai/dsh-client-ui-renderer/client'
import type {} from '@deepseek-ai/dsh-client-ui-layout/client'
import {
  DOG_DEBUG_RPC_CHANNEL,
  DOG_DEBUG_SNAPSHOT_ENDPOINT,
  DOG_RUNTIME_TRACE_ENDPOINT,
} from '../debug-contract.ts'
import { DogDebugger } from './DogDebugger.tsx'
import { openInvocationSession, refreshInvocationCatalog } from './sessionNavigation.ts'
import { DOG_DEBUG_CSS, DOG_DEBUG_STYLE_ID } from './styles.ts'
import { debuggerSessionState } from './sessionState.ts'

/** The overlay uses the shared trusted RPC transport and canonical session navigator. */
export const inject = ['slots', 'sessions', 'connection', 'uiSession', 'uiWorkspace']

/** Register the debugger beside other frame-wide overlays without replacing shipped UI. */
export function apply(ctx: ClientContext): void {
  try {
    ctx.effect(() => install(ctx), 'openwrite-dog: client activation')
  } catch (error) {
    console.error('[OpenWrite/DoG] Debugger disabled: client activation failed', error)
  }
}

function* install(ctx: ClientContext): Generator<() => void> {
  const connection = ctx.get('connection') as unknown as ConnectionHandle
  const sessions = ctx.get('sessions') as unknown as ISessions
  const call = async (endpoint: string, payload: unknown, signal?: AbortSignal): Promise<unknown> => {
    const result = await connection.rpc.call(DOG_DEBUG_RPC_CHANNEL, endpoint, payload, signal)
    if (!result.ok) throw new Error(result.error.message)
    return result.value
  }
  const openSession = (sessionId: string, parentSessionId?: string): Promise<boolean> =>
    openInvocationSession(sessions, sessionId, parentSessionId, undefined,
      typeof (ctx.uiWorkspace as unknown as { openSession?: unknown }).openSession === 'function'
        ? ctx.uiWorkspace as unknown as NonNullable<Parameters<typeof openInvocationSession>[4]>
        : undefined)
  const state = debuggerSessionState(sessions.list, ctx.uiSession)
  state.getSnapshot()
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
    getSessionState={state.getSnapshot}
    subscribeSessions={state.subscribe}
    refreshAgentCatalog={parentSessionId => refreshInvocationCatalog(sessions, parentSessionId)}
  />
  }
  yield ctx.effect(installStyles, 'dog-debugger: styles')
  yield ctx.slots.inject('shell.overlay', () => {
    try {
      return ctx.slots.register({
        name: 'shell.overlay',
        id: 'openwrite.dog-debugger',
        order: 80,
      }, DogDebuggerHost)
    } catch (error) {
      console.error('[OpenWrite/DoG] Debugger disabled: overlay registration failed', error)
      return () => {}
    }
  })
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
