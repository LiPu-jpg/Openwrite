import { useRef, useState, type ChangeEvent } from 'react'
import { Download, ExternalLink, FileUp, FlaskConical, ListTodo, RefreshCw } from 'lucide-react'
import type { ConvViewProps } from '@deepseek-ai/dsh-client-ui-conversation/client'
import type { InjectFace, PropsLocale } from '@deepseek-ai/dsh-client-ui-slots'
import { API_PROXY_BASE, type StudioApiInjected } from './api.ts'
import { ResearchView } from './ResearchView.tsx'
import { TasksView } from './TasksView.tsx'
import { useWorkbench, workbenchStore } from './WorkbenchStore.ts'
import css from './Workbench.module.css'

type OperationsMode = 'tasks' | 'research' | 'transfer'
type ExportFormat = 'md' | 'txt' | 'epub'

interface ImportPlan {
  filename: string
  arc_id: string
  start_number: number
  chapter_count: number
  writing_units: number
  conflicts: string[]
  can_import: boolean
}

export type OperationsViewProps = ConvViewProps & InjectFace<StudioApiInjected> & PropsLocale<'studio-panel'>

/** Background jobs plus the less frequent transfer/maintenance commands. */
export function OperationsView(props: OperationsViewProps) {
  const [mode, setMode] = useState<OperationsMode>('tasks')
  const workbench = useWorkbench()
  const items = [
    { id: 'tasks' as const, icon: ListTodo, label: props.t('view.tasks') },
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
      {mode === 'tasks' && <TasksView key={workbench.epochs.tasks} {...props} />}
      {mode === 'research' && <ResearchView key={workbench.epochs.research} {...props} />}
      {mode === 'transfer' && <TransferPanel {...props} />}
    </section>
  </div>
}

function TransferPanel({ postStudioApi, t }: OperationsViewProps) {
  const [busy, setBusy] = useState('')
  const [note, setNote] = useState<{ text: string; bad: boolean } | null>(null)
  const [importFile, setImportFile] = useState<{ filename: string; content: string } | null>(null)
  const [plan, setPlan] = useState<ImportPlan | null>(null)
  const [startNumber, setStartNumber] = useState('')
  const fileRef = useRef<HTMLInputElement>(null)

  const say = (text: string, bad = false) => setNote({ text, bad })

  const runExport = async (format: ExportFormat) => {
    setBusy(`export-${format}`)
    try {
      const response = await fetch(`${API_PROXY_BASE}/export?format=${format}`)
      if (!response.ok) throw new Error(await response.text())
      const blob = await response.blob()
      const disposition = response.headers.get('content-disposition') ?? ''
      const match = /filename\*?=(?:UTF-8'')?"?([^";]+)"?/i.exec(disposition)
      const name = match?.[1] !== undefined ? decodeURIComponent(match[1]) : `book.${format}`
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

  const chooseFile = async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0]
    if (file === undefined) return
    const content = await file.text()
    if (content.trim() === '') {
      say(t('tools.import.empty'), true)
      return
    }
    setImportFile({ filename: file.name, content })
    setPlan(null)
  }

  const preview = async () => {
    if (importFile === null) return
    setBusy('preview')
    try {
      const result = await postStudioApi('/import/preview', {
        ...importFile,
        ...(startNumber !== '' ? { start_number: startNumber } : {}),
      })
      setPlan(result as ImportPlan)
    } catch (cause: unknown) {
      say(`${t('tools.import.failed')}: ${cause instanceof Error ? cause.message : String(cause)}`, true)
    } finally { setBusy('') }
  }

  const executeImport = async () => {
    if (importFile === null || plan === null) return
    const force = plan.conflicts.length > 0
    if (force && !window.confirm(t('tools.import.force'))) return
    setBusy('import')
    try {
      const result = await postStudioApi('/import', {
        ...importFile,
        ...(startNumber !== '' ? { start_number: startNumber } : {}),
        ...(force ? { force: true } : {}),
      }) as ImportPlan
      say(t('tools.import.done').replace('{count}', String(result.chapter_count)).replace('{start}', String(result.start_number)))
      setPlan(null)
      setImportFile(null)
      if (fileRef.current !== null) fileRef.current.value = ''
      workbenchStore.invalidate('workspace')
      workbenchStore.invalidate('outline')
    } catch (cause: unknown) {
      say(`${t('tools.import.failed')}: ${cause instanceof Error ? cause.message : String(cause)}`, true)
    } finally { setBusy('') }
  }

  return <div className={css.transferPanel}>
    <header><h2>{t('operations.transfer')}</h2><p>{t('operations.transferHint')}</p></header>
    {note !== null && <div className={css.operationNote} data-bad={note.bad}>{note.text}</div>}
    <section className={css.operationSection}>
      <div><Download size={18} /><strong>{t('tools.export')}</strong></div>
      <span>{(['md', 'txt', 'epub'] as const).map(format => <button key={format} type="button" className={css.commandButton}
        disabled={busy !== ''} onClick={() => void runExport(format)}>{format.toUpperCase()}</button>)}</span>
    </section>
    <section className={css.operationSection}>
      <div><RefreshCw size={18} /><strong>{t('tools.sync')}</strong></div>
      <button type="button" className={css.commandButton} disabled={busy !== ''} onClick={() => void runSync()}>{t('tools.sync')}</button>
    </section>
    <section className={css.operationSection}>
      <div><FileUp size={18} /><strong>{t('tools.import')}</strong></div>
      <input ref={fileRef} type="file" accept=".md,.markdown,.txt" onChange={event => void chooseFile(event)} />
      <label>{t('tools.import.start')}<input value={startNumber} inputMode="numeric" placeholder={t('tools.import.startAuto')}
        onChange={event => setStartNumber(event.target.value.replace(/[^0-9]/g, ''))} /></label>
      <button type="button" className={css.commandButton} disabled={busy !== '' || importFile === null} onClick={() => void preview()}>{t('tools.import.preview')}</button>
      {plan !== null && <div className={css.importPlan}>
        <span>{t('tools.import.plan').replace('{count}', String(plan.chapter_count)).replace('{units}', String(plan.writing_units))
          .replace('{start}', String(plan.start_number)).replace('{arc}', plan.arc_id)}</span>
        {plan.conflicts.length > 0 && <span>{t('tools.import.conflicts').replace('{ids}', plan.conflicts.join(', '))}</span>}
        <button type="button" className={css.commandButton} onClick={() => void executeImport()}>
          {plan.conflicts.length > 0 ? t('tools.import.force') : t('tools.import.confirm')}
        </button>
      </div>}
    </section>
    <a className={css.externalLink} href="http://127.0.0.1:4567" target="_blank" rel="noreferrer">
      <ExternalLink size={15} />{t('openExternal')}
    </a>
  </div>
}

