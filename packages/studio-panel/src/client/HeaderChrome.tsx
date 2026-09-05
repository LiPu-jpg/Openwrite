import { useEffect, useRef, useState } from 'react'
import { BookOpen, ExternalLink, MoreHorizontal, RefreshCw } from 'lucide-react'
import type { PropsLocale, PropsRuntime } from '@deepseek-ai/dsh-client-ui-slots'
import type { StudioApiInjected } from './api.ts'
import { useWorkbench, workbenchStore } from './WorkbenchStore.ts'
import { initWorkspaceProject, useBindStudioContext, type StudioPanelInjected } from './workspace-context.ts'
import css from './Workbench.module.css'

type HeaderProps = PropsRuntime<'conversation.session.header.actions'> & PropsLocale<'studio-panel'>
type UtilityProps = PropsRuntime<'conversation.session.header.utilities'> & PropsLocale<'studio-panel'> & Pick<StudioApiInjected, 'postStudioApi'>
type ContextChipProps = PropsRuntime<'conversation.input.left'> & PropsLocale<'studio-panel'>
  & Pick<StudioPanelInjected, 'postStudioApi' | 'workspaces' | 'sessions'>

export function HeaderProjectStatus({ t }: HeaderProps) {
  const workbench = useWorkbench()
  const chapter = workbench.chapters.find(item => item.path === workbench.activeChapterPath)
  return <div className={css.headerStatus} title={`${workbench.projectTitle} · ${chapter?.title ?? ''}`}>
    <span className={css.connectionDot} data-state={workbench.connection} />
    <strong>{workbench.projectTitle || 'OpenWrite'}</strong>
    {chapter !== undefined && <span>{chapter.id} · {chapter.title}</span>}
    <span data-save={workbench.editorStatus}>{t(`creation.status.${workbench.editorStatus}`)}</span>
    {workbench.activeTasks > 0 && <b>{workbench.activeTasks}</b>}
  </div>
}

export function HeaderUtilities({ postStudioApi, t }: UtilityProps) {
  const [open, setOpen] = useState(false)
  const [busy, setBusy] = useState(false)
  const rootRef = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!open) return
    const dismiss = (event: PointerEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) setOpen(false)
    }
    document.addEventListener('pointerdown', dismiss)
    return () => document.removeEventListener('pointerdown', dismiss)
  }, [open])

  const sync = async () => {
    setBusy(true)
    try {
      await postStudioApi('/sync', {})
      workbenchStore.invalidate('workspace')
      setOpen(false)
    } finally { setBusy(false) }
  }

  const openStudio = async () => {
    let url = 'http://127.0.0.1:4567'
    try {
      const response = await fetch('/studio-panel/config.json')
      const data = await response.json() as { studioUrl?: unknown }
      if (typeof data.studioUrl === 'string') url = data.studioUrl
    } catch { /* use local default */ }
    window.open(url, '_blank', 'noopener,noreferrer')
    setOpen(false)
  }

  return <div className={css.headerUtilities} ref={rootRef}>
    <button type="button" className={css.headerIconButton} title={t('tools.title')} aria-expanded={open} onClick={() => setOpen(value => !value)}>
      <MoreHorizontal size={18} />
    </button>
    {open && <div className={css.headerMenu}>
      <button type="button" disabled={busy} onClick={() => void sync()}><RefreshCw size={15} />{t('tools.sync')}</button>
      <button type="button" onClick={() => void openStudio()}><ExternalLink size={15} />{t('openExternal')}</button>
    </div>}
  </div>
}

/**
 * Input-bar Workspace chip: reflects the session's dsh Workspace binding and
 * owns binding it into the WorkbenchStore context barrier. When the binding
 * needs action it is a button opening a small popover: an unbound session
 * gets the directory-pick attach flow; a bound-but-uninitialized workspace
 * gets the inline init form (novel id + title, pinned to the canonical
 * path). An initialized workspace renders read-only.
 */
