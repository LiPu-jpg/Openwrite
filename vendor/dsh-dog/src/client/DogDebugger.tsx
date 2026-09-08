import {
  Fragment,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  useSyncExternalStore,
  type CSSProperties,
  type ReactNode,
} from 'react'
import type { SessionListState } from '@deepseek-ai/dsh-api-session-controller/client'
import type { DogDebugGraphRevision, DogDebugSnapshot } from '../debug-contract.ts'
import type {
  BoolExpr,
  CompiledGraph,
  DogRun,
  GoalAgentSessionRef,
  GoalNodeInput,
  GoalRuntimeEvent,
  GoalRuntimeTrace,
  GoalResult,
  GoalState,
  JsonValue,
  RootTerminalState,
} from '../model.ts'
import {
  agentParentSessionIds,
  goalAgentRefs,
  goalAgentTelemetry,
  settledGoalCount,
  summarizeRunAgents,
} from './agentTelemetry.ts'
import { layoutDag, type PositionedGoal } from './graph-layout.ts'
import { parseDogDebugSnapshot, parseGoalRuntimeTrace } from './snapshot.ts'

const REFRESH_INTERVAL_MS = 3_000
const RECENT_DOG_LIMIT = 4
const DOG_DOCK_RESERVED_WIDTH = 370
const HOST_CENTER_MIN_WIDTH = 640
const DOG_DOCK_COLLAPSED_KEY = '@dsh-external/dsh-dog/dock-collapsed'
const MIN_ZOOM = 0.6
const MAX_ZOOM = 1.2

export interface DogDebuggerProps {
  readonly initialOpen?: boolean
  readonly hideDock?: boolean
  readonly readSnapshot: (signal: AbortSignal) => Promise<unknown>
  readonly readGoalRuntime: (runId: string, goalId: string, signal: AbortSignal) => Promise<unknown>
  readonly openSession: (sessionId: string, parentSessionId?: string) => Promise<boolean>
  readonly getSessionState: () => SessionListState
  readonly subscribeSessions: (listener: () => void) => () => void
  readonly refreshAgentCatalog: (parentSessionId: string) => Promise<void>
}

