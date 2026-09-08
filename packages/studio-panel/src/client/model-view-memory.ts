import type { WorkbenchContext } from './WorkbenchStore.ts'

/** A workspace's canonical root is part of its identity; unbound views never cache. */
export function modelMemoryContextKey(context: WorkbenchContext | null | undefined): string | null {
  return context?.workspaceId && context.root ? JSON.stringify([context.workspaceId, context.root]) : null
}

/**
 * Short-lived view memory only. It never calls localStorage or serializes to disk.
 * Inactive entries expire, and an entry limit also bounds a long-lived app session.
 */
export class WorkspaceViewMemory<T> {
  private readonly entries = new Map<string, { value: T; expiresAt: number; timer: ReturnType<typeof setTimeout> }>()

  constructor(private readonly limit = 8, private readonly retentionMs = 60 * 60 * 1000) {}

  read(key: string | null): T | undefined {
    if (key === null) return undefined
    const entry = this.entries.get(key)
    if (entry && entry.expiresAt <= Date.now()) {
      this.delete(key)
      return undefined
    }
    return entry?.value
  }

  take(key: string | null): T | undefined {
    const value = this.read(key)
    this.delete(key)
    return value
  }

  write(key: string | null, value: T): void {
    if (key === null) return
    this.delete(key)
    const timer = setTimeout(() => this.delete(key), this.retentionMs)
    this.entries.set(key, { value, expiresAt: Date.now() + this.retentionMs, timer })
    while (this.entries.size > this.limit) this.delete(this.entries.keys().next().value!)
  }

  delete(key: string | null): void {
    if (key === null) return
    const entry = this.entries.get(key)
    if (entry) clearTimeout(entry.timer)
    this.entries.delete(key)
  }
}
