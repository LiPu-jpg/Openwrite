import { afterEach, describe, expect, it, vi } from 'vitest'
import { API_PROXY_BASE, fetchStudioApi, putStudioApi, setStudioContext, StudioApiError } from '../../src/client/api.ts'

afterEach(() => {
  setStudioContext(null)
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