export function DogDebugger({
  initialOpen = false,
  hideDock = false,
  readSnapshot,
  readGoalRuntime,
  openSession,
  getSessionState,
  subscribeSessions,
  refreshAgentCatalog,
}: DogDebuggerProps): JSX.Element {
  const [open, setOpen] = useState(initialOpen)
  const [dockCollapsed, setDockCollapsed] = useState(readDogDockCollapsed)
  const [snapshot, setSnapshot] = useState<DogDebugSnapshot>()
  const [selectedDigest, setSelectedDigest] = useState<string>()
  const [selectedRunId, setSelectedRunId] = useState<string>()
  const [selectedNodeId, setSelectedNodeId] = useState<string>()
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string>()
  const [zoom, setZoom] = useState(0.9)
  const inFlight = useRef(false)
  const dialogRef = useRef<HTMLDivElement>(null)
  const overlayRootRef = useRef<HTMLDivElement>(null)
  const sessionState = useSyncExternalStore(subscribeSessions, getSessionState, getSessionState)
  const updateDockCollapsed = useCallback((collapsed: boolean): void => {
    setDockCollapsed(collapsed)
    writeDogDockCollapsed(collapsed)
  }, [])

  useEffect(() => {
    if (hideDock) return
    const root = overlayRootRef.current
    const overlayLayer = root?.parentElement?.parentElement
    const details = overlayLayer?.previousElementSibling
    const center = details?.previousElementSibling
    const sidebar = center?.previousElementSibling
    const frame = overlayLayer?.parentElement
    if (!(root instanceof HTMLElement)
      || !(overlayLayer instanceof HTMLElement)
      || !(details instanceof HTMLElement)
      || !(center instanceof HTMLElement)
      || !(sidebar instanceof HTMLElement)
      || !(frame instanceof HTMLElement)) return

    const previousMarginRight = center.style.marginRight
    const previousMinWidth = center.style.minWidth
    const update = (): void => {
      const frameWidth = frame.getBoundingClientRect().width
      const sidebarWidth = sidebar.getBoundingClientRect().width
      const detailsWidth = details.getBoundingClientRect().width
      const centerWidth = frameWidth - sidebarWidth - detailsWidth
      const canReserve = !open
        && !dockCollapsed
        && detailsWidth < 1
        && centerWidth - DOG_DOCK_RESERVED_WIDTH >= HOST_CENTER_MIN_WIDTH
      if (canReserve) {
        center.style.marginRight = `${DOG_DOCK_RESERVED_WIDTH}px`
        center.style.minWidth = '0'
        root.dataset.dogDockLayout = 'reserved'
        return
      }
      center.style.marginRight = previousMarginRight
      center.style.minWidth = previousMinWidth
      root.dataset.dogDockLayout = open || detailsWidth >= 1 ? 'hidden' : dockCollapsed ? 'collapsed' : 'floating'
    }

    update()
    const observer = new ResizeObserver(update)
    observer.observe(frame)
    observer.observe(sidebar)
    observer.observe(details)
    window.addEventListener('resize', update)
    return () => {
      window.removeEventListener('resize', update)
      observer.disconnect()
      center.style.marginRight = previousMarginRight
      center.style.minWidth = previousMinWidth
      delete root.dataset.dogDockLayout
    }
  }, [dockCollapsed, open, hideDock])

  const refresh = useCallback(async (): Promise<void> => {
    if (inFlight.current) return
    inFlight.current = true
    setLoading(true)
    try {
      const next = parseDogDebugSnapshot(await readSnapshot(new AbortController().signal))
      setSnapshot(next)
      setError(undefined)
      await Promise.allSettled(agentParentSessionIds(next).map(refreshAgentCatalog))
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause))
    } finally {
      inFlight.current = false
      setLoading(false)
    }
  }, [readSnapshot, refreshAgentCatalog])

  const openInvokingSession = useCallback(async (sessionId: string, parentSessionId?: string): Promise<boolean> => {
    const opened = await openSession(sessionId, parentSessionId)
    if (opened) setOpen(false)
    return opened
  }, [openSession])

  useEffect(() => {
    if (hideDock && !open) return
    void refresh()
    const timer = window.setInterval(() => void refresh(), REFRESH_INTERVAL_MS)
    return () => window.clearInterval(timer)
  }, [refresh, open, hideDock])

  useEffect(() => {
    if (!open) return
    const previouslyFocused = document.activeElement
    dialogRef.current?.focus()
    const onKeyDown = (event: KeyboardEvent): void => {
      if (event.key === 'Escape') setOpen(false)
    }
    window.addEventListener('keydown', onKeyDown)
    return () => {
      window.removeEventListener('keydown', onKeyDown)
      if (previouslyFocused instanceof HTMLElement) previouslyFocused.focus()
    }
  }, [open])

  const selectedRevision = snapshot?.graphs.find(item => item.graph.graphDigest === selectedDigest)
    ?? snapshot?.graphs[0]
  const selectedRun = selectedRevision?.runs.find(run => run.runId === selectedRunId)
    ?? selectedRevision?.runs[0]
  const effectiveNodeId = selectedNodeId !== undefined && selectedRevision?.graph.input.nodes[selectedNodeId] !== undefined
    ? selectedNodeId
    : selectedRevision?.graph.input.root

  const chooseRevision = (revision: DogDebugGraphRevision): void => {
    setSelectedDigest(revision.graph.graphDigest)
    setSelectedRunId(revision.runs[0]?.runId)
    setSelectedNodeId(revision.graph.input.root)
  }
  const enterRevision = (revision: DogDebugGraphRevision): void => {
    chooseRevision(revision)
    setOpen(true)
  }

  return (
    <div ref={overlayRootRef} className="dog-overlay-root">
      {open || hideDock ? null : (
        <DogDock
          snapshot={snapshot}
          sessions={sessionState}
          loading={loading}
          error={error}
          onOpenRevision={enterRevision}
          collapsed={dockCollapsed}
          onCollapsedChange={updateDockCollapsed}
          onRefresh={() => void refresh()}
        />
      )}
      {open ? (
        <div className="dog-backdrop">
          <div
            ref={dialogRef}
            className="dog-dialog"
            role="dialog"
            aria-modal="true"
            aria-label="DoG graph"
            tabIndex={-1}
          >
            <header className="dog-header">
              <div className="dog-brand">
                <span className="dog-brand-mark"><NetworkIcon size={18} /></span>
                <div className="dog-brand-copy">
                  <h2 className="dog-brand-title">DoG</h2>
                  <p className="dog-brand-subtitle">Goals · Agents · trusted evidence</p>
                </div>
              </div>
              <span className="dog-header-divider" />
              <div className="dog-context">
                <span className="dog-context-title">{selectedRevision?.graph.input.nodes[selectedRevision.graph.input.root]?.title ?? 'No graph selected'}</span>
                {selectedRevision?.current ? <span className="dog-revision-chip">Current revision</span> : null}
              </div>
              <div className="dog-header-actions">
                <span className="dog-sync-copy" title={error}>{error === undefined ? 'Live · 3s' : 'Refresh failed'}</span>
                <IconButton label="Refresh DoG data" busy={loading} onClick={() => void refresh()}><RefreshIcon /></IconButton>
                <IconButton label="Close DoG" busy={false} onClick={() => setOpen(false)}><CloseIcon /></IconButton>
              </div>
            </header>
            {selectedRevision === undefined ? (
              <EmptyWorkspace loading={loading} error={error} />
            ) : (
              <div className={loading ? 'dog-workspace dog-loading' : 'dog-workspace'}>
                <Sidebar
                  snapshot={snapshot}
                  selectedRevision={selectedRevision}
                  selectedRun={selectedRun}
                  onSelectRevision={chooseRevision}
                  onSelectRun={setSelectedRunId}
                />
                <main className="dog-main">
                  <Summary revision={selectedRevision} run={selectedRun} sessions={sessionState} />
                  {error === undefined ? null : <div className="dog-error-banner" role="status">Live refresh failed: {error}</div>}
                  <section className="dog-canvas-shell" aria-label="Goal DAG canvas">
                    <CanvasToolbar zoom={zoom} onZoom={setZoom} />
                    <GraphCanvas
                      graph={selectedRevision.graph}
                      run={selectedRun}
                      sessions={sessionState}
                      selectedNodeId={effectiveNodeId}
                      zoom={zoom}
                      onSelectNode={setSelectedNodeId}
                      openSession={openInvokingSession}
                    />
                  </section>
                </main>
                <Inspector
                  graph={selectedRevision.graph}
                  run={selectedRun}
                  nodeId={effectiveNodeId}
                  readGoalRuntime={readGoalRuntime}
                  openSession={openInvokingSession}
                />
              </div>
            )}
          </div>
        </div>
      ) : null}
    </div>
  )
}

interface DogDockProps {
  readonly snapshot: DogDebugSnapshot | undefined
  readonly sessions: SessionListState
  readonly loading: boolean
  readonly error: string | undefined
  readonly onOpenRevision: (revision: DogDebugGraphRevision) => void
  readonly onRefresh: () => void
  readonly collapsed: boolean
  readonly onCollapsedChange: (collapsed: boolean) => void
}

