import { describe, it, expect } from 'vitest'
import type { SessionListState } from '@deepseek-ai/dsh-api-session-controller/client'
import { isWritingSession, watchWritingScope } from '../../src/client/writing-scope.ts'

const session = (preset: string) => ({ current: 'current', byId: { current: { projectionValues: { agentPreset: preset } } } }) as unknown as SessionListState
describe('writing presentation scope', () => {
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
    expect(isWritingSession({ current: null, byId: {} } as unknown as SessionListState)).toBe(false)
  })
})
