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

async function readJson(path: string): Promise<RecordValue> {
  try {
    return record(JSON.parse(await readFile(path, 'utf8')))
  } catch {
    return {}
  }
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

function gatePassed(review: RecordValue, threshold: number): boolean {
  const score = Number(review['score'] ?? 0)
  const hard = values(review['issue_details']).some(item =>
    HARD_SEVERITIES.has(String(record(item)['severity'] ?? '').toLowerCase()))
  return Number.isFinite(score) && score >= threshold && !hard
}

function stage(chapterId: string, name: string, verdict: string, status: string, evidence: RecordValue): RecordValue {
  return {
    schemaVersion: 'dsh-novel.delivery.stage.v1', recordType: 'delivery-stage',
    chapterId, stage: name, verdict, status, evidence,
  }
}

/** Rebuild a chapter-delivery graph from canonical manuscript, review and revision records. */
export async function materializeChapterDelivery(
  workspaceValue: unknown,
  chapterId: string,
  threshold?: number,
): Promise<JsonValue> {
  if (!/^ch_\d+$/.test(chapterId)) throw new Error(`invalid chapter id for delivery graph: ${chapterId}`)
  const workspace = record(workspaceValue)
  const project = record(workspace['project'])
  const snapshot = record(workspace['snapshot'])
  const root = String(project['root'] ?? '').trim()
  const novelId = String(snapshot['novel_id'] ?? '').trim()
  if (!root || !novelId) throw new Error('chapter delivery lacks workspace project root or novel_id')
  try {
    if (!(await stat(root)).isDirectory()) throw new Error('not a directory')
  } catch {
    throw new Error(`chapter delivery project root is not a directory: ${root}`)
  }

  const novelRoot = join(root, 'data', 'novels', novelId)
  const relativeDir = join('data', 'novels', novelId, 'data', 'dog', 'deliveries', chapterId).replaceAll('\\', '/')
  const directory = join(root, relativeDir)
  const previous = await readJson(join(directory, 'delivery.json'))
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

  const review = await readJson(join(novelRoot, 'data', 'reviews', `${chapterId}.json`))
  const reviewSourceRevision = String(review['source_revision'] ?? '')
  const reviewStale = Boolean(review['stale'])
    || (Object.keys(review).length > 0 && currentRevision !== '' && reviewSourceRevision !== currentRevision)
  const reviewCurrent = Object.keys(review).length > 0 && currentRevision !== '' && !reviewStale
  const reviewPassed = reviewCurrent && gatePassed(review, effectiveThreshold)
  const issues = values(review['issue_details']).map(record).filter(item => Object.keys(item).length > 0)
  const issueIds = issues.map(item => String(item['id'] ?? '')).filter(Boolean)
  const hardIssueIds = issues
    .filter(item => HARD_SEVERITIES.has(String(item['severity'] ?? '').toLowerCase()))
    .map(item => String(item['id'] ?? '')).filter(Boolean)

  const revisionDir = join(novelRoot, 'data', 'revisions', chapterId)
  let proposalNames: string[] = []
  try {
    proposalNames = (await readdir(revisionDir)).filter(name => /^rev_.*\.json$/.test(name)).sort()
  } catch {
    proposalNames = []
  }
  const proposals = (await Promise.all(proposalNames.map(name => readJson(join(revisionDir, name)))))
    .filter(item => item['kind'] === 'review_fix')
  const applied = proposals.filter(item => item['status'] === 'applied')
  const pending = proposals.filter(item => item['status'] === 'proposed')
  const appliedToCurrent = applied.filter(item => String(item['applied_revision'] ?? '') === currentRevision)

  let reviewStage: RecordValue
  if (Object.keys(review).length === 0) {
    reviewStage = stage(chapterId, 'review', 'inconclusive', 'missing', {})
  } else if (!reviewCurrent) {
    reviewStage = stage(chapterId, 'review', 'inconclusive', reviewStale ? 'stale' : 'unverifiable', {
      sourceRevision: reviewSourceRevision, currentRevision, staleReason: review['stale_reason'] ?? null,
    })
  } else {
    reviewStage = stage(chapterId, 'review', 'pass', 'current', {
      score: review['score'] ?? null, threshold: effectiveThreshold, passedGate: reviewPassed,
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

  const stages = { review: reviewStage, revision: revisionStage, closure: closureStage }
  await Promise.all(Object.entries(stages).map(([name, value]) => atomicWrite(join(directory, `${name}.json`), value)))
  const manifest = {
    schemaVersion: 'dsh-novel.delivery.manifest.v1', recordType: 'chapter-delivery',
    chapterId, novelId, threshold: effectiveThreshold, manuscriptTarget, currentRevision,
    readyForDelivery: currentRevision !== '' && closureStage['verdict'] === 'pass', stages,
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
      completion: { op: 'all', items: ['manuscript', 'review', 'revision', 'closure'].map(id => ({ op: 'ref', id })) },
      verifier: {
        mode: 'agentic',
        instruction: '只检查章节交付 manifest 的整体自洽性：正文、当前评审、修订应用与复评关闭是否形成完整链路。不要修改文件，也不要重新进行 37 维正文审查。',
      },
    },
    manuscript: {
      kind: 'leaf', title: '正文已成形', constraint: 'hard', target: manuscriptTarget,
      verifier: { mode: 'programmatic', script: 'import-chapter' },
    },
  }
  const stageTitles: Array<[string, string]> = [
    ['review', '当前正文已评审'], ['revision', '修订动作已结算'], ['closure', '问题经复评关闭'],
  ]
  for (const [name, title] of stageTitles) {
    nodes[name] = {
      kind: 'leaf', title, constraint: 'hard', target: `${relativeDir}/${name}.json`,
      verifier: { mode: 'programmatic', script: 'delivery-stage' },
    }
  }
  const graph = {
    schemaVersion: '0.9', id: `novel-delivery-${chapterId}`, root: 'root', nodes,
    contains: ['manuscript', 'review', 'revision', 'closure'].map(child => ({ parent: 'root', child, required: true, failure: 'fatal' })),
    dependsOn: [
      { source: 'review', target: 'manuscript', data: ['manuscript'] },
      { source: 'revision', target: 'review', data: ['review'] },
      { source: 'closure', target: 'revision', data: ['revision'] },
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
