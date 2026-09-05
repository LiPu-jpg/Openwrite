import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { once } from 'node:events';
import { createServer } from 'node:net';
import { mkdtemp, mkdir, readFile, writeFile, copyFile, rm, readdir } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import { setTimeout as delay } from 'node:timers/promises';
import test from 'node:test';

const source = fileURLToPath(new URL('..', import.meta.url));
async function put(path, content, executable = false) {
  await mkdir(dirname(path), { recursive: true });
  await writeFile(path, content, executable ? { mode: 0o755 } : {});
}
const json = (path) => readFile(path, 'utf8').then(JSON.parse);

async function fixture(t) {
  const root = await mkdtemp(join(tmpdir(), 'dsh-novel-lifecycle-'));
  const running = [];
  t.after(async () => {
    for (const run of running) {
      if (run.child.exitCode === null) run.child.kill('SIGTERM');
      await Promise.race([run.done, delay(3000)]);
      if (run.child.exitCode === null) run.child.kill('SIGKILL');
    }
    // Keep failing tests isolated too; these PID files belong to fixture mocks.
    for (const name of ['studio.pid', 'dsh.pid']) {
      if (await exists(join(root, name))) {
        const pid = Number(await readFile(join(root, name), 'utf8'));
        try { process.kill(-pid, 'SIGKILL'); } catch (error) { if (error.code !== 'ESRCH') throw error; }
      }
    }
    await rm(root, { recursive: true, force: true });
  });
  for (const name of ['install.sh', 'dev.sh', 'dev-supervisor.mjs']) {
    await mkdir(join(root, 'scripts'), { recursive: true });
    await copyFile(join(source, 'scripts', name), join(root, 'scripts', name));
  }
  await put(join(root, 'presets/openwrite/agent.cordis.yml'), 'preset: openwrite\n');
  await put(join(root, 'scripts/dog/review.js'), '// adapter\n');
  for (const name of ['openwrite-bridge', 'studio-panel']) {
    await put(join(root, 'packages', name, 'package.json'), JSON.stringify({ name: `@dsh-novel/${name}` }));
  }
  const logCode = `const fs = require('node:fs'); const path = require('node:path');
fs.appendFileSync(process.env.TEST_LOG, JSON.stringify({command:path.basename(process.argv[1]), args:process.argv.slice(2), cwd:process.cwd(), dshHome:process.env.DSH_HOME})+'\\n');`;
  for (const name of ['npm', 'pnpm']) {
    await put(join(root, 'bin', name), `#!/usr/bin/env node\n${logCode}\n`, true);
  }
  await put(join(root, 'bin/git'), `#!/usr/bin/env node
${logCode}
const a=process.argv.slice(2);
const cloneIndex=a.indexOf('clone');
if(cloneIndex<0) { console.error('Unexpected git invocation: '+a.join(' ')); process.exit(89); }
const failMarker=path.join(process.env.HOME,'.git-clone-failed-once');
if(process.env.GIT_CLONE_FAIL_ONCE && !fs.existsSync(failMarker)) {
  fs.mkdirSync(path.dirname(failMarker),{recursive:true}); fs.writeFileSync(failMarker,'failed'); process.exit(17);
}
const target=a.at(-1);
fs.mkdirSync(target,{recursive:true});
fs.writeFileSync(path.join(target,'package.json'),JSON.stringify({name:'@dsh-external/dsh-dog'}));
fs.writeFileSync(path.join(target,'pnpm-lock.yaml'),'lockfileVersion: 9\\n');
`, true);
  await put(join(root, 'bin/rsync'), `#!/usr/bin/env node
const fs = require('node:fs'); const args=process.argv.slice(2);
fs.cpSync(args.at(-2),args.at(-1),{recursive:true});
`, true);
  await put(join(root, 'node_modules/.bin/dsh'), `#!/usr/bin/env node
${logCode}
const a=process.argv.slice(2);
if(a[0]==='web') {
  fs.writeFileSync(process.env.DSH_PID_FILE, String(process.pid));
  if(process.env.DSH_TEST_EXIT) setTimeout(()=>process.exit(Number(process.env.DSH_TEST_EXIT)), 100);
  else setInterval(()=>{},1000);
} else {
  const profile=a[a.indexOf('--profile')+1];
  const dir=path.join(process.env.DSH_HOME,'profiles',profile);
  const manifest=path.join(dir,'package.json');
  fs.mkdirSync(dir,{recursive:true});
  const p=fs.existsSync(manifest)?JSON.parse(fs.readFileSync(manifest)): {dependencies:{},dsh:{profile:{bundles:[]}}};
  if (a.includes('--dump-config')) {
    if(profile==='headless'&&process.env.FAIL_HEADLESS) process.exit(47);
  } else if(a[0]==='plugin'&&a[3]==='add'&&a[4]==='-w'&&path.isAbsolute(a[5])) {
    const pkg=JSON.parse(fs.readFileSync(path.join(a[5],'package.json'))).name;
    p.dependencies[pkg]='link:'+a[5];
    if(!p.dsh.profile.bundles.includes(pkg)) p.dsh.profile.bundles.push(pkg);
    fs.mkdirSync(path.join(dir,'node_modules',pkg),{recursive:true});
    fs.writeFileSync(path.join(dir,'node_modules',pkg,'ready'),'installed');
  } else {console.error('Unexpected CLI invocation (model calls forbidden): '+a.join(' '));process.exit(88);}
  fs.writeFileSync(manifest,JSON.stringify(p));
}
`, true);
  await put(join(root, '.venv/bin/openwrite'), `#!/usr/bin/env node
const fs=require('node:fs'); const http=require('node:http'); const {spawn}=require('node:child_process');
const args=process.argv.slice(2);
fs.writeFileSync(process.env.STUDIO_PID_FILE,String(process.pid));
if(process.env.STUDIO_TEST_EXIT) process.exit(Number(process.env.STUDIO_TEST_EXIT));
if(process.env.STUDIO_DESCENDANT) {
  const child=spawn(process.execPath,['-e',"process.on('SIGTERM',()=>{});setInterval(()=>{},1000)"],{stdio:'ignore'});
  fs.writeFileSync(process.env.STUDIO_DESCENDANT,String(child.pid));
}
http.createServer((req,res)=>{res.statusCode=process.env.STUDIO_UNHEALTHY?'503':'200';res.end('{}');})
 .listen(Number(args[args.indexOf('--port')+1]),'127.0.0.1');
`, true);
  const env = { ...process.env, HOME: join(root, 'home'), PATH: `${join(root, 'bin')}:${process.env.PATH}`,
    TEST_LOG: join(root, 'commands.jsonl'), DSH_PID_FILE: join(root, 'dsh.pid'),
    STUDIO_PID_FILE: join(root, 'studio.pid'), DSH_DOG_DIR: '', DSH_DOG_AUTO_INSTALL: '0',
  };
  delete env.DSH_HOME;
  for (const key of ['DSH_TEST_EXIT', 'STUDIO_TEST_EXIT', 'STUDIO_UNHEALTHY', 'STUDIO_DESCENDANT', 'FAIL_HEADLESS']) delete env[key];
  return { root, env, running, home: join(root, 'home/.dsh') };
}

