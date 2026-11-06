/**
 * Machine-global deep-research search defaults.
 *
 * The host settings dialog has no Workspace, so this section uses the global
 * `/research/preferences` route. A single work can override the provider in
 * its own Research view; that workspace setting wins over these defaults.
 */
import { useEffect, useState } from 'react'
import type { PropsLocale } from '@deepseek-ai/dsh-client-ui-slots'
import { fetchGlobalStudioApi, postGlobalStudioApi } from './api.ts'
import css from './OpenWriteSettings.module.css'

interface SearchProvider {
  id: string
  label: string
  requiresApiKey: boolean
  configured: boolean
}

interface ViewState {
  provider: string
  providers: SearchProvider[]
  hostWeb: boolean
}

function parsePreferences(value: unknown): ViewState {
  const outer = value !== null && typeof value === 'object' ? value as Record<string, unknown> : {}
  const data = outer['data'] !== null && typeof outer['data'] === 'object' ? outer['data'] as Record<string, unknown> : outer
  const settings = data['settings'] !== null && typeof data['settings'] === 'object' ? data['settings'] as Record<string, unknown> : {}
  const raw = Array.isArray(settings['search_providers']) ? settings['search_providers'] as unknown[] : []
  const providers = raw.map(item => {
    const row = item !== null && typeof item === 'object' ? item as Record<string, unknown> : {}
    const id = typeof row['id'] === 'string' ? row['id'] : ''
    return {
      id,
      label: typeof row['label'] === 'string' && row['label'] !== '' ? row['label'] : id,
      requiresApiKey: row['requires_api_key'] === true,
      configured: row['configured'] === true,
    }
  }).filter(item => item.id !== '')
  const current = typeof settings['search_provider'] === 'string' ? settings['search_provider'] : ''
  return {
    provider: current !== '' ? current : (providers[0]?.id ?? ''),
    providers,
    hostWeb: data['host_web_available'] === true,
  }
}

export function SearchSettings({ t }: PropsLocale<'studio-panel'>): JSX.Element {
  const [state, setState] = useState<ViewState | null>(null)
  const [provider, setProvider] = useState('')
  const [apiKey, setApiKey] = useState('')
  const [remember, setRemember] = useState(true)
  const [busy, setBusy] = useState(false)
  const [notice, setNotice] = useState<{ text: string; bad: boolean } | null>(null)

  useEffect(() => {
    const controller = new AbortController()
    void fetchGlobalStudioApi('/research/preferences', controller.signal)
      .then(value => {
        if (controller.signal.aborted) return
        const next = parsePreferences(value)
        setState(next)
        setProvider(next.provider)
      })
      .catch(() => { if (!controller.signal.aborted) setState({ provider: '', providers: [], hostWeb: false }) })
    return () => controller.abort()
  }, [])

  const save = async () => {
    if (provider === '') return
    setBusy(true); setNotice(null)
    try {
      const value = await postGlobalStudioApi('/research/preferences', {
        search_provider: provider,
        search_api_key: apiKey,
        remember_api_key: remember,
      })
      const next = parsePreferences(value)
      setState(next)
      setProvider(next.provider)
      setApiKey('')
      setNotice({ text: t('research.settings.saved'), bad: false })
    } catch (cause) {
      setNotice({ text: `${t('research.settings.failed')}: ${cause instanceof Error ? cause.message : String(cause)}`, bad: true })
    } finally { setBusy(false) }
  }

  if (state === null) return <p>{t('loading')}</p>
  const selected = state.providers.find(item => item.id === provider)
  const dshUnavailable = provider === 'dsh' && !state.hostWeb
  const mark = (id: string): string => id === 'dsh' ? 'DSH' : id === 'bocha' ? '博' : id === 'bing' ? 'B' : id === 'jina' ? 'J' : id === 'none' ? '—' : id.slice(0, 2).toUpperCase()
  return <div className={css.searchSurface}>
    <div className={css.searchIntro}>
      <span className={css.searchGlyph} aria-hidden="true">⌕</span>
      <div>
        <h4 className={css.searchTitle}>{t('research.settings')}</h4>
        <p>{t('research.settings.globalHint')}</p>
      </div>
      <span className={css.pill}>{state.hostWeb ? 'DSH' : t('research.settings.unavailable')}</span>
    </div>

    <div className={css.providerGrid} role="radiogroup" aria-label={t('research.settings.provider')}>
      {state.providers.map(item => <label
        key={item.id}
        className={css.providerCard}
        data-selected={item.id === provider}
        data-configured={item.configured}
        data-provider={item.id}
      >
        <input
          type="radio"
          name="research-search-provider"
          value={item.id}
          checked={item.id === provider}
          onChange={() => setProvider(item.id)}
        />
        <span className={css.providerMark} aria-hidden="true">{mark(item.id)}</span>
        <span className={css.providerBody}>
          <strong>{item.label}</strong>
          <small>{item.requiresApiKey ? t('research.settings.apiKeyRequired') : t('research.settings.noKeyRequired')}</small>
        </span>
        <span className={css.providerState} data-configured={item.configured}>
          {item.configured ? t('research.settings.ready') : t('research.settings.notConfigured')}
        </span>
      </label>)}
    </div>

    {selected?.requiresApiKey === true && <label className={css.field}>
      <span className={css.fieldLabel}>{t('research.settings.apiKey')}</span>
      <input className={css.textInput} type="password" value={apiKey} autoComplete="off" onChange={event => setApiKey(event.target.value)} />
    </label>}
    {provider === 'dsh' && <div className={css.callout}><span aria-hidden="true">✦</span><span>{t('research.settings.dshHint')}</span></div>}
    {dshUnavailable && <div className={css.callout}><span aria-hidden="true">!</span><span>{t('research.settings.dshUnavailable')}</span></div>}

    <div className={css.searchFooter}>
      {selected?.requiresApiKey === true
        ? <label className={css.checkboxRow}><input type="checkbox" checked={remember} onChange={event => setRemember(event.target.checked)} /> {t('research.settings.remember')}</label>
        : <span />}
      <button className={css.primaryButton} type="button" disabled={busy || provider === ''} onClick={() => void save()}>
        {busy ? t('research.settings.saving') : t('research.settings.save')}
      </button>
    </div>
    {notice !== null && <p role="status" className={notice.bad ? css.error : css.successNotice}>{notice.text}</p>}
  </div>
}
