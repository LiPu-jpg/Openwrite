/**
 * ModelView workbench tests (component layer, offline).
 *
 * Credential hygiene half (kept from M1c): the Studio API is write-only for
 * credentials — GET /model/profiles answers metadata (`configured: true`) and
 * never the secret. The explicit fake value `test-credential-abc` pins the
 * client half of that contract: typed once into the POST body, cleared after
 * save, never echoed into the DOM.
 *
 * M2b workbench half: grouped editor sections, required/positive-number
 * validation, unsaved-change guard, per-kind test states (untested / success /
 * failed + error_code / loading), `—` for missing latency, delete-preview →
 * confirm with fallback re-preview, routes impact consumed from the server,
 * and loading/error/empty states.
 *
 * Since the M1c envelope flip every model POST/GET answer is wrapped in
 * `{ ok, data, error, request_id }`; the mocks below answer in that shape.
 * The injected `fetchStudioApi`/`postStudioApi` props are mocked, so no
 * network is involved. `t` is stubbed to return the locale key.
 */
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { StudioApiError } from '../../src/client/api.ts'
import { ModelView } from '../../src/client/ModelView.tsx'

const FAKE_CREDENTIAL = 'test-credential-abc'

/** M1c success envelope (all model endpoints answer this way now). */
const envelope = (data: unknown) => ({ ok: true, data, error: null, request_id: 'req_test' })

