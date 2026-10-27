"""Browser data ownership contracts without opening a project or user registry."""

from pathlib import Path
import shutil
import subprocess

import pytest


@pytest.mark.skipif(shutil.which("node") is None, reason="Node is needed for browser module contracts")
def test_recovery_drafts_and_request_workspace_binding():
    assets = Path(__file__).parents[1] / "tools" / "studio_assets" / "js"
    script = r'''
import assert from 'node:assert/strict';
import {pathToFileURL} from 'node:url';
const {DocumentDraftStore} = await import(pathToFileURL(process.argv[1] + '/document-drafts.js'));
const {api, state} = await import(pathToFileURL(process.argv[1] + '/core.js'));
const records = new Map();
const storage = {getItem: key => records.get(key) ?? null, setItem: (key, value) => records.set(key, value), removeItem: key => records.delete(key)};
const drafts = new DocumentDraftStore(() => storage);
const a = {projectRoot: '/作品甲', novelId: 'a', path: 'data/manuscript/ch_001.md'};
const b = {...a, projectRoot: '/作品乙'};
const c = {...a, novelId: 'other-work'};
drafts.save(a, 'v1', '最后的中文输入\n');
assert.equal(drafts.load(b), null);
assert.equal(drafts.load(c), null);
assert.equal(drafts.load(a).content, '最后的中文输入\n');
assert.equal(drafts.load(a).version, 'v1');
drafts.save(a, 'v1', 'newer input');
assert.equal(drafts.removeIfContent(a, 'v1', 'old saved bytes'), false);
assert.equal(drafts.load(a).content, 'newer input');
assert.equal(drafts.removeIfContent(a, 'v2', 'newer input'), false);
assert.equal(drafts.removeIfContent(a, 'v1', 'newer input'), true);
assert.equal(drafts.load(a), null);
drafts.save(a, 'v1', 'conflicted old body');
drafts.save(a, 'v2', 'current body');
assert.equal(drafts.load(a, 'v1').content, 'conflicted old body');
assert.equal(drafts.load(a, 'v2').content, 'current body');
assert.equal(drafts.removeIfContent(a, 'v2', 'current body'), true);
assert.equal(drafts.load(a, 'v2').content, 'conflicted old body');
records.set(drafts.key(a), '{not JSON');
assert.equal(drafts.load(a), null);
assert.throws(() => drafts.save({...a, projectRoot: ''}, 'v1', 'body'));
const denied = new DocumentDraftStore(() => {throw new Error('storage unavailable')});
assert.throws(() => denied.save(a, 'v1', 'body'), /storage unavailable/);
const calls = [];
globalThis.fetch = async (path, options) => {calls.push({path, options}); return new Response('{}', {headers: {'Content-Type': 'application/json'}})};
state.workspace = {project: {root: '/作品甲/100%'}};
await api('/api/document?path=chapter.md');
assert.equal(decodeURIComponent(calls.at(-1).options.headers['X-OpenWrite-Workspace-Root']), '/作品甲/100%');
assert.equal(calls.at(-1).options.headers['X-OpenWrite-Workspace-Root-Encoding'], 'uri');
await api('/api/document', {method: 'PUT', body: '{}', headers: {'X-OpenWrite-Workspace-Root': encodeURIComponent(a.projectRoot), 'X-OpenWrite-Workspace-Root-Encoding': 'uri'}});
assert.equal(decodeURIComponent(calls.at(-1).options.headers['X-OpenWrite-Workspace-Root']), a.projectRoot);
await api('/api/project/open', {method: 'POST', body: '{}'});
assert.equal(calls.at(-1).options.headers['X-OpenWrite-Workspace-Root'], undefined);
'''
    result = subprocess.run(
        ["node", "--input-type=module", "-e", script, str(assets)],
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stderr
