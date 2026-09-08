/** DoG v0.9 engine: graph compilation, two-kernel judgment, Agentic CI run. */

import { createHash, randomUUID } from 'node:crypto'
import { existsSync, readFileSync } from 'node:fs'
import { isAbsolute, join } from 'node:path'
import { evaluateBoolExpr } from './logic.ts'
import { DogValidationError, parseGraph } from './graph.ts'
import { sha256Json } from './json.ts'
import type {
 AcceptancePlan,
 ContainsEdge,
 CompiledGraph,
 DogConfig,
 DogGraphInput,
 DogRun,
 GoalResult,
 GoalRuntimeError,
 GoalRuntimeEvent,
 GoalRuntimePhase,
 GoalState,
 GoalAgentRole,
 GoalAgentSessionRef,
 GraphValidationReport,
 RootTerminalState,
 VerificationRecord,
} from './model.ts'
import type { Agent } from '@deepseek-ai/dsh-agent'
import { DogRepository, captureWorkspaceTarget, type CapturedInputFile } from './storage.ts'
import { runPlan, type AgenticRunner, type ProgrammaticRunner, type Settlement } from './verifiers.ts'
import { WorkspaceManager } from './workspace.ts'
import type { IsolatedWorkspace } from './verifiers.ts'

export interface DogEngineOptions {
 readonly config: DogConfig
 readonly repository: DogRepository
 /** Runtime knob source: read once per run, so host settings changes apply without a restart. */
 readonly liveConfig?: () => Partial<Pick<DogConfig, 'maxConcurrentVerifications'>>
 /** Host hook fired after a run is cancelled — used to interrupt its verifier subagents. */
 readonly onRunCancelled?: (runId: string) => void
 /** Programmatic kernel (script executor) — host wiring; may be installed later. */
 readonly programmatic?: ProgrammaticRunner
 /** Agentic kernel (worker-agent launcher) — host wiring; may be installed later. */
 readonly agentic?: AgenticRunner
 readonly workspaces?: WorkspaceManager
 readonly now?: () => Date
 readonly nextRunId?: () => string
 readonly heartbeatMs?: number
 /** Resolve a live Agent by its session id (host wiring: AgentRegistry.get). */
 readonly resolveLivingAgent?: (sessionId: string) => Agent | undefined
}

export interface DogRunOptions {
 readonly invocation?: {
  readonly callId: string
  readonly agentSessionId?: string
  readonly parentSessionId?: string
 }
 readonly signal?: AbortSignal
 readonly agent?: Agent | undefined
}

export interface DogBindAgentOptions {
 readonly runId: string
 readonly goalId: string
 readonly role: GoalAgentRole
 readonly sessionId: string
 readonly parentSessionId?: string
}

export interface DogAgentDelegationOptions {
 readonly runId: string
 readonly goalId: string
 readonly parentSessionId: string
}

interface RuntimeEventDetails {
 readonly at?: string
 readonly state?: GoalState
 readonly reason?: string
 readonly verifier?: GoalRuntimeEvent['verifier']
 readonly gmDigest?: string
 readonly attempt?: number
 readonly durationMs?: number
}

const GOAL_AGENT_ROLES = new Set<GoalAgentRole>(['orchestrator', 'verifier', 'reviewer'])

/** Agentic CI engine used by the DSH tools and tests. */
export class DogEngine {
 private readonly config: DogConfig
 private readonly repository: DogRepository
 private readonly liveConfig: ((() => Partial<Pick<DogConfig, 'maxConcurrentVerifications'>>) | undefined)
 private readonly onRunCancelled: ((runId: string) => void) | undefined
 private readonly runControllers = new Map<string, AbortController>()
 private programmatic: ProgrammaticRunner | undefined
 private agentic: AgenticRunner | undefined
 private readonly workspaces: WorkspaceManager
 private readonly now: () => Date
 private readonly nextRunId: () => string
 private readonly heartbeatMs: number
 private readonly workspaceRoot: string
 private readonly backgroundTasks = new Set<Promise<void>>()
 private readonly runStops = new Map<string, () => void>()
 private readonly workspaceBaseDirs = new Map<string, string | undefined>()
 private readonly resolveLivingAgent: ((sessionId: string) => Agent | undefined) | undefined

 /** Install the two judgment kernels (host wiring; may arrive later than construction). */
 setKernels(programmatic: ProgrammaticRunner | undefined, agentic: AgenticRunner | undefined): void {
  this.programmatic = programmatic
  this.agentic = agentic
 }

 constructor(options: DogEngineOptions) {
  validateHostConfig(options.config)
  this.config = options.config
  this.repository = options.repository
  this.liveConfig = options.liveConfig
  this.onRunCancelled = options.onRunCancelled
  this.programmatic = options.programmatic
  this.agentic = options.agentic
  this.workspaces = options.workspaces ?? new WorkspaceManager()
  this.now = options.now ?? (() => new Date())
  this.nextRunId = options.nextRunId ?? (() => randomUUID())
  this.heartbeatMs = options.heartbeatMs ?? 30_000
  this.resolveLivingAgent = options.resolveLivingAgent
  this.workspaceRoot = options.config.workspaceRoot
 }

 validate(value: unknown): GraphValidationReport {
  try {
   const graph = this.parse(value)
   this.validateWorkspaceRefs(graph)
   return { valid: true, errors: [], warnings: graphWarnings(graph) }
  } catch (error) {
   const errors = error instanceof DogValidationError ? [...error.errors] : [messageOf(error)]
   return { valid: false, errors, warnings: [] }
  }
 }

