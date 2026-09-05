/**
 * Shared HTTP client for the OpenWrite Studio action surface.
 *
 * Contract (verified against OpenWrite `tools/studio_http.py` and
 * `tools/studio_contracts.py`): GETs are unauthenticated; every POST/PUT must
 * carry `X-OpenWrite-Studio: 1` or the server answers 403. Error responses are
 * JSON `{error, code, recoverable, details, request_id}` with a non-2xx
 * status; some routes wrap success in `{ok: true, data, ...}` which this
 * client unwraps transparently.
 */

/** JSON value as exchanged with the Studio API. */
export type JsonValue = string | number | boolean | null | JsonValue[] | { [key: string]: JsonValue }

/** A JSON object payload. */
export type JsonObject = { [key: string]: JsonValue }

/** Header OpenWrite requires on every write request (POST/PUT). */
const WRITE_HEADER = 'X-OpenWrite-Studio'

/**
 * Request-scoped Workspace identity, per docs/WORKSPACE_CONTEXT_CONTRACT.md §3.
 * `workspaceRoot` is the canonical (realpath'd) absolute path — the only root
 * identity; the id/epoch fields are audit/diagnostic metadata.
 */
export interface WorkspaceContext {
  workspaceRoot: string
  workspaceId?: string
  sessionId?: string
  contextEpoch?: number
  toolCallId?: string
  rootCallId?: string
  toolName?: string
}

/** A normalized Studio failure: HTTP status plus the server's machine-readable code. */
export class StudioError extends Error {
  readonly status: number
  readonly code: string
  readonly details: JsonValue

  constructor(message: string, status: number, code: string, details: JsonValue = null) {
    super(message)
    this.name = 'StudioError'
    this.status = status
    this.code = code
    this.details = details
  }
}

export interface StudioClientOptions {
  /** Studio base URL, e.g. `http://127.0.0.1:4567`. */
  baseUrl: string
  /** Per-request timeout in milliseconds (backstop; the dsh timeout policy owns the budget). */
  timeoutMs: number
  /** Notify the owning domain service after a successful mutation. */
  onMutation?: (path: string, context?: WorkspaceContext) => void
  /** Request-scoped Workspace context stamped onto every request (see `scoped`). */
  context?: WorkspaceContext
}

/** A downloaded export file. */
export interface StudioDownload {
  filename: string
  contentType: string
  content: Uint8Array
}

/** Narrow `JSON.parse` output to the JsonValue union without `any`. */
function asJson(value: unknown): JsonValue {
  // Studio only ever sends JSON; unrepresentable values degrade to null rather
  // than leaking an untyped `any` into tool output.
  return (value === undefined ? null : value) as JsonValue
}

/** Parse a `Content-Disposition: attachment; filename*=UTF-8''...` header. */
function parseDispositionFilename(header: string | null): string | undefined {
  if (header === null) return undefined
  const encoded = /filename\*=UTF-8''([^;]+)/i.exec(header)
  if (encoded?.[1] !== undefined) {
    try {
      return decodeURIComponent(encoded[1])
    } catch {
      // Malformed percent-encoding: fall through to the plain filename form.
    }
  }
  const plain = /filename="?([^";]+)"?/i.exec(header)
  return plain?.[1]
}

/** Query parameters; array values become repeated `key=v1&key=v2` entries. */
export type QueryParams = Record<string, string | string[]>

/** Set query params on a URL, expanding array values into repeated entries. */
function applyParams(url: URL, params: QueryParams): void {
  for (const [key, value] of Object.entries(params)) {
    if (Array.isArray(value)) {
      for (const item of value) url.searchParams.append(key, item)
    } else {
      url.searchParams.set(key, value)
    }
  }
}

export class StudioClient {
  private readonly baseUrl: string
  private readonly timeoutMs: number
  private readonly onMutation: ((path: string, context?: WorkspaceContext) => void) | undefined
  /** Workspace context stamped onto every request; undefined for legacy (unscoped) clients. */
  readonly context: WorkspaceContext | undefined

  constructor(options: StudioClientOptions) {
    this.baseUrl = options.baseUrl.replace(/\/+$/, '')
    this.timeoutMs = options.timeoutMs
    this.onMutation = options.onMutation
    this.context = options.context
  }

  /**
   * Derive a lightweight request-scoped client sharing baseUrl/timeout/onMutation.
   * Every request it makes carries the §3 context headers, and mutation
   * notifications report this context so invalidation stays per-root.
   */
  scoped(context: WorkspaceContext): StudioClient {
    return new StudioClient({ baseUrl: this.baseUrl, timeoutMs: this.timeoutMs, onMutation: this.onMutation, context })
  }

