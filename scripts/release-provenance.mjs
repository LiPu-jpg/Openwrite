// Record source identity and retain licenses for JavaScript runtime dependencies.
import { readFile, writeFile, mkdir, readdir, copyFile, lstat } from 'node:fs/promises'
import { join, dirname, resolve } from 'node:path'
import { createHash } from 'node:crypto'
import { createRequire } from 'node:module'
import { execFileSync } from 'node:child_process'
import { fileURLToPath } from 'node:url'
const root = fileURLToPath(new URL('../', import.meta.url))
const manifest = JSON.parse(await readFile(join(root, 'package.json')))
const visited = new Set()
const components = []
async function collect(name, from) {
  if (name.startsWith('@deepseek-ai/') || name === 'react') return
  const require = createRequire(join(from, 'package.json'))
  let directory
  try { directory = dirname(require.resolve(name + '/package.json')) }
  catch {
    directory = dirname(require.resolve(name))
    while (true) {
      const pkg = await readFile(join(directory, 'package.json'), 'utf8').then(JSON.parse).catch(() => null)
      if (pkg?.name === name) break
      const parent = dirname(directory)
      if (parent === directory) throw new Error('Cannot locate runtime package ' + name)
      directory = parent
    }
  }
  const pkg = JSON.parse(await readFile(join(directory, 'package.json')))
  const key = name + '@' + pkg.version
  if (visited.has(key)) return
  visited.add(key)
  const destination = join(root, 'release/licenses', key.replaceAll('/', '__'))
  await mkdir(destination, { recursive: true })
  const licenses = (await readdir(directory)).filter(file => /^(?:licen[cs]e|copying|notice)(?:[.-]|$)/i.test(file))
  if (!licenses.length) throw new Error('Missing runtime license: ' + key)
  for (const file of licenses) await copyFile(join(directory, file), join(destination, file))
  components.push({ name, version: pkg.version, license: pkg.license, repository: pkg.repository, files: licenses })
  for (const child of Object.keys(pkg.dependencies ?? {})) await collect(child, directory)
}
for (const name of Object.keys(manifest.dependencies ?? {})) await collect(name, root)
const git = args => execFileSync('git', args, { cwd: root, encoding: 'utf8' }).trim()
// pnpm's GitHub source provider downloads a commit archive without .git.
// Hash the actual source tree in that case; never invent a commit or borrow
// an enclosing user's repository identity.
const sourceHash = createHash('sha256')
async function hashSource(directory, prefix = '') {
  for (const entry of (await readdir(directory, { withFileTypes: true })).sort((a, b) => a.name.localeCompare(b.name))) {
    if (['node_modules', 'lib', 'dist', '.git', 'licenses'].includes(entry.name) || entry.name.startsWith('.tmp-') || /(?:\.log|\.tgz|\.manifest\.json)$/.test(entry.name) || entry.name.startsWith('release-report-') || prefix + entry.name === 'release/source.json') continue
    sourceHash.update(prefix + entry.name + '\0')
    if (entry.isDirectory()) await hashSource(join(directory, entry.name), prefix + entry.name + '/')
    else if (entry.isFile()) sourceHash.update(await readFile(join(directory, entry.name)))
  }
}
await hashSource(root)
let identity = { commit: null, tree: null, dirty: null, acquisition: 'source-archive' }
if (await lstat(join(root, '.git')).then(() => true).catch(() => false)) {
  if (resolve(git(['rev-parse', '--show-toplevel'])) !== resolve(root)) throw new Error('Source repository boundary mismatch')
  identity = { commit: git(['rev-parse', 'HEAD']), tree: git(['rev-parse', 'HEAD^{tree}']), dirty: git(['status', '--porcelain']).length > 0, acquisition: 'git-checkout' }
}
await writeFile(join(root, 'release/source.json'), JSON.stringify({ repository: 'https://github.com/LiPu-jpg/Openwrite', ...identity, sourceTreeSha256: sourceHash.digest('hex'), components }, null, 2) + '\n')
console.log(`Recorded ${components.length} runtime dependency licenses and source identity`)
