/**
 * BenchmarkView M1c wiring (component layer, offline).
 *
 * Pins, with the injected API mocked at the api.ts level (the same pattern as
 * model-view.test.tsx) and `t` stubbed to return the locale key:
 *   - real task progress units render (e.g. "5/10 benchmark.candidates") plus
 *     the localized phase — never a fabricated percent;
 *   - a finished task's result_ref opens the benchmark run detail;
 *   - latency renders an em-dash when null/missing, never a fabricated "0 ms";
 *   - the cost tri-state: unreported → '—', explicit 0 → '$0', reported → value.
 */
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { BenchmarkView } from '../../src/client/BenchmarkView.tsx'

/** M1c success envelope (all model/benchmark endpoints answer this way now). */
const envelope = (data: unknown) => ({ ok: true, data, error: null, request_id: 'req_test' })

const WRITER = {
  id: 'writer-a', label: 'Writer A', provider: 'openai', model: 'fake-writer',
  configured: true, embedding_configured: false,
}
const REVIEWER = {
  id: 'reviewer-a', label: 'Reviewer A', provider: 'openai', model: 'fake-reviewer',
  configured: true, embedding_configured: false,
}
const PROFILES = envelope({
  profiles: [WRITER, REVIEWER],
  routes: { chapter_write: 'writer-a', review: 'reviewer-a' },
})

const CHAPTER_PIPELINE = {
  id: 'chapter-production-v1', execution_mode: 'framework',
  nodes: [{ id: 'context', label: 'Chapter context', depends_on: [] }, { id: 'write', label: 'Write chapter', depends_on: ['context'] }, { id: 'settle', label: 'Accept facts', depends_on: ['write'] }],
  review_domains: [{ id: 'prose', label: 'Chapter prose' }, { id: 'continuity', label: 'Chapter continuity' }],
}
const CREATIVE_PIPELINE = {
  id: 'chapter-creative-v1', execution_mode: 'creative',
  nodes: [{ id: 'prompt', label: 'Creative prompt', depends_on: [] }, { id: 'draft', label: 'Creative draft', depends_on: ['prompt'] }],
  review_domains: [{ id: 'diagnostic', label: 'Creative diagnostic' }],
}
const OUTLINE_PIPELINE = {
  id: 'outline-production-v1', execution_mode: 'framework',
  nodes: [{ id: 'window', label: 'Outline window', depends_on: [] }, { id: 'plan', label: 'Plan chapter range', depends_on: ['window'] }, { id: 'review', label: 'Review outline', depends_on: ['plan'] }],
  review_domains: [{ id: 'arc', label: 'Outline arc' }, { id: 'promise', label: 'Outline promises' }],
}
const OPTIONS = {
  chapters: [
    { chapter_id: 'ch_001', title: 'Old manuscript', status: 'written', has_manuscript: true, availability: 'unavailable', reason: 'Historical baseline unavailable' },
    { chapter_id: 'ch_004', title: 'Next chapter', status: 'planned', has_manuscript: false, availability: 'available', reason: '' },
    { chapter_id: 'ch_007', title: 'Later chapter', status: 'planned', has_manuscript: false, availability: 'available', reason: '' },
  ],
  next_chapter_id: 'ch_004', default_outline_start_chapter: 11,
  limits: { outline_start_chapter: { min: 4, max: 100000 }, outline_chapter_count: { min: 1, max: 20, default: 3 } },
  tasks: [
    { task_type: 'chapter', execution_modes: ['framework', 'creative'], pipelines: [CHAPTER_PIPELINE, CREATIVE_PIPELINE] },
    { task_type: 'outline', execution_modes: ['framework'], pipelines: [OUTLINE_PIPELINE] },
  ],
}

const RUN_LIST_ITEM = {
  run_id: 'run_1', status: 'completed', chapter_id: 'ch_001',
  created_at: '2026-08-31T10:05:00Z', context_hash: 'sha256:test',
  candidate_count: 3, evaluation_count: 0, execution_mode: 'creative',
  prompt_version: 'writer-v1', rubric_version: 'review-v2',
  comparison: {
    key: 'sha256:group-a', basis_complete: true, context_hash: 'sha256:test',
    prompt_version: 'writer-v1', rubric_version: 'review-v2', execution_mode: 'creative',
    manifest_schema_version: '3', context_strategy: 'hierarchical-provenance-v2',
    token_estimator: 'mixed-script-conservative-v1', packet_revision: 'packet-a', source_revision: 'source-a',
  },
  summary: { average_quality_score: 80 },
}

const candidate = (id: string, extra: Record<string, unknown>) => ({
  candidate_id: id,
  writer_profile: { id: 'writer-a', label: 'Writer A', provider: 'openai', model: 'fake-writer' },
  ...extra,
})

const RUN_DETAIL = {
  run_id: 'run_1', status: 'completed', chapter_id: 'ch_001', context_hash: 'sha256:test',
  created_at: '2026-08-31T10:05:00Z', started_at: '2026-08-31T10:05:01Z', completed_at: '2026-08-31T10:06:00Z',
  prompt_version: 'writer-v1', rubric_version: 'review-v2',
  comparison: RUN_LIST_ITEM.comparison,
  context_snapshot: {
    chapter_id: 'ch_001', target_words: 3000, characters: ['林岑', '周远'],
    manifest: {
      schema_version: 3, strategy: 'hierarchical-provenance-v2', packet_revision: 'packet-a', source_revision: 'source-a',
      estimated_tokens: 4321, measurement: { estimator: 'mixed-script-conservative-v1' },
      items: [{ section: 'author_intent', sources: [{ path: 'src/story/author_intent.md', exists: true, revision: 'intent-a' }] }],
    },
  },
  config: {
    execution_mode: 'creative', target_words: 3000, repeats: 1, blind_review: true, run_scoped_profiles: true,
    writer_profile_ids: ['writer-a'], reviewer_profile_ids: ['reviewer-a'],
  },
  summary: { average_quality_score: 80, requested_candidates: 3, completed_candidates: 3, requested_evaluations: 0, completed_evaluations: 0 },
  candidates: [
    candidate('c1', { latency_ms: null, cost_reported: false }),
    candidate('c2', { latency_ms: 123, cost_reported: true, cost_usd: 0, usage: { total_tokens: 1000 } }),
    candidate('c3', { latency_ms: 456, cost_reported: true, cost_usd: 1.5, usage: { total_tokens: 1000 } }),
  ],
  evaluations: [],
}

const t = (key: string): string => key

function makeApi(overrides: { task?: unknown; profiles?: unknown; options?: unknown; runs?: unknown[]; details?: Record<string, unknown> } = {}) {
  return {
    fetchStudioApi: vi.fn(async (path: string) => {
      if (path === '/model/profiles') return overrides.profiles ?? PROFILES
      if (path.startsWith('/benchmarks?')) return envelope({ runs: overrides.runs ?? [RUN_LIST_ITEM] })
      if (path === '/benchmarks/options') return overrides.options ?? envelope(OPTIONS)
      if (path.startsWith('/benchmarks/')) {
        const runId = path.slice('/benchmarks/'.length)
        return envelope(overrides.details?.[runId] ?? RUN_DETAIL)
      }
      if (path === '/tasks/tsk_run') return envelope({ task: overrides.task ?? { task_id: 'tsk_run', status: 'running' } })
      throw new Error(`unexpected GET ${path}`)
    }),
    postStudioApi: vi.fn(async (path: string) => {
      if (path === '/benchmarks') return envelope({ task_id: 'tsk_run', status: 'pending' })
      throw new Error(`unexpected POST ${path}`)
    }),
    putStudioApi: vi.fn(async () => envelope({})),
  }
}

