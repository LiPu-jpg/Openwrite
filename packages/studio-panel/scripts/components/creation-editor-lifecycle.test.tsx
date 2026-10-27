import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { CreationView } from '../../src/client/CreationView.tsx'
import { instances } from './stubs/vditor-runtime.ts'

const harness = vi.hoisted(() => ({
  snapshot: {} as Record<string, any>,
  save: vi.fn(), remove: vi.fn(),
}))
vi.mock('../../src/client/WorkbenchStore.ts', () => ({
  useWorkbench: () => harness.snapshot,
  workbenchStore: { getSnapshot: () => harness.snapshot, setEditorStatus: vi.fn(), invalidate: vi.fn(), setActiveChapter: vi.fn() },
}))
vi.mock('../../src/client/workspace-context.ts', () => ({ useBindStudioContext: () => undefined }))
vi.mock('../../src/client/draft-store.ts', async original => ({
  ...await original<typeof import('../../src/client/draft-store.ts')>(),
  manuscriptDraftStore: { load: vi.fn(async () => null), save: harness.save, removeIfContent: harness.remove },
}))
vi.mock('@deepseek-ai/dsh-client-ui-primitives', () => ({ MarkdownText: ({ text }: { text: string }) => <div>{text}</div> }))

const path = 'data/novels/demo/data/manuscript/ch_001.md'
function setup() {
  const fetchStudioApi = vi.fn(async (url: string) => {
    if (!url.startsWith('/document')) return {}
    const documentPath = decodeURIComponent(url.split('path=')[1]!)
    return { path: documentPath, title: '第一章', content: `${harness.snapshot.context.workspaceId} ${documentPath.includes('ch_002') ? '第二章' : '初稿'}\n`, version: 'v1', revision: 'r1' }
  })
  const putStudioApi = vi.fn(async (_url: string, body: Record<string, unknown>) => ({ ...body, title: '第一章', version: 'v2', revision: 'r2' }))
  const props = { fetchStudioApi, putStudioApi, postStudioApi: vi.fn(async () => ({})),
    sessionId: 'session-a', useWorkspaces: vi.fn(), t: (key: string) => key }
  return { props, view: render(<CreationView {...(props as never)} />) }
}
beforeEach(() => {
  harness.snapshot = { context: { workspaceId: 'ws-a', root: '/isolated/a', sessionId: 'session-a' }, contextEpoch: 1,
    epochs: { workspace: 0, manuscript: 0, outline: 0, assets: 0, tasks: 0, revisions: 0 }, connection: 'online',
    activeChapterPath: path, currentChapterId: 'ch_001', chapters: [], workspace: null, tasks: null,
    activeTasks: 0, editorStatus: 'saved', editorMessage: '', writingProgress: { bookUnits: 0, bookTarget: 1000, chapterTarget: 100 } }
  harness.save.mockReset().mockResolvedValue(undefined)
  harness.remove.mockReset().mockResolvedValue(true)
  instances.length = 0
  vi.stubGlobal('Lute', {})
  vi.stubGlobal('VditorI18n', {})
})

