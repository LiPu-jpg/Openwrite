/** Runtime-checked DTO boundary for the OpenWrite Studio API. */
export type JsonRecord = Record<string, unknown>

export function asRecord(value: unknown): JsonRecord {
  return value !== null && typeof value === 'object' && !Array.isArray(value) ? value as JsonRecord : {}
}

export function unwrapData(value: unknown): JsonRecord {
  const root = asRecord(value)
  return asRecord(root['data'] ?? value)
}

export function asText(value: unknown): string {
  return typeof value === 'string' ? value : value === null || value === undefined ? '' : String(value)
}

function asTextOrNull(value: unknown): string | null {
  const text = asText(value)
  return text === '' ? null : text
}

export function asFiniteNumber(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null
}

export function asInteger(value: unknown, fallback = 0): number {
  const number = asFiniteNumber(value)
  return number === null ? fallback : Math.round(number)
}

function asStringList(value: unknown): string[] {
  return Array.isArray(value) ? value.map(asText).filter(item => item !== '') : []
}

/** Server-recorded connection-test outcome on a profile (null = untested). */
export type ModelTestRecordDto = {
  status: 'ok' | 'failed'
  tested_at: string
  latency_ms: number | null
  provider: string
  resolved_model: string
  error_code: string | null
  failed_stage: string | null
}

/** Narrow one last_test record; null when absent or malformed. */
export function parseTestRecord(value: unknown): ModelTestRecordDto | null {
  if (value === null || typeof value !== 'object' || Array.isArray(value)) return null
  const record = asRecord(value)
  const status = record['status']
  if (status !== 'ok' && status !== 'failed') return null
  return {
    status,
    tested_at: asText(record['tested_at']),
    latency_ms: asFiniteNumber(record['latency_ms']),
    provider: asText(record['provider']),
    resolved_model: asText(record['resolved_model']),
    error_code: asTextOrNull(record['error_code']),
    failed_stage: asTextOrNull(record['failed_stage']),
  }
}

export type ModelProfileDto = {
  id: string
  label: string
  provider: string
  model: string
  base_url: string
  api_format: string
  context_tokens: number
  max_output_tokens: number
  temperature: number
  timeout_seconds: number
  configured: boolean
  schema_version: string
  capabilities: { chat: boolean }
  used_by_routes: string[]
  last_test: ModelTestRecordDto | null
}

export function parseModelProfiles(value: unknown): ModelProfileDto[] {
  const root = unwrapData(value)
  const profiles = Array.isArray(root['profiles']) ? root['profiles'] : []
  return profiles.map(raw => {
    const item = asRecord(raw)
    const capabilities = asRecord(item['capabilities'])
    return {
      id: asText(item['id']), label: asText(item['label']), provider: asText(item['provider']), model: asText(item['model']),
      base_url: asText(item['base_url']), api_format: asText(item['api_format']),
      context_tokens: asInteger(item['context_tokens']), max_output_tokens: asInteger(item['max_output_tokens']),
      temperature: asFiniteNumber(item['temperature']) ?? 0.7,
      timeout_seconds: asFiniteNumber(item['timeout_seconds']) ?? 120,
      configured: item['configured'] === true,
      schema_version: asText(item['schema_version']),
      capabilities: { chat: capabilities['chat'] === true },
      used_by_routes: asStringList(item['used_by_routes']),
      last_test: parseTestRecord(item['last_test']),
    }
  }).filter(item => item.id !== '')
}

export function parseRouteMap(value: unknown): Record<string, string> {
  const root = unwrapData(value)
  const routes = asRecord(root['routes'])
  return Object.fromEntries(Object.entries(routes).map(([key, route]) => [key, asText(route)]))
}

/** Success payload of POST /model/test and /model/embedding/test (enveloped). */
export type ConnectionTestResultDto = {
  status: string
  provider: string
  model: string
  latency_ms: number | null
  tested_at: string
  reply: string
}

export function parseConnectionTestResult(value: unknown): ConnectionTestResultDto {
  const root = unwrapData(value)
  return {
    status: asText(root['status']),
    provider: asText(root['provider']),
    model: asText(root['model']),
    latency_ms: asFiniteNumber(root['latency_ms']),
    tested_at: asText(root['tested_at']),
    reply: asText(root['reply']),
  }
}

/** Read-only payload of POST /model/profiles/delete-preview (enveloped). */
export type DeletePreviewDto = {
  profile_id: string
  used_by_routes: string[]
  routes_that_would_fail: string[]
  fallback_candidates: { id: string; label: string; configured: boolean }[]
  resulting_routes: Record<string, string> | null
  deletable: boolean
  blocking_reasons: string[]
}