export function WorkspaceContextChip(props: ContextChipProps) {
  const { t, postStudioApi, workspaces, sessions } = props
  const workbench = useWorkbench()
  const workspace = useBindStudioContext({ sessionId: props.sessionId, useWorkspaces: props.useWorkspaces })
  const notInitialized = workbench.workspaceError === 'WORKSPACE_NOT_INITIALIZED'
  const actionable = workspace === undefined || notInitialized
  const [open, setOpen] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [novelId, setNovelId] = useState('')
  const [title, setTitle] = useState('')
  const rootRef = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!open) return
    const dismiss = (event: PointerEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) setOpen(false)
    }
    document.addEventListener('pointerdown', dismiss)
    return () => document.removeEventListener('pointerdown', dismiss)
  }, [open])

  /** Unbound session: pick a directory, register it as a dsh Workspace, connect a session. */
  const attachWorkspace = async () => {
    if (busy) return
    setBusy(true)
    setError('')
    try {
      const picked = await workspaces.pickDirectory()
      if (picked !== null) {
        const created = await workspaces.create({ path: picked })
        const sessionId = await workspaces.connectWorkspace(created.workspaceId)
        sessions.open(sessionId)
      }
      setOpen(false)
    } catch (cause: unknown) {
      setError(`${t('workspace.bind.failed')}: ${cause instanceof Error ? cause.message : String(cause)}`)
    } finally { setBusy(false) }
  }

  /** Bound-but-uninitialized workspace: init in place at the canonical path. */
  const initProject = async () => {
    if (workspace === undefined || busy || novelId.trim() === '' || title.trim() === '') return
    setBusy(true)
    setError('')
    try {
      await initWorkspaceProject(postStudioApi, workspace.path, { novelId: novelId.trim(), title: title.trim() })
      setOpen(false)
      setNovelId('')
      setTitle('')
    } catch (cause: unknown) {
      setError(`${t('operations.create.failed')}: ${cause instanceof Error ? cause.message : String(cause)}`)
    } finally { setBusy(false) }
  }

  const label = <><BookOpen size={13} />
    <span>{workspace?.title ?? t('workspace.unbound')}</span>
    {notInitialized && <span className={css.contextChipBadge}>{t('workspace.notInitialized')}</span>}</>

  return <div className={css.contextChipRoot} ref={rootRef}>
    {actionable
      ? <button type="button" className={css.contextChip} data-actionable="true"
          data-unbound={workspace === undefined} aria-expanded={open}
          title={workspace !== undefined ? workspace.path : t('workspace.bind.hint')}
          onClick={() => setOpen(value => !value)}>{label}</button>
      : <span className={css.contextChip} title={workspace.path}>{label}</span>}
    {open && workspace === undefined && <div className={css.contextChipPopover}>
      <span className={css.contextChipHint}>{t('workspace.bind.hint')}</span>
      <button type="button" className={css.commandButton} disabled={busy}
        onClick={() => void attachWorkspace()}>{t('workspace.bind.pick')}</button>
      {error !== '' && <span className={css.contextChipError}>{error}</span>}
    </div>}
    {open && workspace !== undefined && notInitialized && <div className={css.contextChipPopover}>
      <span className={css.contextChipHint}>{t('operations.init.hint')}</span>
      <label className={css.contextChipField}>{t('operations.create.id')}
        <input value={novelId} placeholder="my-novel" onChange={e => setNovelId(e.target.value)} /></label>
      <label className={css.contextChipField}>{t('operations.create.title')}
        <input value={title} placeholder={t('operations.create.titleHint')} maxLength={120}
          onChange={e => setTitle(e.target.value)} /></label>
      <button type="button" className={css.commandButton}
        disabled={busy || novelId.trim() === '' || title.trim() === ''}
        onClick={() => void initProject()}>{t('operations.init.submit')}</button>
      {error !== '' && <span className={css.contextChipError}>{error}</span>}
    </div>}
  </div>
}