function renderView(api: ReturnType<typeof makeApi>, initialRunId = '', refreshEpoch = 0) {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  return render(<BenchmarkView {...({ ...api, t, initialRunId, refreshEpoch } as any)} />)
}

/** Render, wait for the profile load, then submit a benchmark run. */
async function renderAndRun(api: ReturnType<typeof makeApi>) {
  const view = renderView(api)
  await screen.findByRole('group', { name: /benchmark\.writer/ })
  fireEvent.click(screen.getByRole('button', { name: /benchmark\.run/ }))
  await waitFor(() => expect(api.postStudioApi).toHaveBeenCalledWith('/benchmarks', expect.anything()))
  return view
}

describe('BenchmarkView M1c task wiring', () => {
  it('retains in-flight cancellation status and loads durable partial results before completion', async () => {
    const api = makeApi({ task: { task_id: 'tsk_run', status: 'running', cancel_requested: true,
      progress: { completed_units: 1, total_units: 3, unit_kind: 'candidates' },
      result_ref: { type: 'benchmark_run', id: 'partial' } },
      details: { partial: { ...RUN_DETAIL, run_id: 'partial', status: 'cancelling', in_flight: 1 } } })
    await renderAndRun(api)
    const button = await screen.findByRole('button', { name: '取消中…' })
    expect((button as HTMLButtonElement).disabled).toBe(true)
    await waitFor(() => expect(api.fetchStudioApi).toHaveBeenCalledWith('/benchmarks/partial'))
    expect(screen.getByText(/已发送的请求仍可能产生费用/)).toBeTruthy()
    expect(await screen.findByText(/还有 1 个请求在途/)).toBeTruthy()
  })

  it('renders real progress units and the phase while the task runs', async () => {
    const api = makeApi({
      task: {
        task_id: 'tsk_run', status: 'running', phase: 'model',
        progress: { completed_units: 5, total_units: 10, ratio: 0.5, unit_kind: 'candidates' },
      },
    })
    renderView(api)
    await screen.findByRole('group', { name: /benchmark\.writer/ })
    fireEvent.click(screen.getByRole('button', { name: /benchmark\.run/ }))

    // Real units only — no percent is ever synthesized.
    await screen.findByText(/5\/10 benchmark\.candidates/)
    expect(screen.getByText(/tasks\.phase\.model/)).toBeTruthy()
  })

  it('a completed task opens its run detail via result_ref', async () => {
    const api = makeApi({
      task: {
        task_id: 'tsk_run', status: 'completed', phase: 'complete',
        progress: { completed_units: 10, total_units: 10, ratio: 1, unit_kind: 'candidates' },
        result_ref: { type: 'benchmark_run', id: 'run_1' },
      },
    })
    await renderAndRun(api)

    await waitFor(() => expect(api.fetchStudioApi).toHaveBeenCalledWith('/benchmarks/run_1'))
    // The run detail rendered (summary header shows the run id).
    expect((await screen.findAllByText('run_1')).length).toBeGreaterThan(0)
  })
})

describe('BenchmarkView experiment outcome', () => {
  it('preserves a failed task error without a benchmark result through terminal and history refreshes, until the next submission', async () => {
    const task: { task_id: string; status: string; phase: string; error?: { code: string; message: string } } = {
      task_id: 'tsk_run', status: 'failed', phase: 'prepare',
      error: { code: 'ACCEPTANCE_BASELINE_REQUIRED', message: 'Existing manuscripts need an accepted facts baseline before this test can run.' },
    }
    const api = makeApi({ task, runs: [] })
    await renderAndRun(api)
    const progress = screen.getByText('benchmark.task').closest('[role="status"]')!
    const failure = await within(progress as HTMLElement).findByRole('alert')
    expect(failure.textContent).toContain(task.error!.message)
    expect(failure.textContent).toContain(task.error!.code)
    expect(progress.getAttribute('data-status')).toBe('failed')
    await waitFor(() => expect(api.fetchStudioApi.mock.calls.filter(([path]) => path.startsWith('/benchmarks?'))).toHaveLength(2))
    await waitFor(() => expect(runButton().disabled).toBe(false))
    expect(api.fetchStudioApi.mock.calls.some(([path]) => path.startsWith('/benchmarks/') && path !== '/benchmarks/options')).toBe(false)

    fireEvent.click(screen.getByRole('button', { name: 'refresh' }))
    await waitFor(() => expect(api.fetchStudioApi.mock.calls.filter(([path]) => path.startsWith('/benchmarks?'))).toHaveLength(3))
    await waitFor(() => expect(runButton().disabled).toBe(false))
    expect(within(progress as HTMLElement).getByRole('alert').textContent).toContain('ACCEPTANCE_BASELINE_REQUIRED')
    expect(within(progress as HTMLElement).getByRole('alert').textContent).toContain(task.error!.message)

    task.status = 'running'
    delete task.error
    fireEvent.click(runButton())
    await waitFor(() => expect(api.postStudioApi).toHaveBeenCalledTimes(2))
    await waitFor(() => expect(progress.getAttribute('data-status')).toBe('running'))
    expect(within(progress as HTMLElement).queryByRole('alert')).toBeNull()
  })

  it('reports a failed experiment even when its background worker completed normally', async () => {
    const api = makeApi({
      task: { task_id: 'tsk_run', status: 'completed', phase: 'complete', result_ref: { type: 'benchmark_run', id: 'run_1' } },
      details: { run_1: { ...RUN_DETAIL, status: 'failed', candidates: [], evaluations: [] } },
    })
    await renderAndRun(api)
    await waitFor(() => {
      const progress = screen.getByText('benchmark.task').closest('[role="status"]')!
      expect(progress.textContent).toContain('tasks.status.failed')
      expect(progress.textContent).not.toContain('tasks.status.completed')
      expect(progress.textContent).not.toContain('tasks.phase.complete')
      expect(progress.getAttribute('data-status')).toBe('failed')
    })
    expect(screen.getByTestId('benchmark-selected-mode').textContent).toContain('tasks.status.failed')
  })
})

describe('BenchmarkView candidate cells', () => {
  it('latency renders an em-dash when null and cost keeps its tri-state', async () => {
    const api = makeApi()
    renderView(api)
    // Open the run from the list (result list is pre-populated by the load).
    fireEvent.click(await screen.findByRole('button', { name: /ch_001/ }))
    await screen.findByText('123 ms')

    expect(screen.getByText('456 ms')).toBeTruthy()
    // Missing latency must never surface as a fabricated "0 ms".
    expect(screen.queryByText('0 ms')).toBeNull()

    // Cost tri-state: explicit 0 → $0, reported → value, unreported → —.
    expect(screen.getByText('$0')).toBeTruthy()
    expect(screen.getByText('$1.50')).toBeTruthy()
  })
})

