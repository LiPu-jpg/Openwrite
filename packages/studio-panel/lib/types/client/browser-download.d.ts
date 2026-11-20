/** Prefer RFC 5987 names, retaining literal percent signs in legacy filenames. */
export declare function downloadFilename(disposition: string, fallback: string): string;
/** Safari needs an attached link and time to consume the Blob URL. */
export declare function downloadBlob(blob: Blob, filename: string): void;