function DogDock({ snapshot, sessions, loading, error, onOpenRevision, onRefresh, collapsed, onCollapsedChange }: DogDockProps): JSX.Element {
  const revisions = snapshot?.graphs.filter(revision => revision.current).slice(0, RECENT_DOG_LIMIT) ?? []
  if (collapsed) {
    return (
      <aside className="dog-dock" data-collapsed="true" aria-label="Collapsed DoG panel">
        <button
          className="dog-dock-rail"
          type="button"
          aria-label="Expand DoG panel"
          title="Expand DoG panel"
          aria-expanded="false"
          onClick={() => onCollapsedChange(false)}
        >
          <span className="dog-dock-rail-mark"><NetworkIcon size={16} /></span>
          <strong>DoG</strong>
          <DockExpandIcon />
        </button>
      </aside>
    )
  }
  return (
    <aside className="dog-dock" data-collapsed="false" aria-label="Recent DoG runs" aria-busy={loading}>
      <div className="dog-dock-collapse-slot">
        <button
          className="dog-dock-collapse-handle"
          type="button"
          aria-label="Collapse DoG panel"
          title="Collapse DoG panel"
          aria-expanded="true"
          onClick={() => onCollapsedChange(true)}
        >
          <DockCollapseIcon />
        </button>
      </div>
      <div className="dog-dock-content">
        <header className="dog-dock-header">
          <span className="dog-dock-mark"><NetworkIcon size={16} /></span>
          <div className="dog-dock-heading">
            <h2>DoG</h2>
            <span>{loading ? 'Syncing…' : error === undefined ? 'Live goals' : 'Refresh failed'}</span>
          </div>
          <IconButton label="Refresh recent DoGs" busy={loading} onClick={onRefresh}><RefreshIcon /></IconButton>
        </header>
        {error === undefined ? null : <div className="dog-dock-error" title={error}>Last sync failed</div>}
        {revisions.length === 0 ? (
          <div className="dog-dock-empty">
            <span className="dog-dock-empty-icon"><NetworkIcon size={19} /></span>
            <strong>{loading ? 'Loading DoGs' : 'No DoG yet'}</strong>
            <span>dog_create adds the first graph.</span>
          </div>
        ) : (
          <ul className="dog-dock-list">
            {revisions.map(revision => {
              const run = latestRun(revision)
              const total = Object.keys(revision.graph.input.nodes).length
              const settled = settledGoalCount(run)
              const agents = summarizeRunAgents(run, sessions)
              const state = run?.rootState ?? run?.state ?? 'pending'
              const progress = total === 0 ? 0 : Math.round((settled / total) * 100)
              const rootTitle = revision.graph.input.nodes[revision.graph.input.root]?.title ?? revision.graph.input.id
              return (
                <li key={revision.graph.graphDigest}>
                  <button
                    className="dog-dock-card"
                    type="button"
                    onClick={() => onOpenRevision(revision)}
                    aria-label={`Open ${rootTitle}: ${humanizeState(state)}, ${settled} of ${total} goals complete`}
                  >
                    <span className="dog-dock-card-head">
                      <span className="dog-dock-title-wrap">
                        <span className="dog-dock-title">{rootTitle}</span>
                        <span className="dog-dock-id">{revision.graph.input.id}</span>
                      </span>
                      <StatusChip state={state} />
                    </span>
                    <span className="dog-dock-progress" aria-hidden="true">
                      <span style={{ width: `${progress}%` }} />
                    </span>
                    <span className="dog-dock-metrics">
                      <span><strong>{settled}/{total}</strong> nodes</span>
                      <span><strong>{agents.linked}</strong> agents</span>
                      <span><strong>{agents.running}</strong> live</span>
                      <span><strong>{formatTokenMetric(agents.tokens, agents.partialTokens)}</strong> tok</span>
                    </span>
                  </button>
                </li>
              )
            })}
          </ul>
        )}
        <div className="dog-dock-footer">Open a DoG to inspect its graph and Agents</div>
      </div>
    </aside>
  )
}

interface SidebarProps {
  readonly snapshot: DogDebugSnapshot | undefined
  readonly selectedRevision: DogDebugGraphRevision
  readonly selectedRun: DogRun | undefined
  readonly onSelectRevision: (revision: DogDebugGraphRevision) => void
  readonly onSelectRun: (runId: string) => void
}

function Sidebar({ snapshot, selectedRevision, selectedRun, onSelectRevision, onSelectRun }: SidebarProps): JSX.Element {
  return (
    <aside className="dog-sidebar" aria-label="Graphs and run history">
      <h3 className="dog-section-label">Graph revisions</h3>
      <ul className="dog-graph-list">
        {snapshot?.graphs.map(revision => {
          const run = latestRun(revision)
          const state = run?.rootState ?? run?.state ?? 'pending'
          return (
            <li key={revision.graph.graphDigest}>
              <button
                className="dog-list-button"
                type="button"
                data-selected={revision.graph.graphDigest === selectedRevision.graph.graphDigest}
                onClick={() => onSelectRevision(revision)}
              >
                <span className="dog-list-row">
                  <span className={`dog-state-dot ${stateClass(state)}`} />
                  <span className="dog-list-title">{revision.graph.input.id}</span>
                </span>
                <span className="dog-list-meta">
                  <span className={revision.current ? 'dog-list-current' : undefined}>{revision.current ? 'current' : 'historical'}</span>
                  <span>·</span>
                  <span>{Object.keys(revision.graph.input.nodes).length} goals</span>
                  <span>·</span>
                  <span className="dog-mono">{shortDigest(revision.graph.graphDigest)}</span>
                </span>
              </button>
            </li>
          )
        })}
      </ul>
      <div className="dog-sidebar-divider" />
      <h3 className="dog-section-label">Run history</h3>
      {selectedRevision.runs.length === 0 ? (
        <p className="dog-empty-small">No runs are bound to this immutable revision.</p>
      ) : (
        <ul className="dog-run-list">
          {selectedRevision.runs.map(run => {
            const state = run.rootState ?? run.state
            return (
              <li key={run.runId}>
                <button
                  className="dog-list-button"
                  type="button"
                  data-selected={run.runId === selectedRun?.runId}
                  onClick={() => onSelectRun(run.runId)}
                >
                  <span className="dog-list-row">
                    <span className={`dog-state-dot ${stateClass(state)}`} />
                    <span className="dog-list-title">{humanizeState(state)}</span>
                  </span>
                  <span className="dog-list-meta">
                    <span>{formatTime(run.updatedAt)}</span>
                    <span>·</span>
                    <span className="dog-mono">{shortId(run.runId)}</span>
                  </span>
                </button>
              </li>
            )
          })}
        </ul>
      )}
    </aside>
  )
}

