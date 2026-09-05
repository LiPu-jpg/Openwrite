#!/usr/bin/env node
// Exercise the real CLI's local plugin registration and config composition.
// No runtime is booted; every profile and package-manager write is temporary.
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { mkdtemp, mkdir, readFile, writeFile, rm, realpath } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = fileURLToPath(new URL('..', import.meta.url));
const temporary = await mkdtemp(join(tmpdir(), 'dsh-novel-profile-'));
const cli = join(root, 'node_modules/.bin/dsh');
const bridge = join(root, 'packages/openwrite-bridge');
const panel = join(root, 'packages/studio-panel');
const bridgeName = '@dsh-novel/openwrite-bridge';
const panelName = '@dsh-novel/studio-panel';
const env = Object.fromEntries(Object.entries(process.env).filter(([key]) =>
  !/(?:API_?KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL|AUTH)/i.test(key)
  && !key.startsWith('DSH_') && !/^npm_config_/i.test(key)
  && !['NODE_OPTIONS', 'NODE_PATH', 'PNPM_HOME'].includes(key)));
Object.assign(env, {
  HOME: join(temporary, 'home'),
  DSH_HOME: join(temporary, 'dsh'),
  XDG_CONFIG_HOME: join(temporary, 'config'),
  XDG_CACHE_HOME: join(temporary, 'cache'),
  XDG_DATA_HOME: join(temporary, 'data'),
  npm_config_userconfig: join(temporary, 'npmrc'),
  npm_config_cache: join(temporary, 'npm-cache'),
  npm_config_store_dir: join(temporary, 'pnpm-store'),
  npm_config_update_notifier: 'false',
  CI: '1',
});

function run(label, args) {
  const result = spawnSync(cli, args, {
    cwd: temporary, env, encoding: 'utf8', timeout: 60_000, maxBuffer: 4 * 1024 * 1024,
  });
  if (result.status !== 0 || result.error) {
    // Do not print a config dump or inherited environment on failure either.
    const errorCode = `${result.stderr ?? ''}\n${result.stdout ?? ''}`.match(/ERR_[A-Z0-9_]+/)?.[0];
    throw new Error(`${label} failed: exit=${result.status}, signal=${result.signal ?? 'none'}, error=${result.error?.code ?? errorCode ?? 'none'}`);
  }
  return result.stdout;
}

async function check(profile, expected) {
  const directory = join(env.DSH_HOME, 'profiles', profile);
  const manifest = JSON.parse(await readFile(join(directory, 'package.json'), 'utf8'));
  const bundles = manifest.dsh.profile.bundles;
  const dump = run(`${profile} dump-config`, ['--profile', profile, '--dump-config']);
  for (const [name, source] of expected) {
    assert.equal(bundles.filter((bundle) => bundle === name).length, 1, `${profile}: bundle registration count for ${name}`);
    assert.ok(manifest.dependencies[name], `${profile}: dependency missing for ${name}`);
    assert.equal(await realpath(join(directory, 'node_modules', name)), await realpath(source), `${profile}: local link target`);
    const escaped = name.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    // Count resolved plugin rows, not the source-layer comments in the dump.
    const matches = dump.match(new RegExp(`^\\s*name:\\s*['"]?${escaped}['"]?\\s*$`, 'gm')) ?? [];
    assert.equal(matches.length, 1, `${profile}: resolved plugin row count for ${name}`);
  }
  if (profile === 'headless') {
    assert.equal(bundles.includes(panelName), false, 'headless must not mount the web panel');
    assert.equal(dump.includes(`name: ${panelName}`), false);
  }
  return { profile, localBundles: expected.length, resolvedRows: expected.length };
}

try {
  await mkdir(env.HOME, { recursive: true });
  await writeFile(env.npm_config_userconfig, '');
  run('web offline add', ['plugin', '--profile', 'web', 'add', '-w', '--offline', bridge, panel]);
  run('headless offline add', ['plugin', '--profile', 'headless', 'add', '-w', '--offline', bridge]);
  const web = await check('web', [[bridgeName, bridge], [panelName, panel]]);
  const headless = await check('headless', [[bridgeName, bridge]]);

  const manifestPath = join(env.DSH_HOME, 'profiles/web/package.json');
  const manifest = JSON.parse(await readFile(manifestPath, 'utf8'));
  manifest.dsh.profile.bundles = manifest.dsh.profile.bundles.filter((name) => name !== bridgeName);
  await writeFile(manifestPath, `${JSON.stringify(manifest, null, 2)}\n`);
  run('web offline repair', ['plugin', '--profile', 'web', 'add', '-w', '--offline', bridge, panel]);
  const repaired = await check('web', [[bridgeName, bridge], [panelName, panel]]);
  console.log(JSON.stringify({ profiles: 2, web, headless, repair: { restoredBundles: 1, ...repaired }, modelCalls: 0 }));
} finally {
  await rm(temporary, { recursive: true, force: true });
}
