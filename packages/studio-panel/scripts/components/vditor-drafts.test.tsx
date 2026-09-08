import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { LibraryView } from '../../src/client/LibraryView.tsx'
import { readAssetDraft, removeAssetDraft } from '../../src/client/asset-drafts.ts'
import { instances } from './stubs/vditor-runtime.ts'

const harness = vi.hoisted(() => ({ contextEpoch: 1, contexts: [
  { workspaceId: 'live-book-one', root: '/live/book-one' },
  { workspaceId: 'live-book-two', root: '/live/book-two' },
] }))
vi.mock('../../src/client/WorkbenchStore.ts', () => ({
  useWorkbench: () => ({ context: harness.contexts[harness.contextEpoch - 1], contextEpoch: harness.contextEpoch, epochs: { assets: 0 } }),
}))
vi.mock('../../src/client/workspace-context.ts', () => ({ useBindStudioContext: () => null }))
vi.mock('@deepseek-ai/dsh-client-ui-primitives', () => ({ MarkdownText: ({ text }: { text: string }) => <span>{text}</span> }))
vi.mock('../../src/client/OutlineView.tsx', () => ({ OutlineView: () => <p>Outline page</p> }))
vi.mock('../../src/client/GraphView.tsx', () => ({ GraphView: () => null }))
vi.mock('../../src/client/ResearchView.tsx', () => ({ ResearchView: () => null }))
vi.mock('../../src/client/SearchView.tsx', () => ({ SearchView: () => null }))

const identity = (index = 0) => ({ ...harness.contexts[index]!, kind: 'character', id: 'a' })
function makeProps() {
  return {
    fetchStudioApi: vi.fn(async (path: string) => path === '/assets' ? { data: { assets: [{ kind: 'character', id: 'a', name: 'Alice' }] } }
      : path === '/workspace' ? {} : { data: { revision: `book-${harness.contextEpoch}`, name: 'Alice', data: {}, body_markdown: `Book ${harness.contextEpoch} original` } }),
    postStudioApi: vi.fn(async () => ({ asset: { revision: 'saved' } })),
    t: (key: string) => key,
  }
}
beforeEach(() => {
  harness.contextEpoch = 1
  removeAssetDraft(identity()); removeAssetDraft(identity(1)); instances.length = 0
  vi.stubGlobal('Lute', {})
  vi.stubGlobal('VditorI18n', {})
})

describe('live Vditor draft recovery before delayed input callbacks', () => {
  it('does not create a recovery when an untouched editor unmounts', async () => {
    const props = makeProps()
    const first = render(<LibraryView {...(props as never)} />)
    fireEvent.click(await screen.findByRole('button', { name: 'Alice' }))
    await screen.findByLabelText('Live asset body')
    first.unmount()
    expect(readAssetDraft(identity())).toBeNull()
  })

  it('flushes the last body before DOM removal and restores it after top-level remount', async () => {
    const props = makeProps()
    const first = render(<LibraryView {...(props as never)} />)
    fireEvent.click(await screen.findByRole('button', { name: 'Alice' }))
    const body = await screen.findByLabelText('Live asset body')
    fireEvent.input(body, { target: { value: 'Typed immediately before leaving' } })
    expect(readAssetDraft(identity())).toBeNull()
    first.unmount()
    expect(readAssetDraft(identity())?.draft.bodyDraft).toBe('Typed immediately before leaving')
    render(<LibraryView {...(props as never)} />)
    await screen.findByDisplayValue('Typed immediately before leaving')
    expect(screen.getByText('assets.draft.restored')).toBeTruthy()
    expect(props.postStudioApi).not.toHaveBeenCalled()
  })

  it('flushes on blur so an immediate save submits the latest body', async () => {
    const props = makeProps()
    render(<LibraryView {...(props as never)} />)
    fireEvent.click(await screen.findByRole('button', { name: 'Alice' }))
    const body = await screen.findByLabelText('Live asset body')
    fireEvent.input(body, { target: { value: 'Body at save click' } })
    fireEvent.focusOut(body)
    fireEvent.click(screen.getByRole('button', { name: 'assets.edit.save' }))
    await waitFor(() => expect(props.postStudioApi).toHaveBeenCalledWith('/assets/update', expect.objectContaining({ body_markdown: 'Body at save click' })))
    await waitFor(() => expect(readAssetDraft(identity())).toBeNull())
  })

  it('keeps deferred body input isolated across a workspace replacement', async () => {
    const props = makeProps()
    const view = render(<LibraryView {...(props as never)} />)
    fireEvent.click(await screen.findByRole('button', { name: 'Alice' }))
    fireEvent.input(await screen.findByLabelText('Live asset body'), { target: { value: 'First workspace only' } })
    const oldInstance = instances.at(-1)!
    harness.contextEpoch = 2
    view.rerender(<LibraryView {...(props as never)} />)
    fireEvent.click(await screen.findByRole('button', { name: 'Alice' }))
    await screen.findByDisplayValue('Book 2 original')
    act(() => { oldInstance.deliverInput() })
    expect(readAssetDraft(identity())?.draft.bodyDraft).toBe('First workspace only')
    expect(readAssetDraft(identity(1))).toBeNull()
    expect(screen.queryByDisplayValue('First workspace only')).toBeNull()
  })

  it('does not resurrect a discarded editor when pending input flushes at unmount', async () => {
    const props = makeProps()
    const view = render(<LibraryView {...(props as never)} />)
    fireEvent.click(await screen.findByRole('button', { name: 'Alice' }))
    const body = await screen.findByLabelText('Live asset body')
    fireEvent.input(body, { target: { value: 'First delivered change' } })
    act(() => { instances.at(-1)!.deliverInput() })
    fireEvent.input(body, { target: { value: 'Last undelivered change to discard' } })
    fireEvent.click(screen.getByRole('button', { name: 'view.outline' }))
    expect(screen.getByRole('alertdialog')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'models.unsavedDiscard' }))
    expect(screen.getByText('Outline page')).toBeTruthy()
    expect(readAssetDraft(identity())).toBeNull()
    view.unmount()
    render(<LibraryView {...(props as never)} />)
    await screen.findByRole('button', { name: 'Alice' })
    expect(screen.queryByText('assets.draft.restored')).toBeNull()
  })
})
