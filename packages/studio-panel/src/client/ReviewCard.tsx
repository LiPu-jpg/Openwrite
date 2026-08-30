/**
 * novel_review_chapter toolview: the OpenWrite multi-dimensional chapter
 * review as a readable report card. Registrant posture over the keyed
 * tool.call.toolview hole — imports the slot contract only, never the chat
 * domain (the bash-sample.tsx pattern).
 *
 * Wire shape (verified against OpenWrite tools/chapter_pipeline.py review
 * stage + tools/review_store.py normalize_review_issues): the tool value is
 * { result: { ok, chapter_id, passed, score, review_v2, issues: <count int>,
 * summary, issue_details: [...], strict, dimensions, ... }, workspace: {...} }.
 * Review v2 is authoritative for quality score, coverage, gate, and delivery.
 * Issue review severity (critical/warning/info) is independent from revision
 * priority (blocker/high/medium/low).
 *
 * Anything unexpected (running call, non-JSON output, missing fields) falls
 * back to the raw pretty-JSON card — the review text is never swallowed.
 */

import { useState, type KeyboardEvent } from 'react'
import { MarkdownText } from '@deepseek-ai/dsh-client-ui-primitives'
import type { ToolCallViewProps } from '@deepseek-ai/dsh-client-ui-tool/client'
import type { PropsLocale } from '@deepseek-ai/dsh-client-ui-slots'
import type { ToolResultNode } from '@deepseek-ai/dsh-client-runtime/client'
import css from './ReviewCard.module.css'

/** Review card props: the toolview runtime share plus the standard locale seat. */
type ReviewCardProps = ToolCallViewProps & PropsLocale<'studio-panel'>

interface ReviewIssue {
  id: string
  dimension: number | null
  reviewSeverity: 'critical' | 'warning' | 'info'
  revisionPriority: 'blocker' | 'high' | 'medium' | 'low'
  summary: string
  category: string
  quote: string
  suggestion: string
}

interface ReviewReport {
  chapterId: string
  passed: boolean
  qualityScore: number | null
  coverage: number | null
  executionStatus: string
  gateStatus: string
  deliveryStatus: string
  issueCount: number
  summary: string
  issues: ReviewIssue[]
}

const REVIEW_SEVERITIES = ['critical', 'warning', 'info'] as const
const REVISION_PRIORITIES = ['blocker', 'high', 'medium', 'low'] as const

/** Flatten a settled result's content blocks to text (the tool-call-model resultText rule). */
function resultText(node: ToolResultNode): string {
  const parts: string[] = []
  for (const block of node.content) {
    if (block.type === 'text') parts.push(block.text)
    else parts.push(JSON.stringify(block, null, 2))
  }
  return parts.join('\n')
}

/** Parse the tool output text into a report; null when the shape is not a review result. */
function parseReport(text: string): ReviewReport | null {
  let data: unknown
  try {
    data = JSON.parse(text)
  } catch {
    return null
  }
  if (data === null || typeof data !== 'object') return null
  const outer = data as Record<string, unknown>
  const result = (outer['result'] !== null && typeof outer['result'] === 'object' ? outer['result'] : outer) as Record<string, unknown>
  const text2 = (value: unknown): string => (typeof value === 'string' ? value : '')
  const v2 = (result['review_v2'] !== null && typeof result['review_v2'] === 'object' && !Array.isArray(result['review_v2'])
    ? result['review_v2'] : {}) as Record<string, unknown>
  const qualityScore = typeof v2['quality_score'] === 'number'
    ? v2['quality_score']
    : typeof result['score'] === 'number' ? result['score'] : null
  const deliveryStatus = text2(v2['delivery_status'])
  if (typeof result['passed'] !== 'boolean' && qualityScore === null && deliveryStatus === '') return null
  const issueList = Array.isArray(result['issue_details']) ? result['issue_details'] : []
  const issues: ReviewIssue[] = []
  for (const raw of issueList) {
    if (raw === null || typeof raw !== 'object') continue
    const item = raw as Record<string, unknown>
    const evidence = (item['evidence'] !== null && typeof item['evidence'] === 'object' ? item['evidence'] : {}) as Record<string, unknown>
    const rawSeverity = text2(item['review_severity'] ?? item['legacy_severity'] ?? item['severity']).toLowerCase()
    const reviewSeverity = rawSeverity === 'critical' || rawSeverity === 'blocker'
      ? 'critical'
      : rawSeverity === 'info' || rawSeverity === 'low' ? 'info' : 'warning'
    const rawPriority = text2(item['revision_priority']).toLowerCase()
    const revisionPriority = (REVISION_PRIORITIES as readonly string[]).includes(rawPriority)
      ? rawPriority as ReviewIssue['revisionPriority']
      : rawSeverity === 'critical' || rawSeverity === 'blocker'
        ? 'blocker'
        : rawSeverity === 'high' ? 'high' : rawSeverity === 'info' || rawSeverity === 'low' ? 'low' : 'medium'
    issues.push({
      id: text2(item['id']) || `issue_${String(issues.length)}`,
      dimension: typeof item['dimension'] === 'number' ? item['dimension'] : null,
      reviewSeverity: (REVIEW_SEVERITIES as readonly string[]).includes(reviewSeverity) ? reviewSeverity : 'warning',
      revisionPriority,
      // normalize_review_issues folds description into summary; keep both fallbacks.
      summary: text2(item['summary']) || text2(item['description']),
      category: text2(item['category']),
      quote: text2(evidence['quote']) || text2(item['quote']),
      suggestion: text2(item['suggestion']),
    })
  }
  return {
    chapterId: text2(result['chapter_id']),
    passed: deliveryStatus !== '' ? deliveryStatus === 'pass' : result['passed'] === true,
    qualityScore,
    coverage: typeof v2['coverage'] === 'number' ? v2['coverage'] : null,
    executionStatus: text2(v2['execution_status']),
    gateStatus: text2(v2['gate_status']),
    deliveryStatus: deliveryStatus || (result['passed'] === true ? 'pass' : 'revise'),
    // `issues` on the wire is a COUNT, not the array (that is issue_details).
    issueCount: typeof result['issues'] === 'number' ? result['issues'] : issues.length,
    summary: text2(result['summary']),
    issues,
  }
}

