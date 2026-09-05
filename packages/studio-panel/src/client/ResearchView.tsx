import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Download, ExternalLink, RefreshCw, Search } from 'lucide-react'
import type { ConvViewProps } from '@deepseek-ai/dsh-client-ui-conversation/client'
import { MarkdownText } from '@deepseek-ai/dsh-client-ui-primitives'
import type { InjectFace, PropsLocale } from '@deepseek-ai/dsh-client-ui-slots'
import type { StudioApiInjected } from './api.ts'
import css from './views.module.css'

interface ResearchModelProfile {
  id: string
  label: string
  model: string
  provider: string
}

interface ResearchSource {
  title: string
  url: string
  sourceType: string
  cited: boolean
}

interface ResearchReport {
  id: string
  title: string
  prompt: string
  status: string
  episodeId: string | null
  taskId: string | null
  createdAt: string | null
  completedAt: string | null
  modelProfile: ResearchModelProfile | null
  searchProvider: string | null
  sources: ResearchSource[] | null
  sourcesStatus: string
  sourceCount: number | null
  wordCount: number | null
  latencyMs: number | null
  usage: { totalTokens: number | null; reported: boolean }
  cost: { value: number | null; reported: boolean }
  failure: { code: string; message: string } | null
  metrics: Record<string, unknown>
}

interface ResearchSurface {
  available: boolean
  setupHint: string
  reports: ResearchReport[]
  searchProvider: string | null
  modelRoute: ResearchModelProfile | null
}

interface ReportBody {
  metadata: ResearchReport
  content: string
}

type LoadState = 'loading' | 'error' | 'ready'
type StatusFilter = 'all' | 'succeeded' | 'failed' | 'needs_human_review' | 'unknown'
type SourceFilter = 'all' | 'available' | 'unavailable'

function record(value: unknown): Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {}
}

function text(value: unknown): string {
  return typeof value === 'string' ? value : ''
}

function nullableText(value: unknown): string | null {
  const rendered = text(value).trim()
  return rendered === '' ? null : rendered
}

function finiteNumber(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null
}

function parseModel(value: unknown): ResearchModelProfile | null {
  const item = record(value)
  if (Object.keys(item).length === 0) return null
  return {
    id: text(item['id'] ?? item['profile_id']),
    label: text(item['label']),
    model: text(item['model']),
    provider: text(item['provider']),
  }
}

function parseSources(value: unknown): ResearchSource[] | null {
  if (!Array.isArray(value)) return null
  return value.map(raw => {
    const item = record(raw)
    return {
      title: text(item['title']),
      url: text(item['url']),
      sourceType: text(item['source_type']),
      cited: item['cited'] === true,
    }
  })
}

function parseReport(raw: unknown, fallbackId = ''): ResearchReport {
  const item = record(raw)
  const model = parseModel(item['model_profile'])
  const usage = record(item['usage'])
  const cost = record(item['cost_usd'])
  const failure = record(item['failure'])
  const sources = parseSources(item['sources'])
  const id = text(item['id']) || fallbackId
  return {
    id,
    title: text(item['title']) || id,
    prompt: text(item['prompt']),
    status: text(item['status']) || 'unknown',
    episodeId: nullableText(item['episode_id']),
    taskId: nullableText(item['task_id']),
    createdAt: nullableText(item['created_at']),
    completedAt: nullableText(item['completed_at']),
    modelProfile: model,
    searchProvider: nullableText(item['search_provider']),
    sources,
    sourcesStatus: text(item['sources_status']) || (sources === null ? 'unavailable' : 'ok'),
    sourceCount: finiteNumber(item['source_count']),
    wordCount: finiteNumber(item['word_count']),
    latencyMs: finiteNumber(item['latency_ms']),
    usage: { totalTokens: finiteNumber(usage['total_tokens']), reported: usage['reported'] === true },
    cost: { value: finiteNumber(cost['value']), reported: cost['reported'] === true },
    failure: Object.keys(failure).length === 0 ? null : { code: text(failure['code']), message: text(failure['message']) },
    metrics: record(item['metrics']),
  }
}

function unwrap(value: unknown): Record<string, unknown> {
  return record(record(value)['data'])
}

function parseSurface(value: unknown): ResearchSurface {
  const inner = unwrap(value)
  const settings = record(inner['settings'])
  return {
    available: inner['available'] === true,
    setupHint: text(inner['setup_hint']),
    reports: Array.isArray(inner['reports']) ? inner['reports'].map(raw => parseReport(raw)) : [],
    searchProvider: nullableText(settings['search_provider']),
    modelRoute: parseModel(inner['model_route']),
  }
}

