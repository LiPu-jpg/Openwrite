/**
 * dto.ts parser contract tests (offline, pure).
 *
 * Pins the M1c envelope flip (`{ ok, data, error, request_id }` on every model
 * POST) and the new profile/task fields. Every parser must tolerate old
 * servers (bare payloads, absent keys) by degrading to null/empty defaults —
 * never throw.
 */
import { describe, expect, it } from 'vitest'
import {
  parseConnectionTestResult, parseDeletePreview, parseModelProfiles,
  chapterForeshadowActions, chapterSprintStats, parseChapterWorkBrief, parseDocumentChangePlan, parseReadingOrder, parseReadingPacket,
  parseResultRef, parseRouteImpact, parseRouteMap, parseTaskProgress,
} from '../../src/client/dto.ts'

const envelope = (data: unknown) => ({ ok: true, data, error: null, request_id: 'req_test' })

const M1C_PROFILE = {
  id: 'writer-a',
  label: 'Writer A',
  provider: 'openai',
  model: 'fake-model-1',
  base_url: 'https://example.invalid/v1',
  api_format: 'chat',
  context_tokens: 64000,
  max_output_tokens: 24000,
  temperature: 0.4,
  timeout_seconds: 90,
  embedding_provider: 'openai',
  embedding_model: 'fake-embed',
  embedding_base_url: 'https://example.invalid/embed',
  configured: true,
  embedding_configured: true,
  schema_version: 'openwrite.model-profile.v1',
  capabilities: { chat: true },
  used_by_routes: ['chapter_write', 'review'],
  last_test: {
    status: 'failed', tested_at: '2026-08-31T10:00:00Z', latency_ms: 1200,
    provider: 'openai', resolved_model: 'fake-model-1',
    error_code: 'MODEL_TEST_TIMEOUT', failed_stage: null,
  },
  last_embedding_test: {
    status: 'ok', tested_at: '2026-08-31T10:01:00Z', latency_ms: 300,
    provider: 'openai', resolved_model: 'fake-embed', error_code: null, failed_stage: null,
  },
  api_key: 'must-not-enter-the-dto',
  embedding_api_key: 'legacy-key-must-not-enter-the-dto',
}

describe('parseModelProfiles', () => {
  it('parses the M1c enveloped surface with all new per-entry fields', () => {
    const [profile] = parseModelProfiles(envelope({ profiles: [M1C_PROFILE], routes: { review: 'writer-a' } }))
    expect(profile).toMatchObject({
      id: 'writer-a',
      schema_version: 'openwrite.model-profile.v1',
      temperature: 0.4,
      timeout_seconds: 90,
      capabilities: { chat: true },
      used_by_routes: ['chapter_write', 'review'],
      last_test: { status: 'failed', error_code: 'MODEL_TEST_TIMEOUT', latency_ms: 1200 },
    })
    // Legacy nested Embedding fields and credentials cannot leak into the chat DTO.
    expect(profile).not.toHaveProperty('embedding_base_url')
    expect(profile).not.toHaveProperty('last_embedding_test')
    expect(profile).not.toHaveProperty('api_key')
    expect(profile).not.toHaveProperty('embedding_api_key')
  })

  it('tolerates the legacy bare payload (no envelope, no new fields)', () => {
    const legacy = {
      profiles: [{ id: 'writer-a', label: 'Writer A', provider: 'openai', model: 'm', configured: true }],
      routes: { review: 'writer-a' },
    }
    const [profile] = parseModelProfiles(legacy)
    expect(profile).toMatchObject({
      id: 'writer-a',
      schema_version: '',
      temperature: 0.7,
      timeout_seconds: 120,
      capabilities: { chat: false },
      used_by_routes: [],
      last_test: null,
    })
    expect(parseRouteMap(legacy)).toEqual({ review: 'writer-a' })
  })

  it('returns empty lists on garbage and drops entries without an id', () => {
    expect(parseModelProfiles(null)).toEqual([])
    expect(parseModelProfiles(envelope({ profiles: [{ label: 'no id' }] }))).toEqual([])
  })
})

