import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  BookOpen, ChevronLeft, ChevronRight, History, PanelLeft, PanelLeftClose, PanelLeftOpen, PanelRight,
  PanelRightClose, PanelRightOpen, RefreshCw, Save, Search, ShieldAlert, X,
} from 'lucide-react'
import { MarkdownText } from '@deepseek-ai/dsh-client-ui-primitives'
import type { ConvViewProps } from '@deepseek-ai/dsh-client-ui-conversation/client'
import type { InjectFace, PropsLocale } from '@deepseek-ai/dsh-client-ui-slots'
import { StudioApiError, type StudioApiInjected, type StudioContext } from './api.ts'
import {
  MANUSCRIPT_DRAFT_FORMAT_VERSION,
  manuscriptDraftKey,
  manuscriptDraftStore,
  manuscriptNovelId,
  type ManuscriptDraftIdentity,
  type ManuscriptDraftRecord,
} from './draft-store.ts'
import { storageKey } from './storage.ts'
import { loadVditor, VditorBody } from './VditorBody.tsx'
import { useWorkbench, workbenchStore, type ChapterSummary } from './WorkbenchStore.ts'
import { ContinuousReader } from './ContinuousReader.tsx'
import {
  parseChapterWorkBrief, parseReadingOrder,
  type ChapterWorkBriefDto, type ReadingOrderDto,
} from './dto.ts'
import { useBindStudioContext } from './workspace-context.ts'
import type { StudioPanelKey } from './locales.ts'
import css from './Workbench.module.css'

type InspectorTab = 'context' | 'review' | 'revisions' | 'activity'
type LoadState = 'idle' | 'loading' | 'ready' | 'error'

interface DocumentPayload {
  path: string
  title: string
  content: string
  version: string
  revision: string
}

interface SaveRequestSnapshot {
  identity: string
  context: StudioContext
  document: DocumentPayload
  content: string
  force: boolean
  saveOrigin: 'autosave' | 'manual'
  draftIdentity: ManuscriptDraftIdentity | null
}

interface ManuscriptVersion {
  versionId: string
  sourceRevision: string
  reason: string
  label: string
  createdAt: string
  writingUnits: number
}

interface DiffSegment {
  id: string
  tag: string
  before: string
  after: string
}

interface VersionPreview {
  version: ManuscriptVersion
  currentRevision: string
  segments: DiffSegment[]
}

interface RevisionProposal {
  proposalId: string
  status: string
  kind: string
  rationale: string
  originalText: string
  replacementText: string
  start: number
  end: number
  reviewIssueIds: string[]
  reviewRevision: string
  sourceRevision: string
  issueHunkProvenance: { issueId: string; hunkIds: string[] }[]
  hunks: DiffSegment[]
}

interface ContextSection {
  title: string
  markdown: string
}

interface ContextSource {
  path: string
  exists: boolean
  revision: string
  line: number
}

interface ContextManifestItem {
  section: string
  status: string
  estimatedTokens: number
  snippet: string
  selectionReason: string
  compressionReason: string
  protected: boolean
  protectionReason: string
  revision: string
  sources: ContextSource[]
}

interface ContextMissingItem {
  section: string
  reason: string
  protected: boolean
  sources: ContextSource[]
}

interface ContextManifest {
  revision: string
  sourceRevision: string
  freshness: string
  previousFreshness: string
  previousRevision: string
  estimatedTokens: number
  requestBudgetAvailable: boolean
  requestBudgetTokens: number | null
  reservedOutputTokens: number | null
  actualUsageReported: boolean
  sessionBudgetAvailable: boolean
  sessionBudgetReason: string
  retrievalStatus: string
  retrievalReason: string
  retrievalIndexStatus: string
  retrievalResults: number
  retrievalSources: ContextSource[]
  items: ContextManifestItem[]
  missingItems: ContextMissingItem[]
  excludedItems: ContextMissingItem[]
}

interface ContextPayload {
  markdown: string
  manifest: ContextManifest
}

type AcceptanceAction = 'baseline' | 'external' | 'resume' | 'acknowledge'

interface ManuscriptAcceptance {
  chapterId: string
  path: string
  status: string
  currentRevision: string
  acceptedRevision: string
  factsRevision: string
  operationId: string
  source: string
  message: string
  impacts: string[]
  needsReview: boolean
}

function record(value: unknown): Record<string, unknown> {
  return value !== null && typeof value === 'object' ? value as Record<string, unknown> : {}
}

function payloadRecord(value: unknown): Record<string, unknown> {
  const item = record(value)
  return item['data'] !== null && typeof item['data'] === 'object' ? record(item['data']) : item
}

function stringArray(value: unknown): string[] {
  return Array.isArray(value) ? value.map(item => String(item)) : []
}

function firstString(item: Record<string, unknown>, keys: string[]): string {
  for (const key of keys) {
    const value = item[key]
    if (typeof value === 'string' && value !== '') return value
  }
  return ''
}

function impactLabels(value: unknown): string[] {
  if (!Array.isArray(value)) return []
  return value.map(raw => {
    if (typeof raw === 'string') return raw
    const item = record(raw)
    return firstString(item, ['domain', 'resource', 'kind', 'id', 'path', 'reason'])
  }).filter(Boolean)
}

function reviewRequired(value: unknown, selectedChapterId: string): boolean {
  if (value === true) return true
  if (!Array.isArray(value)) return false
  return value.some(raw => {
    if (typeof raw === 'string') return raw === selectedChapterId
    const item = record(raw)
    const sourceChapter = String(item['source_chapter'] ?? item['chapter_id'] ?? item['id'] ?? '')
    if (sourceChapter !== '') return sourceChapter === selectedChapterId
    return String(item['status'] ?? '') === 'needs_review'
  })
}

/** Normalize both the project acceptance surface and task-start responses. */
function parseManuscriptAcceptance(value: unknown, selectedChapterId: string): ManuscriptAcceptance | null {
  const payload = payloadRecord(value)
  const acceptance = record(payload['acceptance'])
  const surface = Object.keys(acceptance).length > 0 ? acceptance : payload
  const chapters = Array.isArray(surface['chapters']) ? surface['chapters'] : []
  const selected = chapters
    .map(record)
    .find(item => String(item['chapter_id'] ?? item['id'] ?? '') === selectedChapterId)
  const chapter = selected ?? (() => {
    const nested = record(surface['chapter'])
    return Object.keys(nested).length > 0 ? nested : surface
  })()
  const chapterId_ = firstString(chapter, ['chapter_id', 'id']) || selectedChapterId
  const chapterStatus = firstString(chapter, ['status', 'state', 'acceptance_status']).trim().toLowerCase().replaceAll('-', '_')
  const surfaceStatus = firstString(surface, ['status', 'state', 'acceptance_status']).trim().toLowerCase().replaceAll('-', '_')
  const rawStatus = chapterStatus || surfaceStatus
  const operation = record(chapter['operation'] ?? surface['operation'] ?? payload['task'])
  const operationId = firstString(chapter, ['operation_id']) ||
    firstString(operation, ['operation_id', 'id']) ||
    firstString(surface, ['latest_operation_id', 'operation_id']) ||
    firstString(payload, ['operation_id'])
  const impacts = impactLabels(chapter['impacts'] ?? chapter['stale_derivatives'] ??
    surface['impacts'] ?? surface['stale_derivatives'])
  const needsReview = reviewRequired(chapter['needs_review'], selectedChapterId) ||
    reviewRequired(surface['needs_review'], selectedChapterId) || surfaceStatus === 'needs_review' || rawStatus === 'needs_review'
  if (rawStatus === '' && chapterId_ === '' && operationId === '' && impacts.length === 0 && !needsReview) return null
  return {
    chapterId: chapterId_,
    path: firstString(chapter, ['path']),
    status: needsReview ? 'needs_review' : rawStatus || 'unknown',
    currentRevision: firstString(chapter, ['current_revision', 'content_revision', 'revision']),
    acceptedRevision: firstString(chapter, ['accepted_revision', 'baseline_revision']),
    factsRevision: firstString(chapter, ['facts_revision']),
    operationId,
    source: firstString(chapter, ['source']),
    message: firstString(chapter, ['message', 'reason']) || firstString(surface, ['message', 'reason']),
    impacts,
    needsReview,
  }
}

function acceptanceStatusKey(status: string): StudioPanelKey {
  if (status === 'current' || status === 'accepted' || status === 'ready') return 'creation.acceptance.current'
  if (status === 'baseline_required' || status === 'baseline_pending' || status === 'untracked' || status === 'missing_baseline') return 'creation.acceptance.baselinePending'
  if (status === 'drift' || status === 'external' || status === 'external_change') return 'creation.acceptance.drift'
  if (status === 'needs_review') return 'creation.acceptance.needsReview'
  if (status === 'failed') return 'creation.acceptance.failed'
  if (status === 'pending' || status === 'running' || status === 'analyzing' || status === 'propagating' || status === 'interrupted') {
    return 'creation.acceptance.pending'
  }
  return 'creation.acceptance.unknown'
}

function parseSegment(value: unknown): DiffSegment {
  const item = record(value)
  return {
    id: String(item['id'] ?? ''),
    tag: String(item['tag'] ?? ''),
    before: String(item['before'] ?? ''),
    after: String(item['after'] ?? ''),
  }
}

function parseVersion(value: unknown): ManuscriptVersion {
  const item = record(value)
  return {
    versionId: String(item['version_id'] ?? ''),
    sourceRevision: String(item['source_revision'] ?? ''),
    reason: String(item['reason'] ?? ''),
    label: String(item['label'] ?? ''),
    createdAt: String(item['created_at'] ?? ''),
    writingUnits: Number(item['writing_units'] ?? 0),
  }
}

function parseVersions(value: unknown): ManuscriptVersion[] {
  const items = payloadRecord(value)['versions']
  return Array.isArray(items) ? items.map(parseVersion).filter(item => item.versionId !== '') : []
}

function parseProposals(value: unknown): RevisionProposal[] {
  const items = payloadRecord(value)['proposals']
  if (!Array.isArray(items)) return []
  return items.map(raw => {
    const item = record(raw)
    const selection = record(item['selection'])
    const diff = record(item['diff'])
    const provenance = Array.isArray(item['issue_hunk_provenance']) ? item['issue_hunk_provenance'] : []
    return {
      proposalId: String(item['proposal_id'] ?? ''),
      status: String(item['status'] ?? ''),
      kind: String(item['kind'] ?? ''),
      rationale: String(item['rationale'] ?? ''),
      originalText: String(selection['original_text'] ?? ''),
      replacementText: String(item['replacement_text'] ?? ''),
      start: Number(selection['start'] ?? 0),
      end: Number(selection['end'] ?? 0),
      reviewIssueIds: stringArray(item['review_issue_ids']),
      reviewRevision: String(item['review_revision'] ?? ''),
      sourceRevision: String(item['source_revision'] ?? ''),
      issueHunkProvenance: provenance.map(rawProvenance => {
        const value = record(rawProvenance)
        return { issueId: String(value['issue_id'] ?? ''), hunkIds: stringArray(value['hunk_ids']) }
      }).filter(value => value.issueId !== ''),
      hunks: Array.isArray(diff['hunks']) ? diff['hunks'].map(parseSegment) : [],
    }
  }).filter(item => item.proposalId !== '')
}

function parseVersionPreview(value: unknown): VersionPreview | null {
  const item = payloadRecord(value)
  const version = parseVersion(item['version'])
  if (version.versionId === '') return null
  const diff = record(item['diff'])
  return {
    version,
    currentRevision: String(record(item['current'])['revision'] ?? ''),
    segments: Array.isArray(diff['segments']) ? diff['segments'].map(parseSegment) : [],
  }
}

