import { useSyncExternalStore } from 'react'
import { fetchStudioApi } from './api.ts'
import { nextEpochs, triggersRefresh } from './workbench-epochs.ts'

export type ConnectionState = 'connecting' | 'online' | 'offline'
export type EditorStatus = 'idle' | 'loading' | 'saved' | 'dirty' | 'saving' | 'conflict' | 'offline'
export type ResourceKey = 'workspace' | 'manuscript' | 'outline' | 'assets' | 'tasks' | 'benchmark' | 'models' | 'dag' | 'graph' | 'research' | 'revisions'

export interface ReviewSummary {
  score: number | null
  passed: boolean | null
  issues: number
  issueDetails: readonly unknown[]
}

export interface ChapterSummary {
  id: string
  path: string
  title: string
  subtitle: string
  review: ReviewSummary
}

export interface WorkbenchSnapshot {
  connection: ConnectionState
  projectTitle: string
  currentChapterId: string
  activeChapterPath: string
  chapters: readonly ChapterSummary[]
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
  projectTitle: '',
  currentChapterId: '',
  activeChapterPath: '',
  chapters: [],
  workspace: null,
  tasks: null,
  activeTasks: 0,
  editorStatus: 'idle',
  editorMessage: '',
  epochs: EMPTY_EPOCHS,
  lastUpdatedAt: 0,
}

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

function parseWorkspace(value: unknown): Pick<WorkbenchSnapshot, 'projectTitle' | 'currentChapterId' | 'chapters'> {
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
      path,
      title: text(chapter['title']) || chapterId(path),
      subtitle: text(chapter['subtitle']),
      review: {
        score: typeof review['score'] === 'number' ? review['score'] : null,
        passed: typeof review['passed'] === 'boolean' ? review['passed'] : null,
        issues: typeof review['issues'] === 'number' ? review['issues'] : 0,
        issueDetails: Array.isArray(review['issue_details']) ? review['issue_details'] : [],
      },
    }
  }).filter(chapter => chapter.path !== '')
  return {
    projectTitle: text(snapshot['title']) || text(record(recent[0])['title']),
    currentChapterId: text(snapshot['current_chapter']),
    chapters,
  }
}

function parseActiveTasks(value: unknown): number {
  const counts = record(record(value)['data'])['counts'] ?? record(value)['counts']
  const map = record(counts)
  return ['pending', 'running', 'awaiting_confirmation'].reduce((sum, key) =>
    sum + (typeof map[key] === 'number' ? map[key] : 0), 0)
}

class NovelWorkbenchStore {
  private snapshot: WorkbenchSnapshot = INITIAL
  private readonly listeners = new Set<Listener>()
  private pollTimer: number | null = null
  private eventSource: EventSource | null = null
  private refreshPromise: Promise<void> | null = null
  private taskSignature = ''
  private revision = 0
  private revisionInitialized = false
  private pollTicks = 0

  readonly subscribe = (listener: Listener): (() => void) => {
    this.listeners.add(listener)
    if (this.listeners.size === 1) this.start()
    return () => {
      this.listeners.delete(listener)
      if (this.listeners.size === 0) this.stop()
    }
  }

  readonly getSnapshot = (): WorkbenchSnapshot => this.snapshot

  setActiveChapter(path: string): void {
    if (path === this.snapshot.activeChapterPath) return
    this.patch({ activeChapterPath: path, editorStatus: 'loading', editorMessage: '' })
    try { window.localStorage.setItem('dsh-novel.activeChapterPath', path) } catch { /* unavailable storage */ }
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
    if (this.refreshPromise !== null) return this.refreshPromise
    this.refreshPromise = this.refreshNow().finally(() => { this.refreshPromise = null })
    return this.refreshPromise
  }

  private start(): void {
    this.patch({ connection: 'connecting' })
    void this.refresh()
    if (typeof EventSource === 'undefined') this.startFallbackPolling()
    else {
      const source = new EventSource('/studio-panel/events')
      this.eventSource = source
      source.addEventListener('open', () => {
        if (this.pollTimer !== null) window.clearInterval(this.pollTimer)
        this.pollTimer = null
        this.patch({ connection: 'online' })
      })
      source.addEventListener('ready', event => {
        this.consumeMutation((event as MessageEvent<string>).data)
        this.patch({ connection: 'online' })
      })
      source.addEventListener('invalidate', event => {
        this.consumeMutation((event as MessageEvent<string>).data)
        this.patch({ connection: 'online' })
      })
      source.onerror = () => {
        this.patch({ connection: 'offline' })
        this.startFallbackPolling()
      }
    }
  }

  private startFallbackPolling(): void {
    if (this.pollTimer !== null) return
    void this.pollInvalidation()
    this.pollTimer = window.setInterval(() => {
      if (!document.hidden) void this.pollInvalidation()
    }, 5_000)
  }

  private consumeMutation(value: unknown): void {
    let mutation = record(value)
    if (typeof value === 'string') {
      try { mutation = record(JSON.parse(value)) } catch { return }
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
  }

  private async pollInvalidation(): Promise<void> {
    try {
      const response = await fetch('/studio-panel/invalidation.json', { headers: { accept: 'application/json' } })
      if (!response.ok) throw new Error(`HTTP ${String(response.status)}`)
      this.consumeMutation(await response.json())
      this.pollTicks += 1
      if (this.pollTicks % 4 === 0) void this.refresh()
      this.patch({ connection: 'online' })
    } catch {
      this.patch({ connection: 'offline' })
    }
  }

  private async refreshNow(): Promise<void> {
    try {
      const [workspace, tasks] = await Promise.all([
        fetchStudioApi('/workspace'),
        fetchStudioApi('/tasks?limit=100'),
      ])
      const parsed = parseWorkspace(workspace)
      const taskSignature = JSON.stringify(record(tasks)['data'] ?? tasks)
      const tasksChanged = taskSignature !== this.taskSignature
      this.taskSignature = taskSignature
      let activeChapterPath = this.snapshot.activeChapterPath
      if (activeChapterPath === '') {
        let stored = ''
        try { stored = window.localStorage.getItem('dsh-novel.activeChapterPath') ?? '' } catch { /* unavailable storage */ }
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
        epochs: tasksChanged
          ? { ...this.snapshot.epochs, tasks: this.snapshot.epochs.tasks + 1 }
          : this.snapshot.epochs,
        connection: 'online',
        lastUpdatedAt: Date.now(),
      })
    } catch {
      this.patch({ connection: 'offline' })
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