export function parseDeletePreview(value: unknown): DeletePreviewDto {
  const root = unwrapData(value)
  const candidates = Array.isArray(root['fallback_candidates']) ? root['fallback_candidates'] : []
  const resulting = root['resulting_routes']
  return {
    profile_id: asText(root['profile_id']),
    used_by_routes: asStringList(root['used_by_routes']),
    routes_that_would_fail: asStringList(root['routes_that_would_fail']),
    fallback_candidates: candidates.map(raw => {
      const item = asRecord(raw)
      return { id: asText(item['id']), label: asText(item['label']), configured: item['configured'] === true }
    }).filter(item => item.id !== ''),
    resulting_routes: resulting === null || resulting === undefined
      ? null
      : Object.fromEntries(Object.entries(asRecord(resulting)).map(([key, route]) => [key, asText(route)])),
    deletable: root['deletable'] === true,
    blocking_reasons: asStringList(root['blocking_reasons']),
  }
}

/** Response data of POST /model/routes: the swapped map plus the change impact. */
export type RouteImpactDto = {
  routes: Record<string, string>
  changed_routes: { route: string; from: string; to: string }[]
  profiles_affected: string[]
}

export function parseRouteImpact(value: unknown): RouteImpactDto {
  const root = unwrapData(value)
  const impact = asRecord(root['impact'])
  const changed = Array.isArray(impact['changed_routes']) ? impact['changed_routes'] : []
  // The HTTP answer nests the swapped map under model_profiles (the full
  // surface); older/mocked answers may carry a top-level routes map.
  const topLevel = asRecord(root['routes'])
  const nested = asRecord(asRecord(root['model_profiles'])['routes'])
  const routes = Object.keys(topLevel).length > 0 ? topLevel : nested
  return {
    routes: Object.fromEntries(Object.entries(routes).map(([key, route]) => [key, asText(route)])),
    changed_routes: changed.map(raw => {
      const item = asRecord(raw)
      return { route: asText(item['route']), from: asText(item['from']), to: asText(item['to']) }
    }),
    profiles_affected: asStringList(impact['profiles_affected']),
  }
}

/** Real progress units on a task (benchmark tasks report candidate/evaluation units). */
export type TaskProgressDto = {
  completed_units: number
  total_units: number
  ratio: number | null
  unit_kind: string
}

export function parseTaskProgress(value: unknown): TaskProgressDto | null {
  if (value === null || typeof value !== 'object' || Array.isArray(value)) return null
  const record = asRecord(value)
  return {
    completed_units: asInteger(record['completed_units']),
    total_units: asInteger(record['total_units']),
    ratio: asFiniteNumber(record['ratio']),
    unit_kind: asText(record['unit_kind']),
  }
}

/** Pointer from a finished task to its artifact (e.g. a benchmark run). */
export type ResultRefDto = {
  type: string
  id: string
}

export function parseResultRef(value: unknown): ResultRefDto | null {
  if (value === null || typeof value !== 'object' || Array.isArray(value)) return null
  const record = asRecord(value)
  const id = asText(record['id'])
  return id === '' ? null : { type: asText(record['type']), id }
}

export type ExportFormatDto = 'md' | 'txt' | 'epub'
export type ExportPurposeDto = 'backup' | 'delivery'

export type ExportChapterDto = {
  chapter_id: string
  number: number
  path: string
  title: string
  writing_units: number
  empty: boolean
  revision: string
}

export type ExportIssueDto = {
  code: string
  message: string
  details: JsonRecord
}

export type ExportPreflightDto = {
  schema_version: string
  novel_id: string
  format: ExportFormatDto
  purpose: ExportPurposeDto
  can_export: boolean
  actual_order: string[]
  chapters: ExportChapterDto[]
  structure: {
    duplicates: Record<string, string[]>
    missing: string[]
    empty: string[]
    unreadable: string[]
  }
  writing_units: {
    total: number
    book_target: number
    chapter_target: number
    completion_ratio: number | null
  }
  metadata: { title: string; author: string; language: string }
  reviews: {
    missing: string[]
    current: string[]
    stale: string[]
    approved: string[]
    not_approved: string[]
  }
  manuscript_acceptance: { status: string; blocking: boolean; blocking_chapters: string[]; needs_review: string[] }
  blockers: ExportIssueDto[]
  warnings: ExportIssueDto[]
  preflight_revision: string
}

function exportFormat(value: unknown): ExportFormatDto {
  return value === 'txt' || value === 'epub' ? value : 'md'
}

function exportPurpose(value: unknown): ExportPurposeDto {
  return value === 'backup' ? 'backup' : 'delivery'
}

