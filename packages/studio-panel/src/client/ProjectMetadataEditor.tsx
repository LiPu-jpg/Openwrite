import { useEffect, useRef, useState } from 'react'
import type { OperationsViewProps } from './OperationsView.tsx'
import css from './Workbench.module.css'

type Props = Pick<OperationsViewProps, 'fetchStudioApi' | 'postStudioApi' | 't'> & { onSaved: () => void }
type Metadata = { title: string; author: string; language: string }

export function ProjectMetadataEditor({ fetchStudioApi, postStudioApi, t, onSaved }: Props) {
  const [value, setValue] = useState<Metadata | null>(null)
  const [revision, setRevision] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const mounted = useRef(true)
  useEffect(() => { mounted.current = true; return () => { mounted.current = false } }, [])
  const load = async () => {
    setBusy(true); setError('')
    try {
      const response = await fetchStudioApi('/workspace') as Record<string, any>
      const project = (response.data ?? response).project
      if (!project?.metadata || !project.metadata_revision) throw new Error(t('tools.export.unavailable'))
      if (mounted.current) {
        setValue({ title: String(project.metadata.title ?? ''), author: String(project.metadata.author ?? ''), language: String(project.metadata.language ?? 'zh-CN') })
        setRevision(String(project.metadata_revision))
      }
    } catch (cause) { if (mounted.current) setError(cause instanceof Error ? cause.message : String(cause)) }
    finally { if (mounted.current) setBusy(false) }
  }
  const save = async () => {
    if (!value || busy) return
    setBusy(true); setError('')
    try {
      await postStudioApi('/project/metadata', { ...value, expected_revision: revision })
      if (mounted.current) { setValue(null); onSaved() }
    } catch (cause) { if (mounted.current) setError(cause instanceof Error ? cause.message : String(cause)) }
    finally { if (mounted.current) setBusy(false) }
  }
  return <div>
    <button type="button" className={css.actionButton} disabled={busy || value !== null} onClick={() => void load()}>{t('tools.metadata.edit')}</button>
    {error && <p role="alert">{error}</p>}
    {value && <form onSubmit={event => { event.preventDefault(); void save() }}>
      <p>{t('tools.metadata.hint')}</p>
      <div className={css.exportControls}>
        {(['title', 'author', 'language'] as const).map(key => <label key={key}>{t(`tools.export.metadata.${key}`)}
          <input required disabled={busy} value={value[key]} maxLength={key === 'language' ? 35 : 120}
            onChange={event => setValue({ ...value, [key]: event.target.value })} />
        </label>)}
        <button type="submit" className={css.commandButton} disabled={busy}>{t('tools.metadata.save')}</button>
        <button type="button" className={css.actionButton} disabled={busy} onClick={() => { setValue(null); setError('') }}>{t('tools.metadata.cancel')}</button>
      </div>
    </form>}
  </div>
}
