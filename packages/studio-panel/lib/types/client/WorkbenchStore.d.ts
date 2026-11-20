export type ConnectionState = 'connecting' | 'online' | 'offline';
export type EditorStatus = 'idle' | 'loading' | 'saved' | 'dirty' | 'saving' | 'conflict' | 'offline';
export type ResourceKey = 'workspace' | 'manuscript' | 'outline' | 'assets' | 'tasks' | 'benchmark' | 'models' | 'dag' | 'graph' | 'research' | 'revisions';
/**
 * The panel's Workspace identity (docs/WORKSPACE_CONTEXT_CONTRACT.md §9):
 * `root` is the dsh Workspace's canonical absolute path — the only identity
 * that matters for invalidate filtering; `workspaceId` is the UI/wire
 * reference carried on every proxied request.
 */
export interface WorkbenchContext {
    workspaceId: string;
    root: string;
    sessionId?: string | undefined;
}
export interface ReviewSummary {
    score: number | null;
    passed: boolean | null;
    issues: number;
    issueDetails: readonly unknown[];
    stale: boolean;
    reviewedAt: string;
    sourceRevision: string;
    currentSourceRevision: string;
}
export interface ChapterSummary {
    id: string;
    /** Stable server identity when supplied. An empty value means path is the only available identity. */
    documentId: string;
    /** Stable position in canonical reading order. Repeated documents receive distinct occurrences. */
    occurrenceId: string;
    volumeId: string;
    status: string;
    path: string;
    title: string;
    subtitle: string;
    revision: string;
    readingIndex: number | null;
    writingUnits: number | null;
    updatedAt: string;
    review: ReviewSummary;
}
export interface WritingProgress {
    bookUnits: number;
    bookTarget: number;
    chapterTarget: number;
}
export interface WorkbenchSnapshot {
    connection: ConnectionState;
    /** Bound Workspace context; null = no Workspace bound, panel issues no proxied requests. */
    context: WorkbenchContext | null;
    /** Local generation counter, bumped on every context switch. */
    contextEpoch: number;
    /** Contract error code blocking this context (e.g. WORKSPACE_NOT_INITIALIZED), null when healthy. */
    workspaceError: string | null;
    projectTitle: string;
    currentChapterId: string;
    activeChapterPath: string;
    chapters: readonly ChapterSummary[];
    writingProgress: WritingProgress;
    workspace: unknown;
    tasks: unknown;
    activeTasks: number;
    editorStatus: EditorStatus;
    editorMessage: string;
    epochs: Readonly<Record<ResourceKey, number>>;
    lastUpdatedAt: number;
}
type Listener = () => void;
declare class NovelWorkbenchStore {
    private snapshot;
    private readonly listeners;
    private pollTimer;
    private eventSource;
    private refreshPromise;
    private refreshController;
    private taskSignature;
    /** Raw tasks payload of the last committed refresh (terminal-diff baseline). */
    private tasksPayload;
    private revision;
    private revisionInitialized;
    /** Last seen upstream context_epoch (background-transition hint channel). */
    private contextEpoch;
    private contextEpochInitialized;
    private pollTicks;
    /** Context generation: every setContext bump invalidates in-flight work. */
    private generation;
    readonly subscribe: (listener: Listener) => (() => void);
    readonly getSnapshot: () => WorkbenchSnapshot;
    /**
     * The context barrier (contract §9). A changed context: bumps the
     * generation (late responses from the old generation are dropped on
     * commit), resets every per-context slice back to INITIAL, aborts the
     * in-flight refresh, closes the old SSE stream and poll timer, zeroes the
     * revision/task baselines, rebinds the API layer's context headers, then
     * reconnects and refreshes under the new Workspace. An identical context
     * is a no-op; null stops everything and clears the panel.
     */
    setContext(next: WorkbenchContext | null): void;
    setActiveChapter(path: string): void;
    setEditorStatus(status: EditorStatus, message?: string): void;
    invalidate(resource: ResourceKey): void;
    refresh(): Promise<void>;
    /**
     * Two-layer sync. Layer one is the always-on 5s invalidation poll: it is
     * the only channel that observes background task transitions, because the
     * bridge merges the upstream context_epoch into invalidation.json and task
     * transitions bump it without any bridge-local write. Layer two is SSE,
     * the instant channel for proxied writes and agent mutations; its state
     * never gates the poll loop.
     */
    private start;
    private startPolling;
    private consumeMutation;
    private stop;
    private pollInvalidation;
    private refreshNow;
    private patch;
}
export declare const workbenchStore: NovelWorkbenchStore;
export declare function useWorkbench(): WorkbenchSnapshot;
export {};
