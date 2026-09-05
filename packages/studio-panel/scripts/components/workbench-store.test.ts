/**
 * WorkbenchStore integration layer: Workspace context barrier, two-layer sync
 * (always-on 5s invalidation polling + SSE as the instant layer on top).
 *
 * The pure epoch math is covered by scripts/epochs.test.mjs (node:test); here
 * the real store class runs against a mocked `fetch` and a fake `EventSource`
 * under fake timers, asserting that:
 *   - the 5s poll loop runs regardless of SSE state — with no EventSource,
 *     with a healthy SSE stream, and after an SSE error — and consumes
 *     invalidation revisions, producing the derived epochs (assets → graph);
 *   - an upstream context_epoch increase (background task transitions, which
 *     never touch the bridge-local revision) invalidates `tasks`;
 *   - the SSE channel and the polling channel yield identical epochs for the
 *     same mutation sequence, context_epoch included (SSE≡polling);
 *   - setContext switches clear per-context state immediately, close the old
 *     stream, and drop late responses from the previous generation;
 *   - SSE/polling carry `?workspace=<id>` and only consume invalidate events
 *     naming the bound context's canonical root.
 *
 * Timers are faked; the only awaited wall-clock is microtask flushing.
 */
import { afterEach, describe, expect, it, vi } from 'vitest'
import { nextEpochs, type ResourceKey } from '../../src/client/workbench-epochs.ts'

const WORKSPACE = {
  snapshot: { title: '组件测试项目', current_chapter: 'ch_001', writing_units: 12345, target_units: 80000 },
  documents: { chapters: [{
    path: 'chapters/ch_001.md', title: '第一章', document_id: 'doc-one', occurrence_id: 'occ-one',
    volume: { volume_id: 'arc-one' }, status: 'present', revision: 'revision-one',
    reading_index: 0, writing_units: 2345, updated_at: '2026-09-05T00:00:00Z',
    review: { stale: false, reviewed_at: '2026-09-04T00:00:00Z', source_revision: 'revision-one', current_source_revision: 'revision-one' },
  }, {
    path: 'chapters/ch_002.md', title: '第二章', document_id: 'doc-missing', occurrence_id: 'occ-missing', status: 'missing',
  }] },
  project: { recent: [], writing_targets: { book_words: 90000, chapter_words: 2500 } },
}
const WORKSPACE_B = {
  snapshot: { title: '另一个项目', current_chapter: 'ch_002' },
  documents: { chapters: [{ path: 'chapters/ch_002.md', title: '第二章' }] },
  project: { recent: [] },
}
const TASKS = { data: { counts: {} } }

const CONTEXT_A = { workspaceId: 'ws-a', root: '/root/a' }
const CONTEXT_B = { workspaceId: 'ws-b', root: '/root/b' }

