/** Sandboxed input capture and durable DoG records. */

import { createHash } from 'node:crypto'
import { randomUUID } from 'node:crypto'
import { c as packTar } from 'tar'
import { readdirSync } from 'node:fs'
import { appendFile, lstat, mkdir, readFile, readdir, realpath, rename, stat, writeFile } from 'node:fs/promises'
import { dirname, isAbsolute, join, relative, resolve, sep } from 'node:path'
import type {
 AcceptancePlan,
 CompiledGraph,
 DogGraphInput,
 DogRun,
 GoalRuntimeEvent,
 CapturedInput,
 VerificationRecord,
} from './model.ts'
import { canonicalJson, sha256Json } from './json.ts'
import { withFileLock } from './lockfile.ts'
import { schemaErrorText, type SchemaSet } from './schema.ts'

export interface CapturedInputFile {
 readonly input: CapturedInput
}

export class DogRepository {
 readonly rootPath: string
 private readonly runMutationTails = new Map<string, Promise<void>>()
 private readonly schema: SchemaSet | undefined

 constructor(rootPath: string, schema: SchemaSet | undefined = undefined) {
  this.rootPath = rootPath
  this.schema = schema
 }

 /** Create the repository directory layout. */
 async initialize(): Promise<void> {
  await Promise.all([
   mkdir(join(this.rootPath, 'graphs'), { recursive: true }),
   mkdir(join(this.rootPath, 'graph-index'), { recursive: true }),
   mkdir(join(this.rootPath, 'runs'), { recursive: true }),
   mkdir(join(this.rootPath, 'verifications'), { recursive: true }),
   mkdir(join(this.rootPath, 'runtime-events'), { recursive: true }),
   mkdir(join(this.rootPath, 'artifacts'), { recursive: true }),
   mkdir(join(this.rootPath, 'locks'), { recursive: true }),
  ])
 }

 /** Persist one immutable compiled graph revision and its ID index. */
 async saveGraph(compiled: CompiledGraph): Promise<void> {
  await this.initialize()
  await withFileLock(join(this.rootPath, 'locks', `graph-${compiled.graphDigest}.lock`), async () => {
   const record = {
    schemaVersion: '0.2',
    graphDigest: compiled.graphDigest,
    input: compiled.input,
    acceptancePlans: compiled.acceptancePlans,
   }
   await atomicWriteJson(join(this.rootPath, 'graphs', `${compiled.graphDigest}.json`), record)
   await atomicWriteJson(join(this.rootPath, 'graph-index', `${safeKey(compiled.input.id)}.json`), {
    graphId: compiled.input.id,
    graphDigest: compiled.graphDigest,
   })
  })
 }

 /** Load the latest graph revision for a graph ID. */
 async loadGraph(graphId: string): Promise<CompiledGraph> {
  const index = await readJson<{ graphId: string; graphDigest: string }>(
   join(this.rootPath, 'graph-index', `${safeKey(graphId)}.json`),
  )
  if (index.graphId !== graphId || !isDigest(index.graphDigest)) {
   throw new Error(`invalid graph index for ${graphId}`)
  }
  return readCompiledGraph(this.rootPath, index.graphDigest)
 }

 /** Enumerate immutable graph revisions. Pre-v0.2 records (no grounding/gmDigest contract) are skipped, not deleted. */
 async listGraphs(): Promise<readonly CompiledGraph[]> {
  await this.initialize()
  const entries = await readdir(join(this.rootPath, 'graphs'), { withFileTypes: true })
  const graphs: CompiledGraph[] = []
  for (const entry of entries) {
   if (!entry.isFile() || !/^[a-f0-9]{64}\.json$/u.test(entry.name)) continue
   try {
    graphs.push(await readCompiledGraph(this.rootPath, entry.name.slice(0, -'.json'.length)))
   } catch (error) {
    if (!String(error instanceof Error ? error.message : error).startsWith('invalid persisted graph record')) throw error
   }
  }
  return graphs.sort((left, right) => {
   const byId = left.input.id.localeCompare(right.input.id)
   return byId === 0 ? left.graphDigest.localeCompare(right.graphDigest) : byId
  })
 }

