/**
 * Companion-plugin status: whether the optional integrations (dsh-dog,
 * dsh-ops, dsh-our-free-model) are installed and usable on this host. The
 * section only explains what a companion does here; the one action it offers
 * is writing an OpenWrite model profile that points at the free-model plugin's
 * local gateway.
 *
 * The model profile library is global — Studio keeps it outside every
 * project — so this section reaches it through the context-free global API.
 * The wiring therefore works from the host's settings dialog, with no novel
 * open.
 */

import { useEffect, useState } from 'react'
import { fetchGlobalStudioApi, postGlobalStudioApi } from './api.ts'
import css from './OpenWriteSettings.module.css'

export interface CompanionPluginInfo {
  key: 'dog' | 'ops' | 'freeModel'
  name: string
  npmPackage: string
  repo: string
  url: string
  roleZh: string
  roleEn: string
}

/**
 * The three DSH ecosystem companion plugins OpenWrite natively integrates with.
 * Used in both Settings → Host and the once-per-version release modal.
 */
export const COMPANION_PLUGINS: readonly CompanionPluginInfo[] = [
  {
    key: 'freeModel',
    name: 'dsh-our-free-model',
    npmPackage: '@ebony-vinyl/dsh-our-free-model',
    repo: 'Ebony-Vinyl/dsh-our-free-model',
    url: 'https://github.com/Ebony-Vinyl/dsh-our-free-model',
    roleZh: '免密钥本地转发网关，一键写入写作/评审模型配置，零配置上手创作',
    roleEn: 'Zero-key local model gateway with one-click writing & review routing',
  },
  {
    key: 'ops',
    name: 'dsh-ops',
    npmPackage: 'dsh-ops',
    repo: 'T-Auto/dsh-ops',
    url: 'https://github.com/T-Auto/dsh-ops',
    roleZh: '有界文件工具与渐进式检索，显著降低长篇设定检索 Token 消耗',
    roleEn: 'Bounded file tools & progressive discovery to cut retrieval token cost',
  },
  {
    key: 'dog',
    name: 'dsh-dog',
    npmPackage: '@dsh-external/dsh-dog',
    repo: 'Fun10165/dsh-dog',
    url: 'https://github.com/Fun10165/dsh-dog',
    roleZh: 'DoG 独立交付验证图谱与 dog_* 工具，交付前生成防偏离校验图',
    roleEn: 'Independent DoG delivery verification graph & dog_* tools before handoff',
  },
] as const

export interface OpsPlan {
  files: boolean
  discovery: boolean
  presentation: string
  shell: boolean
  replaceOfficial: boolean
  residentTools: boolean
  residentNames: number
}

export interface CompanionEntry {
  installed: boolean
  usable: boolean
  version: string | null
  reason: string | null
  /** The resolved dsh-ops integration plan, when the companion exposes one. */
  plan?: OpsPlan | null
}

export interface CompanionStatus {
  host: string | null
  dog: CompanionEntry
  ops: CompanionEntry
  freeModel: CompanionEntry
}

/** What the free-model plugin exposes about its local OpenAI-compatible gateway. */
interface FreeModelGateway {
  running: boolean
  baseUrl: string
  key: string
  models: string[]
}

/**
 * The outcome of reading the companion's gateway route. Four different failures
 * used to collapse into one "not switched on" sentence, which told the author a
 * cause that had not been established.
 */
type GatewayRead =
  | { kind: 'ok', gateway: FreeModelGateway }
  | { kind: 'absent' }
  | { kind: 'unavailable', status: number }
  | { kind: 'unreadable', detail: string }
  | { kind: 'shape', detail: string }

export async function fetchCompanions(signal?: AbortSignal): Promise<CompanionStatus | null> {
  const response = await fetch('/studio-panel/companions', signal === undefined ? undefined : { signal })
  if (!response.ok) return null
  return await response.json() as CompanionStatus
}

/**
 * Read the companion's own gateway description. The route is same-origin; its
 * authentication is the companion's own, not something this plugin controls, so
 * an unauthenticated answer is reported rather than assumed away.
 */
