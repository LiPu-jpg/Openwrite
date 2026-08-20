/**
 * Graph view (图谱): OpenWrite continuity data as native SVG — the
 * foreshadowing board (layered by 主线/支线/彩蛋, ordered by target chapter)
 * and the character/world relationship graph (deterministic circular layout).
 * No graph library: both layouts are small deterministic computations.
 * Read-only.
 *
 * Wire shape (verified against OpenWrite tools/novel_service.py continuity()
 * + models/foreshadowing.py + tools/world_query.py get_relations_topology):
 * GET /api/continuity answers WITHOUT an envelope —
 * {
 *   truth: {...},
 *   foreshadowing: {
 *     // PENDING nodes only (get_pending_nodes: status 埋伏/待收, weight >= 1);
 *     // the stored DAG's edges are NOT exposed by this endpoint.
 *     nodes: [{ id, content, weight (1-10), layer (主线/支线/彩蛋),
 *               status (埋伏/待收), created_at, target_arc, target_section,
 *               target_chapter, tags }],
 *     total, by_status, by_layer, by_weight,
 *   },
 *   foreshadowing_validation: { valid, errors },
 *   relationship_graph: {
 *     nodes: [{ id, label, kind (character/faction/place/concept/.../unknown),
 *               type, status, description, unresolved }],
 *     edges: [{ id, source, target, label, kind, origin, confirmed,
 *               source_label }],
 *     truncated, ...
 *   },
 *   workflows: [...],
 * }
 */

import { useCallback, useEffect, useState } from 'react'
import type { ConvViewProps } from '@deepseek-ai/dsh-client-ui-conversation/client'
import type { InjectFace, PropsLocale } from '@deepseek-ai/dsh-client-ui-slots'
import type { StudioApiInjected } from './api.ts'
import css from './views.module.css'

interface ForeshadowNode {
  id: string
  content: string
  weight: number
  layer: string
  status: string
  createdAt: string
  targetChapter: string
  tags: string[]
}

interface ForeshadowEdge {
  from: string
  to: string
  type: string
}

interface RelationNode {
  id: string
  label: string
  kind: string
  type: string
  status: string
  unresolved: boolean
}

interface RelationEdge {
  id: string
  source: string
  target: string
  label: string
  confirmed: boolean
}

interface ContinuityPayload {
  foreshadowNodes: ForeshadowNode[]
  foreshadowEdges: ForeshadowEdge[]
  validationErrors: string[]
  relationNodes: RelationNode[]
  relationEdges: RelationEdge[]
  relationTruncated: boolean
}

type LoadState = 'loading' | 'error' | 'ready'
type Segment = 'foreshadowing' | 'relationships'

/** `ch_0010` → 10; anything else → null (sorted last). */
function chapterNumber(value: string): number | null {
  const match = /ch_0*(\d+)/.exec(value)
  return match !== null ? Number(match[1]) : null
}

/** Narrow the continuity payload, tolerating missing/extra fields. */
function parseContinuity(data: unknown): ContinuityPayload {
  const root = (data !== null && typeof data === 'object' ? data : {}) as Record<string, unknown>
  const text = (value: unknown): string => (typeof value === 'string' ? value : '')
  const record = (value: unknown): Record<string, unknown> =>
    (value !== null && typeof value === 'object' ? value : {}) as Record<string, unknown>

  const foreshadowing = record(root['foreshadowing'])
  const foreshadowNodes: ForeshadowNode[] = (Array.isArray(foreshadowing['nodes']) ? foreshadowing['nodes'] : [])
    .map((raw): ForeshadowNode => {
      const node = record(raw)
      return {
        id: text(node['id']),
        content: text(node['content']),
        weight: typeof node['weight'] === 'number' ? node['weight'] : 0,
        layer: text(node['layer']),
        status: text(node['status']),
        createdAt: text(node['created_at']),
        targetChapter: text(node['target_chapter']),
        tags: Array.isArray(node['tags']) ? node['tags'].filter((tag): tag is string => typeof tag === 'string') : [],
      }
    })
  // Defensive: the endpoint currently exposes no DAG edges; consume them if a
  // future Studio version adds the list (edge model uses the alias `from`).
  const foreshadowEdges: ForeshadowEdge[] = (Array.isArray(foreshadowing['edges']) ? foreshadowing['edges'] : [])
    .map((raw): ForeshadowEdge => {
      const edge = record(raw)
      return { from: text(edge['from']), to: text(edge['to']), type: text(edge['type']) }
    })

  const validation = record(root['foreshadowing_validation'])
  const graph = record(root['relationship_graph'])
  const relationNodes: RelationNode[] = (Array.isArray(graph['nodes']) ? graph['nodes'] : [])
    .map((raw): RelationNode => {
      const node = record(raw)
      return {
        id: text(node['id']),
        label: text(node['label']) || text(node['id']),
        kind: text(node['kind']),
        type: text(node['type']),
        status: text(node['status']),
        unresolved: node['unresolved'] === true,
      }
    })
  const relationEdges: RelationEdge[] = (Array.isArray(graph['edges']) ? graph['edges'] : [])
    .map((raw): RelationEdge => {
      const edge = record(raw)
      return {
        id: text(edge['id']),
        source: text(edge['source']),
        target: text(edge['target']),
        label: text(edge['label']),
        confirmed: edge['confirmed'] === true,
      }
    })

  return {
    foreshadowNodes,
    foreshadowEdges,
    validationErrors: Array.isArray(validation['errors'])
      ? validation['errors'].filter((item): item is string => typeof item === 'string')
      : [],
    relationNodes,
    relationEdges,
    relationTruncated: graph['truncated'] === true,
  }
}

