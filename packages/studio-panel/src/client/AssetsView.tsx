/**
 * Assets view (资产): OpenWrite's structured canon library (Studio's 资料库)
 * rendered natively as an Obsidian-like master-detail layout — left sidebar
 * (segment switcher, search, compact asset rows with collapsible 设定
 * subcategory groups, 新建 button) + main detail pane (header, two-column
 * fields, 索引, 关系, markdown body) with a read/edit toggle and inline
 * creation. Only the asset domain is writable; manuscript/outline mutations
 * stay with the agent tools.
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
 * - POST /api/assets / POST /api/assets/update — the write contract lives in
 *   AssetEditor.tsx's header comment.
 * - GET /api/workspace — NOT enveloped. documents.core[] is the 作品核心
 *   document list; operations.reference_library is the 参考作品 (reference
 *   works) list — Studio's data-view="deconstruct" surface, NOT the 资料库
 *   nav entry (which is this structured asset library).
 * - GET /api/document?path=<p> — NOT enveloped { path, title, content, ... }.
 */

import { useCallback, useEffect, useRef, useState } from 'react'
import { MarkdownText } from '@deepseek-ai/dsh-client-ui-primitives'
import type { ConvViewProps } from '@deepseek-ai/dsh-client-ui-conversation/client'
import type { InjectFace, PropsLocale } from '@deepseek-ai/dsh-client-ui-slots'
import { StudioApiError, type StudioApiInjected } from './api.ts'
import { AssetEditor, NewAssetForm, type RelationDraft } from './AssetEditor.tsx'
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

/**
 * Parsed asset detail: the editor-owned front-matter fields (name/summary/
 * aliases/tags/scalars/related), the read-only leftovers (lists/objects), the
 * resolved display relations, and the body. `revision` is the optimistic lock
 * echoed back on update.
 */
interface AssetDetail {
  revision: string
  name: string
  summary: string
  aliases: string[]
  tags: string[]
  scalars: { key: string; value: string }[]
  fields: { key: string; value: string }[]
  /** List-typed whitelist fields (taboos/detail_refs): string entries. */
  lists: { key: string; items: string[] }[]
  related: RelationDraft[]
  relations: RelationItem[]
  body: string
}

/** Per-asset detail cache entry. */
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

/** Front-matter keys the editor owns (excluded from the read-only field list). */
const EDITOR_OWNED_FIELDS = new Set(['id', 'name', 'summary', 'aliases', 'tags', 'related'])
/** Server-managed keys rendered read-only. */
const READONLY_FIELDS = new Set(['state_updated_at'])
/**
 * List-typed whitelist keys (structured_assets.py: CHARACTER_FIELDS has
 * taboos/detail_refs, WORLD_FIELDS has detail_refs) rendered as proper list
 * blocks in the read view and edited as one-entry-per-line textareas
 * (Studio's assets.js line-join semantics).
 */
const LIST_FIELDS = new Set(['taboos', 'detail_refs'])

/** Segments backed by writable structured assets (新建 lives there). */
const CARDABLE_SEGMENTS: readonly Segment[] = ['characters', 'world', 'progression']

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

