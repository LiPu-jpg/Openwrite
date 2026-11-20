import { type QuoteAnchor } from './manuscript-selection.ts';
import { type EditorSerialization } from './selection-coordinates.ts';
export declare const ANNOTATION_COLORS: readonly ["amber", "rose", "sky", "lime", "violet"];
export type AnnotationColor = (typeof ANNOTATION_COLORS)[number];
export declare const DEFAULT_ANNOTATION_COLOR: AnnotationColor;
export declare const ANNOTATION_COLOR_LABEL: Record<AnnotationColor, `creation.notes.color.${AnnotationColor}`>;
export type AnnotationStatus = 'open' | 'resolved';
export type AnnotationAnchorState = 'attached' | 'relocated' | 'detached';
export type ManuscriptAnnotation = {
    annotationId: string;
    chapterId: string;
    sourceRevision: string;
    quote: string;
    startHint: number;
    endHint: number;
    note: string;
    status: AnnotationStatus;
    anchorState: AnnotationAnchorState;
    currentStart: number | null;
    currentEnd: number | null;
    color: AnnotationColor;
    createdAt: string;
    updatedAt: string;
};
export declare function isAnnotationColor(value: string): value is AnnotationColor;
/** Old records without color keep amber; unknown values also default. */
export declare function annotationColor(value: unknown): AnnotationColor;
export declare function parseAnnotation(value: unknown): ManuscriptAnnotation | null;
export declare function parseAnnotationList(value: unknown): ManuscriptAnnotation[];
export declare function unsavedAnnotationGuard(dirty: boolean): 'ok' | 'save-first';
export declare function annotationLocateLabel(anchor: QuoteAnchor | {
    state: AnnotationAnchorState;
}): string;
export declare function liveAnnotationAnchor(content: string, item: ManuscriptAnnotation, source?: string, serialization?: EditorSerialization): QuoteAnchor;
export declare function revalidateAnnotationRange(content: string, selection: {
    start: number;
    end: number;
    text: string;
}): {
    start: number;
    end: number;
    text: string;
} | null;
export declare function annotateRequest(input: {
    chapterId: string;
    revision: string;
    selection: {
        start: number;
        end: number;
        text: string;
    };
    note: string;
    color: AnnotationColor;
}): {
    ok: true;
    body: Record<string, unknown>;
} | {
    ok: false;
    reason: 'empty' | 'save-first';
};
