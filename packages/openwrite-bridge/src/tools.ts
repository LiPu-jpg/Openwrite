/**
 * The `novel_*` tool definitions bridging dsh agents to the OpenWrite Studio
 * HTTP action surface. Payload shapes are verified against OpenWrite
 * `tools/studio_http.py` (POST_ROUTES / do_GET / do_PUT) and
 * `tools/studio_application.py` (the dispatched methods).
 */

import { mkdir, writeFile } from 'node:fs/promises'
import { join } from 'node:path'
import type { Context } from '@deepseek-ai/cordis'
import { defineTool } from '@deepseek-ai/dsh-tools'
import type { JsonObject, StudioClient } from './client.js'

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

/** Resolve a review target: an explicit manuscript path, or a chapter id mapped to `data/manuscript/<id>.md`. */
function resolveReviewPath(args: { path?: string; chapter_id?: string }): string {
  const path = args.path?.trim()
  if (path) return path
  const chapterId = args.chapter_id?.trim()
  if (!chapterId) throw new Error('either path or chapter_id is required')
  if (!CHAPTER_ID_PATTERN.test(chapterId)) throw new Error(`chapter_id must match ch_<digits>, got "${chapterId}"`)
  return `data/manuscript/${chapterId}.md`
}

/** Register every `novel_*` tool into the host tools registry. */
export function registerNovelTools(ctx: Context, client: StudioClient, options: NovelToolsOptions): void {
  const { timeoutMs, outputDir } = options

  // ── reads ──────────────────────────────────────────────────────────────

  ctx.tools.register(defineTool({
    name: 'novel_status',
    description: 'Get a snapshot of the current OpenWrite novel project: title, chapters, word counts, writing targets, and focus compass.',
    parameters: {},
    output: { schema: JSON_OUTPUT_SCHEMA, render: (_args, value) => renderJson(value) },
    timeoutMs,
    isConcurrencySafe: () => true,
    async execute(_args, exec) {
      return await client.getJson('/api/workspace', {}, exec.signal)
    },
  }))

  ctx.tools.register(defineTool({
    name: 'novel_context_preview',
    description: 'Preview the context packet OpenWrite would assemble for writing a chapter (relevant outline, assets, foreshadowing, and prior-chapter memory).',
    parameters: {
      chapter: { type: 'string', description: 'Chapter id (e.g. "ch_0007"); omit or pass "next" for the next chapter to write.' },
    },
    output: { schema: JSON_OUTPUT_SCHEMA, render: (_args, value) => renderJson(value) },
    timeoutMs,
    isConcurrencySafe: () => true,
    async execute(args, exec) {
      return await client.getJson('/api/context', { chapter: args.chapter?.trim() || 'next' }, exec.signal)
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
      const params: Record<string, string> = {}
      const chapter = args.chapter?.trim()
      if (chapter) params['chapter'] = chapter
      return await client.getJson('/api/outline', params, exec.signal)
    },
  }))

  ctx.tools.register(defineTool({
    name: 'novel_assets_list',
    description: 'List structured assets (characters, world entities, progression systems) of the current novel project.',
    parameters: {
      kind: { type: 'string', enum: ['character', 'world', 'progression'], description: 'Restrict to one asset kind; omit to list all kinds.' },
    },
    output: { schema: JSON_OUTPUT_SCHEMA, render: (_args, value) => renderJson(value) },
    timeoutMs,
    isConcurrencySafe: () => true,
    async execute(args, exec) {
      return await client.getJson('/api/assets', { kind: args.kind ?? '' }, exec.signal)
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
      if (!args.q.trim()) throw new Error('q must be a non-empty string')
      const params: Record<string, string> = { q: args.q }
      if (args.scope !== undefined) params['scope'] = args.scope
      if (args.limit !== undefined) params['limit'] = String(args.limit)
      return await client.getJson('/api/search', params, exec.signal)
    },
  }))

  ctx.tools.register(defineTool({
    name: 'novel_doc_read',
    description: 'Read a project document (path relative to the novel data root, e.g. "src/outline.md" or "data/manuscript/ch_0007.md"). Returns content plus a `version` fingerprint needed by novel_doc_write.',
    parameters: {
      path: { type: 'string', required: true, description: 'Document path relative to the novel data root.' },
    },
    output: { schema: JSON_OUTPUT_SCHEMA, render: (_args, value) => renderJson(value) },
    timeoutMs,
    isConcurrencySafe: () => true,
    async execute(args, exec) {
      if (!args.path.trim()) throw new Error('path must be a non-empty string')
      return await client.getJson('/api/document', { path: args.path }, exec.signal)
    },
  }))

  // ── writes ─────────────────────────────────────────────────────────────

  ctx.tools.register(defineTool({
    name: 'novel_outline_edit',
    description:
      'Apply ONE atomic structural edit to the outline tree. Edits are revision-gated: ' +
      'read the current `revision` via novel_outline_read first and pass it back; the server ' +
      'rejects the edit with a conflict if the outline changed in between. ' +
      'Operations: "rename" (node_id + title), "update_summary" (node_id + summary), ' +
      '"add_child" (node_id = parent, + title/summary/kind), "add_after" (node_id = sibling, + title/summary/kind), ' +
      '"delete" (node_id).',
    parameters: {
      operation: { type: 'string', required: true, enum: ['rename', 'update_summary', 'add_child', 'add_after', 'delete'], description: 'The structural operation to apply.' },
      revision: { type: 'string', required: true, description: 'The outline revision fingerprint from a fresh novel_outline_read call.' },
      node_id: { type: 'string', description: 'Target node id (parent for add_child, sibling for add_after); not needed for add_child at root.' },
      title: { type: 'string', description: 'Node title (rename / add_child / add_after).' },
      summary: { type: 'string', description: 'Node summary (update_summary / add_child / add_after).' },
      kind: { type: 'string', description: 'Node kind, e.g. "volume" or "chapter" (add_child / add_after).' },
    },
    output: { schema: JSON_OUTPUT_SCHEMA, render: (_args, value) => renderJson(value) },
    timeoutMs,
    async execute(args, exec) {
      const body: JsonObject = { operation: args.operation, revision: args.revision }
      if (args.node_id !== undefined) body['node_id'] = args.node_id
      if (args.title !== undefined) body['title'] = args.title
      if (args.summary !== undefined) body['summary'] = args.summary
      if (args.kind !== undefined) body['kind'] = args.kind
      return await client.postJson('/api/outline/edit', body, exec.signal)
    },
  }))

  ctx.tools.register(defineTool({
    name: 'novel_write_chapter',
    description:
      'Write a chapter with OpenWrite (LONG-RUNNING, may take several minutes). Omit chapter_id to write ' +
      'the outline-recommended next chapter; a given chapter_id must match the current recommendation. ' +
      'Preview context first with novel_context_preview and consult novel_outline_read for the recommendation.',
    parameters: {
      target_words: { type: 'integer', description: 'Target word count, 200-12000 (default 3000).' },
      guidance: { type: 'string', description: 'Writing guidance for this chapter (plot beats, tone, POV notes).' },
      chapter_id: { type: 'string', description: 'Chapter id to write; must equal the current outline recommendation. Omit for the next chapter.' },
      temperature: { type: 'number', description: 'Sampling temperature (default 0.7).' },
      outline_revision: { type: 'string', description: 'Optional outline revision guard from novel_outline_read; the server rejects the write if the outline changed.' },
    },
    output: { schema: JSON_OUTPUT_SCHEMA, render: (_args, value) => renderJson(value) },
    timeoutMs,
    async execute(args, exec) {
      const targetWords = args.target_words ?? 3000
      if (!Number.isInteger(targetWords) || targetWords < 200 || targetWords > 12000) {
        throw new Error(`target_words must be an integer between 200 and 12000, got ${String(args.target_words)}`)
      }
      const body: JsonObject = { target_words: targetWords, guidance: args.guidance ?? '' }
      const chapterId = args.chapter_id?.trim()
      if (chapterId) body['chapter_id'] = chapterId
      if (args.temperature !== undefined) body['temperature'] = args.temperature
      if (args.outline_revision !== undefined) body['outline_revision'] = args.outline_revision
      return await client.postJson('/api/write', body, exec.signal)
    },
  }))

  ctx.tools.register(defineTool({
    name: 'novel_review_chapter',
    description:
      'Run OpenWrite\'s multi-dimensional review on a drafted manuscript chapter (LONG-RUNNING). ' +
      'Pass either the manuscript path (e.g. "data/manuscript/ch_0007.md") or a chapter_id like "ch_0007".',
    parameters: {
      path: { type: 'string', description: 'Manuscript path relative to the novel data root. Takes precedence over chapter_id.' },
      chapter_id: { type: 'string', description: 'Chapter id (ch_<digits>), resolved client-side to data/manuscript/<id>.md.' },
      strict: { type: 'boolean', description: 'Enable strict review mode (default false).' },
      dimensions: { type: 'array', items: { type: 'string' }, description: 'Optional list of review dimensions to restrict to.' },
    },
    output: { schema: JSON_OUTPUT_SCHEMA, render: (_args, value) => renderJson(value) },
    timeoutMs,
    async execute(args, exec) {
      const body: JsonObject = { path: resolveReviewPath(args) }
      if (args.strict !== undefined) body['strict'] = args.strict
      if (args.dimensions !== undefined) body['dimensions'] = args.dimensions
      return await client.postJson('/api/review', body, exec.signal)
    },
  }))

  ctx.tools.register(defineTool({
    name: 'novel_asset_update',
    description:
      'Update a structured asset (character / world / progression). Revision-gated: pass the `revision` ' +
      'fingerprint from novel_assets_list; the server rejects the update with a conflict if the asset changed. ' +
      'Pass field changes via `data` (merged into the asset front matter), `body_markdown` to replace the ' +
      'markdown body, or `raw_text` to replace the whole document.',
    parameters: {
      kind: { type: 'string', required: true, enum: ['character', 'world', 'progression'], description: 'Asset kind.' },
      id: { type: 'string', required: true, description: 'Asset id.' },
      revision: { type: 'string', required: true, description: 'The asset revision fingerprint from a fresh novel_assets_list call.' },
      data: { type: 'json', description: 'Object of asset fields to merge (e.g. name, summary, aliases).' },
      body_markdown: { type: 'string', description: 'Replacement markdown body (character/world assets).' },
      raw_text: { type: 'string', description: 'Full replacement document text, validated by the server.' },
    },
    output: { schema: JSON_OUTPUT_SCHEMA, render: (_args, value) => renderJson(value) },
    timeoutMs,
    async execute(args, exec) {
      const body: JsonObject = { kind: args.kind, id: args.id, revision: args.revision }
      if (args.data !== undefined) body['data'] = args.data
      if (args.body_markdown !== undefined) body['body_markdown'] = args.body_markdown
      if (args.raw_text !== undefined) body['raw_text'] = args.raw_text
      return await client.postJson('/api/assets/update', body, exec.signal)
    },
  }))

  ctx.tools.register(defineTool({
    name: 'novel_foreshadowing',
    description:
      'Manage the foreshadowing DAG. action "create": node_id + content, optional weight (1-10, default 5), ' +
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

  ctx.tools.register(defineTool({
    name: 'novel_doc_write',
    description:
      'Write a project document (path relative to the novel data root). Uses a version-based optimistic lock: ' +
      'pass the `version` returned by novel_doc_read; the server rejects with a conflict if the document changed. ' +
      'Omit version to create a new document; set force to bypass the lock.',
    parameters: {
      path: { type: 'string', required: true, description: 'Document path relative to the novel data root.' },
      content: { type: 'string', required: true, description: 'Full new document content (max 2 MB).' },
      version: { type: 'string', description: 'The version fingerprint from novel_doc_read (optimistic lock).' },
      force: { type: 'boolean', description: 'Bypass the version check (default false).' },
    },
    output: { schema: JSON_OUTPUT_SCHEMA, render: (_args, value) => renderJson(value) },
    timeoutMs,
    async execute(args, exec) {
      if (!args.path.trim()) throw new Error('path must be a non-empty string')
      const body: JsonObject = { path: args.path, content: args.content }
      if (args.version !== undefined) body['version'] = args.version
      if (args.force !== undefined) body['force'] = args.force
      return await client.putJson('/api/document', body, exec.signal)
    },
  }))

  ctx.tools.register(defineTool({
    name: 'novel_focus',
    description: 'Set the writing focus compass for the project: the current goal plus constraints the writer must keep or avoid.',
    parameters: {
      goal: { type: 'string', required: true, description: 'The current writing goal.' },
      must_keep: { type: 'array', items: { type: 'string' }, description: 'Constraints that must be kept.' },
      must_avoid: { type: 'array', items: { type: 'string' }, description: 'Things that must be avoided.' },
      notes: { type: 'array', items: { type: 'string' }, description: 'Free-form focus notes.' },
    },
    output: { schema: JSON_OUTPUT_SCHEMA, render: (_args, value) => renderJson(value) },
    timeoutMs,
    async execute(args, exec) {
      const body: JsonObject = { goal: args.goal }
      if (args.must_keep !== undefined) body['must_keep'] = args.must_keep
      if (args.must_avoid !== undefined) body['must_avoid'] = args.must_avoid
      if (args.notes !== undefined) body['notes'] = args.notes
      return await client.postJson('/api/focus', body, exec.signal)
    },
  }))

  ctx.tools.register(defineTool({
    name: 'novel_export',
    description: 'Export the manuscript as a file download and save it locally. Returns the saved file path.',
    parameters: {
      format: { type: 'string', enum: ['md', 'txt', 'epub'], description: 'Export format (default "md").' },
    },
    output: {
      schema: {
        type: 'object',
        additionalProperties: false,
        properties: {
          path: { type: 'string', required: true, description: 'Absolute path of the saved export file.' },
          filename: { type: 'string', required: true },
          format: { type: 'string', required: true },
          bytes: { type: 'integer', required: true },
        },
      },
      render: (_args, value) => [{
        type: 'text',
        text: `Exported ${value.filename} (${value.bytes} bytes) to ${value.path}`,
      }],
    },
    timeoutMs,
    async execute(args, exec) {
      const format = args.format ?? 'md'
      const download = await client.download('/api/export', { format }, exec.signal)
      await mkdir(outputDir, { recursive: true })
      const filename = download.filename === 'export.bin' ? `novel.${format}` : download.filename
      const path = join(outputDir, filename)
      await writeFile(path, download.content)
      return { path, filename, format, bytes: download.content.byteLength }
    },
  }))
}
