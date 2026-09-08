/** Runtime validation for trusted debugger RPC responses. */

import { parseGraph } from '../graph.ts'
import { isJsonValue } from '../model.ts'
import type {
  AcceptancePlan,
  DogRun,
  GoalAgentRole,
  GoalAgentSessionRef,
  GoalResult,
  GoalRuntimeEvent,
  GoalRuntimeTrace,
  GoalState,
  JsonValue,
  RootTerminalState,
  RunInvocationContext,
  CapturedInput,
  VerificationRecord,
} from '../model.ts'
import type { DogDebugGraphRevision, DogDebugSnapshot } from '../debug-contract.ts'

const DIGEST = /^[a-f0-9]{64}$/u
const GOAL_STATES = new Set<GoalState>([
  'pending', 'running', 'success', 'failure', 'blocked', 'needs_human',
  'cancelled', 'invalidated', 'partial', 'inherited',
])
const ROOT_STATES = new Set<RootTerminalState>([
  'success', 'partial_success', 'failure', 'infeasible', 'needs_replan', 'cancelled',
])
const GOAL_AGENT_ROLES = new Set<GoalAgentRole>(['orchestrator', 'verifier', 'reviewer'])
const RUNTIME_PHASES = new Set<GoalRuntimeEvent['phase']>([
  'goal_started', 'dependency_blocked', 'grounding_extracted', 'workspace_allocated',
  'verifier_started', 'verifier_released', 'verifier_passed', 'verifier_failed', 'verifier_inconclusive',
  'composite_evaluated', 'result_inherited', 'structured_error', 'goal_settled', 'run_warning',
])

/** Parse JSON from the debugger endpoint before it reaches render code. */
export function parseDogDebugSnapshot(value: unknown): DogDebugSnapshot {
  const root = requireRecord(value, '$')
  if (root.schemaVersion !== '0.1') throw new Error('debug snapshot schemaVersion must be 0.1')
  const graphs = requireArray(root.graphs, '$.graphs').map((item, index) => parseRevision(item, `$.graphs[${index}]`))
  return {
    schemaVersion: '0.1',
    generatedAt: requireString(root.generatedAt, '$.generatedAt'),
    graphs,
  }
}

/** Parse one lazy per-goal runtime trace before it reaches render code. */
export function parseGoalRuntimeTrace(value: unknown): GoalRuntimeTrace {
  const root = requireRecord(value, '$')
  if (root.schemaVersion !== '0.1') throw new Error('runtime trace schemaVersion must be 0.1')
  const runId = requireBoundedString(root.runId, '$.runId')
  const graphDigest = requireDigest(root.graphDigest, '$.graphDigest')
  const goalId = requireBoundedString(root.goalId, '$.goalId')
  const runState = parseRunState(root.runState, '$.runState')
  const result = parseGoalResult(root.result, '$.result')
  const rootState = root.rootState === undefined ? undefined : parseRootState(root.rootState, '$.rootState')
  const invocation = root.invocation === undefined ? undefined : parseInvocation(root.invocation, '$.invocation')
  const events = requireArray(root.events, '$.events').map((item, index) => (
    parseRuntimeEvent(item, `$.events[${index}]`, { runId, goalId })
  ))
  if (typeof root.truncated !== 'boolean') throw new Error('$.truncated must be a boolean')
  const runtimeWarning = root.runtimeWarning === undefined
    ? undefined
    : requireBoundedString(root.runtimeWarning, '$.runtimeWarning')
  return {
    schemaVersion: '0.1',
    runId,
    graphId: requireBoundedString(root.graphId, '$.graphId'),
    graphDigest,
    runState,
    ...(rootState === undefined ? {} : { rootState }),
    goalId,
    result,
    ...(invocation === undefined ? {} : { invocation }),
    ...(runtimeWarning === undefined ? {} : { runtimeWarning }),
    events,
    truncated: root.truncated,
  }
}