function parseDocument(value: unknown): DocumentPayload {
  const item = record(value)
  return {
    path: typeof item['path'] === 'string' ? item['path'] : '',
    title: typeof item['title'] === 'string' ? item['title'] : '',
    content: typeof item['content'] === 'string' ? item['content'] : '',
    version: String(item['version'] ?? ''),
    revision: String(item['revision'] ?? ''),
  }
}

function numberOrNull(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null
}

function parseContextSource(value: unknown): ContextSource {
  const item = record(value)
  return {
    path: String(item['path'] ?? ''),
    exists: item['exists'] === true,
    revision: String(item['revision'] ?? ''),
    line: Number(item['line'] ?? 0),
  }
}

function parseContextItem(value: unknown): ContextManifestItem {
  const item = record(value)
  return {
    section: String(item['section'] ?? ''),
    status: String(item['status'] ?? 'selected'),
    estimatedTokens: Number(item['estimated_tokens'] ?? 0),
    snippet: String(item['snippet'] ?? ''),
    selectionReason: String(item['selection_reason'] ?? ''),
    compressionReason: String(item['compression_reason'] ?? ''),
    protected: item['protected'] === true,
    protectionReason: String(item['protection_reason'] ?? ''),
    revision: String(item['revision'] ?? ''),
    sources: Array.isArray(item['sources']) ? item['sources'].map(parseContextSource) : [],
  }
}

function parseMissingItem(value: unknown): ContextMissingItem {
  const item = record(value)
  return {
    section: String(item['section'] ?? item['label'] ?? ''),
    reason: String(item['reason'] ?? ''),
    protected: item['protected'] === true,
    sources: Array.isArray(item['sources']) ? item['sources'].map(parseContextSource) : [],
  }
}

function parseContextPayload(value: unknown): ContextPayload {
  const root = payloadRecord(value)
  const manifest = record(root['manifest'])
  const budget = record(manifest['request_budget'])
  const sessionBudget = record(manifest['session_budget'])
  const usage = record(budget['actual_usage'])
  const freshness = record(manifest['freshness'])
  const previous = record(manifest['previous_freshness'])
  const retrieval = record(manifest['retrieval'] ?? root['semantic_retrieval'])
  return {
    markdown: String(root['markdown'] ?? ''),
    manifest: {
      revision: String(manifest['packet_revision'] ?? manifest['revision'] ?? ''),
      sourceRevision: String(manifest['source_revision'] ?? ''),
      freshness: String(freshness['status'] ?? 'unknown'),
      previousFreshness: String(previous['status'] ?? 'current'),
      previousRevision: String(previous['previous_revision'] ?? ''),
      estimatedTokens: Number(manifest['estimated_tokens'] ?? 0),
      requestBudgetAvailable: budget['available'] === true,
      requestBudgetTokens: numberOrNull(budget['input_budget_tokens']),
      reservedOutputTokens: numberOrNull(budget['reserved_output_tokens']),
      actualUsageReported: usage['reported'] === true,
      sessionBudgetAvailable: sessionBudget['available'] === true,
      sessionBudgetReason: String(sessionBudget['reason'] ?? ''),
      retrievalStatus: String(retrieval['status'] ?? 'unavailable'),
      retrievalReason: String(retrieval['reason'] ?? ''),
      retrievalIndexStatus: String(record(retrieval['index'])['status'] ?? 'unavailable'),
      retrievalResults: Number(retrieval['results'] ?? 0),
      retrievalSources: Array.isArray(retrieval['sources']) ? retrieval['sources'].map(parseContextSource) : [],
      items: Array.isArray(manifest['items']) ? manifest['items'].map(parseContextItem) : [],
      missingItems: Array.isArray(manifest['missing_items']) ? manifest['missing_items'].map(parseMissingItem) : [],
      excludedItems: Array.isArray(manifest['excluded_items']) ? manifest['excluded_items'].map(parseMissingItem) : [],
    },
  }
}

function chapterId(path: string): string {
  return /(?:^|\/)(ch_[A-Za-z0-9_-]+)\.md$/.exec(path)?.[1] ?? ''
}

function storedPaneState(key: string, fallback: boolean): boolean {
  if (typeof window === 'undefined') return fallback
  try {
    const value = window.localStorage.getItem(key)
    return value === null ? fallback : value === 'true'
  } catch {
    return fallback
  }
}

function compactInspectorLayout(): boolean {
  return typeof window !== 'undefined' && window.matchMedia('(max-width: 900px)').matches
}

function splitContextSections(markdown: string, fallbackTitle: string): ContextSection[] {
  const sections: ContextSection[] = []
  let title = fallbackTitle
  let lines: string[] = []
  const flush = () => {
    const body = lines.join('\n').trim()
    if (body !== '') sections.push({ title, markdown: body })
  }
  for (const line of markdown.split('\n')) {
    const heading = /^##\s+(.+?)\s*$/.exec(line)
    if (heading === null) {
      lines.push(line)
      continue
    }
    flush()
    title = heading[1] ?? fallbackTitle
    lines = []
  }
  flush()
  return sections.length > 0 ? sections : [{ title: fallbackTitle, markdown }]
}

function ContextDocument({ context, fallbackTitle, t, onOpenSource }: {
  context: ContextPayload
  fallbackTitle: string
  t: CreationViewProps['t']
  onOpenSource: (path: string) => void
}) {
  const { manifest, markdown } = context
  const sections = useMemo(() => splitContextSections(markdown, fallbackTitle), [fallbackTitle, markdown])
  const [open, setOpen] = useState<ReadonlySet<number>>(() => new Set([0]))
  return <div className={css.contextSections}>
    <section className={css.contextOverview}>
      <header>
        <div><strong>{t('creation.context.packet')}</strong><code>{manifest.revision || '—'}</code></div>
        <span data-status={manifest.freshness}>{manifest.freshness === 'current'
          ? t('creation.context.current') : t('creation.context.stale')}</span>
      </header>
      {manifest.previousFreshness === 'stale' && <div className={css.contextStale} role="status">
        <ShieldAlert size={14} />
        <span>{t('creation.context.previousStale')} <code>{manifest.previousRevision}</code></span>
      </div>}
      <div className={css.contextBudgets}>
        <article>
          <strong>{t('creation.context.requestBudget')}</strong>
          <span>{manifest.requestBudgetAvailable && manifest.requestBudgetTokens !== null
            ? `${String(manifest.estimatedTokens)} / ${String(manifest.requestBudgetTokens)} tokens`
            : t('creation.context.unavailable')}</span>
          <small>{t('creation.context.outputReserve')}: {manifest.reservedOutputTokens ?? '—'} · {t('creation.context.actualUsage')}: {manifest.actualUsageReported ? t('creation.context.reported') : t('creation.context.unavailable')}</small>
        </article>
        <article>
          <strong>{t('creation.context.sessionBudget')}</strong>
          <span>{manifest.sessionBudgetAvailable ? t('creation.context.reported') : t('creation.context.unavailable')}</span>
          <small>{manifest.sessionBudgetReason || t('creation.context.sessionSeparate')}</small>
        </article>
      </div>
      <div className={css.contextRetrieval} data-status={manifest.retrievalStatus}>
        <div><strong>{t('creation.context.retrieval')}</strong><small>{manifest.retrievalReason}</small></div>
        <span>{manifest.retrievalStatus} · {manifest.retrievalIndexStatus} · {String(manifest.retrievalResults)}</span>
      </div>
      {manifest.retrievalSources.length > 0 && <div className={css.contextSources}>
        {manifest.retrievalSources.map(source => <button key={`${source.path}:${String(source.line)}`} type="button"
          onClick={() => onOpenSource(source.path)}>{source.path}:{String(source.line || 1)}</button>)}
      </div>}
    </section>
    <section className={css.contextManifest}>
      <h3>{t('creation.context.sources')}</h3>
      {manifest.items.map(item => <article key={`${item.section}:${item.revision}`} className={css.contextItem} data-status={item.status}>
        <header>
          <strong>{item.section}</strong>
          <span>{item.status}</span>
          {item.protected && <b>{t('creation.context.protected')}</b>}
          <small>{String(item.estimatedTokens)} tokens</small>
        </header>
        <p>{item.snippet || t('creation.context.noSnippet')}</p>
        <small>{t('creation.context.reason')}: {item.selectionReason}{item.compressionReason ? ` · ${item.compressionReason}` : ''}</small>
        <div className={css.contextSources}>{item.sources.map(source => source.path.endsWith('/')
          ? <code key={source.path} data-missing={!source.exists}>{source.path} · {source.revision}</code>
          : <button key={source.path} type="button" data-missing={!source.exists}
              onClick={() => onOpenSource(source.path)}>{source.path} · {source.revision}</button>)}</div>
      </article>)}
      {(manifest.missingItems.length > 0 || manifest.excludedItems.length > 0) && <div className={css.contextExceptions}>
        {manifest.missingItems.map(item => <div key={`missing:${item.section}`}><strong>{t('creation.context.missing')}</strong> {item.section} · {item.reason}</div>)}
        {manifest.excludedItems.map(item => <div key={`excluded:${item.section}`}><strong>{t('creation.context.excluded')}</strong> {item.section} · {item.reason}</div>)}
      </div>}
    </section>
    <details className={css.contextFullText}>
      <summary>{t('creation.context.fullText')}</summary>
    {sections.map((section, index) => {
      const expanded = open.has(index)
      return <section key={`${section.title}:${String(index)}`} className={css.contextSection}>
        <button type="button" className={css.contextSectionButton} aria-expanded={expanded}
          onClick={() => setOpen(previous => {
            const next = new Set(previous)
            if (next.has(index)) next.delete(index)
            else next.add(index)
            return next
          })}>
          <ChevronRight size={14} aria-hidden="true" />
          <span>{section.title}</span>
        </button>
        {expanded && <div className={css.contextSectionBody}><MarkdownText text={section.markdown} /></div>}
      </section>
    })}
    </details>
  </div>
}

export type CreationViewProps = ConvViewProps & InjectFace<StudioApiInjected> & PropsLocale<'studio-panel'>

