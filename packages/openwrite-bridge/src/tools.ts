/**
 * The `novel_*` tool definitions bridging dsh agents to the OpenWrite Studio
 * HTTP action surface. Payload shapes are verified against OpenWrite
 * `tools/studio_http.py` (POST_ROUTES / do_GET / do_PUT) and
 * `tools/studio_application.py` (the dispatched methods).
 */

import { createHash } from 'node:crypto'
import { realpathSync } from 'node:fs'
import { mkdir, writeFile } from 'node:fs/promises'
import { isAbsolute, join, normalize } from 'node:path'
import type { Context } from '@deepseek-ai/cordis'
import {
  ToolArgsError,
  parameterSchemaSpecToJsonSchema,
  validateJsonSchemaValue,
  valueSchemaSpecToJsonSchema,
  type DefineToolOptions,
  type ParameterSchemaSpec,
  type ToolDefinition,
  type ToolRunContext,
  type ValueSchemaSpec,
} from '@deepseek-ai/dsh-tools'
import type { JsonObject, JsonValue, StudioClient, WorkspaceContext } from './client.js'
import { StudioError } from './client.js'
import { materializeChapterDelivery } from './dog-delivery.js'
import { materializeCompletedDogTaskReview, materializeDogReview, reviewChapterId } from './dog-review.js'

/** Plugin-level config the tools need beyond the HTTP client. */
export interface NovelToolsOptions {
  /** Cooperative per-call budget (ms), attached as each tool's `timeoutMs`. */
  timeoutMs: number
  /** Directory `novel_export` saves downloaded files into. */
  outputDir: string
}

/** Render an arbitrary JSON payload as pretty-printed model-facing text. */
function renderJson(value: unknown): [{ type: 'text'; text: string }] {
  return [{ type: 'text', text: JSON.stringify(value, null, 2) }]
}

/** The schema for tools whose canonical value is an opaque Studio JSON payload. */
const JSON_OUTPUT_SCHEMA = {
  type: 'json',
  description: 'The JSON payload returned by the OpenWrite Studio API.',
} as const

/** Manuscript chapter ids accepted by OpenWrite (`ch_<digits>`). */
const CHAPTER_ID_PATTERN = /^ch_\d+$/

/** Short, model-facing description of a received argument value's actual shape. */
function describeValue(value: unknown): string {
  if (value === undefined) return 'undefined'
  if (value === null) return 'null'
  if (Array.isArray(value)) return `an array of ${value.length} item(s)`
  if (typeof value === 'string') return 'a string'
  return `a value of type ${typeof value}`
}

/**
 * Parse a JSON string argument once, naming the parameter and the received
 * type when the text is not valid JSON.
 */
function parseJsonArgument(name: string, value: string): unknown {
  try {
    return JSON.parse(value)
  } catch (error) {
    const detail = error instanceof Error ? error.message : String(error)
    throw new Error(`parameter "${name}" expects a JSON value; received a string that is not valid JSON (${detail})`)
  }
}

/**
 * The asset id shape the server accepts. The same text is quoted in the
 * parameter description the model reads and in the error it gets when the id
 * is missing or malformed, so a rejected call can be corrected in one retry
 * instead of guessing the format again.
 */
const ASSET_ID_PATTERN = /^[A-Za-z0-9][A-Za-z0-9_.-]{0,79}$/
const ASSET_ID_SHAPE = '[A-Za-z0-9][A-Za-z0-9_.-]{0,79}'

/** A missing asset id must say what a valid one looks like. */
function assetIdRequired(action: string): string {
  return `id is required for novel_assets(action="${action}"); pass an id matching ${ASSET_ID_SHAPE}`
}

function assertAssetId(id: string): void {
  if (!ASSET_ID_PATTERN.test(id)) {
    throw new Error(`invalid asset id "${id}"; it must match ${ASSET_ID_SHAPE}`)
  }
}

/** JSON-typed parameters that also legitimately accept a raw string. */
const RAW_STRING_JSON_ARGUMENTS = new Set(['novel_source_action.focus'])

/**
 * Normalize arguments for parameters declared `type: 'json'` (and
 * `type: 'array'` with json items). DSH keeps `json` an annotation-only
 * schema, so the value reaches the plugin in whatever shape the model
 * emitted; models that serialize the object/array as a JSON *string* would
 * otherwise fail the plugin-side object/array checks (GitHub issue #75).
 * Parameters in {@link RAW_STRING_JSON_ARGUMENTS} additionally accept their
 * documented plain-string form.
 */
function normalizeJsonArguments(toolName: string, parameters: ParameterSchemaSpec, args: Record<string, unknown>): Record<string, unknown> {
  let normalized: Record<string, unknown> | undefined
  for (const [name, spec] of Object.entries(parameters)) {
    const value = args[name]
    if (value === undefined || spec === null || typeof spec !== 'object') continue
    const type = (spec as { type?: unknown }).type
    if (type === 'json' && typeof value === 'string') {
      let parsed: unknown
      try {
        parsed = parseJsonArgument(name, value)
      } catch (error) {
        // Some parameters describe a plain string for one action and a JSON
        // value for another (novel_source_action.focus). For those, a raw
        // string is a legitimate value, not malformed JSON.
        if (!RAW_STRING_JSON_ARGUMENTS.has(`${toolName}.${name}`)) throw error
        parsed = value
      }
      normalized ??= { ...args }
      normalized[name] = parsed
    } else if (type === 'array') {
      const items = (spec as { items?: unknown }).items
      const itemType = items !== null && typeof items === 'object' ? (items as { type?: unknown }).type : undefined
      if (itemType !== 'json') continue
      if (typeof value === 'string') {
        normalized ??= { ...args }
        normalized[name] = parseJsonArgument(name, value)
      } else if (Array.isArray(value) && value.some((item) => typeof item === 'string')) {
        normalized ??= { ...args }
        normalized[name] = value.map((item) => (typeof item === 'string' ? parseJsonArgument(`${name}[]`, item) : item))
      }
    }
  }
  return normalized ?? args
}

/**
 * Local `defineTool`: mirrors the host helper (`@deepseek-ai/dsh-tools`
 * `defineTool`) using the host's own schema compiler and validator, except
 * every argument flow (execute and the replay presenters) first normalizes
 * string-typed JSON arguments — see {@link normalizeJsonArguments}.
 * Normalization must run *before* validation, otherwise an `array` parameter
 * receiving a JSON string would be rejected by the schema check before the
 * plugin ever sees it (GitHub issue #75). Centralizing here keeps all
 * `novel_*` call sites free of per-parameter parsing.
 */
function defineTool<const S extends ParameterSchemaSpec, const O extends ValueSchemaSpec>(
  options: DefineToolOptions<S, O>,
): ToolDefinition {
  const userExecute = options.execute
  const userFinalizeContent = options.finalizeContent
  const userRender = options.output.render
  const userPresentationMeta = options.output.presentationMeta
  const userPresentCall = options.presentCall
  const userPresentResult = options.presentResult
  const userIsConcurrencySafe = options.isConcurrencySafe
  if (options.timeoutMs !== undefined && (!Number.isFinite(options.timeoutMs) || options.timeoutMs <= 0))
    throw new Error(`defineTool(${options.name}): timeoutMs must be a positive finite number`)
  const compiled = parameterSchemaSpecToJsonSchema(options.parameters) as unknown as Record<string, unknown>
  // A tool that silently accepts an undeclared argument turns a model typo into
  // a no-op write: the argument is dropped and the call still reports success.
  // The host's schema validator enforces this keyword, so an unknown argument
  // is rejected before the tool body runs.
  const parameters = { ...compiled, additionalProperties: false }
  const outputSchema = valueSchemaSpecToJsonSchema(options.output.schema)
  const normalize = (args: unknown): Record<string, unknown> =>
    normalizeJsonArguments(options.name, options.parameters, objectValue(args))
  const validate = (args: Record<string, unknown>): string[] =>
    validateJsonSchemaValue(parameters, args, '')
  const tool: ToolDefinition = {
    name: options.name,
    description: options.description,
    parameters,
    output: {
      schema: outputSchema,
      render: (args, value) => userRender(args as never, value as never),
      ...(userPresentationMeta !== undefined
        ? { presentationMeta: (args: unknown, value: unknown) => userPresentationMeta(args as never, value as never) }
        : {}),
    },
    ...(options.timeoutMs !== undefined ? { timeoutMs: options.timeoutMs } : {}),
    async execute(args: unknown, exec: ToolRunContext) {
      const normalized = normalize(args)
      const violations = validate(normalized)
      if (violations.length > 0) throw new ToolArgsError(violations)
      try {
        return await userExecute(normalized as never, exec)
      } catch (error) {
        if (!(error instanceof StudioError) || error.code.startsWith('WORKSPACE_')) throw error
        error.message = JSON.stringify({ code: error.code, message: error.message,
          status: error.status, details: error.details, request_id: error.requestId,
          // A timeout is as ambiguous as a transport failure about whether the server applied the write.
          recovery: error.code === 'NETWORK_ERROR' || error.code === 'REQUEST_TIMEOUT' ? 'List recent tasks and chapter runs before resubmitting; the server may have accepted the request.' : null,
        })
        throw error
      }
    },
  }
  if (userFinalizeContent) tool.finalizeContent = (exec, result) => userFinalizeContent(exec, result)
  if (userPresentCall)
    tool.presentCall = (args) => {
      const normalized = normalize(args)
      if (validate(normalized).length > 0) return undefined
      return userPresentCall(normalized as never)
    }
  if (userPresentResult)
    tool.presentResult = (args, result) => {
      const normalized = normalize(args)
      if (validate(normalized).length > 0) return undefined
      return userPresentResult(normalized as never, result)
    }
  if (userIsConcurrencySafe)
    tool.isConcurrencySafe = (args) => {
      const normalized = normalize(args)
      if (validate(normalized).length > 0) return false
      return userIsConcurrencySafe(normalized as never)
    }
  return tool
}

/** Resolve a review target: an explicit manuscript path, or a chapter id mapped to `data/manuscript/<id>.md`. */
function resolveReviewPath(args: { path?: string; chapter_id?: string }): string {
  const path = args.path?.trim()
  if (path) return path
  const chapterId = args.chapter_id?.trim()
  if (!chapterId) throw new Error('either path or chapter_id is required')
  if (!CHAPTER_ID_PATTERN.test(chapterId)) throw new Error(`chapter_id must match ch_<digits>, got "${chapterId}"`)
  return `data/manuscript/${chapterId}.md`
}

/** Unicode code-point offset of a JavaScript UTF-16 index (Studio counts code points). */
function codePointOffset(text: string, index: number): number {
  return Array.from(text.slice(0, index)).length
}

/**
 * Derive exact annotation offsets from a quote when the caller supplied none.
 * The server matches `content[start:end]` literally, so a quote that is absent
 * or ambiguous is reported before any request is sent.
 */
async function resolveAnnotationHints(
  client: StudioClient,
  chapterId: string,
  quote: string,
  signal: AbortSignal,
): Promise<{ start: number; end: number }> {
  const brief = objectValue(await client.getJson(`/api/chapters/${encodeURIComponent(chapterId)}/work-brief`, {}, signal))
  const path = objectValue(brief['manuscript'])['path']
  if (typeof path !== 'string' || path === '') {
    throw new Error('cannot locate the chapter document to derive annotation offsets; pass start_hint and end_hint explicitly')
  }
  const document = objectValue(await client.getJson('/api/document', { path }, signal))
  const content = document['content']
  if (typeof content !== 'string') {
    throw new Error('cannot read the chapter document to derive annotation offsets; pass start_hint and end_hint explicitly')
  }
  const first = content.indexOf(quote)
  if (first < 0) {
    throw new Error('quote was not found in the chapter; pass the exact selected text or explicit start_hint/end_hint')
  }
  if (content.indexOf(quote, first + 1) >= 0) {
    throw new Error('quote occurs more than once in the chapter; pass start_hint and end_hint explicitly')
  }
  const start = codePointOffset(content, first)
  return { start, end: start + Array.from(quote).length }
}

function objectValue(value: unknown): JsonObject {
  return value !== null && typeof value === 'object' && !Array.isArray(value) ? value as JsonObject : {}
}

function requireRecord(value: unknown, name: string): JsonObject {
  if (value === null || typeof value !== 'object' || Array.isArray(value)) throw new Error(`${name} must be a JSON object`)
  return value as JsonObject
}

async function deliveryForResponse(
  client: StudioClient,
  response: JsonValue,
  chapterId: string,
  signal: AbortSignal,
  threshold?: number,
): Promise<JsonValue> {
  const embedded = objectValue(response)['workspace']
  const workspace = embedded !== null && typeof embedded === 'object' && !Array.isArray(embedded)
    ? embedded
    : await client.getJson('/api/workspace', {}, signal)
  return await materializeChapterDelivery(workspace, chapterId, threshold, client.context?.workspaceRoot)
}

/**
 * Derive the request-scoped Workspace context from the tool execution, failing
 * closed (docs/WORKSPACE_CONTEXT_CONTRACT.md §2.1): the stamped session cwd is
 * the only root source — never a fallback to the plugin cwd or a fixed project.
 */
export function workspaceContextFromExec(exec: ToolRunContext): WorkspaceContext {
  const header = exec.agent?.session?.header
  const cwd = header?.cwd
  if (cwd === undefined || cwd.trim() === '') {
    throw new StudioError(
      'novel_* tool call lacks a Workspace context: exec.agent.session.header.cwd is missing',
      400, 'WORKSPACE_CONTEXT_MISSING',
    )
  }
  if (!isAbsolute(cwd)) {
    throw new StudioError(
      `Workspace root is not an absolute path: ${cwd}`,
      400, 'WORKSPACE_ROOT_INVALID', { reason: 'not_absolute' },
    )
  }
  let workspaceRoot: string
  try {
    workspaceRoot = realpathSync(cwd)
  } catch {
    throw new StudioError(
      `Workspace root cannot be canonicalized: ${cwd}`,
      400, 'WORKSPACE_ROOT_INVALID', { reason: 'not_found' },
    )
  }
  return {
    workspaceRoot,
    sessionId: header?.id,
    toolCallId: String(exec.callId),
    rootCallId: String(exec.rootCallId ?? exec.callId),
    toolName: exec.name,
  }
}

/** Per-root export directory: `<outputDir>/<sha256(workspaceRoot)[:12]>`. */
function outputDirFor(outputDir: string, client: StudioClient): string {
  const workspaceRoot = client.context?.workspaceRoot
  // Unreachable in practice: clientFor fails closed before any handler runs.
  if (workspaceRoot === undefined) return outputDir
  return join(outputDir, createHash('sha256').update(workspaceRoot).digest('hex').slice(0, 12))
}

/** A server-supplied download name is a filename, never a relative path. */
function exportFilename(filename: string, fallback: string): string {
  const name = filename === 'export.bin' ? fallback : filename
  // Check both platforms' separators, drive prefixes and control characters
  // before joining: exports may later be moved between macOS and Windows.
  if (name.trim() === '' || name === '.' || name === '..' || /[\\/\u0000-\u001f\u007f]/.test(name) || /^[A-Za-z]:/.test(name)) {
    throw new StudioError('Studio returned an unsafe export filename', 502, 'INVALID_EXPORT_FILENAME', { reason: 'not_basename' })
  }
  // Beyond the traversal checks: a name longer than the filesystem limit would
  // otherwise escape as a bare ENAMETOOLONG whose message embeds the full local
  // path. 255 is the common ceiling; stay well under it for extension suffixes.
  if (Buffer.byteLength(name, 'utf8') > 200) {
    throw new StudioError('Studio returned an export filename that is too long', 502, 'INVALID_EXPORT_FILENAME', { reason: 'too_long' })
  }
  return name
}

