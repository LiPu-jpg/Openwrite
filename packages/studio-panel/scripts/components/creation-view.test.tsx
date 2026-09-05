import { act, fireEvent, render, screen } from '@testing-library/react'
import { useEffect } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { CreationView } from '../../src/client/CreationView.tsx'
import { StudioApiError } from '../../src/client/api.ts'

interface Deferred<T> {
  promise: Promise<T>
  resolve: (value: T) => void
  reject: (reason?: unknown) => void
}

function deferred<T>(): Deferred<T> {
  let resolve!: (value: T) => void
  let reject!: (reason?: unknown) => void
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise
    reject = rejectPromise
  })
  return { promise, resolve, reject }
}

const harness = vi.hoisted(() => ({
  snapshot: {} as Record<string, unknown>,
  setEditorStatus: vi.fn(),
  invalidate: vi.fn(),
  setActiveChapter: vi.fn(),
  draftStore: {
    load: vi.fn(),
    save: vi.fn(),
    remove: vi.fn(),
    removeIfContent: vi.fn(),
  },
}))

vi.mock('../../src/client/WorkbenchStore.ts', () => ({
  useWorkbench: () => harness.snapshot,
  workbenchStore: {
    getSnapshot: () => harness.snapshot,
    setEditorStatus: harness.setEditorStatus,
    invalidate: harness.invalidate,
    setActiveChapter: harness.setActiveChapter,
  },
}))

vi.mock('../../src/client/workspace-context.ts', () => ({
  useBindStudioContext: () => undefined,
}))

vi.mock('../../src/client/draft-store.ts', async importOriginal => ({
  ...await importOriginal<typeof import('../../src/client/draft-store.ts')>(),
  manuscriptDraftStore: harness.draftStore,
}))

vi.mock('@deepseek-ai/dsh-client-ui-primitives', () => ({
  MarkdownText: ({ text }: { text: string }) => <div>{text}</div>,
}))

vi.mock('../../src/client/VditorBody.tsx', () => ({
  loadVditor: () => Promise.resolve(),
  VditorBody: ({ initial, onChange, onReady }: {
    initial: string
    onChange: (value: string) => void
    onReady: () => void
  }) => {
    useEffect(() => { onReady() }, [onReady])
    return <textarea aria-label="manuscript-editor" defaultValue={initial}
      onChange={event => onChange(event.target.value)} />
  },
}))

const t = (key: string): string => key
const chapter = (path = 'data/novels/demo/data/manuscript/ch_001.md') => ({
  id: /ch_[A-Za-z0-9_-]+/.exec(path)?.[0] ?? 'ch_001', documentId: '', occurrenceId: '', volumeId: '', status: 'present', path, title: '第一章', subtitle: '',
  revision: '', readingIndex: null, writingUnits: null, updatedAt: '',
  review: {
    score: null, passed: null, issues: 0, issueDetails: [], stale: false,
    reviewedAt: '', sourceRevision: '', currentSourceRevision: '',
  },
})

function chapterWorkBrief(options: {
  path?: string
  documentId?: string
  manuscriptRevision?: string
  reviewRevision?: string
  stale?: boolean
  recentEdits?: Record<string, unknown>[]
  latestClosure?: Record<string, unknown> | null
} = {}) {
  const path = options.path ?? chapter().path
  const manuscriptRevision = options.manuscriptRevision ?? 'revision-current'
  return { data: {
    schema_version: 'openwrite.chapter-work-brief.v1', novel_id: 'demo', chapter_id: chapter(path).id,
    document_id: options.documentId ?? '',
    manuscript: {
      path, title: '第一章', save_status: 'saved', current_revision: manuscriptRevision,
      writing_units: 1200, modified_at: '2026-09-05T01:00:00+08:00',
    },
    review: {
      exists: true, review_revision: options.reviewRevision ?? 'review-revision-current', freshness_status: options.stale ? 'stale' : 'current',
      stale: options.stale === true, stale_reason: options.stale ? 'source_changed' : '', source_revision: manuscriptRevision,
      current_source_revision: manuscriptRevision, reviewed_at: '2026-09-05T00:30:00+08:00', issue_count: 2,
      latest_closure: options.latestClosure ?? null,
    },
    target: { writing_units: 2500, source: 'project.chapter_target', actual_units: 1200, remaining_units: 1300, progress: 0.48 },
    recent_edits: options.recentEdits ?? [],
  } }
}

function canonicalReadingOrder(documents: Record<string, unknown>[], revision = 'order-revision-one') {
  const volumeIds = Array.from(new Set(documents.map(document => String((document['volume'] as Record<string, unknown>)?.['volume_id'] ?? 'arc-one'))))
  return { data: {
    schema_version: 'openwrite.reading-order.v1', novel_id: 'demo', revision, mode: 'outline', mutation_allowed: true,
    actual_order: documents.map(document => String(document['occurrence_id'])),
    volumes: volumeIds.map((volumeId, index) => ({
      volume_id: volumeId, title: `第${String(index + 1)}卷`, order: index,
      occurrence_ids: documents.filter(document => (document['volume'] as Record<string, unknown>)?.['volume_id'] === volumeId)
        .map(document => String(document['occurrence_id'])),
    })),
    documents, issues: [],
  } }
}

function readingDocument(options: {
  path: string
  documentId: string
  occurrenceId: string
  chapterId?: string
  title?: string
  volumeId?: string
  index: number
  content?: string
}) {
  return {
    document_id: options.documentId, occurrence_id: options.occurrenceId, chapter_id: options.chapterId ?? 'ch_001',
    title: options.title ?? '第一章', path: options.path, status: 'present', volume: { volume_id: options.volumeId ?? 'arc-one' },
    writing_units: 1200, revision: `revision-${options.occurrenceId}`, updated_at: '2026-09-05T01:00:00+08:00',
    reading_index: options.index, previous_occurrence_id: '', next_occurrence_id: '', content: options.content ?? '',
  }
}

function setSnapshot(workspaceId: string, contentPath = chapter().path, contextEpoch = 1) {
  harness.snapshot = {
    connection: 'online',
    context: { workspaceId, root: `/root/${workspaceId}`, sessionId: `session-${workspaceId}` },
    contextEpoch,
    workspaceError: null,
    projectTitle: '测试小说',
    currentChapterId: 'ch_001',
    activeChapterPath: contentPath,
    chapters: [chapter(contentPath)],
    writingProgress: { bookUnits: 100, bookTarget: 1000, chapterTarget: 200 },
    workspace: null,
    tasks: null,
    activeTasks: 0,
    editorStatus: 'saved',
    editorMessage: '',
    epochs: {
      workspace: 0, manuscript: 0, outline: 0, assets: 0,
      tasks: 0, benchmark: 0, models: 0, dag: 0, graph: 0, research: 0, revisions: 0,
    },
    lastUpdatedAt: 0,
  }
}

function viewProps(api: {
  fetchStudioApi: ReturnType<typeof vi.fn>
  putStudioApi: ReturnType<typeof vi.fn>
  postStudioApi?: ReturnType<typeof vi.fn>
}) {
  return {
    ...api,
    postStudioApi: api.postStudioApi ?? vi.fn(),
    sessionId: 'session-ws-a',
    useWorkspaces: vi.fn(),
    t,
  }
}

