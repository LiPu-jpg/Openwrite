import type { StudioApiInjected } from './api.ts';
import type { ChapterSummary } from './WorkbenchStore.ts';
import type { PropsLocale } from '@deepseek-ai/dsh-client-ui-slots';
export interface ContinuousReaderProps extends PropsLocale<'studio-panel'> {
    chapters: readonly ChapterSummary[];
    activePath: string;
    activeOccurrenceId: string;
    readingOrderRevision: string;
    fetchStudioApi: StudioApiInjected['fetchStudioApi'];
    onOpenChapter: (path: string, occurrenceId: string) => void;
}
/** Read-only, revision-labelled manuscript view over immutable reading occurrences. */
export declare function ContinuousReader({ chapters, activePath, activeOccurrenceId, readingOrderRevision, fetchStudioApi, onOpenChapter, t, }: ContinuousReaderProps): import("react").JSX.Element;
