import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { ResearchView } from '../../src/client/ResearchView.tsx'

vi.mock('@deepseek-ai/dsh-client-ui-primitives', () => ({
  MarkdownText: ({ text }: { text: string }) => <div>{text}</div>,
}))

const envelope = (data: unknown) => ({ ok: true, data, error: null, request_id: 'req_research' })

const reports = [
  {
    id: 'report_one', title: '港口贸易核查', prompt: '核查港口贸易', status: 'succeeded',
    episode_id: 'EP_1', task_id: 'tsk_1', created_at: '2026-09-01T10:00:00Z', completed_at: '2026-09-01T10:02:00Z',
    model_profile: { id: 'research-a', label: 'Research A', provider: 'openai', model: 'writer-model' },
    search_provider: 'bing', sources_status: 'ok', source_count: 2, word_count: 1200, latency_ms: 120000,
    usage: { total_tokens: 5000, reported: true }, cost_usd: { value: 0, reported: true }, failure: null,
    metrics: { citationCount: 2, usedCitationCount: 1 }, path: 'data/research/reports/report_one.md', bytes: 1200,
  },
  {
    id: 'report_two', title: '失败的制度核查', prompt: '核查制度', status: 'failed',
    episode_id: 'EP_2', task_id: 'tsk_2', created_at: '2026-09-02T10:00:00Z', completed_at: null,
    model_profile: null, search_provider: null, sources_status: 'unavailable', source_count: null,
    word_count: null, latency_ms: null, usage: { total_tokens: null, reported: false },
    cost_usd: { value: null, reported: false }, failure: { code: 'RESEARCH_EPISODE_FAILED', message: 'quality gate failed' },
    metrics: {}, path: 'data/research/reports/report_two.md', bytes: 200,
  },
]

const detail = (report: Record<string, unknown>, content: string, sources: unknown) => envelope({
  id: report.id,
  metadata: { ...report, sources },
  content,
})

function makeApi() {
  return {
    fetchStudioApi: vi.fn(async (path: string) => {
      if (path === '/research') return envelope({
        available: true, setup_hint: '', reports,
        settings: { search_provider: 'bing', search_providers: [] },
        model_route: { profile_id: 'research-a', label: 'Research A', provider: 'openai', model: 'writer-model', configured: true, compatible: true },
      })
      if (path === '/research/reports/report_one') return detail(
        reports[0],
        '# 港口贸易\n\n结论正文 [C1]',
        [
          { title: 'Source A', url: 'https://example.com/a', source_type: 'primary', cited: true },
          { title: 'Unsafe source', url: 'javascript:alert(1)', source_type: 'unknown', cited: false },
        ],
      )
      if (path === '/research/reports/report_two') return detail(reports[1], '# 失败诊断', null)
      throw new Error(`unexpected GET ${path}`)
    }),
    postStudioApi: vi.fn(async () => envelope({ task_id: 'tsk_new', status: 'pending' })),
  }
}

const t = (key: string): string => key

function renderView(api: ReturnType<typeof makeApi>, initialReportId = '') {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  return render(<ResearchView {...({ ...api, t, initialReportId } as any)} />)
}

afterEach(() => vi.restoreAllMocks())

describe('ResearchView M2d workbench', () => {
  it('filters by keyword, status, and source availability', async () => {
    const api = makeApi()
    renderView(api)
    await screen.findByRole('button', { name: /港口贸易核查/ })

    fireEvent.change(screen.getByPlaceholderText('research.filter.keyword'), { target: { value: 'writer-model' } })
    expect(screen.getByRole('button', { name: /港口贸易核查/ })).toBeTruthy()
    expect(screen.queryByRole('button', { name: /失败的制度核查/ })).toBeNull()

    fireEvent.change(screen.getByPlaceholderText('research.filter.keyword'), { target: { value: '' } })
    fireEvent.change(screen.getByLabelText('research.filter.status'), { target: { value: 'failed' } })
    expect(screen.queryByRole('button', { name: /港口贸易核查/ })).toBeNull()
    expect(screen.getByRole('button', { name: /失败的制度核查/ })).toBeTruthy()

    fireEvent.change(screen.getByLabelText('research.filter.status'), { target: { value: 'all' } })
    fireEvent.change(screen.getByLabelText('research.filter.sources'), { target: { value: 'unavailable' } })
    expect(screen.queryByRole('button', { name: /港口贸易核查/ })).toBeNull()
    expect(screen.getByRole('button', { name: /失败的制度核查/ })).toBeTruthy()
  })

  it('opens a task result target and shows provenance, source checks, and tri-state usage', async () => {
    const api = makeApi()
    renderView(api, 'report_one')

    await waitFor(() => expect(api.fetchStudioApi).toHaveBeenCalledWith('/research/reports/report_one'))
    const provenance = await screen.findByTestId('research-provenance')
    expect(within(provenance).getByText('tsk_1')).toBeTruthy()
    expect(within(provenance).getByText(/openai · writer-model/)).toBeTruthy()
    expect(within(provenance).getByText('5,000')).toBeTruthy()
    expect(within(provenance).getByText('$0')).toBeTruthy()
    expect(screen.getByText('research.referenceOnly')).toBeTruthy()

    const sources = screen.getByTestId('research-sources')
    const safe = within(sources).getByRole('link', { name: /Source A/ })
    expect(safe.getAttribute('href')).toBe('https://example.com/a')
    expect(within(sources).getByText('research.source.cited')).toBeTruthy()
    expect(within(sources).queryByRole('link', { name: /Unsafe source/ })).toBeNull()
  })

  it('exports the selected markdown and exposes a failed report reason', async () => {
    const api = makeApi()
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => undefined)
    const createObjectURL = vi.fn(() => 'blob:research')
    const revokeObjectURL = vi.fn()
    Object.defineProperty(URL, 'createObjectURL', { configurable: true, value: createObjectURL })
    Object.defineProperty(URL, 'revokeObjectURL', { configurable: true, value: revokeObjectURL })
    renderView(api, 'report_one')

    fireEvent.click(await screen.findByRole('button', { name: 'research.exportMarkdown' }))
    expect(createObjectURL).toHaveBeenCalledTimes(1)
    expect(click).toHaveBeenCalledTimes(1)
    expect(revokeObjectURL).toHaveBeenCalledWith('blob:research')

    fireEvent.click(screen.getByRole('button', { name: /失败的制度核查/ }))
    const failure = await screen.findByTestId('research-failure')
    expect(failure.textContent).toContain('RESEARCH_EPISODE_FAILED')
    expect(failure.textContent).toContain('quality gate failed')
    const failedProvenance = screen.getByTestId('research-provenance')
    expect(failedProvenance.textContent).toContain('—')
    expect(screen.getAllByText('research.sourcesUnavailable').length).toBeGreaterThan(0)
  })
})
