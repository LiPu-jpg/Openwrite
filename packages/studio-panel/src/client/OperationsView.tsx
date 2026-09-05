import { useCallback, useEffect, useState } from 'react'
import { Download, ExternalLink, FileUp, FlaskConical, Gauge, ListTodo, RefreshCw, Cpu } from 'lucide-react'
import type { ConvViewProps } from '@deepseek-ai/dsh-client-ui-conversation/client'
import type { InjectFace, PropsLocale } from '@deepseek-ai/dsh-client-ui-slots'
import { API_PROXY_BASE, studioContextHeaders } from './api.ts'
import { parseExportPreflight, type ExportFormatDto, type ExportPreflightDto, type ExportPurposeDto } from './dto.ts'
import { ResearchView } from './ResearchView.tsx'
import { BenchmarkView } from './BenchmarkView.tsx'
import { ModelView } from './ModelView.tsx'
import { TasksView, type NavigationRequest } from './TasksView.tsx'
import { ManuscriptImportWorkspace, ProjectArchiveWorkspace } from './TransferWorkspaces.tsx'
import { useWorkbench, workbenchStore } from './WorkbenchStore.ts'
import { createNovelWorkspace, initWorkspaceProject, useBindStudioContext, type StudioPanelInjected } from './workspace-context.ts'
import css from './Workbench.module.css'

type OperationsMode = 'tasks' | 'benchmark' | 'models' | 'research' | 'transfer'

export type OperationsViewProps = ConvViewProps & InjectFace<StudioPanelInjected> & PropsLocale<'studio-panel'>

