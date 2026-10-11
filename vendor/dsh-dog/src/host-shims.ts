/**
 * Self-contained replacements for the two host packages this plugin used to
 * import at runtime: `@deepseek-ai/dsh-home-paths` (`dshHomePath`) and
 * `@deepseek-ai/dsh-tools` (`defineTool`). Both were declared as
 * peerDependencies, and under the DSH profile install layout (pnpm isolated
 * node_modules) peer instances are not resolvable from this vendored
 * directory, so every entry import failed with ERR_MODULE_NOT_FOUND and the
 * plugin never activated (GitHub issue #74). The implementations below match
 * the host behavior for the schema subset this plugin declares; type-only
 * imports from the host packages are still used and erased at build time.
 */

import { homedir } from 'node:os'
import { join, resolve } from 'node:path'
import type { ToolDefinition, ToolRunContext } from '@deepseek-ai/dsh-tools'

// ── dshHomePath ─────────────────────────────────────────────────────────────

/** Directory name for the default DeepSeek Harness home under the OS home. */
const DSH_HOME_DIR_NAME = '.dsh'
/** Environment variable that overrides the default DeepSeek Harness home. */
const DSH_HOME_ENV = 'DSH_HOME'

/** Expand supported tilde prefixes against the operating-system home. */
function expandHomePath(path: string): string {
  if (path === '~') return homedir()
  if (path.startsWith('~/') || path.startsWith('~\\')) return join(homedir(), path.slice(2))
  return path
}

/**
 * Resolve the single-root DeepSeek Harness home: `$DSH_HOME` when set to a
 * non-blank value, otherwise `~/.dsh`. Mirrors the host `resolveDshHome`.
 */
function resolveDshHome(): string {
  const fromEnv = process.env[DSH_HOME_ENV]
  return resolve(expandHomePath(fromEnv !== undefined && fromEnv.trim().length > 0 ? fromEnv : join(homedir(), DSH_HOME_DIR_NAME)))
}

/** Join path segments onto the resolved DeepSeek Harness home. */
export function dshHomePath(...segments: string[]): string {
  return join(resolveDshHome(), ...segments)
}

// ── defineTool ──────────────────────────────────────────────────────────────

type JsonScalar = string | number | boolean | null

/** Author-facing value schema spec, mirroring the host subset DoG declares. */
export type ValueSchemaSpec =
  | { type: 'json'; description?: string }
  | { type: 'string' | 'number' | 'integer' | 'boolean' | 'null'; description?: string; enum?: readonly JsonScalar[]; const?: JsonScalar }
  | { type: 'array'; description?: string; items?: ValueSchemaSpec }
  | { type: 'object'; description?: string; properties?: Record<string, ParameterPropertySpec>; additionalProperties?: boolean }

/** One parameter property: a value schema plus optional requiredness. */
export type ParameterPropertySpec = ValueSchemaSpec & { required?: boolean }

/** Options accepted by the local {@link defineTool}. */
export interface DefineToolOptions {
  readonly name: string
  readonly description: string
  readonly parameters: Record<string, ParameterPropertySpec>
  readonly output: {
    readonly schema: ValueSchemaSpec
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    readonly render: (args: any, value: any) => unknown
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    readonly presentationMeta?: (args: any, value: any) => unknown
  }
  readonly timeoutMs?: number
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  readonly isConcurrencySafe?: (args: any) => boolean
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  readonly execute: (args: any, exec: ToolRunContext) => Promise<unknown>
}

/** Thrown when model-generated arguments violate the compiled schema. */
export class ToolArgsError extends Error {
  readonly violations: readonly string[]
  constructor(violations: readonly string[]) {
    super(`invalid arguments: ${violations.join('; ')}`)
    this.name = 'ToolArgsError'
    this.violations = violations
  }
}

type CompiledSchema = Record<string, unknown>

/** Compile one author-facing value schema node to raw JSON Schema. */
function compileValueSchema(spec: ValueSchemaSpec, path: string): CompiledSchema {
  if (spec === null || typeof spec !== 'object') throw new Error(`${path}: schema node must be an object`)
  const node: CompiledSchema = {}
  if (spec.description !== undefined) node.description = spec.description
  switch (spec.type) {
    case 'json':
      // Annotation-only schema: accepts any JSON value.
      return node
    case 'string':
    case 'number':
    case 'integer':
    case 'boolean':
    case 'null':
      node.type = spec.type
      if ('enum' in spec && spec.enum !== undefined) node.enum = [...spec.enum]
      if ('const' in spec && spec.const !== undefined) node.const = spec.const
      return node
    case 'array':
      node.type = 'array'
      if (spec.items !== undefined) node.items = compileValueSchema(spec.items, `${path}.items`)
      return node
    case 'object': {
      node.type = 'object'
      if (spec.additionalProperties !== undefined) node.additionalProperties = spec.additionalProperties
      if (spec.properties !== undefined) {
        const { properties, required } = compilePropertyMap(spec.properties, `${path}.properties`)
        node.properties = properties
        if (required.length > 0) node.required = required
      }
      return node
    }
    default:
      throw new Error(`${path}.type must be string/number/integer/boolean/null/array/object/json`)
  }
}