describe('BenchmarkView M2c comparable results', () => {
  it('opens the exact task result even when it is outside the newest-run list', async () => {
    const linked = { ...RUN_DETAIL, run_id: 'run_linked', chapter_id: 'ch_linked' }
    const api = makeApi({ details: { run_linked: linked } })
    renderView(api, 'run_linked')

    await waitFor(() => expect(api.fetchStudioApi).toHaveBeenCalledWith('/benchmarks/run_linked'))
    expect((await screen.findAllByText('run_linked')).length).toBeGreaterThan(0)
  })

  it('groups only runs with the same context and comparison versions', async () => {
    const run = (runId: string, key: string, promptVersion: string) => ({
      ...RUN_LIST_ITEM,
      run_id: runId,
      prompt_version: promptVersion,
      comparison: { ...RUN_LIST_ITEM.comparison, key, prompt_version: promptVersion },
    })
    const api = makeApi({
      runs: [
        run('run_same_1', 'sha256:same', 'writer-v1'),
        run('run_same_2', 'sha256:same', 'writer-v1'),
        run('run_changed', 'sha256:changed', 'writer-v2'),
      ],
    })
    renderView(api)

    await screen.findByText('run_same_1')
    const groups = screen.getAllByTestId('benchmark-comparison-group')
    expect(groups).toHaveLength(2)
    expect(within(groups[0]).getByText(/2 benchmark\.runs/)).toBeTruthy()
    expect(within(groups[1]).getByText(/1 benchmark\.runs/)).toBeTruthy()
  })

  it('shows the full input identity, versions, source revisions, and real phases', async () => {
    const api = makeApi()
    renderView(api)
    await screen.findByText('run_1')

    const provenance = screen.getByTestId('benchmark-provenance')
    expect(within(provenance).getByText('sha256:test')).toBeTruthy()
    expect(within(provenance).getByText('writer-v1')).toBeTruthy()
    expect(within(provenance).getByText('review-v2')).toBeTruthy()
    expect(within(provenance).getByText('mixed-script-conservative-v1')).toBeTruthy()
    expect(within(provenance).getByText('packet-a')).toBeTruthy()
    expect(within(provenance).getByText('source-a')).toBeTruthy()
    expect(within(provenance).getByText(/src\/story\/author_intent\.md/)).toBeTruthy()

    const phases = screen.getByTestId('benchmark-run-phases')
    expect(within(phases).getByText(/2026-08-31T10:05:00Z/)).toBeTruthy()
    expect(within(phases).getByText(/3\/3 benchmark\.candidates/)).toBeTruthy()
  })

  it('keeps legacy unknowns explicit and exposes model and failure detail', async () => {
    const legacyRun = {
      ...RUN_LIST_ITEM,
      run_id: 'run_legacy', execution_mode: null,
      comparison: {
        ...RUN_LIST_ITEM.comparison, key: 'sha256:legacy', basis_complete: false,
        execution_mode: null, token_estimator: null, source_revision: null,
      },
    }
    const legacyDetail = {
      ...RUN_DETAIL,
      run_id: 'run_legacy', config: { writer_profile_ids: ['writer-a'], reviewer_profile_ids: ['reviewer-a'] },
      comparison: legacyRun.comparison,
      candidates: [candidate('legacy-candidate', {
        reliability_status: 'failed', word_count: 0,
        response_provider: 'openrouter', response_model: 'actual-writer-v2',
        error: { code: 'MODEL_OUTPUT_TRUNCATED', message: 'ProviderResponseError' },
      })],
      evaluations: [{
        candidate_id: 'legacy-candidate', reviewer_profile: REVIEWER,
        execution_status: 'failed', quality_score: 0,
        error: { code: 'REVIEW_FAILED', message: 'ReviewerResponseError' },
      }],
    }
    const api = makeApi({ runs: [legacyRun], details: { run_legacy: legacyDetail } })
    renderView(api)
    await screen.findByText('run_legacy')

    expect(screen.getByTestId('benchmark-selected-mode').textContent).toContain('benchmark.mode.unknown')
    expect(screen.getByText(/openrouter · actual-writer-v2/)).toBeTruthy()
    expect(screen.getByText(/MODEL_OUTPUT_TRUNCATED/).textContent).toContain('ProviderResponseError')
    expect(screen.getByText(/REVIEW_FAILED/).textContent).toContain('ReviewerResponseError')

    const candidateRow = screen.getByText(/legacy-candidate/).closest('details')
    expect(candidateRow?.textContent).toContain('0 benchmark.actualWords')
    const evaluationRow = screen.getByText(/REVIEW_FAILED/).closest('tr')
    expect(evaluationRow?.textContent).toContain('0')
  })
})


function deferred<T>() {
  let resolve!: (value: T) => void
  let reject!: (reason: unknown) => void
  const promise = new Promise<T>((res, rej) => { resolve = res; reject = rej })
  return { promise, resolve, reject }
}

function openModelChoices(group: HTMLElement): HTMLElement {
  const picker = group.querySelector('details')!
  if (!picker.open) fireEvent.click(picker.querySelector('summary')!)
  return group
}

describe('BenchmarkView usable configuration', () => {
  it('starts with compact model selectors that show the selected profiles', async () => {
    const api = makeApi()
    renderView(api)
    const writers = await screen.findByRole('group', { name: /benchmark\.writer/ })
    const reviewers = screen.getByRole('group', { name: /benchmark\.reviewer/ })
    expect(writers.querySelector('details')!.open).toBe(false)
    expect(reviewers.querySelector('details')!.open).toBe(false)
    expect(writers.querySelector('summary')!.textContent).toBe('Writer A')
    expect(reviewers.querySelector('summary')!.textContent).toBe('Reviewer A')
    // Native details visibility is verified in browser QA; jsdom exposes its descendants.
    fireEvent.click(writers.querySelector('summary')!)
    expect(within(writers).getByRole('checkbox', { name: /Writer A/ })).toBeTruthy()
  })

  it('supports explicit writer and reviewer selection and submits the chosen workload', async () => {
    const api = makeApi()
    renderView(api)
    const writers = openModelChoices(await screen.findByRole('group', { name: /benchmark\.writer/ }))
    const reviewers = openModelChoices(screen.getByRole('group', { name: /benchmark\.reviewer/ }))
    fireEvent.click(within(writers).getByRole('checkbox', { name: /Reviewer A/ }))
    fireEvent.click(within(reviewers).getByRole('checkbox', { name: /Writer A/ }))
    const advanced = screen.getByText('benchmark.advanced').closest('details')!
    expect(advanced.open).toBe(false)
    fireEvent.click(screen.getByText('benchmark.advanced'))
    fireEvent.change(screen.getByLabelText('benchmark.repeats'), { target: { value: '2' } })
    fireEvent.change(screen.getByLabelText('benchmark.concurrency'), { target: { value: '3' } })
    fireEvent.change(screen.getByLabelText('benchmark.words'), { target: { value: '2600' } })
    expect(screen.getByText(/4 benchmark\.plannedCandidates/).textContent).toContain('8 benchmark.plannedEvaluations')
    fireEvent.click(screen.getByRole('button', { name: 'benchmark.run' }))
    await waitFor(() => expect(api.postStudioApi).toHaveBeenCalledWith('/benchmarks', {
      task_type: 'chapter', chapter_id: 'next', writer_profile_ids: ['writer-a', 'reviewer-a'], reviewer_profile_ids: ['reviewer-a', 'writer-a'],
      execution_mode: 'framework', repeats: 2, target_words: 2600, concurrency: 3,
    }))
  })

  it('lets users clear and retype numeric inputs and refuses invalid values', async () => {
    const api = makeApi()
    renderView(api)
    await screen.findByRole('group', { name: /benchmark\.writer/ })
    const input = screen.getByLabelText('benchmark.words') as HTMLInputElement
    fireEvent.change(input, { target: { value: '' } })
    expect(input.value).toBe('')
    fireEvent.click(screen.getByRole('button', { name: 'benchmark.run' }))
    expect(api.postStudioApi).not.toHaveBeenCalled()
    fireEvent.change(input, { target: { value: '2500' } })
    fireEvent.click(screen.getByRole('button', { name: 'benchmark.run' }))
    await waitFor(() => expect(api.postStudioApi).toHaveBeenCalledWith('/benchmarks', expect.objectContaining({ target_words: 2500 })))
  })

  it('shows setup guidance when no configured profiles are available', async () => {
    const api = makeApi({ profiles: envelope({ profiles: [{ ...WRITER, configured: false }], routes: {} }), runs: [] })
    renderView(api)
    await screen.findByText('benchmark.noProfiles')
    expect((screen.getByRole('button', { name: 'benchmark.run' }) as HTMLButtonElement).disabled).toBe(true)
    expect(screen.getByText('benchmark.empty')).toBeTruthy()
    expect(screen.queryByRole('checkbox')).toBeNull()
  })

  it('keeps a deliberately empty model selection when refreshing', async () => {
    const api = makeApi()
    renderView(api)
    const writers = openModelChoices(await screen.findByRole('group', { name: /benchmark\.writer/ }))
    fireEvent.click(within(writers).getByRole('checkbox', { name: /Writer A/ }))
    fireEvent.click(screen.getByRole('button', { name: 'refresh' }))
    await waitFor(() => expect(api.fetchStudioApi.mock.calls.filter(([path]) => path === '/model/profiles')).toHaveLength(2))
    expect((within(writers).getByRole('checkbox', { name: /Writer A/ }) as HTMLInputElement).checked).toBe(false)
    expect(screen.getByText('benchmark.chooseModels')).toBeTruthy()
    expect((screen.getByRole('button', { name: 'benchmark.run' }) as HTMLButtonElement).disabled).toBe(true)
  })

  it('prevents duplicate submissions while the first request is pending and permits retry after failure', async () => {
    const api = makeApi()
    const pending = deferred<ReturnType<typeof envelope>>()
    api.postStudioApi.mockImplementationOnce(() => pending.promise)
    renderView(api)
    await screen.findByRole('group', { name: /benchmark\.writer/ })
    const button = screen.getByRole('button', { name: 'benchmark.run' })
    fireEvent.click(button)
    fireEvent.click(button)
    expect(api.postStudioApi).toHaveBeenCalledTimes(1)
    expect((screen.getByRole('button', { name: 'benchmark.submitting' }) as HTMLButtonElement).disabled).toBe(true)
    await act(async () => { pending.reject(new Error('Network unavailable')) })
    expect(screen.getByRole('alert').textContent).toBe('Network unavailable')
    fireEvent.click(screen.getByRole('button', { name: 'benchmark.run' }))
    await waitFor(() => expect(api.postStudioApi).toHaveBeenCalledTimes(2))
    expect(screen.queryByRole('alert')).toBeNull()
  })

  it('refreshes resource data without losing form settings or user selection', async () => {
    const api = makeApi()
    const view = renderView(api)
    await screen.findByRole('group', { name: /benchmark\.writer/ })
    fireEvent.change(screen.getByLabelText('benchmark.chapter'), { target: { value: 'ch_007' } })
    fireEvent.change(screen.getByLabelText('benchmark.words'), { target: { value: '4100' } })
    fireEvent.click(within(openModelChoices(screen.getByRole('group', { name: /benchmark\.writer/ }))).getByRole('checkbox', { name: /Writer A/ }))
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    view.rerender(<BenchmarkView {...({ ...api, t, refreshEpoch: 1 } as any)} />)
    await waitFor(() => expect(api.fetchStudioApi.mock.calls.filter(([path]) => path === '/model/profiles')).toHaveLength(2))
    expect((screen.getByLabelText('benchmark.chapter') as HTMLSelectElement).value).toBe('ch_007')
    expect((screen.getByLabelText('benchmark.words') as HTMLInputElement).value).toBe('4100')
    expect((within(openModelChoices(screen.getByRole('group', { name: /benchmark\.writer/ }))).getByRole('checkbox', { name: /Writer A/ }) as HTMLInputElement).checked).toBe(false)
  })
})