beforeEach(() => {
  setSnapshot('ws-a')
  harness.setEditorStatus.mockClear()
  harness.invalidate.mockClear()
  harness.setActiveChapter.mockClear()
  harness.draftStore.load.mockReset().mockResolvedValue(null)
  harness.draftStore.save.mockReset().mockResolvedValue(undefined)
  harness.draftStore.remove.mockReset().mockResolvedValue(undefined)
  harness.draftStore.removeIfContent.mockReset().mockResolvedValue(true)
})

afterEach(() => {
  vi.useRealTimers()
})

describe('CreationView save queue', () => {
  it('marks toolbar saves as manual and timer saves as autosave', async () => {
    const fetchStudioApi = vi.fn(async () => ({
      path: chapter().path, title: '第一章', content: '初稿', version: 'v1', revision: 'r1',
    }))
    const putStudioApi = vi.fn(async (_path, body: Record<string, unknown>) => ({
      path: chapter().path, title: '第一章', content: body['content'], version: 'v2', revision: 'r2',
    }))
    render(<CreationView {...(viewProps({ fetchStudioApi, putStudioApi }) as never)} />)

    const editor = await screen.findByRole('textbox', { name: 'manuscript-editor' })
    fireEvent.change(editor, { target: { value: '手动保存稿' } })
    fireEvent.click(screen.getByRole('button', { name: 'creation.status.saved' }))
    await act(async () => { await Promise.resolve() })
    expect(putStudioApi.mock.calls[0]?.[1]).toMatchObject({ save_origin: 'manual' })

    vi.useFakeTimers()
    fireEvent.change(editor, { target: { value: '自动保存稿' } })
    await act(async () => { await vi.advanceTimersByTimeAsync(1_200) })
    expect(putStudioApi.mock.calls[1]?.[1]).toMatchObject({ save_origin: 'autosave' })
  })

  it('keeps text typed during an in-flight save dirty and sends it with the returned version', async () => {
    const first = deferred<unknown>()
    const second = deferred<unknown>()
    const fetchStudioApi = vi.fn(async () => ({
      path: chapter().path, title: '第一章', content: '初稿', version: 'v1', revision: 'r1',
    }))
    const putStudioApi = vi.fn()
      .mockImplementationOnce(() => first.promise)
      .mockImplementationOnce(() => second.promise)
    render(<CreationView {...(viewProps({ fetchStudioApi, putStudioApi }) as never)} />)

    const editor = await screen.findByRole('textbox', { name: 'manuscript-editor' })
    vi.useFakeTimers()
    fireEvent.change(editor, { target: { value: '稿件 A' } })
    await act(async () => { await vi.advanceTimersByTimeAsync(1_200) })
    expect(putStudioApi).toHaveBeenCalledTimes(1)
    expect(putStudioApi.mock.calls[0]?.[1]).toMatchObject({ content: '稿件 A', version: 'v1' })

    fireEvent.change(editor, { target: { value: '稿件 B' } })
    await act(async () => { await vi.advanceTimersByTimeAsync(1_200) })
    expect(putStudioApi).toHaveBeenCalledTimes(1)

    await act(async () => {
      first.resolve({ path: chapter().path, title: '第一章', content: '稿件 A', version: 'v2', revision: 'r2' })
      await first.promise
    })
    await act(async () => { await Promise.resolve() })
    expect(putStudioApi).toHaveBeenCalledTimes(2)
    expect(putStudioApi.mock.calls[1]?.[1]).toMatchObject({ content: '稿件 B', version: 'v2' })
    expect(harness.setEditorStatus).toHaveBeenLastCalledWith('saving')

    await act(async () => {
      second.resolve({ path: chapter().path, title: '第一章', content: '稿件 B', version: 'v3', revision: 'r3' })
      await second.promise
    })
    expect(harness.setEditorStatus).toHaveBeenLastCalledWith('saved')
  })

  it('pins an in-flight write to its Workspace and drops its late response after a context switch', async () => {
    const first = deferred<unknown>()
    const fetchStudioApi = vi.fn(async () => {
      const workspaceId = (harness.snapshot.context as { workspaceId: string }).workspaceId
      return {
        path: chapter().path,
        title: '第一章',
        content: workspaceId === 'ws-a' ? '工作区 A' : '工作区 B',
        version: workspaceId === 'ws-a' ? 'a1' : 'b1',
        revision: workspaceId === 'ws-a' ? 'ar1' : 'br1',
      }
    })
    const putStudioApi = vi.fn(() => first.promise)
    const props = viewProps({ fetchStudioApi, putStudioApi })
    const view = render(<CreationView {...(props as never)} />)

    const editorA = await screen.findByRole('textbox', { name: 'manuscript-editor' })
    vi.useFakeTimers()
    fireEvent.change(editorA, { target: { value: 'A 的未完成保存' } })
    await act(async () => { await vi.advanceTimersByTimeAsync(1_200) })
    expect(putStudioApi).toHaveBeenCalledTimes(1)

    setSnapshot('ws-b', chapter().path, 2)
    await act(async () => {
      view.rerender(<CreationView {...({ ...props, sessionId: 'session-ws-b' } as never)} />)
      await Promise.resolve()
      await Promise.resolve()
    })
    expect(screen.getByRole<HTMLTextAreaElement>('textbox', { name: 'manuscript-editor' }).value).toBe('工作区 B')

    await act(async () => {
      first.resolve({ path: chapter().path, title: '第一章', content: 'A 的未完成保存', version: 'a2', revision: 'ar2' })
      await first.promise
    })
    expect(screen.getByRole<HTMLTextAreaElement>('textbox', { name: 'manuscript-editor' }).value).toBe('工作区 B')
    expect(putStudioApi.mock.calls[0]?.[2]).toEqual({ workspaceId: 'ws-a', sessionId: 'session-ws-a' })
  })

  it('keeps an offline draft and retries the same snapshot from the editor', async () => {
    const failed = deferred<unknown>()
    const retried = deferred<unknown>()
    const fetchStudioApi = vi.fn(async () => ({
      path: chapter().path, title: '第一章', content: '初稿', version: 'v1', revision: 'r1',
    }))
    const putStudioApi = vi.fn()
      .mockImplementationOnce(() => failed.promise)
      .mockImplementationOnce(() => retried.promise)
    const props = viewProps({ fetchStudioApi, putStudioApi })
    const view = render(<CreationView {...(props as never)} />)

    const editor = await screen.findByRole<HTMLTextAreaElement>('textbox', { name: 'manuscript-editor' })
    vi.useFakeTimers()
    fireEvent.change(editor, { target: { value: '断网期间的正文' } })
    await act(async () => { await vi.advanceTimersByTimeAsync(1_200) })
    await act(async () => {
      failed.reject(new Error('network unavailable'))
      await failed.promise.catch(() => undefined)
    })
    harness.snapshot = { ...harness.snapshot, editorStatus: 'offline', editorMessage: 'network unavailable' }
    view.rerender(<CreationView {...(props as never)} />)

    expect(editor.value).toBe('断网期间的正文')
    fireEvent.click(screen.getByRole('button', { name: 'retry' }))
    expect(putStudioApi).toHaveBeenCalledTimes(2)
    expect(putStudioApi.mock.calls[1]?.[1]).toMatchObject({ content: '断网期间的正文', version: 'v1' })

    await act(async () => {
      retried.resolve({ path: chapter().path, title: '第一章', content: '断网期间的正文', version: 'v2', revision: 'r2' })
      await retried.promise
    })
    expect(harness.setEditorStatus).toHaveBeenLastCalledWith('saved')
  })

  it('keeps a conflicted draft and can explicitly overwrite it', async () => {
    const conflicted = deferred<unknown>()
    const overwritten = deferred<unknown>()
    const fetchStudioApi = vi.fn(async () => ({
      path: chapter().path, title: '第一章', content: '初稿', version: 'v1', revision: 'r1',
    }))
    const putStudioApi = vi.fn()
      .mockImplementationOnce(() => conflicted.promise)
      .mockImplementationOnce(() => overwritten.promise)
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    const props = viewProps({ fetchStudioApi, putStudioApi })
    const view = render(<CreationView {...(props as never)} />)

    const editor = await screen.findByRole<HTMLTextAreaElement>('textbox', { name: 'manuscript-editor' })
    vi.useFakeTimers()
    fireEvent.change(editor, { target: { value: '冲突时保留的正文' } })
    await act(async () => { await vi.advanceTimersByTimeAsync(1_200) })
    await act(async () => {
      conflicted.reject(new StudioApiError('conflict', 409, 'DOCUMENT_CONFLICT'))
      await conflicted.promise.catch(() => undefined)
    })
    harness.snapshot = { ...harness.snapshot, editorStatus: 'conflict', editorMessage: 'conflict' }
    view.rerender(<CreationView {...(props as never)} />)

    expect(editor.value).toBe('冲突时保留的正文')
    fireEvent.click(screen.getByRole('button', { name: 'creation.overwrite' }))
    expect(putStudioApi.mock.calls[1]?.[1]).toMatchObject({
      content: '冲突时保留的正文', version: 'v1', force: true,
    })

    await act(async () => {
      overwritten.resolve({ path: chapter().path, title: '第一章', content: '冲突时保留的正文', version: 'v3', revision: 'r3' })
      await overwritten.promise
    })
    expect(harness.setEditorStatus).toHaveBeenLastCalledWith('saved')
  })

  it('drops a completed write response after the editor unmounts', async () => {
    const pending = deferred<unknown>()
    const fetchStudioApi = vi.fn(async () => ({
      path: chapter().path, title: '第一章', content: '初稿', version: 'v1', revision: 'r1',
    }))
    const putStudioApi = vi.fn(() => pending.promise)
    const view = render(<CreationView {...(viewProps({ fetchStudioApi, putStudioApi }) as never)} />)

    const editor = await screen.findByRole('textbox', { name: 'manuscript-editor' })
    vi.useFakeTimers()
    fireEvent.change(editor, { target: { value: '卸载前正文' } })
    await act(async () => { await vi.advanceTimersByTimeAsync(1_200) })
    view.unmount()
    harness.invalidate.mockClear()

    await act(async () => {
      pending.resolve({ path: chapter().path, title: '第一章', content: '卸载前正文', version: 'v2', revision: 'r2' })
      await pending.promise
    })

    expect(harness.invalidate).not.toHaveBeenCalled()
    expect(harness.setEditorStatus).toHaveBeenLastCalledWith('saving')
  })
})

