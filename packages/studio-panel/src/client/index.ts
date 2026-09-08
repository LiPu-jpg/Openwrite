import type {} from '@deepseek-ai/dsh-client-ui-sidebar/client'
import type {} from '@deepseek-ai/dsh-api-remotes/client'
import { watchWritingScope } from './writing-scope.ts'
import { LaunchOpenWrite } from './LaunchOpenWrite.tsx'
import type {} from '@deepseek-ai/dsh-client-ui-renderer/client'
import type {} from '@deepseek-ai/dsh-client-ui-session/client'
import type {} from '@deepseek-ai/dsh-client-ui-chat/client'
import type {} from '@deepseek-ai/dsh-client-ui-workspace/client'
/** Browser half: three native writing workbenches plus dsh-native chrome/tool views. */
import type { Context } from '@deepseek-ai/cordis'
import type {} from '@deepseek-ai/dsh-client-locale/client'
import type {} from '@deepseek-ai/dsh-client-ui-conversation/client'
import type {} from '@deepseek-ai/dsh-client-ui-tool/client'
import { fetchStudioApi, postStudioApi, putStudioApi } from './api.ts'
import { CreationView } from './CreationView.tsx'
import { LibraryView } from './LibraryView.tsx'
import { OperationsView } from './OperationsView.tsx'
import { WorkspaceContextChip, HeaderProjectStatus, HeaderUtilities } from './HeaderChrome.tsx'
import { createDomainToolCard, type ToolFamily } from './DomainToolCard.tsx'
import { en, NS, zh } from './locales.ts'
import { NovelReviewCard } from './ReviewCard.tsx'
import { novelMutationDefinition, TurnMutationSummaryView } from './TurnMutationSummary.tsx'
import type { StudioPanelInjected } from './workspace-context.ts'

export const inject = ['slots', 'locale', 'uiConversation', 'workspaces', 'sessions', 'uiWorkspace', 'remote', 'remote.agentPresets']

