import type { Context } from '@deepseek-ai/cordis'
import type { ToolExecution } from '@deepseek-ai/dsh-tools'
import type {} from '@deepseek-ai/dsh-sandbox-policy'
import type {} from '@deepseek-ai/dsh-plan-mode'

export type NovelEffect = 'read' | 'write' | 'generate'
// Only unconditionally read-only tools belong here. An action-dispatching tool
// must NOT be listed: `reads` short-circuits before `readActions`, so a merged
// family placed here has all of its mutating actions (delete, configure,
// save_routes) classified as reads and run under a read-only sandbox or plan
// mode. `novel_model_profiles` / `novel_embedding_profiles` were listed here by
// mistake after the 95→56 merge; their read-only actions are in `readActions`.
const reads = new Set([
  'novel_status', 'novel_review_framework', 'novel_trace_list',
  'novel_context_preview', 'novel_outline_read', 'novel_reading_packet',
  'novel_chapter_work', 'novel_chapter_scenes', 'novel_search', 'novel_continuity', 'novel_diagnostics',
  'novel_research_status', 'novel_research_report',
  'novel_manuscript_acceptance', 'novel_manuscript_metrics', 'novel_outline_audit',
])
const generates = new Set([
  'novel_write_chapter', 'novel_review_chapter', 'novel_multi_write',
  'novel_revision_regenerate', 'novel_settle_backfill',
])
const readActions: Record<string, readonly string[]> = {
  novel_writing_assets: ['get'],
  novel_model_benchmark: ['list', 'get', 'options'],
  novel_chapter_run_action: ['list', 'get'],
  novel_rolling_plan_action: ['list', 'get'],
  novel_narrative_forecast_action: ['list', 'get'],
  novel_manuscript_edit_action: ['drafts', 'versions', 'version', 'compare', 'annotations'],
  novel_source_action: ['status_v2', 'profile_v2'],
  novel_reference_library_action: ['list', 'status', 'profile'],
  novel_runtime_skill_action: ['list', 'diagnose', 'resolve'],
  novel_rule_action: ['status'],
  // Merged tools: the read-only actions of each family.
  novel_task: ['get', 'list'],
  novel_revision: ['list', 'get'],
  novel_assets: ['list', 'read'],
  novel_assets_package: ['preview'],
  novel_doc: ['read'],
  novel_scene: ['structure'],
  novel_scene_migration: ['preview'],
  novel_reading_order: ['get'],
  novel_export: ['preflight'],
  // `download` is NOT here: it writes a local file (mkdir + writeFile under
  // outputDir), so classifying it as a read would let a read-only sandbox or plan
  // mode write bytes to disk — the same class of mistake as the assets-package
  // export. Its archive_op read variants are covered by the write classification
  // being fail-closed rather than permissive.
  novel_model_profiles: ['list', 'test'],
  novel_embedding_profiles: ['list', 'test'],
}
/** Merged tools whose creating/generating actions replace the old per-tool names. */
const generateActions: Record<string, readonly string[]> = {
  novel_task: ['create', 'retry', 'confirm'],
  novel_revision: ['create'],
}

/** Unknown and preview operations fail closed: previews can persist confirmation records. */
export function novelEffect(name: string, args: unknown): NovelEffect {
  if (reads.has(name)) return 'read'
  const values = args && typeof args === 'object' ? args as Record<string, unknown> : {}
  if (name === 'novel_write_chapter' && values.dry_run === true) return 'read'
  if (readActions[name]?.includes(String(values.action))) return 'read'
  if (name === 'novel_model_benchmark' && values.action === 'run') return 'generate'
  if (generateActions[name]?.includes(String(values.action))) return 'generate'
  return generates.has(name) ? 'generate' : 'write'
}

export function novelPolicyDenial(ctx: Context, execution: Readonly<ToolExecution>): string | undefined {
  if (!execution.name.startsWith('novel_')) return
  const effect = novelEffect(execution.name, execution.arguments)
  if (effect === 'read') return
  const agent = execution.agent
  if (!agent) return 'OPENWRITE_POLICY_REQUIRED: writing requires an Agent session'
  // Plan state can live in the preset realm; consult the executing Agent.
  const plan = agent.ctx.get('planMode')
  if (plan?.get(agent).active) return 'OPENWRITE_PLAN_MODE: plan mode cannot generate or persist changes'
  const policy = ctx.get('sandboxPolicy')
  if (!policy || policy.resolve({ session: agent.session }).mode === 'read-only') {
    return 'OPENWRITE_READ_ONLY: the session does not permit writing'
  }
  return
}
