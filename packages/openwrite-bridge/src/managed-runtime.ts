import { createHash, randomBytes, randomUUID } from 'node:crypto'
import { createReadStream } from 'node:fs'
import { chmod, mkdir, open, readFile, rename, rm, writeFile } from 'node:fs/promises'
import { dirname, isAbsolute, join, resolve, sep } from 'node:path'
import { spawn, type ChildProcess, type SpawnOptions } from 'node:child_process'
import { setTimeout as delay } from 'node:timers/promises'
import { createInterface } from 'node:readline'
import { x as untar } from 'tar'
import { unzipSync } from 'fflate'
import { lock as acquireLock } from 'proper-lockfile'

interface Download { url: string; sha256: string; executable: string }
export interface RuntimeManifest {
  schema: number; dsh: string; python_version: string; core_version: string; contract_version: number
  platforms: Record<string, { uv: Download; python: Download }>
  wheel: { file: string; sha256: string }
  requirements: { file: string; sha256: string }
  dependency_wheels?: Array<{ file: string; sha256: string }>
}
export type RuntimePhase = 'idle' | 'waiting' | 'downloading' | 'installing' | 'starting' | 'ready'
  | 'recovering' | 'cancelled' | 'error' | 'stopped' | 'uninstalled'
export interface RuntimeStatus {
  phase: RuntimePhase
  message: string; downloadedBytes?: number; totalBytes?: number; error?: string
}
export interface BackendConnection { baseUrl: string; token?: string }
export type SpawnFn = (command: string, args: readonly string[], options: SpawnOptions) => ChildProcess
export interface RuntimeOptions {
  spawn?: SpawnFn
  delay?: typeof delay
  restartLimit?: number
  backoffMs?: number[]
}

export const DEFAULT_RESTART_LIMIT = 5
export const DEFAULT_BACKOFF_MS = [1_000, 2_000, 4_000, 8_000, 16_000]

const CREDENTIAL_ENV = /(?:API[_-]?KEY|ACCESS[_-]?TOKEN|SECRET|PASSWORD|CREDENTIAL|AUTHORIZATION)/i
const ALLOWED_ENV = new Set([
  'PATH', 'Path', 'PATHEXT',
  'HOME', 'USER', 'USERNAME', 'LOGNAME',
  'USERPROFILE', 'HOMEDRIVE', 'HOMEPATH', 'APPDATA', 'LOCALAPPDATA',
  'TEMP', 'TMP', 'TMPDIR',
  'SYSTEMROOT', 'SystemRoot', 'WINDIR', 'windir', 'COMSPEC', 'ComSpec',
  'SystemDrive', 'PROGRAMDATA', 'ProgramData', 'ProgramFiles', 'PROGRAMFILES', 'ProgramFiles(x86)',
  'NUMBER_OF_PROCESSORS', 'PROCESSOR_ARCHITECTURE', 'PROCESSOR_IDENTIFIER', 'OS',
  'LANG', 'LC_ALL', 'LC_CTYPE', 'LC_MESSAGES', 'LANGUAGE', 'TZ',
  'HTTP_PROXY', 'HTTPS_PROXY', 'NO_PROXY', 'ALL_PROXY', 'http_proxy', 'https_proxy', 'no_proxy', 'all_proxy',
  'SSL_CERT_FILE', 'SSL_CERT_DIR', 'REQUESTS_CA_BUNDLE', 'CURL_CA_BUNDLE',
])

export async function sha256(file: string): Promise<string> {
  const hash = createHash('sha256')
  for await (const chunk of createReadStream(file)) hash.update(chunk)
  return hash.digest('hex')
}

/** Diagnostics must not echo provider credentials or authenticated download URLs. */
export function sanitizeDiagnostic(message: string): string {
  return message.replace(/(https?:\/\/)[^\s/@]+:[^\s/@]+@/gi, '$1[redacted]@')
    .replace(/([?&](?:token|key|signature|credential|password|secret)=)[^&\s]+/gi, '$1[redacted]')
    .replace(/((?:api[_-]?key|authorization|password|secret|token)\s*[:=]\s*)[^\s,;]+/gi, '$1[redacted]')
    .replace(/\b[a-f0-9]{32,}\b/gi, '[redacted]')
}

