import { describe, expect, it } from 'vitest'
import { latestAssetDraft, readAssetDraft, removeAssetDraft, writeAssetDraft, type AssetDraftRecord } from '../../src/client/asset-drafts.ts'

const record = (root: string, id = 'a', kind = 'character'): AssetDraftRecord => ({
  workspaceId: 'cache-test-workspace', root, id, kind, baseRevision: 'original-revision',
  source: { name: id, summary: '', aliases: [], tags: [], scalars: [], lists: [], related: [], body: 'Original', derivedRelations: [] },
  draft: { name: id, summary: '', aliasesText: '', tagsText: '', scalars: {}, listsText: {}, related: [], newTarget: '', newNote: '', bodyDraft: 'Unsaved' },
})

describe('session-local asset recovery cache', () => {
  it('isolates the same asset id by workspace root and asset kind', () => {
    const first = record('/cache-tests/first')
    const second = record('/cache-tests/second')
    const world = record('/cache-tests/first', 'a', 'world')
    writeAssetDraft(first); writeAssetDraft(second); writeAssetDraft(world)
    expect(readAssetDraft(first)).toBe(first)
    expect(readAssetDraft(second)).toBe(second)
    expect(readAssetDraft(world)).toBe(world)
    expect(readAssetDraft({ ...first, workspaceId: 'different-workspace' })).toBeNull()
    expect(latestAssetDraft(first)).toBe(world)
    for (const entry of [first, second, world]) removeAssetDraft(entry)
  })

  it('evicts the oldest draft after the bounded capacity is exceeded', () => {
    const entries = Array.from({ length: 25 }, (_, index) => record('/cache-tests/bounded', String(index)))
    for (const entry of entries) expect(writeAssetDraft(entry)).toBe(true)
    expect(readAssetDraft(entries[0]!)).toBeNull()
    expect(readAssetDraft(entries[24]!)).toBe(entries[24])
    for (const entry of entries) removeAssetDraft(entry)
  })

  it('rejects oversized recovery records without claiming that they were saved', () => {
    const entry = record('/cache-tests/oversized')
    entry.draft.bodyDraft = 'x'.repeat(4_000_001)
    expect(writeAssetDraft(entry)).toBe(false)
    expect(readAssetDraft(entry)).toBeNull()
  })
})
