/** Restricted, non-interpreted Boolean expressions for DoG completion rules. */

import type { AllExpr, AnyExpr, AtLeastExpr, BoolExpr, NotExpr, RefExpr } from './model.ts'

export type TruthValue = true | false | 'unknown'

export interface ExpressionLimits {
  readonly maxNodes: number
  readonly maxDepth: number
}

export interface ParsedExpression {
  readonly expression?: BoolExpr
  readonly errors: readonly string[]
}

/**
 * Parse and type-check the only expression language accepted by DoG.
 * @param value - untrusted JSON value from a graph draft.
 * @param allowedRefs - child IDs that the enclosing composite may reference.
 * @param limits - expression size limits.
 * @returns a typed AST or validation errors; never evaluates source text.
 */
export function parseBoolExpr(
  value: unknown,
  allowedRefs: ReadonlySet<string>,
  limits: ExpressionLimits,
): ParsedExpression {
  const errors: string[] = []
  let nodeCount = 0

  function visit(candidate: unknown, depth: number, path: string): BoolExpr | undefined {
    if (depth > limits.maxDepth) {
      errors.push(`${path}: expression depth exceeds ${limits.maxDepth}`)
      return undefined
    }
    if (!isRecord(candidate)) {
      errors.push(`${path}: expression must be an object`)
      return undefined
    }
    nodeCount += 1
    if (nodeCount > limits.maxNodes) {
      errors.push(`expression exceeds ${limits.maxNodes} nodes`)
      return undefined
    }
    const keys = Object.keys(candidate)
    if (!Object.prototype.hasOwnProperty.call(candidate, 'op') || keys.length === 0) {
      errors.push(`${path}: expression requires exactly one operator`)
      return undefined
    }
    const op = candidate.op
    if (typeof op !== 'string') {
      errors.push(`${path}.op: operator must be a string`)
      return undefined
    }
    if (op === 'ref') return parseRef(candidate, allowedRefs, errors, path)
    if (op === 'not') return parseNot(candidate, depth, path, visit, errors)
    if (op === 'all' || op === 'any') return parseNary(candidate, op, depth, path, visit, errors)
    if (op === 'atLeast') return parseThreshold(candidate, depth, path, visit, errors)
    errors.push(`${path}.op: unsupported operator ${JSON.stringify(op)}`)
    return undefined
  }

  const expression = visit(value, 0, '$')
  return errors.length === 0 && expression !== undefined ? { expression, errors } : { errors }
}

/**
 * Evaluate a typed AST against settled child truth values.
 * @param expression - validated DoG Boolean AST.
 * @param values - child success values; missing values are unresolved.
 * @returns three-valued result so pending work cannot be mistaken for failure.
 */
export function evaluateBoolExpr(expression: BoolExpr, values: ReadonlyMap<string, boolean | undefined>): TruthValue {
  switch (expression.op) {
    case 'ref': {
      const value = values.get(expression.id)
      return value === undefined ? 'unknown' : value
    }
    case 'not': {
      const value = evaluateBoolExpr(expression.item, values)
      return value === 'unknown' ? 'unknown' : !value
    }
    case 'all':
      return evaluateAll(expression, values)
    case 'any':
      return evaluateAny(expression, values)
    case 'atLeast':
      return evaluateAtLeast(expression, values)
  }
}

function parseRef(
  candidate: Record<string, unknown>,
  allowedRefs: ReadonlySet<string>,
  errors: string[],
  path: string,
): RefExpr | undefined {
  if (Object.keys(candidate).length !== 2 || typeof candidate.id !== 'string' || candidate.id.length === 0) {
    errors.push(`${path}: ref requires only a non-empty string id`)
    return undefined
  }
  if (!allowedRefs.has(candidate.id)) {
    errors.push(`${path}.id: ${JSON.stringify(candidate.id)} is not a containment child`)
    return undefined
  }
  return { op: 'ref', id: candidate.id }
}

function parseNot(
  candidate: Record<string, unknown>,
  depth: number,
  path: string,
  visit: (value: unknown, depth: number, path: string) => BoolExpr | undefined,
  errors: string[],
): NotExpr | undefined {
  if (Object.keys(candidate).length !== 2 || !Object.prototype.hasOwnProperty.call(candidate, 'item')) {
    errors.push(`${path}: not requires only item`)
    return undefined
  }
  const item = visit(candidate.item, depth + 1, `${path}.item`)
  return item === undefined ? undefined : { op: 'not', item }
}

function parseNary(
  candidate: Record<string, unknown>,
  op: 'all' | 'any',
  depth: number,
  path: string,
  visit: (value: unknown, depth: number, path: string) => BoolExpr | undefined,
  errors: string[],
): AllExpr | AnyExpr | undefined {
  if (Object.keys(candidate).length !== 2 || !Array.isArray(candidate.items) || candidate.items.length === 0) {
    errors.push(`${path}: ${op} requires only a non-empty items array`)
    return undefined
  }
  const items: BoolExpr[] = []
  for (const [index, itemValue] of candidate.items.entries()) {
    const item = visit(itemValue, depth + 1, `${path}.items[${index}]`)
    if (item !== undefined) items.push(item)
  }
  if (items.length !== candidate.items.length) return undefined
  return op === 'all' ? { op, items } : { op, items }
}

function parseThreshold(
  candidate: Record<string, unknown>,
  depth: number,
  path: string,
  visit: (value: unknown, depth: number, path: string) => BoolExpr | undefined,
  errors: string[],
): AtLeastExpr | undefined {
  if (
    Object.keys(candidate).length !== 3
    || !Array.isArray(candidate.items)
    || candidate.items.length === 0
    || typeof candidate.count !== 'number'
    || !Number.isInteger(candidate.count)
    || candidate.count < 1
    || candidate.count > candidate.items.length
  ) {
    errors.push(`${path}: atLeast requires count and a non-empty items array with 1 <= count <= items.length`)
    return undefined
  }
  const items: BoolExpr[] = []
  for (const [index, itemValue] of candidate.items.entries()) {
    const item = visit(itemValue, depth + 1, `${path}.items[${index}]`)
    if (item !== undefined) items.push(item)
  }
  if (items.length !== candidate.items.length) return undefined
  return { op: 'atLeast', count: candidate.count, items }
}

function evaluateAll(expression: AllExpr, values: ReadonlyMap<string, boolean | undefined>): TruthValue {
  let unknown = false
  for (const item of expression.items) {
    const result = evaluateBoolExpr(item, values)
    if (result === false) return false
    if (result === 'unknown') unknown = true
  }
  return unknown ? 'unknown' : true
}

function evaluateAny(expression: AnyExpr, values: ReadonlyMap<string, boolean | undefined>): TruthValue {
  let unknown = false
  for (const item of expression.items) {
    const result = evaluateBoolExpr(item, values)
    if (result === true) return true
    if (result === 'unknown') unknown = true
  }
  return unknown ? 'unknown' : false
}

function evaluateAtLeast(expression: AtLeastExpr, values: ReadonlyMap<string, boolean | undefined>): TruthValue {
  let passed = 0
  let unknown = 0
  for (const item of expression.items) {
    const result = evaluateBoolExpr(item, values)
    if (result === true) passed += 1
    if (result === 'unknown') unknown += 1
  }
  if (passed >= expression.count) return true
  return passed + unknown >= expression.count ? 'unknown' : false
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
}
