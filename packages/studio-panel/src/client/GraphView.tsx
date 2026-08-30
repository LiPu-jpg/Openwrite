/**
 * Graph view (图谱): OpenWrite continuity data as SVG and React Flow — the
 * foreshadowing board (layered by 主线/支线/彩蛋, ordered by target chapter)
 * and the interactive character/world relationship graph (circular seed layout).
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
 *   // 事实账本: three markdown DOCUMENTS (truth_manager.py TruthFiles), not
 *   // structured rows — rendered as-is with MarkdownText.
 *   truth: { current_state: string, ledger: string, relationships: string },
 *   // 章节工作流 (workflow_scheduler.py): stages carry
 *   // status pending/running/completed/failed/skipped.
 *   workflows: [{ chapter_id, current_stage, error,
 *                 stages: [{ name, status, message }] }],
 * }
 *
 * Sections (toolbar chips): 伏笔 (board + DAG validation errors), 关系图
 * (kind-filtered interactive canvas), 事实账本 (the three truth documents), 工作流
 * (per-chapter pipeline stages). All read-only.
 */

import { useCallback, useEffect, useMemo, useState, type ReactNode } from 'react'
import type { ConvViewProps } from '@deepseek-ai/dsh-client-ui-conversation/client'
import { MarkdownText } from '@deepseek-ai/dsh-client-ui-primitives'
import type { InjectFace, PropsLocale } from '@deepseek-ai/dsh-client-ui-slots'
import type { StudioApiInjected } from './api.ts'
import { useWorkbench } from './WorkbenchStore.ts'
import ELK from 'elkjs/lib/elk.bundled.js'
import { ReviewDagView } from './DagCanvas.tsx'
import {
  Background,
  BackgroundVariant,
  Controls,
  MarkerType,
  ReactFlow,
  useEdgesState,
  useNodesState,
  type Edge,
  type Node,
  type ReactFlowInstance,
} from '@xyflow/react'
import 'dsh-react-flow-style'
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
  description: string
  sourcePath: string
  unresolved: boolean
}

interface RelationEdge {
  id: string
  source: string
  target: string
  label: string
  kind: string
  origin: string
  sourceLabel: string
  confirmed: boolean
}

/** 事实账本: the three truth markdown documents. */
interface TruthDocs {
  currentState: string
  ledger: string
  relationships: string
}

interface WorkflowStage {
  name: string
  status: string
  message: string
}

/** One chapter pipeline (workflows[] entry). */
interface WorkflowItem {
  chapterId: string
  currentStage: string
  error: string
  stages: WorkflowStage[]
}

interface ContinuityPayload {
  foreshadowNodes: ForeshadowNode[]
  foreshadowEdges: ForeshadowEdge[]
  validationErrors: string[]
  relationNodes: RelationNode[]
  relationEdges: RelationEdge[]
  relationTruncated: boolean
  truth: TruthDocs
  workflows: WorkflowItem[]
}

