/**
 * Tasks view (任务): the OpenWrite persistent task queue rendered natively —
 * type/status/phase badges, input summary, failure messages. Read-only on
 * purpose: cancel/retry/confirm mutations stay with the agent tools.
 *
 * Wire shape (verified against OpenWrite tools/studio_http.py do_GET +
 * tools/studio_application.py task_surface + tools/task_store.py
 * TaskStore.create): GET /api/tasks?limit=N answers WITH the success
 * envelope — { ok: true, data: { tasks: [...], counts: { <status>: n } },
 * error: null, request_id }. A task record carries { task_id, type, status,
 * phase, chapter_id, input_summary, error: { code, message, recoverable } |
 * null, attempt, created_at, started_at, completed_at, updated_at, ... }.
 * There is NO numeric progress field — `phase` (queued/reading/preparing/
 * model/validating/committing/complete) is the progress signal.
 */

import { Fragment, useCallback, useEffect, useState } from 'react'
import type { ConvViewProps } from '@deepseek-ai/dsh-client-ui-conversation/client'
import type { InjectFace, PropsLocale } from '@deepseek-ai/dsh-client-ui-slots'
import type { StudioApiInjected } from './api.ts'
import css from './views.module.css'

/** Server-side status vocabulary (task_store.py TASK_STATUSES), display order. */
const STATUSES = [
  'running',
  'awaiting_confirmation',
  'pending',
  'interrupted',
  'failed',
  'cancelled',
  'completed',
] as const

type TaskStatus = (typeof STATUSES)[number]

/** Server-side phase vocabulary (task_store.py TASK_PHASES). */
const PHASES = ['queued', 'reading', 'preparing', 'model', 'validating', 'committing', 'complete'] as const

type TaskPhase = (typeof PHASES)[number]

/** One task record (the fields this view reads; the payload carries more). */
/** Completed chapter_review result (subset the row/expand reads). */
interface ReviewResult {
  qualityScore: number | null
  coverage: number | null
  gateStatus: string
  deliveryStatus: string
  issues: number | null
  summary: string
  issueDetails: {
    reviewSeverity: 'critical' | 'warning' | 'info'
    revisionPriority: 'blocker' | 'high' | 'medium' | 'low'
    dimension: string
    summary: string
  }[]
}

/** Narrow one issue entry from a completed review result. */
function parseIssue(raw: unknown): ReviewResult['issueDetails'][number] | null {
  if (raw === null || typeof raw !== 'object') return null
  const item = raw as Record<string, unknown>
  const summary = typeof item['summary'] === 'string' ? item.summary : ''
  if (summary === '') return null
  const severity = String(item['review_severity'] ?? item['legacy_severity'] ?? item['severity'] ?? '').toLowerCase()
  const priority = String(item['revision_priority'] ?? '').toLowerCase()
  return {
    reviewSeverity: severity === 'critical' || severity === 'blocker'
      ? 'critical'
      : severity === 'info' || severity === 'low' ? 'info' : 'warning',
    revisionPriority: ['blocker', 'high', 'medium', 'low'].includes(priority)
      ? priority as ReviewResult['issueDetails'][number]['revisionPriority']
      : severity === 'critical' || severity === 'blocker'
        ? 'blocker'
        : severity === 'high' ? 'high' : severity === 'info' || severity === 'low' ? 'low' : 'medium',
    dimension: String(item['dimension'] ?? 'general'),
    summary,
  }
}

/** Narrow a completed chapter_review result (empty on garbage). */
function parseReviewResult(raw: unknown): ReviewResult | null {
  if (raw === null || typeof raw !== 'object' || Array.isArray(raw)) return null
  const r = raw as Record<string, unknown>
  const details = Array.isArray(r['issue_details'])
    ? r['issue_details'].map(parseIssue).filter((item): item is NonNullable<typeof item> => item !== null)
    : []
  const v2 = (r['review_v2'] !== null && typeof r['review_v2'] === 'object' && !Array.isArray(r['review_v2'])
    ? r['review_v2'] : {}) as Record<string, unknown>
  const qualityScore = typeof v2['quality_score'] === 'number'
    ? v2.quality_score
    : typeof r['score'] === 'number' ? r.score : null
  if (qualityScore === null && details.length === 0 && typeof r['passed'] !== 'boolean') return null
  return {
    qualityScore,
    coverage: typeof v2['coverage'] === 'number' ? v2.coverage : null,
    gateStatus: typeof v2['gate_status'] === 'string' ? v2.gate_status : '',
    deliveryStatus: typeof v2['delivery_status'] === 'string'
      ? v2.delivery_status
      : r['passed'] === true ? 'pass' : 'revise',
    issues: typeof r['issues'] === 'number' ? r.issues : null,
    summary: typeof r['summary'] === 'string' ? r.summary : '',
    issueDetails: details,
  }
}

