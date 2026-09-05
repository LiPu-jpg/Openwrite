import { useSyncExternalStore } from 'react'
import { fetchStudioApi, setStudioContext, StudioApiError } from './api.ts'
import { storageKey } from './storage.ts'
import { nextEpochs, terminalTransitionResources, triggersRefresh } from './workbench-epochs.ts'

export type ConnectionState = 'connecting' | 'online' | 'offline'
export type EditorStatus = 'idle' | 'loading' | 'saved' | 'dirty' | 'saving' | 'conflict' | 'offline'
export type ResourceKey = 'workspace' | 'manuscript' | 'outline' | 'assets' | 'tasks' | 'benchmark' | 'models' | 'dag' | 'graph' | 'research' | 'revisions'

/**
 * The panel's Workspace identity (docs/WORKSPACE_CONTEXT_CONTRACT.md §9):
 * `root` is the dsh Workspace's canonical absolute path — the only identity
 * that matters for invalidate filtering; `workspaceId` is the UI/wire
 * reference carried on every proxied request.
 */
export interface WorkbenchContext {
  workspaceId: string
  root: string
  sessionId?: string | undefined
}

export interface ReviewSummary {
  score: number | null
  passed: boolean | null
  issues: number
  issueDetails: readonly unknown[]
  stale: boolean
  reviewedAt: string
  sourceRevision: string
  currentSourceRevision: string
}

export interface ChapterSummary {
  id: string
  /** Stable server identity when supplied. An empty value means path is the only available identity. */
  documentId: string
  /** Stable position in canonical reading order. Repeated documents receive distinct occurrences. */
  occurrenceId: string
  volumeId: string
  status: string
  path: string
  title: string
  subtitle: string
  revision: string
  readingIndex: number | null
  writingUnits: number | null
  updatedAt: string
  review: ReviewSummary
}

export interface WritingProgress {
  bookUnits: number
  bookTarget: number
  chapterTarget: number
}

export interface WorkbenchSnapshot {
  connection: ConnectionState
  /** Bound Workspace context; null = no Workspace bound, panel issues no proxied requests. */
  context: WorkbenchContext | null
  /** Local generation counter, bumped on every context switch. */
  contextEpoch: number
  /** Contract error code blocking this context (e.g. WORKSPACE_NOT_INITIALIZED), null when healthy. */
  workspaceError: string | null
  projectTitle: string
  currentChapterId: string
  activeChapterPath: string
  chapters: readonly ChapterSummary[]
  writingProgress: WritingProgress
  workspace: unknown
  tasks: unknown
  activeTasks: number
  editorStatus: EditorStatus
  editorMessage: string
  epochs: Readonly<Record<ResourceKey, number>>
  lastUpdatedAt: number
}

const EMPTY_EPOCHS: Readonly<Record<ResourceKey, number>> = {
  workspace: 0,
  manuscript: 0,
  outline: 0,
  assets: 0,
  tasks: 0,
  benchmark: 0,
  models: 0,
  dag: 0,
  graph: 0,
  research: 0,
  revisions: 0,
}

const INITIAL: WorkbenchSnapshot = {
  connection: 'connecting',
  context: null,
  contextEpoch: 0,
  workspaceError: null,
  projectTitle: '',
  currentChapterId: '',
  activeChapterPath: '',
  chapters: [],
  writingProgress: { bookUnits: 0, bookTarget: 0, chapterTarget: 0 },
  workspace: null,
  tasks: null,
  activeTasks: 0,
  editorStatus: 'idle',
  editorMessage: '',
  epochs: EMPTY_EPOCHS,
  lastUpdatedAt: 0,
}

const ACTIVE_CHAPTER_KEY = 'dsh-novel.activeChapterPath'

type Listener = () => void

function record(value: unknown): Record<string, unknown> {
  return value !== null && typeof value === 'object' ? value as Record<string, unknown> : {}
}

function text(value: unknown): string {
  return typeof value === 'string' ? value : ''
}

function chapterId(path: string): string {
  return /(?:^|\/)(ch_[A-Za-z0-9_-]+)\.md$/.exec(path)?.[1] ?? ''
}

function finiteNumber(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null
}