/** Format one non-scalar front-matter value for the read-only field list. */
function fieldValue(value: unknown): string {
  if (Array.isArray(value)) return value.map(item => (typeof item === 'object' ? JSON.stringify(item) : String(item))).join('、')
  if (value !== null && typeof value === 'object') return JSON.stringify(value)
  return String(value)
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

/** Parse one front-matter `related` entry (string or { target, kind, note }). */
function parseRelatedDraft(raw: unknown): RelationDraft | null {
  if (typeof raw === 'string') {
    return raw.trim() === '' ? null : { target: raw.trim(), kind: 'related', note: '' }
  }
  if (raw !== null && typeof raw === 'object') {
    const record = raw as Record<string, unknown>
    const target = typeof record['target'] === 'string' ? record['target'].trim() : ''
    if (target === '') return null
    return {
      target,
      kind: typeof record['kind'] === 'string' && record['kind'] !== '' ? record['kind'] : 'related',
      note: typeof record['note'] === 'string' ? record['note']
        : typeof record['description'] === 'string' ? record['description'] : '',
    }
  }
  return null
}

/** Narrow the asset detail payload (envelope unwrapped here). */
function parseAssetDetail(data: unknown): AssetDetail {
  const envelope = (data !== null && typeof data === 'object' ? data : {}) as Record<string, unknown>
  const inner = (envelope['data'] !== null && typeof envelope['data'] === 'object' ? envelope['data'] : envelope) as Record<string, unknown>
  const frontMatter = (inner['data'] !== null && typeof inner['data'] === 'object' ? inner['data'] : {}) as Record<string, unknown>
  const text = (value: unknown): string => (typeof value === 'string' ? value : '')
  const scalars: { key: string; value: string }[] = []
  const fields: { key: string; value: string }[] = []
  const lists: { key: string; items: string[] }[] = []
  for (const [key, value] of Object.entries(frontMatter)) {
    if (EDITOR_OWNED_FIELDS.has(key)) continue
    if (LIST_FIELDS.has(key)) {
      // One row per entry; non-string entries keep a readable JSON form.
      const items = (Array.isArray(value) ? value : [])
        .map(item => (typeof item === 'string' ? item : JSON.stringify(item)))
        .filter(item => item !== '')
      if (items.length > 0) lists.push({ key, items })
      continue
    }
    if (typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean') {
      (READONLY_FIELDS.has(key) ? fields : scalars).push({ key, value: String(value) })
    } else {
      const formatted = fieldValue(value)
      if (formatted !== '' && formatted !== 'null') fields.push({ key, value: formatted })
    }
  }
  const relationView = (inner['relation_view'] !== null && typeof inner['relation_view'] === 'object' ? inner['relation_view'] : {}) as Record<string, unknown>
  const relationList = (key: string, direction: 'outgoing' | 'incoming'): RelationItem[] =>
    (Array.isArray(relationView[key]) ? relationView[key] : []).map(item => parseRelation(item, direction))
  return {
    revision: text(inner['revision']),
    name: text(inner['name']) || text(frontMatter['name']),
    summary: text(frontMatter['summary']),
    aliases: Array.isArray(frontMatter['aliases'])
      ? frontMatter['aliases'].filter((item): item is string => typeof item === 'string' && item !== '')
      : [],
    tags: Array.isArray(frontMatter['tags'])
      ? frontMatter['tags'].filter((item): item is string => typeof item === 'string' && item !== '')
      : [],
    scalars,
    fields,
    lists,
    related: (Array.isArray(frontMatter['related']) ? frontMatter['related'] : [])
      .map(parseRelatedDraft)
      .filter((item): item is RelationDraft => item !== null),
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

/** Client-side search: name/id/assetType/aliases/tags/summary, case-insensitive substring. */
function matchesQuery(asset: AssetSummary, query: string): boolean {
  const haystack = [
    asset.name, asset.id, asset.assetType, asset.summary, ...asset.aliases, ...asset.tags,
  ].join('\n').toLowerCase()
  return haystack.includes(query)
}

/** Full assets-view props: conversation-view runtime share & injected fetch & locale seat. */
export type AssetsViewProps =
  ConvViewProps & InjectFace<StudioApiInjected> & PropsLocale<'studio-panel'>

export function AssetsView({ fetchStudioApi, postStudioApi, resolveStudioUrl, t }: AssetsViewProps) {
  const [state, setState] = useState<LoadState>('loading')
  const [assets, setAssets] = useState<AssetSummary[]>([])
  const [references, setReferences] = useState<ReferenceEntry[]>([])
  const [coreDocs, setCoreDocs] = useState<CoreDoc[]>([])
  const [error, setError] = useState('')
  const [segment, setSegment] = useState<Segment>('characters')
  const [query, setQuery] = useState('')
  /** Selected sidebar row key: `${kind}:${id}` / `doc:${path}` / `ref:${sourceId}`. */
  const [selected, setSelected] = useState<string | null>(null)
  const [collapsedGroups, setCollapsedGroups] = useState<ReadonlySet<string>>(new Set())
  const [details, setDetails] = useState<ReadonlyMap<string, DetailState>>(new Map())
  const [documents, setDocuments] = useState<ReadonlyMap<string, DocState>>(new Map())
  const [editKey, setEditKey] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState<{ message: string; conflict: boolean } | null>(null)
  const [creating, setCreating] = useState(false)
  const [createBusy, setCreateBusy] = useState(false)
  const [createError, setCreateError] = useState<string | null>(null)
  // The detail cache doubles as the in-flight guard for keyed fetches.
  const detailsRef = useRef(details)
  detailsRef.current = details

  const load = useCallback((silent = false) => {
    if (!silent) setState('loading')
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

  const fetchDetail = useCallback((asset: AssetSummary) => {
    const key = `${asset.kind}:${asset.id}`
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
  }, [fetchStudioApi])

  /** Select one sidebar row: clear transient editing state, lazy-load the detail. */
  const selectAsset = (asset: AssetSummary) => {
    const key = `${asset.kind}:${asset.id}`
    setSelected(key)
    setEditKey(null)
    setSaveError(null)
    setCreating(false)
    if (!detailsRef.current.has(key)) fetchDetail(asset)
  }

  const selectDocument = (doc: CoreDoc) => {
    const key = `doc:${doc.path}`
    setSelected(key)
    setEditKey(null)
    setCreating(false)
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

  /** Save one editor draft: revision-locked update, then refresh detail + list. */
  const saveAsset = (asset: AssetSummary, data: Record<string, unknown>, bodyMarkdown: string) => {
    const key = `${asset.kind}:${asset.id}`
    const entry = details.get(key)
    if (entry?.status !== 'ready') return
    setSaving(true)
    setSaveError(null)
    postStudioApi('/assets/update', {
      kind: asset.kind,
      id: asset.id,
      revision: entry.detail.revision,
      data,
      body_markdown: bodyMarkdown,
    })
      .then(() => {
        setSaving(false)
        setEditKey(null)
        fetchDetail(asset)
        load(true)
      })
      .catch((cause: unknown) => {
        setSaving(false)
        setSaveError({
          message: cause instanceof Error ? cause.message : String(cause),
          conflict: cause instanceof StudioApiError && cause.status === 409,
        })
      })
  }

  /** Create one asset, then refresh the list. */
  const createAsset = (kind: 'character' | 'world' | 'progression', payload: { id: string; data: Record<string, unknown> }) => {
    setCreateBusy(true)
    setCreateError(null)
    postStudioApi('/assets', { kind, id: payload.id, data: payload.data })
      .then(() => {
        setCreateBusy(false)
        setCreating(false)
        load(true)
      })
      .catch((cause: unknown) => {
        setCreateBusy(false)
        setCreateError(cause instanceof Error ? cause.message : String(cause))
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

  /** Localized label for a list-typed whitelist field (raw key as fallback). */
  const listLabel = (key: string): string => {
    switch (key) {
      case 'detail_refs': return t('assets.list.detail_refs')
      case 'taboos': return t('assets.list.taboos')
      default: return key
    }
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

  const toggleGroup = (type: string) => {
    setCollapsedGroups(previous => {
      const next = new Set(previous)
      if (next.has(type)) next.delete(type)
      else next.add(type)
      return next
    })
  }

  /* --- sidebar --- */

  const q = query.trim().toLowerCase()

  const renderAssetRow = (asset: AssetSummary) => {
    const key = `${asset.kind}:${asset.id}`
    const meta = asset.assetType !== ''
      ? asset.assetType
      : asset.stageCount !== null
        ? `${asset.stageCount} ${t('assets.stages')}`
        : ''
    return (
      <button
        key={key}
        type="button"
        className={css.assetRow}
        data-active={selected === key}
        onClick={() => { selectAsset(asset) }}
      >
        <span className={`${css.assetRowName} ${css.mdInline}`}>
          <MarkdownText text={asset.name || asset.id} />
        </span>
        {meta !== '' && <span className={css.assetRowMeta}>{meta}</span>}
      </button>
    )
  }

  const renderSidebarList = () => {
    if (segment === 'references') {
      const filtered = q === ''
        ? references
        : references.filter(entry => `${entry.title}\n${entry.sourceId}`.toLowerCase().includes(q))
      if (filtered.length === 0) return <div className={css.sidebarEmpty}>{t('assets.references.empty')}</div>
      return filtered.map(entry => {
        const key = `ref:${entry.sourceId}`
        return (
          <button
            key={key}
            type="button"
            className={css.assetRow}
            data-active={selected === key}
            onClick={() => {
              setSelected(key)
              setEditKey(null)
              setCreating(false)
            }}
          >
            <span className={`${css.assetRowName} ${css.mdInline}`}>
              <MarkdownText text={entry.title || entry.sourceId} />
            </span>
            <span className={css.assetRowMeta}>{intentLabel(entry.intent)}</span>
          </button>
        )
      })
    }
    if (segment === 'core') {
      const filtered = q === ''
        ? coreDocs
        : coreDocs.filter(doc => `${doc.title}\n${doc.categoryLabel}\n${doc.path}`.toLowerCase().includes(q))
      if (filtered.length === 0) return <div className={css.sidebarEmpty}>{t('assets.core.empty')}</div>
      return filtered.map(doc => {
        const key = `doc:${doc.path}`
        return (
          <button
            key={key}
            type="button"
            className={css.assetRow}
            data-active={selected === key}
            onClick={() => { selectDocument(doc) }}
          >
            <span className={`${css.assetRowName} ${css.mdInline}`}>
              <MarkdownText text={doc.title} />
            </span>
            {doc.categoryLabel !== '' && <span className={css.assetRowMeta}>{doc.categoryLabel}</span>}
          </button>
        )
      })
    }
    // character / world / progression segments
    const kind = segment === 'characters' ? 'character' : segment === 'progression' ? 'progression' : 'world'
    const segmentAssets = assets.filter(asset => asset.kind === kind && (q === '' || matchesQuery(asset, q)))
    if (segmentAssets.length === 0) return <div className={css.sidebarEmpty}>{t('assets.segment.empty')}</div>
    if (segment !== 'world') return segmentAssets.map(renderAssetRow)
    // 设定: collapsible subcategory groups by asset_type (unknown lands in 其他).
    const byType = new Map<string, AssetSummary[]>()
    for (const asset of segmentAssets) {
      const type = asset.assetType || t('assets.other')
      const list = byType.get(type)
      if (list !== undefined) list.push(asset)
      else byType.set(type, [asset])
    }
    return [...byType.entries()].map(([type, items]) => {
      const collapsed = collapsedGroups.has(type)
      return (
        <div key={type}>
          <button
            type="button"
            className={css.groupHeader}
            aria-expanded={!collapsed}
            onClick={() => { toggleGroup(type) }}
          >
            <span className={css.groupChevron}>{collapsed ? '▸' : '▾'}</span>
            {type}
            <span className={css.countChip}>{items.length}</span>
          </button>
          {!collapsed && items.map(renderAssetRow)}
        </div>
      )
    })
  }

  /* --- main pane --- */

  const renderAssetDetail = (asset: AssetSummary, key: string) => {
    const entry = details.get(key)
    if (entry === undefined || entry.status === 'loading') {
      return <div className={css.notice}>{t('assets.detail.loading')}</div>
    }
    if (entry.status === 'error') {
      return (
        <div className={css.notice}>
          <span className={css.errorText}>{entry.message}</span>
          <button type="button" className={css.button} onClick={() => { fetchDetail(asset) }}>{t('retry')}</button>
        </div>
      )
    }
    const { detail } = entry
    if (editKey === key) {
      return (
        <AssetEditor
          // Remount on revision change: a post-conflict refresh rebuilds the draft honestly.
          key={`${key}:${detail.revision}`}
          kind={asset.kind}
          source={{
            ...detail,
            // Derived relations (incoming edges / annotation origin) live in
            // other assets' front matter — display-only in this editor.
            derivedRelations: detail.relations.filter(
              relation => relation.direction === 'incoming' || relation.origin === 'annotation',
            ),
          }}
          candidates={assets.filter(candidate => candidate.kind !== 'progression' && candidate.id !== asset.id)}
          saving={saving}
          saveError={saveError?.message ?? null}
          conflict={saveError?.conflict === true}
          onSave={(data, bodyMarkdown) => { saveAsset(asset, data, bodyMarkdown) }}
          onCancel={() => {
            setEditKey(null)
            setSaveError(null)
          }}
          onRefresh={() => {
            setSaveError(null)
            fetchDetail(asset)
          }}
          resolveStudioUrl={resolveStudioUrl}
          t={t}
        />
      )
    }
    return (
      <div className={css.detail}>
        <div className={css.detailHeader}>
          <div className={css.detailTitleRow}>
            <span className={`${css.detailTitle} ${css.mdInline}`}>
              <MarkdownText text={detail.name || asset.id} />
            </span>
            {asset.assetType !== '' && <span className={css.kindBadge}>{asset.assetType}</span>}
            <button
              type="button"
              className={css.button}
              onClick={() => {
                setEditKey(key)
                setSaveError(null)
              }}
            >
              {t('assets.edit.open')}
            </button>
          </div>
          {detail.aliases.length > 0 && (
            <div className={css.assetAliases}>{t('assets.aliases')}: {detail.aliases.join('、')}</div>
          )}
          {detail.summary !== '' && (
            <div className={`${css.detailSummary} ${css.mdInline}`}><MarkdownText text={detail.summary} /></div>
          )}
          {detail.tags.length > 0 && (
            <div className={css.assetMeta}>
              {detail.tags.map(tag => <span key={tag} className={css.tag}>{tag}</span>)}
            </div>
          )}
        </div>
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
        {detail.lists.length > 0 && (
          <div className={css.relationBlock}>
            <div className={css.detailHeading}>{t('assets.detail.index')}</div>
            {detail.lists.map(list => (
              <div key={list.key} className={css.listBlock}>
                <div className={css.listBlockLabel}>{listLabel(list.key)}</div>
                <ul className={css.listBlockItems}>
                  {list.items.map((item, index) => <li key={index}>{item}</li>)}
                </ul>
              </div>
            ))}
          </div>
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
        {detail.body !== '' && <div className={css.detailBody}><MarkdownText text={detail.body} /></div>}
      </div>
    )
  }

  const renderMain = () => {
    // The create form owns the main pane while open.
    if (creating && CARDABLE_SEGMENTS.includes(segment)) {
      const kind = segment === 'characters' ? 'character' : segment === 'progression' ? 'progression' : 'world'
      return (
        <div className={css.createPanel}>
          <NewAssetForm
            kind={kind}
            busy={createBusy}
            error={createError}
            onSubmit={(payload) => { createAsset(kind, payload) }}
            onCancel={() => {
              setCreating(false)
              setCreateError(null)
            }}
            t={t}
          />
        </div>
      )
    }
    if (selected === null) {
      return <div className={css.notice}>{t('assets.selectHint')}</div>
    }
    if (selected.startsWith('doc:')) {
      const path = selected.slice(4)
      const docState = documents.get(selected)
      return (
        <div className={css.detail}>
          {docState === undefined || docState.status === 'loading'
            ? <div className={css.notice}>{t('assets.detail.loading')}</div>
            : docState.status === 'error'
              ? <div className={css.notice}><span className={css.errorText}>{docState.message}</span></div>
              : (
                <>
                  <div className={css.detailHeader}>
                    <div className={css.detailTitleRow}>
                      <span className={`${css.detailTitle} ${css.mdInline}`}>
                        <MarkdownText text={docState.title || path} />
                      </span>
                      <span className={css.kindBadge}>{path}</span>
                    </div>
                  </div>
                  <div className={css.detailBody}><MarkdownText text={docState.content} /></div>
                </>
              )}
        </div>
      )
    }
    if (selected.startsWith('ref:')) {
      const entry = references.find(item => `ref:${item.sourceId}` === selected)
      if (entry === undefined) return <div className={css.notice}>{t('assets.selectHint')}</div>
      return (
        <div className={css.detail}>
          <div className={css.detailHeader}>
            <div className={css.detailTitleRow}>
              <span className={`${css.detailTitle} ${css.mdInline}`}>
                <MarkdownText text={entry.title || entry.sourceId} />
              </span>
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
      )
    }
    const asset = assets.find(item => `${item.kind}:${item.id}` === selected)
    if (asset === undefined) return <div className={css.notice}>{t('assets.selectHint')}</div>
    return renderAssetDetail(asset, selected)
  }

  return (
    <div className={css.libraryRoot}>
      <div className={css.sidebar}>
        <div className={css.sidebarSegments}>
          {SEGMENTS.map(which => (
            <button
              key={which}
              type="button"
              className={css.segmentButton}
              data-active={segment === which}
              onClick={() => {
                setSegment(which)
                setSelected(null)
                setEditKey(null)
                setCreating(false)
              }}
            >
              {segmentLabel(which)}
              <span className={css.countChip}>{segmentCount(which)}</span>
            </button>
          ))}
        </div>
        <input
          className={css.searchInput}
          type="search"
          value={query}
          placeholder={t('assets.searchPlaceholder')}
          aria-label={t('assets.searchPlaceholder')}
          onChange={event => { setQuery(event.target.value) }}
        />
        <div className={css.sidebarList}>
          {state === 'loading' && <div className={css.sidebarEmpty}>{t('loading')}</div>}
          {state === 'error' && (
            <div className={css.sidebarEmpty}>
              <span className={css.errorText}>{error}</span>
              <button type="button" className={css.button} onClick={() => { load() }}>{t('retry')}</button>
            </div>
          )}
          {state === 'ready' && assets.length === 0 && references.length === 0 && coreDocs.length === 0 && (
            <div className={css.sidebarEmpty}>{t('assets.empty')}</div>
          )}
          {state === 'ready' && renderSidebarList()}
        </div>
        <div className={css.sidebarFooter}>
          {CARDABLE_SEGMENTS.includes(segment) && (
            <button
              type="button"
              className={css.button}
              disabled={creating}
              onClick={() => {
                setCreating(true)
                setCreateError(null)
              }}
            >
              {t('assets.create.open')}
            </button>
          )}
          <button type="button" className={css.button} onClick={() => { load() }}>
            {t('refresh')}
          </button>
        </div>
      </div>
      <div className={css.mainPane}>
        {state === 'ready' || creating ? renderMain() : (
          state === 'loading'
            ? <div className={css.notice}>{t('loading')}</div>
            : (
              <div className={css.notice}>
                <span className={css.errorText}>{error}</span>
                <button type="button" className={css.button} onClick={() => { load() }}>{t('retry')}</button>
              </div>
            )
        )}
      </div>
    </div>
  )
}