/* --- foreshadowing layout: one column per layer, nodes ordered by target --- */

const LAYER_ORDER = ['主线', '支线', '彩蛋']
const NODE_W = 220
const NODE_H = 56
const NODE_GAP = 14
const COL_GAP = 40
const COL_PAD = 16
const HEADER_H = 30

interface PlacedForeshadow {
  node: ForeshadowNode
  x: number
  y: number
}

function layoutForeshadow(nodes: readonly ForeshadowNode[]): { placed: PlacedForeshadow[]; layers: string[]; width: number; height: number } {
  const layers = [...new Set(nodes.map(node => node.layer))].sort(
    (a, b) => (LAYER_ORDER.indexOf(a) === -1 ? 99 : LAYER_ORDER.indexOf(a)) - (LAYER_ORDER.indexOf(b) === -1 ? 99 : LAYER_ORDER.indexOf(b)),
  )
  const placed: PlacedForeshadow[] = []
  for (const [column, layer] of layers.entries()) {
    const columnNodes = nodes
      .filter(node => node.layer === layer)
      .sort((a, b) => (chapterNumber(a.targetChapter) ?? 9999) - (chapterNumber(b.targetChapter) ?? 9999))
    for (const [row, node] of columnNodes.entries()) {
      placed.push({
        node,
        x: COL_PAD + column * (NODE_W + COL_GAP),
        y: HEADER_H + COL_PAD + row * (NODE_H + NODE_GAP),
      })
    }
  }
  const maxRows = Math.max(1, ...layers.map(layer => nodes.filter(node => node.layer === layer).length))
  return {
    placed,
    layers,
    width: COL_PAD * 2 + layers.length * NODE_W + Math.max(0, layers.length - 1) * COL_GAP,
    height: HEADER_H + COL_PAD * 2 + maxRows * NODE_H + Math.max(0, maxRows - 1) * NODE_GAP,
  }
}

/* --- relationship layout: deterministic circle, chords for edges --- */

const REL_RADIUS = 260
const REL_NODE_R = 8
/** Above this many visible nodes, edge labels hide (they stay on <title> hover). */
const REL_EDGE_LABEL_LIMIT = 30
/** Above this many visible nodes, node labels clip harder (6 chars). */
const REL_DENSE_NODE_LIMIT = 40

/** Node-kind chip order; kinds outside this list bucket into 'other'. */
const REL_KIND_ORDER = ['character', 'faction', 'place', 'concept'] as const

type RelationKind = (typeof REL_KIND_ORDER)[number] | 'other'

/** Bucket a wire kind into its chip key. */
function relationKind(kind: string): RelationKind {
  return (REL_KIND_ORDER as readonly string[]).includes(kind) ? kind as RelationKind : 'other'
}

interface PlacedRelation {
  node: RelationNode
  x: number
  y: number
}

function layoutRelations(nodes: readonly RelationNode[]): { placed: PlacedRelation[]; size: number } {
  const ordered = [...nodes].sort((a, b) => a.id.localeCompare(b.id))
  const radius = Math.max(140, Math.min(REL_RADIUS, ordered.length * 22))
  const placed = ordered.map((node, index) => {
    const angle = (2 * Math.PI * index) / Math.max(1, ordered.length) - Math.PI / 2
    return {
      node,
      x: radius * Math.cos(angle),
      y: radius * Math.sin(angle),
    }
  })
  return { placed, size: radius * 2 + 140 }
}