  /** §3 context headers; empty for a legacy (unscoped) client. */
  private contextHeaders(): Record<string, string> {
    const context = this.context
    if (context === undefined) return {}
    const headers: Record<string, string> = { 'X-OpenWrite-Workspace-Root': context.workspaceRoot }
    if (context.workspaceId !== undefined) headers['X-OpenWrite-Workspace-Id'] = context.workspaceId
    if (context.sessionId !== undefined) headers['X-OpenWrite-Session-Id'] = context.sessionId
    if (context.contextEpoch !== undefined) headers['X-OpenWrite-Context-Epoch'] = String(context.contextEpoch)
    if (context.toolCallId !== undefined) headers['X-OpenWrite-Tool-Call-Id'] = context.toolCallId
    if (context.rootCallId !== undefined) headers['X-OpenWrite-Root-Call-Id'] = context.rootCallId
    if (context.toolName !== undefined) headers['X-OpenWrite-Tool-Name'] = context.toolName
    return headers
  }

  /** GET a JSON endpoint. `params` entries are URL-encoded; undefined values are dropped. */
  async getJson(path: string, params: QueryParams = {}, signal?: AbortSignal): Promise<JsonValue> {
    const url = new URL(`${this.baseUrl}${path}`)
    applyParams(url, params)
    const response = await this.request(url, { method: 'GET', headers: this.contextHeaders() }, signal)
    return this.readJson(response)
  }

  /** POST a JSON object with the Studio write credential header. */
  async postJson(path: string, body: JsonObject, signal?: AbortSignal): Promise<JsonValue> {
    const response = await this.request(
      new URL(`${this.baseUrl}${path}`),
      {
        method: 'POST',
        headers: { [WRITE_HEADER]: '1', ...this.contextHeaders(), 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      },
      signal,
    )
    const result = await this.readJson(response)
    this.onMutation?.(path, this.context)
    return result
  }

  /** PUT a JSON object with the Studio write credential header. */
  async putJson(path: string, body: JsonObject, signal?: AbortSignal): Promise<JsonValue> {
    const response = await this.request(
      new URL(`${this.baseUrl}${path}`),
      {
        method: 'PUT',
        headers: { [WRITE_HEADER]: '1', ...this.contextHeaders(), 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      },
      signal,
    )
    const result = await this.readJson(response)
    this.onMutation?.(path, this.context)
    return result
  }

  /** GET a file-download endpoint (export), returning the raw bytes and filename. */
  async download(path: string, params: QueryParams, signal?: AbortSignal): Promise<StudioDownload> {
    const url = new URL(`${this.baseUrl}${path}`)
    applyParams(url, params)
    const response = await this.request(url, { method: 'GET', headers: this.contextHeaders() }, signal)
    if (!response.ok) {
      // Error downloads are still JSON payloads.
      await this.readJson(response)
    }
    const content = new Uint8Array(await response.arrayBuffer())
    return {
      filename: parseDispositionFilename(response.headers.get('content-disposition')) ?? 'export.bin',
      contentType: response.headers.get('content-type') ?? 'application/octet-stream',
      content,
    }
  }

  /** One fetch honoring both the caller's abort signal and the configured timeout. */
  private async request(url: URL, init: RequestInit, signal: AbortSignal | undefined): Promise<Response> {
    const signals = [AbortSignal.timeout(this.timeoutMs)]
    if (signal !== undefined) signals.push(signal)
    try {
      return await fetch(url, { ...init, signal: AbortSignal.any(signals) })
    } catch (error: unknown) {
      if (signal?.aborted) throw error
      throw new StudioError(`Studio request failed: ${error instanceof Error ? error.message : String(error)}`, 0, 'NETWORK_ERROR')
    }
  }

  /**
   * Read a JSON response, throwing a normalized StudioError for non-2xx statuses
   * and for bodies carrying the server's `{error, code}` contract. Success
   * envelopes (`{ok: true, data}`) are unwrapped to their `data` payload.
   */
  private async readJson(response: Response): Promise<JsonValue> {
    let parsed: unknown
    try {
      parsed = await response.json()
    } catch {
      throw new StudioError(`Studio returned HTTP ${response.status} with a non-JSON body`, response.status, 'INVALID_RESPONSE')
    }
    const body = asJson(parsed)
    if (typeof body === 'object' && body !== null && !Array.isArray(body)) {
      const error = body['error']
      if (typeof error === 'string' && error.length > 0) {
        const code = typeof body['code'] === 'string' ? body['code'] : 'STUDIO_ERROR'
        const details: JsonValue = 'details' in body ? body['details'] : null
        throw new StudioError(error, response.status, code, details)
      }
      // HTTP status remains authoritative even when a proxy or incompatible
      // server sends a success-shaped envelope with an error status.
      if (response.ok && body['ok'] === true && 'data' in body) return body['data']
    }
    if (!response.ok) {
      throw new StudioError(`Studio returned HTTP ${response.status}`, response.status, 'HTTP_ERROR')
    }
    return body
  }
}
