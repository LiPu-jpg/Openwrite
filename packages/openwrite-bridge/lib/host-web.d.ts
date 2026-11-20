/**
 * A loopback-only relay onto the host's own `ctx.web` service.
 *
 * OpenWrite's deep research runs as a separate Node process. The host's search
 * and fetch providers (including `web_search` / `web_fetch`) live in the host
 * process, so the child cannot reach them directly. This relay gives it a
 * machine-token HTTP face over exactly those two capabilities; no provider key
 * and no browser session can reach it.
 *
 * `/bocha` exists because the vendored DeepResearch framework already speaks
 * the Bocha search protocol. Mapping one search onto that protocol lets us use
 * the host's search without forking the framework's search-provider union.
 */
export interface HostWebSearchSource {
    url: string;
    title?: string;
    snippet?: string;
    publishedAt?: string;
}
export interface HostWebSearchResult {
    content?: string;
    sources: HostWebSearchSource[];
    truncated?: boolean;
}
export interface HostWebFetchResult {
    url: string;
    statusCode: number;
    body: {
        kind: 'html' | 'text';
        content: string;
    };
    truncated?: boolean;
}
/** Structural view of the host's `web` service (`ctx.get('web')`). */
export interface HostWebService {
    search(request: {
        query: string;
        maxResults?: number;
    }, signal?: AbortSignal): Promise<HostWebSearchResult>;
    fetch(request: {
        url: string;
    }, signal?: AbortSignal): Promise<HostWebFetchResult>;
}
export interface HostWebRelayOptions {
    web: HostWebService;
    /** Machine token; every request must present it as a bearer credential. */
    token: string;
}
export declare class HostWebRelay {
    private readonly options;
    private server?;
    private port;
    private closed;
    constructor(options: HostWebRelayOptions);
    listen(): Promise<void>;
    baseUrl(): string;
    token(): string;
    close(): Promise<void>;
    private authorized;
    private handle;
}