 /** Compile and persist one graph revision against the captured input files. */
 async create(value: unknown, options: { readonly captureBaseDir?: string } = {}): Promise<CompiledGraph> {
  const graph = this.parse(value)
  this.validateWorkspaceRefs(graph)
  const acceptancePlans: Record<string, AcceptancePlan> = {}
  const capturedCache = new Map<string, CapturedInputFile>()
  // Capture roots: the invoking session's cwd first (that is where the user is
  // working), then the configured workspace root as the fallback.
  const captureRoots = options.captureBaseDir !== undefined && options.captureBaseDir.length > 0
   ? [options.captureBaseDir, this.workspaceRoot]
   : [this.workspaceRoot]
  for (const [goalId, node] of Object.entries(graph.nodes)) {
   if (node.verifier === undefined) continue
   const workspaceFile = requireTarget(node.target, goalId)
   let captured: CapturedInputFile | undefined = undefined
   if (workspaceFile !== '') {
    captured = capturedCache.get(workspaceFile)
    if (captured === undefined) {
     captured = await captureWorkspaceTarget(
      captureRoots,
      workspaceFile,
      this.config.maxSandboxBytes,
      this.repository,
     )
     capturedCache.set(workspaceFile, captured)
    }
   }
   acceptancePlans[goalId] = {
    goalId,
    verifier: node.verifier,
    judgment: computeJudgment(node.verifier, this.config.scriptsDirectory),
    target: node.target,
    ...(workspaceFile === '' || captured === undefined ? {} : { input: captured.input }),
   }
  }
  const graphDigest = sha256Json({ input: graph, acceptancePlans })
  const compiled = deepFreeze({ input: graph, graphDigest, acceptancePlans })
  await this.repository.saveGraph(compiled)
  return compiled
 }

 /** Synchronous run: prepare + execute to completion (tests, CLI). */
 async run(graphId: string, options: DogRunOptions = {}): Promise<DogRun> {
  const prepared = await this.prepareRun(graphId, options)
  return this.executeRun(prepared, options)
 }

 /** Asynchronous run: returns after the initial record is persisted; verification continues in background. */
 async startRun(graphId: string, options: DogRunOptions = {}): Promise<DogRun> {
  const prepared = await this.prepareRun(graphId, options)
  const controller = new AbortController()
  this.runControllers.set(prepared.runId, controller)
  this.enqueueBackground(prepared, { ...options, signal: controller.signal })
  return prepared.initial
 }

 /** Execute a prepared run on the engine's process-level loop, independent of any caller session. */
 private enqueueBackground(
  prepared: { compiled: CompiledGraph; runId: string; initial: DogRun },
  options: DogRunOptions,
 ): void {
  // options carries the run-level controller's signal (installed by startRun);
  // it must NOT be replaced here — dog_cancel aborts that exact controller.
  const task = this.executeRun(prepared, options)
   .then(() => undefined)
   .catch(async cause => {
    try {
     const live = await this.repository.loadRun(prepared.runId)
     if (live.state === 'running') {
      await this.repository.saveRun({
       ...live,
       state: 'failed',
       rootState: 'failure',
       runtimeWarning: `background execution failed: ${boundedMessage(messageOf(cause))}`,
       updatedAt: this.now().toISOString(),
      })
     }
    } catch {
     // best-effort failure marking; the original error is the authoritative record
    }
    this.runStops.get(prepared.runId)?.()
    this.runStops.delete(prepared.runId)
    this.runControllers.delete(prepared.runId)
    this.backgroundTasks.delete(task)
   })
  void task.finally(() => this.backgroundTasks.delete(task))
  this.backgroundTasks.add(task)
 }

 /** Stop this engine's owned runs before awaiting their settlement. */
 async dispose(): Promise<void> {
  await Promise.allSettled([...this.runControllers.keys()].map(id => this.cancelRun(id, 'OpenWrite stopped')))
  for (const stop of this.runStops.values()) stop()
  this.runStops.clear()
  await this.drainBackground()
 }

 /** Wait for every in-flight background run (host shutdown). */
 async drainBackground(): Promise<void> {
  await Promise.allSettled([...this.backgroundTasks])
 }

 /** Persist a bounded run-level warning (verifier binding/release diagnostics). */
 async annotateRun(runId: string, warning: string): Promise<void> {
  try {
   await this.repository.updateRun(runId, current => ({
    ...current,
    runtimeWarning: boundedMessage(warning),
    updatedAt: this.now().toISOString(),
   }))
  } catch {
   // diagnostic annotation must never throw into verification
  }
 }

 /** Append a verifier worker lifecycle event (verifier_released / verifier_bind_failed). */
 async recordVerifierLifecycle(
  runId: string,
  goalId: string,
  phase: 'verifier_released' | 'verifier_bind_failed',
  _sessionId: string,
  reason?: string,
 ): Promise<void> {
  try {
   await this.repository.appendRuntimeEvent({
    schemaVersion: '0.1',
    runId,
    goalId,
    phase,
    at: this.now().toISOString(),
    ...(reason === undefined ? {} : { reason: boundedMessage(reason) }),
    verifier: { mode: 'agentic' },
   })
  } catch {
   // lifecycle diagnostics must never throw into verification
  }
 }

 /** Cancel one run and stop its heartbeat; partial records remain inspectable. */
 async cancelRun(runId: string, reason: string): Promise<DogRun> {
  // 1) Abort the run-level signal first: in-flight verifiers stop waiting and
  //    settle as cancelled instead of continuing their work.
  this.runControllers.get(runId)?.abort(new Error(reason))
  this.runControllers.delete(runId)
  // 2) Stop the heartbeat.
  this.runStops.get(runId)?.()
  this.runStops.delete(runId)
  // 3) Mark the persisted run.
  const updated = await this.repository.updateRun(runId, current => ({
   ...current,
   state: 'cancelled',
   rootState: 'cancelled',
   runtimeWarning: `cancelled: ${boundedMessage(reason)}`,
   updatedAt: this.now().toISOString(),
  }))
  // 4) Tell the host to interrupt the run's live verifier subagents.
  this.onRunCancelled?.(runId)
  return updated
 }

 /**
  * Block on one run's settlement. Keeps the calling agent/session alive in
  * the process while verifier workers (continuable children of this process)
  * run to completion — the deterministic automation gate after dog_run. A
  * one-shot process that returns before this settles kills the workers it
  * spawned, so automation MUST wait through a dog_wait/monitor step.
  * @param options - bounded wait: default 15 minutes; abort (tool cancel)
  *   and timeout both return the current run with a non-terminal state.
  */
 async waitRun(
  runId: string,
  options: { readonly timeoutMs?: number; readonly pollMs?: number; readonly signal?: AbortSignal } = {},
 ): Promise<DogRun> {
  const deadline = Date.now() + (options.timeoutMs ?? 900_000)
  const pollMs = options.pollMs ?? 15_000
  for (; ;) {
   const run = await this.repository.loadRun(runId)
   if (run.state !== 'running') return run
   options.signal?.throwIfAborted()
   if (Date.now() >= deadline) return run
   await new Promise(resolve => setTimeout(resolve, pollMs))
  }
 }