describe('manuscript lifecycle before the editor input callback', () => {
  it('leaves untouched source alone when the editor unmounts', async () => {
    const { view } = setup()
    await screen.findByLabelText('Live asset body')
    view.unmount()
    expect(harness.save).not.toHaveBeenCalled()
  })

  it('retains the last undelivered input on immediate unmount', async () => {
    const { view } = setup()
    fireEvent.input(await screen.findByLabelText('Live asset body'), { target: { value: '最后一段\n' } })
    view.unmount()
    await waitFor(() => expect(harness.save).toHaveBeenCalledWith(expect.objectContaining({ workspaceId: 'ws-a', path, content: '最后一段\n' })))
  })

  it.each([false, true])('enables Save on first input and drains it (blur=%s)', async blur => {
    const { props } = setup()
    const editor = await screen.findByLabelText('Live asset body')
    fireEvent.input(editor, { target: { value: '手动保存最后一段\n' } })
    if (blur) fireEvent.focusOut(editor)
    expect(screen.getByRole<HTMLButtonElement>('button', { name: 'creation.status.saved' }).disabled).toBe(false)
    fireEvent.click(screen.getByRole('button', { name: 'creation.status.saved' }))
    await waitFor(() => expect(props.putStudioApi).toHaveBeenCalledWith('/document', expect.objectContaining({ content: '手动保存最后一段\n', save_origin: 'manual' }), expect.objectContaining({ workspaceId: 'ws-a' })))
  })

  it('drains the final input even without a preceding blur event', async () => {
    const { props } = setup()
    const editor = await screen.findByLabelText('Live asset body')
    fireEvent.input(editor, { target: { value: '已回调\n' } })
    await act(async () => { instances.at(-1)!.deliverInput() })
    fireEvent.input(editor, { target: { value: '最后输入尚未回调\n' } })
    fireEvent.click(screen.getByRole('button', { name: 'creation.status.saved' }))
    await waitFor(() => expect(props.putStudioApi).toHaveBeenCalledWith('/document', expect.objectContaining({ content: '最后输入尚未回调\n' }), expect.anything()))
  })

  it.each(['workspace', 'chapter'])('keeps the final draft with its original %s identity', async change => {
    const { props, view } = setup()
    fireEvent.input(await screen.findByLabelText('Live asset body'), { target: { value: '只属于第一处的输入\n' } })
    const old = instances.at(-1)!
    if (change === 'workspace') harness.snapshot = { ...harness.snapshot, contextEpoch: 2,
      context: { workspaceId: 'ws-b', root: '/isolated/b', sessionId: 'session-b' } }
    else harness.snapshot = { ...harness.snapshot, activeChapterPath: path.replace('ch_001', 'ch_002') }
    view.rerender(<CreationView {...(props as never)} />)
    await waitFor(() => expect(screen.getByLabelText<HTMLTextAreaElement>('Live asset body').value).toBe(change === 'workspace' ? 'ws-b 初稿\n' : 'ws-a 第二章\n'))
    await act(async () => { old.deliverInput() })
    await waitFor(() => expect(harness.save).toHaveBeenCalledWith(expect.objectContaining({ workspaceId: 'ws-a', path, content: '只属于第一处的输入\n' })))
    expect(harness.save.mock.calls.every(([item]) => item.workspaceId === 'ws-a' && item.path === path)).toBe(true)
    expect(props.putStudioApi).not.toHaveBeenCalled()
  })

  it('does not resurrect discarded input during reload cleanup', async () => {
    const { props, view } = setup()
    const editor = await screen.findByLabelText('Live asset body')
    fireEvent.input(editor, { target: { value: '明确放弃\n' } })
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    harness.snapshot = { ...harness.snapshot, editorStatus: 'conflict' }
    view.rerender(<CreationView {...(props as never)} />)
    fireEvent.click(screen.getByRole('button', { name: 'creation.reload' }))
    await waitFor(() => expect(screen.getByLabelText<HTMLTextAreaElement>('Live asset body').value).toBe('ws-a 初稿\n'))
    view.unmount()
    await waitFor(() => expect(harness.remove).toHaveBeenCalledWith(expect.objectContaining({ path }), '明确放弃\n'))
    const calls = harness.save.mock.calls.length
    await act(async () => { await Promise.resolve() })
    expect(harness.save).toHaveBeenCalledTimes(calls)
  })

  it('does not discard another workspace draft when its document failed to load', async () => {
    const { props, view } = setup()
    const editor = await screen.findByLabelText('Live asset body')
    fireEvent.input(editor, { target: { value: '原工作区未回调的输入\n' } })
    const fetch = props.fetchStudioApi.getMockImplementation()!
    props.fetchStudioApi.mockImplementation(async url => {
      if (url.startsWith('/document') && harness.snapshot.context.workspaceId === 'ws-b') throw Error('fixture unavailable')
      return fetch(url)
    })
    harness.snapshot = { ...harness.snapshot, contextEpoch: 2, context: { workspaceId: 'ws-b', root: '/isolated/b', sessionId: 'session-b' } }
    view.rerender(<CreationView {...(props as never)} />)
    fireEvent.click(await screen.findByRole('button', { name: 'retry' }))
    await waitFor(() => expect(props.fetchStudioApi.mock.calls.filter(([url]) => url.startsWith('/document')).length).toBe(3))
    await act(async () => { await Promise.resolve() })
    expect(harness.remove.mock.calls.some(([identity]) => identity.workspaceId === 'ws-b')).toBe(false)
  })
})