function chooseTask(kind: 'chapter' | 'outline') {
  fireEvent.click(screen.getByRole('radio', { name: new RegExp(`benchmark\\.task\\.${kind}`) }))
}

const runButton = () => screen.getByRole('button', { name: 'benchmark.run' }) as HTMLButtonElement

describe('BenchmarkView task targets and automatic pipelines', () => {
  it('explains a task readiness gate and refuses both button and direct form submission', async () => {
    const message = 'Existing manuscripts require acceptance before chapter testing is available.'
    const api = makeApi({ options: envelope({
      ...OPTIONS,
      tasks: OPTIONS.tasks.map(task => task.task_type === 'chapter'
        ? { ...task, readiness: { ok: false, code: 'ACCEPTANCE_BASELINE_REQUIRED', message } }
        : task),
    }) })
    renderView(api)
    const notice = await screen.findByTestId('benchmark-readiness')
    expect(notice.textContent).toBe(message)
    expect(notice.getAttribute('role')).toBe('status')
    expect(runButton().disabled).toBe(true)
    fireEvent.click(runButton())
    fireEvent.submit(runButton().closest('form')!)
    expect(api.postStudioApi).not.toHaveBeenCalled()
  })

  it('restores submission when switching from an unavailable task back to a ready task', async () => {
    const api = makeApi({ options: envelope({
      ...OPTIONS,
      tasks: OPTIONS.tasks.map(task => ({ ...task, readiness: task.task_type === 'outline'
        ? { ok: false, code: 'OUTLINE_NOT_READY', message: 'Outline planning is not ready for this workspace.' }
        : { ok: true, code: '', message: '' } })),
    }) })
    renderView(api)
    await screen.findByRole('group', { name: /benchmark.writer/ })
    expect(runButton().disabled).toBe(false)
    chooseTask('outline')
    expect(screen.getByTestId('benchmark-readiness').textContent).toContain('Outline planning is not ready')
    expect(runButton().disabled).toBe(true)
    fireEvent.submit(runButton().closest('form')!)
    expect(api.postStudioApi).not.toHaveBeenCalled()
    chooseTask('chapter')
    expect(screen.queryByTestId('benchmark-readiness')).toBeNull()
    expect(runButton().disabled).toBe(false)
    fireEvent.click(runButton())
    await waitFor(() => expect(api.postStudioApi).toHaveBeenCalledWith('/benchmarks', expect.objectContaining({ task_type: 'chapter' })))
  })

  it('allows an available explicit future chapter past a missing-next-outline gate, but never past an acceptance baseline gate', async () => {
    for (const code of ['TARGET_NOT_PLANNED', 'ACCEPTANCE_BASELINE_REQUIRED']) {
      const api = makeApi({ options: envelope({
        ...OPTIONS,
        tasks: OPTIONS.tasks.map(task => task.task_type === 'chapter'
          ? { ...task, readiness: { ok: false, code, message: `Blocked by ${code}` } }
          : task),
      }) })
      const view = renderView(api)
      await screen.findByTestId('benchmark-readiness')
      expect(runButton().disabled).toBe(true)
      const choice = screen.getByRole('combobox', { name: 'benchmark.chapter' })
      fireEvent.change(choice, { target: { value: 'ch_007' } })
      if (code === 'TARGET_NOT_PLANNED') {
        expect(screen.queryByTestId('benchmark-readiness')).toBeNull()
        expect(runButton().disabled).toBe(false)
        fireEvent.change(choice, { target: { value: 'next' } })
        expect(screen.getByTestId('benchmark-readiness').textContent).toContain(code)
        expect(runButton().disabled).toBe(true)
        fireEvent.change(choice, { target: { value: 'ch_007' } })
        fireEvent.submit(runButton().closest('form')!)
        await waitFor(() => expect(api.postStudioApi).toHaveBeenCalledWith('/benchmarks', expect.objectContaining({ chapter_id: 'ch_007' })))
      } else {
        expect(screen.getByTestId('benchmark-readiness').textContent).toContain(code)
        expect(runButton().disabled).toBe(true)
        fireEvent.submit(runButton().closest('form')!)
        expect(api.postStudioApi).not.toHaveBeenCalled()
      }
      view.unmount()
    }
  })

  it('selects an available future chapter other than next without silently changing the target', async () => {
    const api = makeApi()
    renderView(api)
    const choice = await screen.findByRole('combobox', { name: 'benchmark.chapter' }) as HTMLSelectElement
    await waitFor(() => expect(choice.options.length).toBe(5))
    expect(choice.value).toBe('next')
    expect(within(choice).getByRole('option', { name: /benchmark.nextChapter/ }).textContent).toContain('ch_004')
    fireEvent.change(choice, { target: { value: 'ch_007' } })
    fireEvent.click(runButton())
    await waitFor(() => expect(api.postStudioApi).toHaveBeenCalledWith('/benchmarks', {
      task_type: 'chapter', chapter_id: 'ch_007', writer_profile_ids: ['writer-a'], reviewer_profile_ids: ['reviewer-a'],
      execution_mode: 'framework', repeats: 1, concurrency: 1, target_words: 3000,
    }))
  })

  it('disables unavailable historical chapters and refuses unknown custom IDs while permitting a listed custom ID', async () => {
    const api = makeApi()
    renderView(api)
    const history = await screen.findByRole('option', { name: /ch_001.*Old manuscript/ }) as HTMLOptionElement
    expect(history.disabled).toBe(true)
    expect(history.textContent).toContain('Historical baseline unavailable')
    const choice = screen.getByRole('combobox', { name: 'benchmark.chapter' })
    fireEvent.change(choice, { target: { value: 'ch_001' } })
    expect(runButton().disabled).toBe(true)
    fireEvent.submit(runButton().closest('form')!)
    expect(api.postStudioApi).not.toHaveBeenCalled()
    fireEvent.change(choice, { target: { value: '__custom__' } })
    const custom = screen.getByLabelText('benchmark.chapterId')
    for (const value of ['', 'missing', 'ch_999', 'ch_001']) {
      fireEvent.change(custom, { target: { value } })
      expect(runButton().disabled).toBe(true)
      fireEvent.submit(runButton().closest('form')!)
    }
    expect(api.postStudioApi).not.toHaveBeenCalled()
    fireEvent.change(custom, { target: { value: 'ch_007' } })
    expect(runButton().disabled).toBe(false)
    fireEvent.click(runButton())
    await waitFor(() => expect(api.postStudioApi).toHaveBeenCalledWith('/benchmarks', expect.objectContaining({ chapter_id: 'ch_007' })))
  })

  it('continues the outline from the server default with an inclusive three-chapter range and framework-only payload', async () => {
    const api = makeApi()
    renderView(api)
    await screen.findByRole('group', { name: /benchmark.writer/ })
    fireEvent.change(screen.getByLabelText('benchmark.mode'), { target: { value: 'creative' } })
    fireEvent.change(screen.getByLabelText('benchmark.words'), { target: { value: '' } })
    chooseTask('outline')
    expect((screen.getByLabelText('benchmark.outlineOrigin') as HTMLSelectElement).value).toBe('continue')
    const start = screen.getByLabelText('benchmark.outlineStart') as HTMLInputElement
    expect(start.value).toBe('11')
    expect(start.disabled).toBe(true)
    expect(screen.getByText('benchmark.rangeFrom 11 benchmark.rangeTo 13 benchmark.chapterUnit')).toBeTruthy()
    expect(screen.queryByLabelText('benchmark.words')).toBeNull()
    expect(screen.queryByLabelText('benchmark.mode')).toBeNull()
    fireEvent.click(runButton())
    await waitFor(() => expect(api.postStudioApi).toHaveBeenCalledWith('/benchmarks', {
      task_type: 'outline', outline_start_chapter: 11, outline_chapter_count: 3,
      writer_profile_ids: ['writer-a'], reviewer_profile_ids: ['reviewer-a'], execution_mode: 'framework', repeats: 1, concurrency: 1,
    }))
  })

  it('uses a manual inclusive outline start and preserves chapter settings across task switches', async () => {
    const api = makeApi()
    renderView(api)
    await screen.findByRole('group', { name: /benchmark.writer/ })
    fireEvent.change(screen.getByLabelText('benchmark.chapter'), { target: { value: 'ch_007' } })
    fireEvent.change(screen.getByLabelText('benchmark.mode'), { target: { value: 'creative' } })
    fireEvent.change(screen.getByLabelText('benchmark.words'), { target: { value: '4200' } })
    chooseTask('outline')
    fireEvent.change(screen.getByLabelText('benchmark.outlineOrigin'), { target: { value: 'custom' } })
    fireEvent.change(screen.getByLabelText('benchmark.outlineStart'), { target: { value: '17' } })
    fireEvent.change(screen.getByLabelText('benchmark.outlineCount'), { target: { value: '4' } })
    expect(screen.getByText('benchmark.rangeFrom 17 benchmark.rangeTo 20 benchmark.chapterUnit')).toBeTruthy()
    chooseTask('chapter')
    expect((screen.getByLabelText('benchmark.chapter') as HTMLSelectElement).value).toBe('ch_007')
    expect((screen.getByLabelText('benchmark.mode') as HTMLSelectElement).value).toBe('creative')
    expect((screen.getByLabelText('benchmark.words') as HTMLInputElement).value).toBe('4200')
    chooseTask('outline')
    expect((screen.getByLabelText('benchmark.outlineStart') as HTMLInputElement).value).toBe('17')
    expect((screen.getByLabelText('benchmark.outlineCount') as HTMLInputElement).value).toBe('4')
    fireEvent.click(runButton())
    await waitFor(() => expect(api.postStudioApi).toHaveBeenCalledWith('/benchmarks', expect.objectContaining({
      task_type: 'outline', outline_start_chapter: 17, outline_chapter_count: 4, execution_mode: 'framework',
    })))
  })

  it.each(['', '0', '-1', '1.5', '21'])('refuses outline count %s without posting a run', async value => {
    const api = makeApi()
    renderView(api)
    await screen.findByRole('group', { name: /benchmark.writer/ })
    chooseTask('outline')
    const count = screen.getByLabelText('benchmark.outlineCount') as HTMLInputElement
    expect(count.min).toBe('1')
    expect(count.max).toBe('20')
    fireEvent.change(count, { target: { value } })
    expect(runButton().disabled).toBe(true)
    expect(screen.getByText('benchmark.invalidRange')).toBeTruthy()
    fireEvent.submit(runButton().closest('form')!)
    expect(api.postStudioApi).not.toHaveBeenCalled()
  })

  it.each([1, 20])('accepts the outline count boundary %s and reports the correct inclusive end', async count => {
    const api = makeApi()
    renderView(api)
    await screen.findByRole('group', { name: /benchmark.writer/ })
    chooseTask('outline')
    fireEvent.change(screen.getByLabelText('benchmark.outlineCount'), { target: { value: String(count) } })
    expect(screen.getByText(`benchmark.rangeFrom 11 benchmark.rangeTo ${11 + count - 1} benchmark.chapterUnit`)).toBeTruthy()
    fireEvent.click(runButton())
    await waitFor(() => expect(api.postStudioApi).toHaveBeenCalledWith('/benchmarks', expect.objectContaining({ outline_start_chapter: 11, outline_chapter_count: count })))
  })

  it('validates the entire outline range against server start and end limits', async () => {
    const api = makeApi()
    renderView(api)
    await screen.findByRole('group', { name: /benchmark.writer/ })
    chooseTask('outline')
    fireEvent.change(screen.getByLabelText('benchmark.outlineOrigin'), { target: { value: 'custom' } })
    const start = screen.getByLabelText('benchmark.outlineStart') as HTMLInputElement
    const count = screen.getByLabelText('benchmark.outlineCount')
    expect(start.min).toBe('4')
    expect(start.max).toBe('100000')
    for (const [first, size] of [['3', '1'], ['4.5', '1'], ['100000', '2'], ['99999', '3'], ['100001', '1']]) {
      fireEvent.change(start, { target: { value: first } })
      fireEvent.change(count, { target: { value: size } })
      expect(runButton().disabled).toBe(true)
      fireEvent.submit(runButton().closest('form')!)
    }
    expect(api.postStudioApi).not.toHaveBeenCalled()
    fireEvent.change(start, { target: { value: '99999' } })
    fireEvent.change(count, { target: { value: '2' } })
    expect(screen.getByText('benchmark.rangeFrom 99999 benchmark.rangeTo 100000 benchmark.chapterUnit')).toBeTruthy()
    fireEvent.click(runButton())
    await waitFor(() => expect(api.postStudioApi).toHaveBeenCalledWith('/benchmarks', expect.objectContaining({ outline_start_chapter: 99999, outline_chapter_count: 2 })))
  })

  it('switches the authoritative DAG, dependency labels, and review domains by task and mode', async () => {
    const api = makeApi()
    renderView(api)
    let dag = await screen.findByRole('region', { name: 'benchmark.autoDag' })
    const foldedStages = dag.querySelector('details')!
    expect(foldedStages.open).toBe(false)
    fireEvent.click(foldedStages.querySelector('summary')!)
    expect(foldedStages.open).toBe(true)
    expect(dag.textContent).toContain('Write chapter')
    expect(dag.textContent).toContain('benchmark.afterStage Chapter context')
    expect(dag.textContent).toContain('Chapter prose · Chapter continuity')
    fireEvent.change(screen.getByLabelText('benchmark.mode'), { target: { value: 'creative' } })
    dag = screen.getByRole('region', { name: 'benchmark.autoDag' })
    expect(dag.textContent).toContain('Creative draft')
    expect(dag.textContent).toContain('Creative diagnostic')
    expect(dag.textContent).not.toContain('Accept facts')
    chooseTask('outline')
    dag = screen.getByRole('region', { name: 'benchmark.autoDag' })
    expect(dag.textContent).toContain('Plan chapter range')
    expect(dag.textContent).toContain('benchmark.afterStage Outline window')
    expect(dag.textContent).toContain('Outline arc · Outline promises')
    expect(dag.textContent).not.toContain('Creative diagnostic')
    expect(dag.textContent).not.toContain('Chapter prose')
    chooseTask('chapter')
    expect(screen.getByRole('region', { name: 'benchmark.autoDag' }).textContent).toContain('Creative draft')
    expect(api.postStudioApi).not.toHaveBeenCalled()
  })
})

