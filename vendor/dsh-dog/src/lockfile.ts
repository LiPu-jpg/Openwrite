/** Cross-process per-record lock: exclusive-create lockfile with stale expiry. */

import { open, rm, stat } from 'node:fs/promises'

export class FileLock {
 constructor(private readonly path: string) { }

 /**
  * Try to acquire the lock. create-exclusive ('wx') is atomic across
  * processes; an existing lockfile older than `staleMs` is considered
  * abandoned (crashed holder) and replaced.
  */
 async tryAcquire(staleMs = 60_000): Promise<boolean> {
  try {
   const handle = await open(this.path, 'wx')
   await handle.writeFile(`${process.pid} ${Date.now()}`)
   await handle.close()
   return true
  } catch (error: unknown) {
   if ((error as { code?: string }).code !== 'EEXIST') return false
   try {
    const info = await stat(this.path)
    if (Date.now() - info.mtimeMs > staleMs) {
     await rm(this.path, { force: true })
     return this.tryAcquire(staleMs)
    }
   } catch {
    // stale check raced another remover: treat as held this round
   }
   return false
  }
 }

 async release(): Promise<void> {
  await rm(this.path, { force: true }).catch(() => undefined)
 }
}

/** Bounded wait for a FileLock; throws on timeout so callers fail loudly. */
export async function withFileLock<T>(
 path: string,
 action: () => Promise<T>,
 options: { readonly waitMs?: number; readonly staleMs?: number } = {},
): Promise<T> {
 const lock = new FileLock(path)
 const deadline = Date.now() + (options.waitMs ?? 1_500)
 for (; ;) {
  if (await lock.tryAcquire(options.staleMs)) break
  if (Date.now() >= deadline) {
   throw new Error(`storage lock timeout: ${path}`)
  }
  await new Promise(resolve => setTimeout(resolve, 25))
 }
 try {
  return await action()
 } finally {
  await lock.release()
 }
}
