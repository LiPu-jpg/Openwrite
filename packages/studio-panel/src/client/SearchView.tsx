/**
 * Search view (搜索): native project search over the OpenWrite library —
 * debounced query input + scope selector, results with the query highlighted
 * in the snippet. Click-to-read: any result opens an inline preview pane
 * (document via GET /api/document?path=…, hit line highlighted). GET-only;
 * this is the panel's one interactive (non-mutating) view.
 *
 * Wire shape (verified against OpenWrite tools/studio_http.py do_GET +
 * tools/studio_application.py search_project + tools/project_search.py
 * ProjectSearchIndex.search + tools/library_catalog.py scopes):
 * GET /api/search?q=<query>&scope=<scope>&limit=<n> answers WITHOUT an
 * envelope —
 * {
 *   query, scope, scope_label,
 *   results: [{ path, title, line, heading, snippet, scope, scope_label,
 *               category, category_label, score, retrieval: [...], excerpt }],
 *   indexed, engine (lightrag/literal-fallback/none),
 *   warning, warning_code, retrieval_stats, index_updates, embedding,
 * }
 * GET /api/document?path=<p> answers WITHOUT an envelope —
 * { path, title, content, version, revision, ... } (any project document:
 * outline / manuscript chapters / character & world sources).
 * Canonical scopes (library_catalog.py CANONICAL_SEARCH_SCOPES): all /
 * outline / core / characters / settings / continuity / chapters / sources.
 * The payload carries no match offsets, so highlighting re-matches the
 * (server-normalized) query inside the snippet client-side.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { ConvViewProps } from '@deepseek-ai/dsh-client-ui-conversation/client'
import type { InjectFace, PropsLocale } from '@deepseek-ai/dsh-client-ui-slots'
import { StudioApiError, type StudioApiInjected } from './api.ts'
import { parseDocumentChangePlan, type DocumentChangePlanDto } from './dto.ts'
import { useWorkbench, workbenchStore } from './WorkbenchStore.ts'
import css from './views.module.css'

/** Debounce between the last keystroke and the request. */
const DEBOUNCE_MS = 350

/**
 * A hung upstream (wedged Studio, dead proxy keep-alive) must not pin the
 * view on the loading notice forever: after this the request is dropped and
 * the error state offers a retry.
 */
const SEARCH_TIMEOUT_MS = 15_000

/** Canonical scope values, display order (server: CANONICAL_SEARCH_SCOPES). */
const SCOPES = ['all', 'outline', 'core', 'characters', 'settings', 'continuity', 'chapters', 'sources'] as const

type Scope = (typeof SCOPES)[number]

/** One result row (the fields this view reads; the payload carries more). */
interface SearchResult {
  documentId: string
  revision: string
  path: string
  title: string
  line: number
  heading: string
  snippet: string
  scopeLabel: string
  categoryLabel: string
}

interface SearchPayload {
  query: string
  results: SearchResult[]
  indexed: number
  warning: string
}

type LoadState = 'idle' | 'loading' | 'error' | 'ready'

/** Inline preview state for one clicked result. */
interface PreviewState {
  result: SearchResult
  status: 'loading' | 'ready' | 'error'
  content: string
  message: string
  documentPath: string
  documentId: string
  documentRevision: string
}

function record(value: unknown): Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {}
}

function lineAt(content: string, line: number): string {
  return line > 0 ? content.split('\n')[line - 1] ?? '' : ''
}