interface TaskRecord {
  taskId: string
  type: string
  status: TaskStatus
  phase: TaskPhase
  chapterId: string
  inputSummary: string
  errorMessage: string
  /** Completed chapter_review payload (score / issues / issue_details). */
  result: ReviewResult | null
  /** Server hint that a failed task may be retried. */
  recoverable: boolean
  attempt: number
  createdAt: string
  updatedAt: string
}

interface TasksPayload {
  tasks: TaskRecord[]
  counts: Partial<Record<TaskStatus, number>>
}

type LoadState = 'loading' | 'error' | 'ready'

/** Narrow one wire record, tolerating missing/extra fields. */
function parseTask(raw: unknown): TaskRecord {
  const record = (raw !== null && typeof raw === 'object' ? raw : {}) as Record<string, unknown>
  const text = (value: unknown): string => (typeof value === 'string' ? value : '')
  const status = text(record['status'])
  const phase = text(record['phase'])
  const error = (record['error'] !== null && typeof record['error'] === 'object' ? record['error'] : {}) as Record<string, unknown>
  return {
    taskId: text(record['task_id']),
    type: text(record['type']),
    status: (STATUSES as readonly string[]).includes(status) ? status as TaskStatus : 'pending',
    phase: (PHASES as readonly string[]).includes(phase) ? phase as TaskPhase : 'queued',
    chapterId: text(record['chapter_id']),
    inputSummary: text(record['input_summary']),
    result: text(record['type']) === 'chapter_review' && status === 'completed'
      ? parseReviewResult(record['result'])
      : null,
    errorMessage: text(error['message']),
    recoverable: error['recoverable'] === true,
    attempt: typeof record['attempt'] === 'number' ? record['attempt'] : 1,
    createdAt: text(record['created_at']),
    updatedAt: text(record['updated_at']),
  }
}

/** Unwrap the success envelope and narrow the payload (empty on garbage). */
function parseTasks(data: unknown): TasksPayload {
  const envelope = (data !== null && typeof data === 'object' ? data : {}) as Record<string, unknown>
  const inner = (envelope['data'] !== null && typeof envelope['data'] === 'object' ? envelope['data'] : {}) as Record<string, unknown>
  const rawCounts = (inner['counts'] !== null && typeof inner['counts'] === 'object' ? inner['counts'] : {}) as Record<string, unknown>
  const counts: Partial<Record<TaskStatus, number>> = {}
  for (const status of STATUSES) {
    const value = rawCounts[status]
    if (typeof value === 'number') counts[status] = value
  }
  return {
    tasks: Array.isArray(inner['tasks']) ? inner['tasks'].map(parseTask) : [],
    counts,
  }
}

/** `2026-08-20T11:21:41` → `08-20 11:21` (defensive: unrecognized shapes pass through trimmed). */
function shortTime(iso: string): string {
  const match = /^\d{4}-(\d{2}-\d{2})[T ](\d{2}:\d{2})/.exec(iso)
  return match !== null ? `${match[1]} ${match[2]}` : iso.slice(0, 16)
}

/** Full tasks-view props: conversation-view runtime share & injected fetch & locale seat. */
export type TasksViewProps =
  ConvViewProps & InjectFace<StudioApiInjected> & PropsLocale<'studio-panel'>