async function readFreeModelGateway(signal?: AbortSignal): Promise<GatewayRead> {
  let response: Response
  try {
    response = await fetch('/api/our-free-model/clients', signal === undefined ? undefined : { signal, credentials: 'same-origin' })
  } catch (cause) {
    if (signal?.aborted === true) return { kind: 'absent' }
    return { kind: 'unreadable', detail: cause instanceof Error ? cause.message : String(cause) }
  }
  if (response.status === 404) return { kind: 'absent' }
  if (!response.ok) return { kind: 'unavailable', status: response.status }
  let payload: Partial<FreeModelGateway>
  try { payload = await response.json() as Partial<FreeModelGateway> }
  catch (cause) { return { kind: 'unreadable', detail: cause instanceof Error ? cause.message : String(cause) } }
  if (typeof payload.baseUrl !== 'string' || typeof payload.key !== 'string') {
    return { kind: 'shape', detail: 'the route answered without a gateway address and key' }
  }
  return {
    kind: 'ok',
    gateway: {
      running: payload.running === true,
      baseUrl: payload.baseUrl,
      key: payload.key,
      models: Array.isArray(payload.models) ? payload.models.filter(model => typeof model === 'string') : [],
    },
  }
}

const version = (entry: CompanionEntry) => entry.version ? `（${entry.version}）` : ''

/** One companion line: what it does here, or what to install to get it. */
function describe(label: string, entry: CompanionEntry, installed: string, absent: string): string {
  if (!entry.installed) return `${label}：未安装。${absent}`
  if (!entry.usable) return `${label}：已安装${version(entry)}，但当前宿主不兼容。${entry.reason ?? ''}`
  return `${label}：${installed}${version(entry)}`
}

const GATEWAY_PROFILE_ID = 'our-free-model'

/** The two OpenWrite routes a writing session actually uses. */
const WIRED_ROUTE_KEYS = ['chapter_write', 'review'] as const
const ROUTE_LABELS: Record<string, string> = { chapter_write: '写作', review: '评审' }

/**
 * The route entries that still point somewhere else. Sending only these keys
 * leaves planning/search/research routes exactly as the author set them.
 */
export function routeChanges(routes: Record<string, string>, profileId: string = GATEWAY_PROFILE_ID): Record<string, string> {
  const changes: Record<string, string> = {}
  for (const key of WIRED_ROUTE_KEYS) if (routes[key] !== profileId) changes[key] = profileId
  return changes
}

/** Human-readable current routes, for the pre-write summary. */
export function routeSummary(routes: Record<string, string>): string {
  return WIRED_ROUTE_KEYS
    .map(key => `${ROUTE_LABELS[key]} → ${routes[key] || '默认'}`)
    .join('；')
}

interface ProfileState {
  profile: Record<string, unknown> | undefined
  routes: Record<string, string>
}

/** Read the global profile library once for both the overwrite check and routes. */
async function readProfileState(signal?: AbortSignal): Promise<ProfileState> {
  const payload = await fetchGlobalStudioApi('/model/profiles', signal) as Record<string, unknown>
  const profiles = Array.isArray(payload?.profiles) ? payload.profiles as Record<string, unknown>[] : []
  const rawRoutes = payload?.routes
  const routes: Record<string, string> = {}
  if (rawRoutes !== null && typeof rawRoutes === 'object' && !Array.isArray(rawRoutes)) {
    for (const [key, value] of Object.entries(rawRoutes as Record<string, unknown>)) {
      if (typeof value === 'string' && value !== '') routes[key] = value
    }
  }
  return {
    profile: profiles.find(entry => entry?.id === GATEWAY_PROFILE_ID),
    routes,
  }
}

/**
 * The gateway fields of the OpenWrite model profile that routes writing and
 * review at it. Everything else comes from the profile already on the server:
 * a whole-record upsert would silently drop whatever the author tuned in
 * 「设置 → OpenWrite → 模型」 (temperature, context window, timeout) on a
 * second click.
 */
/** The gateway's OpenAI-compatible endpoint, without doubling a reported /v1. */
function gatewayEndpoint(baseUrl: string): string {
  const base = baseUrl.replace(/\/+$/, '').replace(/\/v1$/, '')
  return `${base}/v1`
}

function gatewayProfile(gateway: FreeModelGateway, model: string, existing?: Record<string, unknown>) {
  const base = existing && typeof existing === 'object' ? existing : {}
  return {
    ...base,
    id: GATEWAY_PROFILE_ID,
    label: typeof base.label === 'string' && base.label !== '' ? base.label : 'Our Free Model',
    provider: 'openai',
    model,
    // The gateway speaks OpenAI chat completions under /v1; a gateway that
    // already reports its /v1 endpoint must not become /v1/v1.
    base_url: gatewayEndpoint(gateway.baseUrl),
    api_format: 'chat',
    auth_source: 'api_key',
    // Persisting the companion's key is the author's decision, not this button's.
    remember_api_key: base.remember_api_key === true,
    api_key: gateway.key,
  }
}