function parseReportBody(value: unknown): ReportBody {
  const inner = unwrap(value)
  return {
    metadata: parseReport(inner['metadata'], text(inner['id'])),
    content: text(inner['content']),
  }
}

function shortTime(value: string | null): string {
  if (value === null) return '—'
  const match = /^\d{4}-(\d{2}-\d{2})[T ](\d{2}:\d{2})/.exec(value)
  return match !== null ? `${match[1]} ${match[2]}` : value.slice(0, 16)
}

function formatNumber(value: number | null): string {
  return value === null ? '—' : Math.round(value).toLocaleString()
}

function formatCost(value: number | null, reported: boolean): string {
  if (!reported || value === null) return '—'
  if (value === 0) return '$0'
  return value >= 1 ? `$${value.toFixed(2)}` : `$${value.toFixed(6)}`
}

function safeSourceUrl(value: string): string | null {
  try {
    const parsed = new URL(value)
    return parsed.protocol === 'http:' || parsed.protocol === 'https:' ? parsed.href : null
  } catch {
    return null
  }
}

export type ResearchViewProps =
  ConvViewProps & InjectFace<StudioApiInjected> & PropsLocale<'studio-panel'> & {
    initialReportId?: string
  }

export function ResearchView({ fetchStudioApi, postStudioApi, t, initialReportId = '' }: ResearchViewProps) {
  const [state, setState] = useState<LoadState>('loading')
  const [surface, setSurface] = useState<ResearchSurface | null>(null)
  const [error, setError] = useState('')
  const [selectedId, setSelectedId] = useState('')
  const [reportState, setReportState] = useState<LoadState>('ready')
  const [report, setReport] = useState<ReportBody | null>(null)
  const [reportError, setReportError] = useState('')
  const [keyword, setKeyword] = useState('')
  const [statusFilter, setStatusFilter] = useState<StatusFilter>('all')
  const [sourceFilter, setSourceFilter] = useState<SourceFilter>('all')
  const [launchOpen, setLaunchOpen] = useState(false)
  const [launchPrompt, setLaunchPrompt] = useState('')
  const [launchBusy, setLaunchBusy] = useState(false)
  const [launchNote, setLaunchNote] = useState<{ text: string; bad: boolean } | null>(null)
  const mounted = useRef(true)
  const detailRequest = useRef(0)
  const openedInitial = useRef('')

  useEffect(() => () => { mounted.current = false }, [])

  const load = useCallback(async () => {
    setState('loading')
    try {
      const next = parseSurface(await fetchStudioApi('/research'))
      if (!mounted.current) return
      setSurface(next)
      setError('')
      setState('ready')
    } catch (cause: unknown) {
      if (!mounted.current) return
      setError(cause instanceof Error ? cause.message : String(cause))
      setState('error')
    }
  }, [fetchStudioApi])

  useEffect(() => { void load() }, [load])

  const openReport = useCallback(async (id: string) => {
    const request = ++detailRequest.current
    setSelectedId(id)
    setReportState('loading')
    setReport(null)
    setReportError('')
    try {
      const next = parseReportBody(await fetchStudioApi(`/research/reports/${encodeURIComponent(id)}`))
      if (!mounted.current || request !== detailRequest.current) return
      setReport(next)
      setReportState('ready')
    } catch (cause: unknown) {
      if (!mounted.current || request !== detailRequest.current) return
      setReportError(cause instanceof Error ? cause.message : String(cause))
      setReportState('error')
    }
  }, [fetchStudioApi])

  useEffect(() => {
    if (state !== 'ready' || initialReportId === '' || openedInitial.current === initialReportId) return
    openedInitial.current = initialReportId
    void openReport(initialReportId)
  }, [initialReportId, openReport, state])

  const visibleReports = useMemo(() => {
    const query = keyword.trim().toLowerCase()
    return (surface?.reports ?? []).filter(item => {
      if (statusFilter !== 'all' && item.status !== statusFilter) return false
      if (sourceFilter === 'available' && item.sourcesStatus !== 'ok') return false
      if (sourceFilter === 'unavailable' && item.sourcesStatus === 'ok') return false
      if (query === '') return true
      const model = item.modelProfile
      return [
        item.id, item.title, item.prompt, item.status, item.taskId ?? '', item.episodeId ?? '',
        item.searchProvider ?? '', model?.id ?? '', model?.label ?? '', model?.provider ?? '', model?.model ?? '',
      ].some(value => value.toLowerCase().includes(query))
    })
  }, [keyword, sourceFilter, statusFilter, surface])

  const submitResearch = async () => {
    const prompt = launchPrompt.trim()
    if (prompt === '' || launchBusy) return
    setLaunchBusy(true)
    setLaunchNote(null)
    try {
      await postStudioApi('/tasks', { type: 'research', input: { prompt } })
      setLaunchNote({ text: t('research.launch.submitted'), bad: false })
      setLaunchPrompt('')
      await load()
    } catch (cause: unknown) {
      setLaunchNote({ text: `${t('research.launch.failed')}: ${cause instanceof Error ? cause.message : String(cause)}`, bad: true })
    } finally {
      if (mounted.current) setLaunchBusy(false)
    }
  }

  const exportMarkdown = () => {
    if (report === null || selectedId === '') return
    const blob = new Blob([report.content], { type: 'text/markdown;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const anchor = document.createElement('a')
    anchor.href = url
    anchor.download = `${selectedId}.md`
    anchor.click()
    URL.revokeObjectURL(url)
  }

  const selected = surface?.reports.find(item => item.id === selectedId)
  const detail = report?.metadata ?? selected ?? null

  return <div className={css.root}>
    <div className={css.toolbar}>
      <span className={css.toolbarMeta}>
        {state === 'ready' && surface !== null && (surface.available
          ? `${t('research.reports')}: ${visibleReports.length}/${surface.reports.length} · ${surface.searchProvider ?? '—'} · ${surface.modelRoute?.model ?? '—'}`
          : surface.setupHint || t('research.unavailable'))}
      </span>
      <button type="button" className={css.button} disabled={!surface?.available || launchBusy} title={surface?.available === false ? surface.setupHint : undefined} onClick={() => setLaunchOpen(previous => !previous)}>{t('research.launch')}</button>
      <button type="button" className={css.button} onClick={() => void load()}><RefreshCw size={14} /> {t('refresh')}</button>
    </div>
    {launchOpen && <div className={css.launchPanel}>
      <textarea className={css.summaryTextarea} rows={3} value={launchPrompt} placeholder={t('research.launch.placeholder')} onChange={event => setLaunchPrompt(event.target.value)} />
      <div className={css.inlineActions}>
        <button type="button" className={css.button} disabled={launchBusy || launchPrompt.trim() === ''} onClick={() => void submitResearch()}>{launchBusy ? t('research.launch.submitting') : t('research.launch.submit')}</button>
        <span className={css.toolbarMeta}>{t('research.launch.hint')}</span>
      </div>
      {launchNote !== null && <div className={css.notice}><span className={launchNote.bad ? css.errorText : undefined}>{launchNote.text}</span></div>}
    </div>}
    {state === 'loading' && surface === null && <div className={css.body}><div className={css.notice}>{t('loading')}</div></div>}
    {state === 'error' && <div className={css.body}><div className={css.notice}><span className={css.errorText}>{error}</span><button type="button" className={css.button} onClick={() => void load()}>{t('retry')}</button></div></div>}
    {state === 'ready' && surface !== null && <div className={`${css.libraryRoot} ${css.researchWorkspace}`}>
      <aside className={css.sidebar}>
        <div className={css.researchFilters}>
          <label className={css.researchSearch}><Search size={13} /><input value={keyword} placeholder={t('research.filter.keyword')} onChange={event => setKeyword(event.target.value)} /></label>
          <label>{t('research.filter.status')}<select aria-label={t('research.filter.status')} value={statusFilter} onChange={event => setStatusFilter(event.target.value as StatusFilter)}>
            <option value="all">{t('research.filter.all')}</option><option value="succeeded">{t('research.status.succeeded')}</option><option value="failed">{t('research.status.failed')}</option><option value="needs_human_review">{t('research.status.needsReview')}</option><option value="unknown">{t('research.status.unknown')}</option>
          </select></label>
          <label>{t('research.filter.sources')}<select aria-label={t('research.filter.sources')} value={sourceFilter} onChange={event => setSourceFilter(event.target.value as SourceFilter)}>
            <option value="all">{t('research.filter.all')}</option><option value="available">{t('research.sourcesAvailable')}</option><option value="unavailable">{t('research.sourcesUnavailable')}</option>
          </select></label>
        </div>
        <div className={css.sidebarList}>
          {visibleReports.length === 0 && <div className={css.sidebarEmpty}>{t('research.empty')}</div>}
          {visibleReports.map(item => <button key={item.id} type="button" className={css.assetRow} data-active={item.id === selectedId} onClick={() => void openReport(item.id)}>
            <span className={css.assetRowName}>{item.title}</span>
            <span className={css.assetRowMeta}>{item.status} · {shortTime(item.createdAt)}</span>
          </button>)}
        </div>
      </aside>
      <main className={css.mainPane}>
        {selectedId === '' && <div className={css.detailNotice}>{t('research.selectHint')}</div>}
        {selectedId !== '' && reportState === 'loading' && <div className={css.detailNotice}>{t('research.report.loading')}</div>}
        {selectedId !== '' && reportState === 'error' && <div className={css.detailNotice}><span className={css.errorText}>{reportError}</span> <button type="button" className={css.button} onClick={() => void openReport(selectedId)}>{t('retry')}</button></div>}
        {selectedId !== '' && reportState === 'ready' && report !== null && detail !== null && <article className={css.detail}>
          <header className={css.detailHeader}>
            <div className={css.detailTitleRow}><span className={css.detailTitle}>{detail.title}</span><button type="button" className={css.button} onClick={exportMarkdown}><Download size={14} /> {t('research.exportMarkdown')}</button></div>
            <div className={css.assetMeta}><span className={css.tag}>{detail.status}</span><span className={css.tag}>{shortTime(detail.createdAt)}</span>{detail.sourceCount !== null && <span className={css.tag}>{t('research.sources')} {detail.sourceCount}</span>}</div>
          </header>
          <div className={css.researchReferenceOnly}>{t('research.referenceOnly')}</div>
          {detail.failure !== null && <div className={css.researchFailure} data-testid="research-failure"><strong>{detail.failure.code || 'RESEARCH_FAILED'}</strong><span>{detail.failure.message || '—'}</span></div>}
          <dl className={css.researchProvenance} data-testid="research-provenance">
            <div><dt>{t('research.prompt')}</dt><dd>{detail.prompt || '—'}</dd></div>
            <div><dt>{t('research.taskId')}</dt><dd>{detail.taskId ?? '—'}</dd></div>
            <div><dt>{t('research.episodeId')}</dt><dd>{detail.episodeId ?? '—'}</dd></div>
            <div><dt>{t('research.model')}</dt><dd>{detail.modelProfile === null ? '—' : [detail.modelProfile.label || detail.modelProfile.id, detail.modelProfile.provider, detail.modelProfile.model].filter(Boolean).join(' · ')}</dd></div>
            <div><dt>{t('research.searchProvider')}</dt><dd>{detail.searchProvider ?? '—'}</dd></div>
            <div><dt>{t('research.createdAt')}</dt><dd>{detail.createdAt ?? '—'}</dd></div>
            <div><dt>{t('research.completedAt')}</dt><dd>{detail.completedAt ?? '—'}</dd></div>
            <div><dt>{t('research.latency')}</dt><dd>{detail.latencyMs === null ? '—' : `${detail.latencyMs.toLocaleString()} ms`}</dd></div>
            <div><dt>{t('research.wordCount')}</dt><dd>{formatNumber(detail.wordCount)}</dd></div>
            <div><dt>{t('research.tokens')}</dt><dd>{detail.usage.reported ? formatNumber(detail.usage.totalTokens) : '—'}</dd></div>
            <div><dt>{t('research.cost')}</dt><dd>{formatCost(detail.cost.value, detail.cost.reported)}</dd></div>
            <div><dt>{t('research.sourcesStatus')}</dt><dd>{detail.sourcesStatus === 'ok' ? t('research.sourcesAvailable') : t('research.sourcesUnavailable')}</dd></div>
          </dl>
          <section className={css.researchSources} data-testid="research-sources">
            <h3>{t('research.sourceCheck')}</h3>
            {detail.sources === null ? <div className={css.detailNotice}>{t('research.sourcesUnavailable')}</div> : detail.sources.length === 0 ? <div className={css.detailNotice}>{t('research.sourcesEmpty')}</div> : <div className={css.researchSourceList}>{detail.sources.map((source, index) => {
              const href = safeSourceUrl(source.url)
              return <article key={`${source.url}:${index}`}>
                <div>{href === null ? <strong>{source.title || source.url || `#${index + 1}`}</strong> : <a href={href} target="_blank" rel="noreferrer"><strong>{source.title || href}</strong><ExternalLink size={12} /></a>}<span data-cited={source.cited}>{source.cited ? t('research.source.cited') : t('research.source.uncited')}</span></div>
                <small>{source.sourceType || '—'} · {source.url || '—'}</small>
              </article>
            })}</div>}
          </section>
          {Object.keys(detail.metrics).length > 0 && <details className={css.researchMetrics}><summary>{t('research.metrics')}</summary><dl>{Object.entries(detail.metrics).map(([key, value]) => <div key={key}><dt>{key}</dt><dd>{typeof value === 'object' ? JSON.stringify(value) : String(value)}</dd></div>)}</dl></details>}
          {report.content !== '' && <div className={css.detailBody}><MarkdownText text={report.content} /></div>}
        </article>}
      </main>
    </div>}
  </div>
}