const PROFILE = {
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

const EMBEDDING_PROFILE = {
  id: 'embed-a', label: 'Embedding A', provider: 'openai', model: 'fake-embed-a',
  base_url: 'https://example.invalid/embed', dimension: 1536, max_tokens: 8192,
  configured: true, active: true, last_test: null,
  schema_version: 'openwrite.embedding-profile.v1',
}
const SECOND_EMBEDDING_PROFILE = {
  ...EMBEDDING_PROFILE, id: 'embed-b', label: 'Embedding B', model: 'fake-embed-b', active: false,
}

const SECOND_PROFILE = {
  ...PROFILE,
  id: 'writer-b',
  label: 'Writer B',
  used_by_routes: ['review'],
}

const PROFILES_PAYLOAD = envelope({
  profiles: [PROFILE],
  embedding_profiles: [EMBEDDING_PROFILE],
  active_embedding_profile_id: 'embed-a',
  routes: { chapter_write: 'writer-a', review: 'writer-a' },
})

const TWO_PROFILES_PAYLOAD = envelope({
  profiles: [PROFILE, SECOND_PROFILE],
  routes: { chapter_write: 'writer-a', review: 'writer-b' },
})

/** Read-only delete preview for the single-profile fixture (deletable, no routes). */
const DELETE_PREVIEW = {
  profile_id: 'writer-a',
  used_by_routes: [],
  routes_that_would_fail: [],
  fallback_candidates: [],
  resulting_routes: {},
  deletable: true,
  blocking_reasons: [],
}

const t = (key: string): string => key

/** Stateful independent Embedding service; every read exposes metadata only. */
function makeEmbeddingApi() {
  let items = [{ ...EMBEDDING_PROFILE }, { ...SECOND_EMBEDDING_PROFILE }]
  let active = EMBEDDING_PROFILE.id
  return makeApi({
    fetch: async (path) => {
      if (path !== '/model/profiles') throw new Error(`unexpected GET ${path}`)
      return envelope({ profiles: [PROFILE, SECOND_PROFILE], routes: { review: 'writer-a' },
        embedding_profiles: items.map((item) => ({ ...item, active: item.id === active })),
        active_embedding_profile_id: active })
    },
    post: async (path, raw) => {
      const body = raw as Record<string, unknown>
      if (path === '/model/embedding') {
        const { api_key: _key, remember_api_key: _remember, ...metadata } = body
        const saved = { ...EMBEDDING_PROFILE, ...metadata }
        items = [...items.filter((item) => item.id !== body.id), saved]
        return envelope({ profile: saved })
      }
      if (path === '/model/embedding/select') active = String(body.profile_id)
      else if (path === '/model/embedding/delete') {
        items = items.filter((item) => item.id !== body.profile_id)
        if (active === body.profile_id) active = items[0]!.id
      } else if (path === '/model/embedding/test') {
        return envelope({ status: 'ok', provider: body.provider, model: body.model,
          latency_ms: 31, tested_at: '2026-09-05T01:00:00Z', reply: '' })
      } else throw new Error(`unexpected POST ${path}`)
      return envelope({ profiles: items, active_embedding_profile_id: active })
    },
  })
}

function makeApi(overrides: {
  fetch?: (path: string) => Promise<unknown>
  post?: (path: string, body: unknown) => Promise<unknown>
} = {}) {
  const postStudioApi = vi.fn(overrides.post ?? (async (path: string) => {
    if (path === '/model/profiles/delete-preview') return envelope(DELETE_PREVIEW)
    return envelope({})
  }))
  return {
    fetchStudioApi: vi.fn(overrides.fetch ?? (async (path: string) => {
      if (path === '/model/profiles') return PROFILES_PAYLOAD
      throw new Error(`unexpected GET ${path}`)
    })),
    postStudioApi,
    putStudioApi: vi.fn(async () => envelope({})),
  }
}

function passwordInputs(container: HTMLElement): HTMLInputElement[] {
  return [...container.querySelectorAll<HTMLInputElement>('input[type=password]')]
}

function renderView(api: ReturnType<typeof makeApi>) {
  // ConvViewProps carries runtime fields the view never touches; the injected
  // API + locale seat are the only live dependencies.
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  return render(<ModelView {...({ ...api, t } as any)} />)
}

async function openEmbedding(api: ReturnType<typeof makeApi>) {
  const view = renderView(api)
  await screen.findByRole('button', { name: /Writer A/ })
  fireEvent.click(screen.getByRole('button', { name: 'Embedding', exact: true }))
  return view
}

describe('ModelView independent Embedding contracts', () => {
  it('loads the active independent profile and drops credential fields from reads', async () => {
    const api = makeApi({ fetch: async () => envelope({ profiles: [PROFILE], routes: {},
      embedding_profiles: [{ ...EMBEDDING_PROFILE, api_key: FAKE_CREDENTIAL,
        credential_ref: 'private-reference', last_test: { status: 'failed', latency_ms: null,
          error_code: 'MODEL_TEST_AUTH' } }], active_embedding_profile_id: 'embed-a' }) })
    const { container } = await openEmbedding(api)
    expect((screen.getByLabelText('models.id') as HTMLInputElement).value).toBe('embed-a')
    expect((screen.getByLabelText('models.id') as HTMLInputElement).disabled).toBe(true)
    expect((screen.getByLabelText('Dimension') as HTMLInputElement).value).toBe('1536')
    expect(passwordInputs(container)[0]!.value).toBe('')
    expect(container.innerHTML).not.toContain(FAKE_CREDENTIAL)
    expect(container.innerHTML).not.toContain('private-reference')
    expect(container.textContent).toContain('models.test.failed MODEL_TEST_AUTH · —')
    expect(api.postStudioApi).not.toHaveBeenCalled()
  })

  it('saves a credential-only edit once, clears it, and preserves chat drafts and routes', async () => {
    const api = makeEmbeddingApi()
    const { container } = renderView(api)
    await screen.findByRole('button', { name: /Writer A/ })
    fireEvent.change(screen.getByLabelText('models.label'), { target: { value: 'Unsaved writer label' } })
    fireEvent.change(screen.getByLabelText('models.route.review'), { target: { value: 'writer-b' } })
    fireEvent.click(screen.getByRole('button', { name: 'Embedding', exact: true }))
    const credential = passwordInputs(container)[0]!
    fireEvent.change(credential, { target: { value: FAKE_CREDENTIAL } })
    fireEvent.click(screen.getByRole('button', { name: 'models.save' }))
    await waitFor(() => expect(credential.value).toBe(''))
    expect(api.postStudioApi).toHaveBeenCalledTimes(1)
    expect(api.postStudioApi).toHaveBeenCalledWith('/model/embedding', {
      id: 'embed-a', label: 'Embedding A', provider: 'openai', model: 'fake-embed-a',
      base_url: 'https://example.invalid/embed', dimension: 1536, max_tokens: 8192,
      remember_api_key: true, api_key: FAKE_CREDENTIAL,
    })
    expect(container.innerHTML).not.toContain(FAKE_CREDENTIAL)
    fireEvent.click(screen.getByRole('button', { name: 'Chat', exact: true }))
    expect((screen.getByLabelText('models.label') as HTMLInputElement).value).toBe('Unsaved writer label')
    expect((screen.getByLabelText('models.route.review') as HTMLSelectElement).value).toBe('writer-b')
  })

  it('creates and updates an independent profile without empty credentials or chat fields', async () => {
    const api = makeEmbeddingApi()
    await openEmbedding(api)
    fireEvent.click(screen.getByRole('button', { name: 'models.new' }))
    expect((screen.getByLabelText('models.id') as HTMLInputElement).disabled).toBe(false)
    fireEvent.change(screen.getByLabelText('models.id'), { target: { value: 'embed-c' } })
    fireEvent.change(screen.getByLabelText('models.label'), { target: { value: 'Embedding C' } })
    fireEvent.change(screen.getByLabelText('models.embeddingModel'), { target: { value: 'fake-embed-c' } })
    fireEvent.change(screen.getByLabelText('Dimension'), { target: { value: '1024' } })
    fireEvent.click(screen.getByRole('button', { name: 'models.save' }))
    await screen.findByRole('button', { name: /Embedding C/ })
    const [path, body] = api.postStudioApi.mock.calls[0] as [string, Record<string, unknown>]
    expect(path).toBe('/model/embedding')
    expect(body).toMatchObject({ id: 'embed-c', label: 'Embedding C', model: 'fake-embed-c', dimension: 1024, max_tokens: 8192 })
    expect(body).not.toHaveProperty('api_key')
    expect(body).not.toHaveProperty('embedding_api_key')
    expect(body).not.toHaveProperty('context_tokens')
    expect((screen.getByLabelText('models.id') as HTMLInputElement).disabled).toBe(true)
    fireEvent.change(screen.getByLabelText('models.label'), { target: { value: 'Embedding C updated' } })
    fireEvent.click(screen.getByRole('button', { name: 'models.save' }))
    await screen.findByRole('button', { name: /Embedding C updated/ })
    expect(api.postStudioApi.mock.calls[1]).toEqual(['/model/embedding', expect.objectContaining({ id: 'embed-c', label: 'Embedding C updated' })])
  })

  it('requires explicit discard before selection drops an embedding credential', async () => {
    const api = makeEmbeddingApi()
    const { container } = await openEmbedding(api)
    fireEvent.change(passwordInputs(container)[0]!, { target: { value: FAKE_CREDENTIAL } })
    fireEvent.click(screen.getByRole('button', { name: /Embedding B/ }))
    expect(screen.getByText('models.unsavedChanges')).toBeTruthy()
    expect(api.postStudioApi).not.toHaveBeenCalled()
    fireEvent.click(screen.getByRole('button', { name: 'models.unsavedKeep' }))
    expect(passwordInputs(container)[0]!.value).toBe(FAKE_CREDENTIAL)
    fireEvent.click(screen.getByRole('button', { name: /Embedding B/ }))
    fireEvent.click(screen.getByRole('button', { name: 'models.unsavedDiscard' }))
    await waitFor(() => expect((screen.getByLabelText('models.id') as HTMLInputElement).value).toBe('embed-b'))
    expect(api.postStudioApi).toHaveBeenCalledExactlyOnceWith('/model/embedding/select', { profile_id: 'embed-b' })
    expect(passwordInputs(container)[0]!.value).toBe('')
    expect(container.innerHTML).not.toContain(FAKE_CREDENTIAL)
  })

  it('guards embedding refresh and creation, including credential-only edits', async () => {
    const api = makeEmbeddingApi()
    const { container } = await openEmbedding(api)
    fireEvent.change(passwordInputs(container)[0]!, { target: { value: FAKE_CREDENTIAL } })
    fireEvent.click(screen.getByTitle('refresh'))
    expect(screen.getByText('models.unsavedChanges')).toBeTruthy()
    expect(api.fetchStudioApi).toHaveBeenCalledTimes(1)
    fireEvent.click(screen.getByRole('button', { name: 'models.unsavedKeep' }))
    fireEvent.click(screen.getByRole('button', { name: 'models.new' }))
    expect(screen.getByText('models.unsavedChanges')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'models.unsavedDiscard' }))
    expect((screen.getByLabelText('models.id') as HTMLInputElement).value).toMatch(/^embedding-/)
    expect(passwordInputs(container)[0]!.value).toBe('')
    expect(api.postStudioApi).not.toHaveBeenCalled()
  })

  it('tests the independent draft and entered key without saving or discarding it', async () => {
    const api = makeEmbeddingApi()
    const { container } = await openEmbedding(api)
    fireEvent.change(screen.getByLabelText('models.label'), { target: { value: 'Unsaved embed label' } })
    fireEvent.change(passwordInputs(container)[0]!, { target: { value: FAKE_CREDENTIAL } })
    fireEvent.click(screen.getByRole('button', { name: 'models.embeddingTest' }))
    await screen.findByText('models.embeddingOk · 31 ms')
    expect(api.postStudioApi).toHaveBeenCalledTimes(1)
    expect(api.postStudioApi).toHaveBeenCalledWith('/model/embedding/test', expect.objectContaining({
      id: 'embed-a', label: 'Unsaved embed label', dimension: 1536, max_tokens: 8192, api_key: FAKE_CREDENTIAL,
    }))
    expect((screen.getByLabelText('models.label') as HTMLInputElement).value).toBe('Unsaved embed label')
    expect(passwordInputs(container)[0]!.value).toBe(FAKE_CREDENTIAL)
    expect(container.textContent).not.toContain(FAKE_CREDENTIAL)
  })

  it('refreshes the saved embedding test marker without making an unchanged editor dirty', async () => {
    let tested = false
    const api = makeApi({
      fetch: async () => envelope({ profiles: [PROFILE], routes: {},
        embedding_profiles: [{ ...EMBEDDING_PROFILE, last_test: tested
          ? { status: 'ok', latency_ms: 31, provider: 'openai', resolved_model: 'fake-embed-a' }
          : null }], active_embedding_profile_id: 'embed-a' }),
      post: async () => { tested = true; return envelope({ status: 'ok', latency_ms: 31 }) },
    })
    const { container } = await openEmbedding(api)
    fireEvent.click(screen.getByRole('button', { name: 'models.embeddingTest' }))
    await screen.findByText('models.embeddingOk · 31 ms')
    expect(container.textContent).toContain('models.test.ok · 31 ms')
    const [, body] = api.postStudioApi.mock.calls[0] as [string, Record<string, unknown>]
    expect(body).not.toHaveProperty('api_key')
    fireEvent.click(screen.getByRole('button', { name: 'models.new' }))
    expect(screen.queryByText('models.unsavedChanges')).toBeNull()
    expect((screen.getByLabelText('models.id') as HTMLInputElement).value).toMatch(/^embedding-/)
  })

  it('deletes only after confirmation and protects the last remaining profile', async () => {
    const api = makeEmbeddingApi()
    await openEmbedding(api)
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(false)
    try {
      fireEvent.click(screen.getByRole('button', { name: 'models.delete' }))
      expect(confirm).toHaveBeenCalledTimes(1)
      expect(api.postStudioApi).not.toHaveBeenCalled()
      confirm.mockReturnValue(true)
      fireEvent.click(screen.getByRole('button', { name: 'models.delete' }))
      await waitFor(() => expect((screen.getByLabelText('models.id') as HTMLInputElement).value).toBe('embed-b'))
      expect(api.postStudioApi).toHaveBeenCalledExactlyOnceWith('/model/embedding/delete', { profile_id: 'embed-a' })
      expect((screen.getByRole('button', { name: 'models.delete' }) as HTMLButtonElement).disabled).toBe(true)
      fireEvent.click(screen.getByRole('button', { name: 'models.delete' }))
      expect(confirm).toHaveBeenCalledTimes(2)
    } finally { confirm.mockRestore() }
  })

  it('blocks invalid embedding sizes and missing model before saving', async () => {
    const api = makeEmbeddingApi()
    await openEmbedding(api)
    fireEvent.change(screen.getByLabelText('Dimension'), { target: { value: '0' } })
    fireEvent.click(screen.getByRole('button', { name: 'models.save' }))
    expect(screen.getByText('models.validation.positive')).toBeTruthy()
    fireEvent.change(screen.getByLabelText('Dimension'), { target: { value: '1536' } })
    fireEvent.change(screen.getByLabelText('Max tokens'), { target: { value: '1.5' } })
    fireEvent.click(screen.getByRole('button', { name: 'models.save' }))
    expect(screen.getByText('models.validation.positive')).toBeTruthy()
    fireEvent.change(screen.getByLabelText('Max tokens'), { target: { value: '8192' } })
    fireEvent.change(screen.getByLabelText('models.embeddingModel'), { target: { value: '' } })
    fireEvent.click(screen.getByRole('button', { name: 'models.save' }))
    expect(screen.getByText('models.validation.required')).toBeTruthy()
    expect(api.postStudioApi).not.toHaveBeenCalled()
  })
})