const FAMILY_TOOLS: Readonly<Record<ToolFamily, readonly string[]>> = {
  status: ['novel_status', 'novel_focus', 'novel_writing_targets', 'novel_continuity', 'novel_diagnostics'],
  context: ['novel_context_preview'],
  manuscript: ['novel_doc_read', 'novel_doc_write', 'novel_document_change_plan', 'novel_structured_change_plan', 'novel_doc_create', 'novel_write_chapter', 'novel_multi_write', 'novel_chapter_delete', 'novel_chapter_delete_batch', 'novel_manuscript_edit_action', 'novel_manuscript_acceptance', 'novel_manuscript_acceptance_reconcile', 'novel_export_preflight', 'novel_export', 'novel_import', 'novel_import_preview', 'novel_manuscript_import_action', 'novel_project_archive_action', 'novel_project_archive_download'],
  revision: ['novel_revisions_list', 'novel_revision_get', 'novel_revision_create_selection', 'novel_revision_create_from_review', 'novel_revision_apply', 'novel_revision_reject', 'novel_revision_regenerate'],
  task: ['novel_tasks_list', 'novel_task_get', 'novel_task_create', 'novel_task_cancel', 'novel_task_retry', 'novel_task_confirm', 'novel_chapter_run_action', 'novel_model_benchmark', 'novel_settle_backfill'],
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
  ctx.effect(() => ctx.uiConversation.events.register(novelMutationDefinition), 'studio-panel: novel mutation turn data')

  const workspaceServices: StudioPanelInjected['workspaces'] = {
    list: ctx.workspaces.list,
    create: input => ctx.workspaces.create(input),
    rename: (id, title) => ctx.workspaces.rename(id, title),
    delete: id => ctx.workspaces.delete(id),
    insertBefore: (id, before) => ctx.workspaces.insertBefore(id, before),
    archiveSession: id => ctx.workspaces.archiveSession(id),
    insertSessionBefore: (id, session, before) => ctx.workspaces.insertSessionBefore(id, session, before),
    pickDirectory: () => ctx.uiWorkspace.pickDirectory(),
    connectWorkspace: id => ctx.uiWorkspace.connectWorkspace(id),
  }

  // A workbench is visible activity even before the first chat turn. Its
  // snapshot is independent of generated messages and preserves an empty log.
  ctx.effect(() => ctx.uiConversation.views.register({
    target: 'openwrite.creation',
    create: () => ({ empty: true, replace: () => true, apply: () => true }),
    isActive: () => true,
  }), 'openwrite: empty-session workbench')

  // Studio API trio plus the dsh workspace/session services the new-work flow drives.
  const studioPanel: StudioPanelInjected = {
    fetchStudioApi, postStudioApi, putStudioApi,
    workspaces: workspaceServices, sessions: ctx.sessions,
  }

  ctx.slots.inject('sidebar.footer.action', () => ctx.slots.register({
    name: 'sidebar.footer.action', id: 'openwrite.launch', order: 10,
    inject: () => ({ openWorkspace: async (path?: string) => {
      const selected = path?.trim() || await ctx.uiWorkspace.pickDirectory()
      if (selected === null) return false
      const workspace = await ctx.workspaces.create({ path: selected })
      const sessionId = await ctx.sessions.create({ workspaceId: workspace.workspaceId })
      const result = await ctx.remote.agentPresets.select(sessionId, 'openwrite-0-2-0')
      if (!result.ok) throw new Error(result.error.message)
      ctx.sessions.open(sessionId)
      // Activate a UI target to leave the blank Hero without manufacturing a user turn.
      ctx.uiConversation.binding(sessionId).activate('openwrite.creation')
      return true
    } }),
  }, LaunchOpenWrite))

  const writingSlots = (name: Parameters<typeof ctx.slots.inject>[0], mount: () => (() => void) | Generator<() => void>) => {
    ctx.slots.inject(name, () => watchWritingScope(ctx.sessions.list, () => {
      const result = mount()
      if (typeof result === 'function') return result
      const disposers = [...result]
      return () => { for (const dispose of disposers.reverse()) dispose() }
    }))
  }
  writingSlots('conversation.view' , function* () {
    yield ctx.slots.register({
      name: 'conversation.view', id: 'openwrite.creation', order: 22, locale: NS,
      label: () => t('view.creation'), inject: (): StudioPanelInjected => studioPanel,
    }, CreationView)
    yield ctx.slots.register({
      name: 'conversation.view', id: 'openwrite.library', order: 23, locale: NS,
      label: () => t('view.library'), inject: (): StudioPanelInjected => studioPanel,
    }, LibraryView)
    yield ctx.slots.register({
      name: 'conversation.view', id: 'openwrite.tasks', order: 24, locale: NS,
      label: () => t('view.operations'), inject: (): StudioPanelInjected => studioPanel,
    }, OperationsView)
  })

  writingSlots('conversation.session.header.actions', () => ctx.slots.register({
    name: 'conversation.session.header.actions', id: 'novel-project-status', order: -20, locale: NS,
  }, HeaderProjectStatus))
  writingSlots('conversation.session.header.utilities', () => ctx.slots.register({
    name: 'conversation.session.header.utilities', id: 'novel-utilities', order: 20, locale: NS,
    inject: () => ({ postStudioApi }),
  }, HeaderUtilities))
  writingSlots('conversation.input.left', () => ctx.slots.register({
    name: 'conversation.input.left', id: 'novel-workspace-context', order: 20, locale: NS,
    inject: (): Pick<StudioPanelInjected, 'postStudioApi' | 'workspaces' | 'sessions'> => ({
      postStudioApi, workspaces: workspaceServices, sessions: ctx.sessions,
    }),
  }, WorkspaceContextChip))
  ctx.slots.inject('conversation.chat.turnTail', () => ctx.slots.register({
    name: 'conversation.chat.turnTail', locale: NS,
    select: owner => owner.turn.data.get('dsh-novel-mutations') ?? null,
    inject: () => ({ postStudioApi }),
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
