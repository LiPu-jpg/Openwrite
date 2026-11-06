import test from 'node:test'
import assert from 'node:assert/strict'
import { existsSync, readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'
// Assert against the built module, and fail if it predates the source change so a
// stale build cannot make this gate pass.
const here = dirname(fileURLToPath(import.meta.url))
const built = join(here, '..', 'lib', 'domain.js')
assert.ok(existsSync(built), 'run `npm --prefix packages/openwrite-bridge run build` first')
assert.ok(readFileSync(built, 'utf8').includes('model/profiles/delete-preview'),
  'lib/domain.js is stale: rebuild packages/openwrite-bridge before running this test')
const { GLOBAL_PATHS, WRITABLE_PATH_RE, WRITABLE_PATHS } = await import(built)

test('the proxy allowlist covers every write the panel issues', () => {
  // ModelView drives a two-step delete: preview, then the delete itself.
  assert.ok(WRITABLE_PATHS.has('model/profiles/delete-preview'),
    'the delete preview must be allowlisted or no chat profile can be deleted from the browser')
  assert.ok(WRITABLE_PATHS.has('model/profiles/delete'))
  // The parameterised routes stay matched by the regex rather than enumerated.
  assert.ok(WRITABLE_PATH_RE.test('tasks/tsk_1/cancel'))
  assert.ok(WRITABLE_PATH_RE.test('revisions/selection'))
  assert.ok(WRITABLE_PATH_RE.test('revisions/rev_abc123/apply'))
  assert.ok(!WRITABLE_PATH_RE.test('revisions/rev_abc123/unknown'))
})

test('the model library is reachable without a workspace', () => {
  // The profile library lives in the user's preferences directory, outside
  // every project, and every model route is registered with
  // `requires_project=False`. The host settings dialog is opened without a
  // bound workspace, so these paths must not be gated on a workspace id.
  for (const path of [
    'model',
    'model/test',
    'model/embedding',
    'model/embedding/test',
    'model/embedding/select',
    'model/embedding/delete',
    'model/profiles',
    'model/profiles/delete',
    'model/profiles/delete-preview',
    'model/routes',
    'model/host-models',
    'model/host-profiles',
  ]) {
    assert.ok(GLOBAL_PATHS.has(path), `${path} must be answerable without a workspace`)
    // A global path that is also written must stay in the write allowlist.
    // The read-only ones are not written at all.
    if (!['model/test', 'model/embedding/test', 'model/host-models'].includes(path)) {
      assert.ok(WRITABLE_PATHS.has(path), `${path} is written and must be allowlisted`)
    }
  }
})

test('project-scoped paths stay gated on a workspace', () => {
  // Only the model library is global. Everything else keeps failing closed
  // without a workspace id — including the paths that merely look similar.
  for (const path of ['assets', 'outline/edit', 'tasks', 'scenes/metadata', 'project/metadata']) {
    assert.ok(!GLOBAL_PATHS.has(path), `${path} is project-scoped and must not be global`)
  }
})
