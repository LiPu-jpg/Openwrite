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

export class StudioClient {
  private readonly baseUrl: string
  private readonly timeoutMs: number

  constructor(options: StudioClientOptions) {
    this.baseUrl = options.baseUrl.replace(/\/+$/, '')
    this.timeoutMs = options.timeoutMs
  }

  /** GET a JSON endpoint. `params` entries are URL-encoded; undefined values are dropped. */
  async getJson(path: string, params: Record<string, string> = {}, signal?: AbortSignal): Promise<JsonValue> {
    const url = new URL(`${this.baseUrl}${path}`)
    for (const [key, value] of Object.entries(params)) url.searchParams.set(key, value)
    const response = await this.request(url, { method: 'GET' }, signal)
    return this.readJson(response)
  }

  /** POST a JSON object with the Studio write credential header. */
  async postJson(path: string, body: JsonObject, signal?: AbortSignal): Promise<JsonValue> {
    const response = await this.request(
      new URL(`${this.baseUrl}${path}`),
      {
        method: 'POST',
        headers: { [WRITE_HEADER]: '1', 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      },
      signal,
    )
    return this.readJson(response)
  }

  /** PUT a JSON object with the Studio write credential header. */
  async putJson(path: string, body: JsonObject, signal?: AbortSignal): Promise<JsonValue> {
    const response = await this.request(
      new URL(`${this.baseUrl}${path}`),
      {
        method: 'PUT',
        headers: { [WRITE_HEADER]: '1', 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      },
      signal,
    )
    return this.readJson(response)
  }

  /** GET a file-download endpoint (export), returning the raw bytes and filename. */
  async download(path: string, params: Record<string, string>, signal?: AbortSignal): Promise<StudioDownload> {
    const url = new URL(`${this.baseUrl}${path}`)
    for (const [key, value] of Object.entries(params)) url.searchParams.set(key, value)
    const response = await this.request(url, { method: 'GET' }, signal)
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
      if (body['ok'] === true && 'data' in body) return body['data']
    }
    if (!response.ok) {
      throw new StudioError(`Studio returned HTTP ${response.status}`, response.status, 'HTTP_ERROR')
    }
    return body
  }
}
