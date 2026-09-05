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

const TERMINAL_STATUSES: ReadonlySet<string> = new Set([
  'completed', 'failed', 'cancelled', 'interrupted',
])

/**
 * Task type → the view resource that consumes its terminal artifact.
 * `tasks` itself is not listed: any task-list signature change bumps it
 * unconditionally in the store; these are the *extra* typed bumps.
 */
const TERMINAL_RESOURCE_BY_TYPE: Readonly<Record<string, ResourceKey>> = {
  research: 'research',
  model_benchmark: 'benchmark',
  chapter_review: 'dag',
  chapter_write: 'dag',
  revision_selection: 'dag',
  revision_from_review: 'dag',
  manuscript_import: 'manuscript',
  project_restore: 'workspace',
}

interface TaskStatusType {
  status: string
  type: string
}

/** task_id → (status, type) from a `{data: {tasks: [...]}}` payload; malformed input yields an empty map. */
function taskStatusTypeMap(payload: unknown): Map<string, TaskStatusType> {
  const map = new Map<string, TaskStatusType>()
  if (payload === null || typeof payload !== 'object' || Array.isArray(payload)) return map
  const data = (payload as Record<string, unknown>)['data']
  if (data === null || typeof data !== 'object' || Array.isArray(data)) return map
  const tasks = (data as Record<string, unknown>)['tasks']
  if (!Array.isArray(tasks)) return map
  for (const raw of tasks) {
    if (raw === null || typeof raw !== 'object' || Array.isArray(raw)) continue
    const task = raw as Record<string, unknown>
    const id = task['task_id']
    const status = task['status']
    const type = task['type']
    if (typeof id !== 'string' || id === '') continue
    if (typeof status !== 'string' || typeof type !== 'string') continue
    map.set(id, { status, type })
  }
  return map
}

/**
 * Typed terminal diff between two task-list payloads: the resources whose
 * views must remount because a task they display NEWLY reached a terminal
 * status. A task absent from the previous payload is not a transition (we
 * never observed it running — initial loads and window re-entries stay
 * quiet). Malformed payloads yield [], never throw.
 */
export function terminalTransitionResources(previousTasksJson: unknown, nextTasksJson: unknown): ResourceKey[] {
  try {
    const before = taskStatusTypeMap(previousTasksJson)
    const after = taskStatusTypeMap(nextTasksJson)
    const resources = new Set<ResourceKey>()
    for (const [id, next] of after) {
      const previous = before.get(id)
      if (previous === undefined) continue
      if (TERMINAL_STATUSES.has(previous.status) || !TERMINAL_STATUSES.has(next.status)) continue
      const resource = TERMINAL_RESOURCE_BY_TYPE[next.type]
      if (resource !== undefined) resources.add(resource)
    }
    return [...resources]
  } catch {
    return []
  }
}
