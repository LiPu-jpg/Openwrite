import { useEffect, useMemo, useState, type KeyboardEvent } from 'react'
import { BookMarked, BookOpen, Boxes, Check, ChevronDown, CircleAlert, Clock3, FilePenLine, ListTodo, Search } from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import type { ToolResultNode } from '@deepseek-ai/dsh-client-runtime/client'
import type { ToolCallViewProps } from '@deepseek-ai/dsh-client-ui-tool/client'
import type { PropsLocale } from '@deepseek-ai/dsh-client-ui-slots'
import { workbenchStore, type ResourceKey } from './WorkbenchStore.ts'
import css from './DomainToolCard.module.css'

export type ToolFamily = 'status' | 'context' | 'manuscript' | 'revision' | 'task' | 'search' | 'asset' | 'outline'
type CardProps = ToolCallViewProps & PropsLocale<'studio-panel'> & { family: ToolFamily }

const ICONS: Record<ToolFamily, LucideIcon> = {
  status: Check,
  context: BookOpen,
  manuscript: FilePenLine,
  revision: FilePenLine,
  task: ListTodo,
  search: Search,
  asset: Boxes,
  outline: BookMarked,
}

const MUTATIONS: Readonly<Record<string, ResourceKey>> = {
  novel_write_chapter: 'manuscript',
  novel_doc_write: 'manuscript',
  novel_chapter_delete: 'manuscript',
  novel_manuscript_edit_action: 'manuscript',
  novel_outline_edit: 'outline',
  novel_asset_create: 'assets',
  novel_asset_update: 'assets',
  novel_assets_package_import: 'assets',
  novel_revision_create_selection: 'revisions',
  novel_revision_create_from_review: 'revisions',
  novel_revision_apply: 'manuscript',
  novel_revision_reject: 'revisions',
  novel_revision_regenerate: 'revisions',
  novel_task_create: 'tasks',
  novel_task_cancel: 'tasks',
  novel_task_retry: 'tasks',
  novel_task_confirm: 'tasks',
  novel_multi_write: 'tasks',
  novel_import: 'manuscript',
  novel_sync: 'workspace',
}

const invalidatedCalls = new Set<string>()

function record(value: unknown): Record<string, unknown> {
  return value !== null && typeof value === 'object' ? value as Record<string, unknown> : {}
}

function resultText(node: ToolResultNode): string {
  return node.content.map(block => block.type === 'text' ? block.text : '').filter(Boolean).join('\n')
}

function parseJson(value: string): unknown {
  try { return JSON.parse(value) } catch { return null }
}

function toolArgs(block: CardProps['block']): Record<string, unknown> {
  return record(parseJson('kind' in block ? block.call?.argsRaw ?? '' : block.argsRaw))
}

function resultData(block: CardProps['block']): Record<string, unknown> {
  if (!('kind' in block)) return {}
  const outer = record(parseJson(resultText(block)))
  const result = record(outer['result'])
  const data = record(outer['data'])
  return Object.keys(result).length > 0 ? result : Object.keys(data).length > 0 ? data : outer
}

function listLength(value: unknown): number | null {
  return Array.isArray(value) ? value.length : null
}

function firstNumber(data: Record<string, unknown>, keys: readonly string[]): number | null {
  for (const key of keys) if (typeof data[key] === 'number') return data[key]
  return null
}

function firstText(data: Record<string, unknown>, keys: readonly string[]): string {
  for (const key of keys) if (typeof data[key] === 'string' && data[key] !== '') return data[key]
  return ''
}

function compactSummary(family: ToolFamily, args: Record<string, unknown>, data: Record<string, unknown>): string {
  const chapter = firstText(data, ['chapter_id', 'chapter', 'path']) || firstText(args, ['chapter_id', 'chapter', 'path'])
  const id = firstText(data, ['task_id', 'proposal_id', 'id']) || firstText(args, ['task_id', 'proposal_id', 'id'])
  const status = firstText(data, ['status', 'phase'])
  switch (family) {
    case 'status': return firstText(record(data['snapshot']), ['title']) || firstText(data, ['title', 'novel_id'])
    case 'context': {
      const count = listLength(data['characters'])
      return [chapter, count === null ? '' : `${String(count)} characters`].filter(Boolean).join(' · ')
    }
    case 'manuscript': return [chapter, status, id].filter(Boolean).join(' · ')
    case 'revision': {
      const count = listLength(data['proposals'])
      return [id, status, count === null ? '' : `${String(count)} proposals`].filter(Boolean).join(' · ')
    }
    case 'task': {
      const count = listLength(data['tasks'])
      return [id, status, count === null ? '' : `${String(count)} tasks`].filter(Boolean).join(' · ')
    }
    case 'search': {
      const count = listLength(data['results'])
      return [String(args['q'] ?? ''), count === null ? '' : `${String(count)} results`].filter(Boolean).join(' · ')
    }
    case 'asset': {
      const count = listLength(data['assets'])
      return [String(data['kind'] ?? args['kind'] ?? ''), id, count === null ? '' : `${String(count)} assets`].filter(Boolean).join(' · ')
    }
    case 'outline': {
      const drafted = firstNumber(data, ['drafted_chapters'])
      return [chapter, drafted === null ? '' : `${String(drafted)} drafted`].filter(Boolean).join(' · ')
    }
  }
}