/** Truncate a node label for display; the full text rides the <title> tooltip. */
function clip(value: string, max: number): string {
  return value.length > max ? `${value.slice(0, max - 1)}…` : value
}

/** Full graph-view props: conversation-view runtime share & injected fetch & locale seat. */
export type GraphViewProps =
  ConvViewProps & InjectFace<StudioApiInjected> & PropsLocale<'studio-panel'>

export function GraphView({ fetchStudioApi, t }: GraphViewProps) {
  const [state, setState] = useState<LoadState>('loading')
  const [payload, setPayload] = useState<ContinuityPayload | null>(null)
  const [error, setError] = useState('')
  const [segment, setSegment] = useState<Segment>('foreshadowing')
  // Story-relevant backbone by default: characters + factions.
  const [kindFilter, setKindFilter] = useState<ReadonlySet<RelationKind>>(new Set(['character', 'faction']))

  const load = useCallback(() => {
    setState('loading')
    let cancelled = false
    fetchStudioApi('/continuity')
      .then((data) => {
        if (cancelled) return
        setPayload(parseContinuity(data))
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

  const foreshadow = payload !== null ? layoutForeshadow(payload.foreshadowNodes) : null
  // Kind filtering: edges render only when both endpoints stay visible.
  const visibleRelationNodes = payload === null ? [] : payload.relationNodes.filter(node => kindFilter.has(relationKind(node.kind)))
  const relations = layoutRelations(visibleRelationNodes)
  const relationPositions = new Map(relations.placed.map(item => [item.node.id, item]))
  const visibleRelationEdges = payload === null ? [] : payload.relationEdges.filter(
    edge => relationPositions.has(edge.source) && relationPositions.has(edge.target),
  )
  const showEdgeLabels = visibleRelationNodes.length <= REL_EDGE_LABEL_LIMIT
  const nodeLabelClip = visibleRelationNodes.length > REL_DENSE_NODE_LIMIT ? 6 : 10
  // Chips for the kinds actually present in the data (in canonical order, 'other' last).
  const presentKinds = payload === null ? [] : [...REL_KIND_ORDER, 'other' as const]
    .filter(kind => payload.relationNodes.some(node => relationKind(node.kind) === kind))
  const toggleKind = (kind: RelationKind) => {
    setKindFilter(previous => {
      const next = new Set(previous)
      if (next.has(kind)) next.delete(kind)
      else next.add(kind)
      return next
    })
  }

  return (
    <div className={css.root}>
      <div className={css.toolbar}>
        <span className={css.toolbarMeta}>
          <button
            type="button"
            className={css.chip}
            data-active={segment === 'foreshadowing'}
            onClick={() => { setSegment('foreshadowing') }}
          >
            {t('graph.foreshadowing')} {payload?.foreshadowNodes.length ?? 0}
          </button>
          <button
            type="button"
            className={css.chip}
            data-active={segment === 'relationships'}
            onClick={() => { setSegment('relationships') }}
          >
            {t('graph.relationships')} {visibleRelationEdges.length}/{payload?.relationEdges.length ?? 0}
          </button>
          {payload !== null && payload.validationErrors.length > 0 && (
            <span className={css.errorText}>
              {t('graph.validation.errors')}: {payload.validationErrors.length}
            </span>
          )}
          {segment === 'relationships' && payload?.relationTruncated === true && (
            <span className={css.truncatedNote}>{t('graph.truncated')}</span>
          )}
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
        {state === 'ready' && payload !== null && segment === 'foreshadowing' && foreshadow !== null && (
          payload.foreshadowNodes.length === 0
            ? <div className={css.notice}>{t('graph.empty.foreshadowing')}</div>
            : (
              <svg
                className={css.graphCanvas}
                viewBox={`0 0 ${foreshadow.width} ${foreshadow.height}`}
                role="img"
                aria-label={t('graph.foreshadowing')}
              >
                <defs>
                  <marker id="studio-panel-arrow" viewBox="0 0 8 8" refX="7" refY="4"
                    markerWidth="7" markerHeight="7" orient="auto-start-reverse">
                    <path d="M 0 0 L 8 4 L 0 8 z" className={css.edgeArrow} />
                  </marker>
                </defs>
                {foreshadow.layers.map((layer, column) => (
                  <text
                    key={layer}
                    x={COL_PAD + column * (NODE_W + COL_GAP)}
                    y={COL_PAD + 6}
                    className={css.graphColumnHeader}
                  >
                    {layer}
                  </text>
                ))}
                {payload.foreshadowEdges.map(edge => {
                  const source = foreshadow.placed.find(item => item.node.id === edge.from)
                  const target = foreshadow.placed.find(item => item.node.id === edge.to)
                  if (source === undefined || target === undefined) return null
                  return (
                    <line
                      key={`${edge.from}->${edge.to}`}
                      x1={source.x + NODE_W} y1={source.y + NODE_H / 2}
                      x2={target.x} y2={target.y + NODE_H / 2}
                      className={css.edge}
                      markerEnd="url(#studio-panel-arrow)"
                    />
                  )
                })}
                {foreshadow.placed.map(({ node, x, y }) => (
                  <g key={node.id}>
                    <rect x={x} y={y} width={NODE_W} height={NODE_H} rx={8}
                      className={css.foreshadowNode} data-status={node.status} />
                    <text x={x + 10} y={y + 20} className={css.graphNodeTitle}>
                      {clip(node.content, 16)}
                    </text>
                    <text x={x + 10} y={y + 40} className={css.graphNodeMeta}>
                      {[
                        `${t('graph.weight')} ${node.weight}`,
                        node.targetChapter !== '' ? `${t('graph.target')} ${node.targetChapter}` : '',
                        node.status,
                      ].filter(part => part !== '').join(' · ')}
                    </text>
                    <title>{`${node.id} · ${node.content}`}</title>
                  </g>
                ))}
              </svg>
            )
        )}
        {state === 'ready' && payload !== null && segment === 'relationships' && (
          <>
            {presentKinds.length > 1 && (
              <div className={css.kindFilterRow}>
                {presentKinds.map(kind => (
                  <button
                    key={kind}
                    type="button"
                    className={css.chip}
                    data-active={kindFilter.has(kind)}
                    onClick={() => { toggleKind(kind) }}
                  >
                    {t(`graph.kind.${kind}`)} {payload.relationNodes.filter(node => relationKind(node.kind) === kind).length}
                  </button>
                ))}
              </div>
            )}
            {visibleRelationNodes.length === 0
              ? <div className={css.notice}>{t('graph.empty.relationships')}</div>
              : (
                <svg
                  className={css.graphCanvas}
                  viewBox={`${-relations.size / 2} ${-relations.size / 2} ${relations.size} ${relations.size}`}
                  role="img"
                  aria-label={t('graph.relationships')}
                >
                  <defs>
                    <marker id="studio-panel-rel-arrow" viewBox="0 0 8 8" refX="7" refY="4"
                      markerWidth="7" markerHeight="7" orient="auto-start-reverse">
                      <path d="M 0 0 L 8 4 L 0 8 z" className={css.edgeArrow} />
                    </marker>
                  </defs>
                  {visibleRelationEdges.map(edge => {
                    const source = relationPositions.get(edge.source)
                    const target = relationPositions.get(edge.target)
                    if (source === undefined || target === undefined) return null
                    // Quadratic chord bending toward the center keeps direction readable.
                    const mx = (source.x + target.x) / 2
                    const my = (source.y + target.y) / 2
                    const cx = mx * 0.3
                    const cy = my * 0.3
                    // Trim the line ends so arrows land on the node rim.
                    const dx = target.x - source.x
                    const dy = target.y - source.y
                    const length = Math.hypot(dx, dy) || 1
                    const trim = REL_NODE_R + 4
                    return (
                      <g key={edge.id}>
                        <path
                          d={`M ${source.x + (dx / length) * trim} ${source.y + (dy / length) * trim}`
                            + ` Q ${cx} ${cy} ${target.x - (dx / length) * trim} ${target.y - (dy / length) * trim}`}
                          className={css.edge}
                          data-confirmed={edge.confirmed}
                          markerEnd="url(#studio-panel-rel-arrow)"
                        />
                        {showEdgeLabels && edge.label !== '' && (
                          <text x={mx * 0.65} y={my * 0.65} className={css.edgeLabel}>
                            {clip(edge.label, 8)}
                          </text>
                        )}
                        <title>{`${edge.source} → ${edge.label} → ${edge.target}`}</title>
                      </g>
                    )
                  })}
                  {relations.placed.map(({ node, x, y }) => (
                    <g key={node.id}>
                      <circle cx={x} cy={y} r={REL_NODE_R}
                        className={css.relationNode} data-kind={node.kind} data-unresolved={node.unresolved} />
                      <text x={x + REL_NODE_R + 5} y={y + 4} className={css.graphNodeTitle}>
                        {clip(node.label, nodeLabelClip)}
                      </text>
                      <title>{`${node.label} · ${node.type}${node.unresolved ? ' · unresolved' : ''}`}</title>
                    </g>
                  ))}
                </svg>
              )
            }
          </>
        )}
      </div>
    </div>
  )
}
