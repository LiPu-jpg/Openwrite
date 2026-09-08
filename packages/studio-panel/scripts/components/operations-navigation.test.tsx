import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { OperationsView } from '../../src/client/OperationsView.tsx'

const harness = vi.hoisted(() => ({ contextEpoch: 1, workspaceGroup: 0 }))
vi.mock('../../src/client/WorkbenchStore.ts', () => ({
  useWorkbench: () => ({ context: { workspaceId: `ws-${harness.workspaceGroup}-${harness.contextEpoch}`, root: `/root/${harness.workspaceGroup}/${harness.contextEpoch}` }, contextEpoch: harness.contextEpoch, activeTasks: 0, epochs: { models: 0, benchmark: 0, research: 0 } }),
  workbenchStore: { setContext: vi.fn(), refresh: vi.fn(), invalidate: vi.fn() },
}))
vi.mock('../../src/client/workspace-context.ts', () => ({ useBindStudioContext: vi.fn(), createNovelWorkspace: vi.fn(), initWorkspaceProject: vi.fn() }))
vi.mock('../../src/client/TasksView.tsx', () => ({ TasksView: () => <div>tasks-panel</div> }))
vi.mock('../../src/client/BenchmarkView.tsx', () => ({ BenchmarkView: () => <div>benchmark-panel</div> }))
vi.mock('../../src/client/ResearchView.tsx', () => ({ ResearchView: () => <div>research-panel</div> }))
vi.mock('../../src/client/TransferWorkspaces.tsx', () => ({ ManuscriptImportWorkspace: () => null, ProjectArchiveWorkspace: () => null }))

const t = (key: string) => key
const envelope = (data: unknown) => ({ ok: true, data, error: null, request_id: 'navigation-test' })
const profile = {
  id: 'writer-a', label: 'Writer A', provider: 'openai', model: 'test-model',
  base_url: 'https://example.invalid', api_format: 'chat', context_tokens: 64000,
  max_output_tokens: 8000, temperature: 0.7, timeout_seconds: 120, configured: true,
}
const embedding = {
  id: 'embed-a', label: 'Embedding A', provider: 'openai', model: 'test-embedding',
  base_url: 'https://example.invalid', dimension: 1536, max_tokens: 8192, configured: true, active: true,
}
function makeProps() {
  return {
    t,
    fetchStudioApi: vi.fn(async () => envelope({
      profiles: [harness.contextEpoch === 1 ? profile : { ...profile, label: 'Writer in new workspace' }, { ...profile, id: 'writer-b', label: 'Writer B' }],
      embedding_profiles: [embedding], active_embedding_profile_id: 'embed-a',
      routes: { chapter_write: 'writer-a', review: 'writer-b' },
    })),
    postStudioApi: vi.fn(async (_path: string, _body: unknown) => envelope({})),
    putStudioApi: vi.fn(),
  }
}
async function openModels(props = makeProps()) {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const view = render(<OperationsView {...(props as any)} />)
  fireEvent.click(screen.getByRole('button', { name: 'view.models' }))
  await screen.findByLabelText('models.label')
  return { ...view, props }
}
beforeEach(() => { harness.contextEpoch = 1; harness.workspaceGroup += 1 })

