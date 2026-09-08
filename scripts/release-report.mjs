// Gate promotion on reports for exactly the bytes uploaded by the build job.
import assert from 'node:assert/strict'
import { readFile, readdir, writeFile } from 'node:fs/promises'
import { join, resolve } from 'node:path'
import { createHash } from 'node:crypto'
const directory = resolve(process.argv[2] ?? '.tmp-release-final')
const files = await readdir(directory)
const artifact = files.find(file => /^dsh-openwrite-.*\.tgz$/.test(file))
assert.ok(artifact, 'Missing release artifact')
const manifest = JSON.parse(await readFile(join(directory, artifact + '.manifest.json')))
assert.equal(createHash('sha256').update(await readFile(join(directory, artifact))).digest('hex'), manifest.sha256)
assert.equal(manifest.source.plugin.dirty, false, 'Release source must be clean')
const reports = await Promise.all(files.filter(file => /^release-report-.*\.json$/.test(file)).map(async file => JSON.parse(await readFile(join(directory, file)))))
const required = ['install', 'repeat-install', 'existing-plugin-coexistence', 'native-dependency-load', 'backend-auth', 'failed-upgrade-preserves-active', 'rollback', 'uninstall', 'retain-data']
for (const [platform, arch, major] of [['linux', 'x64', 24], ['darwin', 'arm64', 24], ['darwin', 'x64', 24], ['win32', 'x64', 24], ['linux', 'x64', 22], ['linux', 'x64', 26]]) {
  const report = reports.find(r => r.installSource === 'release' && r.platform === platform && r.arch === arch && Number(r.node.match(/^v(\d+)/)?.[1]) === major)
  assert.ok(report, `Missing ${platform}/${arch}/Node ${major}`)
  assert.equal(report.status, 'passed')
  assert.equal(report.artifactSha256, manifest.sha256, 'Platform tested different artifact')
  for (const check of required) assert.ok(report.checks.includes(check), `Missing check: ${check}`)
  assert.ok(report.checks.includes('native-browser-launch'), 'Missing browser acceptance')
}
const source = reports.find(r => r.installSource.startsWith('github:'))
assert.equal(source?.status, 'passed', 'GitHub source installation must pass')
for (const check of required) assert.ok(source.checks.includes(check), `Source missing check: ${check}`)
const result = { status: 'passed', artifact, sha256: manifest.sha256, host: manifest.host, source: manifest.source, workflow: process.env.GITHUB_RUN_ID ? `https://github.com/${process.env.GITHUB_REPOSITORY}/actions/runs/${process.env.GITHUB_RUN_ID}` : null, reports, realModelValidation: { status: 'not-run', modelCalls: 0, countedAsPassed: false } }
await writeFile(join(directory, 'release-acceptance.json'), JSON.stringify(result, null, 2) + '\n')
await writeFile(join(directory, 'SHA256SUMS'), `${manifest.sha256}  ${artifact}\n`)
console.log(`Release gate passed: ${artifact} ${manifest.sha256}`)
