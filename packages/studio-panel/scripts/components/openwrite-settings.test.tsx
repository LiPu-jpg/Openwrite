import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it, vi } from 'vitest'
import {
  analyzeFeedbackHealth,
  OpenWriteSettings,
  sanitizeDiagnosticText,
  validateFeedbackDraft,
} from '../../src/client/OpenWriteSettings.tsx'
import { dispatchFeedbackToHostAgent } from '../../src/client/feedback-agent.ts'
import {
  hasSeenReleaseAnnouncement,
  maybeShowReleaseAnnouncement,
  RELEASE_MODAL_MARKER,
  SEEN_RELEASE_VERSION_KEY,
} from '../../src/client/ReleaseAnnouncement.ts'
import { zh } from '../../src/client/locales.ts'

/**
 * The real Chinese copy, so the assertions read like the page does instead of
 * echoing key names back at the reader.
 */
const t = (key: string): string => (zh as Record<string, string>)[key] ?? key

/** Serve each route by its path suffix; an unserved URL fails the test. */
function stubRoutes(routes: Record<string, unknown>, hostModels?: () => Response): void {
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input)
    if (url.includes('/studio-panel/api/model/profiles')) {
      return new Response(JSON.stringify({ ok: true, data: { profiles: [], embedding_profiles: [], active_embedding_profile_id: '', routes: {} } }), { status: 200, headers: { 'content-type': 'application/json' } })
    }
    if (url.includes('/studio-panel/api/model/host-models')) {
      if (hostModels !== undefined) return hostModels()
      return new Response(JSON.stringify({ ok: true, data: { available: true, providers: [], models: [{ id: 'deepseek-official/deepseek-flash', provider: 'deepseek-official', model: 'deepseek-flash', label: 'DeepSeek Flash', description: '', context_tokens: 131072 }], error: '' } }), { status: 200, headers: { 'content-type': 'application/json' } })
    }
    const key = Object.keys(routes).find(candidate => url.endsWith(candidate))
    if (key === undefined) throw new Error(`unexpected fetch ${url}`)
    return new Response(JSON.stringify(routes[key]), { status: 200, headers: { 'content-type': 'application/json' } })
  }))
}

const companions = {
  host: '0.2.1-rc.5',
  dog: { installed: true, usable: true, version: '1.4.0', reason: null },
  ops: { installed: true, usable: false, version: '0.5.0', reason: 'peer range excludes this host' },
  freeModel: { installed: false, usable: false, version: null, reason: null },
}

const routes = {
  '/studio-panel/host-model': { available: true, provider: 'deepseek-official', model: 'deepseek-flash', reasoningEffort: 'max' },
  '/studio-panel/runtime': { phase: 'ready', message: 'The writing environment is ready' },
  '/studio-panel/config.json': { studioUrl: 'http://127.0.0.1:4567', managed: true },
  '/studio-panel/companions': companions,
  '/studio-panel/api/research/preferences': {
    schema_version: 'openwrite.research-preferences.v1',
    settings: {
      search_provider: 'dsh',
      search_providers: [
        { id: 'dsh', label: 'DSH web_search / web_fetch', requires_api_key: false, configured: true, credential_configured: false },
        { id: 'bocha', label: '博查', requires_api_key: true, configured: false, credential_configured: false },
      ],
    },
    host_web_available: true,
  },
}

