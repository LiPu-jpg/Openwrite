import type { Context } from '@deepseek-ai/cordis'
import type { ToolExecution } from '@deepseek-ai/dsh-tools'
import type {} from '@deepseek-ai/dsh-sandbox-policy'
import type {} from '@deepseek-ai/dsh-plan-mode'

export type NovelEffect = 'read' | 'write' | 'generate'
const reads = new Set([
  'novel_embedding_profiles', 'novel_status', 'novel_review_framework', 'novel_trace_list',
  'novel_context_preview', 'novel_outline_read', 'novel_reading_order', 'novel_reading_packet',
  'novel_chapter_work', 'novel_scene_structure', 'novel_chapter_scenes', 'novel_scene_migration_preview',
  'novel_assets_list', 'novel_search', 'novel_doc_read', 'novel_asset_read', 'novel_revisions_list',
  'novel_revision_get', 'novel_tasks_list', 'novel_continuity', 'novel_diagnostics',
  'novel_research_status', 'novel_research_report', 'novel_model_profiles',
  'novel_manuscript_acceptance', 'novel_export_preflight',
])
const generates = new Set([
  'novel_write_chapter', 'novel_review_chapter', 'novel_multi_write', 'novel_task_create',
  'novel_task_retry', 'novel_task_confirm', 'novel_revision_create_selection',
  'novel_revision_create_from_review', 'novel_revision_regenerate', 'novel_settle_backfill',
  'novel_model_test', 'novel_model_embedding_test',
])
const readActions: Record<string, readonly string[]> = {
  novel_model_benchmark: ['list', 'get', 'options'],
  novel_chapter_run_action: ['list', 'get'],
  novel_rolling_plan_action: ['list', 'get'],
  novel_narrative_forecast_action: ['list', 'get'],
  novel_manuscript_edit_action: ['versions', 'version', 'compare', 'annotations'],
  novel_source_action: ['status_v2', 'profile_v2'],
  novel_reference_library_action: ['list', 'status', 'profile'],
  novel_runtime_skill_action: ['list', 'diagnose', 'resolve'],
  novel_rule_action: ['status'],
}

/** Unknown and preview operations fail closed: previews can persist confirmation records. */
export function novelEffect(name: string, args: unknown): NovelEffect {
  if (reads.has(name)) return 'read'
  const values = args && typeof args === 'object' ? args as Record<string, unknown> : {}
  if (readActions[name]?.includes(String(values.action))) return 'read'
  if (name === 'novel_model_benchmark' && values.action === 'run') return 'generate'
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
