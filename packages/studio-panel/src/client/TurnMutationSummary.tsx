import { useState } from 'react'
import { FilePenLine } from 'lucide-react'
import type { ConversationLocationData, ConversationMatch, ConversationNodeContext, ConversationNodeDefinition } from '@deepseek-ai/dsh-client-runtime/client'
import type { PropsLocale, PropsRuntime } from '@deepseek-ai/dsh-client-ui-slots'
import type { StudioApiInjected } from './api.ts'
import { workbenchStore } from './WorkbenchStore.ts'
import css from './Workbench.module.css'

export interface NovelMutationItem {
  callId: string
  tool: string
  label: string
  path: string
  status: 'succeeded' | 'partial' | 'failed' | 'refresh_failed' | 'proposed' | 'rejected'
  errorCode: string
  historyVersionId: string
  revision: string
  sourceRevision: string
  resultRevision: string
  changes: readonly NovelEntityChange[]
  previewToken: string
  undoPreviewToken: string
  traceId?: string
  tracePath?: string
  modelCallCount?: number
  traceRetentionDays?: number
}

export interface NovelMutationValue {
  kind: 'missing' | 'text' | 'boolean' | 'number' | 'null' | 'list' | 'object'
  value: unknown
  preview: string
  truncated: boolean
  units: number
  sha256: string
}

export interface NovelEntityChange {
  changeId: string
  entityKind: string
  entityId: string
  path: string
  field: string
  before: NovelMutationValue
  after: NovelMutationValue
  sourceRevision: string
  resultRevision: string
  executionStatus: string
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
    'dsh-novel-mutations': NovelMutationSummary
  }
}