function parseRuntimeEvent(
  value: unknown,
  path: string,
  expected: { readonly runId: string; readonly goalId: string },
): GoalRuntimeEvent {
  const root = requireRecord(value, path)
  if (root.schemaVersion !== '0.1') throw new Error(`${path}.schemaVersion must be 0.1`)
  const runId = requireBoundedString(root.runId, `${path}.runId`)
  const goalId = requireBoundedString(root.goalId, `${path}.goalId`)
  if (runId !== expected.runId || goalId !== expected.goalId) {
    throw new Error(`${path} does not belong to the requested goal trace`)
  }
  const phase = requireString(root.phase, `${path}.phase`)
  if (!RUNTIME_PHASES.has(phase as GoalRuntimeEvent['phase'])) throw new Error(`${path}.phase is invalid`)
  const state = root.state === undefined ? undefined : parseGoalState(root.state, `${path}.state`)
  const reason = root.reason === undefined ? undefined : requireBoundedString(root.reason, `${path}.reason`)
  const durationMs = root.durationMs === undefined
    ? undefined
    : requireNonNegativeInteger(root.durationMs, `${path}.durationMs`)
  const attempt = root.attempt === undefined
    ? undefined
    : requireNonNegativeInteger(root.attempt, `${path}.attempt`)
  const gmDigest = root.gmDigest === undefined ? undefined : requireString(root.gmDigest, `${path}.gmDigest`)
  const verifierRecord = root.verifier === undefined ? undefined : requireRecord(root.verifier, `${path}.verifier`)
  const verifier = verifierRecord === undefined ? undefined : {
    mode: requireEnumValue(verifierRecord.mode, ['programmatic', 'agentic'], `${path}.verifier.mode`),
  }
  return {
    schemaVersion: '0.1',
    runId,
    goalId,
    phase: phase as GoalRuntimeEvent['phase'],
    at: requireString(root.at, `${path}.at`),
    ...(state === undefined ? {} : { state }),
    ...(reason === undefined ? {} : { reason }),
    ...(verifier === undefined ? {} : { verifier }),
    ...(gmDigest === undefined ? {} : { gmDigest }),
    ...(attempt === undefined ? {} : { attempt }),
    ...(durationMs === undefined ? {} : { durationMs }),
  }
}

function parseRevision(value: unknown, path: string): DogDebugGraphRevision {
  const root = requireRecord(value, path)
  const graphRecord = requireRecord(root.graph, `${path}.graph`)
  const graphDigest = requireDigest(graphRecord.graphDigest, `${path}.graph.graphDigest`)
  const input = parseGraph(graphRecord.input, {
    maxGraphNodes: 4096,
    maxExpressionNodes: 8192,
    maxExpressionDepth: 256,
  })
  const acceptancePlans = parseAcceptancePlans(graphRecord.acceptancePlans, `${path}.graph.acceptancePlans`)
  const runs = requireArray(root.runs, `${path}.runs`).map((item, index) => {
    const run = parseRun(item, `${path}.runs[${index}]`)
    if (run.graphDigest !== graphDigest) throw new Error(`${path}.runs[${index}]: graph digest mismatch`)
    return run
  })
  if (typeof root.current !== 'boolean') throw new Error(`${path}.current must be a boolean`)
  return {
    graph: { input, graphDigest, acceptancePlans },
    current: root.current,
    runs,
  }
}

function parseAcceptancePlans(value: unknown, path: string): Record<string, AcceptancePlan> {
  const root = requireRecord(value, path)
  const result: Record<string, AcceptancePlan> = {}
  for (const [key, item] of Object.entries(root)) {
    const plan = parseAcceptancePlan(item, `${path}.${key}`)
    if (plan.goalId !== key) throw new Error(`${path}.${key}: goalId mismatch`)
    result[key] = plan
  }
  return result
}

function parseAcceptancePlan(value: unknown, path: string): AcceptancePlan {
  const root = requireRecord(value, path)
  const input = root.input === undefined ? undefined : parseCapturedInput(root.input, `${path}.input`)
  const verifier = parseVerifierShape(root.verifier ?? root.v09Verifier, `${path}.verifier`)
  const judgment = parseJudgment(root.judgment, `${path}.judgment`)
  return {
    goalId: requireString(root.goalId, `${path}.goalId`),
    verifier,
    judgment,
    target: requireString(root.target, `${path}.target`),
    ...(input === undefined ? {} : { input }),
    ...(root.gmDigest === undefined ? {} : { gmDigest: requireString(root.gmDigest, `${path}.gmDigest`) }),
  }
}

function parseVerifierShape(value: unknown, path: string): AcceptancePlan['verifier'] {
  const record = requireRecord(value, path)
  const mode = requireString(record.mode, `${path}.mode`)
  if (mode === 'programmatic') {
    return { mode: 'programmatic', script: requireString(record.script, `${path}.script`) }
  }
  if (mode === 'agentic') {
    return { mode: 'agentic', instruction: requireString(record.instruction, `${path}.instruction`) }
  }
  throw new Error(`${path}.mode is invalid`)
}

