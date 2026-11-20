/**
 * Same-origin read path to the local OpenWrite Studio API through the host
 * half's proxy route (registered by @dsh-novel/openwrite-bridge, see
 * packages/openwrite-bridge domain.ts). Studio itself sends no CORS headers,
 * so the browser can only reach it via this proxy.
 *
 * Workspace context (docs/WORKSPACE_CONTEXT_CONTRACT.md §2.2): the browser
 * only ever sends the dsh workspace id (plus an optional session id for
 * audit) — never a path. Every proxied request carries the context headers;
 * with no context bound the panel must not issue *project-scoped* proxied
 * requests at all, so the project-scoped request helpers fail closed with
 * WORKSPACE_CONTEXT_MISSING.
 *
 * The global model library is the one exception: Studio keeps it outside
 * every project, so `fetchGlobalStudioApi` / `postGlobalStudioApi` reach it
 * without any workspace identity (see GLOBAL_STUDIO_PATHS).
 */
/** Host-half proxy prefix (kept in sync with openwrite-bridge domain.ts). */
export declare const API_PROXY_BASE = "/studio-panel/api";
/** Browser-side Workspace identity stamped onto every proxied request. */
export interface StudioContext {
    workspaceId: string;
    sessionId?: string | undefined;
}
/**
 * Bind (or clear, with null) the Workspace context for all proxied requests.
 * Owned by the WorkbenchStore context barrier — components never call this
 * directly; they go through `workbenchStore.setContext`.
 */
export declare function setStudioContext(next: StudioContext | null): void;
/** The currently bound Workspace context, or null when unbound. */
export declare function getStudioContext(): StudioContext | null;
/**
 * Context headers for the contract's browser wire format. Throws a
 * StudioApiError (code WORKSPACE_CONTEXT_MISSING) when no context is bound —
 * fail closed, never fall back to a context-less request.
 */
export declare function studioContextHeaders(): Record<string, string>;
/**
 * Injected share of the data views (大纲 / 资产): JSON fetches against the
 * Studio API. `postStudioApi` only reaches the host proxy's write allowlist
 * (asset domain; see openwrite-bridge domain.ts WRITABLE_PATHS).
 */
export interface StudioApiInjected {
    fetchStudioApi: (path: string) => Promise<unknown>;
    postStudioApi: (path: string, body: unknown) => Promise<unknown>;
    putStudioApi: (path: string, body: unknown, context?: StudioContext) => Promise<unknown>;
}
/**
 * The global Studio paths: the model profile library and the model route map.
 *
 * Studio keeps them outside every project (the user's preferences directory,
 * `model-profiles.json`) and registers every model route with
 * `requires_project=False`. They are therefore reachable with no Workspace
 * context at all — which is exactly what the host's settings dialog needs,
 * since that surface is opened without a bound workspace. The host proxy
 * mirrors this list in `GLOBAL_PATHS` (openwrite-bridge domain.ts); a request
 * without a workspace id is forwarded unchanged for those paths only.
 */
export declare const GLOBAL_STUDIO_PATHS: Set<string>;
/** Whether the stale-host fallback is currently in use. */
export declare function isGlobalFallbackActive(): boolean;
/** Forget the stale-host fallback state (test isolation). */
export declare function resetGlobalFallbackState(): void;
/** A Studio API failure that keeps the HTTP status (409 = optimistic-lock conflict) and contract error code. */
export declare class StudioApiError extends Error {
    readonly status: number;
    readonly code: string | undefined;
    readonly details: Readonly<Record<string, unknown>>;
    constructor(message: string, status: number, code?: string, details?: Record<string, unknown>);
}
/**
 * GET one Studio API path through the proxy and parse the JSON body. Throws
 * a StudioApiError carrying the upstream status and message on any non-2xx
 * answer (including the proxy's own 502 when Studio is down).
 * @param path - Studio API path beginning with `/`, query string allowed
 *   (e.g. `/assets?kind=character`).
 * @param signal - optional caller abort (context switches cancel in-flight reads).
 * @returns the parsed JSON payload.
 */
export declare function fetchStudioApi(path: string, signal?: AbortSignal): Promise<unknown>;
/**
 * GET one global Studio API path through the proxy **without** any Workspace
 * context headers.
 *
 * The model library is global, so the host's settings dialog (opened with no
 * bound workspace) can read and edit it. Project-scoped paths are rejected
 * here — they still need `fetchStudioApi`.
 *
 * When the host is still running an older bridge, the proxy refuses the
 * context-free call. The scoped route reaches the same library, so the call
 * is retried with the bound workspace (see `staleHostFallbackHeaders`).
 */
export declare function fetchGlobalStudioApi(path: string, signal?: AbortSignal): Promise<unknown>;
/**
 * POST a JSON body to one allowlisted global Studio API path through the
 * proxy, without any Workspace context headers.
 */
export declare function postGlobalStudioApi(path: string, body: unknown): Promise<unknown>;
/**
 * POST a JSON body to one allowlisted Studio API path through the proxy and
 * parse the JSON response. Throws StudioApiError with the upstream status and
 * message on any non-2xx answer (409 = revision conflict, surfaced by the
 * asset editor as "reload and retry").
 * @param path - allowlisted Studio API path (e.g. `/assets/update`).
 * @param body - JSON-serializable request body, forwarded verbatim.
 * @returns the parsed JSON payload.
 */
export declare function postStudioApi(path: string, body: unknown): Promise<unknown>;
/** PUT a JSON body to one allowlisted Studio API path. */
export declare function putStudioApi(path: string, body: unknown, context?: StudioContext): Promise<unknown>;