type LoadState = 'loading' | 'error' | 'ready'
type Segment = 'foreshadowing' | 'relationships' | 'truth' | 'workflows' | 'review' | 'delivery'

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
        id: text(node['id']), label: text(node['label']) || text(node['id']), kind: text(node['kind']),
        type: text(node['type']), status: text(node['status']), description: text(node['description']),
        sourcePath: text(node['source_path']), unresolved: node['unresolved'] === true,
      }
    })
  const relationEdges: RelationEdge[] = (Array.isArray(graph['edges']) ? graph['edges'] : [])
    .map((raw): RelationEdge => {
      const edge = record(raw)
      return {
        id: text(edge['id']), source: text(edge['source']), target: text(edge['target']), label: text(edge['label']),
        kind: text(edge['kind']), origin: text(edge['origin']), sourceLabel: text(edge['source_label']),
        confirmed: edge['confirmed'] === true,
      }
    })

  const truthRaw = record(root['truth'])
  const truth: TruthDocs = {
    currentState: text(truthRaw['current_state']),
    ledger: text(truthRaw['ledger']),
    relationships: text(truthRaw['relationships']),
  }
  const workflows: WorkflowItem[] = (Array.isArray(root['workflows']) ? root['workflows'] : [])
    .map((raw): WorkflowItem => {
      const workflow = record(raw)
      return {
        chapterId: text(workflow['chapter_id']),
        currentStage: text(workflow['current_stage']),
        error: text(workflow['error']),
        stages: (Array.isArray(workflow['stages']) ? workflow['stages'] : [])
          .map((stageRaw): WorkflowStage => {
            const stage = record(stageRaw)
            return { name: text(stage['name']), status: text(stage['status']), message: text(stage['message']) }
          }),
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
    truth,
    workflows,
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

/* --- relationship layout: deterministic force-directed seed for React Flow --- */

const REL_NODE_W = 156
const REL_NODE_H = 52
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

async function layoutRelations(nodes: readonly RelationNode[], edges: readonly RelationEdge[] = []): Promise<{ placed: PlacedRelation[]; size: number }> {
  const ordered = [...nodes].sort((a, b) => a.id.localeCompare(b.id))
  const nodeById = new Map(ordered.map(node => [node.id, node]))
  const graph = {
    id: 'relations',
    layoutOptions: {
      'elk.algorithm': 'layered',
      'elk.direction': 'RIGHT',
      'elk.layered.spacing.nodeNodeBetweenLayers': '64',
      'elk.spacing.nodeNode': '28',
      'elk.layered.considerModelOrder.strategy': 'NODES_AND_EDGES',
    },
    children: ordered.map(node => ({ id: node.id, width: REL_NODE_W, height: REL_NODE_H })),
    edges: edges.filter(edge => nodeById.has(edge.source) && nodeById.has(edge.target)).map(edge => ({
      id: edge.id, sources: [edge.source], targets: [edge.target],
    })),
  }
  try {
    const result = await new ELK().layout(graph)
    const placed = (result.children ?? []).flatMap(child => {
      const node = nodeById.get(child.id)
      return node === undefined ? [] : [{ node, x: (child.x ?? 0) + 40, y: (child.y ?? 0) + 40 }]
    })
    const maxX = Math.max(1, ...placed.map(item => item.x + REL_NODE_W + 40))
    const maxY = Math.max(1, ...placed.map(item => item.y + REL_NODE_H + 40))
    return { placed, size: Math.max(maxX, maxY) }
  } catch {
    const placed = ordered.map((node, index) => ({ node, x: (index % 4) * 220 + 40, y: Math.floor(index / 4) * 110 + 40 }))
    const maxX = Math.max(1, ...placed.map(item => item.x + REL_NODE_W + 40))
    const maxY = Math.max(1, ...placed.map(item => item.y + REL_NODE_H + 40))
    return { placed, size: Math.max(maxX, maxY) }
  }
}

function relationNodeColor(kind: string): string {
  if (kind === 'character') return 'business'
  if (kind === 'faction') return 'warn'
  if (kind === 'place') return 'success'
  if (kind === 'concept') return 'info'
  return 'neutral'
}

function relationNodeLabel(node: RelationNode): ReactNode {
  return <div className={css.relationFlowNode} data-kind={relationNodeColor(node.kind)}>
    <strong title={node.label}>{node.label}</strong>
    <small>{node.type || node.kind || 'entity'}{node.unresolved ? ' · unresolved' : ''}</small>
  </div>
}

interface RelationshipFlowProps {
  nodes: RelationNode[]
  edges: RelationEdge[]
  t: PropsLocale<'studio-panel'>['t']
}

function RelationshipFlow({ nodes: relationNodes, edges: relationEdges, t }: RelationshipFlowProps) {
  const [nodes, setNodes, onNodesChange] = useNodesState<Node>([])
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>([])
  const [flow, setFlow] = useState<ReactFlowInstance<Node, Edge> | null>(null)
  const [selectedId, setSelectedId] = useState('')
  const [moving, setMoving] = useState(false)
  const relationById = useMemo(() => new Map(relationNodes.map(node => [node.id, node])), [relationNodes])
  const selected = selectedId !== '' ? relationById.get(selectedId) : undefined
  const [selectedEdgeId, setSelectedEdgeId] = useState('')
  const edgeById = useMemo(() => new Map(relationEdges.map(edge => [edge.id, edge])), [relationEdges])
  const selectedEdge = selectedEdgeId !== '' ? edgeById.get(selectedEdgeId) : undefined
  const neighbors = selected === undefined ? [] : relationEdges.flatMap(edge => {
    if (edge.source === selected.id) return relationById.get(edge.target) ? [relationById.get(edge.target)!] : []
    if (edge.target === selected.id) return relationById.get(edge.source) ? [relationById.get(edge.source)!] : []
    return []
  })

  useEffect(() => {
    let active = true
    void layoutRelations(relationNodes, relationEdges).then(({ placed }) => {
      if (!active) return
      let saved: Record<string, { x: number; y: number }> = {}
      try {
        const raw = window.localStorage.getItem('dsh-novel.relationPositions')
        const parsed = raw ? JSON.parse(raw) : {}
        if (parsed !== null && typeof parsed === 'object') saved = parsed as Record<string, { x: number; y: number }>
      } catch { /* unavailable or corrupt local storage */ }
      const nextNodes: Node[] = placed.map(({ node, x, y }) => {
        const position = saved[node.id]
        return {
          id: node.id, type: 'default', position: position && Number.isFinite(position.x) && Number.isFinite(position.y) ? position : { x, y },
          data: { label: relationNodeLabel(node) }, className: css.relationFlowNodeShell ?? '',
          style: { width: REL_NODE_W, minHeight: REL_NODE_H, padding: 0, border: 'none', background: 'transparent', boxShadow: 'none' },
        }
      })
      const visibleIds = new Set(relationNodes.map(node => node.id))
      const nextEdges: Edge[] = relationEdges
        .filter(edge => visibleIds.has(edge.source) && visibleIds.has(edge.target))
        .map(edge => ({
          id: edge.id, source: edge.source, target: edge.target,
          ...(edge.label === '' ? {} : { label: edge.label }), animated: false,
          markerEnd: { type: MarkerType.ArrowClosed },
          style: { strokeWidth: edge.confirmed ? 1.5 : 1, strokeDasharray: edge.confirmed ? undefined : '5 4' },
        }))
      setNodes(nextNodes)
      setEdges(nextEdges)
      const frame = requestAnimationFrame(() => {
        if (flow !== null) void flow.fitView({ padding: 0.22, minZoom: 0.45, maxZoom: 1.2 })
      })
      window.setTimeout(() => cancelAnimationFrame(frame), 0)
    })
    return () => { active = false }
  }, [flow, relationEdges, relationNodes, setEdges, setNodes])

  useEffect(() => {
    setEdges(current => current.map(edge => edge.animated === moving ? edge : { ...edge, animated: moving }))
  }, [moving, setEdges])

  useEffect(() => {
    if (selectedId !== '' && !relationById.has(selectedId)) setSelectedId('')
  }, [relationById, selectedId])

  return <div className={css.relationshipWorkspace} data-detail={selected !== undefined}>
    <div className={css.relationshipCanvas}>
      <ReactFlow
        nodes={nodes}
        edges={edges}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onInit={setFlow}
        onNodeClick={(_event, node) => { setSelectedId(node.id); setSelectedEdgeId('') }}
        onEdgeClick={(_event, edge) => { setSelectedEdgeId(edge.id); setSelectedId('') }}
        onNodeDragStart={() => setMoving(true)}
        onNodeDragStop={(_event, node) => { setMoving(false); try { const current = JSON.parse(window.localStorage.getItem('dsh-novel.relationPositions') || '{}') as Record<string, unknown>; current[node.id] = node.position; window.localStorage.setItem('dsh-novel.relationPositions', JSON.stringify(current)) } catch { /* unavailable storage */ } }}
        nodesDraggable
        nodesConnectable={false}
        elementsSelectable
        fitView
        minZoom={0.25}
        maxZoom={2}
        proOptions={{ hideAttribution: true }}
      >
        <Controls showInteractive={false} />
        <Background variant={BackgroundVariant.Dots} gap={22} size={1} />
      </ReactFlow>
    </div>
    {(selected !== undefined || selectedEdge !== undefined) && <aside className={css.relationshipDetail}>
      {selectedEdge !== undefined ? <>
        <div className={css.detailHeading}>{selectedEdge.label || selectedEdge.id}</div>
        <div className={css.dagDetailRow}><b>{t('graph.edgeType')}</b><span>{selectedEdge.kind || 'relation'}</span></div>
        <div className={css.dagDetailRow}><b>{t('graph.origin')}</b><span>{selectedEdge.origin || '—'} · {selectedEdge.confirmed ? t('graph.confirmed') : t('graph.unresolved')}</span></div>
        <div className={css.dagDetailRow}><b>{t('graph.source')}</b><span>{selectedEdge.sourceLabel || selectedEdge.source} → {selectedEdge.target}</span></div>
      </> : selected !== undefined ? <>
        <div className={css.detailHeading}>{selected.label}</div>
        <div className={css.dagDetailRow}><b>{t('graph.entityType')}</b><span>{selected.type || selected.kind || '—'}</span></div>
        <div className={css.dagDetailRow}><b>{t('graph.entityStatus')}</b><span>{selected.status || '—'}</span></div>
        {selected.description !== '' && <p className={css.detailNotice}>{selected.description}</p>}
        {selected.sourcePath !== '' && <a href={`/studio-panel/api/document?path=${encodeURIComponent(selected.sourcePath)}`} target="_blank" rel="noreferrer">{t('graph.source')}</a>}
        {neighbors.length > 0 && <><div className={css.detailHeading}>{t('graph.neighbors')}</div><ul className={css.validationList}>{neighbors.map(neighbor => <li key={neighbor.id}><button type="button" className={css.linkButton} onClick={() => setSelectedId(neighbor.id)}>{neighbor.label}</button></li>)}</ul></>}
        {selected.unresolved && <div className={css.taskError}>{t('graph.unresolved')}</div>}
      </> : null}
    </aside>}
  </div>
}
/** Truncate a node label for display; the full text rides the <title> tooltip. */
function clip(value: string, max: number): string {
  return value.length > max ? `${value.slice(0, max - 1)}…` : value
}

/** Full graph-view props: conversation-view runtime share & injected fetch & locale seat. */
export type GraphViewProps =
  ConvViewProps & InjectFace<StudioApiInjected> & PropsLocale<'studio-panel'>

export function GraphView({ fetchStudioApi, postStudioApi, t }: GraphViewProps) {
  const workbench = useWorkbench()
  // 评审/交付 DAG 由评审任务产出：任务失效即重载 DAG 视图。
  const dagEpoch = workbench.epochs.tasks
  const [state, setState] = useState<LoadState>('loading')
  const [payload, setPayload] = useState<ContinuityPayload | null>(null)
  const [error, setError] = useState('')
  const [segment, setSegment] = useState<Segment>('foreshadowing')
  // Story-relevant backbone by default: characters + factions.
  const [kindFilter, setKindFilter] = useState<ReadonlySet<RelationKind>>(new Set(['character', 'faction']))
  const [relationQuery, setRelationQuery] = useState(() => {
    try { return window.localStorage.getItem('dsh-novel.relationQuery') ?? '' } catch { return '' }
  })
  const [connectedOnly, setConnectedOnly] = useState(() => {
    try { return window.localStorage.getItem('dsh-novel.relationConnectedOnly') === 'true' } catch { return false }
  })

  useEffect(() => {
    try {
      window.localStorage.setItem('dsh-novel.relationQuery', relationQuery)
      window.localStorage.setItem('dsh-novel.relationConnectedOnly', String(connectedOnly))
    } catch { /* unavailable storage */ }
  }, [connectedOnly, relationQuery])

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
  const query = relationQuery.trim().toLocaleLowerCase()
  const connectedIds = new Set((payload?.relationEdges ?? []).flatMap(edge => [edge.source, edge.target]))
  const visibleRelationNodes = payload === null ? [] : payload.relationNodes.filter(node => {
    const matchesQuery = query === '' || `${node.label} ${node.description} ${node.id}`.toLocaleLowerCase().includes(query)
    return kindFilter.has(relationKind(node.kind)) && matchesQuery && (!connectedOnly || connectedIds.has(node.id))
  })
  const visibleRelationIds = new Set(visibleRelationNodes.map(node => node.id))
  const visibleRelationEdges = payload === null ? [] : payload.relationEdges.filter(
    edge => visibleRelationIds.has(edge.source) && visibleRelationIds.has(edge.target),
  )
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
            {payload !== null && payload.validationErrors.length > 0 && (
              <span className={css.errorText}> ⚠{payload.validationErrors.length}</span>
            )}
          </button>
          <button
            type="button"
            className={css.chip}
            data-active={segment === 'relationships'}
            onClick={() => { setSegment('relationships') }}
          >
            {t('graph.relationships')} {visibleRelationEdges.length}/{payload?.relationEdges.length ?? 0}
          </button>
          <button
            type="button"
            className={css.chip}
            data-active={segment === 'truth'}
            onClick={() => { setSegment('truth') }}
          >
            {t('graph.truth')}
          </button>
          <button
            type="button"
            className={css.chip}
            data-active={segment === 'workflows'}
            onClick={() => { setSegment('workflows') }}
          >
            {t('graph.workflows')} {payload?.workflows.length ?? 0}
          </button>
          <button
            type="button"
            className={css.chip}
            data-active={segment === 'review'}
            onClick={() => { setSegment('review') }}
          >
            {t('graph.reviewDag')}
          </button>
          <button
            type="button"
            className={css.chip}
            data-active={segment === 'delivery'}
            onClick={() => { setSegment('delivery') }}
          >
            {t('graph.deliveryDag')}
          </button>
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
          <>
            {payload.validationErrors.length > 0 && (
              <div className={css.validationBlock}>
                <div className={css.detailHeading}>
                  {t('graph.validation.errors')} ({payload.validationErrors.length})
                </div>
                <ul className={css.validationList}>
                  {payload.validationErrors.map(item => (
                    <li key={item} className={css.errorText}>{item}</li>
                  ))}
                </ul>
              </div>
            )}
            {payload.foreshadowNodes.length === 0
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
            )}
          </>
        )}
        {state === 'ready' && payload !== null && segment === 'relationships' && (
          <>
            <div className={css.graphFilterRow}>
              <input aria-label={t('graph.search')} placeholder={t('graph.search')} value={relationQuery} onChange={event => setRelationQuery(event.target.value)} />
              <label><input type="checkbox" checked={connectedOnly} onChange={event => setConnectedOnly(event.target.checked)} /> {t('graph.connectedOnly')}</label>
              <span>{visibleRelationNodes.length}/{payload.relationNodes.length} · {visibleRelationEdges.length}/{payload.relationEdges.length}</span>
            </div>
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
              : <RelationshipFlow nodes={visibleRelationNodes} edges={visibleRelationEdges} t={t} />}
          </>
        )}
        {state === 'ready' && payload !== null && segment === 'truth' && (
          payload.truth.currentState === '' && payload.truth.ledger === '' && payload.truth.relationships === ''
            ? <div className={css.notice}>{t('graph.empty.truth')}</div>
            : (
              <div className={css.detail}>
                {([
                  ['graph.truth.currentState', payload.truth.currentState],
                  ['graph.truth.ledger', payload.truth.ledger],
                  ['graph.truth.relationships', payload.truth.relationships],
                ] as const).map(([key, document_]) => (
                  <section key={key} className={css.truthSection}>
                    <div className={css.detailHeading}>{t(key)}</div>
                    {document_ === ''
                      ? <div className={css.detailNotice}>{t('graph.empty.truthDoc')}</div>
                      : <div className={css.detailBody}><MarkdownText text={document_} /></div>}
                  </section>
                ))}
              </div>
            )
        )}
        {state === 'ready' && payload !== null && segment === 'workflows' && (
          payload.workflows.length === 0
            ? <div className={css.notice}>{t('graph.empty.workflows')}</div>
            : payload.workflows.map(workflow => (
              <div key={workflow.chapterId} className={css.workflowBlock}>
                <div className={css.taskRow}>
                  <span className={css.taskChapter}>{workflow.chapterId || '—'}</span>
                  <span className={css.taskSummary}>
                    {t('graph.workflow.currentStage')}: {workflow.currentStage || '—'}
                  </span>
                </div>
                {workflow.error !== '' && <div className={css.taskError}>{workflow.error}</div>}
                <div className={css.workflowStages}>
                  {workflow.stages.map(stage => (
                    <span
                      key={stage.name}
                      className={css.taskStatus}
                      data-status={stage.status}
                      title={stage.message !== '' ? stage.message : undefined}
                    >
                      {stage.name}
                    </span>
                  ))}
                </div>
              </div>
            ))
        )}
        {state === 'ready' && segment === 'review' && (
          <ReviewDagView key={dagEpoch} fetchStudioApi={fetchStudioApi} postStudioApi={postStudioApi} kind="review" t={t} />
        )}
        {state === 'ready' && segment === 'delivery' && (
          <ReviewDagView key={dagEpoch} fetchStudioApi={fetchStudioApi} postStudioApi={postStudioApi} kind="delivery" t={t} />
        )}
      </div>
    </div>
  )
}