function parseJudgment(value: unknown, path: string): AcceptancePlan['judgment'] {
  const record = requireRecord(value, path)
  const mode = requireString(record.mode, `${path}.mode`)
  if (mode === 'programmatic') {
    return { mode: 'programmatic', script: requireString(record.script, `${path}.script`), scriptDigest: requireString(record.scriptDigest, `${path}.scriptDigest`) }
  }
  return { mode: 'agentic', instructionHash: requireString(record.instructionHash, `${path}.instructionHash`) }
}

function parseCapturedInput(value: unknown, path: string): CapturedInput {
  const root = requireRecord(value, path)
  const exists = root.exists
  const byteLength = root.byteLength
  if (typeof exists !== 'boolean') throw new Error(`${path}.exists must be a boolean`)
  if (typeof byteLength !== 'number' || !Number.isSafeInteger(byteLength) || byteLength < 0) {
    throw new Error(`${path}.byteLength must be a non-negative safe integer`)
  }
  return {
    path: requireBoundedString(root.path, `${path}.path`),
    digest: requireString(root.digest, `${path}.digest`),
    exists,
    byteLength,
    sha256: requireString(root.sha256, `${path}.sha256`),
  }
}

function parseRun(value: unknown, path: string): DogRun {
  const root = requireRecord(value, path)
  const state = parseRunState(root.state, `${path}.state`)
  const goalsRecord = requireRecord(root.goals, `${path}.goals`)
  const goals: Record<string, GoalResult> = {}
  for (const [id, result] of Object.entries(goalsRecord)) goals[id] = parseGoalResult(result, `${path}.goals.${id}`)
  const rootState = root.rootState === undefined ? undefined : parseRootState(root.rootState, `${path}.rootState`)
  const invocation = root.invocation === undefined ? undefined : parseInvocation(root.invocation, `${path}.invocation`)
  const runtimeWarning = root.runtimeWarning === undefined
    ? undefined
    : requireBoundedString(root.runtimeWarning, `${path}.runtimeWarning`)
  const gmDigestsRecord = root.gmDigests === undefined ? {} : requireRecord(root.gmDigests, `${path}.gmDigests`)
  const gmDigests: Record<string, string> = {}
  for (const [id, digest] of Object.entries(gmDigestsRecord)) gmDigests[id] = requireString(digest, `${path}.gmDigests.${id}`)
  return {
    runId: requireString(root.runId, `${path}.runId`),
    graphId: requireString(root.graphId, `${path}.graphId`),
    graphDigest: requireDigest(root.graphDigest, `${path}.graphDigest`),
    state,
    ...(rootState === undefined ? {} : { rootState }),
    gmDigests,
    goals,
    ...(invocation === undefined ? {} : { invocation }),
    ...(runtimeWarning === undefined ? {} : { runtimeWarning }),
    createdAt: requireString(root.createdAt, `${path}.createdAt`),
    updatedAt: requireString(root.updatedAt, `${path}.updatedAt`),
  }
}

function parseInvocation(value: unknown, path: string): RunInvocationContext {
  const root = requireRecord(value, path)
  const agentSessionId = root.agentSessionId === undefined
    ? undefined
    : requireBoundedString(root.agentSessionId, `${path}.agentSessionId`)
  const parentSessionId = root.parentSessionId === undefined
    ? undefined
    : requireBoundedString(root.parentSessionId, `${path}.parentSessionId`)
  if (parentSessionId !== undefined && agentSessionId === undefined) {
    throw new Error(`${path}.parentSessionId requires agentSessionId`)
  }
  return {
    callId: requireBoundedString(root.callId, `${path}.callId`),
    ...(agentSessionId === undefined ? {} : { agentSessionId }),
    ...(parentSessionId === undefined ? {} : { parentSessionId }),
    invokedAt: requireString(root.invokedAt, `${path}.invokedAt`),
  }
}

function parseGoalResult(value: unknown, path: string): GoalResult {
  const root = requireRecord(value, path)
  const state = parseGoalState(root.state, `${path}.state`)
  const reason = root.reason === undefined ? undefined : requireString(root.reason, `${path}.reason`)
  const verification = root.verification === undefined
    ? undefined
    : parseVerification(root.verification, `${path}.verification`)
  const agentSessions = root.agentSessions === undefined
    ? undefined
    : requireArray(root.agentSessions, `${path}.agentSessions`).map((agent, index) => (
      parseGoalAgentSession(agent, `${path}.agentSessions[${index}]`)
    ))
  const inheritedFrom = root.inheritedFrom === undefined
    ? undefined
    : requireString(root.inheritedFrom, `${path}.inheritedFrom`)
  return {
    state,
    ...(reason === undefined ? {} : { reason }),
    ...(verification === undefined ? {} : { verification }),
    ...(inheritedFrom === undefined ? {} : { inheritedFrom }),
    ...(agentSessions === undefined ? {} : { agentSessions }),
  }
}

