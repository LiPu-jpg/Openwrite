import { useCallback, useEffect, useMemo, useState } from 'react'
import { Play, RefreshCw } from 'lucide-react'
import type { ConvViewProps } from '@deepseek-ai/dsh-client-ui-conversation/client'
import type { InjectFace, PropsLocale } from '@deepseek-ai/dsh-client-ui-slots'
import type { StudioApiInjected } from './api.ts'
import { asFiniteNumber as optionalNumber, asInteger as number, asRecord as record, asText as text, parseModelProfiles, parseRouteMap, unwrapData as data, type JsonRecord as RecordValue, type ModelProfileDto } from './dto.ts'
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
  executionMode: string
  summary: RecordValue
}

type BenchmarkViewProps = ConvViewProps & InjectFace<StudioApiInjected> & PropsLocale<'studio-panel'>


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

function parseRuns(value: unknown): BenchmarkRun[] {
  const root = data(value)
  return (Array.isArray(root['runs']) ? root['runs'] : []).map(raw => {
    const item = record(raw)
    return {
      runId: text(item['run_id']), status: text(item['status']), chapterId: text(item['chapter_id']),
      createdAt: text(item['created_at']), contextHash: text(item['context_hash']),
      candidateCount: number(item['candidate_count']), evaluationCount: number(item['evaluation_count']),
      executionMode: text(item['execution_mode']) || 'creative',
      summary: record(item['summary']),
    }
  })
}

