import { useCallback, useEffect, useMemo, useState } from 'react'
import { FlaskConical, Pencil, Plus, RefreshCw, Save, Trash2 } from 'lucide-react'
import type { ConvViewProps } from '@deepseek-ai/dsh-client-ui-conversation/client'
import type { InjectFace, PropsLocale } from '@deepseek-ai/dsh-client-ui-slots'
import type { StudioApiInjected } from './api.ts'
import { asInteger as integer, asText as text, parseModelProfiles, parseRouteMap, type JsonRecord as RecordValue, type ModelProfileDto } from './dto.ts'
import css from './views.module.css'

type ModelProfile = ModelProfileDto

type ProfileForm = Omit<ModelProfile, 'configured' | 'embedding_configured'> & {
  api_key: string
  embedding_api_key: string
  remember_api_key: boolean
}

type ModelViewProps = ConvViewProps & InjectFace<StudioApiInjected> & PropsLocale<'studio-panel'>


const emptyForm = (): ProfileForm => ({
  id: '', label: '', provider: 'openai', model: '', base_url: '', api_format: 'chat',
  context_tokens: 64000, max_output_tokens: 24000, embedding_provider: 'openai',
  embedding_model: '', api_key: '', embedding_api_key: '', remember_api_key: true,
})

function fromProfile(value: RecordValue): ProfileForm {
  return {
    id: text(value['id']), label: text(value['label']), provider: text(value['provider']) || 'openai',
    model: text(value['model']), base_url: text(value['base_url']), api_format: text(value['api_format']) || 'chat',
    context_tokens: integer(value['context_tokens'], 64000), max_output_tokens: integer(value['max_output_tokens'], 24000),
    embedding_provider: text(value['embedding_provider']) || 'openai', embedding_model: text(value['embedding_model']),
    api_key: '', embedding_api_key: '', remember_api_key: true,
  }
}