 private async prepareRun(graphId: string, options: DogRunOptions): Promise<{ compiled: CompiledGraph; runId: string; initial: DogRun }> {
  const compiled = await this.repository.loadGraph(graphId)
  const runId = this.nextRunId()
  await this.supersedePriorRunningRuns(compiled.input.id, runId)
  const createdAt = this.now().toISOString()
  const invocation = options.invocation === undefined
   ? undefined
   : {
    callId: requireContextId(options.invocation.callId, 'invocation callId'),
    ...(options.invocation.agentSessionId === undefined ? {} : {
     agentSessionId: requireContextId(options.invocation.agentSessionId, 'invocation agentSessionId'),
    }),
    ...(options.invocation.parentSessionId === undefined ? {} : {
     parentSessionId: requireContextId(options.invocation.parentSessionId, 'invocation parentSessionId'),
    }),
    invokedAt: createdAt,
   }
  const goals: Record<string, GoalResult> = Object.fromEntries(
   Object.keys(compiled.input.nodes).map(id => [id, { state: 'pending' as const }]),
  )
  const gmDigests: Record<string, string> = {}
  // Verifier workspaces must land inside the calling session's workspace: that
  // is exactly the tree a verifier subagent's sandbox (workspace-write) permits
  // writing into, so settlements can round-trip. Resolve it once at run start.
  const workspaceBaseDir = options.invocation?.agentSessionId === undefined || this.resolveLivingAgent === undefined
   ? undefined
   : (() => {
    const agent = this.resolveLivingAgent(options.invocation!.agentSessionId!)
    const cwd = agent?.session.header.cwd
    return typeof cwd === 'string' && cwd.length > 0 ? cwd : undefined
   })()
  this.workspaceBaseDirs.set(runId, workspaceBaseDir)
  const initial: DogRun = {
   runId,
   graphId: compiled.input.id,
   graphDigest: compiled.graphDigest,
   ...(workspaceBaseDir === undefined ? {} : { workspaceBaseDir }),
   state: 'running',
   ...(invocation === undefined ? {} : { invocation }),
   gmDigests,
   goals,
   createdAt,
   updatedAt: createdAt,
  }
  await this.repository.saveRun(initial)
  return { compiled, runId, initial }
 }

