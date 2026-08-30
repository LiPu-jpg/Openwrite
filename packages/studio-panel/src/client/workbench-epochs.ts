/**
 * Pure epoch-invalidation logic shared by the WorkbenchStore. Extracted so it
 * can be unit-tested with Node's type-stripping runner without React/DOM.
 */

export type ResourceKey =
  | 'workspace' | 'manuscript' | 'outline' | 'assets' | 'tasks'
  | 'benchmark' | 'models' | 'dag' | 'graph' | 'research' | 'revisions'

export type Epochs = Readonly<Record<ResourceKey, number>>

/** Resources whose mutations also bump `graph`: the relationship graph reads
 * continuity data that spans assets/manuscript/outline/workspace. */
const GRAPH_DERIVED_FROM: ReadonlySet<ResourceKey> = new Set([
  'assets', 'manuscript', 'outline', 'workspace',
])

/** Resources whose mutation triggers a workspace/tasks refresh. */
const REFRESH_ON: ReadonlySet<ResourceKey> = new Set([
  'workspace', 'manuscript', 'outline', 'tasks',
])

export function nextEpochs(resource: ResourceKey, epochs: Epochs): Epochs {
  const derived = GRAPH_DERIVED_FROM.has(resource)
    ? { graph: epochs.graph + 1 }
    : null
  return {
    ...epochs,
    [resource]: epochs[resource] + 1,
    ...derived,
  }
}

export function triggersRefresh(resource: ResourceKey): boolean {
  return REFRESH_ON.has(resource)
}