function scalarRows(data: Record<string, unknown>): { key: string; value: string }[] {
  const rows: { key: string; value: string }[] = []
  for (const [key, value] of Object.entries(data)) {
    if (value === null || value === undefined || value === '') continue
    if (typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean') {
      rows.push({ key, value: String(value) })
    } else if (Array.isArray(value)) {
      rows.push({ key, value: `${String(value.length)} items` })
    } else if (typeof value === 'object') {
      rows.push({ key, value: `${String(Object.keys(value as object).length)} fields` })
    }
    if (rows.length === 8) break
  }
  return rows
}

function manuscriptPath(args: Record<string, unknown>, data: Record<string, unknown>): string {
  const direct = firstText(data, ['path']) || firstText(args, ['path'])
  if (direct.includes('manuscript') && direct.endsWith('.md')) return direct
  const id = firstText(data, ['chapter_id']) || firstText(args, ['chapter_id', 'chapter'])
  if (!id.startsWith('ch_')) return ''
  return workbenchStore.getSnapshot().chapters.find(chapter => chapter.id === id)?.path
    ?? `data/manuscript/${id}.md`
}

export function DomainToolCard({ block, callId, toolName, family, openFile, t }: CardProps) {
  const [expanded, setExpanded] = useState(false)
  const running = !('kind' in block)
  const failed = !running && block.isError
  const args = useMemo(() => toolArgs(block), [block])
  const data = useMemo(() => resultData(block), [block])
  const summary = compactSummary(family, args, data)
  const path = manuscriptPath(args, data)
  const Icon = ICONS[family]

  useEffect(() => {
    if (running || failed || invalidatedCalls.has(callId)) return
    const resource = MUTATIONS[toolName]
    if (resource === undefined) return
    invalidatedCalls.add(callId)
    workbenchStore.invalidate(resource)
    if (resource === 'manuscript') workbenchStore.invalidate('workspace')
    if (invalidatedCalls.size > 512) invalidatedCalls.delete(invalidatedCalls.values().next().value ?? '')
  }, [callId, failed, running, toolName])

  const toggleKeyboard = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault()
      setExpanded(value => !value)
    }
  }

  return <div className={css.card} data-state={running ? 'running' : failed ? 'error' : 'ok'}>
    <div className={css.head} role="button" tabIndex={0} aria-expanded={expanded}
      onClick={() => setExpanded(value => !value)} onKeyDown={toggleKeyboard}>
      <Icon size={15} />
      <span className={css.family}>{t(`tool.family.${family}`)}</span>
      <span className={css.toolName}>{toolName}</span>
      <span className={css.summary}>{running ? t('tool.running') : failed ? t('tool.failed') : summary || t('tool.succeeded')}</span>
      {running ? <Clock3 className={css.spin} size={14} /> : failed ? <CircleAlert size={14} /> : <Check size={14} />}
      <ChevronDown className={css.chevron} size={14} />
    </div>
    {expanded && <div className={css.body}>
      {scalarRows(data).map(row => <div key={row.key} className={css.row}><span>{row.key}</span><strong>{row.value}</strong></div>)}
      {path !== '' && <button type="button" className={css.action} onClick={() => {
        workbenchStore.setActiveChapter(path)
        openFile(path)
      }}><BookOpen size={14} />{t('tool.openChapter')}</button>}
    </div>}
  </div>
}

export function createDomainToolCard(family: ToolFamily) {
  return function FamilyToolCard(props: ToolCallViewProps & PropsLocale<'studio-panel'>) {
    return <DomainToolCard {...props} family={family} />
  }
}
