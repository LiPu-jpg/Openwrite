import type { AssetEditorDraft, AssetEditorSource } from './AssetEditor.tsx'

export interface AssetDraftContext { workspaceId: string; root: string }
export interface AssetDraftIdentity extends AssetDraftContext { kind: string; id: string }
export interface AssetDraftRecord extends AssetDraftIdentity {
  baseRevision: string
  source: AssetEditorSource
  draft: AssetEditorDraft
}

// Session-local recovery only: no asset prose is written to browser storage.
// Limit the number of retained editors and the total serialized character count.
const drafts = new Map<string, AssetDraftRecord>()
const sizes = new Map<string, number>()
let characterCount = 0
const MAX_ENTRIES = 24
const MAX_CHARACTERS = 4_000_000
const keyOf = ({ workspaceId, root, kind, id }: AssetDraftIdentity) => JSON.stringify([workspaceId, root, kind, id])
const valid = (identity: AssetDraftIdentity) => identity.workspaceId !== '' && identity.root !== '' && identity.id !== '' && ['character', 'world'].includes(identity.kind)

export function readAssetDraft(identity: AssetDraftIdentity): AssetDraftRecord | null {
  return valid(identity) ? drafts.get(keyOf(identity)) ?? null : null
}

export function latestAssetDraft(context: AssetDraftContext): AssetDraftRecord | null {
  return [...drafts.values()].reverse().find(record => record.workspaceId === context.workspaceId && record.root === context.root) ?? null
}

export function writeAssetDraft(record: AssetDraftRecord): boolean {
  if (!valid(record)) return false
  const size = JSON.stringify(record).length
  if (size > MAX_CHARACTERS) return false
  const key = keyOf(record)
  characterCount -= sizes.get(key) ?? 0
  drafts.delete(key)
  drafts.set(key, record)
  sizes.set(key, size)
  characterCount += size
  while (drafts.size > MAX_ENTRIES || characterCount > MAX_CHARACTERS) {
    const oldest = drafts.entries().next().value
    if (!oldest) break
    characterCount -= sizes.get(oldest[0]) ?? 0
    sizes.delete(oldest[0])
    drafts.delete(oldest[0])
  }
  return true
}

export function removeAssetDraft(identity: AssetDraftIdentity): void {
  const key = keyOf(identity)
  characterCount -= sizes.get(key) ?? 0
  sizes.delete(key)
  drafts.delete(key)
}

/** A slow save from an unmounted editor must not erase a newer local draft. */
export function removeAssetDraftIfUnchanged(identity: AssetDraftIdentity, saved: AssetEditorDraft): void {
  const current = readAssetDraft(identity)
  if (current && JSON.stringify(current.draft) === JSON.stringify(saved)) removeAssetDraft(identity)
}
