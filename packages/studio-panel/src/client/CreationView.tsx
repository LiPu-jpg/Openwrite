import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  BookOpen, ChevronRight, History, PanelLeft, PanelLeftClose, PanelLeftOpen, PanelRight,
  PanelRightClose, PanelRightOpen, RefreshCw, Save, Search, ShieldAlert, X,
} from 'lucide-react'
import { MarkdownText } from '@deepseek-ai/dsh-client-ui-primitives'
import type { ConvViewProps } from '@deepseek-ai/dsh-client-ui-conversation/client'
import type { InjectFace, PropsLocale } from '@deepseek-ai/dsh-client-ui-slots'
import { StudioApiError, type StudioApiInjected } from './api.ts'
import { loadVditor, VditorBody } from './VditorBody.tsx'
import { useWorkbench, workbenchStore } from './WorkbenchStore.ts'
import css from './Workbench.module.css'

type InspectorTab = 'context' | 'review' | 'revisions'
type LoadState = 'idle' | 'loading' | 'ready' | 'error'

interface DocumentPayload {
  path: string
  title: string
  content: string
  version: string
  revision: string
}

interface ContextSection {
  title: string
  markdown: string
}

function record(value: unknown): Record<string, unknown> {
  return value !== null && typeof value === 'object' ? value as Record<string, unknown> : {}
}

function parseDocument(value: unknown): DocumentPayload {
  const item = record(value)
  return {
    path: typeof item['path'] === 'string' ? item['path'] : '',
    title: typeof item['title'] === 'string' ? item['title'] : '',
    content: typeof item['content'] === 'string' ? item['content'] : '',
    version: String(item['version'] ?? ''),
    revision: String(item['revision'] ?? ''),
  }
}

function chapterId(path: string): string {
  return /(?:^|\/)(ch_[A-Za-z0-9_-]+)\.md$/.exec(path)?.[1] ?? ''
}

function storedPaneState(key: string, fallback: boolean): boolean {
  if (typeof window === 'undefined') return fallback
  try {
    const value = window.localStorage.getItem(key)
    return value === null ? fallback : value === 'true'
  } catch {
    return fallback
  }
}

function compactInspectorLayout(): boolean {
  return typeof window !== 'undefined' && window.matchMedia('(max-width: 900px)').matches
}

function splitContextSections(markdown: string, fallbackTitle: string): ContextSection[] {
  const sections: ContextSection[] = []
  let title = fallbackTitle
  let lines: string[] = []
  const flush = () => {
    const body = lines.join('\n').trim()
    if (body !== '') sections.push({ title, markdown: body })
  }
  for (const line of markdown.split('\n')) {
    const heading = /^##\s+(.+?)\s*$/.exec(line)
    if (heading === null) {
      lines.push(line)
      continue
    }
    flush()
    title = heading[1] ?? fallbackTitle
    lines = []
  }
  flush()
  return sections.length > 0 ? sections : [{ title: fallbackTitle, markdown }]
}

function ContextDocument({ markdown, fallbackTitle }: { markdown: string; fallbackTitle: string }) {
  const sections = useMemo(() => splitContextSections(markdown, fallbackTitle), [fallbackTitle, markdown])
  const [open, setOpen] = useState<ReadonlySet<number>>(() => new Set([0]))
  return <div className={css.contextSections}>
    {sections.map((section, index) => {
      const expanded = open.has(index)
      return <section key={`${section.title}:${String(index)}`} className={css.contextSection}>
        <button type="button" className={css.contextSectionButton} aria-expanded={expanded}
          onClick={() => setOpen(previous => {
            const next = new Set(previous)
            if (next.has(index)) next.delete(index)
            else next.add(index)
            return next
          })}>
          <ChevronRight size={14} aria-hidden="true" />
          <span>{section.title}</span>
        </button>
        {expanded && <div className={css.contextSectionBody}><MarkdownText text={section.markdown} /></div>}
      </section>
    })}
  </div>
}

export type CreationViewProps = ConvViewProps & InjectFace<StudioApiInjected> & PropsLocale<'studio-panel'>

