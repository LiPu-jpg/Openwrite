/**
 * Same-origin read path to the local OpenWrite Studio API through the host
 * half's proxy route (registered by @dsh-novel/openwrite-bridge, see
 * packages/openwrite-bridge domain.ts). Studio itself sends no CORS headers,
 * so the browser can only reach it via this proxy.
 *
 * Workspace context (docs/WORKSPACE_CONTEXT_CONTRACT.md §2.2): the browser
 * only ever sends the dsh workspace id (plus an optional session id for
 * audit) — never a path. Every proxied request carries the context headers;
 * with no context bound the panel must not issue proxied requests at all, so
 * all three request helpers fail closed with WORKSPACE_CONTEXT_MISSING.
 */

/** Host-half proxy prefix (kept in sync with openwrite-bridge domain.ts). */
export const API_PROXY_BASE = '/studio-panel/api'
// A mature novel can make the canonical Workspace snapshot large (hundreds of
// planned chapters and many structured assets). Keep the browser deadline
// above the host proxy's measured cold-read time while callers retain their
// own AbortSignal for context switches and unmounts.
const READ_TIMEOUT_MS = 60_000

/** Browser-side Workspace identity stamped onto every proxied request. */
export interface StudioContext {
  workspaceId: string
  sessionId?: string | undefined
}

let studioContext: StudioContext | null = null

/**
 * Bind (or clear, with null) the Workspace context for all proxied requests.
 * Owned by the WorkbenchStore context barrier — components never call this
 * directly; they go through `workbenchStore.setContext`.
 */
export function setStudioContext(next: StudioContext | null): void {
  studioContext = next === null ? null : { ...next }
}

/** The currently bound Workspace context, or null when unbound. */
export function getStudioContext(): StudioContext | null {
  return studioContext
}

/**
 * Context headers for the contract's browser wire format. Throws a
 * StudioApiError (code WORKSPACE_CONTEXT_MISSING) when no context is bound —
 * fail closed, never fall back to a context-less request.
 */
export function studioContextHeaders(): Record<string, string> {
  if (studioContext === null) {
    throw new StudioApiError('No dsh Workspace is bound to this panel (WORKSPACE_CONTEXT_MISSING)', 400, 'WORKSPACE_CONTEXT_MISSING')
  }
  const headers: Record<string, string> = { 'X-Dsh-Workspace-Id': studioContext.workspaceId }
  if (studioContext.sessionId !== undefined) headers['X-Dsh-Session-Id'] = studioContext.sessionId
  return headers
}

/**
 * Injected share of the data views (大纲 / 资产): JSON fetches against the
 * Studio API. `postStudioApi` only reaches the host proxy's write allowlist
 * (asset domain; see openwrite-bridge domain.ts WRITABLE_PATHS).
 */
export interface StudioApiInjected {
  fetchStudioApi: (path: string) => Promise<unknown>
  postStudioApi: (path: string, body: unknown) => Promise<unknown>
  putStudioApi: (path: string, body: unknown, context?: StudioContext) => Promise<unknown>
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

/** Pull the contract error code out of a Studio/proxy error payload when present. */
function errorCode(data: unknown): string | undefined {
  if (data !== null && typeof data === 'object') {
    const code = (data as { code?: unknown }).code
    if (typeof code === 'string' && code !== '') return code
  }
  return undefined
}

function errorDetails(data: unknown): Record<string, unknown> {
  if (data !== null && typeof data === 'object') {
    const details = (data as { details?: unknown }).details
    if (details !== null && typeof details === 'object' && !Array.isArray(details)) {
      return details as Record<string, unknown>
    }
  }
  return {}
}

/** A Studio API failure that keeps the HTTP status (409 = optimistic-lock conflict) and contract error code. */
export class StudioApiError extends Error {
  readonly status: number
  readonly code: string | undefined
  readonly details: Readonly<Record<string, unknown>>

  constructor(message: string, status: number, code?: string, details: Record<string, unknown> = {}) {
    super(message)
    this.name = 'StudioApiError'
    this.status = status
    this.code = code
    this.details = details
  }
}

/**
 * GET one Studio API path through the proxy and parse the JSON body. Throws
 * a StudioApiError carrying the upstream status and message on any non-2xx
 * answer (including the proxy's own 502 when Studio is down).
 * @param path - Studio API path beginning with `/`, query string allowed
 *   (e.g. `/assets?kind=character`).
 * @param signal - optional caller abort (context switches cancel in-flight reads).
 * @returns the parsed JSON payload.
 */
export async function fetchStudioApi(path: string, signal?: AbortSignal): Promise<unknown> {
  const controller = new AbortController()
  const timer = window.setTimeout(() => controller.abort(), READ_TIMEOUT_MS)
  const onExternalAbort = () => { controller.abort() }
  signal?.addEventListener('abort', onExternalAbort)
  let response: Response
  try {
    response = await fetch(`${API_PROXY_BASE}${path}`, {
      headers: { accept: 'application/json', ...studioContextHeaders() },
      signal: controller.signal,
    })
  } catch (cause: unknown) {
    if (controller.signal.aborted && signal?.aborted !== true) {
      throw new StudioApiError(`Studio API request timed out (${String(READ_TIMEOUT_MS / 1_000)}s)`, 408)
    }
    throw cause
  } finally {
    window.clearTimeout(timer)
    signal?.removeEventListener('abort', onExternalAbort)
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
  if (!response.ok) throw new StudioApiError(errorMessage(data, response.status), response.status, errorCode(data), errorDetails(data))
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
export async function putStudioApi(path: string, body: unknown, context?: StudioContext): Promise<unknown> {
  return mutateStudioApi('PUT', path, body, context)
}

async function mutateStudioApi(
  method: 'POST' | 'PUT',
  path: string,
  body: unknown,
  context?: StudioContext,
): Promise<unknown> {
  const contextHeaders = context === undefined
    ? studioContextHeaders()
    : {
        'X-Dsh-Workspace-Id': context.workspaceId,
        ...(context.sessionId === undefined ? {} : { 'X-Dsh-Session-Id': context.sessionId }),
      }
  const response = await fetch(`${API_PROXY_BASE}${path}`, {
    method,
    headers: { 'content-type': 'application/json', accept: 'application/json', ...contextHeaders },
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
  if (!response.ok) throw new StudioApiError(errorMessage(data, response.status), response.status, errorCode(data), errorDetails(data))
  return data
}
