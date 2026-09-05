import { describe, expect, it } from 'vitest'
import {
  manuscriptDraftKey,
  manuscriptNovelId,
  ManuscriptDraftStorageError,
} from '../../src/client/draft-store.ts'

describe('manuscript recovery draft identity', () => {
  it('isolates the same document path by Workspace and work', () => {
    const base = { path: 'data/novels/demo/data/manuscript/ch_001.md' }
    const a = manuscriptDraftKey({ ...base, workspaceId: 'ws-a', novelId: 'demo' })
    const b = manuscriptDraftKey({ ...base, workspaceId: 'ws-b', novelId: 'demo' })
    const c = manuscriptDraftKey({ ...base, workspaceId: 'ws-a', novelId: 'other' })

    expect(new Set([a, b, c]).size).toBe(3)
  })

  it('prefers the server work identity and supports the canonical path fallback', () => {
    expect(manuscriptNovelId({ snapshot: { novel_id: 'server-id' } }, 'data/novels/path-id/ch.md')).toBe('server-id')
    expect(manuscriptNovelId(null, 'data/novels/path-id/data/manuscript/ch_001.md')).toBe('path-id')
    expect(manuscriptNovelId(null, 'data/manuscript/ch_001.md')).toBe('')
  })

  it('rejects incomplete identities instead of creating a shared default slot', () => {
    expect(() => manuscriptDraftKey({ workspaceId: '', novelId: 'demo', path: 'ch.md' }))
      .toThrow(ManuscriptDraftStorageError)
  })
})
