import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { BarChart3, ChevronRight, FlaskConical, GitBranch, History, LoaderCircle, Play, RefreshCw } from 'lucide-react'
import type { ConvViewProps } from '@deepseek-ai/dsh-client-ui-conversation/client'
import type { InjectFace, PropsLocale } from '@deepseek-ai/dsh-client-ui-slots'
import type { StudioApiInjected } from './api.ts'
import { asFiniteNumber as optionalNumber, asInteger as number, asRecord as record, asText as text, parseModelProfiles, parseResultRef, parseRouteMap, parseTaskProgress, unwrapData as data, type JsonRecord as RecordValue, type ModelProfileDto, type TaskProgressDto } from './dto.ts'
import css from './BenchmarkView.module.css'
import { parseBenchmarkOptions, parseBenchmarkPipeline, positiveInteger, type BenchmarkOptions, type BenchmarkPipeline, type BenchmarkTaskType } from './benchmark-options.ts'

type ModelProfile = ModelProfileDto

interface BenchmarkRun {
  runId: string
  status: string
  chapterId: string
  taskType: BenchmarkTaskType
  outlineStart: number | null
  outlineCount: number | null
  createdAt: string
  contextHash: string
  candidateCount: number
  evaluationCount: number
  executionMode: string | null
  promptVersion: string | null
  rubricVersion: string | null
  comparison: BenchmarkComparison
  summary: RecordValue
}

interface BenchmarkComparison {
  key: string
  basisComplete: boolean
  contextHash: string | null
  promptVersion: string | null
  rubricVersion: string | null
  executionMode: string | null
  manifestSchemaVersion: string | null
  contextStrategy: string | null
  tokenEstimator: string | null
  packetRevision: string | null
  sourceRevision: string | null
}

type BenchmarkViewProps = ConvViewProps & InjectFace<StudioApiInjected> & PropsLocale<'studio-panel'> & {
  initialRunId?: string
  refreshEpoch?: number
}


function formatTokens(value: unknown): string {
  const amount = optionalNumber(value)
  return amount === null ? '—' : Math.round(amount).toLocaleString()
}

function formatUsd(value: unknown): string {
  const amount = optionalNumber(value)
  if (amount === null) return '—'
  if (amount === 0) return '$0'
  if (amount >= 1) return `$${amount.toFixed(2)}`
  if (amount >= 0.01) return `$${amount.toFixed(4)}`
  if (amount >= 0.000001) return `$${amount.toFixed(6)}`
  return `$${amount.toExponential(3)}`
}

function nullableText(value: unknown): string | null {
  const rendered = text(value).trim()
  return rendered === '' ? null : rendered
}

function parseComparison(value: unknown, fallbackKey: string): BenchmarkComparison {
  const item = record(value)
  return {
    key: text(item['key']) || `unclassified:${fallbackKey}`,
    basisComplete: item['basis_complete'] === true,
    contextHash: nullableText(item['context_hash']),
    promptVersion: nullableText(item['prompt_version']),
    rubricVersion: nullableText(item['rubric_version']),
    executionMode: nullableText(item['execution_mode']),
    manifestSchemaVersion: nullableText(item['manifest_schema_version']),
    contextStrategy: nullableText(item['context_strategy']),
    tokenEstimator: nullableText(item['token_estimator']),
    packetRevision: nullableText(item['packet_revision']),
    sourceRevision: nullableText(item['source_revision']),
  }
}

interface ReviewCompleteness {
  incomplete: boolean
  complete: number
  total: number
  reportedCoverage: number[]
  domains: string[]
}

function reviewCompleteness(run: RecordValue): ReviewCompleteness {
  const evaluations = Array.isArray(run['evaluations']) ? run['evaluations'].map(record) : []
  const summary = record(run['summary'])
  const requested = optionalNumber(summary['requested_evaluations'])
  const total = Math.max(evaluations.length, requested ?? 0)
  const domains = new Set<string>()
  const reportedCoverage: number[] = []
  let incomplete = evaluations.length < total
  let complete = 0
  for (const evaluation of evaluations) {
    const diagnostics = record(evaluation['review_diagnostics'])
    const missing = Array.isArray(diagnostics['inconclusive_domain_ids']) ? diagnostics['inconclusive_domain_ids'].map(text).filter(Boolean) : []
    for (const domain of missing) domains.add(domain)
    const coverage = optionalNumber(evaluation['coverage'])
    if (coverage !== null && coverage >= 0 && coverage <= 1) reportedCoverage.push(coverage)
    const status = text(evaluation['execution_status'])
    const partial = ['partial', 'failed', 'cancelled', 'interrupted'].includes(status) || missing.length > 0 || (coverage !== null && coverage >= 0 && coverage < 1)
    incomplete ||= partial
    if (!partial && status === 'completed') complete += 1
  }
  return { incomplete, complete, total, reportedCoverage, domains: [...domains] }
}

function experimentStatus(run: RecordValue): string {
  const status = text(run['status'])
  return status === 'completed' && reviewCompleteness(run).incomplete ? 'partial' : status
}

function parseRuns(value: unknown): BenchmarkRun[] {
  const root = data(value)
  return (Array.isArray(root['runs']) ? root['runs'] : []).map(raw => {
    const item = record(raw)
    const runId = text(item['run_id'])
    const comparison = parseComparison(item['comparison'], runId)
    return {
      runId, status: text(item['status']), chapterId: text(item['chapter_id']),
      taskType: item['task_type'] === 'outline' ? 'outline' : 'chapter',
      outlineStart: optionalNumber(item['outline_start_chapter']), outlineCount: optionalNumber(item['outline_chapter_count']),
      createdAt: text(item['created_at']), contextHash: text(item['context_hash']),
      candidateCount: number(item['candidate_count']), evaluationCount: number(item['evaluation_count']),
      executionMode: nullableText(item['execution_mode']),
      promptVersion: nullableText(item['prompt_version']), rubricVersion: nullableText(item['rubric_version']),
      comparison,
      summary: record(item['summary']),
    }
  })
}

