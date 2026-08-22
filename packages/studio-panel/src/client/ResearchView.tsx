/**
 * Research view (研究): OpenWrite deep-research reports rendered natively —
 * a master-detail list (title/status/date) with the full report body rendered
 * as markdown. launching research submits a managed background task
 * (POST /api/tasks { type: 'research', input: { prompt } } — the same lane the
 * Tasks tab renders); saving API settings stays with Studio / agent tools.
 *
 * Wire shape (verified against OpenWrite tools/studio_http.py do_GET +
 * tools/studio_application.py research_surface/research_report +
 * tools/research_service.py status/list_reports/read_report):
 * GET /api/research answers WITH the success envelope —
 * { ok, data: {
 *     available, node_ready, pnpm_ready, package_ready, dependencies_ready,
 *     setup_hint,
 *     settings: { search_provider, search_providers: [...], ... },
 *     reports: [{ id, title, status, episode_id, created_at, path, bytes,
 *                 metrics: { ... } }],
 *     model_route: { profile_id, label, model, provider, configured, ... },
 *   }, error, request_id }
 * GET /api/research/reports/{id} answers WITH the envelope —
 * { ok, data: { id, metadata: { title, status, episode_id, created_at, ... },
 *               content: <markdown string> }, ... }
 */

import { useCallback, useEffect, useState } from 'react'
import type { ConvViewProps } from '@deepseek-ai/dsh-client-ui-conversation/client'
import { MarkdownText } from '@deepseek-ai/dsh-client-ui-primitives'
import type { InjectFace, PropsLocale } from '@deepseek-ai/dsh-client-ui-slots'
import type { StudioApiInjected } from './api.ts'
import css from './views.module.css'

/** One report-list entry (the fields this view reads; the payload carries more). */
interface ResearchReport {
  id: string
  title: string
  status: string
  episodeId: string
  createdAt: string
  quality: string
  language: string
}

interface ResearchSurface {
  available: boolean
  setupHint: string
  reports: ResearchReport[]
}

/** A fetched report body. */
interface ReportBody {
  title: string
  status: string
  episodeId: string
  createdAt: string
  content: string
}

type LoadState = 'loading' | 'error' | 'ready'

/** Narrow one wire report entry, tolerating missing/extra fields. */
function parseReport(raw: unknown): ResearchReport {
  const record = (raw !== null && typeof raw === 'object' ? raw : {}) as Record<string, unknown>
  const text = (value: unknown): string => (typeof value === 'string' ? value : '')
  const metrics = (record['metrics'] !== null && typeof record['metrics'] === 'object' ? record['metrics'] : {}) as Record<string, unknown>
  // quality/language surface either top-level or inside metrics, as scalars.
  const scalar = (value: unknown): string =>
    typeof value === 'string' ? value : typeof value === 'number' ? String(value) : ''
  return {
    id: text(record['id']),
    title: text(record['title']) || text(record['id']),
    status: text(record['status']),
    episodeId: text(record['episode_id']),
    createdAt: text(record['created_at']),
    quality: scalar(record['quality']) || scalar(metrics['quality']),
    language: scalar(record['language']) || scalar(metrics['language']),
  }
}

/** Unwrap the success envelope and narrow the surface (empty on garbage). */
function parseSurface(data: unknown): ResearchSurface {
  const envelope = (data !== null && typeof data === 'object' ? data : {}) as Record<string, unknown>
  const inner = (envelope['data'] !== null && typeof envelope['data'] === 'object' ? envelope['data'] : {}) as Record<string, unknown>
  return {
    available: inner['available'] === true,
    setupHint: typeof inner['setup_hint'] === 'string' ? inner['setup_hint'] : '',
    reports: Array.isArray(inner['reports']) ? inner['reports'].map(parseReport) : [],
  }
}

