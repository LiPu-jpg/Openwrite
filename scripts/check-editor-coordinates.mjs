// One implementation is used by the native panel and the standalone Core UI.
import {readFileSync, writeFileSync} from 'node:fs'
import {createRequire} from 'node:module'
import {fileURLToPath} from 'node:url'
import {resolve, join} from 'node:path'
import {unzipSync} from 'fflate'
const root = fileURLToPath(new URL('../', import.meta.url))
const require = createRequire(join(root, 'packages/openwrite-bridge/package.json'))
const ts = require('typescript')
const expected = ts.transpileModule(readFileSync(join(root, 'packages/studio-panel/src/client/selection-coordinates.ts'), 'utf8'), {
  compilerOptions: {target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext, newLine: ts.NewLineKind.LineFeed},
}).outputText
const coreIndex = process.argv.indexOf('--write-core')
const name = 'tools/studio_assets/js/selection-coordinates.js'
if (coreIndex >= 0) {
  if (!process.argv[coreIndex + 1]) throw Error('--write-core requires a Core checkout')
  writeFileSync(resolve(process.argv[coreIndex + 1], name), expected)
} else {
  const manifest = JSON.parse(readFileSync(join(root, 'release/runtime-manifest.json'), 'utf8'))
  const wheel = unzipSync(readFileSync(join(root, 'release', manifest.wheel.file)))
  if (!wheel[name] || Buffer.from(wheel[name]).toString('utf8') !== expected) throw Error('Bundled editor coordinate module differs from its TypeScript source')
  console.log('Native panel and Core editor coordinate implementations match')
}
