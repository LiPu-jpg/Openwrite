import { useEffect, useMemo, useRef, useState, type ChangeEvent, type Dispatch, type SetStateAction } from 'react'
import { Archive, ChevronDown, ChevronUp, Download, FileInput, FolderOpen, Plus, RefreshCw, Trash2 } from 'lucide-react'
import { API_PROXY_BASE, studioContextHeaders } from './api.ts'
import {
  IMPORT_STAGE_NAMES,
  asRecord,
  parseManuscriptImportDetail,
  parseManuscriptImportList,
  parseProjectArchiveDetail,
  parseProjectArchiveList,
  parseProjectArchivePreflight,
  parseProjectRestorePreview,
  unwrapData,
  type ManuscriptImportChapterDto,
  type ManuscriptImportOperationDto,
  type ProjectArchivePlanDto,
  type ProjectArchiveSummaryDto,
  type ProjectRestorePreviewDto,
} from './dto.ts'
import type { OperationsViewProps } from './OperationsView.tsx'
import type { StudioPanelInjected } from './workspace-context.ts'
import { workbenchStore } from './WorkbenchStore.ts'
import css from './Workbench.module.css'

type TransferT = OperationsViewProps['t']
type Note = (message: string, bad?: boolean) => void

interface WorkspaceProps extends Pick<StudioPanelInjected, 'fetchStudioApi' | 'postStudioApi'> {
  t: TransferT
  busy: string
  setBusy: Dispatch<SetStateAction<string>>
  say: Note
  workspaceReady: boolean
  tasksEpoch: number
  workspaceEpoch: number
}

interface ArchiveWorkspaceProps extends WorkspaceProps, Pick<StudioPanelInjected, 'workspaces'> {}

function errorText(cause: unknown): string {
  return cause instanceof Error ? cause.message : String(cause)
}

function taskId(value: unknown): string {
  const root = unwrapData(value)
  const task = asRecord(root['task'])
  const candidate = root['task_id'] ?? task['task_id']
  return typeof candidate === 'string' ? candidate : ''
}

function shortDigest(value: string): string {
  return value.length > 22 ? `${value.slice(0, 19)}…` : value
}

function detailFromMutation(value: unknown): ReturnType<typeof parseManuscriptImportDetail> | null {
  const root = unwrapData(value)
  return root['operation'] === undefined ? null : parseManuscriptImportDetail(value)
}

const ACTIVE_IMPORT_STATUSES = new Set(['running', 'published'])
const RESUMABLE_IMPORT_STATUSES = new Set(['ready_to_publish', 'published', 'awaiting_reconciliation', 'failed'])

