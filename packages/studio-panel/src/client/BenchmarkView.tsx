import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Play, RefreshCw } from 'lucide-react'
import type { ConvViewProps } from '@deepseek-ai/dsh-client-ui-conversation/client'
import type { InjectFace, PropsLocale } from '@deepseek-ai/dsh-client-ui-slots'
import type { StudioApiInjected } from './api.ts'
import { asFiniteNumber as optionalNumber, asInteger as number, asRecord as record, asText as text, parseModelProfiles, parseResultRef, parseRouteMap, parseTaskProgress, unwrapData as data, type JsonRecord as RecordValue, type ModelProfileDto, type TaskProgressDto } from './dto.ts'
import css from './views.module.css'

type ModelProfile = ModelProfileDto

interface BenchmarkRun {
  runId: string
  status: string
  chapterId: string
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

function parseRuns(value: unknown): BenchmarkRun[] {
  const root = data(value)
  return (Array.isArray(root['runs']) ? root['runs'] : []).map(raw => {
    const item = record(raw)
    const runId = text(item['run_id'])
    const comparison = parseComparison(item['comparison'], runId)
    return {
      runId, status: text(item['status']), chapterId: text(item['chapter_id']),
      createdAt: text(item['created_at']), contextHash: text(item['context_hash']),
      candidateCount: number(item['candidate_count']), evaluationCount: number(item['evaluation_count']),
      executionMode: nullableText(item['execution_mode']),
      promptVersion: nullableText(item['prompt_version']), rubricVersion: nullableText(item['rubric_version']),
      comparison,
      summary: record(item['summary']),
    }
  })
}

export function BenchmarkView({ fetchStudioApi, postStudioApi, t, initialRunId = '' }: BenchmarkViewProps) {
  const [profiles, setProfiles] = useState<ModelProfile[]>([])
  const [writers, setWriters] = useState<Set<string>>(new Set())
  const [reviewers, setReviewers] = useState<Set<string>>(new Set())
  const [chapter, setChapter] = useState('next')
  const [repeats, setRepeats] = useState(1)
  const [targetWords, setTargetWords] = useState(3000)
  const [concurrency, setConcurrency] = useState(1)
  const [executionMode, setExecutionMode] = useState<'framework' | 'creative'>('framework')
  const [runs, setRuns] = useState<BenchmarkRun[]>([])
  const [selected, setSelected] = useState<RecordValue | null>(null)
  const [activeTask, setActiveTask] = useState('')
  const [taskStatus, setTaskStatus] = useState('')
  const [taskPhase, setTaskPhase] = useState('')
  const [taskProgress, setTaskProgress] = useState<TaskProgressDto | null>(null)
  const [error, setError] = useState('')
  // Late responses must never setState after unmount (epoch remount) — one flag.
  const mounted = useRef(true)
  useEffect(() => () => { mounted.current = false }, [])

  const load = useCallback(async () => {
    setError('')
    try {
      const [profilesValue, runsValue] = await Promise.all([
        fetchStudioApi('/model/profiles'), fetchStudioApi('/benchmarks?limit=30'),
      ])
      if (!mounted.current) return
      const parsedProfiles = parseModelProfiles(profilesValue).filter(item => item.configured)
      setProfiles(parsedProfiles)
      const routes = parseRouteMap(profilesValue)
      setWriters(previous => previous.size > 0 ? previous : new Set([text(routes['chapter_write'])].filter(Boolean)))
      setReviewers(previous => {
        if (previous.size > 0) return previous
        const routeReviewer = text(routes['review']) || parsedProfiles[0]?.id
        return routeReviewer ? new Set([routeReviewer]) : new Set<string>()
      })
      setRuns(parseRuns(runsValue))
    } catch (cause: unknown) {
      if (mounted.current) setError(cause instanceof Error ? cause.message : String(cause))
    }
  }, [fetchStudioApi])

  useEffect(() => { void load() }, [load])

  const openRun = useCallback(async (runId: string) => {
    try {
      const detail = data(await fetchStudioApi(`/benchmarks/${encodeURIComponent(runId)}`))
      if (mounted.current) setSelected(detail)
    } catch (cause: unknown) {
      if (mounted.current) setError(cause instanceof Error ? cause.message : String(cause))
    }
  }, [fetchStudioApi])

  // Task result links name an immutable run and take precedence over the newest
  // list item, which might belong to another run or fall outside the list limit.
  useEffect(() => {
    if (initialRunId !== '' && selected?.['run_id'] !== initialRunId) {
      void openRun(initialRunId)
      return
    }
    const latest = runs[0]
    if (selected === null && latest !== undefined) void openRun(latest.runId)
  }, [initialRunId, openRun, runs, selected])

  useEffect(() => {
    if (activeTask === '') return
    let active = true
    const poll = async () => {
      try {
        const response = data(await fetchStudioApi(`/tasks/${encodeURIComponent(activeTask)}`))
        const task = record(response['task'])
        if (!active) return
        const status = text(task['status'])
        setTaskStatus(status)
        setTaskPhase(text(task['phase']))
        setTaskProgress(parseTaskProgress(task['progress']))
        if (['completed', 'failed', 'cancelled', 'interrupted'].includes(status)) {
          setActiveTask('')
          // M1c: a finished benchmark task points at its run via result_ref.
          const ref = parseResultRef(task['result_ref'])
          if (ref?.type === 'benchmark_run') void openRun(ref.id)
          await load()
        }
      } catch (cause: unknown) {
        if (active) setError(cause instanceof Error ? cause.message : String(cause))
      }
    }
    void poll()
    const timer = window.setInterval(() => { void poll() }, 1500)
    return () => { active = false; window.clearInterval(timer) }
  }, [activeTask, fetchStudioApi, load, openRun])

  const submit = async () => {
    if (writers.size === 0 || reviewers.size === 0 || activeTask !== '') return
    setError('')
    try {
      const response = data(await postStudioApi('/benchmarks', {
        chapter_id: chapter.trim() || 'next', writer_profile_ids: [...writers], reviewer_profile_ids: [...reviewers],
        execution_mode: executionMode, repeats, target_words: targetWords, concurrency,
      }))
      const taskId = text(response['task_id'])
      setActiveTask(taskId)
      setTaskStatus(text(response['status']) || 'pending')
      setTaskPhase('')
      setTaskProgress(null)
    } catch (cause: unknown) {
      setError(cause instanceof Error ? cause.message : String(cause))
    }
  }

  const evaluations = useMemo(() => selected !== null && Array.isArray(selected['evaluations']) ? selected['evaluations'].map(record) : [], [selected])
  const candidates = useMemo(() => selected !== null && Array.isArray(selected['candidates']) ? selected['candidates'].map(record) : [], [selected])
  const candidatesById = useMemo(() => new Map(candidates.map(item => [text(item['candidate_id']), item])), [candidates])
  const selectedConfig = useMemo(() => record(selected?.['config']), [selected])
  const selectedSummary = useMemo(() => record(selected?.['summary']), [selected])
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
    return <span className={css.benchmarkError}>{[code, message].filter(Boolean).join(' · ')}</span>
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

  // Real unit progress only (e.g. "5/10 candidates") — never a fabricated percent.
  const taskMeta = taskStatus === '' ? t('benchmark.title') : [
    `${t('benchmark.task')} · ${taskStatus}`,
    taskPhase === '' ? '' : phaseLabel(taskPhase),
    taskProgress === null ? '' : `${taskProgress.completed_units}/${taskProgress.total_units} ${taskProgress.unit_kind === 'evaluations' ? t('benchmark.evaluations') : t('benchmark.candidates')}`,
  ].filter(part => part !== '').join(' · ')

  return <div className={css.root}>
    <div className={css.toolbar}>
      <span className={css.toolbarMeta}>{taskMeta}</span>
      <button type="button" className={css.button} title={t('refresh')} onClick={() => void load()}><RefreshCw size={14} /></button>
    </div>
    <div className={css.body}>
      <section className={css.benchmarkControls}>
        <div className={css.benchmarkProfiles}>
          {profiles.map(profile => <label key={profile.id} className={css.profileChoice}>
            <input type="checkbox" checked={writers.has(profile.id)} onChange={() => setWriters(previous => {
              const next = new Set(previous); if (next.has(profile.id)) next.delete(profile.id); else next.add(profile.id); return next
            })} />
            <span>{profile.label}<small>{profile.provider} · {profile.model}</small></span>
          </label>)}
        </div>
        <div className={css.benchmarkInputs}>
          <label>{t('benchmark.mode')}<select value={executionMode} onChange={event => setExecutionMode(event.target.value as 'framework' | 'creative')}>
            <option value="framework">{t('benchmark.mode.framework')}</option>
            <option value="creative">{t('benchmark.mode.creative')}</option>
          </select></label>
          <label>{t('benchmark.reviewer')}<select multiple size={Math.min(4, Math.max(2, profiles.length))} value={[...reviewers]} onChange={event => setReviewers(new Set(Array.from(event.target.selectedOptions, option => option.value)))}>
            {profiles.map(profile => <option key={profile.id} value={profile.id}>{profile.label} · {profile.provider} · {profile.model}</option>)}
          </select></label>
          <label>{t('benchmark.chapter')}<input value={chapter} onChange={event => setChapter(event.target.value)} /></label>
          <label>{t('benchmark.repeats')}<input type="number" min={1} max={5} value={repeats} onChange={event => setRepeats(Math.max(1, Math.min(5, Number(event.target.value))))} /></label>
          <label>{t('benchmark.words')}<input type="number" min={200} max={12000} step={100} value={targetWords} onChange={event => setTargetWords(Math.max(200, Math.min(12000, Number(event.target.value))))} /></label>
          <label>{t('benchmark.concurrency')}<input type="number" min={1} max={4} value={concurrency} onChange={event => setConcurrency(Math.max(1, Math.min(4, Number(event.target.value))))} /></label>
          <button type="button" className={css.button} disabled={writers.size === 0 || reviewers.size === 0 || activeTask !== ''} onClick={() => void submit()}>
            <Play size={14} /> {t('benchmark.run')}
          </button>
        </div>
      </section>
      {error !== '' && <div className={css.taskError}>{error}</div>}
      <div className={css.benchmarkSplit}>
        <div className={css.benchmarkRuns}>
          {runs.length === 0 && <div className={css.notice}>{t('benchmark.empty')}</div>}
          {runGroups.map(group => <section key={group.comparison.key} className={css.benchmarkRunGroup} data-testid="benchmark-comparison-group">
            <div className={css.benchmarkRunGroupHeader}>
              <strong>{t('benchmark.sameInputGroup')} · {group.runs.length} {t('benchmark.runs')}</strong>
              <span>{group.comparison.promptVersion ?? '—'} · {group.comparison.rubricVersion ?? '—'}</span>
              <small>{group.comparison.contextHash ?? '—'} · {group.comparison.contextStrategy ?? '—'} · {group.comparison.tokenEstimator ?? '—'}</small>
              {!group.comparison.basisComplete && <small className={css.benchmarkLegacy}>{t('benchmark.comparisonIncomplete')}</small>}
            </div>
            {group.runs.map(run => <button key={run.runId} type="button" className={css.benchmarkRun}
              data-active={selected?.['run_id'] === run.runId} onClick={() => void openRun(run.runId)}>
              <strong>{run.chapterId} · {run.status}</strong>
              <span>{modeLabel(run.executionMode)} · {run.candidateCount} × {run.evaluationCount} · {numberOrDash(run.summary['average_quality_score'])}</span>
              <small>{run.runId}</small>
              <small>{run.createdAt.slice(0, 16).replace('T', ' ')} · {run.contextHash.slice(0, 18)}</small>
            </button>)}
          </section>)}
        </div>
        <div className={css.benchmarkResults}>
          {selected === null ? <div className={css.notice}>{t('benchmark.select')}</div> : <>
            <div className={css.benchmarkSummary}>
              <strong>{text(selected['run_id'])}</strong>
              <span data-testid="benchmark-selected-mode">{modeLabel(selectedMode)} · {text(selected['status'])}</span>
            </div>
            <div className={css.benchmarkMetrics}>
              <div><span>{t('benchmark.averageScore')}</span><strong>{optionalNumber(selectedSummary['average_quality_score']) === null ? '—' : String(optionalNumber(selectedSummary['average_quality_score']))}</strong></div>
              <div><span>{t('benchmark.inputTokens')}</span><strong>{formatTokens(selectedSummary['prompt_tokens'])}</strong></div>
              <div><span>{t('benchmark.outputTokens')}</span><strong>{formatTokens(selectedSummary['completion_tokens'])}</strong></div>
              <div><span>{t('benchmark.reasoningTokens')}</span><strong>{formatTokens(selectedSummary['reasoning_tokens'])}</strong></div>
              <div><span>{t('benchmark.actualCost')}</span><strong>{number(selectedSummary['cost_reported_items']) > 0 ? formatUsd(selectedSummary['total_cost_usd']) : '—'}</strong><small>{t('benchmark.costCoverage')} {number(selectedSummary['cost_item_count']) > 0 ? `${number(selectedSummary['cost_reported_items'])}/${number(selectedSummary['cost_item_count'])}` : '—'}</small></div>
            </div>
            <section className={css.benchmarkSection} data-testid="benchmark-run-phases">
              <h3>{t('benchmark.runPhases')}</h3>
              <ol className={css.benchmarkPhases}>
                <li><span>{t('benchmark.phase.created')}</span><strong>{valueOrDash(selected['created_at'])}</strong></li>
                <li><span>{t('benchmark.phase.started')}</span><strong>{valueOrDash(selected['started_at'])}</strong></li>
                <li><span>{t('benchmark.candidates')}</span><strong>{numberOrDash(selectedSummary['completed_candidates'])}/{numberOrDash(selectedSummary['requested_candidates'])} {t('benchmark.candidates')}</strong></li>
                <li><span>{t('benchmark.evaluations')}</span><strong>{numberOrDash(selectedSummary['completed_evaluations'])}/{numberOrDash(selectedSummary['requested_evaluations'])} {t('benchmark.evaluations')}</strong></li>
                <li><span>{t('benchmark.phase.completed')}</span><strong>{valueOrDash(selected['completed_at'])}</strong></li>
              </ol>
            </section>
            <section className={css.benchmarkSection} data-testid="benchmark-provenance">
              <h3>{t('benchmark.inputProvenance')}</h3>
              <dl className={css.benchmarkProvenance}>
                <div><dt>{t('benchmark.contextHash')}</dt><dd>{valueOrDash(selected['context_hash'])}</dd></div>
                <div><dt>{t('benchmark.comparisonKey')}</dt><dd>{selectedComparison.key}</dd></div>
                <div><dt>{t('benchmark.promptVersion')}</dt><dd>{valueOrDash(selected['prompt_version'])}</dd></div>
                <div><dt>{t('benchmark.rubricVersion')}</dt><dd>{valueOrDash(selected['rubric_version'])}</dd></div>
                <div><dt>{t('benchmark.mode')}</dt><dd>{modeLabel(selectedMode)}</dd></div>
                <div><dt>{t('benchmark.words')}</dt><dd>{numberOrDash(selectedConfig['target_words'] ?? selectedContext['target_words'])}</dd></div>
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
            </section>
            <section className={css.benchmarkSection}>
              <h3>{t('benchmark.candidates')}</h3>
              <div className={css.tableScroll}><table className={css.benchmarkTable} aria-label={t('benchmark.candidates')}>
                <thead><tr><th>{t('benchmark.writer')}</th><th>{t('benchmark.path')}</th><th>{t('benchmark.status')}</th><th>{t('benchmark.actualWords')}</th><th>{t('benchmark.finishReason')}</th><th>{t('benchmark.error')}</th><th>{t('benchmark.usage')}</th><th>{t('benchmark.cost')}</th><th>{t('benchmark.latency')}</th></tr></thead>
                <tbody>{candidates.map(item => {
                  const writerProfile = record(item['writer_profile'])
                  const framework = record(item['framework'])
                  const reliability = text(item['reliability_status'])
                  const mode = nullableText(item['execution_mode']) ?? selectedMode
                  const writeEntrypoint = text(framework['write_entrypoint']) || (mode === 'framework' ? 'execute_write_chapter' : mode === 'creative' ? 'WriterAgent._creative_write' : '')
                  const responseIdentity = [text(item['response_provider']), text(item['response_model'])].filter(Boolean).join(' · ')
                  return <tr key={text(item['candidate_id'])}>
                    <td><span className={css.benchmarkCellStack}><strong>{text(writerProfile['label'] || writerProfile['id']) || '—'}</strong><small>{[text(writerProfile['provider']), text(writerProfile['model'])].filter(Boolean).join(' · ') || '—'}</small>{responseIdentity !== '' && <small>{t('benchmark.responseIdentity')} · {responseIdentity}</small>}</span></td>
                    <td><span className={css.benchmarkCellStack}><strong>{modeLabel(mode)}</strong>{writeEntrypoint !== '' && <small>{writeEntrypoint}</small>}{text(framework['run_id_v2']) !== '' && <small>{text(framework['run_id_v2'])}</small>}</span></td>
                    <td><span className={css.benchmarkStatus} data-status={reliability}>{reliability || '—'}</span></td>
                    <td>{numberOrDash(item['word_count'])}</td><td>{text(item['finish_reason']) || '—'}</td>
                    <td>{errorCell(item)}</td><td>{usageCell(item)}</td><td>{costCell(item)}</td>{latencyCell(item)}
                  </tr>
                })}</tbody>
              </table></div>
            </section>
            <section className={css.benchmarkSection}>
              <h3>{t('benchmark.output')}</h3>
              <div className={css.benchmarkOutputList}>
                {candidates.map(item => {
                  const content = typeof item['content'] === 'string' ? item['content'] : ''
                  const artifact = text(record(item['content'])['$artifact'])
                  return <details key={`output-${text(item['candidate_id'])}`} className={css.benchmarkOutput} open={candidates.length === 1}>
                    <summary>{text(item['title']) || text(item['candidate_id'])} · {numberOrDash(item['word_count'])} {t('benchmark.actualWords')}</summary>
                    {content !== '' ? <pre>{content}</pre> : artifact !== '' ? <p>{artifact}</p> : <p>—</p>}
                  </details>
                })}
              </div>
            </section>
            <section className={css.benchmarkSection}>
              <h3>{t('benchmark.evaluations')}</h3>
              {evaluations.length === 0 ? <div className={css.notice}>—</div> : <div className={css.tableScroll}><table className={css.benchmarkTable} aria-label={t('benchmark.evaluations')}>
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
                    <td><span className={css.benchmarkCellStack}><span className={css.benchmarkStatus} data-status={execution}>{execution || '—'}</span>{text(framework['review_entrypoint']) !== '' && <small>{text(framework['review_entrypoint'])}</small>}{incompleteDomains.length > 0 && <small>{t('benchmark.domains')}: {incompleteDomains.join(', ')}</small>}</span></td>
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
          </>}
        </div>
      </div>
    </div>
  </div>
}