 /** Persist a run snapshot. */
 async saveRun(run: DogRun): Promise<void> {
  await this.initialize()
  await withFileLock(join(this.rootPath, 'locks', `run-${safeKey(run.runId)}.lock`), () =>
   atomicWriteJson(join(this.rootPath, 'runs', `${safeKey(run.runId)}.json`), run),
  )
 }

 /** Atomically read, transform, and replace one run within this repository process. */
 async updateRun(runId: string, update: (run: DogRun) => DogRun): Promise<DogRun> {
  return this.withRunMutation(runId, async () => {
   const current = await this.loadRun(runId)
   const next = update(current)
   if (next.runId !== current.runId || next.graphId !== current.graphId || next.graphDigest !== current.graphDigest) {
    throw new Error(`run update cannot change identity for ${runId}`)
   }
   // Save directly: the mutation lock (both process-level and cross-process)
   // is already held here, so re-entering saveRun would self-deadlock.
   await atomicWriteJson(join(this.rootPath, 'runs', `${safeKey(runId)}.json`), next)
   return next
  })
 }

 private async withRunMutation<T>(runId: string, action: () => Promise<T>): Promise<T> {
  const previous = this.runMutationTails.get(runId) ?? Promise.resolve()
  let release!: () => void
  const gate = new Promise<void>(resolve => { release = resolve })
  const tail = previous.then(() => gate, () => gate)
  this.runMutationTails.set(runId, tail)
  await previous.catch(() => undefined)
  try {
   return await withFileLock(join(this.rootPath, 'locks', `run-${safeKey(runId)}.lock`), action)
  } finally {
   release()
   if (this.runMutationTails.get(runId) === tail) this.runMutationTails.delete(runId)
  }
 }

 /** Load one run snapshot, fail-closed against the run schema. */
 async loadRun(runId: string): Promise<DogRun> {
  const run = await readJson<DogRun>(join(this.rootPath, 'runs', `${safeKey(runId)}.json`))
  if (this.schema !== undefined && !this.schema.validateRun(run)) {
   throw new Error(`run record does not validate: ${schemaErrorText(this.schema.validateRun).join('; ')}`)
  }
  return run
 }

 /**
  * Load the most recently updated non-running run for a graph ID
  * (revalidate_select input). Any terminal record may carry verification
  * settlements worth inheriting — including orphaned runs that a host restart
  * left running and that recovery later invalidated or cancelled.
  */
 async loadLatestSettledRun(graphId: string): Promise<DogRun | undefined> {
  const runs = await this.listRuns()
  return runs.find(run => run.graphId === graphId && run.state !== 'running')
 }

 /** Enumerate persisted run snapshots, newest update first. Pre-v0.2 records are skipped. */
 async listRuns(): Promise<readonly DogRun[]> {
  await this.initialize()
  const entries = await readdir(join(this.rootPath, 'runs'), { withFileTypes: true })
  const runs: DogRun[] = []
  for (const entry of entries) {
   if (!entry.isFile() || !entry.name.endsWith('.json')) continue
   const key = entry.name.slice(0, -'.json'.length)
   if (!/^[a-f0-9]{64}$/u.test(key)) continue
   try {
    const record = readJson<DogRun>(join(this.rootPath, 'runs', `${key}.json`))
    const run = await record
    if (this.schema !== undefined && !this.schema.validateRun(run)) continue
    if (typeof run.runId !== 'string' || run.runId.length === 0 || entry.name !== `${safeKey(run.runId)}.json`) continue
    if (!isDigest(run.graphDigest)) continue
    runs.push(run)
   } catch {
    continue
   }
  }
  return runs.sort((left, right) => {
   const byTime = right.updatedAt.localeCompare(left.updatedAt)
   return byTime === 0 ? left.runId.localeCompare(right.runId) : byTime
  })
 }