function Summary({ revision, run, sessions }: {
  readonly revision: DogDebugGraphRevision
  readonly run: DogRun | undefined
  readonly sessions: SessionListState
}): JSX.Element {
  const results = Object.values(run?.goals ?? {})
  const attention = results.filter(result => isAttentionGoal(result.state)).length
  const total = Object.keys(revision.graph.input.nodes).length
  const settled = settledGoalCount(run)
  const agents = summarizeRunAgents(run, sessions)
  const state = run?.rootState ?? run?.state ?? 'pending'
  return (
    <section className="dog-summary" aria-label="Run summary">
      <div className={`dog-summary-primary ${stateClass(state)}`}>
        <span className="dog-root-orb"><RootIcon /></span>
        <div className="dog-summary-copy">
          <div className="dog-summary-kicker">Root outcome</div>
          <div className="dog-summary-value">{humanizeState(state)}</div>
        </div>
      </div>
      <Metric label="Nodes" value={`${settled}/${total}`} />
      <Metric label="Agent tokens" value={formatTokenMetric(agents.tokens, agents.partialTokens)} />
      <Metric label="Agents" value={`${agents.linked} · ${agents.running} live`} />
      <Metric label="Attention" value={String(attention)} />
    </section>
  )
}

function Metric({ label, value }: { readonly label: string; readonly value: string }): JSX.Element {
  return <div className="dog-metric"><div className="dog-metric-label">{label}</div><div className="dog-metric-value">{value}</div></div>
}

function CanvasToolbar({ zoom, onZoom }: { readonly zoom: number; readonly onZoom: (value: number) => void }): JSX.Element {
  const adjust = (delta: number): void => onZoom(clampZoom(zoom + delta))
  return (
    <div className="dog-canvas-toolbar">
      <div className="dog-legend" aria-label="Edge legend">
        <span className="dog-legend-item"><span className="dog-legend-line" />Contains</span>
        <span className="dog-legend-item"><span className="dog-legend-line" data-kind="depends" />Depends on</span>
      </div>
      <span className="dog-canvas-spacer" />
      <div className="dog-zoom" aria-label="Canvas zoom">
        <button className="dog-zoom-button" type="button" aria-label="Zoom out" onClick={() => adjust(-0.1)}>−</button>
        <span className="dog-zoom-value">{Math.round(zoom * 100)}%</span>
        <button className="dog-zoom-button" type="button" aria-label="Zoom in" onClick={() => adjust(0.1)}>+</button>
      </div>
    </div>
  )
}

interface GraphCanvasProps {
  readonly graph: CompiledGraph
  readonly run: DogRun | undefined
  readonly sessions: SessionListState
  readonly selectedNodeId: string | undefined
  readonly zoom: number
  readonly onSelectNode: (id: string) => void
  readonly openSession: DogDebuggerProps['openSession']
}

function GraphCanvas({ graph, run, sessions, selectedNodeId, zoom, onSelectNode, openSession }: GraphCanvasProps): JSX.Element {
  const layout = useMemo(() => layoutDag(graph.input), [graph])
  const [expandedAgentNodeId, setExpandedAgentNodeId] = useState<string>()
  const scaledWidth = layout.width * zoom
  const scaledHeight = layout.height * zoom
  const stageStyle: CSSProperties = { width: layout.width, height: layout.height, transform: `scale(${zoom})` }
  const wrapStyle: CSSProperties = { width: scaledWidth, height: scaledHeight, minWidth: '100%' }

  useEffect(() => setExpandedAgentNodeId(undefined), [graph.graphDigest, run?.runId])

  return (
    <div className="dog-canvas-scroll">
      <div className="dog-canvas-stage-wrap" style={wrapStyle}>
        <div className="dog-canvas-stage" style={stageStyle}>
          <svg className="dog-edges" width={layout.width} height={layout.height} aria-hidden="true">
            <defs>
              <marker id="dog-dependency-arrow" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto" markerUnits="strokeWidth">
                <path d="M 0 0 L 8 4 L 0 8 z" fill="#c07a39" />
              </marker>
            </defs>
            {layout.edges.map(edge => {
              const connected = selectedNodeId === undefined || edge.source === selectedNodeId || edge.target === selectedNodeId
              return <path
                key={edge.id}
                className="dog-edge"
                data-kind={edge.kind}
                data-muted={!connected}
                data-highlighted={connected && selectedNodeId !== undefined}
                d={edge.path}
                markerEnd={edge.kind === 'dependsOn' ? 'url(#dog-dependency-arrow)' : undefined}
              />
            })}
          </svg>
          {layout.nodes.map(position => {
            const node = graph.input.nodes[position.id]
            if (node === undefined) return null
            const result = run?.goals[position.id] ?? { state: 'pending' as const }
            const agents = goalAgentRefs(run, position.id)
            const expanded = expandedAgentNodeId === position.id
            const style: CSSProperties = {
              left: position.x,
              top: position.y,
              width: position.width,
              height: position.height,
            }
            return (
              <Fragment key={position.id}>
                <button
                  className="dog-node"
                  type="button"
                  style={style}
                  data-selected={position.id === selectedNodeId}
                  data-root={position.id === graph.input.root}
                  data-agents-expanded={expanded || undefined}
                  aria-expanded={expanded}
                  aria-label={`${node.title}: ${humanizeState(result.state)}. Click to ${expanded ? 'hide' : 'show'} ${agents.length} related Agents.`}
                  onClick={() => {
                    onSelectNode(position.id)
                    setExpandedAgentNodeId(current => current === position.id ? undefined : position.id)
                  }}
                >
                  <span className="dog-node-top">
                    <span className={position.id === graph.input.root ? 'dog-node-kind dog-node-root' : 'dog-node-kind'}>
                      {position.id === graph.input.root ? 'Root goal' : `${node.constraint} · ${node.kind}`}
                    </span>
                    <StatusChip state={result.state} />
                  </span>
                  <span className="dog-node-title">{node.title}</span>
                  <span className="dog-node-foot">
                    <span className="dog-node-id">{position.id}</span>
                    <span className="dog-node-agents"><AgentIcon />{agents.length}</span>
                  </span>
                </button>
                {expanded ? (
                  <AgentFlyout
                    goalTitle={node.title}
                    refs={agents}
                    sessions={sessions}
                    style={agentFlyoutStyle(position, layout.width, layout.height)}
                    onClose={() => setExpandedAgentNodeId(undefined)}
                    openSession={openSession}
                  />
                ) : null}
              </Fragment>
            )
          })}
        </div>
      </div>
    </div>
  )
}

interface AgentFlyoutProps {
  readonly goalTitle: string
  readonly refs: readonly GoalAgentSessionRef[]
  readonly sessions: SessionListState
  readonly style: CSSProperties
  readonly onClose: () => void
  readonly openSession: DogDebuggerProps['openSession']
}

