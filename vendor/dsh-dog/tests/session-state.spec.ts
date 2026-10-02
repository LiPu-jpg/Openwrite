import { describe, expect, it, vi } from 'vitest'
import type { SessionListState } from '@deepseek-ai/dsh-api-session-controller/client'
import { debuggerSessionState } from '../src/client/sessionState.ts'
import { apply } from '../src/client/index.tsx'

function source<T>(initial: T) {
  let value = initial
  const listeners = new Set<() => void>()
  return {
    getSnapshot: () => value,
    subscribe(listener: () => void) { listeners.add(listener); return () => { listeners.delete(listener) } },
    publish(next: T) { value = next; for (const listener of listeners) listener() },
    listeners,
  }
}

describe('debugger session state across DSH releases', () => {
  const list = () => source({ current: null, ids: [], byId: {} } as unknown as SessionListState)

  it('keeps the 0.1 pending-interaction source and stable snapshot identity', () => {
    const sessions = list()
    const pendingInteractions = source<ReadonlyMap<string, unknown>>(new Map([['waiting', { kind: 'approval' }]]))
    const state = debuggerSessionState(sessions, { pendingInteractions })
    expect(state.getSnapshot().pendingInteractions).toBe(pendingInteractions.getSnapshot())
    expect(state.getSnapshot()).toBe(state.getSnapshot())
    const listener = vi.fn()
    const stop = state.subscribe(listener)
    pendingInteractions.publish(new Map())
    expect(listener).toHaveBeenCalledOnce()
    expect(state.getSnapshot().pendingInteractions.size).toBe(0)
    stop()
    expect(sessions.listeners.size + pendingInteractions.listeners.size).toBe(0)
  })

  it('uses 0.2 sessionStatus without treating running/completed sessions as waiting for input', () => {
    const sessions = list()
    const interaction = { kind: 'approval' }
    const sessionStatus = source<ReadonlyMap<string, { pendingInteraction?: unknown }>>(new Map([
      ['running', {}], ['waiting', { pendingInteraction: interaction }],
    ]))
    const state = debuggerSessionState(sessions, { sessionStatus })
    const initial = state.getSnapshot()
    expect([...initial.pendingInteractions]).toEqual([['waiting', interaction]])
    expect(state.getSnapshot()).toBe(initial)
    const listener = vi.fn()
    const stop = state.subscribe(listener)
    sessionStatus.publish(new Map([['waiting', {}]]))
    expect(listener).toHaveBeenCalledOnce()
    expect(state.getSnapshot()).not.toBe(initial)
    expect(state.getSnapshot().pendingInteractions.size).toBe(0)
    stop()
    expect(sessions.listeners.size + sessionStatus.listeners.size).toBe(0)
  })

  it('cleans up the list subscription if status subscription setup throws', () => {
    const sessions = list()
    const state = debuggerSessionState(sessions, { sessionStatus: {
      getSnapshot: () => new Map(), subscribe() { throw new Error('status unavailable') },
    } })
    expect(() => state.subscribe(() => {})).toThrow('status unavailable')
    expect(sessions.listeners.size).toBe(0)
  })

  it('reports an unsupported session UI rather than dereferencing an absent source', () => {
    expect(() => debuggerSessionState(list(), {})).toThrow('neither sessionStatus nor pendingInteractions')
  })

  it('contains an activation failure so the host client fiber can still activate', () => {
    const report = vi.spyOn(console, 'error').mockImplementation(() => {})
    try {
      expect(() => apply({
        effect(execute: () => Iterable<() => void>) { for (const _dispose of execute()) { /* setup */ } },
        get: (key: string) => key === 'sessions' ? { list: list() } : {},
        uiSession: {},
      } as never)).not.toThrow()
      expect(report).toHaveBeenCalledWith(
        expect.stringContaining('client activation failed'), expect.any(Error),
      )
    } finally { report.mockRestore() }
  })
})