function launch(f, script, overrides = {}, args = []) {
  const child = spawn('bash', [join(f.root, 'scripts', script), ...args], { env: { ...f.env, ...overrides } });
  let output = '';
  child.stdout.on('data', (chunk) => { output += chunk; });
  child.stderr.on('data', (chunk) => { output += chunk; });
  const done = once(child, 'close').then(([code, signal]) => ({ code, signal, output }));
  const run = { child, done, output: () => output };
  f.running.push(run);
  return run;
}
async function commands(f) {
  return (await readFile(f.env.TEST_LOG, 'utf8')).trim().split('\n').map(JSON.parse);
}
async function until(check, timeout = 6000) {
  const deadline = Date.now() + timeout;
  while (Date.now() < deadline) {
    if (await check()) return;
    await delay(30);
  }
  assert.fail('Timed out waiting for subprocess condition');
}
async function exists(path) { try { await readFile(path); return true; } catch { return false; } }
function alive(pid) { try { process.kill(pid, 0); return true; } catch (error) { if (error.code === 'ESRCH') return false; throw error; } }
async function assertStopped(...paths) {
  for (const path of paths) {
    if (await exists(path)) {
      const pid = Number(await readFile(path, 'utf8'));
      await until(() => !alive(pid));
    }
  }
}
async function freePort() {
  const server = createServer();
  server.listen(0, '127.0.0.1');
  await once(server, 'listening');
  const port = server.address().port;
  await new Promise((resolve) => server.close(resolve));
  return String(port);
}