function AgentFlyout({ goalTitle, refs, sessions, style, onClose, openSession }: AgentFlyoutProps): JSX.Element {
  const [openingSession, setOpeningSession] = useState<string>()
  const [error, setError] = useState<string>()
  const agents = refs.map(ref => goalAgentTelemetry(ref, sessions))
  const open = async (ref: GoalAgentSessionRef): Promise<void> => {
    setOpeningSession(ref.sessionId)
    setError(undefined)
    try {
      if (!await openSession(ref.sessionId, ref.parentSessionId)) {
        setError('This Agent session is no longer addressable.')
      }
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause))
    } finally {
      setOpeningSession(undefined)
    }
  }
  return (
    <section className="dog-agent-flyout" style={style} aria-label={`Agents related to ${goalTitle}`}>
      <header className="dog-agent-flyout-head">
        <span><AgentIcon /> Related Agents</span>
        <button type="button" onClick={onClose} aria-label="Close related Agents"><CloseIcon /></button>
      </header>
      {agents.length === 0 ? (
        <div className="dog-agent-empty">No Agent has bound itself to this node.</div>
      ) : (
        <ul className="dog-agent-list">
          {agents.map(agent => {
            const activity = agent.needsInput ? 'Needs input' : agent.running ? 'Running' : agent.available ? 'Finished' : 'Unavailable'
            return (
              <li key={agent.ref.sessionId}>
                <button
                  className="dog-agent-row"
                  type="button"
                  disabled={openingSession !== undefined}
                  onClick={() => void open(agent.ref)}
                  aria-label={`Open ${agent.label}, ${activity}`}
                >
                  <span className={`dog-agent-state ${agent.running ? 'dog-state-running' : agent.available ? 'dog-state-success' : 'dog-state-blocked'}`} />
                  <span className="dog-agent-copy">
                    <span className="dog-agent-name">{agent.label}</span>
                    <span className="dog-agent-meta">{humanizeState(agent.ref.role)} · {activity}</span>
                  </span>
                  <span className="dog-agent-metrics">
                    <span>{agent.tokens === undefined ? '— tok' : `${formatCompactNumber(agent.tokens)} tok`}</span>
                    <span>{agent.durationMs === undefined ? '—' : formatAgentDuration(agent.durationMs)}</span>
                  </span>
                </button>
              </li>
            )
          })}
        </ul>
      )}
      {error === undefined ? null : <div className="dog-agent-error" role="status">{error}</div>}
      <div className="dog-agent-hint">Click an Agent to open its native DSH conversation.</div>
    </section>
  )
}

function Inspector({ graph, run, nodeId, readGoalRuntime, openSession }: {
  readonly graph: CompiledGraph
  readonly run: DogRun | undefined
  readonly nodeId: string | undefined
  readonly readGoalRuntime: DogDebuggerProps['readGoalRuntime']
  readonly openSession: DogDebuggerProps['openSession']
}): JSX.Element {
  const node = nodeId === undefined ? undefined : graph.input.nodes[nodeId]
  if (node === undefined || nodeId === undefined) {
    return <aside className="dog-inspector"><p className="dog-empty-small">Select a goal to inspect its contract and evidence.</p></aside>
  }
  const result = run?.goals[nodeId] ?? { state: 'pending' as const }
  const plan = graph.acceptancePlans[nodeId]
  const parents = graph.input.contains.filter(edge => edge.child === nodeId)
  const children = graph.input.contains.filter(edge => edge.parent === nodeId)
  const dependencies = graph.input.dependsOn.filter(edge => edge.source === nodeId || edge.target === nodeId)
  const reason = result.reason ?? (result.verification?.passed === false
    ? 'Trusted verifier returned false for this sandboxed input.'
    : undefined)
  return (
    <aside className="dog-inspector" aria-label="Selected goal details">
      <div className="dog-inspector-head">
        <div className="dog-inspector-title-wrap">
          <div className="dog-inspector-eyebrow">{nodeId === graph.input.root ? 'Root goal' : 'Goal contract'}</div>
          <h3 className="dog-inspector-title">{node.title}</h3>
        </div>
        <StatusChip state={result.state} />
      </div>
      <div className="dog-inspector-chips">
        <span className="dog-mini-chip">{node.constraint}</span>
        <span className="dog-mini-chip">{node.kind}</span>
        <span className="dog-mini-chip dog-mono">{nodeId}</span>
      </div>
      {reason === undefined ? null : (
        <section className={`dog-inspector-section ${stateClass(result.state)}`}>
          <h4 className="dog-inspector-section-title">Why this state</h4>
          <div className="dog-reason">{reason}</div>
        </section>
      )}
      <section className="dog-inspector-section">
        <h4 className="dog-inspector-section-title">Contract</h4>
        <dl className="dog-definition">
          <dt>Constraint</dt><dd>{node.constraint}</dd>
          <dt>Completion</dt><dd className="dog-mono">{node.completion === undefined ? 'atomic verifier' : formatExpression(node.completion)}</dd>
          <dt>Updated</dt><dd>{run === undefined ? 'No run yet' : formatTimestamp(run.updatedAt)}</dd>
          <dt>Graph digest</dt><dd className="dog-mono" title={graph.graphDigest}>{shortDigest(graph.graphDigest)}</dd>
        </dl>
      </section>
      <RuntimeContextPanel
        run={run}
        goalId={nodeId}
        readGoalRuntime={readGoalRuntime}
        openSession={openSession}
      />
      <Evidence node={node} result={result} plan={plan} />
      <section className="dog-inspector-section">
        <h4 className="dog-inspector-section-title">Relations</h4>
        {parents.length + children.length + dependencies.length === 0 ? <p className="dog-empty-small">No graph relations.</p> : (
          <ul className="dog-relation-list">
            {parents.map((edge, index) => <li className="dog-relation" key={`parent:${index}`}><strong>{edge.parent}</strong> contains this goal · {edge.required ? 'required' : 'optional'} · {edge.failure}</li>)}
            {children.map((edge, index) => <li className="dog-relation" key={`child:${index}`}>Contains <strong>{edge.child}</strong> · {edge.required ? 'required' : 'optional'} · {edge.failure}</li>)}
            {dependencies.map((edge, index) => <li className="dog-relation" data-kind="dependsOn" key={`dependency:${index}`}><strong>{edge.source}</strong> depends on <strong>{edge.target}</strong>{edge.data === undefined ? '' : ` · ${edge.data.join(', ')}`}</li>)}
          </ul>
        )}
      </section>
      <section className="dog-inspector-section">
        <details className="dog-raw">
          <summary>Raw goal record</summary>
          <pre>{JSON.stringify({ nodeId, node, result, acceptancePlan: plan }, null, 2)}</pre>
        </details>
      </section>
    </aside>
  )
}

