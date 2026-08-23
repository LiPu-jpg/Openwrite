/**
 * Outline view (大纲): the OpenWrite outline tree rendered natively — AND
 * editable in place, Obsidian-style: titles and body blocks render as
 * borderless inputs that look identical to plain text; click into them and
 * type. Commits ride the revision-guarded atomic tree editor
 * (POST /api/outline/edit; operations verified against OpenWrite
 * tools/outline_tree.py mutate_outline_structure):
 *
 * - title input  blur/Enter → rename        (chapters must carry a number)
 * - body textarea blur       → update_summary (updates prose synopsis, preserving metadata)
 * - hover buttons → add_child / add_after / delete (server renumbers on delete)
 * - toolbar      → add a top-level volume (add_child with empty node_id)
 *
 * Commit semantics: optimistic local patch + silent revision bump on success
 * (no tree re-render — focus and scroll survive); 409 reloads the tree and
 * asks for a retry; other failures revert the field and toast the server
 * message. A chapter rename changes its node id server-side, so a follow-up
 * op on the same node may 404 — the error path reloads and the user retries.
 *
 * Wire shape (verified against OpenWrite tools/outline_tree.py
 * build_outline_structure): GET /api/outline answers WITHOUT an envelope —
 * { path, revision, roots, counts, drafted_chapters, recommendation }.
 */

import { useCallback, useEffect, useState, type ReactNode } from 'react'
import type { ConvViewProps } from '@deepseek-ai/dsh-client-ui-conversation/client'
import type { InjectFace, PropsLocale } from '@deepseek-ai/dsh-client-ui-slots'
import { StudioApiError, type StudioApiInjected } from './api.ts'
import { useWorkbench } from './WorkbenchStore.ts'
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

