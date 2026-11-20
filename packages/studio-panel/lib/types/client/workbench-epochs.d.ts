/**
 * Pure epoch-invalidation logic shared by the WorkbenchStore. Extracted so it
 * can be unit-tested with Node's type-stripping runner without React/DOM.
 */
export type ResourceKey = 'workspace' | 'manuscript' | 'outline' | 'assets' | 'tasks' | 'benchmark' | 'models' | 'dag' | 'graph' | 'research' | 'revisions';
export type Epochs = Readonly<Record<ResourceKey, number>>;
export declare function nextEpochs(resource: ResourceKey, epochs: Epochs): Epochs;
export declare function triggersRefresh(resource: ResourceKey): boolean;
/**
 * Typed terminal diff between two task-list payloads: the resources whose
 * views must remount because a task they display NEWLY reached a terminal
 * status. A task absent from the previous payload is not a transition (we
 * never observed it running — initial loads and window re-entries stay
 * quiet). Malformed payloads yield [], never throw.
 */
export declare function terminalTransitionResources(previousTasksJson: unknown, nextTasksJson: unknown): ResourceKey[];
