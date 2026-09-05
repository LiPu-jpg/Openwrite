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

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { ConvViewProps } from '@deepseek-ai/dsh-client-ui-conversation/client'
import { MarkdownText } from '@deepseek-ai/dsh-client-ui-primitives'
import type { InjectFace, PropsLocale } from '@deepseek-ai/dsh-client-ui-slots'
import type { StudioApiInjected } from './api.ts'
import { API_PROXY_BASE, studioContextHeaders } from './api.ts'
import { storageKey } from './storage.ts'
import { useWorkbench } from './WorkbenchStore.ts'
import { ReviewDagView } from './DagCanvas.tsx'
import * as d3 from 'd3'
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

/* --- relationship layout: force-directed seed for the interactive canvas --- */

const REL_CANVAS_MIN = 560
const RELATION_POSITIONS_KEY = 'dsh-novel.relationPositions.v2'
/** Node-kind chip order; kinds outside this list bucket into 'other'. */
const REL_KIND_ORDER = ['character', 'faction', 'place', 'concept'] as const

type RelationKind = (typeof REL_KIND_ORDER)[number] | 'other'

/** Bucket a wire kind into its chip key. */
function relationKind(kind: string): RelationKind {
  return (REL_KIND_ORDER as readonly string[]).includes(kind) ? kind as RelationKind : 'other'
}

function relationNodeColor(kind: string): string {
  if (kind === 'character') return 'business'
  if (kind === 'faction') return 'warn'
  if (kind === 'place') return 'success'
  if (kind === 'concept') return 'info'
  return 'neutral'
}

interface RelationshipFlowProps {
  nodes: RelationNode[]
  edges: RelationEdge[]
  t: PropsLocale<'studio-panel'>['t']
}

interface RelationRenderNode {
  id: string
}

