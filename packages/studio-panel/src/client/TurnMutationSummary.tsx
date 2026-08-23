import { FilePenLine } from 'lucide-react'
import type { ConversationLocationData, ConversationMatch, ConversationNodeContext, ConversationNodeDefinition } from '@deepseek-ai/dsh-client-runtime/client'
import type { PropsLocale, PropsRuntime } from '@deepseek-ai/dsh-client-ui-slots'
import css from './Workbench.module.css'

export interface NovelMutationItem {
  tool: string
  label: string
  path: string
}

export interface NovelMutationSummary {
  items: readonly NovelMutationItem[]
}

interface MutationState {
  turn: number
  calls: Readonly<Record<string, NovelMutationItem>>
  items: readonly NovelMutationItem[]
}

declare module '@deepseek-ai/dsh-client-runtime/client' {
  interface ConversationTurnDataMap {
    novelMutations: NovelMutationSummary
  }
}

const MUTATION_LABELS: Readonly<Record<string, string>> = {
  novel_write_chapter: '写入章节',
  novel_doc_write: '更新文档',
  novel_doc_create: '创建文档',
  novel_chapter_delete: '删除章节',
  novel_outline_edit: '更新大纲',
  novel_asset_create: '创建资料',
  novel_asset_update: '更新资料',
  novel_assets_package_import: '导入资料',
  novel_revision_create_selection: '生成修订',
  novel_revision_create_from_review: '生成修订',
  novel_revision_apply: '应用修订',
  novel_revision_reject: '拒绝修订',
  novel_revision_regenerate: '重生成修订',
  novel_task_create: '创建任务',
  novel_task_cancel: '取消任务',
  novel_task_retry: '重试任务',
  novel_task_confirm: '确认任务',
  novel_multi_write: '启动连写',
  novel_import: '导入章节',
  novel_sync: '同步作品',
  novel_focus: '更新创作重点',
  novel_foreshadowing: '更新伏笔',
  novel_writing_targets: '更新写作目标',
  novel_manuscript_edit_action: '编辑正文',
}

function record(value: unknown): Record<string, unknown> {
  return value !== null && typeof value === 'object' ? value as Record<string, unknown> : {}
}

function parseArgs(raw: string): Record<string, unknown> {
  try { return record(JSON.parse(raw)) } catch { return {} }
}

function targetOf(args: Record<string, unknown>): string {
  for (const key of ['path', 'chapter_id', 'chapter', 'proposal_id', 'task_id', 'id']) {
    if (typeof args[key] === 'string' && args[key] !== '') return args[key]
  }
  return ''
}

/** State-only durable event definition feeding the native Turn-tail summary. */
export const novelMutationDefinition: ConversationNodeDefinition<MutationState> = {
  kind: 'dsh-novel-mutations',
  match(event) {
    if (event.type === 'turn/start') return { id: String(event.data.turn), role: 'start' }
    if (event.type === 'tool/call' || event.type === 'tool/result') {
      return { id: String(event.data.turn), role: 'update' }
    }
    return null
  },
  start(_context, match) {
    const event = match.event
    return { turn: event.type === 'turn/start' ? event.data.turn : 0, calls: {}, items: [] }
  },
  update(context: ConversationNodeContext<MutationState> & { readonly state: MutationState }, match: ConversationMatch) {
    const event = match.event
    if (event.type === 'tool/call') {
      const label = MUTATION_LABELS[event.data.name]
      if (label === undefined) return context.state
      const args = parseArgs(event.data.arguments)
      return {
        ...context.state,
        calls: { ...context.state.calls, [event.data.callId]: { tool: event.data.name, label, path: targetOf(args) } },
      }
    }
    if (event.type === 'tool/result' && event.data.error === undefined) {
      const callId = event.data.message.source.callId
      const item = context.state.calls[callId]
      if (item === undefined || context.state.items.some(entry => entry.tool === item.tool && entry.path === item.path)) return context.state
      return { ...context.state, items: [...context.state.items, item] }
    }
    return context.state
  },
  buildLocationData(context, scope): ConversationLocationData | null {
    if (scope !== 'turn' || context.state === undefined || context.state.items.length === 0) return null
    return { kind: 'turn', turn: context.state.turn, key: 'novelMutations', value: { items: context.state.items } }
  },
}

type TurnSummaryProps = PropsRuntime<'conversation.chat.turnTail'> & PropsLocale<'studio-panel'> & { matched: NovelMutationSummary }

export function TurnMutationSummaryView({ matched, openFile, t }: TurnSummaryProps) {
  return <div className={css.turnSummary}>
    <FilePenLine size={14} />
    <span>{t('turn.changed')}</span>
    {matched.items.map((item, index) => item.path !== ''
      ? <button key={`${item.tool}:${item.path}`} type="button" onClick={() => openFile(item.path)}>{item.label} {item.path}</button>
      : <span key={`${item.tool}:${String(index)}`}>{item.label}</span>)}
  </div>
}

