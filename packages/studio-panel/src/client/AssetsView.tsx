/**
 * Assets view (资产): OpenWrite's structured canon library (Studio's 资料库)
 * rendered natively — segmented sections for 角色 / 设定 (grouped by
 * subcategory) / 进阶体系 / 参考作品 / 作品核心, with lazy per-card detail
 * expansion (fields, relations, body). Read-only; creation and updates stay
 * with the agent's novel_asset_* / novel_reference_* tools.
 *
 * Wire shapes (verified against OpenWrite tools/studio_http.py do_GET,
 * tools/structured_assets.py, tools/world_query.py get_asset_relation_view,
 * tools/studio_application.py workspace/_document_groups/read_document):
 * - GET /api/assets?kind=X — enveloped { ok, data: { assets: [...] } }.
 *   Summaries: character/world { kind, id, name, summary, asset_type,
 *   aliases, tags, path }; progression adds { stage_count }.
 * - GET /api/assets/{kind}/{id} — enveloped detail { kind, id, name,
 *   data: <front-matter/YAML dict>, body_markdown, path, revision } +
 *   character/world only: relation_view { confirmed, registered, suggested,
 *   incoming, counts } with items { target, name, kind, note, origin,
 *   direction, resolved }.
 * - GET /api/workspace — NOT enveloped. documents.core[] is the 作品核心
 *   document list { path, title, subtitle (category_label), category, ... };
 *   operations.reference_library is the 参考作品 (reference works) list —
 *   note this is Studio's data-view="deconstruct" surface, NOT the 资料库
 *   nav entry (which is this structured asset library).
 * - GET /api/document?path=<p> — NOT enveloped { path, title, content,
 *   version, revision, ... }; used for 作品核心 document bodies.
 */

import { useCallback, useEffect, useRef, useState } from 'react'
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
  aliases: string[]
  tags: string[]
  stageCount: number | null
}

/** One reference-work entry from operations.reference_library. */
interface ReferenceEntry {
  sourceId: string
  title: string
  intent: string
  structureStatus: string
  analysisStatus: string
  analysisComplete: boolean
  totalChars: number
}

/** One 作品核心 document from workspace documents.core. */
interface CoreDoc {
  path: string
  title: string
  categoryLabel: string
}

/** One relation row of an asset detail. */
interface RelationItem {
  name: string
  note: string
  direction: 'outgoing' | 'incoming'
  origin: string
  resolved: boolean
}

/** Parsed asset detail: scalar fields, relations, and the markdown body. */
interface AssetDetail {
  fields: { key: string; value: string }[]
  relations: RelationItem[]
  body: string
}

/** Per-card detail cache entry. */
type DetailState =
  | { status: 'loading' }
  | { status: 'error'; message: string }
  | { status: 'ready'; detail: AssetDetail }

type DocState =
  | { status: 'loading' }
  | { status: 'error'; message: string }
  | { status: 'ready'; title: string; content: string }

type LoadState = 'loading' | 'error' | 'ready'

type Segment = 'characters' | 'world' | 'progression' | 'references' | 'core'

const SEGMENTS: readonly Segment[] = ['characters', 'world', 'progression', 'references', 'core']

/** Fields already surfaced on the card chrome; skipped in the detail field list. */
const DETAIL_SKIP_FIELDS = new Set(['id', 'name', 'summary', 'aliases', 'tags'])

