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

import { useCallback, useEffect, useMemo, useState, type ReactNode } from 'react'
import type { ConvViewProps } from '@deepseek-ai/dsh-client-ui-conversation/client'
import type { InjectFace, PropsLocale } from '@deepseek-ai/dsh-client-ui-slots'
import { StudioApiError, type StudioApiInjected } from './api.ts'
import { loadPlans, planColor, type PlanInfo, type PlanTreeNode } from './OutlinePlans.tsx'
import { SceneWorkbench } from './SceneWorkbench.tsx'
import { useWorkbench } from './WorkbenchStore.ts'
import css from './views.module.css'

function asText(value: unknown, fallback = ''): string {
  return typeof value === 'string' ? value : fallback
}
function asObj(value: unknown): Record<string, unknown> {
  return value !== null && typeof value === 'object' ? (value as Record<string, unknown>) : {}
}

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

function resizeSummaryTextarea(element: HTMLTextAreaElement | null): void {
  if (element === null) return
  element.style.height = 'auto'
  element.style.height = `${element.scrollHeight}px`
}

function outlineChapterNumber(value: string): number | null {
  const match = /ch_0*(\d+)/.exec(value)
  return match === null ? null : Number(match[1])
}

/** Find the latest chapter that already has manuscript content. */
function latestDraftedChapter(roots: readonly OutlineNode[]): OutlineNode | null {
  let latest: OutlineNode | null = null
  const visit = (node: OutlineNode) => {
    if (node.kind === 'chapter' && node.status === 'drafted') {
      const currentNumber = outlineChapterNumber(node.id) ?? -1
      const latestNumber = latest === null ? -1 : outlineChapterNumber(latest.id) ?? -1
      if (latest === null || currentNumber > latestNumber) latest = node
    }
    node.children.forEach(visit)
  }
  roots.forEach(visit)
  return latest
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
  const [plans, setPlans] = useState<PlanInfo[]>([])
  const [activePlan, setActivePlan] = useState('')
  const [editor, setEditor] = useState<{ id: string, label: string, text: string, revision: string } | null>(null)
  const [draftBusy, setDraftBusy] = useState(false)

  const load = useCallback(() => {
    setState('loading')
    setDrafts({})
    let cancelled = false
    fetchStudioApi('/outline')
      .then((data) => {
        if (cancelled) return
        const next = parseOutline(data)
        setPayload(next)
        // The workspace pointer can lag behind the manuscript. Prefer the
        // latest drafted chapter so opening the outline reveals the current
        // end of the written content automatically.
        let selected = latestDraftedChapter(next.roots)?.id ?? workbench.currentChapterId
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
  useEffect(() => {
    let on = true
    loadPlans(postStudioApi)
      .then(loaded => { if (on) setPlans(loaded) })
      .catch(() => { /* 预演列表可选：失败不阻塞大纲编辑 */ })
    return () => { on = false }
  }, [postStudioApi])

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
    // 预演颜色：凡是当前接续预演里长出来的节点，行首标该预演颜色（其余与正式树一致）
    const planIndex = activePlan === '' ? -1 : plans.findIndex(plan => plan.id === activePlan)
    const pvColor = planIndex >= 0 ? planColor(planIndex).bar : ''
    const pvPrefix = activePlan === ''
      ? ''
      : (activePlan.includes('::') ? activePlan.replace('::', '-') : activePlan)
    const isPv = pvPrefix !== '' && (node.id.startsWith(pvPrefix) || node.id.startsWith(activePlan))
    return (
      <li key={node.id} className={css.treeItem} style={isPv ? { borderLeft: `3px solid ${pvColor}`, paddingLeft: 4 } : undefined}>
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
              ref={resizeSummaryTextarea}
              value={summaryValue}
              rows={1}
              placeholder={summaryValue === '' ? t('outline.summaryEmpty') : undefined}
              onChange={(event) => {
                setDraft(node.id, { summary: event.target.value })
                resizeSummaryTextarea(event.currentTarget)
              }}
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

  const collectBranchIds = (nodes: OutlineNode[]): string[] => nodes.flatMap(node => [node.id, ...collectBranchIds(node.children)])
  const expandAll = () => setCollapsed(new Set())
  const collapseAll = () => {
    if (payload === null) return
    setCollapsed(new Set(collectBranchIds(payload.roots)))
  }

  const activePlanInfo = activePlan === '' ? undefined : plans.find(plan => plan.id === activePlan)
  /** 把选中的预演“接”进正式大纲树（挂在卷下、颜色区分；结构与正式完全一致）。 */
  const displayRoots = useMemo<OutlineNode[]>(() => {
    if (payload === null) return []
    if (activePlanInfo === undefined || activePlanInfo.nodes.length === 0) return payload.roots
    const clone: OutlineNode[] = JSON.parse(JSON.stringify(payload.roots)) as OutlineNode[]
    const volume = clone.find(node => node.kind === 'volume')
    if (volume === undefined) return payload.roots
    const convert = (nodes: PlanTreeNode[]): OutlineNode[] => nodes.map(node => ({
      id: node.id,
      kind: node.kind,
      label: node.label,
      title: node.title,
      summary: node.summary,
      status: 'planned' as const,
      children: convert(node.children),
      descendant_count: 0,
      editable: false,
      can_delete: false,
    }) as unknown as OutlineNode)
    // 目标容器：当前最后一“幕”。预演直接接在它的结尾，层级/缩进与正式节、章完全一致。
    const acts = volume.children.filter(node => node.kind === 'act')
    const lastAct = acts.length > 0 ? acts[acts.length - 1] : undefined
    if (lastAct === undefined) return payload.roots
    // 预演顶层若是幕，取它的子节；否则直接用（节/章）。这样不会额外长出“幕”。
    const sources: PlanTreeNode[] = activePlanInfo.nodes.flatMap(node =>
      node.kind === 'act' ? node.children : [node])
    const graft: PlanTreeNode[] = sources.length > 0 && sources.every(node => node.kind === 'chapter')
      ? [{
          id: `${activePlan}-wrap`,
          kind: 'section',
          label: '节',
          title: activePlanInfo.label,
          summary: activePlanInfo.idea || activePlanInfo.meta,
          children: sources,
        }]
      : sources
    lastAct.children = [...(lastAct.children ?? []), ...convert(graft)]
    return clone
  }, [payload, plans, activePlan, activePlanInfo])

  // ---------- 草案管理（新建 / 编辑 / 删除 / 并入正式大纲）----------
  const reloadPlans = useCallback(() => {
    loadPlans(postStudioApi)
      .then(loaded => setPlans(loaded))
      .catch(() => { /* 忽略：大纲仍可编辑 */ })
  }, [postStudioApi])
  const activeRolling = activePlanInfo !== undefined && activePlanInfo.kind === 'rolling' ? activePlanInfo : undefined

  const createNewDraft = async () => {
    setDraftBusy(true)
    try {
      const data = asObj(await postStudioApi('/rolling-plans', { action: 'create', window_size: 5 }))
      setEditor({
        id: asText(data.candidate_id),
        label: asText(data.direction) || asText(data.candidate_id),
        text: '',
        revision: asText(data.revision),
      })
      await reloadPlans()
    } catch (cause) {
      setToast({ text: cause instanceof Error ? cause.message : String(cause), bad: true })
    } finally {
      setDraftBusy(false)
    }
  }
  const openEditDraft = (plan: PlanInfo) => {
    setEditor({ id: plan.id, label: plan.label, text: plan.proposal ?? '', revision: plan.revision ?? '' })
  }
  const saveDraft = async () => {
    if (editor === null) return
    setDraftBusy(true)
    try {
      await postStudioApi('/rolling-plans', {
        action: 'stage',
        candidate_id: editor.id,
        proposal: editor.text,
        revision: editor.revision,
      })
      setToast({ text: `草案已保存（${editor.label}）`, bad: false })
      setEditor(null)
      await reloadPlans()
    } catch (cause) {
      setToast({ text: cause instanceof Error ? cause.message : String(cause), bad: true })
    } finally {
      setDraftBusy(false)
    }
  }
  const deleteDraft = async (plan: PlanInfo) => {
    if (!window.confirm(`删除草案「${plan.label}」？（只删候选，不改大纲）`)) return
    setDraftBusy(true)
    try {
      await postStudioApi('/rolling-plans', { action: 'delete', candidate_id: plan.id, revision: plan.revision ?? '' })
      if (activePlan === plan.id) setActivePlan('')
      setToast({ text: `已删除草案「${plan.label}」`, bad: false })
      await reloadPlans()
    } catch (cause) {
      setToast({ text: cause instanceof Error ? cause.message : String(cause), bad: true })
    } finally {
      setDraftBusy(false)
    }
  }
  const applyDraft = async (plan: PlanInfo) => {
    if (!window.confirm(`把草案「${plan.label}」并入正式大纲（只追加不冲突的章节）？\n\n会写入 src/outline.md。`)) return
    setDraftBusy(true)
    try {
      const data = asObj(await postStudioApi('/rolling-plans', {
        action: 'apply',
        candidate_id: plan.id,
        revision: plan.revision ?? '',
      }))
      setToast({ text: asText(data.message, '已并入'), bad: false })
      await load()
      await reloadPlans()
    } catch (cause) {
      setToast({ text: cause instanceof Error ? cause.message : String(cause), bad: true })
    } finally {
      setDraftBusy(false)
    }
  }

  return (
    <div className={css.root}>
      <div className={css.toolbar}>
        {payload !== null && state === 'ready' && (
          <span className={css.toolbarMeta}>
            {t('outline.draftedCount')}: {payload.drafted_chapters}
          </span>
        )}
        <span className={css.toolbarMeta}>
          <label style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>
            接预演
            <select
              value={activePlan}
              onChange={(event) => { setActivePlan(event.target.value) }}
              style={{ maxWidth: 220 }}
            >
              <option value="">（不接 · 仅正式大纲）</option>
              {plans.map(plan => (
                <option key={plan.id} value={plan.id}>
                  {plan.kind === 'rolling' ? '草案·' : '方向·'}{plan.label}
                </option>
              ))}
            </select>
          </label>
        </span>
        <button type="button" className={css.button} disabled={busy} onClick={addVolume}>
          {t('outline.addVolume')}
        </button>
        <button type="button" className={css.button} disabled={busy || payload === null} onClick={expandAll}>
          {t('outline.expandAll')}
        </button>
        <button type="button" className={css.button} disabled={busy || payload === null} onClick={collapseAll}>
          {t('outline.collapseAll')}
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
      {activePlanInfo !== undefined && activePlanInfo.idea !== '' && (
        <div className={css.notice} title={activePlanInfo.idea}>
          <span className={css.toolbarMeta}>构思：{activePlanInfo.idea}</span>
        </div>
      )}
      <div className={css.toolbar} style={{ marginTop: 4 }}>
        <button type="button" className={css.button} disabled={draftBusy || payload === null} onClick={() => { void createNewDraft() }}>
          ＋新建草案
        </button>
        {activeRolling !== undefined && (
          <>
            <button type="button" className={css.button} disabled={draftBusy} onClick={() => { openEditDraft(activeRolling) }}>
              编辑草案
            </button>
            <button type="button" className={css.button} disabled={draftBusy} onClick={() => { void applyDraft(activeRolling) }}>
              并入正式大纲
            </button>
            <button type="button" className={css.button} disabled={draftBusy} onClick={() => { void deleteDraft(activeRolling) }}>
              删除草案
            </button>
          </>
        )}
        {editor !== null && (
          <span className={css.toolbarMeta}>正在编辑：{editor.label}</span>
        )}
      </div>
      {editor !== null && (
        <div className={css.notice} style={{ display: 'flex', flexDirection: 'column', gap: 8, padding: 8 }}>
          <textarea
            className={css.bodyTextarea}
            rows={12}
            value={editor.text}
            placeholder={'粘贴/编写 Markdown 大纲草案（# 篇 / ## 节 / ### 第N章 …）'}
            onChange={(event) => { setEditor({ ...editor, text: event.target.value }) }}
          />
          <div style={{ display: 'flex', gap: 8 }}>
            <button type="button" className={css.button} disabled={draftBusy} onClick={() => { void saveDraft() }}>
              保存草案（stage）
            </button>
            <button type="button" className={css.button} onClick={() => { setEditor(null) }}>
              取消
            </button>
          </div>
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
            <ul className={css.tree}>{displayRoots.map(renderNode)}</ul>
          </>
        )}
      </div>
      <SceneWorkbench fetchStudioApi={fetchStudioApi} postStudioApi={postStudioApi} />
    </div>
  )
}
