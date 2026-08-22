/**
 * Outline view (大纲): the OpenWrite outline tree rendered natively —
 * volume/act/section/chapter hierarchy with kind badges, titles, summaries,
 * and draft status — plus NATIVE structural editing through the
 * revision-guarded atomic tree editor (POST /api/outline/edit; operations
 * verified against OpenWrite tools/outline_tree.py mutate_outline_structure):
 *
 * - rename        node_id + title   (chapter titles must carry a chapter number)
 * - update_summary node_id + summary (replaces the node's body block)
 * - add_child     node_id + title + kind (= parent's child_kind; empty
 *                 node_id adds a top-level volume)
 * - add_after     node_id + title + kind (= the node's own kind)
 * - delete        node_id (only when can_delete; server renumbers following
 *                 chapters and reports the renumber plan)
 *
 * Every answer carries the refreshed outline tree, so each successful op
 * re-renders straight from the response. A stale revision answers 409 →
 * reload the tree and surface a retry hint. Editability flags come from the
 * wire (editable / can_delete / delete_blocked_reason / child_kind).
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
import { StudioApiError, type StudioApiInjected } from './api.ts'
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
  /** Structural-edit affordances served by the wire (optional on garbage). */
  editable?: boolean
  can_delete?: boolean
  delete_blocked_reason?: string
  child_kind?: string
}

interface OutlinePayload {
  revision: string
  roots: OutlineNode[]
  drafted_chapters: number
}

/** Narrow the wire payload, tolerating missing/extra fields (empty tree on garbage). */
function parseOutline(data: unknown): OutlinePayload {
  const root = (data !== null && typeof data === 'object' ? data : {}) as Record<string, unknown>
  const node = (raw: unknown): OutlineNode => {
    const n = (raw !== null && typeof raw === 'object' ? raw : {}) as Record<string, unknown>
    return {
      id: String(n.id ?? ''),
      kind: String(n.kind ?? ''),
      label: String(n.label ?? ''),
      title: String(n.title ?? ''),
      summary: String(n.summary ?? ''),
      status: n.status === 'drafted' ? 'drafted' : 'planned',
      children: Array.isArray(n.children) ? n.children.map(node) : [],
      descendant_count: typeof n.descendant_count === 'number' ? n.descendant_count : 0,
      editable: n.editable === true,
      can_delete: n.can_delete === true,
      delete_blocked_reason: typeof n.delete_blocked_reason === 'string' ? n.delete_blocked_reason : '',
      child_kind: typeof n.child_kind === 'string' ? n.child_kind : '',
    }
  }
  return {
    revision: String(root.revision ?? ''),
    roots: Array.isArray(root.roots) ? root.roots.map(node) : [],
    drafted_chapters: typeof root.drafted_chapters === 'number' ? root.drafted_chapters : 0,
  }
}


type LoadState = 'loading' | 'error' | 'ready'

/** One pending inline form over a node (only one open at a time). */
interface InlineForm {
  kind: 'rename' | 'summary' | 'addChild' | 'addAfter'
  nodeId: string
  /** Expected child kind for add forms ('' = resolved lazily from the node). */
  addKind: string
  text: string
}

/** Full outline-view props: conversation-view runtime share & injected fetch & locale seat. */
export type OutlineViewProps =
  ConvViewProps & InjectFace<StudioApiInjected> & PropsLocale<'studio-panel'>

