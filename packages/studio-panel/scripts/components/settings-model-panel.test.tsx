/**
 * The model profile library lives in the host's settings dialog.
 *
 * Two facts drive this file:
 *
 * 1. The library is global. Studio keeps it outside every project, so the
 *    settings dialog — which is opened with no bound workspace — reaches it
 *    without any Workspace identity. Every request the model panel makes
 *    must therefore carry no `X-Dsh-Workspace-Id`.
 * 2. The panel stays mounted while the author moves between the settings
 *    groups, and a half-edited profile has to survive the dialog closing.
 */
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { setStudioContext } from '../../src/client/api.ts'
import { OpenWriteSettings } from '../../src/client/OpenWriteSettings.tsx'
import { zh } from '../../src/client/locales.ts'

const t = (key: string): string => (zh as Record<string, string>)[key] ?? key

const PROFILE = {
  id: 'writer-a',
  label: 'Writer A',
  provider: 'openai',
  model: 'fake-model-1',
  base_url: 'https://example.invalid/v1',
  api_format: 'chat',
  auth_source: 'api_key',
  workspace_id: '',
  context_tokens: 64000,
  max_output_tokens: 24000,
  temperature: 0.7,
  timeout_seconds: 120,
  configured: true,
  schema_version: 'openwrite.model-profile.v1',
  capabilities: { chat: true },
  used_by_routes: ['chapter_write'],
  last_test: null,
}

const companions = {
  host: '0.2.1-rc.5',
  dog: { installed: true, usable: true, version: '1.4.0', reason: null },
  ops: { installed: true, usable: false, version: '0.5.0', reason: 'peer range excludes this host' },
  freeModel: { installed: false, usable: false, version: null, reason: null },
}

const staticRoutes: Record<string, unknown> = {
  '/studio-panel/host-model': { available: true, provider: 'deepseek-official', model: 'deepseek-flash', reasoningEffort: 'max' },
  '/studio-panel/runtime': { phase: 'ready', message: 'The writing environment is ready' },
  '/studio-panel/config.json': { studioUrl: 'http://127.0.0.1:4567', managed: true },
  '/studio-panel/companions': companions,
}

/** The envelope every Studio answer carries. */
const envelope = (data: unknown) => ({ ok: true, data, error: null, request_id: 'settings-test' })

/**
 * Serve every route the settings page asks for, and remember the model calls
 * so a test can look at the headers they carried.
 */
function stubRoutes(): { modelCalls: { url: string; init: RequestInit | undefined }[] } {
  const modelCalls: { url: string; init: RequestInit | undefined }[] = []
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    if (url.includes('/studio-panel/api/model/profiles')) {
      modelCalls.push({ url, init })
      if (init?.method === 'POST') return new Response(JSON.stringify(envelope({})), { status: 200, headers: { 'content-type': 'application/json' } })
      return new Response(JSON.stringify(envelope({
        schema_version: 'openwrite.model-profile.v1',
        profiles: [PROFILE],
        embedding_profiles: [],
        active_embedding_profile_id: '',
        routes: { chapter_write: 'writer-a' },
      })), { status: 200, headers: { 'content-type': 'application/json' } })
    }
    const key = Object.keys(staticRoutes).find(candidate => url.endsWith(candidate))
    if (key === undefined) throw new Error(`unexpected fetch ${url}`)
    return new Response(JSON.stringify(staticRoutes[key]), { status: 200, headers: { 'content-type': 'application/json' } })
  }))
  return { modelCalls }
}

beforeEach(() => { window.localStorage.clear(); setStudioContext(null) })

