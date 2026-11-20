import { type StudioApiInjected } from './api.ts';
type StructureStatus = 'absent' | 'current' | 'stale' | 'ambiguous';
interface SceneIssue {
    key: string;
    message: string;
    code: string;
    sceneId: string;
    chapterId: string;
    /** Core's severity; `info` means "not produced yet", not "broken". */
    severity: string;
}
interface SceneRecord {
    id: string;
    chapterId: string;
    chapterTitle: string;
    title: string;
    storyTimeSortKey: string;
    storyTimeLabel: string;
    characters: string[];
    locations: string[];
    events: string[];
    revision: string;
    chapterRevision: string;
    readingIndex: number;
    storyTimeIndex: number;
    chapterIndex: number;
}
interface SceneChapter {
    id: string;
    title: string;
    revision: string;
    sceneCount: number;
}
interface SceneStructure {
    schemaVersion: string;
    status: StructureStatus;
    revision: string;
    scenes: SceneRecord[];
    chapters: SceneChapter[];
    issues: SceneIssue[];
    plannedMissingChapters: number;
    mutationAllowed: boolean;
}
interface MigrationPreview {
    schemaVersion: string;
    revision: string;
    rows: string[];
    issues: SceneIssue[];
    canApply: boolean;
}
export type SceneWorkbenchProps = Pick<StudioApiInjected, 'fetchStudioApi' | 'postStudioApi'>;
/** Normalize the scene envelope without turning planned-missing chapters into scenes. */
export declare function parseSceneStructure(value: unknown): SceneStructure;
export declare function parseMigrationPreview(value: unknown): MigrationPreview | null;
/** Native scene-structure editor. All mutations are guarded by envelope and chapter revisions. */
export declare function SceneWorkbench({ fetchStudioApi, postStudioApi }: SceneWorkbenchProps): import("react").JSX.Element;
export {};