 /** The Agentic CI cycle: revalidate-select, parallel verification, recompute. */
 private async executeRun(
  prepared: { compiled: CompiledGraph; runId: string; initial: DogRun },
  options: DogRunOptions,
 ): Promise<DogRun> {
  const { compiled, runId } = prepared
  const signal = options.signal ?? new AbortController().signal
  const goals: Record<string, GoalResult> = { ...prepared.initial.goals }
  const gmDigests: Record<string, string> = { ...prepared.initial.gmDigests }
  let run: DogRun = prepared.initial
  let stopHeartbeat = (): void => { }
  const heartbeat = setInterval(() => {
   if (run.state !== 'running') {
    stopHeartbeat()
    return
   }
   // Touch only updatedAt under the mutation lock: a full-run save here
   // would overwrite host-written bindings (bindAgent) that progress saves
   // carefully merge, and the memory goals never carry them.
   void this.repository.updateRun(runId, current => ({
    ...current,
    updatedAt: this.now().toISOString(),
   })).catch(() => undefined)
  }, this.heartbeatMs)
  stopHeartbeat = () => clearInterval(heartbeat)
  this.runStops.set(runId, stopHeartbeat)

  const appendRuntimeEvent = async (
   goalId: string,
   phase: GoalRuntimePhase,
   details: RuntimeEventDetails = {},
  ): Promise<void> => {
   const event: GoalRuntimeEvent = {
    schemaVersion: '0.1',
    runId,
    goalId,
    phase,
    at: details.at ?? this.now().toISOString(),
    ...(details.state === undefined ? {} : { state: details.state }),
    ...(details.reason === undefined ? {} : { reason: boundedMessage(details.reason) }),
    ...(details.verifier === undefined ? {} : { verifier: details.verifier }),
    ...(details.gmDigest === undefined ? {} : { gmDigest: details.gmDigest }),
    ...(details.attempt === undefined ? {} : { attempt: details.attempt }),
    ...(details.durationMs === undefined ? {} : { durationMs: details.durationMs }),
   }
   try {
    await this.repository.appendRuntimeEvent(event)
   } catch (error) {
    if (run.runtimeWarning === undefined) {
     run = { ...run, runtimeWarning: `runtime context write failed: ${boundedMessage(messageOf(error))}` }
    }
   }
  }
  const saveProgress = async (updatedAt: string): Promise<void> => {
   await this.repository.updateRun(runId, current => ({
    ...current,
    ...(run.runtimeWarning !== undefined ? { runtimeWarning: run.runtimeWarning } : {}),
    goals: this.mergeGoalsKeepingHostSessions(goals, current.goals),
    gmDigests: { ...gmDigests },
    updatedAt,
   }))
  }

  const dependencies = dependenciesBySource(compiled.input)
  const children = childrenByParent(compiled.input)
  const relations = relationsByParent(compiled.input)

  // ---- revalidate_select: partition leaves into re-run and inherited.
  const priorRun = await this.repository.loadLatestSettledRun(compiled.input.id)
  const planFor = (goalId: string): AcceptancePlan | undefined => compiled.acceptancePlans[goalId]
  const inheritedFor = (goalId: string): GoalResult | undefined => {
   if (priorRun === undefined) return undefined
   const plan = planFor(goalId)
   if (plan === undefined) return undefined
   const anchor = anchorOfPlan(plan)
   if (anchor === undefined) return undefined
   const priorDigest = priorRun.gmDigests[goalId]
   if (priorDigest !== anchor) return undefined
   const priorRecord = priorRun.goals[goalId]?.verification
   if (priorRecord === undefined) return undefined
   return { state: 'inherited', inheritedFrom: priorRun.runId, verification: priorRecord }
  }
  const leaves = Object.keys(compiled.input.nodes).filter(id => compiled.input.nodes[id]?.kind === 'leaf')
  for (const goalId of leaves) {
   const plan = planFor(goalId)
   if (plan === undefined) continue
   const anchor = anchorOfPlan(plan)
   if (anchor !== undefined) {
    gmDigests[goalId] = anchor
    const inherited = inheritedFor(goalId)
    if (inherited !== undefined) {
     goals[goalId] = inherited
     await appendRuntimeEvent(goalId, 'result_inherited', {
      state: 'inherited',
      reason: `reused ${inherited.inheritedFrom ?? 'prior run'} verification record`,
     })
     await saveProgress(this.now().toISOString())
    }
   }
  }
  const mergeWholeAssertion = (logical: GoalResult, settled: Settlement): GoalResult => {
   if (settled.state === 'fail') return { state: 'failure', reason: 'whole-object assertion failed' }
   if (settled.state === 'inconclusive') return { state: 'needs_human', reason: 'whole-object assertion inconclusive' }
   return logical
  }
  const evaluateComposite = (goalId: string): GoalResult => {
   const node = compiled.input.nodes[goalId]
   const parentRelations = relations.get(goalId) ?? []
   const childIds = children.get(goalId) ?? []
   const values = relationTruthValues(parentRelations, goals)
   if (node?.completion === undefined) {
    return { state: 'needs_human', reason: 'validated composite lost its completion expression' }
   }
   const requiredFailures = parentRelations.filter(edge => edge.required && relationTruth(edge, goals) === false)
   const fatalRequiredFailure = requiredFailures.find(edge => edge.failure === 'fatal')
   const requiredUnknown = parentRelations.find(edge => edge.required && relationTruth(edge, goals) === undefined)
   if (fatalRequiredFailure !== undefined) {
    return { state: 'failure', reason: `required non-tolerable child ${fatalRequiredFailure.child} failed` }
   }
   if (requiredUnknown !== undefined) {
    return relationNeedsHuman(requiredUnknown, goals)
     ? { state: 'needs_human', reason: `required child relation ${requiredUnknown.child} requires human review` }
     : { state: 'blocked', reason: `required child ${requiredUnknown.child} is unresolved` }
   }
   if (requiredFailures.length > 0) {
    return { state: 'partial', reason: `required child ${requiredFailures[0]?.child ?? 'unknown'} failed under a tolerable policy` }
   }
   const completion = evaluateBoolExpr(node.completion, values)
   if (completion === true) return { state: 'success' }
   if (completion === 'unknown') {
    const humanChild = childIds.find(childId => dependencyNeedsHuman(goals[childId]))
    return humanChild === undefined
     ? { state: 'blocked', reason: 'one or more child outcomes are unresolved' }
     : { state: 'needs_human', reason: `child ${humanChild} requires human review` }
   }
   const failedRelations = parentRelations.filter(edge => relationTruth(edge, goals) === false)
   const fatal = failedRelations.find(edge => edge.failure === 'fatal')
   return fatal === undefined
    ? { state: 'partial', reason: 'completion rule is false, but every failed child relation is tolerable or optional' }
    : { state: 'failure', reason: `non-tolerable child ${fatal.child} failed` }
  }

  const settleLeaf = async (goalId: string): Promise<GoalResult> => {
   const node = compiled.input.nodes[goalId]
   const plan = compiled.acceptancePlans[goalId]
   if (node === undefined || node.kind !== 'leaf') return goals[goalId] ?? { state: 'pending' }
   if (plan === undefined) {
    return { state: 'needs_human', reason: 'compiled acceptance plan is missing' }
   }
   let workspace: IsolatedWorkspace | undefined
   try {
    const startedAt = this.now().toISOString()
    goals[goalId] = { state: 'running' }
    await appendRuntimeEvent(goalId, 'goal_started', { at: startedAt, state: 'running' })
    await saveProgress(startedAt)
    workspace = await this.workspaces.acquire(this.workspaceBaseDirs.get(runId))
    runWorkspaces.add(workspace)
    await appendRuntimeEvent(goalId, 'workspace_allocated', { state: 'running', attempt: 1 })
    const verifier = { mode: plan.verifier.mode }
    await appendRuntimeEvent(goalId, 'verifier_started', { state: 'running', verifier, attempt: 1 })
    const inputPath = await prepareInputPath(plan, workspace, this.repository)
    const settled = await runPlan(
     plan,
     workspace,
     inputPath,
     { parent: options.agent, signal, runId, goalId },
     this.programmatic,
     this.agentic,
    )
    if (signal.aborted) {
     return { state: 'cancelled', reason: 'run cancelled; verifier aborted' }
    }
    const verdict: GoalState = settled.state === 'pass' ? 'success' : settled.state === 'fail' ? 'failure' : 'needs_human'
    const record: VerificationRecord = {
     schemaVersion: '0.1',
     goalId,
     runId,
     graphId: compiled.input.id,
     graphDigest: compiled.graphDigest,
     judgment: plan.judgment,
     ...(plan.gmDigest === undefined ? {} : { gmDigest: plan.gmDigest }),
     passed: settled.state === 'pass' ? true : settled.state === 'fail' ? false : null,
     ...(settled.evidence === undefined ? {} : { evidence: settled.evidence }),
     at: this.now().toISOString(),
    }
    const result: GoalResult = verdict === 'success'
     ? { state: 'success', verification: record }
     : verdict === 'failure'
      ? { state: 'failure', verification: record }
      : { state: 'needs_human', reason: 'verifier was inconclusive; evidence insufficient', verification: record }
    const phase = settled.state === 'pass' ? 'verifier_passed' : settled.state === 'fail' ? 'verifier_failed' : 'verifier_inconclusive'
    await this.repository.appendVerification(record)
    await appendRuntimeEvent(goalId, phase, {
     state: result.state,
     verifier,
     attempt: 1,
     ...(result.state === 'failure' ? { reason: 'trusted verifier rejected the captured input' } : {}),
     ...(result.state === 'needs_human' ? { reason: 'verifier inconclusive' } : {}),
    })
    return result
   } catch (cause) {
    const error: GoalRuntimeError = {
     kind: 'verification_error',
     stage: 'verification',
     message: boundedMessage(messageOf(cause)),
    }
    const failed: GoalResult = { state: 'needs_human', reason: error.message }
    await appendRuntimeEvent(goalId, 'structured_error', { state: 'needs_human', reason: error.kind })
    goals[goalId] = failed
    return failed
   } finally {
    void workspace
   }
  }

  // ---- verify: ready-leaves parallel scheduling, then composite settlement.
  const pendingLeaves = new Set(leaves.filter(id => goals[id]?.state === 'pending'))
  const configuredConcurrency = this.liveConfig?.()?.maxConcurrentVerifications ?? this.config.maxConcurrentVerifications
  const concurrency = Math.max(1, Math.floor(configuredConcurrency))
  const inFlight = new Set<Promise<void>>()
  const inFlightAgentic = new Set<Promise<void>>()
  // Workspaces outlive their verifier: a verifier subagent may still write its
  // settlement after its "turn ended" boundary, so the directory must stay on
  // disk until the whole run has settled. Everything is released at run teardown.
  const runWorkspaces = new Set<IsolatedWorkspace>()
  const drain = async (): Promise<void> => {
   await Promise.allSettled([...inFlight])
   inFlight.clear()
   inFlightAgentic.clear()
  }
  const pump = async (): Promise<void> => {
   // Ready = every dependency target has reached a terminal state. A target
   // that is still running/pending leaves this goal pending — it is re-checked
   // on every pump, so a fast programmatic sibling that settles a moment later
   // releases the waiter instead of latching it into a dead `blocked`.
   for (const goalId of [...pendingLeaves]) {
    const plan = planFor(goalId)
    const waitingOn = (dependencies.get(goalId) ?? []).find(target => !dependencyComplete(goals[target]))
    if (waitingOn !== undefined) continue
    // The concurrency budget bounds model-backed (agentic) verifiers only:
    // programmatic scripts are cheap, deterministic, and must run as soon as
    // their dependencies are satisfied instead of queuing behind agentics.
    const isAgentic = plan?.verifier.mode === 'agentic'
    // Skip (not break) when the agentic budget is full: later pendings may be
    // programmatic or newly-released dependents that must still be examined.
    if (isAgentic && inFlightAgentic.size >= concurrency) continue
    pendingLeaves.delete(goalId)
    const task = settleLeaf(goalId)
     .then(result => {
      goals[goalId] = result
      const settledAt = this.now().toISOString()
      return appendRuntimeEvent(goalId, 'goal_settled', {
       at: settledAt,
       state: result.state,
       ...(result.reason === undefined ? {} : { reason: result.reason }),
       attempt: 1,
      }).then(() => saveProgress(settledAt))
     })
     .finally(() => { inFlight.delete(task); inFlightAgentic.delete(task) })
    inFlight.add(task)
    if (isAgentic) inFlightAgentic.add(task)
   }
  }
  let aborted = false
  signal.addEventListener('abort', () => { aborted = true }, { once: true })
  // Watermark scheduler: fill the agentic budget, then each completion returns
  // to pump() immediately so a free slot is refilled by the next ready leaf.
  // This is true parallelism — never a wave barrier that waits for the whole
  // in-flight batch to settle before starting the next leaves.
  while (!aborted) {
   await pump()
   if (inFlight.size === 0 || pendingLeaves.size === 0) break
   await Promise.race([...inFlight])
  }
  await drain()

  // ---- composites settle once their subtree has settled, and MUTUALLY
  // INDEPENDENT composites run their whole-object assertions concurrently
  // (watermark, same agentic budget as leaves) — never a serial for loop.
  const settleComposite = async (goalId: string): Promise<void> => {
   const startedAt = this.now().toISOString()
   goals[goalId] = { state: 'running' }
   // Persist the running state immediately: the panel reads the persisted
   // run record, so a composite shows running during its whole-object
   // assertion instead of stuck at the initial 'pending'.
   await saveProgress(this.now().toISOString())
   let result: GoalResult = evaluateComposite(goalId)
   const wholePlan = planFor(goalId)
   if (wholePlan !== undefined && result.state !== 'failure') {
    try {
     const workspace = await this.workspaces.acquire(this.workspaceBaseDirs.get(runId))
     runWorkspaces.add(workspace)
     await appendRuntimeEvent(goalId, 'verifier_started', { state: 'running', verifier: { mode: wholePlan.verifier.mode }, attempt: 1 })
     const inputPath = await prepareInputPath(wholePlan, workspace, this.repository)
     const settled = await runPlan(
      wholePlan,
      workspace,
      inputPath,
      { parent: options.agent, signal, runId, goalId },
      this.programmatic,
      this.agentic,
     )
     const phase = settled.state === 'pass' ? 'verifier_passed' : settled.state === 'fail' ? 'verifier_failed' : 'verifier_inconclusive'
     await appendRuntimeEvent(goalId, phase, {
      at: this.now().toISOString(),
      state: settled.state === 'pass' ? 'success' : settled.state === 'fail' ? 'failure' : 'needs_human',
      verifier: { mode: wholePlan.verifier.mode },
     })
     result = mergeWholeAssertion(result, settled)
     const record: VerificationRecord = {
      schemaVersion: '0.1',
      goalId,
      runId,
      graphId: compiled.input.id,
      graphDigest: compiled.graphDigest,
      judgment: wholePlan.judgment,
      ...(wholePlan.gmDigest === undefined ? {} : { gmDigest: wholePlan.gmDigest }),
      passed: settled.state === 'pass' ? true : settled.state === 'fail' ? false : null,
      ...(settled.evidence === undefined ? {} : { evidence: settled.evidence }),
      at: this.now().toISOString(),
     }
     await this.repository.appendVerification(record)
     result = { ...result, verification: record }
    } catch (error) {
     result = { state: 'failure', reason: `whole-object assertion failed: ${boundedMessage(messageOf(error))}` }
    }
   }
   await appendRuntimeEvent(goalId, 'composite_evaluated', {
    state: result.state,
    ...(result.reason === undefined ? {} : { reason: result.reason }),
   })
   await appendRuntimeEvent(goalId, 'goal_settled', {
    at: this.now().toISOString(),
    state: result.state,
    ...(result.reason === undefined ? {} : { reason: result.reason }),
   })
   void startedAt
   goals[goalId] = result
   await saveProgress(this.now().toISOString())
  }
  const compositePending = new Set(
   postorder(compiled.input).filter(id => compiled.input.nodes[id]?.kind === 'composite'),
  )
  const compositeInFlight = new Set<Promise<void>>()
  while (!aborted && (compositePending.size > 0 || compositeInFlight.size > 0)) {
   for (const goalId of [...compositePending]) {
    const unresolvedChild = (children.get(goalId) ?? []).find(id => !dependencyComplete(goals[id]))
    if (unresolvedChild !== undefined) continue
    const blockedDependency = (dependencies.get(goalId) ?? []).find(target => !dependencyComplete(goals[target]))
    if (blockedDependency !== undefined) {
     const state = dependencyNeedsHuman(goals[blockedDependency]) ? 'needs_human' : 'blocked'
     goals[goalId] = { state, reason: `waiting for dependency ${blockedDependency} to complete` }
     compositePending.delete(goalId)
     await saveProgress(this.now().toISOString())
     continue
    }
    const plan = planFor(goalId)
    const isAgentic = plan?.verifier.mode === 'agentic'
    // Composite assertions share the agentic budget with leaves.
    if (isAgentic && inFlightAgentic.size >= concurrency) continue
    compositePending.delete(goalId)
    const task = settleComposite(goalId)
     .then(() => undefined)
     .finally(() => { compositeInFlight.delete(task); if (isAgentic) inFlightAgentic.delete(task) })
    compositeInFlight.add(task)
    if (isAgentic) inFlightAgentic.add(task)
   }
   if (compositeInFlight.size === 0) break
   await Promise.race([...compositeInFlight])
  }
  await Promise.allSettled([...compositeInFlight])

  const rootResult = goals[compiled.input.root]
  const rootState = terminalState(rootResult, this.config.allowPartialRoot)
  const updatedAt = this.now().toISOString()
  // Agentic leaves always re-run by design; count only leaves eligible for
  // inheritance (those with a GM digest) so the warning reflects real drift.
  const inheritableLeaves = leaves.filter(id => planFor(id)?.gmDigest !== undefined)
  const revalidatedCount = inheritableLeaves.filter(id => goals[id]?.state !== 'inherited').length
  const hadAnyInherited = inheritableLeaves.some(id => goals[id]?.state === 'inherited')
  // A fresh or fully re-verified submission is normal; warn only when a partial
  // reuse still re-triggers more than the configured threshold of leaves.
  if (hadAnyInherited && inheritableLeaves.length > 0 && revalidatedCount / inheritableLeaves.length > this.config.revalidateThreshold) {
   run = {
    ...run,
    runtimeWarning: `this submission re-triggers ${revalidatedCount}/${leaves.length} leaves; `
     + 'exceeds revalidateThreshold — confirm unrelated parts were not changed',
   }
  }
  if (signal.aborted) {
   // A cancellation (dog_cancel or host signal) must never be overwritten by
   // the run's own completion record — keep the cancelled state and let the
   // abort reason stand.
   await this.repository.updateRun(runId, current => ({
    ...current,
    state: 'cancelled' as const,
    rootState: 'cancelled' as const,
    goals: current.goals,
    updatedAt,
   }))
  } else {
   await this.repository.updateRun(runId, current => ({
    ...current,
    state: 'completed',
    rootState,
    ...(run.runtimeWarning !== undefined ? { runtimeWarning: run.runtimeWarning } : {}),
    goals: this.mergeGoalsKeepingHostSessions(goals, current.goals),
    gmDigests: { ...gmDigests },
    updatedAt,
   }))
  }
  run = signal.aborted
   ? { ...run, state: 'cancelled', rootState: 'cancelled', updatedAt }
   : { ...run, state: 'completed', rootState, goals: { ...goals }, gmDigests: { ...gmDigests }, updatedAt }
  await this.workspaces.releaseAll([...runWorkspaces])
  stopHeartbeat()
  this.runStops.delete(runId)
  this.runControllers.delete(runId)
  return deepFreeze(run)
 }

