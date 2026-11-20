import { type EditorSerialization } from './selection-coordinates.ts';
/** Editor UTF-16 positions, plus the exact editor value which produced them. */
export type ManuscriptSelection = {
    start: number;
    end: number;
    text: string;
    source: string;
    serialization?: EditorSerialization | undefined;
};
export type SelectionPolishKind = 'expand' | 'compress' | 'naturalize' | 'reviewFix';
export declare const SELECTION_POLISH_ACTIONS: readonly {
    kind: SelectionPolishKind;
    label: 'creation.selection.expand' | 'creation.selection.compress' | 'creation.selection.naturalize' | 'creation.selection.reviewFix';
}[];
/** Mark chrome that must not steal the editor selection on pointer down. */
export declare const MANUSCRIPT_SELECTION_PRESERVE_ATTR = "data-preserve-manuscript-selection";
export declare function nodePreservesManuscriptSelection(node: EventTarget | Node | null): boolean;
/** False when a toolbar click collapsed the native range; keep the last editor span. */
export declare function shouldClearManuscriptSelection(options: {
    selectionInsideEditor: boolean;
    preserveNode: EventTarget | Node | null;
}): boolean;
export declare function manuscriptSelectionFromRange(value: string, start: number, end: number, serialization?: EditorSerialization): ManuscriptSelection | null;
export declare function mapManuscriptSelection(source: string, selection: ManuscriptSelection): {
    start: number;
    end: number;
    text: string;
} | null;
/** Count non-overlapping occurrences of needle in haystack. */
export declare function countOccurrences(haystack: string, needle: string): number;
/** Zero-based nth occurrence start, or -1. */
export declare function nthIndexOf(haystack: string, needle: string, occurrence: number): number;
/**
 * Map a live editor selection onto markdown offsets.
 * Duplicate quotes without an occurrence index do not bind the first hit.
 */
export declare function locateSelectedMarkdown(value: string, selected: string, occurrence?: number, serialization?: EditorSerialization): ManuscriptSelection | null;
export type QuoteAnchor = {
    state: 'attached' | 'relocated';
    start: number;
    end: number;
} | {
    state: 'detached';
    reason: 'missing' | 'ambiguous' | 'mismatch';
};
/** Bind a stored quote to current markdown using hints, then unique relocate. */
export declare function locateQuote(content: string, quote: string, startHint: number, endHint: number): QuoteAnchor;
/** Review issues whose evidence sits inside the current manuscript selection. */
export declare function reviewIssuesForSelection(issues: readonly unknown[], selection: {
    start: number;
    end: number;
    text: string;
}): string[];
export type SelectionPolishRequest = {
    ok: true;
    path: '/revisions/selection' | '/revisions/from-review';
    body: Record<string, unknown>;
} | {
    ok: false;
    reason: 'empty' | 'no-review' | 'no-issues' | 'source-changed';
};
/** Map one author action onto the existing Studio revision-create routes. */
export declare function selectionPolishRequest(input: {
    kind: SelectionPolishKind;
    chapterId: string;
    selection: ManuscriptSelection;
    documentContent: string;
    documentRevision: string;
    reviewRevision: string;
    reviewFresh: boolean;
    issueIds: string[];
}): SelectionPolishRequest;