const MUTATION_LABELS: Readonly<Record<string, string>> = {
  novel_write_chapter: '写入章节',
  novel_doc_write: '更新文档',
  novel_document_change_plan: '文档变更计划',
  novel_structured_change_plan: '结构化变更计划',
  novel_doc_create: '创建文档',
  novel_chapter_delete: '删除章节',
  novel_chapter_delete_batch: '批量删除章节',
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

function nestedRecord(value: unknown, key: string): Record<string, unknown> {
  return record(record(value)[key])
}

function parseToolResult(message: unknown): Record<string, unknown> {
  const blocks = record(message)['content']
  if (!Array.isArray(blocks)) return {}
  for (const outer of blocks) {
    const result = record(outer)
    const contents = result['type'] === 'tool-result' ? result['content'] : [result]
    if (!Array.isArray(contents)) continue
    for (const raw of contents) {
      const block = record(raw)
      if (block['type'] !== 'text' || typeof block['text'] !== 'string') continue
      try {
        const parsed = record(JSON.parse(block['text']))
        return record(parsed['data'] ?? parsed)
      } catch {
        continue
      }
    }
  }
  return {}
}

function resultIsError(message: unknown): boolean {
  const blocks = record(message)['content']
  return Array.isArray(blocks) && blocks.some(block => record(block)['isError'] === true)
}

function resultTarget(payload: Record<string, unknown>, fallback: string): string {
  const proposalDocument = nestedRecord(nestedRecord(payload, 'proposal'), 'document')
  const document = nestedRecord(payload, 'document')
  for (const value of [proposalDocument['path'], document['path'], payload['path'], payload['chapter_id']]) {
    if (typeof value === 'string' && value !== '') return value
  }
  return fallback
}

function historyVersionId(payload: Record<string, unknown>): string {
  const proposal = nestedRecord(payload, 'proposal')
  const authorVersion = nestedRecord(payload, 'author_version')
  for (const value of [proposal['history_version_id'], payload['history_version_id'], authorVersion['version_id']]) {
    if (typeof value === 'string' && value !== '') return value
  }
  return ''
}

function resultRevision(payload: Record<string, unknown>): string {
  const proposal = nestedRecord(payload, 'proposal')
  const document = nestedRecord(payload, 'document')
  for (const value of [proposal['applied_revision'], document['revision'], payload['revision']]) {
    if (typeof value === 'string' && value !== '') return value
  }
  return ''
}

function text(value: unknown): string {
  return typeof value === 'string' ? value : ''
}

function numberValue(value: unknown): number {
  return typeof value === 'number' && Number.isFinite(value) ? value : 0
}

function mutationValue(value: unknown): NovelMutationValue {
  const source = record(value)
  const kind = text(source['kind'])
  return {
    kind: ['missing', 'text', 'boolean', 'number', 'null', 'list', 'object'].includes(kind)
      ? kind as NovelMutationValue['kind']
      : 'text',
    value: source['value'],
    preview: text(source['preview']),
    truncated: source['truncated'] === true,
    units: numberValue(source['units']),
    sha256: text(source['sha256']),
  }
}

function entityChanges(payload: Record<string, unknown>): NovelEntityChange[] {
  const summary = record(payload['mutation_summary'])
  if (summary['schema_version'] !== 'openwrite.mutation-summary.v1') return []
  const items = summary['items']
  if (!Array.isArray(items)) return []
  return items.map(raw => {
    const item = record(raw)
    return {
      changeId: text(item['change_id']),
      entityKind: text(item['entity_kind']),
      entityId: text(item['entity_id']),
      path: text(item['path']),
      field: text(item['field']),
      before: mutationValue(item['before']),
      after: mutationValue(item['after']),
      sourceRevision: text(item['source_revision']),
      resultRevision: text(item['result_revision']),
      executionStatus: text(item['execution_status']),
    }
  }).filter(item => item.changeId !== '' && item.field !== '')
}

function traceReference(payload: Record<string, unknown>) {
  const trace = record(payload['operation_trace'])
  const retention = record(trace['retention'])
  return {
    traceId: text(trace['trace_id']),
    tracePath: text(trace['path']),
    modelCallCount: numberValue(trace['model_call_count']),
    traceRetentionDays: numberValue(retention['max_age_days']),
  }
}

function changePath(changes: readonly NovelEntityChange[], fallback: string): string {
  return changes.find(item => item.path !== '')?.path ?? fallback
}

function renderedValue(value: NovelMutationValue, t: PropsLocale<'studio-panel'>['t']): string {
  if (value.kind === 'missing') return t('turn.missing')
  if (value.truncated) return `${value.preview}\n… ${t('turn.truncated')} · ${value.units}`
  if (typeof value.value === 'string') return value.value
  if (value.value === undefined) return value.preview
  return JSON.stringify(value.value, null, 2)
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
        calls: { ...context.state.calls, [event.data.callId]: {
          callId: event.data.callId,
          tool: event.data.name,
          label,
          path: targetOf(args),
          status: 'succeeded',
          errorCode: '',
          historyVersionId: '',
          revision: '',
          sourceRevision: '',
          resultRevision: '',
          changes: [],
          previewToken: '',
          undoPreviewToken: '',
          traceId: '',
          tracePath: '',
          modelCallCount: 0,
          traceRetentionDays: 0,
        } },
      }
    }
    if (event.type === 'tool/result') {
      const callId = event.data.message.source.callId
      const item = context.state.calls[callId]
      if (item === undefined || context.state.items.some(entry => entry.callId === callId)) return context.state
      const payload = parseToolResult(event.data.message)
      const explicitFailure = event.data.error !== undefined || resultIsError(event.data.message)
      const partial = Array.isArray(payload['failures']) && payload['failures'].length > 0
      const writeCommitted = payload['write_committed'] === true || payload['refresh_failed'] === true
      const mutationState = text(record(payload['mutation_summary'])['execution_status'])
      const status = explicitFailure
        ? (writeCommitted ? 'refresh_failed' : 'failed')
        : payload['status'] === 'rejected' ? 'rejected'
          : mutationState === 'proposed' ? 'proposed'
            : (partial ? 'partial' : 'succeeded')
      const errorCode = String(event.data.error?.code ?? payload['code'] ?? '')
      const changes = entityChanges(payload)
      const trace = traceReference(payload)
      return { ...context.state, items: [...context.state.items, {
        ...item,
        path: changePath(changes, resultTarget(payload, item.path)),
        status,
        errorCode,
        historyVersionId: historyVersionId(payload),
        revision: resultRevision(payload),
        sourceRevision: text(record(payload['mutation_summary'])['source_revision']),
        resultRevision: text(record(payload['mutation_summary'])['result_revision']),
        changes,
        previewToken: text(payload['preview_token']),
        undoPreviewToken: text(payload['undo_preview_token']),
        ...trace,
      }] }
    }
    return context.state
  },
  buildLocationData(context, scope): ConversationLocationData | null {
    if (scope !== 'turn' || context.state === undefined || context.state.items.length === 0) return null
    return { kind: 'turn', turn: context.state.turn, key: 'dsh-novel-mutations', value: { items: context.state.items } }
  },
}