describe('Operations model navigation protects drafts', () => {
  it('leaves a clean model editor directly and only mounts the active workbench', async () => {
    const { props } = await openModels()
    expect(screen.queryByText('tasks-panel')).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: 'view.tasks' }))
    expect(screen.getByText('tasks-panel')).toBeTruthy()
    expect(screen.queryByLabelText('models.label')).toBeNull()
    expect(screen.queryByText('models.unsavedChanges')).toBeNull()
    expect(props.postStudioApi).not.toHaveBeenCalled()
  })

  it.each(['chat', 'embedding', 'routes'] as const)('keeps %s edits until navigation is explicitly confirmed', async kind => {
    const { props } = await openModels()
    let edited: HTMLInputElement | HTMLSelectElement
    let expected: string
    if (kind === 'embedding') {
      fireEvent.click(screen.getByRole('button', { name: 'Embedding', exact: true }))
      edited = screen.getByLabelText('models.label') as HTMLInputElement
      expected = 'Edited embedding'
    } else if (kind === 'routes') {
      edited = screen.getByLabelText('models.route.review') as HTMLSelectElement
      expected = 'writer-a'
    } else {
      edited = screen.getByLabelText('models.label') as HTMLInputElement
      expected = 'Edited writer'
    }
    fireEvent.change(edited, { target: { value: expected } })
    fireEvent.click(screen.getByRole('button', { name: 'view.tasks' }))
    expect(screen.getByText('models.unsavedChanges')).toBeTruthy()
    expect(document.activeElement).toBe(screen.getByRole('alert'))
    expect(screen.queryByText('tasks-panel')).toBeNull()
    expect(edited.value).toBe(expected)
    fireEvent.click(screen.getByRole('button', { name: 'models.unsavedKeep' }))
    expect(edited.value).toBe(expected)
    expect(screen.queryByText('models.unsavedChanges')).toBeNull()

    fireEvent.click(screen.getByRole('button', { name: 'view.benchmark' }))
    fireEvent.click(screen.getByRole('button', { name: 'models.unsavedDiscard' }))
    expect(screen.getByText('benchmark-panel')).toBeTruthy()
    expect(screen.queryByLabelText('models.label')).toBeNull()
    expect(props.postStudioApi).not.toHaveBeenCalled()
  })

  it('blocks conflicting navigation while a save is pending', async () => {
    const props = makeProps()
    let release!: (value: ReturnType<typeof envelope>) => void
    props.postStudioApi.mockImplementation(() => new Promise(resolve => { release = resolve }))
    await openModels(props)
    fireEvent.change(screen.getByLabelText('models.label'), { target: { value: 'Edited writer' } })
    fireEvent.click(screen.getByRole('button', { name: 'models.save' }))
    fireEvent.click(screen.getByRole('button', { name: 'view.tasks' }))
    expect(screen.queryByText('tasks-panel')).toBeNull()
    expect(screen.queryByText('models.unsavedChanges')).toBeNull()
    await act(async () => { release(envelope({})) })
    await waitFor(() => expect((screen.getByRole('button', { name: 'models.save' }) as HTMLButtonElement).disabled).toBe(false))
    fireEvent.click(screen.getByRole('button', { name: 'view.tasks' }))
    expect(screen.getByText('tasks-panel')).toBeTruthy()
  })

  it('resets the editor and pending navigation at the workspace context barrier', async () => {
    const { props, rerender } = await openModels()
    fireEvent.change(screen.getByLabelText('models.label'), { target: { value: 'Old workspace draft' } })
    fireEvent.click(screen.getByRole('button', { name: 'view.tasks' }))
    expect(screen.getByText('models.unsavedChanges')).toBeTruthy()
    harness.contextEpoch = 2
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    rerender(<OperationsView {...(props as any)} />)
    expect(screen.getByText('tasks-panel')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'view.models' }))
    await waitFor(() => expect((screen.getByLabelText('models.label') as HTMLInputElement).value).toBe('Writer in new workspace'))
    expect(screen.queryByText('models.unsavedChanges')).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: 'view.tasks' }))
    expect(screen.getByText('tasks-panel')).toBeTruthy()
    expect(props.postStudioApi).not.toHaveBeenCalled()
  })
})


