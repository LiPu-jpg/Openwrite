import { act, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { SearchView } from '../../src/client/SearchView.tsx'
import { StudioApiError } from '../../src/client/api.ts'

const harness = vi.hoisted(() => ({
  setActiveChapter: vi.fn(),
  invalidate: vi.fn(),
  snapshot: {
    chapters: [{ path: 'data/manuscript/arc_001/ch_001.md' }],
  },
}))

vi.mock('../../src/client/WorkbenchStore.ts', () => ({
  useWorkbench: () => harness.snapshot,
  workbenchStore: { setActiveChapter: harness.setActiveChapter, invalidate: harness.invalidate },
}))

const t = (key: string): string => key

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>(resolvePromise => { resolve = resolvePromise })
  return { promise, resolve }
}

beforeEach(() => {
  harness.setActiveChapter.mockClear()
  harness.invalidate.mockClear()
})

afterEach(() => {
  vi.useRealTimers()
})

describe('SearchView revision-bound preview', () => {
  it('retains document identity, reports a stale locator, and selects the chapter for editing', async () => {
    vi.useFakeTimers()
    const chapterPath = 'data/manuscript/arc_001/ch_001.md'
    const fetchStudioApi = vi.fn(async (url: string) => {
      if (url.startsWith('/search')) return {
        query: '雨夜', indexed: 1,
        results: [{
          document_id: 'doc-chapter-one', revision: 'revision-indexed', path: chapterPath,
          title: '命中标题', line: 2, heading: '雨夜', snippet: '雨夜中的脚步',
          scope_label: '正文', category_label: '章节',
        }],
      }
      if (url.startsWith('/document')) return {
        document_id: 'doc-chapter-one', revision: 'revision-current', path: chapterPath,
        title: '命中标题', content: '第一行\n雨夜中的新脚步\n第三行', version: 'v2',
      }
      throw new Error(`unexpected ${url}`)
    })
    render(<SearchView {...({
      fetchStudioApi, postStudioApi: vi.fn(), putStudioApi: vi.fn(),
      sessionId: 'session-a', useWorkspaces: vi.fn(), t,
    } as never)} />)

    fireEvent.change(screen.getByRole('searchbox'), { target: { value: '雨夜' } })
    await act(async () => { await vi.advanceTimersByTimeAsync(350) })
    const resultTitle = screen.getByText('命中标题')
    fireEvent.click(resultTitle.closest('button')!)
    await act(async () => { await Promise.resolve() })

    expect(screen.getByText('search.preview.locatorStale')).not.toBeNull()
    expect(screen.getByText('doc-chapter-one')).not.toBeNull()
    expect(screen.getByText('revision-current')).not.toBeNull()
    expect(screen.getByText('search.change.unavailable')).not.toBeNull()
    expect(screen.queryByRole('button', { name: 'search.change.preview' })).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: 'search.preview.openCreation' }))
    expect(harness.setActiveChapter).toHaveBeenCalledWith(chapterPath)
    expect(screen.getByText('search.preview.jumpReady')).not.toBeNull()
  })

  it('does not claim locator freshness when search results omit revision', async () => {
    vi.useFakeTimers()
    const chapterPath = 'data/manuscript/arc_001/ch_001.md'
    const fetchStudioApi = vi.fn(async (url: string) => url.startsWith('/search')
      ? { query: '灯', indexed: 1, results: [{ path: chapterPath, title: '灯下', line: 1, snippet: '灯' }] }
      : { path: chapterPath, title: '灯下', content: '灯下', version: 'v1', revision: 'revision-current' })
    render(<SearchView {...({
      fetchStudioApi, postStudioApi: vi.fn(), putStudioApi: vi.fn(),
      sessionId: 'session-a', useWorkspaces: vi.fn(), t,
    } as never)} />)

    fireEvent.change(screen.getByRole('searchbox'), { target: { value: '灯' } })
    await act(async () => { await vi.advanceTimersByTimeAsync(350) })
    const resultTitle = screen.getByText('灯下')
    fireEvent.click(resultTitle.closest('button')!)
    await act(async () => { await Promise.resolve() })

    expect(screen.getByText('search.preview.locatorUnverified')).not.toBeNull()
  })

  it('drops a late document response after the user switches search hits', async () => {
    vi.useFakeTimers()
    const first = deferred<unknown>()
    const second = deferred<unknown>()
    const revision = `sha256:${'a'.repeat(64)}`
    const fetchStudioApi = vi.fn(async (url: string) => {
      if (url.startsWith('/search')) return { query: '章', indexed: 2, results: [
        { document_id: 'doc-one', revision, path: 'data/manuscript/arc_001/ch_001.md', title: '第一章', line: 1, snippet: '一章' },
        { document_id: 'doc-two', revision, path: 'data/manuscript/arc_001/ch_002.md', title: '第二章', line: 1, snippet: '二章' },
      ] }
      return url.includes('ch_001') ? first.promise : second.promise
    })
    render(<SearchView {...({ fetchStudioApi, postStudioApi: vi.fn(), putStudioApi: vi.fn(), sessionId: 'session-a', useWorkspaces: vi.fn(), t } as never)} />)
    fireEvent.change(screen.getByRole('searchbox'), { target: { value: '章' } })
    await act(async () => { await vi.advanceTimersByTimeAsync(350) })
    fireEvent.click(screen.getByText('第一章').closest('button')!)
    fireEvent.click(screen.getByRole('button', { name: 'search.preview.back' }))
    fireEvent.click(screen.getByText('第二章').closest('button')!)
    await act(async () => {
      second.resolve({ document_id: 'doc-two', revision, path: 'data/manuscript/arc_001/ch_002.md', title: '第二章', content: '第二章正文' })
      await second.promise
    })
    await act(async () => {
      first.resolve({ document_id: 'doc-one', revision, path: 'data/manuscript/arc_001/ch_001.md', title: '第一章', content: '第一章正文' })
      await first.promise
    })
    expect(screen.getAllByText(/第二章正文/).length).toBeGreaterThan(0)
    expect(screen.queryAllByText(/第一章正文/)).toHaveLength(0)
  })

  it('previews and applies one exact hit line through the server-owned revision-gated plan', async () => {
    vi.useFakeTimers()
    const chapterPath = 'data/manuscript/arc_001/ch_001.md'
    const sourceRevision = `sha256:${'a'.repeat(64)}`
    const resultRevision = `sha256:${'b'.repeat(64)}`
    const fetchStudioApi = vi.fn(async (url: string) => url.startsWith('/search')
      ? { query: '雨夜', indexed: 1, results: [{
          document_id: 'doc-one', revision: sourceRevision, path: chapterPath, title: '第一章', line: 2, snippet: '雨夜中的脚步',
        }] }
      : { document_id: 'doc-one', revision: sourceRevision, path: chapterPath, title: '第一章', content: '第一行\n雨夜中的脚步\n第三行', version: 'v1' })
    const postStudioApi = vi.fn(async (_url: string, body: Record<string, unknown>) => body['action'] === 'preview'
      ? { data: {
          applied: false, changed: true, path: chapterPath, revision: sourceRevision.slice(-16), preview_token: 'preview-token-one',
          diff: '-雨夜中的脚步\n+雨夜中的急促脚步',
          mutation_summary: { execution_status: 'proposed', source_revision: sourceRevision, result_revision: resultRevision },
        } }
      : { data: {
          applied: true, changed: true, status: 'applied', path: chapterPath,
          mutation_summary: { execution_status: 'committed', source_revision: sourceRevision, result_revision: resultRevision },
        } })
    render(<SearchView {...({
      fetchStudioApi, postStudioApi, putStudioApi: vi.fn(), sessionId: 'session-a', useWorkspaces: vi.fn(), t,
    } as never)} />)

    fireEvent.change(screen.getByRole('searchbox'), { target: { value: '雨夜' } })
    await act(async () => { await vi.advanceTimersByTimeAsync(350) })
    fireEvent.click(screen.getByText('第一章').closest('button')!)
    await act(async () => { await Promise.resolve() })
    expect(screen.getByText('search.preview.locatorCurrent')).not.toBeNull()

    fireEvent.change(screen.getByRole('textbox', { name: 'search.change.replacement' }), { target: { value: '雨夜中的急促脚步' } })
    fireEvent.click(screen.getByRole('button', { name: 'search.change.preview' }))
    await act(async () => { await Promise.resolve() })
    expect(postStudioApi).toHaveBeenNthCalledWith(1, '/document/change-plan', {
      action: 'preview', path: chapterPath, edits: [{ old_text: '雨夜中的脚步', new_text: '雨夜中的急促脚步' }],
    })
    expect(screen.getByText(/\+雨夜中的急促脚步/)).not.toBeNull()

    fireEvent.click(screen.getByRole('button', { name: 'search.change.confirmApply' }))
    await act(async () => { await Promise.resolve() })
    expect(postStudioApi).toHaveBeenNthCalledWith(2, '/document/change-plan', {
      action: 'apply', preview_token: 'preview-token-one',
    })
    expect(screen.getByText('search.change.applied')).not.toBeNull()
    expect(harness.invalidate).toHaveBeenCalledWith('manuscript')
    expect(harness.invalidate).toHaveBeenCalledWith('workspace')
  })

  it('discards a preview whose source revision differs from the search result', async () => {
    vi.useFakeTimers()
    const chapterPath = 'data/manuscript/arc_001/ch_001.md'
    const sourceRevision = `sha256:${'a'.repeat(64)}`
    const fetchStudioApi = vi.fn(async (url: string) => url.startsWith('/search')
      ? { query: '灯下', indexed: 1, results: [{ document_id: 'doc-one', revision: sourceRevision, path: chapterPath, title: '第一章', line: 1, snippet: '灯下' }] }
      : { document_id: 'doc-one', revision: sourceRevision, path: chapterPath, title: '第一章', content: '灯下', version: 'v1' })
    const postStudioApi = vi.fn(async (_url: string, body: Record<string, unknown>) => body['action'] === 'preview'
      ? { data: {
          applied: false, changed: true, path: chapterPath, preview_token: 'mismatched-token', diff: 'diff',
          mutation_summary: { execution_status: 'proposed', source_revision: `sha256:${'c'.repeat(64)}`, result_revision: `sha256:${'d'.repeat(64)}` },
        } }
      : { data: { status: 'rejected' } })
    render(<SearchView {...({ fetchStudioApi, postStudioApi, putStudioApi: vi.fn(), sessionId: 'session-a', useWorkspaces: vi.fn(), t } as never)} />)

    fireEvent.change(screen.getByRole('searchbox'), { target: { value: '灯下' } })
    await act(async () => { await vi.advanceTimersByTimeAsync(350) })
    fireEvent.click(screen.getByText('第一章').closest('button')!)
    await act(async () => { await Promise.resolve() })
    fireEvent.change(screen.getByRole('textbox', { name: 'search.change.replacement' }), { target: { value: '灯灭' } })
    fireEvent.click(screen.getByRole('button', { name: 'search.change.preview' }))
    await act(async () => { await Promise.resolve(); await Promise.resolve() })

    expect(postStudioApi).toHaveBeenLastCalledWith('/document/change-plan', { action: 'reject', preview_token: 'mismatched-token' })
    expect(screen.getByText('search.change.refreshRequired')).not.toBeNull()
    expect(screen.queryByRole('button', { name: 'search.change.confirmApply' })).toBeNull()
  })

  it('stops apply on a document revision conflict and requires refreshed search evidence', async () => {
    vi.useFakeTimers()
    const chapterPath = 'data/manuscript/arc_001/ch_001.md'
    const sourceRevision = `sha256:${'a'.repeat(64)}`
    const resultRevision = `sha256:${'b'.repeat(64)}`
    const fetchStudioApi = vi.fn(async (url: string) => url.startsWith('/search')
      ? { query: '脚步', indexed: 1, results: [{ document_id: 'doc-one', revision: sourceRevision, path: chapterPath, title: '第一章', line: 1, snippet: '脚步' }] }
      : { document_id: 'doc-one', revision: sourceRevision, path: chapterPath, title: '第一章', content: '脚步', version: 'v1' })
    const postStudioApi = vi.fn()
      .mockResolvedValueOnce({ data: {
        applied: false, changed: true, path: chapterPath, preview_token: 'conflict-token', diff: 'diff',
        mutation_summary: { execution_status: 'proposed', source_revision: sourceRevision, result_revision: resultRevision },
      } })
      .mockRejectedValueOnce(new StudioApiError('changed', 409, 'DOCUMENT_REVISION_CONFLICT'))
      .mockResolvedValueOnce({ data: { status: 'rejected' } })
    render(<SearchView {...({ fetchStudioApi, postStudioApi, putStudioApi: vi.fn(), sessionId: 'session-a', useWorkspaces: vi.fn(), t } as never)} />)

    fireEvent.change(screen.getByRole('searchbox'), { target: { value: '脚步' } })
    await act(async () => { await vi.advanceTimersByTimeAsync(350) })
    fireEvent.click(screen.getByText('第一章').closest('button')!)
    await act(async () => { await Promise.resolve() })
    fireEvent.change(screen.getByRole('textbox', { name: 'search.change.replacement' }), { target: { value: '急促脚步' } })
    fireEvent.click(screen.getByRole('button', { name: 'search.change.preview' }))
    await act(async () => { await Promise.resolve() })
    fireEvent.click(screen.getByRole('button', { name: 'search.change.confirmApply' }))
    await act(async () => { await Promise.resolve(); await Promise.resolve() })

    expect(screen.getByText('search.change.refreshRequired')).not.toBeNull()
    expect(postStudioApi).toHaveBeenLastCalledWith('/document/change-plan', { action: 'reject', preview_token: 'conflict-token' })
    expect(harness.invalidate).toHaveBeenCalledWith('manuscript')
    expect(harness.invalidate).toHaveBeenCalledWith('workspace')
  })
})
