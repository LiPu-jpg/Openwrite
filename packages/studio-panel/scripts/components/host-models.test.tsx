/**
 * ModelView host-model contracts (component layer, offline).
 *
 * The host owns the model directory: its own adapters plus the ones other
 * plugins register into the same registry. OpenWrite reaches them through the
 * host's loopback relay, so a profile created from that directory carries no
 * address and no key — the backend resolves both at call time.
 *
 * The route table shows one row for the conversation: the host composes a
 * single `openwrite` preset, so Goethe and Dante are no longer two agents the
 * author picks between. Saving the row writes both underlying route keys, so
 * old archives and the model benchmark still resolve.
 */
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { ModelView } from '../../src/client/ModelView.tsx'

const envelope = (data: unknown) => ({ ok: true, data, error: null, request_id: 'req_test' })

const t = (key: string): string => key

const WRITER = {
  id: 'writer-a',
  label: 'Writer A',
  provider: 'openai',
  model: 'fake-model-1',
  base_url: 'https://example.invalid/v1',
  api_format: 'chat',
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

const HOST_PROFILE = {
  ...WRITER,
  id: 'host-deepseek-official-abc123',
  label: 'DeepSeek Flash',
  provider: 'custom',
  model: 'deepseek-official/deepseek-flash',
  base_url: '',
  auth_source: 'host_relay',
  used_by_routes: [],
}

const SECOND = {
  ...WRITER,
  id: 'writer-b',
  label: 'Writer B',
  model: 'fake-model-2',
  used_by_routes: ['review'],
}

const HOST_MODELS = envelope({
  available: true,
  models: [
    {
      id: 'deepseek-official/deepseek-flash',
      provider: 'deepseek-official',
      model: 'deepseek-flash',
      label: 'DeepSeek Flash',
      description: '',
      context_tokens: 131072,
    },
    {
      id: 'our-free-model/vendor/Model-X',
      provider: 'our-free-model',
      model: 'vendor/Model-X',
      label: 'Model X',
      description: 'free',
      context_tokens: 0,
    },
  ],
  error: '',
})

function makeApi(options: {
  profiles?: unknown[]
  routes?: Record<string, string>
  hostModels?: unknown
  created?: boolean
} = {}) {
  let profiles = options.profiles ?? [WRITER]
  const routes = options.routes ?? { goethe: 'writer-a', dante: 'writer-a', chapter_write: 'writer-a' }
  const postStudioApi = vi.fn(async (path: string, body: unknown) => {
    if (path === '/model/host-profiles') {
      const model = (body as { model: string }).model
      profiles = [...profiles, { ...HOST_PROFILE, model, label: model }]
      return envelope({
        profile: { ...HOST_PROFILE, model },
        model_profiles: { profiles, routes },
      })
    }
    if (path === '/model/routes') {
      return envelope({ routes: (body as { routes: Record<string, string> }).routes, impact: { changed_routes: [] } })
    }
    return envelope({})
  })
  const fetchStudioApi = vi.fn(async (path: string) => {
    if (path === '/model/profiles') {
      return envelope({ profiles, routes, embedding_profiles: [], active_embedding_profile_id: '' })
    }
    if (path === '/model/host-models') {
      return options.hostModels ?? envelope({ available: false, models: [], error: '' })
    }
    throw new Error(`unexpected GET ${path}`)
  })
  return { fetchStudioApi, postStudioApi, putStudioApi: vi.fn(async () => envelope({})) }
}

function renderView(api: ReturnType<typeof makeApi>) {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  return render(<ModelView {...({ ...api, t } as any)} />)
}

describe('ModelView host model contracts', () => {
  it('lists the models the host can reach and adopts one with a single click', async () => {
    const api = makeApi({ hostModels: HOST_MODELS })
    renderView(api)
    await screen.findByRole('button', { name: /Writer A/ })
    expect(screen.getByText('deepseek-official/deepseek-flash')).toBeTruthy()
    expect(screen.getByText('our-free-model/vendor/Model-X')).toBeTruthy()

    fireEvent.click(screen.getAllByRole('button', { name: 'models.hostUse' })[0]!)
    await waitFor(() => expect(api.postStudioApi).toHaveBeenCalledWith('/model/host-profiles', {
      model: 'deepseek-official/deepseek-flash',
    }))
    await screen.findByRole('button', { name: /deepseek-official\/deepseek-flash/ })
  })

  it('says so when the host has no model channel', async () => {
    const api = makeApi({
      hostModels: envelope({ available: false, models: [], error: '宿主模型通道未连接' }),
    })
    renderView(api)
    await screen.findByRole('button', { name: /Writer A/ })
    expect(screen.getByText('models.hostModelsUnavailable')).toBeTruthy()
  })

  it('locks a host profile: the host owns its address and credential', async () => {
    const api = makeApi({ profiles: [WRITER, HOST_PROFILE], hostModels: HOST_MODELS })
    renderView(api)
    await screen.findByRole('button', { name: /DeepSeek Flash/ })
    fireEvent.click(screen.getByRole('button', { name: /DeepSeek Flash/ }))
    await waitFor(() => expect((screen.getByLabelText('models.id') as HTMLInputElement).value)
      .toBe('host-deepseek-official-abc123'))
    expect((screen.getByLabelText('models.id') as HTMLInputElement).disabled).toBe(true)
    const locked = (label: string) => (screen.getByLabelText(label).closest('fieldset') as HTMLFieldSetElement).disabled
    expect(locked('models.modelId')).toBe(true)
    expect(locked('models.baseUrl')).toBe(true)
    expect(screen.getByText('models.hostProfileHint')).toBeTruthy()
    // A profile the author cannot edit is not offered for saving.
    expect(screen.queryByRole('button', { name: 'models.save' })).toBeNull()
  })

  it('shows one chat route and writes both underlying routes', async () => {
    const api = makeApi({ profiles: [WRITER, SECOND] })
    renderView(api)
    await screen.findByRole('button', { name: /Writer A/ })
    expect(screen.getAllByLabelText('models.route.chat')).toHaveLength(1)
    expect(screen.queryByLabelText('models.route.goethe')).toBeNull()
    expect(screen.queryByLabelText('models.route.dante')).toBeNull()

    // One pick, two underlying routes.
    fireEvent.change(screen.getByLabelText('models.route.chat'), { target: { value: 'writer-b' } })
    fireEvent.click(screen.getByRole('button', { name: 'models.routesSave' }))
    await waitFor(() => expect(api.postStudioApi).toHaveBeenCalledWith('/model/routes', {
      routes: { goethe: 'writer-b', dante: 'writer-b', chapter_write: 'writer-a' },
    }))
  })

  it('says when the two chat routes still point at different profiles', async () => {
    const api = makeApi({ routes: { goethe: 'writer-a', dante: 'writer-b', chapter_write: 'writer-a' } })
    renderView(api)
    await screen.findByRole('button', { name: /Writer A/ })
    expect(screen.getByText('models.routeChatSplit')).toBeTruthy()
  })
})