describe('Top-level tab changes retain model drafts in workspace memory', () => {
  function returnToOperations(props: ReturnType<typeof makeProps>) {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    return render(<OperationsView {...(props as any)} />)
  }
  const credential = () => document.querySelector<HTMLInputElement>('input[type="password"]')!

  it('restores the model page, both editors, credentials, and original dirty route baseline after unmount', async () => {
    const storageWrite = vi.spyOn(Storage.prototype, 'setItem')
    const { props, unmount } = await openModels()
    fireEvent.click(screen.getByRole('button', { name: /Writer B/ }))
    fireEvent.change(screen.getByLabelText('models.label'), { target: { value: 'Chat draft' } })
    fireEvent.change(credential(), { target: { value: 'test-chat-key-memory-only' } })
    fireEvent.change(screen.getByLabelText('models.route.review'), { target: { value: 'writer-a' } })
    fireEvent.click(screen.getByRole('button', { name: 'Embedding', exact: true }))
    fireEvent.change(screen.getByLabelText('models.label'), { target: { value: 'Embedding draft' } })
    fireEvent.change(credential(), { target: { value: 'test-embedding-key-memory-only' } })
    unmount()

    returnToOperations(props)
    await waitFor(() => expect((screen.getByLabelText('models.label') as HTMLInputElement).value).toBe('Embedding draft'))
    expect(credential().value).toBe('test-embedding-key-memory-only')
    expect(screen.getByRole('button', { name: 'view.models' }).getAttribute('aria-current')).toBe('page')
    fireEvent.click(screen.getByRole('button', { name: 'Chat', exact: true }))
    expect((screen.getByLabelText('models.label') as HTMLInputElement).value).toBe('Chat draft')
    expect((screen.getByLabelText('models.id') as HTMLInputElement).value).toBe('writer-b')
    expect(credential().value).toBe('test-chat-key-memory-only')
    expect((screen.getByLabelText('models.route.review') as HTMLSelectElement).value).toBe('writer-a')
    fireEvent.click(screen.getByRole('button', { name: 'view.tasks' }))
    expect(screen.getByText('models.unsavedChanges')).toBeTruthy()
    expect(storageWrite).not.toHaveBeenCalled()
    expect(props.postStudioApi).not.toHaveBeenCalled()
  })

  it('does not revive explicitly discarded editor drafts or credentials', async () => {
    const { props, unmount } = await openModels()
    fireEvent.change(screen.getByLabelText('models.label'), { target: { value: 'Discard this draft' } })
    fireEvent.change(credential(), { target: { value: 'test-discarded-key' } })
    fireEvent.change(screen.getByLabelText('models.route.review'), { target: { value: 'writer-a' } })
    fireEvent.click(screen.getByRole('button', { name: 'view.tasks' }))
    fireEvent.click(screen.getByRole('button', { name: 'models.unsavedDiscard' }))
    unmount()
    returnToOperations(props)
    expect(screen.getByText('tasks-panel')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'view.models' }))
    await screen.findByLabelText('models.label')
    expect((screen.getByLabelText('models.label') as HTMLInputElement).value).toBe('Writer A')
    expect(credential().value).toBe('')
    expect((screen.getByLabelText('models.route.review') as HTMLSelectElement).value).toBe('writer-b')
    fireEvent.click(screen.getByRole('button', { name: 'view.tasks' }))
    expect(screen.queryByText('models.unsavedChanges')).toBeNull()
  })

  it('clears a saved profile draft while retaining independent unsaved routes', async () => {
    const { props, unmount } = await openModels()
    fireEvent.change(screen.getByLabelText('models.label'), { target: { value: 'Saved draft' } })
    fireEvent.change(credential(), { target: { value: 'test-saved-key' } })
    fireEvent.change(screen.getByLabelText('models.route.review'), { target: { value: 'writer-a' } })
    fireEvent.click(screen.getByRole('button', { name: 'models.save' }))
    await screen.findByText('models.saved')
    unmount()
    returnToOperations(props)
    await screen.findByLabelText('models.label')
    expect(credential().value).toBe('')
    expect((screen.getByLabelText('models.route.review') as HTMLSelectElement).value).toBe('writer-a')
    fireEvent.click(screen.getByRole('button', { name: 'view.tasks' }))
    expect(screen.getByText('models.unsavedChanges')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'models.unsavedKeep' }))
    // Reverting to the original route baseline makes the restored editor clean.
    fireEvent.change(screen.getByLabelText('models.route.review'), { target: { value: 'writer-b' } })
    fireEvent.click(screen.getByRole('button', { name: 'view.tasks' }))
    expect(screen.getByText('tasks-panel')).toBeTruthy()
  })

  it('removes submitted credentials if the save finishes after its view unmounts', async () => {
    const props = makeProps()
    let release!: (value: ReturnType<typeof envelope>) => void
    props.postStudioApi.mockImplementation(() => new Promise(resolve => { release = resolve }))
    const view = await openModels(props)
    fireEvent.change(credential(), { target: { value: 'test-key-in-flight' } })
    fireEvent.click(screen.getByRole('button', { name: 'models.save' }))
    view.unmount()
    await act(async () => { release(envelope({})) })
    returnToOperations(props)
    await screen.findByLabelText('models.label')
    expect(credential().value).toBe('')
    fireEvent.click(screen.getByRole('button', { name: 'view.tasks' }))
    expect(screen.getByText('tasks-panel')).toBeTruthy()
  })

  it('waits for an earlier save when returning before that request completes', async () => {
    const props = makeProps()
    let release!: (value: ReturnType<typeof envelope>) => void
    props.postStudioApi.mockImplementation(() => new Promise(resolve => { release = resolve }))
    const view = await openModels(props)
    fireEvent.change(credential(), { target: { value: 'test-key-returned-while-saving' } })
    fireEvent.click(screen.getByRole('button', { name: 'models.save' }))
    view.unmount()
    returnToOperations(props)
    expect(screen.getByText('loading')).toBeTruthy()
    expect(screen.queryByRole('button', { name: 'models.save' })).toBeNull()
    await act(async () => { release(envelope({})) })
    await screen.findByLabelText('models.label')
    expect(credential().value).toBe('')
    expect(props.postStudioApi).toHaveBeenCalledTimes(1)
    fireEvent.click(screen.getByRole('button', { name: 'view.tasks' }))
    expect(screen.getByText('tasks-panel')).toBeTruthy()
  })

  it('isolates workspaces while restoring the earlier workspace when it returns', async () => {
    const first = await openModels()
    fireEvent.change(screen.getByLabelText('models.label'), { target: { value: 'Workspace one draft' } })
    fireEvent.change(credential(), { target: { value: 'workspace-one-test-key' } })
    first.unmount()
    harness.contextEpoch = 2
    const second = await openModels(first.props)
    expect((screen.getByLabelText('models.label') as HTMLInputElement).value).toBe('Writer in new workspace')
    expect(credential().value).toBe('')
    second.unmount()
    harness.contextEpoch = 1
    returnToOperations(first.props)
    await waitFor(() => expect((screen.getByLabelText('models.label') as HTMLInputElement).value).toBe('Workspace one draft'))
    expect(credential().value).toBe('workspace-one-test-key')
  })
})