export function ModelView({ fetchStudioApi, postStudioApi, t }: ModelViewProps) {
  const [profiles, setProfiles] = useState<ModelProfile[]>([])
  const [routes, setRoutes] = useState<Record<string, string>>({})
  const [form, setForm] = useState<ProfileForm>(emptyForm)
  const [selectedId, setSelectedId] = useState('')
  const [fallbackId, setFallbackId] = useState('')
  const [busy, setBusy] = useState('')
  const [notice, setNotice] = useState<{ text: string; bad: boolean } | null>(null)

  const load = useCallback(async () => {
    setBusy('load')
    try {
      const value = await fetchStudioApi('/model/profiles')
      const next = parseModelProfiles(value)
      setProfiles(next)
      setRoutes(parseRouteMap(value))
      setSelectedId(current => current && next.some(item => item.id === current) ? current : next[0]?.id || '')
    } catch (cause: unknown) {
      setNotice({ text: cause instanceof Error ? cause.message : String(cause), bad: true })
    } finally { setBusy('') }
  }, [fetchStudioApi])

  useEffect(() => { void load() }, [load])

  const selected = useMemo(() => profiles.find(item => item.id === selectedId), [profiles, selectedId])
  useEffect(() => {
    if (selected !== undefined) setForm(fromProfile(selected as unknown as RecordValue))
  }, [selected])
  useEffect(() => {
    setFallbackId(current => current && profiles.some(item => item.id === current && item.id !== selectedId) ? current : (profiles.find(item => item.id !== selectedId)?.id || ''))
  }, [profiles, selectedId])

  const setField = <K extends keyof ProfileForm>(key: K, value: ProfileForm[K]) => setForm(current => ({ ...current, [key]: value }))
  const save = async () => {
    if (!form.id.trim() || !form.label.trim() || !form.model.trim() || busy !== '') return
    setBusy('save'); setNotice(null)
    try {
      const payload: RecordValue = { ...form, id: form.id.trim(), label: form.label.trim(), model: form.model.trim() }
      if (form.api_key === '') delete payload['api_key']
      if (form.embedding_api_key === '') delete payload['embedding_api_key']
      await postStudioApi('/model/profiles', payload)
      setForm(current => ({ ...current, api_key: '', embedding_api_key: '' }))
      setNotice({ text: t('models.saved'), bad: false }); await load()
    } catch (cause: unknown) { setNotice({ text: cause instanceof Error ? cause.message : String(cause), bad: true }) }
    finally { setBusy('') }
  }
  const create = () => { setSelectedId(''); setForm(emptyForm()); setNotice(null) }
  const remove = async () => {
    if (!selectedId || busy !== '') return
    setBusy('delete'); setNotice(null)
    try {
      await postStudioApi('/model/profiles/delete', { profile_id: selectedId, fallback_id: fallbackId })
      setNotice({ text: t('models.deleted'), bad: false }); await load()
    } catch (cause: unknown) { setNotice({ text: cause instanceof Error ? cause.message : String(cause), bad: true }) }
    finally { setBusy('') }
  }
  const test = async (embedding: boolean) => {
    if (busy !== '') return
    setBusy(embedding ? 'embedding' : 'test'); setNotice(null)
    try {
      const payload: RecordValue = { ...form }
      if (selectedId !== '') payload['id'] = selectedId
      if (embedding) await postStudioApi('/model/embedding/test', payload)
      else await postStudioApi('/model/test', payload)
      setNotice({ text: embedding ? t('models.embeddingOk') : t('models.chatOk'), bad: false })
    } catch (cause: unknown) { setNotice({ text: cause instanceof Error ? cause.message : String(cause), bad: true }) }
    finally { setBusy('') }
  }
  const saveRoutes = async () => {
    setBusy('routes'); setNotice(null)
    try { await postStudioApi('/model/routes', { routes }); setNotice({ text: t('models.routesSaved'), bad: false }); await load() }
    catch (cause: unknown) { setNotice({ text: cause instanceof Error ? cause.message : String(cause), bad: true }) }
    finally { setBusy('') }
  }

  return <div className={css.root}>
    <div className={css.toolbar}><span className={css.toolbarMeta}>{t('models.title')}</span><span className={css.toolbarActions}>
      <button type="button" className={css.button} onClick={create} disabled={busy !== ''}><Plus size={14} /> {t('models.new')}</button>
      <button type="button" className={css.button} onClick={() => void load()} disabled={busy !== ''}><RefreshCw size={14} /></button>
    </span></div>
    <div className={css.body}>
      {notice !== null && <div className={notice.bad ? css.taskError : css.notice}>{notice.text}</div>}
      <div className={css.modelLayout}>
        <section className={css.modelList} aria-label={t('models.list')}>
          {profiles.map(profile => <button type="button" key={profile.id} className={css.modelListItem} data-active={profile.id === selectedId} onClick={() => setSelectedId(profile.id)}>
            <strong>{profile.label}</strong><span>{profile.provider} · {profile.model}</span><small>{profile.configured ? t('models.configured') : t('models.missing')}</small>
          </button>)}
          {profiles.length === 0 && <div className={css.notice}>{t('models.empty')}</div>}
        </section>
        <section className={css.modelEditor} aria-label={t('models.editor')}>
          <div className={css.modelFormGrid}>
            <label>{t('models.id')}<input value={form.id} onChange={event => setField('id', event.target.value)} disabled={selectedId !== ''} /></label>
            <label>{t('models.label')}<input value={form.label} onChange={event => setField('label', event.target.value)} /></label>
            <label>{t('models.provider')}<select value={form.provider} onChange={event => setField('provider', event.target.value)}><option value="openai">openai</option><option value="anthropic">anthropic</option><option value="custom">custom</option></select></label>
            <label>{t('models.modelId')}<input value={form.model} onChange={event => setField('model', event.target.value)} /></label>
            <label>{t('models.baseUrl')}<input value={form.base_url} onChange={event => setField('base_url', event.target.value)} /></label>
            <label>{t('models.apiFormat')}<select value={form.api_format} onChange={event => setField('api_format', event.target.value)}><option value="chat">chat</option><option value="responses">responses</option></select></label>
            <label>{t('models.context')}<input type="number" value={form.context_tokens} onChange={event => setField('context_tokens', Number(event.target.value))} /></label>
            <label>{t('models.output')}<input type="number" value={form.max_output_tokens} onChange={event => setField('max_output_tokens', Number(event.target.value))} /></label>
            <label>{t('models.credential')}<input type="password" autoComplete="new-password" value={form.api_key} onChange={event => setField('api_key', event.target.value)} placeholder={t('models.credentialHint')} /></label>
            <label>{t('models.embeddingProvider')}<input value={form.embedding_provider} onChange={event => setField('embedding_provider', event.target.value)} /></label>
            <label>{t('models.embeddingModel')}<input value={form.embedding_model} onChange={event => setField('embedding_model', event.target.value)} /></label>
            <label>{t('models.embeddingCredential')}<input type="password" autoComplete="new-password" value={form.embedding_api_key} onChange={event => setField('embedding_api_key', event.target.value)} placeholder={t('models.credentialHint')} /></label>
          </div>
          <label className={css.modelCheckbox}><input type="checkbox" checked={form.remember_api_key} onChange={event => setField('remember_api_key', event.target.checked)} />{t('models.remember')}</label>
          <div className={css.modelActions}><button type="button" className={css.button} onClick={() => void save()} disabled={busy !== ''}><Save size={14} /> {t('models.save')}</button><button type="button" className={css.button} onClick={() => void test(false)} disabled={busy !== ''}><Pencil size={14} /> {t('models.chatTest')}</button><button type="button" className={css.button} onClick={() => void test(true)} disabled={busy !== ''}><FlaskConical size={14} /> {t('models.embeddingTest')}</button>{selectedId !== '' && <button type="button" className={css.buttonDanger} onClick={() => void remove()} disabled={busy !== ''}><Trash2 size={14} /> {t('models.delete')}</button>}</div>
          {selectedId !== '' && <div className={css.modelDependencies}><h3>{t('models.dependencies')}</h3><p>{t('models.dependenciesHint')}</p><ul>{Object.entries(routes).filter(([, id]) => id === selectedId).map(([route]) => <li key={route}>{route}</li>)}</ul><label>{t('models.fallback')}<select value={fallbackId} onChange={event => setFallbackId(event.target.value)}><option value="">{t('models.chooseFallback')}</option>{profiles.filter(item => item.id !== selectedId).map(item => <option key={item.id} value={item.id}>{item.label} · {item.model}</option>)}</select></label></div>}
        </section>
      </div>
      <section className={css.modelRoutes}><div className={css.paneHeading}>{t('models.routes')}</div>{Object.entries(routes).map(([route, id]) => <label key={route}>{route}<select value={id} onChange={event => setRoutes(current => ({ ...current, [route]: event.target.value }))}>{profiles.map(profile => <option key={profile.id} value={profile.id}>{profile.label} · {profile.provider} · {profile.model}</option>)}</select></label>)}<button type="button" className={css.button} onClick={() => void saveRoutes()} disabled={busy !== ''}><Save size={14} /> {t('models.routesSave')}</button></section>
    </div>
  </div>
}