export function TasksView({ fetchStudioApi, postStudioApi, t }: TasksViewProps) {
  const [state, setState] = useState<LoadState>('loading')
  const [payload, setPayload] = useState<TasksPayload | null>(null)
  const [error, setError] = useState('')
  const [filter, setFilter] = useState<TaskStatus | 'all'>('all')

  const load = useCallback((silent: boolean) => {
    if (!silent) setState('loading')
    let cancelled = false
    fetchStudioApi('/tasks?limit=100')
      .then((data) => {
        if (cancelled) return
        setPayload(parseTasks(data))
        setState('ready')
      })
      .catch((cause: unknown) => {
        if (cancelled) return
        setError(cause instanceof Error ? cause.message : String(cause))
        setState('error')
      })
    return () => { cancelled = true }
  }, [fetchStudioApi])

  /** One-shot task action (cancel/retry) through the pattern-allowlisted proxy. */
  const [acting, setActing] = useState<string | null>(null)
  const [expanded, setExpanded] = useState<ReadonlySet<string>>(new Set())
  const [actionNote, setActionNote] = useState<{ text: string; bad: boolean } | null>(null)

  const runAction = useCallback(async (task: TaskRecord, action: 'cancel' | 'retry') => {
    if (acting !== null) return
    setActing(`${task.taskId}:${action}`)
    setActionNote(null)
    try {
      await postStudioApi(`/tasks/${task.taskId}/${action}`, {})
      setActionNote({ text: action === 'cancel' ? t('tasks.cancel.done') : t('tasks.retry.done'), bad: false })
      load(true)
    } catch (cause: unknown) {
      setActionNote({
        text: `${action === 'cancel' ? t('tasks.cancel.failed') : t('tasks.retry.failed')}: ${cause instanceof Error ? cause.message : String(cause)}`,
        bad: true,
      })
    } finally {
      setActing(null)
    }
  }, [acting, postStudioApi, load, t])

  // The shared WorkbenchStore owns centralized revision polling. This
  // view remounts on its resource epoch and performs one focused fetch.
  useEffect(() => {
    const cancelInitial = load(false)
    return () => { cancelInitial?.() }
  }, [load])

  const typeLabel = (type: string): string => {
    switch (type) {
      case 'chapter_write': return t('tasks.type.chapter_write')
      case 'chapter_review': return t('tasks.type.chapter_review')
      case 'continuous_write': return t('tasks.type.continuous_write')
      case 'revision_selection':
      case 'revision_from_review': return t('tasks.type.revision')
      case 'source_operation': return t('tasks.type.source_operation')
      case 'reference_operation': return t('tasks.type.reference_operation')
      case 'manuscript_import': return t('tasks.type.manuscript_import')
      case 'research': return t('tasks.type.research')
      case 'model_benchmark': return t('tasks.type.model_benchmark')
      default: return type
    }
  }

  const reviewStatusLabel = (status: string): string => {
    switch (status) {
      case 'pass': return t('review.status.pass')
      case 'blocked': return t('review.status.blocked')
      case 'inconclusive': return t('review.status.inconclusive')
      case 'revise': return t('review.status.revise')
      case 'stale': return t('review.status.stale')
      default: return status || t('review.status.unknown')
    }
  }

  const tasks = payload?.tasks ?? []
  const visible = filter === 'all' ? tasks : tasks.filter(task => task.status === filter)
  // Filter chips: 全部 plus every status the server's counts report as nonzero.
  const chipStatuses = STATUSES.filter(status => (payload?.counts[status] ?? 0) > 0)

  return (
    <div className={css.root}>
      <div className={css.toolbar}>
        <span className={css.toolbarMeta}>
          <button
            type="button"
            className={css.chip}
            data-active={filter === 'all'}
            aria-pressed={filter === 'all'}
            onClick={() => { setFilter('all') }}
          >
            {t('tasks.filter.all')} {tasks.length}
          </button>
          {chipStatuses.map(status => (
            <button
              key={status}
              type="button"
              className={css.chip}
              data-active={filter === status}
              aria-pressed={filter === status}
              onClick={() => { setFilter(status) }}
            >
              {t(`tasks.status.${status}`)} {payload?.counts[status] ?? 0}
            </button>
          ))}
        </span>
        <button type="button" className={css.button} onClick={() => { load(false) }}>
          {t('refresh')}
        </button>
      </div>
        {actionNote !== null && (
          <div className={css.notice}>
            <span className={actionNote.bad ? css.errorText : undefined}>{actionNote.text}</span>
          </div>
        )}
      <div className={css.body}>
        {state === 'loading' && payload === null && <div className={css.notice}>{t('loading')}</div>}
        {state === 'error' && (
          <div className={css.notice}>
            <span className={css.errorText}>{error}</span>
            <button type="button" className={css.button} onClick={() => { load(false) }}>{t('retry')}</button>
          </div>
        )}
        {state === 'ready' && visible.length === 0 && (
          <div className={css.notice}>{t('tasks.empty')}</div>
        )}
        {visible.map(task => (
        <Fragment key={task.taskId}>
          <div className={css.taskRow}>
            <span className={css.kindBadge}>{typeLabel(task.type)}</span>
            <span className={css.taskStatus} data-status={task.status}>{t(`tasks.status.${task.status}`)}</span>
            {(task.status === 'running' || task.status === 'pending') && (
              <span className={css.taskPhase}>{t(`tasks.phase.${task.phase}`)}</span>
            )}
            {task.chapterId !== '' && <span className={css.taskChapter}>{task.chapterId}</span>}
            {task.attempt > 1 && (
              <span className={css.taskPhase}>{t('tasks.attempt')} {task.attempt}</span>
            )}
            <span className={css.taskSummary}>{task.inputSummary}</span>
            {task.result !== null && (
              <button
                type="button"
                className={css.scoreChip}
                data-band={task.result.gateStatus === 'blocked' ? 'bad' : task.result.qualityScore === null ? 'na' : task.result.qualityScore >= 70 ? 'good' : task.result.qualityScore >= 40 ? 'mid' : 'bad'}
                title={t('tasks.result.toggle')}
                onClick={() => {
                  setExpanded(previous => {
                    const next = new Set(previous)
                    if (next.has(task.taskId)) next.delete(task.taskId)
                    else next.add(task.taskId)
                    return next
                  })
                }}
              >
                {t('tasks.result.score')} {task.result.qualityScore ?? '—'}
                {task.result.coverage !== null ? ` · ${t('review.coverage')} ${Math.round(task.result.coverage * 100)}%` : ''}
                {' · '}{reviewStatusLabel(task.result.deliveryStatus)}
                {' · '}{t('tasks.result.issues')} {task.result.issues ?? task.result.issueDetails.length}
              </button>
            )}
            <span className={css.taskActions}>
              {(task.status === 'pending' || task.status === 'running' || task.status === 'awaiting_confirmation') && (
                <button
                  type="button"
                  className={css.actionButton}
                  disabled={acting !== null}
                  title={t('tasks.cancel.title')}
                  onClick={() => {
                    if (window.confirm(t('tasks.cancel.confirm'))) void runAction(task, 'cancel')
                  }}
                >
                  {acting === `${task.taskId}:cancel` ? '…' : t('tasks.cancel')}
                </button>
              )}
              {task.status === 'failed' && (
                <button
                  type="button"
                  className={css.actionButton}
                  disabled={acting !== null || !task.recoverable}
                  title={task.recoverable ? t('tasks.retry.title') : t('tasks.retry.notRecoverable')}
                  onClick={() => { void runAction(task, 'retry') }}
                >
                  {acting === `${task.taskId}:retry` ? '…' : t('tasks.retry')}
                </button>
              )}
            </span>
            <span className={css.taskTime}>{shortTime(task.createdAt)}</span>
            {task.status === 'failed' && task.errorMessage !== '' && (
              <div className={css.taskError}>{task.errorMessage}</div>
            )}
          </div>
          {expanded.has(task.taskId) && task.result !== null && (
            <div className={css.taskIssues}>
              <div className={css.taskReviewMeta}>
                <span>{t('review.delivery')} {reviewStatusLabel(task.result.deliveryStatus)}</span>
                {task.result.gateStatus !== '' && <span>{t('review.gate')} {reviewStatusLabel(task.result.gateStatus)}</span>}
                {task.result.coverage !== null && <span>{t('review.coverage')} {Math.round(task.result.coverage * 100)}%</span>}
              </div>
              {task.result.summary !== '' && <div className={css.taskIssuesSummary}>{task.result.summary}</div>}
              {task.result.issueDetails.slice(0, 10).map((issue, index) => (
                <div key={index} className={css.taskIssueRow}>
                  <span className={css.taskIssueSeverity} data-severity={issue.reviewSeverity}>{t(`review.severity.${issue.reviewSeverity}`)}</span>
                  <span className={css.taskIssuePriority} data-priority={issue.revisionPriority}>{t('review.priority')} · {t(`review.priority.${issue.revisionPriority}`)}</span>
                  <span className={css.taskIssueDim}>{issue.dimension}</span>
                  <span className={css.taskIssueText}>{issue.summary}</span>
                </div>
              ))}
            </div>
          )}
        </Fragment>
        ))}
      </div>
    </div>
  )
}