export function ManuscriptImportWorkspace(props: WorkspaceProps) {
  const { fetchStudioApi, postStudioApi, t, busy, setBusy, say, workspaceReady, tasksEpoch } = props
  const [operations, setOperations] = useState<ManuscriptImportOperationDto[]>([])
  const [selectedId, setSelectedId] = useState('')
  const [detail, setDetail] = useState<ReturnType<typeof parseManuscriptImportDetail> | null>(null)
  const [chapters, setChapters] = useState<ManuscriptImportChapterDto[]>([])
  const [filename, setFilename] = useState('')
  const [content, setContent] = useState('')
  const [arcId, setArcId] = useState('arc_001')
  const [startNumber, setStartNumber] = useState('')
  const [loading, setLoading] = useState(false)
  const [reload, setReload] = useState(0)
  const fileRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    if (!workspaceReady) return
    let current = true
    setLoading(true)
    void fetchStudioApi('/manuscript-imports').then(value => {
      if (!current) return
      const next = parseManuscriptImportList(value).operations
      setOperations(next)
      setSelectedId(previous => previous || next[0]?.import_id || '')
    }).catch(cause => {
      if (current) say(`${t('tools.import.failed')}: ${errorText(cause)}`, true)
    }).finally(() => { if (current) setLoading(false) })
    return () => { current = false }
  }, [fetchStudioApi, reload, say, t, tasksEpoch, workspaceReady])

  useEffect(() => {
    if (!workspaceReady || selectedId === '') {
      setDetail(null)
      setChapters([])
      return
    }
    let current = true
    void fetchStudioApi(`/manuscript-imports/${encodeURIComponent(selectedId)}`).then(value => {
      if (!current) return
      const parsed = parseManuscriptImportDetail(value)
      setDetail(parsed)
      setChapters(parsed.preview?.chapters ?? [])
    }).catch(cause => {
      if (current) say(`${t('tools.import.failed')}: ${errorText(cause)}`, true)
    })
    return () => { current = false }
  }, [fetchStudioApi, reload, say, selectedId, t, tasksEpoch, workspaceReady])

  useEffect(() => {
    if (detail === null || !ACTIVE_IMPORT_STATUSES.has(detail.operation.status)) return
    const timer = window.setInterval(() => setReload(value => value + 1), 2_500)
    return () => window.clearInterval(timer)
  }, [detail?.operation.status])

  const updateFromMutation = (value: unknown) => {
    const next = detailFromMutation(value)
    if (next !== null) {
      setDetail(next)
      setChapters(next.preview?.chapters ?? [])
      setSelectedId(next.operation.import_id)
    }
    setReload(current => current + 1)
  }

  const chooseFile = async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0]
    if (file === undefined) return
    const text = await file.text()
    if (text.trim() === '') {
      say(t('tools.import.empty'), true)
      return
    }
    setFilename(file.name)
    setContent(text)
  }

  const prepare = async () => {
    if (content.trim() === '' || busy !== '') return
    setBusy('import-prepare')
    try {
      const result = await postStudioApi('/manuscript-imports/prepare', {
        filename: filename || 'import.md', content, arc_id: arcId,
        ...(startNumber === '' ? {} : { start_number: Number(startNumber) }),
      })
      updateFromMutation(result)
      setFilename('')
      setContent('')
      if (fileRef.current !== null) fileRef.current.value = ''
      say(t('tools.import.workspace.prepared'))
    } catch (cause: unknown) {
      say(`${t('tools.import.failed')}: ${errorText(cause)}`, true)
    } finally { setBusy('') }
  }

  const saveStructure = async () => {
    const preview = detail?.preview
    if (preview === null || preview === undefined || chapters.length === 0 || busy !== '') return
    setBusy('import-structure')
    try {
      const result = await postStudioApi('/manuscript-imports/structure', {
        import_id: preview.import_id, expected_preview_revision: preview.revision,
        chapters: chapters.map(chapter => ({ chapter_id: chapter.chapter_id, title: chapter.title, content: chapter.content })),
      })
      updateFromMutation(result)
      say(t('tools.import.workspace.structureSaved'))
    } catch (cause: unknown) {
      say(`${t('tools.import.failed')}: ${errorText(cause)}`, true)
      setReload(value => value + 1)
    } finally { setBusy('') }
  }

  const confirmStructure = async () => {
    const preview = detail?.preview
    if (preview === null || preview === undefined || busy !== '') return
    if (!window.confirm(t('tools.import.workspace.confirmPrompt'))) return
    setBusy('import-confirm')
    try {
      const result = await postStudioApi('/manuscript-imports/confirm', {
        import_id: preview.import_id, expected_preview_revision: preview.revision, confirm: true,
      })
      updateFromMutation(result)
      say(t('tools.import.workspace.confirmed'))
    } catch (cause: unknown) {
      say(`${t('tools.import.failed')}: ${errorText(cause)}`, true)
      setReload(value => value + 1)
    } finally { setBusy('') }
  }

  const run = async () => {
    if (detail === null || busy !== '') return
    setBusy('import-run')
    try {
      const result = await postStudioApi('/manuscript-imports/run', { import_id: detail.operation.import_id })
      const id = taskId(result)
      say(t('tools.import.workspace.taskStarted').replace('{id}', id || '—'))
      workbenchStore.invalidate('tasks')
      setReload(value => value + 1)
    } catch (cause: unknown) {
      say(`${t('tools.import.failed')}: ${errorText(cause)}`, true)
    } finally { setBusy('') }
  }

  const discard = async () => {
    if (detail === null || busy !== '' || !window.confirm(t('tools.import.workspace.discardPrompt'))) return
    setBusy('import-discard')
    try {
      await postStudioApi('/manuscript-imports/discard', { import_id: detail.operation.import_id, confirm: true })
      say(t('tools.import.workspace.discarded'))
      setDetail(null)
      setSelectedId('')
      setReload(value => value + 1)
    } catch (cause: unknown) {
      say(`${t('tools.import.failed')}: ${errorText(cause)}`, true)
    } finally { setBusy('') }
  }

  const changeChapter = (index: number, field: 'chapter_id' | 'title' | 'content', value: string) => {
    setChapters(previous => previous.map((chapter, at) => at === index ? { ...chapter, [field]: value } : chapter))
  }
  const moveChapter = (index: number, offset: -1 | 1) => {
    setChapters(previous => {
      const target = index + offset
      if (target < 0 || target >= previous.length) return previous
      const next = [...previous]
      const item = next[index]
      if (item === undefined) return previous
      next.splice(index, 1)
      next.splice(target, 0, item)
      return next.map((chapter, order) => ({ ...chapter, order }))
    })
  }
  const addChapter = () => {
    const max = chapters.reduce((value, chapter) => Math.max(value, Number(chapter.chapter_id.slice(3)) || 0), 0)
    setChapters(previous => [...previous, {
      order: previous.length, chapter_id: `ch_${String(max + 1).padStart(3, '0')}`,
      title: t('tools.import.workspace.newChapter'), content: '', writing_units: 0, sha256: '',
    }])
  }

  const operation = detail?.operation ?? null
  const editable = operation?.status === 'awaiting_confirmation' && operation.publication.committed === false
  const canDiscard = operation !== null && operation.publication.committed === false && ['awaiting_confirmation', 'ready_to_publish', 'failed'].includes(operation.status)
  const canRun = operation !== null && RESUMABLE_IMPORT_STATUSES.has(operation.status) && (operation.failure?.recoverable ?? true)

  return <div className={css.transferWorkspace}>
    <header className={css.transferWorkspaceHeader}>
      <div><FileInput size={17} /><strong>{t('tools.import.workspace.title')}</strong></div>
      <p>{t('tools.import.workspace.ownHint')}</p>
      <button type="button" className={css.actionButton} disabled={loading || busy !== ''} onClick={() => setReload(value => value + 1)}>
        <RefreshCw size={13} />{t('refresh')}
      </button>
    </header>
    <div className={css.transferColumns}>
      <aside className={css.transferList}>
        <h3>{t('tools.import.workspace.operations')}</h3>
        {operations.length === 0 && <p>{t('tools.import.workspace.empty')}</p>}
        {operations.map(item => <button type="button" key={item.import_id} data-active={item.import_id === selectedId}
          onClick={() => setSelectedId(item.import_id)}>
          <strong>{item.source.filename || item.import_id}</strong>
          <span>{item.status} · {item.progress.completed_stages}/{item.progress.total_stages}</span>
          <small>{item.chapter_count} {t('tools.import.workspace.chapters')} · {item.writing_units} {t('tools.export.units')}</small>
        </button>)}
        <div className={css.importPrepare}>
          <h3>{t('tools.import.workspace.new')}</h3>
          <input ref={fileRef} aria-label={t('tools.import.workspace.file')} type="file" accept=".md,.markdown,.txt" onChange={event => void chooseFile(event)} />
          <label>{t('tools.import.workspace.arc')}<input value={arcId} onChange={event => setArcId(event.target.value)} /></label>
          <label>{t('tools.import.start')}<input value={startNumber} inputMode="numeric" placeholder={t('tools.import.startAuto')}
            onChange={event => setStartNumber(event.target.value.replace(/[^0-9]/g, ''))} /></label>
          <button type="button" className={css.commandButton} disabled={busy !== '' || content === ''} onClick={() => void prepare()}>
            {t('tools.import.workspace.prepare')}
          </button>
        </div>
      </aside>
      <main className={css.transferDetail}>
        {operation === null ? <p>{t('tools.import.workspace.select')}</p> : <>
          <div className={css.transferDetailHeader}>
            <div><strong>{operation.source.filename || operation.import_id}</strong><code>{operation.import_id}</code></div>
            <span data-status={operation.status}>{operation.status}</span>
            <small>{operation.arc_id} · {operation.chapter_count} {t('tools.import.workspace.chapters')} · {operation.writing_units} {t('tools.export.units')}</small>
          </div>
          <ol className={css.stageRail}>{IMPORT_STAGE_NAMES.map(name => {
            const stage = operation.stages[name]
            const digest = stage.output_sha256 || stage.input_sha256
            const evidence = stage.error_code || shortDigest(digest) || (stage.attempts > 0 ? `#${String(stage.attempts)}` : '')
            const title = [stage.error_code, stage.input_sha256, stage.output_sha256].filter(Boolean).join('\n')
            return <li key={name} data-status={stage.status}><span>{t(`tools.import.stage.${name}`)}</span><b>{stage.status}</b><small title={title}>{evidence}</small></li>
          })}</ol>
          {operation.failure !== null && <div className={css.transferFailure}>
            <strong>{operation.failure.code}</strong><span>{operation.failure.stage}</span>
            <small>{operation.failure.recoverable ? t('tools.import.workspace.recoverable') : t('tools.import.workspace.notRecoverable')}</small>
          </div>}
          {detail?.preview !== null && detail?.preview !== undefined && <section className={css.importStructure}>
            <header><h3>{t('tools.import.workspace.structure')}</h3><code>{detail.preview.revision}</code></header>
            {chapters.map((chapter, index) => <article key={`${chapter.chapter_id}-${String(index)}`}>
              <div>
                <input aria-label={`${t('tools.import.workspace.chapterId')} ${String(index + 1)}`} value={chapter.chapter_id}
                  disabled={!editable} onChange={event => changeChapter(index, 'chapter_id', event.target.value)} />
                <input aria-label={`${t('tools.import.workspace.chapterTitle')} ${String(index + 1)}`} value={chapter.title}
                  disabled={!editable} onChange={event => changeChapter(index, 'title', event.target.value)} />
                {editable && <span>
                  <button type="button" aria-label={t('tools.import.workspace.moveUp')} disabled={index === 0} onClick={() => moveChapter(index, -1)}><ChevronUp size={13} /></button>
                  <button type="button" aria-label={t('tools.import.workspace.moveDown')} disabled={index === chapters.length - 1} onClick={() => moveChapter(index, 1)}><ChevronDown size={13} /></button>
                  <button type="button" aria-label={t('tools.import.workspace.remove')} disabled={chapters.length === 1}
                    onClick={() => setChapters(previous => previous.filter((_, at) => at !== index))}><Trash2 size={13} /></button>
                </span>}
              </div>
              <textarea aria-label={`${t('tools.import.workspace.chapterContent')} ${String(index + 1)}`} value={chapter.content}
                disabled={!editable} onChange={event => changeChapter(index, 'content', event.target.value)} />
              <small>{chapter.writing_units} {t('tools.export.units')}</small>
            </article>)}
            {editable && <div className={css.transferActions}>
              <button type="button" className={css.actionButton} onClick={addChapter}><Plus size={13} />{t('tools.import.workspace.addChapter')}</button>
              <button type="button" className={css.actionButton} disabled={busy !== '' || chapters.some(chapter => chapter.content.trim() === '')}
                onClick={() => void saveStructure()}>{t('tools.import.workspace.saveStructure')}</button>
              <button type="button" className={css.commandButton} disabled={busy !== '' || chapters.some(chapter => chapter.content.trim() === '')}
                onClick={() => void confirmStructure()}>{t('tools.import.workspace.confirmStructure')}</button>
            </div>}
          </section>}
          <div className={css.transferActions}>
            {canRun && <button type="button" className={css.commandButton} disabled={busy !== ''} onClick={() => void run()}>
              {operation.status === 'ready_to_publish' ? t('tools.import.workspace.run') : t('tools.import.workspace.resume')}
            </button>}
            {canDiscard && <button type="button" className={css.dangerButton} disabled={busy !== ''} onClick={() => void discard()}>{t('tools.import.workspace.discard')}</button>}
          </div>
        </>}
      </main>
    </div>
  </div>
}