describe('parseConnectionTestResult', () => {
  it('unwraps the M1c success envelope', () => {
    const result = parseConnectionTestResult(envelope({
      ok: true, status: 'ok', provider: 'openai', model: 'fake-model-1',
      latency_ms: 812, tested_at: '2026-08-31T10:00:00Z', reply: 'pong',
    }))
    expect(result).toEqual({
      status: 'ok', provider: 'openai', model: 'fake-model-1',
      latency_ms: 812, tested_at: '2026-08-31T10:00:00Z', reply: 'pong',
    })
  })

  it('degrades missing fields to empty/null instead of throwing', () => {
    expect(parseConnectionTestResult(envelope({}))).toEqual({
      status: '', provider: '', model: '', latency_ms: null, tested_at: '', reply: '',
    })
    expect(parseConnectionTestResult(undefined).latency_ms).toBeNull()
  })
})

describe('parseDeletePreview', () => {
  it('parses the full delete-preview payload', () => {
    const preview = parseDeletePreview(envelope({
      profile_id: 'writer-a',
      used_by_routes: ['writing'],
      routes_that_would_fail: [],
      fallback_candidates: [
        { id: 'writer-b', label: 'Writer B', configured: true },
        { id: 'writer-c', label: 'Writer C', configured: false },
      ],
      resulting_routes: { writing: 'writer-b' },
      deletable: true,
      blocking_reasons: [],
    }))
    expect(preview).toEqual({
      profile_id: 'writer-a',
      used_by_routes: ['writing'],
      routes_that_would_fail: [],
      fallback_candidates: [
        { id: 'writer-b', label: 'Writer B', configured: true },
        { id: 'writer-c', label: 'Writer C', configured: false },
      ],
      resulting_routes: { writing: 'writer-b' },
      deletable: true,
      blocking_reasons: [],
    })
  })

  it('null resulting_routes stays null; missing keys default to safe values', () => {
    const blocked = parseDeletePreview(envelope({
      profile_id: 'writer-a', used_by_routes: ['writing'], routes_that_would_fail: ['writing'],
      fallback_candidates: [], resulting_routes: null, deletable: false,
      blocking_reasons: ['MODEL_PROFILE_LAST_PROFILE'],
    }))
    expect(blocked.resulting_routes).toBeNull()
    expect(blocked.deletable).toBe(false)
    expect(parseDeletePreview(null)).toEqual({
      profile_id: '', used_by_routes: [], routes_that_would_fail: [],
      fallback_candidates: [], resulting_routes: null, deletable: false, blocking_reasons: [],
    })
  })
})

describe('parseRouteImpact', () => {
  it('unwraps routes plus the changed_routes impact', () => {
    const impact = parseRouteImpact(envelope({
      routes: { chapter_write: 'writer-a', review: 'writer-b' },
      impact: {
        changed_routes: [{ route: 'review', from: 'writer-a', to: 'writer-b' }],
        profiles_affected: ['writer-a', 'writer-b'],
      },
    }))
    expect(impact.routes).toEqual({ chapter_write: 'writer-a', review: 'writer-b' })
    expect(impact.changed_routes).toEqual([{ route: 'review', from: 'writer-a', to: 'writer-b' }])
    expect(impact.profiles_affected).toEqual(['writer-a', 'writer-b'])
  })

  it('tolerates a bare route map without impact', () => {
    expect(parseRouteImpact({ routes: { review: 'writer-a' } })).toEqual({
      routes: { review: 'writer-a' }, changed_routes: [], profiles_affected: [],
    })
  })

  it('reads the swapped map from the nested model_profiles surface (HTTP shape)', () => {
    // POST /api/model/routes answers data = { model_profiles: surface, impact }.
    const impact = parseRouteImpact(envelope({
      model_profiles: { schema_version: 'openwrite.model-profile.v1', profiles: [], routes: { review: 'writer-b' } },
      impact: { changed_routes: [{ route: 'review', from: 'writer-a', to: 'writer-b' }], profiles_affected: ['writer-a', 'writer-b'] },
    }))
    expect(impact.routes).toEqual({ review: 'writer-b' })
    expect(impact.changed_routes).toEqual([{ route: 'review', from: 'writer-a', to: 'writer-b' }])
  })
})

