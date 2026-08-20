/**
 * Asset editor + create form for the 资产 tab. The write surface is exactly
 * the server's contract (verified against OpenWrite tools/structured_assets.py
 * create/update and tools/studio_application.py create_asset/update_asset):
 *
 * - Update: POST /api/assets/update { kind, id, revision, data } — `revision`
 *   is the optimistic lock (the detail's fingerprint); a stale revision
 *   answers 409 ASSET_CONFLICT. `data` merges into the front matter, filtered
 *   server-side to CHARACTER_FIELDS / WORLD_FIELDS (character: name, aliases,
 *   tier, summary, tags, personality, goal, fear, taboos, appearance, voice,
 *   current_state, organization, progression_system, progression_stage,
 *   detail_refs, related; world: name, kind, type, subtype, summary, status,
 *   tags, detail_refs, related). Relations edit through data.related as
 *   strings or { target, kind, note } dicts. Progression merges data into the
 *   YAML document (absent keys, e.g. stages, are preserved).
 * - Create: POST /api/assets { kind, id, data } — id must match
 *   [A-Za-z0-9][A-Za-z0-9_.-]{0,79}; progression requires a non-empty stages
 *   list of { id, name } and kind in ability/rank/cultivation/career/
 *   reputation/curse/custom.
 */

import { useState } from 'react'
import { MarkdownText } from '@deepseek-ai/dsh-client-ui-primitives'
import type { PropsLocale } from '@deepseek-ai/dsh-client-ui-slots'
import css from './views.module.css'

/** The summary fields the editor needs from the parsed detail. */
export interface AssetEditorSource {
  name: string
  summary: string
  aliases: string[]
  tags: string[]
  scalars: { key: string; value: string }[]
  /** List-typed whitelist fields (taboos/detail_refs), edited one entry per line. */
  lists: { key: string; items: string[] }[]
  related: RelationDraft[]
  /** The markdown body (body_markdown), edited with a preview toggle. */
  body: string
  /**
   * Derived relations (incoming edges and annotation-sourced entries) shown
   * read-only in the editor. They live in OTHER assets' front matter (or in
   * body annotations), so they are not editable here — but hiding them made
   * the editor look broken next to the read view, which shows them.
   */
  derivedRelations: DerivedRelation[]
}

/** One derived (non-editable) relation row for editor display. */
export interface DerivedRelation {
  name: string
  note: string
  direction: 'outgoing' | 'incoming'
  origin: string
}

/** One editable frontmatter relation row. */
export interface RelationDraft {
  target: string
  kind: string
  note: string
}

/** A relation-target candidate from the loaded asset list. */
export interface RelationCandidate {
  id: string
  name: string
  kind: string
}

type TFunc = PropsLocale<'studio-panel'>['t']

/** Split a comma/、/，-separated input into a clean string list. */
function splitList(value: string): string[] {
  return value.split(/[,、，]/).map(item => item.trim()).filter(item => item !== '')
}

/** Split a one-entry-per-line textarea into a clean string list (Studio's line-join semantics). */
function splitLines(value: string): string[] {
  return value.split('\n').map(item => item.trim()).filter(item => item !== '')
}

/** Localized label for a list-typed whitelist field (raw key as fallback). */
function listLabel(key: string, t: TFunc): string {
  switch (key) {
    case 'detail_refs': return t('assets.list.detail_refs')
    case 'taboos': return t('assets.list.taboos')
    default: return key
  }
}

/** Scalar keys always shown even when absent from the current front matter. */
const ALWAYS_SCALARS: Record<string, readonly string[]> = {
  character: ['tier', 'personality', 'goal', 'current_state'],
  world: ['type', 'subtype', 'status'],
  progression: ['kind'],
}

interface AssetEditorProps {
  kind: string
  /** Current values from the freshly loaded detail (remount on revision change resets the draft). */
  source: AssetEditorSource
  candidates: readonly RelationCandidate[]
  saving: boolean
  saveError: string | null
  conflict: boolean
  onSave: (data: Record<string, unknown>, bodyMarkdown: string) => void
  onCancel: () => void
  onRefresh: () => void
  t: TFunc
}