/** Narrow one wire summary, tolerating missing/extra fields. */
function parseAsset(raw: unknown): AssetSummary {
  const record = (raw !== null && typeof raw === 'object' ? raw : {}) as Record<string, unknown>
  const text = (value: unknown): string => (typeof value === 'string' ? value : '')
  const strings = (value: unknown): string[] =>
    Array.isArray(value) ? value.filter((item): item is string => typeof item === 'string' && item !== '') : []
  return {
    kind: text(record['kind']),
    id: text(record['id']),
    name: text(record['name']),
    summary: text(record['summary']),
    assetType: text(record['asset_type']),
    aliases: strings(record['aliases']),
    tags: strings(record['tags']),
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

/** Narrow one reference-work entry from operations.reference_library. */
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

/** Narrow one 作品核心 document summary. */
function parseCoreDoc(raw: unknown): CoreDoc {
  const record = (raw !== null && typeof raw === 'object' ? raw : {}) as Record<string, unknown>
  const text = (value: unknown): string => (typeof value === 'string' ? value : '')
  return {
    path: text(record['path']),
    title: text(record['title']),
    categoryLabel: text(record['category_label']) || text(record['subtitle']),
  }
}

/** Narrow the workspace payload's reference list and core documents. */
function parseWorkspace(data: unknown): { references: ReferenceEntry[]; coreDocs: CoreDoc[] } {
  const root = (data !== null && typeof data === 'object' ? data : {}) as Record<string, unknown>
  const dig = (value: unknown): Record<string, unknown> =>
    (value !== null && typeof value === 'object' ? value : {}) as Record<string, unknown>
  const operations = dig(root['operations'])
  const documents = dig(root['documents'])
  return {
    references: (Array.isArray(operations['reference_library']) ? operations['reference_library'] : []).map(parseReference),
    coreDocs: (Array.isArray(documents['core']) ? documents['core'] : []).map(parseCoreDoc),
  }
}

/** Format one front-matter value for the detail field list. */
function fieldValue(value: unknown): string {
  if (typeof value === 'string') return value
  if (typeof value === 'number' || typeof value === 'boolean') return String(value)
  if (Array.isArray(value)) return value.map(fieldValue).join('、')
  if (value !== null && typeof value === 'object') return JSON.stringify(value)
  return ''
}

/** Parse one relation-view item. */
function parseRelation(raw: unknown, direction: 'outgoing' | 'incoming'): RelationItem {
  const record = (raw !== null && typeof raw === 'object' ? raw : {}) as Record<string, unknown>
  const text = (value: unknown): string => (typeof value === 'string' ? value : '')
  return {
    name: text(record['name']) || text(record['target']),
    note: text(record['note']),
    direction,
    origin: text(record['origin']),
    resolved: record['resolved'] !== false,
  }
}

/** Narrow the asset detail payload (envelope unwrapped by the caller). */
function parseAssetDetail(data: unknown): AssetDetail {
  const envelope = (data !== null && typeof data === 'object' ? data : {}) as Record<string, unknown>
  const inner = (envelope['data'] !== null && typeof envelope['data'] === 'object' ? envelope['data'] : envelope) as Record<string, unknown>
  const fields: { key: string; value: string }[] = []
  const fieldSource = (inner['data'] !== null && typeof inner['data'] === 'object' ? inner['data'] : {}) as Record<string, unknown>
  for (const [key, value] of Object.entries(fieldSource)) {
    if (DETAIL_SKIP_FIELDS.has(key)) continue
    const formatted = fieldValue(value)
    if (formatted !== '') fields.push({ key, value: formatted })
  }
  const relationView = (inner['relation_view'] !== null && typeof inner['relation_view'] === 'object' ? inner['relation_view'] : {}) as Record<string, unknown>
  const relationList = (key: string, direction: 'outgoing' | 'incoming'): RelationItem[] =>
    (Array.isArray(relationView[key]) ? relationView[key] : []).map(item => parseRelation(item, direction))
  return {
    fields,
    relations: [
      ...relationList('confirmed', 'outgoing'),
      ...relationList('registered', 'outgoing'),
      ...relationList('incoming', 'incoming'),
    ],
    body: typeof inner['body_markdown'] === 'string' ? inner['body_markdown'] : '',
  }
}

/** Narrow the document payload (NOT enveloped). */
function parseDocument(data: unknown): { title: string; content: string } {
  const record = (data !== null && typeof data === 'object' ? data : {}) as Record<string, unknown>
  return {
    title: typeof record['title'] === 'string' ? record['title'] : '',
    content: typeof record['content'] === 'string' ? record['content'] : '',
  }
}

/** Full assets-view props: conversation-view runtime share & injected fetch & locale seat. */
export type AssetsViewProps =
  ConvViewProps & InjectFace<StudioApiInjected> & PropsLocale<'studio-panel'>

export function AssetsView({ fetchStudioApi, t }: AssetsViewProps) {
  const [state, setState] = useState<LoadState>('loading')
  const [assets, setAssets] = useState<AssetSummary[]>([])
  const [references, setReferences] = useState<ReferenceEntry[]>([])
  const [coreDocs, setCoreDocs] = useState<CoreDoc[]>([])
  const [error, setError] = useState('')
  const [segment, setSegment] = useState<Segment>('characters')
  const [expanded, setExpanded] = useState<string | null>(null)
  const [details, setDetails] = useState<ReadonlyMap<string, DetailState>>(new Map())
  const [documents, setDocuments] = useState<ReadonlyMap<string, DocState>>(new Map())
  // Detail fetches are keyed fetches; the cache doubles as the in-flight guard.
  const detailsRef = useRef(details)
  detailsRef.current = details

  const load = useCallback(() => {
    setState('loading')
    let cancelled = false
    // The reference works and 作品核心 ride the workspace payload; their
    // failure must not take the asset sections down with it (and vice versa).
    const assetsPromise = fetchStudioApi('/assets').then(parseAssets)
    const workspacePromise = fetchStudioApi('/workspace').then(parseWorkspace).catch(() => null)
    void Promise.all([assetsPromise, workspacePromise])
      .then(([assetList, workspace]) => {
        if (cancelled) return
        setAssets(assetList)
        setReferences(workspace?.references ?? [])
        setCoreDocs(workspace?.coreDocs ?? [])
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

  const toggleAsset = (asset: AssetSummary) => {
    const key = `${asset.kind}:${asset.id}`
    if (expanded === key) {
      setExpanded(null)
      return
    }
    setExpanded(key)
    if (detailsRef.current.has(key)) return
    setDetails(previous => new Map(previous).set(key, { status: 'loading' }))
    fetchStudioApi(`/assets/${asset.kind}/${encodeURIComponent(asset.id)}`)
      .then((data) => {
        setDetails(previous => new Map(previous).set(key, { status: 'ready', detail: parseAssetDetail(data) }))
      })
      .catch((cause: unknown) => {
        setDetails(previous => new Map(previous).set(key, {
          status: 'error',
          message: cause instanceof Error ? cause.message : String(cause),
        }))
      })
  }

  const toggleDocument = (doc: CoreDoc) => {
    const key = `doc:${doc.path}`
    if (expanded === key) {
      setExpanded(null)
      return
    }
    setExpanded(key)
    if (documents.has(key)) return
    setDocuments(previous => new Map(previous).set(key, { status: 'loading' }))
    fetchStudioApi(`/document?path=${encodeURIComponent(doc.path)}`)
      .then((data) => {
        setDocuments(previous => new Map(previous).set(key, { status: 'ready', ...parseDocument(data) }))
      })
      .catch((cause: unknown) => {
        setDocuments(previous => new Map(previous).set(key, {
          status: 'error',
          message: cause instanceof Error ? cause.message : String(cause),
        }))
      })
  }

  const intentLabel = (intent: string): string => {
    switch (intent) {
      case 'continuation': return t('reference.intent.continuation')
      case 'canon': return t('reference.intent.canon')
      case 'migration': return t('reference.intent.migration')
      default: return t('reference.intent.reference')
    }
  }

  const relationOriginLabel = (item: RelationItem): string => {
    if (item.direction === 'incoming') return t('assets.relation.incoming')
    return item.origin === 'annotation' ? t('assets.relation.registered') : t('assets.relation.confirmed')
  }

  const segmentCount = (which: Segment): number => {
    switch (which) {
      case 'characters': return assets.filter(asset => asset.kind === 'character').length
      case 'world': return assets.filter(asset => asset.kind === 'world').length
      case 'progression': return assets.filter(asset => asset.kind === 'progression').length
      case 'references': return references.length
      case 'core': return coreDocs.length
    }
  }

  const segmentLabel = (which: Segment): string => {
    switch (which) {
      case 'characters': return t('assets.segment.characters')
      case 'world': return t('assets.segment.world')
      case 'progression': return t('assets.segment.progression')
      case 'references': return t('assets.segment.references')
      case 'core': return t('assets.segment.core')
    }
  }

  const renderDetail = (key: string) => {
    const entry = details.get(key)
    if (entry === undefined || entry.status === 'loading') {
      return <div className={css.detailNotice}>{t('assets.detail.loading')}</div>
    }
    if (entry.status === 'error') {
      return <div className={css.detailNotice}><span className={css.errorText}>{entry.message}</span></div>
    }
    const { detail } = entry
    return (
      <div className={css.detail}>
        {detail.fields.length > 0 && (
          <dl className={css.fieldList}>
            {detail.fields.map(field => (
              <div key={field.key} className={css.fieldRow}>
                <dt className={css.fieldKey}>{field.key}</dt>
                <dd className={css.fieldValue}>{field.value}</dd>
              </div>
            ))}
          </dl>
        )}
        {detail.relations.length > 0 && (
          <div className={css.relationBlock}>
            <div className={css.detailHeading}>{t('assets.detail.relations')}</div>
            <div className={css.relationChips}>
              {detail.relations.map((relation, index) => (
                <span
                  key={`${relation.direction}:${relation.name}:${index}`}
                  className={css.relationChip}
                  data-resolved={relation.resolved}
                  title={relation.note}
                >
                  {relation.direction === 'incoming' ? '←' : '→'} {relation.name}
                  {relation.note !== '' && <span className={css.relationNote}>{relation.note}</span>}
                  <span className={css.relationOrigin}>{relationOriginLabel(relation)}</span>
                </span>
              ))}
            </div>
          </div>
        )}
        {detail.body !== '' && <div className={css.detailBody}>{detail.body}</div>}
      </div>
    )
  }

  const renderAssetCard = (asset: AssetSummary) => {
    const key = `${asset.kind}:${asset.id}`
    const isOpen = expanded === key
    const shownTags = asset.tags.slice(0, 4)
    return (
      <div key={key} className={css.assetCard} data-kind={asset.kind} data-open={isOpen}>
        <button
          type="button"
          className={css.assetCardButton}
          aria-expanded={isOpen}
          onClick={() => { toggleAsset(asset) }}
        >
          <div className={css.assetCardHead}>
            <span className={css.assetName}>{asset.name || asset.id}</span>
            {asset.assetType !== '' && <span className={css.kindBadge}>{asset.assetType}</span>}
          </div>
          {asset.aliases.length > 0 && (
            <div className={css.assetAliases}>{t('assets.aliases')}: {asset.aliases.join('、')}</div>
          )}
          {asset.summary !== '' && <div className={css.assetSummary}>{asset.summary}</div>}
          <div className={css.assetMeta}>
            {asset.stageCount !== null && (
              <span className={css.tag}>{asset.stageCount} {t('assets.stages')}</span>
            )}
            {shownTags.map(tag => <span key={tag} className={css.tag}>{tag}</span>)}
            {asset.tags.length > shownTags.length && (
              <span className={css.tag}>+{asset.tags.length - shownTags.length}</span>
            )}
          </div>
        </button>
        {isOpen && renderDetail(key)}
      </div>
    )
  }

  const renderSegmentBody = () => {
    if (segment === 'references') {
      if (references.length === 0) return <div className={css.notice}>{t('assets.references.empty')}</div>
      return (
        <div className={css.assetGrid}>
          {references.map(entry => (
            <div key={entry.sourceId} className={css.assetCard} data-kind="reference">
              <div className={css.assetCardButton} data-static="true">
                <div className={css.assetCardHead}>
                  <span className={css.assetName}>{entry.title || entry.sourceId}</span>
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
            </div>
          ))}
        </div>
      )
    }
    if (segment === 'core') {
      if (coreDocs.length === 0) return <div className={css.notice}>{t('assets.core.empty')}</div>
      return (
        <div className={css.docList}>
          {coreDocs.map(doc => {
            const key = `doc:${doc.path}`
            const isOpen = expanded === key
            const docState = documents.get(key)
            return (
              <div key={doc.path} className={css.docRow} data-open={isOpen}>
                <button
                  type="button"
                  className={css.docRowButton}
                  aria-expanded={isOpen}
                  onClick={() => { toggleDocument(doc) }}
                >
                  <span className={css.assetName}>{doc.title}</span>
                  {doc.categoryLabel !== '' && <span className={css.kindBadge}>{doc.categoryLabel}</span>}
                  <span className={css.docPath}>{doc.path}</span>
                </button>
                {isOpen && (
                  docState === undefined || docState.status === 'loading'
                    ? <div className={css.detailNotice}>{t('assets.detail.loading')}</div>
                    : docState.status === 'error'
                      ? <div className={css.detailNotice}><span className={css.errorText}>{docState.message}</span></div>
                      : <div className={css.detailBody}>{docState.content}</div>
                )}
              </div>
            )
          })}
        </div>
      )
    }
    // character / world / progression segments
    const kind = segment === 'characters' ? 'character' : segment === 'progression' ? 'progression' : 'world'
    const segmentAssets = assets.filter(asset => asset.kind === kind)
    if (segmentAssets.length === 0) return <div className={css.notice}>{t('assets.segment.empty')}</div>
    if (segment !== 'world') {
      return <div className={css.assetGrid}>{segmentAssets.map(renderAssetCard)}</div>
    }
    // 设定: group by subcategory (asset_type), unknown type lands in 其他.
    const byType = new Map<string, AssetSummary[]>()
    for (const asset of segmentAssets) {
      const type = asset.assetType || t('assets.other')
      const list = byType.get(type)
      if (list !== undefined) list.push(asset)
      else byType.set(type, [asset])
    }
    return [...byType.entries()].map(([type, items]) => (
      <section key={type} className={css.assetGroup}>
        <h3 className={css.assetGroupTitle}>
          {type}
          <span className={css.countChip}>{items.length}</span>
        </h3>
        <div className={css.assetGrid}>{items.map(renderAssetCard)}</div>
      </section>
    ))
  }

  return (
    <div className={css.root}>
      <div className={css.toolbar}>
        <span className={css.toolbarMeta}>
          {SEGMENTS.map(which => (
            <button
              key={which}
              type="button"
              className={css.chip}
              data-active={segment === which}
              onClick={() => {
                setSegment(which)
                setExpanded(null)
              }}
            >
              {segmentLabel(which)} {segmentCount(which)}
            </button>
          ))}
        </span>
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
        {state === 'ready' && assets.length === 0 && references.length === 0 && coreDocs.length === 0 && (
          <div className={css.notice}>{t('assets.empty')}</div>
        )}
        {state === 'ready' && (assets.length > 0 || references.length > 0 || coreDocs.length > 0) && renderSegmentBody()}
      </div>
    </div>
  )
}