function ExportPreflightCard({ preflight, t }: { preflight: ExportPreflightDto; t: OperationsViewProps['t'] }) {
  const chapters = new Map(preflight.chapters.map(chapter => [chapter.chapter_id, chapter]))
  const duplicateRows = Object.entries(preflight.structure.duplicates)
    .filter(([, ids]) => ids.length > 0)
    .map(([number, ids]) => `${number}: ${ids.join(', ')}`)
  const structureRows = [
    [t('tools.export.structure.duplicates'), duplicateRows],
    [t('tools.export.structure.missing'), preflight.structure.missing],
    [t('tools.export.structure.empty'), preflight.structure.empty],
    [t('tools.export.structure.unreadable'), preflight.structure.unreadable],
  ] as const
  const reviewRows = [
    [t('tools.export.reviews.missing'), preflight.reviews.missing],
    [t('tools.export.reviews.current'), preflight.reviews.current],
    [t('tools.export.reviews.stale'), preflight.reviews.stale],
    [t('tools.export.reviews.approved'), preflight.reviews.approved],
    [t('tools.export.reviews.notApproved'), preflight.reviews.not_approved],
  ] as const
  const ratio = preflight.writing_units.completion_ratio

  return <article className={css.exportPreflight} data-ready={preflight.can_export}>
    <header className={css.exportPreflightHeader}>
      <strong>{t('tools.export.preflight')}</strong>
      <span data-ready={preflight.can_export}>{preflight.can_export ? t('tools.export.ready') : t('tools.export.blocked')}</span>
      <code>{t('tools.export.revision')}: <b>{preflight.preflight_revision}</b></code>
    </header>
    <div className={css.exportSummaryGrid}>
      <section>
        <h3>{t('tools.export.writingUnits')}</h3>
        <dl>
          <div><dt>{t('tools.export.total')}</dt><dd>{preflight.writing_units.total.toLocaleString()}</dd></div>
          <div><dt>{t('tools.export.bookTarget')}</dt><dd>{preflight.writing_units.book_target.toLocaleString()}</dd></div>
          <div><dt>{t('tools.export.chapterTarget')}</dt><dd>{preflight.writing_units.chapter_target.toLocaleString()}</dd></div>
          <div><dt>{t('tools.export.completion')}</dt><dd>{ratio === null ? '—' : `${(ratio * 100).toFixed(1)}%`}</dd></div>
        </dl>
      </section>
      <section>
        <h3>{t('tools.export.metadata')}</h3>
        <dl>
          <div><dt>{t('tools.export.metadata.title')}</dt><dd>{preflight.metadata.title || '—'}</dd></div>
          <div><dt>{t('tools.export.metadata.author')}</dt><dd>{preflight.metadata.author || '—'}</dd></div>
          <div><dt>{t('tools.export.metadata.language')}</dt><dd>{preflight.metadata.language || '—'}</dd></div>
        </dl>
      </section>
      <section>
        <h3>{t('tools.export.acceptance')}</h3>
        <dl>
          <div><dt>{t('tools.export.status')}</dt><dd>{preflight.manuscript_acceptance.status || '—'}</dd></div>
          <div><dt>{t('tools.export.acceptance.blockingState')}</dt><dd>{preflight.manuscript_acceptance.blocking ? t('tools.export.blocked') : t('tools.export.clear')}</dd></div>
          <div><dt>{t('tools.export.acceptance.blocking')}</dt><dd>{preflight.manuscript_acceptance.blocking_chapters.join(', ') || '—'}</dd></div>
          <div><dt>{t('tools.export.acceptance.needsReview')}</dt><dd>{preflight.manuscript_acceptance.needs_review.join(', ') || '—'}</dd></div>
        </dl>
      </section>
    </div>
    <section className={css.exportDetailSection}>
      <h3>{t('tools.export.order')}</h3>
      {preflight.actual_order.length === 0
        ? <p>{t('tools.export.orderEmpty')}</p>
        : <ol className={css.exportChapterList}>{preflight.actual_order.map((chapterId, index) => {
            const chapter = chapters.get(chapterId)
            return <li key={`${chapterId}-${String(index)}`} data-empty={chapter?.empty === true}>
              <b>{chapterId}</b>
              <strong>{chapter?.title || '—'}</strong>
              <span>{chapter?.path || '—'}</span>
              <small>{chapter?.writing_units.toLocaleString() ?? '0'} {t('tools.export.units')}</small>
            </li>
          })}</ol>}
    </section>
    <div className={css.exportSummaryGrid}>
      <section>
        <h3>{t('tools.export.structure')}</h3>
        {structureRows.every(([, values]) => values.length === 0)
          ? <p>{t('tools.export.clear')}</p>
          : <dl>{structureRows.filter(([, values]) => values.length > 0).map(([label, values]) =>
              <div key={label}><dt>{label}</dt><dd>{values.join(' · ')}</dd></div>)}</dl>}
      </section>
      <section>
        <h3>{t('tools.export.reviews')}</h3>
        <dl>{reviewRows.map(([label, values]) =>
          <div key={label}><dt>{label}</dt><dd>{values.join(', ') || '—'}</dd></div>)}</dl>
      </section>
    </div>
    <div className={css.exportIssues}>
      <section data-kind="blocker">
        <h3>{t('tools.export.blockers')}</h3>
        {preflight.blockers.length === 0 ? <p>{t('tools.export.none')}</p> : <ul>{preflight.blockers.map((issue, index) =>
          <li key={`${issue.code}-${String(index)}`}><code>{issue.code}</code><span>{issue.message}</span></li>)}</ul>}
      </section>
      <section data-kind="warning">
        <h3>{t('tools.export.warnings')}</h3>
        {preflight.warnings.length === 0 ? <p>{t('tools.export.none')}</p> : <ul>{preflight.warnings.map((issue, index) =>
          <li key={`${issue.code}-${String(index)}`}><code>{issue.code}</code><span>{issue.message}</span></li>)}</ul>}
      </section>
    </div>
  </article>
}