export function BenchmarkView({ fetchStudioApi, postStudioApi, t }: BenchmarkViewProps) {
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
  const [error, setError] = useState('')

  const load = useCallback(async () => {
    setError('')
    try {
      const [profilesValue, runsValue] = await Promise.all([
        fetchStudioApi('/model/profiles'), fetchStudioApi('/benchmarks?limit=30'),
      ])
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
      setError(cause instanceof Error ? cause.message : String(cause))
    }
  }, [fetchStudioApi])

  useEffect(() => { void load() }, [load])

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
        if (['completed', 'failed', 'cancelled', 'interrupted'].includes(status)) {
          setActiveTask('')
          await load()
        }
      } catch (cause: unknown) {
        if (active) setError(cause instanceof Error ? cause.message : String(cause))
      }
    }
    void poll()
    const timer = window.setInterval(() => { void poll() }, 1500)
    return () => { active = false; window.clearInterval(timer) }
  }, [activeTask, fetchStudioApi, load])

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
    } catch (cause: unknown) {
      setError(cause instanceof Error ? cause.message : String(cause))
    }
  }

  const openRun = async (runId: string) => {
    try { setSelected(data(await fetchStudioApi(`/benchmarks/${encodeURIComponent(runId)}`))) }
    catch (cause: unknown) { setError(cause instanceof Error ? cause.message : String(cause)) }
  }

  const evaluations = useMemo(() => selected !== null && Array.isArray(selected['evaluations']) ? selected['evaluations'].map(record) : [], [selected])
  const candidates = useMemo(() => selected !== null && Array.isArray(selected['candidates']) ? selected['candidates'].map(record) : [], [selected])
  const candidatesById = useMemo(() => new Map(candidates.map(item => [text(item['candidate_id']), item])), [candidates])
  const selectedConfig = useMemo(() => record(selected?.['config']), [selected])
  const selectedSummary = useMemo(() => record(selected?.['summary']), [selected])

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

  return <div className={css.root}>
    <div className={css.toolbar}>
      <span className={css.toolbarMeta}>{taskStatus !== '' ? `${t('benchmark.task')} · ${taskStatus}` : t('benchmark.title')}</span>
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
          {runs.map(run => <button key={run.runId} type="button" className={css.benchmarkRun}
            data-active={selected?.['run_id'] === run.runId} onClick={() => void openRun(run.runId)}>
            <strong>{run.chapterId} · {run.status}</strong>
            <span>{t(`benchmark.mode.${run.executionMode === 'framework' ? 'framework' : 'creative'}`)} · {run.candidateCount} × {run.evaluationCount} · {number(run.summary['average_quality_score']) || '—'}</span>
            <small>{run.createdAt.slice(0, 16).replace('T', ' ')} · {run.contextHash.slice(0, 18)}</small>
          </button>)}
        </div>
        <div className={css.benchmarkResults}>
          {selected === null ? <div className={css.notice}>{t('benchmark.select')}</div> : <>
            <div className={css.benchmarkSummary}>
              <strong>{text(selected['run_id'])}</strong>
              <span>{t(`benchmark.mode.${text(selectedConfig['execution_mode']) === 'framework' ? 'framework' : 'creative'}`)} · {text(selected['status'])} · {text(selected['context_hash']).slice(0, 24)}</span>
            </div>
            <div className={css.benchmarkMetrics}>
              <div><span>{t('benchmark.inputTokens')}</span><strong>{formatTokens(selectedSummary['prompt_tokens'])}</strong></div>
              <div><span>{t('benchmark.outputTokens')}</span><strong>{formatTokens(selectedSummary['completion_tokens'])}</strong></div>
              <div><span>{t('benchmark.reasoningTokens')}</span><strong>{formatTokens(selectedSummary['reasoning_tokens'])}</strong></div>
              <div><span>{t('benchmark.actualCost')}</span><strong>{number(selectedSummary['cost_reported_items']) > 0 ? formatUsd(selectedSummary['total_cost_usd']) : '—'}</strong><small>{t('benchmark.costCoverage')} {number(selectedSummary['cost_item_count']) > 0 ? `${number(selectedSummary['cost_reported_items'])}/${number(selectedSummary['cost_item_count'])}` : '—'}</small></div>
            </div>
            <section className={css.benchmarkSection}>
              <h3>{t('benchmark.candidates')}</h3>
              <div className={css.tableScroll}><table className={css.benchmarkTable} aria-label={t('benchmark.candidates')}>
                <thead><tr><th>{t('benchmark.writer')}</th><th>{t('benchmark.path')}</th><th>{t('benchmark.status')}</th><th>{t('benchmark.actualWords')}</th><th>{t('benchmark.finishReason')}</th><th>{t('benchmark.error')}</th><th>{t('benchmark.usage')}</th><th>{t('benchmark.cost')}</th><th>{t('benchmark.latency')}</th></tr></thead>
                <tbody>{candidates.map(item => {
                  const writerProfile = record(item['writer_profile'])
                  const candidateError = record(item['error'])
                  const framework = record(item['framework'])
                  const reliability = text(item['reliability_status'])
                  const mode = text(item['execution_mode']) === 'framework' ? 'framework' : 'creative'
                  const writeEntrypoint = text(framework['write_entrypoint']) || (mode === 'framework' ? 'execute_write_chapter' : 'WriterAgent._creative_write')
                  return <tr key={text(item['candidate_id'])}>
                    <td><span className={css.benchmarkCellStack}><strong>{text(writerProfile['label'] || writerProfile['id'])}</strong><small>{text(writerProfile['provider'])} · {text(writerProfile['model'])}</small></span></td>
                    <td><span className={css.benchmarkCellStack}><strong>{t(`benchmark.mode.${mode}`)}</strong><small>{writeEntrypoint}</small>{text(framework['run_id_v2']) !== '' && <small>{text(framework['run_id_v2'])}</small>}</span></td>
                    <td><span className={css.benchmarkStatus} data-status={reliability}>{reliability || '—'}</span></td>
                    <td>{number(item['word_count']) || '—'}</td><td>{text(item['finish_reason']) || '—'}</td>
                    <td>{text(candidateError['code']) || '—'}</td><td>{usageCell(item)}</td><td>{costCell(item)}</td><td>{number(item['latency_ms'])} ms</td>
                  </tr>
                })}</tbody>
              </table></div>
            </section>
            <section className={css.benchmarkSection}>
              <h3>{t('benchmark.evaluations')}</h3>
              {evaluations.length === 0 ? <div className={css.notice}>—</div> : <div className={css.tableScroll}><table className={css.benchmarkTable} aria-label={t('benchmark.evaluations')}>
                <thead><tr><th>{t('benchmark.candidate')}</th><th>{t('benchmark.reviewer')}</th><th>{t('benchmark.status')}</th><th>{t('review.score')}</th><th>{t('benchmark.coverage')}</th><th>{t('benchmark.gate')}</th><th>{t('benchmark.delivery')}</th><th>{t('benchmark.productionGate')}</th><th>{t('benchmark.usage')}</th><th>{t('benchmark.cost')}</th><th>{t('benchmark.latency')}</th></tr></thead>
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
                    <td>{text(item['quality_score']) || '—'}</td>
                    <td>{typeof item['coverage'] === 'number' ? `${Math.round(item['coverage'] * 100)}%` : '—'}</td>
                    <td>{text(item['gate_status']) || '—'}</td>
                    <td>{text(item['delivery_status']) || '—'}</td>
                    <td>{text(item['production_gate_status']) || t('benchmark.productionGateMissing')}</td>
                    <td>{usageCell(item)}</td>
                    <td>{costCell(item)}</td>
                    <td>{number(item['latency_ms'])} ms</td>
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