/** Narrow the search payload, tolerating missing/extra fields. */
function parseSearch(data: unknown): SearchPayload {
  const root = (data !== null && typeof data === 'object' ? data : {}) as Record<string, unknown>
  const results = Array.isArray(root['results']) ? root['results'] : []
  return {
    query: String(root['query'] ?? ''),
    results: results.map(item => {
      const r = (item !== null && typeof item === 'object' ? item : {}) as Record<string, unknown>
      return {
        documentId: String(r['document_id'] ?? ''),
        revision: String(r['revision'] ?? ''),
        path: String(r['path'] ?? ''),
        title: String(r['title'] ?? ''),
        line: typeof r['line'] === 'number' ? r.line : 0,
        heading: String(r['heading'] ?? ''),
        snippet: String(r['snippet'] ?? ''),
        scopeLabel: String(r['scope_label'] ?? ''),
        categoryLabel: String(r['category_label'] ?? ''),
      }
    }),
    indexed: typeof root['indexed'] === 'number' ? root.indexed : 0,
    warning: String(root['warning'] ?? ''),
  }
}

/** Split a snippet around case-insensitive query matches for highlighting. */
function highlight(snippet: string, query: string): { text: string; match: boolean }[] {
  const trimmed = query.trim()
  if (trimmed === '') return [{ text: snippet, match: false }]
  const parts: { text: string; match: boolean }[] = []
  let rest = snippet
  while (rest !== '') {
    const index = rest.toLowerCase().indexOf(trimmed.toLowerCase())
    if (index < 0) {
      parts.push({ text: rest, match: false })
      break
    }
    if (index > 0) parts.push({ text: rest.slice(0, index), match: false })
    parts.push({ text: rest.slice(index, index + trimmed.length), match: true })
    rest = rest.slice(index + trimmed.length)
  }
  if (parts.length === 0) parts.push({ text: snippet, match: false })
  return parts
}

/** Full search-view props: conversation-view runtime share & injected fetch & locale seat. */
export type SearchViewProps =
  ConvViewProps & InjectFace<StudioApiInjected> & PropsLocale<'studio-panel'>

