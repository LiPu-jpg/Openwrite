/**
 * Overview view (总览): a native 工具箱 strip (export / sync / import — the
 * OpenWrite 工具与设置 functions that have no other dsh-native surface) above
 * the embedded Studio dashboard iframe.
 *
 * Contracts (verified against OpenWrite tools/studio_application.py):
 * - GET  /api/export?format=md|txt|epub → binary download with
 *   Content-Disposition (proxy is binary-safe since the epub is a zip).
 * - POST /api/sync (no body) → project sync.
 * - POST /api/import/preview {filename, content, arc_id?, start_number?} →
 *   plan {chapter_count, writing_units, conflicts[], can_import, ...};
 *   POST /api/import {same, force?} → executes. TXT/Markdown only.
 */

import type { ConvViewProps } from '@deepseek-ai/dsh-client-ui-conversation/client'
import type { InjectFace, PropsLocale } from '@deepseek-ai/dsh-client-ui-slots'
import { useCallback, useRef, useState, type ChangeEvent, type ComponentType } from 'react'
import { API_PROXY_BASE, type StudioApiInjected } from './api.ts'
import { StudioView, type StudioViewInjected } from './StudioView.tsx'
import css from './views.module.css'

/** Minimal render face for the embedded dashboard: StudioView reads only
 * resolveStudioUrl and t from its slot-runtime prop bundle; composing it
 * directly omits the runtime seats it never touches. */
const EmbeddedDashboard = StudioView as unknown as ComponentType<{
  resolveStudioUrl: () => Promise<string>
  /** Pin the SPA to '#chapters'; empty/undefined boots the dashboard. A
   * fragment-only change navigates without reloading — editor state survives. */
  view?: string | undefined
  t: OverviewViewProps['t']
}>

/** Injected share: the iframe's Studio URL resolver plus the proxied API face. */
export type OverviewInjected = StudioViewInjected & StudioApiInjected

/** Full overview-view props: conversation-view runtime share & injected share & locale seat. */
export type OverviewViewProps =
  ConvViewProps & InjectFace<OverviewInjected> & PropsLocale<'studio-panel'>

interface ImportPlan {
  filename: string
  arc_id: string
  start_number: number
  chapter_count: number
  writing_units: number
  conflicts: string[]
  can_import: boolean
}

type ExportFormat = 'md' | 'txt' | 'epub'

const EXPORT_FORMATS: readonly ExportFormat[] = ['md', 'txt', 'epub']