function stringMap(value: unknown): Record<string, string[]> {
  return Object.fromEntries(Object.entries(asRecord(value)).map(([key, entry]) => [key, asStringList(entry)]))
}

function exportIssues(value: unknown): ExportIssueDto[] {
  if (!Array.isArray(value)) return []
  return value.map(raw => {
    const item = asRecord(raw)
    return {
      code: asText(item['code']),
      message: asText(item['message']),
      details: asRecord(item['details']),
    }
  }).filter(issue => issue.code !== '' || issue.message !== '')
}

/** Runtime-check the stable `openwrite.export-preflight.v1` success envelope. */
export function parseExportPreflight(value: unknown): ExportPreflightDto {
  const root = unwrapData(value)
  const structure = asRecord(root['structure'])
  const writingUnits = asRecord(root['writing_units'])
  const metadata = asRecord(root['metadata'])
  const reviews = asRecord(root['reviews'])
  const acceptance = asRecord(root['manuscript_acceptance'])
  const chaptersRaw = Array.isArray(root['chapters']) ? root['chapters'] : []
  const chapters = chaptersRaw.map(raw => {
    const chapter = asRecord(raw)
    return {
      chapter_id: asText(chapter['chapter_id']),
      number: asInteger(chapter['number']),
      path: asText(chapter['path']),
      title: asText(chapter['title']),
      writing_units: asInteger(chapter['writing_units']),
      empty: chapter['empty'] === true,
      revision: asText(chapter['revision']),
    }
  }).filter(chapter => chapter.chapter_id !== '')
  const actualOrder = asStringList(root['actual_order'])

  return {
    schema_version: asText(root['schema_version']),
    novel_id: asText(root['novel_id']),
    format: exportFormat(root['format']),
    purpose: exportPurpose(root['purpose']),
    can_export: root['can_export'] === true,
    actual_order: actualOrder.length > 0 ? actualOrder : chapters.map(chapter => chapter.chapter_id),
    chapters,
    structure: {
      duplicates: stringMap(structure['duplicates']),
      missing: asStringList(structure['missing']),
      empty: asStringList(structure['empty']),
      unreadable: asStringList(structure['unreadable']),
    },
    writing_units: {
      total: asInteger(writingUnits['total']),
      book_target: asInteger(writingUnits['book_target']),
      chapter_target: asInteger(writingUnits['chapter_target']),
      completion_ratio: asFiniteNumber(writingUnits['completion_ratio']),
    },
    metadata: {
      title: asText(metadata['title']), author: asText(metadata['author']), language: asText(metadata['language']),
    },
    reviews: {
      missing: asStringList(reviews['missing']),
      current: asStringList(reviews['current']),
      stale: asStringList(reviews['stale']),
      approved: asStringList(reviews['approved']),
      not_approved: asStringList(reviews['not_approved']),
    },
    manuscript_acceptance: {
      status: asText(acceptance['status']), blocking: acceptance['blocking'] === true,
      blocking_chapters: asStringList(acceptance['blocking_chapters']), needs_review: asStringList(acceptance['needs_review']),
    },
    blockers: exportIssues(root['blockers']),
    warnings: exportIssues(root['warnings']),
    preflight_revision: asText(root['preflight_revision']),
  }
}

export const IMPORT_STAGE_NAMES = [
  'snapshot', 'split', 'structure_confirmed', 'published', 'acceptance', 'reconcile', 'synthesis', 'complete',
] as const
export type ImportStageNameDto = typeof IMPORT_STAGE_NAMES[number]

export type ImportStageDto = {
  status: string
  attempts: number
  input_sha256: string
  output_sha256: string
  started_at: string
  completed_at: string
  error_code: string
}

export type ManuscriptImportOperationDto = {
  schema_version: string
  import_id: string
  novel_id: string
  status: string
  arc_id: string
  source: { filename: string; suffix: string; bytes: number; sha256: string }
  preview_revision: string
  confirmed_preview_revision: string
  chapter_count: number
  writing_units: number
  progress: { current_stage: string; completed_stages: number; total_stages: number; published_chapters: number; total_chapters: number }
  stages: Record<ImportStageNameDto, ImportStageDto>
  publication: { sha256: string; swap_status: string; committed: boolean }
  acceptance: { operation_id: string; status: string }
  synthesis_sha256: string
  failure: { code: string; stage: string; recoverable: boolean } | null
  created_at: string
  updated_at: string
  completed_at: string
  discarded_at: string
}

export type ManuscriptImportChapterDto = {
  order: number
  chapter_id: string
  title: string
  content: string
  writing_units: number
  sha256: string
}

