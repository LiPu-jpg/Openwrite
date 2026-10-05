import type {} from '@deepseek-ai/dsh-client-ui-sidebar/client'
import type {} from '@deepseek-ai/dsh-api-remotes/client'
import { isWritingSession, watchWritingScope } from './writing-scope.ts'
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
import { novelMutationDefinition, TurnMutationSummaryView, TurnMutationSummaryListView } from './TurnMutationSummary.tsx'
import { sessionOpener, type StudioPanelInjected } from './workspace-context.ts'

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
  try {
    ctx.effect(() => install(ctx), 'studio-panel: client activation')
  } catch (error) {
    console.error('[OpenWrite/Studio] Workbench disabled: client activation failed', error)
  }
}

function* install(ctx: Context): Generator<() => void> {
  yield ctx.effect(() => ctx.locale.register(NS, { zh, en }), 'studio-panel: dictionaries')
  const t = ctx.locale.bind(NS)
  // These registries are optional chrome capabilities. Keep the workbench
  // available when a host no longer exposes the turn-summary extension point.
  if (typeof ctx.uiConversation.events?.register === 'function') {
    yield ctx.effect(() => ctx.uiConversation.events.register(novelMutationDefinition), 'studio-panel: novel mutation turn data')
  } else {
    console.warn('[OpenWrite/Studio] Turn summaries unavailable: uiConversation.events.register is missing')
  }

  const injectSlot = (name: Parameters<typeof ctx.slots.inject>[0], mount: () => (() => void) | Generator<() => void>) =>
    ctx.slots.inject(name, () => {
      try {
        // Cordis unwinds yielded registrations if setup fails, including when
        // the slot is declared after apply() has already returned.
        return ctx.effect(mount, `studio-panel: ${name}`)
      } catch (error) {
        console.error(`[OpenWrite/Studio] UI contribution disabled: ${name}`, error)
        return () => {}
      }
    })

  const pendingActivation = new Set<Parameters<StudioPanelInjected['workspaces']['openSession']>[0]>()
  const activatePending = () => {
    const state = ctx.sessions.list.getSnapshot()
    if (!isWritingSession(state) || typeof ctx.uiConversation.binding !== 'function' ||
      typeof ctx.uiConversation.views?.register !== 'function') return
    for (const id of pendingActivation) {
      const row = state.byId[id] as { retainedBy?: { mainView?: number } } | undefined
      if (state.current !== id && (row?.retainedBy?.mainView ?? 0) === 0) continue
      const binding = ctx.uiConversation.binding(id)
      if (!binding) continue
      binding.activate('openwrite.creation')
      pendingActivation.delete(id)
    }
  }
  yield ctx.effect(() => ctx.sessions.list.subscribe(activatePending), 'openwrite: activate opened workbench')

  const workspaceServices: StudioPanelInjected['workspaces'] = {
    list: ctx.workspaces.list,
    create: input => ctx.workspaces.create(input),
    rename: (id, title) => ctx.workspaces.rename(id, title),
    delete: id => ctx.workspaces.delete(id),
    insertBefore: (id, before) => ctx.workspaces.insertBefore(id, before),
    archiveSession: id => ctx.workspaces.archiveSession(id),
    insertSessionBefore: (id, session, before) => ctx.workspaces.insertSessionBefore(id, session, before),
    pickDirectory: () => ctx.uiWorkspace.pickDirectory(),
    connectWorkspace: async id => {
      const sessionId = await ctx.uiWorkspace.connectWorkspace(id)
      const result = await ctx.remote.agentPresets.select(sessionId, __OPENWRITE_PRESET_ID__)
      if (!result.ok) throw new Error(result.error.message)
      return sessionId
    },
    // dsh 0.2 moved "show this session" out of the Session Controller
    // (`ISessions` has no `open`); the opener probes both generations.
    openSession: target => {
      pendingActivation.add(target)
      try {
        sessionOpener({ uiWorkspace: ctx.uiWorkspace, sessions: ctx.sessions }).openSession(target)
        activatePending()
      } catch (error) {
        pendingActivation.delete(target)
        throw error
      }
    },
  }

  // A workbench is visible activity even before the first chat turn. Its
  // snapshot is independent of generated messages and preserves an empty log.
  if (typeof ctx.uiConversation.views?.register === 'function') yield ctx.effect(() => ctx.uiConversation.views.register({
    target: 'openwrite.creation',
    create: () => ({ empty: true, replace: () => true, apply: () => true }),
    isActive: () => true,
  }), 'openwrite: empty-session workbench')

  // Studio API trio plus the dsh workspace/session services the new-work flow drives.
  const studioPanel: StudioPanelInjected = {
    fetchStudioApi, postStudioApi, putStudioApi,
    workspaces: workspaceServices, sessions: ctx.sessions,
  }

  yield injectSlot('sidebar.footer.action', () => ctx.slots.register({
    name: 'sidebar.footer.action', id: 'openwrite.launch', order: 10,
    inject: () => ({ openWorkspace: async (path?: string) => {
      const selected = path?.trim() || await ctx.uiWorkspace.pickDirectory()
      if (selected === null) return false
      const workspace = await ctx.workspaces.create({ path: selected })
      const sessionId = await ctx.sessions.create({ workspaceId: workspace.workspaceId })
      const result = await ctx.remote.agentPresets.select(sessionId, __OPENWRITE_PRESET_ID__)
      if (!result.ok) throw new Error(result.error.message)
      workspaceServices.openSession(sessionId)
      return true
    } }),
  }, LaunchOpenWrite))

  const writingSlots = (name: Parameters<typeof ctx.slots.inject>[0], mount: () => (() => void) | Generator<() => void>) => {
    return injectSlot(name, () => watchWritingScope(ctx.sessions.list, () => {
      try {
        return ctx.effect(mount, `studio-panel: writing ${name}`)
      } catch (error) {
        console.error(`[OpenWrite/Studio] Writing UI contribution disabled: ${name}`, error)
        return () => {}
      }
    }))
  }
  yield writingSlots('conversation.view' , function* () {
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

  yield writingSlots('conversation.session.header.actions', () => ctx.slots.register({
    name: 'conversation.session.header.actions', id: 'novel-project-status', order: -20, locale: NS,
  }, HeaderProjectStatus))
  yield writingSlots('conversation.session.header.utilities', () => ctx.slots.register({
    name: 'conversation.session.header.utilities', id: 'novel-utilities', order: 20, locale: NS,
    inject: () => ({ postStudioApi }),
  }, HeaderUtilities))
  yield writingSlots('conversation.input.left', () => ctx.slots.register({
    name: 'conversation.input.left', id: 'novel-workspace-context', order: 20, locale: NS,
    inject: (): Pick<StudioPanelInjected, 'postStudioApi' | 'workspaces' | 'sessions'> => ({
      postStudioApi, workspaces: workspaceServices, sessions: ctx.sessions,
    }),
  }, WorkspaceContextChip))
  if (typeof ctx.uiConversation.events?.register === 'function') yield injectSlot('conversation.chat.turnTail', () => {
    // 0.1 uses a chain selector; 0.2 changed this extension point to a list.
    if ((ctx.slots.spec('conversation.chat.turnTail')?.kind as string) === 'list') {
      // The build SDK is pinned to 0.1; narrow the verified 0.2 overload at
      // this boundary instead of pretending both SlotMap declarations merge.
      const registerList = ctx.slots.register.bind(ctx.slots) as unknown as (
        options: { name: 'conversation.chat.turnTail'; id: string; locale: typeof NS; inject: () => { postStudioApi: typeof postStudioApi } },
        component: typeof TurnMutationSummaryListView,
      ) => () => void
      return registerList({
        name: 'conversation.chat.turnTail', id: 'openwrite.mutation-summary', locale: NS,
        inject: () => ({ postStudioApi }),
      }, TurnMutationSummaryListView)
    }
    return ctx.slots.register({
      name: 'conversation.chat.turnTail', locale: NS,
      select: owner => owner.turn.data.get('dsh-novel-mutations') ?? null,
      inject: () => ({ postStudioApi }),
    }, TurnMutationSummaryView)
  })

  yield injectSlot('tool.call.toolview', function* () {
    yield ctx.slots.register({ name: 'tool.call.toolview', key: 'novel_review_chapter', locale: NS }, NovelReviewCard)
    for (const [family, tools] of Object.entries(FAMILY_TOOLS) as [ToolFamily, readonly string[]][]) {
      for (const tool of tools) {
        yield ctx.slots.register({ name: 'tool.call.toolview', key: tool, locale: NS }, FAMILY_CARDS[family])
      }
    }
  })
}
