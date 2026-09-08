// CI-only diagnostic reproduction. Runs installed, unmodified Core code with
// Python's own stack timer, avoiding the Windows venv launcher's separate PID.
import { spawn } from 'node:child_process'
import { createInterface } from 'node:readline'
import { randomBytes } from 'node:crypto'
import { mkdir } from 'node:fs/promises'
import { join } from 'node:path'

export async function diagnoseInitialization(python, temporary, stopOwnedProcess) {
  const state = join(temporary, 'diagnostic-state')
  const novel = join(temporary, 'diagnostic-中文作品')
  await mkdir(state)
  await mkdir(novel)
  const token = randomBytes(32).toString('hex')
  const child = spawn(python, ['-I', '-X', 'utf8', '-u', '-c', 'import faulthandler, runpy; faulthandler.dump_traceback_later(8, repeat=True); runpy.run_module("tools.managed_runtime", run_name="__main__")'], { cwd: state, windowsHide: true, stdio: ['pipe', 'pipe', 'pipe'] })
  // Stack frames only: no locals, credentials, model calls, or private works.
  let stackBytes = 0
  child.stderr.on('data', data => { if (stackBytes < 24_000) console.error(data.toString()); stackBytes += data.length })
  const lines = createInterface({ input: child.stdout })
  let timer
  try {
    const port = await new Promise((resolve, reject) => {
      timer = setTimeout(() => reject(new Error('Diagnostic backend startup timed out')), 20_000)
      child.once('error', reject)
      lines.on('line', line => {
        try { const value = JSON.parse(line); if (value.port) resolve(value.port) } catch {}
      })
      child.stdin.write(JSON.stringify({ token, state_dir: state }) + '\n')
    })
    clearTimeout(timer)
    const response = await fetch(`http://127.0.0.1:${port}/api/project/init`, {
      method: 'POST',
      headers: { Authorization: 'Bearer ' + token, 'Content-Type': 'application/json', 'X-OpenWrite-Studio': '1', 'X-OpenWrite-Workspace-Root': encodeURIComponent(novel), 'X-OpenWrite-Workspace-Root-Encoding': 'uri' },
      body: JSON.stringify({ novel_id: 'diagnostic-test', title: '诊断新书', project_path: novel }),
      signal: AbortSignal.timeout(18_000),
    })
    console.log('Diagnostic initialization response:', response.status)
  } catch (error) { console.error('Diagnostic initialization:', error.message) }
  finally { clearTimeout(timer); lines.close(); child.stdout.resume(); await stopOwnedProcess(child) }
}
