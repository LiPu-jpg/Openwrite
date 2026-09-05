import { createHash } from 'node:crypto'
import { mkdir, readdir, readFile, stat, writeFile } from 'node:fs/promises'
import { join, relative } from 'node:path'
import type { JsonValue } from './client.js'
import { validateReviewV2Decision } from './contracts-generated.js'
import { assertContained, assertWorkspaceRootMatch } from './dog-delivery.js'

type RecordValue = Record<string, unknown>

export const DOG_REVIEW_DIMENSIONS: Readonly<Record<number, string>> = {
  1: 'OOC检查', 2: '时间线检查', 3: '设定冲突', 4: '战力崩坏', 5: '数值检查',
  6: '伏笔检查', 7: '节奏检查', 8: '文风检查', 9: '信息越界', 10: '词汇疲劳',
  11: '利益链断裂', 12: '年代考据', 13: '配角降智', 14: '配角工具人化', 15: '爽点虚化',
  16: '台词失真', 17: '流水账', 18: '知识库污染', 19: '视角一致性', 20: '段落等长',
  21: '套话密度', 22: '公式化转折', 23: '列表式结构', 24: '支线停滞', 25: '弧线平坦',
  26: '节奏单调', 27: '敏感词检查', 28: '正传事件冲突', 29: '未来信息泄露',
  30: '世界规则跨书一致性', 31: '番外伏笔隔离', 32: '读者期待管理', 33: '大纲偏离检测',
  34: '角色还原度', 35: '世界规则遵守', 36: '关系动态', 37: '正典事件一致性',
}

export const DOG_REVIEW_DOMAINS = [
  { id: 'coherence', name: '连贯与逻辑', weight: 20, legacyCheckIds: [2, 3, 4, 5, 9, 11, 35] },
  { id: 'character', name: '角色与关系', weight: 15, legacyCheckIds: [1, 13, 14, 16, 34, 36] },
  { id: 'plot', name: '情节与承诺', weight: 20, legacyCheckIds: [6, 15, 24, 25, 32, 33] },
  { id: 'pacing', name: '节奏与场景', weight: 15, legacyCheckIds: [7, 17, 26] },
  { id: 'prose', name: '文风与表达', weight: 15, legacyCheckIds: [8, 10, 19, 20, 21, 22, 23] },
  { id: 'canon', name: '正典与资料', weight: 15, legacyCheckIds: [12, 18, 28, 29, 30, 31, 37] },
] as const

const HARD_SEVERITIES = new Set(['critical', 'blocker'])

function record(value: unknown): RecordValue {
  return value !== null && typeof value === 'object' && !Array.isArray(value) ? value as RecordValue : {}
}

function values(value: unknown): unknown[] {
  return Array.isArray(value) ? value : []
}

const FRAMEWORK_REVISION_FIELDS = [
  'schema_version', 'id', 'version', 'rubric_version', 'graph_schema_version',
  'root', 'topology_locked', 'topology',
] as const

