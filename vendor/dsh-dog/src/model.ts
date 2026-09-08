/** Core JSON-compatible types for the DoG v0.9 protocol. */

export const DOG_SCHEMA_VERSION = '0.9' as const

export type JsonPrimitive = string | number | boolean | null
export type JsonValue = JsonPrimitive | JsonValue[] | { [key: string]: JsonValue }

export type GoalId = string
export type ConstraintKind = 'hard' | 'soft'
export type GoalKind = 'leaf' | 'composite'
export type FailurePolicy = 'fatal' | 'tolerable' | 'degrade'
export type GoalState =
  | 'pending'
  | 'running'
  | 'success'
  | 'failure'
  | 'blocked'
  | 'needs_human'
  | 'cancelled'
  | 'invalidated'
  | 'partial'
  | 'inherited'

export interface RefExpr {
  readonly op: 'ref'
  readonly id: GoalId
}

export interface AllExpr {
  readonly op: 'all'
  readonly items: readonly BoolExpr[]
}

export interface AnyExpr {
  readonly op: 'any'
  readonly items: readonly BoolExpr[]
}

export interface NotExpr {
  readonly op: 'not'
  readonly item: BoolExpr
}

export interface AtLeastExpr {
  readonly op: 'atLeast'
  readonly count: number
  readonly items: readonly BoolExpr[]
}

export type BoolExpr = RefExpr | AllExpr | AnyExpr | NotExpr | AtLeastExpr

/** One of exactly two judgment kernels: a script, or a natural-language instruction. */
export type VerifierShape =
  | { readonly mode: 'programmatic'; readonly script: string }
  | { readonly mode: 'agentic'; readonly instruction: string }

export interface GoalNodeInput {
  readonly kind: GoalKind
  readonly title: string
  readonly constraint: ConstraintKind
  /** Single file path or a directory/collection (engine packs it into .tar). */
  readonly target: string
  /** Leaf: required. Composite: optional whole-object assertion (runs after subtree settles). */
  readonly verifier?: VerifierShape
  /** Composite only: boolean combination of children. */
  readonly completion?: BoolExpr
}

export interface ContainsEdge {
  readonly parent: GoalId
  readonly child: GoalId
  readonly required: boolean
  readonly failure: FailurePolicy
  readonly degradeTo?: GoalId
}

export interface DependencyEdge {
  readonly source: GoalId
  readonly target: GoalId
  readonly data?: readonly string[]
}

export interface DogGraphInput {
  readonly schemaVersion: typeof DOG_SCHEMA_VERSION
  readonly id: string
  readonly root: GoalId
  readonly nodes: Record<GoalId, GoalNodeInput>
  readonly contains: readonly ContainsEdge[]
  readonly dependsOn: readonly DependencyEdge[]
}

export interface DogConfig {
  readonly storageDirectory: string
  /** Sandbox/root for captured inputs: verifiers' objects come from this tree. */
  readonly workspaceRoot: string
  /** Host-registered script library directory (programmatic kernels). */
  readonly scriptsDirectory: string
  readonly maxGraphNodes: number
  readonly maxExpressionNodes: number
  readonly maxExpressionDepth: number
  readonly maxSandboxBytes: number
  readonly allowPartialRoot: boolean
  readonly maxConcurrentVerifications: number
  readonly revalidateThreshold: number
  readonly gmDigestAlgo: string
}

export interface GraphLimits {
  readonly maxGraphNodes: number
  readonly maxExpressionNodes: number
  readonly maxExpressionDepth: number
}

/** One captured object (file, or packed .tar for a collection). */
export interface CapturedInput {
  readonly path: string
  readonly digest: string
  readonly exists: boolean
  readonly byteLength: number
  readonly sha256: string
  /** True when the capture is a .tar of a directory/collection. */
  readonly packed?: boolean
}

/** Deterministic or agentic: judgment identity double-anchors incremental reuse. */
export type JudgmentIdentity =
  | { readonly mode: 'programmatic'; readonly script: string; readonly scriptDigest: string }
  | { readonly mode: 'agentic'; readonly instructionHash: string }

export interface AcceptancePlan {
  readonly goalId: GoalId
  /** Which kernel judges this goal. */
  readonly verifier: VerifierShape
  /** Identity of the judgment source; part of the inheritance anchor. */
  readonly judgment: JudgmentIdentity
  readonly target: string
  /** Captured object metadata (absent when target is missing/empty). */
  readonly input?: CapturedInput
  readonly gmDigest?: string
}

export interface VerificationRecord {
  readonly schemaVersion: '0.1'
  readonly runId: string
  readonly graphId: string
  readonly graphDigest: string
  readonly goalId: GoalId
  readonly judgment: JudgmentIdentity
  readonly gmDigest?: string
  readonly passed: boolean | null
  readonly evidence?: JsonValue
  readonly at: string
}