describe('CreationView author history and revisions', () => {
  it('renders history and proposals, previews restore, and applies only checked hunks', async () => {
    const slowContext = deferred<unknown>()
    const fetchStudioApi = vi.fn(async (path: string) => {
      if (path.startsWith('/document')) return {
        path: chapter().path, title: '第一章', content: '当前正文', version: 'v1', revision: 'sha256:current',
      }
      // History must remain usable while the heavier context packet is still pending.
      if (path.startsWith('/context')) return slowContext.promise
      if (path.startsWith('/revisions')) return { proposals: [{
        proposal_id: 'rev_example1234', status: 'proposed', kind: 'selection_rewrite',
        rationale: '修正节奏', review_issue_ids: ['issue_pacing'], replacement_text: '新一\n新二',
        review_revision: 'review-revision-one', source_revision: 'source-revision-one',
        issue_hunk_provenance: [{ issue_id: 'issue_pacing', hunk_ids: ['hunk_0', 'hunk_1'] }],
        selection: { start: 0, end: 5, original_text: '旧一\n旧二' },
        diff: { hunks: [
          { id: 'hunk_0', tag: 'replace', before: '旧一\n', after: '新一\n' },
          { id: 'hunk_1', tag: 'replace', before: '旧二', after: '新二' },
        ] },
      }] }
      if (path.startsWith('/manuscript/versions/') && path.includes('/compare')) return {
        version: {
          version_id: 'ver_20260905000000_example1234', source_revision: 'sha256:old',
          reason: 'manual', label: '起稿前', created_at: '2026-09-05T00:00:00+00:00', writing_units: 120,
        },
        current: { revision: 'sha256:current' },
        diff: { segments: [{ id: 'hunk_0', tag: 'replace', before: '当前正文', after: '旧正文' }] },
      }
      if (path.startsWith('/manuscript/versions')) return { versions: [{
        version_id: 'ver_20260905000000_example1234', source_revision: 'sha256:old',
        reason: 'manual', label: '起稿前', created_at: '2026-09-05T00:00:00+00:00', writing_units: 120,
      }] }
      return {}
    })
    const postStudioApi = vi.fn(async () => ({}))
    const putStudioApi = vi.fn()
    render(<CreationView {...(viewProps({ fetchStudioApi, putStudioApi, postStudioApi }) as never)} />)

    await screen.findByRole('textbox', { name: 'manuscript-editor' })
    fireEvent.click(screen.getByRole('button', { name: 'creation.showInspector' }))
    fireEvent.click(screen.getByRole('tab', { name: 'creation.revisions' }))

    expect(await screen.findByText('起稿前')).not.toBeNull()
    expect(screen.getByText('修正节奏')).not.toBeNull()
    expect(screen.getByText('review-revision-one')).not.toBeNull()
    expect(screen.getByText('issue_pacing → hunk_0, hunk_1')).not.toBeNull()
    fireEvent.click(screen.getByRole('button', { name: 'creation.history.compare' }))
    expect(await screen.findByText(/当前正文/)).not.toBeNull()
    expect(screen.getByText(/旧正文/)).not.toBeNull()

    const hunks = screen.getAllByRole('checkbox')
    fireEvent.click(hunks[1]!)
    fireEvent.click(screen.getByRole('button', { name: 'creation.proposals.applySelected' }))
    await act(async () => { await Promise.resolve() })
    expect(postStudioApi).toHaveBeenCalledWith('/revisions/rev_example1234/apply', {
      selected_hunk_ids: ['hunk_0'],
    })
  })
})