/** Windows needs SystemRoot/PATH to start; proxy and CA vars stay when set. Credential names never copy. */
export function buildChildEnv(source: NodeJS.ProcessEnv, extra: Record<string, string | undefined> = {}): NodeJS.ProcessEnv {
  const env: NodeJS.ProcessEnv = {}
  for (const [key, value] of Object.entries(source)) {
    if (value === undefined || CREDENTIAL_ENV.test(key)) continue
    const allowed = ALLOWED_ENV.has(key)
      || (process.platform === 'win32' && [...ALLOWED_ENV].some(name => name.toLowerCase() === key.toLowerCase()))
    if (allowed) env[key] = value
  }
  for (const [key, value] of Object.entries(extra)) {
    if (value === undefined || CREDENTIAL_ENV.test(key)) continue
    env[key] = value
  }
  return env
}

/** Stop only a child we spawned. POSIX groups and Windows trees include grandchildren. */
export async function stopOwnedProcess(child: ChildProcess): Promise<void> {
  if (!child.pid || child.exitCode !== null || child.signalCode !== null) return
  const exited = new Promise<void>(done => child.once('exit', () => done()))
  if (process.platform === 'win32') {
    await new Promise<void>(done => {
      const killer = spawn('taskkill', ['/pid', String(child.pid), '/T', '/F'], { windowsHide: true })
      killer.once('error', () => { child.kill(); done() })
      killer.once('exit', () => done())
    })
  } else {
    try { process.kill(-child.pid, 'SIGTERM') } catch { child.kill('SIGTERM') }
    await Promise.race([exited, delay(3000)])
    if (child.exitCode === null && child.signalCode === null) {
      try { process.kill(-child.pid, 'SIGKILL') } catch { child.kill('SIGKILL') }
    }
  }
  await exited
}

/** All artifacts and children belong to this instance; author files never enter this tree. */
export class ManagedRuntime {
  private state: RuntimeStatus = { phase: 'idle', message: '首次使用将准备写作环境' }
  private pending?: Promise<BackendConnection>
  private controller?: AbortController
  private child?: ChildProcess
  private connection?: BackendConnection
  private closed = false
  private allowRevive = true
  private generation = 0
  private restartAttempts = 0
  private recovered = false
  private readonly spawnFn: SpawnFn
  private readonly wait: typeof delay
  private readonly restartLimit: number
  private readonly backoffMs: number[]

  constructor(readonly root: string, readonly artifacts: string, options: RuntimeOptions = {}) {
    this.spawnFn = options.spawn ?? spawn
    this.wait = options.delay ?? delay
    this.restartLimit = options.restartLimit ?? DEFAULT_RESTART_LIMIT
    this.backoffMs = options.backoffMs ?? DEFAULT_BACKOFF_MS
  }
  status(): RuntimeStatus { return { ...this.state } }
  private update(phase: RuntimeStatus['phase'], message: string, extra: Partial<RuntimeStatus> = {}): void {
    this.state = { phase, message, ...extra }
  }

  ensure(): Promise<BackendConnection> {
    if (this.closed) return Promise.reject(new Error('OpenWrite 已卸载'))
    if (this.connection) return Promise.resolve(this.connection)
    if (this.pending) return this.pending
    this.allowRevive = true
    if (this.state.phase === 'error' || this.state.phase === 'cancelled' || this.state.phase === 'stopped') {
      this.restartAttempts = 0
      this.recovered = false
    }
    const controller = new AbortController()
    this.controller = controller
    this.pending = this.prepare(controller.signal).catch(error => {
      this.state = { phase: controller.signal.aborted ? 'cancelled' : 'error',
        message: controller.signal.aborted ? '准备已取消，可重试' : '写作环境未就绪，可重试',
        error: controller.signal.aborted ? undefined : sanitizeDiagnostic(String(error instanceof Error ? error.message : error)) }
      throw error
    }).finally(() => { this.pending = undefined; this.controller = undefined })
    return this.pending
  }
  async cancel(): Promise<void> {
    this.allowRevive = false
    this.controller?.abort()
    await this.pending?.catch(() => {})
  }
  async dispose(): Promise<void> {
    this.closed = true
    this.allowRevive = false
    this.generation += 1
    await this.cancel()
    if (this.child) {
      this.child.stdin?.end()
      await stopOwnedProcess(this.child)
      this.child = undefined
    }
    this.connection = undefined
    this.update('uninstalled', 'OpenWrite 已卸载，作品和配置已保留')
  }