/** Native manuscript workbench: chapter rail, local Vditor editor and inspector. */
export function CreationView({ fetchStudioApi, putStudioApi, t }: CreationViewProps) {
  const workbench = useWorkbench()
  const [documentState, setDocumentState] = useState<LoadState>('idle')
  const [document_, setDocument] = useState<DocumentPayload | null>(null)
  const [draft, setDraft] = useState('')
  const [loadError, setLoadError] = useState('')
  const [editorFailed, setEditorFailed] = useState(false)
  const [editorReady, setEditorReady] = useState(false)
  const [editorEpoch, setEditorEpoch] = useState(0)
  const [inspectorTab, setInspectorTab] = useState<InspectorTab>('context')
  const [inspectorState, setInspectorState] = useState<LoadState>('idle')
  const [inspectorSlow, setInspectorSlow] = useState(false)
  const [inspectorError, setInspectorError] = useState('')
  const [inspectorReload, setInspectorReload] = useState(0)
  const [compactLayout, setCompactLayout] = useState(compactInspectorLayout)
  const [context, setContext] = useState('')
  const [revisions, setRevisions] = useState<unknown>(null)
  const [chapterQuery, setChapterQuery] = useState('')
  const [chapterRailVisible, setChapterRailVisible] = useState(() => storedPaneState('dsh-novel.chapterRailVisible', true))
  const [inspectorVisible, setInspectorVisible] = useState(() => storedPaneState('dsh-novel.inspectorVisible', false))
  const [leftOpen, setLeftOpen] = useState(false)
  const [rightOpen, setRightOpen] = useState(false)
  const savedContentRef = useRef('')
  const draftRef = useRef('')
  const dirtyRef = useRef(false)
  const saveTimerRef = useRef<number | null>(null)
  const inspectorLoadedKeyRef = useRef('')
  const fetchStudioApiRef = useRef(fetchStudioApi)
  fetchStudioApiRef.current = fetchStudioApi
  const path = workbench.activeChapterPath
  const activeChapter = workbench.chapters.find(chapter => chapter.path === path)
  const normalizedQuery = chapterQuery.trim().toLocaleLowerCase()
  const visibleChapters = workbench.chapters
    .map((chapter, index) => ({ chapter, index }))
    .filter(({ chapter }) => normalizedQuery === '' ||
      `${chapter.title} ${chapter.subtitle} ${chapter.path}`.toLocaleLowerCase().includes(normalizedQuery))
  const inspectorRequested = compactLayout ? rightOpen : inspectorVisible

  useEffect(() => {
    void loadVditor().catch(() => {
      // VditorBody retries and owns the fallback state when the document mounts.
    })
    const query = window.matchMedia('(max-width: 900px)')
    const updateLayout = () => setCompactLayout(query.matches)
    query.addEventListener('change', updateLayout)
    return () => query.removeEventListener('change', updateLayout)
  }, [])

  const loadDocument = useCallback(async (allowDiscard = false) => {
    if (path === '') return
    if (dirtyRef.current && !allowDiscard) {
      workbenchStore.setEditorStatus('conflict', t('creation.changedElsewhere'))
      return
    }
    setDocumentState('loading')
    setLoadError('')
    setEditorReady(false)
    workbenchStore.setEditorStatus('loading')
    try {
      const data = parseDocument(await fetchStudioApi(`/document?path=${encodeURIComponent(path)}`))
      setDocument(data)
      setDraft(data.content)
      draftRef.current = data.content
      savedContentRef.current = data.content
      dirtyRef.current = false
      setEditorFailed(false)
      setEditorEpoch(value => value + 1)
      setDocumentState('ready')
      workbenchStore.setEditorStatus('saved')
    } catch (cause: unknown) {
      const message = cause instanceof Error ? cause.message : String(cause)
      setLoadError(message)
      setDocumentState('error')
      workbenchStore.setEditorStatus('offline', message)
    }
  }, [fetchStudioApi, path, t])

  useEffect(() => {
    dirtyRef.current = false
    void loadDocument(true)
    return () => {
      if (saveTimerRef.current !== null) window.clearTimeout(saveTimerRef.current)
    }
  }, [loadDocument])

  useEffect(() => {
    if (workbench.epochs.manuscript === 0 || documentState !== 'ready') return
    void loadDocument(false)
    // Resource epochs are the signal; documentState/loadDocument are intentionally read at signal time.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [workbench.epochs.manuscript])

  useEffect(() => {
    if (path === '' || !inspectorRequested) return
    const requestKey = `${path}:${String(workbench.epochs.revisions)}:${String(inspectorReload)}`
    if (inspectorLoadedKeyRef.current === requestKey) return
    const id = chapterId(path)
    let cancelled = false
    const slowTimer = window.setTimeout(() => {
      if (!cancelled) setInspectorSlow(true)
    }, 4_000)
    setInspectorState('loading')
    setInspectorSlow(false)
    setInspectorError('')
    setContext('')
    setRevisions(null)
    void Promise.all([
      fetchStudioApiRef.current(`/context?chapter=${encodeURIComponent(id)}`),
      fetchStudioApiRef.current(`/revisions?chapter=${encodeURIComponent(id)}`),
    ]).then(([contextPayload, revisionPayload]) => {
      if (cancelled) return
      const contextRecord = record(contextPayload)
      setContext(typeof contextRecord['markdown'] === 'string' ? contextRecord['markdown'] : '')
      setRevisions(record(revisionPayload)['data'] ?? revisionPayload)
      inspectorLoadedKeyRef.current = requestKey
      setInspectorState('ready')
    }).catch((cause: unknown) => {
      if (!cancelled) {
        setInspectorError(cause instanceof Error ? cause.message : String(cause))
        setInspectorState('error')
      }
    }).finally(() => window.clearTimeout(slowTimer))
    return () => {
      cancelled = true
      window.clearTimeout(slowTimer)
    }
  }, [inspectorReload, inspectorRequested, path, workbench.epochs.revisions])

  useEffect(() => {
    const beforeUnload = (event: BeforeUnloadEvent) => {
      if (!dirtyRef.current) return
      event.preventDefault()
      event.returnValue = ''
    }
    window.addEventListener('beforeunload', beforeUnload)
    return () => window.removeEventListener('beforeunload', beforeUnload)
  }, [])

  useEffect(() => {
    if (!leftOpen && !rightOpen) return
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return
      setLeftOpen(false)
      setRightOpen(false)
    }
    window.addEventListener('keydown', closeOnEscape)
    return () => window.removeEventListener('keydown', closeOnEscape)
  }, [leftOpen, rightOpen])

  const save = useCallback(async (force = false) => {
    if (document_ === null || !dirtyRef.current) return
    if (saveTimerRef.current !== null) window.clearTimeout(saveTimerRef.current)
    workbenchStore.setEditorStatus('saving')
    try {
      const result = parseDocument(await putStudioApi('/document', {
        path: document_.path,
        content: draftRef.current,
        version: document_.version,
        ...(force ? { force: true } : {}),
      }))
      const savedDraft = draftRef.current
      const next = { ...document_, ...result, content: savedDraft }
      setDocument(next)
      savedContentRef.current = savedDraft
      dirtyRef.current = false
      workbenchStore.setEditorStatus('saved')
      workbenchStore.invalidate('workspace')
    } catch (cause: unknown) {
      if (cause instanceof StudioApiError && cause.status === 409) {
        workbenchStore.setEditorStatus('conflict', t('creation.conflict'))
      } else {
        workbenchStore.setEditorStatus('offline', cause instanceof Error ? cause.message : String(cause))
      }
    }
  }, [document_, putStudioApi, t])

  const updateDraft = (value: string) => {
    setDraft(value)
    draftRef.current = value
    const dirty = value !== savedContentRef.current
    dirtyRef.current = dirty
    workbenchStore.setEditorStatus(dirty ? 'dirty' : 'saved')
    if (saveTimerRef.current !== null) window.clearTimeout(saveTimerRef.current)
    if (dirty) saveTimerRef.current = window.setTimeout(() => { void save() }, 1_200)
  }

  const chooseChapter = (nextPath: string) => {
    if (dirtyRef.current && !window.confirm(t('creation.discardConfirm'))) return
    dirtyRef.current = false
    workbenchStore.setActiveChapter(nextPath)
    setLeftOpen(false)
  }

  const reload = () => {
    if (dirtyRef.current && !window.confirm(t('creation.discardConfirm'))) return
    dirtyRef.current = false
    void loadDocument(true)
  }

  const overwrite = () => {
    if (!window.confirm(t('creation.overwriteConfirm'))) return
    void save(true)
  }

  const toggleChapterRail = () => {
    setChapterRailVisible((visible) => {
      try { window.localStorage.setItem('dsh-novel.chapterRailVisible', String(!visible)) } catch { /* unavailable storage */ }
      return !visible
    })
  }

  const toggleInspector = () => {
    setInspectorVisible((visible) => {
      try { window.localStorage.setItem('dsh-novel.inspectorVisible', String(!visible)) } catch { /* unavailable storage */ }
      return !visible
    })
  }

  return (
    <div className={css.creationRoot} data-chapter-rail-visible={chapterRailVisible} data-inspector-visible={inspectorVisible}>
      <div className={css.mobileBar}>
        <button type="button" className={css.iconButton} title={t('creation.chapters')}
          aria-label={t('creation.chapters')} aria-expanded={leftOpen} onClick={() => setLeftOpen(value => !value)}>
          <PanelLeft size={18} />
        </button>
        <span className={css.mobileTitle}>{activeChapter?.title ?? t('creation.empty')}</span>
        <button type="button" className={css.iconButton} title={t('creation.inspector')}
          aria-label={t('creation.inspector')} aria-expanded={rightOpen} onClick={() => setRightOpen(value => !value)}>
          <PanelRight size={18} />
        </button>
      </div>

      <aside className={css.chapterRail} data-mobile-open={leftOpen}>
        <div className={css.paneHeading}>
          <BookOpen size={15} />{t('creation.chapters')}
          <button type="button" className={`${css.drawerClose} ${css.chapterDrawerClose}`}
            title={t('creation.closePanel')} aria-label={t('creation.closePanel')} onClick={() => setLeftOpen(false)}>
            <X size={15} />
          </button>
        </div>
        <label className={css.chapterSearch}>
          <Search size={14} aria-hidden="true" />
          <span className={css.visuallyHidden}>{t('creation.searchChapters')}</span>
          <input value={chapterQuery} placeholder={t('creation.searchChapters')} aria-label={t('creation.searchChapters')}
            onChange={event => setChapterQuery(event.target.value)} />
          {chapterQuery !== '' && (
            <button type="button" title={t('creation.clearSearch')} aria-label={t('creation.clearSearch')}
              onClick={() => setChapterQuery('')}><X size={13} /></button>
          )}
        </label>
        <div className={css.chapterList}>
          {visibleChapters.map(({ chapter, index }) => (
            <button key={chapter.path} type="button" className={css.chapterButton} data-active={chapter.path === path}
              aria-current={chapter.path === path ? 'page' : undefined}
              onClick={() => chooseChapter(chapter.path)}>
              <span className={css.chapterIndex}>{String(index + 1).padStart(2, '0')}</span>
              <span className={css.chapterText}>
                <span className={css.chapterTitle}>{chapter.title}</span>
                <span className={css.chapterMeta}>{chapter.subtitle}</span>
              </span>
            </button>
          ))}
          {visibleChapters.length === 0 && <div className={css.chapterEmpty}>{t('creation.chaptersEmpty')}</div>}
        </div>
      </aside>

      <main className={css.editorPane}>
        <header className={css.editorHeader}>
          <div className={css.editorIdentity}>
            <strong>{document_?.title || activeChapter?.title || t('creation.empty')}</strong>
            <span>{path}</span>
          </div>
          <div className={css.editorActions}>
            <button type="button" className={`${css.iconButton} ${css.desktopPaneButton}`}
              title={chapterRailVisible ? t('creation.hideChapters') : t('creation.showChapters')}
              aria-label={chapterRailVisible ? t('creation.hideChapters') : t('creation.showChapters')}
              aria-expanded={chapterRailVisible} onClick={toggleChapterRail}>
              {chapterRailVisible ? <PanelLeftClose size={17} /> : <PanelLeftOpen size={17} />}
            </button>
            <button type="button" className={`${css.iconButton} ${css.desktopPaneButton}`}
              title={inspectorVisible ? t('creation.hideInspector') : t('creation.showInspector')}
              aria-label={inspectorVisible ? t('creation.hideInspector') : t('creation.showInspector')}
              aria-expanded={inspectorVisible} onClick={toggleInspector}>
              {inspectorVisible ? <PanelRightClose size={17} /> : <PanelRightOpen size={17} />}
            </button>
            <button type="button" className={`${css.iconButton} ${css.tabletInspectorButton}`}
              title={t('creation.inspector')} aria-label={t('creation.inspector')}
              aria-expanded={rightOpen} onClick={() => setRightOpen(value => !value)}>
              <PanelRight size={17} />
            </button>
            <div className={css.saveState} data-status={workbench.editorStatus} title={workbench.editorMessage}>
              <Save size={14} />{t(`creation.status.${workbench.editorStatus}`)}
            </div>
          </div>
        </header>

        {documentState === 'loading' && (
          <div className={css.documentSkeleton} role="status" aria-live="polite">
            <span>{t('creation.documentLoading')}</span><i /><i /><i />
          </div>
        )}
        {documentState === 'error' && (
          <div className={css.centerNotice}>
            <span>{loadError}</span>
            <button type="button" className={css.commandButton} onClick={reload}><RefreshCw size={15} />{t('retry')}</button>
          </div>
        )}
        {documentState === 'ready' && document_ !== null && (
          <div className={css.manuscriptEditor} aria-busy={!editorReady && !editorFailed}>
            {workbench.editorStatus === 'conflict' && (
              <div className={css.conflictBar}>
                <ShieldAlert size={16} />
                <span>{workbench.editorMessage || t('creation.conflict')}</span>
                <button type="button" onClick={reload}>{t('creation.reload')}</button>
                <button type="button" onClick={overwrite}>{t('creation.overwrite')}</button>
              </div>
            )}
            {editorFailed ? (
              <textarea className={css.manuscriptFallback} value={draft} onChange={event => updateDraft(event.target.value)} />
            ) : (
              <VditorBody key={`${path}:${editorEpoch}`} initial={draft} disabled={false} onChange={updateDraft}
                onReady={() => setEditorReady(true)} onFailed={() => { setEditorReady(true); setEditorFailed(true) }} />
            )}
            {!editorReady && !editorFailed && (
              <div className={css.editorBoot} role="status" aria-live="polite">
                <span>{t('creation.editorLoading')}</span><i /><i /><i />
              </div>
            )}
          </div>
        )}
      </main>

      <aside className={css.inspector} data-mobile-open={rightOpen}>
        <div className={css.inspectorHeader}>
          <div className={css.inspectorTabs} role="tablist" aria-label={t('creation.inspector')}>
            {(['context', 'review', 'revisions'] as const).map(tab => (
              <button key={tab} type="button" role="tab" aria-selected={inspectorTab === tab}
                data-active={inspectorTab === tab} onClick={() => setInspectorTab(tab)}>
                {tab === 'context' ? t('creation.context') : tab === 'review' ? t('creation.review') : t('creation.revisions')}
              </button>
            ))}
          </div>
          <button type="button" className={`${css.drawerClose} ${css.inspectorDrawerClose}`}
            title={t('creation.closePanel')} aria-label={t('creation.closePanel')} onClick={() => setRightOpen(false)}>
            <X size={15} />
          </button>
        </div>
        <div className={css.inspectorBody} role="tabpanel">
          {inspectorState === 'loading' && (
            <div className={css.inspectorSkeleton} role="status" aria-live="polite">
              <span>{inspectorSlow ? t('creation.inspectorLoadingSlow') : t('creation.inspectorLoading')}</span>
              <i /><i /><i /><i />
            </div>
          )}
          {inspectorState === 'error' && (
            <div className={css.inspectorNotice}>
              <span>{inspectorError}</span>
              <button type="button" className={css.commandButton} onClick={() => setInspectorReload(value => value + 1)}>
                <RefreshCw size={15} />{t('retry')}
              </button>
            </div>
          )}
          {inspectorState === 'ready' && inspectorTab === 'context' && (context === ''
            ? <div className={css.muted}>{t('creation.contextEmpty')}</div>
            : <ContextDocument key={path} markdown={context} fallbackTitle={t('creation.context')} />)}
          {inspectorState === 'ready' && inspectorTab === 'review' && (
            activeChapter?.review.issueDetails.length ? (
              <div className={css.issueList}>
                <div className={css.reviewSummary}>{activeChapter.review.score ?? '--'} / 100 · {activeChapter.review.issues} {t('creation.issues')}</div>
                {activeChapter.review.issueDetails.map((raw, index) => {
                  const issue = record(raw)
                  return <article key={String(issue['id'] ?? index)} className={css.issue}>
                    <span>{String(issue['severity'] ?? '')} · {String(issue['category'] ?? '')}</span>
                    <strong>{String(issue['description'] ?? issue['summary'] ?? '')}</strong>
                    {typeof issue['suggestion'] === 'string' && <p>{issue['suggestion']}</p>}
                  </article>
                })}
              </div>
            ) : <div className={css.muted}>{t('creation.reviewEmpty')}</div>
          )}
          {inspectorState === 'ready' && inspectorTab === 'revisions' && (
            <div className={css.revisionPane}>
              <History size={18} />
              <pre>{revisions === null ? t('creation.revisionsEmpty') : JSON.stringify(revisions, null, 2)}</pre>
            </div>
          )}
        </div>
      </aside>
      {(leftOpen || rightOpen) && <button type="button" aria-label={t('creation.closePanel')} className={css.scrim} onClick={() => { setLeftOpen(false); setRightOpen(false) }} />}
    </div>
  )
}