type TurnSummaryProps = PropsRuntime<'conversation.chat.turnTail'> & PropsLocale<'studio-panel'> & Pick<StudioApiInjected, 'postStudioApi'> & { matched: NovelMutationSummary }

interface PlanActionState {
  status: NovelMutationItem['status']
  previewToken: string
  undoPreviewToken: string
  changes: readonly NovelEntityChange[]
  sourceRevision: string
  resultRevision: string
  message: string
  busy: boolean
}

export function TurnMutationSummaryView({ matched, openFile, postStudioApi, t }: TurnSummaryProps) {
  const [actions, setActions] = useState<Record<string, PlanActionState>>({})
  const runPlanAction = async (item: NovelMutationItem, action: 'apply' | 'reject' | 'retry' | 'undo') => {
    const current = actions[item.callId]
    const previewToken = action === 'undo'
      ? (current?.undoPreviewToken || item.undoPreviewToken)
      : (current?.previewToken || item.previewToken)
    if (previewToken === '') return
    setActions(value => ({ ...value, [item.callId]: {
      status: current?.status ?? item.status,
      previewToken: current?.previewToken ?? item.previewToken,
      undoPreviewToken: current?.undoPreviewToken ?? item.undoPreviewToken,
      changes: current?.changes ?? item.changes ?? [],
      sourceRevision: current?.sourceRevision ?? item.sourceRevision ?? '',
      resultRevision: current?.resultRevision ?? item.resultRevision ?? '',
      message: '', busy: true,
    } }))
    try {
      const planPath = item.tool === 'novel_structured_change_plan'
        ? '/structured/change-plan'
        : '/document/change-plan'
      const raw = record(await postStudioApi(planPath, { action, preview_token: previewToken }))
      const payload = record(raw['data'] ?? raw)
      const summary = record(payload['mutation_summary'])
      const changes = entityChanges(payload)
      if (item.tool === 'novel_structured_change_plan' && (action === 'apply' || action === 'undo')) {
        const kind = text(payload['change_kind'])
        const resources = kind === 'outline' ? ['outline', 'graph'] as const
          : kind === 'asset' ? ['assets', 'graph'] as const
            : kind === 'foreshadowing' ? ['graph'] as const
              : [] as const
        resources.forEach(resource => workbenchStore.invalidate(resource))
        workbenchStore.invalidate('workspace')
      }
      const nextStatus: NovelMutationItem['status'] = payload['status'] === 'rejected'
        ? 'rejected'
        : summary['execution_status'] === 'proposed' ? 'proposed' : 'succeeded'
      setActions(value => ({ ...value, [item.callId]: {
        status: nextStatus,
        previewToken: text(payload['preview_token']),
        undoPreviewToken: action === 'undo' ? '' : text(payload['undo_preview_token']),
        changes: changes.length > 0 ? changes : value[item.callId]?.changes ?? item.changes ?? [],
        sourceRevision: text(summary['source_revision']) || value[item.callId]?.sourceRevision || item.sourceRevision || '',
        resultRevision: text(summary['result_revision']) || value[item.callId]?.resultRevision || item.resultRevision || '',
        message: action === 'apply' ? t('turn.applied')
          : action === 'reject' ? t('turn.rejected')
            : action === 'retry' ? t('turn.retried') : t('turn.undone'),
        busy: false,
      } }))
    } catch (cause: unknown) {
      setActions(value => ({ ...value, [item.callId]: {
        ...(value[item.callId] ?? {
          status: item.status, previewToken: item.previewToken, undoPreviewToken: item.undoPreviewToken,
          changes: item.changes ?? [], sourceRevision: item.sourceRevision ?? '', resultRevision: item.resultRevision ?? '',
        }),
        message: cause instanceof Error ? cause.message : String(cause), busy: false,
      } }))
    }
  }
  const statuses = matched.items.map(item => actions[item.callId]?.status ?? item.status)
  const failures = statuses.filter(status => status === 'failed').length
  const partial = statuses.some(status => status === 'partial' || status === 'refresh_failed')
  const allProposed = statuses.every(status => status === 'proposed')
  const allRejected = statuses.every(status => status === 'rejected')
  return <div className={css.turnSummary}>
    <FilePenLine size={14} />
    <span>{failures === matched.items.length
      ? t('turn.failed')
      : allProposed ? t('turn.proposed')
        : allRejected ? t('turn.rejected')
          : partial || failures > 0 ? t('turn.partial') : t('turn.changed')}</span>
    {matched.items.map(item => {
      const state = actions[item.callId]
      const itemStatus = state?.status ?? item.status
      const changes = state?.changes ?? item.changes ?? []
      const sourceRevision = state?.sourceRevision ?? item.sourceRevision ?? ''
      const resultRevision = state?.resultRevision ?? item.resultRevision ?? ''
      const previewToken = state?.previewToken ?? item.previewToken ?? ''
      const undoPreviewToken = state?.undoPreviewToken ?? item.undoPreviewToken ?? ''
      return <span key={item.callId} className={css.turnMutationItem} data-status={itemStatus}>
      {item.path !== ''
        ? <button type="button" onClick={() => openFile(item.path)}>{item.label} {item.path}</button>
        : <span>{item.label}</span>}
      {itemStatus === 'failed' && <small>{item.errorCode || t('turn.failed')}</small>}
      {itemStatus === 'partial' && <small>{t('turn.partial')}</small>}
      {itemStatus === 'refresh_failed' && <small>{t('turn.refreshFailed')}</small>}
      {itemStatus === 'proposed' && <small>{t('turn.proposed')}</small>}
      {itemStatus === 'rejected' && <small>{t('turn.rejected')}</small>}
      {item.historyVersionId !== '' && <small>{t('turn.history')} {item.historyVersionId}</small>}
      {(item.traceId ?? '') !== '' && ((item.tracePath ?? '') !== ''
        ? <button type="button" className={css.turnTraceLink} onClick={() => openFile(item.tracePath ?? '')}>
          {t('turn.trace')} {item.traceId} · {item.modelCallCount ?? 0} {t('turn.modelCalls')}
          {(item.traceRetentionDays ?? 0) > 0 ? ` · ${item.traceRetentionDays} ${t('turn.days')}` : ''}
        </button>
        : <small>{t('turn.trace')} {item.traceId}</small>)}
      {changes.length > 0 && <details className={css.turnEntityChanges}>
        <summary>{changes.length} {t('turn.entityChanges')}</summary>
        {(sourceRevision !== '' || resultRevision !== '') && <div className={css.turnRevisionPair}>
          <span>{t('turn.sourceRevision')} {sourceRevision || '—'}</span>
          <span>{t('turn.resultRevision')} {resultRevision || '—'}</span>
        </div>}
        {changes.map(change => <article key={change.changeId} className={css.turnEntityChange}>
          <header>
            <strong>{change.entityKind} · {change.entityId}</strong>
            <span>{change.field}</span>
            <small>{change.executionStatus || t('turn.committed')}</small>
          </header>
          <div className={css.turnValuePair}>
            <div><span>{t('turn.before')}</span><pre>{renderedValue(change.before, t)}</pre></div>
            <div><span>{t('turn.after')}</span><pre>{renderedValue(change.after, t)}</pre></div>
          </div>
        </article>)}
        {(itemStatus === 'proposed' && previewToken !== '') && <div className={css.turnPlanActions}>
          <button type="button" disabled={state?.busy} onClick={() => void runPlanAction(item, 'apply')}>{t('turn.accept')}</button>
          <button type="button" disabled={state?.busy} onClick={() => void runPlanAction(item, 'reject')}>{t('turn.reject')}</button>
          <button type="button" disabled={state?.busy} onClick={() => void runPlanAction(item, 'retry')}>{t('turn.retry')}</button>
        </div>}
        {(itemStatus === 'succeeded' && undoPreviewToken !== '') && <div className={css.turnPlanActions}>
          <button type="button" disabled={state?.busy} onClick={() => void runPlanAction(item, 'undo')}>{t('turn.undo')}</button>
        </div>}
        {state?.message && <p className={css.turnPlanNotice}>{state.message}</p>}
      </details>}
    </span>})}
  </div>
}