 /**
   * Cancel every persisted run still in `running` state. Called at host boot
   * (before any engine instance exists), so runs from a killed/restarted host
   * surface as cancelled instead of frozen "running" forever. Their settled
   * leaves stay inheritable by the next run of the same graph.
   */
 async markOrphanedRunningRuns(nowIso: string): Promise<number> {
  const runs = await this.listRuns()
  let marked = 0
  for (const prior of runs) {
   const orphanedGoals = Object.values(prior.goals).some(goal => goal.state === 'pending' || goal.state === 'running')
   if (prior.state !== 'running' && !orphanedGoals) continue
   await this.updateRun(prior.runId, current => ({
    ...current,
    ...(current.state === 'running'
     ? {
      state: 'cancelled' as const,
      rootState: 'cancelled' as const,
      runtimeWarning: `orphaned by host restart (last update ${prior.updatedAt})`,
     }
     : {}),
    goals: Object.fromEntries(
     Object.entries(current.goals).map(([goalId, goal]) =>
      goal.state === 'pending' || goal.state === 'running'
       ? [goalId, { ...goal, state: 'cancelled' as const }]
       : [goalId, goal],
     ),
    ),
    updatedAt: nowIso,
   }))
   marked++
  }
  return marked
 }

 /** Append one verification record without rewriting prior records. */
 async appendVerification(record: VerificationRecord): Promise<void> {
  await this.initialize()
  const path = join(this.rootPath, 'verifications', `${safeKey(record.runId)}.jsonl`)
  await appendFile(path, `${canonicalJson(record)}\n`, { encoding: 'utf8', flag: 'a' })
 }

 /** Append diagnostic runtime context to the selected goal shard, separately from trusted verifier evidence. */
 async appendRuntimeEvent(event: GoalRuntimeEvent): Promise<void> {
  await this.initialize()
  const path = join(this.rootPath, 'runtime-events', `${safeKey(event.runId)}-${safeKey(event.goalId)}.jsonl`)
  await appendFile(path, `${canonicalJson(event)}\n`, { encoding: 'utf8', flag: 'a' })
 }

 /** Load one goal's validated event shard. A torn final line is ignored. */
 async loadGoalRuntimeEvents(runId: string, goalId: string): Promise<readonly GoalRuntimeEvent[]> {
  const path = join(this.rootPath, 'runtime-events', `${safeKey(runId)}-${safeKey(goalId)}.jsonl`)
  let source: string
  try {
   source = await readFile(path, 'utf8')
  } catch (error) {
   if (isMissing(error)) return []
   throw error
  }

  const complete = source.endsWith('\n') ? source : source.slice(0, source.lastIndexOf('\n') + 1)
  return complete.split('\n')
   .filter(line => line.length > 0)
   .map((line, index) => parseRuntimeEvent(JSON.parse(line) as unknown, runId, goalId, index))
 }

 /** Persist the verbatim verifier settlement text (survives workspace cleanup). */
 async saveSettlement(runId: string, goalId: string, content: string): Promise<void> {
  await this.initialize()
  await atomicWriteJson(join(this.rootPath, 'settlements', `${safeKey(runId)}-${safeKey(goalId)}.json`), {
   runId,
   goalId,
   savedAt: new Date().toISOString(),
   content,
  })
 }

 /** Store captured input bytes and its metadata manifest under content identity. */
 async putSandboxFile(input: CapturedInput, bytes: Uint8Array | undefined): Promise<void> {
  await this.initialize()
  const key = capturedKey(input.digest)
  if (bytes !== undefined) {
   await atomicWrite(join(this.rootPath, 'artifacts', `${key}.bin`), bytes)
  }
  await atomicWriteJson(join(this.rootPath, 'artifacts', `${key}.json`), input)
 }

 /** Read and re-hash a captured input named by a verification plan. */
 async readCapturedFile(input: CapturedInput): Promise<Uint8Array> {
  if (!input.exists) throw new Error(`captured input ${input.digest} represents a missing file`)
  const bytes = await readFile(join(this.rootPath, 'artifacts', `${capturedKey(input.digest)}.bin`))
  const digest = createHash('sha256').update(bytes).digest('hex')
  if (digest !== input.sha256 || bytes.byteLength !== input.byteLength) {
   throw new Error(`captured input integrity mismatch for ${input.digest}`)
  }
  return bytes
 }

 /** InputReader contract: read one captured input. */
 async read(input: CapturedInput): Promise<Uint8Array> {
  return this.readCapturedFile(input)
 }