export interface GoalRuntimeVerifier {
  readonly mode: 'programmatic' | 'agentic'
}

export interface GoalRuntimeError {
  readonly kind: 'acceptance_plan_missing' | 'completion_expression_missing' | 'verification_error' | 'agentic_unavailable'
  readonly stage: 'scheduling' | 'verification' | 'composition'
  readonly message: string
}

export type GoalRuntimePhase =
  | 'goal_started'
  | 'dependency_blocked'
  | 'grounding_extracted'
  | 'workspace_allocated'
  | 'verifier_started'
  | 'verifier_passed'
  | 'verifier_failed'
  | 'verifier_inconclusive'
  | 'composite_evaluated'
  | 'result_inherited'
  | 'verifier_released'
  | 'verifier_bind_failed'
  | 'structured_error'
  | 'goal_settled'
  | 'run_warning'

export interface GoalRuntimeEvent {
  readonly schemaVersion: '0.1'
  readonly runId: string
  readonly goalId: GoalId
  readonly phase: GoalRuntimePhase
  readonly state?: GoalState
  readonly at: string
  readonly reason?: string
  readonly verifier?: GoalRuntimeVerifier
  readonly gmDigest?: string
  readonly attempt?: number
  readonly durationMs?: number
}

export type GoalAgentRole = 'orchestrator' | 'verifier' | 'reviewer'

export interface GoalAgentSessionRef {
  readonly sessionId: string
  readonly parentSessionId?: string
  readonly role: GoalAgentRole
  readonly boundAt: string
}

export interface RunInvocationContext {
  readonly callId: string
  readonly agentSessionId?: string
  readonly parentSessionId?: string
  readonly invokedAt: string
}

export interface GoalResult {
  readonly state: GoalState
  readonly reason?: string
  readonly verification?: VerificationRecord
  readonly inheritedFrom?: string
  readonly agentSessions?: readonly GoalAgentSessionRef[]
}

export type RootTerminalState =
  | 'success'
  | 'partial_success'
  | 'failure'
  | 'infeasible'
  | 'needs_replan'
  | 'cancelled'

export interface CompiledGraph {
  readonly input: DogGraphInput
  readonly graphDigest: string
  readonly acceptancePlans: Readonly<Record<GoalId, AcceptancePlan>>
}

export interface DogRun {
  readonly runId: string
  readonly graphId: string
  readonly graphDigest: string
  /** Calling session's cwd; verifier workspaces are allocated under it. */
  readonly workspaceBaseDir?: string
  readonly state: 'running' | 'completed' | 'cancelled' | 'failed'
  readonly rootState?: RootTerminalState
  readonly invocation?: RunInvocationContext
  readonly runtimeWarning?: string
  readonly gmDigests: Readonly<Record<GoalId, string>>
  readonly goals: Readonly<Record<GoalId, GoalResult>>
  readonly createdAt: string
  readonly updatedAt: string
}

export interface GoalRuntimeTrace {
  readonly schemaVersion: '0.1'
  readonly runId: string
  readonly graphId: string
  readonly graphDigest: string
  readonly runState: DogRun['state']
  readonly rootState?: RootTerminalState
  readonly goalId: GoalId
  readonly result: GoalResult
  readonly invocation?: RunInvocationContext
  readonly runtimeWarning?: string
  readonly events: readonly GoalRuntimeEvent[]
  readonly truncated: boolean
}

export interface GraphValidationReport {
  readonly valid: boolean
  readonly errors: readonly string[]
  readonly warnings: readonly string[]
}

export interface CiGoalReport {
  readonly goalId: GoalId
  readonly state: GoalState
  readonly verifier?: GoalRuntimeVerifier
  readonly evidence?: readonly Record<string, JsonValue>[]
  readonly defect?: string
  readonly settledAt?: string
}

export interface CiReport {
  readonly runId: string
  readonly graphId: string
  readonly graphDigest?: string
  readonly rootState: RootTerminalState | 'running' | 'cancelled'
  readonly goals: readonly CiGoalReport[]
  readonly revalidated?: readonly GoalId[]
  readonly inherited?: readonly { goalId: GoalId; fromRunId: string; state: 'inherited' }[]
  readonly warning?: string
  readonly generatedAt: string
}

export function isJsonValue(value: unknown): value is JsonValue {
  if (value === null || typeof value === 'string' || typeof value === 'boolean') return true
  if (typeof value === 'number') return Number.isFinite(value)
  if (Array.isArray(value)) return value.every(isJsonValue)
  if (typeof value !== 'object') return false
  return Object.values(value).every(isJsonValue)
}