/** Compile a property map, hoisting per-property `required` flags onto the parent. */
function compilePropertyMap(
  input: Record<string, ParameterPropertySpec>,
  path: string,
): { properties: Record<string, CompiledSchema>; required: string[] } {
  const properties: Record<string, CompiledSchema> = {}
  const required: string[] = []
  for (const [key, property] of Object.entries(input)) {
    const { required: isRequired, ...spec } = property
    properties[key] = compileValueSchema(spec as ValueSchemaSpec, `${path}.${key}`)
    if (isRequired === true) required.push(key)
  }
  return { properties, required }
}

/** Compile the implicit open parameter object into raw JSON Schema. */
function compileParameters(spec: Record<string, ParameterPropertySpec>): CompiledSchema {
  const { properties, required } = compilePropertyMap(spec, 'parameters')
  const schema: CompiledSchema = { type: 'object', properties }
  if (required.length > 0) schema.required = required
  return schema
}

/** Validate one JSON value against the compiled subset, collecting violations. */
function validateValue(schema: CompiledSchema, value: unknown, path: string, violations: string[]): void {
  const at = path === '' ? 'arguments' : path
  if (schema.const !== undefined && value !== schema.const) {
    violations.push(`${at}: must equal ${JSON.stringify(schema.const)}`)
    return
  }
  if (Array.isArray(schema.enum) && !schema.enum.some((entry) => entry === value)) {
    violations.push(`${at}: must be one of ${JSON.stringify(schema.enum)}`)
    return
  }
  switch (schema.type) {
    case undefined:
      return // annotation-only schema accepts any JSON value
    case 'null':
      if (value !== null) violations.push(`${at}: expected null`)
      return
    case 'boolean':
      if (typeof value !== 'boolean') violations.push(`${at}: expected boolean, got ${describe(value)}`)
      return
    case 'string':
      if (typeof value !== 'string') violations.push(`${at}: expected string, got ${describe(value)}`)
      return
    case 'number':
      if (typeof value !== 'number' || !Number.isFinite(value)) violations.push(`${at}: expected number, got ${describe(value)}`)
      return
    case 'integer':
      if (typeof value !== 'number' || !Number.isInteger(value)) violations.push(`${at}: expected integer, got ${describe(value)}`)
      return
    case 'array': {
      if (!Array.isArray(value)) {
        violations.push(`${at}: expected array, got ${describe(value)}`)
        return
      }
      const items = schema.items as CompiledSchema | undefined
      if (items !== undefined) value.forEach((item, index) => validateValue(items, item, `${at}[${index}]`, violations))
      return
    }
    case 'object': {
      if (value === null || typeof value !== 'object' || Array.isArray(value)) {
        violations.push(`${at}: expected object, got ${describe(value)}`)
        return
      }
      const record = value as Record<string, unknown>
      for (const key of (schema.required as string[] | undefined) ?? []) {
        if (!Object.hasOwn(record, key)) violations.push(`${at}: missing required property "${key}"`)
      }
      const properties = schema.properties as Record<string, CompiledSchema> | undefined
      if (properties !== undefined) {
        for (const [key, propertySchema] of Object.entries(properties)) {
          if (Object.hasOwn(record, key)) validateValue(propertySchema, record[key], `${at}.${key}`, violations)
        }
      }
      return
    }
  }
}

function describe(value: unknown): string {
  if (value === null) return 'null'
  if (Array.isArray(value)) return 'array'
  return typeof value
}

/** Validate model-generated arguments against the compiled parameter schema. */
export function validateArgs(parameters: CompiledSchema, args: unknown): string[] {
  const violations: string[] = []
  validateValue(parameters, args, '', violations)
  return violations
}

/**
 * Define a first-party tool with strict execution validation, matching the
 * host `defineTool` contract: arguments are validated before `execute`, and
 * replay presenters validate softly and fall back to generic rendering.
 */
export function defineTool(options: DefineToolOptions): ToolDefinition {
  const userExecute = options.execute
  const userRender = options.output.render
  const userPresentationMeta = options.output.presentationMeta
  const userIsConcurrencySafe = options.isConcurrencySafe
  if (options.timeoutMs !== undefined && (!Number.isFinite(options.timeoutMs) || options.timeoutMs <= 0))
    throw new Error(`defineTool(${options.name}): timeoutMs must be a positive finite number`)
  const parameters = compileParameters(options.parameters)
  const outputSchema = compileValueSchema(options.output.schema, 'schema')
  const validate = (args: unknown) => validateArgs(parameters, args)
  const tool: ToolDefinition = {
    name: options.name,
    description: options.description,
    parameters: parameters as ToolDefinition['parameters'],
    output: {
      schema: outputSchema as ToolDefinition['output']['schema'],
      render: (args, value) => userRender(args, value) as ReturnType<ToolDefinition['output']['render']>,
      ...(userPresentationMeta !== undefined
        ? { presentationMeta: (args: unknown, value: unknown) => userPresentationMeta(args, value) as never }
        : {}),
    },
    ...(options.timeoutMs !== undefined ? { timeoutMs: options.timeoutMs } : {}),
    async execute(args: unknown, exec: ToolRunContext) {
      const violations = validate(args)
      if (violations.length > 0) throw new ToolArgsError(violations)
      return userExecute(args, exec)
    },
  }
  if (userIsConcurrencySafe)
    tool.isConcurrencySafe = (args) => {
      if (validate(args).length > 0) return false
      return userIsConcurrencySafe(args)
    }
  return tool
}