 /** Copy a captured input into one run workspace (or resolve to the workspace dir). */
 async copyCapturedInput(input: CapturedInput | undefined, workspacePath: string): Promise<string> {
  if (input === undefined) return workspacePath
  const bytes = await this.readCapturedFile(input)
  const target = join(workspacePath, input.path)
  await mkdir(dirname(target), { recursive: true })
  await writeFile(target, bytes)
  return target
 }
}

/** Resolve one workspace-relative path to an absolute path, never accepting escapes. */
export async function resolveWorkspacePath(workspaceRoot: string, relPath: string): Promise<string> {
 if (!isAbsolute(workspaceRoot)) throw new Error('workspaceRoot must be absolute')
 if (relPath === '') throw new Error('empty workspace path has no single file to resolve')
 if (isAbsolute(relPath)) throw new Error('workspace path must be relative')
 const rootPath = resolve(workspaceRoot)
 const lexicalCandidate = resolve(rootPath, relPath)
 const lexicalRelative = relative(rootPath, lexicalCandidate)
 if (!isWithinRoot(lexicalRelative)) throw new Error(`workspace path ${relPath} escapes its configured root`)
 const rootStat = await stat(rootPath)
 if (!rootStat.isDirectory()) throw new Error(`workspace root ${workspaceRoot} is not a directory`)
 const canonicalRoot = await realpath(rootPath)
 return resolveBoundPath(canonicalRoot, lexicalRelative)
}

/** Capture one sandbox file into the repository's content-addressed store. */
export async function captureWorkspaceFile(
 workspaceRoot: string,
 relPath: string,
 maxBytes: number,
 repository: DogRepository,
): Promise<CapturedInputFile> {
 try {
  const absolutePath = await resolveWorkspacePath(workspaceRoot, relPath)
  const metadata = await stat(absolutePath)
  if (!metadata.isFile()) throw new Error(`sandbox path ${relPath} is not a regular file`)
  if (metadata.size > maxBytes) throw new Error(`sandbox file ${relPath} exceeds ${maxBytes} bytes`)
  const bytes = await readFile(absolutePath)
  if (bytes.byteLength > maxBytes) throw new Error(`sandbox file ${relPath} exceeds ${maxBytes} bytes`)
  const sha256 = createHash('sha256').update(bytes).digest('hex')
  const input: CapturedInput = {
   path: relPath,
   digest: `sha256:${sha256}`,
   exists: true,
   byteLength: bytes.byteLength,
   sha256,
  }
  await repository.putSandboxFile(input, bytes)
  return { input }
 } catch (error) {
  if (!isMissing(error)) throw error
  const missingDigest = sha256Json({ path: relPath })
  const input: CapturedInput = {
   path: relPath,
   digest: `missing:${missingDigest}`,
   exists: false,
   byteLength: 0,
   sha256: '',
  }
  await repository.putSandboxFile(input, undefined)
  return { input }
 }
}

/**
 * Capture one target: a single file, or a directory packed into a .tar
 * (relative structure preserved). Roots are tried in order — the invoking
 * session cwd first (which is where the user is actually working), then the
 * configured workspace root as fallback. A non-missing error (escape, not a
 * regular file…) always aborts; only a target absent from every root settles
 * as `missing`.
 */
export async function captureWorkspaceTarget(
 captureRoots: readonly string[],
 target: string,
 maxBytes: number,
 repository: DogRepository,
): Promise<CapturedInputFile> {
 for (const root of captureRoots) {
  try {
   const absolutePath = await resolveWorkspacePath(root, target)
   const metadata = await stat(absolutePath)
   let bytes: Uint8Array
   let packed = false
   if (metadata.isDirectory()) {
    const rootPath = resolve(root)
    assertTreeSafe(rootPath, absolutePath)
    const chunks: Buffer[] = []
    let length = 0
    for await (const chunk of packTar({ cwd: rootPath, portable: true }, [target])) {
     length += chunk.length
     if (length > maxBytes) throw new Error(`target ${target} exceeds ${maxBytes} bytes`)
     chunks.push(chunk)
    }
    bytes = Buffer.concat(chunks)
    packed = true
   } else if (metadata.isFile()) {
    bytes = await readFile(absolutePath)
   } else {
    throw new Error(`target ${target} is not a regular file or directory`)
   }
   if (bytes.byteLength > maxBytes) throw new Error(`target ${target} exceeds ${maxBytes} bytes`)
   const sha256 = createHash('sha256').update(bytes).digest('hex')
   const input: CapturedInput = {
    path: target,
    digest: `sha256:${sha256}`,
    exists: true,
    byteLength: bytes.byteLength,
    sha256,
    ...(packed ? { packed: true } : {}),
   }
   await repository.putSandboxFile(input, bytes)
   return { input }
  } catch (error) {
   if (!isMissing(error)) throw error
   // absent here — try the next capture root
  }
 }
 const input: CapturedInput = {
  path: target,
  digest: `missing:${sha256Json({ path: target })}`,
  exists: false,
  byteLength: 0,
  sha256: '',
 }
 await repository.putSandboxFile(input, undefined)
 return { input }
}