test('install uses locks and offline config, repairs registration, preserves earlier preset backups', async (t) => {
  const f = await fixture(t);
  await put(join(f.home, '.agent-presets-legacy/goethe/original'), 'old backup');
  await put(join(f.home, '.agent-presets/goethe/agent'), 'first migration');
  let result = await launch(f, 'install.sh').done;
  assert.equal(result.code, 0, result.output);
  const manifest = join(f.home, 'profiles/web/package.json');
  const first = await json(manifest);
  assert.deepEqual(first.dsh.profile.bundles, ['@dsh-novel/openwrite-bridge', '@dsh-novel/studio-panel']);
  first.dsh.profile.bundles = [];
  await writeFile(manifest, JSON.stringify(first));
  await rm(join(f.home, 'profiles/web/node_modules'), { recursive: true });
  await put(join(f.home, '.agent-presets/goethe/agent'), 'second migration');
  result = await launch(f, 'install.sh').done;
  assert.equal(result.code, 0, result.output);
  assert.deepEqual((await json(manifest)).dsh.profile.bundles, ['@dsh-novel/openwrite-bridge', '@dsh-novel/studio-panel']);
  assert.equal(await readFile(join(f.home, 'profiles/web/node_modules/@dsh-novel/openwrite-bridge/ready'), 'utf8'), 'installed');
  assert.equal(await readFile(join(f.home, '.agent-presets-legacy/goethe/original'), 'utf8'), 'old backup');
  const backups = (await readdir(join(f.home, '.agent-presets-legacy'))).filter((name) => name.startsWith('goethe.'));
  assert.equal(backups.length, 2);
  assert.deepEqual((await Promise.all(backups.map((name) => readFile(join(f.home, '.agent-presets-legacy', name, 'preset/agent'), 'utf8')))).sort(), ['first migration', 'second migration']);
  const calls = await commands(f);
  assert.equal(calls.filter((c) => c.command === 'npm' && c.args[0] === 'ci').length, 6);
  assert.equal(calls.filter((c) => c.command === 'npm' && c.args[0] === 'install').length, 0);
  assert.equal(calls.filter((c) => c.command === 'dsh' && c.args.includes('--dump-config')).length, 4);
  assert.equal(calls.filter((c) => c.command === 'dsh' && c.args[0] === 'plugin').length, 6);
  assert.ok(calls.every((c) => c.dshHome === f.home));
});

test('install exposes headless initialization failures and honors DSH_HOME', async (t) => {
  const f = await fixture(t);
  const custom = join(f.root, 'custom-dsh');
  const result = await launch(f, 'install.sh', { DSH_HOME: custom, FAIL_HEADLESS: '1' }).done;
  assert.equal(result.code, 47, result.output);
  const calls = await commands(f);
  assert.ok(calls.every((c) => c.dshHome === custom));
  assert.equal(calls.filter((c) => c.args[0] === 'plugin').length, 0);
});

test('install automatically bootstraps and reuses the pinned dsh-dog integration', async (t) => {
  const f = await fixture(t);
  const overrides = {
    DSH_DOG_AUTO_INSTALL: '1',
    DSH_DOG_REPOSITORY: 'https://example.invalid/Fun10165/dsh-dog.git',
    DSH_DOG_REF: 'v1.2.0',
    GIT_CLONE_FAIL_ONCE: '1',
  };
  let result = await launch(f, 'install.sh', overrides).done;
  assert.equal(result.code, 0, result.output);

  const dogDir = join(f.home, 'extensions/dsh-dog');
  const web = await json(join(f.home, 'profiles/web/package.json'));
  const headless = await json(join(f.home, 'profiles/headless/package.json'));
  assert.deepEqual(web.dsh.profile.bundles, [
    '@dsh-novel/openwrite-bridge', '@dsh-novel/studio-panel', '@dsh-external/dsh-dog',
  ]);
  assert.deepEqual(headless.dsh.profile.bundles, ['@dsh-novel/openwrite-bridge']);
  assert.match(await readFile(join(f.home, 'settings.yaml'), 'utf8'), new RegExp(`workspaceRoot: ${f.root}`));
  assert.equal(await exists(join(dogDir, '.dsh-openwrite-managed')), true);

  result = await launch(f, 'install.sh', overrides).done;
  assert.equal(result.code, 0, result.output);
  const calls = await commands(f);
  const clones = calls.filter((call) => call.command === 'git' && call.args.includes('clone'));
  assert.equal(clones.length, 2);
  assert.deepEqual(clones[1].args.slice(0, 4), ['-c', 'http.proxy=', '-c', 'https.proxy=']);
  assert.match(result.output, /复用已安装的 dsh-dog/);
});

