/**
 * Workspace context UI layer (contract §9, offline).
 *
 * - WorkspaceContextChip reflects the session's dsh Workspace binding: the
 *   workspace title when bound, the unbound hint otherwise, and it owns
 *   binding the resolved context into the WorkbenchStore barrier.
 * - OperationsView's transfer panel replaces the old project switcher with a
 *   read-only workspace block; a bound-but-uninitialized workspace (store
 *   reports WORKSPACE_NOT_INITIALIZED) gets the onboarding form whose submit
 *   POSTs /project/init with the workspace's canonical absolute path.
 *
 * WorkbenchStore is mocked to a controllable snapshot; the components under
 * test never touch the network (all Studio API faces are vi.fn stubs).
 */
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { WorkspaceContextChip } from '../../src/client/HeaderChrome.tsx'
import { OperationsView } from '../../src/client/OperationsView.tsx'

/** Mutable store state shared with the WorkbenchStore mock. */
const harness = vi.hoisted(() => ({
  workspaceError: null as string | null,
  setContext: vi.fn(),
  refresh: vi.fn(),
  invalidate: vi.fn(),
}))

vi.mock('../../src/client/WorkbenchStore.ts', () => ({
  useWorkbench: () => ({
    connection: 'online',
    context: { workspaceId: 'ws-a', root: '/root/a' },
    contextEpoch: 1,
    workspaceError: harness.workspaceError,
    projectTitle: '',
    currentChapterId: '',
    activeChapterPath: '',
    chapters: [],
    workspace: null,
    tasks: null,
    activeTasks: 0,
    editorStatus: 'idle',
    editorMessage: '',
    epochs: {
      workspace: 0, manuscript: 0, outline: 0, assets: 0,
      tasks: 0, benchmark: 0, models: 0, dag: 0, graph: 0, research: 0, revisions: 0,
    },
    lastUpdatedAt: 0,
  }),
  workbenchStore: {
    setContext: harness.setContext,
    refresh: harness.refresh,
    invalidate: harness.invalidate,
  },
}))

vi.mock('@deepseek-ai/dsh-client-ui-primitives', () => ({
  MarkdownText: ({ text }: { text: string }) => <div>{text}</div>,
}))

const t = (key: string): string => key

beforeEach(() => {
  harness.workspaceError = null
  harness.setContext.mockClear()
  harness.refresh.mockClear()
  harness.invalidate.mockClear()
})

const WORKSPACE = {
  workspaceId: 'ws-a',
  path: '/root/a',
  title: '我的小说',
  sessionIds: ['s1'],
  createdAt: '2026-08-30T00:00:00Z',
  updatedAt: '2026-08-30T00:00:00Z',
}

function workspacesState(items: readonly unknown[]) {
  return { items, archivedSessionIds: [], state: 'idle', phase: 'ready', error: null, baselinesReady: true, recentWorkspaceId: undefined }
}

function chipProps(sessionId: string | undefined) {
  return {
    sessionId,
    useWorkspaces: (sel: (state: ReturnType<typeof workspacesState>) => unknown) => sel(workspacesState([WORKSPACE])),
    postStudioApi: vi.fn(async () => ({})),
    workspaces: {
      pickDirectory: vi.fn(async () => '/picked/dir'),
      create: vi.fn(async () => ({ workspaceId: 'ws-new', path: '/picked/dir' })),
      connectWorkspace: vi.fn(async () => 's-new'),
    },
    sessions: { open: vi.fn() },
    t,
  }
}