 /**
   * Merge in-memory goal progress with host-agent-session bindings recorded
   * concurrently inside an atomic read-modify-write: bindAgent (and future
   * host writers) update the same row under updateRun's serialization, so a
   * progress save can never overwrite a binding it never saw.
  */
 private mergeGoalsKeepingHostSessions(
  target: Record<string, GoalResult>,
  current: Record<string, GoalResult>,
 ): Record<string, GoalResult> {
  const merged: Record<string, GoalResult> = { ...current }
  for (const [goalId, value] of Object.entries(target)) {
   const prior = current[goalId]
   merged[goalId] = prior !== undefined && (prior.agentSessions?.length ?? 0) > 0
    ? { ...value, agentSessions: prior.agentSessions as readonly GoalAgentSessionRef[] }
    : value
  }
  return merged
 }

 /** Mark any prior run of the same graph that never reached a terminal state, so a host restart cannot leave zombies. */
 private async supersedePriorRunningRuns(graphId: string, nextRunId: string): Promise<void> {
  const runs = await this.repository.listRuns()
  for (const prior of runs) {
   if (prior.graphId !== graphId || prior.state !== 'running' || prior.runId === nextRunId) continue
   await this.repository.updateRun(prior.runId, current => ({
    ...current,
    state: 'cancelled',
    rootState: 'cancelled',
    runtimeWarning: `superseded by run ${nextRunId} (host restart or previous run was interrupted)`,
    updatedAt: this.now().toISOString(),
   }))
  }
 }

