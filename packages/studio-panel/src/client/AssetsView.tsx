/**
 * Assets view (资产): OpenWrite structured assets (characters / world /
 * progression) as grouped card lists. Read-only; creation and updates stay
 * with the agent's novel_asset_* tools.
 *
 * Wire shape (verified against OpenWrite tools/studio_http.py do_GET +
 * tools/structured_assets.py StructuredAssetService.list): GET /api/assets
 * answers WITH the success envelope — { ok: true, data: { assets: [...] },
 * error: null, request_id }. Character/world summaries carry { kind, id,
 * name, summary, asset_type, aliases, tags, path }; progression summaries
 * carry { kind, id, name, summary, asset_type, tags, stage_count, path }.
 */

import { useCallback, useEffect, useState } from 'react'
import type { ConvViewProps } from '@deepseek-ai/dsh-client-ui-conversation/client'
import type { InjectFace, PropsLocale } from '@deepseek-ai/dsh-client-ui-slots'
import type { StudioApiInjected } from './api.ts'
import css from './views.module.css'

/** One asset summary (the fields this view reads; the payload carries more). */
interface AssetSummary {
  kind: string
  id: string
  name: string
  summary: string
  assetType: string
  tags: string[]
  stageCount: number | null
}

type LoadState = 'loading' | 'error' | 'ready'

/** Group order and locale keys; unknown kinds land in 'other'. */
const KNOWN_KINDS = ['character', 'world', 'progression'] as const

/** Narrow one wire summary, tolerating missing/extra fields. */
function parseAsset(raw: unknown): AssetSummary {
  const record = (raw !== null && typeof raw === 'object' ? raw : {}) as Record<string, unknown>
  const text = (value: unknown): string => (typeof value === 'string' ? value : '')
  return {
    kind: text(record['kind']),
    id: text(record['id']),
    name: text(record['name']),
    summary: text(record['summary']),
    assetType: text(record['asset_type']),
    tags: Array.isArray(record['tags']) ? record['tags'].filter((tag): tag is string => typeof tag === 'string') : [],
    stageCount: typeof record['stage_count'] === 'number' ? record['stage_count'] : null,
  }
}

/** Unwrap the success envelope and narrow the asset list (empty on garbage). */
function parseAssets(data: unknown): AssetSummary[] {
  const envelope = (data !== null && typeof data === 'object' ? data : {}) as Record<string, unknown>
  const inner = (envelope['data'] !== null && typeof envelope['data'] === 'object' ? envelope['data'] : {}) as Record<string, unknown>
  const list = Array.isArray(inner['assets']) ? inner['assets'] : []
  return list.map(parseAsset)
}

/** Full assets-view props: conversation-view runtime share & injected fetch & locale seat. */
export type AssetsViewProps =
  ConvViewProps & InjectFace<StudioApiInjected> & PropsLocale<'studio-panel'>

export function AssetsView({ fetchStudioApi, t }: AssetsViewProps) {
  const [state, setState] = useState<LoadState>('loading')
  const [assets, setAssets] = useState<AssetSummary[]>([])
  const [error, setError] = useState('')

  const load = useCallback(() => {
    setState('loading')
    let cancelled = false
    fetchStudioApi('/assets')
      .then((data) => {
        if (cancelled) return
        setAssets(parseAssets(data))
        setState('ready')
      })
      .catch((cause: unknown) => {
        if (cancelled) return
        setError(cause instanceof Error ? cause.message : String(cause))
        setState('error')
      })
    return () => { cancelled = true }
  }, [fetchStudioApi])

  useEffect(() => load(), [load])

  const kindLabel = (kind: string): string => {
    switch (kind) {
      case 'character': return t('assets.character')
      case 'world': return t('assets.world')
      case 'progression': return t('assets.progression')
      default: return t('assets.other')
    }
  }

  const groups: { kind: string; items: AssetSummary[] }[] = []
  for (const kind of [...KNOWN_KINDS] as string[]) {
    const items = assets.filter(asset => asset.kind === kind)
    if (items.length > 0) groups.push({ kind, items })
  }
  const others = assets.filter(asset => !(KNOWN_KINDS as readonly string[]).includes(asset.kind))
  if (others.length > 0) groups.push({ kind: 'other', items: others })

  return (
    <div className={css.root}>
      <div className={css.toolbar}>
        <button type="button" className={css.button} onClick={() => { load() }}>
          {t('refresh')}
        </button>
      </div>
      <div className={css.body}>
        {state === 'loading' && <div className={css.notice}>{t('loading')}</div>}
        {state === 'error' && (
          <div className={css.notice}>
            <span className={css.errorText}>{error}</span>
            <button type="button" className={css.button} onClick={() => { load() }}>{t('retry')}</button>
          </div>
        )}
        {state === 'ready' && assets.length === 0 && (
          <div className={css.notice}>{t('assets.empty')}</div>
        )}
        {state === 'ready' && groups.map(group => (
          <section key={group.kind} className={css.assetGroup}>
            <h3 className={css.assetGroupTitle}>{kindLabel(group.kind)}</h3>
            <div className={css.assetGrid}>
              {group.items.map(asset => (
                <div key={`${asset.kind}:${asset.id}`} className={css.assetCard}>
                  <div className={css.assetCardHead}>
                    <span className={css.nodeTitle}>{asset.name || asset.id}</span>
                    {asset.assetType !== '' && (
                      <span className={css.kindBadge}>{asset.assetType}</span>
                    )}
                  </div>
                  {asset.summary !== '' && <div className={css.nodeSummary}>{asset.summary}</div>}
                  <div className={css.assetMeta}>
                    {asset.stageCount !== null && (
                      <span className={css.tag}>{asset.stageCount} {t('assets.stages')}</span>
                    )}
                    {asset.tags.map(tag => <span key={tag} className={css.tag}>{tag}</span>)}
                  </div>
                </div>
              ))}
            </div>
          </section>
        ))}
      </div>
    </div>
  )
}
