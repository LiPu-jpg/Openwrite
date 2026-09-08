import { spawn } from 'node:child_process'

/** Execute without blocking the host event loop; cancellation owns only this process tree. */
export async function runOwnedScript(script: string, input: string, signal?: AbortSignal): Promise<string> {
  signal?.throwIfAborted()
  const js = /\.(?:c|m)?js$/.test(script)
  const child = spawn(js ? process.execPath : script, js ? [script, input] : [input], {
    detached: process.platform !== 'win32', windowsHide: true, stdio: ['ignore', 'pipe', 'pipe'],
  })
  let output = ''
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
    if (Buffer.byteLength(output) > 32 * 1024 ** 2) { failure = new Error('verifier output exceeds limit'); stop() }
  })
  child.stderr.resume()
  signal?.addEventListener('abort', stop, { once: true })
  const timer = setTimeout(() => { failure = new Error('verifier timeout'); stop() }, 900_000)
  try {
    if (signal?.aborted) stop()
    await new Promise<void>((done, reject) => {
      child.once('error', reject)
      child.once('close', code => code === 0 ? done() : reject(failure ?? new Error(`verifier exited (${code})`)))
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
