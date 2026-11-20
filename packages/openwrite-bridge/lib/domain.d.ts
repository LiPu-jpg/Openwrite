import type { BackendConnection } from './managed-runtime.js';
import { Service, type Context } from '@deepseek-ai/cordis';
import type { ToolRunContext } from '@deepseek-ai/dsh-tools';
import { StudioClient, type WorkspaceContext } from './client.js';
export declare const CONFIG_ROUTE = "/studio-panel/config.json";
export declare const API_PROXY_ROUTE = "/studio-panel/api";
export declare const EVENTS_ROUTE = "/studio-panel/events";
export declare const INVALIDATION_ROUTE = "/studio-panel/invalidation.json";
/** Every browser write path the proxy forwards. Exported for the regression test. */
export declare const WRITABLE_PATHS: Set<string>;
export declare const WRITABLE_PATH_RE: RegExp;
/**
 * Paths whose payload is global, not project-scoped.
 *
 * The model profile library lives outside every project — Studio keeps it in
 * the user's preferences directory (`model-profiles.json`), and every model
 * route is registered with `requires_project=False`. The host settings dialog
 * is the one surface that is opened *without* a bound workspace, so these
 * paths must be reachable without a workspace id: the browser sends no
 * `X-Dsh-Workspace-Id` and the proxy forwards the call without a project
 * root, exactly as the contract's project-free routes expect.
 *
 * Every other proxied path stays fail-closed on a missing workspace id.
 */
export declare const GLOBAL_PATHS: Set<string>;
declare module '@deepseek-ai/cordis' {
    interface Context {
        novelDomain: NovelDomainService;
    }
}
export interface NovelDomainOptions {
    outputDir?: string;
    authorizeRequest?: (headers: Record<string, string | string[] | undefined>) => number | undefined;
    connect?: () => Promise<BackendConnection>;
    baseUrl: string;
    timeoutMs: number;
    /**
     * Host-trusted workspace_id → canonical root resolution (dsh
     * `ctx.workspaceRegistry`), looked up lazily per call so plugin start order
     * cannot strand it. Absent resolver or a `null` result means the registry
     * service itself is missing: every browser entry fails closed with
     * WORKSPACE_REGISTRY_UNAVAILABLE. `undefined` means unknown id.
     */
    resolveWorkspace?: (workspaceId: string) => string | undefined | null;
}
/** Single host-side boundary shared by agent tools, browser proxy and live invalidation. */
export declare class NovelDomainService extends Service {
    readonly toolOptions: {
        timeoutMs: number;
        outputDir?: string;
    };
    readonly client: StudioClient;
    private readonly authorizeRequest;
    private readonly connect;
    readonly baseUrl: string;
    private readonly resolveWorkspace;
    /** Undelivered SSE bytes per stream, for backpressure (see notifyMutation). */
    private readonly streamPending;
    /** Per-root invalidation state, keyed by canonical workspace root ('' = legacy). */
    private readonly roots;
    /** Open SSE connections bound to the root key they subscribed to. */
    private readonly streams;
    constructor(ctx: Context, options: NovelDomainOptions);
    /**
     * Factory for the tool surface: every tool execution derives its own
     * request-scoped client from the dsh session context (fail closed).
     */
    clientFactory(): (exec: ToolRunContext) => StudioClient;
    /** Record a mutation under its root and broadcast only to that root's SSE connections. */
    notifyMutation(path: string, context?: WorkspaceContext): void;
    /** Snapshot of one root's invalidation state (zero revision when never mutated). */
    private snapshotFor;
    /**
     * Best-effort read of the upstream per-root context epoch (the only signal
     * that background task transitions bump). ANY failure — network, non-2xx,
     * missing/invalid field — degrades to null so the caller omits the field;
     * this helper never throws and never breaks a snapshot.
     */
    private fetchContextEpoch;
    /**
     * Resolve a browser-supplied workspace id through the host registry, failing
     * closed per the contract: missing id → 400 WORKSPACE_CONTEXT_MISSING, no
     * registry → 503 WORKSPACE_REGISTRY_UNAVAILABLE, unknown id → 400 WORKSPACE_UNKNOWN.
     */
    /**
     * The workspace a browser view belongs to, for invalidation only.
     *
     * An unknown or absent workspace id resolves to the global bucket rather
     * than to a rejection: the payload of a global path does not depend on the
     * workspace, so a stale id must not turn a readable answer into an error.
     */
    private viewerRoot;
    private resolveBrowserWorkspace;
    private static sendRejection;
    registerWebRoutes(ctx: Context): void;
    private createProxyHandler;
}