/** Background jobs plus the less frequent transfer/maintenance commands. */
export function OperationsView(props: OperationsViewProps) {
  const [mode, setMode] = useState<OperationsMode>('tasks')
  const [resultTarget, setResultTarget] = useState<NavigationRequest | null>(null)
  const workbench = useWorkbench()
  useBindStudioContext({ sessionId: props.sessionId, useWorkspaces: props.useWorkspaces })
  const items = [
    { id: 'tasks' as const, icon: ListTodo, label: props.t('view.tasks') },
    { id: 'benchmark' as const, icon: Gauge, label: props.t('view.benchmark') },
    { id: 'models' as const, icon: Cpu, label: props.t('view.models') },
    { id: 'research' as const, icon: FlaskConical, label: props.t('view.research') },
    { id: 'transfer' as const, icon: FileUp, label: props.t('operations.transfer') },
  ]
  return <div className={css.workspaceRoot}>
    <nav className={css.workspaceNav} aria-label={props.t('view.operations')}>
      {items.map(item => <button key={item.id} type="button" data-active={mode === item.id} onClick={() => setMode(item.id)}>
        <item.icon size={16} /><span>{item.label}</span>
        {item.id === 'tasks' && workbench.activeTasks > 0 && <b>{workbench.activeTasks}</b>}
      </button>)}
    </nav>
    <section className={css.workspaceContent}>
      {mode === 'tasks' && <TasksView key={workbench.epochs.tasks} {...props} onNavigate={target => { setResultTarget(target); setMode(target.view) }} />}
      {mode === 'benchmark' && <BenchmarkView key={workbench.epochs.benchmark} {...props} initialRunId={resultTarget?.view === 'benchmark' ? resultTarget.id : ''} />}
      {mode === 'models' && <ModelView {...props} />}
      {mode === 'research' && <ResearchView key={workbench.epochs.research} {...props} initialReportId={resultTarget?.view === 'research' ? resultTarget.id : ''} />}
      {mode === 'transfer' && <TransferPanel {...props} />}
    </section>
  </div>
}