export function SearchView({ fetchStudioApi, postStudioApi, t }: SearchViewProps) {
  const workbench = useWorkbench()
  const [input, setInput] = useState('')
  const [scope, setScope] = useState<Scope>('all')
  const [state, setState] = useState<LoadState>('idle')
  const [payload, setPayload] = useState<SearchPayload | null>(null)
  const [error, setError] = useState('')
  const [timedOut, setTimedOut] = useState(false)
  // Retry signal: bumping re-runs the effect with unchanged query/scope.
  const [nonce, setNonce] = useState(0)
  /** Inline preview for one clicked result (null = list mode). */
  const [preview, setPreview] = useState<PreviewState | null>(null)
  const [jumpNotice, setJumpNotice] = useState('')
  const [replacement, setReplacement] = useState('')
  const [changePlan, setChangePlan] = useState<DocumentChangePlanDto | null>(null)
  const [changePlanBusy, setChangePlanBusy] = useState<'preview' | 'apply' | 'reject' | ''>('')
  const [changePlanMessage, setChangePlanMessage] = useState('')
  const [changePlanConflict, setChangePlanConflict] = useState(false)
  const [changePlanApplied, setChangePlanApplied] = useState(false)
  const previewRequestRef = useRef(0)

  const resetChangePlan = useCallback(() => {
    setReplacement('')
    setChangePlan(null)
    setChangePlanBusy('')
    setChangePlanMessage('')
    setChangePlanConflict(false)
    setChangePlanApplied(false)
  }, [])

  // Debounced live search: fires 350ms after the last keystroke, immediately
  // (well, one debounce tick) on scope change. Empty query returns to idle.
  // The watchdog drops a request that never settles (wedged upstream) into
  // the error state instead of leaving the loading notice up forever.
  useEffect(() => {
    const query = input.trim()
    if (query === '') {
      setState('idle')
      setPayload(null)
      setError('')
      setTimedOut(false)
      return
    }
    setState('loading')
    setTimedOut(false)
    let cancelled = false
    let watchdog: ReturnType<typeof setTimeout> | undefined
    const timer = setTimeout(() => {
      watchdog = setTimeout(() => {
        if (cancelled) return
        cancelled = true // the late response, if any, is dropped
        setTimedOut(true)
        setState('error')
      }, SEARCH_TIMEOUT_MS)
      fetchStudioApi(`/search?q=${encodeURIComponent(query)}&scope=${scope}&limit=20`)
        .then((data) => {
          if (cancelled) return
          if (watchdog !== undefined) clearTimeout(watchdog)
          setPayload(parseSearch(data))
          setState('ready')
        })
        .catch((cause: unknown) => {
          if (cancelled) return
          if (watchdog !== undefined) clearTimeout(watchdog)
          setError(cause instanceof Error ? cause.message : String(cause))
          setState('error')
        })
    }, DEBOUNCE_MS)
    return () => {
      cancelled = true
      clearTimeout(timer)
      if (watchdog !== undefined) clearTimeout(watchdog)
    }
  }, [input, scope, nonce, fetchStudioApi])

  /** Open the inline preview: fetch the hit document, keep the hit line. */
  const openPreview = useCallback((result: SearchResult) => {
    const requestId = ++previewRequestRef.current
    setJumpNotice('')
    resetChangePlan()
    setPreview({ result, status: 'loading', content: '', message: '', documentPath: '', documentId: '', documentRevision: '' })
    fetchStudioApi(`/document?path=${encodeURIComponent(result.path)}`)
      .then((data) => {
        if (previewRequestRef.current !== requestId) return
        const document = record(data)
        const documentPath = typeof document['path'] === 'string' ? document['path'] : ''
        const documentId = typeof document['document_id'] === 'string' ? document['document_id'] : ''
        if (documentPath !== result.path) throw new Error(t('search.preview.identityMismatch'))
        if (result.documentId !== '' && documentId !== result.documentId) throw new Error(t('search.preview.identityMismatch'))
        const content = typeof document['content'] === 'string' ? document.content : ''
        setPreview({
          result,
          status: 'ready',
          content,
          message: '',
          documentPath,
          documentId: documentId || result.documentId,
          documentRevision: typeof document['revision'] === 'string' ? document['revision'] : '',
        })
        setReplacement(lineAt(content, result.line))
      })
      .catch((cause: unknown) => {
        if (previewRequestRef.current !== requestId) return
        setPreview({
          result,
          status: 'error',
          content: '',
          message: cause instanceof Error ? cause.message : String(cause),
          documentPath: '',
          documentId: '',
          documentRevision: '',
        })
      })
  }, [fetchStudioApi, resetChangePlan, t])

  const refreshSearchResult = useCallback(() => {
    previewRequestRef.current += 1
    setPreview(null)
    resetChangePlan()
    setNonce(value => value + 1)
  }, [resetChangePlan])

  const discardPreviewToken = useCallback(async (previewToken: string) => {
    if (previewToken === '') return
    try { await postStudioApi('/document/change-plan', { action: 'reject', preview_token: previewToken }) } catch { /* never apply an unverifiable token */ }
  }, [postStudioApi])

  const previewReplacement = async () => {
    const current = preview
    if (current === null || current.status !== 'ready' || changePlanBusy !== '') return
    const oldText = lineAt(current.content, current.result.line)
    const locatorCurrent = current.result.revision !== '' && current.result.revision === current.documentRevision &&
      current.result.documentId !== '' && current.result.documentId === current.documentId
    if (!locatorCurrent || oldText === '' || replacement === oldText) return
    setChangePlanBusy('preview')
    setChangePlan(null)
    setChangePlanMessage('')
    setChangePlanConflict(false)
    setChangePlanApplied(false)
    try {
      const plan = parseDocumentChangePlan(await postStudioApi('/document/change-plan', {
        action: 'preview', path: current.documentPath, edits: [{ old_text: oldText, new_text: replacement }],
      }))
      const safe = plan.path === current.documentPath && plan.changed && plan.preview_token !== '' &&
        plan.mutation_summary.execution_status === 'proposed' &&
        plan.mutation_summary.source_revision === current.result.revision &&
        plan.mutation_summary.source_revision === current.documentRevision &&
        plan.mutation_summary.result_revision !== ''
      if (!safe) {
        await discardPreviewToken(plan.preview_token)
        setChangePlanConflict(true)
        setChangePlanMessage(t('search.change.refreshRequired'))
        return
      }
      setChangePlan(plan)
    } catch (cause: unknown) {
      const conflict = cause instanceof StudioApiError && [
        'DOCUMENT_REVISION_CONFLICT', 'DOCUMENT_PREVIEW_INVALID', 'DOCUMENT_PREVIEW_RESULT_MISMATCH',
        'OLD_TEXT_NOT_FOUND', 'AMBIGUOUS_OLD_TEXT', 'AMBIGUOUS_TEXT_RANGE',
      ].includes(cause.code ?? '')
      setChangePlanConflict(conflict)
      setChangePlanMessage(conflict ? t('search.change.refreshRequired') : cause instanceof Error ? cause.message : String(cause))
    } finally {
      setChangePlanBusy('')
    }
  }

  const applyReplacement = async () => {
    const current = preview
    const plan = changePlan
    if (current === null || plan === null || changePlanBusy !== '') return
    setChangePlanBusy('apply')
    setChangePlanMessage('')
    try {
      const applied = parseDocumentChangePlan(await postStudioApi('/document/change-plan', {
        action: 'apply', preview_token: plan.preview_token,
      }))
      if (!applied.applied || applied.path !== current.documentPath ||
        applied.mutation_summary.execution_status !== 'committed' ||
        applied.mutation_summary.source_revision !== plan.mutation_summary.source_revision ||
        applied.mutation_summary.result_revision !== plan.mutation_summary.result_revision) {
        if (!applied.applied) await discardPreviewToken(plan.preview_token)
        setChangePlan(null)
        setChangePlanConflict(true)
        setChangePlanMessage(t('search.change.invalidApply'))
        workbenchStore.invalidate('manuscript')
        workbenchStore.invalidate('workspace')
        return
      }
      setChangePlan(null)
      setChangePlanMessage(t('search.change.applied'))
      setChangePlanApplied(true)
      workbenchStore.invalidate('manuscript')
      workbenchStore.invalidate('workspace')
    } catch (cause: unknown) {
      await discardPreviewToken(plan.preview_token)
      setChangePlan(null)
      setChangePlanConflict(true)
      setChangePlanMessage(t('search.change.refreshRequired'))
      workbenchStore.invalidate('manuscript')
      workbenchStore.invalidate('workspace')
    } finally {
      setChangePlanBusy('')
    }
  }

  const rejectReplacement = async () => {
    const plan = changePlan
    if (plan === null || changePlanBusy !== '') return
    setChangePlanBusy('reject')
    setChangePlanMessage('')
    try {
      const rejected = parseDocumentChangePlan(await postStudioApi('/document/change-plan', {
        action: 'reject', preview_token: plan.preview_token,
      }))
      if (rejected.status !== 'rejected') throw new Error(t('search.change.invalidReject'))
      setChangePlan(null)
      setChangePlanMessage(t('search.change.rejected'))
    } catch (cause: unknown) {
      setChangePlanMessage(cause instanceof Error ? cause.message : String(cause))
    } finally {
      setChangePlanBusy('')
    }
  }

  const meta = useMemo(() => {
    if (state !== 'ready' || payload === null) return ''
    return `${payload.results.length} / ${t('search.indexed')} ${payload.indexed}`
  }, [state, payload, t])

  return (
    <div className={css.root}>
      <div className={css.toolbar}>
        <span className={css.toolbarMeta}>
          <input
            type="search"
            className={css.searchInput}
            placeholder={t('search.placeholder')}
            value={input}
            onChange={(event) => { previewRequestRef.current += 1; setInput(event.target.value); setPreview(null); resetChangePlan() }}
          />
          <select
            className={css.scopeSelect}
            value={scope}
            onChange={(event) => { previewRequestRef.current += 1; setScope(event.target.value as Scope); setPreview(null); resetChangePlan() }}
          >
            {SCOPES.map(item => (
              <option key={item} value={item}>{t(`search.scope.${item}`)}</option>
            ))}
          </select>
          {meta !== '' && <span>{meta}</span>}
        </span>
      </div>
      <div className={css.body}>
        {preview !== null ? (
          <div className={css.previewPane}>
            <div className={css.previewHead}>
              <button type="button" className={css.actionButton}
                onClick={() => { previewRequestRef.current += 1; setPreview(null); resetChangePlan() }}>
                {t('search.preview.back')}
              </button>
              <span className={css.searchResultPath}>
                {preview.result.path}{preview.result.line > 0 ? `:${preview.result.line}` : ''}
              </span>
              <span className={css.searchResultTitle}>{preview.result.title}</span>
              {workbench.chapters.some(chapter => chapter.path === preview.documentPath) && (
                <button type="button" className={css.actionButton} onClick={() => {
                  workbenchStore.setActiveChapter(preview.documentPath)
                  setJumpNotice(t('search.preview.jumpReady'))
                }}>{t('search.preview.openCreation')}</button>
              )}
            </div>
            {preview.status === 'loading' && <div className={css.notice}>{t('loading')}</div>}
            {preview.status === 'error' && (
              <div className={css.notice}>
                <span className={css.errorText}>{preview.message}</span>
                <button type="button" className={css.button}
                  onClick={() => { openPreview(preview.result) }}>
                  {t('retry')}
                </button>
              </div>
            )}
            {preview.status === 'ready' && function renderPreviewWindow() {
              const lines = preview.content.split('\n')
              const hit = Math.max(1, preview.result.line)
              const from = Math.max(1, hit - 2)
              const to = Math.min(lines.length, hit + 2)
              const rows: { line: number; text: string }[] = []
              for (let n = from; n <= to; n++) {
                rows.push({ line: n, text: lines[n - 1] ?? '' })
              }
              const query = input.trim()
              const locatorStatus = preview.result.revision === '' || preview.result.documentId === '' || preview.documentId === ''
                ? 'unverified'
                : preview.result.revision === preview.documentRevision && preview.result.documentId === preview.documentId
                  ? 'current'
                  : 'stale'
              const oldText = lineAt(preview.content, preview.result.line)
              const canPlan = locatorStatus === 'current' && oldText !== ''
              return (
                <>
                  <div className={css.searchLocator} data-status={locatorStatus}>
                    <span>{locatorStatus === 'current'
                      ? t('search.preview.locatorCurrent')
                      : locatorStatus === 'stale'
                        ? t('search.preview.locatorStale')
                        : t('search.preview.locatorUnverified')}</span>
                    <code>{preview.documentId || preview.documentPath}</code>
                    <code>{preview.documentRevision || t('search.preview.revisionUnavailable')}</code>
                  </div>
                  {jumpNotice !== '' && <div className={css.truncatedNote} role="status">{jumpNotice}</div>}
                  {rows.map(row => (
                    <pre
                      key={row.line}
                      className={row.line === hit ? css.previewHit : css.previewLine}
                    >
                      {String(row.line).padStart(4)}  {row.text}
                    </pre>
                  ))}
                  {query.trim() !== '' && (
                    <div className={css.searchSnippet}>
                      {highlight(rows.find(row => row.line === hit)?.text ?? '', query).map((part, index) => (
                        part.match
                          ? <mark key={index} className={css.searchMark}>{part.text}</mark>
                          : <span key={index}>{part.text}</span>
                      ))}
                    </div>
                  )}
                  <section className={css.searchChangePlan} data-conflict={changePlanConflict}>
                    <header>
                      <strong>{t('search.change.title')}</strong>
                      <span>{t('search.change.serverOwned')}</span>
                    </header>
                    {!canPlan && <p>{t('search.change.unavailable')}</p>}
                    {canPlan && (
                      <>
                        <label>
                          <span>{t('search.change.currentLine')}</span>
                          <code>{oldText}</code>
                        </label>
                        <label>
                          <span>{t('search.change.replacement')}</span>
                          <textarea value={replacement} disabled={changePlan !== null || changePlanBusy !== '' || changePlanApplied}
                            onChange={event => { setReplacement(event.target.value); setChangePlanMessage(''); setChangePlanConflict(false) }} />
                        </label>
                        {changePlan === null && !changePlanApplied && <button type="button" className={css.button}
                          disabled={changePlanBusy !== '' || replacement === oldText}
                          onClick={() => { void previewReplacement() }}>
                          {changePlanBusy === 'preview' ? t('search.change.previewing') : t('search.change.preview')}
                        </button>}
                      </>
                    )}
                    {changePlan !== null && (
                      <div className={css.searchChangeDiff}>
                        <dl>
                          <div><dt>{t('search.change.sourceRevision')}</dt><dd><code>{changePlan.mutation_summary.source_revision}</code></dd></div>
                          <div><dt>{t('search.change.resultRevision')}</dt><dd><code>{changePlan.mutation_summary.result_revision}</code></dd></div>
                        </dl>
                        <pre>{changePlan.diff}</pre>
                        <div>
                          <button type="button" className={css.button} disabled={changePlanBusy !== ''}
                            onClick={() => { void rejectReplacement() }}>{t('search.change.reject')}</button>
                          <button type="button" className={css.primaryButton} disabled={changePlanBusy !== ''}
                            onClick={() => { void applyReplacement() }}>
                            {changePlanBusy === 'apply' ? t('search.change.applying') : t('search.change.confirmApply')}
                          </button>
                        </div>
                      </div>
                    )}
                    {changePlanMessage !== '' && <p role="status">{changePlanMessage}</p>}
                    {(changePlanConflict || changePlanApplied) && <button type="button" className={css.button}
                      onClick={refreshSearchResult}>{t('search.change.refresh')}</button>}
                  </section>
                </>
              )
            }()}
          </div>
        ) : (
          <>
            {state === 'idle' && <div className={css.notice}>{t('search.hint')}</div>}
            {state === 'loading' && <div className={css.notice}>{t('loading')}</div>}
            {state === 'error' && (
              <div className={css.notice}>
                <span className={css.errorText}>{timedOut ? t('search.timeout') : error}</span>
                <button type="button" className={css.button} onClick={() => { setNonce(value => value + 1) }}>
                  {t('retry')}
                </button>
              </div>
            )}
            {state === 'ready' && payload !== null && (
              <>
                {payload.warning !== '' && <div className={css.truncatedNote}>{payload.warning}</div>}
                {payload.results.length === 0
                  ? <div className={css.notice}>{t('search.empty')}</div>
                  : payload.results.map(result => (
                    <button
                      key={`${result.documentId || result.path}:${result.revision}:${result.line}`}
                      type="button"
                      className={css.searchResult}
                      onClick={() => { openPreview(result) }}
                    >
                      <div className={css.searchResultHead}>
                        <span className={css.searchResultTitle}>{result.title}</span>
                        {result.scopeLabel !== '' && <span className={css.tag}>{result.scopeLabel}</span>}
                        {result.categoryLabel !== '' && <span className={css.tag}>{result.categoryLabel}</span>}
                        <span className={css.searchResultPath}>
                          {result.path}{result.line > 0 ? `:${result.line}` : ''}
                        </span>
                      </div>
                      {result.heading !== '' && <div className={css.searchResultHeading}>{result.heading}</div>}
                      {result.snippet !== '' && (
                        <div className={css.searchSnippet}>
                          {highlight(result.snippet, payload.query).map((part, index) => (
                            part.match
                              ? <mark key={index} className={css.searchMark}>{part.text}</mark>
                              : <span key={index}>{part.text}</span>
                          ))}
                        </div>
                      )}
                    </button>
                  ))
                }
              </>
            )}
          </>
        )}
      </div>
    </div>
  )
}