/** Group issues by category, preserving first-seen order ('' groups last as 未分类/general). */
function groupByCategory(issues: readonly ReviewIssue[]): { category: string; items: ReviewIssue[] }[] {
  const groups: { category: string; items: ReviewIssue[] }[] = []
  for (const issue of issues) {
    const key = issue.category
    const group = groups.find(entry => entry.category === key)
    if (group !== undefined) group.items.push(issue)
    else groups.push({ category: key, items: [issue] })
  }
  return groups
}

/**
 * The review card: collapsed summary row (tool · chapter · score · verdict)
 * toggling the expanded report — verdict banner, summary, then issue groups
 * with severity badges, quotes, and suggestions.
 */
export function NovelReviewCard({ block, t }: ReviewCardProps) {
  const [expanded, setExpanded] = useState(false)
  const running = !('kind' in block)
  const rawText = running ? '' : resultText(block)
  const report = running ? null : parseReport(rawText)
  const isError = !running && block.isError

  const toggle = () => { setExpanded(value => !value) }
  const toggleFromKeyboard = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.key !== 'Enter' && event.key !== ' ') return
    event.preventDefault()
    toggle()
  }

  const statusLabel = (status: string): string => {
    switch (status) {
      case 'pass': return t('review.status.pass')
      case 'blocked': return t('review.status.blocked')
      case 'inconclusive': return t('review.status.inconclusive')
      case 'revise': return t('review.status.revise')
      case 'completed': return t('review.status.completed')
      case 'partial': return t('review.status.partial')
      case 'failed': return t('review.status.failed')
      case 'stale': return t('review.status.stale')
      default: return status || t('review.status.unknown')
    }
  }

  const summaryLine = running
    ? t('review.running')
    : report !== null
      ? [
        report.chapterId,
        report.qualityScore !== null ? `${t('review.score')} ${String(report.qualityScore)}` : '',
        report.coverage !== null ? `${t('review.coverage')} ${Math.round(report.coverage * 100)}%` : '',
        statusLabel(report.deliveryStatus),
      ].filter(part => part !== '').join(' · ')
      : ''

  return (
    <div className={css.card}>
      <div
        className={css.root}
        role="button"
        tabIndex={0}
        aria-expanded={expanded}
        data-state={running ? 'running' : isError ? 'error' : report?.deliveryStatus === 'pass' ? 'ok' : 'error'}
        onClick={toggle}
        onKeyDown={toggleFromKeyboard}
      >
        <span className={css.title}>novel_review_chapter</span>
        <span className={css.sep} aria-hidden />
        <span className={css.summary}>{summaryLine}</span>
      </div>
      {expanded && (
        <div className={css.bodyWrap}>
          {report !== null && (
            <>
              <div className={css.verdictRow}>
                <span className={css.verdict} data-passed={report.passed}>
                  {report.passed ? t('review.passed') : t('review.failed')}
                </span>
                {report.qualityScore !== null && (
                  <span className={css.score}>{t('review.score')} {report.qualityScore}</span>
                )}
                {report.coverage !== null && <span className={css.metric}>{t('review.coverage')} {Math.round(report.coverage * 100)}%</span>}
                {report.gateStatus !== '' && <span className={css.metric}>{t('review.gate')} {statusLabel(report.gateStatus)}</span>}
                {report.executionStatus !== '' && <span className={css.metric}>{t('review.execution')} {statusLabel(report.executionStatus)}</span>}
                <span className={css.issueCount}>{t('review.issues')} {report.issueCount}</span>
              </div>
              {report.summary !== '' && <div className={css.reportSummary}><MarkdownText text={report.summary} /></div>}
              {groupByCategory(report.issues).map(group => (
                <section key={group.category || '_'} className={css.issueGroup}>
                  {group.category !== '' && <h4 className={css.issueGroupTitle}>{group.category}</h4>}
                  {group.items.map(issue => (
                    <div key={issue.id} className={css.issue}>
                      <div className={css.issueHead}>
                        <span className={css.severity} data-severity={issue.reviewSeverity}>
                          {t(`review.severity.${issue.reviewSeverity}`)}
                        </span>
                        <span className={css.priority} data-priority={issue.revisionPriority}>
                          {t('review.priority')} · {t(`review.priority.${issue.revisionPriority}`)}
                        </span>
                        {issue.dimension !== null && (
                          <span className={css.dimension}>{t('review.dimension')} {issue.dimension}</span>
                        )}
                        <span className={css.issueSummary}><MarkdownText text={issue.summary} /></span>
                      </div>
                      {issue.quote !== '' && (
                        <blockquote className={css.quote}><MarkdownText text={issue.quote} /></blockquote>
                      )}
                      {issue.suggestion !== '' && (
                        <div className={css.suggestion}>
                          <span className={css.suggestionLabel}>{t('review.suggestion')}</span>
                          <MarkdownText text={issue.suggestion} />
                        </div>
                      )}
                    </div>
                  ))}
                </section>
              ))}
            </>
          )}
          {report === null && !running && (
            <>
              <div className={css.rawTitle}>{t('review.rawTitle')}</div>
              <pre className={css.rawJson}>{rawText}</pre>
            </>
          )}
        </div>
      )}
    </div>
  )
}
