/** Browser half: three native writing workbenches plus dsh-native chrome/tool views. */
import type { Context } from '@deepseek-ai/cordis'
import type {} from '@deepseek-ai/dsh-client-locale/client'
import type {} from '@deepseek-ai/dsh-client-ui-conversation/client'
import type {} from '@deepseek-ai/dsh-client-ui-tool/client'
import { fetchStudioApi, postStudioApi, putStudioApi, type StudioApiInjected } from './api.ts'
import { CreationView } from './CreationView.tsx'
import { LibraryView } from './LibraryView.tsx'
import { OperationsView } from './OperationsView.tsx'
import { ProjectSwitcherChip, HeaderProjectStatus, HeaderUtilities } from './HeaderChrome.tsx'
import { createDomainToolCard, type ToolFamily } from './DomainToolCard.tsx'
import { en, NS, zh } from './locales.ts'
import { NovelReviewCard } from './ReviewCard.tsx'
import { novelMutationDefinition, TurnMutationSummaryView } from './TurnMutationSummary.tsx'

export const inject = ['slots', 'locale', 'conversationEvents']

const studioApi: StudioApiInjected = { fetchStudioApi, postStudioApi, putStudioApi }

const FAMILY_TOOLS: Readonly<Record<ToolFamily, readonly string[]>> = {
  status: ['novel_status', 'novel_focus', 'novel_writing_targets', 'novel_continuity', 'novel_diagnostics'],
  context: ['novel_context_preview'],
  manuscript: ['novel_doc_read', 'novel_doc_write', 'novel_doc_create', 'novel_write_chapter', 'novel_multi_write', 'novel_chapter_delete', 'novel_manuscript_edit_action', 'novel_import', 'novel_import_preview'],
  revision: ['novel_revisions_list', 'novel_revision_get', 'novel_revision_create_selection', 'novel_revision_create_from_review', 'novel_revision_apply', 'novel_revision_reject', 'novel_revision_regenerate'],
  task: ['novel_tasks_list', 'novel_task_get', 'novel_task_create', 'novel_task_cancel', 'novel_task_retry', 'novel_task_confirm', 'novel_chapter_run_action', 'novel_model_benchmark'],
  search: ['novel_search'],
  asset: ['novel_assets_list', 'novel_asset_read', 'novel_asset_create', 'novel_asset_update', 'novel_assets_package_preview', 'novel_assets_package_import', 'novel_reference_library_action', 'novel_source_action'],
  outline: ['novel_outline_read', 'novel_outline_edit', 'novel_foreshadowing', 'novel_rolling_plan_action', 'novel_narrative_forecast_action'],
}

const FAMILY_CARDS: Readonly<Record<ToolFamily, ReturnType<typeof createDomainToolCard>>> = {
  status: createDomainToolCard('status'),
  context: createDomainToolCard('context'),
  manuscript: createDomainToolCard('manuscript'),
  revision: createDomainToolCard('revision'),
  task: createDomainToolCard('task'),
  search: createDomainToolCard('search'),
  asset: createDomainToolCard('asset'),
  outline: createDomainToolCard('outline'),
}

export function apply(ctx: Context): void {
  ctx.effect(() => ctx.locale.register(NS, { zh, en }), 'studio-panel: dictionaries')
  const t = ctx.locale.bind(NS)
  ctx.effect(() => ctx.conversationEvents.register(novelMutationDefinition), 'studio-panel: novel mutation turn data')

  ctx.slots.inject('conversation.view', function* () {
    yield ctx.slots.register({
      name: 'conversation.view', id: 'creation', order: 22, locale: NS,
      label: () => t('view.creation'), inject: (): StudioApiInjected => studioApi,
    }, CreationView)
    yield ctx.slots.register({
      name: 'conversation.view', id: 'library', order: 23, locale: NS,
      label: () => t('view.library'), inject: (): StudioApiInjected => studioApi,
    }, LibraryView)
    yield ctx.slots.register({
      name: 'conversation.view', id: 'tasks', order: 24, locale: NS,
      label: () => t('view.operations'), inject: (): StudioApiInjected => studioApi,
    }, OperationsView)
  })

  ctx.slots.inject('conversation.session.header.actions', () => ctx.slots.register({
    name: 'conversation.session.header.actions', id: 'novel-project-status', order: -20, locale: NS,
  }, HeaderProjectStatus))
  ctx.slots.inject('conversation.session.header.utilities', () => ctx.slots.register({
    name: 'conversation.session.header.utilities', id: 'novel-utilities', order: 20, locale: NS,
    inject: () => ({ postStudioApi }),
  }, HeaderUtilities))
  ctx.slots.inject('conversation.input.left', () => ctx.slots.register({
    name: 'conversation.input.left', id: 'novel-project-switcher', order: 20, locale: NS,
    inject: () => ({ fetchStudioApi, postStudioApi }),
  }, ProjectSwitcherChip))
  ctx.slots.inject('conversation.chat.turnTail', () => ctx.slots.register({
    name: 'conversation.chat.turnTail', locale: NS,
    select: owner => owner.turn.data.get('novelMutations') ?? null,
  }, TurnMutationSummaryView))

  ctx.slots.inject('tool.call.toolview', function* () {
    yield ctx.slots.register({ name: 'tool.call.toolview', key: 'novel_review_chapter', locale: NS }, NovelReviewCard)
    for (const [family, tools] of Object.entries(FAMILY_TOOLS) as [ToolFamily, readonly string[]][]) {
      for (const tool of tools) {
        yield ctx.slots.register({ name: 'tool.call.toolview', key: tool, locale: NS }, FAMILY_CARDS[family])
      }
    }
  })
}
