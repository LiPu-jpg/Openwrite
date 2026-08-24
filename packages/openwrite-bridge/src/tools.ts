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
import { materializeDogReview, reviewChapterId } from './dog-review.js'

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
      dog_threshold: { type: 'integer', description: 'DoG aggregate score threshold (default 70); this does not change OpenWrite review.' },
    },
    output: { schema: JSON_OUTPUT_SCHEMA, render: (_args, value) => renderJson(value) },
    timeoutMs,
    async execute(args, exec) {
      const body: JsonObject = { path: resolveReviewPath(args) }
      if (args.strict !== undefined) body['strict'] = args.strict
      if (args.dimensions !== undefined) body['dimensions'] = args.dimensions
      const response = await client.postJson('/api/review', body, exec.signal)
      try {
        const dogReview = await materializeDogReview(response, reviewChapterId(args), args.dog_threshold ?? 70)
        const value = response !== null && typeof response === 'object' && !Array.isArray(response)
          ? response as JsonObject
          : { result: response }
        return { ...value, dog_review: dogReview }
      } catch (error) {
        const value = response !== null && typeof response === 'object' && !Array.isArray(response)
          ? response as JsonObject
          : { result: response }
        return { ...value, dog_review: { status: 'unavailable', error: error instanceof Error ? error.message : String(error) } }
      }
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

  // ── assets: create / read / packages ────────────────────────────────────

  ctx.tools.register(defineTool({
    name: 'novel_asset_read',
    description: 'Read one structured asset by kind and id, including its relation view.',
    parameters: {
      kind: { type: 'string', required: true, enum: ['character', 'world', 'progression'], description: 'Asset kind.' },
      id: { type: 'string', required: true, description: 'Asset id.' },
    },
    output: { schema: JSON_OUTPUT_SCHEMA, render: (_args, value) => renderJson(value) },
    timeoutMs,
    isConcurrencySafe: () => true,
    async execute(args, exec) {
      if (!/^[A-Za-z0-9][A-Za-z0-9_.-]{0,79}$/.test(args.id)) throw new Error(`invalid asset id "${args.id}"`)
      return await client.getJson(`/api/assets/${args.kind}/${encodeURIComponent(args.id)}`, {}, exec.signal)
    },
  }))

  ctx.tools.register(defineTool({
    name: 'novel_asset_create',
    description:
      'Create a structured asset. character/world assets take front-matter fields via `data` plus an optional ' +
      '`body_markdown`; progression assets take their YAML mapping via `data`. Fails with a conflict if the id exists — ' +
      'use novel_asset_update instead.',
    parameters: {
      kind: { type: 'string', required: true, enum: ['character', 'world', 'progression'], description: 'Asset kind.' },
      id: { type: 'string', required: true, description: 'Asset id (letters, digits, "_", "-", ".").' },
      data: { type: 'json', description: 'Object of asset fields (e.g. name, summary, aliases).' },
      body_markdown: { type: 'string', description: 'Markdown body (character/world assets).' },
    },
    output: { schema: JSON_OUTPUT_SCHEMA, render: (_args, value) => renderJson(value) },
    timeoutMs,
    async execute(args, exec) {
      if (!/^[A-Za-z0-9][A-Za-z0-9_.-]{0,79}$/.test(args.id)) throw new Error(`invalid asset id "${args.id}"`)
      const body: JsonObject = { kind: args.kind, id: args.id }
      if (args.data !== undefined) body['data'] = args.data
      if (args.body_markdown !== undefined) body['body_markdown'] = args.body_markdown
      return await client.postJson('/api/assets', body, exec.signal)
    },
  }))

  ctx.tools.register(defineTool({
    name: 'novel_assets_package_export',
    description: 'Export assets as an .owasset.zip package and save it locally. Omit selections to export all assets.',
    parameters: {
      selections: { type: 'array', items: { type: 'string' }, description: 'Asset selectors in "kind:id" form, e.g. ["character:hero", "world:capital"].' },
    },
    output: {
      schema: {
        type: 'object',
        additionalProperties: false,
        properties: {
          path: { type: 'string', required: true, description: 'Absolute path of the saved package file.' },
          filename: { type: 'string', required: true },
          bytes: { type: 'integer', required: true },
        },
      },
      render: (_args, value) => [{
        type: 'text',
        text: `Exported asset package ${value.filename} (${value.bytes} bytes) to ${value.path}`,
      }],
    },
    timeoutMs,
    isConcurrencySafe: () => true,
    async execute(args, exec) {
      const selections = args.selections ?? []
      for (const item of selections) {
        if (!/^(character|world|progression):[A-Za-z0-9][A-Za-z0-9_.-]{0,79}$/.test(item)) {
          throw new Error(`invalid asset selection "${item}"; expected "kind:id"`)
        }
      }
      const download = await client.download('/api/assets/package/export', { select: selections }, exec.signal)
      await mkdir(outputDir, { recursive: true })
      const filename = download.filename === 'export.bin' ? 'assets.owasset.zip' : download.filename
      const path = join(outputDir, filename)
      await writeFile(path, download.content)
      return { path, filename, bytes: download.content.byteLength }
    },
  }))

  ctx.tools.register(defineTool({
    name: 'novel_assets_package_preview',
    description:
      'Stage an .owasset.zip asset package (base64) and preview its contents and conflicts without importing. ' +
      'Returns an upload_id to pass to novel_assets_package_import.',
    parameters: {
      package_base64: { type: 'string', required: true, description: 'Base64-encoded .owasset.zip package (max 25 MB decoded).' },
    },
    output: { schema: JSON_OUTPUT_SCHEMA, render: (_args, value) => renderJson(value) },
    timeoutMs,
    async execute(args, exec) {
      if (!args.package_base64.trim()) throw new Error('package_base64 must be a non-empty string')
      return await client.postJson('/api/assets/package/preview', { package_base64: args.package_base64 }, exec.signal)
    },
  }))

  ctx.tools.register(defineTool({
    name: 'novel_assets_package_import',
    description:
      'Import a previously staged asset package (see novel_assets_package_preview). Resolves per-asset conflicts ' +
      'via `resolutions`; set allow_missing_dependencies to skip missing dependency checks.',
    parameters: {
      upload_id: { type: 'string', required: true, description: 'The upload_id returned by novel_assets_package_preview.' },
      package_sha256: { type: 'string', description: 'Optional expected package digest guard.' },
      resolutions: { type: 'json', description: 'Object mapping conflicting asset keys to resolutions.' },
      allow_missing_dependencies: { type: 'boolean', description: 'Allow import despite missing asset dependencies (default false).' },
    },
    output: { schema: JSON_OUTPUT_SCHEMA, render: (_args, value) => renderJson(value) },
    timeoutMs,
    async execute(args, exec) {
      const body: JsonObject = { upload_id: args.upload_id }
      if (args.package_sha256 !== undefined) body['package_sha256'] = args.package_sha256
      if (args.resolutions !== undefined) body['resolutions'] = args.resolutions
      if (args.allow_missing_dependencies !== undefined) body['allow_missing_dependencies'] = args.allow_missing_dependencies
      return await client.postJson('/api/assets/package/import', body, exec.signal)
    },
  }))

  // ── revisions ────────────────────────────────────────────────────────────

  ctx.tools.register(defineTool({
    name: 'novel_revisions_list',
    description: 'List revision proposals, optionally filtered by chapter and/or status.',
    parameters: {
      chapter: { type: 'string', description: 'Chapter id filter (e.g. "ch_0007").' },
      status: { type: 'string', description: 'Status filter (e.g. "proposed", "applied", "rejected").' },
    },
    output: { schema: JSON_OUTPUT_SCHEMA, render: (_args, value) => renderJson(value) },
    timeoutMs,
    isConcurrencySafe: () => true,
    async execute(args, exec) {
      const params: Record<string, string> = {}
      if (args.chapter !== undefined) params['chapter'] = args.chapter
      if (args.status !== undefined) params['status'] = args.status
      return await client.getJson('/api/revisions', params, exec.signal)
    },
  }))

  ctx.tools.register(defineTool({
    name: 'novel_revision_get',
    description: 'Get one revision proposal with its diff hunks by proposal id (rev_*).',
    parameters: {
      proposal_id: { type: 'string', required: true, description: 'Revision proposal id (rev_*).' },
    },
    output: { schema: JSON_OUTPUT_SCHEMA, render: (_args, value) => renderJson(value) },
    timeoutMs,
    isConcurrencySafe: () => true,
    async execute(args, exec) {
      if (!/^rev_[A-Za-z0-9_-]+$/.test(args.proposal_id)) throw new Error(`invalid proposal_id "${args.proposal_id}"`)
      return await client.getJson(`/api/revisions/${encodeURIComponent(args.proposal_id)}`, {}, exec.signal)
    },
  }))

  ctx.tools.register(defineTool({
    name: 'novel_revision_create_selection',
    description:
      'Create a revision proposal for a text selection in a chapter (LONG-RUNNING, model-generated). ' +
      'start/end are character offsets; pass the selected text as original_text. The proposal is only staged — ' +
      'apply it with novel_revision_apply.',
    parameters: {
      chapter_id: { type: 'string', required: true, description: 'Chapter id (ch_<digits>).' },
      start: { type: 'integer', required: true, description: 'Selection start offset.' },
      end: { type: 'integer', required: true, description: 'Selection end offset.' },
      original_text: { type: 'string', description: 'The selected original text.' },
      instruction: { type: 'string', description: 'Revision instruction (max 4000 characters).' },
      action: { type: 'string', enum: ['rewrite', 'expand', 'compress', 'pace', 'dialogue', 'naturalize', 'custom'], description: 'Revision mode (default "rewrite").' },
      target_units: { type: 'integer', description: 'Target length in writing units (0 = keep similar).' },
      full_chapter: { type: 'boolean', description: 'Treat the whole chapter as the selection (default false).' },
    },
    output: { schema: JSON_OUTPUT_SCHEMA, render: (_args, value) => renderJson(value) },
    timeoutMs,
    async execute(args, exec) {
      if (!CHAPTER_ID_PATTERN.test(args.chapter_id)) throw new Error(`chapter_id must match ch_<digits>, got "${args.chapter_id}"`)
      const body: JsonObject = { chapter_id: args.chapter_id, start: args.start, end: args.end }
      if (args.original_text !== undefined) body['original_text'] = args.original_text
      if (args.instruction !== undefined) body['instruction'] = args.instruction
      if (args.action !== undefined) body['action'] = args.action
      if (args.target_units !== undefined) body['target_units'] = args.target_units
      if (args.full_chapter !== undefined) body['full_chapter'] = args.full_chapter
      return await client.postJson('/api/revisions/selection', body, exec.signal)
    },
  }))

  ctx.tools.register(defineTool({
    name: 'novel_revision_create_from_review',
    description:
      'Create a revision proposal that addresses selected issues from a chapter review (LONG-RUNNING, model-generated). ' +
      'Issue ids come from novel_review_chapter\'s issue_details. The proposal is only staged — apply it with novel_revision_apply.',
    parameters: {
      chapter_id: { type: 'string', required: true, description: 'Chapter id (ch_<digits>).' },
      issue_ids: { type: 'array', required: true, items: { type: 'string' }, description: 'Review issue ids to fix.' },
      instruction: { type: 'string', description: 'Additional revision instruction.' },
      target_units: { type: 'integer', description: 'Target length in writing units (0 = keep similar).' },
    },
    output: { schema: JSON_OUTPUT_SCHEMA, render: (_args, value) => renderJson(value) },
    timeoutMs,
    async execute(args, exec) {
      if (!CHAPTER_ID_PATTERN.test(args.chapter_id)) throw new Error(`chapter_id must match ch_<digits>, got "${args.chapter_id}"`)
      if (args.issue_ids.length === 0) throw new Error('issue_ids must be a non-empty array')
      const body: JsonObject = { chapter_id: args.chapter_id, issue_ids: args.issue_ids }
      if (args.instruction !== undefined) body['instruction'] = args.instruction
      if (args.target_units !== undefined) body['target_units'] = args.target_units
      return await client.postJson('/api/revisions/from-review', body, exec.signal)
    },
  }))

  ctx.tools.register(defineTool({
    name: 'novel_revision_apply',
    description:
      'Apply a staged revision proposal to the manuscript. Optionally override the generated text or apply only ' +
      'selected diff hunks. Fails with a conflict if the document changed since the proposal was created.',
    parameters: {
      proposal_id: { type: 'string', required: true, description: 'Revision proposal id (rev_*).' },
      replacement_text: { type: 'string', description: 'Replacement text overriding the proposal.' },
      selected_hunk_ids: { type: 'array', items: { type: 'string' }, description: 'Apply only these diff hunk ids.' },
    },
    output: { schema: JSON_OUTPUT_SCHEMA, render: (_args, value) => renderJson(value) },
    timeoutMs,
    async execute(args, exec) {
      if (!/^rev_[A-Za-z0-9_-]+$/.test(args.proposal_id)) throw new Error(`invalid proposal_id "${args.proposal_id}"`)
      const body: JsonObject = {}
      if (args.replacement_text !== undefined) body['replacement_text'] = args.replacement_text
      if (args.selected_hunk_ids !== undefined) body['selected_hunk_ids'] = args.selected_hunk_ids
      return await client.postJson(`/api/revisions/${encodeURIComponent(args.proposal_id)}/apply`, body, exec.signal)
    },
  }))

  ctx.tools.register(defineTool({
    name: 'novel_revision_reject',
    description:
      'Reject and discard a staged revision proposal. This permanently drops the generated text — it cannot be ' +
      'recovered except by regenerating.',
    parameters: {
      proposal_id: { type: 'string', required: true, description: 'Revision proposal id (rev_*).' },
    },
    output: { schema: JSON_OUTPUT_SCHEMA, render: (_args, value) => renderJson(value) },
    timeoutMs,
    async execute(args, exec) {
      if (!/^rev_[A-Za-z0-9_-]+$/.test(args.proposal_id)) throw new Error(`invalid proposal_id "${args.proposal_id}"`)
      return await client.postJson(`/api/revisions/${encodeURIComponent(args.proposal_id)}/reject`, {}, exec.signal)
    },
  }))

  ctx.tools.register(defineTool({
    name: 'novel_revision_regenerate',
    description: 'Regenerate the text of a staged revision proposal (LONG-RUNNING, model-generated).',
    parameters: {
      proposal_id: { type: 'string', required: true, description: 'Revision proposal id (rev_*).' },
    },
    output: { schema: JSON_OUTPUT_SCHEMA, render: (_args, value) => renderJson(value) },
    timeoutMs,
    async execute(args, exec) {
      if (!/^rev_[A-Za-z0-9_-]+$/.test(args.proposal_id)) throw new Error(`invalid proposal_id "${args.proposal_id}"`)
      return await client.postJson(`/api/revisions/${encodeURIComponent(args.proposal_id)}/regenerate`, {}, exec.signal)
    },
  }))

  // ── background tasks ─────────────────────────────────────────────────────

  ctx.tools.register(defineTool({
    name: 'novel_tasks_list',
    description: 'List background tasks (queued/running/finished AI jobs) with per-status counts.',
    parameters: {
      limit: { type: 'integer', description: 'Maximum number of tasks (server default 100).' },
    },
    output: { schema: JSON_OUTPUT_SCHEMA, render: (_args, value) => renderJson(value) },
    timeoutMs,
    isConcurrencySafe: () => true,
    async execute(args, exec) {
      const params: Record<string, string> = {}
      if (args.limit !== undefined) params['limit'] = String(args.limit)
      return await client.getJson('/api/tasks', params, exec.signal)
    },
  }))

  ctx.tools.register(defineTool({
    name: 'novel_task_get',
    description: 'Get one background task with its event log by task id (tsk_*).',
    parameters: {
      task_id: { type: 'string', required: true, description: 'Task id (tsk_*).' },
    },
    output: { schema: JSON_OUTPUT_SCHEMA, render: (_args, value) => renderJson(value) },
    timeoutMs,
    isConcurrencySafe: () => true,
    async execute(args, exec) {
      if (!/^tsk_[A-Za-z0-9_-]+$/.test(args.task_id)) throw new Error(`invalid task_id "${args.task_id}"`)
      return await client.getJson(`/api/tasks/${encodeURIComponent(args.task_id)}`, {}, exec.signal)
    },
  }))

  ctx.tools.register(defineTool({
    name: 'novel_task_create',
    description:
      'Queue a background AI task and return immediately; poll with novel_task_get. Task types and their `input` keys: ' +
      'chapter_write {chapter_id?, guidance?, target_words?, temperature?, outline_revision?}; ' +
      'chapter_review {chapter_id | path, strict?, dimensions?}; ' +
      'revision_selection / revision_from_review (same inputs as the novel_revision_create_* tools); ' +
      'source_operation / reference_operation (same inputs as novel_source_action / novel_reference_library_action); ' +
      'manuscript_import (same input as novel_import); research {prompt, search?, language?, quality?, llm?}; ' +
      'continuous_write — prefer the novel_multi_write convenience tool.',
    parameters: {
      type: {
        type: 'string',
        required: true,
        enum: ['chapter_write', 'chapter_review', 'revision_selection', 'revision_from_review', 'source_operation', 'reference_operation', 'manuscript_import', 'continuous_write', 'research'],
        description: 'Task type.',
      },
      input: { type: 'json', required: true, description: 'Task input object; shape depends on the task type (see description).' },
    },
    output: { schema: JSON_OUTPUT_SCHEMA, render: (_args, value) => renderJson(value) },
    timeoutMs,
    async execute(args, exec) {
      if (typeof args.input !== 'object' || args.input === null || Array.isArray(args.input)) {
        throw new Error('input must be a JSON object')
      }
      return await client.postJson('/api/tasks', { type: args.type, input: args.input }, exec.signal)
    },
  }))

  ctx.tools.register(defineTool({
    name: 'novel_task_cancel',
    description: 'Cancel a queued or running background task. Cancellation is permanent for that task; retry with novel_task_retry if the type supports it.',
    parameters: {
      task_id: { type: 'string', required: true, description: 'Task id (tsk_*).' },
    },
    output: { schema: JSON_OUTPUT_SCHEMA, render: (_args, value) => renderJson(value) },
    timeoutMs,
    async execute(args, exec) {
      if (!/^tsk_[A-Za-z0-9_-]+$/.test(args.task_id)) throw new Error(`invalid task_id "${args.task_id}"`)
      return await client.postJson(`/api/tasks/${encodeURIComponent(args.task_id)}/cancel`, {}, exec.signal)
    },
  }))

  ctx.tools.register(defineTool({
    name: 'novel_task_retry',
    description: 'Retry a failed or cancelled background task.',
    parameters: {
      task_id: { type: 'string', required: true, description: 'Task id (tsk_*).' },
    },
    output: { schema: JSON_OUTPUT_SCHEMA, render: (_args, value) => renderJson(value) },
    timeoutMs,
    async execute(args, exec) {
      if (!/^tsk_[A-Za-z0-9_-]+$/.test(args.task_id)) throw new Error(`invalid task_id "${args.task_id}"`)
      return await client.postJson(`/api/tasks/${encodeURIComponent(args.task_id)}/retry`, {}, exec.signal)
    },
  }))

  ctx.tools.register(defineTool({
    name: 'novel_task_confirm',
    description: 'Confirm a background task that is awaiting confirmation (e.g. a continuous_write run paused between chapters), letting it resume.',
    parameters: {
      task_id: { type: 'string', required: true, description: 'Task id (tsk_*).' },
    },
    output: { schema: JSON_OUTPUT_SCHEMA, render: (_args, value) => renderJson(value) },
    timeoutMs,
    async execute(args, exec) {
      if (!/^tsk_[A-Za-z0-9_-]+$/.test(args.task_id)) throw new Error(`invalid task_id "${args.task_id}"`)
      return await client.postJson(`/api/tasks/${encodeURIComponent(args.task_id)}/confirm`, {}, exec.signal)
    },
  }))

  ctx.tools.register(defineTool({
    name: 'novel_multi_write',
    description:
      'Queue a BACKGROUND continuous-writing run: writes up to max_chapters chapters following the outline, ' +
      'reviewing each; stops early on review blockers, continuity errors, low scores, or budget limits. ' +
      'Returns immediately with a task id — poll with novel_task_get and resume paused runs with novel_task_confirm.',
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
      require_confirmation_after_each_chapter: { type: 'boolean', description: 'Pause for novel_task_confirm after each chapter (default false).' },
    },
    output: { schema: JSON_OUTPUT_SCHEMA, render: (_args, value) => renderJson(value) },
    timeoutMs,
    async execute(args, exec) {
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

  ctx.tools.register(defineTool({
    name: 'novel_project_init',
    description:
      'Create a new OpenWrite novel project on the server machine and make it the active project. ' +
      'Works without a currently open project. novel_id must be 2-64 chars of letters/digits/"-"/"_".',
    parameters: {
      novel_id: { type: 'string', required: true, description: 'Project id, e.g. "my_novel" (2-64 chars: letters, digits, "-", "_").' },
      title: { type: 'string', required: true, description: 'Book title (max 120 characters).' },
      project_path: { type: 'string', description: 'Target directory on the server; omit to use the server default location.' },
      template: { type: 'string', enum: ['default', 'demo_short'], description: 'Project template (default "default").' },
    },
    output: { schema: JSON_OUTPUT_SCHEMA, render: (_args, value) => renderJson(value) },
    timeoutMs,
    async execute(args, exec) {
      if (!/^[A-Za-z0-9][A-Za-z0-9_-]{1,63}$/.test(args.novel_id)) {
        throw new Error('novel_id must be 2-64 chars of letters, digits, "-" or "_"')
      }
      if (!args.title.trim() || args.title.length > 120) throw new Error('title must be non-empty and at most 120 characters')
      const body: JsonObject = { novel_id: args.novel_id, title: args.title }
      if (args.project_path !== undefined) body['project_path'] = args.project_path
      if (args.template !== undefined) body['template'] = args.template
      return await client.postJson('/api/project/init', body, exec.signal)
    },
  }))

  ctx.tools.register(defineTool({
    name: 'novel_project_open',
    description:
      'Switch the Studio server to another existing project directory (must contain novel_config.yaml). ' +
      'Works without a currently open project; afterwards every other novel_* tool targets the newly opened project. ' +
      'The server rejects the switch while a background task is active.',
    parameters: {
      project_path: { type: 'string', required: true, description: 'Absolute project directory path on the server machine.' },
    },
    output: { schema: JSON_OUTPUT_SCHEMA, render: (_args, value) => renderJson(value) },
    timeoutMs,
    async execute(args, exec) {
      if (!args.project_path.trim()) throw new Error('project_path must be a non-empty string')
      return await client.postJson('/api/project/open', { project_path: args.project_path }, exec.signal)
    },
  }))

  ctx.tools.register(defineTool({
    name: 'novel_project_delete',
    description:
      'PERMANENTLY delete a project directory and all its contents from the server machine (recursive delete, ' +
      'not recoverable). The server requires confirm to exactly equal the project\'s novel_id as a safeguard.',
    parameters: {
      project_path: { type: 'string', required: true, description: 'Project directory to delete.' },
      confirm: { type: 'string', required: true, description: 'Must exactly equal the project\'s novel_id (from its novel_config.yaml).' },
    },
    output: { schema: JSON_OUTPUT_SCHEMA, render: (_args, value) => renderJson(value) },
    timeoutMs,
    async execute(args, exec) {
      if (!args.project_path.trim() || !args.confirm.trim()) throw new Error('project_path and confirm are required')
      return await client.postJson('/api/project/delete', { project_path: args.project_path, confirm: args.confirm }, exec.signal)
    },
  }))

  // ── chapters, documents, import, sync ────────────────────────────────────

  ctx.tools.register(defineTool({
    name: 'novel_chapter_delete',
    description:
      'Delete the LATEST manuscript chapter. The server enforces three safeguards: the path must be a chapter under ' +
      'data/manuscript, confirm must exactly equal the chapter id (e.g. "ch_0007"), and version must equal the ' +
      'document version fingerprint from a fresh novel_doc_read. Only the newest chapter can be deleted, and never ' +
      'while a background task is active.',
    parameters: {
      path: { type: 'string', required: true, description: 'Chapter path, e.g. "data/manuscript/ch_0007.md".' },
      confirm: { type: 'string', required: true, description: 'Must exactly equal the chapter id, e.g. "ch_0007".' },
      version: { type: 'string', required: true, description: 'The document version fingerprint from novel_doc_read.' },
    },
    output: { schema: JSON_OUTPUT_SCHEMA, render: (_args, value) => renderJson(value) },
    timeoutMs,
    async execute(args, exec) {
      return await client.postJson(
        '/api/chapter/delete',
        { path: args.path, confirm: args.confirm, version: args.version },
        exec.signal,
      )
    },
  }))

  ctx.tools.register(defineTool({
    name: 'novel_doc_create',
    description: 'Create a new project document by kind and name (e.g. a setting or character note), then returns the created document.',
    parameters: {
      kind: { type: 'string', required: true, description: 'Document kind (e.g. "setting", "character").' },
      name: { type: 'string', required: true, description: 'Document name.' },
      description: { type: 'string', description: 'Short description of the document.' },
    },
    output: { schema: JSON_OUTPUT_SCHEMA, render: (_args, value) => renderJson(value) },
    timeoutMs,
    async execute(args, exec) {
      if (!args.kind.trim() || !args.name.trim()) throw new Error('kind and name must be non-empty strings')
      const body: JsonObject = { kind: args.kind, name: args.name }
      if (args.description !== undefined) body['description'] = args.description
      return await client.postJson('/api/document/create', body, exec.signal)
    },
  }))

  ctx.tools.register(defineTool({
    name: 'novel_import_preview',
    description:
      'Preview a TXT/Markdown manuscript import without writing anything: detected chapters, numbering, and ' +
      'conflicts with existing chapters. Run this before novel_import.',
    parameters: {
      content: { type: 'string', required: true, description: 'The manuscript text to import.' },
      filename: { type: 'string', description: 'Source filename; suffix must be .txt/.md/.markdown (default "import.md").' },
      arc_id: { type: 'string', description: 'Arc id like "arc_001" (default: the project\'s current arc).' },
      start_number: { type: 'integer', description: 'First chapter number (default: after the last existing chapter).' },
      force: { type: 'boolean', description: 'Report the import as allowed despite conflicts (default false).' },
    },
    output: { schema: JSON_OUTPUT_SCHEMA, render: (_args, value) => renderJson(value) },
    timeoutMs,
    isConcurrencySafe: () => true,
    async execute(args, exec) {
      if (!args.content.trim()) throw new Error('content must be a non-empty string')
      const body: JsonObject = { content: args.content }
      if (args.filename !== undefined) body['filename'] = args.filename
      if (args.arc_id !== undefined) body['arc_id'] = args.arc_id
      if (args.start_number !== undefined) body['start_number'] = args.start_number
      if (args.force !== undefined) body['force'] = args.force
      return await client.postJson('/api/import/preview', body, exec.signal)
    },
  }))

  ctx.tools.register(defineTool({
    name: 'novel_import',
    description:
      'Import a TXT/Markdown manuscript as chapters (split on headings). Preview first with novel_import_preview; ' +
      'the server rejects conflicting chapter ids unless force is set.',
    parameters: {
      content: { type: 'string', required: true, description: 'The manuscript text to import.' },
      filename: { type: 'string', description: 'Source filename; suffix must be .txt/.md/.markdown (default "import.md").' },
      arc_id: { type: 'string', description: 'Arc id like "arc_001" (default: the project\'s current arc).' },
      start_number: { type: 'integer', description: 'First chapter number (default: continue numbering).' },
      force: { type: 'boolean', description: 'Overwrite conflicting existing chapters (default false).' },
    },
    output: { schema: JSON_OUTPUT_SCHEMA, render: (_args, value) => renderJson(value) },
    timeoutMs,
    async execute(args, exec) {
      if (!args.content.trim()) throw new Error('content must be a non-empty string')
      const body: JsonObject = { content: args.content }
      if (args.filename !== undefined) body['filename'] = args.filename
      if (args.arc_id !== undefined) body['arc_id'] = args.arc_id
      if (args.start_number !== undefined) body['start_number'] = args.start_number
      if (args.force !== undefined) body['force'] = args.force
      return await client.postJson('/api/import', body, exec.signal)
    },
  }))

  ctx.tools.register(defineTool({
    name: 'novel_sync',
    description: 'Synchronize the project: rebuild derived indexes (character state, chapter memory, search index) from the source documents.',
    parameters: {},
    output: { schema: JSON_OUTPUT_SCHEMA, render: (_args, value) => renderJson(value) },
    timeoutMs,
    async execute(_args, exec) {
      return await client.postJson('/api/sync', {}, exec.signal)
    },
  }))

  ctx.tools.register(defineTool({
    name: 'novel_writing_targets',
    description:
      'Update the project writing targets. Ranges: book_words 10000-5000000, chapter_words 200-12000, ' +
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
      action: { type: 'string', required: true, enum: ['list', 'get', 'record_intervention', 'update_intervention', 'cancel'], description: 'The chapter-run operation.' },
      run_id: { type: 'string', description: 'Run id (required for get/record_intervention/update_intervention/cancel).' },
      revision: { type: 'string', description: 'Current run revision (required for mutating actions).' },
      chapter_id: { type: 'string', description: 'Chapter filter for list.' },
      statuses: { type: 'array', items: { type: 'string' }, description: 'Status filter for list.' },
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
      const body: JsonObject = { action: args.action }
      for (const key of ['run_id', 'revision', 'chapter_id', 'statuses', 'limit', 'scope', 'risk', 'request', 'affected_items', 'rewrite_required', 'intervention_id', 'state', 'facts_revision', 'impact', 'proposal', 'confirm', 'reason'] as const) {
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
      '(current_arc?, window_size? default 5), "get" (candidate_id), "stage" (candidate_id + proposal + revision — ' +
      'stages a plan proposal against the candidate; revision-gated).',
    parameters: {
      action: { type: 'string', required: true, enum: ['list', 'create', 'get', 'stage'], description: 'The rolling-plan operation.' },
      limit: { type: 'integer', description: 'List limit (default 20).' },
      current_arc: { type: 'string', description: 'Current arc id (create).' },
      window_size: { type: 'integer', description: 'Planning window size in chapters (create, default 5).' },
      candidate_id: { type: 'string', description: 'Candidate id (get/stage).' },
      proposal: { type: 'string', description: 'Plan proposal text (stage).' },
      revision: { type: 'string', description: 'Candidate revision (stage, revision-gated).' },
    },
    output: { schema: JSON_OUTPUT_SCHEMA, render: (_args, value) => renderJson(value) },
    timeoutMs,
    isConcurrencySafe: (args) => args.action === 'list' || args.action === 'get',
    async execute(args, exec) {
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
      'Chapter version snapshots and annotations. Actions: "versions" (chapter_id), "version" (chapter_id + ' +
      'version_id — returns the snapshot content), "checkpoint" (chapter_id, optional label — save a snapshot), ' +
      '"restore" (chapter_id + version_id + revision — REVERTS the chapter to a snapshot; revision-gated and ' +
      'confirmation-gated: the server demands confirm: true), "annotations" (chapter_id), "annotate" (chapter_id + ' +
      'revision + quote + note, optional start_hint/end_hint), "resolve_annotation" (chapter_id + annotation_id).',
    parameters: {
      action: { type: 'string', required: true, enum: ['versions', 'version', 'checkpoint', 'restore', 'annotations', 'annotate', 'resolve_annotation'], description: 'The manuscript-editing operation.' },
      chapter_id: { type: 'string', required: true, description: 'Chapter id (ch_<digits>).' },
      version_id: { type: 'string', description: 'Snapshot id (version/restore).' },
      label: { type: 'string', description: 'Snapshot label (checkpoint).' },
      revision: { type: 'string', description: 'Current chapter revision (restore/annotate).' },
      confirm: { type: 'boolean', description: 'Confirm a restore (required by the server).' },
      quote: { type: 'string', description: 'Annotated passage (annotate).' },
      note: { type: 'string', description: 'Annotation note (annotate).' },
      start_hint: { type: 'integer', description: 'Approximate start offset (annotate).' },
      end_hint: { type: 'integer', description: 'Approximate end offset (annotate).' },
      annotation_id: { type: 'string', description: 'Annotation id (resolve_annotation).' },
    },
    output: { schema: JSON_OUTPUT_SCHEMA, render: (_args, value) => renderJson(value) },
    timeoutMs,
    isConcurrencySafe: (args) => args.action === 'versions' || args.action === 'version' || args.action === 'annotations',
    async execute(args, exec) {
      if (!CHAPTER_ID_PATTERN.test(args.chapter_id)) throw new Error(`chapter_id must match ch_<digits>, got "${args.chapter_id}"`)
      const body: JsonObject = { action: args.action, chapter_id: args.chapter_id }
      for (const key of ['version_id', 'label', 'revision', 'confirm', 'quote', 'note', 'start_hint', 'end_hint', 'annotation_id'] as const) {
        const value = args[key]
        if (value !== undefined) body[key] = value
      }
      return await client.postJson('/api/manuscript-editing', body, exec.signal)
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
      target: { type: 'string', description: 'Promotion target (promotion_preview_v2/promote, default "all").' },
      preview_id: { type: 'string', description: 'Promotion preview id (promote_v2).' },
      confirm: { type: 'boolean', description: 'Confirm a gated promotion (default false).' },
    },
    output: { schema: JSON_OUTPUT_SCHEMA, render: (_args, value) => renderJson(value) },
    timeoutMs,
    isConcurrencySafe: (args) => args.action === 'status_v2' || args.action === 'profile_v2' || args.action === 'promotion_preview_v2',
    async execute(args, exec) {
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
    isConcurrencySafe: (args) => args.action === 'list' || args.action === 'status' || args.action === 'profile' || args.action === 'adoption_preview',
    async execute(args, exec) {
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
      const body: JsonObject = { action: args.action }
      if (args.preview_id !== undefined) body['preview_id'] = args.preview_id
      if (args.confirm !== undefined) body['confirm'] = args.confirm
      return await client.postJson('/api/rules', body, exec.signal)
    },
  }))

  // ── deep research ────────────────────────────────────────────────────────

  ctx.tools.register(defineTool({
    name: 'novel_research_status',
    description: 'Get the deep-research surface: settings status, report list, and the configured model route. Run a research job via novel_task_create with type "research".',
    parameters: {},
    output: { schema: JSON_OUTPUT_SCHEMA, render: (_args, value) => renderJson(value) },
    timeoutMs,
    isConcurrencySafe: () => true,
    async execute(_args, exec) {
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
      if (typeof args.settings !== 'object' || args.settings === null || Array.isArray(args.settings)) {
        throw new Error('settings must be a JSON object')
      }
      return await client.postJson('/api/research/settings', args.settings, exec.signal)
    },
  }))

  // ── model configuration ──────────────────────────────────────────────────

  ctx.tools.register(defineTool({
    name: 'novel_model_profiles',
    description: 'List the server\'s model profiles and per-task routing (which provider/model OpenWrite uses for writing, review, etc.).',
    parameters: {},
    output: { schema: JSON_OUTPUT_SCHEMA, render: (_args, value) => renderJson(value) },
    timeoutMs,
    isConcurrencySafe: () => true,
    async execute(_args, exec) {
      return await client.getJson('/api/model/profiles', {}, exec.signal)
    },
  }))

  ctx.tools.register(defineTool({
    name: 'novel_model_configure',
    description:
      'Apply and persist the server\'s active model connection (OpenWrite\'s own LLM for writing/review — ' +
      'independent of the dsh model). max_tokens must stay below context_tokens.',
    parameters: {
      provider: { type: 'string', enum: ['openai', 'anthropic', 'custom'], description: 'Provider (default "openai").' },
      model: { type: 'string', required: true, description: 'Model name (max 120 characters).' },
      api_key: { type: 'string', description: 'API key; omit to reuse the server environment key.' },
      base_url: { type: 'string', description: 'Base URL (required for provider "custom").' },
      api_format: { type: 'string', enum: ['chat', 'responses'], description: 'API format (default "chat").' },
      context_tokens: { type: 'integer', description: 'Context budget (min 12000).' },
      max_tokens: { type: 'integer', description: 'Max output tokens (min 256, must be < context_tokens).' },
      remember_api_key: { type: 'boolean', description: 'Persist the API key on the server (default true).' },
    },
    output: { schema: JSON_OUTPUT_SCHEMA, render: (_args, value) => renderJson(value) },
    timeoutMs,
    async execute(args, exec) {
      if (!args.model.trim() || args.model.length > 120) throw new Error('model must be non-empty and at most 120 characters')
      const body: JsonObject = { model: args.model }
      for (const key of ['provider', 'api_key', 'base_url', 'api_format', 'context_tokens', 'max_tokens', 'remember_api_key'] as const) {
        const value = args[key]
        if (value !== undefined) body[key] = value
      }
      return await client.postJson('/api/model', body, exec.signal)
    },
  }))

  ctx.tools.register(defineTool({
    name: 'novel_model_test',
    description:
      'Test a model connection without changing active settings. Pass id to test a stored profile, or a full ' +
      'candidate (provider/model/base_url/api_key...).',
    parameters: {
      id: { type: 'string', description: 'Stored profile id to test.' },
      provider: { type: 'string', enum: ['openai', 'anthropic', 'custom'], description: 'Provider (default "openai").' },
      model: { type: 'string', description: 'Model name (required when id is omitted).' },
      base_url: { type: 'string', description: 'Base URL (required for provider "custom").' },
      api_format: { type: 'string', enum: ['chat', 'responses'], description: 'API format (default "chat").' },
      api_key: { type: 'string', description: 'API key; omit to reuse the server environment key.' },
      context_tokens: { type: 'integer', description: 'Context budget.' },
      max_tokens: { type: 'integer', description: 'Max output tokens.' },
    },
    output: { schema: JSON_OUTPUT_SCHEMA, render: (_args, value) => renderJson(value) },
    timeoutMs,
    isConcurrencySafe: () => true,
    async execute(args, exec) {
      if (args.id === undefined && (args.model === undefined || !args.model.trim())) {
        throw new Error('either id (stored profile) or model (candidate) is required')
      }
      const body: JsonObject = {}
      for (const key of ['id', 'provider', 'model', 'base_url', 'api_format', 'api_key', 'context_tokens', 'max_tokens'] as const) {
        const value = args[key]
        if (value !== undefined) body[key] = value
      }
      return await client.postJson('/api/model/test', body, exec.signal)
    },
  }))

  ctx.tools.register(defineTool({
    name: 'novel_model_embedding_test',
    description:
      'Probe an embedding route without saving anything. Pass id for a stored profile, or embedding settings ' +
      'via `candidate` (e.g. embedding_provider, embedding_model, embedding_base_url, embedding_dimension).',
    parameters: {
      id: { type: 'string', description: 'Stored profile id to probe.' },
      candidate: { type: 'json', description: 'Embedding candidate settings object (merged into the request).' },
      api_key: { type: 'string', description: 'Chat API key override.' },
      embedding_api_key: { type: 'string', description: 'Embedding API key override.' },
    },
    output: { schema: JSON_OUTPUT_SCHEMA, render: (_args, value) => renderJson(value) },
    timeoutMs,
    isConcurrencySafe: () => true,
    async execute(args, exec) {
      const body: JsonObject = {}
      if (args.candidate !== undefined) {
        if (typeof args.candidate !== 'object' || args.candidate === null || Array.isArray(args.candidate)) {
          throw new Error('candidate must be a JSON object')
        }
        Object.assign(body, args.candidate)
      }
      for (const key of ['id', 'api_key', 'embedding_api_key'] as const) {
        const value = args[key]
        if (value !== undefined) body[key] = value
      }
      return await client.postJson('/api/model/embedding/test', body, exec.signal)
    },
  }))

  ctx.tools.register(defineTool({
    name: 'novel_model_profile_save',
    description: 'Save (create or update) a named model profile on the server, with optional credentials.',
    parameters: {
      profile: { type: 'json', required: true, description: 'Profile object, e.g. {"id": "fast", "label": "...", "provider": "openai", "model": "...", "base_url": "...", "max_output_tokens": 24000}.' },
      api_key: { type: 'string', description: 'Chat API key to store with the profile.' },
      embedding_api_key: { type: 'string', description: 'Embedding API key to store with the profile.' },
      remember_api_key: { type: 'boolean', description: 'Persist credentials on the server (default true).' },
    },
    output: { schema: JSON_OUTPUT_SCHEMA, render: (_args, value) => renderJson(value) },
    timeoutMs,
    async execute(args, exec) {
      if (typeof args.profile !== 'object' || args.profile === null || Array.isArray(args.profile)) {
        throw new Error('profile must be a JSON object')
      }
      const body: JsonObject = { ...args.profile }
      for (const key of ['api_key', 'embedding_api_key', 'remember_api_key'] as const) {
        const value = args[key]
        if (value !== undefined) body[key] = value
      }
      return await client.postJson('/api/model/profiles', body, exec.signal)
    },
  }))

  ctx.tools.register(defineTool({
    name: 'novel_model_profile_delete',
    description: 'Delete a stored model profile. Routes pointing at it fall back to fallback_id.',
    parameters: {
      profile_id: { type: 'string', required: true, description: 'Profile id to delete.' },
      fallback_id: { type: 'string', description: 'Profile id to reroute to (default: the server default profile).' },
    },
    output: { schema: JSON_OUTPUT_SCHEMA, render: (_args, value) => renderJson(value) },
    timeoutMs,
    async execute(args, exec) {
      if (!args.profile_id.trim()) throw new Error('profile_id must be a non-empty string')
      const body: JsonObject = { profile_id: args.profile_id }
      if (args.fallback_id !== undefined) body['fallback_id'] = args.fallback_id
      return await client.postJson('/api/model/profiles/delete', body, exec.signal)
    },
  }))

  ctx.tools.register(defineTool({
    name: 'novel_model_routes_save',
    description: 'Save per-task model routing: map operation names (e.g. "chapter_write", "review", "research") to profile ids.',
    parameters: {
      routes: { type: 'json', required: true, description: 'Object mapping operation names to profile ids.' },
    },
    output: { schema: JSON_OUTPUT_SCHEMA, render: (_args, value) => renderJson(value) },
    timeoutMs,
    async execute(args, exec) {
      if (typeof args.routes !== 'object' || args.routes === null || Array.isArray(args.routes)) {
        throw new Error('routes must be a JSON object')
      }
      return await client.postJson('/api/model/routes', { routes: args.routes }, exec.signal)
    },
  }))
}
