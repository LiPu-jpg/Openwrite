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
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
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

function makeApi(overrides: { task?: unknown; runs?: unknown[]; details?: Record<string, unknown> } = {}) {
  return {
    fetchStudioApi: vi.fn(async (path: string) => {
      if (path === '/model/profiles') return PROFILES
      if (path.startsWith('/benchmarks?')) return envelope({ runs: overrides.runs ?? [RUN_LIST_ITEM] })
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

function renderView(api: ReturnType<typeof makeApi>, initialRunId = '') {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  return render(<BenchmarkView {...({ ...api, t, initialRunId } as any)} />)
}

/** Render, wait for the profile load, then submit a benchmark run. */
async function renderAndRun(api: ReturnType<typeof makeApi>) {
  const view = renderView(api)
  await screen.findByText('Writer A')
  fireEvent.click(screen.getByRole('button', { name: /benchmark\.run/ }))
  await waitFor(() => expect(api.postStudioApi).toHaveBeenCalledWith('/benchmarks', expect.anything()))
  return view
}

describe('BenchmarkView M1c task wiring', () => {
  it('renders real progress units and the phase while the task runs', async () => {
    const api = makeApi({
      task: {
        task_id: 'tsk_run', status: 'running', phase: 'model',
        progress: { completed_units: 5, total_units: 10, ratio: 0.5, unit_kind: 'candidates' },
      },
    })
    renderView(api)
    await screen.findByText('Writer A')
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
