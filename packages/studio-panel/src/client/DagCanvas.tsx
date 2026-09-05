import { useEffect, useMemo, useState, type ReactNode } from 'react'
import ELK from 'elkjs/lib/elk.bundled.js'
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
import type { PropsLocale } from '@deepseek-ai/dsh-client-ui-slots'
import type { StudioApiInjected } from './api.ts'
import css from './views.module.css'

type RecordValue = Record<string, unknown>
type Filter = 'all' | 'anomaly' | 'blocker'

interface DogGraph {
  id?: string
  root?: string
  nodes?: Record<string, RecordValue>
  contains?: RecordValue[]
  dependsOn?: RecordValue[]
}

interface GraphArtifact {
  graph: DogGraph
  manifest: RecordValue
  records: Record<string, RecordValue>
}

interface DogSurface {
  chapter_id: string
  chapters: string[]
  review: GraphArtifact | null
  delivery: GraphArtifact | null
  reviewFramework: RecordValue
}

interface ReviewDagViewProps {
  fetchStudioApi: StudioApiInjected['fetchStudioApi']
  postStudioApi: StudioApiInjected['postStudioApi']
  kind: 'review' | 'delivery'
  t: PropsLocale<'studio-panel'>['t']
}

const elk = new ELK()
const NODE_WIDTH = 214
const NODE_HEIGHT = 84


/** 详情面板中文字段标签（英文界面回退显示原始键名）。 */
const DAG_FIELD_LABELS: Record<string, string> = {
  status: '状态', verdict: '判定', qualityScore: '质量分', coverage: '覆盖率',
  gateStatus: '硬门禁', deliveryStatus: '交付结论', executionStatus: '执行状态',
  currentRevision: '当前正文版本', sourceRevision: '评审基线版本', threshold: '阈值',
  frameworkId: '审稿框架', frameworkVersion: '框架版本', frameworkRevision: '框架修订',
  legacyCheckIds: '兼容检查项', criteria: '评分细则', issues: '问题',
  evidence: '证据原文', provenance: '模型与调用', score: '旧版得分',
}

function record(value: unknown): RecordValue {
  return value !== null && typeof value === 'object' && !Array.isArray(value) ? value as RecordValue : {}
}

function text(value: unknown): string {
  return typeof value === 'string' ? value : value === null || value === undefined ? '' : String(value)
}

function issues(value: RecordValue): RecordValue[] {
  return Array.isArray(value['issues']) ? value['issues'].map(record) : []
}

function isBlocker(value: RecordValue): boolean {
  return text(value['status']) === 'blocked'
    || text(value['gateStatus']) === 'blocked'
    || issues(value).some(item => ['critical', 'blocker'].includes(text(item['reviewSeverity'] ?? item['severity'] ?? item['revisionPriority']).toLowerCase()))
}

function verdict(value: RecordValue): string {
  return text(value['verdict'] || value['deliveryStatus'] || value['status'] || 'inconclusive').toLowerCase()
}

function nodeMeta(value: RecordValue): string {
  const parts: string[] = []
  const score = value['qualityScore'] ?? value['score'] ?? value['earned']
  if (typeof score === 'number') parts.push(`${Math.round(score * 10) / 10}`)
  if (typeof value['coverage'] === 'number') parts.push(`${Math.round(value['coverage'] * 100)}%`)
  const count = typeof value['issueCount'] === 'number' ? value['issueCount'] : issues(value).length
  if (count > 0) parts.push(`${count} issues`)
  const provenance = record(value['provenance'])
  if (text(provenance['model']) !== '') parts.push(text(provenance['model']))
  return parts.join(' · ')
}

