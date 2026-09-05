/**
 * Workspace-scoped localStorage keys (docs/WORKSPACE_CONTEXT_CONTRACT.md §9):
 * every persisted panel key carries the bound workspace id as suffix so
 * per-workspace UI state never leaks across contexts. The 'default' segment
 * covers the no-context window (before a session's workspace resolves).
 */

/** Namespace one base key with the workspace id ('default' when unbound). */
export function storageKey(base: string, workspaceId: string | null | undefined): string {
  return `${base}.${workspaceId !== null && workspaceId !== undefined && workspaceId !== '' ? workspaceId : 'default'}`
}
