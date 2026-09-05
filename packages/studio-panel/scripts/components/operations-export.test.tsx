import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { OperationsView } from '../../src/client/OperationsView.tsx'
import { setStudioContext } from '../../src/client/api.ts'

const harness = vi.hoisted(() => ({ setContext: vi.fn(), refresh: vi.fn(), invalidate: vi.fn() }))

vi.mock('../../src/client/WorkbenchStore.ts', () => ({
  useWorkbench: () => ({
    connection: 'online', context: { workspaceId: 'ws-a', root: '/root/a' }, contextEpoch: 1,
    workspaceError: null, projectTitle: '', currentChapterId: '', activeChapterPath: '', chapters: [],
    workspace: null, tasks: null, activeTasks: 0, editorStatus: 'idle', editorMessage: '',
    epochs: { workspace: 0, manuscript: 0, outline: 0, assets: 0, tasks: 0, benchmark: 0, models: 0, dag: 0, graph: 0, research: 0, revisions: 0 },
    lastUpdatedAt: 0,
  }),
  workbenchStore: { setContext: harness.setContext, refresh: harness.refresh, invalidate: harness.invalidate },
}))

vi.mock('@deepseek-ai/dsh-client-ui-primitives', () => ({ MarkdownText: ({ text }: { text: string }) => <div>{text}</div> }))

const t = (key: string): string => key
const WORKSPACE = {
  workspaceId: 'ws-a', path: '/root/a', title: '我的小说', sessionIds: ['s1'],
  createdAt: '2026-08-30T00:00:00Z', updatedAt: '2026-08-30T00:00:00Z',
}

function preflight(overrides: Record<string, unknown> = {}) {
  return {
    ok: true,
    data: {
      schema_version: 'openwrite.export-preflight.v1', novel_id: 'demo', format: 'md', purpose: 'delivery',
      can_export: false, actual_order: ['ch_002', 'ch_001'],
      chapters: [
        { chapter_id: 'ch_002', number: 2, path: 'data/manuscript/ch_002.md', title: '第二章', writing_units: 1800, empty: false, revision: 'sha-2' },
        { chapter_id: 'ch_001', number: 1, path: 'data/manuscript/ch_001.md', title: '第一章', writing_units: 0, empty: true, revision: 'sha-1' },
      ],
      structure: { duplicates: { '1': ['ch_001', 'ch_001_copy'] }, missing: ['ch_003'], empty: ['ch_001'], unreadable: ['ch_004'] },
      writing_units: { total: 1800, book_target: 80000, chapter_target: 2500, completion_ratio: 0.0225 },
      metadata: { title: '测试书', author: '作者甲', language: 'zh-CN' },
      reviews: { missing: ['ch_003'], current: ['ch_002'], stale: ['ch_001'], approved: ['ch_002'], not_approved: ['ch_001'] },
      manuscript_acceptance: { status: 'needs_review', blocking: true, blocking_chapters: [], needs_review: ['outline', 'foreshadowing'] },
      blockers: [{ code: 'EMPTY_CHAPTER', message: '第一章正文为空' }],
      warnings: [{ code: 'STALE_REVIEW', message: '第一章复核已过期' }],
      preflight_revision: 'pf-rev-1',
      ...overrides,
    },
  }
}

function props(fetchStudioApi: ReturnType<typeof vi.fn>) {
  return {
    sessionId: 's1',
    useWorkspaces: (select: (state: unknown) => unknown) => select({ items: [WORKSPACE], archivedSessionIds: [], state: 'idle', phase: 'ready', error: null, baselinesReady: true }),
    fetchStudioApi,
    postStudioApi: vi.fn(async () => ({})), putStudioApi: vi.fn(async () => ({})),
    workspaces: { pickDirectory: vi.fn(), create: vi.fn(), connectWorkspace: vi.fn() }, sessions: { open: vi.fn() }, t,
  }
}

async function openTransfer(fetchStudioApi: ReturnType<typeof vi.fn>) {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  render(<OperationsView {...(props(fetchStudioApi) as any)} />)
  fireEvent.click(screen.getByText('operations.transfer'))
  await waitFor(() => expect(fetchStudioApi).toHaveBeenCalledWith('/export/preflight?format=md&purpose=delivery'))
}

