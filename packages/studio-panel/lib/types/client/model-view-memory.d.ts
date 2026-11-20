import type { WorkbenchContext } from './WorkbenchStore.ts';
/** A workspace's canonical root is part of its identity; unbound views never cache. */
export declare function modelMemoryContextKey(context: WorkbenchContext | null | undefined): string | null;
/**
 * Short-lived view memory only. It never calls localStorage or serializes to disk.
 * Inactive entries expire, and an entry limit also bounds a long-lived app session.
 */
export declare class WorkspaceViewMemory<T> {
    private readonly limit;
    private readonly retentionMs;
    private readonly entries;
    constructor(limit?: number, retentionMs?: number);
    read(key: string | null): T | undefined;
    take(key: string | null): T | undefined;
    write(key: string | null, value: T): void;
    delete(key: string | null): void;
}
