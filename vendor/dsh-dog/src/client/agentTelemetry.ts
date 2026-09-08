import type { SessionId } from '@deepseek-ai/dsh-session'
/** Live DSH session telemetry projected onto persisted DoG Agent bindings. */

import type { SessionListState, SessionSummary } from '@deepseek-ai/dsh-api-session-controller/client'
import type { DogDebugSnapshot } from '../debug-contract.ts'
import type { DogRun, GoalAgentSessionRef, GoalState } from '../model.ts'

export interface GoalAgentTelemetry {
  readonly ref: GoalAgentSessionRef
  readonly label: string
  readonly available: boolean
  readonly running: boolean
  readonly needsInput: boolean
  readonly tokens?: number
  readonly durationMs?: number
}

export interface RunAgentSummary {
  readonly linked: number
  readonly visible: number
  readonly running: number
  readonly tokens?: number
  readonly partialTokens: boolean
}

/** Stable, de-duplicated bindings for one goal. */
export function goalAgentRefs(run: DogRun | undefined, goalId: string): readonly GoalAgentSessionRef[] {
  if (run === undefined) return []
  const seen = new Set<string>()
  const result: GoalAgentSessionRef[] = []
  for (const ref of run.goals[goalId]?.agentSessions ?? []) {
    if (seen.has(ref.sessionId)) continue
    seen.add(ref.sessionId)
    result.push(ref)
  }
  return result
}

/** Stable, de-duplicated Agent bindings across a run. */
export function runAgentRefs(run: DogRun | undefined): readonly GoalAgentSessionRef[] {
  if (run === undefined) return []
  const seen = new Set<string>()
  const result: GoalAgentSessionRef[] = []
  for (const goal of Object.values(run.goals)) {
    for (const ref of goal.agentSessions ?? []) {
      if (seen.has(ref.sessionId)) continue
      seen.add(ref.sessionId)
      result.push(ref)
    }
  }
  return result
}

/** Direct parent catalogs that can resolve bound subagent sessions in the host UI. */
export function agentParentSessionIds(snapshot: DogDebugSnapshot): readonly string[] {
  const parents = new Set<string>()
  for (const revision of snapshot.graphs) {
    for (const run of revision.runs) {
      for (const ref of runAgentRefs(run)) {
        if (ref.parentSessionId !== undefined) parents.add(ref.parentSessionId)
      }
    }
  }
  return [...parents]
}

/** Merge one persisted binding with the newest host-projected session facts. */
export function goalAgentTelemetry(
  ref: GoalAgentSessionRef,
  sessions: SessionListState & { pendingInteractions?: ReadonlyMap<string, unknown> },
  now = Date.now(),
): GoalAgentTelemetry {
  const summary = sessions.byId[ref.sessionId as SessionId]
  const tokens = summary === undefined ? undefined : sessionTokenTotal(summary)
  const durationMs = summary === undefined ? undefined : sessionDuration(summary, now)
  return {
    ref,
    label: summary?.displayTitle ?? summary?.title ?? `${capitalize(ref.role)} Agent`,
    available: summary !== undefined,
    running: summary?.running ?? false,
    needsInput: sessions.pendingInteractions?.has(ref.sessionId) ?? false,
    ...(tokens === undefined ? {} : { tokens }),
    ...(durationMs === undefined ? {} : { durationMs }),
  }
}

/** DoG-level Agent counts and de-duplicated token usage. */
export function summarizeRunAgents(
  run: DogRun | undefined,
  sessions: SessionListState & { pendingInteractions?: ReadonlyMap<string, unknown> },
  now = Date.now(),
): RunAgentSummary {
  const refs = runAgentRefs(run)
  let visible = 0
  let running = 0
  let tokens = 0
  let measured = 0
  for (const ref of refs) {
    const telemetry = goalAgentTelemetry(ref, sessions, now)
    if (telemetry.available) visible += 1
    if (telemetry.running) running += 1
    if (telemetry.tokens !== undefined) {
      tokens += telemetry.tokens
      measured += 1
    }
  }
  return {
    linked: refs.length,
    visible,
    running,
    ...(measured === 0 ? {} : { tokens }),
    partialTokens: measured > 0 && measured < refs.length,
  }
}

/** Count goals that reached any terminal state, independently of success. */
export function settledGoalCount(run: DogRun | undefined): number {
  if (run === undefined) return 0
  return Object.values(run.goals).filter(result => isTerminalGoalState(result.state)).length
}

function isTerminalGoalState(state: GoalState): boolean {
  return state !== 'pending' && state !== 'running'
}

function sessionTokenTotal(summary: SessionSummary): number | undefined {
  const projections = summary.projectionValues as Readonly<Record<string, unknown>> | undefined
  const usage = projections?.tokenUsage
  if (!isRecord(usage)) return undefined
  const uncached = finiteNonNegative(usage.uncachedInputTokens)
  const output = finiteNonNegative(usage.outputTokens)
  const cacheRead = finiteNonNegative(usage.cacheReadTokens)
  const cacheWrite = finiteNonNegative(usage.cacheWriteTokens)
  if (uncached === undefined || output === undefined || cacheRead === undefined || cacheWrite === undefined) return undefined
  return uncached + output + cacheRead + cacheWrite
}

function sessionDuration(summary: SessionSummary, now: number): number | undefined {
  const projections = summary.projectionValues as Readonly<Record<string, unknown>> | undefined
  const timing = projections?.subagentTiming
  if (!isRecord(timing)) return undefined
  const settledMs = finiteNonNegative(timing.settledMs)
  if (settledMs === undefined) return undefined
  if (!isRecord(timing.active)) return settledMs
  const since = finiteNumber(timing.active.since)
  const through = finiteNumber(timing.active.through)
  if (since === undefined || through === undefined) return settledMs
  const end = summary.running ? now : through
  return settledMs + Math.max(0, end - since)
}

function finiteNonNegative(value: unknown): number | undefined {
  const number = finiteNumber(value)
  return number === undefined || number < 0 ? undefined : number
}

function finiteNumber(value: unknown): number | undefined {
  return typeof value === 'number' && Number.isFinite(value) ? value : undefined
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
}

function capitalize(value: string): string {
  return value.length === 0 ? value : `${value[0]?.toUpperCase() ?? ''}${value.slice(1)}`
}