/** Register every `novel_*` tool into the host tools registry. */
export function registerNovelTools(ctx: Context, clientFactory: (exec: ToolRunContext) => StudioClient, options: NovelToolsOptions): void {
  const { timeoutMs, outputDir } = options
  // Every handler resolves its own request-scoped client from the execution;
  // a missing/invalid Workspace context fails closed before any HTTP call.
  const clientFor = (exec: ToolRunContext): StudioClient => clientFactory(exec)

  // ── reads ──────────────────────────────────────────────────────────────

    // ── embedding configuration ───────────────────────────────────────────────────

  ctx.tools.register(defineTool({
    name: 'novel_embedding_profiles',
    description:
      'List, save, select, delete and test embedding profiles. Selection chooses the profile the ' +
      'server uses for semantic search and recall.',
    parameters: {
      action: { type: 'string', required: true, enum: ['list', 'save', 'select', 'delete', 'test'], description: 'Embedding configuration operation.' },
      profile: { type: 'json', description: 'Embedding profile: id, label, provider, model, base_url, dimension, max_tokens.' },
      api_key: { type: 'string', description: 'Embedding API key.' },
      remember_api_key: { type: 'boolean', description: 'Persist the key (default true).' },
      profile_id: { type: 'string' },
      id: { type: 'string', description: 'Stored profile id to probe.' },
      candidate: { type: 'json', description: 'Embedding candidate settings object (merged into the request).' },
    },
    output: { schema: JSON_OUTPUT_SCHEMA, render: (_args, value) => renderJson(value) },
    timeoutMs,
    isConcurrencySafe: args => ['list', 'test'].includes(args.action),
    async execute(args, exec) {
      switch (args.action) {
        case 'list': {
              return await clientFor(exec).getJson('/api/model/embedding', {}, exec.signal)
            
        }
        case 'save': {
        if (args.profile === undefined) throw new Error('profile is required for novel_embedding_profiles(action="save")')
              if (typeof args.profile !== 'object' || args.profile === null || Array.isArray(args.profile)) throw new Error('profile must be a JSON object')
              const body: JsonObject = { ...args.profile }
              for (const key of ['api_key', 'remember_api_key'] as const) if (args[key] !== undefined) body[key] = args[key]
              return await clientFor(exec).postJson('/api/model/embedding', body, exec.signal)
            
        }
        case 'select': {
        if (args.profile_id === undefined) throw new Error('profile_id is required for novel_embedding_profiles(action="select")')
              if (!args.profile_id.trim()) throw new Error('profile_id must be non-empty')
              return await clientFor(exec).postJson('/api/model/embedding/select', { profile_id: args.profile_id }, exec.signal)
            
        }
        case 'delete': {
        if (args.profile_id === undefined) throw new Error('profile_id is required for novel_embedding_profiles(action="delete")')
              if (!args.profile_id.trim()) throw new Error('profile_id must be non-empty')
              return await clientFor(exec).postJson('/api/model/embedding/delete', { profile_id: args.profile_id }, exec.signal)
            
        }
        case 'test': {
              const client = clientFor(exec)
              const body: JsonObject = {}
              if (args.candidate !== undefined) {
                if (typeof args.candidate !== 'object' || args.candidate === null || Array.isArray(args.candidate)) {
                  throw new Error('candidate must be a JSON object')
                }
                Object.assign(body, args.candidate)
              }
              for (const key of ['id', 'api_key'] as const) {
                const value = args[key]
                if (value !== undefined) body[key] = value
              }
              return await client.postJson('/api/model/embedding/test', body, exec.signal)
            
        }
        default: throw new Error(`novel_embedding_profiles: unknown action ${String(args.action)}`)
      }
    },
  }))

        ctx.tools.register(defineTool({
    name: 'novel_status',
    description: 'Get a snapshot of the current OpenWrite novel project: title, chapters, word counts, writing targets, and focus compass.',
    parameters: {},
    output: { schema: JSON_OUTPUT_SCHEMA, render: (_args, value) => renderJson(value) },
    timeoutMs,
    isConcurrencySafe: () => true,
    async execute(_args, exec) {
      const client = clientFor(exec)
      return await client.getJson('/api/workspace', {}, exec.signal)
    },
  }))

  ctx.tools.register(defineTool({
    name: 'novel_review_framework',
    description:
      'Inspect the canonical reusable chapter-review DAG blueprint: its version, revision, six quality domains, 37 checks, hard gates, dependencies, invariants, and extension points.',
    parameters: {},
    output: { schema: JSON_OUTPUT_SCHEMA, render: (_args, value) => renderJson(value) },
    timeoutMs,
    isConcurrencySafe: () => true,
    async execute(_args, exec) {
      return await clientFor(exec).getJson('/api/review/framework', {}, exec.signal)
    },
  }))

  ctx.tools.register(defineTool({
    name: 'novel_manuscript_acceptance',
    description:
      'Inspect the canonical manuscript acceptance ledger: current and accepted content revisions, drift, ' +
      'recoverable operations, derived-result impacts, and chapters that require author review.',
    parameters: {},
    output: { schema: JSON_OUTPUT_SCHEMA, render: (_args, value) => renderJson(value) },
    timeoutMs,
    isConcurrencySafe: () => true,
    async execute(_args, exec) {
      return await clientFor(exec).getJson('/api/manuscript/acceptance', {}, exec.signal)
    },
  }))

  ctx.tools.register(defineTool({
    name: 'novel_trace_list',
    description: 'Inspect recent redacted Prompt→context→model→tool→domain traces. Raw prompts, context, model output, credentials, chain-of-thought, and mutation values are never stored.',
    parameters: {
      limit: { type: 'number', description: 'Maximum records to return (1-100, default 20).' },
    },
    output: { schema: JSON_OUTPUT_SCHEMA, render: (_args, value) => renderJson(value) },
    timeoutMs,
    isConcurrencySafe: () => true,
    async execute(args, exec) {
      const limit = Math.max(1, Math.min(100, Math.trunc(args.limit ?? 20)))
      return await clientFor(exec).getJson('/api/traces', { limit: String(limit) }, exec.signal)
    },
  }))

  ctx.tools.register(defineTool({
    name: 'novel_context_preview',
    description: 'Preview the context packet OpenWrite would assemble for writing a chapter (relevant outline, assets, foreshadowing, and prior-chapter memory). The chapter must already exist in the outline; an unknown chapter id is rejected instead of returning an empty generic context. Set include_agent_payload to inspect canonical writer inputs and document inclusion without calling a model.',
    parameters: {
      chapter: { type: 'string', description: 'Chapter id (e.g. "ch_0007"); omit or pass "next" for the next chapter to write.' },
      include_agent_payload: { type: 'boolean', description: 'Include the full writer payload, rendered initial messages and document inventory. Later segment/retry messages depend on the write request.' },
    },
    output: { schema: JSON_OUTPUT_SCHEMA, render: (_args, value) => renderJson(value) },
    timeoutMs,
    isConcurrencySafe: () => true,
    async execute(args, exec) {
      const client = clientFor(exec)
      return await client.getJson('/api/context', { chapter: args.chapter?.trim() || 'next', ...(args.include_agent_payload ? { include_agent_payload: 'true' } : {}) }, exec.signal)
    },
  }))

  ctx.tools.register(defineTool({
    name: 'novel_outline_read',
    description: 'Read the live outline tree. The response carries a `revision` fingerprint required by novel_outline_edit and a chapter `recommendation`.',
    parameters: {
      chapter: { type: 'string', description: 'Optional chapter id to get a writing recommendation for.' },
    },
    output: { schema: JSON_OUTPUT_SCHEMA, render: (_args, value) => renderJson(value) },
    timeoutMs,
    isConcurrencySafe: () => true,
    async execute(args, exec) {
      const client = clientFor(exec)
      const params: Record<string, string> = {}
      const chapter = args.chapter?.trim()
      if (chapter) params['chapter'] = chapter
      return await client.getJson('/api/outline', params, exec.signal)
    },
  }))

    // ── reading order ─────────────────────────────────────────────────────────────

  ctx.tools.register(defineTool({
    name: 'novel_reading_order',
    description:
      'Read the reading order of the current project and move one document to another volume or ' +
      'position. The move is optimistic and requires the current revision.',
    parameters: {
      action: { type: 'string', required: true, enum: ['get', 'move'], description: 'Reading-order operation.' },
      document_id: { type: 'string', description: 'Stable document_id or unambiguous occurrence_id.' },
      target_volume_id: { type: 'string', description: 'Target volume_id from novel_reading_order.' },
      target_index: { type: 'integer', description: 'Zero-based position inside the target volume.' },
      expected_revision: { type: 'string', description: 'Fresh reading-order revision used for CAS.' },
    },
    output: { schema: JSON_OUTPUT_SCHEMA, render: (_args, value) => renderJson(value) },
    timeoutMs,
    isConcurrencySafe: args => ['get'].includes(args.action),
    async execute(args, exec) {
      switch (args.action) {
        case 'get': {
              return await clientFor(exec).getJson('/api/reading-order', {}, exec.signal)
            
        }
        case 'move': {
        if (args.document_id === undefined) throw new Error('document_id is required for novel_reading_order(action="move")')
        if (args.target_volume_id === undefined) throw new Error('target_volume_id is required for novel_reading_order(action="move")')
        if (args.target_index === undefined) throw new Error('target_index is required for novel_reading_order(action="move")')
        if (args.expected_revision === undefined) throw new Error('expected_revision is required for novel_reading_order(action="move")')
              if (!args.document_id.trim()) throw new Error('document_id must be non-empty')
              if (!args.target_volume_id.trim()) throw new Error('target_volume_id must be non-empty')
              if (!args.expected_revision.trim()) throw new Error('expected_revision must be non-empty')
              return await clientFor(exec).postJson('/api/reading-order/move', {
                document_id: args.document_id,
                target_volume_id: args.target_volume_id,
                target_index: args.target_index,
                expected_revision: args.expected_revision,
              }, exec.signal)
            
        }
        default: throw new Error(`novel_reading_order: unknown action ${String(args.action)}`)
      }
    },
  }))

  ctx.tools.register(defineTool({
    name: 'novel_reading_packet',
    description: 'Read a bounded continuous-reading window around one stable manuscript document or occurrence id.',
    parameters: {
      document_id: { type: 'string', required: true, description: 'Stable document_id or occurrence_id from novel_reading_order.' },
      before: { type: 'integer', description: 'Number of preceding chapters (0-20, default 1).' },
      after: { type: 'integer', description: 'Number of following chapters (0-20, default 1).' },
    },
    output: { schema: JSON_OUTPUT_SCHEMA, render: (_args, value) => renderJson(value) },
    timeoutMs,
    isConcurrencySafe: () => true,
    async execute(args, exec) {
      if (!args.document_id.trim()) throw new Error('document_id must be non-empty')
      const params: Record<string, string> = { document_id: args.document_id }
      if (args.before !== undefined) params['before'] = String(args.before)
      if (args.after !== undefined) params['after'] = String(args.after)
      return await clientFor(exec).getJson('/api/reading-packet', params, exec.signal)
    },
  }))

  ctx.tools.register(defineTool({
    name: 'novel_chapter_work',
    description: 'Read one chapter work brief: manuscript/acceptance/review revisions, writing target, recent edits, tasks, and categorized foreshadowing obligations.',
    parameters: {
      chapter_id: { type: 'string', required: true, description: 'Chapter id (ch_<digits>).' },
      document_id: { type: 'string', description: 'Stable document id used to bind recent activity.' },
      recent_limit: { type: 'integer', description: 'Maximum recent edit records (default 20).' },
    },
    output: { schema: JSON_OUTPUT_SCHEMA, render: (_args, value) => renderJson(value) },
    timeoutMs,
    isConcurrencySafe: () => true,
    async execute(args, exec) {
      if (!CHAPTER_ID_PATTERN.test(args.chapter_id)) throw new Error(`chapter_id must match ch_<digits>, got "${args.chapter_id}"`)
      const params: Record<string, string> = {}
      if (args.document_id !== undefined) params['document_id'] = args.document_id
      if (args.recent_limit !== undefined) params['recent_limit'] = String(args.recent_limit)
      return await clientFor(exec).getJson(`/api/chapters/${encodeURIComponent(args.chapter_id)}/work-brief`, params, exec.signal)
    },
  }))

    // ── scenes ────────────────────────────────────────────────────────────────────

  ctx.tools.register(defineTool({
    name: 'novel_scene',
    description:
      'Read the scene structure of a chapter, update one scene, and move a scene to another chapter ' +
      'or position. Structure is read-only; update and move are optimistic and require the current ' +
      'revision.',
    parameters: {
      action: { type: 'string', required: true, enum: ['structure', 'update', 'move'], description: 'Scene operation.' },
      scene_id: { type: 'string', description: 'Stable scene id from novel_scene(action="structure").' },
      expected_revision: { type: 'string', description: 'Fresh scene-structure revision used for CAS.' },
      title: { type: 'string', description: 'Optional scene title.' },
      story_time_sort_key: { type: 'string', description: 'Optional lexical story-time sort key.' },
      story_time_label: { type: 'string', description: 'Optional author-facing story-time label.' },
      characters: { type: 'array', items: { type: 'string' }, description: 'Character references; replaces the current list when supplied.' },
      locations: { type: 'array', items: { type: 'string' }, description: 'Location references; replaces the current list when supplied.' },
      events: { type: 'array', items: { type: 'string' }, description: 'Event references; replaces the current list when supplied.' },
      target_chapter_id: { type: 'string', description: 'Target chapter id (ch_<digits>).' },
      target_index: { type: 'integer', description: 'Zero-based scene position inside the target chapter.' },
      expected_source_revision: { type: 'string', description: 'Fresh source chapter revision.' },
      expected_target_revision: { type: 'string', description: 'Fresh target chapter revision.' },
    },
    output: { schema: JSON_OUTPUT_SCHEMA, render: (_args, value) => renderJson(value) },
    timeoutMs,
    isConcurrencySafe: args => ['structure'].includes(args.action),
    async execute(args, exec) {
      switch (args.action) {
        case 'structure': {
              return await clientFor(exec).getJson('/api/scenes', {}, exec.signal)
            
        }
        case 'update': {
        if (args.scene_id === undefined) throw new Error('scene_id is required for novel_scene(action="update")')
        if (args.expected_revision === undefined) throw new Error('expected_revision is required for novel_scene(action="update")')
              if (!args.scene_id.trim() || !args.expected_revision.trim()) throw new Error('scene_id and expected_revision must be non-empty')
              const body: JsonObject = { scene_id: args.scene_id, expected_revision: args.expected_revision }
              if (args.title !== undefined) body['title'] = args.title
              if (args.story_time_sort_key !== undefined) body['story_time_sort_key'] = args.story_time_sort_key
              if (args.story_time_label !== undefined) body['story_time_label'] = args.story_time_label
              if (args.characters !== undefined) body['characters'] = args.characters
              if (args.locations !== undefined) body['locations'] = args.locations
              if (args.events !== undefined) body['events'] = args.events
              return await clientFor(exec).postJson('/api/scenes/metadata', body, exec.signal)
            
        }
        case 'move': {
        if (args.scene_id === undefined) throw new Error('scene_id is required for novel_scene(action="move")')
        if (args.target_chapter_id === undefined) throw new Error('target_chapter_id is required for novel_scene(action="move")')
        if (args.target_index === undefined) throw new Error('target_index is required for novel_scene(action="move")')
        if (args.expected_revision === undefined) throw new Error('expected_revision is required for novel_scene(action="move")')
        if (args.expected_source_revision === undefined) throw new Error('expected_source_revision is required for novel_scene(action="move")')
        if (args.expected_target_revision === undefined) throw new Error('expected_target_revision is required for novel_scene(action="move")')
              if (!args.scene_id.trim() || !CHAPTER_ID_PATTERN.test(args.target_chapter_id)) throw new Error('scene_id and a valid target_chapter_id are required')
              if (!args.expected_revision.trim() || !args.expected_source_revision.trim() || !args.expected_target_revision.trim()) throw new Error('all scene and chapter revisions are required')
              return await clientFor(exec).postJson('/api/scenes/move', {
                scene_id: args.scene_id,
                target_chapter_id: args.target_chapter_id,
                target_index: args.target_index,
                expected_revision: args.expected_revision,
                expected_source_revision: args.expected_source_revision,
                expected_target_revision: args.expected_target_revision,
              }, exec.signal)
            
        }
        default: throw new Error(`novel_scene: unknown action ${String(args.action)}`)
      }
    },
  }))

  ctx.tools.register(defineTool({
    name: 'novel_chapter_scenes',
    description: 'Read the revision-labelled scene slice for one chapter.',
    parameters: {
      chapter_id: { type: 'string', required: true, description: 'Chapter id (ch_<digits>).' },
    },
    output: { schema: JSON_OUTPUT_SCHEMA, render: (_args, value) => renderJson(value) },
    timeoutMs,
    isConcurrencySafe: () => true,
    async execute(args, exec) {
      if (!CHAPTER_ID_PATTERN.test(args.chapter_id)) throw new Error(`chapter_id must match ch_<digits>, got "${args.chapter_id}"`)
      return await clientFor(exec).getJson(`/api/chapters/${encodeURIComponent(args.chapter_id)}/scenes`, {}, exec.signal)
    },
  }))

    // ── scene migration ───────────────────────────────────────────────────────────

  ctx.tools.register(defineTool({
    name: 'novel_scene_migration',
    description:
      'Preview, apply and roll back the paragraph-to-scene migration of one chapter. The preview is ' +
      'read-only; apply and rollback are guarded by the revisions the previous step reported.',
    parameters: {
      action: { type: 'string', required: true, enum: ['preview', 'apply', 'rollback'], description: 'Scene migration step; apply and rollback require the revision the previous step reported.' },
      expected_preview_revision: { type: 'string', description: 'Exact preview_revision from novel_scene_migration(action="preview").' },
      confirm: { type: 'boolean', description: 'Must be true after the author approves the preview.' },
      migration_id: { type: 'string', description: 'Migration id returned by novel_scene_migration(action="apply").' },
      expected_revision: { type: 'string', description: 'Fresh scene-structure revision used for CAS.' },
    },
    output: { schema: JSON_OUTPUT_SCHEMA, render: (_args, value) => renderJson(value) },
    timeoutMs,
    isConcurrencySafe: args => ['preview'].includes(args.action),
    async execute(args, exec) {
      switch (args.action) {
        case 'preview': {
              return await clientFor(exec).getJson('/api/scenes/migration-preview', {}, exec.signal)
            
        }
        case 'apply': {
        if (args.expected_preview_revision === undefined) throw new Error('expected_preview_revision is required for novel_scene_migration(action="apply")')
        if (args.confirm === undefined) throw new Error('confirm is required for novel_scene_migration(action="apply")')
              if (!args.expected_preview_revision.trim()) throw new Error('expected_preview_revision must be non-empty')
              if (args.confirm !== true) throw new Error('confirm must be true')
              return await clientFor(exec).postJson('/api/scenes/migration/apply', {
                expected_preview_revision: args.expected_preview_revision,
                confirm: true,
              }, exec.signal)
            
        }
        case 'rollback': {
        if (args.migration_id === undefined) throw new Error('migration_id is required for novel_scene_migration(action="rollback")')
        if (args.expected_revision === undefined) throw new Error('expected_revision is required for novel_scene_migration(action="rollback")')
              if (!args.migration_id.trim() || !args.expected_revision.trim()) throw new Error('migration_id and expected_revision must be non-empty')
              return await clientFor(exec).postJson('/api/scenes/migration/rollback', {
                migration_id: args.migration_id,
                expected_revision: args.expected_revision,
              }, exec.signal)
            
        }
        default: throw new Error(`novel_scene_migration: unknown action ${String(args.action)}`)
      }
    },
  }))

    // ── writing assets ────────────────────────────────────────────────────────────

  ctx.tools.register(defineTool({
    name: 'novel_assets',
    description:
      'List, read, create and update the writing assets of the current project (terminology, sample ' +
      'pools, character attribute groups and related records).',
    parameters: {
      action: { type: 'string', required: true, enum: ['list', 'read', 'create', 'update'], description: 'Writing-asset operation.' },
      kind: { type: 'string', enum: ['character', 'world', 'progression'], description: 'Restrict to one asset kind; omit to list all kinds.' },
      id: { type: 'string', description: 'Asset id; required for read/create/update. Must match [A-Za-z0-9][A-Za-z0-9_.-]{0,79}.' },
      data: { type: 'json', description: 'Object of asset fields (e.g. name, summary, aliases).' },
      body_markdown: { type: 'string', description: 'Markdown body (character/world assets).' },
      revision: { type: 'string', description: 'The asset revision fingerprint from a fresh novel_assets(action="list") call.' },
      raw_text: { type: 'string', description: 'Full replacement document text, validated by the server.' },
      related_mode: { type: 'string', enum: ['merge', 'replace'], description: 'Preserve and merge existing related entries by default; replace explicitly clears or replaces relations.' },
    },
    output: { schema: JSON_OUTPUT_SCHEMA, render: (_args, value) => renderJson(value) },
    timeoutMs,
    isConcurrencySafe: args => ['list', 'read'].includes(args.action),
    async execute(args, exec) {
      switch (args.action) {
        case 'list': {
              const client = clientFor(exec)
              return await client.getJson('/api/assets', { kind: args.kind ?? '' }, exec.signal)
            
        }
        case 'read': {
        if (args.kind === undefined) throw new Error('kind is required for novel_assets(action="read")')
        if (args.id === undefined) throw new Error(assetIdRequired('read'))
              const client = clientFor(exec)
              assertAssetId(args.id)
              return await client.getJson(`/api/assets/${args.kind}/${encodeURIComponent(args.id)}`, {}, exec.signal)
            
        }
        case 'create': {
        if (args.kind === undefined) throw new Error('kind is required for novel_assets(action="create")')
        if (args.id === undefined) throw new Error(assetIdRequired('create'))
              const client = clientFor(exec)
              assertAssetId(args.id)
              const body: JsonObject = { kind: args.kind as string, id: args.id }
              if (args.data !== undefined) body['data'] = args.data
              if (args.body_markdown !== undefined) body['body_markdown'] = args.body_markdown
              return await client.postJson('/api/assets', body, exec.signal)
            
        }
        case 'update': {
        if (args.kind === undefined) throw new Error('kind is required for novel_assets(action="update")')
        if (args.id === undefined) throw new Error(assetIdRequired('update'))
        if (args.revision === undefined) throw new Error('revision is required for novel_assets(action="update")')
              const client = clientFor(exec)
              assertAssetId(args.id)
              const body: JsonObject = { kind: args.kind as string, id: args.id, revision: args.revision }
              if (args.data !== undefined) body['data'] = args.data
              if (args.body_markdown !== undefined) body['body_markdown'] = args.body_markdown
              if (args.raw_text !== undefined) body['raw_text'] = args.raw_text
              if (args.related_mode !== undefined) body['related_mode'] = args.related_mode
              return await client.postJson('/api/assets/update', body, exec.signal)
            
        }
        default: throw new Error(`novel_assets: unknown action ${String(args.action)}`)
      }
    },
  }))

  ctx.tools.register(defineTool({
    name: 'novel_search',
    description: 'Search the novel project (semantic + exact match) across chapters, outline, and assets.',
    parameters: {
      q: { type: 'string', required: true, description: 'The search query.' },
      scope: { type: 'string', description: 'Search scope, e.g. "all" (default), "chapters", "outline", "assets".' },
      limit: { type: 'integer', description: 'Maximum number of results (server default 20).' },
    },
    output: { schema: JSON_OUTPUT_SCHEMA, render: (_args, value) => renderJson(value) },
    timeoutMs,
    isConcurrencySafe: () => true,
    async execute(args, exec) {
      const client = clientFor(exec)
      if (!args.q.trim()) throw new Error('q must be a non-empty string')
      const params: Record<string, string> = { q: args.q }
      if (args.scope !== undefined) params['scope'] = args.scope
      if (args.limit !== undefined) params['limit'] = String(args.limit)
      return await client.getJson('/api/search', params, exec.signal)
    },
  }))

    // ── project documents ─────────────────────────────────────────────────────────

  ctx.tools.register(defineTool({
    name: 'novel_doc',
    description:
      'Read, write and create the plain documents of the current project (notes, briefs and other ' +
      'author-owned files). Writes are optimistic and reject a stale version.',
    parameters: {
      action: { type: 'string', required: true, enum: ['read', 'write', 'create'], description: 'Document operation.' },
      path: { type: 'string', description: 'Document path relative to the novel data root (read/write). Writable roots are src/ and data/manuscript/; create derives its path from kind and name.' },
      content: { type: 'string', description: 'Full new document content (max 2 MB).' },
      version: { type: 'string', description: 'The version fingerprint from novel_doc(action="read") (optimistic lock).' },
      force: { type: 'boolean', description: 'Bypass the version check (default false).' },
      kind: { type: 'string', description: 'Document kind for create: "character" or "world" (the server derives the file path).' },
      name: { type: 'string', description: 'Document name.' },
      description: { type: 'string', description: 'Short description of the document.' },
    },
    output: { schema: JSON_OUTPUT_SCHEMA, render: (_args, value) => renderJson(value) },
    timeoutMs,
    isConcurrencySafe: args => ['read'].includes(args.action),
    async execute(args, exec) {
      switch (args.action) {
        case 'read': {
        if (args.path === undefined) throw new Error('path is required for novel_doc(action="read")')
              const client = clientFor(exec)
              if (!args.path.trim()) throw new Error('path must be a non-empty string')
              return await client.getJson('/api/document', { path: args.path }, exec.signal)
            
        }
        case 'write': {
        if (args.path === undefined) throw new Error('path is required for novel_doc(action="write")')
        if (args.content === undefined) throw new Error('content is required for novel_doc(action="write")')
              const client = clientFor(exec)
              if (!args.path.trim()) throw new Error('path must be a non-empty string')
              const writable = normalize(args.path.replaceAll('\\', '/')).replace(/^\.\//, '')
              if (!(writable.startsWith('src/') || writable.startsWith('data/manuscript/')) || !writable.toLowerCase().endsWith('.md')) {
                throw new Error('path must be a .md document under src/ or data/manuscript/; Studio does not write other locations')
              }
              // The server only CAS-checks when `version` is present, so omitting
              // it is an unlocked last-write-wins overwrite of an existing
              // document. `force` is the explicit bypass; require one or the
              // other rather than silently choosing "overwrite".
              if (args.version === undefined && args.force !== true) {
                throw new Error('version is required for novel_doc(action="write"); pass force=true to overwrite without a lock')
              }
              const body: JsonObject = { path: args.path, content: args.content }
              if (args.version !== undefined) body['version'] = args.version
              if (args.force !== undefined) body['force'] = args.force
              return await client.putJson('/api/document', body, exec.signal)
            
        }
        case 'create': {
        if (args.kind === undefined) throw new Error('kind is required for novel_doc(action="create")')
        if (args.name === undefined) throw new Error('name is required for novel_doc(action="create")')
              const client = clientFor(exec)
              if (!args.kind.trim() || !args.name.trim()) throw new Error('kind and name must be non-empty strings')
              if (args.kind !== 'character' && args.kind !== 'world') {
                throw new Error('kind must be "character" or "world" for novel_doc(action="create"); the server derives the document path from it')
              }
              const body: JsonObject = { kind: args.kind, name: args.name }
              if (args.description !== undefined) body['description'] = args.description
              return await client.postJson('/api/document/create', body, exec.signal)
            
        }
        default: throw new Error(`novel_doc: unknown action ${String(args.action)}`)
      }
    },
  }))

  // ── writes ─────────────────────────────────────────────────────────────

  ctx.tools.register(defineTool({
    name: 'novel_outline_edit',
    description:
      'Immediate compatibility write for an outline change the author has already authorized exactly; otherwise use ' +
      'novel_change_plan(action="structured"). Apply ONE atomic structural edit to the outline tree. Edits are revision-gated: ' +
      'read the current `revision` via novel_outline_read first and pass it back; the server ' +
      'rejects the edit with a conflict if the outline changed in between. ' +
      'Operations: "rename" (node_id + title), "update_summary" (node_id + summary), ' +
      '"add_child" (node_id = parent, + title/summary/kind), ' +
      '"add_after" (node_id = the node to insert after, + title/summary/kind; kind is either the ' +
      'target\'s own level - a sibling right after it - or the level its container accepts - its last ' +
      'child: a volume takes an act, an act a section, a section a chapter), ' +
      '"delete" (node_id, cascade=false keeps children), "promote" (remove a container), and ' +
      '"get_meta"/"set_meta" (chapter metadata, optionally updates[] for a batch).',
    parameters: {
      operation: { type: 'string', required: true, enum: ['rename', 'update_summary', 'add_child', 'add_after', 'delete', 'promote', 'get_meta', 'set_meta'], description: 'The structural operation to apply.' },
      cascade: { type: 'boolean', description: 'For delete, false removes only the container and keeps children and chapter IDs.' },
      metadata: { type: 'json', description: 'Field object for set_meta; use dramatic_position, content_focus, goals, target_words, word_budget, characters, settings, emotional_arc, beats, hooks, promise, payoff_of or function. Text fields (dramatic_position, content_focus, emotional_arc) take one line of text; word counts (target_words, word_budget) take a number. List fields (goals, beats, hooks, characters, settings, payoff_of, function) take an array of strings or one comma-separated string; promise accepts both too.' },
      chapter_id: { type: 'string', description: 'Chapter ID alias for node_id in get_meta/set_meta.' },
      updates: { type: 'json', description: 'Batch of 1-50 {chapter_id, metadata} objects for set_meta, or {chapter_id} for get_meta; one revision guards the whole batch.' },
      revision: { type: 'string', required: true, description: 'The outline revision fingerprint from a fresh novel_outline_read call.' },
      node_id: { type: 'string', description: 'Target node id (parent for add_child, the node to insert after for add_after); not needed for add_child at root.' },
      title: { type: 'string', description: 'Node title (rename / add_child / add_after).' },
      summary: { type: 'string', description: 'Node summary (update_summary / add_child / add_after).' },
      kind: { type: 'string', description: 'Node kind, e.g. "volume" or "chapter" (add_child / add_after). For add_after: the target\'s own level, or the level its container accepts (volume→act, act→section, section→chapter).' },
    },
    output: { schema: JSON_OUTPUT_SCHEMA, render: (_args, value) => renderJson(value) },
    timeoutMs,
    async execute(args, exec) {
      const client = clientFor(exec)
      const body: JsonObject = { operation: args.operation, revision: args.revision }
      if (args.node_id !== undefined) body['node_id'] = args.node_id
      if (args.title !== undefined) body['title'] = args.title
      if (args.summary !== undefined) body['summary'] = args.summary
      if (args.cascade !== undefined) body['cascade'] = args.cascade
      if (args.metadata !== undefined) body['metadata'] = args.metadata
      if (args.chapter_id !== undefined) body['chapter_id'] = args.chapter_id
      if (args.updates !== undefined) body['updates'] = args.updates
      if (args.kind !== undefined) body['kind'] = args.kind
      return await client.postJson('/api/outline/edit', body, exec.signal)
    },
  }))

            ctx.tools.register(defineTool({
    name: 'novel_write_chapter',
    description:
      'Queue a chapter write and immediately return a durable task_id. Poll novel_task(action="get") for progress/result. Omit chapter_id to write ' +
      'the outline-recommended next chapter; a given chapter_id must match the current recommendation. ' +
      'Preview context first with novel_context_preview and consult novel_outline_read for the recommendation. ' +
      'Cancel with novel_task(action="cancel"). Generated partial prose is retained; resume_from_draft continues it in a new run when the source/context revisions still match.',
    parameters: {
      dry_run: { type: 'boolean', description: 'Only assemble the current writer input and per-document sizes; no model call and no writing task. Guidance and target_words are included in this preview.' },
      run_id_v2: { type: 'string', description: 'Resume this completed draft without generating it again.' },
      resume_from_draft: { type: 'boolean', description: 'Resume the latest uncommitted draft for this chapter.' },
      target_words: { type: 'integer', description: 'Target word count, 200-50000. When omitted use the outline target, then default 3000.' },
      guidance: { type: 'string', description: 'Writing guidance for this chapter (plot beats, tone, POV notes).' },
      chapter_id: { type: 'string', description: 'Chapter id to write; must equal the current outline recommendation. Omit for the next chapter.' },
      temperature: { type: 'number', description: 'Sampling temperature (default 0.7).' },
      outline_revision: { type: 'string', description: 'Optional outline revision guard from novel_outline_read; the server rejects the write if the outline changed.' },
    },
    output: { schema: JSON_OUTPUT_SCHEMA, render: (_args, value) => renderJson(value) },
    timeoutMs,
    async execute(args, exec) {
      const client = clientFor(exec)
      const targetWords = args.target_words
      if (targetWords !== undefined && (!Number.isInteger(targetWords) || targetWords < 200 || targetWords > 50000)) {
        throw new Error(`target_words must be an integer between 200 and 50000, got ${String(args.target_words)}`)
      }
      const body: JsonObject = { guidance: args.guidance ?? '' }
      if (targetWords !== undefined) body['target_words'] = targetWords
      if (args.run_id_v2 !== undefined) body['run_id_v2'] = args.run_id_v2
      if (args.resume_from_draft !== undefined) body['resume_from_draft'] = args.resume_from_draft
      const chapterId = args.chapter_id?.trim()
      if (chapterId) body['chapter_id'] = chapterId
      if (args.temperature !== undefined) body['temperature'] = args.temperature
      if (args.outline_revision !== undefined) body['outline_revision'] = args.outline_revision
      if (args.dry_run === true) return await client.postJson('/api/write', { ...body, dry_run: true }, exec.signal)
      return await client.postJson('/api/tasks', { type: 'chapter_write', input: body }, exec.signal)
    },
  }))

  ctx.tools.register(defineTool({
    name: 'novel_review_chapter',
    description:
      'Run OpenWrite\'s multi-dimensional review on a drafted manuscript chapter (LONG-RUNNING). ' +
      'Pass either the manuscript path (e.g. "data/manuscript/ch_0007.md") or a chapter_id like "ch_0007".',
    parameters: {
      action: { type: 'string', enum: ['review', 'versions', 'compare'], description: 'Default review; versions lists saved reviews, compare compares a historical revision with the current review.' },
      revision: { type: 'string', description: 'Historical review revision for compare.' },
      path: { type: 'string', description: 'Manuscript path relative to the novel data root. Takes precedence over chapter_id.' },
      chapter_id: { type: 'string', description: 'Chapter id (ch_<digits>), resolved client-side to data/manuscript/<id>.md.' },
      strict: { type: 'boolean', description: 'Enable strict review mode (default false).' },
      dimensions: { type: 'array', items: { type: 'integer' }, description: 'Optional list of review dimension numbers (1-37) to restrict to.' },
      depth: { type: 'string', enum: ['quick', 'full'], description: 'Default full. Quick reviews coherence/canon/prose and safety only; scope_status=partial cannot approve full-chapter delivery. Do not combine quick with dimensions.' },
      domains: { type: 'array', items: { type: 'string' }, description: 'Review domain ids: coherence, character, plot, pacing, prose, canon. Use this or dimensions. Omitted domains remain explicitly unreviewed.' },
      dog_threshold: { type: 'integer', description: 'DoG aggregate score threshold (default 70); this does not change OpenWrite review.' },
    },
    output: { schema: JSON_OUTPUT_SCHEMA, render: (_args, value) => renderJson(value) },
    timeoutMs,
    async execute(args, exec) {
      const client = clientFor(exec)
      if (args.action === 'versions' || args.action === 'compare') {
        // "versions" lists saved reviews and needs no revision; only
        // "compare" needs one. An empty revision for compare is not "unset":
        // the store answers REVIEW_HISTORY_NOT_FOUND, so report the real cause
        // before sending the request.
        if (args.action === 'compare' && !args.revision?.trim()) {
          throw new Error('revision is required for novel_review_chapter(action="compare")')
        }
        return await client.postJson('/api/review/history', {
          action: args.action,
          chapter_id: reviewChapterId(args),
          revision: args.revision ?? '',
        }, exec.signal)
      }
      if (args.dimensions !== undefined && args.dimensions.some(value => !Number.isInteger(value) || value < 1 || value > 37)) {
        throw new Error('dimensions must contain only integers from 1 to 37')
      }
      const dogThreshold = args.dog_threshold ?? 70
      if (!Number.isInteger(dogThreshold) || dogThreshold < 0 || dogThreshold > 100) {
        throw new Error(`dog_threshold must be an integer between 0 and 100, got ${String(args.dog_threshold)}`)
      }
      const body: JsonObject = { path: resolveReviewPath(args) }
      if (args.strict !== undefined) body['strict'] = args.strict
      if (args.dimensions !== undefined) body['dimensions'] = args.dimensions
      if (args.depth !== undefined) body['depth'] = args.depth
      if (args.domains !== undefined) body['domains'] = args.domains
      const response = await client.postJson('/api/review', body, exec.signal)
      const value = response !== null && typeof response === 'object' && !Array.isArray(response)
        ? response as JsonObject
        : { result: response }
      let dogReview: JsonValue
      try {
        dogReview = await materializeDogReview(response, reviewChapterId(args), dogThreshold, client.context?.workspaceRoot)
      } catch (error) {
        dogReview = { status: 'unavailable', error: error instanceof Error ? error.message : String(error) }
      }
      let dogDelivery: JsonValue
      try {
        dogDelivery = await deliveryForResponse(client, response, reviewChapterId(args), exec.signal, dogThreshold)
      } catch (error) {
        dogDelivery = { status: 'unavailable', error: error instanceof Error ? error.message : String(error) }
      }
      return { ...value, dog_review: dogReview, dog_delivery: dogDelivery }
    },
  }))

    ctx.tools.register(defineTool({
    name: 'novel_foreshadowing',
    description:
      'Immediate compatibility write for a foreshadowing change the author has already authorized exactly; otherwise use ' +
      'novel_change_plan(action="structured"). Manage the foreshadowing DAG. action "create": node_id + content, optional weight (1-10, default 5), ' +
      'layer (default "支线"), target_chapter. action "update": node_id + status (e.g. planted/paid-off).',
    parameters: {
      action: { type: 'string', required: true, enum: ['create', 'update'], description: 'Create a new foreshadowing node or update an existing one.' },
      node_id: { type: 'string', required: true, description: 'Foreshadowing node id.' },
      content: { type: 'string', description: 'Node content (create).' },
      weight: { type: 'integer', description: 'Narrative weight 1-10 (create, default 5).' },
      layer: { type: 'string', description: 'Story layer, e.g. "主线" or "支线" (create, default "支线").' },
      target_chapter: { type: 'string', description: 'Chapter id the foreshadowing should pay off at (create).' },
      status: { type: 'string', description: 'New node status (update).' },
    },
    output: { schema: JSON_OUTPUT_SCHEMA, render: (_args, value) => renderJson(value) },
    timeoutMs,
    async execute(args, exec) {
      const client = clientFor(exec)
      if (!args.node_id.trim()) throw new Error('node_id must be a non-empty string')
      const body: JsonObject = { action: args.action, node_id: args.node_id }
      if (args.content !== undefined) body['content'] = args.content
      if (args.weight !== undefined) body['weight'] = args.weight
      if (args.layer !== undefined) body['layer'] = args.layer
      if (args.target_chapter !== undefined) body['target_chapter'] = args.target_chapter
      if (args.status !== undefined) body['status'] = args.status
      return await client.postJson('/api/foreshadowing', body, exec.signal)
    },
  }))

      // ── change plans ──────────────────────────────────────────────────────────────

  ctx.tools.register(defineTool({
    name: 'novel_change_plan',
    description:
      'Preview, apply, reject, retry and undo a change plan. document plans edit one project document ' +
      'as text; structured plans edit the manuscript model (outline, scenes, canon) as operations. ' +
      'Both are two-step: preview returns a token the follow-up step must present.',
    parameters: {
      action: { type: 'string', required: true, enum: ['document', 'structured'], description: 'Plan kind: document edits a project document, structured edits the manuscript model.' },
      step: { type: 'string', enum: ['preview', 'apply', 'reject', 'retry', 'undo'], description: 'Plan lifecycle step.' },
      confirm: { type: 'boolean', description: 'Required true for apply and undo after author acceptance.' },
      path: { type: 'string', description: 'Existing document path for preview, relative to the novel root.' },
      edits: { type: 'json', description: 'Preview edits: [{old_text,new_text}] or [{start_text,end_text,new_text,end_inclusive}]. Range end defaults to inclusive for compatibility; end_inclusive:false preserves the end anchor (e.g. the next heading).' },
      preview_token: { type: 'string', description: 'Immutable preview or undo token for apply/reject/retry/undo.' },
      change_kind: { type: 'string', enum: ['outline', 'asset', 'focus', 'foreshadowing', 'writing_targets'], description: 'Structured domain for a preview.' },
      change: { type: 'json', description: 'One direct-tool-shaped change object, required for preview.' },
    },
    output: { schema: JSON_OUTPUT_SCHEMA, render: (_args, value) => renderJson(value) },
    timeoutMs,
    isConcurrencySafe: () => false,
    async execute(args, exec) {
      switch (args.action) {
        case 'document': {
        if (args.step === undefined) throw new Error('step is required for novel_change_plan(action="document")')
              if (args.step === 'preview' && (!Array.isArray(args.edits) || (args.edits.length < 1 || args.edits.length > 50))) {
                throw new Error(
                  'preview requires between 1 and 50 edits ' +
                    `(received ${describeValue(args.edits)})`,
                )
              }
              if (args.step !== 'preview' && !args.preview_token?.trim()) {
                throw new Error(`${args.step} requires preview_token`)
              }
              if (['apply', 'undo'].includes(args.step) && args.confirm !== true) throw new Error('apply/undo requires confirm: true')
              const client = clientFor(exec)
              const body: JsonObject = { action: args.step }
              if (args.confirm !== undefined) body['confirm'] = args.confirm
              if (args.path !== undefined) body['path'] = args.path
              if (args.edits !== undefined) body['edits'] = args.edits
              if (args.preview_token !== undefined) body['preview_token'] = args.preview_token
              return await client.postJson('/api/document/change-plan', body, exec.signal)
            
        }
        case 'structured': {
        if (args.step === undefined) throw new Error('step is required for novel_change_plan(action="structured")')
              if (args.step === 'preview') {
                if (!args.change_kind) throw new Error('preview requires change_kind')
                if (args.change === null || typeof args.change !== 'object' || Array.isArray(args.change)) {
                  throw new Error(`preview requires one change object (received ${describeValue(args.change)})`)
                }
              } else if (!args.preview_token?.trim()) {
                throw new Error(`${args.step} requires preview_token`)
              }
              const client = clientFor(exec)
              const body: JsonObject = { action: args.step }
              if (args.change_kind !== undefined) body['change_kind'] = args.change_kind
              if (args.change !== undefined) body['change'] = args.change
              if (args.preview_token !== undefined) body['preview_token'] = args.preview_token
              return await client.postJson('/api/structured/change-plan', body, exec.signal)
            
        }
        default: throw new Error(`novel_change_plan: unknown action ${String(args.action)}`)
      }
    },
  }))

    ctx.tools.register(defineTool({
    name: 'novel_focus',
    description: 'Immediate compatibility write for a focus change the author has already authorized exactly; otherwise use novel_change_plan(action="structured"). Set the writing focus compass for the project.',
    parameters: {
      goal: { type: 'string', required: true, description: 'The current writing goal.' },
      must_keep: { type: 'array', items: { type: 'string' }, description: 'Constraints that must be kept.' },
      must_avoid: { type: 'array', items: { type: 'string' }, description: 'Things that must be avoided.' },
      notes: { type: 'array', items: { type: 'string' }, description: 'Free-form focus notes.' },
    },
    output: { schema: JSON_OUTPUT_SCHEMA, render: (_args, value) => renderJson(value) },
    timeoutMs,
    async execute(args, exec) {
      const client = clientFor(exec)
      const body: JsonObject = { goal: args.goal }
      if (args.must_keep !== undefined) body['must_keep'] = args.must_keep
      if (args.must_avoid !== undefined) body['must_avoid'] = args.must_avoid
      if (args.notes !== undefined) body['notes'] = args.notes
      return await client.postJson('/api/focus', body, exec.signal)
    },
  }))

    // ── export ────────────────────────────────────────────────────────────────────

  ctx.tools.register(defineTool({
    name: 'novel_export',
    description:
      'Preflight and run a manuscript export. Preflight validates the selection, purpose and format ' +
      'and returns a revision the export must present.',
    parameters: {
      action: { type: 'string', required: true, enum: ['preflight', 'export'], description: 'Export step; preflight reports what would be written without writing it.' },
      format: { type: 'string', enum: ['md', 'txt', 'epub'], description: 'Export format (default "md").' },
      purpose: { type: 'string', enum: ['backup', 'delivery', 'personal_archive'], description: 'Export purpose (default "delivery"). personal_archive preserves author copies with gate findings recorded as warnings.' },
      preflight_revision: { type: 'string', description: 'Revision returned by novel_export(action="preflight") for the same format and purpose.' },
    },
    output: { schema: JSON_OUTPUT_SCHEMA, render: (_args, value) => renderJson(value) },
    timeoutMs,
    isConcurrencySafe: args => ['preflight'].includes(args.action),
    async execute(args, exec) {
      switch (args.action) {
        case 'preflight': {
              const client = clientFor(exec)
              return await client.getJson('/api/export/preflight', {
                format: args.format ?? 'md',
                purpose: args.purpose ?? 'delivery',
              }, exec.signal)
            
        }
        case 'export': {
              const client = clientFor(exec)
              const format = args.format ?? 'md'
              const purpose = args.purpose ?? 'delivery'
              const download = await client.download('/api/export', {
                format,
                purpose,
                ...(args.preflight_revision === undefined ? {} : { preflight_revision: args.preflight_revision }),
              }, exec.signal)
              const filename = exportFilename(download.filename, `novel.${format}`)
              const exportDir = outputDirFor(outputDir, client)
              await mkdir(exportDir, { recursive: true })
              const path = join(exportDir, filename)
              await writeFile(path, download.content)
              return { path, filename, format, bytes: download.content.byteLength }
            
        }
        default: throw new Error(`novel_export: unknown action ${String(args.action)}`)
      }
    },
  }))

    // ── assets: create / read / packages ────────────────────────────────────

        // ── asset packages ────────────────────────────────────────────────────────────

  ctx.tools.register(defineTool({
    name: 'novel_assets_package',
    description:
      'Export the project assets into a portable package, preview a package before importing it, and ' +
      'import a reviewed package with explicit dependency resolutions.',
    parameters: {
      action: { type: 'string', required: true, enum: ['export', 'preview', 'import'], description: 'Asset package operation.' },
      selections: { type: 'array', items: { type: 'string' }, description: 'Asset selectors in "kind:id" form, e.g. ["character:hero", "world:capital"].' },
      package_base64: { type: 'string', description: 'Base64-encoded .owasset.zip package (max 25 MB decoded).' },
      upload_id: { type: 'string', description: 'The upload_id returned by novel_assets_package(action="preview").' },
      package_sha256: { type: 'string', description: 'Package digest. Required for import: pass the package_sha256 returned by action="preview"; the server rejects an import without it as a stale package.' },
      resolutions: { type: 'json', description: 'Object mapping conflicting asset keys to resolutions.' },
      allow_missing_dependencies: { type: 'boolean', description: 'Allow import despite missing asset dependencies (default false).' },
    },
    output: { schema: JSON_OUTPUT_SCHEMA, render: (_args, value) => renderJson(value) },
    timeoutMs,
    // `export` writes a local archive (non-atomic `writeFile` to a fixed name),
    // so it must be serialized; `preview` is the server-side read-only action.
    isConcurrencySafe: args => args.action === 'preview',
    async execute(args, exec) {
      switch (args.action) {
        case 'export': {
              const client = clientFor(exec)
              const selections = args.selections ?? []
              for (const item of selections) {
                if (!/^(character|world|progression):[A-Za-z0-9][A-Za-z0-9_.-]{0,79}$/.test(item)) {
                  throw new Error(`invalid asset selection "${item}"; expected "kind:id"`)
                }
              }
              const download = await client.download('/api/assets/package/export', { select: selections }, exec.signal)
              const filename = exportFilename(download.filename, 'assets.owasset.zip')
              const exportDir = outputDirFor(outputDir, client)
              await mkdir(exportDir, { recursive: true })
              const path = join(exportDir, filename)
              await writeFile(path, download.content)
              return { path, filename, bytes: download.content.byteLength }
            
        }
        case 'preview': {
        if (args.package_base64 === undefined) throw new Error('package_base64 is required for novel_assets_package(action="preview")')
              const client = clientFor(exec)
              if (!args.package_base64.trim()) throw new Error('package_base64 must be a non-empty string')
              return await client.postJson('/api/assets/package/preview', { package_base64: args.package_base64 }, exec.signal)
            
        }
        case 'import': {
        if (args.upload_id === undefined) throw new Error('upload_id is required for novel_assets_package(action="import")')
              const client = clientFor(exec)
              // The server treats a missing digest as a stale package, so an
              // import without the preview digest always fails with
              // ASSET_PACKAGE_CONFLICT. Require it and name the fix here.
              if (!args.package_sha256?.trim()) {
                throw new Error('package_sha256 is required for novel_assets_package(action="import"); pass the package_sha256 returned by action="preview"')
              }
              const body: JsonObject = { upload_id: args.upload_id }
              if (args.package_sha256 !== undefined) body['package_sha256'] = args.package_sha256
              if (args.resolutions !== undefined) body['resolutions'] = args.resolutions
              if (args.allow_missing_dependencies !== undefined) body['allow_missing_dependencies'] = args.allow_missing_dependencies
              return await client.postJson('/api/assets/package/import', body, exec.signal)
            
        }
        default: throw new Error(`novel_assets_package: unknown action ${String(args.action)}`)
      }
    },
  }))

      // ── revisions ────────────────────────────────────────────────────────────

    // ── revisions ─────────────────────────────────────────────────────────────────

  ctx.tools.register(defineTool({
    name: 'novel_revision',
    description:
      'List, inspect, create, regenerate, apply and reject revision proposals for a chapter. Create ' +
      'builds a proposal from review issues (source=review) or from an explicit text selection ' +
      '(source=selection); apply writes the accepted hunks into the manuscript.',
    parameters: {
      action: { type: 'string', required: true, enum: ['list', 'get', 'create', 'regenerate', 'apply', 'reject'], description: 'Revision operation; create reads its source from the source parameter.' },
      chapter: { type: 'string', description: 'Chapter id filter (e.g. "ch_0007").' },
      status: { type: 'string', description: 'Status filter (e.g. "proposed", "applied", "rejected").' },
      proposal_id: { type: 'string', description: 'Revision proposal id (rev_*).' },
      source: { type: 'string', enum: ['review', 'selection'], description: 'Create source: review (default) fixes review issues, selection revises an explicit text range.' },
      chapter_id: { type: 'string', description: 'Chapter id (ch_<digits>).' },
      issue_ids: { type: 'array', items: { type: 'string' }, description: 'Review issue ids to fix; required for create with source="review".' },
      selection: { type: 'object', additionalProperties: false, description: 'Optional exact saved-text range in Unicode code points; preserve raw CR/LF characters.', properties: {
        start: { type: 'integer', description: 'Inclusive source code-point offset.' },
        end: { type: 'integer', description: 'Exclusive source code-point offset.' },
        original_text: { type: 'string', required: true, description: 'Exact saved text inside this range.' },
      } },
      instruction: { type: 'string', description: 'Additional revision instruction.' },
      target_units: { type: 'integer', description: 'Target length in writing units (0 = keep similar).' },
      expected_review_revision: { type: 'string', description: 'Exact review file revision from the chapter work brief.' },
      expected_document_revision: { type: 'string', description: 'Exact manuscript revision from the chapter work brief.' },
      start: { type: 'integer', description: 'Selection start offset.' },
      end: { type: 'integer', description: 'Selection end offset.' },
      original_text: { type: 'string', description: 'The selected original text.' },
      mode: { type: 'string', enum: ['rewrite', 'expand', 'compress', 'pace', 'dialogue', 'naturalize', 'custom'], description: 'Revision mode (default "rewrite").' },
      full_chapter: { type: 'boolean', description: 'Treat the whole chapter as the selection (default false).' },
      replacement_text: { type: 'string', description: 'Replacement text overriding the proposal.' },
      selected_hunk_ids: { type: 'array', items: { type: 'string' }, description: 'Apply only these diff hunk ids.' },
    },
    output: { schema: JSON_OUTPUT_SCHEMA, render: (_args, value) => renderJson(value) },
    timeoutMs,
    isConcurrencySafe: args => ['list', 'get'].includes(args.action),
    async execute(args, exec) {
      switch (args.action) {
        case 'list': {
              const client = clientFor(exec)
              const params: Record<string, string> = {}
              if (args.chapter !== undefined) params['chapter'] = args.chapter
              if (args.status !== undefined) params['status'] = args.status
              return await client.getJson('/api/revisions', params, exec.signal)
            
        }
        case 'get': {
        if (args.proposal_id === undefined) throw new Error('proposal_id is required for novel_revision(action="get")')
              const client = clientFor(exec)
              if (!/^rev_[A-Za-z0-9_-]+$/.test(args.proposal_id)) throw new Error(`invalid proposal_id "${args.proposal_id}"`)
              return await client.getJson(`/api/revisions/${encodeURIComponent(args.proposal_id)}`, {}, exec.signal)
            
        }
        case 'create': {
        if (args.chapter_id === undefined) throw new Error('chapter_id is required for novel_revision(action="create")')
        // source=selection keeps the pre-merge create-from-selection contract;
        // anything else (including an omitted source) stays on from-review.
        if (args.source === 'selection') {
        if (args.chapter_id === undefined) throw new Error('chapter_id is required for novel_revision(action="create", source="selection")')
        if (args.start === undefined) throw new Error('start is required for novel_revision(action="create", source="selection")')
        if (args.end === undefined) throw new Error('end is required for novel_revision(action="create", source="selection")')
              const client = clientFor(exec)
              if (!CHAPTER_ID_PATTERN.test(args.chapter_id)) throw new Error(`chapter_id must match ch_<digits>, got "${args.chapter_id}"`)
              const body: JsonObject = { chapter_id: args.chapter_id, start: args.start, end: args.end }
              if (args.original_text !== undefined) body['original_text'] = args.original_text
              if (args.expected_document_revision !== undefined) body['expected_document_revision'] = args.expected_document_revision
              if (args.instruction !== undefined) body['instruction'] = args.instruction
              if (args.mode !== undefined) body['action'] = args.mode
              if (args.target_units !== undefined) body['target_units'] = args.target_units
              if (args.full_chapter !== undefined) body['full_chapter'] = args.full_chapter
              return await client.postJson('/api/revisions/selection', body, exec.signal)
            
        }
        if (args.source !== undefined && args.source !== 'review' && args.source !== 'selection') {
          throw new Error(`source must be "review" or "selection", got "${args.source}"`)
        }
        if (args.issue_ids === undefined) throw new Error('issue_ids is required for novel_revision(action="create", source="review")')
              const client = clientFor(exec)
              if (!CHAPTER_ID_PATTERN.test(args.chapter_id)) throw new Error(`chapter_id must match ch_<digits>, got "${args.chapter_id}"`)
              if (args.issue_ids.length === 0) throw new Error('issue_ids must be a non-empty array')
              const body: JsonObject = { chapter_id: args.chapter_id, issue_ids: args.issue_ids }
              if (args.selection !== undefined) body['selection'] = args.selection
              if (args.instruction !== undefined) body['instruction'] = args.instruction
              if (args.target_units !== undefined) body['target_units'] = args.target_units
              if (args.expected_review_revision !== undefined) body['expected_review_revision'] = args.expected_review_revision
              if (args.expected_document_revision !== undefined) body['expected_document_revision'] = args.expected_document_revision
              const response = await client.postJson('/api/revisions/from-review', body, exec.signal)
              try {
                return { ...objectValue(response), dog_delivery: await deliveryForResponse(client, response, args.chapter_id, exec.signal) }
              } catch (error) {
                return { ...objectValue(response), dog_delivery: { status: 'unavailable', error: error instanceof Error ? error.message : String(error) } }
              }
            
        }
        case 'regenerate': {
        if (args.proposal_id === undefined) throw new Error('proposal_id is required for novel_revision(action="regenerate")')
              const client = clientFor(exec)
              if (!/^rev_[A-Za-z0-9_-]+$/.test(args.proposal_id)) throw new Error(`invalid proposal_id "${args.proposal_id}"`)
              const response = await client.postJson(`/api/revisions/${encodeURIComponent(args.proposal_id)}/regenerate`, {}, exec.signal)
              const chapterId = String(objectValue(response)['chapter_id'] ?? '')
              try {
                return { ...objectValue(response), dog_delivery: await deliveryForResponse(client, response, chapterId, exec.signal) }
              } catch (error) {
                return { ...objectValue(response), dog_delivery: { status: 'unavailable', error: error instanceof Error ? error.message : String(error) } }
              }
            
        }
        case 'apply': {
        if (args.proposal_id === undefined) throw new Error('proposal_id is required for novel_revision(action="apply")')
              const client = clientFor(exec)
              if (!/^rev_[A-Za-z0-9_-]+$/.test(args.proposal_id)) throw new Error(`invalid proposal_id "${args.proposal_id}"`)
              const body: JsonObject = {}
              if (args.replacement_text !== undefined) body['replacement_text'] = args.replacement_text
              if (args.selected_hunk_ids !== undefined) body['selected_hunk_ids'] = args.selected_hunk_ids
              const response = await client.postJson(`/api/revisions/${encodeURIComponent(args.proposal_id)}/apply`, body, exec.signal)
              const responseValue = objectValue(response)
              const proposal = objectValue(responseValue['proposal'] ?? response)
              const chapterId = String(proposal['chapter_id'] ?? '')
              try {
                return { ...objectValue(response), dog_delivery: await deliveryForResponse(client, response, chapterId, exec.signal) }
              } catch (error) {
                return { ...objectValue(response), dog_delivery: { status: 'unavailable', error: error instanceof Error ? error.message : String(error) } }
              }
            
        }
        case 'reject': {
        if (args.proposal_id === undefined) throw new Error('proposal_id is required for novel_revision(action="reject")')
              const client = clientFor(exec)
              if (!/^rev_[A-Za-z0-9_-]+$/.test(args.proposal_id)) throw new Error(`invalid proposal_id "${args.proposal_id}"`)
              const response = await client.postJson(`/api/revisions/${encodeURIComponent(args.proposal_id)}/reject`, {}, exec.signal)
              const chapterId = String(objectValue(response)['chapter_id'] ?? '')
              try {
                return { ...objectValue(response), dog_delivery: await deliveryForResponse(client, response, chapterId, exec.signal) }
              } catch (error) {
                return { ...objectValue(response), dog_delivery: { status: 'unavailable', error: error instanceof Error ? error.message : String(error) } }
              }
            
        }
        default: throw new Error(`novel_revision: unknown action ${String(args.action)}`)
      }
    },
  }))

              // ── background tasks ─────────────────────────────────────────────────────

        // ── background tasks ──────────────────────────────────────────────────────────

  ctx.tools.register(defineTool({
    name: 'novel_task',
    description:
      'Queue a background AI task and return immediately; poll with get or list. Task types and their ' +
      '`input` keys: chapter_write {chapter_id?, guidance?, target_words?, temperature?, outline_revision?}; ' +
      'chapter_review {chapter_id | path, strict?, dimensions?}; revision_selection / revision_from_review ' +
      '(same inputs as the novel_revision create action); source_operation / reference_operation (same ' +
      'inputs as novel_source_action / novel_reference_library_action); manuscript_import (same input as ' +
      'novel_import); research {prompt, search?, language?, quality? (advisory|balanced|strict), llm?}; manuscript_reconcile (durable ' +
      'acceptance analysis; usually started through novel_manuscript_acceptance_reconcile); settle_backfill ' +
      '{chapter_ids?, only_missing?} - prefer the novel_settle_backfill convenience tool; continuous_write ' +
      '- prefer the novel_multi_write convenience tool.',
    parameters: {
      action: { type: 'string', required: true, enum: ['create', 'get', 'list', 'cancel', 'confirm', 'retry'], description: 'Task operation; long-running work returns a task id immediately. confirm resumes a paused run and returns a continuation task: poll the returned task_id; re-confirming the paused task is idempotent.' },
      type: {
        type: 'string',
        enum: ['chapter_write', 'chapter_review', 'revision_selection', 'revision_from_review', 'source_operation', 'reference_operation', 'manuscript_import', 'manuscript_reconcile', 'continuous_write', 'research', 'settle_backfill'],
        description: 'Task type; required for create.',
      },
      input: { type: 'json', description: 'Task input object; required for create. Shape depends on the task type (see description).' },
      task_id: { type: 'string', description: 'Task id (tsk_*).' },
      since: { type: 'string', description: 'ISO timestamp filter for requests whose response was lost.' },
      limit: { type: 'integer', description: 'Maximum number of tasks (server default 100).' },
      wait_seconds: { type: 'number', description: 'Wait up to 30 seconds for actual cancellation; running model calls may finish later.' },
    },
    output: { schema: JSON_OUTPUT_SCHEMA, render: (_args, value) => renderJson(value) },
    timeoutMs,
    isConcurrencySafe: args => ['list'].includes(args.action),
    async execute(args, exec) {
      switch (args.action) {
        case 'create': {
        if (args.type === undefined) throw new Error('type is required for novel_task(action="create")')
        if (args.input === undefined) throw new Error('input is required for novel_task(action="create")')
              const client = clientFor(exec)
              if (typeof args.input !== 'object' || args.input === null || Array.isArray(args.input)) {
                throw new Error('input must be a JSON object')
              }
              return await client.postJson('/api/tasks', { type: args.type, input: args.input }, exec.signal)
            
        }
        case 'get': {
        if (args.task_id === undefined) throw new Error('task_id is required for novel_task(action="get")')
              const client = clientFor(exec)
              if (!/^tsk_[A-Za-z0-9_-]+$/.test(args.task_id)) throw new Error(`invalid task_id "${args.task_id}"`)
              const response = await client.getJson(`/api/tasks/${encodeURIComponent(args.task_id)}`, {}, exec.signal)
              const responseRecord = response !== null && typeof response === 'object' && !Array.isArray(response)
                ? response as JsonObject
                : {}
              const taskValue = responseRecord['task'] ?? response
              const taskRecord = taskValue !== null && typeof taskValue === 'object' && !Array.isArray(taskValue)
                ? taskValue as JsonObject
                : {}
              if (taskRecord['status'] !== 'completed') return response
              const taskType = String(taskRecord['type'] ?? '')
              if (!['chapter_write', 'chapter_review', 'revision_from_review'].includes(taskType)) return response
              const taskResult = objectValue(taskRecord['result'])
              const taskInput = objectValue(taskRecord['input'])
              const chapterId = String(taskRecord['chapter_id'] ?? taskResult['chapter_id'] ?? '').trim()
                || String(taskInput['path'] ?? '').match(/(?:^|\/)(ch_\d+)\.md$/)?.[1]
                || ''
              const value = response !== null && typeof response === 'object' && !Array.isArray(response)
                ? response as JsonObject
                : { task: response }
              if (!/^ch_\d+$/.test(chapterId)) {
                return { ...value, dog_delivery: { status: 'unavailable', error: 'completed chapter task lacks a resolvable chapter id' } }
              }
              let workspace: JsonValue
              try {
                workspace = await client.getJson('/api/workspace', {}, exec.signal)
              } catch (error) {
                const unavailable = { status: 'unavailable', error: error instanceof Error ? error.message : String(error) }
                return taskType === 'chapter_review'
                  ? { ...value, dog_review: unavailable, dog_delivery: unavailable }
                  : { ...value, dog_delivery: unavailable }
              }
              let dogDelivery: JsonValue
              try {
                dogDelivery = await materializeChapterDelivery(workspace, chapterId, undefined, client.context?.workspaceRoot)
              } catch (error) {
                dogDelivery = { status: 'unavailable', error: error instanceof Error ? error.message : String(error) }
              }
              if (taskType !== 'chapter_review') return { ...value, dog_delivery: dogDelivery }
              let dogReview: JsonValue
              try {
                const framework = await client.getJson('/api/review/framework', {}, exec.signal)
                // Pass the threshold through rather than hardcoding 70: the
                // manifest's threshold feeds deliveryStatus, so a caller who
                // asked for another value must not silently get the default.
                // `undefined` makes the materializer read it back from the
                // persisted delivery.json, exactly as the direct path does.
                dogReview = await materializeCompletedDogTaskReview(response, workspace, framework, undefined, client.context?.workspaceRoot) ?? { status: 'unavailable', error: 'review task was not materialized' }
              } catch (error) {
                dogReview = { status: 'unavailable', error: error instanceof Error ? error.message : String(error) }
              }
              return { ...value, dog_review: dogReview, dog_delivery: dogDelivery }
            
        }
        case 'list': {
              const client = clientFor(exec)
              const params: Record<string, string> = {}
              if (args.since !== undefined) params['since'] = args.since
              if (args.limit !== undefined) params['limit'] = String(args.limit)
              return await client.getJson('/api/tasks', params, exec.signal)
            
        }
        case 'cancel': {
        if (args.task_id === undefined) throw new Error('task_id is required for novel_task(action="cancel")')
              const client = clientFor(exec)
              if (!/^tsk_[A-Za-z0-9_-]+$/.test(args.task_id)) throw new Error(`invalid task_id "${args.task_id}"`)
              return await client.postJson(`/api/tasks/${encodeURIComponent(args.task_id)}/cancel`, { wait_seconds: args.wait_seconds ?? 0 }, exec.signal)
            
        }
        case 'confirm': {
        if (args.task_id === undefined) throw new Error('task_id is required for novel_task(action="confirm")')
              const client = clientFor(exec)
              if (!/^tsk_[A-Za-z0-9_-]+$/.test(args.task_id)) throw new Error(`invalid task_id "${args.task_id}"`)
              return await client.postJson(`/api/tasks/${encodeURIComponent(args.task_id)}/confirm`, {}, exec.signal)
            
        }
        case 'retry': {
        if (args.task_id === undefined) throw new Error('task_id is required for novel_task(action="retry")')
              const client = clientFor(exec)
              if (!/^tsk_[A-Za-z0-9_-]+$/.test(args.task_id)) throw new Error(`invalid task_id "${args.task_id}"`)
              return await client.postJson(`/api/tasks/${encodeURIComponent(args.task_id)}/retry`, {}, exec.signal)
            
        }
        default: throw new Error(`novel_task: unknown action ${String(args.action)}`)
      }
    },
  }))

        ctx.tools.register(defineTool({
    name: 'novel_multi_write',
    description:
      'Queue a BACKGROUND continuous-writing run: writes up to max_chapters chapters following the outline, ' +
      'reviewing each; stops early on review blockers, continuity errors, low scores, or budget limits. ' +
      'Returns immediately with a task id — poll with novel_task(action="get"). A paused run is resumed with novel_task(action="confirm"), which returns a continuation task: poll that returned task_id. Confirming the same paused task again is idempotent.',
    parameters: {
      max_chapters: { type: 'integer', description: 'Chapters to write, 1-10 (default 1).' },
      minimum_review_score: { type: 'integer', description: 'Stop when a chapter scores below this, 0-100 (default 82).' },
      max_tokens: { type: 'integer', description: 'Token budget, 0 = unlimited (default 0).' },
      max_failures: { type: 'integer', description: 'Stop after this many consecutive failures, 1-10 (default 2).' },
      max_cost_usd: { type: 'number', description: 'Cost budget in USD, 0 = unlimited (default 0).' },
      guidance: { type: 'string', description: 'Writing guidance applied to every chapter.' },
      target_words: { type: 'integer', description: 'Target words per chapter (falls back to the outline recommendation).' },
      temperature: { type: 'number', description: 'Sampling temperature (default 0.7).' },
      stop_on_blocker: { type: 'boolean', description: 'Stop when a review reports a blocker issue (default true).' },
      stop_on_continuity_error: { type: 'boolean', description: 'Stop on high-severity continuity issues (default true).' },
      require_confirmation_after_each_chapter: { type: 'boolean', description: 'Pause for novel_task(action="confirm") after each chapter (default false).' },
    },
    output: { schema: JSON_OUTPUT_SCHEMA, render: (_args, value) => renderJson(value) },
    timeoutMs,
    async execute(args, exec) {
      const client = clientFor(exec)
      const input: JsonObject = {}
      if (args.max_chapters !== undefined) input['max_chapters'] = args.max_chapters
      if (args.minimum_review_score !== undefined) input['minimum_review_score'] = args.minimum_review_score
      if (args.max_tokens !== undefined) input['max_tokens'] = args.max_tokens
      if (args.max_failures !== undefined) input['max_failures'] = args.max_failures
      if (args.max_cost_usd !== undefined) input['max_cost_usd'] = args.max_cost_usd
      if (args.guidance !== undefined) input['guidance'] = args.guidance
      if (args.target_words !== undefined) input['target_words'] = args.target_words
      if (args.temperature !== undefined) input['temperature'] = args.temperature
      if (args.stop_on_blocker !== undefined) input['stop_on_blocker'] = args.stop_on_blocker
      if (args.stop_on_continuity_error !== undefined) input['stop_on_continuity_error'] = args.stop_on_continuity_error
      if (args.require_confirmation_after_each_chapter !== undefined) input['require_confirmation_after_each_chapter'] = args.require_confirmation_after_each_chapter
      return await client.postJson('/api/tasks', { type: 'continuous_write', input }, exec.signal)
    },
  }))

  // ── project lifecycle ────────────────────────────────────────────────────

    // ── projects ──────────────────────────────────────────────────────────────────

  ctx.tools.register(defineTool({
    name: 'novel_project',
    description:
      'Initialize, open and delete a novel project, and manage its archive packages (list, get, ' +
      'create, restore preview, restore, download). Archiving never touches the live project.',
    parameters: {
      action: { type: 'string', required: true, enum: ['init', 'open', 'delete', 'archive', 'download'], description: 'Project operation.' },
      novel_id: { type: 'string', description: 'Project id, e.g. "my_novel" (2-64 chars: letters, digits, "-", "_").' },
      title: { type: 'string', description: 'Book title (max 120 characters).' },
      author: { type: 'string', description: 'Author credit for delivery export (max 120 characters).' },
      language: { type: 'string', description: 'Book language tag, e.g. zh-CN or en (default zh-CN).' },
      project_path: { type: 'string', description: 'Target directory on the server; omit to use the server default location.' },
      template: { type: 'string', enum: ['default', 'demo_short'], description: 'Project template (default "default").' },
      confirm_novel_id: { type: 'string', description: 'Must exactly equal the project\'s novel_id (from its novel_config.yaml).' },
      archive_op: { type: 'string', enum: ['preflight', 'list', 'get', 'create', 'restore_preview', 'restore'], description: 'Archive lifecycle operation.' },
      archive_id: { type: 'string', description: 'Archive id shaped owa_<24 lowercase hex>.' },
      expected_preflight_revision: { type: 'string', description: 'Current archive preflight revision for create.' },
      target_root: { type: 'string', description: 'Absolute new or empty project directory for restore.' },
      target_novel_id: { type: 'string', description: 'Optional restored novel id.' },
      reference_policy: { type: 'string', enum: ['preserve_relative', 'rewrite_novel_id'], description: 'Reference handling during restore.' },
      archive_sha256: { type: 'string', description: 'Checksum returned by restore_preview.' },
      confirm: { type: 'boolean', description: 'Must be true for restore.' },
    },
    output: { schema: JSON_OUTPUT_SCHEMA, render: (_args, value) => renderJson(value) },
    timeoutMs,
    isConcurrencySafe: () => false,
    async execute(args, exec) {
      switch (args.action) {
        case 'init': {
        if (args.novel_id === undefined) throw new Error('novel_id is required for novel_project(action="init")')
        if (args.title === undefined) throw new Error('title is required for novel_project(action="init")')
              const client = clientFor(exec)
              if (!/^[A-Za-z0-9][A-Za-z0-9_-]{1,63}$/.test(args.novel_id)) {
                throw new Error('novel_id must be 2-64 chars of letters, digits, "-" or "_"')
              }
              if (!args.title.trim() || args.title.length > 120) throw new Error('title must be non-empty and at most 120 characters')
              const body: JsonObject = { novel_id: args.novel_id, title: args.title }
              if (args.author !== undefined) body['author'] = args.author
              if (args.language !== undefined) body['language'] = args.language
              if (args.project_path !== undefined) body['project_path'] = args.project_path
              if (args.template !== undefined) body['template'] = args.template
              return await client.postJson('/api/project/init', body, exec.signal)
            
        }
        case 'open': {
        if (args.project_path === undefined) throw new Error('project_path is required for novel_project(action="open")')
              const client = clientFor(exec)
              if (!args.project_path.trim()) throw new Error('project_path must be a non-empty string')
              return await client.postJson('/api/project/open', { project_path: args.project_path }, exec.signal)
            
        }
        case 'delete': {
        if (args.project_path === undefined) throw new Error('project_path is required for novel_project(action="delete")')
        if (args.confirm_novel_id === undefined) throw new Error('confirm_novel_id is required for novel_project(action="delete")')
              const client = clientFor(exec)
              if (!args.project_path.trim() || !args.confirm_novel_id.trim()) throw new Error('project_path and confirm are required')
              return await client.postJson('/api/project/delete', { project_path: args.project_path, confirm: args.confirm_novel_id }, exec.signal)
            
        }
        case 'archive': {
        if (args.archive_op === undefined) throw new Error('archive_op is required for novel_project(action="archive")')
              const client = clientFor(exec)
              if (args.archive_op === 'preflight') return await client.getJson('/api/project-archives/preflight', {}, exec.signal)
              if (args.archive_op === 'list') return await client.getJson('/api/project-archives', {}, exec.signal)
              if (args.archive_op === 'create') {
                if (!args.expected_preflight_revision?.trim()) throw new Error('create requires expected_preflight_revision')
                return await client.postJson('/api/project-archives/create', {
                  expected_preflight_revision: args.expected_preflight_revision,
                }, exec.signal)
              }
              const archiveId = args.archive_id?.trim()
              if (!archiveId || !/^owa_[0-9a-f]{24}$/.test(archiveId)) throw new Error(`${args.archive_op} requires a valid archive_id`)
              if (args.archive_op === 'get') return await client.getJson(`/api/project-archives/${archiveId}`, {}, exec.signal)
              if (!args.target_root?.trim()) throw new Error(`${args.archive_op} requires target_root`)
              const body: JsonObject = {
                archive_id: archiveId,
                target_root: args.target_root,
                reference_policy: args.reference_policy ?? 'preserve_relative',
              }
              if (args.target_novel_id !== undefined) body['target_novel_id'] = args.target_novel_id
              if (args.archive_op === 'restore_preview') {
                return await client.postJson('/api/project-archives/restore/preview', body, exec.signal)
              }
              if (!args.archive_sha256?.trim()) throw new Error('restore requires archive_sha256')
              if (args.confirm !== true) throw new Error('restore requires confirm=true')
              body['archive_sha256'] = args.archive_sha256
              body['confirm'] = true
              return await client.postJson('/api/project-archives/restore', body, exec.signal)
            
        }
        case 'download': {
        if (args.archive_id === undefined) throw new Error('archive_id is required for novel_project(action="download")')
              if (!/^owa_[0-9a-f]{24}$/.test(args.archive_id)) throw new Error('archive_id must match owa_<24 lowercase hex>')
              const client = clientFor(exec)
              const download = await client.download(`/api/project-archives/${args.archive_id}/download`, {}, exec.signal)
              const filename = exportFilename(download.filename, `${args.archive_id}.owarchive.zip`)
              const exportDir = outputDirFor(outputDir, client)
              await mkdir(exportDir, { recursive: true })
              const path = join(exportDir, filename)
              await writeFile(path, download.content)
              return { path, filename, archive_id: args.archive_id, bytes: download.content.byteLength }
            
        }
        default: throw new Error(`novel_project: unknown action ${String(args.action)}`)
      }
    },
  }))

      // ── chapters, documents, import, sync ────────────────────────────────────

  ctx.tools.register(defineTool({
    name: 'novel_chapter_delete',
    description:
      'Delete the LATEST manuscript chapter. The server enforces three safeguards: the path must be a chapter under ' +
      'data/manuscript, confirm must exactly equal the chapter id (e.g. "ch_0007"), and version must equal the ' +
      'document version fingerprint from a fresh novel_doc(action="read"). Only the newest chapter can be deleted, and never ' +
      'while a background task is active.',
    parameters: {
      path: { type: 'string', required: true, description: 'Chapter path, e.g. "data/manuscript/ch_0007.md".' },
      confirm: { type: 'string', required: true, description: 'Must exactly equal the chapter id, e.g. "ch_0007".' },
      version: { type: 'string', required: true, description: 'The document version fingerprint from novel_doc(action="read").' },
    },
    output: { schema: JSON_OUTPUT_SCHEMA, render: (_args, value) => renderJson(value) },
    timeoutMs,
    async execute(args, exec) {
      const client = clientFor(exec)
      return await client.postJson(
        '/api/chapter/delete',
        { path: args.path, confirm: args.confirm, version: args.version },
        exec.signal,
      )
    },
  }))

  ctx.tools.register(defineTool({
    name: 'novel_chapter_delete_batch',
    description:
      'Delete the contiguous latest manuscript tail in one server request, retaining the specified chapter. ' +
      'The server still performs the single-chapter backup/projection cleanup for every chapter and refuses ' +
      'active tasks, missing chapters, non-tail ranges, or stale latest-version fingerprints. ' +
      'confirm must exactly equal "DELETE_AFTER:<keep_through>" (for example "DELETE_AFTER:ch_0030").',
    parameters: {
      keep_through: { type: 'string', required: true, description: 'Last chapter to retain, e.g. "ch_0030".' },
      confirm: { type: 'string', required: true, description: 'Must exactly equal DELETE_AFTER:<keep_through>.' },
      version: { type: 'string', required: true, description: 'The latest chapter version fingerprint from a fresh novel_doc(action="read").' },
    },
    output: { schema: JSON_OUTPUT_SCHEMA, render: (_args, value) => renderJson(value) },
    timeoutMs,
    async execute(args, exec) {
      const client = clientFor(exec)
      return await client.postJson(
        '/api/chapter/delete-batch',
        { keep_through: args.keep_through, confirm: args.confirm, version: args.version },
        exec.signal,
      )
    },
  }))

      // ── manuscript import ─────────────────────────────────────────────────────────

  ctx.tools.register(defineTool({
    name: 'novel_import',
    description:
      'Preview an imported manuscript and then import it. Preview reports the parsed chapters, arc ' +
      'mapping and conflicts without writing; import applies the reviewed plan.',
    parameters: {
      action: { type: 'string', required: true, enum: ['preview', 'import'], description: 'Import step; preview never writes anything.' },
      content: { type: 'string', description: 'The manuscript text to import.' },
      filename: { type: 'string', description: 'Source filename; suffix must be .txt/.md/.markdown (default "import.md").' },
      arc_id: { type: 'string', description: 'Arc id like "arc_001" (default: the project\'s current arc).' },
      start_number: { type: 'integer', description: 'First chapter number (default: after the last existing chapter).' },
      force: { type: 'boolean', description: 'Report the import as allowed despite conflicts (default false).' },
    },
    output: { schema: JSON_OUTPUT_SCHEMA, render: (_args, value) => renderJson(value) },
    timeoutMs,
    isConcurrencySafe: args => ['preview'].includes(args.action),
    async execute(args, exec) {
      switch (args.action) {
        case 'preview': {
        if (args.content === undefined) throw new Error('content is required for novel_import(action="preview")')
              const client = clientFor(exec)
              if (!args.content.trim()) throw new Error('content must be a non-empty string')
              const body: JsonObject = { content: args.content }
              if (args.filename !== undefined) body['filename'] = args.filename
              if (args.arc_id !== undefined) body['arc_id'] = args.arc_id
              if (args.start_number !== undefined) body['start_number'] = args.start_number
              if (args.force !== undefined) body['force'] = args.force
              return await client.postJson('/api/import/preview', body, exec.signal)
            
        }
        case 'import': {
        if (args.content === undefined) throw new Error('content is required for novel_import(action="import")')
              const client = clientFor(exec)
              if (!args.content.trim()) throw new Error('content must be a non-empty string')
              const body: JsonObject = { content: args.content }
              if (args.filename !== undefined) body['filename'] = args.filename
              if (args.arc_id !== undefined) body['arc_id'] = args.arc_id
              if (args.start_number !== undefined) body['start_number'] = args.start_number
              if (args.force !== undefined) body['force'] = args.force
              return await client.postJson('/api/import', body, exec.signal)
            
        }
        default: throw new Error(`novel_import: unknown action ${String(args.action)}`)
      }
    },
  }))

    ctx.tools.register(defineTool({
    name: 'novel_manuscript_import_action',
    description:
      'Operate the durable, resumable import workspace for the author\'s own TXT/Markdown manuscript. ' +
      'Use list/get to inspect saved operations, prepare to snapshot and split a manuscript, structure to revise the ' +
      'chapter boundaries against the current preview revision, confirm for explicit structure approval, run to start ' +
      'or resume the persistent import task, and discard only before publication. This is manuscript migration, not ' +
      'reference-library analysis.',
    parameters: {
      action: { type: 'string', required: true, enum: ['list', 'get', 'prepare', 'structure', 'confirm', 'run', 'discard'], description: 'Import workspace action.' },
      import_id: { type: 'string', description: 'Persistent import operation id.' },
      limit: { type: 'integer', description: 'Maximum operations for list (default 50).' },
      filename: { type: 'string', description: 'Source filename ending in .txt, .md, or .markdown.' },
      content: { type: 'string', description: 'The author\'s own manuscript text for prepare.' },
      arc_id: { type: 'string', description: 'Target arc id, e.g. arc_001. Optional for prepare; defaults to the project\'s current arc.' },
      start_number: { type: 'integer', description: 'Optional first chapter number.' },
      expected_preview_revision: { type: 'string', description: 'Current preview revision required by structure/confirm.' },
      chapters: { type: 'array', items: { type: 'json' }, description: 'Edited chapter objects: chapter_id, title, content.' },
      confirm: { type: 'boolean', description: 'Must be true for confirm or discard.' },
    },
    output: { schema: JSON_OUTPUT_SCHEMA, render: (_args, value) => renderJson(value) },
    timeoutMs,
    async execute(args, exec) {
      const client = clientFor(exec)
      const importId = args.import_id?.trim()
      if (args.action === 'list') {
        return await client.getJson('/api/manuscript-imports', args.limit === undefined ? {} : { limit: String(args.limit) }, exec.signal)
      }
      if (args.action === 'prepare') {
        if (!args.content?.trim()) throw new Error('prepare requires non-empty content')
        // The server resolves the project's current arc when arc_id is absent,
        // exactly like the sibling novel_import tool. Demanding it here only
        // cost the agent a round trip.
        const body: JsonObject = { filename: args.filename ?? 'import.md', content: args.content }
        if (args.arc_id !== undefined) body['arc_id'] = args.arc_id
        if (args.start_number !== undefined) body['start_number'] = args.start_number
        return await client.postJson('/api/manuscript-imports/prepare', body, exec.signal)
      }
      if (!importId || !/^import_[A-Za-z0-9_-]{12,80}$/.test(importId)) throw new Error(`${args.action} requires a valid import_id`)
      if (args.action === 'get') {
        return await client.getJson(`/api/manuscript-imports/${encodeURIComponent(importId)}`, {}, exec.signal)
      }
      if (args.action === 'structure') {
        if (!args.expected_preview_revision?.trim()) throw new Error('structure requires expected_preview_revision')
        if (!Array.isArray(args.chapters) || args.chapters.length === 0) throw new Error('structure requires non-empty chapters')
        return await client.postJson('/api/manuscript-imports/structure', {
          import_id: importId,
          expected_preview_revision: args.expected_preview_revision,
          chapters: args.chapters,
        }, exec.signal)
      }
      if (args.action === 'confirm') {
        if (!args.expected_preview_revision?.trim()) throw new Error('confirm requires expected_preview_revision')
        if (args.confirm !== true) throw new Error('confirm requires confirm=true')
        return await client.postJson('/api/manuscript-imports/confirm', {
          import_id: importId,
          expected_preview_revision: args.expected_preview_revision,
          confirm: true,
        }, exec.signal)
      }
      if (args.action === 'run') {
        return await client.postJson('/api/manuscript-imports/run', { import_id: importId }, exec.signal)
      }
      if (args.confirm !== true) throw new Error('discard requires confirm=true')
      return await client.postJson('/api/manuscript-imports/discard', { import_id: importId, confirm: true }, exec.signal)
    },
  }))

      ctx.tools.register(defineTool({
    name: 'novel_sync',
    description:
      'Synchronize derived caches that are direct src derivatives: outline hierarchy (data/hierarchy.yaml) and ' +
      'character cards (data/characters/cards/*.yaml). It does NOT rebuild chapter memory / runtime truth / ' +
      'character state: those are produced by the chapter-write settlement, so imported or pre-existing chapters ' +
      'need a one-time novel_settle_backfill. The sync response also reports memory_missing / memory_missing_count.',
    parameters: {},
    output: { schema: JSON_OUTPUT_SCHEMA, render: (_args, value) => renderJson(value) },
    timeoutMs,
    async execute(_args, exec) {
      const client = clientFor(exec)
      return await client.postJson('/api/sync', {}, exec.signal)
    },
  }))

  ctx.tools.register(defineTool({
    name: 'novel_settle_backfill',
    description:
      'Settlement backfill for existing/imported chapters: replay the writer pipeline observer+settler over the ' +
      'actual chapter prose (never rewriting it) and commit chapter memory, runtime-truth notes and a ' +
      'character-state index refresh. Run once after importing an old manuscript so later chapters, reviews and ' +
      'canon/continuity checks have real facts from earlier chapters (without it, review canon stays inconclusive ' +
      'and context lacks previous-chapter recaps). Returns a background task (tsk_*); poll with novel_task(action="get").',
    parameters: {
      chapter_ids: {
        type: 'array',
        description: 'Optional chapter ids to backfill, e.g. ["ch_001","ch_002"]; omit to backfill every chapter missing memory.',
        items: { type: 'string' },
      },
      only_missing: { type: 'boolean', description: 'Skip chapters that already have memory (default true).' },
    },
    output: { schema: JSON_OUTPUT_SCHEMA, render: (_args, value) => renderJson(value) },
    timeoutMs,
    async execute(args, exec) {
      const client = clientFor(exec)
      const input: JsonObject = {}
      if (args.chapter_ids !== undefined) input['chapter_ids'] = args.chapter_ids
      if (args.only_missing !== undefined) input['only_missing'] = args.only_missing
      return await client.postJson('/api/tasks', { type: 'settle_backfill', input }, exec.signal)
    },
  }))

  ctx.tools.register(defineTool({
    name: 'novel_writing_targets',
    description:
      'Immediate compatibility write for targets the author has already authorized exactly; otherwise use ' +
      'novel_change_plan(action="structured"). Update the project writing targets. Ranges: book_words 10000-5000000, chapter_words 200-50000, ' +
      'outline_volume_words 100-5000, outline_act_words 80-3000, outline_section_words 50-2000, ' +
      'outline_chapter_words 30-1000. Omitted fields keep their current values.',
    parameters: {
      book_words: { type: 'integer', description: 'Whole-book target word count.' },
      chapter_words: { type: 'integer', description: 'Default words per chapter.' },
      outline_volume_words: { type: 'integer', description: 'Outline summary words per volume.' },
      outline_act_words: { type: 'integer', description: 'Outline summary words per act.' },
      outline_section_words: { type: 'integer', description: 'Outline summary words per section.' },
      outline_chapter_words: { type: 'integer', description: 'Outline summary words per chapter.' },
    },
    output: { schema: JSON_OUTPUT_SCHEMA, render: (_args, value) => renderJson(value) },
    timeoutMs,
    async execute(args, exec) {
      const client = clientFor(exec)
      const body: JsonObject = {}
      if (args.book_words !== undefined) body['book_words'] = args.book_words
      if (args.chapter_words !== undefined) body['chapter_words'] = args.chapter_words
      if (args.outline_volume_words !== undefined) body['outline_volume_words'] = args.outline_volume_words
      if (args.outline_act_words !== undefined) body['outline_act_words'] = args.outline_act_words
      if (args.outline_section_words !== undefined) body['outline_section_words'] = args.outline_section_words
      if (args.outline_chapter_words !== undefined) body['outline_chapter_words'] = args.outline_chapter_words
      if (Object.keys(body).length === 0) throw new Error('provide at least one writing target field')
      return await client.postJson('/api/project/writing-targets', body, exec.signal)
    },
  }))

  // ── continuity & diagnostics ─────────────────────────────────────────────

  ctx.tools.register(defineTool({
    name: 'novel_continuity',
    description: 'Get the continuity report: unresolved foreshadowing, character state drift, and timeline consistency of the current project.',
    parameters: {},
    output: { schema: JSON_OUTPUT_SCHEMA, render: (_args, value) => renderJson(value) },
    timeoutMs,
    isConcurrencySafe: () => true,
    async execute(_args, exec) {
      const client = clientFor(exec)
      return await client.getJson('/api/continuity', {}, exec.signal)
    },
  }))

  ctx.tools.register(defineTool({
    name: 'novel_diagnostics',
    description: 'Run runtime diagnostics over the project (read-only): stuck runs, stale locks, and other operational issues.',
    parameters: {
      stuck_minutes: { type: 'integer', description: 'Minutes after which a run counts as stuck (default 30).' },
    },
    output: { schema: JSON_OUTPUT_SCHEMA, render: (_args, value) => renderJson(value) },
    timeoutMs,
    isConcurrencySafe: () => true,
    async execute(args, exec) {
      const client = clientFor(exec)
      const body: JsonObject = {}
      if (args.stuck_minutes !== undefined) body['stuck_minutes'] = args.stuck_minutes
      return await client.postJson('/api/diagnostics', body, exec.signal)
    },
  }))

  // ── planning: chapter runs, rolling plans, forecasts, manuscript editing ──

  ctx.tools.register(defineTool({
    name: 'novel_chapter_run_action',
    description:
      'Manage Chapter Run V2 records (the server\'s per-chapter write/review run ledger). Actions: "list" ' +
      '(chapter_id?/statuses?/limit?), "get" (run_id), "record_intervention" (run_id + revision + request, ' +
      'optional scope/risk/affected_items/rewrite_required), "update_intervention" (run_id + revision + ' +
      'intervention_id + state, optional facts_revision/impact/proposal/confirm — state transitions may require ' +
      'confirm: true), "cancel" (run_id + revision, optional reason). All mutating actions are revision-gated: ' +
      'pass the run\'s current revision from a list/get call.',
    parameters: {
      include_archived: { type: 'boolean', description: 'For list: include historical runs moved to chapter_deletions when a chapter was deleted. Archived runs are read-only and include archive_directory.' },
      action: { type: 'string', required: true, enum: ['list', 'get', 'record_intervention', 'update_intervention', 'cancel', 'archive'], description: 'The chapter-run operation.' },
      run_id: { type: 'string', description: 'Run id (required for get/record_intervention/update_intervention/cancel).' },
      revision: { type: 'string', description: 'Current run revision (required for mutating actions).' },
      chapter_id: { type: 'string', description: 'Chapter filter for list.' },
      statuses: { type: 'array', items: { type: 'string' }, description: 'Status filter for list.' },
      since: { type: 'string', description: 'ISO timestamp filter for recent runs.' },
      limit: { type: 'integer', description: 'List limit (default 20).' },
      scope: { type: 'string', description: 'Intervention scope (default "chapter").' },
      risk: { type: 'string', description: 'Intervention risk level (default "medium").' },
      request: { type: 'string', description: 'Intervention request text.' },
      affected_items: { type: 'json', description: 'Array of affected item ids.' },
      rewrite_required: { type: 'boolean', description: 'Whether the intervention forces a rewrite.' },
      intervention_id: { type: 'string', description: 'Intervention id (update_intervention).' },
      state: { type: 'string', description: 'Target intervention state (update_intervention).' },
      facts_revision: { type: 'string', description: 'Facts revision for the transition (update_intervention).' },
      impact: { type: 'json', description: 'Impact array for the transition (update_intervention).' },
      proposal: { type: 'string', description: 'Proposal text for the transition (update_intervention).' },
      confirm: { type: 'boolean', description: 'Confirm a gated state transition (default false).' },
      reason: { type: 'string', description: 'Cancel reason (cancel).' },
    },
    output: { schema: JSON_OUTPUT_SCHEMA, render: (_args, value) => renderJson(value) },
    timeoutMs,
    isConcurrencySafe: (args) => args.action === 'list' || args.action === 'get',
    async execute(args, exec) {
      const client = clientFor(exec)
      const body: JsonObject = { action: args.action }
      for (const key of ['run_id', 'revision', 'chapter_id', 'statuses', 'since', 'limit', 'include_archived', 'scope', 'risk', 'request', 'affected_items', 'rewrite_required', 'intervention_id', 'state', 'facts_revision', 'impact', 'proposal', 'confirm', 'reason'] as const) {
        const value = args[key]
        if (value !== undefined) body[key] = value
      }
      return await client.postJson('/api/chapter-runs-v2', body, exec.signal)
    },
  }))

  ctx.tools.register(defineTool({
    name: 'novel_rolling_plan_action',
    description:
      'Manage rolling plan candidates (mid-range plot planning windows). Actions: "list" (limit?), "create" ' +
      '(current_arc?, window_size? default 50, max 50). current_window/accepted_window is accepted manuscript ' +
      'facts only; next_window/planned_window is outline plan, not facts. "get" (candidate_id), "stage" ' +
      '(candidate_id + proposal + revision — stages a Markdown plan; chapter headings should read "第N章：标题" ' +
      'or "第N章 标题" and Chinese numerals are accepted; revision-gated), ' +
      '"delete" (candidate_id + revision), "apply" (candidate_id + revision — appends staged draft chapters ' +
      'that do not collide with the canonical outline into src/outline.md; never writes accepted facts; ' +
      'a proposal without recognizable chapter headings is reported as such instead of as "already exists").',
    parameters: {
      action: { type: 'string', required: true, enum: ['list', 'create', 'get', 'stage', 'delete', 'apply'], description: 'The rolling-plan operation.' },
      limit: { type: 'integer', description: 'List limit (default 20).' },
      current_arc: { type: 'string', description: 'Current arc id (create).' },
      window_size: { type: 'integer', description: 'Planning window size in chapters (create, default 50, max 50).' },
      candidate_id: { type: 'string', description: 'Candidate id (get/stage/delete/apply).' },
      proposal: { type: 'string', description: 'Plan proposal text (stage).' },
      revision: { type: 'string', description: 'Candidate revision (stage/delete/apply, revision-gated).' },
    },
    output: { schema: JSON_OUTPUT_SCHEMA, render: (_args, value) => renderJson(value) },
    timeoutMs,
    isConcurrencySafe: (args) => args.action === 'list' || args.action === 'get',
    async execute(args, exec) {
      const client = clientFor(exec)
      const body: JsonObject = { action: args.action }
      for (const key of ['limit', 'current_arc', 'window_size', 'candidate_id', 'proposal', 'revision'] as const) {
        const value = args[key]
        if (value !== undefined) body[key] = value
      }
      return await client.postJson('/api/rolling-plans', body, exec.signal)
    },
  }))

  ctx.tools.register(defineTool({
    name: 'novel_narrative_forecast_action',
    description:
      'Manage narrative forecasts (branching "what-if" plot projections). Actions: "list" (limit?), "create" ' +
      '(divergence + anchor_chapter_id?, branch_count default 3, horizon default 5), "get" (forecast_id), ' +
      '"stage" (forecast_id + branches + revision), "select" (forecast_id + branch_id + revision — commits one ' +
      'branch; revision-gated).',
    parameters: {
      action: { type: 'string', required: true, enum: ['list', 'create', 'get', 'stage', 'select'], description: 'The forecast operation.' },
      limit: { type: 'integer', description: 'List limit (default 20).' },
      divergence: { type: 'string', description: 'The divergence point description (create).' },
      anchor_chapter_id: { type: 'string', description: 'Chapter to anchor the forecast at (create).' },
      branch_count: { type: 'integer', description: 'Number of branches (create, default 3).' },
      horizon: { type: 'integer', description: 'Forecast horizon in chapters (create, default 5).' },
      forecast_id: { type: 'string', description: 'Forecast id (get/stage/select).' },
      branches: { type: 'json', description: 'Branch array to stage (stage).' },
      branch_id: { type: 'string', description: 'Branch id to commit (select).' },
      revision: { type: 'string', description: 'Forecast revision (stage/select, revision-gated).' },
    },
    output: { schema: JSON_OUTPUT_SCHEMA, render: (_args, value) => renderJson(value) },
    timeoutMs,
    isConcurrencySafe: (args) => args.action === 'list' || args.action === 'get',
    async execute(args, exec) {
      const client = clientFor(exec)
      const body: JsonObject = { action: args.action }
      for (const key of ['limit', 'divergence', 'anchor_chapter_id', 'branch_count', 'horizon', 'forecast_id', 'branches', 'branch_id', 'revision'] as const) {
        const value = args[key]
        if (value !== undefined) body[key] = value
      }
      return await client.postJson('/api/narrative-forecasts', body, exec.signal)
    },
  }))

  ctx.tools.register(defineTool({
    name: 'novel_manuscript_edit_action',
    description:
      'Chapter snapshots, annotations and saved drafts. Actions: "drafts" (list recoverable uncommitted prose), ' +
      '"restore_draft" (run_id_v2 + revision + confirm: true; copy the exact saved bytes without generation, then reconcile facts). Other actions: "versions" (chapter_id), "version" (chapter_id + ' +
      'version_id — returns the snapshot content), "checkpoint" (chapter_id, optional label — save a snapshot), ' +
      '"compare" (chapter_id + version_id — preview current-to-snapshot differences without writing), ' +
      '"restore" (chapter_id + version_id + revision — REVERTS the chapter to a snapshot; revision-gated and ' +
      'confirmation-gated: the server demands confirm: true), "annotations" (chapter_id), "annotate" (chapter_id + ' +
      'revision + quote + note, optional start_hint/end_hint (derived from the quote when omitted) and color amber|rose|sky|lime|violet), ' +
      '"resolve_annotation" (chapter_id + annotation_id).',
    parameters: {
      action: { type: 'string', required: true, enum: ['drafts', 'restore_draft', 'versions', 'version', 'compare', 'checkpoint', 'restore', 'annotations', 'annotate', 'resolve_annotation'], description: 'The manuscript-editing operation.' },
      chapter_id: { type: 'string', description: 'Chapter id (ch_<digits>), required except for drafts/restore_draft.' },
      run_id_v2: { type: 'string', description: 'Saved run id from drafts (restore_draft).' },
      version_id: { type: 'string', description: 'Snapshot id (version/restore).' },
      label: { type: 'string', description: 'Snapshot label (checkpoint).' },
      revision: { type: 'string', description: 'Current chapter revision (restore/annotate).' },
      confirm: { type: 'boolean', description: 'Confirm a restore (required by the server).' },
      quote: { type: 'string', description: 'Annotated passage (annotate).' },
      note: { type: 'string', description: 'Annotation note (annotate).' },
      start_hint: { type: 'integer', description: 'Approximate start offset (annotate).' },
      end_hint: { type: 'integer', description: 'Approximate end offset (annotate).' },
      color: { type: 'string', enum: ['amber', 'rose', 'sky', 'lime', 'violet'], description: 'Display color for a selection note (annotate).' },
      annotation_id: { type: 'string', description: 'Annotation id (resolve_annotation).' },
    },
    output: { schema: JSON_OUTPUT_SCHEMA, render: (_args, value) => renderJson(value) },
    timeoutMs,
    isConcurrencySafe: (args) => args.action === 'drafts' || args.action === 'versions' || args.action === 'version' || args.action === 'compare' || args.action === 'annotations',
    async execute(args, exec) {
      const client = clientFor(exec)
      if (args.action === 'drafts') return await client.getJson('/api/manuscript/drafts', {}, exec.signal)
      if (args.action === 'restore_draft') {
        if (!args.run_id_v2) throw new Error('run_id_v2 is required; list drafts first')
        // A blank expected_revision is not "no guard": the server computes
        // `expected = ""` when the chapter file is absent, so `'' != ''` is
        // false and the revision check is silently satisfied. Sending
        // `confirm: false` likewise guarantees CONFIRMATION_REQUIRED.
        if (args.revision === undefined || !String(args.revision).trim()) {
          throw new Error('revision is required for novel_manuscript_edit_action(action="restore_draft"); read the current chapter revision first')
        }
        if (args.confirm !== true) {
          throw new Error('confirm: true is required for novel_manuscript_edit_action(action="restore_draft")')
        }
        return await client.postJson('/api/manuscript/drafts/restore', {
          run_id_v2: args.run_id_v2, expected_revision: args.revision, confirm: true,
        }, exec.signal)
      }
      if (!args.chapter_id || !CHAPTER_ID_PATTERN.test(args.chapter_id)) throw new Error(`chapter_id must match ch_<digits>, got "${args.chapter_id}"`)
      // An empty quote selects `content[0:0]`, which trivially "matches", so the
      // server would persist a junk annotation and consume the chapter revision.
      if (args.action === 'annotate') {
        if (!args.quote?.trim()) throw new Error('quote is required for novel_manuscript_edit_action(action="annotate")')
        if (!args.note?.trim()) throw new Error('note is required for novel_manuscript_edit_action(action="annotate")')
        if (args.revision === undefined || !String(args.revision).trim()) {
          throw new Error('revision is required for novel_manuscript_edit_action(action="annotate")')
        }
      }
      const body: JsonObject = { action: args.action, chapter_id: args.chapter_id }
      let startHint = args.start_hint
      let endHint = args.end_hint
      if (args.action === 'annotate' && (startHint === undefined || endHint === undefined)) {
        // The server matches content[start_hint:end_hint] literally against the
        // quote, so optional hints must still produce exact offsets.
        const derived = await resolveAnnotationHints(client, args.chapter_id, args.quote!, exec.signal)
        startHint = derived.start
        endHint = derived.end
      }
      for (const key of ['version_id', 'label', 'revision', 'confirm', 'quote', 'note', 'color', 'annotation_id'] as const) {
        const value = args[key]
        if (value !== undefined) body[key] = value
      }
      if (startHint !== undefined) body['start_hint'] = startHint
      if (endHint !== undefined) body['end_hint'] = endHint
      return await client.postJson('/api/manuscript-editing', body, exec.signal)
    },
  }))

  ctx.tools.register(defineTool({
    name: 'novel_manuscript_acceptance_reconcile',
    description:
      'Reconcile the canonical manuscript acceptance ledger. Actions: "baseline" (accept current text as the ' +
      'initial baseline), "external" (accept a detected external edit), "resume" (continue a durable incomplete ' +
      'operation), "abandon" (release a stale operation without deleting prose), and "acknowledge" (record that the author reviewed the completed acceptance and impacts). ' +
      'Each action is mapped to the corresponding OpenWrite acceptance endpoint. Baseline, external, and ' +
      'acknowledge are confirmation-gated by the server.',
    parameters: {
      action: { type: 'string', required: true, enum: ['baseline', 'external', 'resume', 'acknowledge', 'abandon'], description: 'The reconciliation action.' },
      mode: { type: 'string', enum: ['full', 'fast'], description: 'resume: fast accepts frozen manuscript without calling a model; derived facts remain stale and can be reconciled later.' },
      no_model: { type: 'boolean', description: 'external: accept manuscript bytes without extracting facts; does not clear the facts guard.' },
      chapter_id: { type: 'string', description: 'Optional chapter id (ch_<digits>); omit for the project-level operation.' },
      operation_id: { type: 'string', description: 'Durable operation id to resume or acknowledge.' },
      domains: { type: 'array', items: { type: 'string' }, description: 'Affected domains to acknowledge or retry; acknowledge defaults to outline and foreshadowing.' },
      confirm: { type: 'boolean', description: 'Explicit confirmation for a gated baseline, external acceptance, or acknowledgement.' },
    },
    output: { schema: JSON_OUTPUT_SCHEMA, render: (_args, value) => renderJson(value) },
    timeoutMs,
    async execute(args, exec) {
      // An empty chapter id is the project-level operation, not a malformed
      // one: the server resolves it to the first chapter and covers the book.
      // Rejecting "" here made the documented project-level call unreachable
      // for any caller that passes the field as an empty string.
      const chapterId = args.chapter_id?.trim()
      if (chapterId !== undefined && chapterId !== '' && !CHAPTER_ID_PATTERN.test(chapterId)) {
        throw new Error(`chapter_id must match ch_<digits>, got "${args.chapter_id}"`)
      }
      const body: JsonObject = {}
      for (const key of ['operation_id', 'domains', 'confirm', 'mode', 'no_model'] as const) {
        const value = args[key]
        if (value !== undefined) body[key] = value
      }
      if (chapterId) body['chapter_id'] = chapterId
      if (args.action === 'acknowledge' && args.domains === undefined) body['domains'] = ['outline', 'foreshadowing']
      const route = args.action === 'acknowledge' ? 'ack' : args.action === 'resume' ? 'reconcile' : args.action
      return await clientFor(exec).postJson(`/api/manuscript/acceptance/${route}`, body, exec.signal)
    },
  }))

  ctx.tools.register(defineTool({
    name: 'novel_writing_assets',
    description: 'Read or save shared project terminology, review_terms toggle, concrete noun lexicon, overlap_threshold and character_groups. Anchors are Markdown files in the novel anchor/ directory. Save requires the revision returned by get. Character groups are optional descriptive material; retain identity and canonical state in character cards.',
    parameters: {
      action: { type: 'string', required: true, enum: ['get', 'save', 'save_anchor', 'mark_usage'], description: 'Asset operation.' },
      assets: { type: 'json', description: 'Object: terms [{term, forbidden?, replacement?, min_occurrences?, example?}], character_groups {name: [{id,text}]}, review_terms?, concrete_nouns?, overlap_threshold?.' },
      expected_revision: { type: 'string', description: 'Revision from get; empty for a new asset table.' },
      name: { type: 'string', description: 'save_anchor: simple .md filename.' },
      content: { type: 'string', description: 'save_anchor: Markdown reference prose.' },
      chapter_id: { type: 'string', description: 'mark_usage: chapter whose optional character details were used.' },
      groups: { type: 'json', description: 'mark_usage: character name to group IDs used in this chapter.' },
    },
    output: { schema: JSON_OUTPUT_SCHEMA, render: (_args, value) => renderJson(value) },
    timeoutMs,
    isConcurrencySafe: args => args.action === 'get',
    async execute(args, exec) {
      const client = clientFor(exec)
      if (args.action === 'get') return await client.getJson('/api/writing-assets', {}, exec.signal)
      if (args.action === 'save_anchor') {
        // A blank name/content reaches the server as INVALID_WRITING_ASSETS
        // (400), which is also what a stale expected_revision answers — the two
        // are indistinguishable by code. Validate the payload locally so the
        // caller is told which parameter is actually wrong.
        if (!args.name?.trim()) throw new Error('name is required for novel_writing_assets(action="save_anchor")')
        if (!/^[\w-]{1,80}\.md$/.test(args.name)) throw new Error(`save_anchor name must be a simple .md filename, got "${args.name}"`)
        if (!args.content?.trim()) throw new Error('content is required for novel_writing_assets(action="save_anchor")')
        return await client.postJson('/api/writing-assets', { action: args.action, name: args.name, content: args.content, expected_revision: args.expected_revision ?? '' }, exec.signal)
      }
      if (args.action === 'mark_usage') return await client.postJson('/api/writing-assets', { action: args.action, chapter_id: args.chapter_id ?? '', groups: requireRecord(args.groups, 'groups') }, exec.signal)
      const assets = requireRecord(args.assets, 'assets')
      return await client.postJson('/api/writing-assets', { assets: assets as JsonObject, expected_revision: args.expected_revision ?? '' }, exec.signal)
    },
  }))

  ctx.tools.register(defineTool({
    name: 'novel_manuscript_metrics',
    description: 'Read deterministic chapter metrics, terminology findings, overlap against anchors and the previous three chapters, duplicate paragraphs and selected character groups. Overlap spans use Unicode codepoint offsets. No model call.',
    parameters: { chapter_id: { type: 'string', required: true, description: 'Canonical chapter ID.' } },
    output: { schema: JSON_OUTPUT_SCHEMA, render: (_args, value) => renderJson(value) },
    timeoutMs, isConcurrencySafe: () => true,
    async execute(args, exec) {
      if (!CHAPTER_ID_PATTERN.test(args.chapter_id)) throw new Error('Invalid chapter_id')
      return await clientFor(exec).getJson(`/api/manuscript/${encodeURIComponent(args.chapter_id)}/metrics`, {}, exec.signal)
    },
  }))

  ctx.tools.register(defineTool({
    name: 'novel_outline_audit',
    description: 'Read countable chapter-group facts: budgets/actual words, declared promises and function streaks, declared/confirmed payoffs, overdue hooks and drift ledger. Never generates a score or claims prose fulfilled a promise. No model call.',
    parameters: {
      group_id: { type: 'string', description: 'Optional sec_* or arc_* group.' },
      start: { type: 'string', description: 'Optional first chapter ID.' },
      end: { type: 'string', description: 'Optional last chapter ID.' },
    },
    output: { schema: JSON_OUTPUT_SCHEMA, render: (_args, value) => renderJson(value) },
    timeoutMs, isConcurrencySafe: () => true,
    async execute(args, exec) {
      return await clientFor(exec).getJson('/api/outline/audit', { group_id: args.group_id ?? '', start: args.start ?? '', end: args.end ?? '' }, exec.signal)
    },
  }))

  ctx.tools.register(defineTool({
    name: 'novel_drift_entry',
    description: 'Record author-observed chapter drift. Saves an immutable outline/manuscript baseline first. More than two unresolved rewrite drifts in a section freezes generation until explicit reconciliation and replanning.',
    parameters: {
      group_id: { type: 'string', required: true, description: 'Section ID sec_*.' },
      chapter_id: { type: 'string', required: true, description: 'Chapter in this section.' },
      kind: { type: 'string', required: true, enum: ['growth', 'escape', 'dilution', 'snowball'], description: 'Drift kind.' },
      impact: { type: 'string', required: true, enum: ['local', 'section', 'arc'], description: 'Impact scope.' },
      rewrite: { type: 'boolean', description: 'Counts toward rewrite budget; default true.' },
      note: { type: 'string', required: true, description: 'Observed drift and supporting evidence.' },
      expected_revision: { type: 'integer', required: true, description: 'ledger.revision from outline audit.' },
    },
    output: { schema: JSON_OUTPUT_SCHEMA, render: (_args, value) => renderJson(value) },
    timeoutMs,
    async execute(args, exec) {
      return await clientFor(exec).postJson('/api/arc-reconcile', { ...args, action: 'drift_entry' }, exec.signal)
    },
  }))

  ctx.tools.register(defineTool({
    name: 'novel_arc_reconcile',
    description: 'Resolve selected drift entries by absorbing authored outline metadata, scheduling recovery in a later chapter, or freezing. Absorption requires concrete outline_updates and outline_revision; baseline is saved before edits. resume=true explicitly resumes a replanned group within budget. Does not rewrite manuscript.',
    parameters: {
      data: { type: 'json', required: true, description: 'Object: group_id, expected_revision, entry_ids[], decision absorb/recover/freeze, confirm:true. absorb: outline_revision, outline_updates[{node_id,metadata}], resume?. recover: plan, target_chapter_id.' },
    },
    output: { schema: JSON_OUTPUT_SCHEMA, render: (_args, value) => renderJson(value) },
    timeoutMs,
    async execute(args, exec) {
      return await clientFor(exec).postJson('/api/arc-reconcile', { ...requireRecord(args.data, 'data'), action: 'arc_reconcile' } as JsonObject, exec.signal)
    },
  }))

  // ── style sources, reference library, runtime skills, rules ──────────────

  ctx.tools.register(defineTool({
    name: 'novel_source_action',
    description:
      'Style/setting source pipeline (learning from reference texts). Actions: "extract" (source_id + content, ' +
      'focus "style"|"setting"), "analyze_v2" (source_id + content, focus as array, optional relative_name/' +
      'input_budget_tokens), "status_v2" (source_id), "retry_v2" (source_id + chunk_id?), "synthesize_v2" ' +
      '(source_ids array), "profile_v2" (profile_id), "promotion_preview_v2" (profile_id + target), "promote_v2" ' +
      '(preview_id, confirm: true to commit), "review" (source_id), "promote" (source_id, target? default "all"), ' +
      '"synthesize" (source_id). Model-backed actions are LONG-RUNNING.',
    parameters: {
      action: { type: 'string', required: true, enum: ['extract', 'analyze_v2', 'status_v2', 'retry_v2', 'synthesize_v2', 'profile_v2', 'promotion_preview_v2', 'promote_v2', 'review', 'promote', 'synthesize'], description: 'The source operation.' },
      source_id: { type: 'string', description: 'Source pack id.' },
      content: { type: 'string', description: 'Source text (extract/analyze_v2).' },
      focus: { type: 'json', description: '"style"/"setting" string for extract; array of focus names for analyze_v2.' },
      relative_name: { type: 'string', description: 'Display filename (analyze_v2, default "source.txt").' },
      input_budget_tokens: { type: 'integer', description: 'Token budget per analysis chunk (default 12000).' },
      chunk_id: { type: 'string', description: 'Chunk to retry (retry_v2).' },
      source_ids: { type: 'array', items: { type: 'string' }, description: 'Sources to synthesize (synthesize_v2).' },
      profile_id: { type: 'string', description: 'Analysis profile id (profile_v2/promotion_preview_v2).' },
      target: { type: 'string', description: 'Promotion target: style/rules/inspiration/setting_candidates for promotion_preview_v2 (required); style/setting/world/all for legacy promote (default "all").' },
      preview_id: { type: 'string', description: 'Promotion preview id (promote_v2).' },
      confirm: { type: 'boolean', description: 'Confirm a gated promotion (default false).' },
    },
    output: { schema: JSON_OUTPUT_SCHEMA, render: (_args, value) => renderJson(value) },
    timeoutMs,
    isConcurrencySafe: (args) => args.action === 'status_v2' || args.action === 'profile_v2' || args.action === 'promotion_preview_v2',
    async execute(args, exec) {
      const client = clientFor(exec)
      if (args.action === 'promotion_preview_v2') {
        const target = args.target?.trim()
        if (!target) {
          throw new Error('target is required for novel_source_action(action="promotion_preview_v2"); choose style, rules, inspiration, or setting_candidates')
        }
        if (!['style', 'rules', 'inspiration', 'setting_candidates'].includes(target)) {
          throw new Error('target must be style, rules, inspiration, or setting_candidates for promotion_preview_v2')
        }
      }
      const body: JsonObject = { action: args.action }
      for (const key of ['source_id', 'content', 'focus', 'relative_name', 'input_budget_tokens', 'chunk_id', 'source_ids', 'profile_id', 'target', 'preview_id', 'confirm'] as const) {
        const value = args[key]
        if (value !== undefined) body[key] = value
      }
      return await client.postJson('/api/source', body, exec.signal)
    },
  }))

  ctx.tools.register(defineTool({
    name: 'novel_reference_library_action',
    description:
      'Reference-library pipeline (decomposing reference works into structured evidence). Actions: "list", ' +
      '"prepare" (source_id + content, optional title/relative_name/intent/focus array/input_budget_tokens), ' +
      '"confirm_structure" (source_id, units? array), "analyze" (source_id, LONG-RUNNING), "status" (source_id), ' +
      '"retry" (source_id + chunk_id?), "synthesize" (source_ids array), "profile" (profile_id), ' +
      '"adoption_preview" (profile_id + selections array, optional rejected_item_ids), "adopt" (preview_id, ' +
      'confirm: true to commit).',
    parameters: {
      action: { type: 'string', required: true, enum: ['list', 'prepare', 'confirm_structure', 'analyze', 'status', 'retry', 'synthesize', 'profile', 'adoption_preview', 'adopt'], description: 'The reference-library operation.' },
      source_id: { type: 'string', description: 'Reference source id.' },
      content: { type: 'string', description: 'Reference text (prepare).' },
      title: { type: 'string', description: 'Reference title (prepare).' },
      relative_name: { type: 'string', description: 'Display filename (prepare, default "source.txt").' },
      intent: { type: 'string', description: 'Analysis intent (prepare, default "reference").' },
      focus: { type: 'json', description: 'Array of focus names (prepare).' },
      input_budget_tokens: { type: 'integer', description: 'Token budget per chunk (prepare, default 12000).' },
      units: { type: 'json', description: 'Confirmed structure units (confirm_structure).' },
      chunk_id: { type: 'string', description: 'Chunk to retry (retry).' },
      source_ids: { type: 'array', items: { type: 'string' }, description: 'References to synthesize (synthesize).' },
      profile_id: { type: 'string', description: 'Analysis profile id (profile/adoption_preview).' },
      selections: { type: 'json', description: 'Array of adoption selections (adoption_preview).' },
      rejected_item_ids: { type: 'array', items: { type: 'string' }, description: 'Items to reject (adoption_preview).' },
      preview_id: { type: 'string', description: 'Adoption preview id (adopt).' },
      confirm: { type: 'boolean', description: 'Confirm a gated adoption (default false).' },
    },
    output: { schema: JSON_OUTPUT_SCHEMA, render: (_args, value) => renderJson(value) },
    timeoutMs,
    isConcurrencySafe: (args) => args.action === 'list' || args.action === 'status' || args.action === 'profile',
    async execute(args, exec) {
      const client = clientFor(exec)
      const body: JsonObject = { action: args.action }
      for (const key of ['source_id', 'content', 'title', 'relative_name', 'intent', 'focus', 'input_budget_tokens', 'units', 'chunk_id', 'source_ids', 'profile_id', 'selections', 'rejected_item_ids', 'preview_id', 'confirm'] as const) {
        const value = args[key]
        if (value !== undefined) body[key] = value
      }
      return await client.postJson('/api/reference-library', body, exec.signal)
    },
  }))

  ctx.tools.register(defineTool({
    name: 'novel_runtime_skill_action',
    description:
      'Inspect OpenWrite runtime skills. Actions: "list" (all discovered skills), "diagnose" (skill loading ' +
      'problems), "resolve" (which skills apply for an agent and task — optional agent one of dante/goethe/writer/' +
      'reviewer/studio, skills, task, intent, document_type). Read-only.',
    parameters: {
      action: { type: 'string', required: true, enum: ['list', 'diagnose', 'resolve'], description: 'The runtime-skill operation.' },
      agent: { type: 'string', description: 'Agent baseline for resolve: "dante", "goethe", "writer", "reviewer", or "studio" (default).' },
      skills: { type: 'array', items: { type: 'string' }, description: 'Explicit skill ids to resolve.' },
      task: { type: 'string', description: 'Task description for resolve.' },
      intent: { type: 'string', description: 'Intent hint for resolve.' },
      document_type: { type: 'string', description: 'Document type hint for resolve.' },
    },
    output: { schema: JSON_OUTPUT_SCHEMA, render: (_args, value) => renderJson(value) },
    timeoutMs,
    isConcurrencySafe: () => true,
    async execute(args, exec) {
      const client = clientFor(exec)
      const body: JsonObject = { action: args.action }
      for (const key of ['agent', 'skills', 'task', 'intent', 'document_type'] as const) {
        const value = args[key]
        if (value !== undefined) body[key] = value
      }
      return await client.postJson('/api/runtime-skills', body, exec.signal)
    },
  }))

  ctx.tools.register(defineTool({
    name: 'novel_rule_action',
    description:
      'Compiled writing rules. Actions: "status" (active rule set), "preview" (compile a candidate preview), ' +
      '"apply" (preview_id — confirmation-gated: the server answers CONFIRMATION_REQUIRED until called again ' +
      'with confirm: true).',
    parameters: {
      action: { type: 'string', required: true, enum: ['status', 'preview', 'apply'], description: 'The rule operation.' },
      preview_id: { type: 'string', description: 'Preview id to apply (apply).' },
      confirm: { type: 'boolean', description: 'Confirm applying the preview (apply).' },
    },
    output: { schema: JSON_OUTPUT_SCHEMA, render: (_args, value) => renderJson(value) },
    timeoutMs,
    isConcurrencySafe: (args) => args.action === 'status',
    async execute(args, exec) {
      const client = clientFor(exec)
      const body: JsonObject = { action: args.action }
      if (args.preview_id !== undefined) body['preview_id'] = args.preview_id
      if (args.confirm !== undefined) body['confirm'] = args.confirm
      return await client.postJson('/api/rules', body, exec.signal)
    },
  }))

  // ── deep research ────────────────────────────────────────────────────────

  ctx.tools.register(defineTool({
    name: 'novel_research_status',
    description: 'Get the deep-research surface: settings status, report list, and the configured model route. Run a research job via novel_task(action="create") with type "research".',
    parameters: {},
    output: { schema: JSON_OUTPUT_SCHEMA, render: (_args, value) => renderJson(value) },
    timeoutMs,
    isConcurrencySafe: () => true,
    async execute(_args, exec) {
      const client = clientFor(exec)
      return await client.getJson('/api/research', {}, exec.signal)
    },
  }))

  ctx.tools.register(defineTool({
    name: 'novel_research_report',
    description: 'Read one deep-research report by id (ids come from novel_research_status).',
    parameters: {
      report_id: { type: 'string', required: true, description: 'Report id.' },
    },
    output: { schema: JSON_OUTPUT_SCHEMA, render: (_args, value) => renderJson(value) },
    timeoutMs,
    isConcurrencySafe: () => true,
    async execute(args, exec) {
      const client = clientFor(exec)
      if (!/^[A-Za-z0-9][A-Za-z0-9_-]{0,100}$/.test(args.report_id)) throw new Error(`invalid report_id "${args.report_id}"`)
      return await client.getJson(`/api/research/reports/${encodeURIComponent(args.report_id)}`, {}, exec.signal)
    },
  }))

  ctx.tools.register(defineTool({
    name: 'novel_research_settings_save',
    description: 'Save deep-research API settings (search/LLM providers, API keys, defaults). Pass the whole settings object; returns the refreshed research surface.',
    parameters: {
      settings: { type: 'json', required: true, description: 'Settings object, e.g. {"search": "bocha", "llm": "deepseek", ...}.' },
    },
    output: { schema: JSON_OUTPUT_SCHEMA, render: (_args, value) => renderJson(value) },
    timeoutMs,
    async execute(args, exec) {
      const client = clientFor(exec)
      if (typeof args.settings !== 'object' || args.settings === null || Array.isArray(args.settings)) {
        throw new Error('settings must be a JSON object')
      }
      return await client.postJson('/api/research/settings', args.settings, exec.signal)
    },
  }))

  // ── model configuration ──────────────────────────────────────────────────

    // ── model configuration ───────────────────────────────────────────────────────

  ctx.tools.register(defineTool({
    name: 'novel_model_profiles',
    description:
      'List, save, delete and test OpenWrite model profiles, per-task routing and the active model ' +
      'settings. Profiles select which provider/model each task uses; routes map tasks to profiles.',
    parameters: {
      action: { type: 'string', required: true, enum: ['list', 'save', 'delete', 'save_routes', 'configure', 'test'], description: 'Model configuration operation.' },
      profile: { type: 'json', description: 'Profile object, e.g. {"id": "fast", "label": "...", "provider": "openai", "model": "...", "base_url": "...", "max_output_tokens": 24000}.' },
      api_key: { type: 'string', description: 'Chat API key to store with the profile.' },
      remember_api_key: { type: 'boolean', description: 'Persist the API key on the server (default true).' },
      profile_id: { type: 'string', description: 'Profile id to delete.' },
      fallback_id: { type: 'string', description: 'Profile id to reroute to (default: the server default profile).' },
      routes: { type: 'json', description: 'Object mapping operation names to profile ids.' },
      provider: { type: 'string', enum: ['openai', 'anthropic', 'custom'], description: 'Provider (default "openai").' },
      model: { type: 'string', description: 'Model name (max 120 characters).' },
      base_url: { type: 'string', description: 'Base URL (required for provider "custom").' },
      api_format: { type: 'string', enum: ['chat', 'responses'], description: 'API format (default "chat").' },
      context_tokens: { type: 'integer', description: 'Context budget (min 12000).' },
      max_tokens: { type: 'integer', description: 'Max output tokens (min 256, must be < context_tokens).' },
      id: { type: 'string', description: 'Stored profile id to test.' },
    },
    output: { schema: JSON_OUTPUT_SCHEMA, render: (_args, value) => renderJson(value) },
    timeoutMs,
    isConcurrencySafe: args => ['list', 'test'].includes(args.action),
    async execute(args, exec) {
      switch (args.action) {
        case 'list': {
              const client = clientFor(exec)
              return await client.getJson('/api/model/profiles', {}, exec.signal)
            
        }
        case 'save': {
        if (args.profile === undefined) throw new Error('profile is required for novel_model_profiles(action="save")')
              const client = clientFor(exec)
              if (typeof args.profile !== 'object' || args.profile === null || Array.isArray(args.profile)) {
                throw new Error('profile must be a JSON object')
              }
              const body: JsonObject = { ...args.profile }
              for (const key of ['api_key', 'remember_api_key'] as const) {
                const value = args[key]
                if (value !== undefined) body[key] = value
              }
              return await client.postJson('/api/model/profiles', body, exec.signal)
            
        }
        case 'delete': {
        if (args.profile_id === undefined) throw new Error('profile_id is required for novel_model_profiles(action="delete")')
              const client = clientFor(exec)
              if (!args.profile_id.trim()) throw new Error('profile_id must be a non-empty string')
              const body: JsonObject = { profile_id: args.profile_id }
              if (args.fallback_id !== undefined) body['fallback_id'] = args.fallback_id
              return await client.postJson('/api/model/profiles/delete', body, exec.signal)
            
        }
        case 'save_routes': {
        if (args.routes === undefined) throw new Error('routes is required for novel_model_profiles(action="save_routes")')
              const client = clientFor(exec)
              if (typeof args.routes !== 'object' || args.routes === null || Array.isArray(args.routes)) {
                throw new Error('routes must be a JSON object')
              }
              return await client.postJson('/api/model/routes', { routes: args.routes }, exec.signal)
            
        }
        case 'configure': {
        if (args.model === undefined) throw new Error('model is required for novel_model_profiles(action="configure")')
              const client = clientFor(exec)
              if (!args.model.trim() || args.model.length > 120) throw new Error('model must be non-empty and at most 120 characters')
              const body: JsonObject = { model: args.model }
              for (const key of ['provider', 'api_key', 'base_url', 'api_format', 'context_tokens', 'max_tokens', 'remember_api_key'] as const) {
                const value = args[key]
                if (value !== undefined) body[key] = value
              }
              return await client.postJson('/api/model', body, exec.signal)
            
        }
        case 'test': {
              const client = clientFor(exec)
              if (args.id === undefined && (args.model === undefined || !args.model.trim())) {
                throw new Error('either id (stored profile) or model (candidate) is required')
              }
              const body: JsonObject = {}
              for (const key of ['id', 'provider', 'model', 'base_url', 'api_format', 'api_key', 'context_tokens', 'max_tokens'] as const) {
                const value = args[key]
                if (value !== undefined) body[key] = value
              }
              return await client.postJson('/api/model/test', body, exec.signal)
            
        }
        default: throw new Error(`novel_model_profiles: unknown action ${String(args.action)}`)
      }
    },
  }))

  ctx.tools.register(defineTool({
    name: 'novel_model_benchmark',
    description:
      'Run or inspect isolated chapter or outline model benchmarks through OpenWrite profiles and LiteLLM. ' +
      'Use options first to read chapter choices, task limits, supported execution modes and the authoritative ' +
      'pipeline DAG/review domains without invoking a model. The run action creates a background task and never ' +
      'changes model routes, canonical manuscript or canonical outline files.',
    parameters: {
      action: { type: 'string', required: true, enum: ['list', 'get', 'options', 'run'], description: 'Benchmark operation; options previews task choices and pipeline DAGs without starting a run.' },
      run_id: { type: 'string', description: 'Benchmark run id for get.' },
      task_type: { type: 'string', enum: ['chapter', 'outline'], description: 'Run target: chapter (default) or outline. Outline supports framework mode only.' },
      chapter_id: { type: 'string', description: 'Chapter task target: next (default) or an available canonical chapter_id from options, e.g. ch_003. Unavailable targets are rejected without fallback; inspect availability/reason first.' },
      allow_historical: { type: 'boolean', description: 'Explicit isolated rewrite of an already written chapter using current canon. This is not a reconstructed pre-chapter baseline. Source manuscript and ledgers remain unchanged.' },
      outline_start_chapter: { type: 'integer', description: 'Outline task first chapter number, inclusive, 1-100000. Omit to continue after the last outline chapter.' },
      outline_chapter_count: { type: 'integer', description: 'Outline task range length including its starting chapter, 1-20 (default 3).' },
      writer_profile_ids: { type: 'array', items: { type: 'string' }, description: 'Writing profiles to compare (run).' },
      reviewer_profile_ids: { type: 'array', items: { type: 'string' }, description: 'Independent blind-review profiles (run).' },
      execution_mode: { type: 'string', enum: ['framework', 'creative'], description: 'Execution path: full framework (default); creative diagnostic is available only for chapter tasks. Read task pipelines with options.' },
      repeats: { type: 'integer', description: 'Repeats per writing profile, 1-5.' },
      target_words: { type: 'integer', description: 'Chapter candidate target length, 200-50000; use outline_chapter_count for outline range.' },
      concurrency: { type: 'integer', description: 'Concurrent model jobs, 1-4.' },
      limit: { type: 'integer', description: 'List limit, default 20.' },
    },
    output: { schema: JSON_OUTPUT_SCHEMA, render: (_args, value) => renderJson(value) },
    timeoutMs,
    isConcurrencySafe: args => args.action !== 'run',
    async execute(args, exec) {
      const client = clientFor(exec)
      if (args.action === 'list') {
        return await client.getJson('/api/benchmarks', args.limit === undefined ? {} : { limit: String(args.limit) }, exec.signal)
      }
      if (args.action === 'options') {
        return await client.getJson('/api/benchmarks/options', {}, exec.signal)
      }
      if (args.action === 'get') {
        if (!args.run_id?.trim()) throw new Error('run_id is required for get')
        return await client.getJson(`/api/benchmarks/${encodeURIComponent(args.run_id.trim())}`, {}, exec.signal)
      }
      if (!Array.isArray(args.writer_profile_ids) || args.writer_profile_ids.length === 0) {
        throw new Error('writer_profile_ids is required for run')
      }
      if (!Array.isArray(args.reviewer_profile_ids) || args.reviewer_profile_ids.length === 0) {
        throw new Error('reviewer_profile_ids is required for run')
      }
      const body: JsonObject = {
        writer_profile_ids: args.writer_profile_ids,
        reviewer_profile_ids: args.reviewer_profile_ids,
      }
      for (const key of ['task_type', 'chapter_id', 'allow_historical', 'outline_start_chapter', 'outline_chapter_count', 'execution_mode', 'repeats', 'target_words', 'concurrency'] as const) {
        const value = args[key]
        if (value !== undefined) body[key] = value
      }
      return await client.postJson('/api/benchmarks', body, exec.signal)
    },
  }))

            
}