function noticeText(item: ProjectRestorePreviewDto['path_rewrites'][number]): string {
  const source = item.source || item.source_path
  const target = item.target || item.target_path
  if (source || target) return [source, target].filter(Boolean).join(' → ')
  if (item.before || item.after) return [item.path, item.location, `${item.before} → ${item.after}`].filter(Boolean).join(' · ')
  const collision = item.source_paths.length > 0 ? `${item.source_paths.join(', ')} → ${item.target_path}` : ''
  return [item.path, item.location, item.kind, item.value, item.message, item.reason, item.state, collision].filter(Boolean).join(' · ')
}

function ArchivePlan({ plan, t }: { plan: ProjectArchivePlanDto; t: TransferT }) {
  const categories = Object.entries(plan.includes.category_counts)
  return <div className={css.archivePlan}>
    <div className={css.archiveSummary}>
      <span>{t('tools.archive.files')}: <b>{plan.includes.file_count}</b></span>
      <span>{t('tools.archive.size')}: <b>{plan.includes.total_size.toLocaleString()}</b></span>
      <code>{plan.preflight_revision}</code>
    </div>
    <section><h4>{t('tools.archive.categories')}</h4><p>{categories.map(([name, count]) => `${name}: ${String(count)}`).join(' · ') || '—'}</p></section>
    <section><h4>{t('tools.archive.includes')}</h4><ul>{plan.includes.files.map(file => <li key={file.path}><span>{file.path}</span><small>{file.category} · {file.size.toLocaleString()} · {file.sha256}</small></li>)}</ul></section>
    <section><h4>{t('tools.archive.excludes')}</h4><ul>{plan.excludes.entries.length === 0 ? <li>—</li> : plan.excludes.entries.map((item, index) => <li key={`${item.path}-${String(index)}`}>{noticeText(item)}</li>)}</ul></section>
    <section><h4>{t('tools.archive.missing')}</h4><p>{[...plan.missing.required, ...plan.missing.optional.map(noticeText)].join(' · ') || '—'}</p></section>
    <section><h4>{t('tools.archive.references')}</h4><p>{t('tools.archive.referencePlan').replace('{known}', String(plan.reference_inventory.known.length))
      .replace('{preserved}', String(plan.reference_inventory.preserved.length)).replace('{warnings}', String(plan.reference_inventory.warnings.length))}</p>
      <small>{plan.policies.reference_default} · {plan.policies.reference_supported.join(', ')} · {plan.policies.tasks}</small>
      <ul>{[...plan.reference_inventory.known, ...plan.reference_inventory.preserved, ...plan.reference_inventory.warnings]
        .map((item, index) => <li key={`${item.path}-${item.location}-${String(index)}`}>{noticeText(item)}</li>)}</ul>
    </section>
  </div>
}

