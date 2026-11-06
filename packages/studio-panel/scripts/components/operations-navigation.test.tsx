import { fireEvent, render, screen } from '@testing-library/react'
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
vi.mock('../../src/client/SerialWritingView.tsx', () => ({ SerialWritingView: () => <div>serial-panel</div> }))
vi.mock('../../src/client/TransferWorkspaces.tsx', () => ({ ManuscriptImportWorkspace: () => null, ProjectArchiveWorkspace: () => null }))

const t = (key: string) => key
const envelope = (data: unknown) => ({ ok: true, data, error: null, request_id: 'navigation-test' })
function makeProps() {
  return {
    t,
    fetchStudioApi: vi.fn(async () => envelope({})),
    postStudioApi: vi.fn(async () => envelope({})),
    putStudioApi: vi.fn(),
  }
}
function renderOperations(props = makeProps()) {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  return render(<OperationsView {...(props as any)} />)
}
beforeEach(() => { harness.contextEpoch = 1; harness.workspaceGroup += 1 })

describe('Operations navigation', () => {
  it('offers the doing pages and no longer offers the model editor', () => {
    renderOperations()
    // The model profile library is a setting: it lives in the host's settings
    // dialog under 「设置 → OpenWrite → 模型」, edited without a bound
    // workspace. The workbench must not carry a second copy of it.
    expect(screen.queryByRole('button', { name: 'view.models' })).toBeNull()
    expect(screen.getByRole('button', { name: 'view.tasks' })).toBeTruthy()
    expect(screen.getByRole('button', { name: 'view.benchmark' })).toBeTruthy()
    expect(screen.getByRole('button', { name: 'view.research' })).toBeTruthy()
    expect(screen.getByRole('button', { name: 'operations.transfer' })).toBeTruthy()
    expect(screen.getByRole('button', { name: 'serial.title' })).toBeTruthy()
  })

  it('mounts only the active page', () => {
    renderOperations()
    expect(screen.getByText('tasks-panel')).toBeTruthy()
    expect(screen.queryByText('benchmark-panel')).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: 'view.benchmark' }))
    expect(screen.getByText('benchmark-panel')).toBeTruthy()
    expect(screen.queryByText('tasks-panel')).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: 'view.research' }))
    expect(screen.getByText('research-panel')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'view.tasks' }))
    expect(screen.getByText('tasks-panel')).toBeTruthy()
  })

  it('marks the active page for assistive technology', () => {
    renderOperations()
    expect(screen.getByRole('button', { name: 'view.tasks' }).getAttribute('aria-current')).toBe('page')
    fireEvent.click(screen.getByRole('button', { name: 'view.research' }))
    expect(screen.getByRole('button', { name: 'view.research' }).getAttribute('aria-current')).toBe('page')
    expect(screen.getByRole('button', { name: 'view.tasks' }).getAttribute('aria-current')).toBeNull()
  })
})