interface RuntimeContextPanelProps {
  readonly run: DogRun | undefined
  readonly goalId: string
  readonly readGoalRuntime: DogDebuggerProps['readGoalRuntime']
  readonly openSession: DogDebuggerProps['openSession']
}

function RuntimeContextPanel({ run, goalId, readGoalRuntime, openSession }: RuntimeContextPanelProps): JSX.Element {
  const [trace, setTrace] = useState<GoalRuntimeTrace>()
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string>()
  const [sessionError, setSessionError] = useState<string>()
  const [openingSession, setOpeningSession] = useState(false)
  const runId = run?.runId
  const runState = run?.state

  useEffect(() => {
    setTrace(undefined)
    setError(undefined)
    setSessionError(undefined)
    setOpeningSession(false)
    if (runId === undefined || runState === undefined) {
      setLoading(false)
      return
    }
    let disposed = false
    let inFlight = false
    const controller = new AbortController()
    const refresh = async (): Promise<void> => {
      if (inFlight) return
      inFlight = true
      setLoading(true)
      try {
        const next = parseGoalRuntimeTrace(await readGoalRuntime(runId, goalId, controller.signal))
        if (next.runId !== runId || next.goalId !== goalId) throw new Error('runtime trace identity mismatch')
        if (!disposed) {
          setTrace(next)
          setError(undefined)
        }
      } catch (cause) {
        if (!disposed && !controller.signal.aborted) setError(cause instanceof Error ? cause.message : String(cause))
      } finally {
        inFlight = false
        if (!disposed) setLoading(false)
      }
    }
    void refresh()
    const timer = runState === 'running'
      ? window.setInterval(() => void refresh(), 1_500)
      : undefined
    return () => {
      disposed = true
      controller.abort()
      if (timer !== undefined) window.clearInterval(timer)
    }
  }, [goalId, readGoalRuntime, runId, runState])

  if (run === undefined) {
    return (
      <section className="dog-inspector-section">
        <h4 className="dog-inspector-section-title">Runtime context</h4>
        <p className="dog-empty-small dog-runtime-empty">Run this graph to capture node activity and failure context.</p>
      </section>
    )
  }

  const events = trace?.events ?? []
  const latestEvent = events[events.length - 1]
  const errorEvent = [...events].reverse().find(event => event.phase === 'structured_error')
  const attempts = new Set(events.map(event => event.attempt ?? 1)).size
  const invocation = trace?.invocation
  const goalState = trace?.result.state ?? run.goals[goalId]?.state ?? 'pending'
  const activity = runtimeActivity(goalState, latestEvent, loading)
  const openInvoker = async (): Promise<void> => {
    setSessionError(undefined)
    const sessionId = invocation?.agentSessionId
    const parentSessionId = invocation?.parentSessionId
    if (sessionId === undefined) return
    setOpeningSession(true)
    try {
      if (!await openSession(sessionId, parentSessionId)) {
        setSessionError('The invoking session is no longer available in this client.')
      }
    } catch (cause) {
      setSessionError(cause instanceof Error ? cause.message : String(cause))
    } finally {
      setOpeningSession(false)
    }
  }

  return (
    <section className="dog-inspector-section" aria-label="Goal runtime context">
      <div className="dog-runtime-heading">
        <h4 className="dog-inspector-section-title">Runtime context</h4>
        {loading ? <span className="dog-runtime-live"><span className="dog-runtime-pulse" />refreshing</span> : null}
      </div>
      {error === undefined ? null : <div className="dog-runtime-warning">Context unavailable: {error}</div>}
      {trace?.runtimeWarning === undefined ? null : <div className="dog-runtime-warning">{trace.runtimeWarning}</div>}
      <div className={`dog-runtime-card ${stateClass(goalState)}`}>
        <span className="dog-runtime-orb" />
        <div className="dog-runtime-card-copy">
          <div className="dog-runtime-activity">{activity}</div>
          <div className="dog-runtime-meta">
            {events.length === 0 ? 'No events yet' : `${events.length} events · ${attempts} attempt${attempts === 1 ? '' : 's'}`}
            {latestEvent?.durationMs === undefined ? '' : ` · ${formatDuration(latestEvent.durationMs)}`}
          </div>
        </div>
      </div>
      {errorEvent === undefined || errorEvent.reason === undefined ? null : (
        <div className={`dog-runtime-error ${stateClass(errorEvent.state ?? 'needs_human')}`}>
          <strong>Verification error</strong>
          <span>{errorEvent.reason}</span>
        </div>
      )}
      {invocation === undefined ? null : (
        <div className="dog-runtime-session">
          <div className="dog-runtime-session-head">
            <span>Invoking DSH session</span>
            {invocation.agentSessionId === undefined ? null : (
              <button className="dog-runtime-session-button" type="button" disabled={openingSession} onClick={() => void openInvoker()}>{openingSession ? 'Opening…' : 'Open session'}</button>
            )}
          </div>
          <dl className="dog-definition">
            <dt>Session</dt><dd className="dog-mono">{invocation.agentSessionId === undefined ? 'headless / unavailable' : shortId(invocation.agentSessionId)}</dd>
            {invocation.parentSessionId === undefined ? null : <><dt>Parent</dt><dd className="dog-mono">{shortId(invocation.parentSessionId)}</dd></>}
            <dt>Tool call</dt><dd className="dog-mono" title={invocation.callId}>{shortId(invocation.callId)}</dd>
            <dt>Invoked</dt><dd>{formatTimestamp(invocation.invokedAt)}</dd>
          </dl>
          {sessionError === undefined ? null : <div className="dog-runtime-session-error">{sessionError}</div>}
        </div>
      )}
      {events.length === 0 ? (
        <p className="dog-empty-small dog-runtime-empty">
          {loading ? 'Loading node activity…' : 'No runtime events were recorded for this node.'}
        </p>
      ) : (
        <ol className="dog-runtime-timeline" aria-label="Runtime event timeline">
          {events.map((event, index) => (
            <li className={`dog-runtime-event ${stateClass(event.state ?? 'running')}`} key={index}>
              <span className="dog-runtime-marker" />
              <div className="dog-runtime-event-copy">
                <div className="dog-runtime-event-head">
                  <strong>{runtimeEventLabel(event.phase)}</strong>
                  <time dateTime={event.at}>{formatTime(event.at)}</time>
                </div>
                {event.attempt === undefined ? null : <div className="dog-runtime-event-meta">Attempt {event.attempt}</div>}
                {runtimeEventDetail(event) === undefined ? null : <div className="dog-runtime-event-detail">{runtimeEventDetail(event)}</div>}
              </div>
            </li>
          ))}
        </ol>
      )}
      {trace?.truncated === true ? <div className="dog-runtime-warning">Showing the latest 64 events for this goal.</div> : null}
      {trace === undefined ? null : (
        <details className="dog-raw dog-runtime-raw">
          <summary>Raw runtime trace</summary>
          <pre>{JSON.stringify(trace, null, 2)}</pre>
        </details>
      )}
    </section>
  )
}