/** Route the global fetch: invalidation polls drain `queue`, then repeat its tail. */
function stubFetch(queue: { revision: number; resource?: string; workspace_root?: string; context_epoch?: number }[]) {
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
  closed = false
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

  close(): void {
    this.closed = true
  }
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
  it('polls invalidation on a 5s cadence when EventSource is unavailable', async () => {
    vi.useFakeTimers()
    vi.stubGlobal('EventSource', undefined)
    const fetchMock = stubFetch([
      { revision: 1 },                          // baseline poll: initializes revision
      { revision: 2, resource: 'assets' },      // first 5s tick: derived bump
    ])
    vi.stubGlobal('fetch', fetchMock)
    const store = await freshStore()

    const stop = store.subscribe(() => undefined)
    store.setContext(CONTEXT_A)
    await flush() // initial refresh + immediate poll
    // Polling carries the workspace query parameter (contract §2.2).
    expect(fetchMock.mock.calls.some(([input]) => String(input).includes('/studio-panel/invalidation.json?workspace=ws-a'))).toBe(true)
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

  it('keeps polling while SSE is healthy and reacts to context_epoch growth', async () => {
    vi.useFakeTimers()
    vi.stubGlobal('EventSource', FakeEventSource)
    const fetchMock = stubFetch([
      { revision: 1, context_epoch: 1 },        // baseline poll
      { revision: 1, context_epoch: 1 },        // first tick: nothing changed
      { revision: 1, context_epoch: 2 },        // second tick: background task transition
    ])
    vi.stubGlobal('fetch', fetchMock)
    const store = await freshStore()

    const stop = store.subscribe(() => undefined)
    store.setContext(CONTEXT_A)
    await flush() // refresh + immediate poll establish both baselines
    const source = FakeEventSource.instances.at(-1)!
    source.emit('ready', { revision: 1, context_epoch: 1 })
    expect(store.getSnapshot().connection).toBe('online')
    const baseline = store.getSnapshot().epochs
    const polls = () => fetchMock.mock.calls.filter(([input]) => String(input).includes('invalidation.json')).length
    const pollsBefore = polls()

    await flush(5_000) // tick: same revision, same epoch → no bumps, but the poll ran
    expect(store.getSnapshot().epochs).toEqual(baseline)
    expect(polls()).toBeGreaterThan(pollsBefore) // SSE health never stops the poll loop

    await flush(5_000) // tick: context_epoch 2 > 1 → background transition → tasks refresh
    expect(store.getSnapshot().epochs.tasks).toBe(baseline.tasks + 1)
    expect(store.getSnapshot().epochs.assets).toBe(baseline.assets)
    stop()
  })

  it('keeps polling after an SSE error and catches up equivalently', async () => {
    vi.useFakeTimers()
    vi.stubGlobal('EventSource', FakeEventSource)
    vi.stubGlobal('fetch', stubFetch([
      { revision: 1 },                          // baseline (first poll)
      { revision: 2, resource: 'assets' },
    ]))
    const store = await freshStore()

    const stop = store.subscribe(() => undefined)
    store.setContext(CONTEXT_A)
    await flush()
    const source = FakeEventSource.instances.at(-1)!
    expect(source.url).toBe('/studio-panel/events?workspace=ws-a')
    // First refresh bumps the tasks epoch once (task signature changes from
    // empty); capture that settled baseline.
    const baseline = store.getSnapshot().epochs
    expect(baseline.assets).toBe(0)

    source.emit('ready', { revision: 1 }) // SSE alive: baseline, no epochs
    expect(store.getSnapshot().connection).toBe('online')
    expect(store.getSnapshot().epochs).toEqual(baseline)

    source.fail() // SSE dies → offline; the poll loop keeps running regardless
    expect(store.getSnapshot().connection).toBe('offline')
    await flush()
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
    store.setContext(CONTEXT_A)
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

  it('context_epoch growth bumps tasks identically on the SSE and polling channels', async () => {
    // SSE channel: ready establishes the baseline, one invalidate carries both
    // a revision bump and a context_epoch bump.
    vi.useFakeTimers()
    vi.stubGlobal('EventSource', FakeEventSource)
    vi.stubGlobal('fetch', stubFetch([{ revision: 1, context_epoch: 1 }]))
    const sseStore = await freshStore()
    const stopSse = sseStore.subscribe(() => undefined)
    sseStore.setContext(CONTEXT_A)
    await flush()
    const source = FakeEventSource.instances.at(-1)!
    source.emit('ready', { revision: 1, context_epoch: 1 })
    const sseBaseline = sseStore.getSnapshot().epochs
    source.emit('invalidate', { revision: 2, resource: 'assets', context_epoch: 2 })
    const sseEpochs = sseStore.getSnapshot().epochs
    stopSse()

    // Polling channel: the same mutation sequence arrives via two polls.
    vi.stubGlobal('EventSource', undefined)
    vi.stubGlobal('fetch', stubFetch([
      { revision: 1, context_epoch: 1 },
      { revision: 2, resource: 'assets', context_epoch: 2 },
    ]))
    const pollStore = await freshStore()
    const stopPoll = pollStore.subscribe(() => undefined)
    pollStore.setContext(CONTEXT_A)
    await flush()
    expect(pollStore.getSnapshot().epochs).toEqual(sseBaseline)
    await flush(5_000)
    expect(pollStore.getSnapshot().epochs).toEqual(sseEpochs)
    expect(sseEpochs).toEqual(nextEpochs('assets' as ResourceKey, nextEpochs('tasks' as ResourceKey, sseBaseline)))
    stopPoll()
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
    store.setContext(CONTEXT_A)
    await flush()
    await flush(5_000)
    await flush(5_000) // duplicate revision tick
    expect(store.getSnapshot().epochs.assets).toBe(1)
    expect(store.getSnapshot().epochs.graph).toBe(1)
    stop()
  })
})

describe('WorkbenchStore context barrier', () => {
  it('clears per-context state immediately on a context switch', async () => {
    vi.useFakeTimers()
    vi.stubGlobal('EventSource', FakeEventSource)
    vi.stubGlobal('fetch', stubFetch([{ revision: 1 }]))
    const store = await freshStore()

    const stop = store.subscribe(() => undefined)
    store.setContext(CONTEXT_A)
    await flush()
    const loaded = store.getSnapshot()
    expect(loaded.projectTitle).toBe('组件测试项目')
    expect(loaded.chapters.length).toBe(1)
    expect(loaded.activeChapterPath).toBe('chapters/ch_001.md')
    expect(loaded.chapters[0]).toMatchObject({
      documentId: 'doc-one', occurrenceId: 'occ-one', volumeId: 'arc-one', status: 'present', revision: 'revision-one', readingIndex: 0,
      writingUnits: 2345, updatedAt: '2026-09-05T00:00:00Z',
      review: { stale: false, sourceRevision: 'revision-one', currentSourceRevision: 'revision-one' },
    })
    expect(loaded.writingProgress).toEqual({ bookUnits: 12345, bookTarget: 80000, chapterTarget: 2500 })
    expect(loaded.contextEpoch).toBe(1)
    const oldSource = FakeEventSource.instances.at(-1)!
    expect(oldSource.closed).toBe(false)

    store.setContext(CONTEXT_B)
    // Synchronous reset: every per-context slice is back at INITIAL.
    const cleared = store.getSnapshot()
    expect(cleared.context).toEqual(CONTEXT_B)
    expect(cleared.contextEpoch).toBe(2)
    expect(cleared.chapters).toEqual([])
    expect(cleared.tasks).toBeNull()
    expect(cleared.workspace).toBeNull()
    expect(cleared.currentChapterId).toBe('')
    expect(cleared.activeChapterPath).toBe('')
    expect(cleared.projectTitle).toBe('')
    expect(cleared.epochs.tasks).toBe(0)
    expect(oldSource.closed).toBe(true)
    // The new context reconnects with its own workspace query.
    await flush()
    expect(FakeEventSource.instances.at(-1)!.url).toBe('/studio-panel/events?workspace=ws-b')
    // The revision baseline restarted: the first event of the new context is
    // treated as its baseline, not as a mutation. (The always-on poll has
    // already initialized it at the same revision the bridge reports.)
    const source = FakeEventSource.instances.at(-1)!
    const epochsBeforeReady = store.getSnapshot().epochs
    source.emit('ready', { revision: 1 })
    expect(store.getSnapshot().epochs).toEqual(epochsBeforeReady)
    stop()
  })

  it('drops late responses from the previous generation', async () => {
    vi.useFakeTimers()
    vi.stubGlobal('EventSource', FakeEventSource)
    // The first /workspace read stays pending until the test resolves it;
    // every later call answers with project B immediately.
    let workspaceCalls = 0
    let releaseFirst: ((response: Response) => void) | null = null
    vi.stubGlobal('fetch', vi.fn((input: unknown) => {
      const url = String(input)
      if (url.includes('/workspace')) {
        workspaceCalls += 1
        if (workspaceCalls === 1) {
          return new Promise<Response>(resolve => { releaseFirst = resolve })
        }
        return Promise.resolve(new Response(JSON.stringify(WORKSPACE_B), { status: 200 }))
      }
      if (url.includes('/tasks')) return Promise.resolve(new Response(JSON.stringify(TASKS), { status: 200 }))
      throw new Error(`unexpected fetch ${url}`)
    }))
    const store = await freshStore()

    const stop = store.subscribe(() => undefined)
    store.setContext(CONTEXT_A)
    await flush() // refresh for A is in flight (workspace read pending)
    expect(store.getSnapshot().projectTitle).toBe('')

    store.setContext(CONTEXT_B) // aborts A's in-flight refresh, refreshes B
    await flush()
    expect(store.getSnapshot().projectTitle).toBe('另一个项目')
    expect(store.getSnapshot().activeChapterPath).toBe('chapters/ch_002.md')

    // A's late answer must not overwrite B's state.
    releaseFirst!(new Response(JSON.stringify(WORKSPACE), { status: 200 }))
    await flush()
    expect(store.getSnapshot().projectTitle).toBe('另一个项目')
    expect(store.getSnapshot().activeChapterPath).toBe('chapters/ch_002.md')
    stop()
  })

  it('only consumes invalidate events naming the bound root', async () => {
    vi.useFakeTimers()
    vi.stubGlobal('EventSource', FakeEventSource)
    vi.stubGlobal('fetch', stubFetch([{ revision: 1 }]))
    const store = await freshStore()

    const stop = store.subscribe(() => undefined)
    store.setContext(CONTEXT_A)
    await flush()
    const baseline = store.getSnapshot().epochs
    const source = FakeEventSource.instances.at(-1)!
    source.emit('ready', { revision: 1, workspace_root: '/root/a' })

    // Foreign roots never advance the revision baseline nor bump epochs.
    source.emit('invalidate', { revision: 9, resource: 'assets', workspace_root: '/root/other' })
    expect(store.getSnapshot().epochs).toEqual(baseline)

    // A matching root consumes normally.
    source.emit('invalidate', { revision: 2, resource: 'assets', workspace_root: '/root/a' })
    expect(store.getSnapshot().epochs).toEqual(nextEpochs('assets' as ResourceKey, baseline))
    stop()
  })

  it('setContext(null) stops the channels and clears the panel', async () => {
    vi.useFakeTimers()
    vi.stubGlobal('EventSource', FakeEventSource)
    vi.stubGlobal('fetch', stubFetch([{ revision: 1 }]))
    const store = await freshStore()

    const stop = store.subscribe(() => undefined)
    store.setContext(CONTEXT_A)
    await flush()
    expect(store.getSnapshot().chapters.length).toBe(1)
    const source = FakeEventSource.instances.at(-1)!

    store.setContext(null)
    const snapshot = store.getSnapshot()
    expect(snapshot.context).toBeNull()
    expect(snapshot.chapters).toEqual([])
    expect(snapshot.connection).toBe('offline')
    expect(source.closed).toBe(true)
    stop()
  })
})