describe('BenchmarkView option freshness', () => {
  it('blocks submission while options reload and after failure, then recovers on a successful refresh', async () => {
    const api = makeApi()
    renderView(api)
    await screen.findByRole('group', { name: /benchmark.writer/ })
    const pending = deferred<ReturnType<typeof envelope>>()
    const original = api.fetchStudioApi.getMockImplementation()!
    api.fetchStudioApi.mockImplementation(path => path === '/benchmarks/options' ? pending.promise : original(path))
    fireEvent.click(screen.getByRole('button', { name: 'refresh' }))
    expect(runButton().disabled).toBe(true)
    fireEvent.submit(runButton().closest('form')!)
    expect(api.postStudioApi).not.toHaveBeenCalled()
    await act(async () => { pending.reject(new Error('Options unavailable')) })
    expect(screen.getByText('Options unavailable')).toBeTruthy()
    expect(runButton().disabled).toBe(true)
    fireEvent.submit(runButton().closest('form')!)
    expect(api.postStudioApi).not.toHaveBeenCalled()
    api.fetchStudioApi.mockImplementation(original)
    fireEvent.click(screen.getByRole('button', { name: 'refresh' }))
    await waitFor(() => expect(runButton().disabled).toBe(false))
    expect(screen.queryByText('Options unavailable')).toBeNull()
  })

  it('ignores an older options success arriving after a newer refresh failure', async () => {
    const api = makeApi()
    const pending = deferred<ReturnType<typeof envelope>>()
    const original = api.fetchStudioApi.getMockImplementation()!
    let optionsCalls = 0
    api.fetchStudioApi.mockImplementation(path => path !== '/benchmarks/options' ? original(path)
      : ++optionsCalls === 1 ? pending.promise : Promise.reject(new Error('Newest options failed')))
    const view = renderView(api)
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    view.rerender(<BenchmarkView {...({ ...api, t, refreshEpoch: 1 } as any)} />)
    await screen.findByText('Newest options failed')
    await act(async () => { pending.resolve(envelope(OPTIONS)) })
    expect(runButton().disabled).toBe(true)
    expect(screen.getByText('Newest options failed')).toBeTruthy()
    expect(screen.queryByRole('region', { name: 'benchmark.autoDag' })).toBeNull()
    expect(api.postStudioApi).not.toHaveBeenCalled()
  })

  it('retains the latest chapter and outline options when an older refresh finishes late', async () => {
    const api = makeApi()
    const pending = deferred<ReturnType<typeof envelope>>()
    const original = api.fetchStudioApi.getMockImplementation()!
    let optionsCalls = 0
    const latest = { ...OPTIONS, next_chapter_id: 'ch_008', default_outline_start_chapter: 21,
      chapters: [{ chapter_id: 'ch_008', title: 'Newest chapter', status: 'planned', has_manuscript: false, availability: 'available', reason: '' }] }
    api.fetchStudioApi.mockImplementation(path => path !== '/benchmarks/options' ? original(path)
      : ++optionsCalls === 1 ? pending.promise : Promise.resolve(envelope(latest)))
    const view = renderView(api)
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    view.rerender(<BenchmarkView {...({ ...api, t, refreshEpoch: 1 } as any)} />)
    await screen.findByRole('option', { name: /ch_008.*Newest chapter/ })
    await act(async () => { pending.resolve(envelope(OPTIONS)) })
    expect(screen.queryByRole('option', { name: /ch_007.*Later chapter/ })).toBeNull()
    expect(runButton().disabled).toBe(false)
    chooseTask('outline')
    expect((screen.getByLabelText('benchmark.outlineStart') as HTMLInputElement).value).toBe('21')
  })
})