 async status(runId: string): Promise<DogRun> {
  return this.repository.loadRun(runId)
 }

 async assertAgentCanDelegate(options: DogAgentDelegationOptions): Promise<void> {
  const runId = requireContextId(options.runId, 'runId')
  const goalId = requireContextId(options.goalId, 'goalId')
  const parentSessionId = requireContextId(options.parentSessionId, 'delegating Agent sessionId')
  const run = await this.repository.loadRun(runId)
  if (run.goals[goalId] === undefined) throw new Error(`run ${runId} has no goal ${goalId}`)
  const ownerSessionId = run.invocation?.agentSessionId
  if (ownerSessionId === undefined) throw new Error(`run ${runId} has no trusted invocation Agent session`)
  const knownSessions = new Set<string>([ownerSessionId])
  for (const goal of Object.values(run.goals)) {
   for (const linked of goal.agentSessions ?? []) knownSessions.add(linked.sessionId)
  }
  if (!knownSessions.has(parentSessionId)) {
   throw new Error(`Agent session ${parentSessionId} is not rooted in run ${runId}`)
  }
 }

 async bindAgent(
  options: DogBindAgentOptions,
  policy: { readonly allowUnrooted?: boolean } = {},
 ): Promise<{ readonly run: DogRun; readonly agent: GoalAgentSessionRef }> {
  const runId = requireContextId(options.runId, 'runId')
  const goalId = requireContextId(options.goalId, 'goalId')
  const sessionId = requireContextId(options.sessionId, 'agent sessionId')
  const parentSessionId = options.parentSessionId === undefined
   ? undefined
   : requireContextId(options.parentSessionId, 'agent parentSessionId')
  if (!GOAL_AGENT_ROLES.has(options.role)) throw new Error(`unsupported goal Agent role ${String(options.role)}`)
  const boundAt = this.now().toISOString()
  let agent: GoalAgentSessionRef | undefined
  const run = await this.repository.updateRun(runId, current => {
   const result = current.goals[goalId]
   if (result === undefined) throw new Error(`run ${runId} has no goal ${goalId}`)
   const ownerSessionId = current.invocation?.agentSessionId
   if (ownerSessionId === undefined) throw new Error(`run ${runId} has no trusted invocation Agent session`)
   const knownSessions = new Set<string>([ownerSessionId])
   for (const goal of Object.values(current.goals)) {
    for (const linked of goal.agentSessions ?? []) knownSessions.add(linked.sessionId)
   }
   if (sessionId !== ownerSessionId && (parentSessionId === undefined || !knownSessions.has(parentSessionId))) {
    if (policy.allowUnrooted === true && parentSessionId === undefined) {
     // Recovery/background verifier spawns lose the original parent session identity;
     // the engine itself spawned this verifier, so registration is still trustworthy.
    } else {
     throw new Error(`Agent session ${sessionId} is not rooted in run ${runId}`)
    }
   }
   agent = {
    sessionId,
    ...(parentSessionId === undefined ? {} : { parentSessionId }),
    role: options.role,
    boundAt,
   }
   const agentSessions = [...(result.agentSessions ?? []).filter(linked => linked.sessionId !== sessionId), agent]
   return {
    ...current,
    goals: { ...current.goals, [goalId]: { ...result, agentSessions } },
    updatedAt: boundAt,
   }
  })
  if (agent === undefined) throw new Error(`run ${runId} Agent binding did not commit`)
  return { run, agent }
 }