export type ManuscriptImportPreviewDto = {
  schema_version: string
  import_id: string
  arc_id: string
  source_sha256: string
  revision: string
  chapter_count: number
  writing_units: number
  chapters: ManuscriptImportChapterDto[]
  updated_at: string
}

function parseImportOperation(value: unknown): ManuscriptImportOperationDto {
  const root = asRecord(value)
  const source = asRecord(root['source'])
  const progress = asRecord(root['progress'])
  const stagesRoot = asRecord(root['stages'])
  const stages = Object.fromEntries(IMPORT_STAGE_NAMES.map(name => {
    const stage = asRecord(stagesRoot[name])
    return [name, {
      status: asText(stage['status']) || 'pending', attempts: asInteger(stage['attempts']),
      input_sha256: asText(stage['input_sha256']), output_sha256: asText(stage['output_sha256']),
      started_at: asText(stage['started_at']), completed_at: asText(stage['completed_at']),
      error_code: asText(stage['error_code']),
    }]
  })) as Record<ImportStageNameDto, ImportStageDto>
  const completedStages = IMPORT_STAGE_NAMES.filter(name => stages[name].status === 'completed').length
  const currentStage = asText(progress['current_stage']) || IMPORT_STAGE_NAMES.find(name => stages[name].status !== 'completed') || 'complete'
  const publicationRaw = asRecord(root['publication'])
  const transaction = asRecord(root['publication_transaction'])
  const acceptanceRaw = asRecord(root['acceptance'])
  const failureRaw = asRecord(root['failure'] ?? root['last_error'])
  const published = Array.isArray(root['published_chapters']) ? root['published_chapters'].length : 0
  return {
    schema_version: asText(root['schema_version']), import_id: asText(root['import_id']), novel_id: asText(root['novel_id']),
    status: asText(root['status']), arc_id: asText(root['arc_id']),
    source: {
      filename: asText(source['filename']), suffix: asText(source['suffix']), bytes: asInteger(source['bytes']), sha256: asText(source['sha256']),
    },
    preview_revision: asText(root['preview_revision']), confirmed_preview_revision: asText(root['confirmed_preview_revision']),
    chapter_count: asInteger(root['chapter_count']), writing_units: asInteger(root['writing_units']),
    progress: {
      current_stage: currentStage, completed_stages: asFiniteNumber(progress['completed_stages']) === null ? completedStages : asInteger(progress['completed_stages']),
      total_stages: asInteger(progress['total_stages'], IMPORT_STAGE_NAMES.length),
      published_chapters: asFiniteNumber(progress['published_chapters']) === null ? published : asInteger(progress['published_chapters']),
      total_chapters: asFiniteNumber(progress['total_chapters']) === null ? asInteger(root['chapter_count']) : asInteger(progress['total_chapters']),
    },
    stages,
    publication: {
      sha256: asText(publicationRaw['sha256'] ?? root['publication_sha256']),
      swap_status: asText(publicationRaw['swap_status'] ?? transaction['swap_status']),
      committed: publicationRaw['committed'] === true || transaction['swap_status'] === 'committed',
    },
    acceptance: {
      operation_id: asText(acceptanceRaw['operation_id'] ?? root['acceptance_operation_id']),
      status: asText(acceptanceRaw['status'] ?? root['acceptance_status']),
    },
    synthesis_sha256: asText(root['synthesis_sha256']),
    failure: Object.keys(failureRaw).length === 0 ? null : {
      code: asText(failureRaw['code']), stage: asText(failureRaw['stage']), recoverable: failureRaw['recoverable'] !== false,
    },
    created_at: asText(root['created_at']), updated_at: asText(root['updated_at']),
    completed_at: asText(root['completed_at']), discarded_at: asText(root['discarded_at']),
  }
}

function parseImportPreview(value: unknown): ManuscriptImportPreviewDto | null {
  if (value === null || value === undefined) return null
  const root = asRecord(value)
  const chaptersRaw = Array.isArray(root['chapters']) ? root['chapters'] : []
  return {
    schema_version: asText(root['schema_version']), import_id: asText(root['import_id']), arc_id: asText(root['arc_id']),
    source_sha256: asText(root['source_sha256']), revision: asText(root['revision']),
    chapter_count: asInteger(root['chapter_count']), writing_units: asInteger(root['writing_units']),
    chapters: chaptersRaw.map(raw => {
      const chapter = asRecord(raw)
      return {
        order: asInteger(chapter['order']), chapter_id: asText(chapter['chapter_id']), title: asText(chapter['title']),
        content: asText(chapter['content']), writing_units: asInteger(chapter['writing_units']), sha256: asText(chapter['sha256']),
      }
    }).filter(chapter => chapter.chapter_id !== ''),
    updated_at: asText(root['updated_at']),
  }
}