export function CompanionSection({ status }: { status: CompanionStatus | null }): JSX.Element | null {
  const [read, setRead] = useState<GatewayRead>({ kind: 'absent' })
  const [model, setModel] = useState('')
  const [busy, setBusy] = useState(false)
  const [notice, setNotice] = useState('')
  const [confirming, setConfirming] = useState(false)
  const [routes, setRoutes] = useState<Record<string, string>>({})
  const [wireRoutes, setWireRoutes] = useState(true)
  const [plan, setPlan] = useState<{ overwrite: boolean, routes: Record<string, string> }>({ overwrite: false, routes: {} })
  const usable = status?.freeModel.usable === true
  useEffect(() => {
    if (!usable) return
    const controller = new AbortController()
    setRead({ kind: 'absent' })
    void readFreeModelGateway(controller.signal).then(setRead).catch(() => setRead({ kind: 'absent' }))
    return () => controller.abort()
  }, [usable])
  const gateway = read.kind === 'ok' ? read.gateway : null
  const gatewayReady = gateway !== null && gateway.running && gateway.baseUrl.trim() !== ''
  useEffect(() => {
    const models = gateway?.models ?? []
    const first = models[0]
    if (first === undefined) return
    // Adopt the first model only while the author has not chosen one. The
    // gateway arrives after the section has mounted, so this effect can run
    // after the author already picked a model; resetting unconditionally
    // would overwrite that choice and write the wrong model.
    setModel(current => (current === '' || !models.includes(current) ? first : current))
  }, [gateway])
  useEffect(() => {
    if (gateway === null) return
    const controller = new AbortController()
    void readProfileState(controller.signal)
      .then(state => setRoutes(state.routes))
      .catch(() => { /* the write path reports its own read failure */ })
    return () => controller.abort()
  }, [gateway])
  // The early return sits below every hook: the settings page mounts this
  // section before the companion inventory has arrived, and a hook that only
  // runs once the data is there would change the hook count between renders.
  if (!status) return null
  const opsPlan = status.ops.plan
  const opsDetail = opsPlan
    ? `已接入：${opsPlan.files ? `有界文件工具${opsPlan.residentTools ? `（${opsPlan.residentNames} 个常驻）` : ''}` : '不挂文件工具'}${opsPlan.discovery ? ' + 渐进发现' : ''}${opsPlan.shell ? ' + shell' : ''}；${opsPlan.replaceOfficial ? '替换官方文件工具' : '不替换官方文件工具'}`
    : '已接入，提供有界文件工具与渐进发现'
  const descriptions: Record<CompanionPluginInfo['key'], string> = {
    dog: describe('dsh-dog', status.dog, '已安装且宿主放行；会话中可用 dog_* 工具，交付前可按 dog-delivery-verification 技能生成独立校验图', '安装 @dsh-external/dsh-dog 可获得 dog_* 工具与独立校验图。'),
    ops: describe('dsh-ops', status.ops, opsDetail, '安装 dsh-ops 可减少文件检索的 token 消耗。'),
    freeModel: describe('dsh-our-free-model', status.freeModel, '已安装，可一键写入写作/评审模型配置', '安装 @ebony-vinyl/dsh-our-free-model 可免密钥使用免费模型。'),
  }
  const items = COMPANION_PLUGINS.map(plugin => ({ plugin, text: descriptions[plugin.key] }))
  const write = async () => {
    if (gateway === null || model === '' || gateway.baseUrl.trim() === '') return
    setBusy(true); setNotice(''); setConfirming(false)
    try {
      const state = await readProfileState()
      // The same route the model page saves through, so Core validates the
      // profile. The library is global, so this write needs no workspace.
      await postGlobalStudioApi('/model/profiles', gatewayProfile(gateway, model, state.profile))
      const changes = wireRoutes ? routeChanges(state.routes) : {}
      let suffix = ''
      if (Object.keys(changes).length > 0) {
        try {
          // Only the two writing-session routes are sent; planning/search stay
          // exactly as the author configured them.
          await postGlobalStudioApi('/model/routes', { routes: changes })
        } catch (cause) {
          setNotice(`模型配置 ${GATEWAY_PROFILE_ID} 已写入，但写作/评审路由切换失败：${cause instanceof Error ? cause.message : String(cause)}`)
          return
        }
        suffix = '；写作/评审路由已切到该模型'
        setRoutes(current => ({ ...current, ...changes }))
      } else if (wireRoutes) {
        suffix = '；写作/评审路由已指向该模型'
      }
      setNotice(`已写入模型配置 ${GATEWAY_PROFILE_ID}${suffix}。`)
    } catch (cause) {
      setNotice(`写入失败：${cause instanceof Error ? cause.message : String(cause)}`)
    } finally { setBusy(false) }
  }
  const wire = async () => {
    if (gateway === null || model === '' || gateway.baseUrl.trim() === '') return
    const state = await readProfileState().catch(() => ({ profile: undefined, routes: {} }))
    const changes = wireRoutes ? routeChanges(state.routes) : {}
    if (state.profile !== undefined || Object.keys(changes).length > 0) {
      setPlan({ overwrite: state.profile !== undefined, routes: changes })
      setConfirming(true)
      return
    }
    await write()
  }
  return <section><strong>联动插件</strong>
    <p>{`宿主 dsh ${status.host ?? '（版本未知）'}。联动插件均为可选项，未安装时功能不受影响。`}</p>
    <ul className={css.companionList}>{items.map(({ plugin, text }) => <li key={plugin.key} className={css.companionItem}>
      <span>{text}</span>
      <span className={css.companionLinks}>
        <a href={plugin.url} target="_blank" rel="noreferrer">{`GitHub: ${plugin.repo}`}</a>
        <code>{plugin.npmPackage}</code>
      </span>
    </li>)}</ul>
    <p className={css.hint}>如果这些开源联动插件帮到了你的创作，欢迎点开仓库顺手给项目和 OpenWrite 点一颗 ★ Star 支持作者持续维护。</p>
    {usable && <div>
      {read.kind === 'absent' && gateway === null && <p>正在读取免费模型网关…</p>}
      {read.kind === 'absent' && <p>免费模型插件没有提供本地转发：请到「设置 → Our Free Model → 本地转发」打开后再接入。</p>}
      {read.kind === 'unavailable' && <p>{`免费模型的网关读取失败（HTTP ${read.status}）。请重试；持续失败请查看该插件的设置页。`}</p>}
      {read.kind === 'unreadable' && <p>{`免费模型的网关读取失败：${read.detail}`}</p>}
      {read.kind === 'shape' && <p>{`免费模型的网关返回了无法识别的内容：${read.detail}`}</p>}
      {gateway !== null && !gateway.running && <p>免费模型的本地转发没有开启：请到「设置 → Our Free Model → 本地转发」打开后再接入。</p>}
      {gateway !== null && gateway.running && gateway.baseUrl.trim() === '' && <p>免费模型网关没有返回可用地址，请到该插件设置页检查本地转发。</p>}
      {gatewayReady && <>
        <p>{`本地网关 ${gatewayEndpoint(gateway.baseUrl)} 已就绪，可用模型 ${gateway.models.length} 个。`}</p>
        <p>{`当前全局路由：${routeSummary(routes)}（作品内 model_routes 优先）`}</p>
        <label>接入模型<select value={model} onChange={event => setModel(event.target.value)}>
          {gateway.models.map(entry => <option key={entry} value={entry}>{entry}</option>)}
        </select></label>
        <label><input type="checkbox" checked={wireRoutes} onChange={event => setWireRoutes(event.target.checked)} /> 同时把写作/评审切到该模型</label>
        {confirming
          ? <>
            <p>
              {plan.overwrite ? `已存在模型配置 ${GATEWAY_PROFILE_ID}，写入会保留你调过的参数，只更新网关地址、模型与密钥。` : ''}
              {Object.keys(plan.routes).length > 0 ? `写作/评审路由将切换到 ${GATEWAY_PROFILE_ID}（其余路由不变）。` : ''}
              继续？
            </p>
            <button type="button" disabled={busy} onClick={() => void write()}>{busy ? '正在写入…' : (plan.overwrite ? '确认覆盖' : '确认切换')}</button>
            <button type="button" disabled={busy} onClick={() => setConfirming(false)}>取消</button>
          </>
          : <button type="button" disabled={busy || model === ''} onClick={() => void wire()}>{busy ? '正在写入…' : '写入 OpenWrite 模型配置'}</button>}
        {notice !== '' && <p role="status">{notice}</p>}
      </>}
    </div>}
  </section>
}
