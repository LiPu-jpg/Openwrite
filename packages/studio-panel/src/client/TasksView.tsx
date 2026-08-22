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
 *
 * Polling: 5s interval while mounted; the tick is skipped while
 * document.hidden. Inactive conversation views unmount (the view ring renders
 * `only: <active id>`), so switching tabs stops polling via effect cleanup.
 */

import { useCallback, useEffect, useState } from 'react'
import type { ConvViewProps } from '@deepseek-ai/dsh-client-ui-conversation/client'
import type { InjectFace, PropsLocale } from '@deepseek-ai/dsh-client-ui-slots'
import type { StudioApiInjected } from './api.ts'
import css from './views.module.css'

/** Poll cadence while the tab is mounted and the page is visible. */
const POLL_INTERVAL_MS = 5_000

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
interface TaskRecord {
  taskId: string
  type: string
  status: TaskStatus
  phase: TaskPhase
  chapterId: string
  inputSummary: string
  errorMessage: string
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

  // Initial load + 5s polling; hidden-page ticks are skipped, and unmount
  // (tab switch unmounts the view) clears the interval.
  useEffect(() => {
    const cancelInitial = load(false)
    const timer = setInterval(() => {
      if (typeof document !== 'undefined' && document.hidden) return
      load(true)
    }, POLL_INTERVAL_MS)
    return () => {
      cancelInitial?.()
      clearInterval(timer)
    }
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
      default: return type
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
          <div key={task.taskId} className={css.taskRow}>
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
        ))}
      </div>
    </div>
  )
}