describe('task helpers', () => {
  it('parseTaskProgress reads real units and degrades to null', () => {
    expect(parseTaskProgress({ completed_units: 5, total_units: 10, ratio: 0.5, unit_kind: 'candidates' }))
      .toEqual({ completed_units: 5, total_units: 10, ratio: 0.5, unit_kind: 'candidates' })
    expect(parseTaskProgress(null)).toBeNull()
    expect(parseTaskProgress('nope')).toBeNull()
    expect(parseTaskProgress([1, 2])).toBeNull()
  })

  it('parseResultRef requires a non-empty id', () => {
    expect(parseResultRef({ type: 'benchmark_run', id: 'run_1' })).toEqual({ type: 'benchmark_run', id: 'run_1' })
    expect(parseResultRef({ type: 'benchmark_run' })).toBeNull()
    expect(parseResultRef(null)).toBeNull()
    expect(parseResultRef(42)).toBeNull()
  })
})

describe('author workbench DTOs', () => {
  const readingDocument = {
    document_id: 'doc-one', occurrence_id: 'occ-one', chapter_id: 'ch_001', title: '第一章', path: 'data/manuscript/ch_001.md',
    status: 'present', writing_units: 1200, revision: 'manuscript-one', updated_at: '2026-09-05T00:00:00Z', reading_index: 0,
    previous_occurrence_id: '', next_occurrence_id: '', volume: { volume_id: 'arc-one' }, content: '正文',
  }

  it('retains canonical reading occurrences and bounded packet content', () => {
    const order = parseReadingOrder(envelope({
      schema_version: 'openwrite.reading-order.v1', novel_id: 'demo', revision: 'order-one', mode: 'outline', mutation_allowed: true,
      actual_order: ['occ-one'], volumes: [{ volume_id: 'arc-one', title: '第一卷', order: 0, occurrence_ids: ['occ-one'] }],
      documents: [readingDocument], issues: [],
    }))
    expect(order.documents[0]).toMatchObject({ document_id: 'doc-one', occurrence_id: 'occ-one', volume_id: 'arc-one', revision: 'manuscript-one' })
    expect(order.actual_order).toEqual(['occ-one'])

    const packet = parseReadingPacket(envelope({
      schema_version: 'openwrite.reading-packet.v1', novel_id: 'demo', revision: 'order-one',
      anchor_document_id: 'doc-one', anchor_occurrence_id: 'occ-one', start_index: 0, end_index: 0,
      has_previous: false, has_next: false, complete: true, documents: [readingDocument], issues: [],
    }))
    expect(packet.documents[0]?.content).toBe('正文')
  })

  it('parses only explicit re-review closure outcomes', () => {
    const brief = parseChapterWorkBrief(envelope({
      schema_version: 'openwrite.chapter-work-brief.v1', novel_id: 'demo', chapter_id: 'ch_001', document_id: 'doc-one',
      manuscript: { path: readingDocument.path, current_revision: 'manuscript-two', writing_units: 1200 },
      review: {
        exists: true, review_revision: 'review-two', current_source_revision: 'manuscript-two',
        latest_closure: {
          closure_id: 'closure-one', proposal_id: 'proposal-one', rereview_review_revision: 'review-two',
          issue_outcomes: [{ issue_id: 'issue-a', outcome: 'resolved' }, { issue_id: 'issue-b', outcome: 'retained' }, { issue_id: 'bad', outcome: 'guessed' }],
          regressions: [{ issue_id: 'issue-c', outcome: 'regressed', issue: { description: '回归' } }],
        },
      },
      target: {}, recent_edits: [],
    }))
    expect(brief.review.latest_closure?.issue_outcomes).toEqual([
      { issue_id: 'issue-a', outcome: 'resolved' }, { issue_id: 'issue-b', outcome: 'retained' },
    ])
    expect(brief.review.latest_closure?.regressions[0]).toMatchObject({ issue_id: 'issue-c', outcome: 'regressed' })
  })

  it('maps work-brief must_resolve/overdue/to_plant onto author due/overdue/to-plant actions', () => {
    const brief = parseChapterWorkBrief(envelope({
      schema_version: 'openwrite.chapter-work-brief.v1', novel_id: 'demo', chapter_id: 'ch_005',
      manuscript: { path: readingDocument.path, current_revision: 'rev' },
      review: {}, target: {}, recent_edits: [],
      foreshadowing: {
        must_resolve: [{ id: 'f_due', content: '到期', reveal_anchor: { chapter_id: 'ch_005' } }],
        overdue: [{ id: 'f_overdue', content: '超期', target_chapter: 'ch_004' }],
        to_plant: [{ id: 'f_plant', content: '待埋', planned: true, plant_anchor: { chapter_id: 'ch_005' } }],
        upcoming: [{ id: 'f_later', content: '未到' }],
        source_revision: 'sha256:dag',
        counts: { must_resolve: 1, overdue: 1, to_plant: 1, upcoming: 1 },
      },
    }))
    expect(brief.foreshadowing.due.map(item => item.id)).toEqual(['f_due'])
    expect(brief.foreshadowing.overdue.map(item => item.id)).toEqual(['f_overdue'])
    expect(brief.foreshadowing.to_plant.map(item => item.id)).toEqual(['f_plant'])
    expect(brief.foreshadowing.due[0]?.reveal_chapter_id).toBe('ch_005')
    expect(brief.foreshadowing.overdue[0]?.reveal_chapter_id).toBe('ch_004')
    expect(brief.foreshadowing.to_plant[0]?.plant_chapter_id).toBe('ch_005')
    expect(chapterForeshadowActions(brief).map(entry => entry.bucket)).toEqual(['due', 'overdue', 'to_plant'])
  })

  it('derives sprint stats from the work-brief target and known deltas without guessing missing ones', () => {
    const brief = parseChapterWorkBrief(envelope({
      schema_version: 'openwrite.chapter-work-brief.v1', novel_id: 'demo', chapter_id: 'ch_001',
      manuscript: { path: readingDocument.path, current_revision: 'rev', writing_units: 1200 },
      review: {},
      target: { writing_units: 2500, source: 'project.chapter_target', actual_units: 1200, remaining_units: 1300, progress: 0.48 },
      recent_edits: [
        { kind: 'manuscript_saved', id: 'save-one', status: 'saved', updated_at: '2026-09-06T01:00:00Z', writing_units_delta: 80 },
        { kind: 'revision_applied', id: 'rev-one', status: 'applied', updated_at: '2026-09-06T01:05:00Z', writing_units_delta: 40 },
        { kind: 'revision_applied', id: 'rev-two', status: 'applied', updated_at: '2026-09-06T01:06:00Z', writing_units_delta: -10 },
        { kind: 'reviewed', id: 'review-one', status: 'current', updated_at: '2026-09-06T01:07:00Z', writing_units_delta: null },
      ],
    }))
    expect(chapterSprintStats(brief)).toEqual({
      targetUnits: 2500, actualUnits: 1200, remainingUnits: 1300, progress: 0.48,
      added: 120, deleted: 10, net: 110, knownDeltaEvents: 3, unknownDeltaEvents: 1,
      aiNet: 30, humanNet: 80,
    })
  })

  it('does not invent AI or human sprint splits when events lack a writing-units delta', () => {
    const brief = parseChapterWorkBrief(envelope({
      schema_version: 'openwrite.chapter-work-brief.v1', novel_id: 'demo', chapter_id: 'ch_001',
      manuscript: { path: readingDocument.path, current_revision: 'rev' },
      review: {},
      target: { writing_units: 3000, actual_units: 900, remaining_units: 2100, progress: 0.3 },
      recent_edits: [
        { kind: 'manuscript_saved', id: 'save-one', status: 'saved', updated_at: '2026-09-06T01:00:00Z' },
        { kind: 'task_updated', id: 'task-one', status: 'running', updated_at: '2026-09-06T01:01:00Z' },
      ],
    }))
    expect(chapterSprintStats(brief)).toMatchObject({
      targetUnits: 3000, added: 0, deleted: 0, net: 0,
      knownDeltaEvents: 0, unknownDeltaEvents: 2, aiNet: null, humanNet: null,
    })
  })

  it('parses the immutable document change preview revisions', () => {
    expect(parseDocumentChangePlan(envelope({
      applied: false, changed: true, status: '', path: 'data/manuscript/ch_001.md', revision: 'abcdef',
      diff: '-old\n+new', preview_token: 'token-one', undo_preview_token: '',
      mutation_summary: { execution_status: 'proposed', source_revision: 'sha256:source', result_revision: 'sha256:result' },
    }))).toEqual({
      applied: false, changed: true, status: '', path: 'data/manuscript/ch_001.md', revision: 'abcdef',
      diff: '-old\n+new', preview_token: 'token-one', undo_preview_token: '',
      mutation_summary: { execution_status: 'proposed', source_revision: 'sha256:source', result_revision: 'sha256:result' },
    })
  })
})
