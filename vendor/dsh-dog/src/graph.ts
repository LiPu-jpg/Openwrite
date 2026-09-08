/** Graph parser, structural validator, and cycle checker for DoG v0.2. */

import { parseBoolExpr } from './logic.ts'
import type {
  ContainsEdge,
  DependencyEdge,
  DogGraphInput,
  GoalId,
  GoalNodeInput,
  GraphLimits,
} from './model.ts'
import { DOG_SCHEMA_VERSION } from './model.ts'

const ID_PATTERN = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/u

/** Structured validation failure at the model-to-core boundary. */
export class DogValidationError extends Error {
  readonly errors: readonly string[]

  constructor(errors: readonly string[]) {
    super(`invalid DoG graph: ${errors.join('; ')}`)
    this.name = 'DogValidationError'
    this.errors = errors
  }
}

/** Parse an untrusted graph value into a normalized, acyclic DoG graph. */
export function parseGraph(value: unknown, limits: GraphLimits): DogGraphInput {
  const errors: string[] = []
  const root = asRecord(value, '$', errors)
  if (root === undefined) throw new DogValidationError(errors)
  checkExactKeys(root, ['schemaVersion', 'id', 'root', 'nodes', 'contains', 'dependsOn'], '$', errors)
  if (root.schemaVersion !== DOG_SCHEMA_VERSION) errors.push(`$.schemaVersion: expected ${DOG_SCHEMA_VERSION}`)
  const graphId = parseId(root.id, '$.id', errors)
  const rootId = parseId(root.root, '$.root', errors)
  const nodes = parseNodes(root.nodes, limits, errors)
  const contains = parseContains(root.contains, errors)
  const dependsOn = parseDependencies(root.dependsOn, errors)
  if (graphId === undefined || rootId === undefined || nodes === undefined || contains === undefined || dependsOn === undefined) {
    throw new DogValidationError(errors)
  }
  validateGraphReferences(rootId, nodes, contains, dependsOn, limits, errors)
  validateAcyclic(nodes, contains, dependsOn, errors)
  if (errors.length > 0) throw new DogValidationError(errors)
  return {
    schemaVersion: DOG_SCHEMA_VERSION,
    id: graphId,
    root: rootId,
    nodes,
    contains,
    dependsOn,
  }
}

function parseNodes(
  value: unknown,
  limits: GraphLimits,
  errors: string[],
): Record<GoalId, GoalNodeInput> | undefined {
  const record = asRecord(value, '$.nodes', errors)
  if (record === undefined) return undefined
  const ids = Object.keys(record)
  if (ids.length === 0) errors.push('$.nodes: must not be empty')
  if (ids.length > limits.maxGraphNodes) errors.push(`$.nodes: exceeds ${limits.maxGraphNodes} nodes`)
  const nodes: Record<string, GoalNodeInput> = {}
  for (const id of ids) {
    if (!ID_PATTERN.test(id)) errors.push(`$.nodes.${id}: invalid goal ID`)
    const node = asRecord(record[id], `$.nodes.${id}`, errors)
    if (node === undefined) continue
    checkExactKeys(node, ['kind', 'title', 'constraint', 'target', 'completion', 'verifier'], `$.nodes.${id}`, errors)
    const kind = parseEnum(node.kind, ['leaf', 'composite'] as const, `$.nodes.${id}.kind`, errors)
    const title = parseNonEmptyString(node.title, `$.nodes.${id}.title`, errors)
    const constraint = parseEnum(node.constraint, ['hard', 'soft'] as const, `$.nodes.${id}.constraint`, errors)
    const target = parseNonEmptyString(node.target, `$.nodes.${id}.target`, errors)
    const verifier = parseVerifier(node.verifier, `$.nodes.${id}.verifier`, errors)
    if (kind === undefined || title === undefined || constraint === undefined || target === undefined) continue
    if (kind === 'leaf' && verifier === undefined) errors.push(`$.nodes.${id}: leaf requires verifier`)
    if (kind === 'composite' && verifier !== undefined) {
      // Optional whole-object assertion: allowed and runs after the subtree settles.
    }
    if (kind === 'composite' && node.completion === undefined) errors.push(`$.nodes.${id}: composite requires completion`)
    if (kind === 'leaf' && node.completion !== undefined) errors.push(`$.nodes.${id}: leaf cannot declare completion`)
    const nodeValue = {
      kind,
      title,
      constraint,
      target,
      ...(verifier === undefined ? {} : { verifier }),
      ...(kind === 'composite' && node.completion !== undefined ? { completion: node.completion } : {}),
    } as unknown as GoalNodeInput
    nodes[id] = nodeValue
  }
  return nodes
}

