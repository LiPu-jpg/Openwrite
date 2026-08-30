import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { validateOrRaise, validateSchema } from './schema-lint.mjs'

const here = dirname(fileURLToPath(import.meta.url))
const openwriteRoot = process.env.OPENWRITE_ROOT ?? join(here, '..', '..', '..', '..', 'OpenWrite')
const fixturePath = join(openwriteRoot, 'tests', 'fixtures', 'contracts', 'canonical_v2.json')
const fixture = JSON.parse(await readFile(fixturePath, 'utf8'))

// ── load the shared machine-readable schemas (source of truth) ──────────────
const schemas = Object.fromEntries(await Promise.all([
  'review-v2-decision', 'review-manifest-v2', 'delivery-manifest-v2',
  'delivery-stage-v2', 'model-benchmark-v1', 'model-profile-surface-v1',
].map(async name => [
  name,
  JSON.parse(await readFile(join(openwriteRoot, 'contracts', `${name}.schema.json`), 'utf8')),
])))

const SCHEMA_BY_KEY = {
  review: 'review-v2-decision',
  delivery: 'delivery-manifest-v2',
  model_profile: 'model-profile-surface-v1',
  benchmark: 'model-benchmark-v1',
}
// Golden fixture must pass the shared schemas on the JS side, mirroring
// tests/test_contract_schema_parity.py on the Python side.
for (const [key, schemaName] of Object.entries(SCHEMA_BY_KEY)) {
  validateOrRaise(fixture[key], schemas[schemaName])
}

const review = fixture.review
assert.equal(review.schema_version, 'openwrite.review.v2')
for (const field of ['quality_score', 'coverage', 'gate_status', 'delivery_status', 'production_gate_status', 'execution_status']) {
  assert.ok(Object.hasOwn(review, field), `review field: ${field}`)
}
assert.equal(fixture.delivery.schemaVersion, 'dsh-novel.delivery.manifest.v2')
assert.equal(fixture.model_profile.schema_version, 'openwrite.model-profile.v1')
assert.equal(fixture.benchmark.schema_version, 'openwrite.model-benchmark.v1')
assert.equal(JSON.stringify(fixture).includes('api_key'), false)
assert.equal(JSON.stringify(fixture).includes('secret'), false)

// ── parity matrix: same verdicts as the Python tests ────────────────────────
// review v2: unknown/missing schema version and bad enums fail on both sides.
for (const mutate of [
  { schema_version: 'openwrite.review.v999' },
  { execution_status: 'finished' },
  { coverage: 1.5 },
  { quality_score: 120 },
]) {
  assert.ok(validateSchema({ ...review, ...mutate }, schemas['review-v2-decision']), JSON.stringify(mutate))
}
const reviewMissing = { ...review }
delete reviewMissing.schema_version
assert.ok(validateSchema(reviewMissing, schemas['review-v2-decision']))

// benchmark: bad status / array types fail on both sides.
for (const mutate of [
  { status: 'done' },
  { candidates: 'nope' },
  { evaluations: null },
]) {
  assert.ok(validateSchema({ ...fixture.benchmark, ...mutate }, schemas['model-benchmark-v1']), JSON.stringify(mutate))
}

// profile surface: credentials must never appear in a valid surface.
const leakedProfile = {
  ...fixture.model_profile,
  profiles: [{ ...fixture.model_profile.profiles[0], api_key: 'must-not-appear' }],
}
assert.ok(validateSchema(leakedProfile, schemas['model-profile-surface-v1']))

// delivery stage: bad verdict and empty status fail on both sides.
const stageSchema = schemas['delivery-manifest-v2'].properties.stages.additionalProperties
const stageBase = fixture.delivery.stages.writing
assert.equal(validateSchema(stageBase, stageSchema).length, 0)
assert.ok(validateSchema({ ...stageBase, verdict: 'excellent' }, stageSchema))
assert.ok(validateSchema({ ...stageBase, status: '' }, stageSchema))

console.log('canonical contract smoke ok:', fixturePath)