 private parse(value: unknown): DogGraphInput {
  return parseGraph(value, {
   maxGraphNodes: this.config.maxGraphNodes,
   maxExpressionNodes: this.config.maxExpressionNodes,
   maxExpressionDepth: this.config.maxExpressionDepth,
  })
 }

 private validateWorkspaceRefs(graph: DogGraphInput): void {
  for (const [goalId, node] of Object.entries(graph.nodes)) {
   if (node.verifier === undefined) {
    if (node.kind === 'leaf') throw new Error(`goal ${goalId} is a leaf but declares no verifier`)
    continue
   }
   requireTarget(node.target, goalId)
   if (node.verifier.mode === 'programmatic' && node.verifier.script.length === 0) {
    throw new Error(`goal ${goalId} programmatic verifier requires a script`)
   }
   if (node.verifier.mode === 'agentic' && node.verifier.instruction.length === 0) {
    throw new Error(`goal ${goalId} agentic verifier requires an instruction`)
   }
  }
 }
}

/** SPEC §4 programmatic-subtree rule: every composite must have at least one non-programmatic descendant. */
function validateHostConfig(config: DogConfig): void {
 if (config.maxGraphNodes < 1 || !Number.isInteger(config.maxGraphNodes)) throw new Error('maxGraphNodes must be a positive integer')
 if (config.maxExpressionNodes < 1 || !Number.isInteger(config.maxExpressionNodes)) throw new Error('maxExpressionNodes must be a positive integer')
 if (config.maxExpressionDepth < 1 || !Number.isInteger(config.maxExpressionDepth)) throw new Error('maxExpressionDepth must be a positive integer')
 if (config.maxSandboxBytes < 1 || !Number.isInteger(config.maxSandboxBytes)) throw new Error('maxSandboxBytes must be a positive integer')
 if (config.maxConcurrentVerifications < 1 || !Number.isInteger(config.maxConcurrentVerifications)) {
  throw new Error('maxConcurrentVerifications must be a positive integer')
 }
 if (config.revalidateThreshold < 0 || config.revalidateThreshold > 1 || !Number.isFinite(config.revalidateThreshold)) {
  throw new Error('revalidateThreshold must be a ratio in [0, 1]')
 }
 if (config.gmDigestAlgo.length === 0) throw new Error('gmDigestAlgo must not be empty')
 if (config.storageDirectory.length === 0 || isAbsolute(config.storageDirectory) || hasTraversal(config.storageDirectory)) {
  throw new Error('storageDirectory must be a non-empty relative path without traversal')
 }
 if (!isAbsolute(config.workspaceRoot)) throw new Error(`workspaceRoot must be absolute`)
}

function requireContextId(value: string, label: string): string {
 if (value.length === 0 || value.length > 512) throw new Error(`${label} must contain 1-512 characters`)
 return value
}

function requireTarget(target: string, goalId: string): string {
 if (typeof target !== 'string' || target.length === 0) {
  throw new Error(`goal ${goalId} must declare a target`)
 }
 if (isAbsolute(target)) throw new Error(`goal ${goalId} target must be workspace-relative (absolute given)`)
 return target
}

function computeJudgment(verifier: { mode: 'programmatic'; script: string } | { mode: 'agentic'; instruction: string }, scriptsDirectory: string): AcceptancePlan['judgment'] {
 if (verifier.mode === 'programmatic') {
  const scriptPath = resolveScriptPath(scriptsDirectory, verifier.script)
  const scriptDigest = readScriptDigest(scriptPath)
  return { mode: 'programmatic', script: verifier.script, scriptDigest }
 }
 return { mode: 'agentic', instructionHash: `sha256:${sha256Json({ instruction: verifier.instruction })}` }
}

/** Inheritance anchor: the captured object plus the judgment identity. */
function anchorOfPlan(plan: AcceptancePlan): string | undefined {
 if (plan.input === undefined || !plan.input.exists) return undefined
 return sha256Json({ object: plan.input.digest, judgment: plan.judgment })
}

