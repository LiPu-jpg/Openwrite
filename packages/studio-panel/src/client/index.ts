/**
 * Browser studio-panel plugin: the 稿件 (Studio iframe), 大纲 (outline tree)
 * and 资产 (asset board) conversation view tabs, plus the keyed
 * novel_review_chapter report card — all registered through the slot system,
 * no service defined (the ui-trajectory registration pattern).
 */
import type { Context } from '@deepseek-ai/cordis'
// Type-only: pulls the locale plugin's Context merge (ctx.locale).
import type {} from '@deepseek-ai/dsh-client-locale/client'
// Type-only: the 'conversation.view' SlotMap row (declared by the slot's
// owning package) must be in the program for the register calls to type.
import type {} from '@deepseek-ai/dsh-client-ui-conversation/client'
// Type-only: the 'tool.call.toolview' SlotMap row (declared by ui-tool).
import type {} from '@deepseek-ai/dsh-client-ui-tool/client'
import { fetchStudioApi, postStudioApi, type StudioApiInjected } from './api.ts'
import { AssetsView } from './AssetsView.tsx'
import { GraphView } from './GraphView.tsx'
import { en, NS, zh } from './locales.ts'
import { OutlineView } from './OutlineView.tsx'
import { NovelReviewCard } from './ReviewCard.tsx'
import { StudioView, type StudioViewInjected } from './StudioView.tsx'
import { TasksView } from './TasksView.tsx'

/** Required services: the conversation/tool slots and the locale service. */
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

/** The data views share one read-only Studio fetch face plus the allowlisted write face. */
const studioApi: StudioApiInjected = { fetchStudioApi, postStudioApi }

/**
 * Client plugin body: register the three view tabs and the review tool card.
 * Registrations ride the slot service's inject wrapper, so they wait on the
 * owning packages' declarations and plugin unload removes the entries.
 * @param ctx - client root context.
 */
export function apply(ctx: Context): void {
  ctx.effect(() => ctx.locale.register(NS, { zh, en }), 'studio-panel: dictionaries')
  // Registration-time text (the view tab labels) reads through the bound
  // translate as a thunk, so it follows the active locale without
  // re-registration.
  const t = ctx.locale.bind(NS)
  ctx.slots.inject('conversation.view', function* () {
    yield ctx.slots.register({
      name: 'conversation.view',
      id: 'studio',
      order: 20,
      locale: NS,
      label: () => t('view.studio'),
      inject: (): StudioViewInjected => ({ resolveStudioUrl }),
    }, StudioView)
    yield ctx.slots.register({
      name: 'conversation.view',
      id: 'outline',
      order: 21,
      locale: NS,
      label: () => t('view.outline'),
      inject: (): StudioApiInjected => studioApi,
    }, OutlineView)
    yield ctx.slots.register({
      name: 'conversation.view',
      id: 'assets',
      order: 22,
      locale: NS,
      label: () => t('view.assets'),
      inject: (): StudioApiInjected => studioApi,
    }, AssetsView)
    yield ctx.slots.register({
      name: 'conversation.view',
      id: 'tasks',
      order: 23,
      locale: NS,
      label: () => t('view.tasks'),
      inject: (): StudioApiInjected => studioApi,
    }, TasksView)
    yield ctx.slots.register({
      name: 'conversation.view',
      id: 'graph',
      order: 24,
      locale: NS,
      label: () => t('view.graph'),
      inject: (): StudioApiInjected => studioApi,
    }, GraphView)
  })
  // The novel_review_chapter report card: keyed entry of the Tool-owned
  // toolview hole (the bash-sample registrant posture).
  ctx.slots.inject('tool.call.toolview', () =>
    ctx.slots.register({ name: 'tool.call.toolview', key: 'novel_review_chapter', locale: NS }, NovelReviewCard))
}