export function parseManuscriptImportList(value: unknown): { schema_version: string; novel_id: string; operations: ManuscriptImportOperationDto[]; counts: Record<string, number> } {
  const root = unwrapData(value)
  const operations = Array.isArray(root['operations']) ? root['operations'].map(parseImportOperation).filter(item => item.import_id !== '') : []
  return {
    schema_version: asText(root['schema_version']), novel_id: asText(root['novel_id']), operations,
    counts: Object.fromEntries(Object.entries(asRecord(root['counts'])).map(([status, count]) => [status, asInteger(count)])),
  }
}

export function parseManuscriptImportDetail(value: unknown): { operation: ManuscriptImportOperationDto; preview: ManuscriptImportPreviewDto | null } {
  const root = unwrapData(value)
  return { operation: parseImportOperation(root['operation']), preview: parseImportPreview(root['preview']) }
}

export type ArchiveFileDto = { path: string; archive_path: string; category: string; sha256: string; size: number }
export type ArchiveNoticeDto = {
  path: string
  location: string
  kind: string
  source: string
  target: string
  source_path: string
  target_path: string
  source_paths: string[]
  format: string
  value: string
  before: string
  after: string
  message: string
  reason: string
  state: string
  sha256_before: string
  sha256_after: string
  reference_count: number
  replacement_count: number
}

function archiveNotices(value: unknown): ArchiveNoticeDto[] {
  if (!Array.isArray(value)) return []
  return value.map(raw => {
    const item = asRecord(raw)
    return {
      path: asText(item['path']), location: asText(item['location']), kind: asText(item['kind']),
      source: asText(item['source']), target: asText(item['target']),
      source_path: asText(item['source_path']), target_path: asText(item['target_path']), source_paths: asStringList(item['source_paths']),
      format: asText(item['format']), value: asText(item['value']), before: asText(item['before']), after: asText(item['after']),
      message: asText(item['message']), reason: asText(item['reason']), state: asText(item['state']),
      sha256_before: asText(item['sha256_before']), sha256_after: asText(item['sha256_after']),
      reference_count: asInteger(item['reference_count']), replacement_count: asInteger(item['replacement_count']),
    }
  })
}

export type ProjectArchivePlanDto = {
  schema_version: string
  novel_id: string
  archive_id: string
  preflight_revision: string
  includes: { roots: string[]; file_count: number; total_size: number; category_counts: Record<string, number>; directories: string[]; files: ArchiveFileDto[] }
  excludes: { rules: string[]; entries: ArchiveNoticeDto[] }
  missing: { required: string[]; optional: ArchiveNoticeDto[] }
  reference_inventory: { known: ArchiveNoticeDto[]; preserved: ArchiveNoticeDto[]; warnings: ArchiveNoticeDto[] }
  policies: { tasks: string; target: string; reference_default: string; reference_supported: string[] }
}

function parseArchivePlanRoot(root: JsonRecord): ProjectArchivePlanDto {
  const includes = asRecord(root['includes'])
  const excludes = asRecord(root['excludes'])
  const missing = asRecord(root['missing'])
  const inventory = asRecord(root['reference_inventory'])
  const policies = asRecord(root['policies'])
  const referencePolicy = asRecord(policies['references'])
  const filesRaw = Array.isArray(includes['files']) ? includes['files'] : []
  return {
    schema_version: asText(root['schema_version']), novel_id: asText(root['novel_id'] ?? asRecord(root['source'])['novel_id']),
    archive_id: asText(root['archive_id']), preflight_revision: asText(root['preflight_revision']),
    includes: {
      roots: asStringList(includes['roots']), file_count: asInteger(includes['file_count']), total_size: asInteger(includes['total_size']),
      category_counts: Object.fromEntries(Object.entries(asRecord(includes['category_counts'])).map(([key, count]) => [key, asInteger(count)])),
      directories: asStringList(includes['directories']),
      files: filesRaw.map(raw => {
        const file = asRecord(raw)
        return { path: asText(file['path']), archive_path: asText(file['archive_path']), category: asText(file['category']), sha256: asText(file['sha256']), size: asInteger(file['size']) }
      }).filter(file => file.path !== ''),
    },
    excludes: { rules: asStringList(excludes['rules']), entries: archiveNotices(excludes['entries'] ?? root['excludes']) },
    missing: { required: asStringList(missing['required']), optional: archiveNotices(missing['optional']) },
    reference_inventory: {
      known: archiveNotices(inventory['known']), preserved: archiveNotices(inventory['preserved']), warnings: archiveNotices(inventory['warnings']),
    },
    policies: {
      tasks: asText(policies['tasks']), target: asText(policies['target']),
      reference_default: asText(referencePolicy['default']), reference_supported: asStringList(referencePolicy['supported']),
    },
  }
}