function parseContains(value: unknown, errors: string[]): ContainsEdge[] | undefined {
  if (!Array.isArray(value)) {
    errors.push('$.contains: must be an array')
    return undefined
  }
  const edges: ContainsEdge[] = []
  for (const [index, candidate] of value.entries()) {
    const path = `$.contains[${index}]`
    const record = asRecord(candidate, path, errors)
    if (record === undefined) continue
    checkExactKeys(record, ['parent', 'child', 'required', 'failure', 'degradeTo'], path, errors)
    const parent = parseId(record.parent, `${path}.parent`, errors)
    const child = parseId(record.child, `${path}.child`, errors)
    const required = parseBoolean(record.required, `${path}.required`, errors)
    const failure = parseEnum(record.failure, ['fatal', 'tolerable', 'degrade'] as const, `${path}.failure`, errors)
    const degradeTo = record.degradeTo === undefined ? undefined : parseId(record.degradeTo, `${path}.degradeTo`, errors)
    if (failure !== 'degrade' && degradeTo !== undefined) errors.push(`${path}.degradeTo: only valid with failure=degrade`)
    if (failure === 'degrade' && degradeTo === undefined) errors.push(`${path}: failure=degrade requires degradeTo`)
    if (parent !== undefined && child !== undefined && required !== undefined && failure !== undefined) {
      edges.push({ parent, child, required, failure, ...(degradeTo === undefined ? {} : { degradeTo }) })
    }
  }
  return edges
}

function parseDependencies(value: unknown, errors: string[]): DependencyEdge[] | undefined {
  if (!Array.isArray(value)) {
    errors.push('$.dependsOn: must be an array')
    return undefined
  }
  const edges: DependencyEdge[] = []
  for (const [index, candidate] of value.entries()) {
    const path = `$.dependsOn[${index}]`
    const record = asRecord(candidate, path, errors)
    if (record === undefined) continue
    checkExactKeys(record, ['source', 'target', 'data'], path, errors)
    const source = parseId(record.source, `${path}.source`, errors)
    const target = parseId(record.target, `${path}.target`, errors)
    const data = parseStringArray(record.data, `${path}.data`, errors)
    if (source !== undefined && target !== undefined) edges.push({ source, target, ...(data === undefined ? {} : { data }) })
  }
  return edges
}

function parseVerifier(value: unknown, path: string, errors: string[]): GoalNodeInput['verifier'] | undefined {
  if (value === undefined) return undefined
  const record = asRecord(value, path, errors)
  if (record === undefined) return undefined
  const mode = parseEnum(record.mode, ['programmatic', 'agentic'] as const, `${path}.mode`, errors)
  if (mode === undefined) return undefined
  if (mode === 'programmatic') {
    checkExactKeys(record, ['mode', 'script'], path, errors)
    const script = parseNonEmptyString(record.script, `${path}.script`, errors)
    return script === undefined ? undefined : { mode: 'programmatic', script }
  }
  checkExactKeys(record, ['mode', 'instruction'], path, errors)
  const instruction = parseNonEmptyString(record.instruction, `${path}.instruction`, errors)
  return instruction === undefined ? undefined : { mode: 'agentic', instruction }
}

