import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, test, vi } from 'vitest'
import { CompanionSection } from '../../src/client/companions.tsx'
import { setStudioContext } from '../../src/client/api.ts'

const status = {
  host: '0.2.0-rc.2',
  dog: { installed: true, usable: true, version: '1.4.0-alpha.1', reason: null },
  ops: { installed: true, usable: true, version: '0.5.0-alpha3', reason: null },
  freeModel: { installed: true, usable: true, version: '2.7.4', reason: null },
}

describe('CompanionSection', () => {
  beforeEach(() => { vi.restoreAllMocks(); setStudioContext({ workspaceId: 'ws-a', sessionId: 'ses-a' }) })
  afterEach(() => { setStudioContext(null) })

  it('explains a companion the running host would reject instead of claiming it works', () => {
    render(<CompanionSection status={{ host: '0.2.1-rc.5', dog: { installed: true, usable: false, version: '1.4.0-alpha.1', reason: 'its @deepseek-ai/dsh-* peer ranges exclude dsh 0.2.1-rc.5' }, ops: { installed: true, usable: false, version: '0.4.4', reason: 'declared host range >=0.2.0-rc.2 <0.2.2-0 excludes dsh 0.2.1-rc.5' }, freeModel: { installed: false, usable: false, version: null, reason: null } }} />)
    expect(screen.getByText(/dsh-ops：已安装（0\.4\.4），但当前宿主不兼容/)).toBeTruthy()
    expect(screen.getByText(/dsh-our-free-model：未安装/)).toBeTruthy()
    // A rejected companion must not offer a wiring action.
    expect(screen.queryByRole('button', { name: /写入 OpenWrite 模型配置/ })).toBeNull()
  })

  it('describes the exact dsh-ops mount plan instead of a generic claim', () => {
    render(<CompanionSection status={{
      ...status,
      ops: { ...status.ops, plan: { files: true, discovery: true, presentation: 'native', shell: false, replaceOfficial: false, residentTools: true, residentNames: 8 } },
    }} />)
    expect(screen.getByText(/dsh-ops：已接入：有界文件工具（8 个常驻） \+ 渐进发现；不替换官方文件工具/)).toBeTruthy()
  })

  it('says what to install when no companion is present', () => {
    render(<CompanionSection status={{ host: null, dog: { installed: false, usable: false, version: null, reason: null }, ops: { installed: false, usable: false, version: null, reason: null }, freeModel: { installed: false, usable: false, version: null, reason: null } }} />)
    expect(screen.getByText(/宿主 dsh （版本未知）/)).toBeTruthy()
    expect(screen.getByText(/安装 dsh-ops 可减少文件检索的 token 消耗/)).toBeTruthy()
  })

  it('writes a model profile at the gateway when the forward listener is up', async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input)
      if (url.includes('/api/our-free-model/clients')) {
        return new Response(JSON.stringify({ running: true, baseUrl: 'http://127.0.0.1:8326/v1', key: 'k'.repeat(24), models: ['deepseek-v4-flash-free', 'kimi-k3'] }), { status: 200, headers: { 'content-type': 'application/json' } })
      }
      if (url.includes('/studio-panel/api/model/profiles') && (input as unknown as RequestInit | undefined)?.body === undefined) {
        return new Response(JSON.stringify({ profiles: [], routes: { chapter_write: 'default', review: 'default' } }), { status: 200, headers: { 'content-type': 'application/json' } })
      }
      if (url.includes('/studio-panel/api/model/routes')) return new Response(JSON.stringify({ ok: true }), { status: 200, headers: { 'content-type': 'application/json' } })
      throw new Error(`unexpected fetch ${url}`)
    })
    vi.stubGlobal('fetch', fetchMock)
    render(<CompanionSection status={status} />)
    // The button is disabled until the default model has been applied, and that
    // happens in an effect after the gateway arrives. Waiting for the button to
    // merely exist can resolve before the effect has run, which leaves the
    // selection below racing the default.
    await waitFor(() => expect((screen.getByRole('button', { name: '写入 OpenWrite 模型配置' }) as HTMLButtonElement).disabled).toBe(false))
    expect(screen.getByText(/本地网关 http:\/\/127\.0\.0\.1:8326\/v1 已就绪，可用模型 2 个/)).toBeTruthy()
    fireEvent.change(screen.getByRole('combobox'), { target: { value: 'kimi-k3' } })
    // The gateway arrives asynchronously, so the default-model effect can
    // still be pending when the author picks one. Assert the selection so a
    // late reset fails here instead of silently writing the first model.
    expect((screen.getByRole('combobox') as HTMLSelectElement).value).toBe('kimi-k3')
    fireEvent.click(screen.getByRole('button', { name: '写入 OpenWrite 模型配置' }))
    // Switching the writing/review routes is a second, explicit decision.
    await waitFor(() => expect(screen.getByText(/写作\/评审路由将切换到 our-free-model/)).toBeTruthy())
    fireEvent.click(screen.getByRole('button', { name: '确认切换' }))
    await waitFor(() => expect(screen.getByText(/已写入模型配置 our-free-model/)).toBeTruthy())
    // The GET (read-back) and the POST (write) share one path; the write is the
    // last call to it.
    const writeCall = fetchMock.mock.calls
      .filter(([input, init]) => String(input).includes('/studio-panel/api/model/profiles') && (init as RequestInit | undefined)?.body !== undefined)
      .at(-1)
    expect((writeCall?.[1] as RequestInit).method).toBe('POST')
    const body = JSON.parse(String((writeCall?.[1] as RequestInit).body))
    expect(body).toMatchObject({
      id: 'our-free-model', provider: 'openai', model: 'kimi-k3',
      base_url: 'http://127.0.0.1:8326/v1', api_key: 'k'.repeat(24),
    })
    // Persisting the companion's key stays the author's decision.
    expect(body.remember_api_key).toBe(false)
    // Writing and review are wired in the same action; other routes are not sent.
    const routeCall = fetchMock.mock.calls
      .filter(([input]) => String(input).includes('/studio-panel/api/model/routes'))
      .at(-1)
    expect(JSON.parse(String((routeCall?.[1] as RequestInit).body))).toEqual({
      routes: { chapter_write: 'our-free-model', review: 'our-free-model' },
    })
  })

  it('merges over a stored profile instead of dropping the author tuning', async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input)
      if (url.includes('/api/our-free-model/clients')) {
        return new Response(JSON.stringify({ running: true, baseUrl: 'http://127.0.0.1:8327', key: 'k'.repeat(24), models: ['deepseek-v4-flash-free'] }), { status: 200, headers: { 'content-type': 'application/json' } })
      }
      if (url.includes('/studio-panel/api/model/profiles') && (input as unknown as RequestInit | undefined)?.body === undefined) {
        return new Response(JSON.stringify({ profiles: [{ id: 'our-free-model', label: '我的免费车道', temperature: 0.3, context_tokens: 96000, remember_api_key: true }], routes: { chapter_write: 'our-free-model', review: 'our-free-model' } }), { status: 200, headers: { 'content-type': 'application/json' } })
      }
      if (url.includes('/studio-panel/api/model/profiles')) return new Response(JSON.stringify({ ok: true }), { status: 200, headers: { 'content-type': 'application/json' } })
      throw new Error(`unexpected fetch ${url}`)
    })
    vi.stubGlobal('fetch', fetchMock)
    render(<CompanionSection status={status} />)
    // The button is disabled until the default model has been applied, and that
    // happens in an effect after the gateway arrives. Waiting for the button to
    // merely exist can resolve before the effect has run, which leaves the
    // selection below racing the default.
    await waitFor(() => expect((screen.getByRole('button', { name: '写入 OpenWrite 模型配置' }) as HTMLButtonElement).disabled).toBe(false))
    fireEvent.click(screen.getByRole('button', { name: '写入 OpenWrite 模型配置' }))
    // An existing profile is never overwritten without a confirmation.
    await waitFor(() => expect(screen.getByText(/已存在模型配置 our-free-model/)).toBeTruthy())
    expect(screen.queryByRole('button', { name: '确认覆盖' })).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: '确认覆盖' }))
    await waitFor(() => expect(screen.getByText(/已写入模型配置/)).toBeTruthy())
    const writeCall = fetchMock.mock.calls
      .filter(([input, init]) => String(input).includes('/studio-panel/api/model/profiles') && (init as RequestInit | undefined)?.body !== undefined)
      .at(-1)
    const body = JSON.parse(String((writeCall?.[1] as RequestInit).body))
    expect(body).toMatchObject({ id: 'our-free-model', label: '我的免费车道', temperature: 0.3, context_tokens: 96000, base_url: 'http://127.0.0.1:8327/v1' })
    expect(body.remember_api_key).toBe(true)
  })

  it('reports a partial write when the writing/review route switch fails', async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input)
      if (url.includes('/api/our-free-model/clients')) {
        return new Response(JSON.stringify({ running: true, baseUrl: 'http://127.0.0.1:8326', key: 'k'.repeat(24), models: ['deepseek-v4-flash-free'] }), { status: 200, headers: { 'content-type': 'application/json' } })
      }
      if (url.includes('/studio-panel/api/model/profiles') && (input as unknown as RequestInit | undefined)?.body === undefined) {
        return new Response(JSON.stringify({ profiles: [], routes: { chapter_write: 'default', review: 'default' } }), { status: 200, headers: { 'content-type': 'application/json' } })
      }
      if (url.includes('/studio-panel/api/model/profiles')) return new Response(JSON.stringify({ ok: true }), { status: 200, headers: { 'content-type': 'application/json' } })
      if (url.includes('/studio-panel/api/model/routes')) return new Response('boom', { status: 500 })
      throw new Error(`unexpected fetch ${url}`)
    })
    vi.stubGlobal('fetch', fetchMock)
    render(<CompanionSection status={status} />)
    // The button is disabled until the default model has been applied, and that
    // happens in an effect after the gateway arrives. Waiting for the button to
    // merely exist can resolve before the effect has run, which leaves the
    // selection below racing the default.
    await waitFor(() => expect((screen.getByRole('button', { name: '写入 OpenWrite 模型配置' }) as HTMLButtonElement).disabled).toBe(false))
    fireEvent.click(screen.getByRole('button', { name: '写入 OpenWrite 模型配置' }))
    await waitFor(() => expect(screen.getByRole('button', { name: '确认切换' })).toBeTruthy())
    fireEvent.click(screen.getByRole('button', { name: '确认切换' }))
    await waitFor(() => expect(screen.getByText(/已写入，但写作\/评审路由切换失败/)).toBeTruthy())
    // The profile itself is not rolled back; the message must say so rather
    // than claiming the whole action failed.
    expect(screen.getByText(/模型配置 our-free-model 已写入/)).toBeTruthy()
  })

  it('can write only the profile without touching the author routes', async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input)
      if (url.includes('/api/our-free-model/clients')) {
        return new Response(JSON.stringify({ running: true, baseUrl: 'http://127.0.0.1:8326', key: 'k'.repeat(24), models: ['deepseek-v4-flash-free'] }), { status: 200, headers: { 'content-type': 'application/json' } })
      }
      if (url.includes('/studio-panel/api/model/profiles') && (input as unknown as RequestInit | undefined)?.body === undefined) {
        return new Response(JSON.stringify({ profiles: [], routes: { chapter_write: 'default', review: 'default' } }), { status: 200, headers: { 'content-type': 'application/json' } })
      }
      if (url.includes('/studio-panel/api/model/profiles')) return new Response(JSON.stringify({ ok: true }), { status: 200, headers: { 'content-type': 'application/json' } })
      throw new Error(`unexpected fetch ${url}`)
    })
    vi.stubGlobal('fetch', fetchMock)
    render(<CompanionSection status={status} />)
    // The button is disabled until the default model has been applied, and that
    // happens in an effect after the gateway arrives. Waiting for the button to
    // merely exist can resolve before the effect has run, which leaves the
    // selection below racing the default.
    await waitFor(() => expect((screen.getByRole('button', { name: '写入 OpenWrite 模型配置' }) as HTMLButtonElement).disabled).toBe(false))
    fireEvent.click(screen.getByRole('checkbox', { name: /同时把写作\/评审切到该模型/ }))
    fireEvent.click(screen.getByRole('button', { name: '写入 OpenWrite 模型配置' }))
    await waitFor(() => expect(screen.getByText(/已写入模型配置 our-free-model/)).toBeTruthy())
    expect(fetchMock.mock.calls.some(([input]) => String(input).includes('/studio-panel/api/model/routes'))).toBe(false)
  })

  it('offers the write without a bound workspace, because the model library is global', async () => {
    setStudioContext(null)
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input)
      if (url.includes('/api/our-free-model/clients')) {
        return new Response(JSON.stringify(({ running: true, baseUrl: 'http://127.0.0.1:8326', key: 'k'.repeat(24), models: ['deepseek-v4-flash-free'] })), { status: 200, headers: { 'content-type': 'application/json' } })
      }
      if (url.includes('/studio-panel/api/model/profiles')) return new Response(JSON.stringify({ profiles: [] }), { status: 200, headers: { 'content-type': 'application/json' } })
      throw new Error(`unexpected fetch ${url}`)
    }))
    render(<CompanionSection status={status} />)
    // The profile library lives outside every project, so the settings dialog
    // can wire the free-model gateway without a novel being open.
    await waitFor(() => expect(screen.getByRole('button', { name: /写入 OpenWrite 模型配置/ })).toBeTruthy())
    expect(screen.queryByText(/请先进入一个作品/)).toBeNull()
  })

  it('refuses to write a profile when the gateway reports no address', async () => {
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      if (String(input).includes('/api/our-free-model/clients')) {
        return new Response(JSON.stringify({ running: true, baseUrl: '', key: '', models: [] }), { status: 200, headers: { 'content-type': 'application/json' } })
      }
      throw new Error(`unexpected fetch ${String(input)}`)
    }))
    render(<CompanionSection status={status} />)
    await waitFor(() => expect(screen.getByText(/网关没有返回可用地址/)).toBeTruthy())
    expect(screen.queryByRole('button', { name: /写入 OpenWrite 模型配置/ })).toBeNull()
  })

  it('tells the author to enable the forward listener instead of writing a dead profile', async () => {
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      if (String(input).includes('/api/our-free-model/clients')) {
        return new Response(JSON.stringify(({ running: false, baseUrl: 'http://127.0.0.1:<forward-port>', key: '', models: [] })), { status: 200, headers: { 'content-type': 'application/json' } })
      }
      throw new Error(`unexpected fetch ${String(input)}`)
    }))
    render(<CompanionSection status={status} />)
    await waitFor(() => expect(screen.getByText(/本地转发没有开启/)).toBeTruthy())
    expect(screen.queryByRole('button', { name: /写入 OpenWrite 模型配置/ })).toBeNull()
  })
})

test('a gateway route that answers differently keeps its own cause', async () => {
  for (const [label, answer, expected] of [
    ['unavailable', () => new Response('boom', { status: 502 }), /HTTP 502/],
    ['unreadable', () => { throw new Error('network down') }, /network down/],
    ['shape', () => new Response(JSON.stringify({ running: true }), { status: 200, headers: { 'content-type': 'application/json' } }), /无法识别/],
  ] as const) {
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      if (String(input).includes('/api/our-free-model/clients')) return answer()
      throw new Error(`unexpected fetch ${String(input)}`)
    }))
    const view = render(<CompanionSection status={status} />)
    await waitFor(() => expect(screen.getByText(expected)).toBeTruthy())
    // None of these may claim the forward listener is simply switched off.
    expect(screen.queryByText(/本地转发没有开启/)).toBeNull()
    view.unmount()
  }
})