describe('BenchmarkView result navigation', () => {
  it('shows a historical outline range, actual designed chapters and the recorded DAG independently of current options', async () => {
    const archivedPipeline = {
      id: 'outline-archived-v0', execution_mode: 'framework',
      nodes: [{ id: 'input', label: 'Archived outline context', depends_on: [] }, { id: 'plan', label: 'Archived range planner', depends_on: ['input'] }],
      review_domains: [{ id: 'old-arc', label: 'Archived arc standard' }],
    }
    const outlineRun = { ...RUN_LIST_ITEM, run_id: 'run_outline', task_type: 'outline', chapter_id: 'ch_011',
      outline_start_chapter: 11, outline_end_chapter: 13, outline_chapter_count: 3, execution_mode: 'framework' }
    const detail = {
      ...RUN_DETAIL, run_id: 'run_outline', task_type: 'outline', chapter_id: 'ch_011',
      config: { task_type: 'outline', execution_mode: 'framework', outline_start_chapter: 11, outline_end_chapter: 13, outline_chapter_count: 3, pipeline: archivedPipeline },
      candidates: [candidate('outline-candidate', {
        task_type: 'outline', title: 'Archived outline', content: 'Chapter eleven plan.\nChapter twelve plan.\nChapter thirteen plan.',
        reliability_status: 'completed', outline_start_chapter: 11, outline_end_chapter: 13, outline_chapter_count: 3,
        word_count: 987, execution_mode: 'framework',
      })],
    }
    const api = makeApi({ runs: [outlineRun], details: { run_outline: detail } })
    renderView(api)
    const outputSummary = await screen.findByText('Archived outline · 3 benchmark.actualChapters')
    const output = outputSummary.closest('details')!
    expect(output.open).toBe(true)
    expect(within(output).getByText('benchmark.rangeFrom 11 benchmark.rangeTo 13 benchmark.chapterUnit')).toBeTruthy()
    const candidates = screen.getByRole('table', { name: 'benchmark.candidates' })
    expect(within(candidates).getByRole('columnheader', { name: 'benchmark.actualChapters' })).toBeTruthy()
    expect(within(candidates).queryByRole('columnheader', { name: 'benchmark.actualWords' })).toBeNull()
    expect(within(candidates).getAllByRole('row')[1].children[3].textContent).toBe('3')
    expect(candidates.textContent).not.toContain('987')
    const heading = screen.getByRole('heading', { level: 2, name: /benchmark.results/ })
    expect(heading.textContent).toContain('benchmark.task.outline · benchmark.rangeFrom 11 benchmark.rangeTo 13 benchmark.chapterUnit')
    expect(screen.getByRole('button', { name: /run_outline/ }).textContent).toContain('benchmark.rangeFrom 11 benchmark.rangeTo 13 benchmark.chapterUnit')
    const recorded = [...document.querySelectorAll('details')].find(element => element.querySelector(':scope > summary')?.textContent === 'benchmark.executedDag')!
    expect(recorded.open).toBe(false)
    fireEvent.click(recorded.querySelector(':scope > summary')!)
    expect(recorded.open).toBe(true)
    const recordedDag = screen.getByRole('region', { name: 'benchmark.executedDag' })
    expect(recordedDag.textContent).toContain('Archived range planner')
    expect(recordedDag.textContent).toContain('benchmark.afterStage Archived outline context')
    expect(recordedDag.textContent).toContain('Archived arc standard')
    expect(recordedDag.textContent).not.toContain('Plan chapter range')
    chooseTask('outline')
    expect(screen.getByRole('region', { name: 'benchmark.autoDag' }).textContent).toContain('Plan chapter range')
    expect(recordedDag.textContent).toContain('Archived range planner')
    expect(api.postStudioApi).not.toHaveBeenCalled()
  })

  it('does not substitute the requested chapter count or word count when an outline candidate has no validated range', async () => {
    const api = makeApi({ details: { run_1: {
      ...RUN_DETAIL, task_type: 'outline',
      config: { task_type: 'outline', execution_mode: 'framework', outline_start_chapter: 11, outline_chapter_count: 3 },
      candidates: [candidate('failed-outline', { task_type: 'outline', title: 'Unvalidated outline', content: 'Unstructured plan', word_count: 500, reliability_status: 'failed' })],
    } } })
    renderView(api)
    const output = (await screen.findByText('Unvalidated outline · — benchmark.actualChapters')).closest('details')!
    expect(output.textContent).not.toContain('3 benchmark.actualChapters')
    expect(output.textContent).not.toContain('500')
    expect(within(output).getByText('—')).toBeTruthy()
    const candidates = screen.getByRole('table', { name: 'benchmark.candidates' })
    expect(within(candidates).getAllByRole('row')[1].children[3].textContent).toBe('—')
  })

  it('allows browsing another run after opening a linked task result', async () => {
    const linked = { ...RUN_DETAIL, run_id: 'run_linked', chapter_id: 'ch_linked' }
    const api = makeApi({ details: { run_linked: linked } })
    renderView(api, 'run_linked')
    await screen.findByText('run_linked')
    fireEvent.click(screen.getByRole('button', { name: /ch_001/ }))
    await waitFor(() => expect(screen.queryByText('run_linked')).toBeNull())
    expect(screen.getByRole('button', { name: /ch_001/ }).getAttribute('aria-pressed')).toBe('true')
    expect(api.fetchStudioApi.mock.calls.filter(([path]) => path === '/benchmarks/run_linked')).toHaveLength(1)
  })

  it('keeps the latest selected run when detail requests resolve out of order', async () => {
    const second = { ...RUN_LIST_ITEM, run_id: 'run_2', chapter_id: 'ch_002' }
    const api = makeApi({ runs: [RUN_LIST_ITEM, second] })
    const pending = deferred<ReturnType<typeof envelope>>()
    const original = api.fetchStudioApi.getMockImplementation()!
    api.fetchStudioApi.mockImplementation(path => path === '/benchmarks/run_1' ? pending.promise : path === '/benchmarks/run_2' ? Promise.resolve(envelope({ ...RUN_DETAIL, run_id: 'run_2', chapter_id: 'ch_002' })) : original(path))
    renderView(api)
    fireEvent.click(await screen.findByRole('button', { name: /ch_002/ }))
    await waitFor(() => expect(screen.getByRole('button', { name: /ch_002/ }).getAttribute('aria-pressed')).toBe('true'))
    await act(async () => { pending.resolve(envelope(RUN_DETAIL)) })
    expect(screen.getByRole('button', { name: /ch_002/ }).getAttribute('aria-pressed')).toBe('true')
    expect(screen.getByRole('button', { name: /ch_001/ }).getAttribute('aria-pressed')).toBe('false')
  })

  it('keeps technical provenance collapsed and gives missing outcomes useful empty states', async () => {
    const api = makeApi({ details: { run_1: { ...RUN_DETAIL, candidates: [], evaluations: [] } } })
    renderView(api)
    await screen.findByText('benchmark.noCandidates')
    expect(screen.getByText('benchmark.noEvaluations')).toBeTruthy()
    const provenance = screen.getByTestId('benchmark-provenance') as HTMLDetailsElement
    expect(provenance.open).toBe(false)
    fireEvent.click(within(provenance).getByText('benchmark.inputProvenance'))
    expect(provenance.open).toBe(true)
    expect(within(provenance).getByText('sha256:test')).toBeTruthy()
  })
})

