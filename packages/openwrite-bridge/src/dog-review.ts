import { mkdir, writeFile } from 'node:fs/promises'
import { join, relative } from 'node:path'
import type { JsonValue } from './client.js'

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

const HARD_SEVERITIES = new Set(['critical', 'blocker'])

function record(value: unknown): RecordValue {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
    ? value as RecordValue
    : {}
}

function dimension(value: unknown): number | undefined {
  const number = typeof value === 'number' ? value : Number(value)
  return Number.isInteger(number) && number in DOG_REVIEW_DIMENSIONS ? number : undefined
}

function selectedDimensions(review: RecordValue): Set<number> {
  const values = review['dimensions']
  if (!Array.isArray(values)) return new Set(Object.keys(DOG_REVIEW_DIMENSIONS).map(Number))
  return new Set(values.map(dimension).filter((value): value is number => value !== undefined))
}

function normalizedIssue(value: unknown): RecordValue {
  const item = record(value)
  const evidence = item['evidence']
  return {
    id: String(item['id'] ?? ''),
    severity: String(item['severity'] ?? 'warning').toLowerCase(),
    category: String(item['category'] ?? ''),
    description: String(item['description'] ?? item['summary'] ?? ''),
    suggestion: String(item['suggestion'] ?? ''),
    evidence: typeof evidence === 'string' ? { quote: evidence } : record(evidence),
  }
}

function gatePassed(review: RecordValue, threshold: number): boolean {
  const score = Number(review['score'] ?? 0)
  const issues = Array.isArray(review['issue_details']) ? review['issue_details'] : []
  const hard = issues.some(item => HARD_SEVERITIES.has(String(record(item)['severity'] ?? '').toLowerCase()))
  return score >= threshold && !hard
}

/** Materialize the review response into files consumable by dsh-dog. */
export async function materializeDogReview(
  response: unknown,
  chapterId: string,
  threshold: number,
): Promise<JsonValue> {
  const outer = record(response)
  const review = record(outer['result'] ?? response)
  const workspace = record(outer['workspace'])
  const project = record(workspace['project'])
  const snapshot = record(workspace['snapshot'])
  const root = String(project['root'] ?? '')
  const novelId = String(snapshot['novel_id'] ?? '')
  if (!root || !novelId) throw new Error('review response lacks workspace project root or novel_id')

  const selected = selectedDimensions(review)
  const grouped = new Map<number, RecordValue[]>()
  for (const number of Object.keys(DOG_REVIEW_DIMENSIONS).map(Number)) grouped.set(number, [])
  const issues = Array.isArray(review['issue_details']) ? review['issue_details'] : []
  for (const item of issues) {
    const number = dimension(record(item)['dimension'])
    if (number !== undefined) grouped.get(number)?.push(normalizedIssue(item))
  }

  const dimensionRecords = Object.entries(DOG_REVIEW_DIMENSIONS).map(([key, name]) => {
    const number = Number(key)
    const dimensionIssues = grouped.get(number) ?? []
    const verdict = !selected.has(number)
      ? 'inconclusive'
      : dimensionIssues.some(item => HARD_SEVERITIES.has(String(item['severity']))) ? 'fail' : 'pass'
    return {
      schemaVersion: 'dsh-novel.review.dimension.v1', recordType: 'dimension', chapterId,
      dimension: number, name, verdict, issueCount: dimensionIssues.length, issues: dimensionIssues,
      sourceReviewPassed: Boolean(review['passed']), sourceReviewScore: review['score'],
    }
  })
  const manifest = {
    schemaVersion: 'dsh-novel.review.manifest.v1', recordType: 'review', chapterId, threshold,
    verdict: gatePassed(review, threshold) ? 'pass' : 'fail', sourceReviewPassed: Boolean(review['passed']),
    score: review['score'], summary: String(review['summary'] ?? ''), requestedDimensions: [...selected].sort((a, b) => a - b),
    dimensionCount: 37, issueCount: dimensionRecords.reduce((sum, item) => sum + Number(item.issueCount), 0),
    dimensions: dimensionRecords,
  }

  const relativeDir = join('data', 'novels', novelId, 'data', 'dog', 'reviews', chapterId).replaceAll('\\', '/')
  const directory = join(root, relativeDir)
  await mkdir(directory, { recursive: true })
  const write = async (name: string, value: unknown) => writeFile(join(directory, name), `${JSON.stringify(value, null, 2)}\n`, 'utf8')
  await write('review.json', manifest)
  for (const item of dimensionRecords) await write(`dim_${String(item.dimension).padStart(2, '0')}.json`, item)

  const manifestTarget = `${relativeDir}/review.json`
  const nodes: RecordValue = {
    root: {
      kind: 'composite', title: `${chapterId} 37维审查`, constraint: 'hard', target: manifestTarget,
      completion: { op: 'all', items: dimensionRecords.map(item => ({ op: 'ref', id: `dim-${String(item.dimension).padStart(2, '0')}` })) },
      verifier: { mode: 'agentic', instruction: '只检查这份 OpenWrite 37 维审查 manifest 的聚合一致性，不重新审查正文；给出证据。' },
    },
  }
  const contains: RecordValue[] = []
  for (const item of dimensionRecords) {
    const id = `dim-${String(item.dimension).padStart(2, '0')}`
    nodes[id] = {
      kind: 'leaf', title: `${item.dimension}. ${item.name}`, constraint: 'hard',
      target: `${relativeDir}/dim_${String(item.dimension).padStart(2, '0')}.json`,
      verifier: { mode: 'programmatic', script: 'review-dimension' },
    }
    contains.push({ parent: 'root', child: id, required: true, failure: 'fatal' })
  }
  const graph = { schemaVersion: '0.9', id: `novel-review-${chapterId}`, root: 'root', nodes, contains, dependsOn: [] }
  const graphPath = join(directory, 'dog-graph.json')
  await write('dog-graph.json', graph)
  return {
    status: 'ready', graphPath, manifestPath: join(directory, 'review.json'),
    graphTarget: relative(root, graphPath), manifestTarget, dimensions: 37,
  } as unknown as JsonValue
}

export function reviewChapterId(args: { path?: string; chapter_id?: string }): string {
  const candidate = args.chapter_id?.trim() || args.path?.match(/(?:^|\/)(ch_\d+)\.md$/)?.[1]
  if (!candidate || !/^ch_\d+$/.test(candidate)) throw new Error('could not resolve chapter id for DoG review graph')
  return candidate
}