export function ProjectArchiveWorkspace(props: ArchiveWorkspaceProps) {
  const { fetchStudioApi, postStudioApi, workspaces, t, busy, setBusy, say, workspaceReady, workspaceEpoch } = props
  const [preflight, setPreflight] = useState<ProjectArchivePlanDto | null>(null)
  const [archives, setArchives] = useState<ProjectArchiveSummaryDto[]>([])
  const [selectedId, setSelectedId] = useState('')
  const [selectedPlan, setSelectedPlan] = useState<ProjectArchivePlanDto | null>(null)
  const [targetRoot, setTargetRoot] = useState('')
  const [targetNovelId, setTargetNovelId] = useState('')
  const [referencePolicy, setReferencePolicy] = useState<'preserve_relative' | 'rewrite_novel_id'>('preserve_relative')
  const [restorePreview, setRestorePreview] = useState<ProjectRestorePreviewDto | null>(null)
  const [reload, setReload] = useState(0)

  useEffect(() => {
    if (!workspaceReady) return
    let current = true
    void Promise.all([
      fetchStudioApi('/project-archives/preflight'),
      fetchStudioApi('/project-archives'),
    ]).then(([preflightValue, listValue]) => {
      if (!current) return
      setPreflight(parseProjectArchivePreflight(preflightValue))
      setArchives(parseProjectArchiveList(listValue).archives)
    }).catch(cause => { if (current) say(`${t('tools.archive.failed')}: ${errorText(cause)}`, true) })
    return () => { current = false }
  }, [fetchStudioApi, reload, say, t, workspaceEpoch, workspaceReady])

  useEffect(() => {
    if (!workspaceReady || selectedId === '') {
      setSelectedPlan(null)
      return
    }
    let current = true
    void fetchStudioApi(`/project-archives/${selectedId}`).then(value => {
      if (current) setSelectedPlan(parseProjectArchiveDetail(value).plan)
    }).catch(cause => { if (current) say(`${t('tools.archive.failed')}: ${errorText(cause)}`, true) })
    return () => { current = false }
  }, [fetchStudioApi, say, selectedId, t, workspaceReady])

  const createArchive = async () => {
    if (preflight === null || busy !== '') return
    setBusy('archive-create')
    try {
      const result = await postStudioApi('/project-archives/create', { expected_preflight_revision: preflight.preflight_revision })
      const archive = asRecord(unwrapData(result)['archive'])
      const id = typeof archive['archive_id'] === 'string' ? archive['archive_id'] : ''
      say(t('tools.archive.created').replace('{id}', id || '—'))
      setSelectedPlan(null)
      setSelectedId(id)
      setReload(value => value + 1)
    } catch (cause: unknown) {
      say(`${t('tools.archive.failed')}: ${errorText(cause)}`, true)
      setReload(value => value + 1)
    } finally { setBusy('') }
  }

  const downloadArchive = async (archiveId: string) => {
    if (busy !== '') return
    setBusy('archive-download')
    try {
      const response = await fetch(`${API_PROXY_BASE}/project-archives/${archiveId}/download`, { headers: studioContextHeaders() })
      if (!response.ok) throw new Error(await response.text())
      const blob = await response.blob()
      const disposition = response.headers.get('content-disposition') ?? ''
      const match = /filename\*?=(?:UTF-8'')?"?([^";]+)"?/i.exec(disposition)
      const name = match?.[1] === undefined ? `${archiveId}.owarchive.zip` : decodeURIComponent(match[1])
      const url = URL.createObjectURL(blob)
      const anchor = document.createElement('a')
      anchor.href = url
      anchor.download = name
      anchor.click()
      URL.revokeObjectURL(url)
      say(t('tools.archive.downloaded').replace('{name}', name))
    } catch (cause: unknown) {
      say(`${t('tools.archive.failed')}: ${errorText(cause)}`, true)
    } finally { setBusy('') }
  }

  const pickTarget = async () => {
    const picked = await workspaces.pickDirectory()
    if (picked !== null) {
      setTargetRoot(picked)
      setRestorePreview(null)
    }
  }

  const previewRestore = async () => {
    if (selectedId === '' || targetRoot === '' || busy !== '') return
    setBusy('archive-restore-preview')
    try {
      const value = await postStudioApi('/project-archives/restore/preview', {
        archive_id: selectedId, target_root: targetRoot,
        ...(targetNovelId.trim() === '' ? {} : { target_novel_id: targetNovelId.trim() }),
        reference_policy: referencePolicy,
      })
      setRestorePreview(parseProjectRestorePreview(value))
    } catch (cause: unknown) {
      say(`${t('tools.archive.failed')}: ${errorText(cause)}`, true)
    } finally { setBusy('') }
  }

  const restore = async () => {
    if (restorePreview === null || !restorePreview.can_restore || busy !== '') return
    if (!window.confirm(t('tools.archive.restoreConfirm'))) return
    setBusy('archive-restore')
    try {
      const value = await postStudioApi('/project-archives/restore', {
        archive_id: restorePreview.archive_id, target_root: restorePreview.target_root,
        target_novel_id: restorePreview.target_novel_id, reference_policy: restorePreview.reference_policy,
        archive_sha256: restorePreview.archive_sha256, confirm: true,
      })
      say(t('tools.archive.restoreStarted').replace('{id}', taskId(value) || '—'))
      workbenchStore.invalidate('tasks')
    } catch (cause: unknown) {
      say(`${t('tools.archive.failed')}: ${errorText(cause)}`, true)
      setRestorePreview(null)
    } finally { setBusy('') }
  }

  const activePlan = selectedPlan ?? preflight
  const restoreLists = useMemo(() => restorePreview === null ? [] : [
    [t('tools.archive.pathRewrites'), restorePreview.path_rewrites],
    [t('tools.archive.rewrittenFiles'), restorePreview.rewritten_files],
    [t('tools.archive.rewrittenReferences'), restorePreview.rewritten_references],
    [t('tools.archive.preservedReferences'), restorePreview.preserved_references],
    [t('tools.archive.referenceWarnings'), restorePreview.reference_warnings],
    [t('tools.archive.referenceConflicts'), restorePreview.reference_conflicts],
  ] as const, [restorePreview, t])

  return <div className={css.transferWorkspace}>
    <header className={css.transferWorkspaceHeader}>
      <div><Archive size={17} /><strong>{t('tools.archive.title')}</strong></div>
      <p>{t('tools.archive.hint')}</p>
      <button type="button" className={css.actionButton} disabled={busy !== ''} onClick={() => setReload(value => value + 1)}><RefreshCw size={13} />{t('refresh')}</button>
    </header>
    {preflight !== null && <div className={css.archiveCreate}>
      <span>{t('tools.archive.preflight')}: <code>{preflight.preflight_revision}</code></span>
      <button type="button" className={css.commandButton} disabled={busy !== '' || preflight.missing.required.length > 0}
        onClick={() => void createArchive()}>{t('tools.archive.create')}</button>
    </div>}
    <div className={css.transferColumns}>
      <aside className={css.transferList}>
        <h3>{t('tools.archive.list')}</h3>
        {archives.length === 0 && <p>{t('tools.archive.empty')}</p>}
        {archives.map(archive => <div className={css.archiveListItem} key={archive.archive_id} data-active={archive.archive_id === selectedId}>
          <button type="button" onClick={() => { setSelectedPlan(null); setSelectedId(archive.archive_id); setRestorePreview(null) }}>
            <strong>{archive.archive_id}</strong><span>{archive.created_at || '—'}</span>
            <small>{archive.file_count} · {archive.total_size.toLocaleString()} · {archive.archive_sha256}</small>
          </button>
          <button type="button" aria-label={`${t('tools.archive.download')} ${archive.archive_id}`} disabled={busy !== ''}
            onClick={() => void downloadArchive(archive.archive_id)}><Download size={14} /></button>
        </div>)}
      </aside>
      <main className={css.transferDetail}>
        {activePlan !== null && <ArchivePlan plan={activePlan} t={t} />}
        {selectedId !== '' && <section className={css.restoreWorkspace}>
          <h3>{t('tools.archive.restore')}</h3>
          <label>{t('tools.archive.targetRoot')}<span><input value={targetRoot} onChange={event => { setTargetRoot(event.target.value); setRestorePreview(null) }} />
            <button type="button" aria-label={t('tools.archive.pickTarget')} onClick={() => void pickTarget()}><FolderOpen size={14} /></button></span></label>
          <label>{t('tools.archive.targetNovelId')}<input value={targetNovelId} onChange={event => { setTargetNovelId(event.target.value); setRestorePreview(null) }} /></label>
          <label>{t('tools.archive.referencePolicy')}<select value={referencePolicy} onChange={event => { setReferencePolicy(event.target.value as typeof referencePolicy); setRestorePreview(null) }}>
            <option value="preserve_relative">{t('tools.archive.preserveRelative')}</option>
            <option value="rewrite_novel_id">{t('tools.archive.rewriteNovelId')}</option>
          </select></label>
          <button type="button" className={css.actionButton} disabled={busy !== '' || targetRoot === ''} onClick={() => void previewRestore()}>{t('tools.archive.previewRestore')}</button>
          {restorePreview !== null && <div className={css.restorePreview} data-ready={restorePreview.can_restore}>
            <div><strong>{restorePreview.can_restore ? t('tools.archive.restoreReady') : t('tools.archive.restoreBlocked')}</strong><code>{restorePreview.archive_sha256}</code></div>
            <p>{restorePreview.source_novel_id} → {restorePreview.target_novel_id} · {restorePreview.file_count} · {restorePreview.total_size.toLocaleString()}</p>
            {restorePreview.conflicts.length > 0 && <p>{t('tools.archive.conflicts')}: {restorePreview.conflicts.join(', ')}</p>}
            {restoreLists.map(([label, items]) => <section key={label}><h4>{label}</h4><ul>{items.length === 0 ? <li>—</li> : items.map((item, index) => <li key={`${label}-${String(index)}`}>{noticeText(item)}</li>)}</ul></section>)}
            <p>{t('tools.archive.tasksArchived').replace('{count}', String(restorePreview.task_file_count))}
              {' · '}{restorePreview.auto_resume_tasks ? t('tools.archive.autoResume') : t('tools.archive.noAutoResume')}</p>
            {restorePreview.task_archive_path !== '' && <code>{restorePreview.task_archive_path}</code>}
            <button type="button" className={css.commandButton} disabled={!restorePreview.can_restore || busy !== ''} onClick={() => void restore()}>{t('tools.archive.confirmRestore')}</button>
          </div>}
        </section>}
      </main>
    </div>
  </div>
}