function TransferPanel(props: OperationsViewProps) {
  const { fetchStudioApi, postStudioApi, workspaces, sessions, t } = props
  const [busy, setBusy] = useState('')
  const [note, setNote] = useState<{ text: string; bad: boolean } | null>(null)
  const workbench = useWorkbench()
  const workspace = useBindStudioContext({ sessionId: props.sessionId, useWorkspaces: props.useWorkspaces })
  const notInitialized = workbench.workspaceError === 'WORKSPACE_NOT_INITIALIZED'
  const [initNovelId, setInitNovelId] = useState('')
  const [initTitle, setInitTitle] = useState('')
  const [showCreate, setShowCreate] = useState(false)
  const [newNovelId, setNewNovelId] = useState('')
  const [newTitle, setNewTitle] = useState('')
  const [exportFormat, setExportFormat] = useState<ExportFormatDto>('md')
  const [exportPurpose, setExportPurpose] = useState<ExportPurposeDto>('delivery')
  const [preflight, setPreflight] = useState<ExportPreflightDto | null>(null)
  const [preflightState, setPreflightState] = useState<'idle' | 'loading' | 'ready' | 'failed'>('idle')
  const [preflightError, setPreflightError] = useState('')
  const [preflightReload, setPreflightReload] = useState(0)

  const say = useCallback((text: string, bad = false) => setNote({ text, bad }), [])

  useEffect(() => {
    if (workspace === undefined || notInitialized) {
      setPreflight(null)
      setPreflightState('idle')
      return
    }
    let current = true
    setPreflight(null)
    setPreflightState('loading')
    setPreflightError('')
    const query = new URLSearchParams({ format: exportFormat, purpose: exportPurpose })
    void fetchStudioApi(`/export/preflight?${query.toString()}`).then(value => {
      if (!current) return
      const result = parseExportPreflight(value)
      if (result.schema_version !== 'openwrite.export-preflight.v1' || result.preflight_revision === '') {
        throw new Error(t('tools.export.unavailable'))
      }
      if (result.format !== exportFormat || result.purpose !== exportPurpose) {
        throw new Error(t('tools.export.unavailable'))
      }
      setPreflight(result)
      setPreflightState('ready')
    }).catch((cause: unknown) => {
      if (!current) return
      setPreflight(null)
      setPreflightState('failed')
      setPreflightError(cause instanceof Error ? cause.message : String(cause))
    })
    return () => { current = false }
  }, [exportFormat, exportPurpose, fetchStudioApi, notInitialized, preflightReload, t, workspace?.workspaceId])

  /** Onboarding for a bound-but-uninitialized Workspace (contract §5: init pins the context root). */
  const initProject = async () => {
    if (workspace === undefined || busy !== '' || initNovelId.trim() === '' || initTitle.trim() === '') return
    setBusy('init')
    try {
      await initWorkspaceProject(postStudioApi, workspace.path, {
        novelId: initNovelId.trim(),
        title: initTitle.trim(),
      })
      say(t('operations.create.done').replace('{title}', initTitle.trim()))
      setInitNovelId('')
      setInitTitle('')
    } catch (cause: unknown) {
      say(`${t('operations.create.failed')}: ${cause instanceof Error ? cause.message : String(cause)}`, true)
    } finally { setBusy('') }
  }

  /** New-work flow: native directory pick → workspace create → init → connect (see workspace-context.ts). */
  const createNovel = async () => {
    if (busy !== '' || newNovelId.trim() === '' || newTitle.trim() === '') return
    setBusy('create')
    try {
      const result = await createNovelWorkspace({ workspaces, sessions }, postStudioApi, {
        novelId: newNovelId.trim(),
        title: newTitle.trim(),
      })
      if (result === 'created') {
        say(t('operations.create.done').replace('{title}', newTitle.trim()))
        setShowCreate(false)
        setNewNovelId('')
        setNewTitle('')
      }
    } catch (cause: unknown) {
      say(`${t('operations.create.failed')}: ${cause instanceof Error ? cause.message : String(cause)}`, true)
    } finally { setBusy('') }
  }

  const runExport = async () => {
    if (preflight === null || preflightState !== 'ready' || !preflight.can_export || preflight.preflight_revision === '') return
    const revision = preflight.preflight_revision
    setBusy(`export-${exportFormat}`)
    try {
      const query = new URLSearchParams({
        format: exportFormat,
        purpose: exportPurpose,
        preflight_revision: revision,
      })
      const response = await fetch(`${API_PROXY_BASE}/export?${query.toString()}`, { headers: studioContextHeaders() })
      if (!response.ok) {
        if (response.status === 409) {
          setPreflight(null)
          setPreflightState('loading')
          setPreflightReload(value => value + 1)
          say(t('tools.export.stale'), true)
          return
        }
        throw new Error(await response.text())
      }
      const blob = await response.blob()
      const disposition = response.headers.get('content-disposition') ?? ''
      const match = /filename\*?=(?:UTF-8'')?"?([^";]+)"?/i.exec(disposition)
      const name = match?.[1] !== undefined ? decodeURIComponent(match[1]) : `book.${exportFormat}`
      const url = URL.createObjectURL(blob)
      const anchor = document.createElement('a')
      anchor.href = url
      anchor.download = name
      anchor.click()
      URL.revokeObjectURL(url)
      say(t('tools.export.done').replace('{name}', name))
    } catch (cause: unknown) {
      say(`${t('tools.export.failed')}: ${cause instanceof Error ? cause.message : String(cause)}`, true)
    } finally { setBusy('') }
  }

  const selectPurpose = (purpose: ExportPurposeDto) => {
    if (purpose === exportPurpose) return
    setPreflight(null)
    setExportPurpose(purpose)
  }

  const selectFormat = (format: ExportFormatDto) => {
    if (format === exportFormat) return
    setPreflight(null)
    setExportFormat(format)
  }

  const runSync = async () => {
    setBusy('sync')
    try {
      await postStudioApi('/sync', {})
      workbenchStore.invalidate('workspace')
      say(t('tools.sync.done'))
    } catch (cause: unknown) {
      say(`${t('tools.sync.failed')}: ${cause instanceof Error ? cause.message : String(cause)}`, true)
    } finally { setBusy('') }
  }

  return <div className={css.transferPanel}>
    <header><h2>{t('operations.transfer')}</h2><p>{t('operations.transferHint')}</p></header>
    {note !== null && <div className={css.operationNote} data-bad={note.bad}>{note.text}</div>}
    <section className={css.operationSection}>
      <div><strong>{t('operations.project')}</strong></div>
      <div className={css.projectSwitchRow}>
        <span className={css.projectCurrent}>{workspace?.title ?? t('workspace.unbound')}</span>
        {workspace !== undefined && <span className={css.projectPath}>{workspace.path}</span>}
        <button type="button" className={css.actionButton} disabled={busy !== ''}
          onClick={() => { setShowCreate(previous => !previous) }}>
          {showCreate ? t('operations.cancel') : t('operations.create.new')}
        </button>
      </div>
      {notInitialized && workspace !== undefined && (
        <div className={css.projectSwitchRow}>
          <span>{t('operations.init.hint')}</span>
          <label>{t('operations.create.id')}<input value={initNovelId} placeholder="my-novel"
            onChange={e => setInitNovelId(e.target.value)} /></label>
          <label>{t('operations.create.title')}<input value={initTitle}
            placeholder={t('operations.create.titleHint')}
            maxLength={120} onChange={e => setInitTitle(e.target.value)} /></label>
          <button type="button" className={css.commandButton} disabled={busy !== '' || initNovelId.trim() === '' || initTitle.trim() === ''}
            onClick={() => void initProject()}>{t('operations.init.submit')}</button>
        </div>
      )}
      {showCreate && (
        <div className={css.projectSwitchRow}>
          <label>{t('operations.create.id')}<input value={newNovelId} placeholder="my-novel"
            onChange={e => setNewNovelId(e.target.value)} /></label>
          <label>{t('operations.create.title')}<input value={newTitle}
            placeholder={t('operations.create.titleHint')}
            maxLength={120} onChange={e => setNewTitle(e.target.value)} /></label>
          <button type="button" className={css.commandButton} disabled={busy !== '' || newNovelId.trim() === '' || newTitle.trim() === ''}
            onClick={() => void createNovel()}>{t('operations.create.submit')}</button>
          <span>{t('operations.create.pickHint')}</span>
        </div>
      )}
    </section>
    <section className={css.operationSection}>
      <div><Download size={18} /><strong>{t('tools.export')}</strong></div>
      <div className={css.exportWorkspace}>
        <div className={css.exportControls}>
          <span className={css.exportPurpose} role="group" aria-label={t('tools.export.purpose')}>
            {(['delivery', 'backup'] as const).map(purpose => <button key={purpose} type="button" className={css.actionButton}
              data-active={exportPurpose === purpose} disabled={busy !== ''}
              onClick={() => selectPurpose(purpose)}>{t(`tools.export.purpose.${purpose}`)}</button>)}
          </span>
          <label>{t('tools.export.format')}
            <select aria-label={t('tools.export.format')} value={exportFormat} disabled={busy !== ''}
              onChange={event => selectFormat(event.target.value as ExportFormatDto)}>
              {(['md', 'txt', 'epub'] as const).map(format => <option key={format} value={format}>{format.toUpperCase()}</option>)}
            </select>
          </label>
          <button type="button" className={css.actionButton} disabled={busy !== '' || preflightState === 'loading'}
            onClick={() => setPreflightReload(value => value + 1)}><RefreshCw size={13} />{t('tools.export.refresh')}</button>
          <button type="button" className={css.commandButton}
            disabled={busy !== '' || preflightState !== 'ready' || preflight?.can_export !== true || preflight.preflight_revision === ''}
            onClick={() => void runExport()}>{t('tools.export.download')}</button>
        </div>
        {preflightState === 'loading' && <p className={css.exportState}>{t('tools.export.loading')}</p>}
        {preflightState === 'failed' && <p className={css.exportState} data-bad="true">{t('tools.export.unavailable')}: {preflightError}</p>}
        {preflight !== null && <ExportPreflightCard preflight={preflight} t={t} />}
      </div>
    </section>
    <section className={css.operationSection}>
      <div><RefreshCw size={18} /><strong>{t('tools.sync')}</strong></div>
      <button type="button" className={css.commandButton} disabled={busy !== ''} onClick={() => void runSync()}>{t('tools.sync')}</button>
    </section>
    <section className={css.operationSection}>
      <div><FileUp size={18} /><strong>{t('tools.import')}</strong></div>
      <ManuscriptImportWorkspace fetchStudioApi={fetchStudioApi} postStudioApi={postStudioApi} t={t}
        busy={busy} setBusy={setBusy} say={say} workspaceReady={workspace !== undefined && !notInitialized}
        tasksEpoch={workbench.epochs.tasks} workspaceEpoch={workbench.epochs.workspace} />
    </section>
    <section className={css.operationSection}>
      <div><strong>{t('tools.archive.title')}</strong></div>
      <ProjectArchiveWorkspace fetchStudioApi={fetchStudioApi} postStudioApi={postStudioApi} workspaces={workspaces} t={t}
        busy={busy} setBusy={setBusy} say={say} workspaceReady={workspace !== undefined && !notInitialized}
        tasksEpoch={workbench.epochs.tasks} workspaceEpoch={workbench.epochs.workspace} />
    </section>
    <a className={css.externalLink} href="http://127.0.0.1:4567" target="_blank" rel="noreferrer">
      <ExternalLink size={15} />{t('openExternal')}
    </a>
  </div>
}