/** Reject symlinks anywhere in the tree before packing (tar would otherwise carry them over). */
function assertTreeSafe(rootPath: string, dirPath: string): void {
 const entries = readdirSync(dirPath, { withFileTypes: true })
 for (const entry of entries) {
  const child = join(dirPath, entry.name)
  if (entry.isSymbolicLink()) {
   throw new Error(`target tree contains a symbolic link: ${relative(rootPath, child)}`)
  }
  if (entry.isDirectory()) assertTreeSafe(rootPath, child)
 }
}

function capturedKey(digest: string): string {
 return digest.replaceAll(/[^a-zA-Z0-9_-]/gu, '_')
}

function safeKey(value: string): string {
 return sha256Json(value)
}

function isWithinRoot(relativePath: string): boolean {
 return relativePath !== '..' && !relativePath.startsWith(`..${sep}`) && !isAbsolute(relativePath)
}

async function resolveBoundPath(rootPath: string, relativePath: string): Promise<string> {
 const segments = relativePath.length === 0 ? [] : relativePath.split(sep)
 let current = rootPath
 for (let index = 0; index < segments.length; index++) {
  const segment = segments[index]
  if (segment === undefined) continue
  const candidate = join(current, segment)
  let metadata
  try {
   metadata = await lstat(candidate)
  } catch (error) {
   if (!isMissing(error)) throw error
   return join(current, ...segments.slice(index))
  }
  if (metadata.isSymbolicLink()) {
   try {
    current = await realpath(candidate)
   } catch (error) {
    if (isMissing(error)) throw new Error('sandbox path contains a dangling symbolic link')
    throw error
   }
  } else {
   current = candidate
  }
  if (!isWithinRoot(relative(rootPath, current))) {
   throw new Error('sandbox path escapes its configured root through a symbolic link')
  }
 }
 return current
}

async function readCompiledGraph(rootPath: string, graphDigest: string): Promise<CompiledGraph> {
 if (!isDigest(graphDigest)) throw new Error(`invalid graph digest ${graphDigest}`)
 const record = await readJson<{
  schemaVersion: string
  graphDigest: string
  input: DogGraphInput
  acceptancePlans: Record<string, AcceptancePlan>
 }>(join(rootPath, 'graphs', `${graphDigest}.json`))
 const actualDigest = sha256Json({ input: record.input, acceptancePlans: record.acceptancePlans })
 if (record.schemaVersion !== '0.2' || record.graphDigest !== graphDigest || actualDigest !== graphDigest) {
  throw new Error(`invalid persisted graph record ${graphDigest}`)
 }
 return {
  input: record.input,
  graphDigest: record.graphDigest,
  acceptancePlans: record.acceptancePlans,
 }
}

function isDigest(value: unknown): value is string {
 return typeof value === 'string' && /^[a-f0-9]{64}$/u.test(value)
}

const RUNTIME_PHASES = new Set([
 'goal_started',
 'dependency_blocked',
 'grounding_extracted',
 'workspace_allocated',
 'verifier_started',
 'verifier_passed',
 'verifier_failed',
 'verifier_inconclusive',
 'composite_evaluated',
 'result_inherited',
 'verifier_released',
 'verifier_bind_failed',
 'structured_error',
 'goal_settled',
 'run_warning',
])
const GOAL_STATES = new Set([
 'pending', 'running', 'success', 'failure', 'blocked', 'needs_human',
 'cancelled', 'invalidated', 'partial', 'inherited',
])