export function resolveScriptPath(scriptsDirectory: string, script: string): string {
 const direct = join(scriptsDirectory, script)
 if (existsSync(direct)) return direct
 if (!script.endsWith('.js')) {
  const withJs = `${direct}.js`
  if (existsSync(withJs)) return withJs
 }
 throw new Error(`programmatic script not found in library: ${direct}`)
}

function readScriptDigest(scriptPath: string): string {
 try {
  return `sha256:${createHash('sha256').update(readFileSync(scriptPath)).digest('hex')}`
 } catch {
  throw new Error(`programmatic script not found in library: ${scriptPath}`)
 }
}

async function prepareInputPath(plan: AcceptancePlan, workspace: IsolatedWorkspace, repository: DogRepository): Promise<string> {
 if (plan.input === undefined) return workspace.path
 return repository.copyCapturedInput(plan.input, workspace.path)
}

function graphWarnings(graph: DogGraphInput): string[] {
 const warnings: string[] = []
 for (const [goalId, node] of Object.entries(graph.nodes)) {
  if (goalId === graph.root) continue
  if (node.constraint === 'soft') warnings.push(`goal ${goalId} is soft; v0.2 records this but has no soft-score model`)
 }
 return warnings
}

function messageOf(error: unknown): string {
 return error instanceof Error ? error.message : String(error)
}

function boundedMessage(message: string): string {
 return message.length > 512 ? message.slice(0, 512) : message
}

function postorder(input: DogGraphInput): string[] {
 const children = new Map<string, string[]>()
 for (const edge of input.contains) {
  const list = children.get(edge.parent) ?? []
  list.push(edge.child)
  children.set(edge.parent, list)
 }
 const visited = new Set<string>()
 const order: string[] = []
 const visit = (id: string): void => {
  if (visited.has(id)) return
  visited.add(id)
  for (const child of children.get(id) ?? []) visit(child)
  order.push(id)
 }
 visit(input.root)
 return order
}

function dependenciesBySource(input: DogGraphInput): Map<string, string[]> {
 const map = new Map<string, string[]>()
 for (const edge of input.dependsOn) {
  const list = map.get(edge.source) ?? []
  list.push(edge.target)
  map.set(edge.source, list)
 }
 return map
}

function childrenByParent(input: DogGraphInput): Map<string, string[]> {
 const map = new Map<string, string[]>()
 for (const edge of input.contains) {
  const list = map.get(edge.parent) ?? []
  list.push(edge.child)
  map.set(edge.parent, list)
 }
 return map
}

function relationsByParent(input: DogGraphInput): Map<string, ContainsEdge[]> {
 const map = new Map<string, ContainsEdge[]>()
 for (const edge of input.contains) {
  const list = map.get(edge.parent) ?? []
  list.push(edge)
  map.set(edge.parent, list)
 }
 return map
}

function relationTruth(edge: { readonly child: string; readonly failure?: string; readonly degradeTo?: string }, goals: Record<string, GoalResult>): boolean | undefined {
 const state = goals[edge.child]?.state
 const inheritedVerification = state === 'inherited' ? goals[edge.child]?.verification?.passed : undefined
 if (state === 'success' || state === 'inherited' && inheritedVerification === true || state === 'partial') return true
 if (state === 'failure' || state === 'blocked' || state === 'inherited' && inheritedVerification === false) {
  if (edge.failure === 'degrade' && edge.degradeTo !== undefined) {
   const substitute = goals[edge.degradeTo]?.state
   if (substitute === 'success') return true
   if (substitute === 'inherited') {
    const substitutePassed = goals[edge.degradeTo]?.verification?.passed
    if (substitutePassed === true) return true
    if (substitutePassed === null || substitutePassed === undefined) return undefined
   }
   if (substitute === 'needs_human' || substitute === 'invalidated') return undefined
  }
  return false
 }
 return undefined
}

function relationTruthValues(edges: readonly { readonly child: string; readonly failure?: string; readonly degradeTo?: string }[], goals: Record<string, GoalResult>): Map<string, boolean | undefined> {
 const values = new Map<string, boolean | undefined>()
 for (const edge of edges) values.set(edge.child, relationTruth(edge, goals))
 return values
}

function relationNeedsHuman(edge: { readonly child: string; readonly failure?: string; readonly degradeTo?: string }, goals: Record<string, GoalResult>): boolean {
 const childState = goals[edge.child]?.state
 if (childState === 'needs_human' || childState === 'invalidated') return true
 if (childState === 'inherited' && goals[edge.child]?.verification?.passed === null) return true
 if (edge.failure === 'degrade' && edge.degradeTo !== undefined) {
  const substitute = goals[edge.degradeTo]?.state
  return substitute === 'needs_human' || substitute === 'invalidated'
   || substitute === 'inherited' && goals[edge.degradeTo]?.verification?.passed === null
 }
 return false
}

function dependencyNeedsHuman(result: GoalResult | undefined): boolean {
 return result?.state === 'needs_human' || result?.state === 'invalidated'
  || result?.state === 'inherited' && result.verification?.passed === null
}

/**
 * A dependency is satisfied for scheduling once its target has reached a
 * terminal state — success, failure, needs_human, cancelled, invalidated,
 * partial, or an inherited verdict. This is a *completion* gate, not a
 * success gate: the waiter is released to run its own judgment even when the
 * dependency failed (its verdict is independent evidence).
 */
function dependencyComplete(result: GoalResult | undefined): boolean {
 const state = result?.state
 if (state === 'success' || state === 'failure' || state === 'needs_human'
  || state === 'cancelled' || state === 'invalidated' || state === 'partial'
  || state === 'inherited') return true
 return false
}

function terminalState(rootResult: GoalResult | undefined, allowPartialRoot: boolean): RootTerminalState {
 if (rootResult?.state === 'success' || rootResult?.state === 'inherited') return 'success'
 if (rootResult?.state === 'partial' && allowPartialRoot) return 'partial_success'
 if (rootResult?.state === 'needs_human') return 'needs_replan'
 return 'failure'
}

function deepFreeze<T>(value: T): T {
 if (value === null || typeof value !== 'object') return value
 Object.freeze(value)
 for (const item of Object.values(value)) deepFreeze(item)
 return value
}

function hasTraversal(value: string): boolean {
 return value.split(/[\\/]/u).some(segment => segment === '..' || segment === '.')
}