function parseWorkspace(value: unknown): Pick<WorkbenchSnapshot, 'projectTitle' | 'currentChapterId' | 'chapters' | 'writingProgress'> {
  const root = record(value)
  const snapshot = record(root['snapshot'])
  const documents = record(root['documents'])
  const project = record(root['project'])
  const recent = Array.isArray(project['recent']) ? project['recent'] : []
  const chapters = (Array.isArray(documents['chapters']) ? documents['chapters'] : []).map((item): ChapterSummary => {
    const chapter = record(item)
    const review = record(chapter['review'])
    const path = text(chapter['path'])
    return {
      id: chapterId(path),
      documentId: text(chapter['document_id']),
      occurrenceId: text(chapter['occurrence_id']),
      volumeId: text(record(chapter['volume'])['volume_id']) || text(chapter['volume_id']),
      status: text(chapter['status']),
      path,
      title: text(chapter['title']) || chapterId(path),
      subtitle: text(chapter['subtitle']),
      revision: text(chapter['revision']),
      readingIndex: finiteNumber(chapter['reading_index']),
      writingUnits: finiteNumber(chapter['writing_units']),
      updatedAt: text(chapter['updated_at']),
      review: {
        score: typeof review['score'] === 'number' ? review['score'] : null,
        passed: typeof review['passed'] === 'boolean' ? review['passed'] : null,
        issues: typeof review['issues'] === 'number' ? review['issues'] : 0,
        issueDetails: Array.isArray(review['issue_details']) ? review['issue_details'] : [],
        stale: review['stale'] === true,
        reviewedAt: text(review['reviewed_at']),
        sourceRevision: text(review['source_revision']),
        currentSourceRevision: text(review['current_source_revision']),
      },
    }
  }).filter(chapter => chapter.path !== '' && chapter.status !== 'missing')
  const targets = record(project['writing_targets'])
  return {
    projectTitle: text(snapshot['title']) || text(record(recent[0])['title']),
    currentChapterId: text(snapshot['current_chapter']),
    chapters,
    writingProgress: {
      bookUnits: finiteNumber(snapshot['writing_units']) ?? 0,
      bookTarget: finiteNumber(snapshot['target_units']) ?? finiteNumber(targets['book_words']) ?? 0,
      chapterTarget: finiteNumber(targets['chapter_words']) ?? 0,
    },
  }
}

function parseActiveTasks(value: unknown): number {
  const counts = record(record(value)['data'])['counts'] ?? record(value)['counts']
  const map = record(counts)
  return ['pending', 'running', 'awaiting_confirmation'].reduce((sum, key) =>
    sum + (typeof map[key] === 'number' ? map[key] : 0), 0)
}

function sameContext(a: WorkbenchContext | null, b: WorkbenchContext | null): boolean {
  if (a === null || b === null) return a === b
  return a.workspaceId === b.workspaceId && a.root === b.root && a.sessionId === b.sessionId
}

class NovelWorkbenchStore {
  private snapshot: WorkbenchSnapshot = INITIAL
  private readonly listeners = new Set<Listener>()
  private pollTimer: number | null = null
  private eventSource: EventSource | null = null
  private refreshPromise: Promise<void> | null = null
  private refreshController: AbortController | null = null
  private taskSignature = ''
  /** Raw tasks payload of the last committed refresh (terminal-diff baseline). */
  private tasksPayload: unknown = null
  private revision = 0
  private revisionInitialized = false
  /** Last seen upstream context_epoch (background-transition hint channel). */
  private contextEpoch = 0
  private contextEpochInitialized = false
  private pollTicks = 0
  /** Context generation: every setContext bump invalidates in-flight work. */
  private generation = 0

  readonly subscribe = (listener: Listener): (() => void) => {
    this.listeners.add(listener)
    if (this.listeners.size === 1) this.start()
    return () => {
      this.listeners.delete(listener)
      if (this.listeners.size === 0) this.stop()
    }
  }

  readonly getSnapshot = (): WorkbenchSnapshot => this.snapshot

  /**
   * The context barrier (contract §9). A changed context: bumps the
   * generation (late responses from the old generation are dropped on
   * commit), resets every per-context slice back to INITIAL, aborts the
   * in-flight refresh, closes the old SSE stream and poll timer, zeroes the
   * revision/task baselines, rebinds the API layer's context headers, then
   * reconnects and refreshes under the new Workspace. An identical context
   * is a no-op; null stops everything and clears the panel.
   */
  setContext(next: WorkbenchContext | null): void {
    if (sameContext(this.snapshot.context, next)) return
    this.generation += 1
    this.refreshController?.abort()
    this.refreshController = null
    this.refreshPromise = null
    this.eventSource?.close()
    this.eventSource = null
    if (this.pollTimer !== null) window.clearInterval(this.pollTimer)
    this.pollTimer = null
    this.revision = 0
    this.revisionInitialized = false
    this.contextEpoch = 0
    this.contextEpochInitialized = false
    this.taskSignature = ''
    this.tasksPayload = null
    this.pollTicks = 0
    setStudioContext(next === null ? null : { workspaceId: next.workspaceId, sessionId: next.sessionId })
    this.patch({
      ...INITIAL,
      context: next,
      contextEpoch: this.generation,
      connection: next === null ? 'offline' : 'connecting',
    })
    if (next !== null && this.listeners.size > 0) this.start()
  }

