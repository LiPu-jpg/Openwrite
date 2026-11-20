import { type ChildProcess, type SpawnOptions } from 'node:child_process';
import { setTimeout as delay } from 'node:timers/promises';
interface Download {
    url: string;
    sha256: string;
    executable: string;
}
export interface RuntimeManifest {
    schema: number;
    dsh: string;
    python_version: string;
    core_version: string;
    contract_version: number;
    platforms: Record<string, {
        uv: Download;
        python: Download;
    }>;
    wheel: {
        file: string;
        sha256: string;
    };
    requirements: {
        file: string;
        sha256: string;
    };
    dependency_wheels?: Array<{
        file: string;
        sha256: string;
    }>;
}
export type RuntimePhase = 'idle' | 'waiting' | 'downloading' | 'installing' | 'starting' | 'ready' | 'recovering' | 'cancelled' | 'error' | 'stopped' | 'uninstalled';
export interface RuntimeStatus {
    phase: RuntimePhase;
    message: string;
    downloadedBytes?: number;
    totalBytes?: number;
    error?: string;
}
export interface BackendConnection {
    baseUrl: string;
    token?: string;
}
export declare class UnsupportedRuntimePlatformError extends Error {
    readonly platform: string;
    readonly code = "RUNTIME_PLATFORM_UNSUPPORTED";
    readonly status = 503;
    constructor(platform: string);
}
export type SpawnFn = (command: string, args: readonly string[], options: SpawnOptions) => ChildProcess;
export interface RuntimeOptions {
    /** Prepared Python >=3.10. Dependencies belong to the author; Core stays in our own directory. */
    pythonPath?: string;
    /** Explicit dependency directories, e.g. an Android author's prepared pyroot. */
    pythonModulePaths?: string[];
    spawn?: SpawnFn;
    delay?: typeof delay;
    restartLimit?: number;
    backoffMs?: number[];
    /**
     * The host's OpenAI-compatible relay, handed to Core over the stdio
     * handshake. Core needs it to call the models dsh itself can reach; the
     * relay address is ephemeral, so it is resolved per start, never cached.
     */
    hostLlm?: () => Promise<HostLlmHandshake | undefined> | HostLlmHandshake | undefined;
    /** The host's search/fetch relay, handed to Core over the same handshake. */
    hostWeb?: () => Promise<HostWebHandshake | undefined> | HostWebHandshake | undefined;
}
/** The relay coordinates Core receives in its private startup handshake. */
export interface HostLlmHandshake {
    /** OpenAI-compatible base URL of the relay. */
    url: string;
    /** Machine token the relay requires as a bearer credential. */
    token: string;
}
/** The host's web search/fetch relay coordinates. */
export interface HostWebHandshake {
    url: string;
    token: string;
}
export declare const DEFAULT_RESTART_LIMIT = 5;
export declare const DEFAULT_BACKOFF_MS: number[];
export declare function sha256(file: string): Promise<string>;
/** Diagnostics must not echo provider credentials or authenticated download URLs. */
export declare function sanitizeDiagnostic(message: string): string;
/**
 * Drop bracketed IPv6 literals (e.g. `[::1]`) from a no_proxy value. DSH's
 * loopback bypass list is written for undici as well as generic consumers, but
 * httpx parses each entry as host:port and fails at client construction with
 * `Invalid port: ':1]'`, so the request never leaves the process. Plain
 * entries such as `::1` stay — httpx handles them fine.
 */
export declare function sanitizeNoProxy(value: string): string;
/** Windows needs SystemRoot/PATH to start; proxy and CA vars stay when set. Credential names never copy. */
export declare function buildChildEnv(source: NodeJS.ProcessEnv, extra?: Record<string, string | undefined>): NodeJS.ProcessEnv;
/** Stop only a child we spawned. POSIX groups and Windows trees include grandchildren. */
export declare function stopOwnedProcess(child: ChildProcess): Promise<void>;
/** All artifacts and children belong to this instance; author files never enter this tree. */
export declare class ManagedRuntime {
    readonly root: string;
    readonly artifacts: string;
    private state;
    private pending?;
    private controller?;
    private child?;
    private connection?;
    private closed;
    private allowRevive;
    private cancelEpoch;
    private generation;
    private restartAttempts;
    private recovered;
    private readonly spawnFn;
    private readonly wait;
    private readonly restartLimit;
    private readonly backoffMs;
    private readonly pythonPath?;
    private readonly pythonModulePaths;
    private readonly hostLlm?;
    private readonly hostWeb?;
    constructor(root: string, artifacts: string, options?: RuntimeOptions);
    status(): RuntimeStatus;
    private update;
    ensure(): Promise<BackendConnection>;
    /**
     * The child process can outlive its listening socket (a stuck request thread
     * during shutdown leaves it alive but refusing connections), and no exit is
     * ever observed in that state, so the auto-restart logic never fires. Probe
     * the cached connection before handing it out; a dead backend is torn down
     * forcefully and pushed through the normal recovery path.
     */
    private verifyConnection;
    /**
     * The host relay coordinates, if the host offers one.
     *
     * A relay that cannot be reached is not a startup failure: Core still runs,
     * it simply has no host models to offer. The failure is silent on purpose —
     * the relay's own diagnostics belong to the host, not to the backend boot.
     */
    private resolveHostLlm;
    private resolveHostWeb;
    /**
     * Liveness with three outcomes. `dead` is only returned on positive evidence —
     * the child exited, or the connection was refused, or health answered
     * non-ok (auth drift). A probe that timed out returns `unknown`, because a
     * busy backend is indistinguishable from a hung one at a 1.5 s deadline and
     * killing the former destroys in-flight work.
     */
    private probeLiveness;
    cancel(): Promise<void>;
    dispose(): Promise<void>;
    private exitDiagnostic;
    private handleReadyExit;
    private live;
    private queueRestart;
    private recover;
    private download;
    /**
     * Restricted networks throttle single connections to GitHub releases to a
     * few dozen KB/s, so a fixed total timeout can never finish a 23 MB runtime
     * archive (OpenWrite issue #82). Try the origin first, then optional mirror
     * prefixes; every candidate is verified against the manifest checksum, so a
     * mirror cannot substitute content. OPENWRITE_DOWNLOAD_MIRRORS overrides the
     * prefix list (empty disables mirrors); the slow-start window uses
     * OPENWRITE_DOWNLOAD_SLOW_MS / OPENWRITE_DOWNLOAD_SLOW_BYTES.
     */
    private downloadInto;
    /**
     * One download attempt against a single source. A source that stays below
     * the byte threshold through the grace window is abandoned for the next
     * candidate, and a transfer that stops progressing is cut by an idle
     * timeout — there is deliberately no total-duration cap.
     */
    private downloadFrom;
    private extract;
    private command;
    /** Shared Android/embedded Python may need its host's native-library search paths. */
    private pythonLibraryEnv;
    private lock;
    private prepare;
    private start;
}
export {};
