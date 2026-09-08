// Record source identity and retain licenses for JavaScript runtime dependencies.
import { readFile, writeFile, mkdir, readdir, copyFile } from 'node:fs/promises'
import { join, dirname } from 'node:path'
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
await writeFile(join(root, 'release/source.json'), JSON.stringify({ repository: 'https://github.com/LiPu-jpg/Openwrite', commit: git(['rev-parse', 'HEAD']), tree: git(['rev-parse', 'HEAD^{tree}']), dirty: git(['status', '--porcelain']).length > 0, components }, null, 2) + '\n')
console.log(`Recorded ${components.length} runtime dependency licenses and source identity`)