describe('CreationView chapter navigation and reading', () => {
  it('keeps duplicate chapter entries visible and navigates the server order', async () => {
    const first = { ...chapter('data/novels/demo/data/manuscript/arc_001/ch_001.md'), title: '第一卷第一章' }
    const duplicate = { ...chapter('data/novels/demo/data/manuscript/arc_002/ch_001.md'), title: '第二卷第一章' }
    const next = { ...chapter('data/novels/demo/data/manuscript/arc_002/ch_002.md'), title: '第二卷第二章' }
    harness.snapshot = {
      ...harness.snapshot,
      activeChapterPath: duplicate.path,
      chapters: [first, duplicate, next],
      writingProgress: { bookUnits: 12_345, bookTarget: 80_000, chapterTarget: 2_500 },
    }
    const fetchStudioApi = vi.fn(async (url: string) => {
      if (url.startsWith('/document')) {
        const path = decodeURIComponent(url.split('path=')[1] ?? '')
        return { path, title: path, content: `正文 ${path}`, version: 'v1', revision: `rev:${path}` }
      }
      return {}
    })
    render(<CreationView {...(viewProps({ fetchStudioApi, putStudioApi: vi.fn() }) as never)} />)

    await screen.findByRole('textbox', { name: 'manuscript-editor' })
    expect(screen.getAllByText(/creation\.chapterDuplicate/).length).toBeGreaterThanOrEqual(2)
    expect(screen.getByText(/12,345 \/ 80,000/)).not.toBeNull()

    fireEvent.click(screen.getByRole('button', { name: 'creation.previousChapter' }))
    expect(harness.setActiveChapter).toHaveBeenLastCalledWith(first.path)
    fireEvent.click(screen.getByRole('button', { name: 'creation.nextChapter' }))
    expect(harness.setActiveChapter).toHaveBeenLastCalledWith(next.path)
  })

  it('loads every ordered occurrence into a revision-labelled continuous reader', async () => {
    const first = { ...chapter(), documentId: 'doc-one', title: '第一章' }
    const second = { ...chapter('data/novels/demo/data/manuscript/ch_002.md'), documentId: 'doc-two', title: '第二章' }
    harness.snapshot = { ...harness.snapshot, chapters: [first, second] }
    const fetchStudioApi = vi.fn(async (url: string) => {
      if (url.startsWith('/document')) {
        const path = decodeURIComponent(url.split('path=')[1] ?? '')
        return {
          path, document_id: path === first.path ? first.documentId : second.documentId,
          title: path, content: path === first.path ? '连续正文一' : '连续正文二',
          version: 'v1', revision: path === first.path ? 'revision-one' : 'revision-two',
        }
      }
      return {}
    })
    render(<CreationView {...(viewProps({ fetchStudioApi, putStudioApi: vi.fn() }) as never)} />)
    await screen.findByRole('textbox', { name: 'manuscript-editor' })

    fireEvent.click(screen.getByRole('button', { name: 'creation.mode.reader' }))
    expect(await screen.findByText('连续正文一')).not.toBeNull()
    expect(await screen.findByText('连续正文二')).not.toBeNull()
    expect(screen.getByText('revision-one')).not.toBeNull()
    expect(screen.getByText('doc-two')).not.toBeNull()
    expect(fetchStudioApi).toHaveBeenCalledWith(`/document?path=${encodeURIComponent(second.path)}`)
  })

  it('navigates repeated paths by canonical occurrence identity', async () => {
    const repeated = { ...chapter(), documentId: 'doc-repeat' }
    harness.snapshot = { ...harness.snapshot, chapters: [repeated] }
    const first = readingDocument({ path: repeated.path, documentId: 'doc-repeat', occurrenceId: 'occ-first', index: 0 })
    const second = readingDocument({ path: repeated.path, documentId: 'doc-repeat', occurrenceId: 'occ-second', index: 1 })
    const fetchStudioApi = vi.fn(async (url: string) => {
      if (url === '/reading-order') return canonicalReadingOrder([first, second])
      if (url.startsWith('/document')) return { path: repeated.path, title: repeated.title, content: '正文', version: 'v1', revision: 'revision-current' }
      if (url.startsWith('/chapters/ch_001/work-brief?')) return chapterWorkBrief({ documentId: 'doc-repeat' })
      return {}
    })
    render(<CreationView {...(viewProps({ fetchStudioApi, putStudioApi: vi.fn() }) as never)} />)

    await screen.findByText('occ-second')
    const jump = screen.getByRole<HTMLSelectElement>('combobox', { name: 'creation.jumpChapter' })
    expect(jump.value).toBe('0')
    fireEvent.click(screen.getByRole('button', { name: 'creation.nextChapter' }))
    expect(jump.value).toBe('1')
    fireEvent.click(screen.getByRole('button', { name: 'creation.previousChapter' }))
    expect(jump.value).toBe('0')
  })

  it('loads canonical reading packets and moves with the fresh order revision', async () => {
    const firstChapter = { ...chapter(), documentId: 'doc-one' }
    const secondChapter = { ...chapter('data/novels/demo/data/manuscript/ch_002.md'), documentId: 'doc-two', title: '第二章' }
    harness.snapshot = { ...harness.snapshot, chapters: [firstChapter, secondChapter] }
    const first = readingDocument({ path: firstChapter.path, documentId: 'doc-one', occurrenceId: 'occ-one', volumeId: 'arc-one', index: 0, content: '规范正文一' })
    const second = readingDocument({ path: secondChapter.path, documentId: 'doc-two', occurrenceId: 'occ-two', chapterId: 'ch_002', title: '第二章', volumeId: 'arc-two', index: 1, content: '规范正文二' })
    const order = canonicalReadingOrder([first, second])
    const fetchStudioApi = vi.fn(async (url: string) => {
      if (url === '/reading-order') return order
      if (url.startsWith('/reading-packet?')) return { data: {
        schema_version: 'openwrite.reading-packet.v1', novel_id: 'demo', revision: 'order-revision-one',
        anchor_document_id: 'doc-one', anchor_occurrence_id: 'occ-one', start_index: 0, end_index: 1,
        has_previous: false, has_next: false, complete: true, documents: [first, second], issues: [],
      } }
      if (url.startsWith('/document')) return { path: firstChapter.path, title: firstChapter.title, content: '正文', version: 'v1', revision: 'revision-current' }
      if (url.startsWith('/chapters/ch_001/work-brief?')) return chapterWorkBrief({ documentId: 'doc-one' })
      return {}
    })
    const postStudioApi = vi.fn(async (url: string) => url === '/reading-order/move'
      ? { data: { reading_order: order.data } }
      : {})
    render(<CreationView {...(viewProps({ fetchStudioApi, putStudioApi: vi.fn(), postStudioApi }) as never)} />)
    await screen.findByText('occ-two')

    fireEvent.click(screen.getByRole('button', { name: 'creation.mode.reader' }))
    expect(await screen.findByText('规范正文一')).not.toBeNull()
    expect(screen.getByText('规范正文二')).not.toBeNull()
    expect(fetchStudioApi).toHaveBeenCalledWith('/reading-packet?document_id=occ-one&before=0&after=20')

    fireEvent.click(screen.getByRole('button', { name: 'creation.mode.edit' }))
    const volume = screen.getByRole<HTMLSelectElement>('combobox', { name: 'creation.order.volume' })
    fireEvent.change(volume, { target: { value: 'arc-two' } })
    fireEvent.change(screen.getByRole('spinbutton'), { target: { value: '0' } })
    fireEvent.click(screen.getByRole('button', { name: 'creation.order.applyMove' }))
    await act(async () => { await Promise.resolve() })
    expect(postStudioApi).toHaveBeenCalledWith('/reading-order/move', {
      document_id: 'doc-one', target_volume_id: 'arc-two', target_index: 0, expected_revision: 'order-revision-one',
    })
  })
})