/** Native manuscript workbench: chapter rail, local Vditor editor and inspector. */
export function CreationView(props: CreationViewProps) {
  const { fetchStudioApi, postStudioApi, putStudioApi, t } = props
  const workbench = useWorkbench()
  useBindStudioContext({ sessionId: props.sessionId, useWorkspaces: props.useWorkspaces })
  const workspaceId = workbench.context?.workspaceId
  const [documentState, setDocumentState] = useState<LoadState>('idle')
  const [document_, setDocument] = useState<DocumentPayload | null>(null)
  const [draft, setDraft] = useState('')
  const [loadError, setLoadError] = useState('')
  const [recoveryDraft, setRecoveryDraft] = useState<ManuscriptDraftRecord | null>(null)
  const [draftStorageError, setDraftStorageError] = useState('')
  const [editorFailed, setEditorFailed] = useState(false)
  const [editorReady, setEditorReady] = useState(false)
  const [editorEpoch, setEditorEpoch] = useState(0)
  const [inspectorTab, setInspectorTab] = useState<InspectorTab>('context')
  const [inspectorState, setInspectorState] = useState<LoadState>('idle')
  const [inspectorSlow, setInspectorSlow] = useState(false)
  const [inspectorError, setInspectorError] = useState('')
  const [inspectorErrorSources, setInspectorErrorSources] = useState<string[]>([])
  const [historyState, setHistoryState] = useState<LoadState>('idle')
  const [historyError, setHistoryError] = useState('')
  const [inspectorReload, setInspectorReload] = useState(0)
  const [compactLayout, setCompactLayout] = useState(compactInspectorLayout)
  const [context, setContext] = useState<ContextPayload | null>(null)
  const [versions, setVersions] = useState<ManuscriptVersion[]>([])
  const [versionPreview, setVersionPreview] = useState<VersionPreview | null>(null)
  const [revisionProposals, setRevisionProposals] = useState<RevisionProposal[]>([])
  const [revisionSelections, setRevisionSelections] = useState<Record<string, string[]>>({})
  const [historyBusy, setHistoryBusy] = useState('')
  const [historyNotice, setHistoryNotice] = useState('')
  const [acceptanceState, setAcceptanceState] = useState<LoadState>('idle')
  const [acceptance, setAcceptance] = useState<ManuscriptAcceptance | null>(null)
  const [acceptanceError, setAcceptanceError] = useState('')
  const [acceptanceBusy, setAcceptanceBusy] = useState<AcceptanceAction | ''>('')
  const [acceptanceReload, setAcceptanceReload] = useState(0)
  const [chapterQuery, setChapterQuery] = useState('')
  const [readerMode, setReaderMode] = useState(false)
  const [selectedReviewIssueIds, setSelectedReviewIssueIds] = useState<string[]>([])
  const [reviewInstruction, setReviewInstruction] = useState('')
  const [reviewTaskBusy, setReviewTaskBusy] = useState<'revision' | 'rereview' | ''>('')
  const [reviewTaskNotice, setReviewTaskNotice] = useState('')
  const [workBrief, setWorkBrief] = useState<ChapterWorkBriefDto | null>(null)
  const [workBriefState, setWorkBriefState] = useState<LoadState>('idle')
  const [workBriefError, setWorkBriefError] = useState('')
  const [workBriefReload, setWorkBriefReload] = useState(0)
  const [readingOrder, setReadingOrder] = useState<ReadingOrderDto | null>(null)
  const [readingOrderState, setReadingOrderState] = useState<LoadState>('idle')
  const [readingOrderError, setReadingOrderError] = useState('')
  const [readingOrderReload, setReadingOrderReload] = useState(0)
  const [activeOccurrenceId, setActiveOccurrenceId] = useState('')
  const [moveVolumeId, setMoveVolumeId] = useState('')
  const [moveIndex, setMoveIndex] = useState('0')
  const [moveBusy, setMoveBusy] = useState(false)
  const [moveNotice, setMoveNotice] = useState('')
  const [chapterRailVisible, setChapterRailVisible] = useState(() => storedPaneState(storageKey('dsh-novel.chapterRailVisible', workspaceId), true))
  const [inspectorVisible, setInspectorVisible] = useState(() => storedPaneState(storageKey('dsh-novel.inspectorVisible', workspaceId), false))
  const [leftOpen, setLeftOpen] = useState(false)
  const [rightOpen, setRightOpen] = useState(false)
  const savedContentRef = useRef('')
  const draftRef = useRef('')
  const dirtyRef = useRef(false)
  const documentRef = useRef<DocumentPayload | null>(null)
  const saveTimerRef = useRef<number | null>(null)
  const saveInFlightRef = useRef(false)
  const saveQueuedRef = useRef(false)
  const queuedForceRef = useRef(false)
  const queuedManualRef = useRef(false)
  const saveRef = useRef<(force?: boolean, origin?: 'autosave' | 'manual') => Promise<void>>(async () => undefined)
  const mountedRef = useRef(true)
  const draftWriteChainRef = useRef<Promise<void>>(Promise.resolve())
  const draftUpdatedAtRef = useRef(0)
  const inspectorLoadedKeyRef = useRef('')
  const historyLoadedKeyRef = useRef('')
  const contextRevisionRef = useRef({ identity: '', revision: '', sourceRevision: '' })
  const fetchStudioApiRef = useRef(fetchStudioApi)
  fetchStudioApiRef.current = fetchStudioApi
  const path = workbench.activeChapterPath
  const orderedChapters = useMemo<readonly ChapterSummary[]>(() => {
    if (readingOrder === null) return workbench.chapters
    return readingOrder.documents.filter(document => document.status !== 'missing').map(document => {
      const existing = workbench.chapters.find(chapter => chapter.documentId !== '' && chapter.documentId === document.document_id)
        ?? workbench.chapters.find(chapter => chapter.path === document.path)
      return {
        id: document.chapter_id,
        documentId: document.document_id,
        occurrenceId: document.occurrence_id,
        volumeId: document.volume_id,
        status: document.status,
        path: existing?.path ?? document.path,
        title: document.title || existing?.title || document.chapter_id,
        subtitle: existing?.subtitle ?? '',
        revision: document.revision,
        readingIndex: document.reading_index,
        writingUnits: document.writing_units,
        updatedAt: document.updated_at,
        review: existing?.review ?? {
          score: null, passed: null, issues: 0, issueDetails: [], stale: false,
          reviewedAt: '', sourceRevision: '', currentSourceRevision: '',
        },
      }
    })
  }, [readingOrder, workbench.chapters])
  const occurrenceChapterIndex = orderedChapters.findIndex(chapter =>
    activeOccurrenceId !== '' && chapter.occurrenceId === activeOccurrenceId && chapter.path === path)
  const activeChapterIndex = occurrenceChapterIndex >= 0
    ? occurrenceChapterIndex
    : orderedChapters.findIndex(chapter => chapter.path === path)
  const activeChapter = orderedChapters[activeChapterIndex] ?? orderedChapters.find(chapter => chapter.path === path)
  const activeDocumentId = activeChapter?.documentId ?? ''
  const missingChapterCount = readingOrder?.documents.filter(document => document.status === 'missing').length ?? 0
  const moveTargetMax = readingOrder === null ? 0 : Math.max(0,
    readingOrder.documents.filter(document => document.volume_id === moveVolumeId).length -
      (activeChapter?.volumeId === moveVolumeId ? 1 : 0))
  const documentIdentity = `${String(workbench.contextEpoch)}:${workspaceId ?? ''}:${activeChapter?.occurrenceId ?? ''}:${activeDocumentId}:${path}`
  const documentIdentityRef = useRef(documentIdentity)
  documentIdentityRef.current = documentIdentity
  const novelId = manuscriptNovelId(workbench.workspace, path)
  const draftIdentity = workspaceId !== undefined && novelId !== '' && path !== ''
    ? { workspaceId, novelId, path }
    : null
  const draftIdentityKey = draftIdentity === null ? '' : manuscriptDraftKey(draftIdentity)
  const draftIdentityRef = useRef<ManuscriptDraftIdentity | null>(draftIdentity)
  const draftIdentityKeyRef = useRef(draftIdentityKey)
  draftIdentityRef.current = draftIdentity
  draftIdentityKeyRef.current = draftIdentityKey
  const writingProgress = workbench.writingProgress ?? { bookUnits: 0, bookTarget: 0, chapterTarget: 0 }
  const reviewStale = workBrief?.review.stale ?? activeChapter?.review.stale ?? false
  const reviewCasReady = workBrief !== null &&
    workBrief.review.review_revision !== '' &&
    workBrief.manuscript.current_revision !== '' &&
    !workBrief.review.stale &&
    workBrief.review.current_source_revision === workBrief.manuscript.current_revision
  const duplicateChapterKeys = useMemo(() => {
    const counts = new Map<string, number>()
    for (const chapter of orderedChapters) {
      for (const key of new Set([chapter.id, chapter.path]).values()) {
        if (key !== '') counts.set(key, (counts.get(key) ?? 0) + 1)
      }
    }
    return counts
  }, [orderedChapters])
  const normalizedQuery = chapterQuery.trim().toLocaleLowerCase()
  const visibleChapters = orderedChapters
    .map((chapter, index) => ({ chapter, index }))
    .filter(({ chapter }) => normalizedQuery === '' ||
      `${chapter.title} ${chapter.subtitle} ${chapter.path}`.toLocaleLowerCase().includes(normalizedQuery))
  const inspectorRequested = compactLayout ? rightOpen : inspectorVisible
  const hasUnsavedDraft = document_ !== null && draft !== savedContentRef.current
  const openContextSource = useCallback((relativePath: string) => {
    if (relativePath === '' || relativePath.endsWith('/')) return
    const match = /^(data\/novels\/[^/]+)\//.exec(path)
    if (match === null) return
    workbenchStore.setActiveChapter(`${match[1]}/${relativePath}`)
    setRightOpen(false)
  }, [path])

  useEffect(() => {
    mountedRef.current = true
    return () => { mountedRef.current = false }
  }, [])

  useEffect(() => {
    let cancelled = false
    setReadingOrderState('loading')
    setReadingOrderError('')
    void fetchStudioApiRef.current('/reading-order').then(payload => {
      if (cancelled) return
      const order = parseReadingOrder(payload)
      const occurrenceIds = order.documents.map(document => document.occurrence_id)
      const uniqueOccurrences = new Set(occurrenceIds)
      if (order.schema_version !== 'openwrite.reading-order.v1' || order.revision === '' ||
        uniqueOccurrences.size !== occurrenceIds.length ||
        order.actual_order.length !== occurrenceIds.length ||
        order.actual_order.some((occurrenceId, index) => occurrenceId !== occurrenceIds[index])) {
        throw new Error(t('creation.order.invalid'))
      }
      setReadingOrder(order)
      setReadingOrderState('ready')
      setActiveOccurrenceId(previous => {
        if (order.documents.some(document => document.occurrence_id === previous && document.path === path)) return previous
        const workspaceIdentity = workbench.chapters.find(chapter => chapter.path === path)?.documentId ?? ''
        return order.documents.find(document => workspaceIdentity !== '' && document.document_id === workspaceIdentity)?.occurrence_id
          ?? order.documents.find(document => document.path === path)?.occurrence_id
          ?? ''
      })
    }).catch((cause: unknown) => {
      if (cancelled) return
      setReadingOrder(null)
      setReadingOrderError(cause instanceof Error ? cause.message : String(cause))
      setReadingOrderState('error')
    })
    return () => { cancelled = true }
  }, [
    path,
    readingOrderReload,
    t,
    workspaceId,
    workbench.contextEpoch,
    workbench.epochs.workspace,
    workbench.epochs.manuscript,
  ])

  useEffect(() => {
    setSelectedReviewIssueIds([])
    setReviewInstruction('')
    setReviewTaskNotice('')
  }, [documentIdentity])

  const queueDraftOperation = useCallback((
    identity: ManuscriptDraftIdentity,
    operation: () => Promise<unknown>,
  ) => {
    const identityKey = manuscriptDraftKey(identity)
    draftWriteChainRef.current = draftWriteChainRef.current
      .catch(() => undefined)
      .then(operation)
      .then(() => {
        if (mountedRef.current && draftIdentityKeyRef.current === identityKey) setDraftStorageError('')
      }, () => {
        if (mountedRef.current && draftIdentityKeyRef.current === identityKey) {
          setDraftStorageError(t('creation.draft.unavailable'))
        }
      })
  }, [t])

  useEffect(() => {
    void loadVditor().catch(() => {
      // VditorBody retries and owns the fallback state when the document mounts.
    })
    const query = window.matchMedia('(max-width: 900px)')
    const updateLayout = () => setCompactLayout(query.matches)
    query.addEventListener('change', updateLayout)
    return () => query.removeEventListener('change', updateLayout)
  }, [])

  const loadDocument = useCallback(async (allowDiscard = false) => {
    if (path === '') return
    const requestIdentity = documentIdentity
    if (dirtyRef.current && !allowDiscard) {
      workbenchStore.setEditorStatus('conflict', t('creation.changedElsewhere'))
      return
    }
    setDocumentState('loading')
    setLoadError('')
    setRecoveryDraft(null)
    setDraftStorageError('')
    setEditorReady(false)
    workbenchStore.setEditorStatus('loading')
    try {
      const data = parseDocument(await fetchStudioApi(`/document?path=${encodeURIComponent(path)}`))
      if (!mountedRef.current || documentIdentityRef.current !== requestIdentity) return
      setDocument(data)
      documentRef.current = data
      setDraft(data.content)
      draftRef.current = data.content
      savedContentRef.current = data.content
      dirtyRef.current = false
      setEditorFailed(false)
      setEditorEpoch(value => value + 1)
      setDocumentState('ready')
      workbenchStore.setEditorStatus('saved')
      const requestDraftIdentity = draftIdentity
      if (requestDraftIdentity !== null) {
        try {
          const stored = await manuscriptDraftStore.load(requestDraftIdentity)
          if (!mountedRef.current || documentIdentityRef.current !== requestIdentity) return
          if (stored !== null && stored.content !== data.content) {
            setRecoveryDraft(stored)
          } else if (stored !== null) {
            queueDraftOperation(requestDraftIdentity, () =>
              manuscriptDraftStore.removeIfContent(requestDraftIdentity, stored.content))
          }
        } catch {
          if (mountedRef.current && documentIdentityRef.current === requestIdentity) {
            setDraftStorageError(t('creation.draft.unavailable'))
          }
        }
      }
    } catch (cause: unknown) {
      if (!mountedRef.current || documentIdentityRef.current !== requestIdentity) return
      const message = cause instanceof Error ? cause.message : String(cause)
      setLoadError(message)
      setDocumentState('error')
      workbenchStore.setEditorStatus('offline', message)
    }
  }, [documentIdentity, draftIdentityKey, fetchStudioApi, path, queueDraftOperation, t])

  useEffect(() => {
    documentRef.current = null
    setRecoveryDraft(null)
    setDraftStorageError('')
    saveQueuedRef.current = false
    queuedForceRef.current = false
    queuedManualRef.current = false
    dirtyRef.current = false
    void loadDocument(true)
    return () => {
      if (saveTimerRef.current !== null) window.clearTimeout(saveTimerRef.current)
    }
  }, [loadDocument])

  useEffect(() => {
    const id = chapterId(path)
    if (id === '') {
      setWorkBrief(null)
      setWorkBriefState('idle')
      setWorkBriefError('')
      return
    }
    let cancelled = false
    setWorkBrief(null)
    setWorkBriefState('loading')
    setWorkBriefError('')
    const query = new URLSearchParams({ recent_limit: '20' })
    if (activeDocumentId !== '') query.set('document_id', activeDocumentId)
    void fetchStudioApiRef.current(`/chapters/${encodeURIComponent(id)}/work-brief?${query.toString()}`).then(payload => {
      if (cancelled) return
      const brief = parseChapterWorkBrief(payload)
      if (brief.schema_version !== 'openwrite.chapter-work-brief.v1' || brief.chapter_id !== id ||
        (activeDocumentId !== '' && brief.document_id !== activeDocumentId)) {
        throw new Error(t('creation.activity.invalid'))
      }
      setWorkBrief(brief)
      setWorkBriefState('ready')
    }).catch((cause: unknown) => {
      if (cancelled) return
      setWorkBrief(null)
      setWorkBriefError(cause instanceof Error ? cause.message : String(cause))
      setWorkBriefState('error')
    })
    return () => { cancelled = true }
  }, [
    activeDocumentId,
    path,
    t,
    workBriefReload,
    workspaceId,
    workbench.contextEpoch,
    workbench.epochs.manuscript,
    workbench.epochs.revisions,
    workbench.epochs.tasks,
  ])

  useEffect(() => {
    const id = chapterId(path)
    if (id === '') {
      setAcceptanceState('idle')
      setAcceptance(null)
      setAcceptanceError('')
      return
    }
    let cancelled = false
    setAcceptanceState('loading')
    setAcceptanceError('')
    void fetchStudioApiRef.current('/manuscript/acceptance').then(payload => {
      if (cancelled) return
      setAcceptance(parseManuscriptAcceptance(payload, id))
      setAcceptanceState('ready')
    }).catch((cause: unknown) => {
      if (cancelled) return
      setAcceptance(null)
      setAcceptanceError(cause instanceof Error ? cause.message : String(cause))
      setAcceptanceState('error')
    })
    return () => { cancelled = true }
  }, [
    acceptanceReload,
    path,
    workspaceId,
    workbench.contextEpoch,
    workbench.epochs.workspace,
    workbench.epochs.manuscript,
    workbench.epochs.tasks,
  ])

  useEffect(() => {
    if (workbench.epochs.manuscript === 0 || documentState !== 'ready') return
    if (saveInFlightRef.current || saveQueuedRef.current) return
    void loadDocument(false)
    // Resource epochs are the signal; documentState/loadDocument are intentionally read at signal time.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [workbench.epochs.manuscript])

  useEffect(() => {
    if (path === '' || !inspectorRequested || inspectorTab !== 'context') return
    const sourceEpochs = [
      workbench.epochs.workspace,
      workbench.epochs.manuscript,
      workbench.epochs.outline,
      workbench.epochs.assets,
      workbench.epochs.revisions,
    ].join(':')
    const requestKey = `${path}:${sourceEpochs}:${String(inspectorReload)}`
    if (inspectorLoadedKeyRef.current === requestKey) return
    const id = chapterId(path)
    if (id === '') return
    const contextIdentity = `${workspaceId ?? ''}:${id}`
    const previous = contextRevisionRef.current.identity === contextIdentity
      ? contextRevisionRef.current.revision
      : ''
    let cancelled = false
    const slowTimer = window.setTimeout(() => {
      if (!cancelled) setInspectorSlow(true)
    }, 4_000)
    setInspectorState('loading')
    setInspectorSlow(false)
    setInspectorError('')
    setInspectorErrorSources([])
    setContext(null)
    void fetchStudioApiRef.current(`/context?chapter=${encodeURIComponent(id)}${previous === '' ? '' : `&known_revision=${encodeURIComponent(previous)}&known_source_revision=${encodeURIComponent(contextRevisionRef.current.sourceRevision)}`}`)
      .then((contextPayload) => {
      if (cancelled) return
      const parsedContext = parseContextPayload(contextPayload)
      setContext(parsedContext)
      contextRevisionRef.current = {
        identity: contextIdentity,
        revision: parsedContext.manifest.revision,
        sourceRevision: parsedContext.manifest.sourceRevision,
      }
      inspectorLoadedKeyRef.current = requestKey
      setInspectorState('ready')
    }).catch((cause: unknown) => {
      if (!cancelled) {
        setInspectorError(cause instanceof Error ? cause.message : String(cause))
        setInspectorErrorSources(
          cause instanceof StudioApiError && cause.code === 'PROTECTED_CONTEXT_OVER_BUDGET'
            ? stringArray(cause.details['source_paths'])
            : [],
        )
        setInspectorState('error')
      }
    }).finally(() => window.clearTimeout(slowTimer))
    return () => {
      cancelled = true
      window.clearTimeout(slowTimer)
    }
  }, [
    inspectorReload,
    inspectorRequested,
    inspectorTab,
    path,
    workspaceId,
    workbench.epochs.workspace,
    workbench.epochs.manuscript,
    workbench.epochs.outline,
    workbench.epochs.assets,
    workbench.epochs.revisions,
  ])

  useEffect(() => {
    if (path === '' || !inspectorRequested || inspectorTab !== 'revisions') return
    const sourceEpochs = [
      workbench.epochs.workspace,
      workbench.epochs.manuscript,
      workbench.epochs.revisions,
    ].join(':')
    const requestKey = `${path}:${sourceEpochs}:${String(inspectorReload)}`
    if (historyLoadedKeyRef.current === requestKey) return
    const id = chapterId(path)
    if (id === '') return
    let cancelled = false
    setHistoryState('loading')
    setHistoryError('')
    setVersions([])
    setVersionPreview(null)
    setRevisionProposals([])
    setHistoryNotice('')
    void Promise.all([
      fetchStudioApiRef.current(`/revisions?chapter=${encodeURIComponent(id)}`),
      fetchStudioApiRef.current(`/manuscript/versions?chapter=${encodeURIComponent(id)}`),
    ]).then(([revisionPayload, versionPayload]) => {
      if (cancelled) return
      const proposals = parseProposals(revisionPayload)
      setRevisionProposals(proposals)
      setRevisionSelections(Object.fromEntries(proposals.map(proposal => [
        proposal.proposalId,
        proposal.hunks.map(hunk => hunk.id).filter(Boolean),
      ])))
      setVersions(parseVersions(versionPayload))
      historyLoadedKeyRef.current = requestKey
      setHistoryState('ready')
    }).catch((cause: unknown) => {
      if (!cancelled) {
        setHistoryError(cause instanceof Error ? cause.message : String(cause))
        setHistoryState('error')
      }
    })
    return () => { cancelled = true }
  }, [
    inspectorReload,
    inspectorRequested,
    inspectorTab,
    path,
    workbench.epochs.workspace,
    workbench.epochs.manuscript,
    workbench.epochs.revisions,
  ])

  useEffect(() => {
    const beforeUnload = (event: BeforeUnloadEvent) => {
      if (!dirtyRef.current) return
      event.preventDefault()
      event.returnValue = ''
    }
    window.addEventListener('beforeunload', beforeUnload)
    return () => window.removeEventListener('beforeunload', beforeUnload)
  }, [])

  useEffect(() => {
    if (!leftOpen && !rightOpen) return
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return
      setLeftOpen(false)
      setRightOpen(false)
    }
    window.addEventListener('keydown', closeOnEscape)
    return () => window.removeEventListener('keydown', closeOnEscape)
  }, [leftOpen, rightOpen])

  const save = useCallback(async (force = false, origin: 'autosave' | 'manual' = 'autosave') => {
    if (saveTimerRef.current !== null) {
      window.clearTimeout(saveTimerRef.current)
      saveTimerRef.current = null
    }
    if (!dirtyRef.current) return
    if (saveInFlightRef.current) {
      saveQueuedRef.current = true
      queuedForceRef.current = queuedForceRef.current || force
      queuedManualRef.current = queuedManualRef.current || origin === 'manual'
      return
    }
    const currentDocument = documentRef.current
    const currentContext = workbenchStore.getSnapshot().context
    if (currentDocument === null || currentContext === null) return
    const request: SaveRequestSnapshot = {
      identity: documentIdentityRef.current,
      context: { workspaceId: currentContext.workspaceId, sessionId: currentContext.sessionId },
      document: currentDocument,
      content: draftRef.current,
      force,
      saveOrigin: origin,
      draftIdentity: draftIdentityRef.current,
    }
    saveInFlightRef.current = true
    saveQueuedRef.current = false
    queuedForceRef.current = false
    queuedManualRef.current = false
    workbenchStore.setEditorStatus('saving')
    let succeeded = false
    try {
      const response = await putStudioApi('/document', {
        path: request.document.path,
        content: request.content,
        version: request.document.version,
        save_origin: request.saveOrigin,
        ...(force ? { force: true } : {}),
      }, request.context)
      const result = parseDocument(response)
      succeeded = true
      if (!mountedRef.current || documentIdentityRef.current !== request.identity) return
      if (result.path !== request.document.path || result.content !== request.content) {
        throw new StudioApiError(t('creation.conflict'), 409, 'DOCUMENT_RESPONSE_MISMATCH')
      }
      const next = { ...request.document, ...result, content: request.content }
      setDocument(next)
      documentRef.current = next
      savedContentRef.current = request.content
      dirtyRef.current = draftRef.current !== request.content
      const savedDraftIdentity = request.draftIdentity
      if (savedDraftIdentity !== null) {
        queueDraftOperation(savedDraftIdentity, () =>
          manuscriptDraftStore.removeIfContent(savedDraftIdentity, request.content))
      }
      workbenchStore.setEditorStatus(dirtyRef.current ? 'dirty' : 'saved')
      workbenchStore.invalidate('workspace')
      setWorkBriefReload(value => value + 1)
      const nextAcceptance = parseManuscriptAcceptance(response, chapterId(request.document.path))
      if (nextAcceptance !== null) {
        setAcceptance(nextAcceptance)
        setAcceptanceState('ready')
      }
      if (record(response)['author_version'] !== undefined) setInspectorReload(value => value + 1)
    } catch (cause: unknown) {
      if (!mountedRef.current || documentIdentityRef.current !== request.identity) return
      succeeded = false
      if (cause instanceof StudioApiError && cause.status === 409) {
        workbenchStore.setEditorStatus('conflict', t('creation.conflict'))
      } else {
        workbenchStore.setEditorStatus('offline', cause instanceof Error ? cause.message : String(cause))
      }
    } finally {
      saveInFlightRef.current = false
      const queued = saveQueuedRef.current
      const queuedForce = queuedForceRef.current
      const queuedManual = queuedManualRef.current
      saveQueuedRef.current = false
      queuedForceRef.current = false
      queuedManualRef.current = false
      if (!mountedRef.current) return
      const requestStillCurrent = documentIdentityRef.current === request.identity
      if ((succeeded || !requestStillCurrent) && (queued || dirtyRef.current)) {
        void saveRef.current(queuedForce, queuedManual ? 'manual' : 'autosave')
      }
    }
  }, [putStudioApi, queueDraftOperation, t])
  saveRef.current = save

  const reconcileAcceptance = useCallback(async (action: AcceptanceAction) => {
    const id = chapterId(path)
    if (id === '' || acceptanceBusy !== '') return
    const confirmationKey = action === 'baseline'
      ? 'creation.acceptance.confirmBaseline'
      : action === 'external'
        ? 'creation.acceptance.confirmExternal'
        : action === 'acknowledge'
          ? 'creation.acceptance.confirmAcknowledge'
          : null
    if (confirmationKey !== null && !window.confirm(t(confirmationKey))) return
    setAcceptanceBusy(action)
    setAcceptanceError('')
    try {
      const body: Record<string, unknown> = { chapter_id: id }
      if (acceptance?.operationId) body['operation_id'] = acceptance.operationId
      if (confirmationKey !== null) body['confirm'] = true
      if (action === 'acknowledge') body['domains'] = ['outline', 'foreshadowing']
      const route = action === 'acknowledge' ? 'ack' : action === 'resume' ? 'reconcile' : action
      const response = await postStudioApi(`/manuscript/acceptance/${route}`, body)
      const next = parseManuscriptAcceptance(response, id)
      if (next !== null) {
        setAcceptance(next)
        setAcceptanceState('ready')
      } else {
        setAcceptanceReload(value => value + 1)
      }
      workbenchStore.invalidate('manuscript')
      workbenchStore.invalidate('tasks')
    } catch (cause: unknown) {
      setAcceptanceError(cause instanceof Error ? cause.message : String(cause))
      setAcceptanceState('error')
    } finally {
      setAcceptanceBusy('')
    }
  }, [acceptance, acceptanceBusy, path, postStudioApi, t])

  const persistDraft = (value: string, previousValue: string) => {
    const identity = draftIdentityRef.current
    const currentDocument = documentRef.current
    if (identity === null || currentDocument === null) return
    if (value === savedContentRef.current) {
      queueDraftOperation(identity, () => manuscriptDraftStore.removeIfContent(identity, previousValue))
      return
    }
    const updatedAt = Math.max(Date.now(), draftUpdatedAtRef.current + 1)
    draftUpdatedAtRef.current = updatedAt
    const record: ManuscriptDraftRecord = {
      ...identity,
      key: manuscriptDraftKey(identity),
      formatVersion: MANUSCRIPT_DRAFT_FORMAT_VERSION,
      baseRevision: currentDocument.revision,
      content: value,
      updatedAt,
    }
    queueDraftOperation(identity, () => manuscriptDraftStore.save(record))
  }

  const updateDraft = (value: string) => {
    const previousValue = draftRef.current
    setDraft(value)
    draftRef.current = value
    setRecoveryDraft(null)
    persistDraft(value, previousValue)
    const dirty = value !== savedContentRef.current
    dirtyRef.current = dirty
    workbenchStore.setEditorStatus(dirty ? 'dirty' : 'saved')
    if (saveTimerRef.current !== null) window.clearTimeout(saveTimerRef.current)
    if (dirty) saveTimerRef.current = window.setTimeout(() => { void saveRef.current() }, 1_200)
  }

  const restoreRecoveryDraft = () => {
    const stored = recoveryDraft
    const currentDocument = documentRef.current
    if (stored === null || currentDocument === null) return
    const staleBase = stored.baseRevision !== currentDocument.revision
    setRecoveryDraft(null)
    setDraft(stored.content)
    draftRef.current = stored.content
    setEditorReady(false)
    setEditorEpoch(value => value + 1)
    dirtyRef.current = stored.content !== savedContentRef.current
    if (saveTimerRef.current !== null) window.clearTimeout(saveTimerRef.current)
    saveTimerRef.current = null
    if (staleBase) {
      workbenchStore.setEditorStatus('conflict', t('creation.draft.conflict'))
    } else {
      workbenchStore.setEditorStatus(dirtyRef.current ? 'dirty' : 'saved')
      if (dirtyRef.current) {
        saveTimerRef.current = window.setTimeout(() => { void saveRef.current() }, 1_200)
      }
    }
  }

  const dismissRecoveryDraft = () => {
    const stored = recoveryDraft
    if (stored === null) return
    setRecoveryDraft(null)
    const identity: ManuscriptDraftIdentity = stored
    queueDraftOperation(identity, () => manuscriptDraftStore.removeIfContent(identity, stored.content))
  }

  const chooseChapter = (nextPath: string, nextOccurrenceId = '') => {
    if (nextPath === path) {
      setActiveOccurrenceId(nextOccurrenceId)
      setReaderMode(false)
      setLeftOpen(false)
      return
    }
    if (dirtyRef.current && !window.confirm(t('creation.discardConfirm'))) return
    dirtyRef.current = false
    setActiveOccurrenceId(nextOccurrenceId)
    workbenchStore.setActiveChapter(nextPath)
    setReaderMode(false)
    setLeftOpen(false)
  }

  useEffect(() => {
    if (activeChapter === undefined || readingOrder === null) return
    setMoveVolumeId(activeChapter.volumeId)
    const siblings = readingOrder.documents.filter(document => document.volume_id === activeChapter.volumeId)
    const index = siblings.findIndex(document => document.occurrence_id === activeChapter.occurrenceId)
    setMoveIndex(String(Math.max(0, index)))
    setMoveNotice('')
  }, [activeChapter?.documentId, activeChapter?.occurrenceId, activeChapter?.volumeId, readingOrder?.revision])

  const moveActiveChapter = async () => {
    if (readingOrder === null || activeChapter === undefined || moveBusy || moveVolumeId === '') return
    if (dirtyRef.current) {
      await saveRef.current(false, 'manual')
      if (dirtyRef.current) return
    }
    const targetIndex = Number(moveIndex)
    if (!Number.isInteger(targetIndex) || targetIndex < 0 || targetIndex > moveTargetMax) return
    setMoveBusy(true)
    setMoveNotice('')
    try {
      const response = await postStudioApi('/reading-order/move', {
        document_id: activeChapter.documentId,
        target_volume_id: moveVolumeId,
        target_index: targetIndex,
        expected_revision: readingOrder.revision,
      })
      const result = payloadRecord(response)
      const nextOrder = parseReadingOrder(result['reading_order'])
      const nextOccurrences = nextOrder.documents.map(document => document.occurrence_id)
      if (nextOrder.schema_version !== 'openwrite.reading-order.v1' || nextOrder.revision === '' ||
        new Set(nextOccurrences).size !== nextOccurrences.length ||
        nextOrder.actual_order.length !== nextOccurrences.length ||
        nextOrder.actual_order.some((occurrenceId, index) => occurrenceId !== nextOccurrences[index])) {
        throw new Error(t('creation.order.invalid'))
      }
      const moved = nextOrder.documents.find(document => document.document_id === activeChapter.documentId)
      setReadingOrder(nextOrder)
      setReadingOrderState('ready')
      if (moved !== undefined) {
        setActiveOccurrenceId(moved.occurrence_id)
        workbenchStore.setActiveChapter(moved.path)
      }
      workbenchStore.invalidate('workspace')
      workbenchStore.invalidate('manuscript')
      setMoveNotice(t('creation.order.moveComplete'))
    } catch (cause: unknown) {
      if (cause instanceof StudioApiError && cause.code === 'READING_ORDER_CONFLICT') {
        setMoveNotice(t('creation.order.conflict'))
        setReadingOrderReload(value => value + 1)
      } else {
        setMoveNotice(cause instanceof Error ? cause.message : String(cause))
      }
    } finally {
      setMoveBusy(false)
    }
  }

  const launchReviewTask = async (kind: 'revision' | 'rereview') => {
    const id = chapterId(path)
    const expectedReviewRevision = workBrief?.review.review_revision ?? ''
    const expectedDocumentRevision = workBrief?.manuscript.current_revision ?? ''
    if (id === '' || reviewTaskBusy !== '') return
    if (kind === 'revision' && selectedReviewIssueIds.length === 0) return
    if (kind === 'revision' && (!reviewCasReady || expectedReviewRevision === '' || expectedDocumentRevision === '')) {
      setReviewTaskNotice(t('creation.review.refreshRequired'))
      return
    }
    setReviewTaskBusy(kind)
    setReviewTaskNotice('')
    try {
      await postStudioApi('/tasks', kind === 'revision'
        ? {
            type: 'revision_from_review',
            input: {
              chapter_id: id,
              issue_ids: selectedReviewIssueIds,
              expected_review_revision: expectedReviewRevision,
              expected_document_revision: expectedDocumentRevision,
              ...(reviewInstruction.trim() === '' ? {} : { instruction: reviewInstruction.trim() }),
            },
          }
        : { type: 'chapter_review', input: { chapter_id: id } })
      setReviewTaskNotice(t(kind === 'revision'
        ? 'creation.review.revisionStarted'
        : 'creation.review.rereviewStarted'))
      workbenchStore.invalidate('tasks')
      setWorkBriefReload(value => value + 1)
    } catch (cause: unknown) {
      setReviewTaskNotice(cause instanceof StudioApiError &&
        ['REVIEW_CONFLICT', 'REVIEW_STALE', 'DOCUMENT_CONFLICT'].includes(cause.code ?? '')
        ? t('creation.review.refreshRequired')
        : cause instanceof Error ? cause.message : String(cause))
    } finally {
      setReviewTaskBusy('')
    }
  }

  const reload = () => {
    if (dirtyRef.current && !window.confirm(t('creation.discardConfirm'))) return
    dirtyRef.current = false
    void loadDocument(true)
  }

  const overwrite = () => {
    if (!window.confirm(t('creation.overwriteConfirm'))) return
    void save(true, 'manual')
  }

  const toggleChapterRail = () => {
    setChapterRailVisible((visible) => {
      try { window.localStorage.setItem(storageKey('dsh-novel.chapterRailVisible', workspaceId), String(!visible)) } catch { /* unavailable storage */ }
      return !visible
    })
  }

  const toggleInspector = () => {
    setInspectorVisible((visible) => {
      try { window.localStorage.setItem(storageKey('dsh-novel.inspectorVisible', workspaceId), String(!visible)) } catch { /* unavailable storage */ }
      return !visible
    })
  }

  const createNamedSnapshot = async () => {
    if (historyBusy !== '') return
    if (dirtyRef.current) {
      await saveRef.current(false, 'manual')
      if (dirtyRef.current) return
    }
    const label = window.prompt(t('creation.history.snapshotName'))
    if (label === null) return
    setHistoryBusy('snapshot')
    setHistoryNotice('')
    try {
      await postStudioApi('/manuscript-editing', {
        action: 'checkpoint', chapter_id: chapterId(path), label: label.trim(),
      })
      setHistoryNotice(t('creation.history.snapshotCreated'))
      setInspectorReload(value => value + 1)
    } catch (cause: unknown) {
      setHistoryNotice(cause instanceof Error ? cause.message : String(cause))
    } finally {
      setHistoryBusy('')
    }
  }

  const previewVersion = async (versionId: string) => {
    if (historyBusy !== '') return
    setHistoryBusy(versionId)
    setHistoryNotice('')
    try {
      const preview = parseVersionPreview(await fetchStudioApi(
        `/manuscript/versions/${encodeURIComponent(versionId)}/compare?chapter=${encodeURIComponent(chapterId(path))}`,
      ))
      if (preview === null) throw new Error(t('creation.history.previewFailed'))
      setVersionPreview(preview)
    } catch (cause: unknown) {
      setHistoryNotice(cause instanceof Error ? cause.message : String(cause))
    } finally {
      setHistoryBusy('')
    }
  }

  const restoreVersion = async () => {
    const preview = versionPreview
    const currentDocument = documentRef.current
    if (preview === null || currentDocument === null || historyBusy !== '') return
    if (!window.confirm(t('creation.history.restoreConfirm'))) return
    setHistoryBusy(preview.version.versionId)
    setHistoryNotice('')
    try {
      await postStudioApi('/manuscript-editing', {
        action: 'restore',
        chapter_id: chapterId(path),
        version_id: preview.version.versionId,
        revision: currentDocument.revision,
        confirm: true,
      })
      setVersionPreview(null)
      setHistoryNotice(t('creation.history.restored'))
      workbenchStore.invalidate('manuscript')
      workbenchStore.invalidate('revisions')
      await loadDocument(true)
      setInspectorReload(value => value + 1)
    } catch (cause: unknown) {
      setHistoryNotice(cause instanceof Error ? cause.message : String(cause))
    } finally {
      setHistoryBusy('')
    }
  }

  const toggleRevisionHunk = (proposalId: string, hunkId: string) => {
    setRevisionSelections(previous => {
      const selected = new Set(previous[proposalId] ?? [])
      if (selected.has(hunkId)) selected.delete(hunkId)
      else selected.add(hunkId)
      return { ...previous, [proposalId]: Array.from(selected) }
    })
  }

  const runRevisionAction = async (
    proposal: RevisionProposal,
    action: 'apply' | 'reject' | 'regenerate',
  ) => {
    if (historyBusy !== '') return
    const selected = revisionSelections[proposal.proposalId] ?? []
    if (action === 'apply' && selected.length === 0) return
    setHistoryBusy(proposal.proposalId)
    setHistoryNotice('')
    try {
      await postStudioApi(`/revisions/${encodeURIComponent(proposal.proposalId)}/${action}`,
        action === 'apply' ? { selected_hunk_ids: selected } : {})
      if (action === 'apply') {
        workbenchStore.invalidate('manuscript')
        await loadDocument(true)
        setWorkBriefReload(value => value + 1)
        setHistoryNotice(t('creation.proposals.appliedNeedsReview'))
      }
      workbenchStore.invalidate('revisions')
      setInspectorReload(value => value + 1)
    } catch (cause: unknown) {
      setHistoryNotice(cause instanceof Error ? cause.message : String(cause))
    } finally {
      setHistoryBusy('')
    }
  }

  const versionReason = (reason: string) => {
    if (reason === 'autosave') return t('creation.history.reason.autosave')
    if (reason === 'manual') return t('creation.history.reason.manual')
    if (reason === 'ai_revision') return t('creation.history.reason.aiRevision')
    if (reason === 'full_rewrite') return t('creation.history.reason.fullRewrite')
    if (reason === 'restore') return t('creation.history.reason.restore')
    return reason
  }

  return (
    <div className={css.creationRoot} data-chapter-rail-visible={chapterRailVisible} data-inspector-visible={inspectorVisible}>
      <div className={css.mobileBar}>
        <button type="button" className={css.iconButton} title={t('creation.chapters')}
          aria-label={t('creation.chapters')} aria-expanded={leftOpen} onClick={() => setLeftOpen(value => !value)}>
          <PanelLeft size={18} />
        </button>
        <span className={css.mobileTitle}>{activeChapter?.title ?? t('creation.empty')}</span>
        <button type="button" className={css.iconButton} title={t('creation.inspector')}
          aria-label={t('creation.inspector')} aria-expanded={rightOpen} onClick={() => setRightOpen(value => !value)}>
          <PanelRight size={18} />
        </button>
      </div>

      <aside className={css.chapterRail} data-mobile-open={leftOpen}>
        <div className={css.paneHeading}>
          <BookOpen size={15} />{t('creation.chapters')}
          <button type="button" className={`${css.drawerClose} ${css.chapterDrawerClose}`}
            title={t('creation.closePanel')} aria-label={t('creation.closePanel')} onClick={() => setLeftOpen(false)}>
            <X size={15} />
          </button>
        </div>
        <label className={css.chapterSearch}>
          <Search size={14} aria-hidden="true" />
          <span className={css.visuallyHidden}>{t('creation.searchChapters')}</span>
          <input value={chapterQuery} placeholder={t('creation.searchChapters')} aria-label={t('creation.searchChapters')}
            onChange={event => setChapterQuery(event.target.value)} />
          {chapterQuery !== '' && (
            <button type="button" title={t('creation.clearSearch')} aria-label={t('creation.clearSearch')}
              onClick={() => setChapterQuery('')}><X size={13} /></button>
          )}
        </label>
        {readingOrderState === 'loading' && <div className={css.orderNotice} role="status">{t('creation.order.loading')}</div>}
        {readingOrderState === 'error' && <div className={css.orderNotice} data-status="error">
          <span>{t('creation.order.unavailable')}</span>
          <button type="button" title={readingOrderError} onClick={() => setReadingOrderReload(value => value + 1)}>
            <RefreshCw size={12} />{t('creation.order.refresh')}
          </button>
        </div>}
        {readingOrderState === 'ready' && missingChapterCount > 0 && <div className={css.orderNotice}>
          {t('creation.order.missingCount')} {missingChapterCount}
        </div>}
        <div className={css.chapterList}>
          {visibleChapters.map(({ chapter, index }) => (
            <button key={chapter.occurrenceId || `${String(index)}:${chapter.path}`} type="button" className={css.chapterButton} data-active={index === activeChapterIndex}
              aria-current={index === activeChapterIndex ? 'page' : undefined}
              data-duplicate={(duplicateChapterKeys.get(chapter.id) ?? 0) > 1 || (duplicateChapterKeys.get(chapter.path) ?? 0) > 1}
              onClick={() => chooseChapter(chapter.path, chapter.occurrenceId)}>
              <span className={css.chapterIndex}>{String(index + 1).padStart(2, '0')}</span>
              <span className={css.chapterText}>
                <span className={css.chapterTitle}>{chapter.title}</span>
                <span className={css.chapterMeta}>{chapter.subtitle}
                  {((duplicateChapterKeys.get(chapter.id) ?? 0) > 1 || (duplicateChapterKeys.get(chapter.path) ?? 0) > 1)
                    ? ` · ${t('creation.chapterDuplicate')}` : ''}
                </span>
                {chapter.occurrenceId && <span className={css.chapterIdentity}>{chapter.occurrenceId}</span>}
              </span>
            </button>
          ))}
          {visibleChapters.length === 0 && <div className={css.chapterEmpty}>{t('creation.chaptersEmpty')}</div>}
        </div>
        {readingOrder !== null && activeChapter !== undefined && (
          <div className={css.chapterMove}>
            <strong>{t('creation.order.move')}</strong>
            <label><span>{t('creation.order.volume')}</span>
              <select value={moveVolumeId} disabled={moveBusy || !readingOrder.mutation_allowed}
                onChange={event => { setMoveVolumeId(event.target.value); setMoveIndex('0') }}>
                {readingOrder.volumes.map(volume => <option key={volume.volume_id} value={volume.volume_id}>{volume.title}</option>)}
              </select>
            </label>
            <label><span>{t('creation.order.position')}</span>
              <input type="number" min="0" max={moveTargetMax} step="1" value={moveIndex} disabled={moveBusy || !readingOrder.mutation_allowed}
                onChange={event => setMoveIndex(event.target.value)} />
            </label>
            <button type="button" disabled={moveBusy || !readingOrder.mutation_allowed || activeChapter.documentId === ''}
              onClick={() => { void moveActiveChapter() }}>{t('creation.order.applyMove')}</button>
            {!readingOrder.mutation_allowed && <small>{t('creation.order.blocked')}</small>}
            <small>{t('creation.order.positionHelp')} 0–{moveTargetMax}</small>
            {moveNotice !== '' && <small role="status">{moveNotice}</small>}
          </div>
        )}
      </aside>

      <main className={css.editorPane}>
        <header className={css.editorHeader}>
          <div className={css.editorIdentity}>
            <strong>{document_?.title || activeChapter?.title || t('creation.empty')}</strong>
            <span>{path}</span>
            {writingProgress.bookTarget > 0 && <span className={css.writingProgress}
              title={`${t('creation.writing.bookProgress')}: ${String(writingProgress.bookUnits)} / ${String(writingProgress.bookTarget)} · ${t('creation.writing.chapterTarget')}: ${String(writingProgress.chapterTarget)}`}>
              {t('creation.writing.bookProgress')} {writingProgress.bookUnits.toLocaleString()} / {writingProgress.bookTarget.toLocaleString()}
              {workBrief !== null && workBrief.target.writing_units > 0
                ? ` · ${t('creation.writing.chapterProgress')} ${workBrief.target.actual_units.toLocaleString()} / ${workBrief.target.writing_units.toLocaleString()}`
                : writingProgress.chapterTarget > 0 ? ` · ${t('creation.writing.chapterTarget')} ${writingProgress.chapterTarget.toLocaleString()}` : ''}
            </span>}
          </div>
          <div className={css.editorActions}>
            <button type="button" className={css.iconButton} title={t('creation.previousChapter')}
              aria-label={t('creation.previousChapter')}
              disabled={activeChapterIndex <= 0}
              onClick={() => chooseChapter(orderedChapters[activeChapterIndex - 1]?.path ?? '', orderedChapters[activeChapterIndex - 1]?.occurrenceId ?? '')}>
              <ChevronLeft size={17} />
            </button>
            <select className={css.chapterJump} aria-label={t('creation.jumpChapter')}
              value={activeChapterIndex < 0 ? '' : String(activeChapterIndex)}
              onChange={event => {
                const index = Number(event.target.value)
                const chapter = orderedChapters[index]
                if (chapter !== undefined) chooseChapter(chapter.path, chapter.occurrenceId)
              }}>
              {orderedChapters.map((chapter, index) => <option key={chapter.occurrenceId || `${String(index)}:${chapter.path}`} value={String(index)}>
                {String(index + 1).padStart(2, '0')} · {chapter.title}{((duplicateChapterKeys.get(chapter.id) ?? 0) > 1 || (duplicateChapterKeys.get(chapter.path) ?? 0) > 1) ? ` · ${t('creation.chapterDuplicate')}` : ''}
              </option>)}
            </select>
            <button type="button" className={css.iconButton} title={t('creation.nextChapter')}
              aria-label={t('creation.nextChapter')}
              disabled={activeChapterIndex < 0 || activeChapterIndex >= orderedChapters.length - 1}
              onClick={() => chooseChapter(orderedChapters[activeChapterIndex + 1]?.path ?? '', orderedChapters[activeChapterIndex + 1]?.occurrenceId ?? '')}>
              <ChevronRight size={17} />
            </button>
            <button type="button" className={css.commandButton} data-active={readerMode}
              onClick={() => setReaderMode(value => !value)}>
              {readerMode ? t('creation.mode.edit') : t('creation.mode.reader')}
            </button>
            <button type="button" className={`${css.iconButton} ${css.desktopPaneButton}`}
              title={chapterRailVisible ? t('creation.hideChapters') : t('creation.showChapters')}
              aria-label={chapterRailVisible ? t('creation.hideChapters') : t('creation.showChapters')}
              aria-expanded={chapterRailVisible} onClick={toggleChapterRail}>
              {chapterRailVisible ? <PanelLeftClose size={17} /> : <PanelLeftOpen size={17} />}
            </button>
            <button type="button" className={`${css.iconButton} ${css.desktopPaneButton}`}
              title={inspectorVisible ? t('creation.hideInspector') : t('creation.showInspector')}
              aria-label={inspectorVisible ? t('creation.hideInspector') : t('creation.showInspector')}
              aria-expanded={inspectorVisible} onClick={toggleInspector}>
              {inspectorVisible ? <PanelRightClose size={17} /> : <PanelRightOpen size={17} />}
            </button>
            <button type="button" className={`${css.iconButton} ${css.tabletInspectorButton}`}
              title={t('creation.inspector')} aria-label={t('creation.inspector')}
              aria-expanded={rightOpen} onClick={() => setRightOpen(value => !value)}>
              <PanelRight size={17} />
            </button>
            <button type="button" className={css.saveState} data-status={workbench.editorStatus}
              title={workbench.editorMessage || t(`creation.status.${workbench.editorStatus}`)}
              aria-label={t(`creation.status.${workbench.editorStatus}`)} disabled={!hasUnsavedDraft}
              onClick={() => { void save(false, 'manual') }}>
              <Save size={14} />{t(`creation.status.${workbench.editorStatus}`)}
            </button>
          </div>
        </header>

        {!readerMode && (acceptanceState === 'loading' || acceptanceState === 'error' || acceptance !== null) && (
          <section className={css.acceptanceCard} data-status={acceptance?.status ?? acceptanceState}
            aria-label={t('creation.acceptance.title')} aria-live="polite">
            <header className={css.acceptanceHeader}>
              <ShieldAlert size={15} aria-hidden="true" />
              <strong>{t('creation.acceptance.title')}</strong>
              <span>{acceptanceState === 'loading'
                ? t('creation.acceptance.loading')
                : acceptanceState === 'error'
                  ? t('creation.acceptance.unavailable')
                  : t(acceptanceStatusKey(acceptance?.status ?? 'unknown'))}</span>
              <button type="button" title={t('creation.acceptance.refresh')}
                aria-label={t('creation.acceptance.refresh')} disabled={acceptanceBusy !== ''}
                onClick={() => setAcceptanceReload(value => value + 1)}>
                <RefreshCw size={13} />
              </button>
            </header>
            {acceptanceError !== '' && <p className={css.acceptanceError}>{acceptanceError}</p>}
            {acceptance !== null && (
              <>
                {acceptance.message !== '' && <p className={css.acceptanceMessage}>{acceptance.message}</p>}
                <dl className={css.acceptanceDetails}>
                  <div><dt>{t('creation.acceptance.currentRevision')}</dt><dd><code>{acceptance.currentRevision || '—'}</code></dd></div>
                  <div><dt>{t('creation.acceptance.acceptedRevision')}</dt><dd><code>{acceptance.acceptedRevision || '—'}</code></dd></div>
                  {acceptance.operationId !== '' && <div><dt>{t('creation.acceptance.operation')}</dt><dd><code>{acceptance.operationId}</code></dd></div>}
                  {acceptance.impacts.length > 0 && <div><dt>{t('creation.acceptance.stale')}</dt><dd>{acceptance.impacts.join(' · ')}</dd></div>}
                </dl>
                <div className={css.acceptanceActions}>
                  {['baseline_required', 'baseline_pending', 'untracked', 'missing_baseline'].includes(acceptance.status) && (
                    <button type="button" disabled={acceptanceBusy !== ''}
                      onClick={() => { void reconcileAcceptance('baseline') }}>{t('creation.acceptance.baseline')}</button>
                  )}
                  {['drift', 'external', 'external_change'].includes(acceptance.status) && (
                    <button type="button" disabled={acceptanceBusy !== ''}
                      onClick={() => { void reconcileAcceptance('external') }}>{t('creation.acceptance.external')}</button>
                  )}
                  {['pending', 'running', 'analyzing', 'propagating', 'interrupted', 'failed'].includes(acceptance.status) && acceptance.operationId !== '' && (
                    <button type="button" disabled={acceptanceBusy !== ''}
                      onClick={() => { void reconcileAcceptance('resume') }}>{t('creation.acceptance.resume')}</button>
                  )}
                  {acceptance.needsReview && (
                    <button type="button" disabled={acceptanceBusy !== ''}
                      onClick={() => { void reconcileAcceptance('acknowledge') }}>{t('creation.acceptance.acknowledge')}</button>
                  )}
                </div>
              </>
            )}
          </section>
        )}

        {readerMode && <ContinuousReader key={`${workspaceId ?? ''}:${String(workbench.contextEpoch)}:${String(workbench.epochs.manuscript)}`}
          chapters={orderedChapters} activePath={path} activeOccurrenceId={activeOccurrenceId}
          readingOrderRevision={readingOrder?.revision ?? ''} fetchStudioApi={fetchStudioApi}
          onOpenChapter={chooseChapter} t={t} />}
        {!readerMode && documentState === 'loading' && (
          <div className={css.documentSkeleton} role="status" aria-live="polite">
            <span>{t('creation.documentLoading')}</span><i /><i /><i />
          </div>
        )}
        {!readerMode && documentState === 'error' && (
          <div className={css.centerNotice}>
            <span>{loadError}</span>
            <button type="button" className={css.commandButton} onClick={reload}><RefreshCw size={15} />{t('retry')}</button>
          </div>
        )}
        {!readerMode && documentState === 'ready' && document_ !== null && (
          <div className={css.manuscriptEditor} aria-busy={!editorReady && !editorFailed}>
            {recoveryDraft !== null && (
              <section className={css.recoveryBar}
                data-conflict={recoveryDraft.baseRevision !== document_.revision}>
                <ShieldAlert size={16} aria-hidden="true" />
                <div className={css.recoveryBody}>
                  <strong>{t(recoveryDraft.baseRevision === document_.revision
                    ? 'creation.draft.available'
                    : 'creation.draft.conflict')}</strong>
                  <small>{t('creation.draft.updated')} {new Date(recoveryDraft.updatedAt).toLocaleString()}</small>
                  <details>
                    <summary>{t('creation.draft.preview')}</summary>
                    <pre>{recoveryDraft.content}</pre>
                  </details>
                </div>
                <div className={css.recoveryActions}>
                  <button type="button" aria-label={t('creation.draft.restore')}
                    onClick={restoreRecoveryDraft}>{t('creation.draft.restore')}</button>
                  <button type="button" onClick={dismissRecoveryDraft}>{t('creation.draft.dismiss')}</button>
                </div>
              </section>
            )}
            {draftStorageError !== '' && (
              <div className={css.draftStorageError} role="status">
                <ShieldAlert size={15} aria-hidden="true" />
                <span>{draftStorageError}</span>
              </div>
            )}
            {workbench.editorStatus === 'conflict' && (
              <div className={css.conflictBar}>
                <ShieldAlert size={16} />
                <span>{workbench.editorMessage || t('creation.conflict')}</span>
                <button type="button" onClick={reload}>{t('creation.reload')}</button>
                <button type="button" onClick={overwrite}>{t('creation.overwrite')}</button>
              </div>
            )}
            {workbench.editorStatus === 'offline' && hasUnsavedDraft && (
              <div className={css.conflictBar} data-status="offline">
                <ShieldAlert size={16} />
                <span>{workbench.editorMessage || t('creation.status.offline')}</span>
                <button type="button" onClick={() => { void save(false, 'manual') }}>{t('retry')}</button>
              </div>
            )}
            {editorFailed ? (
              <textarea className={css.manuscriptFallback} value={draft} onChange={event => updateDraft(event.target.value)} />
            ) : (
              <VditorBody key={`${path}:${editorEpoch}`} initial={draft} disabled={false} onChange={updateDraft}
                onReady={() => setEditorReady(true)} onFailed={() => { setEditorReady(true); setEditorFailed(true) }} />
            )}
            {!editorReady && !editorFailed && (
              <div className={css.editorBoot} role="status" aria-live="polite">
                <span>{t('creation.editorLoading')}</span><i /><i /><i />
              </div>
            )}
          </div>
        )}
      </main>

      <aside className={css.inspector} data-mobile-open={rightOpen}>
        <div className={css.inspectorHeader}>
          <div className={css.inspectorTabs} role="tablist" aria-label={t('creation.inspector')}>
            {(['context', 'review', 'revisions', 'activity'] as const).map(tab => (
              <button key={tab} type="button" role="tab" aria-selected={inspectorTab === tab}
                data-active={inspectorTab === tab} onClick={() => setInspectorTab(tab)}>
                {tab === 'context' ? t('creation.context')
                  : tab === 'review' ? t('creation.review')
                    : tab === 'revisions' ? t('creation.revisions') : t('creation.activity')}
              </button>
            ))}
          </div>
          <button type="button" className={`${css.drawerClose} ${css.inspectorDrawerClose}`}
            title={t('creation.closePanel')} aria-label={t('creation.closePanel')} onClick={() => setRightOpen(false)}>
            <X size={15} />
          </button>
        </div>
        <div className={css.inspectorBody} role="tabpanel">
          {inspectorTab === 'context' && inspectorState === 'loading' && (
            <div className={css.inspectorSkeleton} role="status" aria-live="polite">
              <span>{inspectorSlow ? t('creation.inspectorLoadingSlow') : t('creation.inspectorLoading')}</span>
              <i /><i /><i /><i />
            </div>
          )}
          {inspectorTab === 'context' && inspectorState === 'error' && (
            <div className={css.inspectorNotice}>
              <span>{inspectorError}</span>
              {inspectorErrorSources.map(source => source.endsWith('/')
                ? <code key={source}>{source}</code>
                : <button key={source} type="button" className={css.commandButton}
                    onClick={() => openContextSource(source)}>{source}</button>)}
              <button type="button" className={css.commandButton} onClick={() => setInspectorReload(value => value + 1)}>
                <RefreshCw size={15} />{t('retry')}
              </button>
            </div>
          )}
          {inspectorTab === 'revisions' && historyState === 'loading' && (
            <div className={css.inspectorSkeleton} role="status" aria-live="polite">
              <span>{t('creation.inspectorLoading')}</span><i /><i /><i /><i />
            </div>
          )}
          {inspectorTab === 'revisions' && historyState === 'error' && (
            <div className={css.inspectorNotice}>
              <span>{historyError}</span>
              <button type="button" className={css.commandButton} onClick={() => setInspectorReload(value => value + 1)}>
                <RefreshCw size={15} />{t('retry')}
              </button>
            </div>
          )}
          {inspectorState === 'ready' && inspectorTab === 'context' && (context === null || context.manifest.items.length === 0
            ? <div className={css.muted}>{t('creation.contextEmpty')}</div>
            : <ContextDocument key={path} context={context} fallbackTitle={t('creation.context')} t={t} onOpenSource={openContextSource} />)}
          {inspectorTab === 'review' && workBrief?.review.latest_closure !== null && workBrief?.review.latest_closure !== undefined && (() => {
            const closure = workBrief.review.latest_closure
            return <section className={css.reviewClosure} aria-label={t('creation.review.closure')}>
              <header>
                <strong>{t('creation.review.closure')}</strong>
                <time>{closure.closed_at === '' ? '' : new Date(closure.closed_at).toLocaleString()}</time>
              </header>
              <small>{t('creation.review.closureProposal')} <code>{closure.proposal_id}</code></small>
              <small>{t('creation.review.closureRevision')} <code>{closure.rereview_review_revision}</code></small>
              <ul>
                {closure.issue_outcomes.map(item => <li key={item.issue_id} data-outcome={item.outcome}>
                  <code>{item.issue_id}</code><b>{t(`creation.review.outcome.${item.outcome}`)}</b>
                </li>)}
                {closure.regressions.map(item => {
                  const issue = record(item.issue)
                  return <li key={`regression:${item.issue_id}`} data-outcome="regressed">
                    <code>{item.issue_id}</code><b>{t('creation.review.outcome.regressed')}</b>
                    {String(issue['description'] ?? issue['summary'] ?? '') !== '' && <span>{String(issue['description'] ?? issue['summary'])}</span>}
                  </li>
                })}
              </ul>
            </section>
          })()}
          {inspectorTab === 'review' && (
            activeChapter?.review.issueDetails.length ? (
              <div className={css.issueList}>
                <div className={css.reviewSummary}>{activeChapter.review.score ?? '--'} / 100 · {activeChapter.review.issues} {t('creation.issues')}</div>
                {reviewStale && <div className={css.reviewStale} role="status">
                  <ShieldAlert size={14} />{t('creation.review.stale')}
                </div>}
                {!reviewStale && !reviewCasReady && <div className={css.reviewStale} role="status">
                  <ShieldAlert size={14} />{t('creation.review.casUnavailable')}
                </div>}
                {activeChapter.review.issueDetails.map((raw, index) => {
                  const issue = record(raw)
                  const issueId = String(issue['id'] ?? '')
                  const selected = selectedReviewIssueIds.includes(issueId)
                  return <label key={issueId || String(index)} className={css.issue}>
                    <input type="checkbox" checked={selected} disabled={issueId === '' || !reviewCasReady || reviewTaskBusy !== ''}
                      onChange={() => setSelectedReviewIssueIds(previous => selected
                        ? previous.filter(id => id !== issueId)
                        : [...previous, issueId])} />
                    <span>{String(issue['severity'] ?? '')} · {String(issue['category'] ?? '')}</span>
                    <strong>{String(issue['description'] ?? issue['summary'] ?? '')}</strong>
                    {typeof issue['suggestion'] === 'string' && <p>{issue['suggestion']}</p>}
                  </label>
                })}
                <div className={css.reviewRevisionActions}>
                  <small>{t('creation.review.selectionSummary')}
                    {' '}{String(selectedReviewIssueIds.length)} / {String(activeChapter.review.issueDetails.length)}
                  </small>
                  <textarea value={reviewInstruction} disabled={!reviewCasReady || reviewTaskBusy !== ''}
                    placeholder={t('creation.review.instruction')}
                    onChange={event => setReviewInstruction(event.target.value)} />
                  <div>
                    <button type="button" disabled={!reviewCasReady || selectedReviewIssueIds.length === 0 || reviewTaskBusy !== ''}
                      onClick={() => { void launchReviewTask('revision') }}>{t('creation.review.createRevision')}</button>
                    <button type="button" disabled={reviewTaskBusy !== ''}
                      onClick={() => { void launchReviewTask('rereview') }}>{t('creation.review.rereview')}</button>
                  </div>
                  {reviewTaskNotice !== '' && <p role="status">{reviewTaskNotice}</p>}
                </div>
              </div>
            ) : <div className={css.muted}>{t('creation.reviewEmpty')}</div>
          )}
          {inspectorTab === 'activity' && workBriefState === 'loading' && (
            <div className={css.inspectorSkeleton} role="status" aria-live="polite">
              <span>{t('creation.activity.loading')}</span><i /><i /><i /><i />
            </div>
          )}
          {inspectorTab === 'activity' && workBriefState === 'error' && (
            <div className={css.inspectorNotice}>
              <span>{t('creation.activity.unavailable')}</span>
              {workBriefError !== '' && <code>{workBriefError}</code>}
              <button type="button" className={css.commandButton} onClick={() => setWorkBriefReload(value => value + 1)}>
                <RefreshCw size={15} />{t('retry')}
              </button>
            </div>
          )}
          {inspectorTab === 'activity' && workBriefState === 'ready' && workBrief !== null && (
            <div className={css.activityPane}>
              <section className={css.activityCard}>
                <strong>{t('creation.activity.target')}</strong>
                <div className={css.activityProgress} role="progressbar" aria-valuemin={0} aria-valuemax={100}
                  aria-valuenow={Math.round(Math.max(0, Math.min(1, workBrief.target.progress)) * 100)}>
                  <i style={{ width: `${String(Math.max(0, Math.min(1, workBrief.target.progress)) * 100)}%` }} />
                </div>
                <span>{workBrief.target.actual_units.toLocaleString()} / {workBrief.target.writing_units.toLocaleString()}
                  {' · '}{t('creation.activity.remaining')} {workBrief.target.remaining_units.toLocaleString()}</span>
                <small>{workBrief.target.source}</small>
              </section>
              <section className={css.activityCard}>
                <strong>{t('creation.activity.identity')}</strong>
                <dl>
                  <div><dt>{t('creation.reader.documentId')}</dt><dd><code>{workBrief.document_id || '—'}</code></dd></div>
                  <div><dt>{t('creation.reader.revision')}</dt><dd><code>{workBrief.manuscript.current_revision || '—'}</code></dd></div>
                  <div><dt>{t('creation.proposals.reviewRevision')}</dt><dd><code>{workBrief.review.review_revision || '—'}</code></dd></div>
                </dl>
              </section>
              <section className={css.activityCard}>
                <strong>{t('creation.activity.recent')}</strong>
                {workBrief.recent_edits.length === 0
                  ? <span>{t('creation.activity.empty')}</span>
                  : <ol className={css.activityList}>{workBrief.recent_edits.map((event, index) => (
                    <li key={`${event.kind}:${event.id}:${event.revision}:${String(index)}`}>
                      <header><b>{event.kind}</b><span>{event.status}</span></header>
                      <time>{new Date(event.updated_at).toLocaleString()}</time>
                      {event.revision !== '' && <code>{event.revision}</code>}
                      {event.writing_units_delta !== null && <small>{event.writing_units_delta >= 0 ? '+' : ''}{event.writing_units_delta} {t('creation.history.units')}</small>}
                      {event.reason !== '' && <p>{event.reason}</p>}
                    </li>
                  ))}</ol>}
              </section>
            </div>
          )}
          {historyState === 'ready' && inspectorTab === 'revisions' && (
            <div className={css.revisionPane}>
              <section className={css.historySection}>
                <header className={css.historyHeader}>
                  <strong><History size={15} />{t('creation.history.title')}</strong>
                  <button type="button" disabled={historyBusy !== ''}
                    onClick={() => { void createNamedSnapshot() }}>{t('creation.history.snapshot')}</button>
                </header>
                {versions.length === 0
                  ? <div className={css.muted}>{t('creation.history.empty')}</div>
                  : <div className={css.versionList}>{versions.map(version => (
                    <article key={version.versionId} className={css.versionCard}>
                      <div>
                        <strong>{version.label || versionReason(version.reason)}</strong>
                        <span>{versionReason(version.reason)} · {new Date(version.createdAt).toLocaleString()}</span>
                        <small>{version.writingUnits} {t('creation.history.units')} · {version.sourceRevision.slice(0, 18)}</small>
                      </div>
                      <button type="button" disabled={historyBusy !== ''}
                        onClick={() => { void previewVersion(version.versionId) }}>
                        {historyBusy === version.versionId ? t('creation.history.loading') : t('creation.history.compare')}
                      </button>
                    </article>
                  ))}</div>}
                {versionPreview !== null && (
                  <div className={css.versionPreview}>
                    <header>
                      <strong>{t('creation.history.restorePreview')}</strong>
                      <button type="button" aria-label={t('creation.history.closePreview')}
                        onClick={() => setVersionPreview(null)}><X size={14} /></button>
                    </header>
                    <span>{versionPreview.version.label || versionReason(versionPreview.version.reason)}</span>
                    <div className={css.diffList}>
                      {versionPreview.segments.filter(segment => segment.tag !== 'equal').length === 0
                        ? <div className={css.muted}>{t('creation.history.noChanges')}</div>
                        : versionPreview.segments.filter(segment => segment.tag !== 'equal').map((segment, index) => (
                          <div key={segment.id || String(index)} className={css.diffBlock}>
                            {segment.before !== '' && <pre data-side="before">− {segment.before}</pre>}
                            {segment.after !== '' && <pre data-side="after">+ {segment.after}</pre>}
                          </div>
                        ))}
                    </div>
                    <button type="button" className={css.dangerAction} disabled={historyBusy !== ''}
                      onClick={() => { void restoreVersion() }}>{t('creation.history.restore')}</button>
                  </div>
                )}
              </section>

              <section className={css.historySection}>
                <header className={css.historyHeader}>
                  <strong>{t('creation.proposals.title')}</strong>
                </header>
                {revisionProposals.length === 0
                  ? <div className={css.muted}>{t('creation.revisionsEmpty')}</div>
                  : <div className={css.proposalList}>{revisionProposals.map(proposal => {
                    const selected = revisionSelections[proposal.proposalId] ?? []
                    return <article key={proposal.proposalId} className={css.proposalCard}>
                      <header>
                        <strong>{proposal.kind}</strong>
                        <span data-status={proposal.status}>{proposal.status}</span>
                      </header>
                      <p>{proposal.rationale || t('creation.proposals.noRationale')}</p>
                      <small>{t('creation.proposals.range')} {proposal.start}–{proposal.end}</small>
                      {proposal.reviewIssueIds.length > 0 && <small>
                        {t('creation.proposals.evidence')} {proposal.reviewIssueIds.join(', ')}
                      </small>}
                      {proposal.reviewRevision !== '' && <small>
                        {t('creation.proposals.reviewRevision')} <code>{proposal.reviewRevision}</code>
                      </small>}
                      {proposal.sourceRevision !== '' && <small>
                        {t('creation.proposals.sourceRevision')} <code>{proposal.sourceRevision}</code>
                      </small>}
                      {proposal.issueHunkProvenance.length > 0 && <div className={css.proposalProvenance}>
                        {proposal.issueHunkProvenance.map(item => <small key={item.issueId}>
                          {item.issueId} → {item.hunkIds.join(', ') || t('creation.proposals.noHunks')}
                        </small>)}
                      </div>}
                      <details>
                        <summary>{t('creation.proposals.originalCandidate')}</summary>
                        <div className={css.proposalTexts}>
                          <pre data-side="before">{proposal.originalText}</pre>
                          <pre data-side="after">{proposal.replacementText}</pre>
                        </div>
                      </details>
                      {proposal.hunks.length > 0 && <div className={css.proposalHunks}>
                        {proposal.hunks.map(hunk => <label key={hunk.id}>
                          <input type="checkbox" checked={selected.includes(hunk.id)}
                            disabled={proposal.status !== 'proposed' || historyBusy !== ''}
                            onChange={() => toggleRevisionHunk(proposal.proposalId, hunk.id)} />
                          <span>
                            {hunk.before !== '' && <del>{hunk.before}</del>}
                            {hunk.after !== '' && <ins>{hunk.after}</ins>}
                          </span>
                        </label>)}
                      </div>}
                      <footer>
                        <button type="button" disabled={proposal.status !== 'proposed' || historyBusy !== ''}
                          onClick={() => { void runRevisionAction(proposal, 'reject') }}>{t('creation.proposals.reject')}</button>
                        <button type="button" disabled={proposal.status === 'applied' || historyBusy !== ''}
                          onClick={() => { void runRevisionAction(proposal, 'regenerate') }}>{t('creation.proposals.regenerate')}</button>
                        <button type="button" disabled={proposal.status !== 'proposed' || selected.length === 0 || historyBusy !== ''}
                          onClick={() => { void runRevisionAction(proposal, 'apply') }}>{t('creation.proposals.applySelected')}</button>
                      </footer>
                    </article>
                  })}</div>}
              </section>
              {historyNotice !== '' && <div className={css.historyNotice} role="status">{historyNotice}</div>}
            </div>
          )}
        </div>
      </aside>
      {(leftOpen || rightOpen) && <button type="button" aria-label={t('creation.closePanel')} className={css.scrim} onClick={() => { setLeftOpen(false); setRightOpen(false) }} />}
    </div>
  )
}