/** Unwrap the report-body envelope. */
function parseReportBody(data: unknown): ReportBody {
  const envelope = (data !== null && typeof data === 'object' ? data : {}) as Record<string, unknown>
  const inner = (envelope['data'] !== null && typeof envelope['data'] === 'object' ? envelope['data'] : {}) as Record<string, unknown>
  const metadata = (inner['metadata'] !== null && typeof inner['metadata'] === 'object' ? inner['metadata'] : {}) as Record<string, unknown>
  const text = (value: unknown): string => (typeof value === 'string' ? value : '')
  return {
    title: text(metadata['title']) || text(inner['id']),
    status: text(metadata['status']),
    episodeId: text(metadata['episode_id']),
    createdAt: text(metadata['created_at']),
    content: text(inner['content']),
  }
}

/** `2026-08-20T11:21:41` → `08-20 11:21` (defensive: unrecognized shapes pass through trimmed). */
function shortTime(iso: string): string {
  const match = /^\d{4}-(\d{2}-\d{2})[T ](\d{2}:\d{2})/.exec(iso)
  return match !== null ? `${match[1]} ${match[2]}` : iso.slice(0, 16)
}

/** Full research-view props: conversation-view runtime share & injected fetch & locale seat. */
export type ResearchViewProps =
  ConvViewProps & InjectFace<StudioApiInjected> & PropsLocale<'studio-panel'>

