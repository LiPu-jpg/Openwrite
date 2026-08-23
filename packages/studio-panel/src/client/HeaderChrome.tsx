import { useEffect, useRef, useState } from 'react'
import { BookOpen, ExternalLink, MoreHorizontal, RefreshCw } from 'lucide-react'
import type { PropsLocale, PropsRuntime } from '@deepseek-ai/dsh-client-ui-slots'
import type { StudioApiInjected } from './api.ts'
import { useWorkbench, workbenchStore } from './WorkbenchStore.ts'
import css from './Workbench.module.css'

type HeaderProps = PropsRuntime<'conversation.session.header.actions'> & PropsLocale<'studio-panel'>
type UtilityProps = PropsRuntime<'conversation.session.header.utilities'> & PropsLocale<'studio-panel'> & Pick<StudioApiInjected, 'postStudioApi'>
type ContextChipProps = PropsRuntime<'conversation.input.left'> & PropsLocale<'studio-panel'>

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

export function ComposerContextChip({ t }: ContextChipProps) {
  const workbench = useWorkbench()
  const chapter = workbench.chapters.find(item => item.path === workbench.activeChapterPath)
  if (chapter === undefined) return null
  return <span className={css.contextChip} title={`${t('creation.context')}: ${chapter.path}`}>
    <BookOpen size={13} /><span>{chapter.id}</span>
  </span>
}