describe('ModelView credential non-echo', () => {
  it('renders a configured profile without any credential value', async () => {
    const api = makeApi()
    const { container } = renderView(api)
    await screen.findByRole('button', { name: /Writer A/ })

    // Configured marker shown, but no secret material anywhere.
    expect(container.textContent).toContain('models.configured')
    expect(container.textContent).not.toContain(FAKE_CREDENTIAL)
    for (const input of passwordInputs(container)) {
      expect(input.value).toBe('')
    }
    expect(passwordInputs(container).length).toBe(1)
    fireEvent.click(screen.getByRole('button', { name: 'Embedding', exact: true }))
    expect(passwordInputs(container)).toHaveLength(1)
    expect(passwordInputs(container)[0]!.value).toBe('')
  })

  it('POSTs the credential once, then clears it and never echoes it', async () => {
    const api = makeApi()
    const { container } = renderView(api)
    await screen.findByRole('button', { name: /Writer A/ })

    const [credentialInput] = passwordInputs(container)
    fireEvent.change(credentialInput!, { target: { value: FAKE_CREDENTIAL } })
    expect(credentialInput!.value).toBe(FAKE_CREDENTIAL) // user typing only

    fireEvent.click(screen.getByRole('button', { name: /models\.save/ }))

    await waitFor(() => expect(api.postStudioApi).toHaveBeenCalled())
    const [path, body] = api.postStudioApi.mock.calls[0] as [string, Record<string, unknown>]
    expect(path).toBe('/model/profiles')
    expect(body['api_key']).toBe(FAKE_CREDENTIAL)

    // After the save completes the field is cleared and the DOM is clean.
    await waitFor(() => expect(credentialInput!.value).toBe(''))
    for (const input of passwordInputs(container)) {
      expect(input.value).toBe('')
    }
    expect(container.textContent).not.toContain(FAKE_CREDENTIAL)
    expect(container.innerHTML).not.toContain(FAKE_CREDENTIAL)
    // Save triggers a reload; the reload payload stays credential-free.
    await waitFor(() => expect(api.fetchStudioApi.mock.calls.length).toBeGreaterThanOrEqual(2))
  })

  it('omits the credential key entirely when the field is left empty', async () => {
    const api = makeApi()
    renderView(api)
    await screen.findByRole('button', { name: /Writer A/ })

    fireEvent.click(screen.getByRole('button', { name: /models\.save/ }))
    await waitFor(() => expect(api.postStudioApi).toHaveBeenCalled())
    const [, body] = api.postStudioApi.mock.calls[0] as [string, Record<string, unknown>]
    expect('api_key' in body).toBe(false)
    expect('embedding_api_key' in body).toBe(false)
  })

  it('delete round-trip (preview → confirm) keeps the DOM credential-free', async () => {
    const api = makeApi()
    const { container } = renderView(api)
    await screen.findByRole('button', { name: /Writer A/ })

    // Delete intent only previews; nothing is deleted until the confirm.
    fireEvent.click(screen.getByRole('button', { name: 'models.delete' }))
    await waitFor(() => expect(api.postStudioApi).toHaveBeenCalled())
    const [previewPath, previewBody] = api.postStudioApi.mock.calls[0] as [string, Record<string, unknown>]
    expect(previewPath).toBe('/model/profiles/delete-preview')
    expect(previewBody['profile_id']).toBe('writer-a')

    fireEvent.click(await screen.findByRole('button', { name: 'models.delete.confirm' }))
    await waitFor(() => expect(api.postStudioApi).toHaveBeenCalledTimes(2))
    const [path, body] = api.postStudioApi.mock.calls[1] as [string, Record<string, unknown>]
    expect(path).toBe('/model/profiles/delete')
    expect(body['profile_id']).toBe('writer-a')
    expect(JSON.stringify(body)).not.toContain(FAKE_CREDENTIAL)
    expect(container.textContent).not.toContain(FAKE_CREDENTIAL)
  })
})