  setActiveChapter(path: string): void {
    if (path === this.snapshot.activeChapterPath) return
    this.patch({ activeChapterPath: path, editorStatus: 'loading', editorMessage: '' })
    const context = this.snapshot.context
    if (context !== null) {
      try { window.localStorage.setItem(storageKey(ACTIVE_CHAPTER_KEY, context.workspaceId), path) } catch { /* unavailable storage */ }
    }
  }

  setEditorStatus(status: EditorStatus, message = ''): void {
    if (status === this.snapshot.editorStatus && message === this.snapshot.editorMessage) return
    this.patch({ editorStatus: status, editorMessage: message })
  }

  invalidate(resource: ResourceKey): void {
    // Derived invalidation lives in workbench-epochs.ts (pure + unit-tested).
    this.patch({ epochs: nextEpochs(resource, this.snapshot.epochs) })
    if (triggersRefresh(resource)) {
      void this.refresh()
    }
  }

  async refresh(): Promise<void> {
    if (this.snapshot.context === null) return
    if (this.refreshPromise !== null) return this.refreshPromise
    this.refreshPromise = this.refreshNow().finally(() => { this.refreshPromise = null })
    return this.refreshPromise
  }

  /**
   * Two-layer sync. Layer one is the always-on 5s invalidation poll: it is
   * the only channel that observes background task transitions, because the
   * bridge merges the upstream context_epoch into invalidation.json and task
   * transitions bump it without any bridge-local write. Layer two is SSE,
   * the instant channel for proxied writes and agent mutations; its state
   * never gates the poll loop.
   */
  private start(): void {
    const context = this.snapshot.context
    if (context === null) return
    const generation = this.generation
    this.patch({ connection: 'connecting' })
    void this.refresh()
    this.startPolling()
    if (typeof EventSource === 'undefined') return
    const source = new EventSource(`/studio-panel/events?workspace=${encodeURIComponent(context.workspaceId)}`)
    this.eventSource = source
    source.addEventListener('open', () => {
      if (generation !== this.generation) return
      this.patch({ connection: 'online' })
    })
    source.addEventListener('ready', event => {
      if (generation !== this.generation) return
      this.consumeMutation((event as MessageEvent<string>).data)
      this.patch({ connection: 'online' })
    })
    source.addEventListener('invalidate', event => {
      if (generation !== this.generation) return
      this.consumeMutation((event as MessageEvent<string>).data)
      this.patch({ connection: 'online' })
    })
    source.onerror = () => {
      if (generation !== this.generation) return
      this.patch({ connection: 'offline' })
      // The poll loop is already running; this only matters when an early
      // error raced the start() call that launched it.
      this.startPolling()
    }
  }

  private startPolling(): void {
    if (this.pollTimer !== null) return
    const context = this.snapshot.context
    if (context === null) return
    const generation = this.generation
    const workspaceId = context.workspaceId
    void this.pollInvalidation(generation, workspaceId)
    this.pollTimer = window.setInterval(() => {
      if (generation !== this.generation) return
      if (!document.hidden) void this.pollInvalidation(generation, workspaceId)
    }, 5_000)
  }

  private consumeMutation(value: unknown): void {
    let mutation = record(value)
    if (typeof value === 'string') {
      try { mutation = record(JSON.parse(value)) } catch { return }
    }
    // Invalidate events are per-root (contract §8): drop anything that does
    // not name the bound context's canonical root.
    const root = mutation['workspace_root']
    const context = this.snapshot.context
    if (typeof root === 'string' && root !== '' && (context === null || root !== context.root)) return
    // Both channels (SSE events and invalidation polls) funnel through this
    // one method, which keeps SSE≡polling by construction.
    const contextEpoch = typeof mutation['context_epoch'] === 'number' ? mutation['context_epoch'] : null
    if (contextEpoch !== null) {
      // Upstream task transitions bump the per-root context epoch without any
      // bridge-local revision: growth beyond the last seen value means the
      // task list must be refreshed. First sight is the baseline, not a change.
      const initialEpoch = !this.contextEpochInitialized
      this.contextEpochInitialized = true
      if (contextEpoch > this.contextEpoch) {
        this.contextEpoch = contextEpoch
        if (!initialEpoch) this.invalidate('tasks')
      }
    }
    const revision = typeof mutation['revision'] === 'number' ? mutation['revision'] : 0
    const resource = mutation['resource']
    const initial = !this.revisionInitialized
    this.revisionInitialized = true
    if (revision > this.revision) {
      this.revision = revision
      if (!initial) this.invalidate(typeof resource === 'string' && resource in EMPTY_EPOCHS ? resource as ResourceKey : 'workspace')
    }
  }

