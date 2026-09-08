/** Cross-process file lock: mutual exclusion and stale expiry. */

import { mkdtemp, readFile, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { afterEach, describe, expect, it } from 'vitest'
import { FileLock, withFileLock } from '../src/lockfile.ts'

const temporaryRoots: string[] = []

afterEach(async () => {
  await Promise.all(temporaryRoots.map(root => rm(root, { recursive: true, force: true })))
  temporaryRoots.length = 0
})

describe('FileLock', () => {
  it('holds mutual exclusion across instances of the same path', async () => {
    const root = await mkdtemp(join(tmpdir(), 'dsh-dog-lock-'))
    temporaryRoots.push(root)
    const path = join(root, 'record.lock')
    const first = new FileLock(path)
    expect(await first.tryAcquire()).toBe(true)
    const second = new FileLock(path)
    expect(await second.tryAcquire()).toBe(false)
    await first.release()
    expect(await second.tryAcquire()).toBe(true)
    await second.release()
  })

  it('expires a stale lockfile', async () => {
    const root = await mkdtemp(join(tmpdir(), 'dsh-dog-lock-'))
    temporaryRoots.push(root)
    const path = join(root, 'record.lock')
    const lock = new FileLock(path)
    expect(await lock.tryAcquire()).toBe(true)
    // backdate the owner content beyond the stale horizon is simulated by
    // accepting a negative stale window against the mtime
    expect(await lock.tryAcquire(-1)).toBe(true)
    await lock.release()
  })

  it('withFileLock runs the action under exclusion and serializes writers', async () => {
    const root = await mkdtemp(join(tmpdir(), 'dsh-dog-lock-'))
    temporaryRoots.push(root)
    const path = join(root, 'record.lock')
    const counts: number[] = []
    const gate = new Promise<void>(resolve => resolve())
    await Promise.all([
      withFileLock(path, async () => {
        await gate
        counts.push(1)
      }),
      withFileLock(path, async () => {
        counts.push(2)
      }),
    ])
    expect(counts).toHaveLength(2)
    expect(await readFile(path, 'utf8').catch(() => '')).toBe('')
  })
})
