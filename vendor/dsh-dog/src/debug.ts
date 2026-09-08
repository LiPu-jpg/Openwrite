/** Read-only debugger snapshots and lazy runtime context over DSH Connection RPC. */

import type { ConnectionRpcHandler } from '@deepseek-ai/dsh-client-connection'
import type { CompiledGraph, GoalRuntimeTrace } from './model.ts'
import type { DogRepository } from './storage.ts'

export * from './debug-contract.ts'
import { DOG_DEBUG_SNAPSHOT_ENDPOINT, DOG_RUNTIME_TRACE_ENDPOINT } from './debug-contract.ts'
import type { DogDebugGraphRevision, DogDebugSnapshot } from './debug-contract.ts'
const MAX_RUNTIME_EVENTS_PER_GOAL = 64

/** Build a digest-safe view: an old run is never shown against a newer graph revision. */
export async function buildDogDebugSnapshot(
  repository: DogRepository,
  now: () => Date = () => new Date(),
): Promise<DogDebugSnapshot> {
  const [allGraphs, runs] = await Promise.all([repository.listGraphs(), repository.listRuns()])
  // 0.9 re-shaped the judgment layer; pre-0.9 graphs no longer parse under the
  // 0.9 schema and would poison the whole panel snapshot. Keep them on disk as
  // history (runs unchanged) but never surface them as current revisions.
  const graphs = allGraphs.filter(graph => graph.input.schemaVersion === '0.9')
  const graphIds = [...new Set(graphs.map(graph => graph.input.id))]
  const settled = await Promise.allSettled(graphIds.map(id => repository.loadGraph(id)))
  const currentDigests = new Set(settled
    .filter((result): result is PromiseFulfilledResult<CompiledGraph> => result.status === 'fulfilled')
    .map(result => result.value.graphDigest))
  const revisions = graphs.map(graph => ({
    graph,
    current: currentDigests.has(graph.graphDigest),
    runs: runs.filter(run => run.graphDigest === graph.graphDigest),
  })).sort(compareRevisions)
  return {
    schemaVersion: '0.1',
    generatedAt: now().toISOString(),
    graphs: revisions,
  }
}

/** Build one bounded node trace without loading any DSH transcript or artifact bytes. */
export async function buildGoalRuntimeTrace(
  repository: DogRepository,
  runId: string,
  goalId: string,
): Promise<GoalRuntimeTrace> {
  const run = await repository.loadRun(runId)
  const result = run.goals[goalId]
  if (result === undefined) throw new Error(`run ${runId} has no goal ${goalId}`)
  const matching = [...await repository.loadGoalRuntimeEvents(runId, goalId)]
  const truncated = matching.length > MAX_RUNTIME_EVENTS_PER_GOAL
  return {
    schemaVersion: '0.1',
    runId: run.runId,
    graphId: run.graphId,
    graphDigest: run.graphDigest,
    runState: run.state,
    ...(run.rootState === undefined ? {} : { rootState: run.rootState }),
    goalId,
    result,
    ...(run.invocation === undefined ? {} : { invocation: run.invocation }),
    ...(run.runtimeWarning === undefined ? {} : { runtimeWarning: boundedMessage(run.runtimeWarning) }),
    events: truncated ? matching.slice(-MAX_RUNTIME_EVENTS_PER_GOAL) : matching,
    truncated,
  }
}

/** Register this handler on the trusted-host Connection channel, never as an unauthenticated raw HTTP route. */
export function createDogDebugRpcHandler(repository: DogRepository): ConnectionRpcHandler {
  return async (endpoint, payload, signal) => {
    try {
      signal.throwIfAborted()
      if (endpoint === DOG_DEBUG_SNAPSHOT_ENDPOINT) {
        requireEmptyPayload(payload)
        return { ok: true, value: await buildDogDebugSnapshot(repository) }
      }
      if (endpoint === DOG_RUNTIME_TRACE_ENDPOINT) {
        const request = parseGoalRuntimeRequest(payload)
        return { ok: true, value: await buildGoalRuntimeTrace(repository, request.runId, request.goalId) }
      }
      return internalError(`unknown DoG debugger endpoint ${endpoint}`)
    } catch (error) {
      if (signal.aborted) {
        return { ok: false, error: { code: 'cancelled', message: 'DoG debugger request cancelled', details: {} } }
      }
      return internalError(messageOf(error))
    }
  }
}

function compareRevisions(left: DogDebugGraphRevision, right: DogDebugGraphRevision): number {
  if (left.current !== right.current) return left.current ? -1 : 1
  const leftUpdated = left.runs[0]?.updatedAt ?? ''
  const rightUpdated = right.runs[0]?.updatedAt ?? ''
  const byActivity = rightUpdated.localeCompare(leftUpdated)
  if (byActivity !== 0) return byActivity
  const byId = left.graph.input.id.localeCompare(right.graph.input.id)
  return byId === 0 ? left.graph.graphDigest.localeCompare(right.graph.graphDigest) : byId
}

function requireEmptyPayload(value: unknown): void {
  if (value === null || typeof value !== 'object' || Array.isArray(value) || Object.keys(value).length !== 0) {
    throw new Error('DoG snapshot request payload must be an empty object')
  }
}

function parseGoalRuntimeRequest(value: unknown): { readonly runId: string; readonly goalId: string } {
  if (value === null || typeof value !== 'object' || Array.isArray(value)) {
    throw new Error('DoG runtime request payload must be an object')
  }
  const record = Object.fromEntries(Object.entries(value))
  if (Object.keys(record).length !== 2) throw new Error('DoG runtime request requires exactly runId and goalId')
  return {
    runId: requireBoundedId(record.runId, 'runId'),
    goalId: requireBoundedId(record.goalId, 'goalId'),
  }
}

function requireBoundedId(value: unknown, label: string): string {
  if (typeof value !== 'string' || value.length === 0 || value.length > 512) {
    throw new Error(`${label} must contain 1-512 characters`)
  }
  return value
}

function internalError(message: string) {
  return {
    ok: false as const,
    error: { code: 'internal' as const, message: boundedMessage(message), details: {} },
  }
}

function boundedMessage(value: string): string {
  const normalized = value.length === 0 ? 'DoG debugger request failed' : value
  return normalized.length <= 512 ? normalized : `${normalized.slice(0, 509)}...`
}

function messageOf(error: unknown): string {
  return error instanceof Error ? error.message : String(error)
}