describe('BenchmarkView execution evidence', () => {
  it('shows per-branch partial, failed and skipped statuses with dependencies and evidence independently of quality scores', async () => {
    const candidateHash = 'sha256:0123456789abcdef0123456789abcdef'
    const reviewHash = 'sha256:abcdef0123456789abcdef0123456789'
    const api = makeApi({ details: { run_1: {
      ...RUN_DETAIL,
      config: { ...RUN_DETAIL.config, pipeline: CHAPTER_PIPELINE },
      candidates: [
        candidate('failed-branch', { reliability_status: 'failed', framework: { pipeline_execution: {
          id: 'candidate-execution-v1', nodes: [
            { id: 'context', label: 'Captured context', depends_on: [], status: 'completed', evidence: [{ path: 'artifacts/candidate/context.json', sha256: candidateHash }] },
            { id: 'write', label: 'Failed writer', depends_on: ['context'], status: 'failed', evidence: [], error_code: 'MODEL_OUTPUT_TRUNCATED' },
            { id: 'commit', label: 'Skipped acceptance', depends_on: ['write'], status: 'skipped', evidence: [], reason: 'UPSTREAM_WRITE_FAILED' },
          ],
        } } }),
        candidate('reviewed-branch', { reliability_status: 'completed' }),
      ],
      evaluations: [{ candidate_id: 'reviewed-branch', reviewer_profile: REVIEWER, execution_status: 'partial', quality_score: 99, coverage: 0.9,
        framework: { pipeline_execution: {
          id: 'review-execution-v1', nodes: [{ id: 'review', label: 'Partial independent review', depends_on: [], status: 'partial',
            evidence: [{ path: 'artifacts/reviewer/review.json', sha256: reviewHash }], reason: 'MISSING_PROSE_CRITERION' }],
        } },
      }],
    } } })
    renderView(api)
    const executions = await screen.findByTestId('benchmark-executions') as HTMLDetailsElement
    expect(executions.open).toBe(false)
    fireEvent.click(executions.querySelector(':scope > summary')!)
    expect(executions.open).toBe(true)
    expect(within(executions).getByRole('heading', { name: 'benchmark.candidate · Writer A' })).toBeTruthy()
    expect(within(executions).getByRole('heading', { name: 'benchmark.reviewer · Reviewer A' })).toBeTruthy()
    expect(executions.textContent).toContain('failed-branch · candidate-execution-v1')
    expect(executions.textContent).toContain('reviewed-branch · review-execution-v1')
    const failed = within(executions).getByText('Failed writer').closest('li')!
    expect(failed.querySelector('[data-status="failed"]')?.textContent).toBe('tasks.status.failed')
    expect(failed.textContent).toContain('benchmark.afterStage Captured context')
    expect(failed.textContent).toContain('MODEL_OUTPUT_TRUNCATED')
    expect(failed.textContent).not.toContain('tasks.status.completed')
    const skipped = within(executions).getByText('Skipped acceptance').closest('li')!
    expect(skipped.querySelector('[data-status="skipped"]')?.textContent).toBe('benchmark.status.skipped')
    expect(skipped.textContent).toContain('benchmark.afterStage Failed writer')
    expect(skipped.textContent).toContain('UPSTREAM_WRITE_FAILED')
    const partial = within(executions).getByText('Partial independent review').closest('li')!
    expect(partial.querySelector('[data-status="partial"]')?.textContent).toBe('review.status.partial')
    expect(partial.textContent).toContain('MISSING_PROSE_CRITERION')
    expect(partial.textContent).not.toContain('tasks.status.completed')
    expect(screen.getByRole('table', { name: 'benchmark.evaluations' }).textContent).toContain('99')
    const candidateEvidence = within(executions).getByTitle(candidateHash)
    expect(candidateEvidence.textContent).toContain('artifacts/candidate/context.json')
    expect(candidateEvidence.textContent).toContain(candidateHash.slice(0, 12))
    const reviewEvidence = within(executions).getByTitle(reviewHash)
    expect(reviewEvidence.textContent).toContain('artifacts/reviewer/review.json')
    expect(reviewEvidence.textContent).toContain(reviewHash.slice(0, 12))
    expect(executions.textContent).not.toContain('Write chapter')
    expect(api.postStudioApi).not.toHaveBeenCalled()
  })

  it('does not invent execution evidence for old results that only have a configured pipeline and high quality scores', async () => {
    const api = makeApi({ details: { run_1: {
      ...RUN_DETAIL,
      config: { ...RUN_DETAIL.config, pipeline: CHAPTER_PIPELINE },
      candidates: [candidate('old-candidate', { reliability_status: 'completed', framework: { write_entrypoint: 'execute_write_chapter' } })],
      evaluations: [{ candidate_id: 'old-candidate', reviewer_profile: REVIEWER, execution_status: 'completed', quality_score: 100, coverage: 1 }],
    } } })
    renderView(api)
    await screen.findByTestId('benchmark-selected-mode')
    expect(screen.queryByTestId('benchmark-executions')).toBeNull()
    expect(screen.getByRole('table', { name: 'benchmark.evaluations' }).textContent).toContain('100')
    const recorded = [...document.querySelectorAll('details')].find(element => element.querySelector(':scope > summary')?.textContent === 'benchmark.executedDag')!
    expect(recorded).toBeTruthy()
    fireEvent.click(recorded.querySelector(':scope > summary')!)
    expect(screen.getByRole('region', { name: 'benchmark.executedDag' }).textContent).toContain('Write chapter')
    expect(screen.queryByTestId('benchmark-executions')).toBeNull()
  })
})