  private exitDiagnostic(code: number | null, signalName: NodeJS.Signals | null, stderr = ''): string {
    return sanitizeDiagnostic(`exit ${code ?? 'none'} signal ${signalName ?? 'none'}${stderr ? `: ${stderr}` : ''}`)
  }

  private handleReadyExit(generation: number, child: ChildProcess, code: number | null, signalName: NodeJS.Signals | null, stderr: string): void {
    if (this.generation !== generation) return
    if (this.child === child) this.child = undefined
    this.connection = undefined
    if (this.closed) return
    const error = this.exitDiagnostic(code, signalName, stderr)
    if (!this.allowRevive) {
      this.update('cancelled', '准备已取消，可重试', { error })
      return
    }
    this.restartAttempts += 1
    if (this.restartAttempts > this.restartLimit) {
      this.allowRevive = false
      this.update('error', '写作后端多次异常退出，已停止自动恢复，可手动重试', { error })
      return
    }
    this.recovered = true
    this.update('recovering', `写作后端异常退出，正在恢复（${this.restartAttempts}/${this.restartLimit}）`, { error })
    void this.queueRestart()
  }

  private queueRestart(): Promise<BackendConnection> {
    if (this.pending) return this.pending
    const controller = new AbortController()
    this.controller = controller
    const wait = this.backoffMs[Math.min(this.restartAttempts - 1, this.backoffMs.length - 1)] ?? 1_000
    this.pending = this.wait(wait, undefined, { signal: controller.signal }).then(() => this.prepare(controller.signal)).catch(error => {
      this.state = { phase: controller.signal.aborted ? 'cancelled' : 'error',
        message: controller.signal.aborted ? '准备已取消，可重试' : '写作环境未就绪，可重试',
        error: controller.signal.aborted ? undefined : sanitizeDiagnostic(String(error instanceof Error ? error.message : error)) }
      throw error
    }).finally(() => { this.pending = undefined; this.controller = undefined })
    return this.pending
  }

  private async download(item: Download, signal: AbortSignal): Promise<string> {
    const cache = join(this.root, 'cache')
    await mkdir(cache, { recursive: true })
    const destination = join(cache, item.sha256)
    if (await sha256(destination).catch(() => '') === item.sha256) return destination
    const partial = destination + '.' + randomUUID() + '.partial'
    this.update('downloading', '正在下载并校验写作环境')
    try {
      const response = await fetch(item.url, { signal: AbortSignal.any([signal, AbortSignal.timeout(600_000)]) })
      if (!response.ok || !response.body) throw new Error(`下载失败：HTTP ${response.status}`)
      const size = Number(response.headers.get('content-length')) || undefined
      const file = await open(partial, 'wx', 0o600)
      let received = 0
      try {
        for await (const chunk of response.body) {
          signal.throwIfAborted()
          received += chunk.length
          if (received > 1024 ** 3) throw new Error('下载超过允许大小')
          await file.write(chunk)
          this.state = { phase: 'downloading', message: '正在下载并校验写作环境', downloadedBytes: received, totalBytes: size }
        }
      } finally { await file.close() }
      if (await sha256(partial) !== item.sha256) throw new Error('下载校验失败，请重试')
      await rename(partial, destination)
      return destination
    } finally { await rm(partial, { force: true }) }
  }

  private async extract(item: Download, signal: AbortSignal): Promise<string> {
    const dir = join(this.root, 'binaries', item.sha256)
    const executable = join(dir, item.executable)
    const marker = join(dir, '.complete')
    if (await readFile(marker, 'utf8').catch(() => '') === item.sha256) return executable
    const archive = await this.download(item, signal)
    await rm(dir, { recursive: true, force: true })
    await mkdir(dir, { recursive: true })
    if (item.url.endsWith('.zip')) {
      for (const [name, bytes] of Object.entries(unzipSync(await readFile(archive)))) {
        const target = resolve(dir, name)
        if (isAbsolute(name) || !target.startsWith(dir + sep)) throw new Error('压缩包路径无效')
        if (name.endsWith('/')) await mkdir(target, { recursive: true })
        else { await mkdir(dirname(target), { recursive: true }); await writeFile(target, bytes) }
      }
    } else await untar({ file: archive, cwd: dir, strict: true, preservePaths: false })
    signal.throwIfAborted()
    if (process.platform !== 'win32') await chmod(executable, 0o755)
    await writeFile(marker, item.sha256)
    return executable
  }

