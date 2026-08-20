/**
 * Assets view (资产): OpenWrite structured assets (characters / world /
 * progression) as grouped card lists, plus the reference library (资料库)
 * group. Read-only; creation and updates stay with the agent's novel_asset_*
 * and novel_reference_* tools.
 *
 * Wire shapes (verified against OpenWrite tools/studio_http.py do_GET +
 * tools/structured_assets.py StructuredAssetService.list +
 * tools/reference_library.py ReferenceLibraryService.list):
 * - GET /api/assets answers WITH the success envelope — { ok: true, data:
 *   { assets: [...] }, error: null, request_id }. Character/world summaries
 *   carry { kind, id, name, summary, asset_type, aliases, tags, path };
 *   progression summaries carry { kind, id, name, summary, asset_type, tags,
 *   stage_count, path }.
 * - The reference library has NO GET route of its own (/api/reference-library
 *   is a POST-only action dispatcher — even Studio's own status reads POST).
 *   The list IS reachable read-only through GET /api/workspace →
 *   operations.reference_library (workspace() embeds operation_status()).
 *   Entries carry { record: { source_id, title, relative_name, intent
 *   (reference/continuation/canon/migration), total_chars, updated_at },
 *   structure: { status (awaiting_confirmation/confirmed), ... }, analysis:
 *   { status, complete, chunks }, assets }.
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

/** One reference-library entry (the fields this view reads). */
interface ReferenceEntry {
  sourceId: string
  title: string
  intent: string
  structureStatus: string
  analysisStatus: string
  analysisComplete: boolean
  totalChars: number
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

/** Narrow one reference-library entry from operations.reference_library. */
function parseReference(raw: unknown): ReferenceEntry {
  const entry = (raw !== null && typeof raw === 'object' ? raw : {}) as Record<string, unknown>
  const dig = (value: unknown): Record<string, unknown> =>
    (value !== null && typeof value === 'object' ? value : {}) as Record<string, unknown>
  const record = dig(entry['record'])
  const structure = dig(entry['structure'])
  const analysis = dig(entry['analysis'])
  const text = (value: unknown): string => (typeof value === 'string' ? value : '')
  return {
    sourceId: text(record['source_id']),
    title: text(record['title']),
    intent: text(record['intent']),
    structureStatus: text(structure['status']),
    analysisStatus: text(analysis['status']),
    analysisComplete: analysis['complete'] === true,
    totalChars: typeof record['total_chars'] === 'number' ? record['total_chars'] : 0,
  }
}

/** Narrow the workspace payload's reference list (null when the workspace fetch failed). */
function parseReferences(data: unknown): ReferenceEntry[] {
  const root = (data !== null && typeof data === 'object' ? data : {}) as Record<string, unknown>
  const operations = (root['operations'] !== null && typeof root['operations'] === 'object' ? root['operations'] : {}) as Record<string, unknown>
  const list = Array.isArray(operations['reference_library']) ? operations['reference_library'] : []
  return list.map(parseReference)
}

/** Full assets-view props: conversation-view runtime share & injected fetch & locale seat. */
export type AssetsViewProps =
  ConvViewProps & InjectFace<StudioApiInjected> & PropsLocale<'studio-panel'>

export function AssetsView({ fetchStudioApi, t }: AssetsViewProps) {
  const [state, setState] = useState<LoadState>('loading')
  const [assets, setAssets] = useState<AssetSummary[]>([])
  const [references, setReferences] = useState<ReferenceEntry[]>([])
  const [error, setError] = useState('')

  const load = useCallback(() => {
    setState('loading')
    let cancelled = false
    // The reference library rides the workspace payload; its failure must not
    // take the asset groups down with it (and vice versa).
    const assetsPromise = fetchStudioApi('/assets').then(parseAssets)
    const referencesPromise = fetchStudioApi('/workspace').then(parseReferences).catch(() => null)
    void Promise.all([assetsPromise, referencesPromise])
      .then(([assetList, referenceList]) => {
        if (cancelled) return
        setAssets(assetList)
        setReferences(referenceList ?? [])
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

  const intentLabel = (intent: string): string => {
    switch (intent) {
      case 'continuation': return t('reference.intent.continuation')
      case 'canon': return t('reference.intent.canon')
      case 'migration': return t('reference.intent.migration')
      default: return t('reference.intent.reference')
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
        {state === 'ready' && assets.length === 0 && references.length === 0 && (
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
        {state === 'ready' && references.length > 0 && (
          <section className={css.assetGroup}>
            <h3 className={css.assetGroupTitle}>{t('assets.references')}</h3>
            <div className={css.assetGrid}>
              {references.map(entry => (
                <div key={entry.sourceId} className={css.assetCard}>
                  <div className={css.assetCardHead}>
                    <span className={css.nodeTitle}>{entry.title || entry.sourceId}</span>
                    <span className={css.kindBadge}>{intentLabel(entry.intent)}</span>
                  </div>
                  <div className={css.assetMeta}>
                    {entry.structureStatus !== '' && (
                      <span className={css.tag} data-confirmed={entry.structureStatus === 'confirmed'}>
                        {entry.structureStatus === 'confirmed'
                          ? t('reference.structure.confirmed')
                          : t('reference.structure.awaiting_confirmation')}
                      </span>
                    )}
                    <span className={css.tag} data-confirmed={entry.analysisComplete}>
                      {entry.analysisComplete ? t('reference.analysis.complete') : entry.analysisStatus || t('reference.analysis.pending')}
                    </span>
                    {entry.totalChars > 0 && (
                      <span className={css.tag}>{Math.round(entry.totalChars / 1000)}k {t('reference.chars')}</span>
                    )}
                  </div>
                </div>
              ))}
            </div>
          </section>
        )}
      </div>
    </div>
  )
}