export function BenchmarkView({ fetchStudioApi, postStudioApi, t, initialRunId = '', refreshEpoch = 0 }: BenchmarkViewProps) {
  const [profiles, setProfiles] = useState<ModelProfile[]>([])
  const [writers, setWriters] = useState<Set<string>>(new Set())
  const [reviewers, setReviewers] = useState<Set<string>>(new Set())
  const [options, setOptions] = useState<BenchmarkOptions | null>(null)
  const [taskType, setTaskType] = useState<BenchmarkTaskType>('chapter')
  const [chapterChoice, setChapterChoice] = useState('next')
  const [customChapter, setCustomChapter] = useState('')
  const [outlineStartMode, setOutlineStartMode] = useState<'continue' | 'custom'>('continue')
  const [outlineStart, setOutlineStart] = useState('1')
  const [outlineCount, setOutlineCount] = useState('3')
  const [repeats, setRepeats] = useState('1')
  const [targetWords, setTargetWords] = useState('3000')
  const [concurrency, setConcurrency] = useState('1')
  const [executionMode, setExecutionMode] = useState<'framework' | 'creative'>('framework')
  const [runs, setRuns] = useState<BenchmarkRun[]>([])
  const [selected, setSelected] = useState<RecordValue | null>(null)
  const [reviewOutcomes, setReviewOutcomes] = useState<Record<string, { status: string; incomplete: boolean }>>({})
  const [activeTask, setActiveTask] = useState('')
  const [taskStatus, setTaskStatus] = useState('')
  const [cancelling, setCancelling] = useState(false)
  const [taskPhase, setTaskPhase] = useState('')
  const [taskProgress, setTaskProgress] = useState<TaskProgressDto | null>(null)
  const [taskFailure, setTaskFailure] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)
  const [loadingRunId, setLoadingRunId] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const submissionPending = useRef(false)
  const loadSequence = useRef(0)
  const detailSequence = useRef(0)
  const requestedRun = useRef('')
  const initializedProfiles = useRef(false)
  // Late responses must never setState after unmount (epoch remount) — one flag.
  const mounted = useRef(true)
  useEffect(() => {
    mounted.current = true
    return () => { mounted.current = false }
  }, [])

  const load = useCallback(async () => {
    const sequence = ++loadSequence.current
    setLoading(true)
    setError('')
    try {
      const [profilesValue, runsValue, optionsValue] = await Promise.all([
        fetchStudioApi('/model/profiles'), fetchStudioApi('/benchmarks?limit=30'), fetchStudioApi('/benchmarks/options'),
      ])
      if (!mounted.current || sequence !== loadSequence.current) return
      const parsedProfiles = parseModelProfiles(profilesValue).filter(item => item.configured)
      setProfiles(parsedProfiles)
      const parsedOptions = parseBenchmarkOptions(optionsValue)
      setOptions(parsedOptions)
      const routes = parseRouteMap(profilesValue)
      const available = new Set(parsedProfiles.map(profile => profile.id))
      const initial = !initializedProfiles.current
      if (initial) setOutlineStart(String(parsedOptions.defaultOutlineStart))
      initializedProfiles.current = true
      const defaultWriter = text(routes['chapter_write'])
      const defaultReviewer = text(routes['review'])
      setWriters(previous => initial
        ? new Set([available.has(defaultWriter) ? defaultWriter : parsedProfiles[0]?.id].filter((id): id is string => Boolean(id)))
        : new Set([...previous].filter(id => available.has(id))))
      setReviewers(previous => initial
        ? new Set([available.has(defaultReviewer) ? defaultReviewer : parsedProfiles[0]?.id].filter((id): id is string => Boolean(id)))
        : new Set([...previous].filter(id => available.has(id))))
      setRuns(parseRuns(runsValue))
    } catch (cause: unknown) {
      if (mounted.current && sequence === loadSequence.current) {
        setOptions(null)
        setError(cause instanceof Error ? cause.message : String(cause))
      }
    } finally {
      if (mounted.current && sequence === loadSequence.current) setLoading(false)
    }
  }, [fetchStudioApi])

  const openRun = useCallback(async (runId: string) => {
    const sequence = ++detailSequence.current
    requestedRun.current = runId
    setLoadingRunId(runId)
    setError('')
    try {
      const detail = data(await fetchStudioApi(`/benchmarks/${encodeURIComponent(runId)}`))
      if (mounted.current && sequence === detailSequence.current) {
        setSelected(detail)
        setReviewOutcomes(previous => ({ ...previous, [runId]: { status: experimentStatus(detail), incomplete: reviewCompleteness(detail).incomplete } }))
      }
      return detail
    } catch (cause: unknown) {
      if (mounted.current && sequence === detailSequence.current) setError(cause instanceof Error ? cause.message : String(cause))
    } finally {
      if (mounted.current && sequence === detailSequence.current) setLoadingRunId('')
    }
  }, [fetchStudioApi])

  const refresh = useCallback(() => {
    void load()
    if (requestedRun.current !== '') void openRun(requestedRun.current)
  }, [load, openRun])

  // Resource invalidation reloads data without discarding the user's configuration.
  useEffect(() => { refresh() }, [refresh, refreshEpoch])

  // A task link opens its immutable result once. Users can then browse other runs.
  useEffect(() => {
    if (initialRunId !== '') void openRun(initialRunId)
  }, [initialRunId, openRun])

  useEffect(() => {
    const latest = runs[0]
    if (initialRunId === '' && requestedRun.current === '' && latest !== undefined) void openRun(latest.runId)
  }, [initialRunId, openRun, runs])

  useEffect(() => {
    if (activeTask === '') return
    let active = true
    let polling = false
    let lastPartial = ''
    const poll = async () => {
      if (polling) return
      polling = true
      try {
        const response = data(await fetchStudioApi(`/tasks/${encodeURIComponent(activeTask)}`))
        const task = record(response['task'])
        if (!active) return
        const status = text(task['status'])
        const cancelRequested = task['cancel_requested'] === true && status === 'running'
        setCancelling(cancelRequested)
        setTaskStatus(cancelRequested ? 'cancelling' : status)
        const partialRef = parseResultRef(task['result_ref'])
        const progressKey = JSON.stringify([task['progress'], cancelRequested, partialRef])
        if (status === 'running' && partialRef?.type === 'benchmark_run' && lastPartial !== progressKey) {
          lastPartial = progressKey
          await openRun(partialRef.id)
          if (!active) return
        }
        setTaskPhase(text(task['phase']))
        setTaskProgress(parseTaskProgress(task['progress']))
        if (['completed', 'failed', 'cancelled', 'interrupted'].includes(status)) {
          const failure = record(task['error'])
          setTaskFailure([text(failure['message']), text(failure['code'])].filter(Boolean).join(' · '))
          // A completed worker only means the benchmark pipeline returned. Its
          // immutable run describes whether the experiment actually succeeded.
          const ref = parseResultRef(task['result_ref'])
          if (ref?.type === 'benchmark_run') {
            const result = await openRun(ref.id)
            if (!active) return
            const outcome = result ? experimentStatus(result) : ''
            if (status === 'completed' && ['completed', 'failed', 'partial', 'cancelled', 'interrupted'].includes(outcome)) {
              setTaskStatus(outcome)
              if (outcome !== 'completed') setTaskPhase('')
            }
          }
          setActiveTask('')
          await load()
        }
      } catch (cause: unknown) {
        if (active) setError(cause instanceof Error ? cause.message : String(cause))
      } finally {
        polling = false
      }
    }
    void poll()
    const timer = window.setInterval(() => { void poll() }, 1500)
    return () => { active = false; window.clearInterval(timer) }
  }, [activeTask, fetchStudioApi, load, openRun])

  const chapter = chapterChoice === '__custom__' ? customChapter.trim() : chapterChoice
  const chapterTarget = chapter === 'next' ? options?.nextChapterId : chapter
  const chosenChapter = options?.chapters.find(item => item.id === chapterTarget)
  const outlineStartNumber = outlineStartMode === 'continue' ? options?.defaultOutlineStart ?? null : positiveInteger(outlineStart)
  const outlineCountNumber = positiveInteger(outlineCount)
  const effectiveMode = taskType === 'outline' ? 'framework' : executionMode
  const taskCapability = options?.tasks.find(task => task.taskType === taskType)
  const pipeline = taskCapability?.pipelines.find(item => item.executionMode === effectiveMode) ?? null
  const readinessBlocked = taskCapability?.readiness.ok === false
    && !(taskType === 'chapter' && chapter !== 'next' && chosenChapter?.available
      && taskCapability.readiness.code === 'TARGET_NOT_PLANNED')
  const validRange = outlineStartNumber !== null && outlineCountNumber !== null && options !== null
    && outlineStartNumber >= options.outlineStartMin && outlineCountNumber <= options.outlineCountMax
    && outlineStartNumber + outlineCountNumber - 1 <= options.outlineStartMax
  const validTarget = taskType === 'outline' ? validRange : chosenChapter !== undefined && chosenChapter.available
  const validConfig = validTarget && pipeline !== null && pipeline.nodes.length > 0 && !readinessBlocked

  const submit = async () => {
    if (loading || writers.size === 0 || reviewers.size === 0 || activeTask !== '' || submissionPending.current) return
    if (!validConfig) return
    const numericSettings: [number, number, number][] = [[Number(repeats), 1, 5], [Number(concurrency), 1, 4]]
    if (taskType === 'chapter') numericSettings.push([Number(targetWords), 200, 12000])
    if (!numericSettings.every(([value, min, max]) => Number.isInteger(value) && value >= min && value <= max)) return
    submissionPending.current = true
    setSubmitting(true)
    setError('')
    setTaskFailure('')
    try {
      const response = data(await postStudioApi('/benchmarks', {
        task_type: taskType, writer_profile_ids: [...writers], reviewer_profile_ids: [...reviewers],
        execution_mode: effectiveMode, repeats: Number(repeats), concurrency: Number(concurrency),
        ...(taskType === 'chapter' ? { chapter_id: chapter, target_words: Number(targetWords) }
          : { outline_start_chapter: outlineStartNumber, outline_chapter_count: outlineCountNumber }),
      }))
      if (!mounted.current) return
      const taskId = text(response['task_id'])
      setActiveTask(taskId)
      setTaskStatus(text(response['status']) || 'pending')
      setTaskPhase('')
      setTaskProgress(null)
    } catch (cause: unknown) {
      if (mounted.current) setError(cause instanceof Error ? cause.message : String(cause))
    } finally {
      submissionPending.current = false
      if (mounted.current) setSubmitting(false)
    }
  }

  const evaluations = useMemo(() => selected !== null && Array.isArray(selected['evaluations']) ? selected['evaluations'].map(record) : [], [selected])
  const candidates = useMemo(() => selected !== null && Array.isArray(selected['candidates']) ? selected['candidates'].map(record) : [], [selected])
  const candidatesById = useMemo(() => new Map(candidates.map(item => [text(item['candidate_id']), item])), [candidates])
  const executionEntries = useMemo(() => [
    ...candidates.map((item, index) => ({ key: `candidate:${index}`, kind: 'candidate', item, profile: record(item['writer_profile']) })),
    ...evaluations.map((item, index) => ({ key: `evaluation:${index}`, kind: 'evaluation', item, profile: record(item['reviewer_profile']) })),
  ].flatMap(entry => {
    const trace = record(record(entry.item['framework'])['pipeline_execution'])
    const nodes = Array.isArray(trace['nodes']) ? trace['nodes'].map(record) : []
    return nodes.length > 0 ? [{ ...entry, nodes, pipelineId: text(trace['id']) }] : []
  }), [candidates, evaluations])
  const selectedConfig = useMemo(() => record(selected?.['config']), [selected])
  const selectedTaskType = selected?.['task_type'] === 'outline' || selectedConfig['task_type'] === 'outline' ? 'outline' : 'chapter'
  const selectedPipeline = useMemo(() => parseBenchmarkPipeline(selectedConfig['pipeline']), [selectedConfig])
  const selectedSummary = useMemo(() => record(selected?.['summary']), [selected])
  const selectedReview = useMemo(() => reviewCompleteness(selected ?? {}), [selected])
  const selectedStatus = selected === null ? '' : experimentStatus(selected)
  const coverageRange = selectedReview.reportedCoverage.length === 0 ? '—' : (() => {
    const min = Math.round(Math.min(...selectedReview.reportedCoverage) * 100)
    const max = Math.round(Math.max(...selectedReview.reportedCoverage) * 100)
    return min === max ? `${min}%` : `${min}–${max}%`
  })()
  const factsPending = [...candidates, ...evaluations].some(item => text(record(item['error'])['code']) === 'MANUSCRIPT_FACTS_PENDING')
  const selectedContext = useMemo(() => record(selected?.['context_snapshot']), [selected])
  const selectedManifest = useMemo(() => record(selectedContext['manifest']), [selectedContext])
  const selectedComparison = useMemo(
    () => parseComparison(selected?.['comparison'], text(selected?.['run_id'])),
    [selected],
  )
  const runGroups = useMemo(() => {
    const grouped = new Map<string, { comparison: BenchmarkComparison; runs: BenchmarkRun[] }>()
    for (const run of runs) {
      const current = grouped.get(run.comparison.key)
      if (current) current.runs.push(run)
      else grouped.set(run.comparison.key, { comparison: run.comparison, runs: [run] })
    }
    return [...grouped.values()]
  }, [runs])
  const selectedMode = nullableText(selectedConfig['execution_mode']) ?? selectedComparison.executionMode
  const selectedSources = useMemo(() => {
    const unique = new Map<string, { path: string; revision: string; exists: boolean | null; section: string }>()
    const items = Array.isArray(selectedManifest['items']) ? selectedManifest['items'].map(record) : []
    for (const item of items) {
      const section = text(item['section'])
      for (const rawSource of Array.isArray(item['sources']) ? item['sources'] : []) {
        const source = record(rawSource)
        const path = text(source['path'])
        const revision = text(source['revision'])
        if (path === '') continue
        const exists = typeof source['exists'] === 'boolean' ? source['exists'] : null
        unique.set(`${path}\u0000${revision}`, { path, revision, exists, section })
      }
    }
    return [...unique.values()]
  }, [selectedManifest])

  const modeLabel = (mode: string | null): string => {
    if (mode === 'framework') return t('benchmark.mode.framework')
    if (mode === 'creative') return t('benchmark.mode.creative')
    return t('benchmark.mode.unknown')
  }

  const valueOrDash = (value: unknown): string => nullableText(value) ?? '—'
  const numberOrDash = (value: unknown): string => {
    const amount = optionalNumber(value)
    return amount === null ? '—' : String(amount)
  }

  const errorCell = (item: RecordValue) => {
    const error = record(item['error'])
    const code = text(error['code'])
    const message = text(error['message'])
    if (code === '' && message === '') return <span>—</span>
    return <span className={css.benchmarkError}>
      {code === 'MANUSCRIPT_FACTS_PENDING' && <strong>{t('benchmark.factsPendingTitle')}</strong>}
      <span>{[code, message].filter(Boolean).join(' · ')}</span>
    </span>
  }

  const usageCell = (item: RecordValue) => {
    const usage = record(item['usage'])
    const prompt = optionalNumber(usage['prompt_tokens'] ?? usage['input_tokens'])
    const completion = optionalNumber(usage['completion_tokens'] ?? usage['output_tokens'])
    const reasoning = optionalNumber(item['reasoning_tokens'])
    const total = optionalNumber(usage['total_tokens'])
    if (prompt === null && completion === null && reasoning === null) {
      return <span>{total === null ? '—' : `${t('benchmark.totalTokens')} ${formatTokens(total)}`}</span>
    }
    return <span className={css.benchmarkUsage}>
      <span>{t('benchmark.inputTokens')} {formatTokens(prompt)}</span>
      <span>{t('benchmark.outputTokens')} {formatTokens(completion)}</span>
      <small>{t('benchmark.reasoningTokens')} {formatTokens(reasoning)}</small>
    </span>
  }

  const costCell = (item: RecordValue) => {
    if (item['cost_reported'] !== true) return <span>—</span>
    const cost = optionalNumber(item['cost_usd'])
    const usage = record(item['usage'])
    const total = optionalNumber(usage['total_tokens'])
    const effectiveRate = cost !== null && total !== null && total > 0 ? cost * 1_000_000 / total : null
    return <span className={css.benchmarkCost}>
      <strong>{formatUsd(cost)}</strong>
      <small>{t('benchmark.effectiveRate')} {formatUsd(effectiveRate)}</small>
    </span>
  }

  // Latency is optional in the contract: never render a fabricated "0 ms".
  const latencyCell = (item: RecordValue) => {
    const latency = optionalNumber(item['latency_ms'])
    return <td>{latency === null ? '—' : `${Math.round(latency)} ms`}</td>
  }

  const phaseLabel = (phase: string): string => {
    switch (phase) {
      case 'queued': return t('tasks.phase.queued')
      case 'reading': return t('tasks.phase.reading')
      case 'preparing': return t('tasks.phase.preparing')
      case 'model': return t('tasks.phase.model')
      case 'validating': return t('tasks.phase.validating')
      case 'committing': return t('tasks.phase.committing')
      case 'complete': return t('tasks.phase.complete')
      default: return phase
    }
  }

  const statusLabel = (status: string): string => {
    switch (status) {
      case 'pending': return t('tasks.status.pending')
      case 'running': return t('tasks.status.running')
      case 'completed': return t('tasks.status.completed')
      case 'finished': return t('benchmark.pipelineFinished')
      case 'failed': return t('tasks.status.failed')
      case 'partial': return t('review.status.partial')
      case 'cancelling': return '取消中'
      case 'cancelled': return t('tasks.status.cancelled')
      case 'interrupted': return t('tasks.status.interrupted')
      case 'skipped': return t('benchmark.status.skipped')
      case 'stale': return t('benchmark.status.stale')
      default: return status || '—'
    }
  }

  // Display reported units; never fabricate progress percentages.
  const taskMeta = [
    statusLabel(taskStatus),
    taskPhase === '' ? '' : phaseLabel(taskPhase),
    taskProgress === null ? '' : `${taskProgress.completed_units}/${taskProgress.total_units} ${taskProgress.unit_kind === 'evaluations' ? t('benchmark.evaluations') : t('benchmark.candidates')}`,
  ].filter(part => part !== '').join(' · ')
  const repeatCount = Number(repeats)
  const plannedCandidates = writers.size * (Number.isInteger(repeatCount) && repeatCount >= 1 && repeatCount <= 5 ? repeatCount : 0)
  const plannedEvaluations = plannedCandidates * reviewers.size
  const busy = submitting || activeTask !== ''
  const selectedNames = (ids: Set<string>): string => profiles.filter(profile => ids.has(profile.id)).map(profile => profile.label).join(' · ')
  const toggleProfile = (previous: Set<string>, id: string): Set<string> => {
    const next = new Set(previous)
    if (next.has(id)) next.delete(id)
    else next.add(id)
    return next
  }
  const taskLabel = (kind: BenchmarkTaskType): string => t(kind === 'outline' ? 'benchmark.task.outline' : 'benchmark.task.chapter')
  const rangeLabel = (start: number | null, count: number | null): string => start === null || count === null ? '—'
    : `${t('benchmark.rangeFrom')} ${start} ${t('benchmark.rangeTo')} ${start + count - 1} ${t('benchmark.chapterUnit')}`.trim()
  const renderPipeline = (plan: BenchmarkPipeline, result = false) => <section className={css.pipeline} aria-label={t(result ? 'benchmark.executedDag' : 'benchmark.autoDag')}>
    <details open={result}>
    <summary className={css.pipelineHeading}><GitBranch size={15} aria-hidden="true" /><strong>{t(result ? 'benchmark.executedDag' : 'benchmark.autoDag')} · {plan.nodes.length}</strong><span>{t('benchmark.dagAutomatic')}</span><ChevronRight size={14} aria-hidden="true" /></summary>
    <ol className={css.pipelineNodes}>{plan.nodes.map(node => <li key={node.id}>
      <strong>{node.label}</strong>
      {node.dependsOn.length > 0 && <small>{t('benchmark.afterStage')} {node.dependsOn.map(id => plan.nodes.find(parent => parent.id === id)?.label ?? id).join(' · ')}</small>}
    </li>)}</ol>
    </details>
    {plan.reviewDomains.length > 0 && <p>{t('benchmark.reviewScope')} {plan.reviewDomains.map(domain => domain.label).join(' · ')}</p>}
    {!result && <p>{t('benchmark.isolatedHint')}</p>}
  </section>

  return <div className={css.root}>
    <div className={css.body}>
      <header className={css.pageHeader}>
        <div className={css.pageIdentity}>
          <span className={css.pageIcon}><FlaskConical size={21} aria-hidden="true" /></span>
          <div><h1>{t('benchmark.title')}</h1><p>{t('benchmark.description')}</p></div>
        </div>
        <button type="button" className={css.button} title={t('refresh')} disabled={loading} onClick={refresh}>
          <RefreshCw size={14} className={loading ? css.spinning : undefined} aria-hidden="true" />{t('refresh')}
        </button>
      </header>
      {error !== '' && <div className={css.taskError} role="alert">{error}</div>}
      <form className={css.benchmarkControls} onSubmit={event => { event.preventDefault(); void submit() }}>
        <div className={css.sectionHeading}>
          <div><h2>{t('benchmark.configure')}</h2><p>{t('benchmark.modelHint')}</p></div>
        </div>
        <fieldset className={css.taskSelector} disabled={busy || loading}>
          <legend>{t('benchmark.taskType')}</legend>
          {(['chapter', 'outline'] as const).map(kind => <label key={kind} data-selected={taskType === kind}>
            <input type="radio" name="benchmark-task" value={kind} checked={taskType === kind} onChange={() => setTaskType(kind)} />
            <span><strong>{taskLabel(kind)}</strong><small>{t(kind === 'chapter' ? 'benchmark.task.chapterHint' : 'benchmark.task.outlineHint')}</small></span>
          </label>)}
        </fieldset>
        {loading && profiles.length === 0 ? <div className={css.loading} role="status"><LoaderCircle size={18} className={css.spinning} aria-hidden="true" />{t('loading')}</div>
          : profiles.length === 0 ? <div className={css.notice}>{t('benchmark.noProfiles')}</div>
          : <div className={css.modelGroups}>
            <fieldset className={css.modelGroup} disabled={busy}>
              <legend>{t(taskType === 'outline' ? 'benchmark.planner' : 'benchmark.writer')} <span className={css.count}>{writers.size}</span></legend>
              <details className={css.modelPicker}>
                <summary><span data-empty={writers.size === 0} title={selectedNames(writers)}>{selectedNames(writers) || t('benchmark.selectModels')}</span><ChevronRight size={15} aria-hidden="true" /></summary>
                <div className={css.benchmarkProfiles}>{profiles.map(profile => <label key={profile.id} className={css.profileChoice} data-selected={writers.has(profile.id)}>
                  <input type="checkbox" checked={writers.has(profile.id)} onChange={() => setWriters(previous => toggleProfile(previous, profile.id))} />
                  <span><strong>{profile.label}</strong><small>{profile.provider} · {profile.model}</small></span>
                </label>)}</div>
              </details>
            </fieldset>
            <fieldset className={css.modelGroup} disabled={busy}>
              <legend>{t('benchmark.reviewer')} <span className={css.count}>{reviewers.size}</span></legend>
              <details className={css.modelPicker}>
                <summary><span data-empty={reviewers.size === 0} title={selectedNames(reviewers)}>{selectedNames(reviewers) || t('benchmark.selectModels')}</span><ChevronRight size={15} aria-hidden="true" /></summary>
                <div className={css.benchmarkProfiles}>{profiles.map(profile => <label key={profile.id} className={css.profileChoice} data-selected={reviewers.has(profile.id)}>
                  <input type="checkbox" checked={reviewers.has(profile.id)} onChange={() => setReviewers(previous => toggleProfile(previous, profile.id))} />
                  <span><strong>{profile.label}</strong><small>{profile.provider} · {profile.model}</small></span>
                </label>)}</div>
              </details>
            </fieldset>
          </div>}
        <fieldset className={css.configFields} disabled={busy}>
          <div className={css.benchmarkInputs}>
            {taskType === 'chapter' ? <>
            <label>{t('benchmark.chapter')}<select value={chapterChoice} onChange={event => setChapterChoice(event.target.value)}>
              <option value="next">{t('benchmark.nextChapter')}{options?.nextChapterId ? ` · ${options.nextChapterId}` : ''}</option>
              {options?.chapters.map(item => <option key={item.id} value={item.id} disabled={!item.available}>
                {item.id} · {item.title} · {t(item.hasManuscript ? 'benchmark.chapterWritten' : 'benchmark.chapterPlanned')}{!item.available ? ` · ${item.reason || t('benchmark.chapterUnavailable')}` : ''}
              </option>)}
              <option value="__custom__">{t('benchmark.customChapter')}</option>
            </select></label>
            <label>{t('benchmark.words')}<input type="number" min={200} max={12000} step={1} required value={targetWords} onChange={event => setTargetWords(event.target.value)} /></label>
            <label>{t('benchmark.mode')}<select value={executionMode} onChange={event => setExecutionMode(event.target.value as 'framework' | 'creative')}>
              <option value="framework">{t('benchmark.mode.framework')}</option>
              <option value="creative">{t('benchmark.mode.creative')}</option>
            </select></label>
            {chapterChoice === '__custom__' && <label>{t('benchmark.chapterId')}<input required value={customChapter} placeholder={options?.nextChapterId || 'ch_001'} onChange={event => setCustomChapter(event.target.value)} /></label>}
            </> : <>
              <label>{t('benchmark.outlineOrigin')}<select value={outlineStartMode} onChange={event => setOutlineStartMode(event.target.value as 'continue' | 'custom')}>
                <option value="continue">{t('benchmark.continueOutline')} · {options?.defaultOutlineStart ?? '—'}</option>
                <option value="custom">{t('benchmark.customOutlineStart')}</option>
              </select></label>
              <label>{t('benchmark.outlineStart')}<input type="number" min={options?.outlineStartMin ?? 1} max={options?.outlineStartMax ?? 100000} step={1} required disabled={outlineStartMode === 'continue'}
                value={outlineStartMode === 'continue' ? String(options?.defaultOutlineStart ?? '') : outlineStart} onChange={event => setOutlineStart(event.target.value)} /></label>
              <label>{t('benchmark.outlineCount')}<input type="number" min={1} max={options?.outlineCountMax ?? 20} step={1} required value={outlineCount} onChange={event => setOutlineCount(event.target.value)} /></label>
            </>}
          </div>
          {taskType === 'outline' ? <p className={css.scopeHint} role="status">
            {validRange ? <strong>{rangeLabel(outlineStartNumber, outlineCountNumber)}</strong> : <strong>{t('benchmark.invalidRange')}</strong>}
            <span>{t('benchmark.outlineRangeHint')} {t('benchmark.earliestOutlineStart')} {options?.outlineStartMin ?? 1}</span>
          </p> : <p className={css.scopeHint}>
            {chosenChapter ? <span>{chosenChapter.available ? chosenChapter.title : chosenChapter.reason || t('benchmark.chapterUnavailable')}</span> : <span>{t('benchmark.invalidChapter')}</span>}
            {options?.chapters.some(item => !item.available && (item.hasManuscript || Number(item.id.replace(/^ch_/, '')) < options.outlineStartMin)) && <span>{t('benchmark.historicalChapterHint')}</span>}
          </p>}
          {pipeline ? renderPipeline(pipeline) : !loading && <p className={css.scopeHint} role="alert">{t('benchmark.pipelineUnavailable')}</p>}
          <details className={css.advanced}>
            <summary><ChevronRight size={14} aria-hidden="true" />{t('benchmark.advanced')}<span>{t('benchmark.repeats')} {repeats || '—'} · {t('benchmark.concurrency')} {concurrency || '—'}</span></summary>
            <div className={css.advancedInputs}>
              <label>{t('benchmark.repeats')}<input type="number" min={1} max={5} step={1} required onInvalid={event => event.currentTarget.closest('details')?.setAttribute('open', '')} value={repeats} onChange={event => setRepeats(event.target.value)} /></label>
              <label>{t('benchmark.concurrency')}<input type="number" min={1} max={4} step={1} required onInvalid={event => event.currentTarget.closest('details')?.setAttribute('open', '')} value={concurrency} onChange={event => setConcurrency(event.target.value)} /></label>
            </div>
          </details>
        </fieldset>
        {readinessBlocked && taskCapability && <div className={css.taskError} role="status" data-testid="benchmark-readiness">
          {taskCapability.readiness.message || taskCapability.readiness.code}
        </div>}
        <div className={css.launchBar}>
          <div className={css.workload}>
            <strong>{t('benchmark.workload')}</strong>
            <span>{plannedCandidates} {t('benchmark.plannedCandidates')} <span aria-hidden="true">·</span> {plannedEvaluations} {t('benchmark.plannedEvaluations')}</span>
            <small>每次请求的输出 token 上限：{profiles.filter(profile => writers.has(profile.id) || reviewers.has(profile.id)).map(profile => `${profile.label || profile.id} ${profile.max_output_tokens || '未配置'}`).join(' · ') || '请先选择模型'}</small>
            <small>评审数为上限；实际调用取决于候选完成情况。费用由服务商返回，未返回时标记为未知。</small>
            {!loading && (writers.size === 0 || reviewers.size === 0) && <small>{t('benchmark.chooseModels')}</small>}
          </div>
          <button type="submit" className={css.primaryButton} disabled={loading || !validConfig || writers.size === 0 || reviewers.size === 0 || busy}>
            {busy ? <LoaderCircle size={15} className={css.spinning} aria-hidden="true" /> : <Play size={15} aria-hidden="true" />}
            {submitting ? t('benchmark.submitting') : activeTask !== '' ? t('tasks.status.running') : t('benchmark.run')}
          </button>
        </div>
      </form>
      {taskStatus !== '' && <div className={css.taskProgress} data-status={taskStatus} role="status" aria-live="polite">
        {activeTask !== '' && <LoaderCircle size={16} className={css.spinning} aria-hidden="true" />}
        <strong>{t('benchmark.task')}</strong><span>{taskMeta}</span>
        {activeTask !== '' && <button type="button" disabled={cancelling} onClick={() => {
          setCancelling(true)
          void postStudioApi(`/tasks/${encodeURIComponent(activeTask)}/cancel`, {}).catch(cause => { setCancelling(false); setError(String(cause)) })
        }}>{cancelling ? '取消中…' : '取消测试'}</button>}
        {cancelling && <p>已停止后续调度。已发送的请求仍可能产生费用；返回后会保存结果和实际用量。</p>}
        {taskFailure !== '' && <p className={css.taskFailure} role="alert">{taskFailure}</p>}
        {taskProgress !== null && taskProgress.total_units > 0 && <progress max={taskProgress.total_units} value={taskProgress.completed_units} aria-label={t('benchmark.task')} />}
      </div>}
      <div className={css.benchmarkSplit}>
        <aside className={css.benchmarkRuns} aria-label={t('benchmark.history')}>
          <div className={css.historyHeading}><h2><History size={16} aria-hidden="true" />{t('benchmark.history')}</h2><span className={css.count}>{runs.length}</span></div>
          <div className={css.runList}>
          {runs.length === 0 && <div className={css.notice}>{loading ? t('loading') : t('benchmark.empty')}</div>}
          {runGroups.map(group => <section key={group.comparison.key} className={css.benchmarkRunGroup} data-testid="benchmark-comparison-group">
            <div className={css.benchmarkRunGroupHeader}>
              <strong>{t('benchmark.sameInputGroup')} · {group.runs.length} {t('benchmark.runs')}</strong>
              <span title={`${group.comparison.promptVersion ?? '—'} · ${group.comparison.rubricVersion ?? '—'}`}>{group.comparison.promptVersion ?? '—'} · {group.comparison.rubricVersion ?? '—'}</span>
              {!group.comparison.basisComplete && <small className={css.benchmarkLegacy}>{t('benchmark.comparisonIncomplete')}</small>}
            </div>
            {group.runs.map(run => {
              // List summaries count partial reviews as completed; a neutral
              // finished state is honest until this run's details are inspected.
              const outcome = reviewOutcomes[run.runId]
              const displayStatus = outcome?.status ?? (run.status === 'completed' ? 'finished' : run.status)
              return <button key={run.runId} type="button" className={css.benchmarkRun}
              aria-pressed={selected?.['run_id'] === run.runId} data-active={selected?.['run_id'] === run.runId} onClick={() => void openRun(run.runId)}>
              <span className={css.runHeading}><strong>{run.taskType === 'outline' ? rangeLabel(run.outlineStart, run.outlineCount) : run.chapterId}</strong><span className={css.benchmarkStatus} data-status={displayStatus}>{statusLabel(displayStatus)}</span></span>
              <span>{taskLabel(run.taskType)} · {modeLabel(run.executionMode)}</span>
              <span className={css.runScore}>{t(outcome?.incomplete ? 'benchmark.partialScore' : 'benchmark.averageScore')} <strong>{numberOrDash(run.summary['average_quality_score'])}</strong><small>{run.candidateCount} {t('benchmark.plannedCandidates')} · {run.evaluationCount} {t('benchmark.plannedEvaluations')}</small></span>
              {outcome === undefined && run.status === 'completed' && run.evaluationCount > 0 && <small>{t('benchmark.coveragePending')}</small>}
              <small className={css.runId} title={run.runId}>{run.runId}</small>
              <small>{run.createdAt.slice(0, 16).replace('T', ' ')}</small>
            </button>})}
          </section>)}
          </div>
        </aside>
        <div className={css.benchmarkResults} aria-busy={loadingRunId !== ''}>
          {loadingRunId !== '' ? <div className={css.resultPlaceholder} role="status"><LoaderCircle size={25} className={css.spinning} aria-hidden="true" /><strong>{t('loading')}</strong></div>
          : selected === null ? <div className={css.resultPlaceholder}><BarChart3 size={30} aria-hidden="true" /><strong>{t('benchmark.results')}</strong><p>{t('benchmark.select')}</p></div> : <>
            <div className={css.benchmarkSummary}>
              <div><h2>{t('benchmark.results')} <span>{selectedTaskType === 'outline'
                ? `${taskLabel('outline')} · ${rangeLabel(optionalNumber(selectedConfig['outline_start_chapter']), optionalNumber(selectedConfig['outline_chapter_count']))}`
                : text(selected['chapter_id'])}</span></h2><small>{text(selected['run_id'])}</small></div>
              <span data-testid="benchmark-selected-mode">{modeLabel(selectedMode)} <span className={css.benchmarkStatus} data-status={selectedStatus}>{statusLabel(selectedStatus)}</span></span>
            </div>
            {selectedStatus === 'cancelling' && <div role="status" className={css.reviewWarning}>取消中：还有 {number(selected['in_flight'])} 个请求在途。以下为已保存的部分结果，费用尚未结算完整。</div>}
            {factsPending && <div className={css.reviewWarning} role="note" aria-label={t('benchmark.factsPendingTitle')}>
              <strong>{t('benchmark.factsPendingTitle')}</strong><p>{t('benchmark.factsPendingHint')}</p>
            </div>}
            {selectedReview.incomplete && <div className={css.reviewWarning} role="note" aria-label={t('benchmark.reviewIncomplete')}>
              <strong>{t('benchmark.reviewIncomplete')}</strong>
              <p>{t('benchmark.reviewIncompleteHint')}</p>
              <span>{t('benchmark.completeReviews')} {selectedReview.complete}/{selectedReview.total} · {t('benchmark.reportedCoverage')} {coverageRange}</span>
              {selectedReview.domains.length > 0 && <span>{t('benchmark.domains')}: {selectedReview.domains.join(', ')}</span>}
            </div>}
            <div className={css.benchmarkMetrics}>
              <div data-partial={selectedReview.incomplete}><span>{t(selectedReview.incomplete ? 'benchmark.partialScore' : 'benchmark.averageScore')}</span><strong>{optionalNumber(selectedSummary['average_quality_score']) === null ? '—' : String(optionalNumber(selectedSummary['average_quality_score']))}</strong>{selectedReview.incomplete && <small>{t('benchmark.reviewIncomplete')}</small>}</div>
              <div><span>{t('benchmark.inputTokens')}</span><strong>{formatTokens(selectedSummary['prompt_tokens'])}</strong></div>
              <div><span>{t('benchmark.outputTokens')}</span><strong>{formatTokens(selectedSummary['completion_tokens'])}</strong></div>
              <div><span>{t('benchmark.reasoningTokens')}</span><strong>{formatTokens(selectedSummary['reasoning_tokens'])}</strong></div>
              <div><span>{t('benchmark.actualCost')}</span><strong>{number(selectedSummary['cost_reported_items']) > 0 ? formatUsd(selectedSummary['total_cost_usd']) : '—'}</strong><small>{t('benchmark.costCoverage')} {number(selectedSummary['cost_item_count']) > 0 ? `${number(selectedSummary['cost_reported_items'])}/${number(selectedSummary['cost_item_count'])}` : '—'}</small></div>
            </div>
            <section className={css.benchmarkSection}>
              <h3>{t('benchmark.candidates')} <span className={css.count}>{candidates.length}</span></h3>
              {candidates.length === 0 ? <div className={css.notice}>{t('benchmark.noCandidates')}</div> : <div className={css.tableScroll} tabIndex={0} role="region" aria-label={t('benchmark.candidates')}><table className={css.benchmarkTable} aria-label={t('benchmark.candidates')}>
                <thead><tr><th>{t(selectedTaskType === 'outline' ? 'benchmark.planner' : 'benchmark.writer')}</th><th>{t('benchmark.path')}</th><th>{t('benchmark.status')}</th><th>{t(selectedTaskType === 'outline' ? 'benchmark.actualChapters' : 'benchmark.actualWords')}</th><th>{t('benchmark.finishReason')}</th><th>{t('benchmark.error')}</th><th>{t('benchmark.usage')}</th><th>{t('benchmark.cost')}</th><th>{t('benchmark.latency')}</th></tr></thead>
                <tbody>{candidates.map(item => {
                  const writerProfile = record(item['writer_profile'])
                  const framework = record(item['framework'])
                  const reliability = text(item['reliability_status'])
                  const mode = nullableText(item['execution_mode']) ?? selectedMode
                  const writeEntrypoint = text(framework['write_entrypoint']) || (selectedTaskType === 'outline' ? '' : mode === 'framework' ? 'execute_write_chapter' : mode === 'creative' ? 'WriterAgent._creative_write' : '')
                  const responseIdentity = [text(item['response_provider']), text(item['response_model'])].filter(Boolean).join(' · ')
                  return <tr key={text(item['candidate_id'])}>
                    <td><span className={css.benchmarkCellStack}><strong>{text(writerProfile['label'] || writerProfile['id']) || '—'}</strong><small>{[text(writerProfile['provider']), text(writerProfile['model'])].filter(Boolean).join(' · ') || '—'}</small>{responseIdentity !== '' && <small>{t('benchmark.responseIdentity')} · {responseIdentity}</small>}</span></td>
                    <td><span className={css.benchmarkCellStack}><strong>{modeLabel(mode)}</strong>{writeEntrypoint !== '' && <small>{writeEntrypoint}</small>}{text(framework['run_id_v2']) !== '' && <small>{text(framework['run_id_v2'])}</small>}</span></td>
                    <td><span className={css.benchmarkStatus} data-status={reliability}>{statusLabel(reliability)}</span></td>
                    <td>{numberOrDash(item[selectedTaskType === 'outline' ? 'outline_chapter_count' : 'word_count'])}</td><td>{text(item['finish_reason']) || '—'}</td>
                    <td>{errorCell(item)}</td><td>{usageCell(item)}</td><td>{costCell(item)}</td>{latencyCell(item)}
                  </tr>
                })}</tbody>
              </table></div>}
            </section>
            {candidates.length > 0 && <section className={css.benchmarkSection}>
              <h3>{t('benchmark.output')}</h3>
              <div className={css.benchmarkOutputList}>
                {candidates.map(item => {
                  const content = typeof item['content'] === 'string' ? item['content'] : ''
                  const artifact = text(record(item['content'])['$artifact'])
                  return <details key={`output-${text(item['candidate_id'])}`} className={css.benchmarkOutput} open={candidates.length === 1}>
                    <summary>{text(item['title']) || text(item['candidate_id'])} · {numberOrDash(item[selectedTaskType === 'outline' ? 'outline_chapter_count' : 'word_count'])} {t(selectedTaskType === 'outline' ? 'benchmark.actualChapters' : 'benchmark.actualWords')}</summary>
                    {selectedTaskType === 'outline' && <p>{rangeLabel(optionalNumber(item['outline_start_chapter']), optionalNumber(item['outline_chapter_count']))}</p>}
                    {content !== '' ? <pre>{content}</pre> : artifact !== '' ? <p>{artifact}</p> : <p>—</p>}
                  </details>
                })}
              </div>
            </section>}
            <section className={css.benchmarkSection}>
              <h3>{t('benchmark.evaluations')} <span className={css.count}>{evaluations.length}</span></h3>
              {evaluations.length === 0 ? <div className={css.notice}>{t('benchmark.noEvaluations')}</div> : <div className={css.tableScroll} tabIndex={0} role="region" aria-label={t('benchmark.evaluations')}><table className={css.benchmarkTable} aria-label={t('benchmark.evaluations')}>
                <thead><tr><th>{t('benchmark.candidate')}</th><th>{t('benchmark.reviewer')}</th><th>{t('benchmark.status')}</th><th>{t('benchmark.error')}</th><th>{t('review.score')}</th><th>{t('benchmark.coverage')}</th><th>{t('benchmark.gate')}</th><th>{t('benchmark.delivery')}</th><th>{t('benchmark.productionGate')}</th><th>{t('benchmark.usage')}</th><th>{t('benchmark.cost')}</th><th>{t('benchmark.latency')}</th></tr></thead>
                <tbody>{evaluations.map((item, index) => {
                  const reviewerProfile = record(item['reviewer_profile'])
                  const candidateProfile = record(candidatesById.get(text(item['candidate_id']))?.['writer_profile'])
                  const diagnostics = record(item['review_diagnostics'])
                  const framework = record(item['framework'])
                  const incompleteDomains = Array.isArray(diagnostics['inconclusive_domain_ids']) ? diagnostics['inconclusive_domain_ids'].map(text).filter(Boolean) : []
                  const execution = text(item['execution_status'])
                  return <tr key={`${text(item['candidate_id'])}-${index}`}>
                    <td>{text(candidateProfile['label'] || candidateProfile['id'] || item['candidate_id'])}</td>
                    <td><span className={css.benchmarkCellStack}><strong>{text(reviewerProfile['label'] || reviewerProfile['id'])}</strong><small>{text(reviewerProfile['provider'])} · {text(reviewerProfile['model'])}</small></span></td>
                    <td><span className={css.benchmarkCellStack}><span className={css.benchmarkStatus} data-status={execution}>{statusLabel(execution)}</span>{text(framework['review_entrypoint']) !== '' && <small>{text(framework['review_entrypoint'])}</small>}{incompleteDomains.length > 0 && <small>{t('benchmark.domains')}: {incompleteDomains.join(', ')}</small>}</span></td>
                    <td>{errorCell(item)}</td>
                    <td>{numberOrDash(item['quality_score'])}</td>
                    <td>{typeof item['coverage'] === 'number' ? `${Math.round(item['coverage'] * 100)}%` : '—'}</td>
                    <td>{text(item['gate_status']) || '—'}</td>
                    <td>{text(item['delivery_status']) || '—'}</td>
                    <td>{text(item['production_gate_status']) || t('benchmark.productionGateMissing')}</td>
                    <td>{usageCell(item)}</td>
                    <td>{costCell(item)}</td>
                    {latencyCell(item)}
                  </tr>
                })}</tbody>
              </table></div>}
            </section>
            {executionEntries.length > 0 && <details className={css.metadataSection} data-testid="benchmark-executions">
              <summary><GitBranch size={15} aria-hidden="true" />{t('benchmark.executionEvidence')} · {executionEntries.length}</summary>
              {executionEntries.map(entry => <section key={entry.key} className={css.executionRecord}>
                <h3>{t(entry.kind === 'candidate' ? 'benchmark.candidate' : 'benchmark.reviewer')} · {text(entry.profile['label'] || entry.profile['id']) || '—'}</h3>
                <small>{text(entry.item['candidate_id'])} · {entry.pipelineId}</small>
                <ol className={css.pipelineNodes}>{entry.nodes.map(node => <li key={text(node['id'])}>
                  <strong>{text(node['label'] || node['id'])}</strong> <span className={css.benchmarkStatus} data-status={text(node['status'])}>{statusLabel(text(node['status']))}</span>
                  {Array.isArray(node['depends_on']) && node['depends_on'].length > 0 && <small>{t('benchmark.afterStage')} {node['depends_on'].map(id => text(entry.nodes.find(parent => parent['id'] === id)?.['label'] || id)).join(' · ')}</small>}
                  {(Array.isArray(node['evidence']) ? node['evidence'] : []).map((raw, index) => {
                    const evidence = record(raw)
                    return <small key={index} title={text(evidence['sha256'])}>{t('benchmark.evidence')} {text(evidence['path'])}{text(evidence['sha256']) ? ` · ${text(evidence['sha256']).slice(0, 12)}` : ''}</small>
                  })}
                  {(text(node['error_code']) || text(node['reason'])) && <small>{text(node['error_code'] || node['reason'])}</small>}
                </li>)}</ol>
              </section>)}
            </details>}
            {selectedPipeline && <details className={css.metadataSection}>
              <summary><GitBranch size={15} aria-hidden="true" />{t('benchmark.executedDag')}</summary>
              {renderPipeline(selectedPipeline, true)}
            </details>}
            <details className={css.metadataSection} data-testid="benchmark-run-phases">
              <summary><ChevronRight size={14} aria-hidden="true" />{t('benchmark.runPhases')}</summary>
              <ol className={css.benchmarkPhases}>
                <li><span>{t('benchmark.phase.created')}</span><strong>{valueOrDash(selected['created_at'])}</strong></li>
                <li><span>{t('benchmark.phase.started')}</span><strong>{valueOrDash(selected['started_at'])}</strong></li>
                <li><span>{t('benchmark.candidates')}</span><strong>{numberOrDash(selectedSummary['completed_candidates'])}/{numberOrDash(selectedSummary['requested_candidates'])} {t('benchmark.candidates')}</strong></li>
                <li><span>{t('benchmark.evaluations')}</span><strong>{numberOrDash(selectedSummary['completed_evaluations'])}/{numberOrDash(selectedSummary['requested_evaluations'])} {t('benchmark.evaluations')}</strong></li>
                <li><span>{t('benchmark.phase.completed')}</span><strong>{valueOrDash(selected['completed_at'])}</strong></li>
              </ol>
            </details>
            <details className={css.metadataSection} data-testid="benchmark-provenance">
              <summary><ChevronRight size={14} aria-hidden="true" />{t('benchmark.inputProvenance')}</summary>
              <dl className={css.benchmarkProvenance}>
                <div><dt>{t('benchmark.pipelineStatus')}</dt><dd>{statusLabel(text(selected?.['status']))}</dd></div>
                <div><dt>{t('benchmark.contextHash')}</dt><dd>{valueOrDash(selected['context_hash'])}</dd></div>
                <div><dt>{t('benchmark.comparisonKey')}</dt><dd>{selectedComparison.key}</dd></div>
                <div><dt>{t('benchmark.promptVersion')}</dt><dd>{valueOrDash(selected['prompt_version'])}</dd></div>
                <div><dt>{t('benchmark.rubricVersion')}</dt><dd>{valueOrDash(selected['rubric_version'])}</dd></div>
                <div><dt>{t('benchmark.mode')}</dt><dd>{modeLabel(selectedMode)}</dd></div>
                <div><dt>{t('benchmark.taskType')}</dt><dd>{taskLabel(selectedTaskType)}</dd></div>
                {selectedTaskType === 'outline' ? <>
                  <div><dt>{t('benchmark.outlineStart')}</dt><dd>{numberOrDash(selectedConfig['outline_start_chapter'])}</dd></div>
                  <div><dt>{t('benchmark.outlineCount')}</dt><dd>{numberOrDash(selectedConfig['outline_chapter_count'])}</dd></div>
                </> : <div><dt>{t('benchmark.words')}</dt><dd>{numberOrDash(selectedConfig['target_words'] ?? selectedContext['target_words'])}</dd></div>}
                <div><dt>{t('benchmark.repeats')}</dt><dd>{numberOrDash(selectedConfig['repeats'])}</dd></div>
                <div><dt>{t('benchmark.writer')}</dt><dd>{Array.isArray(selectedConfig['writer_profile_ids']) ? selectedConfig['writer_profile_ids'].map(text).join(', ') : '—'}</dd></div>
                <div><dt>{t('benchmark.reviewer')}</dt><dd>{Array.isArray(selectedConfig['reviewer_profile_ids']) ? selectedConfig['reviewer_profile_ids'].map(text).join(', ') : '—'}</dd></div>
                <div><dt>{t('benchmark.blindReview')}</dt><dd>{typeof selectedConfig['blind_review'] === 'boolean' ? String(selectedConfig['blind_review']) : '—'}</dd></div>
                <div><dt>{t('benchmark.contextStrategy')}</dt><dd>{selectedComparison.contextStrategy ?? '—'}</dd></div>
                <div><dt>{t('benchmark.manifestVersion')}</dt><dd>{selectedComparison.manifestSchemaVersion ?? '—'}</dd></div>
                <div><dt>{t('benchmark.tokenEstimator')}</dt><dd>{selectedComparison.tokenEstimator ?? '—'}</dd></div>
                <div><dt>{t('benchmark.packetRevision')}</dt><dd>{selectedComparison.packetRevision ?? '—'}</dd></div>
                <div><dt>{t('benchmark.sourceRevision')}</dt><dd>{selectedComparison.sourceRevision ?? '—'}</dd></div>
                <div><dt>{t('benchmark.estimatedTokens')}</dt><dd>{formatTokens(selectedManifest['estimated_tokens'])}</dd></div>
                <div><dt>{t('benchmark.characters')}</dt><dd>{Array.isArray(selectedContext['characters']) ? selectedContext['characters'].map(text).join(', ') : '—'}</dd></div>
              </dl>
              {!selectedComparison.basisComplete && <div className={css.benchmarkLegacy}>{t('benchmark.comparisonIncomplete')}</div>}
              {selectedSources.length > 0 && <details className={css.benchmarkSources}>
                <summary>{t('benchmark.contextSources')} · {selectedSources.length}</summary>
                <ul>{selectedSources.map(source => <li key={`${source.path}:${source.revision}`}>
                  <strong>{source.path}</strong><span>{source.section || '—'} · {source.revision || '—'} · {source.exists === null ? '—' : source.exists ? t('benchmark.sourcePresent') : t('benchmark.sourceMissing')}</span>
                </li>)}</ul>
              </details>}
            </details>
          </>}
        </div>
      </div>
    </div>
  </div>
}