function runtimeActivity(state: GoalState, event: GoalRuntimeEvent | undefined, loading: boolean): string {
  if (event === undefined) return loading ? 'Loading runtime context' : state === 'pending' ? 'Waiting for scheduler' : humanizeState(state)
  if (event.phase === 'verifier_started' && event.verifier !== undefined) return `Running ${event.verifier.mode} kernel`
  if (event.phase === 'dependency_blocked') return 'Blocked by an upstream dependency'
  if (event.phase === 'structured_error') return 'Execution needs human review'
  if (event.phase === 'goal_settled') return `Settled as ${humanizeState(event.state ?? state)}`
  return runtimeEventLabel(event.phase)
}

function runtimeEventLabel(phase: GoalRuntimeEvent['phase']): string {
  switch (phase) {
    case 'goal_started': return 'Goal started'
    case 'dependency_blocked': return 'Dependency blocked'
    case 'grounding_extracted': return 'Grounding material extracted'
    case 'workspace_allocated': return 'Isolated workspace allocated'
    case 'verifier_started': return 'Verifier started'
    case 'verifier_passed': return 'Verifier passed'
    case 'verifier_failed': return 'Verifier failed'
    case 'verifier_inconclusive': return 'Verifier inconclusive'
    case 'composite_evaluated': return 'Completion rule evaluated'
    case 'result_inherited': return 'Verification reused: material unchanged'
    case 'verifier_released': return 'Verifier worker released'
    case 'verifier_bind_failed': return 'Verifier worker binding failed'
    case 'structured_error': return 'Runtime error'
    case 'goal_settled': return 'Goal settled'
    case 'run_warning': return 'Run warning'
  }
}

function runtimeEventDetail(event: GoalRuntimeEvent): string | undefined {
  if (event.reason !== undefined) return event.reason
  if (event.verifier !== undefined) return `${event.verifier.mode} kernel`
  return undefined
}

function formatDuration(value: number): string {
  return value < 1_000 ? `${value} ms` : `${(value / 1_000).toFixed(value < 10_000 ? 1 : 0)} s`
}