describe('ModelView M1c surface', () => {
  it('renders a failed last_test with its error_code and an untested marker', async () => {
    const failedProfile = {
      ...SECOND_PROFILE,
      last_test: {
        status: 'failed',
        tested_at: '2026-08-31T10:00:00Z',
        latency_ms: 1200,
        provider: 'openai',
        resolved_model: 'fake-model-1',
        error_code: 'MODEL_TEST_TIMEOUT',
        failed_stage: null,
      },
    }
    const api = makeApi({
      fetch: async (path: string) => {
        if (path === '/model/profiles') {
          return envelope({ profiles: [PROFILE, failedProfile], routes: { chapter_write: 'writer-a', review: 'writer-b' } })
        }
        throw new Error(`unexpected GET ${path}`)
      },
    })
    const { container } = renderView(api)
    await screen.findByRole('button', { name: /Writer B/ })

    // Failed chat test surfaces the contract error code; the never-tested
    // profile shows the untested marker instead.
    expect(container.textContent).toContain('models.test.failed')
    expect(container.textContent).toContain('MODEL_TEST_TIMEOUT')
    expect(container.textContent).toContain('models.test.untested')
    expect(container.textContent).not.toContain(FAKE_CREDENTIAL)
  })

  it('delete flow: preview shows route usage, confirm posts delete with fallback_id', async () => {
    const preview = {
      profile_id: 'writer-a',
      used_by_routes: ['chapter_write'],
      routes_that_would_fail: [],
      fallback_candidates: [{ id: 'writer-b', label: 'Writer B', configured: true }],
      resulting_routes: { chapter_write: 'writer-b', review: 'writer-b' },
      deletable: true,
      blocking_reasons: [],
    }
    const api = makeApi({
      fetch: async (path: string) => {
        if (path === '/model/profiles') return TWO_PROFILES_PAYLOAD
        throw new Error(`unexpected GET ${path}`)
      },
      post: async (path: string) => {
        if (path === '/model/profiles/delete-preview') return envelope(preview)
        return envelope({})
      },
    })
    renderView(api)
    await screen.findByRole('button', { name: /Writer B/ })

    fireEvent.click(screen.getByRole('button', { name: 'models.delete' }))
    // The preview lists the dependent route and the confirm appears.
    await screen.findByRole('button', { name: 'models.delete.confirm' })
    const [previewPath, previewBody] = api.postStudioApi.mock.calls[0] as [string, Record<string, unknown>]
    expect(previewPath).toBe('/model/profiles/delete-preview')
    expect(previewBody).toEqual({ profile_id: 'writer-a', fallback_id: 'writer-b' })

    fireEvent.click(screen.getByRole('button', { name: 'models.delete.confirm' }))
    await waitFor(() => expect(api.postStudioApi).toHaveBeenCalledTimes(2))
    const [path, body] = api.postStudioApi.mock.calls[1] as [string, Record<string, unknown>]
    expect(path).toBe('/model/profiles/delete')
    expect(body).toEqual({ profile_id: 'writer-a', fallback_id: 'writer-b' })
  })

  it('a blocked preview disables the confirm and shows the blocking reason', async () => {
    const api = makeApi({
      post: async (path: string) => {
        if (path === '/model/profiles/delete-preview') {
          return envelope({
            ...DELETE_PREVIEW,
            used_by_routes: ['chapter_write'],
            routes_that_would_fail: ['chapter_write'],
            deletable: false,
            blocking_reasons: ['MODEL_PROFILE_LAST_PROFILE'],
          })
        }
        return envelope({})
      },
    })
    renderView(api)
    await screen.findByRole('button', { name: /Writer A/ })

    fireEvent.click(screen.getByRole('button', { name: 'models.delete' }))
    const confirm = await screen.findByRole('button', { name: 'models.delete.confirm' })
    expect((confirm as HTMLButtonElement).disabled).toBe(true)
    expect(screen.getByText(/MODEL_PROFILE_LAST_PROFILE/)).toBeTruthy()
    // Only the preview was posted — never the delete.
    expect(api.postStudioApi).toHaveBeenCalledTimes(1)
  })
})

