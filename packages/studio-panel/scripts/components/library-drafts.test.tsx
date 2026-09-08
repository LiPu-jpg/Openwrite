import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { LibraryView } from '../../src/client/LibraryView.tsx'
import { StudioApiError } from '../../src/client/api.ts'
import { readAssetDraft, removeAssetDraft } from '../../src/client/asset-drafts.ts'

const harness = vi.hoisted(() => ({
  contextEpoch: 1,
  assetsEpoch: 0,
  revisionSuffix: '',
  contexts: [
    { workspaceId: 'draft-book-one', root: '/draft/book-one' },
    { workspaceId: 'draft-book-two', root: '/draft/book-two' },
  ],
}))
vi.mock('../../src/client/WorkbenchStore.ts', () => ({
  useWorkbench: () => ({ context: harness.contexts[harness.contextEpoch - 1], contextEpoch: harness.contextEpoch, epochs: { assets: harness.assetsEpoch, outline: 0, graph: 0, research: 0, workspace: 0 } }),
}))
vi.mock('../../src/client/workspace-context.ts', () => ({ useBindStudioContext: () => null }))
vi.mock('@deepseek-ai/dsh-client-ui-primitives', () => ({ MarkdownText: ({ text }: { text: string }) => <span>{text}</span> }))
vi.mock('../../src/client/OutlineView.tsx', () => ({ OutlineView: () => <p>Outline page</p> }))
vi.mock('../../src/client/GraphView.tsx', () => ({ GraphView: () => null }))
vi.mock('../../src/client/ResearchView.tsx', () => ({ ResearchView: () => null }))
vi.mock('../../src/client/SearchView.tsx', () => ({ SearchView: () => null }))
vi.mock('../../src/client/VditorBody.tsx', () => ({
  VditorBody: ({ initial, onChange, disabled }: { initial: string; onChange: (value: string) => void; disabled: boolean }) =>
    <textarea aria-label="Asset body" defaultValue={initial} disabled={disabled} onChange={event => onChange(event.target.value)} />,
}))

function makeProps() {
  const fetchStudioApi = vi.fn(async (path: string) => {
    if (path === '/assets') return { data: { assets: [
      { kind: 'character', id: 'a', name: 'Alice' }, { kind: 'character', id: 'b', name: 'Bob' },
    ] } }
    if (path === '/workspace') return {}
    const id = path.endsWith('/a') ? 'a' : 'b'
    return { data: {
      revision: `book-${harness.contextEpoch}-${id}${harness.revisionSuffix}`, name: id === 'a' ? 'Alice' : 'Bob',
      data: { related: [{ target: 'b', kind: 'related', note: 'Original relation' }] },
      body_markdown: `Book ${harness.contextEpoch} body ${id}`,
    } }
  })
  return { fetchStudioApi, postStudioApi: vi.fn(async () => ({ asset: { revision: 'saved' } })), t: (key: string) => key }
}

beforeEach(() => {
  harness.contextEpoch = 1; harness.assetsEpoch = 0; harness.revisionSuffix = ''
  for (const context of harness.contexts) for (const id of ['a', 'b']) removeAssetDraft({ ...context, kind: 'character', id })
})

