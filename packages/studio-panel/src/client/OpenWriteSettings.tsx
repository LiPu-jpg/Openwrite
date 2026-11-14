/**
 * OpenWrite's page in the host's settings dialog.
 *
 * The host dialog is the one surface the author opens without a novel in
 * front of them, so this page owns every setting that is not tied to one
 * work: the writing environment, the model profile library (global by
 * design), the host's current model, and the companion plugins.
 *
 * The groups are tabs, the way `dsh-our-free-model` groups its own page: one
 * section, several groups, and the chosen group survives a dialog reopen.
 *
 * Every fact here comes from a host route that does not need a bound
 * workspace. The model library is global too — Studio keeps it outside every
 * project — so it is reached through the context-free global API.
 */

import { useCallback, useEffect, useRef, useState } from 'react'
import type { PropsLocale } from '@deepseek-ai/dsh-client-ui-slots'
import { CompanionSection, fetchCompanions, type CompanionStatus } from './companions.tsx'
import { ModelView } from './ModelView.tsx'
import { SearchSettings } from './SearchSettings.tsx'
import { fetchGlobalStudioApi } from './api.ts'
import { parseHostModelCatalog, type HostModelCatalogDto } from './dto.ts'
import type { StudioPanelKey } from './locales.ts'
import { showReleaseAnnouncementModal } from './ReleaseAnnouncement.ts'
import css from './OpenWriteSettings.module.css'

/** The host's default-model selection, as the host's own route reports it. */
export interface HostModelSelection {
  available: boolean
  provider: string
  model: string
  reasoningEffort: string
}

/** The writing environment's lifecycle, as the host's runtime route reports it. */
export interface RuntimeStatus {
  phase: string
  message: string
  error?: string
  downloadedBytes?: number
  totalBytes?: number
}

/** The Studio backend the bridge talks to. */
export interface StudioBackend {
  studioUrl: string
  managed: boolean
  available?: boolean
}

/** The groups of this page, in the order they are shown. */
export type OpenWriteSettingsTab = 'environment' | 'models' | 'search' | 'host'

const TABS: readonly OpenWriteSettingsTab[] = ['environment', 'models', 'search', 'host'] as const

/** The tab labels, as dictionary keys. */
const TAB_KEYS: Readonly<Record<OpenWriteSettingsTab, StudioPanelKey>> = {
  environment: 'settings.tab.environment',
  models: 'settings.tab.models',
  search: 'settings.tab.search',
  host: 'settings.tab.host',
}

/** Where the chosen tab is remembered between dialog reopens. */
const TAB_STORAGE_KEY = 'openwrite.settings.tab'

/**
 * Read the remembered tab.
 *
 * localStorage can throw (a locked-down browser profile, a private window
 * with storage disabled), and the host may run this page outside a window at
 * all — a missing or unreadable store must never break the settings page.
 */
function readStoredTab(): OpenWriteSettingsTab {
  try {
    const stored = window.localStorage.getItem(TAB_STORAGE_KEY)
    return TABS.find(tab => tab === stored) ?? 'environment'
  } catch {
    return 'environment'
  }
}

/** Remember the chosen tab, best effort. */
function storeTab(tab: OpenWriteSettingsTab): void {
  try {
    window.localStorage.setItem(TAB_STORAGE_KEY, tab)
  } catch {
    // A tab that cannot be remembered is still a working tab.
  }
}

/** Read a JSON route, answering null when it is missing or unreadable. */
async function readJson<T>(url: string, signal?: AbortSignal): Promise<T | null> {
  let response: Response
  try {
    response = await fetch(url, signal === undefined ? undefined : { signal, credentials: 'same-origin' })
  } catch (cause) {
    if (signal?.aborted === true) return null
    throw cause
  }
  if (!response.ok) return null
  try { return await response.json() as T } catch { return null }
}

/** The host's default model selection. Null when the route is unreachable. */
export async function fetchHostModel(signal?: AbortSignal): Promise<HostModelSelection | null> {
  return await readJson<HostModelSelection>('/studio-panel/host-model', signal)
}