describe('BenchmarkView incomplete review results', () => {
  const partialReview = {
    candidate_id: 'c1', reviewer_profile: REVIEWER, execution_status: 'partial',
    quality_score: 85.56, coverage: 0.9,
    review_diagnostics: { inconclusive_domain_ids: ['prose'] },
  }

  it('marks the task, inspected history, and score as partial when a completed run has incomplete review', async () => {
    const api = makeApi({
      runs: [RUN_LIST_ITEM, { ...RUN_LIST_ITEM, run_id: 'run_uninspected', chapter_id: 'ch_002' }],
      task: { task_id: 'tsk_run', status: 'completed', phase: 'complete', result_ref: { type: 'benchmark_run', id: 'run_1' } },
      details: { run_1: {
        ...RUN_DETAIL, status: 'completed', evaluations: [partialReview],
        summary: { ...RUN_DETAIL.summary, requested_evaluations: 1, completed_evaluations: 1, average_quality_score: 85.56 },
      } },
    })
    await renderAndRun(api)
    await waitFor(() => expect(screen.getByText('benchmark.task').closest('[role="status"]')!.textContent).toContain('review.status.partial'))
    expect(screen.getByTestId('benchmark-selected-mode').textContent).toContain('review.status.partial')
    const history = screen.getByRole('button', { name: /ch_001/ })
    expect(history.textContent).toContain('review.status.partial')
    expect(history.textContent).toContain('benchmark.partialScore')
    const note = screen.getByRole('note', { name: 'benchmark.reviewIncomplete' })
    expect(note.textContent).toContain('benchmark.completeReviews 0/1')
    expect(note.textContent).toContain('benchmark.reportedCoverage 90%')
    expect(note.textContent).toContain('prose')
    expect(note.textContent).toContain('benchmark.reviewIncompleteHint')
    // A summary alone cannot distinguish a partial review from a complete one.
    const uninspected = screen.getByRole('button', { name: /ch_002/ })
    expect(uninspected.textContent).toContain('benchmark.pipelineFinished')
    expect(uninspected.textContent).not.toContain('tasks.status.completed')
    // Preserve the original record separately from the derived completeness indicator.
    expect(within(screen.getByTestId('benchmark-provenance')).getByText('tasks.status.completed')).toBeTruthy()
  })

  it('uses reported coverage even when an evaluation execution is marked completed', async () => {
    const api = makeApi({ details: { run_1: {
      ...RUN_DETAIL, evaluations: [{ ...partialReview, execution_status: 'completed', review_diagnostics: {} }],
    } } })
    renderView(api)
    await screen.findByRole('note', { name: 'benchmark.reviewIncomplete' })
    expect(screen.getByTestId('benchmark-selected-mode').textContent).toContain('review.status.partial')
  })

  it('does not confuse missing production approval with an incomplete review', async () => {
    const api = makeApi({ details: { run_1: {
      ...RUN_DETAIL, evaluations: [{ ...partialReview, execution_status: 'completed', coverage: 1, review_diagnostics: {}, production_gate_status: 'not_recorded' }],
    } } })
    renderView(api)
    await screen.findByTestId('benchmark-selected-mode')
    expect(screen.getByTestId('benchmark-selected-mode').textContent).toContain('tasks.status.completed')
    expect(screen.queryByRole('note', { name: 'benchmark.reviewIncomplete' })).toBeNull()
  })

  it('gives manuscript-fact recovery instructions while retaining the original error details', async () => {
    const api = makeApi({ details: { run_1: {
      ...RUN_DETAIL, status: 'failed', evaluations: [],
      candidates: [candidate('blocked', { reliability_status: 'failed', error: { code: 'MANUSCRIPT_FACTS_PENDING', message: 'ManuscriptAcceptanceError' } })],
    } } })
    renderView(api)
    const note = await screen.findByRole('note', { name: 'benchmark.factsPendingTitle' })
    expect(note.textContent).toContain('benchmark.factsPendingHint')
    const error = screen.getByText(/MANUSCRIPT_FACTS_PENDING/)
    expect(error.textContent).toContain('ManuscriptAcceptanceError')
    expect(error.closest('td')!.textContent).toContain('benchmark.factsPendingTitle')
    expect(api.postStudioApi).not.toHaveBeenCalled()
  })
})
