import { useCallback, useEffect, useRef, useState } from 'react'
import { BookOpen, ChevronDown, ExternalLink, MoreHorizontal, Plus, RefreshCw } from 'lucide-react'
import type { PropsLocale, PropsRuntime } from '@deepseek-ai/dsh-client-ui-slots'
import type { StudioApiInjected } from './api.ts'
import { useWorkbench, workbenchStore } from './WorkbenchStore.ts'
import css from './Workbench.module.css'

type HeaderProps = PropsRuntime<'conversation.session.header.actions'> & PropsLocale<'studio-panel'>
type UtilityProps = PropsRuntime<'conversation.session.header.utilities'> & PropsLocale<'studio-panel'> & Pick<StudioApiInjected, 'postStudioApi'>
type ContextChipProps = PropsRuntime<'conversation.input.left'> & PropsLocale<'studio-panel'> & Pick<StudioApiInjected, 'fetchStudioApi' | 'postStudioApi'>

interface ProjectEntry {
  path: string
  title: string
  novel_id: string
}

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
 * Input-bar project selector chip: always visible, shows the currently bound
 * OpenWrite project. Click to open a dropdown listing registered projects —
 * select one to switch via POST /api/project/open.
 */
export function ProjectSwitcherChip({ fetchStudioApi, postStudioApi, t }: ContextChipProps) {
  const workbench = useWorkbench()
  const [open, setOpen] = useState(false)
  const [projects, setProjects] = useState<ProjectEntry[]>([])
  const [creating, setCreating] = useState(false)
  const [newTitle, setNewTitle] = useState('')
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

  const loadProjects = useCallback(() => {
    fetchStudioApi('/project/list').then((data: unknown) => {
      if (Array.isArray(data)) setProjects(data as ProjectEntry[])
    }).catch(() => {})
  }, [fetchStudioApi])

  useEffect(() => {
    if (open) loadProjects()
  }, [open, loadProjects])

  const current = workbench.projectTitle || 'OpenWrite'

  const switchTo = async (path: string) => {
    if (busy) return
    setBusy(true)
    try {
      await postStudioApi('/project/open', { project_path: path })
      window.location.reload()
    } finally { setBusy(false) }
  }

  const createProject = async () => {
    const title = newTitle.trim()
    if (!title || busy) return
    const novelId = 'novel_' + title.replace(/[^a-zA-Z0-9]/g, '_').replace(/_+/g, '_').slice(0, 40).toLowerCase()
    setBusy(true)
    try {
      await postStudioApi('/project/init', {
        project_path: novelId,
        novel_id: novelId,
        title,
      })
      window.location.reload()
    } catch {
      setBusy(false)
    }
  }

  return <div className={css.contextChipRoot} ref={rootRef}>
    <button type="button" className={css.contextChip} aria-expanded={open}
      onClick={() => { setOpen(value => !value); loadProjects() }}>
      <BookOpen size={13} />
      <span>{current}</span>
      <ChevronDown size={12} />
    </button>
    {open && <div className={css.contextChipMenu}>
      <div className={css.contextChipLabel}>{t('project.switcher.label')}</div>
      {projects.map(project => (
        <button key={project.path} type="button" className={css.contextChipMenuItem}
          data-active={project.title === current}
          disabled={busy} onClick={() => { void switchTo(project.path) }}>
          <BookOpen size={14} />
          <span>{project.title}</span>
          {project.title === current && <span className={css.contextChipCurrentMark}>✓</span>}
        </button>
      ))}
      <div className={css.contextChipDivider} />
      {!creating ? (
        <button type="button" className={css.contextChipMenuItem} onClick={() => setCreating(true)}>
          <Plus size={14} />{t('project.switcher.new')}
        </button>
      ) : (
        <div className={css.contextChipCreateForm}>
          <input value={newTitle} placeholder={t('project.switcher.newTitle')}
            onChange={e => setNewTitle(e.target.value)}
            onKeyDown={e => { if (e.key === 'Enter' && newTitle.trim()) void createProject() }}
            autoFocus />
          <button type="button" className={css.contextChipMenuItem} disabled={!newTitle.trim() || busy}
            onClick={() => void createProject()}>
            {t('project.switcher.create')}
          </button>
        </div>
      )}
    </div>}
  </div>
}