describe('WorkspaceContextChip', () => {
  it('renders the bound workspace title and binds the store context', () => {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    render(<WorkspaceContextChip {...(chipProps('s1') as any)} />)
    expect(screen.getByText('我的小说')).toBeTruthy()
    expect(harness.setContext).toHaveBeenCalledWith({ workspaceId: 'ws-a', root: '/root/a', sessionId: 's1' })
  })

  it('shows the unbound hint when the session has no workspace', () => {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    render(<WorkspaceContextChip {...(chipProps('s-unaccounted') as any)} />)
    expect(screen.getByText('workspace.unbound')).toBeTruthy()
    expect(harness.setContext).toHaveBeenCalledWith(null)
  })

  it('opens the attach popover for an unbound session and drives the dsh workspace flow', async () => {
    const props = chipProps('s-unaccounted')
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    render(<WorkspaceContextChip {...(props as any)} />)

    fireEvent.click(screen.getByText('workspace.unbound'))
    await screen.findByText('workspace.bind.hint')
    fireEvent.click(screen.getByText('workspace.bind.pick'))

    await waitFor(() => expect(props.workspaces.create).toHaveBeenCalledWith({ path: '/picked/dir' }))
    await waitFor(() => expect(props.workspaces.connectWorkspace).toHaveBeenCalledWith('ws-new'))
    expect(props.sessions.open).toHaveBeenCalledWith('s-new')
  })

  it('opens the inline init form for a bound-but-uninitialized workspace and inits at its canonical path', async () => {
    harness.workspaceError = 'WORKSPACE_NOT_INITIALIZED'
    const props = chipProps('s1')
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    render(<WorkspaceContextChip {...(props as any)} />)

    fireEvent.click(screen.getByText('workspace.notInitialized'))
    await screen.findByText('operations.init.hint')
    fireEvent.change(screen.getByPlaceholderText('my-novel'), { target: { value: 'my_novel' } })
    fireEvent.change(screen.getByPlaceholderText('operations.create.titleHint'), { target: { value: '新书' } })
    fireEvent.click(screen.getByText('operations.init.submit'))

    await waitFor(() => expect(props.postStudioApi).toHaveBeenCalledWith('/project/init', {
      project_path: '/root/a',
      novel_id: 'my_novel',
      title: '新书',
    }))
    await waitFor(() => expect(harness.refresh).toHaveBeenCalled())
  })
})

function operationsProps() {
  const postStudioApi = vi.fn(async () => ({}))
  const props = {
    sessionId: 's1',
    useWorkspaces: (sel: (state: ReturnType<typeof workspacesState>) => unknown) => sel(workspacesState([WORKSPACE])),
    fetchStudioApi: vi.fn(async () => ({ data: { tasks: [], counts: {} } })),
    postStudioApi,
    putStudioApi: vi.fn(async () => ({})),
    workspaces: { pickDirectory: vi.fn(), create: vi.fn(), connectWorkspace: vi.fn() },
    sessions: { open: vi.fn() },
    t,
  }
  return { props, postStudioApi }
}

describe('OperationsView workspace block', () => {
  it('shows the onboarding form for an uninitialized workspace and inits with its canonical path', async () => {
    harness.workspaceError = 'WORKSPACE_NOT_INITIALIZED'
    const { props, postStudioApi } = operationsProps()
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    render(<OperationsView {...(props as any)} />)

    fireEvent.click(screen.getByText('operations.transfer'))
    await screen.findByText('operations.init.hint')
    // Read-only workspace state: title and canonical path, no project list.
    expect(screen.getByText('我的小说')).toBeTruthy()
    expect(screen.getByText('/root/a')).toBeTruthy()

    fireEvent.change(screen.getByPlaceholderText('my-novel'), { target: { value: 'my_novel' } })
    fireEvent.change(screen.getByPlaceholderText('operations.create.titleHint'), { target: { value: '新书' } })
    fireEvent.click(screen.getByText('operations.init.submit'))

    await waitFor(() => expect(postStudioApi).toHaveBeenCalledWith('/project/init', {
      project_path: '/root/a',
      novel_id: 'my_novel',
      title: '新书',
    }))
    await waitFor(() => expect(harness.refresh).toHaveBeenCalled())
  })

  it('renders no onboarding form while the workspace is initialized', async () => {
    harness.workspaceError = null
    const { props } = operationsProps()
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    render(<OperationsView {...(props as any)} />)

    fireEvent.click(screen.getByText('operations.transfer'))
    await screen.findByText('我的小说')
    expect(screen.queryByText('operations.init.hint')).toBeNull()
  })
})