function detailValue(value: unknown): ReactNode {
  if (value === null || value === undefined || value === '') return <span>—</span>
  if (typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean') return <span>{String(value)}</span>
  if (Array.isArray(value)) {
    if (value.length === 0) return <span>—</span>
    if (value.every(item => item === null || ['string', 'number', 'boolean'].includes(typeof item))) {
      return <div className={css.dagPrimitiveList}>{value.map((item, index) => <span key={index}>{String(item ?? '—')}</span>)}</div>
    }
    return <div className={css.dagObjectList}>{value.map((item, index) => (
      <div key={index} className={css.dagObjectItem}>{detailValue(item)}</div>
    ))}</div>
  }
  const entries = Object.entries(record(value))
  if (entries.length === 0) return <span>—</span>
  return <dl className={css.dagStructured}>{entries.map(([key, item]) => (
    <div key={key} className={css.dagStructuredRow}>
      <dt>{key}</dt><dd>{detailValue(item)}</dd>
    </div>
  ))}</dl>
}

async function layout(nodes: Node[], edges: Edge[]): Promise<Node[]> {
  if (nodes.length === 0) return []
  const result = await elk.layout({
    id: 'root',
    layoutOptions: {
      'elk.algorithm': 'layered',
      'elk.direction': 'RIGHT',
      'elk.spacing.nodeNode': '34',
      'elk.layered.spacing.nodeNodeBetweenLayers': '72',
      'elk.layered.nodePlacement.strategy': 'NETWORK_SIMPLEX',
    },
    children: nodes.map(node => ({ id: node.id, width: NODE_WIDTH, height: NODE_HEIGHT })),
    edges: edges.map(edge => ({ id: edge.id, sources: [edge.source], targets: [edge.target] })),
  })
  const positions = new Map((result.children ?? []).map(item => [item.id, { x: item.x ?? 0, y: item.y ?? 0 }]))
  return nodes.map(node => ({ ...node, position: positions.get(node.id) ?? { x: 0, y: 0 } }))
}

function DagCanvas({ artifact, kind, chapterId, postStudioApi, t }: { artifact: GraphArtifact; kind: 'review' | 'delivery'; chapterId: string; postStudioApi: StudioApiInjected['postStudioApi']; t: PropsLocale<'studio-panel'>['t'] }) {
  const [filter, setFilter] = useState<Filter>('all')
  const [expanded, setExpanded] = useState(false)
  const [compact, setCompact] = useState(() => window.matchMedia('(max-width: 760px)').matches)
  const [selectedId, setSelectedId] = useState('')
  const [nodes, setNodes, onNodesChange] = useNodesState<Node>([])
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>([])
  const [flow, setFlow] = useState<ReactFlowInstance<Node, Edge> | null>(null)
  const graphNodes = artifact.graph.nodes ?? {}
  const fitMinimumZoom = compact || expanded ? 0.92 : 0.8

  // 章节/过滤变化时重置选择，避免详情面板指向已不存在的节点。
  useEffect(() => { setSelectedId('') }, [artifact, expanded, filter])

  const manifestDomains = ((artifact.manifest['domains'] ?? []) as unknown[]).filter((item): item is RecordValue => typeof item === 'object' && item !== null)
  const stale = artifact.manifest['stale'] === true
  const selectedIssues = selectedId !== '' && Array.isArray(artifact.records[selectedId]?.['issues'])
    ? (artifact.records[selectedId]['issues'] as RecordValue[]).filter(item => typeof item === 'object' && item !== null)
    : []
  const [revisionNote, setRevisionNote] = useState('')
  const issueToRevision = async () => {
    const issueIds = selectedIssues.map(item => text(item['id'])).filter(Boolean)
    if (issueIds.length === 0) return
    setRevisionNote('')
    try {
      await postStudioApi('/tasks', { type: 'revision_from_review', input: { chapter_id: chapterId, issue_ids: issueIds } })
      setRevisionNote(t('dag.toRevisionDone'))
    } catch (cause: unknown) {
      setRevisionNote(`${t('dag.toRevisionFailed')}: ${cause instanceof Error ? cause.message : String(cause)}`)
    }
  }

  useEffect(() => {
    const media = window.matchMedia('(max-width: 760px)')
    const update = () => setCompact(media.matches)
    update()
    media.addEventListener('change', update)
    return () => media.removeEventListener('change', update)
  }, [])

  const visible = useMemo(() => {
    const all = new Set(Object.keys(graphNodes).filter(id => expanded || !id.startsWith('dim-')))
    if (filter === 'all') return all
    const matching = new Set([...all].filter(id => {
      const value = artifact.records[id] ?? {}
      return filter === 'blocker' ? isBlocker(value) : verdict(value) !== 'pass' || issues(value).length > 0
    }))
    matching.add(artifact.graph.root ?? 'root')
    for (const edge of artifact.graph.contains ?? []) {
      const parent = text(edge['parent'])
      const child = text(edge['child'])
      if (matching.has(child)) matching.add(parent)
    }
    if (kind === 'review' && matching.size > 1) {
      matching.add('context')
      matching.add('aggregate')
    }
    return matching
  }, [artifact, expanded, filter, graphNodes, kind])

  useEffect(() => {
    const rawNodes: Node[] = [...visible].map(id => {
      const node = graphNodes[id] ?? {}
      const value = artifact.records[id] ?? (id === artifact.graph.root ? artifact.manifest : {})
      const state = isBlocker(value) ? 'blocked' : verdict(value)
      return {
        id,
        position: { x: 0, y: 0 },
        className: css.dagNode ?? '',
        data: {
          label: <div className={css.dagNodeContent} data-verdict={state}>
            <strong title={text(node['title'])}>{text(node['title']) || id}</strong>
            <span>{text(value['status'] ?? value['deliveryStatus'] ?? value['executionStatus']) || state}</span>
            <small>{nodeMeta(value)}</small>
          </div>,
        },
        style: { width: NODE_WIDTH, height: NODE_HEIGHT },
      }
    })
    const sourceEdges = (artifact.graph.dependsOn ?? []).map(item => ({
      source: text(item['target']),
      target: text(item['source']),
    }))
    if (kind === 'delivery' && visible.has('root') && visible.has('closure')) sourceEdges.push({ source: 'closure', target: 'root' })
    if (kind === 'review') {
      for (const item of artifact.graph.contains ?? []) {
        const child = text(item['child'])
        if (child.startsWith('dim-')) sourceEdges.push({ source: text(item['parent']), target: child })
      }
      if (visible.has('root') && visible.has('aggregate')) sourceEdges.push({ source: 'aggregate', target: 'root' })
    }
    const rawEdges: Edge[] = sourceEdges
      .filter(edge => visible.has(edge.source) && visible.has(edge.target) && edge.source !== '' && edge.target !== '')
      .map((edge, index) => ({
        id: `${edge.source}-${edge.target}-${index}`,
        source: edge.source,
        target: edge.target,
        markerEnd: { type: MarkerType.ArrowClosed },
        animated: false,
      }))
    let active = true
    let frame = 0
    void layout(rawNodes, rawEdges).then(placed => {
      if (!active) return
      setNodes(placed)
      setEdges(rawEdges)
      frame = requestAnimationFrame(() => {
        if (!active || flow === null) return
        void flow.fitView({ padding: 0.16, minZoom: fitMinimumZoom, maxZoom: 1 }).then(() => {
          if (!active || !compact || kind !== 'review') return
          const columns = new Map<number, Node[]>()
          for (const node of placed) {
            const x = Math.round(node.position.x)
            columns.set(x, [...(columns.get(x) ?? []), node])
          }
          const focus = [...columns.values()].sort((left, right) => right.length - left.length)[0]
          if (focus === undefined) return
          const centerX = focus.reduce((sum, node) => sum + node.position.x + NODE_WIDTH / 2, 0) / focus.length
          const minY = Math.min(...focus.map(node => node.position.y))
          const maxY = Math.max(...focus.map(node => node.position.y + NODE_HEIGHT))
          void flow.setCenter(centerX, (minY + maxY) / 2, { zoom: fitMinimumZoom })
        })
      })
    })
    return () => {
      active = false
      cancelAnimationFrame(frame)
    }
  }, [artifact, fitMinimumZoom, flow, graphNodes, kind, setEdges, setNodes, visible])

  const selected = selectedId !== '' ? artifact.records[selectedId] ?? artifact.manifest : null
  return <div className={css.dagRoot}>
    {kind === 'review' && <div className={css.dagOverview}>
      <span className={css.benchmarkStatus} data-status={stale ? 'stale' : 'pass'}>{stale ? t('dag.stale') : t('dag.current')}</span>
      <span>{t('dag.quality')} <b>{text(artifact.manifest['qualityScore']) || '—'}</b></span>
      <span>{t('dag.coverage')} <b>{typeof artifact.manifest['coverage'] === 'number' ? `${Math.round(Number(artifact.manifest['coverage']) * 100)}%` : '—'}</b></span>
      <span>{t('dag.gate')} <b>{text(artifact.manifest['gateStatus']) || '—'}</b></span>
      <span>{t('dag.delivery')} <b>{text(artifact.manifest['deliveryStatus']) || '—'}</b></span>
    </div>}
    {kind === 'review' && manifestDomains.length > 0 && <div className={css.dagDomainRow}>
      {manifestDomains.map((domain, index) => <span key={index} className={css.chip} title={`${text(domain['name'])} · ${t('dag.coverage')} ${typeof domain['coverage'] === 'number' ? `${Math.round(Number(domain['coverage']) * 100)}%` : '—'}`}>{text(domain['name'])}</span>)}
    </div>}
    <div className={css.kindFilterRow}>
      {(['all', 'anomaly', 'blocker'] as const).map(value => <button key={value} type="button" className={css.chip}
        data-active={filter === value} onClick={() => setFilter(value)}>{t(`graph.filter.${value}` as 'graph.filter.all')}</button>)}
      {kind === 'review' && <button type="button" className={css.chip} data-active={expanded}
        onClick={() => setExpanded(value => !value)}>{expanded ? t('graph.collapseChecks') : t('graph.expandChecks')}</button>}
    </div>
    <div className={css.dagWorkspace} data-detail={selected !== null}>
      <div className={css.dagCanvas}>
        <ReactFlow nodes={nodes} edges={edges} onNodesChange={onNodesChange} onEdgesChange={onEdgesChange}
          onInit={setFlow}
          onNodeClick={(_event, node) => setSelectedId(node.id)} fitView minZoom={0.25} maxZoom={1.8}
          nodesDraggable={false} nodesConnectable={false} elementsSelectable>
          <Controls showInteractive={false} />
          <Background variant={BackgroundVariant.Dots} gap={20} size={1} />
        </ReactFlow>
      </div>
      {selected !== null && <aside className={css.dagDetail}>
        <div className={css.detailHeading}>{text(graphNodes[selectedId]?.['title']) || selectedId}</div>
        {['status', 'verdict', 'qualityScore', 'coverage', 'gateStatus', 'deliveryStatus', 'currentRevision', 'sourceRevision', 'legacyCheckIds', 'criteria', 'issues', 'evidence', 'provenance'].map(key => (
          selected[key] === undefined ? null : <div key={key} className={css.dagDetailRow}>
            <b>{DAG_FIELD_LABELS[key] ?? key}</b>{detailValue(selected[key])}
          </div>
        ))}
        {kind === 'review' && selectedIssues.length > 0 && <div className={css.dagRevisionAction}>
          <button type="button" className={css.button} onClick={() => void issueToRevision()}>{t('dag.toRevision')}</button>
          {revisionNote !== '' && <small>{revisionNote}</small>}
        </div>}
      </aside>}
    </div>
  </div>
}
export function ReviewDagView({ fetchStudioApi, postStudioApi, kind, t }: ReviewDagViewProps) {
  const [state, setState] = useState<'loading' | 'ready' | 'error'>('loading')
  const [surface, setSurface] = useState<DogSurface | null>(null)
  const [chapter, setChapter] = useState('')
  const [error, setError] = useState('')

  useEffect(() => {
    let active = true
    setState('loading')
    fetchStudioApi(`/dog/graphs${chapter !== '' ? `?chapter=${encodeURIComponent(chapter)}` : ''}`)
      .then(value => {
        if (!active) return
        const data = record(value)
        const parsed: DogSurface = {
          chapter_id: text(data['chapter_id']),
          chapters: Array.isArray(data['chapters']) ? data['chapters'].map(text) : [],
          review: data['review'] === null || data['review'] === undefined ? null : record(data['review']) as unknown as GraphArtifact,
          delivery: data['delivery'] === null || data['delivery'] === undefined ? null : record(data['delivery']) as unknown as GraphArtifact,
          reviewFramework: record(data['review_framework']),
        }
        setSurface(parsed)
        if (chapter === '' && parsed.chapter_id !== '') setChapter(parsed.chapter_id)
        setState('ready')
      })
      .catch((cause: unknown) => {
        if (!active) return
        setError(cause instanceof Error ? cause.message : String(cause))
        setState('error')
      })
    return () => { active = false }
  }, [chapter, fetchStudioApi])

  const artifact = surface?.[kind] ?? null
  const framework = surface?.reviewFramework ?? {}
  const frameworkInvariants = record(framework['invariants'])
  return <>
    <div className={css.kindFilterRow}>
      <select className={css.scopeSelect} value={chapter} onChange={event => setChapter(event.target.value)}>
        {(surface?.chapters ?? []).map(item => <option key={item} value={item}>{item}</option>)}
      </select>
      {kind === 'review' && text(framework['id']) !== '' && (
        <span title={text(framework['revision'])}>
          {t('graph.reviewFramework')} v{text(framework['version'])}
          {' · '}{text(frameworkInvariants['domain_count'])} {t('graph.reviewDomains')}
          {' · '}{text(frameworkInvariants['legacy_check_count'])} {t('graph.reviewChecks')}
          {' · '}{text(frameworkInvariants['criterion_count'])} {t('graph.reviewCriteria')}
        </span>
      )}
    </div>
    {state === 'loading' && <div className={css.notice}>{t('loading')}</div>}
    {state === 'error' && <div className={css.notice}><span className={css.errorText}>{error}</span></div>}
    {state === 'ready' && artifact === null && <div className={css.notice}>{t('graph.empty.dag')}</div>}
    {state === 'ready' && artifact !== null && <DagCanvas artifact={artifact} kind={kind} chapterId={chapter || surface?.chapter_id || ''} postStudioApi={postStudioApi} t={t} />}
  </>
}
