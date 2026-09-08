/** Shared browser-safe debugger protocol. */
import type { CompiledGraph, DogRun } from './model.ts'

export const DOG_DEBUG_RPC_CHANNEL = '/dog-rpc'
export const DOG_DEBUG_SNAPSHOT_ENDPOINT = 'snapshot'
export const DOG_RUNTIME_TRACE_ENDPOINT = 'goal-runtime'

/** One immutable graph revision and every run bound to that exact digest. */
export interface DogDebugGraphRevision {
  readonly graph: CompiledGraph
  readonly current: boolean
  readonly runs: readonly DogRun[]
}

/** Complete, point-in-time view exposed to the debugger. */
export interface DogDebugSnapshot {
  readonly schemaVersion: '0.1'
  readonly generatedAt: string
  readonly graphs: readonly DogDebugGraphRevision[]
}

