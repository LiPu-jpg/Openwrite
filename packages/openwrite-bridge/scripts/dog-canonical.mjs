// Deterministic regression: dog materializers must trust the canonical v2
// decision and never re-derive it from legacy score/passed/severity fields.
import assert from 'node:assert/strict'
import { buildDogReviewBundle } from '../lib/dog-review.js'

const canonicalPass = {
  review_v2: {
    schema_version: 'openwrite.review.v2',
    execution_status: 'completed',
    quality_score: 90,
    coverage: 1,
    gate_status: 'pass',
    delivery_status: 'pass',
    production_gate_status: 'disabled_uncalibrated',
  },
  // Conflicting legacy evidence: recompute rules would say blocked/revise.
  score: 0, passed: false,
  issue_details: [{ dimension: 2, severity: 'critical', review_severity: 'critical', description: 'legacy conflict' }],
}

const bundle = buildDogReviewBundle(canonicalPass, 'ch_090', 70)
assert.equal(bundle.manifest.decisionSource, 'v2')
assert.equal(bundle.manifest.gateStatus, 'pass', 'gate must come from review_v2')
assert.equal(bundle.manifest.deliveryStatus, 'pass', 'delivery must come from review_v2')

const legacy = {
  score: 95, passed: true,
  issue_details: [{ dimension: 7, severity: 'warning', description: 'slow' }],
}
const legacyBundle = buildDogReviewBundle(legacy, 'ch_091', 70)
assert.equal(legacyBundle.manifest.decisionSource, 'v1-adapter')
assert.equal(legacyBundle.manifest.deliveryStatus, 'pass')

console.log('dog canonical authority ok')


// Unknown review_v2 versions must be rejected, never silently materialized.
const v999 = {
  review_v2: { schema_version: 'openwrite.review.v999', delivery_status: 'pass', gate_status: 'pass' },
  score: 0, passed: false,
  issue_details: [{ dimension: 2, severity: 'critical', review_severity: 'critical' }],
}
assert.throws(() => buildDogReviewBundle(v999, 'ch_092', 70), /unsupported review_v2 schema version/)
// Existence/type matrix: a present review_v2 key of any non-object type
// (including null) must be rejected, never ridden into the legacy adapter.
for (const [label, bad] of [
  ['null', null],
  ['array', []],
  ['string', 'invalid'],
  ['number', 42],
  ['boolean', true],
]) {
  assert.throws(
    () => buildDogReviewBundle({ review_v2: bad, score: 95, passed: true }, 'ch_094', 70),
    /review_v2 must be a JSON object when present/,
    label,
  )
}
// Empty object: present but without a supported schema version.
assert.throws(
  () => buildDogReviewBundle({ review_v2: {}, score: 95, passed: true }, 'ch_095', 70),
  /review_v2 empty object/,
)
// No review_v2 key at all: legacy adapter applies.
const legacyOnly = buildDogReviewBundle({ score: 90, passed: true }, 'ch_096', 70)
assert.equal(legacyOnly.manifest.decisionSource, 'v1-adapter')

// A present review_v2 with a missing schema_version must fail too.
const missingVersion = {
  review_v2: { delivery_status: 'pass', gate_status: 'pass' },
  score: 0, passed: false,
}
assert.throws(() => buildDogReviewBundle(missingVersion, 'ch_093', 70), /unsupported review_v2 schema version/)

// ── materializeChapterDelivery artifact-read strategy ────────────────────────
import { mkdtemp, mkdir, writeFile, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { materializeChapterDelivery } from '../lib/dog-delivery.js'

const workspaceRoot = await mkdtemp(join(tmpdir(), 'dsh-dog-delivery-'))
try {
  const novelRoot = join(workspaceRoot, 'data', 'novels', 'paritynovel')
  await mkdir(join(novelRoot, 'data', 'reviews'), { recursive: true })
  await mkdir(join(novelRoot, 'data', 'manuscript', 'arc_001'), { recursive: true })
  await writeFile(join(novelRoot, 'data', 'manuscript', 'arc_001', 'ch_100.md'), '# t\n', 'utf8')
  const workspace = { project: { root: workspaceRoot }, snapshot: { novel_id: 'paritynovel' } }

  // Absent review is tolerated: materializes as inconclusive/missing.
  const absent = await materializeChapterDelivery(workspace, 'ch_100', 70)
  assert.equal(absent.readyForDelivery, false)

  const reviewPath = join(novelRoot, 'data', 'reviews', 'ch_101.json')
  for (const [label, body, pattern] of [
    ['corrupt JSON', '{broken', /corrupt JSON/],
    ['non-object root', '[]', /root must be a JSON object/],
    ['empty object', '{}', /empty object/],
    ['unknown v2 version', JSON.stringify({ review_v2: { schema_version: 'openwrite.review.v999' } }), /unsupported review_v2 schema version/],
    ['missing v2 version', JSON.stringify({ review_v2: { delivery_status: 'pass' } }), /unsupported review_v2 schema version/],
    ['non-object review_v2 (array)', JSON.stringify({ review_v2: [], score: 95, passed: true }), /review_v2 must be a JSON object when present/],
    ['null review_v2', JSON.stringify({ review_v2: null, score: 95, passed: true }), /review_v2 must be a JSON object when present/],
  ]) {
    await writeFile(reviewPath, body, 'utf8')
    await assert.rejects(
      () => materializeChapterDelivery(workspace, 'ch_101', 70),
      pattern,
      label,
    )
  }
} finally {
  await rm(workspaceRoot, { recursive: true, force: true })
}