beforeEach(() => {
  setStudioContext({ workspaceId: 'ws-a', sessionId: 's1' })
  harness.setContext.mockClear()
  harness.invalidate.mockClear()
})

describe('Operations export preflight', () => {
  it('renders the real preflight order, structure, targets, metadata, reviews, acceptance and issues', async () => {
    const fetchStudioApi = vi.fn(async () => preflight())
    await openTransfer(fetchStudioApi)

    expect((await screen.findAllByText('pf-rev-1')).length).toBeGreaterThan(0)
    expect(screen.getByText('第二章')).toBeTruthy()
    expect(screen.getByText('第一章')).toBeTruthy()
    expect(screen.getByText('data/manuscript/ch_002.md')).toBeTruthy()
    expect(screen.getByText('第一章正文为空')).toBeTruthy()
    expect(screen.getByText('第一章复核已过期')).toBeTruthy()
    expect(screen.getByText('测试书')).toBeTruthy()
    expect(screen.getByText('作者甲')).toBeTruthy()
    expect(screen.getByText('needs_review')).toBeTruthy()
    expect(screen.getByText('tools.export.acceptance.blockingState')).toBeTruthy()
    expect(screen.getByText('outline, foreshadowing')).toBeTruthy()
    expect((screen.getByRole('button', { name: 'tools.export.download' }) as HTMLButtonElement).disabled).toBe(true)
  })

  it('downloads only with the displayed preflight revision and selected purpose/format', async () => {
    const fetchStudioApi = vi.fn(async path => preflight({
      can_export: true,
      format: path.includes('format=epub') ? 'epub' : 'md',
      purpose: path.includes('purpose=backup') ? 'backup' : 'delivery',
      preflight_revision: 'pf-current-9', blockers: [],
    }))
    const downloadFetch = vi.fn(async () => new Response('book', {
      status: 200, headers: { 'content-disposition': "attachment; filename*=UTF-8''backup.epub" },
    }))
    vi.stubGlobal('fetch', downloadFetch)
    const NativeUrl = URL
    class DownloadUrl extends NativeUrl {
      static createObjectURL = vi.fn(() => 'blob:test')
      static revokeObjectURL = vi.fn()
    }
    vi.stubGlobal('URL', DownloadUrl)
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => undefined)

    await openTransfer(fetchStudioApi)
    fireEvent.click(screen.getByRole('button', { name: 'tools.export.purpose.backup' }))
    fireEvent.change(screen.getByLabelText('tools.export.format'), { target: { value: 'epub' } })
    await waitFor(() => expect(fetchStudioApi).toHaveBeenCalledWith('/export/preflight?format=epub&purpose=backup'))
    expect((await screen.findAllByText('pf-current-9')).length).toBeGreaterThan(0)
    fireEvent.click(screen.getByRole('button', { name: 'tools.export.download' }))

    await waitFor(() => expect(downloadFetch).toHaveBeenCalled())
    const url = new URL(String(downloadFetch.mock.calls[0]?.[0]), 'http://local.test')
    expect(url.pathname).toBe('/studio-panel/api/export')
    expect(url.searchParams.get('format')).toBe('epub')
    expect(url.searchParams.get('purpose')).toBe('backup')
    expect(url.searchParams.get('preflight_revision')).toBe('pf-current-9')
  })

  it('refreshes the preflight after a download revision conflict', async () => {
    let preflightReads = 0
    const fetchStudioApi = vi.fn(async path => {
      if (!path.startsWith('/export/preflight')) return { data: { tasks: [], counts: {} } }
      preflightReads += 1
      return preflight({ can_export: true, preflight_revision: preflightReads === 1 ? 'pf-old' : 'pf-new', blockers: [] })
    })
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({ code: 'EXPORT_PREFLIGHT_CONFLICT' }), {
      status: 409, headers: { 'content-type': 'application/json' },
    })))

    await openTransfer(fetchStudioApi)
    await screen.findByText('pf-old')
    fireEvent.click(screen.getByRole('button', { name: 'tools.export.download' }))

    await screen.findByText('tools.export.stale')
    await screen.findByText('pf-new')
    expect(preflightReads).toBe(2)
  })
})