function RelationshipFlow({ nodes: relationNodes, edges: relationEdges, t }: RelationshipFlowProps) {
  const workspaceId = useWorkbench().context?.workspaceId
  const containerRef = useRef<HTMLDivElement>(null)
  const svgRef = useRef<SVGSVGElement>(null)
  const [selectedId, setSelectedId] = useState('')
  const relationById = useMemo(() => new Map(relationNodes.map(node => [node.id, node])), [relationNodes])
  const selected = selectedId !== '' ? relationById.get(selectedId) : undefined
  const [selectedEdgeId, setSelectedEdgeId] = useState('')
  const [layoutNonce, setLayoutNonce] = useState(0)
  const edgeById = useMemo(() => new Map(relationEdges.map(edge => [edge.id, edge])), [relationEdges])
  const selectedEdge = selectedEdgeId !== '' ? edgeById.get(selectedEdgeId) : undefined
  const neighbors = selected === undefined ? [] : relationEdges.flatMap(edge => {
    if (edge.source === selected.id) return relationById.get(edge.target) ? [relationById.get(edge.target)!] : []
    if (edge.target === selected.id) return relationById.get(edge.source) ? [relationById.get(edge.source)!] : []
    return []
  })

  useEffect(() => {
    const container = containerRef.current
    const svgElement = svgRef.current
    if (!container || !svgElement || relationNodes.length === 0) return
    const width = Math.max(640, container.clientWidth)
    const height = Math.max(REL_CANVAS_MIN, container.clientHeight)
    const svg = d3.select(svgElement).attr('width', width).attr('height', height).attr('viewBox', `0 0 ${width} ${height}`)
    svg.selectAll('*').remove()
    const defs = svg.append('defs')
    const glow = defs.append('filter').attr('id', `relation-glow-${layoutNonce}`).attr('x', '-50%').attr('y', '-50%').attr('width', '200%').attr('height', '200%')
    glow.append('feGaussianBlur').attr('stdDeviation', 4).attr('result', 'blur')
    const merge = glow.append('feMerge')
    merge.append('feMergeNode').attr('in', 'blur')
    merge.append('feMergeNode').attr('in', 'SourceGraphic')
    const root = svg.append('g')
    const zoom = d3.zoom<SVGSVGElement, unknown>().scaleExtent([0.15, 5]).on('zoom', event => root.attr('transform', event.transform))
    svg.call(zoom)

    interface SimNode extends RelationNode { x: number; y: number; fx?: number | null; fy?: number | null; linkCount: number }
    interface SimLink { source: string | SimNode; target: string | SimNode; edge: RelationEdge }
    const degree = new Map<string, number>()
    relationEdges.forEach(edge => {
      degree.set(edge.source, (degree.get(edge.source) ?? 0) + 1)
      degree.set(edge.target, (degree.get(edge.target) ?? 0) + 1)
    })
    let saved: Record<string, { x: number; y: number }> = {}
    try {
      const raw = window.localStorage.getItem(storageKey(RELATION_POSITIONS_KEY, workspaceId))
      const parsed: unknown = raw ? JSON.parse(raw) : {}
      if (parsed !== null && typeof parsed === 'object') saved = parsed as Record<string, { x: number; y: number }>
    } catch { /* unavailable or corrupt local storage */ }
    const simNodes: SimNode[] = relationNodes.map((node, index) => {
      const prior = saved[node.id]
      const angle = (2 * Math.PI * index) / Math.max(1, relationNodes.length)
      return {
        ...node,
        linkCount: degree.get(node.id) ?? 0,
        x: prior?.x ?? width / 2 + Math.cos(angle) * Math.min(width, height) * 0.28,
        y: prior?.y ?? height / 2 + Math.sin(angle) * Math.min(width, height) * 0.28,
        // Positions written after a drag are restored as pinned nodes, so a
        // later selection or data refresh cannot undo the user's arrangement.
        ...(prior !== undefined ? { fx: prior.x, fy: prior.y } : {}),
      }
    })
    const simLinks: SimLink[] = relationEdges
      .filter(edge => relationById.has(edge.source) && relationById.has(edge.target))
      .map(edge => ({ source: edge.source, target: edge.target, edge }))
    const nodeRadius = (node: SimNode) => Math.max(5, Math.sqrt(node.linkCount + 1) * 5.5)
    const simulation = d3.forceSimulation<SimNode>(simNodes)
      .force('link', d3.forceLink<SimNode, SimLink>(simLinks).id(node => node.id).distance(160).strength(0.35))
      .force('charge', d3.forceManyBody<SimNode>().strength(-400))
      .force('center', d3.forceCenter(width / 2, height / 2))
      .force('collision', d3.forceCollide<SimNode>().radius(node => nodeRadius(node) + 10))
      .force('x', d3.forceX<SimNode>(width / 2).strength(0.03))
      .force('y', d3.forceY<SimNode>(height / 2).strength(0.03))
    const link = root.append('g').attr('class', css.relationD3Links ?? '').selectAll<SVGLineElement, SimLink>('line').data(simLinks).join('line')
      .attr('stroke-width', edge => edge.edge.confirmed ? 1.2 : 1)
      .attr('stroke-dasharray', edge => edge.edge.confirmed ? null : '5 4')
      .attr('data-edge-id', edge => edge.edge.id)
      .on('click', (event, edge) => { event.stopPropagation(); setSelectedEdgeId(edge.edge.id); setSelectedId('') })
    const node = root.append('g').attr('class', css.relationD3Nodes ?? '').selectAll<SVGGElement, SimNode>('g').data(simNodes).join('g')
      .attr('data-node-id', item => item.id)
      .style('cursor', 'pointer')
      .call(d3.drag<SVGGElement, SimNode>()
        .on('start', (event, item) => { if (!event.active) simulation.alphaTarget(0.3).restart(); item.fx = item.x; item.fy = item.y })
        .on('drag', (event, item) => { item.fx = event.x; item.fy = event.y })
        .on('end', (event, item) => {
          if (!event.active) simulation.alphaTarget(0)
          // Keep a manually arranged node pinned. Releasing fx/fy here lets
          // the simulation pull it back to its old equilibrium a few seconds
          // later, which makes saved graph layouts appear to "jump" back.
          item.fx = item.x; item.fy = item.y
          try {
            const key = storageKey(RELATION_POSITIONS_KEY, workspaceId)
            const current = JSON.parse(window.localStorage.getItem(key) || '{}') as Record<string, unknown>
            current[item.id] = { x: item.x, y: item.y }
            window.localStorage.setItem(key, JSON.stringify(current))
          } catch { /* unavailable storage */ }
        }))
    node.append('circle')
      .attr('r', item => nodeRadius(item))
      .attr('class', css.relationD3Circle ?? '')
      .attr('data-kind', item => relationNodeColor(item.kind))
      .attr('data-selected', item => item.id === selectedId ? 'true' : 'false')
      .attr('filter', `url(#relation-glow-${layoutNonce})`)
    node.append('text')
      .text(item => clip(item.label, 16))
      .attr('dx', item => nodeRadius(item) + 7)
      .attr('dy', 4)
      .attr('class', css.relationD3Label ?? '')
      .attr('pointer-events', 'none')
    node.append('title').text(item => `${item.label} · ${item.type || item.kind || 'entity'}`)
    node.on('click', (event, item) => { event.stopPropagation(); setSelectedId(item.id); setSelectedEdgeId('') })
    node.on('mouseover', (_event, item) => {
      const related = new Set(relationEdges.flatMap(edge => edge.source === item.id ? [edge.target] : edge.target === item.id ? [edge.source] : []))
      node.select('circle').attr('data-hovered', current => current.id === item.id ? 'true' : related.has(current.id) ? 'neighbor' : 'dimmed')
      node.select('text').attr('data-hovered', current => current.id === item.id || related.has(current.id) ? 'true' : 'false')
      link.attr('data-hovered', edge => edge.edge.source === item.id || edge.edge.target === item.id ? 'true' : 'false')
    })
    node.on('mouseout', () => {
      node.select('circle').attr('data-hovered', null)
      node.select('text').attr('data-hovered', null)
      link.attr('data-hovered', null)
    })
    svg.on('click', () => { setSelectedId(''); setSelectedEdgeId('') })
    simulation.on('tick', () => {
      const padding = 34
      simNodes.forEach(item => { const radius = nodeRadius(item) + padding; item.x = Math.max(radius, Math.min(width - radius, item.x)); item.y = Math.max(radius, Math.min(height - radius, item.y)) })
      link.attr('x1', item => (typeof item.source === 'string' ? 0 : item.source.x)).attr('y1', item => (typeof item.source === 'string' ? 0 : item.source.y)).attr('x2', item => (typeof item.target === 'string' ? 0 : item.target.x)).attr('y2', item => (typeof item.target === 'string' ? 0 : item.target.y))
      node.attr('transform', item => `translate(${item.x},${item.y})`)
    })
    return () => { simulation.stop(); svg.on('.zoom', null); svg.on('click', null) }
  }, [layoutNonce, relationById, relationEdges, relationNodes, workspaceId])

  // Selection is presentation state. Updating it must not tear down the force
  // simulation, otherwise a click can reset the user's current arrangement.
  useEffect(() => {
    const svgElement = svgRef.current
    if (!svgElement) return
    d3.select(svgElement)
      .selectAll<SVGCircleElement, RelationRenderNode>('circle[data-kind]')
      .attr('data-selected', item => item.id === selectedId ? 'true' : 'false')
  }, [selectedId])

  useEffect(() => {
    if (selectedId !== '' && !relationById.has(selectedId)) setSelectedId('')
  }, [relationById, selectedId])

  return <div className={css.relationshipWorkspace} data-detail={selected !== undefined || selectedEdge !== undefined}>
    <div ref={containerRef} className={css.relationshipCanvas}>
      <div className={css.relationshipCanvasHeader}>
        <span><b>{relationNodes.length}</b> 节点 · <b>{relationEdges.length}</b> 连接</span>
        <button type="button" className={css.button} onClick={() => {
          setSelectedId(''); setSelectedEdgeId('')
          try { window.localStorage.removeItem(storageKey(RELATION_POSITIONS_KEY, workspaceId)) } catch { /* unavailable storage */ }
          setLayoutNonce(value => value + 1)
        }}>
          {t('graph.relayout')}
        </button>
      </div>
      <svg ref={svgRef} className={css.relationshipSvg} role="img" aria-label={t('graph.relationships')} />
      <div className={css.relationshipStats}><b>{relationNodes.length}</b> {t('graph.nodes')} · <b>{relationEdges.length}</b> {t('graph.connections')}</div>
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
        {selected.sourcePath !== '' && <button type="button" className={css.linkButton} onClick={() => void openSourceDocument(selected.sourcePath)}>{t('graph.source')}</button>}
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

/**
 * Open a source document through the proxied API. An <a href> cannot carry
 * the contract's X-Dsh-Workspace-Id header, so the download goes through
 * fetch with explicit context headers and opens as a blob.
 */
async function openSourceDocument(path: string): Promise<void> {
  try {
    const response = await fetch(`${API_PROXY_BASE}/document?path=${encodeURIComponent(path)}`, { headers: studioContextHeaders() })
    if (!response.ok) return
    const url = URL.createObjectURL(await response.blob())
    window.open(url, '_blank', 'noopener,noreferrer')
  } catch { /* unavailable without a bound context; the chip already shows that state */ }
}

/** Full graph-view props: conversation-view runtime share & injected fetch & locale seat. */
export type GraphViewProps =
  ConvViewProps & InjectFace<StudioApiInjected> & PropsLocale<'studio-panel'>

export function GraphView({ fetchStudioApi, postStudioApi, t }: GraphViewProps) {
  const workbench = useWorkbench()
  const workspaceId = workbench.context?.workspaceId
  // 评审/交付 DAG 由评审任务产出：任务失效即重载 DAG 视图。
  const dagEpoch = workbench.epochs.tasks
  const [state, setState] = useState<LoadState>('loading')
  const [payload, setPayload] = useState<ContinuityPayload | null>(null)
  const [error, setError] = useState('')
  const [segment, setSegment] = useState<Segment>('foreshadowing')
  // Show the complete graph by default, matching the knowledge-map view. The
  // kind chips remain available for narrowing a dense novel workspace.
  const [kindFilter, setKindFilter] = useState<ReadonlySet<RelationKind>>(
    new Set<RelationKind>([...REL_KIND_ORDER, 'other']),
  )
  const [relationQuery, setRelationQuery] = useState(() => {
    try { return window.localStorage.getItem(storageKey('dsh-novel.relationQuery', workspaceId)) ?? '' } catch { return '' }
  })
  const [connectedOnly, setConnectedOnly] = useState(() => {
    try { return window.localStorage.getItem(storageKey('dsh-novel.relationConnectedOnly', workspaceId)) === 'true' } catch { return false }
  })

  useEffect(() => {
    try {
      window.localStorage.setItem(storageKey('dsh-novel.relationQuery', workspaceId), relationQuery)
      window.localStorage.setItem(storageKey('dsh-novel.relationConnectedOnly', workspaceId), String(connectedOnly))
    } catch { /* unavailable storage */ }
  }, [connectedOnly, relationQuery, workspaceId])

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
  const connectedIds = useMemo(
    () => new Set((payload?.relationEdges ?? []).flatMap(edge => [edge.source, edge.target])),
    [payload],
  )
  // Keep these references stable across WorkbenchStore connection/epoch
  // updates. RelationshipFlow uses reference identity to decide whether the
  // graph data changed; rebuilding arrays on every parent render used to
  // restart the simulation on the 5s invalidation poll.
  const visibleRelationNodes = useMemo(() => payload === null ? [] : payload.relationNodes.filter(node => {
    const matchesQuery = query === '' || `${node.label} ${node.description} ${node.id}`.toLocaleLowerCase().includes(query)
    return kindFilter.has(relationKind(node.kind)) && matchesQuery && (!connectedOnly || connectedIds.has(node.id))
  }), [connectedIds, connectedOnly, kindFilter, payload, query])
  const visibleRelationIds = useMemo(() => new Set(visibleRelationNodes.map(node => node.id)), [visibleRelationNodes])
  const visibleRelationEdges = useMemo(() => payload === null ? [] : payload.relationEdges.filter(
    edge => visibleRelationIds.has(edge.source) && visibleRelationIds.has(edge.target),
  ), [payload, visibleRelationIds])
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
