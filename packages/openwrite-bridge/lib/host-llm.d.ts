/**
 * A loopback-only, OpenAI-compatible relay onto the host's own model
 * directory.
 *
 * OpenWrite's Core speaks the OpenAI chat-completions protocol (LiteLLM), so
 * giving it a plain HTTP endpoint is enough to make every model dsh itself can
 * reach — the host's own adapters and the models other plugins register into
 * the same directory — usable from a writing task. The relay never sees a
 * provider key: the host's `llm` service owns the credentials and performs the
 * call, so the relay only translates a request shape.
 *
 * The relay is deliberately NOT mounted on the host's web server. That port is
 * browser-authenticated and possibly reachable from the LAN; this one is bound
 * to 127.0.0.1 on an ephemeral port and answers only to a machine token that
 * is handed to the Core process over its private stdio handshake.
 */
/** Structural view of the host's `llm` service (`ctx.get('llm')`). */
export interface HostLlmService {
    listProviders(): Array<{
        id: string;
        name: string;
    }>;
    listConfigurableProviders?(): Array<{
        provider: string;
        displayName: string;
        settingsNs: string;
    }>;
    listModels(provider: string): Promise<Array<{
        provider: string;
        id: string;
        name: string;
        description?: string;
    }>>;
    resolveModelInfo?(provider: string, model: string, signal?: AbortSignal): Promise<{
        context?: {
            contextWindow?: number;
        };
    }>;
    stream(options: HostGenerateOptions): AsyncIterable<HostStreamChunk>;
}
/** Why the host's model call stopped. A failure carries the provider's words. */
export interface HostFinishReason {
    kind: 'stop' | 'tool-calls' | 'max-tokens' | 'aborted' | 'error' | string;
    failure?: {
        message?: string;
        code?: string;
        status?: number;
    };
}
export interface HostGenerateOptions {
    provider: string;
    model: string;
    messages: unknown[];
    temperature?: number;
    maxTokens?: number;
    stop?: string[];
    tools?: unknown[];
    reasoningEffort?: string;
    signal?: AbortSignal;
}
export type HostStreamChunk = {
    type: 'block-start';
    index: number;
    blockType: string;
} | {
    type: 'text-delta';
    index: number;
    text: string;
} | {
    type: 'reasoning-delta';
    index: number;
    text: string;
} | {
    type: 'tool-call-delta';
    index: number;
    id: string;
    name?: string;
    argumentsDelta: string;
} | {
    type: 'block-end';
    index: number;
    block: {
        type: string;
        text?: string;
        id?: string;
        name?: string;
        arguments?: string;
    };
} | {
    type: 'usage';
    usage: {
        inputTokens?: number;
        outputTokens?: number;
        totalTokens?: number;
    };
} | {
    type: 'finish';
    reason: string | HostFinishReason;
};
/** The host's own default-model selection, when the host composes that service. */
export type HostDefaultSelection = () => {
    provider: string;
    model: string;
    reasoningEffort?: string;
} | undefined;
/** Pseudo model id meaning "whatever dsh itself would use right now". */
export declare const HOST_CURRENT_MODEL = "host/current";
/** One directory entry the Core side renders as a selectable model. */
export interface HostModelEntry {
    /** `provider/model` route, or {@link HOST_CURRENT_MODEL}. */
    id: string;
    provider: string;
    model: string;
    label: string;
    description: string;
    /** The route's own context budget, when the adapter declares one. */
    contextTokens: number;
}
export interface HostModelCatalog {
    available: boolean;
    providers: Array<{
        id: string;
        name: string;
    }>;
    models: HostModelEntry[];
    /** Present when the host composes a default-model service. */
    current: {
        provider: string;
        model: string;
    } | null;
    error: string;
}
export interface HostLlmRelayOptions {
    llm: HostLlmService;
    /** Machine token; every request must present it as a bearer credential. */
    token: string;
    /** The host's default-model selection, when the host composes that service. */
    defaultSelection?: HostDefaultSelection;
    /**
     * How long one provider's directory may take before the catalog gives up on
     * it. Overridable so the gate can be exercised without waiting for it.
     */
    providerDeadlineMs?: number;
    /**
     * How long one model's context lookup may take. It is optional metadata, so
     * a slow lookup must cost the entry its context window, never the entry.
     */
    modelDeadlineMs?: number;
}
export declare class HostLlmRelay {
    private readonly options;
    private server?;
    private port;
    private closed;
    constructor(options: HostLlmRelayOptions);
    /** Bind the loopback port. Idempotent. */
    listen(): Promise<void>;
    /** The OpenAI-compatible base URL Core should use. */
    baseUrl(): string;
    /** The machine token Core must present. */
    token(): string;
    close(): Promise<void>;
    /** The host's model directory, including the models other plugins registered. */
    catalog(): Promise<HostModelCatalog>;
    /** One provider's models, or none when that provider did not answer in time. */
    private providerModels;
    /** The route's own context budget, or 0 when the adapter declares none. */
    private contextTokens;
    /** Split `provider/model`; the first segment is the provider route. */
    private resolveRoute;
    private handle;
    private authorized;
    private chatCompletions;
    /**
     * Retry once without the reasoning effort when the host refuses it.
     *
     * A model that declares no reasoning support rejects an explicit effort
     * (the host reports `UNSUPPORTED_REASONING_EFFORT` as a terminal finish).
     * Asking for "no reasoning" must never turn into a failed call, so the
     * second attempt drops the effort and lets the provider decide. The retry
     * only happens before any content was produced: the refusal arrives as the
     * first chunk, so nothing has been written to the client yet.
     */
    private withEffortFallback;
    private writeChunk;
}
/** A fresh machine token for one relay instance. */
export declare function newRelayToken(): string;
