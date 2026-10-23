import { useEffect, useRef, useState } from 'react'
import { asRecord, asText, unwrapData } from './dto.ts'
import type { ModelNavigationGuard } from './ModelView.tsx'
import type { OperationsViewProps } from './OperationsView.tsx'
import css from './SerialWritingView.module.css'

type Row = Record<string, unknown>
function rows(value: unknown): Row[] { return Array.isArray(value) ? value.map(asRecord) : [] }
function strings(value: unknown): string[] { return Array.isArray(value) ? value.filter((s): s is string => typeof s === 'string') : [] }
function message(error: unknown): string { return error instanceof Error ? error.message : String(error) }

/** Deterministic chapter diagnostics and author-owned serial-writing assets. */
export function SerialWritingView({ fetchStudioApi, postStudioApi, t, onNavigationGuardChange }: Pick<OperationsViewProps, 'fetchStudioApi' | 'postStudioApi' | 't'> & { onNavigationGuardChange?: (guard: ModelNavigationGuard | null) => void }) {
  const [assets, setAssets] = useState<Row>({ terms: [], character_groups: {} })
  const [assetsRevision, setAssetsRevision] = useState('')
  const [anchors, setAnchors] = useState<Row[]>([])
  const [audit, setAudit] = useState<Row>({})
  const [group, setGroup] = useState('')
  const [chapter, setChapter] = useState('')
  const [metrics, setMetrics] = useState<Row>({})
  const [identity, setIdentity] = useState<Row>({})
  const [dirty, setDirty] = useState(false)
  const [busy, setBusy] = useState(false)
  const [notice, setNotice] = useState('')
  const [bad, setBad] = useState(false)
  const [selected, setSelected] = useState<string[]>([])
  const [kind, setKind] = useState('growth')
  const [impact, setImpact] = useState('section')
  const [note, setNote] = useState('')
  const [decision, setDecision] = useState('absorb')
  const [target, setTarget] = useState('')
  const [edits, setEdits] = useState<Record<string, Row>>({})
  const [characterName, setCharacterName] = useState('')
  const [groupText, setGroupText] = useState('')
  const active = useRef(true)
  const auditRequest = useRef(0)
  const metricRequest = useRef(0)
  const chapters = rows(audit['chapters'])
  const ledger = asRecord(audit['ledger'])
  const groups = rows(audit['available_groups'])
  const entries = rows(ledger['entries']).filter(e => !group || e['group_id'] === group)
  const termRows = rows(assets['terms'])

  useEffect(() => {
    active.current = true
    void Promise.all([fetchStudioApi('/writing-assets'), fetchStudioApi('/status')]).then(([value, status]) => {
      if (!active.current) return
      const result = unwrapData(value)
      setAssets(asRecord(result['assets'])); setAssetsRevision(asText(result['revision']))
      setAnchors(rows(result['anchors'])); setIdentity(unwrapData(status))
    }).catch(error => { if (active.current) { setNotice(message(error)); setBad(true) } })
    return () => { active.current = false }
  }, [fetchStudioApi])

  useEffect(() => {
    const request = ++auditRequest.current
    void fetchStudioApi(`/outline/audit?group_id=${encodeURIComponent(group)}`).then(value => {
      if (!active.current || request !== auditRequest.current) return
      setAudit(unwrapData(value)); setSelected([]); setEdits({})
    }).catch(error => { if (active.current && request === auditRequest.current) { setNotice(message(error)); setBad(true) } })
  }, [fetchStudioApi, group])

  useEffect(() => {
    const request = ++metricRequest.current
    setMetrics({})
    if (!chapter) return
    void fetchStudioApi(`/manuscript/${encodeURIComponent(chapter)}/metrics`).then(value => {
      if (active.current && request === metricRequest.current) setMetrics(unwrapData(value))
    }).catch(error => { if (active.current && request === metricRequest.current) { setNotice(message(error)); setBad(true) } })
  }, [fetchStudioApi, chapter])

  useEffect(() => {
    onNavigationGuardChange?.((navigate) => { if ((!dirty && !Object.keys(edits).length) || window.confirm(t('serial.discard'))) navigate() })
    return () => onNavigationGuardChange?.(null)
  }, [dirty, edits, onNavigationGuardChange, t])

  useEffect(() => {
    if (!dirty) return
    const guard = (event: BeforeUnloadEvent) => { event.preventDefault(); event.returnValue = '' }
    window.addEventListener('beforeunload', guard)
    return () => window.removeEventListener('beforeunload', guard)
  }, [dirty])

  const run = async (action: () => Promise<void>) => {
    if (busy) return
    setBusy(true); setNotice(''); setBad(false)
    try { await action(); if (active.current) setNotice(t('serial.saved')) }
    catch (error) { if (active.current) { setNotice(message(error)); setBad(true) } }
    finally { if (active.current) setBusy(false) }
  }
  const updateAssets = (next: Row) => { setAssets(next); setDirty(true) }
  const editTerm = (index: number, changes: Row) => updateAssets({ ...assets, terms: termRows.map((row, i) => i === index ? { ...row, ...changes } : row) })
  const editChapter = (id: string, changes: Row) => setEdits(previous => ({ ...previous, [id]: { ...previous[id], ...changes } }))
  const outlineUpdates = Object.entries(edits).map(([node_id, metadata]) => ({ node_id, metadata }))
  const saveAssets = () => run(async () => {
    const result = unwrapData(await postStudioApi('/writing-assets', { assets, expected_revision: assetsRevision }))
    if (active.current) { setAssetsRevision(asText(result['revision'])); setAssets(asRecord(result['assets'])); setDirty(false) }
  })
  const reconcile = () => run(async () => {
    const result = unwrapData(await postStudioApi('/arc-reconcile', {
      action: 'arc_reconcile', group_id: group, expected_revision: ledger['revision'], entry_ids: selected,
      decision, confirm: true, plan: note, target_chapter_id: target,
      outline_revision: audit['outline_revision'], outline_updates: outlineUpdates, resume: decision === 'absorb',
    }))
    if (active.current) { setAudit(result); setSelected([]); setEdits({}) }
  })
  const numbers = asRecord(metrics['metrics'])
  const overlap = asRecord(metrics['overlap'])
  const functions = asRecord(audit['functions'])
  const debt = asRecord(audit['foreshadowing'])
  const wordTotals = asRecord(audit['words'])

  return <div className={css.root}>
    <header><h2>{t('serial.title')}</h2><p>{t('serial.hint')}</p>
      <small>{asText(identity['project_path'])} · {asText(identity['instance_id'])} · {String(identity['port'] ?? '')}</small>
    </header>
    {notice && <p role={bad ? 'alert' : 'status'} className={bad ? css.error : css.notice}>{notice}</p>}
    <section><h3>{t('serial.audit')}</h3>
      <label>{t('serial.scope')}<select value={group} disabled={busy} onChange={event => { if (!Object.keys(edits).length || window.confirm(t('serial.discard'))) setGroup(event.target.value) }}>
        <option value="">{t('serial.all')}</option>{groups.map(row => <option key={asText(row['id'])} value={asText(row['id'])}>{asText(row['title'])} · {asText(row['id'])}</option>)}
      </select></label>
      <div className={css.facts}>
        <span>{t('serial.words')}: {String(wordTotals['actual'] ?? '—')} / {String(wordTotals['planned'] ?? '—')}</span>
        {Object.entries(asRecord(functions['counts'])).map(([name, value]) => <span key={name}>{name}: {String(value)}</span>)}
        <span>{t('serial.payoffs')}: {strings(debt['confirmed_recovered']).length} / {strings(debt['declared_payoffs']).length}</span>
        <span>{t('serial.overdue')}: {strings(debt['overdue']).length}</span>
      </div>
      <p>{t('serial.promiseHint')}</p>
      <div className={css.scroll}><table><thead><tr><th>{t('serial.chapter')}</th><th>{t('serial.promise')}</th><th>{t('serial.budget')}</th><th>{t('serial.function')}</th><th>{t('serial.payoffIds')}</th><th>{t('serial.actual')}</th></tr></thead>
        <tbody>{chapters.map(row => { const id = asText(row['chapter_id']); const edit = edits[id] ?? {}; return <tr key={id}>
          <th>{id}</th><td><input aria-label={`${id} ${t('serial.promise')}`} value={asText(edit['promise'] ?? row['promise'])} onChange={event => editChapter(id, { promise: event.target.value })} /></td>
          <td><input aria-label={`${id} ${t('serial.budget')}`} type="number" min={200} max={50000} value={String(edit['word_budget'] ?? row['word_budget'] ?? '')} onChange={event => editChapter(id, { word_budget: Number(event.target.value) })} /></td>
          <td><input aria-label={`${id} ${t('serial.function')}`} value={edit['function'] === undefined ? strings(row['function']).join(', ') : asText(edit['function'])} onChange={event => editChapter(id, { function: event.target.value })} /></td>
          <td><input aria-label={`${id} ${t('serial.payoffIds')}`} value={edit['payoff_of'] === undefined ? strings(row['payoff_of']).join(', ') : asText(edit['payoff_of'])} onChange={event => editChapter(id, { payoff_of: event.target.value })} /></td>
          <td>{String(row['actual_words'] ?? '—')}</td></tr> })}</tbody></table></div>
      <button disabled={busy || !outlineUpdates.length} onClick={() => void run(async () => {
        await postStudioApi('/outline/edit', { operation: 'set_meta', revision: audit['outline_revision'], updates: outlineUpdates })
        const result = unwrapData(await fetchStudioApi(`/outline/audit?group_id=${encodeURIComponent(group)}`))
        if (active.current) { setAudit(result); setEdits({}) }
      })}>{t('serial.saveOutline')}</button>
      {Object.entries(asRecord(functions['streaks'])).map(([name, streaks]) => Array.isArray(streaks) && streaks.length > 0 && <p key={name}>{t('serial.streak')}: {name} · {streaks.map(streak => strings(streak).join(' → ')).join('; ')}</p>)}
    </section>

    <section><h3>{t('serial.metrics')}</h3>
      <label>{t('serial.chapter')}<select value={chapter} onChange={event => setChapter(event.target.value)}><option value="">—</option>{chapters.filter(row => row['manuscript_status'] === 'current').map(row => <option key={asText(row['chapter_id'])}>{asText(row['chapter_id'])}</option>)}</select></label>
      {chapter && <><div className={css.facts}><span>{t('serial.hanzi')}: {String(numbers['hanzi_count'] ?? '—')}</span><span>{t('serial.paragraphs')}: {String(numbers['paragraph_count'] ?? '—')}</span><span>{t('serial.sentences')}: {String(asRecord(numbers['sentences'])['p50'] ?? '—')} / {String(asRecord(numbers['sentences'])['p90'] ?? '—')}</span><span>{t('serial.paragraphLengths')}: {String(asRecord(numbers['paragraphs'])['p50'] ?? '—')} / {String(asRecord(numbers['paragraphs'])['p90'] ?? '—')}</span><span>{t('serial.nounDensity')}: {String(asRecord(numbers['concrete_nouns'])['per_1000_units'] ?? '—')}</span><span>{t('serial.dialogue')}: {typeof numbers['dialogue_ratio'] === 'number' ? `${(numbers['dialogue_ratio'] * 100).toFixed(1)}%` : '—'}</span></div>
        {rows(metrics['terms']).map((row, i) => <p className={css.warning} key={i}>{asText(row['kind'])} · {asText(row['term'])} · {String(row['line'] ?? `${String(row['actual'] ?? 0)}/${String(row['minimum'] ?? 0)}`)}</p>)}
        {rows(overlap['references']).map(row => <details key={asText(row['source'])} open={row['flagged'] === true}><summary>{asText(row['source'])} · {(Number(row['ratio']) * 100).toFixed(1)}%</summary>{rows(row['spans']).map((span, i) => <p key={i}><mark className={row['flagged'] === true ? css.overlap : ''}>{asText(span['text'])}</mark></p>)}</details>)}
        {rows(overlap['duplicate_paragraphs']).map((row, i) => <p key={i}><strong>{t('serial.duplicate')}</strong> <mark className={css.overlap}>{asText(row['text'])}</mark></p>)}
        {Object.entries(asRecord(metrics['character_groups'])).map(([name, value]) => <div key={name}><strong>{name}</strong>{rows(value).map(row => <label key={asText(row['id'])}><input type="checkbox" disabled={busy} checked={strings(asRecord(asRecord(metrics['character_group_usage'])['used'])[name]).includes(asText(row['id']))} onChange={event => {
          const used = asRecord(asRecord(metrics['character_group_usage'])['used']); const ids = strings(used[name]); const groupId = asText(row['id'])
          const next = { ...used, [name]: event.target.checked ? [...ids, groupId] : ids.filter(id => id !== groupId) }
          void run(async () => { await postStudioApi('/writing-assets', { action: 'mark_usage', chapter_id: chapter, groups: next }); if (active.current) setMetrics(current => ({ ...current, character_group_usage: { used: next } })) })
        }} />{t('serial.used')} · {asText(row['text'])}</label>)}</div>)}
      </>}
    </section>

    <section><h3>{t('serial.assets')}</h3><p>{t('serial.assetsHint')}</p>
      <div className={css.scroll}><table><thead><tr><th>{t('serial.term')}</th><th>{t('serial.forbidden')}</th><th>{t('serial.minimum')}</th><th>{t('serial.example')}</th><th>{t('serial.replacement')}</th><th /></tr></thead><tbody>
        {termRows.map((row, index) => <tr key={index}><td><input aria-label={t('serial.term')} value={asText(row['term'])} onChange={e => editTerm(index, { term: e.target.value })} /></td><td><input aria-label={t('serial.forbidden')} type="checkbox" checked={row['forbidden'] === true} onChange={e => editTerm(index, { forbidden: e.target.checked, ...(e.target.checked ? { min_occurrences: 0 } : {}) })} /></td><td><input aria-label={t('serial.minimum')} type="number" min={0} max={1000} disabled={row['forbidden'] === true} value={Number(row['min_occurrences'] ?? 0)} onChange={e => editTerm(index, { min_occurrences: Number(e.target.value) })} /></td><td><input aria-label={t('serial.example')} value={asText(row['example'])} onChange={e => editTerm(index, { example: e.target.value })} /></td><td><input aria-label={t('serial.replacement')} value={asText(row['replacement'])} onChange={e => editTerm(index, { replacement: e.target.value })} /></td><td><button onClick={() => updateAssets({ ...assets, terms: termRows.filter((_, i) => i !== index) })}>{t('serial.remove')}</button></td></tr>)}
      </tbody></table></div>
      <button onClick={() => updateAssets({ ...assets, terms: [...termRows, { term: '', min_occurrences: 0 }] })}>{t('serial.addTerm')}</button>
      <label><input type="checkbox" checked={assets['review_terms'] !== false} onChange={e => updateAssets({ ...assets, review_terms: e.target.checked })} />{t('serial.reviewTerms')}</label>
      <label>{t('serial.nouns')}<input value={strings(assets['concrete_nouns']).join(', ')} onChange={e => updateAssets({ ...assets, concrete_nouns: e.target.value.split(/[,，、]/).map(s => s.trim()).filter(Boolean) })} /></label>
      <label>{t('serial.threshold')}<input type="number" min={0} max={1} step={.01} value={Number(assets['overlap_threshold'] ?? .05)} onChange={e => updateAssets({ ...assets, overlap_threshold: Number(e.target.value) })} /></label>
      <h4>{t('serial.groups')}</h4><p>{t('serial.groupsHint')}</p>
      {Object.entries(asRecord(assets['character_groups'])).map(([name, value]) => <div key={name}><strong>{name}</strong>{rows(value).map(row => <p key={asText(row['id'])}>{asText(row['text'])} <button onClick={() => updateAssets({ ...assets, character_groups: { ...asRecord(assets['character_groups']), [name]: rows(value).filter(g => g['id'] !== row['id']) } })}>{t('serial.remove')}</button></p>)}</div>)}
      <div className={css.controls}><input aria-label={t('serial.character')} placeholder={t('serial.character')} value={characterName} onChange={e => setCharacterName(e.target.value)} /><input aria-label={t('serial.detail')} placeholder={t('serial.detail')} value={groupText} onChange={e => setGroupText(e.target.value)} /><button disabled={!characterName.trim() || !groupText.trim()} onClick={() => {
        const current = asRecord(assets['character_groups']); const name = characterName.trim()
        updateAssets({ ...assets, character_groups: { ...current, [name]: [...rows(current[name]), { id: crypto.randomUUID(), text: groupText.trim() }] } }); setGroupText('')
      }}>{t('serial.addGroup')}</button></div>
      <button disabled={busy || !dirty} onClick={() => void saveAssets()}>{t('serial.saveAssets')}{dirty ? ' *' : ''}</button>
      <h4>{t('serial.anchors')}</h4><p>{t('serial.anchorHint')}</p>
      {anchors.map(row => <p key={asText(row['path'])}>{asText(row['path'])} · {String(row['characters'])}</p>)}
      <input type="file" accept=".md,text/markdown" aria-label={t('serial.anchors')} disabled={busy} onChange={event => {
        const file = event.target.files?.[0]; if (!file) return
        void run(async () => { const existing = anchors.find(row => row['path'] === `anchor/${file.name}`); const result = unwrapData(await postStudioApi('/writing-assets', { action: 'save_anchor', name: file.name, content: await file.text(), expected_revision: asText(existing?.['revision']) })); if (active.current) setAnchors(rows(result['anchors'])) })
      }} />
    </section>

    <section><h3>{t('serial.drift')}</h3><p>{t('serial.driftHint')}</p>
      <button disabled={busy} onClick={() => void run(async () => { const result = unwrapData(await postStudioApi('/arc-reconcile', { action: 'recover_transaction', confirm: true })); if (active.current) setAudit(result) })}>{t('serial.recoverTransaction')}</button>
      <p>{asRecord(asRecord(ledger['groups'])[group])['frozen'] === true ? t('serial.frozen') : t('serial.unfrozen')}</p>
      <div className={css.controls}><select aria-label={t('serial.chapter')} value={chapter} onChange={e => setChapter(e.target.value)}><option value="">—</option>{chapters.map(row => <option key={asText(row['chapter_id'])}>{asText(row['chapter_id'])}</option>)}</select>
        <select aria-label={t('serial.kind')} value={kind} onChange={e => setKind(e.target.value)}>{(['growth', 'escape', 'dilution', 'snowball'] as const).map(value => <option key={value} value={value}>{t(`serial.${value}`)}</option>)}</select>
        <select aria-label={t('serial.impact')} value={impact} onChange={e => setImpact(e.target.value)}>{(['local', 'section', 'arc'] as const).map(value => <option key={value} value={value}>{t(`serial.${value}`)}</option>)}</select>
      </div>
      <textarea aria-label={t('serial.note')} placeholder={t('serial.note')} value={note} onChange={e => setNote(e.target.value)} />
      <button disabled={busy || !group.startsWith('sec_') || !chapter || !note.trim()} onClick={() => void run(async () => {
        const result = unwrapData(await postStudioApi('/arc-reconcile', { action: 'drift_entry', group_id: group, chapter_id: chapter, kind, impact, note, expected_revision: ledger['revision'] }))
        if (active.current) { setAudit(result); setNote('') }
      })}>{t('serial.addDrift')}</button>
      {entries.map(entry => <label key={asText(entry['id'])}><input type="checkbox" checked={selected.includes(asText(entry['id']))} onChange={e => setSelected(previous => e.target.checked ? [...previous, asText(entry['id'])] : previous.filter(id => id !== entry['id']))} />{asText(entry['chapter_id'])} · {asText(entry['note'])} · {asText(entry['status'])}</label>)}
      <div className={css.controls}><select aria-label={t('serial.decision')} value={decision} onChange={e => setDecision(e.target.value)}>{(['absorb', 'recover', 'freeze'] as const).map(value => <option key={value} value={value}>{t(`serial.${value}`)}</option>)}</select>
        {decision === 'recover' && <input aria-label={t('serial.target')} placeholder={t('serial.target')} value={target} onChange={e => setTarget(e.target.value)} />}
        <button disabled={busy || !group || !selected.length || decision === 'absorb' && !outlineUpdates.length} onClick={() => void reconcile()}>{t('serial.reconcile')}</button>
      </div>
    </section>
  </div>
}