function validateGraphReferences(
  root: GoalId,
  nodes: Record<GoalId, GoalNodeInput>,
  contains: readonly ContainsEdge[],
  dependsOn: readonly DependencyEdge[],
  limits: GraphLimits,
  errors: string[],
): void {
  if (!Object.prototype.hasOwnProperty.call(nodes, root)) errors.push(`$.root: unknown node ${root}`)
  const rootNode = nodes[root]
  if (rootNode !== undefined && rootNode.constraint !== 'hard') errors.push('$.root: root goal must be a hard constraint')
  const children = new Map<string, string[]>()
  const edgeKeys = new Set<string>()
  for (const edge of contains) {
    const key = `${edge.parent}\u0000${edge.child}`
    if (edgeKeys.has(key)) errors.push(`$.contains: duplicate edge ${edge.parent}->${edge.child}`)
    edgeKeys.add(key)
    if (!Object.prototype.hasOwnProperty.call(nodes, edge.parent)) errors.push(`$.contains: unknown parent ${edge.parent}`)
    if (!Object.prototype.hasOwnProperty.call(nodes, edge.child)) errors.push(`$.contains: unknown child ${edge.child}`)
    const parent = nodes[edge.parent]
    if (parent !== undefined && parent.kind !== 'composite') errors.push(`$.contains: ${edge.parent} is not composite`)
    const siblings = children.get(edge.parent) ?? []
    siblings.push(edge.child)
    children.set(edge.parent, siblings)
  }
  for (const edge of contains) {
    if (edge.degradeTo === edge.child) errors.push(`$.contains: degradeTo cannot equal child ${edge.child}`)
    else if (edge.degradeTo !== undefined && !(children.get(edge.parent) ?? []).includes(edge.degradeTo)) {
      errors.push(`$.contains: degradeTo ${edge.degradeTo} is not a child of ${edge.parent}`)
    }
  }
  const dependencyKeys = new Set<string>()
  for (const edge of dependsOn) {
    const key = `${edge.source}\u0000${edge.target}`
    if (dependencyKeys.has(key)) errors.push(`$.dependsOn: duplicate edge ${edge.source}->${edge.target}`)
    dependencyKeys.add(key)
    if (edge.source === edge.target) errors.push(`$.dependsOn: self-dependency ${edge.source}`)
    if (!Object.prototype.hasOwnProperty.call(nodes, edge.source)) errors.push(`$.dependsOn: unknown source ${edge.source}`)
    if (!Object.prototype.hasOwnProperty.call(nodes, edge.target)) errors.push(`$.dependsOn: unknown target ${edge.target}`)
  }
  for (const [parent, node] of Object.entries(nodes)) {
    if (node.kind !== 'composite') continue
    const childIds = children.get(parent) ?? []
    if (childIds.length === 0) errors.push(`$.nodes.${parent}: composite requires at least one child`)
    if (node.completion === undefined) {
      errors.push(`$.nodes.${parent}.completion: missing completion expression`)
      continue
    }
    const parsed = parseBoolExpr(node.completion, new Set(childIds), {
      maxNodes: limits.maxExpressionNodes,
      maxDepth: limits.maxExpressionDepth,
    })
    if (parsed.errors.length > 0) errors.push(...parsed.errors.map(error => `$.nodes.${parent}.completion${error.slice(1)}`))
    else if (parsed.expression !== undefined) nodes[parent] = { ...node, completion: parsed.expression }
  }
  const reachable = new Set<string>()
  const queue = [root]
  while (queue.length > 0) {
    const current = queue.shift()
    if (current === undefined || reachable.has(current)) continue
    reachable.add(current)
    for (const child of children.get(current) ?? []) queue.push(child)
  }
  for (const id of Object.keys(nodes)) if (!reachable.has(id)) errors.push(`$.nodes.${id}: unreachable from root through containment`)
}

function validateAcyclic(
  nodes: Record<GoalId, GoalNodeInput>,
  contains: readonly ContainsEdge[],
  dependsOn: readonly DependencyEdge[],
  errors: string[],
): void {
  const outgoing = new Map<string, string[]>()
  for (const id of Object.keys(nodes)) outgoing.set(id, [])
  for (const edge of contains) outgoing.get(edge.parent)?.push(edge.child)
  for (const edge of dependsOn) outgoing.get(edge.source)?.push(edge.target)
  const visiting = new Set<string>()
  const visited = new Set<string>()
  function visit(id: string, path: string[]): void {
    if (visiting.has(id)) {
      errors.push(`graph contains a cycle: ${[...path, id].join(' -> ')}`)
      return
    }
    if (visited.has(id)) return
    visiting.add(id)
    for (const target of outgoing.get(id) ?? []) visit(target, [...path, id])
    visiting.delete(id)
    visited.add(id)
  }
  for (const id of Object.keys(nodes)) visit(id, [])
}

function asRecord(value: unknown, path: string, errors: string[]): Record<string, unknown> | undefined {
  if (value === null || typeof value !== 'object' || Array.isArray(value)) {
    errors.push(`${path}: must be an object`)
    return undefined
  }
  return value as Record<string, unknown>
}

function checkExactKeys(value: Record<string, unknown>, allowed: readonly string[], path: string, errors: string[]): void {
  const allowedSet = new Set(allowed)
  for (const key of Object.keys(value)) if (!allowedSet.has(key)) errors.push(`${path}: unknown field ${key}`)
}

function parseId(value: unknown, path: string, errors: string[]): string | undefined {
  if (typeof value !== 'string' || !ID_PATTERN.test(value)) {
    errors.push(`${path}: must be an ASCII ID matching ${ID_PATTERN.source}`)
    return undefined
  }
  return value
}

function parseNonEmptyString(value: unknown, path: string, errors: string[]): string | undefined {
  if (typeof value !== 'string' || value.trim().length === 0) {
    errors.push(`${path}: must be a non-empty string`)
    return undefined
  }
  return value
}

function parseBoolean(value: unknown, path: string, errors: string[]): boolean | undefined {
  if (typeof value !== 'boolean') {
    errors.push(`${path}: must be boolean`)
    return undefined
  }
  return value
}

function parseEnum<T extends string>(value: unknown, allowed: readonly T[], path: string, errors: string[]): T | undefined {
  if (typeof value !== 'string' || !allowed.includes(value as T)) {
    errors.push(`${path}: expected one of ${allowed.join(', ')}`)
    return undefined
  }
  return value as T
}

function parseStringArray(value: unknown, path: string, errors: string[]): string[] | undefined {
  if (value === undefined) return undefined
  if (!Array.isArray(value) || value.some(item => typeof item !== 'string')) {
    errors.push(`${path}: must be an array of strings`)
    return undefined
  }
  return [...value]
}
