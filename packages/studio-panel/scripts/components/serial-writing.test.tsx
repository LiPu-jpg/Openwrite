import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { SerialWritingView } from '../../src/client/SerialWritingView.tsx'
import { StudioApiError } from '../../src/client/api.ts'

const audit = {
  chapters: [{ chapter_id: 'ch_001', promise: 'A -> B', function: ['推进'], payoff_of: [], word_budget: 1000, actual_words: 800, manuscript_status: 'current' }],
  available_groups: [{ id: 'sec_001', title: 'First section' }], group_id: '', outline_revision: 'outline-1',
  ledger: { revision: 3, entries: [], groups: {} }, words: { planned: 1000, actual: 800 },
}
function api() {
  const fetchStudioApi = vi.fn(async (path: string) => {
    if (path === '/writing-assets') return { assets: { terms: [{ term: '钥匙', min_occurrences: 1 }], character_groups: {}, overlap_threshold: .05, review_terms: true }, revision: 'assets-1', anchors: [] }
    if (path === '/status') return { instance_id: 'instance-one', project_path: '/my_novel', port: 1234 }
    if (path.startsWith('/outline/audit')) return audit
    if (path.endsWith('/metrics')) return { metrics: { hanzi_count: 800, paragraph_count: 5 }, overlap: { references: [{ source: 'anchor/style.md', ratio: .2, flagged: true, spans: [{ text: 'A matching sentence from the anchor.' }] }] } }
    throw new Error('Unexpected read: ' + path)
  })
  const postStudioApi = vi.fn(async () => ({ ok: true, data: { assets: { terms: [] }, revision: 'assets-2', ...audit } }))
  return { fetchStudioApi, postStudioApi, t: (key: string) => key }
}

describe('serial-writing workbench', () => {
  it('shows identity and measured overlap without a model request', async () => {
    const props = api()
    render(<SerialWritingView {...props} />)
    expect(await screen.findByText(/instance-one/)).toBeTruthy()
    await screen.findByDisplayValue('A -> B')
    const chapterSelect = screen.getAllByRole('combobox', { name: 'serial.chapter' })[0]!
    fireEvent.change(chapterSelect, { target: { value: 'ch_001' } })
    expect(await screen.findByText('A matching sentence from the anchor.')).toBeTruthy()
    expect(props.postStudioApi).not.toHaveBeenCalled()
  })

  it('saves edited terminology with the revision it loaded', async () => {
    const props = api()
    render(<SerialWritingView {...props} />)
    const term = await screen.findByDisplayValue('钥匙')
    fireEvent.change(term, { target: { value: '密钥' } })
    fireEvent.click(screen.getByRole('button', { name: /serial.saveAssets/ }))
    await waitFor(() => expect(props.postStudioApi).toHaveBeenCalledWith('/writing-assets', expect.objectContaining({ expected_revision: 'assets-1', assets: expect.objectContaining({ terms: [expect.objectContaining({ term: '密钥' })] }) })))
  })

  it('saves a chapter promise through the existing outline revision check', async () => {
    const props = api()
    render(<SerialWritingView {...props} />)
    const promise = await screen.findByDisplayValue('A -> B')
    fireEvent.change(promise, { target: { value: 'A -> C' } })
    fireEvent.click(screen.getByRole('button', { name: 'serial.saveOutline' }))
    await waitFor(() => expect(props.postStudioApi).toHaveBeenCalledWith('/outline/edit', {
      operation: 'set_meta', revision: 'outline-1', updates: [{ node_id: 'ch_001', metadata: { promise: 'A -> C' } }],
    }))
  })

  it('re-pulls the audit and explains a revision conflict instead of surfacing the raw server error', async () => {
    // Every write here is revision-gated. Without a 409 branch the raw server
    // message was shown and the stale expected_revision was kept, so retrying
    // conflicted again with no way forward.
    const props = api()
    props.postStudioApi = vi.fn(async () => {
      throw new StudioApiError('OUTLINE_REVISION_CONFLICT', 409, 'OUTLINE_REVISION_CONFLICT')
    })
    render(<SerialWritingView {...props} />)
    const promise = await screen.findByDisplayValue('A -> B')
    fireEvent.change(promise, { target: { value: 'A -> C' } })
    fireEvent.click(screen.getByRole('button', { name: /serial.saveOutline/ }))
    await waitFor(() => expect(props.postStudioApi).toHaveBeenCalled())
    await waitFor(() => expect(props.fetchStudioApi).toHaveBeenCalledWith(
      expect.stringContaining('/outline/audit'),
    ))
    expect((await screen.findByRole('alert')).textContent).toBe('serial.conflictReload')
    // The stale edit must not be left looking saved.
    expect(screen.queryByText('serial.saved')).toBeNull()
  })
})
