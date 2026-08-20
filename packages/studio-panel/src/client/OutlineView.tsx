/**
 * Outline view (大纲): the OpenWrite outline tree rendered natively —
 * volume/act/section/chapter hierarchy with kind badges, titles, summaries,
 * and draft status. Read-only; edits stay in Studio or the agent tools.
 *
 * Wire shape (verified against OpenWrite tools/outline_tree.py
 * build_outline_structure): GET /api/outline answers WITHOUT an envelope —
 * { path, revision, roots: OutlineNode[], counts, drafted_chapters,
 * recommendation }. Every node carries { id, kind, label, title, summary,
 * status: 'drafted'|'planned', children, descendant_count, ... }.
 */

import { useCallback, useEffect, useState, type ReactNode } from 'react'
import type { ConvViewProps } from '@deepseek-ai/dsh-client-ui-conversation/client'
import type { InjectFace, PropsLocale } from '@deepseek-ai/dsh-client-ui-slots'
import type { StudioApiInjected } from './api.ts'
import css from './views.module.css'

/** One outline tree node (the fields this view reads; the payload carries more). */
interface OutlineNode {
  id: string
  kind: string
  /** Server-provided Chinese kind label (卷/篇/节/章/附录). */
  label: string
  title: string
  summary: string
  status: 'drafted' | 'planned'
  children: OutlineNode[]
  descendant_count: number
}

interface OutlinePayload {
  roots: OutlineNode[]
  drafted_chapters: number
}

/** Narrow the wire payload, tolerating missing/extra fields (empty tree on garbage). */
function parseOutline(data: unknown): OutlinePayload {
  const root = (data !== null && typeof data === 'object' ? data : {}) as Record<string, unknown>
  const node = (raw: unknown): OutlineNode => {
    const record = (raw !== null && typeof raw === 'object' ? raw : {}) as Record<string, unknown>
    const text = (value: unknown): string => (typeof value === 'string' ? value : '')
    return {
      id: text(record['id']),
      kind: text(record['kind']),
      label: text(record['label']),
      title: text(record['title']),
      summary: text(record['summary']),
      status: record['status'] === 'drafted' ? 'drafted' : 'planned',
      children: Array.isArray(record['children']) ? record['children'].map(node) : [],
      descendant_count: typeof record['descendant_count'] === 'number' ? record['descendant_count'] : 0,
    }
  }
  return {
    roots: Array.isArray(root['roots']) ? root['roots'].map(node) : [],
    drafted_chapters: typeof root['drafted_chapters'] === 'number' ? root['drafted_chapters'] : 0,
  }
}

type LoadState = 'loading' | 'error' | 'ready'

/** Full outline-view props: conversation-view runtime share & injected fetch & locale seat. */
export type OutlineViewProps =
  ConvViewProps & InjectFace<StudioApiInjected> & PropsLocale<'studio-panel'>

export function OutlineView({ fetchStudioApi, t }: OutlineViewProps) {
  const [state, setState] = useState<LoadState>('loading')
  const [payload, setPayload] = useState<OutlinePayload | null>(null)
  const [error, setError] = useState('')
  const [collapsed, setCollapsed] = useState<ReadonlySet<string>>(new Set())

  const load = useCallback(() => {
    setState('loading')
    let cancelled = false
    fetchStudioApi('/outline')
      .then((data) => {
        if (cancelled) return
        setPayload(parseOutline(data))
        setState('ready')
      })
      .catch((cause: unknown) => {
        if (cancelled) return
        setError(cause instanceof Error ? cause.message : String(cause))
        setState('error')
      })
    return () => { cancelled = true }
  }, [fetchStudioApi])

  useEffect(() => load(), [load])

  const toggle = (id: string) => {
    setCollapsed(previous => {
      const next = new Set(previous)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  const renderNode = (node: OutlineNode): ReactNode => {
    const isCollapsed = collapsed.has(node.id)
    const hasChildren = node.children.length > 0
    return (
      <li key={node.id} className={css.treeItem}>
        <div className={css.treeRow}>
          {hasChildren
            ? (
              <button
                type="button"
                className={css.chevronButton}
                aria-expanded={!isCollapsed}
                onClick={() => { toggle(node.id) }}
              >
                {isCollapsed ? '▸' : '▾'}
              </button>
            )
            : <span className={css.chevronPlaceholder} aria-hidden />}
          <span className={css.kindBadge} data-kind={node.kind}>{node.label || node.kind}</span>
          <span className={css.nodeTitle}>{node.title}</span>
          {node.kind === 'chapter' && (
            <span
              className={css.statusBadge}
              data-status={node.status}
            >
              {node.status === 'drafted' ? t('outline.drafted') : t('outline.planned')}
            </span>
          )}
        </div>
        {node.summary !== '' && <div className={css.nodeSummary}>{node.summary}</div>}
        {hasChildren && !isCollapsed && (
          <ul className={css.treeChildren}>{node.children.map(renderNode)}</ul>
        )}
      </li>
    )
  }

  return (
    <div className={css.root}>
      <div className={css.toolbar}>
        {payload !== null && state === 'ready' && (
          <span className={css.toolbarMeta}>
            {t('outline.draftedCount')}: {payload.drafted_chapters}
          </span>
        )}
        <button type="button" className={css.button} onClick={() => { load() }}>
          {t('refresh')}
        </button>
      </div>
      <div className={css.body}>
        {state === 'loading' && <div className={css.notice}>{t('loading')}</div>}
        {state === 'error' && (
          <div className={css.notice}>
            <span className={css.errorText}>{error}</span>
            <button type="button" className={css.button} onClick={() => { load() }}>{t('retry')}</button>
          </div>
        )}
        {state === 'ready' && payload !== null && payload.roots.length === 0 && (
          <div className={css.notice}>{t('outline.empty')}</div>
        )}
        {state === 'ready' && payload !== null && payload.roots.length > 0 && (
          <ul className={css.tree}>{payload.roots.map(renderNode)}</ul>
        )}
      </div>
    </div>
  )
}
