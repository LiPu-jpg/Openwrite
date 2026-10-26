import { test, expect } from 'vitest'
import { mkdtemp, readFile, writeFile, rm } from 'node:fs/promises'
import { join } from 'node:path'
import { tmpdir } from 'node:os'
import { execFile } from 'node:child_process'
import { promisify } from 'node:util'
import ts from 'typescript'

const electron = process.env.OPENWRITE_ELECTRON_EXECUTABLE
test.skipIf(!electron)('runs an ESM verifier when process.execPath is a real Electron binary', async () => {
  const root = await mkdtemp(join(tmpdir(), 'openwrite-electron-verifier-'))
  try {
    const source = await readFile(new URL('../src/owned-script.ts', import.meta.url), 'utf8')
    await writeFile(join(root, 'owned.mjs'), ts.transpileModule(source, {compilerOptions: {module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022}}).outputText)
    await writeFile(join(root, 'verifier.mjs'), 'console.log(JSON.stringify({verdict:process.env.ELECTRON_RUN_AS_NODE === "1" && process.argv[2] === "input with spaces.json" ? "pass" : "fail",evidence:{electron:process.versions.electron}})); process.exit(0)')
    await writeFile(join(root, 'parent.mjs'), 'import {runOwnedScript} from "./owned.mjs"; import {fileURLToPath} from "node:url"; delete process.env.ELECTRON_RUN_AS_NODE; console.log(await runOwnedScript(fileURLToPath(new URL("./verifier.mjs",import.meta.url)),"input with spaces.json")); process.exit(0)')
    const {stdout} = await promisify(execFile)(electron!, [join(root, 'parent.mjs')], {env: {...process.env, ELECTRON_RUN_AS_NODE: '1'}, timeout: 15000})
    expect(JSON.parse(stdout)).toMatchObject({verdict: 'pass', evidence: {electron: expect.any(String)}})
  } finally { await rm(root, {recursive: true, force: true}) }
}, 20000)