function parseRuntimeEvent(value: unknown, expectedRunId: string, expectedGoalId: string, index: number): GoalRuntimeEvent {
 const path = `runtime event ${index}`
 const record = requireRecord(value, path)
 const runId = requireString(record.runId, `${path}.runId`)
 const goalId = requireString(record.goalId, `${path}.goalId`)
 const phase = requireString(record.phase, `${path}.phase`)
 if (runId !== expectedRunId) throw new Error(`${path}.runId does not match its event log`)
 if (goalId !== expectedGoalId) throw new Error(`${path}.goalId does not match its event log`)
 if (!RUNTIME_PHASES.has(phase)) throw new Error(`${path}.phase is invalid`)

 const state = record.state === undefined ? undefined : requireString(record.state, `${path}.state`)
 if (state !== undefined && !GOAL_STATES.has(state)) throw new Error(`${path}.state is invalid`)
 const reason = record.reason === undefined ? undefined : requireBoundedString(record.reason, `${path}.reason`)
 const durationMs = record.durationMs === undefined
  ? undefined
  : requireNonNegativeInteger(record.durationMs, `${path}.durationMs`)
 const attempt = record.attempt === undefined
  ? undefined
  : requireNonNegativeInteger(record.attempt, `${path}.attempt`)
 if (attempt !== undefined && attempt < 1) throw new Error(`${path}.attempt must be positive`)
 const gmDigest = record.gmDigest === undefined ? undefined : requireString(record.gmDigest, `${path}.gmDigest`)
 const verifierRecord = record.verifier === undefined ? undefined : requireRecord(record.verifier, `${path}.verifier`)
 const verifier = verifierRecord === undefined ? undefined : {
  mode: requireEnum(verifierRecord.mode, ['programmatic', 'agentic'], `${path}.verifier.mode`),
 }
 return {
  schemaVersion: record.schemaVersion === '0.1' ? '0.1' : fail(`${path}.schemaVersion must be 0.1`),
  runId,
  goalId,
  phase: phase as GoalRuntimeEvent['phase'],
  at: requireString(record.at, `${path}.at`),
  ...(state === undefined ? {} : { state: state as NonNullable<GoalRuntimeEvent['state']> }),
  ...(reason === undefined ? {} : { reason }),
  ...(verifier === undefined ? {} : { verifier }),
  ...(gmDigest === undefined ? {} : { gmDigest }),
  ...(attempt === undefined ? {} : { attempt }),
  ...(durationMs === undefined ? {} : { durationMs }),
 }
}

function requireRecord(value: unknown, path: string): Record<string, unknown> {
 if (value === null || typeof value !== 'object' || Array.isArray(value)) throw new Error(`${path} must be an object`)
 return Object.fromEntries(Object.entries(value))
}

function requireString(value: unknown, path: string): string {
 if (typeof value !== 'string') throw new Error(`${path} must be a string`)
 return value
}

function requireEnum(value: unknown, allowed: readonly string[], path: string): 'programmatic' | 'agentic' {
 const candidate = requireString(value, path)
 if (!allowed.includes(candidate)) throw new Error(`${path} is invalid`)
 return candidate as 'programmatic' | 'agentic'
}

function requireBoundedString(value: unknown, path: string): string {
 const text = requireString(value, path)
 if (text.length > 512) throw new Error(`${path} exceeds 512 characters`)
 return text
}

function requireNonNegativeInteger(value: unknown, path: string): number {
 if (typeof value !== 'number' || !Number.isSafeInteger(value) || value < 0) {
  throw new Error(`${path} must be a non-negative safe integer`)
 }
 return value
}

function fail(message: string): never {
 throw new Error(message)
}

async function atomicWriteJson(path: string, value: unknown): Promise<void> {
 await atomicWrite(path, `${JSON.stringify(value)}\n`)
}

async function atomicWrite(path: string, value: string | Uint8Array): Promise<void> {
 const temporary = `${path}.tmp-${process.pid}-${randomUUID()}`
 await writeFile(temporary, value)
 await rename(temporary, path)
}

async function readJson<T>(path: string): Promise<T> {
 return JSON.parse(await readFile(path, 'utf8')) as T
}

function isMissing(error: unknown): boolean {
 return error instanceof Error && 'code' in error && error.code === 'ENOENT'
}