/**
 * The host's own model directory.
 *
 * The host owns the adapters — its own providers and the ones other plugins
 * register into the same registry — so this is what dsh itself can call. The
 * list is read through the backend's machine channel; the browser never sees
 * the relay's token.
 */
export async function fetchHostModelCatalog(signal?: AbortSignal): Promise<HostModelCatalogDto | null> {
  try {
    return parseHostModelCatalog(await fetchGlobalStudioApi('/model/host-models', signal))
  } catch (cause) {
    // The reason has to survive the trip: a list that is empty with no words
    // is what made a broken host model channel look like a host that owns no
    // models at all.
    return {
      available: false,
      models: [],
      error: cause instanceof Error ? cause.message : String(cause),
    }
  }
}

/** The writing environment's status. Null when the route is unreachable. */
export async function fetchRuntimeStatus(signal?: AbortSignal): Promise<RuntimeStatus | null> {
  return await readJson<RuntimeStatus>('/studio-panel/runtime', signal)
}

/** The Studio backend address. Null when the route is unreachable. */
export async function fetchStudioBackend(signal?: AbortSignal): Promise<StudioBackend | null> {
  return await readJson<StudioBackend>('/studio-panel/config.json', signal)
}

/**
 * Ask the host to act on the writing environment.
 *
 * `prepare` and `retry` reach the same server-side action; the caller picks
 * the word that matches the phase it is looking at. `cancel` stops a run that
 * is already under way.
 */
export async function postRuntimeAction(action: 'prepare' | 'retry' | 'cancel'): Promise<RuntimeStatus | null> {
  const response = await fetch('/studio-panel/runtime', {
    method: 'POST',
    headers: { 'content-type': 'application/json', 'x-openwrite-studio': '1' },
    body: JSON.stringify({ action }),
    credentials: 'same-origin',
  })
  if (!response.ok) return null
  try { return await response.json() as RuntimeStatus } catch { return null }
}

/** Runtime phases mapped to the dictionary key that explains them. */
const PHASE_KEYS: Readonly<Record<string, StudioPanelKey>> = {
  idle: 'settings.phase.idle',
  waiting: 'settings.phase.busy',
  downloading: 'settings.phase.busy',
  installing: 'settings.phase.busy',
  starting: 'settings.phase.busy',
  recovering: 'settings.phase.busy',
  ready: 'settings.phase.ready',
  error: 'settings.phase.error',
  cancelled: 'settings.phase.cancelled',
  stopped: 'settings.phase.stopped',
  uninstalled: 'settings.phase.uninstalled',
}

/** Phases in which the environment is still working on something. */
const BUSY_PHASES = new Set(['waiting', 'downloading', 'installing', 'starting', 'recovering'])

/** Phases where runtime preparation is no longer advancing in the background. */
const TERMINAL_PHASES = new Set(['ready', 'error', 'cancelled', 'stopped', 'uninstalled'])

/** How many times an unreadable status is re-read before the page gives up. */
const READ_RETRIES = 4
/** The pause between two status reads. */
const READ_RETRY_MS = 2_000

/** The upstream open-source repository for stars and issue reports. */
export const GITHUB_REPO_URL = 'https://github.com/LiPu-jpg/Openwrite'

/**
 * Strip user-identifying home paths and accidental credentials from a
 * diagnostic string before showing it in the copyable bug-report block or
 * pre-filling a GitHub issue URL.
 */
