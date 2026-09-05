import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { TasksView } from '../../src/client/TasksView.tsx'

const envelope = (data: unknown) => ({ ok: true, data, error: null, request_id: 'req_tasks' })
const t = (key: string): string => key

const TASKS = [
  {
    task_id: 'tsk_running', type: 'model_benchmark', status: 'running', phase: 'model', phase_index: 3,
    progress: { completed_units: 5, total_units: 10, ratio: 0.5, unit_kind: 'candidates' },
    chapter_id: 'ch_001', input_summary: '运行模型横评', retryable: true,
    created_at: '2026-09-01T08:00:00Z', updated_at: '2026-09-01T08:05:00Z', started_at: '2026-09-01T08:01:00Z', completed_at: null,
    error: null, result_ref: null,
  },
  {
    task_id: 'tsk_waiting', type: 'continuous_write', status: 'awaiting_confirmation', phase: 'committing', phase_index: 5,
    progress: null, chapter_id: 'ch_002', input_summary: '等待确认下一章', retryable: true,
    created_at: '2026-09-01T07:00:00Z', updated_at: '2026-09-01T07:01:00Z', started_at: null, completed_at: null,
    error: null, result_ref: null,
  },
  {
    task_id: 'tsk_failed', type: 'research', status: 'failed', phase: 'model', phase_index: 3,
    progress: null, chapter_id: '', input_summary: '研究失败任务', retryable: true,
    created_at: '2026-09-01T06:00:00Z', updated_at: '2026-09-01T06:02:00Z', started_at: '2026-09-01T06:00:10Z', completed_at: null,
    error: { code: 'TIMEOUT', message: 'provider timeout', recoverable: true, failed_stage: 'model' }, result_ref: null,
  },
  {
    task_id: 'tsk_restore', type: 'project_restore', status: 'completed', phase: 'complete', phase_index: 6,
    progress: null, chapter_id: '', input_summary: '恢复作品档案', retryable: false,
    created_at: '2026-09-01T05:00:00Z', updated_at: '2026-09-01T05:02:00Z', started_at: '2026-09-01T05:00:10Z', completed_at: '2026-09-01T05:02:00Z',
    error: null, result_ref: null,
  },
]

function makeApi() {
  const taskDetail = {
    ...TASKS[0],
    result_ref: { type: 'benchmark_run', id: 'bench_001' },
  }
  const fetchStudioApi = vi.fn(async (path: string) => {
    if (path === '/tasks?limit=100') return envelope({ schema_version: 'openwrite.task-surface.v1', phase_order: ['queued', 'reading', 'preparing', 'model', 'validating', 'committing', 'complete'], tasks: TASKS, counts: { running: 1, awaiting_confirmation: 1, failed: 1, completed: 1 } })
    if (path === '/tasks/tsk_running') return envelope({ task: taskDetail, events: [{ event_id: 'evt_1', event: 'task_progress_updated', created_at: '2026-09-01T08:04:00Z', note: '5 candidates complete' }] })
    throw new Error(`unexpected GET ${path}`)
  })
  const postStudioApi = vi.fn(async () => envelope({ ok: true }))
  return { fetchStudioApi, postStudioApi, putStudioApi: vi.fn(async () => envelope({})) }
}

function renderView(api: ReturnType<typeof makeApi>, onNavigate = vi.fn()) {
  // ConvViewProps and the injected face contain runtime values unused by this view.
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  render(<TasksView {...({ ...api, t, onNavigate } as any)} />)
  return onNavigate
}

describe('TasksView workbench', () => {
  it('shows summary counts, real progress, and never invents progress for null', async () => {
    const api = makeApi()
    renderView(api)
    await screen.findByText('5/10 · candidates')
    expect(screen.getByText('tasks.summary.total')).toBeTruthy()
    expect(screen.getAllByText('tasks.type.project_restore').length).toBeGreaterThan(0)
    expect(screen.queryByText('0%')).toBeNull()
  })

  it('filters by type and keyword, then opens detail events', async () => {
    const api = makeApi()
    renderView(api)
    await screen.findByText('运行模型横评')
    fireEvent.change(screen.getByPlaceholderText('tasks.filter.keyword'), { target: { value: '研究失败' } })
    expect(screen.queryByText('运行模型横评')).toBeNull()
    expect(screen.getByText('研究失败任务')).toBeTruthy()
    fireEvent.change(screen.getByPlaceholderText('tasks.filter.keyword'), { target: { value: '' } })
    const runningCard = screen.getByText('运行模型横评').closest('article')!
    fireEvent.click(runningCard.querySelector('button[title="tasks.detail.open"]')!)
    await screen.findByText('5 candidates complete')
    expect(api.fetchStudioApi).toHaveBeenCalledWith('/tasks/tsk_running')
  })

  it('confirms waiting tasks and cancels only after confirmation', async () => {
    const api = makeApi()
    vi.stubGlobal('confirm', vi.fn(() => true))
    renderView(api)
    await screen.findByText('等待确认下一章')
    const waitingCard = screen.getByText('等待确认下一章').closest('article')!
    fireEvent.click(waitingCard.querySelector('button[title="tasks.confirm.title"]')!)
    await waitFor(() => expect(api.postStudioApi).toHaveBeenCalledWith('/tasks/tsk_waiting/confirm', {}))
    fireEvent.click(waitingCard.querySelector('button[title="tasks.cancel.title"]')!)
    await waitFor(() => expect(api.postStudioApi).toHaveBeenCalledWith('/tasks/tsk_waiting/cancel', {}))
  })

  it('navigates a result reference to the benchmark view', async () => {
    const api = makeApi()
    const onNavigate = renderView(api)
    await screen.findByText('运行模型横评')
    const runningCard = screen.getByText('运行模型横评').closest('article')!
    fireEvent.click(runningCard.querySelector('button[title="tasks.detail.open"]')!)
    await screen.findAllByText('bench_001')
    fireEvent.click(screen.getByRole('button', { name: /tasks\.jump\.benchmark/ }))
    expect(onNavigate).toHaveBeenCalledWith({ view: 'benchmark', id: 'bench_001' })
  })
})