  private stop(): void {
    if (this.pollTimer !== null) window.clearInterval(this.pollTimer)
    this.pollTimer = null
    this.eventSource?.close()
    this.eventSource = null
    this.refreshController?.abort()
    this.refreshController = null
  }

  private async pollInvalidation(generation: number, workspaceId: string): Promise<void> {
    try {
      const response = await fetch(`/studio-panel/invalidation.json?workspace=${encodeURIComponent(workspaceId)}`, { headers: { accept: 'application/json' } })
      if (!response.ok) throw new Error(`HTTP ${String(response.status)}`)
      const payload: unknown = await response.json()
      if (generation !== this.generation) return
      this.consumeMutation(payload)
      this.pollTicks += 1
      if (this.pollTicks % 4 === 0) void this.refresh()
      this.patch({ connection: 'online' })
    } catch {
      if (generation !== this.generation) return
      this.patch({ connection: 'offline' })
    }
  }

  private async refreshNow(): Promise<void> {
    const context = this.snapshot.context
    if (context === null) return
    const generation = this.generation
    const controller = new AbortController()
    this.refreshController = controller
    try {
      const [workspace, tasks] = await Promise.all([
        fetchStudioApi('/workspace', controller.signal),
        fetchStudioApi('/tasks?limit=100', controller.signal),
      ])
      // Generation barrier: a context switch during the flight makes this
      // answer stale — drop it without touching the snapshot.
      if (generation !== this.generation || this.snapshot.context?.workspaceId !== context.workspaceId) return
      const parsed = parseWorkspace(workspace)
      const nextTasksPayload = record(tasks)['data'] ?? tasks
      const taskSignature = JSON.stringify(nextTasksPayload)
      const tasksChanged = taskSignature !== this.taskSignature
      // Typed terminal diff: tasks that newly reached a terminal status also
      // remount the view consuming their artifact (research/benchmark/dag) —
      // precisely, without a whole-workbench refresh.
      const terminalResources = terminalTransitionResources(this.tasksPayload, nextTasksPayload)
      this.taskSignature = taskSignature
      this.tasksPayload = nextTasksPayload
      let epochs = this.snapshot.epochs
      if (tasksChanged) epochs = { ...epochs, tasks: epochs.tasks + 1 }
      for (const resource of terminalResources) epochs = nextEpochs(resource, epochs)
      let activeChapterPath = this.snapshot.activeChapterPath
      if (activeChapterPath === '') {
        let stored = ''
        try { stored = window.localStorage.getItem(storageKey(ACTIVE_CHAPTER_KEY, context.workspaceId)) ?? '' } catch { /* unavailable storage */ }
        const candidate = parsed.chapters.find(chapter => chapter.path === stored)
          ?? parsed.chapters.find(chapter => chapter.id === parsed.currentChapterId)
          ?? parsed.chapters.at(-1)
        activeChapterPath = candidate?.path ?? ''
      } else if (!parsed.chapters.some(chapter => chapter.path === activeChapterPath)) {
        activeChapterPath = parsed.chapters.find(chapter => chapter.id === parsed.currentChapterId)?.path
          ?? parsed.chapters.at(-1)?.path
          ?? ''
      }
      this.patch({
        ...parsed,
        activeChapterPath,
        workspace,
        tasks,
        activeTasks: parseActiveTasks(tasks),
        workspaceError: null,
        epochs,
        connection: 'online',
        lastUpdatedAt: Date.now(),
      })
    } catch (cause: unknown) {
      if (generation !== this.generation) return
      if (cause instanceof StudioApiError && cause.status === 428) {
        // Uninitialized Workspace (contract §4): the root answers but has no
        // novel_config.yaml — surface the onboarding state, keep the panel empty.
        this.patch({
          connection: 'online',
          workspaceError: cause.code ?? 'WORKSPACE_NOT_INITIALIZED',
          projectTitle: '',
          currentChapterId: '',
          activeChapterPath: '',
          chapters: [],
          writingProgress: { bookUnits: 0, bookTarget: 0, chapterTarget: 0 },
          workspace: null,
          tasks: null,
          activeTasks: 0,
          lastUpdatedAt: Date.now(),
        })
        return
      }
      this.patch({ connection: 'offline' })
    } finally {
      if (this.refreshController === controller) this.refreshController = null
    }
  }

  private patch(patch: Partial<WorkbenchSnapshot>): void {
    this.snapshot = { ...this.snapshot, ...patch }
    for (const listener of this.listeners) listener()
  }
}

export const workbenchStore = new NovelWorkbenchStore()

export function useWorkbench(): WorkbenchSnapshot {
  return useSyncExternalStore(workbenchStore.subscribe, workbenchStore.getSnapshot, workbenchStore.getSnapshot)
}
