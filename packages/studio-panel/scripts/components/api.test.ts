import { afterEach, describe, expect, it, vi } from 'vitest'
import { API_PROXY_BASE, fetchGlobalStudioApi, fetchStudioApi, isGlobalFallbackActive, postGlobalStudioApi, putStudioApi, resetGlobalFallbackState, setStudioContext, StudioApiError } from '../../src/client/api.ts'

afterEach(() => {
  setStudioContext(null)
  resetGlobalFallbackState()
  vi.unstubAllGlobals()
})

describe('Studio write context snapshot', () => {
  it('uses the captured Workspace headers after the globally bound context changes', async () => {
    const fetchMock = vi.fn(async () => new Response(JSON.stringify({ ok: true }), {
      status: 200,
      headers: { 'content-type': 'application/json' },
    }))
    vi.stubGlobal('fetch', fetchMock)
    setStudioContext({ workspaceId: 'ws-new', sessionId: 'session-new' })

    await putStudioApi('/document', { content: 'old workspace draft' }, {
      workspaceId: 'ws-old',
      sessionId: 'session-old',
    })

    expect(fetchMock).toHaveBeenCalledWith(`${API_PROXY_BASE}/document`, expect.objectContaining({
      method: 'PUT',
      headers: expect.objectContaining({
        'X-Dsh-Workspace-Id': 'ws-old',
        'X-Dsh-Session-Id': 'session-old',
      }),
    }))
  })
})

describe('Studio write deadline', () => {
  it('rejects a write that never settles instead of hanging forever', async () => {
    vi.stubGlobal('fetch', vi.fn((_input: unknown, init?: RequestInit) => new Promise((_resolve, reject) => {
      // Never resolves on its own; only the caller's abort can end it.
      init?.signal?.addEventListener('abort', () => reject(new DOMException('aborted', 'AbortError')))
    })))
    setStudioContext({ workspaceId: 'ws-a' })

    vi.useFakeTimers()
    try {
      const pending = putStudioApi('/document', { content: 'x' })
      const assertion = pending.then(
        () => { throw new Error('the write must not resolve') },
        cause => {
          expect(cause).toBeInstanceOf(StudioApiError)
          expect((cause as StudioApiError).status).toBe(408)
        },
      )
      await vi.advanceTimersByTimeAsync(200_000)
      await assertion
    } finally {
      vi.useRealTimers()
    }
  })

  it('passes an abort signal so a hung write can be cancelled', async () => {
    const fetchMock = vi.fn(async () => new Response(JSON.stringify({ ok: true }), {
      status: 200, headers: { 'content-type': 'application/json' },
    }))
    vi.stubGlobal('fetch', fetchMock)
    setStudioContext({ workspaceId: 'ws-a' })

    await putStudioApi('/document', { content: 'x' })

    expect(fetchMock.mock.calls[0]?.[1]).toHaveProperty('signal')
  })
})

describe('Studio error contract', () => {
  it('preserves protected-context adjustment details from Studio', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({
      error: 'protected context is over budget',
      code: 'PROTECTED_CONTEXT_OVER_BUDGET',
      details: { source_paths: ['src/story/current_focus.md'], budget_tokens: 1000 },
    }), { status: 422, headers: { 'content-type': 'application/json' } })))
    setStudioContext({ workspaceId: 'ws-a' })

    const error = await fetchStudioApi('/context?chapter=ch_001').catch(cause => cause)

    expect(error).toBeInstanceOf(StudioApiError)
    expect(error).toMatchObject({
      status: 422,
      code: 'PROTECTED_CONTEXT_OVER_BUDGET',
      details: { source_paths: ['src/story/current_focus.md'], budget_tokens: 1000 },
    })
  })
})

describe('global Studio paths', () => {
  it('reaches the model library without any Workspace identity', async () => {
    const fetchMock = vi.fn(async () => new Response(JSON.stringify({ ok: true }), {
      status: 200,
      headers: { 'content-type': 'application/json' },
    }))
    vi.stubGlobal('fetch', fetchMock)

    await fetchGlobalStudioApi('/model/profiles')

    const headers = (fetchMock.mock.calls[0]?.[1] as RequestInit).headers as Record<string, string>
    expect(headers['X-Dsh-Workspace-Id']).toBeUndefined()
    expect(headers['X-Dsh-Session-Id']).toBeUndefined()
  })

  it('writes the model library without any Workspace identity', async () => {
    const fetchMock = vi.fn(async () => new Response(JSON.stringify({ ok: true }), {
      status: 200,
      headers: { 'content-type': 'application/json' },
    }))
    vi.stubGlobal('fetch', fetchMock)

    await postGlobalStudioApi('/model/routes', { routes: {} })

    const init = fetchMock.mock.calls[0]?.[1] as RequestInit
    const headers = init.headers as Record<string, string>
    expect(init.method).toBe('POST')
    expect(headers['X-Dsh-Workspace-Id']).toBeUndefined()
  })

  it('refuses a project-scoped path instead of degrading it to a context-free request', async () => {
    const fetchMock = vi.fn(async () => new Response(JSON.stringify({ ok: true }), {
      status: 200,
      headers: { 'content-type': 'application/json' },
    }))
    vi.stubGlobal('fetch', fetchMock)

    const error = await fetchGlobalStudioApi('/assets').catch(cause => cause)

    expect(error).toBeInstanceOf(StudioApiError)
    // A path that was never global is a caller mistake — it must not be
    // retried with a workspace, so it carries its own code.
    expect((error as StudioApiError).code).toBe('PATH_NOT_GLOBAL')
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it('retries through the bound workspace when the host still runs the old bridge', async () => {
    // The host's proxy half is loaded at startup: a plugin update reaches the
    // browser at once, but the host keeps refusing the context-free call until
    // it is restarted. The scoped route reaches the same library.
    const fetchMock = vi.fn(async (_input: unknown, init?: RequestInit) => {
      const headers = (init?.headers ?? {}) as Record<string, string>
      if (headers['X-Dsh-Workspace-Id'] === undefined) {
        return new Response(JSON.stringify({ error: 'missing workspace id', code: 'WORKSPACE_CONTEXT_MISSING' }), {
          status: 400,
          headers: { 'content-type': 'application/json' },
        })
      }
      return new Response(JSON.stringify({ ok: true }), { status: 200, headers: { 'content-type': 'application/json' } })
    })
    vi.stubGlobal('fetch', fetchMock)
    setStudioContext({ workspaceId: 'ws-a' })

    await fetchGlobalStudioApi('/model/profiles')

    expect(fetchMock).toHaveBeenCalledTimes(2)
    const retryHeaders = (fetchMock.mock.calls[1]?.[1] as RequestInit).headers as Record<string, string>
    expect(retryHeaders['X-Dsh-Workspace-Id']).toBe('ws-a')
    expect(isGlobalFallbackActive()).toBe(true)
  })

  it('does not retry without a bound workspace', async () => {
    const fetchMock = vi.fn(async () => new Response(JSON.stringify({ error: 'missing workspace id', code: 'WORKSPACE_CONTEXT_MISSING' }), {
      status: 400,
      headers: { 'content-type': 'application/json' },
    }))
    vi.stubGlobal('fetch', fetchMock)

    const error = await fetchGlobalStudioApi('/model/profiles').catch(cause => cause)

    expect(error).toBeInstanceOf(StudioApiError)
    expect((error as StudioApiError).code).toBe('WORKSPACE_CONTEXT_MISSING')
    expect(fetchMock).toHaveBeenCalledTimes(1)
    expect(isGlobalFallbackActive()).toBe(false)
  })
})