function Evidence({ node, result, plan }: { readonly node: GoalNodeInput; readonly result: GoalResult; readonly plan: CompiledGraph['acceptancePlans'][string] | undefined }): JSX.Element | null {
  if (node.kind !== 'leaf') return null
  return (
    <section className="dog-inspector-section">
      <h4 className="dog-inspector-section-title">Trusted evidence</h4>
      {plan === undefined ? <div className="dog-reason dog-state-needs_human">No compiled acceptance plan is available.</div> : (
        <div className="dog-evidence">
          <div className="dog-evidence-head">
            <span className="dog-evidence-name">{plan.verifier.mode === 'programmatic' ? `script:${plan.verifier.script}` : 'agentic'}</span>
            {result.verification === undefined ? <span className="dog-mini-chip">not run</span> : <StatusChip state={result.verification.passed ? 'success' : 'failure'} />}
          </div>
          <div className="dog-evidence-body">
            <dl className="dog-definition">
              <dt>Sandbox file</dt><dd className="dog-mono">{(typeof plan.input?.path === 'string' && plan.input.path.length > 0) ? plan.input.path : '(run workspace)'}</dd>
              <dt>Digest</dt><dd className="dog-mono" title={plan.input?.digest}>{plan.input === undefined ? '—' : shortId(plan.input.digest)}</dd>
              <dt>Bytes</dt><dd>{plan.input === undefined ? '—' : plan.input.byteLength.toLocaleString()}</dd>
              <dt>Target</dt><dd className="dog-mono">{plan.target}</dd>
            </dl>
            {result.verification === undefined ? null : (
              <div className="dog-inspector-section">
                <h5 className="dog-inspector-section-title">Evidence</h5>
                <div className="dog-observation">
                  {Object.entries(result.verification.evidence as unknown as Record<string, JsonValue> ?? {}).map(([key, value]) => (
                    <div className="dog-observation-row" key={key}>
                      <span className="dog-observation-key">{key}</span>
                      <span className="dog-observation-value">{formatJson(value)}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        </div>
      )}
    </section>
  )
}

function EmptyWorkspace({ loading, error }: { readonly loading: boolean; readonly error: string | undefined }): JSX.Element {
  return (
    <div className="dog-workspace">
      <div className="dog-empty">
        <div className="dog-empty-card">
          <div className="dog-empty-icon">{loading ? <RefreshIcon /> : <NetworkIcon size={22} />}</div>
          <h3 className="dog-empty-title">{loading ? 'Loading DoG revisions…' : error === undefined ? 'No persisted graphs yet' : 'Debugger data unavailable'}</h3>
          <p className="dog-empty-copy">{error ?? 'Create a graph with dog_create, then run it. The immutable revision and verifier evidence will appear here automatically.'}</p>
        </div>
      </div>
    </div>
  )
}

function StatusChip({ state }: { readonly state: GoalState | RootTerminalState | DogRun['state'] }): JSX.Element {
  const title = state === 'inherited'
    ? 'Reused the prior run verification record: same material digest (GM) and same verifier contract. Not re-run.'
    : undefined
  return <span className={`dog-status-chip ${stateClass(state)}`} title={title}>{humanizeState(state)}</span>
}

function IconButton({ label, busy, onClick, children }: { readonly label: string; readonly busy: boolean; readonly onClick: () => void; readonly children: ReactNode }): JSX.Element {
  return <button className="dog-icon-button" type="button" aria-label={label} title={label} aria-busy={busy} onClick={onClick}>{children}</button>
}

function readDogDockCollapsed(): boolean {
  try {
    if (typeof window === 'undefined') return true
    const stored = window.localStorage.getItem(DOG_DOCK_COLLAPSED_KEY)
    return stored === null ? true : stored === 'true'
  } catch {
    return true
  }
}

function writeDogDockCollapsed(collapsed: boolean): void {
  try {
    window.localStorage.setItem(DOG_DOCK_COLLAPSED_KEY, String(collapsed))
  } catch {
    // Storage can be unavailable in restricted browser contexts; in-memory state still works.
  }
}

function latestRun(revision: DogDebugGraphRevision): DogRun | undefined {
  return revision.runs[0]
}

function isAttentionGoal(state: GoalState): boolean {
  return state === 'failure' || state === 'needs_human' || state === 'blocked' || state === 'partial'
}


function stateClass(state: string): string {
  return `dog-state-${state}`
}

function humanizeState(state: string): string {
  return state.replaceAll('_', ' ').replace(/\b\w/gu, letter => letter.toUpperCase())
}

function formatExpression(expression: BoolExpr): string {
  switch (expression.op) {
    case 'ref': return expression.id
    case 'not': return `NOT(${formatExpression(expression.item)})`
    case 'all': return `ALL(${expression.items.map(formatExpression).join(', ')})`
    case 'any': return `ANY(${expression.items.map(formatExpression).join(', ')})`
    case 'atLeast': return `AT_LEAST ${expression.count}(${expression.items.map(formatExpression).join(', ')})`
  }
}

function formatJson(value: JsonValue): string {
  return typeof value === 'string' ? value : JSON.stringify(value)
}

function formatTime(value: string): string {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return new Intl.DateTimeFormat(undefined, { hour: '2-digit', minute: '2-digit', month: 'short', day: 'numeric' }).format(date)
}

function formatTimestamp(value: string): string {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeStyle: 'short' }).format(date)
}

function shortDigest(value: string): string {
  return `${value.slice(0, 8)}…${value.slice(-5)}`
}

function shortId(value: string): string {
  return value.length <= 17 ? value : `${value.slice(0, 9)}…${value.slice(-6)}`
}

function formatCompactNumber(value: number): string {
  return new Intl.NumberFormat('en-US', { notation: 'compact', maximumFractionDigits: 1 }).format(value)
}

function formatTokenMetric(tokens: number | undefined, partial: boolean): string {
  if (tokens === undefined) return '—'
  const formatted = formatCompactNumber(tokens)
  return partial ? `≥${formatted}` : formatted
}

function formatAgentDuration(value: number): string {
  if (value < 60_000) return `${Math.max(1, Math.round(value / 1_000))}s`
  if (value < 3_600_000) return `${Math.round(value / 60_000)}m`
  return `${(value / 3_600_000).toFixed(value < 36_000_000 ? 1 : 0)}h`
}

function agentFlyoutStyle(position: PositionedGoal, canvasWidth: number, canvasHeight: number): CSSProperties {
  const width = 228
  const gap = 10
  const right = position.x + position.width + gap
  const left = right + width <= canvasWidth ? right : Math.max(gap, position.x - width - gap)
  const maxHeight = Math.max(150, canvasHeight - gap * 2)
  const top = Math.min(Math.max(gap, position.y - 4), Math.max(gap, canvasHeight - Math.min(250, maxHeight) - gap))
  return { left, top, width, maxHeight }
}

function clampZoom(value: number): number {
  return Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, Math.round(value * 10) / 10))
}


function NetworkIcon({ size = 16 }: { readonly size?: number }): JSX.Element {
  return <svg width={size} height={size} viewBox="0 0 24 24" fill="none" aria-hidden="true"><circle cx="12" cy="5" r="2.5" fill="currentColor" /><circle cx="5" cy="18" r="2.5" fill="currentColor" /><circle cx="19" cy="18" r="2.5" fill="currentColor" /><path d="M10.6 7.1 6.4 15.6M13.4 7.1l4.2 8.5M7.5 18h9" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" /></svg>
}
function AgentIcon(): JSX.Element {
  return <svg width="13" height="13" viewBox="0 0 24 24" fill="none" aria-hidden="true"><circle cx="12" cy="8" r="3.2" stroke="currentColor" strokeWidth="1.7" /><path d="M5.5 19c.5-3.4 2.7-5.3 6.5-5.3s6 1.9 6.5 5.3" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" /><path d="M18.3 7.2h2.2M19.4 6.1v2.2" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" /></svg>
}
function RefreshIcon(): JSX.Element {
  return <svg width="16" height="16" viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M19 8a8 8 0 1 0 1 7M19 4v4h-4" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" /></svg>
}
function CloseIcon(): JSX.Element {
  return <svg width="17" height="17" viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="m6 6 12 12M18 6 6 18" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" /></svg>
}
function DockCollapseIcon(): JSX.Element {
  return <svg width="16" height="16" viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="m14.5 6-6 6 6 6" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" /></svg>
}
function DockExpandIcon(): JSX.Element {
  return <svg width="14" height="14" viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="m9.5 6 6 6-6 6" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" /></svg>
}
function RootIcon(): JSX.Element {
  return <svg width="16" height="16" viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M12 3 4.5 7.2v9.6L12 21l7.5-4.2V7.2L12 3Z" stroke="currentColor" strokeWidth="1.7" /><circle cx="12" cy="12" r="2.3" fill="currentColor" /></svg>
}