/** Uncommitted field overlay keyed by node id (title / summary drafts). */
interface FieldDraft {
  title?: string
  summary?: string
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

/** Full outline-view props: conversation-view runtime share & injected fetch & locale seat. */
export type OutlineViewProps =
  ConvViewProps & InjectFace<StudioApiInjected> & PropsLocale<'studio-panel'>

export function OutlineView({ fetchStudioApi, postStudioApi, t }: OutlineViewProps) {
  const workbench = useWorkbench()
  const [state, setState] = useState<LoadState>('loading')
  const [payload, setPayload] = useState<OutlinePayload | null>(null)
  const [error, setError] = useState('')
  const [collapsed, setCollapsed] = useState<ReadonlySet<string>>(new Set())
  const [selectedNodeId, setSelectedNodeId] = useState('')
  const [drafts, setDrafts] = useState<Record<string, FieldDraft>>({})
  const [busy, setBusy] = useState(false)
  const [toast, setToast] = useState<{ text: string, bad: boolean } | null>(null)

  const load = useCallback(() => {
    setState('loading')
    setDrafts({})
    let cancelled = false
    fetchStudioApi('/outline')
      .then((data) => {
        if (cancelled) return
        const next = parseOutline(data)
        setPayload(next)
        let selected = workbench.currentChapterId
        const collapsedNodes = new Set<string>()
        const visit = (node: OutlineNode): boolean => {
          const childContains = node.children.map(visit).some(Boolean)
          const containsTarget = node.id === selected || childContains
          if (node.children.length > 0 && !containsTarget) collapsedNodes.add(node.id)
          return containsTarget
        }
        const found = next.roots.map(visit).some(Boolean)
        if (!found) selected = next.roots[0]?.id ?? ''
        setSelectedNodeId(selected)
        setCollapsed(collapsedNodes)
        setState('ready')
      })
      .catch((cause: unknown) => {
        if (cancelled) return
        setError(cause instanceof Error ? cause.message : String(cause))
        setState('error')
      })
    return () => { cancelled = true }
  }, [fetchStudioApi, workbench.currentChapterId])

  useEffect(() => load(), [load])

  const showToast = (text: string, bad: boolean) => {
    setToast({ text, bad })
    window.setTimeout(() => setToast(null), 6000)
  }

  /** Patch one node's draft overlay. */
  const setDraft = (id: string, patch: FieldDraft) => {
    setDrafts(previous => ({ ...previous, [id]: { ...previous[id], ...patch } }))
  }

  const clearDraft = (id: string, field: 'title' | 'summary') => {
    setDrafts(previous => {
      const next = { ...previous }
      const entry = { ...next[id] }
      delete entry[field]
      if (Object.keys(entry).length === 0) delete next[id]
      else next[id] = entry
      return next
    })
  }

  /**
   * Run one structural operation. Success bumps the revision silently (the
   * optimistic local patch already reflects the edit — no re-render, focus
   * survives); failure reverts the field and toasts; 409 reloads the tree.
   * Returns true when the local patch should stick.
   */
  const runOp = useCallback(async (
    op: { operation: string, node_id?: string, title?: string, summary?: string, kind?: string },
  ): Promise<boolean> => {
    if (payload === null || busy) return false
    setBusy(true)
    try {
      const data = await postStudioApi('/outline/edit', { ...op, revision: payload.revision }) as Record<string, unknown>
      const fresh = (data.outline ?? null) as Record<string, unknown> | null
      if (fresh !== null) {
        const nextRevision = String(fresh.revision ?? payload.revision)
        setPayload(previous => previous === null ? previous : { ...previous, revision: nextRevision })
      }
      return true
    } catch (cause: unknown) {
      if (cause instanceof StudioApiError && cause.status === 409) {
        load()
        showToast(t('outline.opConflict'), true)
      } else {
        showToast(`${t('outline.opFailed')}: ${cause instanceof Error ? cause.message : String(cause)}`, true)
      }
      return false
    } finally {
      setBusy(false)
    }
  }, [payload, busy, postStudioApi, load, t])

  /** Title blur/Enter: commit a rename when the value actually changed. */
  const commitTitle = async (node: OutlineNode) => {
    const value = (drafts[node.id]?.title ?? node.title).trim()
    if (value === '' || value === node.title) {
      clearDraft(node.id, 'title')
      return
    }
    const ok = await runOp({ operation: 'rename', node_id: node.id, title: value })
    if (ok) clearDraft(node.id, 'title')
  }

  /** Body blur: commit update_summary when the block actually changed. */
  const commitSummary = async (node: OutlineNode) => {
    const value = drafts[node.id]?.summary ?? node.summary
    if (value === node.summary) {
      clearDraft(node.id, 'summary')
      return
    }
    const ok = await runOp({ operation: 'update_summary', node_id: node.id, summary: value })
    if (ok) clearDraft(node.id, 'summary')
  }

  const toggle = (id: string) => {
    setCollapsed(previous => {
      const next = new Set(previous)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  const findNode = (roots: OutlineNode[], id: string): OutlineNode | null => {
    for (const root of roots) {
      if (root.id === id) return root
      const hit = findNode(root.children, id)
      if (hit !== null) return hit
    }
    return null
  }

  /** Inline add form state: '' nodeId = top-level volume; otherwise child/sibling. */
  const [addForm, setAddForm] = useState<{ mode: 'child' | 'after' | 'volume', nodeId: string, kind: string, text: string } | null>(null)

  const commitAdd = async () => {
    if (addForm === null || payload === null) return
    const title = addForm.text.trim()
    if (title === '') {
      setAddForm(null)
      return
    }
    const op = addForm.mode === 'volume'
      ? { operation: 'add_child', node_id: '', kind: addForm.kind, title }
      : addForm.mode === 'child'
        ? { operation: 'add_child', node_id: addForm.nodeId, kind: addForm.kind, title }
        : { operation: 'add_after', node_id: addForm.nodeId, kind: addForm.kind, title }
    const ok = await runOp(op)
    if (ok) setAddForm(null)
  }

  const renderAddForm = (): ReactNode => {
    if (addForm === null) return null
    const kindHint = addForm.mode === 'volume' ? 'volume' : addForm.kind
    return (
      <div className={css.inlineActions}>
        <input
          className={css.inlineInput}
          value={addForm.text}
          autoFocus
          placeholder={`${t('outline.newTitlePlaceholder')} (${kindHint})`}
          onChange={(event) => { setAddForm({ ...addForm, text: event.target.value }) }}
          onKeyDown={(event) => {
            if (event.key === 'Enter') void commitAdd()
            if (event.key === 'Escape') setAddForm(null)
          }}
          onBlur={() => { if (addForm.text.trim() === '') setAddForm(null) }}
        />
        <button type="button" className={css.actionButton} disabled={busy} onClick={() => { void commitAdd() }}>✓</button>
        <button type="button" className={css.actionButton} onClick={() => { setAddForm(null) }}>✕</button>
      </div>
    )
  }

  const renderNode = (node: OutlineNode): ReactNode => {
    const isCollapsed = collapsed.has(node.id)
    const hasChildren = node.children.length > 0
    const editable = node.editable === true
    const titleValue = drafts[node.id]?.title ?? node.title
    const summaryValue = drafts[node.id]?.summary ?? node.summary
    const summaryDirty = (drafts[node.id]?.summary ?? '') !== '' && summaryValue !== node.summary
    return (
      <li key={node.id} className={css.treeItem}>
        <div className={css.treeRow} data-selected={selectedNodeId === node.id} onClick={() => setSelectedNodeId(node.id)}>
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
          {editable
            ? (
              <input
                className={css.titleInput}
                value={titleValue}
                onChange={(event) => { setDraft(node.id, { title: event.target.value }) }}
                onKeyDown={(event) => {
                  if (event.key === 'Enter') { event.currentTarget.blur() }
                  if (event.key === 'Escape') {
                    setDraft(node.id, { title: node.title })
                    event.currentTarget.blur()
                  }
                }}
                onBlur={() => { void commitTitle(node) }}
              />
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
          {editable && (
            <span className={css.nodeActions}>
              {node.child_kind !== '' && (
                <button type="button" className={css.actionButton} title={t('outline.addChild')}
                  onClick={() => {
                    if (hasChildren && collapsed.has(node.id)) toggle(node.id)
                    setAddForm({ mode: 'child', nodeId: node.id, kind: node.child_kind ?? '', text: '' })
                  }}>
                  +{t('outline.addChild')}
                </button>
              )}
              <button type="button" className={css.actionButton} title={t('outline.addAfter')}
                onClick={() => { setAddForm({ mode: 'after', nodeId: node.id, kind: node.kind, text: '' }) }}>
                +{t('outline.addAfter')}
              </button>
              <button
                type="button"
                className={css.actionButton}
                title={node.can_delete === false ? node.delete_blocked_reason : t('outline.del')}
                disabled={node.can_delete !== true || busy}
                onClick={() => {
                  if (window.confirm(`${t('outline.confirmDelete')}「${node.title}」`)) {
                    void runOp({ operation: 'delete', node_id: node.id })
                  }
                }}
              >
                {t('outline.del')}
              </button>
            </span>
          )}
        </div>
        {selectedNodeId === node.id && (editable
          ? (
            <textarea
              className={`${css.bodyTextarea}${summaryDirty ? ` ${css.bodyTextareaDirty}` : ''}`}
              value={summaryValue}
              rows={Math.min(16, Math.max(1, summaryValue.split('\n').length))}
              placeholder={summaryValue === '' ? t('outline.summaryEmpty') : undefined}
              onChange={(event) => { setDraft(node.id, { summary: event.target.value }) }}
              onBlur={() => { void commitSummary(node) }}
            />
          )
          : node.summary !== '' && <div className={css.nodeSummary}>{node.summary}</div>)}
        {addForm !== null && addForm.mode === 'after' && addForm.nodeId === node.id && renderAddForm()}
        {hasChildren && !isCollapsed && (
          <ul className={css.treeChildren}>
            {node.children.map(renderNode)}
            {addForm !== null && addForm.mode === 'child' && addForm.nodeId === node.id && renderAddForm()}
          </ul>
        )}
      </li>
    )
  }

  const addVolume = () => {
    setAddForm({ mode: 'volume', nodeId: '', kind: 'volume', text: '' })
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
          <div className={css.notice}>{renderAddForm() ?? t('outline.empty')}</div>
        )}
        {state === 'ready' && payload !== null && payload.roots.length > 0 && (
          <>
            {renderAddForm()}
            <ul className={css.tree}>{payload.roots.map(renderNode)}</ul>
          </>
        )}
      </div>
    </div>
  )
}
