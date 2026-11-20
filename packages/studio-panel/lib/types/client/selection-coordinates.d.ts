/** Exact mapping between an editor's UTF-16 view and the saved source's code points. */
export type SourceRange = {
    start: number;
    end: number;
    text: string;
};
/** A pair captured from the editor's initial serialization, before author input. */
export type EditorSerialization = {
    source: string;
    value: string;
};
/** Exact content and witnessed newline serialization; never guess among quotes. */
export declare function mapEditorRange(source: string, editor: string, start: number, end: number, serialization?: EditorSerialization): SourceRange | null;
/** Translate stored source code-point hints back into the editor's UTF-16 view. */
export declare function mapSourceRange(source: string, editor: string, start: number, end: number, serialization?: EditorSerialization): SourceRange | null;
