/** Shared browser-safe debugger protocol. */
import type { CompiledGraph, DogRun } from './model.ts'

/**
 * Dedicated debugger channel. It is served by this plugin directly on the Web
 * carrier (see serveDogDebugRpc): Connection's generic channel registry mounts
 * its HTTP route through the Connection plugin's own context, which only sees
 * `webServer` when a bundle patch injects it into the shared connection row —
 * and per-key patch semantics make any such patch clobber other bundles
 * (OpenWrite issue #81), while the shared `/api` channel already belongs to
 * the host's Typert gateway. The wire envelope mirrors Connection's, so the
 * browser side keeps using its stock `connection.rpc.call`.
 */
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