describe('library draft protection', () => {
  it('clears a saved recovery without allowing an old save to erase newer edits', async () => {
    const props = makeProps()
    let finish!: (value: { asset: { revision: string } }) => void
    const pending = new Promise<{ asset: { revision: string } }>(resolve => { finish = resolve })
    props.postStudioApi.mockImplementationOnce(() => pending)
    const first = render(<LibraryView {...(props as never)} />)
    fireEvent.click(await screen.findByRole('button', { name: 'Alice' }))
    await screen.findByLabelText('Asset body')
    fireEvent.change(screen.getByLabelText('Asset body'), { target: { value: 'Submitted scene' } })
    fireEvent.click(screen.getByRole('button', { name: 'assets.edit.save' }))
    first.unmount()
    render(<LibraryView {...(props as never)} />)
    await screen.findByDisplayValue('Submitted scene')
    fireEvent.change(screen.getByLabelText('Asset body'), { target: { value: 'New scene after returning' } })
    await act(async () => { finish({ asset: { revision: 'saved' } }); await pending })
    expect(readAssetDraft({ ...harness.contexts[0]!, kind: 'character', id: 'a' })?.draft.bodyDraft).toBe('New scene after returning')
    fireEvent.click(screen.getByRole('button', { name: 'assets.edit.save' }))
    await waitFor(() => expect(readAssetDraft({ ...harness.contexts[0]!, kind: 'character', id: 'a' })).toBeNull())
  })

  it('restores selected asset, body, and relations after top-level tab unmount/remount', async () => {
    const props = makeProps()
    const first = render(<LibraryView {...(props as never)} />)
    fireEvent.click(await screen.findByRole('button', { name: 'Alice' }))
    await screen.findByLabelText('Asset body')
    fireEvent.change(screen.getByLabelText('Asset body'), { target: { value: 'Retain across top-level tabs' } })
    fireEvent.change(screen.getByDisplayValue('Original relation'), { target: { value: 'Retain relationship' } })
    first.unmount()
    render(<LibraryView {...(props as never)} />)
    await screen.findByDisplayValue('Retain across top-level tabs')
    expect(screen.getByDisplayValue('Retain relationship')).toBeTruthy()
    expect(screen.getByText('assets.draft.restored')).toBeTruthy()
    expect(props.postStudioApi).not.toHaveBeenCalled()
  })

  it('keeps the original revision when a recovered asset has changed on the server', async () => {
    const props = makeProps()
    const first = render(<LibraryView {...(props as never)} />)
    fireEvent.click(await screen.findByRole('button', { name: 'Alice' }))
    await screen.findByLabelText('Asset body')
    fireEvent.change(screen.getByLabelText('Asset body'), { target: { value: 'Draft based on original revision' } })
    first.unmount()
    harness.revisionSuffix = '-changed'
    render(<LibraryView {...(props as never)} />)
    await screen.findByDisplayValue('Draft based on original revision')
    expect(screen.getByText('assets.draft.conflict')).toBeTruthy()
    props.postStudioApi.mockRejectedValueOnce(new StudioApiError('Revision conflict', 409, 'ASSET_CONFLICT'))
    fireEvent.click(screen.getByRole('button', { name: 'assets.edit.save' }))
    await waitFor(() => expect(props.postStudioApi).toHaveBeenCalledWith('/assets/update', expect.objectContaining({
      id: 'a', revision: 'book-1-a', body_markdown: 'Draft based on original revision',
    })))
    expect(screen.getByDisplayValue('Draft based on original revision')).toBeTruthy()
  })

  it('removes the recovery only after explicit discard', async () => {
    const props = makeProps()
    const first = render(<LibraryView {...(props as never)} />)
    fireEvent.click(await screen.findByRole('button', { name: 'Alice' }))
    await screen.findByLabelText('Asset body')
    fireEvent.change(screen.getByLabelText('Asset body'), { target: { value: 'Draft to discard' } })
    fireEvent.click(screen.getByRole('button', { name: 'assets.edit.cancel' }))
    fireEvent.click(screen.getByRole('button', { name: 'models.unsavedDiscard' }))
    await screen.findByDisplayValue('Book 1 body a')
    first.unmount()
    render(<LibraryView {...(props as never)} />)
    await screen.findByRole('button', { name: 'Alice' })
    expect(screen.queryByDisplayValue('Draft to discard')).toBeNull()
    expect(screen.queryByText('assets.draft.restored')).toBeNull()
  })

  it('keeps unsaved body and relation changes through background updates and declined page switches', async () => {
    const props = makeProps()
    const view = render(<LibraryView {...(props as never)} />)
    fireEvent.click(await screen.findByRole('button', { name: 'Alice' }))
    await screen.findByDisplayValue('Book 1 body a')
    fireEvent.change(screen.getByLabelText('Asset body'), { target: { value: 'My unsaved scene' } })
    fireEvent.change(screen.getByDisplayValue('Original relation'), { target: { value: 'My unsaved relationship' } })
    harness.assetsEpoch += 1
    view.rerender(<LibraryView {...(props as never)} />)
    await waitFor(() => expect(props.fetchStudioApi.mock.calls.filter(([path]) => path === '/assets')).toHaveLength(2))
    expect(screen.getByDisplayValue('My unsaved scene')).toBeTruthy()
    expect(screen.getByDisplayValue('My unsaved relationship')).toBeTruthy()
    const confirm = vi.spyOn(window, 'confirm')
    fireEvent.click(screen.getByRole('button', { name: 'view.outline' }))
    expect(screen.getByRole('alertdialog')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'models.unsavedKeep' }))
    expect(screen.queryByText('Outline page')).toBeNull()
    expect(screen.getByDisplayValue('My unsaved scene')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'view.outline' }))
    fireEvent.click(screen.getByRole('button', { name: 'models.unsavedDiscard' }))
    expect(screen.getByText('Outline page')).toBeTruthy()
    expect(props.postStudioApi).not.toHaveBeenCalled()
    expect(confirm).not.toHaveBeenCalled()
  })

  it('protects local work on a different asset or category selection', async () => {
    const props = makeProps()
    render(<LibraryView {...(props as never)} />)
    fireEvent.click(await screen.findByRole('button', { name: 'Alice' }))
    await screen.findByLabelText('Asset body')
    fireEvent.change(screen.getByLabelText('Asset body'), { target: { value: 'Keep this body' } })
    const confirm = vi.spyOn(window, 'confirm')
    fireEvent.click(screen.getByRole('button', { name: 'Bob' }))
    fireEvent.click(screen.getByRole('button', { name: 'models.unsavedKeep' }))
    expect(screen.getByDisplayValue('Keep this body')).toBeTruthy()
    expect(props.fetchStudioApi).not.toHaveBeenCalledWith('/assets/character/b')
    fireEvent.click(screen.getByRole('button', { name: /assets.segment.world/ }))
    fireEvent.click(screen.getByRole('button', { name: 'models.unsavedKeep' }))
    expect(screen.getByDisplayValue('Keep this body')).toBeTruthy()
    expect(confirm).not.toHaveBeenCalled()
  })

  it('keeps the draft visible when a background refresh fails', async () => {
    const props = makeProps()
    const view = render(<LibraryView {...(props as never)} />)
    fireEvent.click(await screen.findByRole('button', { name: 'Alice' }))
    await screen.findByLabelText('Asset body')
    fireEvent.change(screen.getByLabelText('Asset body'), { target: { value: 'Offline draft' } })
    props.fetchStudioApi.mockRejectedValueOnce(new Error('Refresh unavailable'))
    harness.assetsEpoch += 1
    view.rerender(<LibraryView {...(props as never)} />)
    await screen.findByRole('alert')
    expect(screen.getByDisplayValue('Offline draft')).toBeTruthy()
  })

  it('retains the draft after a save conflict instead of refetching and erasing it', async () => {
    const props = makeProps()
    props.postStudioApi.mockRejectedValueOnce(new StudioApiError('Asset changed elsewhere', 409, 'ASSET_CONFLICT'))
    render(<LibraryView {...(props as never)} />)
    fireEvent.click(await screen.findByRole('button', { name: 'Alice' }))
    await screen.findByLabelText('Asset body')
    fireEvent.change(screen.getByLabelText('Asset body'), { target: { value: 'Conflicted local scene' } })
    fireEvent.click(screen.getByRole('button', { name: 'assets.edit.save' }))
    await screen.findByText('Asset changed elsewhere')
    expect(screen.getByDisplayValue('Conflicted local scene')).toBeTruthy()
    expect(props.fetchStudioApi.mock.calls.filter(([path]) => path === '/assets/character/a')).toHaveLength(1)
    fireEvent.click(screen.getByRole('button', { name: 'assets.edit.conflictRefresh' }))
    fireEvent.click(screen.getByRole('button', { name: 'models.unsavedKeep' }))
    expect(screen.getByDisplayValue('Conflicted local scene')).toBeTruthy()
  })

  it('isolates drafts when the bound workspace changes', async () => {
    const props = makeProps()
    const view = render(<LibraryView {...(props as never)} />)
    fireEvent.click(await screen.findByRole('button', { name: 'Alice' }))
    await screen.findByLabelText('Asset body')
    fireEvent.change(screen.getByLabelText('Asset body'), { target: { value: 'Only in book one' } })
    harness.contextEpoch += 1
    view.rerender(<LibraryView {...(props as never)} />)
    fireEvent.click(await screen.findByRole('button', { name: 'Alice' }))
    await screen.findByDisplayValue('Book 2 body a')
    expect(screen.queryByDisplayValue('Only in book one')).toBeNull()
    expect(props.postStudioApi).not.toHaveBeenCalled()
    harness.contextEpoch = 1
    view.rerender(<LibraryView {...(props as never)} />)
    await screen.findByDisplayValue('Only in book one')
  })
})
