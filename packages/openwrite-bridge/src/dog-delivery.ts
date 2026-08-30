import { createHash, randomUUID } from 'node:crypto'
import { mkdir, readdir, readFile, rename, rm, stat, writeFile } from 'node:fs/promises'
import { basename, dirname, join, relative } from 'node:path'
import type { JsonValue } from './client.js'

type RecordValue = Record<string, unknown>

const HARD_SEVERITIES = new Set(['critical', 'blocker'])

function record(value: unknown): RecordValue {
  return value !== null && typeof value === 'object' && !Array.isArray(value) ? value as RecordValue : {}
}

function values(value: unknown): unknown[] {
  return Array.isArray(value) ? value : []
}

function strings(value: unknown): string[] {
  return values(value).map(item => String(item)).filter(Boolean)
}

/** Read an artifact. Only a missing file is tolerated (undefined); corrupt
 * JSON, non-object roots, and empty objects are contract failures so a
 * malformed artifact can never masquerade as an absent one. */
async function readJson(path: string): Promise<RecordValue | undefined> {
  let text: string
  try {
    text = await readFile(path, 'utf8')
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === 'ENOENT') return undefined
    throw new Error(`DoG artifact unreadable: ${basename(path)}`)
  }
  let parsed: unknown
  try {
    parsed = JSON.parse(text)
  } catch {
    throw new Error(`DoG artifact corrupt JSON: ${basename(path)}`)
  }
  if (parsed === null || typeof parsed !== 'object' || Array.isArray(parsed)) {
    throw new Error(`DoG artifact root must be a JSON object: ${basename(path)}`)
  }
  const value = parsed as RecordValue
  if (Object.keys(value).length === 0) {
    throw new Error(`DoG artifact empty object: ${basename(path)}`)
  }
  return value
}

async function atomicWrite(path: string, value: unknown): Promise<void> {
  await mkdir(dirname(path), { recursive: true })
  const temporary = join(dirname(path), `.${basename(path)}.${process.pid}.${randomUUID()}`)
  try {
    await writeFile(temporary, `${JSON.stringify(value, null, 2)}\n`, 'utf8')
    await rename(temporary, path)
  } catch (error) {
    await rm(temporary, { force: true })
    throw error
  }
}

async function findNamedFiles(root: string, filename: string): Promise<string[]> {
  const found: string[] = []
  async function walk(directory: string): Promise<void> {
    let entries
    try {
      entries = await readdir(directory, { withFileTypes: true })
    } catch {
      return
    }
    for (const entry of entries) {
      const path = join(directory, entry.name)
      if (entry.isDirectory()) await walk(path)
      else if (entry.isFile() && entry.name === filename) found.push(path)
    }
  }
  await walk(root)
  return found
}

function reviewSeverity(issue: RecordValue): string {
  return String(issue['review_severity'] ?? issue['legacy_severity'] ?? issue['severity'] ?? 'warning').toLowerCase()
}

/** v1-only adapter: derive delivery from legacy score/passed/severity. Never
 * used when review_v2 is present; v2 records carry OpenWrite's canonical
 * delivery_status. */
function legacyDeliveryStatus(review: RecordValue, threshold: number): string {
  const hard = values(review['issue_details']).some(item => HARD_SEVERITIES.has(reviewSeverity(record(item))))
  if (hard) return 'blocked'
  if (review['passed'] === false) return 'revise'
  return Number(review['score'] ?? 0) >= threshold ? 'pass' : 'revise'
}

function deliveryStatus(review: RecordValue, threshold: number): string {
  const v2 = record(review['review_v2'])
  if (Object.keys(v2).length > 0) return String(v2['delivery_status'] ?? 'inconclusive').toLowerCase()
  return legacyDeliveryStatus(review, threshold)
}

function stage(chapterId: string, name: string, verdict: string, status: string, evidence: RecordValue): RecordValue {
  return {
    schemaVersion: 'dsh-novel.delivery.stage.v2', recordType: 'delivery-stage',
    chapterId, stage: name, verdict, status, evidence,
  }
}