export function sanitizeDiagnosticText(input: string): string {
  return input
    .replace(/\/Users\/[^/\s"':;]+/g, '<HOME>')
    .replace(/\/home\/[^/\s"':;]+/g, '<HOME>')
    .replace(/[A-Za-z]:\\Users\\[^\\\s"':;]+/g, '<HOME>')
    .replace(/Bearer\s+[A-Za-z0-9._~+/-]+=*/gi, 'Bearer <REDACTED>')
    .replace(/\bsk-[A-Za-z0-9_-]{8,}\b/g, '<REDACTED_KEY>')
}

/**
 * Build a privacy-safe diagnostic summary containing only environment, host,
 * and companion metadata — never novel manuscripts, outlines, character/world
 * assets, workspace paths, or API keys.
 */
export function formatDiagnosticReport(
  runtime: RuntimeStatus | null,
  backend: StudioBackend | null,
  hostModel: HostModelSelection | null,
  companions: CompanionStatus | null,
): string {
  const companionLine = (name: string, entry: CompanionStatus['dog'] | undefined): string => {
    if (entry === undefined) return `${name}: unknown`
    if (!entry.installed) return `${name}: not-installed`
    const ver = entry.version !== null && entry.version !== '' ? `@${entry.version}` : ''
    return `${name}${ver}: ${entry.usable ? 'usable' : `incompatible (${sanitizeDiagnosticText(entry.reason ?? 'unknown')})`}`
  }
  const lines = [
    `host_dsh: ${companions?.host ?? 'unknown'}`,
    `runtime_phase: ${runtime?.phase ?? 'unavailable'}`,
    `backend_mode: ${backend === null ? 'unavailable' : backend.managed ? 'managed' : 'external'}`,
    `backend_available: ${backend?.available === undefined ? 'unknown' : String(backend.available)}`,
    `host_model: ${hostModel === null ? 'unavailable' : hostModel.available ? `${hostModel.provider}/${hostModel.model}` : 'none'}`,
    `companions: ${[
      companionLine('dsh-dog', companions?.dog),
      companionLine('dsh-ops', companions?.ops),
      companionLine('dsh-our-free-model', companions?.freeModel),
    ].join(', ')}`,
  ]
  if (runtime?.message !== undefined && runtime.message !== '') {
    lines.push(`runtime_message: ${sanitizeDiagnosticText(runtime.message)}`)
  }
  if (runtime?.error !== undefined && runtime.error !== '') {
    lines.push(`runtime_error: ${sanitizeDiagnosticText(runtime.error)}`)
  }
  return lines.join('\n')
}

/** Pre-fill a GitHub issue URL with the sanitized diagnostic summary. */
export function buildGitHubIssueUrl(diagnosticReport: string): string {
  const body = [
    '## 问题描述 / What happened',
    '（请简述遇到的问题或复现步骤，无需粘贴任何小说正文、大纲或人物设定）',
    '',
    '## 脱敏环境诊断 / Sanitized Diagnostics',
    '```text',
    diagnosticReport,
    '```',
  ].join('\n')
  return `${GITHUB_REPO_URL}/issues/new?body=${encodeURIComponent(body)}`
}

export function OpenWriteSettings({ t }: PropsLocale<'studio-panel'>): JSX.Element {
  const [tab, setTab] = useState<OpenWriteSettingsTab>(readStoredTab)
  const [runtime, setRuntime] = useState<RuntimeStatus | null>(null)
  const [backend, setBackend] = useState<StudioBackend | null>(null)
  const [hostModel, setHostModel] = useState<HostModelSelection | null>(null)
  const [hostCatalog, setHostCatalog] = useState<HostModelCatalogDto | null>(null)
  const [companions, setCompanions] = useState<CompanionStatus | null>(null)
  const [busy, setBusy] = useState(false)
  const [notice, setNotice] = useState('')
  const [copied, setCopied] = useState(false)
  const [copiedFeedbackCmd, setCopiedFeedbackCmd] = useState(false)
  const [attempt, setAttempt] = useState(0)
  const [preparePending, setPreparePending] = useState(false)
  const [readyEpoch, setReadyEpoch] = useState(0)
  const prevPhaseRef = useRef<string | undefined>(undefined)

  /**
   * Read the four statuses this page shows.
   *
   * Answers `false` when at least one of them could not be read: the host may
   * still be starting its writing environment, and a status page that gave up
   * on the first miss would keep saying "unreadable" long after the answer
   * became available.
   */
  const load = useCallback(async (signal?: AbortSignal): Promise<boolean> => {
    const [runtimeResult, backendResult, hostModelResult, companionResult] = await Promise.all([
      fetchRuntimeStatus(signal).catch(() => null).then(res => { if (signal?.aborted !== true) setRuntime(res); return res }),
      fetchStudioBackend(signal).catch(() => null).then(res => { if (signal?.aborted !== true) setBackend(res); return res }),
      fetchHostModel(signal).catch(() => null).then(res => { if (signal?.aborted !== true) setHostModel(res); return res }),
      fetchCompanions(signal).catch(() => null).then(res => { if (signal?.aborted !== true) setCompanions(res); return res }),
      fetchHostModelCatalog(signal).catch(() => null).then(res => { if (signal?.aborted !== true) setHostCatalog(res); return res }),
    ])
    if (signal?.aborted === true) return true
    return runtimeResult !== null && backendResult !== null && hostModelResult !== null && companionResult !== null
  }, [])

  useEffect(() => {
    const controller = new AbortController()
    let timer: ReturnType<typeof setTimeout> | undefined
    void load(controller.signal).then(complete => {
      if (complete || controller.signal.aborted) return
      if (attempt >= READ_RETRIES) return
      timer = setTimeout(() => setAttempt(value => value + 1), READ_RETRY_MS)
    })
    return () => { controller.abort(); if (timer !== undefined) clearTimeout(timer) }
  }, [load, attempt])

  // Detect when runtime transitions to ready so sibling tabs (Models / Search)
  // refresh automatically without forcing the user to close and reopen Settings.
  useEffect(() => {
    const phase = runtime?.phase
    if (phase === undefined) return
    if (TERMINAL_PHASES.has(phase)) setPreparePending(false)
    if (phase === 'ready' && prevPhaseRef.current !== undefined && prevPhaseRef.current !== 'ready') {
      setReadyEpoch(value => value + 1)
    }
    prevPhaseRef.current = phase
  }, [runtime?.phase])

  // The environment reports its progress through the runtime route. While it
  // is working — or right after the author clicked prepare/retry before the
  // bridge switches out of idle — poll it so the dialog turns ready live.
  useEffect(() => {
    if (runtime === null || (!BUSY_PHASES.has(runtime.phase) && !preparePending)) return
    const controller = new AbortController()
    const timer = window.setInterval(() => {
      void fetchRuntimeStatus(controller.signal).then(next => {
        if (controller.signal.aborted || next === null) return
        setRuntime(next)
      }).catch(() => undefined)
    }, 1_000)
    return () => { controller.abort(); window.clearInterval(timer) }
  }, [runtime, preparePending])

  const act = async (action: 'prepare' | 'retry' | 'cancel') => {
    setBusy(true)
    setNotice('')
    try {
      const next = await postRuntimeAction(action)
      setRuntime(next)
      if (action === 'cancel' || (next !== null && TERMINAL_PHASES.has(next.phase))) {
        setPreparePending(false)
      } else if (next !== null) {
        setPreparePending(true)
      }
      setNotice(next === null ? t('settings.section.unavailable') : '')
    } catch (cause) {
      setPreparePending(false)
      setNotice(cause instanceof Error ? cause.message : String(cause))
    } finally {
      setBusy(false)
    }
  }

  const selectTab = (next: OpenWriteSettingsTab) => {
    if (next === tab) return
    setTab(next)
    storeTab(next)
  }

  const phaseKey = runtime === null ? undefined : PHASE_KEYS[runtime.phase]
  const phaseLabel = runtime === null ? '' : phaseKey === undefined ? runtime.phase : t(phaseKey)
  const ready = runtime?.phase === 'ready'
  const idle = runtime?.phase === 'idle'
  const preparing = runtime !== null && BUSY_PHASES.has(runtime.phase)
  const diagnosticReport = formatDiagnosticReport(runtime, backend, hostModel, companions)
  const issueUrl = buildGitHubIssueUrl(diagnosticReport)

  const copyDiagnostics = async () => {
    try {
      await navigator.clipboard?.writeText(diagnosticReport)
    } catch {
      // Clipboard write is best-effort in restricted webviews; still confirm selection/intent.
    }
    setCopied(true)
  }

  const copyFeedbackCommand = async () => {
    try {
      await navigator.clipboard?.writeText('/feedback 请帮我排查刚才遇到的错误，并在彻底剥离小说正文、角色设定、本机路径与密钥后，生成一份可直接提交到 GitHub Issues 的脱敏报告。')
    } catch {
      // Clipboard write is best-effort in restricted webviews.
    }
    setCopiedFeedbackCmd(true)
  }

  return <section className={css.page}>
    <header className={css.header}>
      <h2>{t('settings.section.label')}</h2>
      <p>{t('settings.section.intro')}</p>
    </header>

    <div className={css.tabs} role="tablist" aria-label={t('settings.section.label')}>
      {TABS.map(id => <button
        key={id}
        type="button"
        role="tab"
        id={`openwrite-settings-tab-${id}`}
        aria-selected={tab === id}
        aria-controls={`openwrite-settings-panel-${id}`}
        data-active={tab === id}
        onClick={() => selectTab(id)}
      >{t(TAB_KEYS[id])}</button>)}
    </div>

    <div
      role="tabpanel"
      id="openwrite-settings-panel-environment"
      aria-labelledby="openwrite-settings-tab-environment"
      hidden={tab !== 'environment'}
      className={css.panel}
    >
      <div className={css.block}>
        <h3>{t('settings.section.runtime')}</h3>
        {runtime === null
          ? <p>{t('settings.section.unavailable')}</p>
          : <>
            <p>{phaseLabel}</p>
            <p className={css.hint}>{runtime.message}</p>
            {runtime.error !== undefined && runtime.error !== '' && <p className={css.error}>{runtime.error}</p>}
            {preparing && runtime.totalBytes !== undefined && runtime.totalBytes > 0 && (
              <progress value={runtime.downloadedBytes ?? 0} max={runtime.totalBytes} aria-label={t('settings.section.runtime')} />
            )}
            <div className={css.actions}>
              {!ready && <button type="button" disabled={busy} onClick={() => void act(idle ? 'prepare' : 'retry')}>
                {busy ? t('settings.section.working') : idle ? t('settings.section.prepare') : t('settings.section.retry')}
              </button>}
              {preparing && <button type="button" disabled={busy} onClick={() => void act('cancel')}>
                {t('settings.section.cancel')}
              </button>}
            </div>
          </>}
      </div>

      <div className={css.block}>
        <h3>{t('settings.section.backend')}</h3>
        {backend === null
          ? <p>{t('settings.section.unavailable')}</p>
          : <>
            <p>{backend.managed ? t('settings.section.backendManaged') : t('settings.section.backendExternal')}</p>
            <code>{backend.studioUrl}</code>
            {backend.available === false && <p className={css.error}>{t('settings.section.backendDown')}</p>}
          </>}
      </div>

      <details className={css.block} open={runtime?.phase === 'error'}>
        <summary>{t('settings.section.diagnostics')}</summary>
        <p>{t('settings.section.phaseLabel')}：{runtime?.phase ?? t('settings.section.unavailable')}</p>
        {runtime?.error !== undefined && runtime.error !== '' && <pre className={css.error}>{sanitizeDiagnosticText(runtime.error)}</pre>}
        <p className={css.hint}>{t('settings.diagnostics.privacy')}</p>
        <pre data-testid="openwrite-diagnostic-summary">{diagnosticReport}</pre>
        <div className={css.actions}>
          <button type="button" onClick={() => void copyDiagnostics()}>
            {copied ? t('settings.diagnostics.copied') : t('settings.diagnostics.copy')}
          </button>
          <a
            className={css.linkButton}
            href={issueUrl}
            target="_blank"
            rel="noreferrer"
          >{t('settings.diagnostics.reportIssue')}</a>
        </div>
        <p className={css.hint}>{t('settings.section.diagnosticsHint')}</p>
      </details>

      <div className={css.supportCard}>
        <div className={css.supportHeader}>
          <h3>{t('settings.support.title')}</h3>
          <span className={css.pill}>GitHub</span>
        </div>
        <p className={css.hint}>{t('settings.support.body')}</p>
        <div className={css.actions}>
          <a
            className={css.starButton}
            href={GITHUB_REPO_URL}
            target="_blank"
            rel="noreferrer"
          >{t('settings.support.star')}</a>
          <button
            type="button"
            className={css.linkButton}
            onClick={() => void copyFeedbackCommand()}
          >{copiedFeedbackCmd ? t('settings.support.copiedFeedbackCmd') : t('settings.support.copyFeedbackCmd')}</button>
          <a
            className={css.linkButton}
            href={issueUrl}
            target="_blank"
            rel="noreferrer"
          >{t('settings.support.feedback')}</a>
          <button
            type="button"
            className={css.linkButton}
            onClick={() => showReleaseAnnouncementModal({ t, issueUrl })}
          >{t('settings.support.releaseNotes')}</button>
        </div>
      </div>
    </div>

    <div
      role="tabpanel"
      id="openwrite-settings-panel-models"
      aria-labelledby="openwrite-settings-tab-models"
      hidden={tab !== 'models'}
      className={css.panel}
    >
      <p className={css.hint}>{t('settings.tab.modelsHint')}</p>
      <ModelView t={t} refreshNonce={readyEpoch} />
    </div>

    <div
      role="tabpanel"
      id="openwrite-settings-panel-search"
      aria-labelledby="openwrite-settings-tab-search"
      hidden={tab !== 'search'}
      className={css.panel}
    >
      <SearchSettings t={t} refreshNonce={readyEpoch} />
    </div>

    <div
      role="tabpanel"
      id="openwrite-settings-panel-host"
      aria-labelledby="openwrite-settings-tab-host"
      hidden={tab !== 'host'}
      className={css.panel}
    >
      <div className={css.block}>
        <h3>{t('settings.section.hostModel')}</h3>
        {hostModel === null
          ? <p>{t('settings.section.unavailable')}</p>
          : hostModel.available !== true
            ? <p>{t('settings.section.hostModelNone')}</p>
            : <p><code>{hostModel.model}</code>{` · ${hostModel.provider}`}{hostModel.reasoningEffort !== '' ? ` · ${hostModel.reasoningEffort}` : ''}</p>}
        <p className={css.hint}>{t('settings.section.hostModelHint')}</p>
      </div>

      <div className={css.block}>
        <h3>{t('settings.section.hostModels')}</h3>
        {hostCatalog === null
          ? <p>{t('settings.section.unavailable')}</p>
          : !hostCatalog.available
            ? (
              <>
                {/* The reason first: "the host owns no models" and "the host
                    could not be read" are different faults, and only the second
                    one is worth acting on. */}
                <p>{hostCatalog.error !== '' ? hostCatalog.error : t('settings.section.hostModelsUnavailable')}</p>
                {hostCatalog.error !== '' && (
                  <p className={css.hint}>{t('settings.section.hostModelsUnavailable')}</p>
                )}
              </>
            )
            : hostCatalog.models.length === 0
              ? <p>{t('settings.section.hostModelsEmpty')}</p>
              : <ul className={css.modelHostList}>
                {hostCatalog.models.map((model) => (
                  <li key={model.id} className={css.modelHostItem}>
                    <span>
                      <strong>{model.label}</strong>
                      <small>{model.id}</small>
                    </span>
                  </li>
                ))}
              </ul>}
        <p className={css.hint}>{t('settings.section.hostModelsHint')}</p>
      </div>

      <div className={css.block}>
        <CompanionSection status={companions} />
      </div>
    </div>

    {notice !== '' && <p role="status" className={css.notice}>{notice}</p>}
  </section>
}