describe('CreationView review-to-revision workflow', () => {
  it('submits only selected current-review issues and offers an explicit rereview task', async () => {
    const reviewed = {
      ...chapter(),
      review: {
        ...chapter().review,
        issues: 2,
        issueDetails: [
          { id: 'issue-one', severity: 'warning', category: '节奏', description: '问题一', suggestion: '建议一' },
          { id: 'issue-two', severity: 'info', category: '措辞', description: '问题二', suggestion: '建议二' },
        ],
      },
    }
    harness.snapshot = { ...harness.snapshot, chapters: [reviewed] }
    const fetchStudioApi = vi.fn(async (url: string) => {
      if (url.startsWith('/document')) return { path: reviewed.path, title: reviewed.title, content: '正文', version: 'v1', revision: 'revision-current' }
      if (url.startsWith('/chapters/ch_001/work-brief?')) return chapterWorkBrief()
      return {}
    })
    const postStudioApi = vi.fn(async () => ({ task: { id: 'tsk-example' } }))
    render(<CreationView {...(viewProps({ fetchStudioApi, putStudioApi: vi.fn(), postStudioApi }) as never)} />)
    await screen.findByRole('textbox', { name: 'manuscript-editor' })
    await screen.findByText(/1,200 \/ 2,500/)
    fireEvent.click(screen.getByRole('button', { name: 'creation.showInspector' }))
    fireEvent.click(screen.getByRole('tab', { name: 'creation.review' }))

    const issues = screen.getAllByRole('checkbox')
    fireEvent.click(issues[1]!)
    fireEvent.change(screen.getByPlaceholderText('creation.review.instruction'), { target: { value: '只压缩重复段落' } })
    fireEvent.click(screen.getByRole('button', { name: 'creation.review.createRevision' }))
    await act(async () => { await Promise.resolve() })
    expect(postStudioApi).toHaveBeenCalledWith('/tasks', {
      type: 'revision_from_review',
      input: {
        chapter_id: 'ch_001', issue_ids: ['issue-two'], instruction: '只压缩重复段落',
        expected_review_revision: 'review-revision-current', expected_document_revision: 'revision-current',
      },
    })
    expect(await screen.findByText('creation.review.revisionStarted')).not.toBeNull()

    fireEvent.click(screen.getByRole('button', { name: 'creation.review.rereview' }))
    await act(async () => { await Promise.resolve() })
    expect(postStudioApi).toHaveBeenLastCalledWith('/tasks', {
      type: 'chapter_review', input: { chapter_id: 'ch_001' },
    })
  })

  it('blocks issue revision generation when the server marks the review stale', async () => {
    const reviewed = {
      ...chapter(),
      review: {
        ...chapter().review,
        stale: true,
        issues: 1,
        issueDetails: [{ id: 'issue-old', severity: 'warning', category: '节奏', description: '旧问题' }],
      },
    }
    harness.snapshot = { ...harness.snapshot, chapters: [reviewed] }
    const fetchStudioApi = vi.fn(async (url: string) => {
      if (url.startsWith('/document')) return { path: reviewed.path, title: reviewed.title, content: '新正文', version: 'v2', revision: 'revision-new' }
      if (url.startsWith('/chapters/ch_001/work-brief?')) return chapterWorkBrief({ manuscriptRevision: 'revision-new', stale: true })
      return {}
    })
    render(<CreationView {...(viewProps({ fetchStudioApi, putStudioApi: vi.fn() }) as never)} />)
    await screen.findByRole('textbox', { name: 'manuscript-editor' })
    fireEvent.click(screen.getByRole('button', { name: 'creation.showInspector' }))
    fireEvent.click(screen.getByRole('tab', { name: 'creation.review' }))

    expect(await screen.findByText('creation.review.stale')).not.toBeNull()
    expect((screen.getByRole('checkbox') as HTMLInputElement).disabled).toBe(true)
    expect((screen.getByRole('button', { name: 'creation.review.createRevision' }) as HTMLButtonElement).disabled).toBe(true)
  })

  it('requires refresh when review CAS rejects the selected issues', async () => {
    const reviewed = {
      ...chapter(),
      review: {
        ...chapter().review,
        issues: 1,
        issueDetails: [{ id: 'issue-current', severity: 'warning', category: '节奏', description: '问题' }],
      },
    }
    harness.snapshot = { ...harness.snapshot, chapters: [reviewed] }
    const fetchStudioApi = vi.fn(async (url: string) => {
      if (url.startsWith('/document')) return { path: reviewed.path, title: reviewed.title, content: '正文', version: 'v1', revision: 'revision-current' }
      if (url.startsWith('/chapters/ch_001/work-brief?')) return chapterWorkBrief()
      return {}
    })
    const postStudioApi = vi.fn().mockRejectedValue(new StudioApiError('changed', 409, 'REVIEW_CONFLICT'))
    render(<CreationView {...(viewProps({ fetchStudioApi, putStudioApi: vi.fn(), postStudioApi }) as never)} />)
    await screen.findByText(/1,200 \/ 2,500/)
    fireEvent.click(screen.getByRole('button', { name: 'creation.showInspector' }))
    fireEvent.click(screen.getByRole('tab', { name: 'creation.review' }))
    fireEvent.click(screen.getByRole('checkbox'))
    fireEvent.click(screen.getByRole('button', { name: 'creation.review.createRevision' }))

    expect(await screen.findByText('creation.review.refreshRequired')).not.toBeNull()
  })

  it('shows explicit resolved, retained, and regressed outcomes after rereview', async () => {
    const fetchStudioApi = vi.fn(async (url: string) => {
      if (url.startsWith('/document')) return { path: chapter().path, title: '第一章', content: '正文', version: 'v1', revision: 'revision-current' }
      if (url.startsWith('/chapters/ch_001/work-brief?')) return chapterWorkBrief({ latestClosure: {
        closure_id: 'closure-one', proposal_id: 'proposal-one', rereview_review_revision: 'review-rereview',
        closed_at: '2026-09-05T02:00:00+08:00',
        issue_outcomes: [{ issue_id: 'issue-resolved', outcome: 'resolved' }, { issue_id: 'issue-retained', outcome: 'retained' }],
        regressions: [{ issue_id: 'issue-regressed', outcome: 'regressed', issue: { description: '新增时间线冲突' } }],
      } })
      return {}
    })
    render(<CreationView {...(viewProps({ fetchStudioApi, putStudioApi: vi.fn() }) as never)} />)
    await screen.findByText(/1,200 \/ 2,500/)
    fireEvent.click(screen.getByRole('button', { name: 'creation.showInspector' }))
    fireEvent.click(screen.getByRole('tab', { name: 'creation.review' }))

    expect(screen.getByText('creation.review.closure')).not.toBeNull()
    expect(screen.getByText('creation.review.outcome.resolved')).not.toBeNull()
    expect(screen.getByText('creation.review.outcome.retained')).not.toBeNull()
    expect(screen.getByText('creation.review.outcome.regressed')).not.toBeNull()
    expect(screen.getByText('新增时间线冲突')).not.toBeNull()
  })
})