export function OutlineView({ fetchStudioApi, postStudioApi, t }: OutlineViewProps) {
  const [state, setState] = useState<LoadState>('loading')
  const [payload, setPayload] = useState<OutlinePayload | null>(null)
  const [error, setError] = useState('')
  const [collapsed, setCollapsed] = useState<ReadonlySet<string>>(new Set())
  const [form, setForm] = useState<InlineForm | null>(null)
  const [busy, setBusy] = useState(false)
  const [toast, setToast] = useState<{ text: string, bad: boolean } | null>(null)

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

  const showToast = (text: string, bad: boolean) => {
    setToast({ text, bad })
    window.setTimeout(() => setToast(null), 6000)
  }

  /**
   * Run one structural operation against the current revision. The response's
   * refreshed tree re-renders the view directly; conflicts reload first.
   */
  const runOp = useCallback(async (
    op: { operation: string, node_id?: string, title?: string, summary?: string, kind?: string },
    okText: string,
  ) => {
    if (payload === null || busy) return
    setBusy(true)
    try {
      const data = await postStudioApi('/outline/edit', { ...op, revision: payload.revision }) as Record<string, unknown>
      setPayload(parseOutline(data.outline))
      setToast({ text: typeof data.message === 'string' && data.message !== '' ? data.message : okText, bad: false })
      setForm(null)
    } catch (cause: unknown) {
      if (cause instanceof StudioApiError && cause.status === 409) {
        load()
        showToast(t('outline.opConflict'), true)
      } else {
        showToast(`${t('outline.opFailed')}: ${cause instanceof Error ? cause.message : String(cause)}`, true)
      }
    } finally {
      setBusy(false)
    }
  }, [payload, busy, postStudioApi, load, t])

  const toggle = (id: string) => {
    setCollapsed(previous => {
      const next = new Set(previous)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  /** Commit the currently open inline form as one structural operation. */
  const commitForm = () => {
    if (form === null || payload === null) return
    const title = form.text.trim()
    if (form.kind === 'rename') {
      if (title === '') return
      void runOp({ operation: 'rename', node_id: form.nodeId, title }, '')
    } else if (form.kind === 'summary') {
      void runOp({ operation: 'update_summary', node_id: form.nodeId, summary: form.text }, '')
    } else if (form.kind === 'addChild') {
      if (title === '') return
      const parent = findNode(payload.roots, form.nodeId)
      void runOp({
        operation: 'add_child',
        node_id: form.nodeId,
        kind: form.addKind !== '' ? form.addKind : parent?.child_kind ?? '',
        title,
      }, '')
    } else {
      if (title === '') return
      const sibling = findNode(payload.roots, form.nodeId)
      void runOp({
        operation: 'add_after',
        node_id: form.nodeId,
        kind: form.addKind !== '' ? form.addKind : sibling?.kind ?? '',
        title,
      }, '')
    }
  }

  const renderNode = (node: OutlineNode): ReactNode => {
    const isCollapsed = collapsed.has(node.id)
    const hasChildren = node.children.length > 0
    const editingThis = form !== null && form.nodeId === node.id
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
          {(form?.kind ?? '') === 'rename' && editingThis
            ? (
              <span className={css.inlineRename}>
                <input
                  className={css.inlineInput}
                  value={form.text}
                  autoFocus
                  onChange={(event) => { setForm({ ...form, text: event.target.value }) }}
                  onKeyDown={(event) => {
                    if (event.key === 'Enter') commitForm()
                    if (event.key === 'Escape') setForm(null)
                  }}
                  placeholder={t('outline.newTitlePlaceholder')}
                />
                <button type="button" className={css.actionButton} disabled={busy} onClick={() => { commitForm() }}>✓</button>
                <button type="button" className={css.actionButton} onClick={() => { setForm(null) }}>✕</button>
              </span>
            )
            : <span className={css.nodeTitle}>{node.title}</span>}
          {node.kind === 'chapter' && (
            <span
              className={css.statusBadge}
              data-status={node.status}
            >
              {node.status === 'drafted' ? t('outline.drafted') : t('outline.planned')}
            </span>
          )}
          {node.editable === true && form === null && (
            <span className={css.nodeActions}>
              <button type="button" className={css.actionButton} title={t('outline.rename')}
                onClick={() => { setForm({ kind: 'rename', nodeId: node.id, addKind: '', text: node.title }) }}>
                {t('outline.rename')}
              </button>
              <button type="button" className={css.actionButton} title={t('outline.editSummary')}
                onClick={() => { setForm({ kind: 'summary', nodeId: node.id, addKind: '', text: node.summary }) }}>
                {t('outline.editSummary')}
              </button>
              {node.child_kind !== '' && (
                <button type="button" className={css.actionButton} title={t('outline.addChild')}
                  disabled={node.child_kind === ''}
                  onClick={() => {
                    toggleIfCollapsed(node.id, hasChildren)
                    setForm({ kind: 'addChild', nodeId: node.id, addKind: node.child_kind ?? '', text: '' })
                  }}>
                  {t('outline.addChild')}
                </button>
              )}
              <button type="button" className={css.actionButton} title={t('outline.addAfter')}
                onClick={() => {
                  setForm({ kind: 'addAfter', nodeId: node.id, addKind: node.kind, text: '' })
                }}>
                {t('outline.addAfter')}
              </button>
              <button
                type="button"
                className={css.actionButton}
                title={node.can_delete === false ? node.delete_blocked_reason : t('outline.del')}
                disabled={node.can_delete !== true || busy}
                onClick={() => {
                  if (window.confirm(`${t('outline.confirmDelete')}「${node.title}」`)) {
                    void runOp({ operation: 'delete', node_id: node.id }, '')
                  }
                }}
              >
                {t('outline.del')}
              </button>
            </span>
          )}
        </div>
        {(form?.kind ?? '') === 'summary' && editingThis && (
          <div className={css.summaryEditor}>
            <textarea
              className={css.summaryTextarea}
              value={form.text}
              rows={Math.min(14, Math.max(3, form.text.split('\n').length + 1))}
              onChange={(event) => { setForm({ ...form, text: event.target.value }) }}
              placeholder={t('outline.summaryHint')}
            />
            <div className={css.inlineActions}>
              <button type="button" className={css.button} disabled={busy} onClick={() => { commitForm() }}>
                {t('outline.save')}
              </button>
              <button type="button" className={css.button} onClick={() => { setForm(null) }}>
                {t('outline.cancel')}
              </button>
            </div>
          </div>
        )}
        {(form?.kind ?? '') === 'addChild' && editingThis && (
          <div className={css.inlineActions}>
            <input
              className={css.inlineInput}
              value={form.text}
              autoFocus
              placeholder={`${t('outline.newTitlePlaceholder')} (${form.addKind})`}
              onChange={(event) => { setForm({ ...form, text: event.target.value }) }}
              onKeyDown={(event) => {
                if (event.key === 'Enter') commitForm()
                if (event.key === 'Escape') setForm(null)
              }}
            />
            <button type="button" className={css.actionButton} disabled={busy} onClick={() => { commitForm() }}>✓</button>
            <button type="button" className={css.actionButton} onClick={() => { setForm(null) }}>✕</button>
          </div>
        )}
        {(form?.kind ?? '') === 'addAfter' && editingThis && (
          <div className={css.inlineActions}>
            <input
              className={css.inlineInput}
              value={form.text}
              autoFocus
              placeholder={`${t('outline.newTitlePlaceholder')} (${form.addKind})`}
              onChange={(event) => { setForm({ ...form, text: event.target.value }) }}
              onKeyDown={(event) => {
                if (event.key === 'Enter') commitForm()
                if (event.key === 'Escape') setForm(null)
              }}
            />
            <button type="button" className={css.actionButton} disabled={busy} onClick={() => { commitForm() }}>✓</button>
            <button type="button" className={css.actionButton} onClick={() => { setForm(null) }}>✕</button>
          </div>
        )}
        {node.summary !== '' && (form === null || !editingThis) && (
          <div className={css.nodeSummary}>{node.summary}</div>
        )}
        {hasChildren && !isCollapsed && (
          <ul className={css.treeChildren}>{node.children.map(renderNode)}</ul>
        )}
      </li>
    )
  }

  const findNode = (roots: OutlineNode[], id: string): OutlineNode | null => {
    for (const root of roots) {
      if (root.id === id) return root
      const hit = findNode(root.children, id)
      if (hit !== null) return hit
    }
    return null
  }

  const toggleIfCollapsed = (id: string, hasChildren: boolean) => {
    if (hasChildren && collapsed.has(id)) toggle(id)
  }

  const addVolume = () => {
    if (payload === null || busy) return
    setForm({ kind: 'addChild', nodeId: '', addKind: 'volume', text: '' })
  }

  const renderAddVolume = () => {
    if (form === null || form.kind !== 'addChild' || form.nodeId !== '') return null
    return (
      <div className={css.inlineActions}>
        <input
          className={css.inlineInput}
          value={form.text}
          autoFocus
          placeholder={`${t('outline.newTitlePlaceholder')} (volume)`}
          onChange={(event) => { setForm({ ...form, text: event.target.value }) }}
          onKeyDown={(event) => {
            if (event.key === 'Enter') commitForm()
            if (event.key === 'Escape') setForm(null)
          }}
        />
        <button type="button" className={css.actionButton} disabled={busy} onClick={() => { commitForm() }}>✓</button>
        <button type="button" className={css.actionButton} onClick={() => { setForm(null) }}>✕</button>
      </div>
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
        <button type="button" className={css.button} disabled={busy} onClick={addVolume}>
          {t('outline.addVolume')}
        </button>
        <button type="button" className={css.button} disabled={busy} onClick={() => { load() }}>
          {t('refresh')}
        </button>
      </div>
      {toast !== null && (
        <div className={css.notice}>
          <span className={toast.bad ? css.errorText : undefined}>{toast.text}</span>
        </div>
      )}
      <div className={css.body}>
        {state === 'loading' && <div className={css.notice}>{t('loading')}</div>}
        {state === 'error' && (
          <div className={css.notice}>
            <span className={css.errorText}>{error}</span>
            <button type="button" className={css.button} onClick={() => { load() }}>{t('retry')}</button>
          </div>
        )}
        {state === 'ready' && payload !== null && payload.roots.length === 0 && (
          <div className={css.notice}>{renderAddVolume() ?? t('outline.empty')}</div>
        )}
        {state === 'ready' && payload !== null && payload.roots.length > 0 && (
          <>
            {renderAddVolume()}
            <ul className={css.tree}>{payload.roots.map(renderNode)}</ul>
          </>
        )}
      </div>
    </div>
  )
}