  private async command(executable: string, args: string[], signal: AbortSignal): Promise<void> {
    signal.throwIfAborted()
    const child = this.spawnFn(executable, args, { cwd: this.root, detached: process.platform !== 'win32', windowsHide: true,
      env: buildChildEnv(process.env, { UV_CACHE_DIR: join(this.root, 'cache', 'uv'), UV_PYTHON_DOWNLOADS: 'never', UV_NO_CONFIG: '1' }),
      stdio: ['ignore', 'ignore', 'pipe'] })
    let failure = ''
    child.stderr?.on('data', bytes => { failure = (failure + String(bytes)).slice(-2000) })
    const abort = () => { void stopOwnedProcess(child) }
    signal.addEventListener('abort', abort, { once: true })
    try {
      await new Promise<void>((done, reject) => {
        child.once('error', reject)
        child.once('exit', code => code === 0 ? done() : reject(new Error(`环境准备失败 (${code})：${failure}`)))
      })
      signal.throwIfAborted()
    } finally { signal.removeEventListener('abort', abort) }
  }

  private async lock(signal: AbortSignal): Promise<() => Promise<void>> {
    for (;;) {
      signal.throwIfAborted()
      try {
        return await acquireLock(this.root, {
          realpath: false, stale: 30_000, update: 5_000, retries: 0,
          onCompromised: () => this.controller?.abort(),
        })
      } catch (error) {
        if ((error as NodeJS.ErrnoException).code !== 'ELOCKED') throw error
        this.update('waiting', '另一个 OpenWrite 正在准备环境，等待完成')
        await this.wait(250, undefined, { signal })
      }
    }
  }