function canonicalJson(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(canonicalJson).join(',')}]`
  if (value !== null && typeof value === 'object') {
    const source = value as RecordValue
    return `{${Object.keys(source).sort().map(key => `${JSON.stringify(key)}:${canonicalJson(source[key])}`).join(',')}}`
  }
  return JSON.stringify(value)
}

export function dogReviewFrameworkRevision(frameworkValue: unknown): string {
  const framework = record(frameworkValue)
  const identity: RecordValue = {}
  for (const key of FRAMEWORK_REVISION_FIELDS) identity[key] = framework[key]
  return `sha256:${createHash('sha256').update(canonicalJson(identity)).digest('hex')}`
}

/** Bind OpenWrite's versioned review blueprint to one chapter. The bridge
 * supplies paths only; all nodes and edges come from the canonical server. */
export function instantiateDogReviewFramework(
  frameworkValue: unknown,
  chapterId: string,
  relativeDirectory: string,
): RecordValue {
  const framework = record(frameworkValue)
  if (framework['schema_version'] !== 'openwrite.review-dag-framework.v1') {
    throw new Error(`unsupported review DAG framework: ${String(framework['schema_version'] ?? 'missing')}`)
  }
  if (framework['id'] !== 'openwrite.standard-chapter-review') {
    throw new Error(`unsupported review DAG framework id: ${String(framework['id'] ?? 'missing')}`)
  }
  if (!/^sha256:[a-f0-9]{64}$/.test(String(framework['revision'] ?? ''))) {
    throw new Error('review DAG framework lacks a valid revision')
  }
  if (framework['revision'] !== dogReviewFrameworkRevision(framework)) {
    throw new Error('review DAG framework revision does not match its content')
  }
  if (!/^ch_\d+$/.test(chapterId)) throw new Error('review DAG chapter id must match ch_<digits>')
  const prefix = relativeDirectory.replaceAll('\\', '/').replace(/\/+$/, '')
  if (!prefix || prefix.startsWith('/') || prefix.split('/').includes('..')) {
    throw new Error('review DAG artifact directory must be a contained relative path')
  }
  const topology = record(framework['topology'])
  const templates = record(topology['nodes'])
  const contains = values(topology['contains'])
  const dependsOn = values(topology['dependsOn'])
  const invariants = record(framework['invariants'])
  if (framework['graph_schema_version'] !== '0.9') throw new Error('unsupported review DAG graph schema')
  if (Object.keys(templates).length !== Number(invariants['node_count'] ?? -1) || Object.keys(templates).length !== 47) {
    throw new Error('review DAG framework node count does not match its invariant')
  }
  if (contains.length !== Number(invariants['contains_count'] ?? -1) || dependsOn.length !== Number(invariants['dependency_count'] ?? -1)) {
    throw new Error('review DAG framework edge counts do not match its invariants')
  }
  for (let checkId = 1; checkId <= 37; checkId += 1) {
    if (!Object.hasOwn(templates, `dim-${String(checkId).padStart(2, '0')}`)) {
      throw new Error(`review DAG framework is missing legacy check ${checkId}`)
    }
  }
  const root = String(framework['root'] ?? '')
  if (!Object.hasOwn(templates, root) || record(templates[root])['kind'] !== 'composite') {
    throw new Error('review DAG framework root must be a composite node')
  }
  const nodeIds = new Set(Object.keys(templates))
  const parentByChild = new Map<string, string>()
  for (const edgeValue of contains) {
    const edge = record(edgeValue)
    const parent = String(edge['parent'] ?? '')
    const child = String(edge['child'] ?? '')
    if (!nodeIds.has(parent) || !nodeIds.has(child)) throw new Error('review DAG contains edge references an unknown node')
    if (parentByChild.has(child)) throw new Error(`review DAG node has multiple parents: ${child}`)
    parentByChild.set(child, parent)
  }
  if (parentByChild.size !== nodeIds.size - 1 || parentByChild.has(root)) {
    throw new Error('review DAG containment must form one rooted tree')
  }
  const adjacency = new Map([...nodeIds].map(nodeId => [nodeId, [] as string[]]))
  for (const edgeValue of dependsOn) {
    const edge = record(edgeValue)
    const source = String(edge['source'] ?? '')
    const target = String(edge['target'] ?? '')
    if (!nodeIds.has(source) || !nodeIds.has(target)) throw new Error('review DAG dependency references an unknown node')
    adjacency.get(target)?.push(source)
  }
  const visiting = new Set<string>()
  const visited = new Set<string>()
  const visit = (nodeId: string): void => {
    if (visiting.has(nodeId)) throw new Error('review DAG framework dependencies must be acyclic')
    if (visited.has(nodeId)) return
    visiting.add(nodeId)
    for (const successor of adjacency.get(nodeId) ?? []) visit(successor)
    visiting.delete(nodeId)
    visited.add(nodeId)
  }
  for (const nodeId of nodeIds) visit(nodeId)
  const nodes: RecordValue = {}
  for (const [nodeId, templateValue] of Object.entries(templates)) {
    const template = record(templateValue)
    const artifact = String(template['artifact'] ?? '')
    if (!/^[A-Za-z0-9][A-Za-z0-9_.-]*\.json$/.test(artifact)) {
      throw new Error(`review DAG node ${nodeId} has an unsafe artifact binding`)
    }
    const titleTemplate = typeof template['title_template'] === 'string'
      ? template['title_template']
      : String(template['title'] ?? nodeId)
    const node: RecordValue = {
      kind: template['kind'],
      title: titleTemplate.replaceAll('{chapter_id}', chapterId),
      constraint: template['constraint'],
      target: `${prefix}/${artifact}`,
      verifier: template['verifier'],
    }
    if (template['completion'] !== undefined) node['completion'] = template['completion']
    nodes[nodeId] = node
  }
  return {
    schemaVersion: String(framework['graph_schema_version'] ?? ''),
    id: `novel-review-${chapterId}`,
    root,
    nodes,
    contains: JSON.parse(JSON.stringify(contains)) as unknown,
    dependsOn: JSON.parse(JSON.stringify(dependsOn)) as unknown,
  }
}

function dimension(value: unknown): number | undefined {
  const number = typeof value === 'number' ? value : Number(value)
  return Number.isInteger(number) && number in DOG_REVIEW_DIMENSIONS ? number : undefined
}

function reviewV2(review: RecordValue): RecordValue {
  return record(review['review_v2'])
}

function selectedDimensions(review: RecordValue): Set<number> {
  const configured = reviewV2(review)['requested_dimensions'] ?? review['dimensions']
  if (!Array.isArray(configured)) return new Set(Object.keys(DOG_REVIEW_DIMENSIONS).map(Number))
  return new Set(configured.map(dimension).filter((item): item is number => item !== undefined))
}

function reviewSeverity(issue: RecordValue): string {
  const raw = String(issue['review_severity'] ?? issue['legacy_severity'] ?? issue['severity'] ?? 'warning').toLowerCase()
  if (raw === 'critical' || raw === 'blocker') return 'critical'
  if (raw === 'info' || raw === 'low') return 'info'
  return 'warning'
}

function revisionPriority(issue: RecordValue): string {
  const raw = String(issue['revision_priority'] ?? '').toLowerCase()
  if (['blocker', 'high', 'medium', 'low'].includes(raw)) return raw
  return { critical: 'blocker', warning: 'medium', info: 'low' }[reviewSeverity(issue)] ?? 'medium'
}

function normalizedIssue(value: unknown): RecordValue {
  const item = record(value)
  const evidence = item['evidence']
  const severity = reviewSeverity(item)
  return {
    id: String(item['id'] ?? ''), severity, reviewSeverity: severity,
    revisionPriority: revisionPriority(item), category: String(item['category'] ?? ''),
    description: String(item['description'] ?? item['summary'] ?? ''),
    suggestion: String(item['suggestion'] ?? ''),
    evidence: typeof evidence === 'string' ? { quote: evidence } : record(evidence),
  }
}

function verdict(status: string): 'pass' | 'fail' | 'inconclusive' {
  if (['pass', 'completed', 'evaluated', 'not_applicable'].includes(status)) return 'pass'
  if (['blocked', 'fail', 'failed', 'revise'].includes(status)) return 'fail'
  return 'inconclusive'
}

/** v1-only adapter: derive a gate from legacy severities. Never used when
 * review_v2 is present; v2 records carry OpenWrite's canonical gate_status. */
function legacyGateStatus(review: RecordValue): string {
  return values(review['issue_details']).some(item => reviewSeverity(record(item)) === 'critical') ? 'blocked' : 'pass'
}

/** v1-only adapter: derive delivery from legacy score/passed semantics. */
function legacyDeliveryStatus(review: RecordValue, threshold: number): string {
  if (legacyGateStatus(review) === 'blocked') return 'blocked'
  if (review['passed'] === false) return 'revise'
  return Number(review['score'] ?? 0) >= threshold ? 'pass' : 'revise'
}

function gateStatus(review: RecordValue): string {
  const v2 = reviewV2(review)
  if (Object.keys(v2).length > 0) return String(v2['gate_status'] ?? 'inconclusive').toLowerCase()
  return legacyGateStatus(review)
}

function deliveryStatus(review: RecordValue, threshold: number): string {
  const v2 = reviewV2(review)
  if (Object.keys(v2).length > 0) return String(v2['delivery_status'] ?? 'inconclusive').toLowerCase()
  return legacyDeliveryStatus(review, threshold)
}

function criteriaByDimension(review: RecordValue): Map<number, RecordValue> {
  const mapped = new Map<number, RecordValue>()
  for (const domain of values(reviewV2(review)['domains'])) {
    for (const criterionValue of values(record(domain)['criteria'])) {
      const criterion = record(criterionValue)
      for (const rawId of values(criterion['legacy_check_ids'])) {
        const number = dimension(rawId)
        if (number !== undefined) mapped.set(number, criterion)
      }
    }
  }
  return mapped
}

export function buildDogReviewBundle(reviewValue: unknown, chapterId: string, threshold: number): {
  manifest: RecordValue
  dimensionRecords: RecordValue[]
} {
  if (!Number.isInteger(threshold) || threshold < 0 || threshold > 100) {
    throw new Error('review threshold must be an integer between 0 and 100')
  }
  const review = record(reviewValue)
  // Existence/type/version policy, mirroring Python review_store:
  // a present review_v2 key (even null) must be a non-empty JSON object
  // declaring the supported schema version; only records without the key
  // ride the legacy v1 adapter.
  const hasV2 = Object.hasOwn(review, 'review_v2')
  const rawV2 = review['review_v2']
  if (hasV2) {
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
    // Full schema-derived contract check (generated from
    // OpenWrite contracts/review-v2-decision.schema.json).
    validateReviewV2Decision(rawV2)
  }
  const selected = selectedDimensions(review)
  const grouped = new Map<number, RecordValue[]>()
  for (const number of Object.keys(DOG_REVIEW_DIMENSIONS).map(Number)) grouped.set(number, [])
  const unmappedIssues: RecordValue[] = []
  for (const rawIssue of values(review['issue_details'])) {
    const number = dimension(record(rawIssue)['dimension'])
    const issue = normalizedIssue(rawIssue)
    if (number === undefined) unmappedIssues.push(issue)
    else grouped.get(number)?.push(issue)
  }

  const criteria = criteriaByDimension(review)
  const gate = gateStatus(review)
  const dimensionRecords = Object.entries(DOG_REVIEW_DIMENSIONS).map(([key, name]) => {
    const number = Number(key)
    const issues = grouped.get(number) ?? []
    const criterion = criteria.get(number) ?? {}
    const criterionStatus = String(criterion['status'] ?? '')
    let itemVerdict: 'pass' | 'fail' | 'inconclusive'
    let status: string
    if (!selected.has(number)) {
      itemVerdict = 'inconclusive'; status = 'not_requested'
    } else if (issues.some(item => item['reviewSeverity'] === 'critical')) {
      itemVerdict = 'fail'; status = 'blocked'
    } else if (number === 27) {
      itemVerdict = verdict(gate); status = gate
    } else if (Object.keys(criterion).length > 0) {
      itemVerdict = verdict(criterionStatus); status = criterionStatus
    } else {
      itemVerdict = 'pass'; status = 'legacy_evaluated'
    }
    return {
      schemaVersion: 'dsh-novel.review.dimension.v2', recordType: 'review-dimension', chapterId,
      dimension: number, name, verdict: itemVerdict, status, criterionId: String(criterion['id'] ?? ''),
      issueCount: issues.length, issues, sourceReviewPassed: Boolean(review['passed']), sourceReviewScore: review['score'],
    }
  })

  const v2 = reviewV2(review)
  const rawDomains = new Map(values(v2['domains']).map(item => [String(record(item)['id'] ?? ''), record(item)]))
  const domains = DOG_REVIEW_DOMAINS.map(spec => {
    const raw = rawDomains.get(spec.id) ?? {}
    const domainDimensions = dimensionRecords.filter(item => spec.legacyCheckIds.includes(Number(item['dimension']) as never))
    const status = String(raw['status'] ?? '') || (domainDimensions.some(item => item['verdict'] === 'inconclusive') ? 'inconclusive' : 'evaluated')
    const domainVerdict = domainDimensions.some(item => item['verdict'] === 'fail') ? 'fail' : verdict(status)
    return {
      schemaVersion: 'dsh-novel.review.domain.v2', recordType: 'review-domain', chapterId,
      id: spec.id, name: spec.name, weight: spec.weight, verdict: domainVerdict, status,
      earned: raw['earned'], max: raw['max'], potentialMax: raw['potential_max'], coverage: raw['coverage'],
      legacyCheckIds: [...spec.legacyCheckIds], criteria: values(raw['criteria']),
      issues: spec.legacyCheckIds.flatMap(number => grouped.get(number) ?? []),
    }
  })
  const delivery = deliveryStatus(review, threshold)
  return {
    manifest: {
      schemaVersion: 'dsh-novel.review.manifest.v2', recordType: 'review', chapterId, threshold,
      verdict: verdict(delivery), executionStatus: String(v2['execution_status'] ?? (Object.keys(review).length > 0 ? 'completed' : 'failed')),
      qualityScore: v2['quality_score'] ?? review['score'], coverage: v2['coverage'] ?? (Object.keys(review).length > 0 ? 1 : 0),
      gateStatus: gate, deliveryStatus: delivery, sourceReviewPassed: Boolean(review['passed']), score: review['score'],
      summary: String(review['summary'] ?? ''), requestedDimensions: [...selected].sort((a, b) => a - b),
      dimensionCount: 37, issueCount: dimensionRecords.reduce((sum, item) => sum + Number(item['issueCount']), 0) + unmappedIssues.length,
      unmappedIssueCount: unmappedIssues.length, unmappedIssues, sourceRevision: String(review['source_revision'] ?? ''),
      provenance: record(v2['provenance']), domains, dimensions: dimensionRecords,
      decisionSource: Object.hasOwn(review, 'review_v2') ? 'v2' : 'v1-adapter',
    },
    dimensionRecords,
  }
}

async function findNamedFiles(root: string, filename: string): Promise<string[]> {
  const found: string[] = []
  async function walk(directory: string): Promise<void> {
    let entries
    try { entries = await readdir(directory, { withFileTypes: true }) } catch { return }
    for (const entry of entries) {
      const path = join(directory, entry.name)
      if (entry.isDirectory()) await walk(path)
      else if (entry.isFile() && entry.name === filename) found.push(path)
    }
  }
  await walk(root)
  return found
}

/** Materialize the review response into model-free files consumable by dsh-dog. */
export async function materializeDogReview(response: unknown, chapterId: string, threshold: number, expectedRoot?: string): Promise<JsonValue> {
  const outer = record(response)
  const review = record(outer['result'] ?? response)
  const framework = record(outer['review_framework'])
  const workspace = record(outer['workspace'])
  const project = record(workspace['project'])
  const snapshot = record(workspace['snapshot'])
  const root = String(project['root'] ?? '')
  const novelId = String(snapshot['novel_id'] ?? '')
  if (!root || !novelId) throw new Error('review response lacks workspace project root or novel_id')
  if (expectedRoot !== undefined) assertWorkspaceRootMatch(root, expectedRoot)
  try { if (!(await stat(root)).isDirectory()) throw new Error('not a directory') } catch { throw new Error(`invalid project root: ${root}`) }

  const { manifest, dimensionRecords } = buildDogReviewBundle(review, chapterId, threshold)
  // The artifact records retain the exact blueprint identity so a historical
  // review can always be explained against the topology that produced it.
  manifest['frameworkId'] = framework['id']
  manifest['frameworkVersion'] = framework['version']
  manifest['frameworkRevision'] = framework['revision']
  const manuscriptFiles = await findNamedFiles(join(root, 'data', 'novels', novelId, 'data', 'manuscript'), `${chapterId}.md`)
  const currentRevision = manuscriptFiles.length === 1
    ? `sha256:${createHash('sha256').update(await readFile(manuscriptFiles[0]!)).digest('hex')}`
    : ''
  const sourceRevision = String(manifest['sourceRevision'] ?? '') || currentRevision
  const stale = sourceRevision !== '' && currentRevision !== '' && sourceRevision !== currentRevision
  manifest['sourceRevision'] = sourceRevision
  manifest['currentRevision'] = currentRevision
  manifest['stale'] = stale
  if (stale) { manifest['verdict'] = 'inconclusive'; manifest['deliveryStatus'] = 'stale' }

  const relativeDir = join('data', 'novels', novelId, 'data', 'dog', 'reviews', chapterId).replaceAll('\\', '/')
  const graph = instantiateDogReviewFramework(framework, chapterId, relativeDir)
  const directory = join(root, relativeDir)
  assertContained(directory, root)
  await mkdir(directory, { recursive: true })
  const write = async (name: string, value: unknown) => writeFile(join(directory, name), `${JSON.stringify(value, null, 2)}\n`, 'utf8')
  await write('review.json', manifest)
  await write('context.json', {
    schemaVersion: 'dsh-novel.review.context.v2', recordType: 'review-context', chapterId,
    verdict: stale || sourceRevision === '' ? 'inconclusive' : 'pass',
    status: stale ? 'stale' : sourceRevision !== '' ? 'current' : 'missing_revision',
    sourceRevision, currentRevision, provenance: manifest['provenance'],
  })
  for (const domain of values(manifest['domains']).map(record)) await write(`domain_${domain['id']}.json`, domain)
  const gateDimension = dimensionRecords.find(item => item['dimension'] === 27) ?? {}
  await write('gate.json', {
    schemaVersion: 'dsh-novel.review.gate.v2', recordType: 'review-gate', chapterId,
    verdict: verdict(String(manifest['gateStatus'])), status: manifest['gateStatus'], legacyCheckIds: [27], issues: gateDimension['issues'],
  })
  await write('aggregate.json', {
    schemaVersion: 'dsh-novel.review.aggregate.v2', recordType: 'review-aggregate', chapterId,
    verdict: manifest['verdict'], executionStatus: manifest['executionStatus'], qualityScore: manifest['qualityScore'],
    coverage: manifest['coverage'], gateStatus: manifest['gateStatus'], deliveryStatus: manifest['deliveryStatus'], threshold,
  })
  for (const item of dimensionRecords) await write(`dim_${String(item['dimension']).padStart(2, '0')}.json`, item)

  const target = (name: string) => `${relativeDir}/${name}`
  const graphPath = join(directory, 'dog-graph.json')
  await write('dog-graph.json', graph)
  return {
    status: 'ready', graphPath, manifestPath: join(directory, 'review.json'),
    graphTarget: relative(root, graphPath), manifestTarget: target('review.json'),
    dimensions: 37, domains: 6,
    framework: { id: framework['id'], version: framework['version'], revision: framework['revision'] },
  } as unknown as JsonValue
}

export async function materializeCompletedDogTaskReview(response: unknown, workspace: unknown, framework: unknown, threshold = 70, expectedRoot?: string): Promise<JsonValue | undefined> {
  const outer = record(response)
  const task = record(outer['task'] ?? response)
  if (task['type'] !== 'chapter_review' || task['status'] !== 'completed') return undefined
  const review = record(task['result'])
  const input = record(task['input'])
  const chapterId = String(task['chapter_id'] ?? review['chapter_id'] ?? '').trim()
    || String(input['path'] ?? '').match(/(?:^|\/)(ch_\d+)\.md$/)?.[1]
  if (!chapterId || !/^ch_\d+$/.test(chapterId)) throw new Error('completed chapter_review task lacks a resolvable chapter id')
  return await materializeDogReview({ result: review, workspace, review_framework: framework }, chapterId, threshold, expectedRoot)
}

export function reviewChapterId(args: { path?: string; chapter_id?: string }): string {
  const candidate = args.chapter_id?.trim() || args.path?.match(/(?:^|\/)(ch_\d+)\.md$/)?.[1]
  if (!candidate || !/^ch_\d+$/.test(candidate)) throw new Error('could not resolve chapter id for DoG review graph')
  return candidate
}
