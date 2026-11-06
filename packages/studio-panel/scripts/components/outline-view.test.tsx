import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { OutlineView } from '../../src/client/OutlineView.tsx'

const outline = {
  revision: 'outline-1',
  roots: [{
    id: 'ch_001', kind: 'chapter', title: '第一章', status: 'drafted', children: [],
    promise: 'A -> B', summary: '旧摘要', metadata: {}, editable: true,
  }],
  counts: { chapters: 1, planned: 0, drafted: 1 }, drafted_chapters: 1, recommendation: '',
}

function makeApi() {
  const fetchStudioApi = vi.fn(async (path: string) => {
    if (path === '/outline') return outline
    return { data: {} }
  })
  const postStudioApi = vi.fn(async () => ({ ok: true, data: { revision: 'outline-2' } }))
  return { fetchStudioApi, postStudioApi, t: (key: string) => key }
}

describe('OutlineView draft preservation', () => {
  it('keeps an uncommitted summary edit through a refresh', async () => {
    // A refresh click, a 409 conflict reload or a post-merge reload used to clear
    // the drafts, silently reverting the summary the author was still typing.
    const api = makeApi()
    render(<OutlineView {...(api as never)} />)
    fireEvent.click(await screen.findByTitle('outline.addAfter'))
    const summary = await screen.findByDisplayValue('旧摘要')
    fireEvent.change(summary, { target: { value: '作者正在输入的新摘要' } })
    expect((summary as HTMLTextAreaElement).value).toBe('作者正在输入的新摘要')

    fireEvent.click(screen.getByRole('button', { name: 'refresh' }))

    await waitFor(() => expect(api.fetchStudioApi.mock.calls.length).toBeGreaterThan(1))
    const after = await screen.findByDisplayValue('作者正在输入的新摘要')
    expect((after as HTMLTextAreaElement).value).toBe('作者正在输入的新摘要')
    // The server's own value must not have overwritten the draft either.
    expect(screen.queryByDisplayValue('旧摘要')).toBeNull()
  })

  it('commits the edited summary with the revision it loaded', async () => {
    // The companion assertion to preservation: the draft must actually reach the
    // server, not merely survive a refresh inside the browser.
    const api = makeApi()
    render(<OutlineView {...(api as never)} />)
    fireEvent.click(await screen.findByTitle('outline.addAfter'))
    const summary = await screen.findByDisplayValue('旧摘要')
    fireEvent.change(summary, { target: { value: '作者提交的新摘要' } })
    fireEvent.blur(summary)
    await waitFor(() => expect(api.postStudioApi).toHaveBeenCalled())
    const call = api.postStudioApi.mock.calls
      .map(args => args as [string, unknown])
      .find(([path]) => path === '/outline/edit')
    expect(call, 'the edited summary must reach /outline/edit').toBeTruthy()
    expect(JSON.stringify(call![1])).toContain('作者提交的新摘要')
  })
})
