import { describe, it, expect, vi } from 'vitest'
import type { SessionListState } from '@deepseek-ai/dsh-api-session-controller/client'
import { isWritingSession, watchWritingScope } from '../../src/client/writing-scope.ts'

/** dsh 0.2 list snapshot: main-view retention marks the displayed session. */
const session = (preset: string, retainedBy: Record<string, number> = { mainView: 1 }) => ({
  ids: ['current'],
  byId: { current: { retainedBy, projectionValues: { agentPreset: preset } } },
}) as unknown as SessionListState

describe('writing presentation scope', () => {
  it('unsubscribes if the first writing-scope mount fails', () => {
    const stop = vi.fn()
    expect(() => watchWritingScope({
      getSnapshot: () => session('openwrite'), subscribe: () => stop,
    }, () => { throw new Error('unavailable slot') })).toThrow('unavailable slot')
    expect(stop).toHaveBeenCalledOnce()
  })
  it('follows preset identity without leaking UI or changing tools on navigation', () => {
    let state = session('standard')
    let change = () => {}
    let mounted = 0
    let unmounted = 0
    const stop = watchWritingScope({ getSnapshot: () => state, subscribe: listener => { change = listener; return () => { change = () => {} } } }, () => { mounted++; return () => { unmounted++ } })
    expect(mounted).toBe(0)
    state = session('openwrite-0-2-0'); change(); change()
    expect(mounted).toBe(1)
    state = session('standard'); change()
    expect(unmounted).toBe(1)
    state = session('openwrite-custom'); change(); stop()
    expect([mounted, unmounted]).toEqual([2, 2])
    expect(isWritingSession({ ids: [], byId: {} } as unknown as SessionListState)).toBe(false)
  })
  it('reads the displayed session from main-view retention, not from every listed session', () => {
    // A listed-but-not-displayed OpenWrite session must not mount this UI.
    expect(isWritingSession(session('openwrite', {}) as SessionListState)).toBe(false)
    // A displayed OpenWrite session mounts it even when other rows exist.
    const mixed = {
      ids: ['other', 'current'],
      byId: {
        other: { retainedBy: { mainView: 0 }, projectionValues: { agentPreset: 'standard' } },
        current: { retainedBy: { mainView: 1 }, projectionValues: { agentPreset: 'openwrite-0-2-11' } },
      },
    } as unknown as SessionListState
    expect(isWritingSession(mixed)).toBe(true)
  })
  it('keeps hosts that still publish the displayed session as `current` working', () => {
    const legacy = {
      ids: [],
      byId: { s: { projectionValues: { agentPreset: 'openwrite' } } },
      current: 's',
    } as unknown as SessionListState
    expect(isWritingSession(legacy)).toBe(true)
  })
})
