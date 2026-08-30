/**
 * Reachability probe for the E2E skip gate. Both services must answer before
 * any browser is launched; Node's fetch does not honor http_proxy, so the
 * loopback probe is proxy-safe even inside the dev shell.
 */

export const DSH_WEB = 'http://127.0.0.1:3080'
export const STUDIO = 'http://127.0.0.1:4567'

async function probe(url) {
  try {
    const response = await fetch(url, { signal: AbortSignal.timeout(2000) })
    return response.ok || response.status < 500
  } catch {
    return false
  }
}

/** @returns {{ ok: boolean, reason: string }} */
export async function probeServices() {
  const [web, studio] = await Promise.all([
    probe(`${DSH_WEB}/`),
    probe(`${STUDIO}/api/health`),
  ])
  if (!web && !studio) return { ok: false, reason: `dsh web (${DSH_WEB}) and Studio (${STUDIO}) both unreachable` }
  if (!web) return { ok: false, reason: `dsh web (${DSH_WEB}) unreachable` }
  if (!studio) return { ok: false, reason: `OpenWrite Studio (${STUDIO}/api/health) unreachable` }
  return { ok: true, reason: '' }
}