/** Rebuild a chapter-delivery graph from canonical manuscript, review and revision records. */
export async function materializeChapterDelivery(
  workspaceValue: unknown,
  chapterId: string,
  threshold?: number,
): Promise<JsonValue> {
  const workspace = record(workspaceValue)
  const project = record(workspace['project'])
  const snapshot = record(workspace['snapshot'])
  const root = String(project['root'] ?? '').trim()
  const novelId = String(snapshot['novel_id'] ?? '').trim()
  if (!root || !novelId) throw new Error('chapter delivery lacks workspace project root or novel_id')
  if (!/^ch_\d+$/.test(chapterId)) throw new Error(`invalid chapter id for delivery graph: ${chapterId}`)
  try {
    if (!(await stat(root)).isDirectory()) throw new Error('not a directory')
  } catch {
    throw new Error(`chapter delivery project root is not a directory: ${root}`)
  }

  const novelRoot = join(root, 'data', 'novels', novelId)
  const relativeDir = join('data', 'novels', novelId, 'data', 'dog', 'deliveries', chapterId).replaceAll('\\', '/')
  const directory = join(root, relativeDir)
  const previous = await readJson(join(directory, 'delivery.json')) ?? {}
  const effectiveThreshold = threshold ?? Number(previous['threshold'] ?? 70)
  if (!Number.isInteger(effectiveThreshold) || effectiveThreshold < 0 || effectiveThreshold > 100) {
    throw new Error('delivery threshold must be an integer between 0 and 100')
  }

  const manuscripts = await findNamedFiles(join(novelRoot, 'data', 'manuscript'), `${chapterId}.md`)
  const manuscript = manuscripts.length === 1 ? manuscripts[0] : undefined
  const fallback = join(novelRoot, 'data', 'manuscript', 'arc_001', `${chapterId}.md`)
  const manuscriptTarget = relative(root, manuscript ?? fallback).replaceAll('\\', '/')
  let currentRevision = ''
  if (manuscript !== undefined) {
    currentRevision = `sha256:${createHash('sha256').update(await readFile(manuscript)).digest('hex')}`
  }

  const review = await readJson(join(novelRoot, 'data', 'reviews', `${chapterId}.json`)) ?? {}
  // Existence/type/version policy, mirroring Python review_store: a present
  // review_v2 key (even null) must be a non-empty JSON object declaring the
  // supported schema version; only records without the key ride the legacy
  // v1 adapter.
  const rawV2 = review['review_v2']
  if (rawV2 !== undefined) {
    if (rawV2 === null || typeof rawV2 !== 'object' || Array.isArray(rawV2)) {
      throw new Error(`review_v2 must be a JSON object when present, got ${rawV2 === null ? 'null' : typeof rawV2}`)
    }
    const versionProbe = rawV2 as RecordValue
    if (Object.keys(versionProbe).length === 0) {
      throw new Error('review_v2 empty object: unsupported or missing schema version')
    }
    if (versionProbe['schema_version'] !== 'openwrite.review.v2') {
      throw new Error(`unsupported review_v2 schema version: ${String(versionProbe['schema_version'])}`)
    }
  }
  const reviewSourceRevision = String(review['source_revision'] ?? '')
  const reviewStale = Boolean(review['stale'])
    || (Object.keys(review).length > 0 && currentRevision !== '' && reviewSourceRevision !== currentRevision)
  const reviewCurrent = Object.keys(review).length > 0 && currentRevision !== '' && !reviewStale
  const currentDeliveryStatus = Object.keys(review).length > 0 ? deliveryStatus(review, effectiveThreshold) : 'inconclusive'
  const reviewPassed = reviewCurrent && currentDeliveryStatus === 'pass'
  const issues = values(review['issue_details']).map(record).filter(item => Object.keys(item).length > 0)
  const issueIds = issues.map(item => String(item['id'] ?? '')).filter(Boolean)
  const hardIssueIds = issues
    .filter(item => HARD_SEVERITIES.has(reviewSeverity(item)))
    .map(item => String(item['id'] ?? '')).filter(Boolean)

  const revisionDir = join(novelRoot, 'data', 'revisions', chapterId)
  let proposalNames: string[] = []
  try {
    proposalNames = (await readdir(revisionDir)).filter(name => /^rev_.*\.json$/.test(name)).sort()
  } catch {
    proposalNames = []
  }
  const proposalRecords = await Promise.all(proposalNames.map(name => readJson(join(revisionDir, name))))
  const proposals = proposalRecords.filter((item): item is RecordValue => item !== undefined && item['kind'] === 'review_fix')
  const applied = proposals.filter(item => item['status'] === 'applied')
  const pending = proposals.filter(item => item['status'] === 'proposed')
  const appliedToCurrent = applied.filter(item => String(item['applied_revision'] ?? '') === currentRevision)

  const writingStage = stage(chapterId, 'writing', currentRevision !== '' ? 'pass' : 'inconclusive', currentRevision !== '' ? 'committed' : 'missing', {
    manuscriptTarget, currentRevision,
  })
  let reviewStage: RecordValue
  if (Object.keys(review).length === 0) {
    reviewStage = stage(chapterId, 'review', 'inconclusive', 'missing', {})
  } else if (!reviewCurrent) {
    reviewStage = stage(chapterId, 'review', 'inconclusive', reviewStale ? 'stale' : 'unverifiable', {
      sourceRevision: reviewSourceRevision, currentRevision, staleReason: review['stale_reason'] ?? null,
    })
  } else {
    const v2 = record(review['review_v2'])
    reviewStage = stage(chapterId, 'review', reviewPassed ? 'pass' : ['inconclusive', 'stale'].includes(currentDeliveryStatus) ? 'inconclusive' : 'fail', 'current', {
      score: review['score'] ?? null, threshold: effectiveThreshold, passedGate: reviewPassed,
      qualityScore: v2['quality_score'] ?? review['score'] ?? null, coverage: v2['coverage'] ?? 1,
      gateStatus: v2['gate_status'] ?? (hardIssueIds.length > 0 ? 'blocked' : 'pass'),
      deliveryStatus: currentDeliveryStatus,
      issueIds, hardIssueIds, sourceRevision: reviewSourceRevision,
    })
  }

  let revisionStage: RecordValue
  if (reviewPassed) {
    revisionStage = stage(chapterId, 'revision', 'pass', 'not_required', {
      appliedProposalIds: applied.map(item => String(item['proposal_id'] ?? '')).filter(Boolean),
    })
  } else if (reviewStale && appliedToCurrent.length > 0) {
    revisionStage = stage(chapterId, 'revision', 'pass', 'applied_requires_rereview', {
      appliedProposalIds: appliedToCurrent.map(item => String(item['proposal_id'] ?? '')).filter(Boolean),
      addressedIssueIds: [...new Set(appliedToCurrent.flatMap(item => strings(item['review_issue_ids'])))].sort(),
    })
  } else if (pending.length > 0) {
    revisionStage = stage(chapterId, 'revision', 'inconclusive', 'proposal_pending', {
      proposalIds: pending.map(item => String(item['proposal_id'] ?? '')).filter(Boolean), requiredIssueIds: issueIds,
    })
  } else {
    revisionStage = stage(chapterId, 'revision', 'inconclusive', 'revision_required', { requiredIssueIds: issueIds })
  }

  let applicationStage: RecordValue
  if (reviewPassed && appliedToCurrent.length === 0) {
    applicationStage = stage(chapterId, 'application', 'pass', 'not_required', {})
  } else if (appliedToCurrent.length > 0) {
    applicationStage = stage(chapterId, 'application', 'pass', 'applied', {
      proposalIds: appliedToCurrent.map(item => String(item['proposal_id'] ?? '')).filter(Boolean), appliedRevision: currentRevision,
    })
  } else if (pending.length > 0) {
    applicationStage = stage(chapterId, 'application', 'inconclusive', 'awaiting_application', {
      proposalIds: pending.map(item => String(item['proposal_id'] ?? '')).filter(Boolean),
    })
  } else {
    applicationStage = stage(chapterId, 'application', 'inconclusive', 'waiting_for_revision', {})
  }

  let rereviewStage: RecordValue
  const rereviewAfterApplication = appliedToCurrent.length > 0 && reviewCurrent && reviewSourceRevision === currentRevision
  if (rereviewAfterApplication) {
    rereviewStage = stage(chapterId, 'rereview', reviewPassed ? 'pass' : 'fail', 'completed', {
      sourceRevision: reviewSourceRevision, deliveryStatus: currentDeliveryStatus,
    })
  } else if (appliedToCurrent.length > 0) {
    rereviewStage = stage(chapterId, 'rereview', 'inconclusive', 'required', { currentRevision })
  } else if (reviewPassed) {
    rereviewStage = stage(chapterId, 'rereview', 'pass', 'not_required', {})
  } else {
    rereviewStage = stage(chapterId, 'rereview', 'inconclusive', 'waiting_for_application', {})
  }

  let closureStage: RecordValue
  if (reviewPassed) {
    const delta = record(review['issue_delta'])
    closureStage = stage(chapterId, 'closure', 'pass', 'closed', {
      score: review['score'] ?? null, sourceRevision: reviewSourceRevision,
      resolvedIssueIds: values(delta['resolved']).map(record).map(item => String(item['id'] ?? '')).filter(Boolean),
    })
  } else if (reviewStale && appliedToCurrent.length > 0) {
    closureStage = stage(chapterId, 'closure', 'inconclusive', 'rereview_required', {
      currentRevision, appliedProposalIds: appliedToCurrent.map(item => String(item['proposal_id'] ?? '')).filter(Boolean),
    })
  } else if (reviewCurrent) {
    closureStage = stage(chapterId, 'closure', 'fail', 'review_failed', {
      score: review['score'] ?? null, threshold: effectiveThreshold, issueIds, hardIssueIds,
    })
  } else {
    closureStage = stage(chapterId, 'closure', 'inconclusive', 'review_required', {})
  }

  const stages = {
    writing: writingStage, review: reviewStage, revision: revisionStage,
    application: applicationStage, rereview: rereviewStage, closure: closureStage,
  }
  await Promise.all(Object.entries(stages).map(([name, value]) => atomicWrite(join(directory, `${name}.json`), value)))
  const manifest = {
    schemaVersion: 'dsh-novel.delivery.manifest.v2', recordType: 'chapter-delivery',
    chapterId, novelId, threshold: effectiveThreshold, manuscriptTarget, currentRevision,
    readyForDelivery: currentRevision !== '' && closureStage['verdict'] === 'pass', verdict: closureStage['verdict'], stages,
    decisionSource: Object.keys(record(review['review_v2'])).length > 0 ? 'v2' : 'v1-adapter',
    revisionTrail: proposals.map(item => ({
      proposalId: String(item['proposal_id'] ?? ''), status: String(item['status'] ?? ''),
      issueIds: strings(item['review_issue_ids']), sourceRevision: String(item['source_revision'] ?? ''),
      appliedRevision: String(item['applied_revision'] ?? ''),
    })),
  }
  await atomicWrite(join(directory, 'delivery.json'), manifest)

  const nodes: RecordValue = {
    root: {
      kind: 'composite', title: `${chapterId} 章节交付`, constraint: 'hard', target: `${relativeDir}/delivery.json`,
      completion: { op: 'all', items: Object.keys(stages).map(id => ({ op: 'ref', id })) },
      verifier: { mode: 'programmatic', script: 'delivery-stage' },
    },
  }
  const stageTitles: Array<[string, string]> = [
    ['writing', '正文已成形'], ['review', '当前正文已评审'], ['revision', '修订提案已生成'],
    ['application', '修订已应用'], ['rereview', '新正文已复评'], ['closure', '问题经复评关闭'],
  ]
  for (const [name, title] of stageTitles) {
    nodes[name] = {
      kind: 'leaf', title, constraint: 'hard', target: `${relativeDir}/${name}.json`,
      verifier: { mode: 'programmatic', script: 'delivery-stage' },
    }
  }
  const graph = {
    schemaVersion: '0.9', id: `novel-delivery-${chapterId}`, root: 'root', nodes,
    contains: Object.keys(stages).map(child => ({ parent: 'root', child, required: true, failure: 'fatal' })),
    dependsOn: [
      { source: 'review', target: 'writing', data: ['manuscript'] },
      { source: 'revision', target: 'review', data: ['review'] },
      { source: 'application', target: 'revision', data: ['revision'] },
      { source: 'rereview', target: 'application', data: ['application'] },
      { source: 'closure', target: 'rereview', data: ['rereview'] },
    ],
  }
  const graphPath = join(directory, 'dog-graph.json')
  await atomicWrite(graphPath, graph)
  return {
    status: 'ready', manifestPath: join(directory, 'delivery.json'), graphPath,
    graphTarget: relative(root, graphPath), readyForDelivery: manifest.readyForDelivery,
    stages: Object.fromEntries(Object.entries(stages).map(([name, value]) => [name, value['status']])),
  } as unknown as JsonValue
}
