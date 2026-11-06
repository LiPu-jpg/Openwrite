/**
 * Same-origin read path to the local OpenWrite Studio API through the host
 * half's proxy route (registered by @dsh-novel/openwrite-bridge, see
 * packages/openwrite-bridge domain.ts). Studio itself sends no CORS headers,
 * so the browser can only reach it via this proxy.
 *
 * Workspace context (docs/WORKSPACE_CONTEXT_CONTRACT.md §2.2): the browser
 * only ever sends the dsh workspace id (plus an optional session id for
 * audit) — never a path. Every proxied request carries the context headers;
 * with no context bound the panel must not issue *project-scoped* proxied
 * requests at all, so the project-scoped request helpers fail closed with
 * WORKSPACE_CONTEXT_MISSING.
 *
 * The global model library is the one exception: Studio keeps it outside
 * every project, so `fetchGlobalStudioApi` / `postGlobalStudioApi` reach it
 * without any workspace identity (see GLOBAL_STUDIO_PATHS).
 */

/** Host-half proxy prefix (kept in sync with openwrite-bridge domain.ts). */
export const API_PROXY_BASE = '/studio-panel/api'
// A mature novel can make the canonical Workspace snapshot large (hundreds of
// planned chapters and many structured assets). Keep the browser deadline
// above the host proxy's measured cold-read time while callers retain their
// own AbortSignal for context switches and unmounts.
const READ_TIMEOUT_MS = 60_000
// Writes are shorter than a cold read but still unbounded without a deadline:
// a stuck proxy would leave the calling view on its loading branch forever.
const WRITE_TIMEOUT_MS = 120_000

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

/**
 * The global Studio paths: the model profile library and the model route map.
 *
 * Studio keeps them outside every project (the user's preferences directory,
 * `model-profiles.json`) and registers every model route with
 * `requires_project=False`. They are therefore reachable with no Workspace
 * context at all — which is exactly what the host's settings dialog needs,
 * since that surface is opened without a bound workspace. The host proxy
 * mirrors this list in `GLOBAL_PATHS` (openwrite-bridge domain.ts); a request
 * without a workspace id is forwarded unchanged for those paths only.
 */
export const GLOBAL_STUDIO_PATHS = new Set([
  'model',
  'model/test',
  'model/embedding',
  'model/embedding/test',
  'model/embedding/select',
  'model/embedding/delete',
  'model/profiles',
  'model/host-models',
  'model/host-profiles',
  'model/profiles/delete',
  'model/profiles/delete-preview',
  'model/routes',
  'research/preferences',
])

/**
 * Guard for the context-free request helpers: only the global paths may be
 * reached without a Workspace. A typo or a future non-global path fails here
 * instead of silently degrading to a project-less request.
 *
 * The code is deliberately *not* `WORKSPACE_CONTEXT_MISSING`: that code means
 * "the host proxy refused because it wants a workspace id", which is what
 * triggers the stale-host fallback below. A path that was never global is a
 * caller mistake and must not be retried with a workspace.
 */
function assertGlobalPath(path: string): void {
  const key = path.split('?')[0]?.replace(/^\//, '') ?? ''
  if (!GLOBAL_STUDIO_PATHS.has(key)) {
    throw new StudioApiError(`"${path}" is not a global Studio path (PATH_NOT_GLOBAL)`, 400, 'PATH_NOT_GLOBAL')
  }
}

/**
 * Whether a global call had to be answered by the workspace-scoped route.
 *
 * True means the host is still running an older bridge: the proxy half is
 * loaded when the host starts, so a plugin update reaches the browser at once
 * but the host keeps answering with the old rules until it is restarted. The
 * panel keeps working against both hosts, and says so.
 */
let globalFallbackActive = false

/** Whether the stale-host fallback is currently in use. */
export function isGlobalFallbackActive(): boolean {
  return globalFallbackActive
}

/** Forget the stale-host fallback state (test isolation). */
export function resetGlobalFallbackState(): void {
  globalFallbackActive = false
}

/**
 * The scoped headers to retry a global call with, or null when the failure is
 * not the stale host.
 *
 * An old proxy has no global allowlist and refuses the context-free call with
 * WORKSPACE_CONTEXT_MISSING. When a workspace happens to be bound, the scoped
 * call reaches the same library — the model profile library is global either
 * way — so the page keeps working until the host is restarted.
 */
function staleHostFallbackHeaders(cause: unknown): Record<string, string> | null {
  if (!(cause instanceof StudioApiError) || cause.code !== 'WORKSPACE_CONTEXT_MISSING') return null
  if (studioContext === null) return null
  globalFallbackActive = true
  return studioContextHeaders()
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
  return requestJson('GET', path, undefined, studioContextHeaders(), READ_TIMEOUT_MS, signal)
}

/**
 * GET one global Studio API path through the proxy **without** any Workspace
 * context headers.
 *
 * The model library is global, so the host's settings dialog (opened with no
 * bound workspace) can read and edit it. Project-scoped paths are rejected
 * here — they still need `fetchStudioApi`.
 *
 * When the host is still running an older bridge, the proxy refuses the
 * context-free call. The scoped route reaches the same library, so the call
 * is retried with the bound workspace (see `staleHostFallbackHeaders`).
 */
export async function fetchGlobalStudioApi(path: string, signal?: AbortSignal): Promise<unknown> {
  assertGlobalPath(path)
  try {
    const value = await requestJson('GET', path, undefined, {}, READ_TIMEOUT_MS, signal)
    globalFallbackActive = false
    return value
  } catch (cause) {
    const scoped = staleHostFallbackHeaders(cause)
    if (scoped === null) throw cause
    return await requestJson('GET', path, undefined, scoped, READ_TIMEOUT_MS, signal)
  }
}

/**
 * POST a JSON body to one allowlisted global Studio API path through the
 * proxy, without any Workspace context headers.
 */
export async function postGlobalStudioApi(path: string, body: unknown): Promise<unknown> {
  assertGlobalPath(path)
  try {
    const value = await requestJson('POST', path, body, {}, WRITE_TIMEOUT_MS)
    globalFallbackActive = false
    return value
  } catch (cause) {
    const scoped = staleHostFallbackHeaders(cause)
    if (scoped === null) throw cause
    return await requestJson('POST', path, body, scoped, WRITE_TIMEOUT_MS)
  }
}

/**
 * One JSON round trip through the host proxy.
 *
 * `headers` carries the caller's identity: the Workspace context headers for
 * a project-scoped call, or nothing at all for a global one.
 */
async function requestJson(
  method: 'GET' | 'POST' | 'PUT',
  path: string,
  body: unknown,
  headers: Record<string, string>,
  timeoutMs: number,
  signal?: AbortSignal,
): Promise<unknown> {
  const controller = new AbortController()
  const timer = window.setTimeout(() => controller.abort(), timeoutMs)
  const onExternalAbort = () => { controller.abort() }
  signal?.addEventListener('abort', onExternalAbort)
  let response: Response
  try {
    response = await fetch(`${API_PROXY_BASE}${path}`, {
      method,
      headers: {
        accept: 'application/json',
        ...(body === undefined ? {} : { 'content-type': 'application/json' }),
        ...headers,
      },
      ...(body === undefined ? {} : { body: JSON.stringify(body) }),
      signal: controller.signal,
    })
  } catch (cause: unknown) {
    if (controller.signal.aborted && signal?.aborted !== true) {
      throw new StudioApiError(`Studio API request timed out (${String(timeoutMs / 1_000)}s)`, 408)
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
  return requestJson(method, path, body, contextHeaders, WRITE_TIMEOUT_MS)
}