describe('CreationView chapter activity', () => {
  it('shows the chapter target, revisions, and recent edits from the work brief', async () => {
    const fetchStudioApi = vi.fn(async (url: string) => {
      if (url.startsWith('/document')) return { path: chapter().path, title: '第一章', content: '正文', version: 'v1', revision: 'revision-current' }
      if (url.startsWith('/chapters/ch_001/work-brief?')) return chapterWorkBrief({
        recentEdits: [{
          kind: 'manuscript_save', id: 'edit-one', status: 'saved', document_id: '', path: chapter().path,
          chapter_id: 'ch_001', revision: 'revision-current', updated_at: '2026-09-05T01:00:00+08:00',
          writing_units_delta: 42, reason: 'manual',
        }],
      })
      return {}
    })
    render(<CreationView {...(viewProps({ fetchStudioApi, putStudioApi: vi.fn() }) as never)} />)
    await screen.findByText(/1,200 \/ 2,500/)
    fireEvent.click(screen.getByRole('button', { name: 'creation.showInspector' }))
    fireEvent.click(screen.getByRole('tab', { name: 'creation.activity' }))

    expect(screen.getByText('creation.activity.target')).not.toBeNull()
    expect(screen.getByText(/creation\.activity\.remaining 1,300/)).not.toBeNull()
    expect(screen.getAllByText('revision-current').length).toBeGreaterThan(0)
    expect(screen.getByText('manuscript_save')).not.toBeNull()
    expect(screen.getByText('+42 creation.history.units')).not.toBeNull()
  })
})

describe('CreationView manuscript acceptance', () => {
  it('shows revision drift and reconciles the external manuscript explicitly', async () => {
    const fetchStudioApi = vi.fn(async (path: string) => {
      if (path.startsWith('/document')) return {
        path: chapter().path, title: '第一章', content: '当前正文', version: 'v1', revision: 'sha256:current',
      }
      if (path.startsWith('/manuscript/acceptance')) return {
        data: {
          schema_version: 'openwrite.manuscript-acceptance.v1', status: 'drift', blocking: true,
          chapters: [{
            chapter_id: 'ch_001', path: chapter().path, status: 'drift',
            current_revision: 'sha256:current', accepted_revision: 'sha256:accepted',
            message: '磁盘正文发生了外部变化',
          }],
          impacts: ['context', 'review'], needs_review: false,
        },
      }
      return {}
    })
    const postStudioApi = vi.fn(async () => ({ data: { acceptance: {
      chapter_id: 'ch_001', status: 'current',
      current_revision: 'sha256:current', accepted_revision: 'sha256:current',
    } } }))
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    render(<CreationView {...(viewProps({ fetchStudioApi, putStudioApi: vi.fn(), postStudioApi }) as never)} />)

    expect(await screen.findByText('creation.acceptance.drift')).not.toBeNull()
    expect(screen.getByText('sha256:accepted')).not.toBeNull()
    expect(screen.getByText('context · review')).not.toBeNull()
    fireEvent.click(screen.getByRole('button', { name: 'creation.acceptance.external' }))

    await act(async () => { await Promise.resolve() })
    expect(window.confirm).toHaveBeenCalledWith('creation.acceptance.confirmExternal')
    expect(postStudioApi).toHaveBeenCalledWith('/manuscript/acceptance/external', {
      chapter_id: 'ch_001', confirm: true,
    })
    expect(await screen.findByText('creation.acceptance.current')).not.toBeNull()
    expect(harness.invalidate).toHaveBeenCalledWith('manuscript')
  })

  it.each([
    ['baseline_required', 'creation.acceptance.baseline', 'baseline', true, undefined],
    ['pending', 'creation.acceptance.resume', 'reconcile', undefined, 'op_001'],
    ['needs_review', 'creation.acceptance.acknowledge', 'ack', true, 'op_002'],
  ] as const)('maps %s to the required recovery action', async (status, label, route, confirm, operationId) => {
    const fetchStudioApi = vi.fn(async (path: string) => {
      if (path.startsWith('/document')) return {
        path: chapter().path, title: '第一章', content: '正文', version: 'v1', revision: 'sha256:current',
      }
      if (status === 'needs_review') return { data: {
        status: 'needs_review', latest_operation_id: operationId,
        chapters: [{ chapter_id: 'ch_001', status: 'current', current_revision: 'sha256:current' }],
        needs_review: [{ domain: 'outline', status: 'needs_review', source_chapter: 'ch_001' }],
      } }
      return { acceptance: {
        chapter_id: 'ch_001', status, operation: operationId === undefined ? undefined : { operation_id: operationId },
      } }
    })
    const postStudioApi = vi.fn(async () => ({ acceptance: { chapter_id: 'ch_001', status: 'current' } }))
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    render(<CreationView {...(viewProps({ fetchStudioApi, putStudioApi: vi.fn(), postStudioApi }) as never)} />)

    fireEvent.click(await screen.findByRole('button', { name: label }))
    await act(async () => { await Promise.resolve() })
    expect(postStudioApi).toHaveBeenCalledWith(`/manuscript/acceptance/${route}`, {
      chapter_id: 'ch_001',
      ...(operationId === undefined ? {} : { operation_id: operationId }),
      ...(confirm === undefined ? {} : { confirm }),
      ...(route === 'ack' ? { domains: ['outline', 'foreshadowing'] } : {}),
    })
  })
})

