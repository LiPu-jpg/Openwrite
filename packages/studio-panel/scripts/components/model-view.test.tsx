/**
 * ModelView credential hygiene (component layer, offline).
 *
 * The Studio API is write-only for credentials: GET /model/profiles answers
 * metadata (`configured: true`) and never the secret. These tests pin the
 * client half of that contract with the explicit fake value
 * `test-credential-abc`:
 *   - typing a credential and saving sends it once in the POST body, then the
 *     password inputs are cleared and the value never appears in the DOM;
 *   - profile list/detail rendering after CRUD contains no credential text.
 *
 * The injected `fetchStudioApi`/`postStudioApi` props are mocked, so no
 * network is involved. `t` is stubbed to return the locale key.
 */
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { ModelView } from '../../src/client/ModelView.tsx'

const FAKE_CREDENTIAL = 'test-credential-abc'

const PROFILE = {
  id: 'writer-a',
  label: 'Writer A',
  provider: 'openai',
  model: 'fake-model-1',
  base_url: 'https://example.invalid/v1',
  api_format: 'chat',
  context_tokens: 64000,
  max_output_tokens: 24000,
  embedding_provider: 'openai',
  embedding_model: '',
  configured: true,
  embedding_configured: false,
}

const PROFILES_PAYLOAD = {
  profiles: [PROFILE],
  routes: { writing: 'writer-a', review: 'writer-a' },
}

const t = (key: string): string => key

function makeApi(overrides: { post?: (path: string, body: unknown) => Promise<unknown> } = {}) {
  const postStudioApi = vi.fn(overrides.post ?? (async () => ({})))
  return {
    fetchStudioApi: vi.fn(async (path: string) => {
      if (path === '/model/profiles') return PROFILES_PAYLOAD
      throw new Error(`unexpected GET ${path}`)
    }),
    postStudioApi,
    putStudioApi: vi.fn(async () => ({})),
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

describe('ModelView credential non-echo', () => {
  it('renders a configured profile without any credential value', async () => {
    const api = makeApi()
    const { container } = renderView(api)
    await screen.findByText('Writer A')

    // Configured marker shown, but no secret material anywhere.
    expect(container.textContent).toContain('models.configured')
    expect(container.textContent).not.toContain(FAKE_CREDENTIAL)
    for (const input of passwordInputs(container)) {
      expect(input.value).toBe('')
    }
    expect(passwordInputs(container).length).toBe(2)
  })

  it('POSTs the credential once, then clears it and never echoes it', async () => {
    const api = makeApi()
    const { container } = renderView(api)
    await screen.findByText('Writer A')

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
    await screen.findByText('Writer A')

    fireEvent.click(screen.getByRole('button', { name: /models\.save/ }))
    await waitFor(() => expect(api.postStudioApi).toHaveBeenCalled())
    const [, body] = api.postStudioApi.mock.calls[0] as [string, Record<string, unknown>]
    expect('api_key' in body).toBe(false)
    expect('embedding_api_key' in body).toBe(false)
  })

  it('delete round-trip keeps the DOM credential-free', async () => {
    const api = makeApi()
    const { container } = renderView(api)
    await screen.findByText('Writer A')

    fireEvent.click(screen.getByRole('button', { name: /models\.delete/ }))
    await waitFor(() => expect(api.postStudioApi).toHaveBeenCalled())
    const [path, body] = api.postStudioApi.mock.calls[0] as [string, Record<string, unknown>]
    expect(path).toBe('/model/profiles/delete')
    expect(body['profile_id']).toBe('writer-a')
    expect(JSON.stringify(body)).not.toContain(FAKE_CREDENTIAL)
    expect(container.textContent).not.toContain(FAKE_CREDENTIAL)
  })
})
