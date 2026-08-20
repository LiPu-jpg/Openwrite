/**
 * Browser studio-panel plugin contributing one entry (稿件) to the
 * conversation view slot, without defining a service — the ui-trajectory
 * registration pattern.
 */
import type { Context } from '@deepseek-ai/cordis'
// Type-only: pulls the locale plugin's Context merge (ctx.locale).
import type {} from '@deepseek-ai/dsh-client-locale/client'
// Type-only: the 'conversation.view' SlotMap row (declared by the slot's
// owning package) must be in the program for the register call to type.
import type {} from '@deepseek-ai/dsh-client-ui-conversation/client'
import { en, NS, zh } from './locales.ts'
import { StudioView, type StudioViewInjected } from './StudioView.tsx'

/** Required services: the conversation slot and the locale service. */
export const inject = ['slots', 'locale']

/**
 * Schema default baked into the bundle: the fallback when the host half's
 * config route is absent (server-less profile) or unreadable. Keep in sync
 * with the host-side Config schema default in src/index.ts.
 */
const DEFAULT_STUDIO_URL = 'http://127.0.0.1:4567'

/** Host-half config endpoint (same-origin; see src/index.ts CONFIG_ROUTE). */
const CONFIG_ENDPOINT = '/studio-panel/config.json'

/**
 * Resolve the configured Studio base URL through the host half's config
 * route. Any failure (route absent, non-JSON, malformed payload) falls back
 * to the schema default — the iframe then simply shows Studio's absence.
 */
async function resolveStudioUrl(): Promise<string> {
  try {
    const response = await fetch(CONFIG_ENDPOINT, { headers: { accept: 'application/json' } })
    if (!response.ok) throw new Error(`studio-panel: config route answered ${String(response.status)}`)
    const data: unknown = await response.json()
    const url = (data as { studioUrl?: unknown }).studioUrl
    return typeof url === 'string' && url !== '' ? url : DEFAULT_STUDIO_URL
  } catch {
    return DEFAULT_STUDIO_URL
  }
}

/**
 * Client plugin body: register the 稿件 view tab. The registration rides the
 * slot service's inject wrapper, so it waits on the conversation package's
 * declaration and plugin unload removes the tab.
 * @param ctx - client root context.
 */
export function apply(ctx: Context): void {
  ctx.effect(() => ctx.locale.register(NS, { zh, en }), 'studio-panel: dictionaries')
  // Registration-time text (the view tab label) reads through the bound
  // translate as a thunk, so it follows the active locale without
  // re-registration.
  const t = ctx.locale.bind(NS)
  ctx.slots.inject('conversation.view', () => ctx.slots.register({
    name: 'conversation.view',
    id: 'studio',
    order: 20,
    locale: NS,
    label: () => t('view.studio'),
    inject: (): StudioViewInjected => ({ resolveStudioUrl }),
  }, StudioView))
}