export function ResearchView({ fetchStudioApi, postStudioApi, t }: ResearchViewProps) {
  const [state, setState] = useState<LoadState>('loading')
  const [surface, setSurface] = useState<ResearchSurface | null>(null)
  const [error, setError] = useState('')
  const [selectedId, setSelectedId] = useState('')
  const [reportState, setReportState] = useState<LoadState>('loading')
  const [report, setReport] = useState<ReportBody | null>(null)
  const [reportError, setReportError] = useState('')
  /** 发起研究：折叠面板状态 */
  const [launchOpen, setLaunchOpen] = useState(false)
  const [launchPrompt, setLaunchPrompt] = useState('')
  const [launchBusy, setLaunchBusy] = useState(false)
  const [launchNote, setLaunchNote] = useState<{ text: string; bad: boolean } | null>(null)

  const load = useCallback(() => {
    setState('loading')
    let cancelled = false
    fetchStudioApi('/research')
      .then((data) => {
        if (cancelled) return
        setSurface(parseSurface(data))
        setState('ready')
      })
      .catch((cause: unknown) => {
        if (cancelled) return
        setError(cause instanceof Error ? cause.message : String(cause))
        setState('error')
      })
    return () => { cancelled = true }
  }, [fetchStudioApi])

  useEffect(() => load(), [load])

  const openReport = useCallback((id: string) => {
    setSelectedId(id)
    setReportState('loading')
    setReport(null)
    setReportError('')
    let cancelled = false
    fetchStudioApi(`/research/reports/${encodeURIComponent(id)}`)
      .then((data) => {
        if (cancelled) return
        setReport(parseReportBody(data))
        setReportState('ready')
      })
      .catch((cause: unknown) => {
        if (cancelled) return
        setReportError(cause instanceof Error ? cause.message : String(cause))
        setReportState('error')
      })
    return () => { cancelled = true }
  }, [fetchStudioApi])

  /** Submit one deep-research task; progress shows up in the Tasks tab. */
  const submitResearch = async () => {
    const prompt = launchPrompt.trim()
    if (prompt === '' || launchBusy) return
    setLaunchBusy(true)
    setLaunchNote(null)
    try {
      await postStudioApi('/tasks', { type: 'research', input: { prompt } })
      setLaunchNote({ text: t('research.launch.submitted'), bad: false })
      setLaunchPrompt('')
      load()
    } catch (cause: unknown) {
      setLaunchNote({
        text: `${t('research.launch.failed')}: ${cause instanceof Error ? cause.message : String(cause)}`,
        bad: true,
      })
    } finally {
      setLaunchBusy(false)
    }
  }

  const selected = surface?.reports.find(item => item.id === selectedId)

  return (
    <div className={css.root}>
      <div className={css.toolbar}>
        <span className={css.toolbarMeta}>
          {state === 'ready' && surface !== null && (
            surface.available
              ? `${t('research.reports')}: ${surface.reports.length}`
              : surface.setupHint !== '' ? surface.setupHint : t('research.unavailable')
          )}
        </span>
        <button
          type="button"
          className={css.button}
          disabled={!surface?.available || launchBusy}
          title={surface?.available === false ? surface.setupHint : undefined}
          onClick={() => { setLaunchOpen(previous => !previous) }}
        >
          {t('research.launch')}
        </button>
        <button type="button" className={css.button} onClick={() => { load() }}>
          {t('refresh')}
        </button>
      </div>
      {launchOpen && (
        <div className={css.launchPanel}>
          <textarea
            className={css.summaryTextarea}
            rows={3}
            value={launchPrompt}
            placeholder={t('research.launch.placeholder')}
            onChange={event => { setLaunchPrompt(event.target.value) }}
          />
          <div className={css.inlineActions}>
            <button
              type="button"
              className={css.button}
              disabled={launchBusy || launchPrompt.trim() === ''}
              onClick={() => { void submitResearch() }}
            >
              {launchBusy ? t('research.launch.submitting') : t('research.launch.submit')}
            </button>
            <span className={css.toolbarMeta}>{t('research.launch.hint')}</span>
          </div>
          {launchNote !== null && (
            <div className={css.notice}>
              <span className={launchNote.bad ? css.errorText : undefined}>{launchNote.text}</span>
            </div>
          )}
        </div>
      )}
      {state === 'loading' && <div className={css.body}><div className={css.notice}>{t('loading')}</div></div>}
      {state === 'error' && (
        <div className={css.body}>
          <div className={css.notice}>
            <span className={css.errorText}>{error}</span>
            <button type="button" className={css.button} onClick={() => { load() }}>{t('retry')}</button>
          </div>
        </div>
      )}
      {state === 'ready' && surface !== null && (
        <div className={css.libraryRoot}>
          <div className={css.sidebar}>
            <div className={css.sidebarList}>
              {surface.reports.length === 0 && (
                <div className={css.sidebarEmpty}>{t('research.empty')}</div>
              )}
              {surface.reports.map(item => (
                <button
                  key={item.id}
                  type="button"
                  className={css.assetRow}
                  data-active={item.id === selectedId}
                  onClick={() => { openReport(item.id) }}
                >
                  <span className={css.assetRowName}>{item.title}</span>
                  <span className={css.assetRowMeta}>
                    {[item.status, item.createdAt !== '' ? shortTime(item.createdAt) : '']
                      .filter(part => part !== '').join(' · ')}
                  </span>
                </button>
              ))}
            </div>
          </div>
          <div className={css.mainPane}>
            {selectedId === '' && <div className={css.detailNotice}>{t('research.selectHint')}</div>}
            {selectedId !== '' && reportState === 'loading' && (
              <div className={css.detailNotice}>{t('research.report.loading')}</div>
            )}
            {selectedId !== '' && reportState === 'error' && (
              <div className={css.detailNotice}>
                <span className={css.errorText}>{reportError}</span>{' '}
                <button type="button" className={css.button} onClick={() => { openReport(selectedId) }}>{t('retry')}</button>
              </div>
            )}
            {selectedId !== '' && reportState === 'ready' && report !== null && (
              <div className={css.detail}>
                <div className={css.detailHeader}>
                  <div className={css.detailTitleRow}>
                    <span className={css.detailTitle}>{report.title}</span>
                  </div>
                  <div className={css.assetMeta}>
                    {report.status !== '' && <span className={css.tag}>{report.status}</span>}
                    {report.episodeId !== '' && <span className={css.tag}>{report.episodeId}</span>}
                    {report.createdAt !== '' && <span className={css.tag}>{shortTime(report.createdAt)}</span>}
                    {selected?.quality !== undefined && selected.quality !== '' && (
                      <span className={css.tag}>{t('research.quality')} {selected.quality}</span>
                    )}
                    {selected?.language !== undefined && selected.language !== '' && (
                      <span className={css.tag}>{t('research.language')} {selected.language}</span>
                    )}
                  </div>
                </div>
                {report.content !== '' && <div className={css.detailBody}><MarkdownText text={report.content} /></div>}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
