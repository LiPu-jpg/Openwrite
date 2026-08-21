/**
 * Search view (搜索): native project search over the OpenWrite library —
 * debounced query input + scope selector, results with the query highlighted
 * in the snippet. Read-only (GET only); this is the panel's one interactive
 * (non-mutating) view.
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
 * Canonical scopes (library_catalog.py CANONICAL_SEARCH_SCOPES): all /
 * outline / core / characters / settings / continuity / chapters / sources.
 * The payload carries no match offsets, so highlighting re-matches the
 * (server-normalized) query inside the snippet client-side.
 */

import { useEffect, useMemo, useState } from 'react'
import type { ConvViewProps } from '@deepseek-ai/dsh-client-ui-conversation/client'
import type { InjectFace, PropsLocale } from '@deepseek-ai/dsh-client-ui-slots'
import type { StudioApiInjected } from './api.ts'
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

/** Narrow the search payload, tolerating missing/extra fields. */
function parseSearch(data: unknown): SearchPayload {
  const root = (data !== null && typeof data === 'object' ? data : {}) as Record<string, unknown>
  const text = (value: unknown): string => (typeof value === 'string' ? value : '')
  const results: SearchResult[] = (Array.isArray(root['results']) ? root['results'] : [])
    .map((raw): SearchResult => {
      const record = (raw !== null && typeof raw === 'object' ? raw : {}) as Record<string, unknown>
      return {
        path: text(record['path']),
        title: text(record['title']) || text(record['path']),
        line: typeof record['line'] === 'number' ? record['line'] : 0,
        heading: text(record['heading']),
        snippet: text(record['snippet']) || text(record['excerpt']),
        scopeLabel: text(record['scope_label']),
        categoryLabel: text(record['category_label']),
      }
    })
  return {
    query: text(root['query']),
    results,
    indexed: typeof root['indexed'] === 'number' ? root['indexed'] : 0,
    warning: text(root['warning']),
  }
}

/** Split a snippet around case-insensitive query matches for highlighting. */
function highlight(snippet: string, query: string): { text: string; match: boolean }[] {
  const needle = query.trim()
  if (needle === '') return [{ text: snippet, match: false }]
  const parts: { text: string; match: boolean }[] = []
  const lower = snippet.toLowerCase()
  const target = needle.toLowerCase()
  let cursor = 0
  for (;;) {
    const found = lower.indexOf(target, cursor)
    if (found === -1) break
    if (found > cursor) parts.push({ text: snippet.slice(cursor, found), match: false })
    parts.push({ text: snippet.slice(found, found + needle.length), match: true })
    cursor = found + needle.length
  }
  if (cursor < snippet.length) parts.push({ text: snippet.slice(cursor), match: false })
  return parts
}

/** Full search-view props: conversation-view runtime share & injected fetch & locale seat. */
export type SearchViewProps =
  ConvViewProps & InjectFace<StudioApiInjected> & PropsLocale<'studio-panel'>

export function SearchView({ fetchStudioApi, t }: SearchViewProps) {
  const [input, setInput] = useState('')
  const [scope, setScope] = useState<Scope>('all')
  const [state, setState] = useState<LoadState>('idle')
  const [payload, setPayload] = useState<SearchPayload | null>(null)
  const [error, setError] = useState('')
  const [timedOut, setTimedOut] = useState(false)
  // Retry signal: bumping re-runs the effect with unchanged query/scope.
  const [nonce, setNonce] = useState(0)

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
            onChange={(event) => { setInput(event.target.value) }}
          />
          <select
            className={css.scopeSelect}
            value={scope}
            onChange={(event) => { setScope(event.target.value as Scope) }}
          >
            {SCOPES.map(item => (
              <option key={item} value={item}>{t(`search.scope.${item}`)}</option>
            ))}
          </select>
          {meta !== '' && <span>{meta}</span>}
        </span>
      </div>
      <div className={css.body}>
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
                <div key={`${result.path}:${result.line}`} className={css.searchResult}>
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
                </div>
              ))
            }
          </>
        )}
      </div>
    </div>
  )
}
