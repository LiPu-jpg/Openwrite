/**
 * 预演大纲数据面（供 OutlineView 以“树内接续”方式渲染）。
 *
 * 每套预演 = 一棵和正式大纲一样语法的迷你树（卷/篇/节/章），并携带“构思”。
 * OutlineView 把它的顶层节点接到正式大纲当前卷的末尾——除颜色外与正式树完全一致。
 */

export interface PlanTreeNode {
  id: string
  kind: 'act' | 'section' | 'chapter'
  label: string
  title: string
  summary: string
  children: PlanTreeNode[]
}

export interface PlanInfo {
  id: string
  kind: 'rolling' | 'branch'
  label: string
  idea: string
  meta: string
  nodes: PlanTreeNode[]
  /** rolling 草案专用：正文 / revision / state（供编辑、删除、并入） */
  proposal?: string
  revision?: string
  state?: string
}

export const PLAN_PALETTES = [
  { accent: '#8f9bff', bar: '#5b6cff', bg: 'rgba(120,140,255,0.13)' },
  { accent: '#4fd6a8', bar: '#22b587', bg: 'rgba(60,200,150,0.13)' },
  { accent: '#f6a95c', bar: '#e58a2a', bg: 'rgba(240,170,90,0.14)' },
  { accent: '#e07cd6', bar: '#c552b9', bg: 'rgba(224,124,214,0.12)' },
]
export function planColor(index: number): { accent: string; bar: string; bg: string } {
  const palette = PLAN_PALETTES[index % PLAN_PALETTES.length]
  return palette ?? { accent: '#aaa', bar: '#8a8a8a', bg: 'transparent' }
}

function asString(value: unknown, fallback = ''): string {
  return typeof value === 'string' ? value : fallback
}
function asRec(value: unknown): Record<string, unknown> {
  return value !== null && typeof value === 'object' ? (value as Record<string, unknown>) : {}
}
function asList(value: unknown): Record<string, unknown>[] {
  return Array.isArray(value) ? value.map(asRec).filter(item => Object.keys(item).length > 0) : []
}
function asStringArray(value: unknown): string[] {
  return Array.isArray(value) ? value.map(item => asString(item)).filter(Boolean) : []
}

/** 第一段非标题文本 = “构思”。 */
function firstParagraph(markdown: string): string {
  const parts: string[] = []
  for (const raw of (markdown || '').split(/\r?\n/)) {
    const line = raw.trim()
    if (line === '' || line.startsWith('#')) continue
    if (line.startsWith('>')) continue
    parts.push(line)
    if (parts.join(' ').length > 240) break
  }
  return parts.join(' ').slice(0, 320) || ''
}

/** 把 markdown 大纲（# 篇 / ## 节 / ###·#### 章）解析成迷你树。 */
function parseOutlineTree(prefix: string, markdown: string): PlanTreeNode[] {
  const roots: PlanTreeNode[] = []
  const stack: { level: number; node: PlanTreeNode }[] = []
  let counter = 0

  const push = (level: number, title: string, kind: PlanTreeNode['kind']) => {
    const node: PlanTreeNode = {
      id: `${prefix}-n${counter++}`,
      kind,
      label: kind === 'act' ? '幕' : kind === 'section' ? '节' : '章',
      title,
      summary: '',
      children: [],
    }
    while (stack.length > 0) {
      const last = stack[stack.length - 1]
      if (last === undefined || level > last.level) break
      stack.pop()
    }
    const parent = stack[stack.length - 1]
    if (parent !== undefined) parent.node.children.push(node)
    else roots.push(node)
    stack.push({ level, node })
  }

  const kindForLevel = (level: number): PlanTreeNode['kind'] =>
    level <= 1 ? 'act' : level === 2 ? 'section' : 'chapter'

  for (const raw of (markdown || '').split(/\r?\n/)) {
    const heading = /^(#{1,6})\s+(.*)$/.exec(raw)
    if (heading !== null) {
      const mark = heading[1]
      const textRaw = heading[2]
      if (mark !== undefined && textRaw !== undefined && textRaw.trim() !== '') {
        push(mark.length, textRaw.trim(), kindForLevel(mark.length))
      }
      continue
    }
    const line = raw.trim()
    if (line === '' || line.startsWith('>') || line.startsWith('---')) continue
    const top = stack[stack.length - 1]
    if (top !== undefined && top.node.summary.length < 200) {
      top.node.summary += top.node.summary === '' ? line : ' ' + line
    }
  }
  return roots
}

export async function loadPlans(
  postStudioApi: (path: string, body: unknown) => Promise<unknown>,
): Promise<PlanInfo[]> {
  const next: PlanInfo[] = []
  const rolling = asRec(await postStudioApi('/rolling-plans', { action: 'list' }))
  const forecasts = asRec(await postStudioApi('/narrative-forecasts', { action: 'list' }))
  for (const brief of asList(rolling.candidates)) {
    const id = asString(brief.candidate_id)
    const detail = asRec(await postStudioApi('/rolling-plans', { action: 'get', candidate_id: id }))
    const proposal = asString(detail.proposal) || asString(detail.goethe_brief)
    next.push({
      id,
      kind: 'rolling',
      label: asString(detail.direction) || id,
      idea: firstParagraph(proposal),
      meta: `窗口 ${asStringArray(detail.current_window).join('→') || '—'}`,
      nodes: parseOutlineTree(id, proposal),
      proposal,
      revision: asString(detail.revision),
      state: asString(detail.state),
    })
  }
  for (const brief of asList(forecasts.forecasts)) {
    const forecastId = asString(brief.forecast_id)
    const detail = asRec(await postStudioApi('/narrative-forecasts', { action: 'get', forecast_id: forecastId }))
    const divergence = asString(detail.divergence)
    for (const branch of asList(detail.branches)) {
      const branchId = asString(branch.branch_id)
      const beatNodes: PlanTreeNode[] = asList(branch.beats).map((beat, index) => ({
        id: `${forecastId}-${branchId}-b${index}`,
        kind: 'chapter',
        label: '章',
        title: `第${asString(beat.chapter_id).replace(/^ch_0*/, '') || asString(beat.offset)}章（+${asString(beat.offset)}）`,
        summary: asString(beat.summary),
        children: [],
      }))
      next.push({
        id: `${forecastId}::${branchId}`,
        kind: 'branch',
        label: asString(branch.title) || branchId,
        idea: divergence,
        meta: `${forecastId} · ${asString(detail.anchor_chapter_title) || asString(detail.anchor_chapter_id) || '全书'}`,
        nodes: [{
          id: `${forecastId}-${branchId}-root`,
          kind: 'section',
          label: '节',
          title: `方向：${asString(branch.title) || branchId}`,
          summary: asString(branch.premise),
          children: beatNodes,
        }],
      })
    }
  }
  return next
}