function parseGoalAgentSession(value: unknown, path: string): GoalAgentSessionRef {
  const root = requireRecord(value, path)
  const role = requireBoundedString(root.role, `${path}.role`) as GoalAgentRole
  if (!GOAL_AGENT_ROLES.has(role)) throw new Error(`${path}.role is invalid`)
  const parentSessionId = root.parentSessionId === undefined
    ? undefined
    : requireBoundedString(root.parentSessionId, `${path}.parentSessionId`)
  return {
    sessionId: requireBoundedString(root.sessionId, `${path}.sessionId`),
    ...(parentSessionId === undefined ? {} : { parentSessionId }),
    role,
    boundAt: requireBoundedString(root.boundAt, `${path}.boundAt`),
  }
}

function parseVerification(value: unknown, path: string): VerificationRecord {
  const root = requireRecord(value, path)
  if (root.passed !== null && typeof root.passed !== 'boolean') throw new Error(`${path}.passed must be a boolean or null`)
  return {
    schemaVersion: '0.1' as const,
    goalId: requireString(root.goalId, `${path}.goalId`),
    runId: requireString(root.runId, `${path}.runId`),
    graphId: requireString(root.graphId, `${path}.graphId`),
    graphDigest: requireDigest(root.graphDigest, `${path}.graphDigest`),
    judgment: parseJudgment(root.judgment, `${path}.judgment`),
    ...(root.gmDigest === undefined ? {} : { gmDigest: requireString(root.gmDigest, `${path}.gmDigest`) }),
    passed: root.passed === null ? null : root.passed,
    ...(root.evidence === undefined ? {} : { evidence: requireJson(root.evidence, `${path}.evidence`) }),
    at: requireString(root.at, `${path}.at`),
  }
}

function requireEnumValue(value: unknown, allowed: readonly string[], path: string): 'programmatic' | 'agentic' {
  const candidate = requireString(value, path)
  if (!allowed.includes(candidate)) throw new Error(`${path} is invalid`)
  return candidate as 'programmatic' | 'agentic'
}

function requireJson(value: unknown, path: string): JsonValue {
  if (!isJsonValue(value)) throw new Error(`${path} must be JSON-compatible`)
  return value
}

function parseGoalState(value: unknown, path: string): GoalState {
  if (typeof value !== 'string' || !GOAL_STATES.has(value as GoalState)) throw new Error(`${path} is invalid`)
  return value as GoalState
}

function parseRootState(value: unknown, path: string): RootTerminalState {
  if (typeof value !== 'string' || !ROOT_STATES.has(value as RootTerminalState)) throw new Error(`${path} is invalid`)
  return value as RootTerminalState
}

function parseRunState(value: unknown, path: string): DogRun['state'] {
  if (value !== 'running' && value !== 'completed' && value !== 'cancelled' && value !== 'failed') {
    throw new Error(`${path} is invalid`)
  }
  return value
}

function requireDigest(value: unknown, path: string): string {
  const text = requireString(value, path)
  if (!DIGEST.test(text)) throw new Error(`${path} must be a SHA-256 digest`)
  return text
}

function requireRecord(value: unknown, path: string): Record<string, unknown> {
  if (value === null || typeof value !== 'object' || Array.isArray(value)) throw new Error(`${path} must be an object`)
  return Object.fromEntries(Object.entries(value))
}

function requireArray(value: unknown, path: string): readonly unknown[] {
  if (!Array.isArray(value)) throw new Error(`${path} must be an array`)
  return value
}

function requireString(value: unknown, path: string): string {
  if (typeof value !== 'string') throw new Error(`${path} must be a string`)
  return value
}

function requireBoundedString(value: unknown, path: string): string {
  const text = requireString(value, path)
  if (text.length === 0 || text.length > 512) throw new Error(`${path} must contain 1-512 characters`)
  return text
}

function requireNonNegativeInteger(value: unknown, path: string): number {
  if (typeof value !== 'number' || !Number.isSafeInteger(value) || value < 0) {
    throw new Error(`${path} must be a non-negative safe integer`)
  }
  return value
}