describe('OpenWriteSettings', () => {
  it('groups the page into environment, model and host', async () => {
    stubRoutes(routes)
    render(<OpenWriteSettings t={t} />)
    expect(screen.getByRole('tab', { name: '环境' })).toBeTruthy()
    expect(screen.getByRole('tab', { name: '模型' })).toBeTruthy()
    expect(screen.getByRole('tab', { name: '宿主' })).toBeTruthy()
    // The environment group is the one an author opens first.
    expect(screen.getByRole('tab', { name: '环境' }).getAttribute('aria-selected')).toBe('true')
  })

  it('shows the host model, the runtime phase and the companion inventory', async () => {
    stubRoutes(routes)
    render(<OpenWriteSettings t={t} />)

    expect(await screen.findByText('deepseek-flash')).toBeTruthy()
    expect(screen.getByText(/deepseek-official · max/)).toBeTruthy()
    expect(within(document.getElementById('openwrite-settings-panel-environment')!).getByText(/已就绪/)).toBeTruthy()
    expect(screen.getByText('http://127.0.0.1:4567')).toBeTruthy()
    expect(screen.getByText(/dsh-dog：已安装且宿主放行/)).toBeTruthy()
    // A companion the host would reject must not read as available.
    expect(screen.getByText(/dsh-ops：已安装.*但当前宿主不兼容/)).toBeTruthy()
    expect(screen.getByText(/dsh-our-free-model：未安装/)).toBeTruthy()
    // A ready environment needs no repair action.
    expect(screen.queryByRole('button', { name: /准备写作环境/ })).toBeNull()
  })

  it('lists the models the host itself can reach', async () => {
    stubRoutes(routes)
    render(<OpenWriteSettings t={t} />)
    fireEvent.click(screen.getByRole('tab', { name: '宿主' }))
    const host = within(document.getElementById('openwrite-settings-panel-host')!)
    expect(await host.findByText('DeepSeek Flash')).toBeTruthy()
    expect(host.getByText('deepseek-official/deepseek-flash')).toBeTruthy()
  })

  it('says why the host model list could not be read', async () => {
    // A host model channel that cannot be read must say so. A list that is
    // simply empty reads as "the host owns no models", and the author is left
    // looking for a model that is really there.
    stubRoutes(routes, () => new Response(
      JSON.stringify({ ok: false, error: { message: '宿主模型目录读取失败: timed out' } }),
      { status: 502, headers: { 'content-type': 'application/json' } },
    ))
    render(<OpenWriteSettings t={t} />)
    fireEvent.click(screen.getByRole('tab', { name: '宿主' }))
    const host = within(document.getElementById('openwrite-settings-panel-host')!)
    expect(await host.findByText(/宿主模型目录读取失败/)).toBeTruthy()
    // The actionable advice stays: the reason says what failed, the hint says
    // what to do about it.
    expect(host.getByText(t('settings.section.hostModelsUnavailable'))).toBeTruthy()
  })

  it('configures the global search default in the search group', async () => {
    const base = routes['/studio-panel/api/research/preferences']
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      if (url.includes('/studio-panel/api/model/profiles')) return new Response(JSON.stringify({ data: { profiles: [], routes: {} } }), { status: 200, headers: { 'content-type': 'application/json' } })
      if (url.includes('/studio-panel/api/model/host-models')) return new Response(JSON.stringify({ data: { available: false, models: [] } }), { status: 200, headers: { 'content-type': 'application/json' } })
      if (url.endsWith('/studio-panel/api/research/preferences')) {
        if (init?.method === 'POST') {
          const body = JSON.parse(String(init.body)) as { search_provider?: string }
          return new Response(
            JSON.stringify({
              ...base,
              settings: {
                ...base.settings,
                search_provider: body.search_provider ?? base.settings.search_provider,
              },
            }),
            { status: 200, headers: { 'content-type': 'application/json' } }
          )
        }
        return new Response(JSON.stringify(base), { status: 200, headers: { 'content-type': 'application/json' } })
      }
      const key = Object.keys(routes).find(candidate => url.endsWith(candidate))
      if (key === undefined) throw new Error(`unexpected fetch ${url}`)
      return new Response(JSON.stringify(routes[key]), { status: 200, headers: { 'content-type': 'application/json' } })
    })
    vi.stubGlobal('fetch', fetchMock)
    render(<OpenWriteSettings t={t} />)

    fireEvent.click(screen.getByRole('tab', { name: '搜索' }))
    expect(await screen.findByText(/这里的默认值用于新作品/)).toBeTruthy()
    fireEvent.click(screen.getByRole('radio', { name: /博查/ }))
    fireEvent.click(screen.getByRole('button', { name: '保存搜索设置' }))
    await waitFor(() => expect(screen.getByText('搜索设置已保存')).toBeTruthy())
    expect((screen.getByRole('radio', { name: /博查/ }) as HTMLInputElement).checked).toBe(true)
    expect(screen.getByText('当前默认：博查')).toBeTruthy()
    const call = fetchMock.mock.calls.find(([input, init]) => String(input).includes('/research/preferences') && (init as RequestInit | undefined)?.method === 'POST')
    expect(JSON.parse(String((call?.[1] as RequestInit).body))).toMatchObject({ search_provider: 'bocha' })
  })

  it('reports an error instead of saved notice when backend keeps a different provider', async () => {
    const base = routes['/studio-panel/api/research/preferences']
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      if (url.includes('/studio-panel/api/model/profiles')) return new Response(JSON.stringify({ data: { profiles: [], routes: {} } }), { status: 200, headers: { 'content-type': 'application/json' } })
      if (url.includes('/studio-panel/api/model/host-models')) return new Response(JSON.stringify({ data: { available: false, models: [] } }), { status: 200, headers: { 'content-type': 'application/json' } })
      if (url.endsWith('/studio-panel/api/research/preferences')) {
        return new Response(
          JSON.stringify({
            ...base,
            settings: {
              ...base.settings,
              search_provider: init?.method === 'POST' ? 'dsh' : base.settings.search_provider,
            },
          }),
          { status: 200, headers: { 'content-type': 'application/json' } }
        )
      }
      const key = Object.keys(routes).find(candidate => url.endsWith(candidate))
      if (key === undefined) throw new Error(`unexpected fetch ${url}`)
      return new Response(JSON.stringify(routes[key]), { status: 200, headers: { 'content-type': 'application/json' } })
    })
    vi.stubGlobal('fetch', fetchMock)
    render(<OpenWriteSettings t={t} />)

    fireEvent.click(screen.getByRole('tab', { name: '搜索' }))
    expect(await screen.findByText(/这里的默认值用于新作品/)).toBeTruthy()
    fireEvent.click(screen.getByRole('radio', { name: /博查/ }))
    fireEvent.click(screen.getByRole('button', { name: '保存搜索设置' }))
    await waitFor(() => expect(screen.getByText(/未能保留选择|保存失败|当前默认/)).toBeTruthy())
    expect(screen.queryByText('搜索设置已保存')).toBeNull()
  })

  it('shows saved API key placeholder when credential_configured is true', async () => {
    const base = routes['/studio-panel/api/research/preferences']
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input)
      if (url.includes('/studio-panel/api/model/profiles')) return new Response(JSON.stringify({ data: { profiles: [], routes: {} } }), { status: 200, headers: { 'content-type': 'application/json' } })
      if (url.includes('/studio-panel/api/model/host-models')) return new Response(JSON.stringify({ data: { available: false, models: [] } }), { status: 200, headers: { 'content-type': 'application/json' } })
      if (url.endsWith('/studio-panel/api/research/preferences')) {
        return new Response(
          JSON.stringify({
            ...base,
            settings: {
              ...base.settings,
              search_provider: 'bocha',
              search_providers: base.settings.search_providers.map(provider =>
                provider.id === 'bocha' ? { ...provider, configured: true, credential_configured: true } : provider
              ),
            },
          }),
          { status: 200, headers: { 'content-type': 'application/json' } }
        )
      }
      const key = Object.keys(routes).find(candidate => url.endsWith(candidate))
      if (key === undefined) throw new Error(`unexpected fetch ${url}`)
      return new Response(JSON.stringify(routes[key]), { status: 200, headers: { 'content-type': 'application/json' } })
    })
    vi.stubGlobal('fetch', fetchMock)
    render(<OpenWriteSettings t={t} />)

    fireEvent.click(screen.getByRole('tab', { name: '搜索' }))
    expect(await screen.findByPlaceholderText('已保存 API Key，留空则保持不变')).toBeTruthy()
  })

  it('hosts the model profile library in the model group', async () => {
    stubRoutes(routes)
    render(<OpenWriteSettings t={t} />)
    fireEvent.click(screen.getByRole('tab', { name: '模型' }))
    await screen.findByLabelText('档案名')
    // The library is global, so the page says so.
    expect(screen.getByText(/模型档案是全局的/)).toBeTruthy()
  })

  it('says the host has no default model instead of naming an empty one', async () => {
    stubRoutes({
      '/studio-panel/host-model': { available: false, provider: '', model: '', reasoningEffort: '' },
      '/studio-panel/runtime': { phase: 'ready', message: 'ready' },
      '/studio-panel/config.json': { studioUrl: 'http://127.0.0.1:4567', managed: true },
      '/studio-panel/companions': companions,
    })
    render(<OpenWriteSettings t={t} />)
    expect(await screen.findByText('宿主还没有配置默认模型。')).toBeTruthy()
  })

  it('prepares the writing environment on request and shows the new phase', async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      if (url.endsWith('/studio-panel/runtime') && init?.method === 'POST') {
        return new Response(JSON.stringify({ phase: 'downloading', message: 'Downloading the writing environment' }), { status: 202, headers: { 'content-type': 'application/json' } })
      }
      if (url.includes('/studio-panel/api/model/profiles')) return new Response(JSON.stringify({ ok: true, data: { profiles: [], embedding_profiles: [], active_embedding_profile_id: '', routes: {} } }), { status: 200, headers: { 'content-type': 'application/json' } })
      if (url.endsWith('/studio-panel/host-model')) return new Response(JSON.stringify({ available: true, provider: 'p', model: 'm', reasoningEffort: '' }), { status: 200, headers: { 'content-type': 'application/json' } })
      if (url.endsWith('/studio-panel/runtime')) return new Response(JSON.stringify({ phase: 'idle', message: 'not prepared yet' }), { status: 200, headers: { 'content-type': 'application/json' } })
      if (url.endsWith('/studio-panel/config.json')) return new Response(JSON.stringify({ studioUrl: 'http://127.0.0.1:4567', managed: true }), { status: 200, headers: { 'content-type': 'application/json' } })
      if (url.endsWith('/studio-panel/companions')) return new Response(JSON.stringify(companions), { status: 200, headers: { 'content-type': 'application/json' } })
      throw new Error(`unexpected fetch ${url}`)
    })
    vi.stubGlobal('fetch', fetchMock)
    render(<OpenWriteSettings t={t} />)

    const button = await screen.findByRole('button', { name: '准备写作环境' })
    fireEvent.click(button)
    await waitFor(() => expect(screen.getByText(/准备中/)).toBeTruthy())
    const call = fetchMock.mock.calls.find(([, init]) => (init as RequestInit | undefined)?.method === 'POST')
    expect(JSON.parse(String((call?.[1] as RequestInit).body))).toEqual({ action: 'prepare' })
  })

  it('reports every status block as unreadable when the routes are unreachable', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response('nope', { status: 503 })))
    render(<OpenWriteSettings t={t} />)
    // One block per fact the page reads: runtime, backend, host model,
    // host model directory, companions.
    await waitFor(() => expect(screen.getAllByText('暂时读不到这项状态。').length).toBe(4))
  })

  it('re-reads a status that could not be read the first time', async () => {
    // The host may still be bringing its writing environment up when the
    // dialog opens. A status page that gave up on the first miss would keep
    // saying "unreadable" long after the answer became available.
    let runtimeReads = 0
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input)
      if (url.includes('/studio-panel/api/model/profiles')) return new Response(JSON.stringify({ ok: true, data: { profiles: [], embedding_profiles: [], active_embedding_profile_id: '', routes: {} } }), { status: 200, headers: { 'content-type': 'application/json' } })
      if (url.endsWith('/studio-panel/runtime')) {
        runtimeReads += 1
        if (runtimeReads === 1) return new Response('nope', { status: 503 })
        return new Response(JSON.stringify({ phase: 'ready', message: 'ready now' }), { status: 200, headers: { 'content-type': 'application/json' } })
      }
      const key = Object.keys(routes).find(candidate => url.endsWith(candidate))
      if (key === undefined) throw new Error(`unexpected fetch ${url}`)
      return new Response(JSON.stringify(routes[key]), { status: 200, headers: { 'content-type': 'application/json' } })
    }))
    render(<OpenWriteSettings t={t} />)
    await waitFor(() => expect(screen.getByText('ready now')).toBeTruthy(), { timeout: 8_000 })
    expect(runtimeReads).toBeGreaterThan(1)
  })

  it('is registered as the host settings section', () => {
    // The section lives in the host's settings dialog, which the pinned 0.1
    // build SDK cannot type. Pin the registration in the source so a rename
    // cannot silently drop the page from the dialog.
    const source = readFileSync(resolve(process.cwd(), 'src/client/index.ts'), 'utf-8')
    expect(source).toContain("name: 'settings.section'")
    expect(source).toContain("id: 'openwrite'")
    expect(source).toContain('OpenWriteSettings')
  })

  it('renders the open-source support card and privacy-safe diagnostics with path/token redaction', async () => {
    const writeText = vi.fn(async () => undefined)
    Object.assign(navigator, { clipboard: { writeText } })

    stubRoutes({
      ...routes,
      '/studio-panel/runtime': {
        phase: 'error',
        message: 'Failed in /Users/authorname/Novels/SecretBook',
        error: 'EACCES at C:\\Users\\authorname\\Novels\\SecretBook with key sk-1234567890abcdef and Bearer secret_token_xyz',
      },
    })
    render(<OpenWriteSettings t={t} />)

    const summary = await screen.findByTestId('openwrite-diagnostic-summary')
    await waitFor(() => expect(summary.textContent).toContain('host_dsh: 0.2.1-rc.5'))
    expect(summary.textContent).toContain('runtime_phase: error')
    expect(summary.textContent).toContain('backend_mode: managed')
    expect(summary.textContent).not.toContain('authorname')
    expect(summary.textContent).not.toContain('sk-1234567890abcdef')
    expect(summary.textContent).not.toContain('secret_token_xyz')
    expect(summary.textContent).toContain('<HOME>/Novels/SecretBook')
    expect(summary.textContent).toContain('<REDACTED_KEY>')
    expect(summary.textContent).toContain('Bearer <REDACTED>')

    const starLink = screen.getByRole('link', { name: '★ 去 GitHub 点 Star 支持 OpenWrite' })
    expect(starLink.getAttribute('href')).toBe('https://github.com/LiPu-jpg/Openwrite')

    const issueLink = screen.getByRole('link', { name: '去 GitHub 反馈问题（自动带入环境信息）' })
    const href = issueLink.getAttribute('href') ?? ''
    expect(href).toContain('https://github.com/LiPu-jpg/Openwrite/issues/new?body=')
    expect(decodeURIComponent(href)).not.toContain('authorname')

    fireEvent.click(screen.getByRole('button', { name: '复制脱敏诊断信息' }))
    await waitFor(() => expect(screen.getByRole('button', { name: '已复制脱敏诊断信息' })).toBeTruthy())
    expect(writeText).toHaveBeenCalledTimes(1)
    expect(String(writeText.mock.calls[0]?.[0])).not.toContain('authorname')

    fireEvent.click(screen.getByRole('button', { name: '复制 /feedback 指令（交给 Agent 排查）' }))
    await waitFor(() => expect(screen.getByRole('button', { name: '已复制 /feedback，去对话粘贴即可' })).toBeTruthy())
    expect(writeText).toHaveBeenCalledTimes(2)
    expect(String(writeText.mock.calls[1]?.[0])).toContain('/feedback')
  })

  it('sanitizes unix, windows, and credential tokens in diagnostic strings', () => {
    expect(sanitizeDiagnosticText('at /Users/alice/.dsh and /home/bob/.dsh and D:\\Users\\carol\\work and C:/Users/dave/doc sk-abcdefgh12345678 https://example.com?api_key=secret123'))
      .toBe('at <HOME>/.dsh and <HOME>/.dsh and <HOME>\\work and <HOME>/doc <REDACTED_KEY> https://example.com?api_key=<REDACTED>')
  })

  it('shows the OpenWrite release announcement modal only once per version update and allows manual reopen from settings', async () => {
    expect(hasSeenReleaseAnnouncement('0.2.39')).toBe(false)

    // First boot on v0.2.39: modal opens automatically
    const firstModal = maybeShowReleaseAnnouncement({ t, version: '0.2.39', allowWebdriver: true })
    expect(firstModal).not.toBeNull()
    expect(document.querySelector(`[${RELEASE_MODAL_MARKER}="0.2.39"]`)).not.toBeNull()
    expect(firstModal?.textContent).toContain('说点心里话：如果你觉得 OpenWrite 好用，想请你顺手点个 Star')
    expect(firstModal?.textContent).toContain('LiPu-jpg/Openwrite')
    expect(firstModal?.textContent).not.toContain('EAC-Desktop')
    expect(firstModal?.textContent).not.toContain('EAC-Pack')
    expect(firstModal?.textContent).not.toContain('EAC-design-world')

    const starAnchor = firstModal?.querySelector('a[href="https://github.com/LiPu-jpg/Openwrite"]')
    expect(starAnchor).not.toBeNull()
    expect(firstModal?.querySelector('a[href="https://github.com/Ebony-Vinyl/dsh-our-free-model"]')).not.toBeNull()
    expect(firstModal?.querySelector('a[href="https://github.com/T-Auto/dsh-ops"]')).not.toBeNull()
    expect(firstModal?.querySelector('a[href="https://github.com/Fun10165/dsh-dog"]')).not.toBeNull()
    expect(firstModal?.textContent).toContain('dsh-our-free-model')
    expect(firstModal?.textContent).toContain('dsh-ops')
    expect(firstModal?.textContent).toContain('dsh-dog')

    // Dismissing records the version in localStorage and removes the modal
    const dismissButton = Array.from(firstModal?.querySelectorAll('button') ?? []).find(
      button => button.textContent === '我知道了，开始创作',
    )
    expect(dismissButton).toBeDefined()
    dismissButton?.click()

    expect(window.localStorage.getItem(SEEN_RELEASE_VERSION_KEY)).toBe('0.2.39')
    expect(hasSeenReleaseAnnouncement('0.2.39')).toBe(true)
    expect(document.querySelector(`[${RELEASE_MODAL_MARKER}]`)).toBeNull()

    // Subsequent boots on the same version v0.2.39 do NOT pop up again
    expect(maybeShowReleaseAnnouncement({ t, version: '0.2.39', allowWebdriver: true })).toBeNull()
    expect(document.querySelector(`[${RELEASE_MODAL_MARKER}]`)).toBeNull()

    // Upgrading to a new version (e.g. v0.2.40) pops up once for the new version
    const nextVersionModal = maybeShowReleaseAnnouncement({ t, version: '0.2.40', allowWebdriver: true })
    expect(nextVersionModal).not.toBeNull()
    expect(document.querySelector(`[${RELEASE_MODAL_MARKER}="0.2.40"]`)).not.toBeNull()
    nextVersionModal?.querySelector('button')?.click()
    expect(window.localStorage.getItem(SEEN_RELEASE_VERSION_KEY)).toBe('0.2.40')

    // Manual reopen button inside Settings -> OpenWrite works anytime
    stubRoutes({
      '/studio-panel/runtime': { phase: 'ready', message: '写作环境已就绪' },
      '/studio-panel/config.json': { studioUrl: 'http://127.0.0.1:18765', managed: true, available: true },
      '/studio-panel/host-model': { available: false, provider: '', model: '', reasoningEffort: '' },
      '/studio-panel/companions': { host: '0.2.2-rc.3', dog: { installed: false, usable: false }, ops: { installed: false, usable: false }, freeModel: { installed: false, usable: false } },
    })
    render(<OpenWriteSettings t={t} />)
    fireEvent.click(await screen.findByRole('button', { name: '查看本版更新说明' }))
    expect(document.querySelector(`[${RELEASE_MODAL_MARKER}]`)).not.toBeNull()
  })

  it('keeps polling to ready after prepare even if POST initially reports idle and reloads sibling tabs', async () => {
    let runtimePhase: 'idle' | 'ready' = 'idle'
    let prefCalls = 0
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      if (url.endsWith('/studio-panel/runtime') && init?.method === 'POST') {
        setTimeout(() => { runtimePhase = 'ready' }, 50)
        return new Response(JSON.stringify({ phase: 'idle', message: 'The writing environment will be prepared on first use' }), { status: 202, headers: { 'content-type': 'application/json' } })
      }
      if (url.endsWith('/studio-panel/runtime')) {
        return new Response(JSON.stringify({
          phase: runtimePhase,
          message: runtimePhase === 'ready' ? 'The writing environment is ready' : 'The writing environment will be prepared on first use',
        }), { status: 200, headers: { 'content-type': 'application/json' } })
      }
      if (url.includes('/studio-panel/api/model/profiles')) {
        if (runtimePhase !== 'ready') return new Response('not ready', { status: 503 })
        return new Response(JSON.stringify({ ok: true, data: { profiles: [], embedding_profiles: [], active_embedding_profile_id: '', routes: {} } }), { status: 200, headers: { 'content-type': 'application/json' } })
      }
      if (url.includes('/studio-panel/api/model/host-models')) {
        return new Response(JSON.stringify({ ok: true, data: { available: false, models: [] } }), { status: 200, headers: { 'content-type': 'application/json' } })
      }
      if (url.endsWith('/studio-panel/api/research/preferences')) {
        prefCalls += 1
        if (runtimePhase !== 'ready') return new Response('not ready', { status: 503 })
        return new Response(JSON.stringify(routes['/studio-panel/api/research/preferences']), { status: 200, headers: { 'content-type': 'application/json' } })
      }
      const key = Object.keys(routes).find(candidate => url.endsWith(candidate))
      if (key === undefined) throw new Error(`unexpected fetch ${url}`)
      return new Response(JSON.stringify(routes[key]), { status: 200, headers: { 'content-type': 'application/json' } })
    })
    vi.stubGlobal('fetch', fetchMock)
    render(<OpenWriteSettings t={t} />)

    fireEvent.click(await screen.findByRole('button', { name: '准备写作环境' }))
    await waitFor(() => expect(screen.getByText('已就绪')).toBeTruthy(), { timeout: 5_000 })
    await waitFor(() => expect(prefCalls).toBeGreaterThanOrEqual(2), { timeout: 5_000 })
    fireEvent.click(screen.getByRole('tab', { name: '搜索' }))
    expect(await screen.findByText('当前默认：DSH')).toBeTruthy()
  })

  it('guides feedback through health pre-check, placeholder validation, and sanitized GitHub pre-fill', async () => {
    expect(validateFeedbackDraft({ category: 'bug', title: '1111', description: 'some description here' })).toEqual({
      valid: false,
      errorKey: 'settings.feedback.validationMissingTitle',
    })
    expect(validateFeedbackDraft({ category: 'bug', title: '生成大纲超时', description: '太短' })).toEqual({
      valid: false,
      errorKey: 'settings.feedback.validationMissingDesc',
    })
    expect(analyzeFeedbackHealth(
      { phase: 'error', message: 'boom' },
      { studioUrl: 'http://127.0.0.1:18765', managed: true, available: false },
      { available: false, provider: '', model: '', reasoningEffort: '' },
      { host: '0.2.2-rc.3', dog: { installed: true, usable: false, version: '1.0.0', reason: 'mismatch' }, ops: { installed: false, usable: false }, freeModel: { installed: false, usable: false } },
    ).map(item => item.key)).toEqual([
      'settings.feedback.healthError',
      'settings.feedback.healthBackendDown',
      'settings.feedback.healthHostModelNone',
      'settings.feedback.healthCompanionIncompatible',
    ])

    stubRoutes({
      '/studio-panel/runtime': { phase: 'ready', message: '写作环境已就绪' },
      '/studio-panel/config.json': { studioUrl: 'http://127.0.0.1:18765', managed: true, available: true },
      '/studio-panel/host-model': { available: true, provider: 'deepseek-official', model: 'deepseek-flash', reasoningEffort: '' },
      '/studio-panel/companions': { host: '0.2.2-rc.3', dog: { installed: true, usable: true, version: '2.0.0-alpha.2' }, ops: { installed: false, usable: false }, freeModel: { installed: false, usable: false } },
      '/studio-panel/api/research/preferences': { ok: true, data: { search_engine: 'dsh', fetch_engine: 'dsh', search_engines: [], fetch_engines: [] } },
    })
    render(<OpenWriteSettings t={t} />)

    fireEvent.click(await screen.findByRole('button', { name: '提交问题 / 建议' }))
    const assistant = await screen.findByTestId('openwrite-feedback-assistant')
    expect(assistant.textContent).toContain('当前运行环境与模型状态正常')
    expect(within(assistant).getByRole('button', { name: '前往 GitHub 提交（已预填标题与脱敏报告）' }).hasAttribute('disabled')).toBe(true)

    fireEvent.change(within(assistant).getByLabelText('一句话标题（必填）'), {
      target: { value: '1111' },
    })
    fireEvent.change(within(assistant).getByLabelText('现象与复现步骤（必填，自动脱敏路径与密钥）'), {
      target: { value: '在 /Users/alice/Novels/Book 执行生成时携带 sk-1234567890abcdef 报错' },
    })
    expect(within(assistant).getByRole('button', { name: '前往 GitHub 提交（已预填标题与脱敏报告）' }).hasAttribute('disabled')).toBe(true)

    fireEvent.change(within(assistant).getByLabelText('一句话标题（必填）'), {
      target: { value: '生成章节大纲返回 502 超时' },
    })
    const submitLink = within(assistant).getByRole('link', { name: '前往 GitHub 提交（已预填标题与脱敏报告）' })
    const href = submitLink.getAttribute('href') ?? ''
    const parsed = new URL(href)
    const bodyParam = parsed.searchParams.get('body') ?? ''
    expect(href).toContain('https://github.com/LiPu-jpg/Openwrite/issues/new?')
    expect(parsed.searchParams.get('title')).toBe('[Bug]: 生成章节大纲返回 502 超时')
    expect(parsed.searchParams.get('labels')).toBe('bug')
    expect(bodyParam).toContain('openwrite_version: v')
    expect(bodyParam).toContain('<HOME>/Novels/Book')
    expect(bodyParam).toContain('<REDACTED_KEY>')
    expect(bodyParam).not.toContain('alice')
    expect(bodyParam).not.toContain('sk-1234567890abcdef')
  })

  it('dispatches /feedback directly into the host Agent Loop and falls back to clipboard when unavailable', async () => {
    const writeText = vi.fn(async () => undefined)
    Object.assign(navigator, { clipboard: { writeText } })

    stubRoutes({
      '/studio-panel/runtime': { phase: 'ready', message: '写作环境已就绪' },
      '/studio-panel/config.json': { studioUrl: 'http://127.0.0.1:18765', managed: true, available: true },
      '/studio-panel/host-model': { available: true, provider: 'deepseek-official', model: 'deepseek-flash', reasoningEffort: '' },
      '/studio-panel/companions': { host: '0.2.2-rc.3', dog: { installed: true, usable: true, version: '2.0.0-alpha.2' }, ops: { installed: false, usable: false }, freeModel: { installed: false, usable: false } },
      '/studio-panel/api/research/preferences': { ok: true, data: { search_engine: 'dsh', fetch_engine: 'dsh', search_engines: [], fetch_engines: [] } },
    })

    const onDispatch = vi.fn(async () => ({ status: 'dispatched' as const, sessionId: 'sess-ow-1' }))
    render(<OpenWriteSettings t={t} onDispatchFeedbackToAgent={onDispatch} />)

    fireEvent.click(await screen.findByRole('button', { name: '提交问题 / 建议' }))
    const assistant = await screen.findByTestId('openwrite-feedback-assistant')
    fireEvent.click(within(assistant).getByRole('button', { name: '让 Agent 自动排查（直连对话）' }))

    await waitFor(() => expect(onDispatch).toHaveBeenCalledTimes(1))
    expect(String(onDispatch.mock.calls[0]?.[0])).toContain('/feedback')
    expect(String(onDispatch.mock.calls[0]?.[0])).toContain('openwrite_version: v')
    expect(await within(assistant).findByText('已接入 OpenWrite 对话并发送排查指令，关闭设置窗口即可查看 Agent 自动排查与脱敏报告。')).toBeTruthy()

    // Fallback path when host dispatch returns fallback
    const onFallback = vi.fn(async () => ({ status: 'fallback' as const, reason: 'unavailable' }))
    render(<OpenWriteSettings t={t} onDispatchFeedbackToAgent={onFallback} />)
    const buttons = screen.getAllByRole('button', { name: '提交问题 / 建议' })
    fireEvent.click(buttons[1]!)
    const assistants = await screen.findAllByTestId('openwrite-feedback-assistant')
    fireEvent.click(within(assistants[1]!).getByRole('button', { name: '让 Agent 自动排查（直连对话）' }))
    await waitFor(() => expect(writeText).toHaveBeenCalled())
    expect(await within(assistants[1]!).findByText('当前无法直连对话，已为您复制 /feedback 指令，请粘贴到任意创作对话发送。')).toBeTruthy()
  })

  it('dispatchFeedbackToHostAgent reuses an active OpenWrite session or creates one on demand', async () => {
    const promptFn = vi.fn(async () => ({ ok: true, value: { accepted: true } }))
    const openSessionFn = vi.fn()
    const createFn = vi.fn(async () => 'sess-created')

    const resExisting = await dispatchFeedbackToHostAgent({
      sessions: {
        list: {
          getSnapshot: () => ({
            ids: ['sess-1'],
            byId: { 'sess-1': { retainedBy: { mainView: 1 }, projectionValues: { agentPreset: 'openwrite' } } },
          }),
        },
        create: createFn,
        scope: () => ({}),
        sessionOf: () => ({ prompt: promptFn }),
      } as never,
      uiWorkspace: { openSession: openSessionFn },
    }, '/feedback test')
    expect(resExisting).toEqual({ status: 'dispatched', sessionId: 'sess-1' })
    expect(createFn).not.toHaveBeenCalled()
    expect(promptFn).toHaveBeenCalledWith([{ type: 'text', text: '/feedback test' }], 'queue')
    expect(openSessionFn).toHaveBeenCalledWith('sess-1')

    const resCreated = await dispatchFeedbackToHostAgent({
      sessions: {
        list: {
          getSnapshot: () => ({ ids: [], byId: {} }),
        },
        create: createFn,
        scope: () => ({}),
        sessionOf: () => ({ prompt: promptFn }),
      } as never,
      uiWorkspace: { openSession: openSessionFn },
    }, '/feedback new-session')
    expect(resCreated).toEqual({ status: 'dispatched', sessionId: 'sess-created' })
    expect(createFn).toHaveBeenCalledWith({ agentPreset: 'openwrite' })
    expect(openSessionFn).toHaveBeenCalledWith('sess-created')
  })
})