export function parseProjectArchivePreflight(value: unknown): ProjectArchivePlanDto {
  return parseArchivePlanRoot(unwrapData(value))
}

export type ProjectArchiveSummaryDto = { archive_id: string; archive_sha256: string; created_at: string; file_count: number; total_size: number; missing_required: string[]; missing_optional: ArchiveNoticeDto[] }

export function parseProjectArchiveList(value: unknown): { schema_version: string; novel_id: string; archives: ProjectArchiveSummaryDto[] } {
  const root = unwrapData(value)
  const raw = Array.isArray(root['archives']) ? root['archives'] : []
  return {
    schema_version: asText(root['schema_version']), novel_id: asText(root['novel_id']),
    archives: raw.map(value => {
      const item = asRecord(value)
      const missing = asRecord(item['missing'])
      return {
        archive_id: asText(item['archive_id']), archive_sha256: asText(item['archive_sha256']), created_at: asText(item['created_at']),
        file_count: asInteger(item['file_count']), total_size: asInteger(item['total_size']),
        missing_required: asStringList(missing['required']), missing_optional: archiveNotices(missing['optional']),
      }
    }).filter(item => item.archive_id !== ''),
  }
}

export function parseProjectArchiveDetail(value: unknown): { archive_sha256: string; file_count: number; total_size: number; plan: ProjectArchivePlanDto } {
  const root = asRecord(unwrapData(value)['archive'])
  const manifest = asRecord(root['manifest'])
  return {
    archive_sha256: asText(root['archive_sha256']), file_count: asInteger(root['file_count']), total_size: asInteger(root['total_size']),
    plan: parseArchivePlanRoot(manifest),
  }
}

export type ProjectRestorePreviewDto = {
  archive_id: string
  archive_sha256: string
  source_novel_id: string
  target_novel_id: string
  target_root: string
  reference_policy: 'preserve_relative' | 'rewrite_novel_id'
  can_restore: boolean
  conflicts: string[]
  file_count: number
  total_size: number
  missing: { required: string[]; optional: ArchiveNoticeDto[] }
  task_file_count: number
  task_archive_path: string
  auto_resume_tasks: boolean
  path_rewrites: ArchiveNoticeDto[]
  rewritten_files: ArchiveNoticeDto[]
  rewritten_references: ArchiveNoticeDto[]
  preserved_references: ArchiveNoticeDto[]
  reference_warnings: ArchiveNoticeDto[]
  reference_conflicts: ArchiveNoticeDto[]
}

export function parseProjectRestorePreview(value: unknown): ProjectRestorePreviewDto {
  const root = unwrapData(value)
  const missing = asRecord(root['missing'])
  return {
    archive_id: asText(root['archive_id']), archive_sha256: asText(root['archive_sha256']),
    source_novel_id: asText(root['source_novel_id']), target_novel_id: asText(root['target_novel_id']), target_root: asText(root['target_root']),
    reference_policy: root['reference_policy'] === 'rewrite_novel_id' ? 'rewrite_novel_id' : 'preserve_relative',
    can_restore: root['can_restore'] === true, conflicts: asStringList(root['conflicts']),
    file_count: asInteger(root['file_count']), total_size: asInteger(root['total_size']),
    missing: { required: asStringList(missing['required']), optional: archiveNotices(missing['optional']) },
    task_file_count: asInteger(root['task_file_count']), task_archive_path: asText(root['task_archive_path']), auto_resume_tasks: root['auto_resume_tasks'] === true,
    path_rewrites: archiveNotices(root['path_rewrites']), rewritten_files: archiveNotices(root['rewritten_files']),
    rewritten_references: archiveNotices(root['rewritten_references']), preserved_references: archiveNotices(root['preserved_references']),
    reference_warnings: archiveNotices(root['reference_warnings']), reference_conflicts: archiveNotices(root['reference_conflicts']),
  }
}

export type ChapterWorkEventDto = {
  kind: string
  id: string
  status: string
  document_id: string
  path: string
  chapter_id: string
  revision: string
  updated_at: string
  writing_units_delta: number | null
  reason: string
}

export type ReadingOrderDocumentDto = {
  document_id: string
  occurrence_id: string
  chapter_id: string
  title: string
  path: string
  status: string
  volume_id: string
  writing_units: number
  revision: string
  updated_at: string
  reading_index: number
  previous_occurrence_id: string
  next_occurrence_id: string
  content: string
}

