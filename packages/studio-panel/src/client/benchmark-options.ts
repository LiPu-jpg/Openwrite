import { asRecord, asText, asFiniteNumber, unwrapData } from './dto.ts'

export type BenchmarkTaskType = 'chapter' | 'outline'
export type BenchmarkExecutionMode = 'framework' | 'creative'

export interface BenchmarkPipeline {
  id: string
  executionMode: string
  nodes: { id: string; label: string; dependsOn: string[] }[]
  reviewDomains: { id: string; label: string }[]
}

export interface BenchmarkOptions {
  chapters: { id: string; title: string; status: string; hasManuscript: boolean; available: boolean; reason: string }[]
  nextChapterId: string
  defaultOutlineStart: number
  outlineStartMin: number
  outlineStartMax: number
  outlineCountMax: number
  tasks: { taskType: BenchmarkTaskType; executionModes: string[]; pipelines: BenchmarkPipeline[]; readiness: { ok: boolean; code: string; message: string } }[]
}

export function parseBenchmarkPipeline(value: unknown): BenchmarkPipeline | null {
  const item = asRecord(value)
  const id = asText(item['id'])
  if (!id) return null
  return {
    id,
    executionMode: asText(item['execution_mode']),
    nodes: (Array.isArray(item['nodes']) ? item['nodes'] : []).map(raw => {
      const node = asRecord(raw)
      return {
        id: asText(node['id']), label: asText(node['label']) || asText(node['id']),
        dependsOn: (Array.isArray(node['depends_on']) ? node['depends_on'] : []).map(asText).filter(Boolean),
      }
    }).filter(node => node.id !== ''),
    reviewDomains: (Array.isArray(item['review_domains']) ? item['review_domains'] : []).map(raw => {
      const domain = asRecord(raw)
      return { id: asText(domain['id']), label: asText(domain['label']) || asText(domain['id']) }
    }).filter(domain => domain.id !== ''),
  }
}

export function parseBenchmarkOptions(value: unknown): BenchmarkOptions {
  const item = unwrapData(value)
  const start = asFiniteNumber(item['default_outline_start_chapter'])
  const limits = asRecord(item['limits'])
  const startLimits = asRecord(limits['outline_start_chapter'])
  const countLimits = asRecord(limits['outline_chapter_count'])
  return {
    chapters: (Array.isArray(item['chapters']) ? item['chapters'] : []).map(raw => {
      const chapter = asRecord(raw)
      return {
        id: asText(chapter['chapter_id']), title: asText(chapter['title']), status: asText(chapter['status']),
        hasManuscript: chapter['has_manuscript'] === true, available: chapter['availability'] !== 'unavailable',
        reason: asText(chapter['reason']),
      }
    }).filter(chapter => chapter.id !== ''),
    nextChapterId: asText(item['next_chapter_id']),
    defaultOutlineStart: start !== null && Number.isSafeInteger(start) && start > 0 ? start : 1,
    outlineStartMin: asFiniteNumber(startLimits['min']) ?? 1,
    outlineStartMax: asFiniteNumber(startLimits['max']) ?? 100000,
    outlineCountMax: asFiniteNumber(countLimits['max']) ?? 20,
    tasks: (Array.isArray(item['tasks']) ? item['tasks'] : []).flatMap(raw => {
      const task = asRecord(raw)
      const taskType = asText(task['task_type'])
      if (taskType !== 'chapter' && taskType !== 'outline') return []
      return [{
        taskType,
        readiness: {
          ok: asRecord(task['readiness'])['ok'] !== false,
          code: asText(asRecord(task['readiness'])['code']),
          message: asText(asRecord(task['readiness'])['message']),
        },
        executionModes: (Array.isArray(task['execution_modes']) ? task['execution_modes'] : []).map(asText),
        pipelines: (Array.isArray(task['pipelines']) ? task['pipelines'] : []).map(parseBenchmarkPipeline)
          .filter((pipeline): pipeline is BenchmarkPipeline => pipeline !== null),
      }]
    }),
  }
}

export function positiveInteger(value: string): number | null {
  if (!/^\d+$/.test(value.trim())) return null
  const parsed = Number(value)
  return Number.isSafeInteger(parsed) && parsed > 0 ? parsed : null
}
