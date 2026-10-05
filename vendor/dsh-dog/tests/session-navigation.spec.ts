import { describe, expect, it, vi } from 'vitest'
import { openInvocationSession } from '../src/client/sessionNavigation.ts'

type Navigator = Parameters<typeof openInvocationSession>[0]
type Select = (sessionId: string) => void

interface FixtureOptions {
  readonly ids: string[]
  readonly current?: string
  readonly onOpen?: (sessionId: string, select: Select) => void
  readonly onOpenSubagent?: (address: unknown, select: Select) => void
  readonly onRefresh?: (parentSessionId: string) => void | Promise<void>
}

function sessionFixture(options: FixtureOptions): {
  readonly sessions: Navigator
  readonly select: Select
  readonly setAddress: (sessionId: string, address: unknown) => void
  readonly open: ReturnType<typeof vi.fn>
  readonly openSubagent: ReturnType<typeof vi.fn>
  readonly refreshSubagents: ReturnType<typeof vi.fn>
} {
  let snapshot = { ids: options.ids, current: options.current }
  const listeners = new Set<() => void>()
  const addresses = new Map<string, unknown>()
  const select: Select = (sessionId) => {
    snapshot = { ...snapshot, current: sessionId }
    for (const listener of listeners) listener()
  }
  const open = vi.fn((sessionId: string) => options.onOpen?.(sessionId, select))
  const openSubagent = vi.fn((address: unknown) => options.onOpenSubagent?.(address, select))
  const refreshSubagents = vi.fn(async (parentSessionId: string) => options.onRefresh?.(parentSessionId))
  const sessions = {
    list: {
      getSnapshot: () => snapshot,
      subscribe: (listener: () => void) => {
        listeners.add(listener)
        return () => listeners.delete(listener)
      },
    },
    open,
    openSubagent,
    subagentAddress: (sessionId: string) => addresses.get(sessionId),
    refreshSubagents,
  } as unknown as Navigator
  return {
    sessions,
    select,
    setAddress: (sessionId, address) => addresses.set(sessionId, address),
    open,
    openSubagent,
    refreshSubagents,
  }
}

describe('invocation session navigation', () => {
  it('does not report success until an ordinary session becomes current', async () => {
    let release: (() => void) | undefined
    const fixture = sessionFixture({
      ids: ['session-old', 'session-target'],
      current: 'session-old',
      onOpen: (sessionId, select) => { release = () => select(sessionId) },
    })

    let settled = false
    const opening = openInvocationSession(fixture.sessions, 'session-target', undefined, 100)
      .finally(() => { settled = true })
    await Promise.resolve()
    expect(fixture.open).toHaveBeenCalledWith('session-target')
    expect(settled).toBe(false)

    release?.()
    await expect(opening).resolves.toBe(true)
    expect(settled).toBe(true)
  })

  it('refreshes the recorded parent before opening an addressed subagent', async () => {
    const address = { parentSessionId: 'session-parent', childSessionId: 'session-child', mode: 'task' }
    let fixture: ReturnType<typeof sessionFixture>
    fixture = sessionFixture({
      ids: ['session-parent'],
      current: 'session-parent',
      onRefresh: () => fixture.setAddress('session-child', address),
      onOpenSubagent: (candidate, select) => select((candidate as typeof address).childSessionId),
    })

    await expect(openInvocationSession(
      fixture.sessions,
      'session-child',
      'session-parent',
      100,
    )).resolves.toBe(true)
    expect(fixture.refreshSubagents).toHaveBeenCalledWith('session-parent')
    expect(fixture.openSubagent).toHaveBeenCalledWith(address)
  })

  it('returns false when the persisted session is no longer addressable', async () => {
    const fixture = sessionFixture({ ids: ['session-other'], current: 'session-other' })

    await expect(openInvocationSession(
      fixture.sessions,
      'session-missing',
      'session-parent',
      100,
    )).resolves.toBe(false)
    expect(fixture.open).not.toHaveBeenCalled()
    expect(fixture.openSubagent).not.toHaveBeenCalled()
  })

  it('fails instead of closing the debugger when DSH never stages the target', async () => {
    const fixture = sessionFixture({
      ids: ['session-old', 'session-target'],
      current: 'session-old',
      onOpen: () => undefined,
    })

    await expect(openInvocationSession(
      fixture.sessions,
      'session-target',
      undefined,
      10,
    )).rejects.toThrow('did not select session session-target')
  })
})

describe('0.2 invocation navigation', () => {
  it('confirms main-view retention without current or legacy navigation methods', async () => {
    let snapshot = { ids: ['target'], byId: { target: { retainedBy: {} } } }
    const listeners = new Set<() => void>()
    const sessions = { list: { getSnapshot: () => snapshot, subscribe: (f: () => void) => { listeners.add(f); return () => listeners.delete(f) } } } as unknown as Navigator
    const openSession = vi.fn(() => {
      snapshot = { ids: ['target'], byId: { target: { retainedBy: { mainView: 1 } } } }
      for (const listener of listeners) listener()
    })
    await expect(openInvocationSession(sessions, 'target', undefined, 100, { openSession })).resolves.toBe(true)
    expect(openSession).toHaveBeenCalledWith('target')
  })

  it('uses the persisted continuable parent address when the old catalog API is absent', async () => {
    let snapshot = { ids: ['parent'], byId: {} as Record<string, { retainedBy: { mainView: number } }> }
    const listeners = new Set<() => void>()
    const sessions = { list: { getSnapshot: () => snapshot, subscribe: (f: () => void) => { listeners.add(f); return () => listeners.delete(f) } } } as unknown as Navigator
    const openSession = vi.fn(() => {
      snapshot = { ...snapshot, byId: { child: { retainedBy: { mainView: 1 } } } }
      for (const listener of listeners) listener()
    })
    await expect(openInvocationSession(sessions, 'child', 'parent', 100, { openSession })).resolves.toBe(true)
    expect(openSession).toHaveBeenCalledWith({ parentSessionId: 'parent', childSessionId: 'child', mode: 'continuable' })
    await expect(openInvocationSession(sessions, 'unknown', undefined, 100, { openSession })).resolves.toBe(false)
  })

  it('does not accept a successful navigation call without selection', async () => {
    const sessions = { list: { getSnapshot: () => ({ ids: ['target'], byId: {} }), subscribe: () => () => {} } } as unknown as Navigator
    await expect(openInvocationSession(sessions, 'target', undefined, 10, { openSession: vi.fn() })).rejects.toThrow('did not select')
  })
})