export type ReadingOrderDto = {
  schema_version: string
  novel_id: string
  revision: string
  mode: string
  mutation_allowed: boolean
  actual_order: string[]
  volumes: { volume_id: string; title: string; order: number; occurrence_ids: string[] }[]
  documents: ReadingOrderDocumentDto[]
  issues: unknown[]
}

export type ReadingPacketDto = {
  schema_version: string
  novel_id: string
  revision: string
  anchor_document_id: string
  anchor_occurrence_id: string
  start_index: number
  end_index: number
  has_previous: boolean
  has_next: boolean
  complete: boolean
  documents: ReadingOrderDocumentDto[]
  issues: unknown[]
}

function readingOrderDocuments(value: unknown): ReadingOrderDocumentDto[] {
  return (Array.isArray(value) ? value : []).map(raw => {
    const item = asRecord(raw)
    const volume = asRecord(item['volume'])
    return {
      document_id: asText(item['document_id']), occurrence_id: asText(item['occurrence_id']), chapter_id: asText(item['chapter_id']),
      title: asText(item['title']), path: asText(item['path']), status: asText(item['status']), volume_id: asText(volume['volume_id']), writing_units: asInteger(item['writing_units']),
      revision: asText(item['revision']), updated_at: asText(item['updated_at']), reading_index: asInteger(item['reading_index']),
      previous_occurrence_id: asText(item['previous_occurrence_id']), next_occurrence_id: asText(item['next_occurrence_id']),
      content: asText(item['content']),
    }
  }).filter(item => item.occurrence_id !== '' && item.document_id !== '')
}

/** Canonical reading order. Every occurrence is retained, including repeated documents. */
export function parseReadingOrder(value: unknown): ReadingOrderDto {
  const root = unwrapData(value)
  const volumes = (Array.isArray(root['volumes']) ? root['volumes'] : []).map(raw => {
    const item = asRecord(raw)
    return {
      volume_id: asText(item['volume_id']), title: asText(item['title']), order: asInteger(item['order']),
      occurrence_ids: asStringList(item['occurrence_ids']),
    }
  }).filter(item => item.volume_id !== '')
  return {
    schema_version: asText(root['schema_version']), novel_id: asText(root['novel_id']), revision: asText(root['revision']),
    mode: asText(root['mode']), mutation_allowed: root['mutation_allowed'] === true, actual_order: asStringList(root['actual_order']), volumes,
    documents: readingOrderDocuments(root['documents']), issues: Array.isArray(root['issues']) ? root['issues'] : [],
  }
}

/** Bounded continuous-reading packet with immutable occurrence identities. */
export function parseReadingPacket(value: unknown): ReadingPacketDto {
  const root = unwrapData(value)
  return {
    schema_version: asText(root['schema_version']), novel_id: asText(root['novel_id']), revision: asText(root['revision']),
    anchor_document_id: asText(root['anchor_document_id']), anchor_occurrence_id: asText(root['anchor_occurrence_id']),
    start_index: asInteger(root['start_index']), end_index: asInteger(root['end_index']),
    has_previous: root['has_previous'] === true, has_next: root['has_next'] === true, complete: root['complete'] === true,
    documents: readingOrderDocuments(root['documents']), issues: Array.isArray(root['issues']) ? root['issues'] : [],
  }
}

export type DocumentChangePlanDto = {
  applied: boolean
  changed: boolean
  status: string
  path: string
  revision: string
  diff: string
  preview_token: string
  undo_preview_token: string
  mutation_summary: {
    execution_status: string
    source_revision: string
    result_revision: string
  }
}

/** Server-owned immutable document change preview/apply projection. */
export function parseDocumentChangePlan(value: unknown): DocumentChangePlanDto {
  const root = unwrapData(value)
  const summary = asRecord(root['mutation_summary'])
  return {
    applied: root['applied'] === true,
    changed: root['changed'] === true,
    status: asText(root['status']),
    path: asText(root['path']),
    revision: asText(root['revision']),
    diff: asText(root['diff']),
    preview_token: asText(root['preview_token']),
    undo_preview_token: asText(root['undo_preview_token']),
    mutation_summary: {
      execution_status: asText(summary['execution_status']),
      source_revision: asText(summary['source_revision']),
      result_revision: asText(summary['result_revision']),
    },
  }
}

