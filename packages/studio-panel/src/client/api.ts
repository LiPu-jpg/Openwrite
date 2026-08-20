/**
 * Same-origin read path to the local OpenWrite Studio API through the host
 * half's proxy route (see src/index.ts API_PROXY_ROUTE). Studio itself sends
 * no CORS headers, so the browser can only reach it via this proxy.
 */

/** Host-half proxy prefix (kept in sync with src/index.ts). */
export const API_PROXY_BASE = '/studio-panel/api'

/**
 * Injected share of the data views (大纲 / 资产): one read-only JSON fetch
 * against the Studio API, e.g. `fetchStudioApi('/outline')`.
 */
export interface StudioApiInjected {
  fetchStudioApi: (path: string) => Promise<unknown>
}

/** Pull a human-readable message out of a Studio error payload when present. */
function errorMessage(data: unknown, status: number): string {
  if (data !== null && typeof data === 'object') {
    const message = (data as { error?: unknown }).error
    if (typeof message === 'string' && message !== '') return message
  }
  return `HTTP ${String(status)}`
}

/**
 * GET one Studio API path through the proxy and parse the JSON body. Throws
 * an Error carrying the upstream message on any non-2xx answer (including the
 * proxy's own 502 when Studio is down).
 * @param path - Studio API path beginning with `/`, query string allowed
 *   (e.g. `/assets?kind=character`).
 * @returns the parsed JSON payload.
 */
export async function fetchStudioApi(path: string): Promise<unknown> {
  const response = await fetch(`${API_PROXY_BASE}${path}`, { headers: { accept: 'application/json' } })
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
  if (!response.ok) throw new Error(errorMessage(data, response.status))
  return data
}