describe('CreationView context manifest', () => {
  it('shows the actual packet, separate budgets, source reasons and stale predecessor', async () => {
    const fetchStudioApi = vi.fn(async (path: string) => {
      if (path.startsWith('/document')) return {
        path: chapter().path, title: '第一章', content: '当前正文', version: 'v1', revision: 'sha256:current',
      }
      if (path.startsWith('/context')) return {
        markdown: '## 作者意图\n\n人物不能违背承诺。',
        manifest: {
          packet_revision: 'packet-new', source_revision: 'sources-new', estimated_tokens: 960,
          freshness: { status: 'current' },
          previous_freshness: {
            status: 'stale', previous_revision: 'packet-old', current_revision: 'packet-new',
          },
          request_budget: {
            scope: 'openwrite_writing_request', available: true, input_budget_tokens: 3200,
            reserved_output_tokens: 800, actual_usage: { reported: false },
          },
          session_budget: {
            scope: 'dsh_session', available: false, reason: 'not_reported_by_session_runtime',
          },
          retrieval: { status: 'unavailable', results: 0 },
          items: [{
            section: 'creative_focus', status: 'selected', estimated_tokens: 18,
            snippet: '本章必须在雨夜完成关系反转。', selection_reason: 'active_author_focus',
            protected: true, protection_reason: 'author_hard_constraint', revision: 'focus-rev',
            sources: [{ path: 'src/story/current_focus.md', exists: true, revision: 'source-rev' }],
          }],
          missing_items: [{ section: 'chapter_requirements', reason: 'source_missing_or_empty', protected: true }],
          excluded_items: [{ section: 'style_documents', reason: 'input_budget' }],
        },
      }
      if (path.startsWith('/revisions')) return { proposals: [] }
      if (path.startsWith('/manuscript/versions')) return { versions: [] }
      return {}
    })
    render(<CreationView {...(viewProps({ fetchStudioApi, putStudioApi: vi.fn() }) as never)} />)

    await screen.findByRole('textbox', { name: 'manuscript-editor' })
    fireEvent.click(screen.getByRole('button', { name: 'creation.showInspector' }))

    expect(await screen.findByText('packet-new')).not.toBeNull()
    expect(screen.getByText('creation.context.requestBudget')).not.toBeNull()
    expect(screen.getByText('960 / 3200 tokens')).not.toBeNull()
    expect(screen.getByText('creation.context.sessionBudget')).not.toBeNull()
    expect(screen.getByText(/packet-old/)).not.toBeNull()
    expect(screen.getByText('本章必须在雨夜完成关系反转。')).not.toBeNull()
    expect(screen.getByText('creation.context.protected')).not.toBeNull()
    expect(screen.getByText(/chapter_requirements/)).not.toBeNull()
    expect(screen.getByText(/style_documents/)).not.toBeNull()

    fireEvent.click(screen.getByRole('button', { name: /src\/story\/current_focus\.md/ }))
    expect(harness.setActiveChapter).toHaveBeenCalledWith('data/novels/demo/src/story/current_focus.md')
  })

  it('sends the displayed packet revision when source epochs refresh', async () => {
    let contextCalls = 0
    const fetchStudioApi = vi.fn(async (path: string) => {
      if (path.startsWith('/document')) return {
        path: chapter().path, title: '第一章', content: '当前正文', version: 'v1', revision: 'sha256:current',
      }
      if (path.startsWith('/context')) {
        contextCalls += 1
        return {
          markdown: '## 作者意图\n\n约束',
          manifest: {
            packet_revision: contextCalls === 1 ? 'packet-one' : 'packet-two',
            freshness: { status: 'current' },
            previous_freshness: { status: contextCalls === 1 ? 'current' : 'stale' },
            request_budget: {}, session_budget: {}, retrieval: {},
            items: [{ section: 'author_intent', revision: `r${String(contextCalls)}` }],
          },
        }
      }
      if (path.startsWith('/revisions')) return { proposals: [] }
      if (path.startsWith('/manuscript/versions')) return { versions: [] }
      return {}
    })
    const props = viewProps({ fetchStudioApi, putStudioApi: vi.fn() })
    const view = render(<CreationView {...(props as never)} />)
    await screen.findByRole('textbox', { name: 'manuscript-editor' })
    fireEvent.click(screen.getByRole('button', { name: 'creation.showInspector' }))
    expect(await screen.findByText('packet-one')).not.toBeNull()

    harness.snapshot = {
      ...harness.snapshot,
      epochs: { ...harness.snapshot.epochs, assets: 1 },
    }
    view.rerender(<CreationView {...(props as never)} />)
    expect(await screen.findByText('packet-two')).not.toBeNull()
    expect(fetchStudioApi).toHaveBeenCalledWith('/context?chapter=ch_001&known_revision=packet-one&known_source_revision=')
  })

  it('offers protected source documents when the request budget cannot fit them', async () => {
    const fetchStudioApi = vi.fn(async (path: string) => {
      if (path.startsWith('/document')) return {
        path: chapter().path, title: '第一章', content: '当前正文', version: 'v1', revision: 'sha256:current',
      }
      if (path.startsWith('/context')) throw new StudioApiError(
        '受保护上下文超过预算，请提高预算或精简来源。',
        422,
        'PROTECTED_CONTEXT_OVER_BUDGET',
        { source_paths: ['src/story/current_focus.md', 'src/outline.md'] },
      )
      return { proposals: [], versions: [] }
    })
    render(<CreationView {...(viewProps({ fetchStudioApi, putStudioApi: vi.fn() }) as never)} />)
    await screen.findByRole('textbox', { name: 'manuscript-editor' })
    fireEvent.click(screen.getByRole('button', { name: 'creation.showInspector' }))

    expect(await screen.findByText(/受保护上下文超过预算/)).not.toBeNull()
    fireEvent.click(screen.getByRole('button', { name: 'src/story/current_focus.md' }))
    expect(harness.setActiveChapter).toHaveBeenCalledWith('data/novels/demo/src/story/current_focus.md')
  })

  it('switches packet sources and request budget with the Workspace and chapter', async () => {
    const fetchStudioApi = vi.fn(async (path: string) => {
      const workspaceId = (harness.snapshot.context as { workspaceId: string }).workspaceId
      if (path.startsWith('/document')) return {
        path: harness.snapshot.activeChapterPath, title: workspaceId, content: workspaceId,
        version: `${workspaceId}-v1`, revision: `${workspaceId}-r1`,
      }
      if (path.startsWith('/context')) {
        const isA = workspaceId === 'ws-a'
        return {
          markdown: `## 作者意图\n\n${workspaceId}`,
          manifest: {
            packet_revision: isA ? 'packet-a' : 'packet-b',
            source_revision: isA ? 'source-a' : 'source-b',
            estimated_tokens: isA ? 100 : 200,
            freshness: { status: 'current' }, request_budget: {
              available: true, input_budget_tokens: isA ? 1000 : 2000, actual_usage: {},
            },
            session_budget: {}, retrieval: {}, items: [{
              section: 'creative_focus', revision: isA ? 'item-a' : 'item-b',
              snippet: isA ? 'Workspace A focus' : 'Workspace B focus',
              sources: [{ path: isA ? 'src/story/a.md' : 'src/story/b.md', exists: true }],
            }],
          },
        }
      }
      return { proposals: [], versions: [] }
    })
    const props = viewProps({ fetchStudioApi, putStudioApi: vi.fn() })
    const view = render(<CreationView {...(props as never)} />)
    await screen.findByRole('textbox', { name: 'manuscript-editor' })
    fireEvent.click(screen.getByRole('button', { name: 'creation.showInspector' }))
    expect(await screen.findByText('packet-a')).not.toBeNull()
    expect(screen.getByText('100 / 1000 tokens')).not.toBeNull()
    expect(screen.getByRole('button', { name: /src\/story\/a\.md/ })).not.toBeNull()

    const nextPath = 'data/novels/demo/data/manuscript/ch_002.md'
    setSnapshot('ws-b', nextPath, 2)
    await act(async () => {
      view.rerender(<CreationView {...({ ...props, sessionId: 'session-ws-b' } as never)} />)
      await Promise.resolve()
    })

    expect(await screen.findByText('packet-b')).not.toBeNull()
    expect(screen.getByText('200 / 2000 tokens')).not.toBeNull()
    expect(screen.getByRole('button', { name: /src\/story\/b\.md/ })).not.toBeNull()
    expect(screen.queryByText('packet-a')).toBeNull()
  })
})

