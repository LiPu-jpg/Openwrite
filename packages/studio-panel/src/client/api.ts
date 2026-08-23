/**
 * Same-origin read path to the local OpenWrite Studio API through the host
 * half's proxy route (see src/index.ts API_PROXY_ROUTE). Studio itself sends
 * no CORS headers, so the browser can only reach it via this proxy.
 */

/** Host-half proxy prefix (kept in sync with src/index.ts). */
export const API_PROXY_BASE = '/studio-panel/api'
const READ_TIMEOUT_MS = 20_000

/**
 * Injected share of the data views (大纲 / 资产): JSON fetches against the
 * Studio API. `postStudioApi` only reaches the host proxy's write allowlist
 * (asset domain; see src/index.ts WRITABLE_PATHS).
 */
export interface StudioApiInjected {
  fetchStudioApi: (path: string) => Promise<unknown>
  postStudioApi: (path: string, body: unknown) => Promise<unknown>
  putStudioApi: (path: string, body: unknown) => Promise<unknown>
}

/** Pull a human-readable message out of a Studio error payload when present. */
function errorMessage(data: unknown, status: number): string {
  if (data !== null && typeof data === 'object') {
    const error = (data as { error?: unknown }).error
    if (typeof error === 'string' && error !== '') return error
    if (error !== null && typeof error === 'object') {
      const message = (error as { message?: unknown }).message
      if (typeof message === 'string' && message !== '') return message
    }
    const message = (data as { message?: unknown }).message
    if (typeof message === 'string' && message !== '') return message
  }
  return `HTTP ${String(status)}`
}

/** A Studio API failure that keeps the HTTP status (409 = optimistic-lock conflict). */
export class StudioApiError extends Error {
  readonly status: number

  constructor(message: string, status: number) {
    super(message)
    this.name = 'StudioApiError'
    this.status = status
  }
}

/**
 * GET one Studio API path through the proxy and parse the JSON body. Throws
 * a StudioApiError carrying the upstream status and message on any non-2xx
 * answer (including the proxy's own 502 when Studio is down).
 * @param path - Studio API path beginning with `/`, query string allowed
 *   (e.g. `/assets?kind=character`).
 * @returns the parsed JSON payload.
 */
export async function fetchStudioApi(path: string): Promise<unknown> {
  const controller = new AbortController()
  const timer = window.setTimeout(() => controller.abort(), READ_TIMEOUT_MS)
  let response: Response
  try {
    response = await fetch(`${API_PROXY_BASE}${path}`, {
      headers: { accept: 'application/json' },
      signal: controller.signal,
    })
  } catch (cause: unknown) {
    if (controller.signal.aborted) {
      throw new StudioApiError(`Studio API request timed out (${String(READ_TIMEOUT_MS / 1_000)}s)`, 408)
    }
    throw cause
  } finally {
    window.clearTimeout(timer)
  }
  const text = await response.text()
  let data: unknown = null
  if (text !== '') {
    try {
      data = JSON.parse(text)
    } catch {
      // Non-JSON upstream body: surface as text below rather than failing twice.
      data = null
    }
  }
  if (!response.ok) throw new StudioApiError(errorMessage(data, response.status), response.status)
  return data
}

/**
 * POST a JSON body to one allowlisted Studio API path through the proxy and
 * parse the JSON response. Throws StudioApiError with the upstream status and
 * message on any non-2xx answer (409 = revision conflict, surfaced by the
 * asset editor as "reload and retry").
 * @param path - allowlisted Studio API path (e.g. `/assets/update`).
 * @param body - JSON-serializable request body, forwarded verbatim.
 * @returns the parsed JSON payload.
 */
export async function postStudioApi(path: string, body: unknown): Promise<unknown> {
  return mutateStudioApi('POST', path, body)
}

/** PUT a JSON body to one allowlisted Studio API path. */
export async function putStudioApi(path: string, body: unknown): Promise<unknown> {
  return mutateStudioApi('PUT', path, body)
}

async function mutateStudioApi(method: 'POST' | 'PUT', path: string, body: unknown): Promise<unknown> {
  const response = await fetch(`${API_PROXY_BASE}${path}`, {
    method,
    headers: { 'content-type': 'application/json', accept: 'application/json' },
    body: JSON.stringify(body),
  })
  const text = await response.text()
  let data: unknown = null
  if (text !== '') {
    try {
      data = JSON.parse(text)
    } catch {
      data = null
    }
  }
  if (!response.ok) throw new StudioApiError(errorMessage(data, response.status), response.status)
  return data
}
