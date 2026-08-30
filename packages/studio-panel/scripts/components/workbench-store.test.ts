/**
 * WorkbenchStore integration layer: SSE primary channel, 5s polling fallback.
 *
 * The pure epoch math is covered by scripts/epochs.test.mjs (node:test); here
 * the real store class runs against a mocked `fetch` and a fake `EventSource`
 * under fake timers, asserting that:
 *   - with no EventSource, the 5s polling fallback consumes invalidation
 *     revisions and produces the derived epochs (assets → graph);
 *   - an SSE error drops to the same polling fallback;
 *   - the SSE channel and the polling channel yield identical epochs for the
 *     same mutation sequence (integration-level SSE≡polling).
 *
 * Timers are faked; the only awaited wall-clock is microtask flushing.
 */
import { afterEach, describe, expect, it, vi } from 'vitest'
import { nextEpochs, type ResourceKey } from '../../src/client/workbench-epochs.ts'

const WORKSPACE = {
  snapshot: { title: '组件测试项目', current_chapter: 'ch_001' },
  documents: { chapters: [{ path: 'chapters/ch_001.md', title: '第一章' }] },
  project: { recent: [] },
}
const TASKS = { data: { counts: {} } }

/** Route the global fetch: invalidation polls drain `queue`, then repeat its tail. */
function stubFetch(queue: { revision: number; resource?: string }[]) {
  let polls = 0
  return vi.fn(async (input: unknown) => {
    const url = String(input)
    if (url.includes('/studio-panel/invalidation.json')) {
      const mutation = queue[Math.min(polls, queue.length - 1)]!
      polls += 1
      return new Response(JSON.stringify(mutation), { status: 200 })
    }
    if (url.includes('/workspace')) return new Response(JSON.stringify(WORKSPACE), { status: 200 })
    if (url.includes('/tasks')) return new Response(JSON.stringify(TASKS), { status: 200 })
    throw new Error(`unexpected fetch ${url}`)
  })
}

class FakeEventSource {
  static instances: FakeEventSource[] = []
  onerror: (() => void) | null = null
  private readonly listeners = new Map<string, ((event: { data: string }) => void)[]>()

  constructor(readonly url: string) {
    FakeEventSource.instances.push(this)
  }

  addEventListener(type: string, listener: (event: { data: string }) => void): void {
    this.listeners.set(type, [...this.listeners.get(type) ?? [], listener])
  }

  emit(type: string, data: unknown): void {
    for (const listener of this.listeners.get(type) ?? []) listener({ data: JSON.stringify(data) })
  }

  fail(): void {
    this.onerror?.()
  }

  close(): void {}
}

async function freshStore() {
  vi.resetModules()
  const module = await import('../../src/client/WorkbenchStore.ts')
  return module.workbenchStore
}

async function flush(ms = 0): Promise<void> {
  await vi.advanceTimersByTimeAsync(ms)
}

afterEach(() => {
  vi.useRealTimers()
})

describe('WorkbenchStore SSE/polling integration', () => {
  it('falls back to 5s polling when EventSource is unavailable', async () => {
    vi.useFakeTimers()
    vi.stubGlobal('EventSource', undefined)
    vi.stubGlobal('fetch', stubFetch([
      { revision: 1 },                          // baseline poll: initializes revision
      { revision: 2, resource: 'assets' },      // first 5s tick: derived bump
    ]))
    const store = await freshStore()

    const stop = store.subscribe(() => undefined)
    await flush() // initial refresh + immediate fallback poll
    // The first refresh changes the task signature from empty, so the tasks
    // epoch bumps once on load; capture whatever baseline the store settled on.
    const baseline = store.getSnapshot().epochs
    expect(baseline.assets).toBe(0)

    await flush(5_000) // first interval tick consumes revision 2
    const epochs = store.getSnapshot().epochs
    expect(epochs).toEqual(nextEpochs('assets' as ResourceKey, baseline))
    expect(epochs.graph).toBe(baseline.graph + 1) // derived invalidation through the store
    expect(store.getSnapshot().connection).toBe('online')
    stop()
  })

  it('drops to polling after an SSE error and catches up equivalently', async () => {
    vi.useFakeTimers()
    vi.stubGlobal('EventSource', FakeEventSource)
    vi.stubGlobal('fetch', stubFetch([
      { revision: 1 },                          // baseline (first fallback poll)
      { revision: 2, resource: 'assets' },
    ]))
    const store = await freshStore()

    const stop = store.subscribe(() => undefined)
    await flush()
    const source = FakeEventSource.instances.at(-1)!
    expect(source.url).toBe('/studio-panel/events')
    // First refresh bumps the tasks epoch once (task signature changes from
    // empty); capture that settled baseline.
    const baseline = store.getSnapshot().epochs
    expect(baseline.assets).toBe(0)

    source.emit('ready', { revision: 1 }) // SSE alive: baseline, no epochs
    expect(store.getSnapshot().connection).toBe('online')
    expect(store.getSnapshot().epochs).toEqual(baseline)

    source.fail() // SSE dies → offline + fallback polling
    await flush() // immediate fallback poll: revision 1 again, still baseline
    expect(store.getSnapshot().epochs).toEqual(baseline)

    await flush(5_000) // interval poll consumes revision 2
    const epochs = store.getSnapshot().epochs
    expect(epochs).toEqual(nextEpochs('assets' as ResourceKey, baseline))
    stop()
  })

  it('SSE channel produces the same epochs as the polling channel', async () => {
    vi.useFakeTimers()
    vi.stubGlobal('EventSource', FakeEventSource)
    vi.stubGlobal('fetch', stubFetch([{ revision: 1 }]))
    const store = await freshStore()

    const stop = store.subscribe(() => undefined)
    await flush()
    const baseline = store.getSnapshot().epochs // tasks epoch bumped once by first refresh
    const source = FakeEventSource.instances.at(-1)!
    source.emit('ready', { revision: 1 })
    source.emit('invalidate', { revision: 2, resource: 'assets' })
    const sseEpochs = store.getSnapshot().epochs
    stop()

    // Same mutation through the pure channel both sides share.
    expect(sseEpochs).toEqual(nextEpochs('assets' as ResourceKey, baseline))
  })

  it('polling deduplicates already-seen revisions', async () => {
    vi.useFakeTimers()
    vi.stubGlobal('EventSource', undefined)
    vi.stubGlobal('fetch', stubFetch([
      { revision: 1 },
      { revision: 2, resource: 'assets' },
      { revision: 2, resource: 'assets' }, // duplicate delivery must not re-bump
    ]))
    const store = await freshStore()

    const stop = store.subscribe(() => undefined)
    await flush()
    await flush(5_000)
    await flush(5_000) // duplicate revision tick
    expect(store.getSnapshot().epochs.assets).toBe(1)
    expect(store.getSnapshot().epochs.graph).toBe(1)
    stop()
  })
})