describe('ModelView workbench (M2b)', () => {
  it('groups chat fields and route usage while embedding has its own editor', async () => {
    const api = makeApi()
    renderView(api)
    await screen.findByRole('button', { name: /Writer A/ })

    for (const group of ['models.group.basic', 'models.group.connection', 'models.group.generation', 'models.group.credentials', 'models.group.routeUsage']) {
      expect(screen.getByText(group)).toBeTruthy()
    }
    // Route usage group lists the routes bound to the selected profile.
    expect(screen.getAllByText('models.route.chapter_write').length).toBeGreaterThanOrEqual(1)
  })

  it('create flow: id stays editable and the save posts the new profile', async () => {
    const api = makeApi()
    renderView(api)
    await screen.findByRole('button', { name: /Writer A/ })

    fireEvent.click(screen.getByRole('button', { name: /models\.new/ }))
    const idInput = screen.getByLabelText('models.id') as HTMLInputElement
    expect(idInput.disabled).toBe(false)
    fireEvent.change(idInput, { target: { value: 'writer-c' } })
    fireEvent.change(screen.getByLabelText('models.label'), { target: { value: 'Writer C' } })
    fireEvent.change(screen.getByLabelText('models.modelId'), { target: { value: 'fake-model-2' } })
    fireEvent.click(screen.getByRole('button', { name: /models\.save/ }))

    await waitFor(() => expect(api.postStudioApi).toHaveBeenCalled())
    const [path, body] = api.postStudioApi.mock.calls[0] as [string, Record<string, unknown>]
    expect(path).toBe('/model/profiles')
    expect(body).toMatchObject({ id: 'writer-c', label: 'Writer C', model: 'fake-model-2' })
    // Numeric fields arrive as numbers, not strings.
    expect(typeof body['context_tokens']).toBe('number')
    expect(typeof body['temperature']).toBe('number')
  })

  it('edit flow: id is locked and a label change saves with the existing id', async () => {
    const api = makeApi()
    renderView(api)
    await screen.findByRole('button', { name: /Writer A/ })

    const idInput = screen.getByLabelText('models.id') as HTMLInputElement
    expect(idInput.value).toBe('writer-a')
    expect(idInput.disabled).toBe(true)
    fireEvent.change(screen.getByLabelText('models.label'), { target: { value: 'Writer A renamed' } })
    fireEvent.click(screen.getByRole('button', { name: /models\.save/ }))

    await waitFor(() => expect(api.postStudioApi).toHaveBeenCalled())
    const [path, body] = api.postStudioApi.mock.calls[0] as [string, Record<string, unknown>]
    expect(path).toBe('/model/profiles')
    expect(body).toMatchObject({ id: 'writer-a', label: 'Writer A renamed' })
  })

  it('blocks the save with a required-fields message and never POSTs', async () => {
    const api = makeApi()
    renderView(api)
    await screen.findByRole('button', { name: /Writer A/ })

    fireEvent.click(screen.getByRole('button', { name: /models\.new/ }))
    fireEvent.click(screen.getByRole('button', { name: /models\.save/ }))
    expect(await screen.findByText('models.validation.required')).toBeTruthy()
    expect(api.postStudioApi).not.toHaveBeenCalled()
  })

  it('blocks non-positive or out-of-range numbers before any POST', async () => {
    const api = makeApi()
    renderView(api)
    await screen.findByRole('button', { name: /Writer A/ })

    fireEvent.change(screen.getByLabelText('models.context'), { target: { value: '-5' } })
    fireEvent.click(screen.getByRole('button', { name: /models\.save/ }))
    expect(await screen.findByText('models.validation.positive')).toBeTruthy()
    expect(api.postStudioApi).not.toHaveBeenCalled()

    fireEvent.change(screen.getByLabelText('models.context'), { target: { value: '64000' } })
    fireEvent.change(screen.getByLabelText('models.temperature'), { target: { value: '3' } })
    fireEvent.click(screen.getByRole('button', { name: /models\.save/ }))
    expect(await screen.findByText('models.validation.temperature')).toBeTruthy()
    expect(api.postStudioApi).not.toHaveBeenCalled()
  })

  it('guards unsaved changes on switch: keep editing stays, discard switches', async () => {
    const api = makeApi({
      fetch: async (path: string) => {
        if (path === '/model/profiles') return TWO_PROFILES_PAYLOAD
        throw new Error(`unexpected GET ${path}`)
      },
    })
    renderView(api)
    await screen.findByRole('button', { name: /Writer B/ })

    fireEvent.change(screen.getByLabelText('models.label'), { target: { value: 'Writer A edited' } })
    fireEvent.click(screen.getByRole('button', { name: /Writer B/ }))
    // The switch is not silent: a guard strip appears and the form is intact.
    expect(await screen.findByText('models.unsavedChanges')).toBeTruthy()
    expect((screen.getByLabelText('models.id') as HTMLInputElement).value).toBe('writer-a')
    expect((screen.getByLabelText('models.label') as HTMLInputElement).value).toBe('Writer A edited')

    fireEvent.click(screen.getByRole('button', { name: 'models.unsavedKeep' }))
    expect(screen.queryByText('models.unsavedChanges')).toBeNull()
    expect((screen.getByLabelText('models.id') as HTMLInputElement).value).toBe('writer-a')

    fireEvent.click(screen.getByRole('button', { name: /Writer B/ }))
    fireEvent.click(await screen.findByRole('button', { name: 'models.unsavedDiscard' }))
    await waitFor(() => expect((screen.getByLabelText('models.id') as HTMLInputElement).value).toBe('writer-b'))
  })

  it('guards unsaved changes on create instead of dropping them silently', async () => {
    const api = makeApi()
    renderView(api)
    await screen.findByRole('button', { name: /Writer A/ })

    fireEvent.change(screen.getByLabelText('models.label'), { target: { value: 'Writer A edited' } })
    fireEvent.click(screen.getByRole('button', { name: /models\.new/ }))
    expect(await screen.findByText('models.unsavedChanges')).toBeTruthy()
    // Still editing writer-a until the user explicitly discards.
    expect((screen.getByLabelText('models.id') as HTMLInputElement).value).toBe('writer-a')
    fireEvent.click(screen.getByRole('button', { name: 'models.unsavedDiscard' }))
    await waitFor(() => expect((screen.getByLabelText('models.id') as HTMLInputElement).value).toBe(''))
    expect((screen.getByLabelText('models.id') as HTMLInputElement).disabled).toBe(false)
  })

  it('chat test success shows real latency; embedding failure shows the error code', async () => {
    const api = makeApi({
      post: async (path: string) => {
        if (path === '/model/test') {
          return envelope({ status: 'ok', provider: 'openai', model: 'fake-model-1', latency_ms: 812, tested_at: '2026-09-01T10:00:00Z', reply: 'pong' })
        }
        if (path === '/model/embedding/test') {
          throw new StudioApiError('provider rejected the embedding key', 502, 'MODEL_TEST_AUTH')
        }
        return envelope({})
      },
    })
    const { container } = renderView(api)
    await screen.findByRole('button', { name: /Writer A/ })

    fireEvent.click(screen.getByRole('button', { name: 'models.chatTest' }))
    await waitFor(() => expect(container.textContent).toContain('models.chatOk'))
    expect(container.textContent).toContain('812 ms')

    fireEvent.click(screen.getByRole('button', { name: 'Embedding', exact: true }))
    fireEvent.click(screen.getByRole('button', { name: 'models.embeddingTest' }))
    await waitFor(() => expect(container.textContent).toContain('MODEL_TEST_AUTH'))
    // The failure text is the contract code plus message, never a secret.
    expect(container.textContent).not.toContain(FAKE_CREDENTIAL)
  })

  it('keeps dirty form fields when a saved profile is connection-tested', async () => {
    const api = makeApi({
      post: async (path: string) => {
        if (path === '/model/test') return envelope({ status: 'ok', provider: 'openai', model: 'fake-model-1', latency_ms: 12, tested_at: '2026-09-01T10:00:00Z', reply: 'pong' })
        return envelope({})
      },
    })
    renderView(api)
    await screen.findByRole('button', { name: /Writer A/ })

    const label = screen.getByLabelText('models.label') as HTMLInputElement
    const credential = passwordInputs(document.body)[0]!
    fireEvent.change(label, { target: { value: 'Edited before test' } })
    fireEvent.change(credential, { target: { value: FAKE_CREDENTIAL } })
    fireEvent.click(screen.getByRole('button', { name: 'models.chatTest' }))

    await waitFor(() => expect(api.postStudioApi).toHaveBeenCalledWith('/model/test', expect.anything()))
    expect(label.value).toBe('Edited before test')
    expect(credential.value).toBe(FAKE_CREDENTIAL)
  })

  it('guards refresh when profile edits are dirty and discards only after confirmation', async () => {
    const api = makeApi()
    renderView(api)
    await screen.findByRole('button', { name: /Writer A/ })

    const label = screen.getByLabelText('models.label') as HTMLInputElement
    fireEvent.change(label, { target: { value: 'Edited before refresh' } })
    fireEvent.click(screen.getByTitle('refresh'))
    expect(await screen.findByText('models.unsavedChanges')).toBeTruthy()
    expect(label.value).toBe('Edited before refresh')

    fireEvent.click(screen.getByRole('button', { name: 'models.unsavedKeep' }))
    expect(label.value).toBe('Edited before refresh')
    fireEvent.click(screen.getByTitle('refresh'))
    fireEvent.click(await screen.findByRole('button', { name: 'models.unsavedDiscard' }))
    await waitFor(() => expect(label.value).toBe('Writer A'))
  })

  it('shows — for missing latency and never invents 0 ms', async () => {
    const noLatency = {
      ...PROFILE,
      last_test: {
        status: 'ok', tested_at: '2026-08-31T10:00:00Z', latency_ms: null,
        provider: 'openai', resolved_model: 'fake-model-1', error_code: null, failed_stage: null,
      },
    }
    const api = makeApi({
      fetch: async (path: string) => {
        if (path === '/model/profiles') return envelope({ profiles: [noLatency], routes: {} })
        throw new Error(`unexpected GET ${path}`)
      },
    })
    const { container } = renderView(api)
    await screen.findByRole('button', { name: /Writer A/ })

    expect(container.textContent).toContain('models.test.ok · —')
    expect(container.textContent).not.toContain('0 ms')
  })

  it('re-runs the delete preview when the fallback selection changes', async () => {
    const preview = {
      profile_id: 'writer-a',
      used_by_routes: ['chapter_write'],
      routes_that_would_fail: [],
      fallback_candidates: [
        { id: 'writer-b', label: 'Writer B', configured: true },
        { id: 'writer-c', label: 'Writer C', configured: true },
      ],
      resulting_routes: { chapter_write: 'writer-b' },
      deletable: true,
      blocking_reasons: [],
    }
    const api = makeApi({
      fetch: async (path: string) => {
        if (path === '/model/profiles') return TWO_PROFILES_PAYLOAD
        throw new Error(`unexpected GET ${path}`)
      },
      post: async (path: string) => {
        if (path === '/model/profiles/delete-preview') return envelope(preview)
        return envelope({})
      },
    })
    renderView(api)
    await screen.findByRole('button', { name: /Writer B/ })

    fireEvent.click(screen.getByRole('button', { name: 'models.delete' }))
    await screen.findByRole('button', { name: 'models.delete.confirm' })
    expect(api.postStudioApi).toHaveBeenCalledTimes(1)

    fireEvent.change(screen.getByLabelText('models.fallback'), { target: { value: 'writer-c' } })
    await waitFor(() => expect(api.postStudioApi).toHaveBeenCalledTimes(2))
    const [path, body] = api.postStudioApi.mock.calls[1] as [string, Record<string, unknown>]
    expect(path).toBe('/model/profiles/delete-preview')
    expect(body).toEqual({ profile_id: 'writer-a', fallback_id: 'writer-c' })
    // Still no delete: the preview refresh is read-only.
    for (const [callPath] of api.postStudioApi.mock.calls as [string][]) {
      expect(callPath).not.toBe('/model/profiles/delete')
    }
  })

  it('routes: shows purpose labels and saves through the server impact payload', async () => {
    // Stateful mock: the route save mutates the map the next GET answers.
    let savedRoutes = { chapter_write: 'writer-a', review: 'writer-b' }
    const api = makeApi({
      fetch: async (path: string) => {
        if (path === '/model/profiles') return envelope({ profiles: [PROFILE, SECOND_PROFILE], routes: savedRoutes })
        throw new Error(`unexpected GET ${path}`)
      },
      post: async (path: string, body: unknown) => {
        if (path === '/model/routes') {
          const posted = (body as { routes: Record<string, string> }).routes
          const previous = savedRoutes
          savedRoutes = { ...savedRoutes, ...posted }
          return envelope({
            model_profiles: { routes: savedRoutes },
            impact: {
              changed_routes: [{ route: 'review', from: previous['review'], to: posted['review'] }],
              profiles_affected: ['writer-a', 'writer-b'],
            },
          })
        }
        return envelope({})
      },
    })
    const { container } = renderView(api)
    await screen.findByRole('button', { name: /Writer B/ })

    // Purpose labels instead of raw route keys, plus the current profile meta.
    expect(screen.getByLabelText('models.route.review')).toBeTruthy()
    expect(container.textContent).toContain('models.route.chapter_write')

    fireEvent.change(screen.getByLabelText('models.route.review'), { target: { value: 'writer-a' } })
    fireEvent.click(screen.getByRole('button', { name: /models\.routesSave/ }))
    await waitFor(() => expect(api.postStudioApi).toHaveBeenCalled())
    const [path, body] = api.postStudioApi.mock.calls[0] as [string, { routes: Record<string, string> }]
    expect(path).toBe('/model/routes')
    expect(body.routes['review']).toBe('writer-a')

    // The impact line is rendered from the server answer, not simulated.
    await waitFor(() => expect(container.textContent).toContain('models.routesImpact'))
    expect(container.textContent).toContain('writer-b → writer-a')
    // The select adopts the route map the server returned.
    await waitFor(() => expect((screen.getByLabelText('models.route.review') as HTMLSelectElement).value).toBe('writer-a'))
  })

  it('preserves dirty route edits when saving a profile triggers a reload', async () => {
    const api = makeApi({
      fetch: async (path: string) => {
        if (path === '/model/profiles') return TWO_PROFILES_PAYLOAD
        throw new Error(`unexpected GET ${path}`)
      },
    })
    renderView(api)
    await screen.findByRole('button', { name: /Writer B/ })

    const route = screen.getByLabelText('models.route.review') as HTMLSelectElement
    fireEvent.change(route, { target: { value: 'writer-a' } })
    fireEvent.click(screen.getByLabelText('models.label'))
    fireEvent.click(screen.getByRole('button', { name: /models\.save/ }))

    await waitFor(() => expect(api.postStudioApi).toHaveBeenCalledWith('/model/profiles', expect.anything()))
    await waitFor(() => expect(route.value).toBe('writer-a'))
  })

  it('shows loading, then an error with a working retry, then renders', async () => {
    let attempt = 0
    const api = makeApi({
      fetch: async (path: string) => {
        if (path !== '/model/profiles') throw new Error(`unexpected GET ${path}`)
        attempt += 1
        if (attempt === 1) throw new StudioApiError('Studio API request timed out (20s)', 408)
        return PROFILES_PAYLOAD
      },
    })
    renderView(api)

    // First attempt fails: the error state offers a retry instead of a dead panel.
    expect(await screen.findByText(/408|timed out/)).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'retry' }))
    await screen.findByRole('button', { name: /Writer A/ })
    expect(attempt).toBe(2)
  })

  it('shows the empty state and keeps the create form usable', async () => {
    const api = makeApi({
      fetch: async (path: string) => {
        if (path === '/model/profiles') return envelope({ profiles: [], routes: {} })
        throw new Error(`unexpected GET ${path}`)
      },
    })
    renderView(api)

    expect(await screen.findByText('models.empty')).toBeTruthy()
    const idInput = screen.getByLabelText('models.id') as HTMLInputElement
    expect(idInput.disabled).toBe(false)
    // Chat and independent Embedding each show an honest untested state.
    expect(screen.getByText(/models\.test\.untested/)).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'Embedding', exact: true }))
    expect(screen.getByText('models.embeddingEmpty')).toBeTruthy()
    expect(screen.getByText(/models\.test\.untested/)).toBeTruthy()
  })

  it('renders long identifiers in full (wrapping/ellipsis is a CSS concern)', async () => {
    const longLabel = 'Writer ' + '超长档案名'.repeat(20)
    const longModel = 'fake-model-' + 'x'.repeat(100)
    const longProfile = { ...PROFILE, label: longLabel, model: longModel }
    const api = makeApi({
      fetch: async (path: string) => {
        if (path === '/model/profiles') return envelope({ profiles: [longProfile], routes: { chapter_write: 'writer-a' } })
        throw new Error(`unexpected GET ${path}`)
      },
    })
    const { container } = renderView(api)
    await screen.findByRole('button', { name: new RegExp(longLabel) })

    // jsdom cannot measure overflow (browser QA / E2E territory); the DOM must
    // carry the full text so CSS ellipsis/wrapping has something to clip.
    expect(container.textContent).toContain(longModel)
  })

  it('disables conflicting actions while a save is in flight', async () => {
    let release: (value: unknown) => void = () => undefined
    const api = makeApi({
      post: async (path: string) => {
        if (path === '/model/profiles') {
          return await new Promise(resolve => { release = resolve })
        }
        return envelope({})
      },
    })
    renderView(api)
    await screen.findByRole('button', { name: /Writer A/ })

    fireEvent.click(screen.getByRole('button', { name: /models\.save/ }))
    await waitFor(() => expect((screen.getByRole('button', { name: /models\.save/ }) as HTMLButtonElement).disabled).toBe(true))
    expect((screen.getByRole('button', { name: 'models.chatTest' }) as HTMLButtonElement).disabled).toBe(true)
    expect((screen.getByRole('button', { name: 'Embedding', exact: true }) as HTMLButtonElement).disabled).toBe(true)
    expect((screen.getByRole('button', { name: /models\.new/ }) as HTMLButtonElement).disabled).toBe(true)

    release(envelope({}))
    await waitFor(() => expect((screen.getByRole('button', { name: /models\.save/ }) as HTMLButtonElement).disabled).toBe(false))
  })
})