describe('CreationView recovery drafts', () => {
  const recoveryDraft = (overrides: Record<string, unknown> = {}) => ({
    key: 'draft-key',
    formatVersion: 1,
    workspaceId: 'ws-a',
    novelId: 'demo',
    path: chapter().path,
    baseRevision: 'r1',
    content: '本地恢复稿',
    updatedAt: 1_788_000_000_000,
    ...overrides,
  })

  it('offers a matching-base draft for preview and explicit recovery without replacing server text first', async () => {
    harness.draftStore.load.mockResolvedValue(recoveryDraft())
    const fetchStudioApi = vi.fn(async () => ({
      path: chapter().path, title: '第一章', content: '服务器正文', version: 'v1', revision: 'r1',
    }))
    const putStudioApi = vi.fn()
    render(<CreationView {...(viewProps({ fetchStudioApi, putStudioApi }) as never)} />)

    const editor = await screen.findByRole<HTMLTextAreaElement>('textbox', { name: 'manuscript-editor' })
    expect(editor.value).toBe('服务器正文')
    const restore = await screen.findByRole('button', { name: 'creation.draft.restore' })
    expect(editor.value).toBe('服务器正文')
    fireEvent.click(screen.getByText('creation.draft.preview'))
    expect(screen.getByText('本地恢复稿')).not.toBeNull()

    fireEvent.click(restore)
    expect(screen.getByRole<HTMLTextAreaElement>('textbox', { name: 'manuscript-editor' }).value).toBe('本地恢复稿')
    expect(harness.setEditorStatus).toHaveBeenLastCalledWith('dirty')
  })

  it('marks a stale-base recovery as a conflict and never autosaves it', async () => {
    harness.draftStore.load.mockResolvedValue(recoveryDraft({ baseRevision: 'old-r1' }))
    const fetchStudioApi = vi.fn(async () => ({
      path: chapter().path, title: '第一章', content: '服务器新版本', version: 'v2', revision: 'r2',
    }))
    const putStudioApi = vi.fn()
    render(<CreationView {...(viewProps({ fetchStudioApi, putStudioApi }) as never)} />)

    const editor = await screen.findByRole<HTMLTextAreaElement>('textbox', { name: 'manuscript-editor' })
    expect(await screen.findByText('creation.draft.conflict')).not.toBeNull()
    vi.useFakeTimers()
    fireEvent.click(screen.getByRole('button', { name: 'creation.draft.restore' }))
    await act(async () => { await vi.advanceTimersByTimeAsync(1_200) })

    expect(screen.getByRole<HTMLTextAreaElement>('textbox', { name: 'manuscript-editor' }).value).toBe('本地恢复稿')
    expect(harness.setEditorStatus).toHaveBeenLastCalledWith('conflict', 'creation.draft.conflict')
    expect(putStudioApi).not.toHaveBeenCalled()
  })

  it('loads same-path drafts by Workspace and work identity', async () => {
    harness.draftStore.load.mockImplementation(async (identity: { workspaceId: string }) =>
      recoveryDraft({
        workspaceId: identity.workspaceId,
        content: identity.workspaceId === 'ws-a' ? 'A 的恢复稿' : 'B 的恢复稿',
      }))
    const fetchStudioApi = vi.fn(async () => ({
      path: chapter().path, title: '第一章', content: '服务器正文', version: 'v1', revision: 'r1',
    }))
    const putStudioApi = vi.fn()
    const props = viewProps({ fetchStudioApi, putStudioApi })
    const view = render(<CreationView {...(props as never)} />)

    expect(await screen.findByText('A 的恢复稿')).not.toBeNull()
    setSnapshot('ws-b', chapter().path, 2)
    await act(async () => {
      view.rerender(<CreationView {...({ ...props, sessionId: 'session-ws-b' } as never)} />)
      await Promise.resolve()
    })
    expect(await screen.findByText('B 的恢复稿')).not.toBeNull()
    expect(screen.queryByText('A 的恢复稿')).toBeNull()
    expect(harness.draftStore.load).toHaveBeenCalledWith(expect.objectContaining({
      workspaceId: 'ws-a', novelId: 'demo', path: chapter().path,
    }))
    expect(harness.draftStore.load).toHaveBeenCalledWith(expect.objectContaining({
      workspaceId: 'ws-b', novelId: 'demo', path: chapter().path,
    }))
  })

  it('shows unavailable recovery protection without losing the editor content', async () => {
    harness.draftStore.save.mockRejectedValue(new Error('quota denied'))
    const fetchStudioApi = vi.fn(async () => ({
      path: chapter().path, title: '第一章', content: '初稿', version: 'v1', revision: 'r1',
    }))
    const putStudioApi = vi.fn(() => new Promise(() => undefined))
    render(<CreationView {...(viewProps({ fetchStudioApi, putStudioApi }) as never)} />)

    const editor = await screen.findByRole<HTMLTextAreaElement>('textbox', { name: 'manuscript-editor' })
    fireEvent.change(editor, { target: { value: '存储失败仍保留' } })

    expect(await screen.findByText('creation.draft.unavailable')).not.toBeNull()
    expect(editor.value).toBe('存储失败仍保留')
  })

  it('does not read or write a shared draft slot when no Workspace is bound', async () => {
    harness.snapshot = { ...harness.snapshot, context: null }
    const fetchStudioApi = vi.fn(async () => ({
      path: chapter().path, title: '第一章', content: '初稿', version: 'v1', revision: 'r1',
    }))
    const putStudioApi = vi.fn()
    render(<CreationView {...(viewProps({ fetchStudioApi, putStudioApi }) as never)} />)

    const editor = await screen.findByRole('textbox', { name: 'manuscript-editor' })
    fireEvent.change(editor, { target: { value: '未绑定正文' } })
    await act(async () => { await Promise.resolve() })

    expect(harness.draftStore.load).not.toHaveBeenCalled()
    expect(harness.draftStore.save).not.toHaveBeenCalled()
  })

  it('does not let an older save response clear a newer recovery draft', async () => {
    let stored: Record<string, unknown> | null = null
    harness.draftStore.save.mockImplementation(async (record: Record<string, unknown>) => {
      stored = record
    })
    harness.draftStore.removeIfContent.mockImplementation(async (_identity: unknown, content: string) => {
      if (stored?.['content'] !== content) return false
      stored = null
      return true
    })
    const first = deferred<unknown>()
    const second = deferred<unknown>()
    const fetchStudioApi = vi.fn(async () => ({
      path: chapter().path, title: '第一章', content: '初稿', version: 'v1', revision: 'r1',
    }))
    const putStudioApi = vi.fn()
      .mockImplementationOnce(() => first.promise)
      .mockImplementationOnce(() => second.promise)
    render(<CreationView {...(viewProps({ fetchStudioApi, putStudioApi }) as never)} />)

    const editor = await screen.findByRole('textbox', { name: 'manuscript-editor' })
    vi.useFakeTimers()
    fireEvent.change(editor, { target: { value: '稿件 A' } })
    await act(async () => { await vi.advanceTimersByTimeAsync(1_200) })
    fireEvent.change(editor, { target: { value: '稿件 B' } })
    await act(async () => {
      first.resolve({ path: chapter().path, title: '第一章', content: '稿件 A', version: 'v2', revision: 'r2' })
      await first.promise
      await Promise.resolve()
      await Promise.resolve()
    })

    expect(stored?.['content']).toBe('稿件 B')
    expect(putStudioApi).toHaveBeenCalledTimes(2)

    await act(async () => {
      second.resolve({ path: chapter().path, title: '第一章', content: '稿件 B', version: 'v3', revision: 'r3' })
      await second.promise
      await Promise.resolve()
      await Promise.resolve()
    })
    expect(stored).toBeNull()
  })
})