  private async prepare(signal: AbortSignal): Promise<BackendConnection> {
    const manifest = JSON.parse(await readFile(join(this.artifacts, 'runtime-manifest.json'), 'utf8')) as RuntimeManifest
    const platform = manifest.platforms[`${process.platform}-${process.arch}`]
    if (!platform) throw new Error(`暂不支持 ${process.platform}/${process.arch}`)
    if (!manifest.wheel || !manifest.requirements) throw new Error('发布包缺少 Core 或依赖校验清单')
    const wheel = join(this.artifacts, manifest.wheel.file)
    const requirements = join(this.artifacts, manifest.requirements.file)
    if (await sha256(wheel) !== manifest.wheel.sha256 || await sha256(requirements) !== manifest.requirements.sha256) {
      throw new Error('发布包校验失败，请重新安装')
    }
    for (const artifact of manifest.dependency_wheels ?? []) {
      if (await sha256(join(this.artifacts, artifact.file)) !== artifact.sha256) throw new Error('平台依赖校验失败，请重新安装')
    }
    await mkdir(this.root, { recursive: true, mode: 0o700 })
    const unlock = await this.lock(signal)
    let python: string
    try {
      const generation = createHash('sha256').update(JSON.stringify(manifest)).digest('hex').slice(0, 24)
      const destination = join(this.root, 'environments', generation)
      python = join(destination, process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python')
      if (await readFile(join(destination, '.complete'), 'utf8').catch(() => '') !== generation) {
        const uv = await this.extract(platform.uv, signal)
        const basePython = await this.extract(platform.python, signal)
        this.update('installing', '正在安装隔离依赖，首次使用可能需要几分钟')
        await rm(destination, { recursive: true, force: true })
        try {
          await this.command(uv, ['venv', '--python', basePython, destination], signal)
          await this.command(uv, ['pip', 'sync', '--python', python, '--require-hashes', '--only-binary', ':all:',
            ...(manifest.dependency_wheels?.length ? ['--find-links', join(this.artifacts, 'wheels')] : []), requirements], signal)
          await this.command(uv, ['pip', 'install', '--python', python, '--no-deps', wheel], signal)
          await this.command(python, ['-I', '-c', 'from tools.studio_http import health_payload; from tools.studio import create_server; assert health_payload()["contract_version"] == 1'], signal)
          await writeFile(join(destination, '.complete'), generation)
        } catch (error) { await rm(destination, { recursive: true, force: true }); throw error }
      }
      signal.throwIfAborted()
      this.update(this.recovered ? 'recovering' : 'starting', this.recovered ? '正在恢复写作环境' : '正在启动写作环境')
      const connection = await this.start(python, manifest, signal)
      const pending = join(this.root, 'active.' + randomUUID() + '.json')
      try {
        await writeFile(pending, JSON.stringify({ generation, coreVersion: manifest.core_version }))
        await rename(pending, join(this.root, 'active.json'))
      } catch (error) {
        this.connection = undefined
        if (this.child) await stopOwnedProcess(this.child)
        throw error
      } finally { await rm(pending, { force: true }) }
      return connection
    } finally { await unlock() }
  }

  private async start(python: string, manifest: RuntimeManifest, signal: AbortSignal): Promise<BackendConnection> {
    signal.throwIfAborted()
    const token = randomBytes(32).toString('hex')
    const generation = ++this.generation
    // Windows defaults redirected stdout to its legacy locale encoding. Core
    // initialization logs and manuscript paths are Unicode; -I ignores Python
    // environment options, so set UTF-8 explicitly on the interpreter as well.
    const child = this.spawnFn(python, ['-I', '-X', 'utf8', '-u', '-m', 'tools.managed_runtime'], {
      cwd: this.root, detached: process.platform !== 'win32', windowsHide: true, stdio: ['pipe', 'pipe', 'pipe'],
      env: buildChildEnv(process.env, { PYTHONNOUSERSITE: '1', PYTHONUTF8: '1' }),
    })
    this.child = child
    let stderrTail = ''
    child.stderr?.on('data', bytes => { stderrTail = (stderrTail + String(bytes)).slice(-500) })
    const lines = createInterface({ input: child.stdout! })
    let timer: ReturnType<typeof setTimeout> | undefined
    let started = false
    child.once('exit', (code, signalName) => {
      if (!started) return
      this.handleReadyExit(generation, child, code, signalName, stderrTail)
    })
    try {
      const ready = new Promise<number>((done, reject) => {
        child.once('error', reject)
        child.once('exit', (code, signalName) => {
          if (started) return
          reject(new Error(`写作后端在启动时退出 (${code ?? 'none'}/${signalName ?? 'none'})`))
        })
        timer = setTimeout(() => reject(new Error('写作后端启动超时')), 120_000)
        lines.on('line', line => {
          try {
            const message = JSON.parse(line)
            if (Number.isInteger(message.port) && message.port > 0 && message.port < 65536) done(message.port)
          } catch { /* non-protocol startup logging */ }
        })
      })
      const abort = () => { void stopOwnedProcess(child) }
      signal.addEventListener('abort', abort, { once: true })
      let port: number
      try {
        child.stdin!.write(JSON.stringify({ token, state_dir: join(this.root, 'state') }) + '\n')
        port = await ready
      } finally { signal.removeEventListener('abort', abort) }
      signal.throwIfAborted()
      const connection = { baseUrl: `http://127.0.0.1:${port}`, token }
      const health = await fetch(connection.baseUrl + '/api/health', {
        headers: { Authorization: `Bearer ${token}` }, signal: AbortSignal.any([signal, AbortSignal.timeout(10_000)]),
      })
      const result = await health.json() as Record<string, unknown>
      if (!health.ok || result.core_version !== manifest.core_version || result.contract_version !== manifest.contract_version) {
        throw new Error('写作后端版本或接口不匹配，请重新安装')
      }
      this.connection = connection
      started = true
      if (!this.recovered) this.restartAttempts = 0
      this.update('ready', this.recovered
        ? '写作环境已恢复；进行中的写作或评审任务不会自动重试'
        : '写作环境已就绪')
      return connection
    } catch (error) {
      if (this.generation === generation) {
        this.generation += 1
        this.connection = undefined
        if (this.child === child) this.child = undefined
      }
      await stopOwnedProcess(child); throw error
    }
    finally { if (timer) clearTimeout(timer); lines.close(); child.stdout?.resume() }
  }
}