export function OverviewView({ postStudioApi, resolveStudioUrl, t }: OverviewViewProps) {
  const [busy, setBusy] = useState<'export-md' | 'export-txt' | 'export-epub' | 'sync' | 'import' | null>(null)
  const [status, setStatus] = useState<{ text: string, bad: boolean } | null>(null)
  const [plan, setPlan] = useState<ImportPlan | null>(null)
  const [importText, setImportText] = useState<{ filename: string, content: string } | null>(null)
  const [startNumber, setStartNumber] = useState('')
  const [force, setForce] = useState(false)
  const [importOpen, setImportOpen] = useState(false)
  const fileRef = useRef<HTMLInputElement | null>(null)
  /** Which Studio surface the single iframe shows: dashboard or chapter editor. */
  const [mode, setMode] = useState<'overview' | 'chapters' | 'review'>('overview')

  const say = (text: string, bad = false) => {
    setStatus({ text, bad })
    window.setTimeout(() => setStatus(null), 6000)
  }

  /** Download one export format through the binary-safe same-origin proxy. */
  const runExport = async (format: ExportFormat) => {
    if (busy !== null) return
    setBusy(`export-${format}`)
    try {
      const response = await fetch(`${API_PROXY_BASE}/export?format=${format}`)
      if (!response.ok) {
        const text = await response.text()
        let message = text
        try { message = String(JSON.parse(text).error ?? text) } catch { /* keep raw text */ }
        throw new Error(message)
      }
      const blob = await response.blob()
      const dispo = response.headers.get('content-disposition') ?? ''
      const match = /filename\*?=(?:UTF-8'')?"?([^\";]+)"?/i.exec(dispo)
      const rawName = match === null ? undefined : match[1]
      const name = rawName !== undefined ? decodeURIComponent(rawName) : `book.${format}`
      const url = URL.createObjectURL(blob)
      const anchor = document.createElement('a')
      anchor.href = url
      anchor.download = name
      anchor.click()
      URL.revokeObjectURL(url)
      say(t('tools.export.done').replace('{name}', name))
    } catch (cause: unknown) {
      say(`${t('tools.export.failed')}: ${cause instanceof Error ? cause.message : String(cause)}`, true)
    } finally {
      setBusy(null)
    }
  }

  const runSync = async () => {
    if (busy !== null) return
    setBusy('sync')
    try {
      await postStudioApi('/sync', {})
      say(t('tools.sync.done'))
    } catch (cause: unknown) {
      say(`${t('tools.sync.failed')}: ${cause instanceof Error ? cause.message : String(cause)}`, true)
    } finally {
      setBusy(null)
    }
  }

  const pickFile = async (file: File) => {
    const content = await file.text()
    if (content.trim() === '') {
      say(t('tools.import.empty'), true)
      return
    }
    setImportText({ filename: file.name, content })
    setImportOpen(true)
    setPlan(null)
    setForce(false)
  }

  const runPreview = async () => {
    if (importText === null || busy !== null) return
    setBusy('import')
    try {
      const data = await postStudioApi('/import/preview', {
        filename: importText.filename,
        content: importText.content,
        ...(startNumber.trim() !== '' ? { start_number: startNumber.trim() } : {}),
      }) as ImportPlan
      setPlan(data)
    } catch (cause: unknown) {
      say(`${t('tools.import.failed')}: ${cause instanceof Error ? cause.message : String(cause)}`, true)
    } finally {
      setBusy(null)
    }
  }

  const runImport = useCallback(async (forceFlag: boolean) => {
    if (importText === null || busy !== null) return
    setBusy('import')
    try {
      const data = await postStudioApi('/import', {
        filename: importText.filename,
        content: importText.content,
        ...(startNumber.trim() !== '' ? { start_number: startNumber.trim() } : {}),
        ...(forceFlag ? { force: true } : {}),
      }) as ImportPlan
      setPlan(null)
      setImportText(null)
      if (fileRef.current !== null) fileRef.current.value = ''
      say(t('tools.import.done')
        .replace('{count}', String(data.chapter_count ?? 0))
        .replace('{start}', String(data.start_number ?? '')))
    } catch (cause: unknown) {
      say(`${t('tools.import.failed')}: ${cause instanceof Error ? cause.message : String(cause)}`, true)
    } finally {
      setBusy(null)
    }
  }, [importText, busy, postStudioApi, startNumber, t])

  const onFileChosen = (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0]
    if (file !== undefined) void pickFile(file)
  }

  return (
    <div className={css.toolsRoot}>
      <div className={css.toolsBar}>
        <span className={css.toolsTitle}>{t('tools.title')}</span>
        <span className={css.toolsGroup}>
          {EXPORT_FORMATS.map(format => (
            <button
              key={format}
              type="button"
              className={css.actionButton}
              disabled={busy !== null}
              onClick={() => { void runExport(format) }}
            >
              {busy === `export-${format}` ? '…' : t('tools.export').toUpperCase() + ' ' + format.toUpperCase()}
            </button>
          ))}
        </span>
        <span className={css.toolsGroup}>
          <button type="button" className={css.actionButton} disabled={busy !== null} onClick={() => { void runSync() }}>
            {busy === 'sync' ? '…' : t('tools.sync')}
          </button>
          <button
            type="button"
            className={css.actionButton}
            disabled={busy !== null}
            onClick={() => {
              setImportOpen(previous => !previous)
              if (importOpen) { setPlan(null); setImportText(null) }
            }}
          >
            {t('tools.import')}
          </button>
        </span>
        <input ref={fileRef} type="file" accept=".md,.markdown,.txt" className={css.toolsFile} onChange={onFileChosen} />
      </div>
      {status !== null && (
        <div className={css.toolsStatus} data-bad={status.bad}>
          {status.text}
        </div>
      )}
      {importOpen && (
        <div className={css.toolsImport}>
          <div className={css.toolsImportRow}>
            <button type="button" className={css.actionButton} disabled={busy !== null}
              onClick={() => { if (fileRef.current !== null) fileRef.current.click() }}>
              {t('tools.import.choose')}
            </button>
            <span className={css.toolsImportFile}>
              {importText?.filename ?? t('tools.import.noFile')}
            </span>
            <label className={css.toolsImportLabel}>
              {t('tools.import.start')}
              <input
                className={css.inlineInput}
                value={startNumber}
                inputMode="numeric"
                placeholder={t('tools.import.startAuto')}
                onChange={(event) => { setStartNumber(event.target.value.replace(/[^0-9]/g, '')) }}
              />
            </label>
            <button type="button" className={css.actionButton} disabled={busy !== null || importText === null}
              onClick={() => { void runPreview() }}>
              {t('tools.import.preview')}
            </button>
          </div>
          {plan !== null && (
            <div className={css.toolsImportPlan}>
              <div>
                {t('tools.import.plan')
                  .replace('{count}', String(plan.chapter_count))
                  .replace('{units}', String(plan.writing_units))
                  .replace('{start}', String(plan.start_number))
                  .replace('{arc}', plan.arc_id)}
                {plan.conflicts.length > 0 && (
                  <span className={css.errorText}> {t('tools.import.conflicts').replace('{ids}', plan.conflicts.join(', '))}</span>
                )}
              </div>
              <button
                type="button"
                className={css.actionButton}
                disabled={busy !== null || (!plan.can_import && !force)}
                onClick={() => { void runImport(plan.conflicts.length > 0) }}
              >
                {plan.conflicts.length > 0 ? t('tools.import.force') : t('tools.import.confirm')}
              </button>
            </div>
          )}
        </div>
      )}
      <div className={css.modeSwitch}>
        <button type="button" className={css.modeButton} data-active={mode === 'overview'}
          onClick={() => { setMode('overview') }}>
          {t('view.overview')}
        </button>
        <button type="button" className={css.modeButton} data-active={mode === 'chapters'}
          onClick={() => { setMode('chapters') }}>
          {t('view.studio')}
        </button>
        <button type="button" className={css.modeButton} data-active={mode === 'review'}
          onClick={() => { setMode('review') }}>
          {t('view.reviewWs')}
        </button>
      </div>
      <div className={css.toolsFrame}>
        <EmbeddedDashboard resolveStudioUrl={resolveStudioUrl} t={t} view={mode === 'overview' ? undefined : mode} />
      </div>
    </div>
  )
}
