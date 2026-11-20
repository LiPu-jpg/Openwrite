import type { BackendConnection } from './managed-runtime.js';
/** Windows roots are case-insensitive and may use either separator. */
export declare function workspaceRootsEqual(left: string, right: string, platform?: NodeJS.Platform): boolean;
/**
 * Shared HTTP client for the OpenWrite Studio action surface.
 *
 * Contract (verified against OpenWrite `tools/studio_http.py` and
 * `tools/studio_contracts.py`): managed requests carry instance authentication; every POST/PUT must
 * carry `X-OpenWrite-Studio: 1` or the server answers 403. Error responses are
 * JSON `{error, code, recoverable, details, request_id}` with a non-2xx
 * status; some routes wrap success in `{ok: true, data, ...}` which this
 * client unwraps transparently.
 */
/** JSON value as exchanged with the Studio API. */
export type JsonValue = string | number | boolean | null | JsonValue[] | {
    [key: string]: JsonValue;
};
/** A JSON object payload. */
export type JsonObject = {
    [key: string]: JsonValue;
};
/** HTTP header values are bytes, so Unicode paths need explicit wire encoding.
 * Plain ASCII retains the old contract, including literal percent characters. */
export declare function workspaceRootHeaders(root: string, lowercase?: boolean): Record<string, string>;
/**
 * Request-scoped Workspace identity, per docs/WORKSPACE_CONTEXT_CONTRACT.md §3.
 * `workspaceRoot` is the canonical (realpath'd) absolute path — the only root
 * identity; the id/epoch fields are audit/diagnostic metadata.
 */
export interface WorkspaceContext {
    workspaceRoot: string;
    workspaceId?: string;
    sessionId?: string;
    contextEpoch?: number;
    toolCallId?: string;
    rootCallId?: string;
    toolName?: string;
}
export declare class StudioError extends Error {
    readonly status: number;
    readonly code: string;
    readonly details: JsonValue;
    requestId: string | null;
    constructor(message: string, status: number, code: string, details?: JsonValue);
}
export interface StudioClientOptions {
    connect?: () => Promise<BackendConnection>;
    /** Studio base URL, e.g. `http://127.0.0.1:4567`. */
    baseUrl: string;
    /** Per-request timeout in milliseconds (backstop; the dsh timeout policy owns the budget). */
    timeoutMs: number;
    /** Notify the owning domain service after a successful mutation. */
    onMutation?: (path: string, context?: WorkspaceContext) => void;
    /** Request-scoped Workspace context stamped onto every request (see `scoped`). */
    context?: WorkspaceContext;
}
/** A downloaded export file. */
export interface StudioDownload {
    filename: string;
    contentType: string;
    content: Uint8Array;
}
/** Query parameters; array values become repeated `key=v1&key=v2` entries. */
export type QueryParams = Record<string, string | string[]>;
/** Legacy Core fallback; newer servers declare mutation semantics in a response header. */
export declare function mutationAffectsState(path: string, body: unknown, headers?: Headers): boolean;
export declare class StudioClient {
    private readonly connect;
    private readonly baseUrl;
    private readonly timeoutMs;
    private readonly onMutation;
    /** Workspace context stamped onto every request; undefined for legacy (unscoped) clients. */
    readonly context: WorkspaceContext | undefined;
    constructor(options: StudioClientOptions);
    /**
     * Derive a lightweight request-scoped client sharing baseUrl/timeout/onMutation.
     * Every request it makes carries the §3 context headers, and mutation
     * notifications report this context so invalidation stays per-root.
     */
    scoped(context: WorkspaceContext): StudioClient;
    /** §3 context headers; empty for a legacy (unscoped) client. */
    private contextHeaders;
    /** GET a JSON endpoint. `params` entries are URL-encoded; undefined values are dropped. */
    getJson(path: string, params?: QueryParams, signal?: AbortSignal): Promise<JsonValue>;
    /** POST a JSON object with the Studio write protocol header. */
    postJson(path: string, body: JsonObject, signal?: AbortSignal): Promise<JsonValue>;
    /** PUT a JSON object with the Studio write protocol header. */
    putJson(path: string, body: JsonObject, signal?: AbortSignal): Promise<JsonValue>;
    /** GET a file-download endpoint (export), returning the raw bytes and filename. */
    download(path: string, params: QueryParams, signal?: AbortSignal): Promise<StudioDownload>;
    /** One fetch honoring both the caller's abort signal and the configured timeout. */
    private request;
    /**
     * Read a JSON response, throwing a normalized StudioError for non-2xx statuses
     * and for bodies carrying the server's `{error, code}` contract. Success
     * envelopes (`{ok: true, data}`) are unwrapped to their `data` payload.
     */
    private readJson;
}