/** Read-write editor over one asset's allowed front-matter fields. */
export function AssetEditor({ kind, source, candidates, saving, saveError, conflict, onSave, onCancel, onRefresh, t }: AssetEditorProps) {
  const [name, setName] = useState(source.name)
  const [summary, setSummary] = useState(source.summary)
  const [aliasesText, setAliasesText] = useState(source.aliases.join('、'))
  const [tagsText, setTagsText] = useState(source.tags.join('、'))
  const [scalars, setScalars] = useState<Record<string, string>>(() => {
    const initial: Record<string, string> = {}
    for (const { key, value } of source.scalars) initial[key] = value
    for (const key of ALWAYS_SCALARS[kind] ?? []) initial[key] ??= ''
    return initial
  })
  const [related, setRelated] = useState<RelationDraft[]>(source.related.map(row => ({ ...row })))
  const [listsText, setListsText] = useState<Record<string, string>>(() =>
    Object.fromEntries(source.lists.map(list => [list.key, list.items.join('\n')])))
  const [newTarget, setNewTarget] = useState('')
  const [newNote, setNewNote] = useState('')
  const [bodyDraft, setBodyDraft] = useState(source.body)
  const [bodyMode, setBodyMode] = useState<'edit' | 'preview'>('edit')

  const scalarKeys = Object.keys(scalars)
  const save = () => {
    const data: Record<string, unknown> = {
      name: name.trim(),
      summary,
      aliases: splitList(aliasesText),
      tags: splitList(tagsText),
    }
    for (const [key, value] of Object.entries(scalars)) {
      if (value !== '') data[key] = value
    }
    // List fields serialize back as arrays, one entry per line.
    for (const [key, value] of Object.entries(listsText)) {
      data[key] = splitLines(value)
    }
    // character/world only: related is the editable front-matter list
    // (relation_view's incoming/annotation entries are derived, not edited).
    if (kind !== 'progression') {
      data['related'] = related
        .filter(row => row.target.trim() !== '')
        .map(row => row.note.trim() === '' && row.kind === 'related'
          ? row.target.trim()
          : { target: row.target.trim(), kind: row.kind.trim() || 'related', note: row.note.trim() })
    }
    onSave(data, bodyDraft)
  }

  return (
    <div className={css.editor}>
      <label className={css.editorRow}>
        <span className={css.editorLabel}>{t('assets.edit.name')}</span>
        <input className={css.input} value={name} onChange={event => { setName(event.target.value) }} disabled={saving} />
      </label>
      <label className={css.editorRow}>
        <span className={css.editorLabel}>{t('assets.edit.summary')}</span>
        <textarea className={css.textarea} rows={3} value={summary} onChange={event => { setSummary(event.target.value) }} disabled={saving} />
      </label>
      <label className={css.editorRow}>
        <span className={css.editorLabel}>{t('assets.aliases')}</span>
        <input className={css.input} value={aliasesText} placeholder={t('assets.edit.listHint')} onChange={event => { setAliasesText(event.target.value) }} disabled={saving} />
      </label>
      <label className={css.editorRow}>
        <span className={css.editorLabel}>{t('assets.edit.tags')}</span>
        <input className={css.input} value={tagsText} placeholder={t('assets.edit.listHint')} onChange={event => { setTagsText(event.target.value) }} disabled={saving} />
      </label>
      {scalarKeys.map(key => (
        <label key={key} className={css.editorRow}>
          <span className={css.editorLabel}>{key}</span>
          <input
            className={css.input}
            value={scalars[key] ?? ''}
            onChange={event => { setScalars(previous => ({ ...previous, [key]: event.target.value })) }}
            disabled={saving}
          />
        </label>
      ))}
      {Object.keys(listsText).map(key => (
        <label key={key} className={css.editorRow}>
          <span className={css.editorLabel}>{listLabel(key, t)}</span>
          <textarea
            className={css.textarea}
            rows={Math.max(2, splitLines(listsText[key] ?? '').length + 1)}
            value={listsText[key] ?? ''}
            placeholder={t('assets.edit.linesHint')}
            onChange={event => { setListsText(previous => ({ ...previous, [key]: event.target.value })) }}
            disabled={saving}
          />
        </label>
      ))}
      {kind !== 'progression' && (
        <div className={css.editorRow}>
          <span className={css.editorLabel}>{t('assets.detail.relations')}</span>
          <div className={css.relationEditor}>
            {related.map((row, index) => (
              <div key={index} className={css.relationRow}>
                <input
                  className={css.input}
                  value={row.target}
                  list="studio-panel-relation-targets"
                  placeholder={t('assets.edit.relationTarget')}
                  onChange={event => {
                    const value = event.target.value
                    setRelated(previous => previous.map((item, at) => (at === index ? { ...item, target: value } : item)))
                  }}
                  disabled={saving}
                />
                <input
                  className={css.input}
                  value={row.note}
                  placeholder={t('assets.edit.relationNote')}
                  onChange={event => {
                    const value = event.target.value
                    setRelated(previous => previous.map((item, at) => (at === index ? { ...item, note: value } : item)))
                  }}
                  disabled={saving}
                />
                <button
                  type="button"
                  className={css.iconButton}
                  aria-label={t('assets.edit.removeRelation')}
                  onClick={() => { setRelated(previous => previous.filter((_, at) => at !== index)) }}
                  disabled={saving}
                >
                  ×
                </button>
              </div>
            ))}
            <div className={css.relationRow}>
              <input
                className={css.input}
                value={newTarget}
                list="studio-panel-relation-targets"
                placeholder={t('assets.edit.relationTarget')}
                onChange={event => { setNewTarget(event.target.value) }}
                disabled={saving}
              />
              <input
                className={css.input}
                value={newNote}
                placeholder={t('assets.edit.relationNote')}
                onChange={event => { setNewNote(event.target.value) }}
                disabled={saving}
              />
              <button
                type="button"
                className={css.button}
                disabled={saving || newTarget.trim() === ''}
                onClick={() => {
                  setRelated(previous => [...previous, { target: newTarget.trim(), kind: 'related', note: newNote.trim() }])
                  setNewTarget('')
                  setNewNote('')
                }}
              >
                {t('assets.edit.addRelation')}
              </button>
            </div>
            <datalist id="studio-panel-relation-targets">
              {candidates.map(candidate => (
                <option key={`${candidate.kind}:${candidate.id}`} value={candidate.id}>
                  {candidate.name !== '' ? `${candidate.name} (${candidate.id})` : candidate.id}
                </option>
              ))}
            </datalist>
            {source.derivedRelations.length > 0 && (
              <div className={css.derivedRelations}>
                <div className={css.derivedTitle}>{t('assets.edit.derivedRelations')}</div>
                {source.derivedRelations.map((relation, index) => (
                  <div key={`${relation.direction}:${relation.name}:${index}`} className={css.derivedRow}>
                    <span className={css.derivedArrow}>{relation.direction === 'incoming' ? '←' : '→'}</span>
                    <span className={css.derivedName}>{relation.name}</span>
                    {relation.note !== '' && <span className={css.derivedNote}>{relation.note}</span>}
                    <span className={css.derivedOrigin}>
                      {relation.direction === 'incoming'
                        ? t('assets.relation.incoming')
                        : t('assets.relation.registered')}
                    </span>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      )}
      <div className={css.editorRow}>
        <span className={css.editorLabel}>{t('assets.edit.body')}</span>
        <div className={css.bodyEditor}>
          <div className={css.bodyToggleRow} role="group" aria-label={t('assets.edit.body')}>
            <button
              type="button"
              className={css.chip}
              data-active={bodyMode === 'edit'}
              onClick={() => { setBodyMode('edit') }}
              disabled={saving}
            >
              {t('assets.edit.mode.edit')}
            </button>
            <button
              type="button"
              className={css.chip}
              data-active={bodyMode === 'preview'}
              onClick={() => { setBodyMode('preview') }}
              disabled={saving}
            >
              {t('assets.edit.mode.preview')}
            </button>
          </div>
          {bodyMode === 'edit'
            ? (
              <textarea
                className={css.textarea}
                rows={8}
                value={bodyDraft}
                onChange={event => { setBodyDraft(event.target.value) }}
                disabled={saving}
              />
            )
            : (
              <div className={css.detailBody}>
                {bodyDraft.trim() === ''
                  ? <span className={css.detailNotice}>{t('assets.edit.bodyEmpty')}</span>
                  : <MarkdownText text={bodyDraft} />}
              </div>
            )}
        </div>
      </div>
      {conflict && (
        <div className={css.conflictNotice}>
          <span className={css.errorText}>{saveError ?? t('assets.edit.conflict')}</span>
          <button type="button" className={css.button} onClick={onRefresh} disabled={saving}>
            {t('assets.edit.conflictRefresh')}
          </button>
        </div>
      )}
      {!conflict && saveError !== null && <div className={css.errorText}>{saveError}</div>}
      <div className={css.editorActions}>
        <button type="button" className={css.primaryButton} onClick={save} disabled={saving || name.trim() === ''}>
          {saving ? t('assets.edit.saving') : t('assets.edit.save')}
        </button>
        <button type="button" className={css.button} onClick={onCancel} disabled={saving}>
          {t('assets.edit.cancel')}
        </button>
      </div>
    </div>
  )
}

interface NewAssetFormProps {
  kind: 'character' | 'world' | 'progression'
  busy: boolean
  error: string | null
  onSubmit: (payload: { id: string; data: Record<string, unknown> }) => void
  onCancel: () => void
  t: TFunc
}

const PROGRESSION_KINDS = ['ability', 'rank', 'cultivation', 'career', 'reputation', 'curse', 'custom'] as const

/** Inline create form for one asset kind (minimal required fields per the server contract). */
export function NewAssetForm({ kind, busy, error, onSubmit, onCancel, t }: NewAssetFormProps) {
  const [id, setId] = useState('')
  const [name, setName] = useState('')
  const [summary, setSummary] = useState('')
  const [extra, setExtra] = useState('')
  const [stages, setStages] = useState<{ id: string; name: string }[]>([{ id: '', name: '' }])

  const extraLabel = kind === 'character' ? t('assets.create.tier') : kind === 'world' ? t('assets.create.type') : ''
  const validId = /^[A-Za-z0-9][A-Za-z0-9_.-]{0,79}$/.test(id) && !id.includes('..')
  const validStages = kind !== 'progression' || stages.some(stage => stage.id.trim() !== '' && stage.name.trim() !== '')
  const canSubmit = validId && (kind !== 'progression' || name.trim() !== '') && validStages && !busy

  const submit = () => {
    const data: Record<string, unknown> = { name: name.trim() || id }
    if (summary.trim() !== '') data['summary'] = summary.trim()
    if (kind === 'character' && extra.trim() !== '') data['tier'] = extra.trim()
    if (kind === 'world' && extra.trim() !== '') data['type'] = extra.trim()
    if (kind === 'progression') {
      data['kind'] = PROGRESSION_KINDS.includes(extra as (typeof PROGRESSION_KINDS)[number]) ? extra : 'ability'
      data['stages'] = stages
        .filter(stage => stage.id.trim() !== '' && stage.name.trim() !== '')
        .map(stage => ({ id: stage.id.trim(), name: stage.name.trim() }))
    }
    onSubmit({ id: id.trim(), data })
  }

  return (
    <div className={css.editor}>
      <label className={css.editorRow}>
        <span className={css.editorLabel}>ID</span>
        <input
          className={css.input}
          value={id}
          placeholder={t('assets.create.idHint')}
          onChange={event => { setId(event.target.value) }}
          disabled={busy}
          data-invalid={id !== '' && !validId}
        />
      </label>
      <label className={css.editorRow}>
        <span className={css.editorLabel}>{t('assets.edit.name')}</span>
        <input className={css.input} value={name} onChange={event => { setName(event.target.value) }} disabled={busy} />
      </label>
      <label className={css.editorRow}>
        <span className={css.editorLabel}>{t('assets.edit.summary')}</span>
        <textarea className={css.textarea} rows={2} value={summary} onChange={event => { setSummary(event.target.value) }} disabled={busy} />
      </label>
      {kind !== 'progression' && (
        <label className={css.editorRow}>
          <span className={css.editorLabel}>{extraLabel}</span>
          <input className={css.input} value={extra} onChange={event => { setExtra(event.target.value) }} disabled={busy} />
        </label>
      )}
      {kind === 'progression' && (
        <>
          <label className={css.editorRow}>
            <span className={css.editorLabel}>{t('assets.create.progressionKind')}</span>
            <select className={css.input} value={extra || 'ability'} onChange={event => { setExtra(event.target.value) }} disabled={busy}>
              {PROGRESSION_KINDS.map(value => <option key={value} value={value}>{value}</option>)}
            </select>
          </label>
          <div className={css.editorRow}>
            <span className={css.editorLabel}>{t('assets.create.stages')}</span>
            <div className={css.relationEditor}>
              {stages.map((stage, index) => (
                <div key={index} className={css.relationRow}>
                  <input
                    className={css.input}
                    value={stage.id}
                    placeholder={t('assets.create.stageId')}
                    onChange={event => {
                      const value = event.target.value
                      setStages(previous => previous.map((item, at) => (at === index ? { ...item, id: value } : item)))
                    }}
                    disabled={busy}
                  />
                  <input
                    className={css.input}
                    value={stage.name}
                    placeholder={t('assets.create.stageName')}
                    onChange={event => {
                      const value = event.target.value
                      setStages(previous => previous.map((item, at) => (at === index ? { ...item, name: value } : item)))
                    }}
                    disabled={busy}
                  />
                  <button
                    type="button"
                    className={css.iconButton}
                    aria-label={t('assets.edit.removeRelation')}
                    disabled={busy || stages.length <= 1}
                    onClick={() => { setStages(previous => previous.filter((_, at) => at !== index)) }}
                  >
                    ×
                  </button>
                </div>
              ))}
              <button
                type="button"
                className={css.button}
                disabled={busy}
                onClick={() => { setStages(previous => [...previous, { id: '', name: '' }]) }}
              >
                {t('assets.create.addStage')}
              </button>
            </div>
          </div>
        </>
      )}
      {error !== null && error !== '' && <div className={css.errorText}>{error}</div>}
      <div className={css.editorActions}>
        <button type="button" className={css.primaryButton} onClick={submit} disabled={!canSubmit}>
          {busy ? t('assets.edit.saving') : t('assets.create.submit')}
        </button>
        <button type="button" className={css.button} onClick={onCancel} disabled={busy}>
          {t('assets.edit.cancel')}
        </button>
      </div>
    </div>
  )
}