test('dev rejects an occupied Studio port without starting or killing other services', async (t) => {
  const f = await fixture(t);
  const server = createServer();
  server.listen(0, '127.0.0.1');
  await once(server, 'listening');
  t.after(() => new Promise((resolve) => server.close(resolve)));
  const result = await launch(f, 'dev.sh', { STUDIO_PORT: String(server.address().port) }).done;
  assert.equal(result.code, 1, result.output);
  assert.match(result.output, /端口.*无法使用/);
  assert.equal(await exists(f.env.STUDIO_PID_FILE), false);
  assert.equal(await exists(f.env.DSH_PID_FILE), false);
  assert.ok(server.listening);
});

test('dev stops immediately when Studio exits during startup', async (t) => {
  const f = await fixture(t);
  const result = await launch(f, 'dev.sh', { STUDIO_PORT: await freePort(), STUDIO_TEST_EXIT: '23' }).done;
  assert.equal(result.code, 23, result.output);
  assert.equal(await exists(f.env.DSH_PID_FILE), false);
  await assertStopped(f.env.STUDIO_PID_FILE);
});

test('dev stops Studio and its descendants when dsh exits', async (t) => {
  const f = await fixture(t);
  const descendant = join(f.root, 'descendant.pid');
  const result = await launch(f, 'dev.sh', { STUDIO_PORT: await freePort(), DSH_TEST_EXIT: '7', STUDIO_DESCENDANT: descendant }).done;
  assert.equal(result.code, 7, result.output);
  assert.equal((await commands(f)).find((call) => call.args[0] === 'web').dshHome, f.home);
  await assertStopped(f.env.STUDIO_PID_FILE, f.env.DSH_PID_FILE, descendant);
});

test('dev bootstraps from OPENWRITE_DIR, including paths with spaces', async (t) => {
  const f = await fixture(t);
  const checkout = join(f.root, 'OpenWrite source');
  await put(join(checkout, 'pyproject.toml'), '[project]\nname = "openwrite"\n');
  await rm(join(f.root, '.venv'), { recursive: true });
  await put(join(f.root, 'bin/uv'), `#!/usr/bin/env node
const fs=require('node:fs'); const args=process.argv.slice(2);
fs.appendFileSync(process.env.TEST_LOG,JSON.stringify({command:'uv',args})+'\\n');
if(args[0]==='pip') process.exit(42);
`, true);
  const result = await launch(f, 'dev.sh', { OPENWRITE_DIR: checkout }).done;
  assert.equal(result.code, 42, result.output);
  const pip = (await commands(f)).find((call) => call.args[0] === 'pip');
  assert.equal(pip.args.at(-1), checkout);
  assert.equal(pip.args.at(-2), '-e');
  assert.equal(await exists(f.env.STUDIO_PID_FILE), false);
});

for (const [signal, code] of [['SIGINT', 130], ['SIGTERM', 143]]) {
  test(`dev cleans up both services on ${signal}`, async (t) => {
    const f = await fixture(t);
    const running = launch(f, 'dev.sh', { STUDIO_PORT: await freePort() });
    t.after(() => { if (running.child.exitCode === null) running.child.kill('SIGKILL'); });
    await until(() => exists(f.env.DSH_PID_FILE));
    running.child.kill(signal);
    const result = await running.done;
    assert.equal(result.code, code, result.output);
    await assertStopped(f.env.STUDIO_PID_FILE, f.env.DSH_PID_FILE);
  });
}

test('dev health timeout fails without launching dsh and cleans Studio', { timeout: 40_000 }, async (t) => {
  const f = await fixture(t);
  const result = await launch(f, 'dev.sh', { STUDIO_PORT: await freePort(), STUDIO_UNHEALTHY: '1' }).done;
  assert.equal(result.code, 1, result.output);
  assert.match(result.output, /30 秒内未通过健康检查/);
  assert.equal(await exists(f.env.DSH_PID_FILE), false);
  await assertStopped(f.env.STUDIO_PID_FILE);
});