export type ChapterWorkBriefDto = {
  schema_version: string
  novel_id: string
  chapter_id: string
  document_id: string
  manuscript: {
    path: string
    title: string
    save_status: string
    current_revision: string
    writing_units: number
    modified_at: string
  }
  review: {
    exists: boolean
    review_revision: string
    freshness_status: string
    stale: boolean
    stale_reason: string
    source_revision: string
    current_source_revision: string
    reviewed_at: string
    issue_count: number
    latest_closure: null | {
      closure_id: string
      proposal_id: string
      source_review_revision: string
      rereview_review_revision: string
      applied_revision: string
      rereview_source_revision: string
      closed_at: string
      issue_outcomes: { issue_id: string; outcome: 'resolved' | 'retained' }[]
      regressions: { issue_id: string; outcome: 'regressed'; issue: unknown }[]
    }
  }
  target: {
    writing_units: number
    source: string
    actual_units: number
    remaining_units: number
    progress: number
  }
  recent_edits: ChapterWorkEventDto[]
}

function parseClosureOutcome(value: unknown): { issue_id: string; outcome: 'resolved' | 'retained' } | null {
  const item = asRecord(value)
  const issueId = asText(item['issue_id'])
  const outcome = item['outcome']
  return issueId !== '' && (outcome === 'resolved' || outcome === 'retained') ? { issue_id: issueId, outcome } : null
}

function parseClosureRegression(value: unknown): { issue_id: string; outcome: 'regressed'; issue: unknown } | null {
  const item = asRecord(value)
  const issueId = asText(item['issue_id'])
  return issueId !== '' && item['outcome'] === 'regressed'
    ? { issue_id: issueId, outcome: 'regressed', issue: item['issue'] }
    : null
}

/** Narrow the chapter work projection used by editor CAS and activity UI. */
export function parseChapterWorkBrief(value: unknown): ChapterWorkBriefDto {
  const root = unwrapData(value)
  const manuscript = asRecord(root['manuscript'])
  const review = asRecord(root['review'])
  const latestClosureRaw = review['latest_closure']
  const latestClosure = latestClosureRaw !== null && typeof latestClosureRaw === 'object' && !Array.isArray(latestClosureRaw)
    ? asRecord(latestClosureRaw) : null
  const target = asRecord(root['target'])
  const events = Array.isArray(root['recent_edits']) ? root['recent_edits'] : []
  return {
    schema_version: asText(root['schema_version']),
    novel_id: asText(root['novel_id']),
    chapter_id: asText(root['chapter_id']),
    document_id: asText(root['document_id']),
    manuscript: {
      path: asText(manuscript['path']), title: asText(manuscript['title']), save_status: asText(manuscript['save_status']),
      current_revision: asText(manuscript['current_revision']), writing_units: asInteger(manuscript['writing_units']), modified_at: asText(manuscript['modified_at']),
    },
    review: {
      exists: review['exists'] === true, review_revision: asText(review['review_revision']), freshness_status: asText(review['freshness_status']),
      stale: review['stale'] === true, stale_reason: asText(review['stale_reason']), source_revision: asText(review['source_revision']),
      current_source_revision: asText(review['current_source_revision']), reviewed_at: asText(review['reviewed_at']), issue_count: asInteger(review['issue_count']),
      latest_closure: latestClosure === null ? null : {
        closure_id: asText(latestClosure['closure_id']), proposal_id: asText(latestClosure['proposal_id']),
        source_review_revision: asText(latestClosure['source_review_revision']), rereview_review_revision: asText(latestClosure['rereview_review_revision']),
        applied_revision: asText(latestClosure['applied_revision']), rereview_source_revision: asText(latestClosure['rereview_source_revision']),
        closed_at: asText(latestClosure['closed_at']),
        issue_outcomes: (Array.isArray(latestClosure['issue_outcomes']) ? latestClosure['issue_outcomes'] : [])
          .map(parseClosureOutcome).filter((item): item is NonNullable<typeof item> => item !== null),
        regressions: (Array.isArray(latestClosure['regressions']) ? latestClosure['regressions'] : [])
          .map(parseClosureRegression).filter((item): item is NonNullable<typeof item> => item !== null),
      },
    },
    target: {
      writing_units: asInteger(target['writing_units']), source: asText(target['source']), actual_units: asInteger(target['actual_units']),
      remaining_units: asInteger(target['remaining_units']), progress: asFiniteNumber(target['progress']) ?? 0,
    },
    recent_edits: events.map(raw => {
      const item = asRecord(raw)
      return {
        kind: asText(item['kind']), id: asText(item['id']), status: asText(item['status']), document_id: asText(item['document_id']),
        path: asText(item['path']), chapter_id: asText(item['chapter_id']), revision: asText(item['revision']), updated_at: asText(item['updated_at']),
        writing_units_delta: asFiniteNumber(item['writing_units_delta']), reason: asText(item['reason']),
      }
    }).filter(item => item.kind !== '' && item.updated_at !== ''),
  }
}
