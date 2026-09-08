/** Test fixtures for DoG v0.9: graph builders and kernel stubs. */

import { mkdtemp, mkdir, writeFile, chmod } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import type { DogConfig, DogGraphInput, GoalNodeInput, VerifierShape } from '../src/model.ts'

export interface EngineFixture {
  root: string
  config: DogConfig
}

export async function temporaryRoot(): Promise<string> {
  return mkdtemp(join(tmpdir(), 'dsh-dog-'))
}

/** Create a minimal programmatic script library under the fixture root. */
export async function ensureScripts(root: string, names: readonly string[] = ['file-non-empty']): Promise<void> {
  const scripts = join(root, 'scripts')
  await mkdir(scripts, { recursive: true })
  for (const name of names) {
    const path = join(scripts, name)
    await writeFile(path, '#!/usr/bin/env node\nprocess.stdout.write(JSON.stringify({ verdict: "pass", evidence: { script: true } }))\n')
    await chmod(path, 0o755)
  }
}

export function mkConfig(root: string, scripts: string): DogConfig {
  return {
    workspaceRoot: root,
    scriptsDirectory: scripts,
    storageDirectory: 'dog',
    maxGraphNodes: 64,
    maxExpressionNodes: 128,
    maxExpressionDepth: 16,
    maxSandboxBytes: 1024 * 1024,
    allowPartialRoot: false,
    maxConcurrentVerifications: 1,
    revalidateThreshold: 0.3,
    gmDigestAlgo: 'sha256',
  }
}

export function leafNode(overrides: Partial<{ title: string; constraint: 'hard' | 'soft'; target: string; verifier: VerifierShape }> = {}): GoalNodeInput {
  return {
    kind: 'leaf' as const,
    title: 'leaf',
    constraint: 'hard' as const,
    target: 'artifact.txt' as const,
    verifier: { mode: 'programmatic' as const, script: 'file-non-empty' },
    ...overrides,
  } as GoalNodeInput
}

export function compositeNode(completion: object, overrides: Partial<{ title: string; constraint: 'hard' | 'soft'; target: string; verifier?: VerifierShape }> = {}): GoalNodeInput {
  return {
    kind: 'composite' as const,
    title: 'root',
    constraint: 'hard' as const,
    target: 'artifact.txt' as const,
    completion: completion as GoalNodeInput['completion'],
    ...overrides,
  } as GoalNodeInput
}

export function graph(
  nodes: Record<string, GoalNodeInput>,
  contains: DogGraphInput['contains'],
  id = 'demo',
): DogGraphInput {
  return {
    schemaVersion: '0.9',
    id,
    root: 'root',
    nodes,
    contains,
    dependsOn: [],
  }
}

/** Fake programmatic kernel: succeeds without executing a real script. */
export function stubProgrammatic(): (script: string, inputPath: string, env?: import('../src/verifiers.ts').VerifierExecutionEnv) => Promise<import('../src/verifiers.ts').Verdict> {
  return async () => ({ state: 'pass', evidence: { stubbed: true } })
}

/** Fake agentic kernel: returns a fixed verdict. */
export function stubAgentic(verdict: 'pass' | 'fail' | 'inconclusive' = 'pass'): (instruction: string, workspace?: import('../src/verifiers.ts').IsolatedWorkspace, inputPath?: string, env?: import('../src/verifiers.ts').VerifierExecutionEnv) => Promise<import('../src/verifiers.ts').Verdict> {
  return async () => ({ state: verdict, evidence: { stubbed: true, verdict } })
}
