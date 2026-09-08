import { afterEach, describe, expect, it, vi } from 'vitest'
import { modelMemoryContextKey, WorkspaceViewMemory } from '../../src/client/model-view-memory.ts'

afterEach(() => { vi.useRealTimers() })

describe('Ephemeral model workspace memory', () => {
  it('requires a bound identity and distinguishes canonical roots', () => {
    expect(modelMemoryContextKey(null)).toBeNull()
    expect(modelMemoryContextKey({ workspaceId: '', root: '/a' })).toBeNull()
    expect(modelMemoryContextKey({ workspaceId: 'same-id', root: '/a' })).not.toBe(modelMemoryContextKey({ workspaceId: 'same-id', root: '/b' }))
  })

  it('evicts old workspace entries at its configured bound and expires inactive drafts', () => {
    vi.useFakeTimers()
    const memory = new WorkspaceViewMemory<string>(2, 60_000)
    memory.write('a', 'first')
    memory.write('b', 'second')
    memory.write('c', 'third')
    expect(memory.read('a')).toBeUndefined()
    expect(memory.read('b')).toBe('second')
    vi.advanceTimersByTime(60_000)
    expect(memory.read('b')).toBeUndefined()
    expect(memory.read('c')).toBeUndefined()
  })

  it('never keeps unbound data and does not let an older expiry erase a replacement', () => {
    vi.useFakeTimers()
    const memory = new WorkspaceViewMemory<string>(2, 60_000)
    memory.write(null, 'unbound')
    expect(memory.read(null)).toBeUndefined()
    memory.write('a', 'old')
    vi.advanceTimersByTime(30_000)
    memory.write('a', 'new')
    vi.advanceTimersByTime(30_000)
    expect(memory.take('a')).toBe('new')
    expect(memory.read('a')).toBeUndefined()
  })
})
