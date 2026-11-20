/** Map overlay needles onto live IR text nodes. Display-only; never writes into markdown. */
/** nth occurrence of needle across adjacent text nodes, including Vditor IR splits. */
export declare function rangeForNeedle(root: ParentNode, needle: string, occurrence: number): Range | null;
/** Repaint when the IR scroller moves or the frame size changes. */
export declare function bindOverlayResync(host: HTMLElement, refresh: () => void): () => void;
/** Select the quoted span in the live IR and bring it into view. */
export declare function revealNeedle(root: ParentNode, needle: string, occurrence: number): Range | null;
