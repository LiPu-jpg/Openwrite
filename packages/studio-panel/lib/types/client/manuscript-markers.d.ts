/** Core inline metadata: character state and directed relations. Display-only coloring. */
export declare const STATE_MARKER_RE: RegExp;
export declare const RELATION_MARKER_RE: RegExp;
export type MarkerKind = 'state' | 'relation';
export type ParsedMarker = {
    kind: 'state';
    name: string;
    field: string;
    oldState: string;
    newState: string;
} | {
    kind: 'relation';
    source: string;
    target: string;
    description: string;
};
export type MarkerSpan = {
    kind: MarkerKind | 'invalid';
    start: number;
    end: number;
    line: number;
    text: string;
    parsed: ParsedMarker | null;
    hint: string;
};
export type MarkerDraftError = 'empty' | 'newline' | 'reserved';
export declare function parseMarkerLine(line: string): {
    parsed: ParsedMarker | null;
    invalid: boolean;
    hint: string;
};
/** Parse markers outside fenced code. Invalid/unclosed fences keep source text. */
export declare function parseMarkers(text: string): MarkerSpan[];
export declare function formatStateMarker(input: {
    name: string;
    field?: string;
    oldState: string;
    newState: string;
}): {
    ok: true;
    markdown: string;
} | {
    ok: false;
    error: MarkerDraftError;
    field: string;
};
export declare function formatRelationMarker(input: {
    source: string;
    target: string;
    description: string;
}): {
    ok: true;
    markdown: string;
} | {
    ok: false;
    error: MarkerDraftError;
    field: string;
};
/** Readable prose with valid metadata lines removed; invalid markers stay. */
export declare function stripValidMarkers(text: string): string;
export declare function readableWritingUnits(text: string): number;
