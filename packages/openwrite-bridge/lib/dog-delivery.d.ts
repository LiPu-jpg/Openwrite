import { type JsonValue } from './client.js';
export declare function atomicWrite(path: string, value: unknown): Promise<void>;
/**
 * Anti-drift guard (docs/WORKSPACE_CONTEXT_CONTRACT.md §7): the workspace
 * payload's project root must canonicalize to the current tool context root.
 * Anything else means the Studio response belongs to another Workspace and
 * materializing it here would leak artifacts across roots.
 */
export declare function assertWorkspaceRootMatch(payloadRoot: string, expectedRoot: string): void;
/** Refuse write targets that escape the project root (e.g. via a hostile novel_id). */
export declare function assertContained(target: string, root: string): void;
/** Rebuild a chapter-delivery graph from canonical manuscript, review and revision records. */
export declare function materializeChapterDelivery(workspaceValue: unknown, chapterId: string, threshold?: number, expectedRoot?: string): Promise<JsonValue>;