describe('the model panel inside the host settings dialog', () => {
  it('reads and writes the global library without a Workspace identity', async () => {
    const { modelCalls } = stubRoutes()
    render(<OpenWriteSettings t={t} />)
    fireEvent.click(screen.getByRole('tab', { name: '模型' }))
    await screen.findByLabelText('档案名')

    expect(modelCalls.length).toBeGreaterThan(0)
    for (const call of modelCalls) {
      const headers = (call.init?.headers ?? {}) as Record<string, string>
      // The settings dialog is opened with no bound workspace: a Workspace
      // header here would make the host proxy reject the call.
      expect(headers['X-Dsh-Workspace-Id']).toBeUndefined()
      expect(headers['X-Dsh-Session-Id']).toBeUndefined()
    }
  })

  it('remembers the chosen group between dialog reopens', async () => {
    stubRoutes()
    const first = render(<OpenWriteSettings t={t} />)
    fireEvent.click(screen.getByRole('tab', { name: '模型' }))
    await waitFor(() => expect(window.localStorage.getItem('openwrite.settings.tab')).toBe('models'))
    first.unmount()

    render(<OpenWriteSettings t={t} />)
    expect((screen.getByRole('tab', { name: '模型' }) as HTMLElement).getAttribute('aria-selected')).toBe('true')
    expect((screen.getByRole('tab', { name: '环境' }) as HTMLElement).getAttribute('aria-selected')).toBe('false')
  })

  it('keeps a half-edited profile when the dialog closes and reopens', async () => {
    stubRoutes()
    const first = render(<OpenWriteSettings t={t} />)
    fireEvent.click(screen.getByRole('tab', { name: '模型' }))
    const field = await screen.findByLabelText('档案名')
    fireEvent.change(field, { target: { value: 'Half-written name' } })
    first.unmount()

    render(<OpenWriteSettings t={t} />)
    fireEvent.click(screen.getByRole('tab', { name: '模型' }))
    await waitFor(() => expect((screen.getByLabelText('档案名') as HTMLInputElement).value).toBe('Half-written name'))
  })

  it('does not let a stale group choice hide the model library', async () => {
    stubRoutes()
    window.localStorage.setItem('openwrite.settings.tab', 'models')
    render(<OpenWriteSettings t={t} />)
    // The panel is mounted even when its group is hidden, so its state
    // survives a group switch instead of being reloaded from the server.
    await screen.findByLabelText('档案名')
    fireEvent.click(screen.getByRole('tab', { name: '宿主' }))
    expect(screen.getByRole('tab', { name: '宿主' }).getAttribute('aria-selected')).toBe('true')
    fireEvent.click(screen.getByRole('tab', { name: '模型' }))
    expect((screen.getByLabelText('档案名') as HTMLInputElement).value).toBe('Writer A')
  })

  it('still reaches the library when the host still runs the old bridge', async () => {
    // The host's proxy half is loaded at startup. A host that has not been
    // restarted since the plugin update refuses the context-free call; the
    // panel falls back to the scoped route and says so.
    setStudioContext({ workspaceId: 'ws-a' })
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      const headers = (init?.headers ?? {}) as Record<string, string>
      if (url.includes('/studio-panel/api/model/profiles')) {
        if (headers['X-Dsh-Workspace-Id'] === undefined) {
          return new Response(JSON.stringify({ error: 'missing workspace id', code: 'WORKSPACE_CONTEXT_MISSING' }), { status: 400, headers: { 'content-type': 'application/json' } })
        }
        return new Response(JSON.stringify(envelope({
          schema_version: 'openwrite.model-profile.v1',
          profiles: [PROFILE],
          embedding_profiles: [],
          active_embedding_profile_id: '',
          routes: { chapter_write: 'writer-a' },
        })), { status: 200, headers: { 'content-type': 'application/json' } })
      }
      const key = Object.keys(staticRoutes).find(candidate => url.endsWith(candidate))
      if (key === undefined) throw new Error(`unexpected fetch ${url}`)
      return new Response(JSON.stringify(staticRoutes[key]), { status: 200, headers: { 'content-type': 'application/json' } })
    })
    vi.stubGlobal('fetch', fetchMock)

    render(<OpenWriteSettings t={t} />)
    fireEvent.click(screen.getByRole('tab', { name: '模型' }))
    await screen.findByLabelText('档案名')
    expect((screen.getByLabelText('档案名') as HTMLInputElement).value).toBe('Writer A')
    // The author is told why the route differs from the global one.
    expect(screen.getByText(/宿主还在运行上一版 OpenWrite/)).toBeTruthy()
  })
})
