import { spawn } from 'node:child_process'
import { stat } from 'node:fs/promises'

export class ScriptExecutionError extends Error {
  constructor(
    readonly code: 'SCRIPT_NOT_FOUND' | 'SCRIPT_START_FAILED' | 'SCRIPT_EXIT_FAILED' | 'SCRIPT_TIMEOUT' | 'SCRIPT_OUTPUT_LIMIT',
    message: string,
    readonly diagnostics: { script: string; exitCode?: number | null; signal?: string | null; stderr?: string; outputPreview?: string },
  ) { super(message); this.name = 'ScriptExecutionError' }
}

export function outputPreview(output: string): string {
  return new TextDecoder().decode(Buffer.from(output).subarray(0, 200), { stream: true })
}

/** Execute without blocking the host event loop; cancellation owns only this process tree. */
export async function runOwnedScript(script: string, input: string, signal?: AbortSignal): Promise<string> {
  signal?.throwIfAborted()
  try {
    if (!(await stat(script)).isFile()) throw new Error('not a file')
  } catch {
    throw new ScriptExecutionError('SCRIPT_NOT_FOUND', `Verifier script was not found: ${script}`, { script })
  }
  signal?.throwIfAborted()
  const js = /\.(?:c|m)?js$/.test(script)
  const child = spawn(js ? process.execPath : script, js ? [script, input] : [input], {
    detached: process.platform !== 'win32', windowsHide: true, stdio: ['ignore', 'pipe', 'pipe'],
    // Desktop's executable is Electron. Use its supported Node mode in this
    // child only, as the host itself does for package operations.
    env: js ? { ...process.env, ELECTRON_RUN_AS_NODE: '1' } : process.env,
  })
  let output = ''
  let stderr = ''
  let failure: Error | undefined
  let escalation: ReturnType<typeof setTimeout> | undefined
  const stop = () => {
    if (!child.pid || child.exitCode !== null || child.signalCode !== null) return
    if (process.platform === 'win32') {
      const killer = spawn('taskkill', ['/pid', String(child.pid), '/T', '/F'], { windowsHide: true, stdio: 'ignore' })
      killer.once('error', () => child.kill())
    } else {
      try { process.kill(-child.pid, 'SIGTERM') } catch { child.kill() }
      escalation ??= setTimeout(() => {
        if (child.exitCode !== null || child.signalCode !== null) return
        try { process.kill(-child.pid!, 'SIGKILL') } catch { child.kill('SIGKILL') }
      }, 3000)
    }
  }
  child.stdout.on('data', chunk => {
    output += String(chunk)
    if (Buffer.byteLength(output) > 32 * 1024 ** 2) {
      output = outputPreview(output)
      failure = new ScriptExecutionError('SCRIPT_OUTPUT_LIMIT', 'Verifier output exceeds limit', { script })
      stop()
    }
  })
  child.stderr.on('data', chunk => { stderr = Buffer.concat([Buffer.from(stderr), Buffer.from(chunk)]).subarray(-4096).toString('utf8') })
  signal?.addEventListener('abort', stop, { once: true })
  const timer = setTimeout(() => { failure = new ScriptExecutionError('SCRIPT_TIMEOUT', 'Verifier timed out', { script }); stop() }, 900_000)
  try {
    if (signal?.aborted) stop()
    await new Promise<void>((done, reject) => {
      child.once('error', error => reject(new ScriptExecutionError('SCRIPT_START_FAILED', `Could not start verifier: ${error.message}`, { script, stderr, outputPreview: outputPreview(output) })))
      child.once('close', (code, exitSignal) => {
        const diagnostics = { script, exitCode: code, signal: exitSignal, stderr, outputPreview: outputPreview(output) }
        if (failure instanceof ScriptExecutionError) Object.assign(failure.diagnostics, diagnostics)
        code === 0 ? done() : reject(failure ?? new ScriptExecutionError('SCRIPT_EXIT_FAILED', `Verifier exited (${code ?? exitSignal})`, diagnostics))
      })
    })
    signal?.throwIfAborted()
    if (failure) throw failure
    return output
  } finally {
    clearTimeout(timer)
    if (escalation) clearTimeout(escalation)
    signal?.removeEventListener('abort', stop)
  }
}
