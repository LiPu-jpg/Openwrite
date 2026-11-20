import { UnsupportedRuntimePlatformError } from './managed-runtime.js';
import { mkdir, writeFile } from 'node:fs/promises';
import { join, resolve, win32 } from 'node:path';
import { randomUUID } from 'node:crypto';
import { realpathSync } from 'node:fs';
/** Windows roots are case-insensitive and may use either separator. */
export function workspaceRootsEqual(left, right, platform = process.platform) {
    const normalize = platform === 'win32'
        ? (value) => win32.normalize(value).replace(/[\\/]+$/, '').toLowerCase()
        : (value) => resolve(value);
    return normalize(left) === normalize(right);
}
/** Header OpenWrite requires on every write request (POST/PUT). */
const WRITE_HEADER = 'X-OpenWrite-Studio';
/** HTTP header values are bytes, so Unicode paths need explicit wire encoding.
 * Plain ASCII retains the old contract, including literal percent characters. */
export function workspaceRootHeaders(root, lowercase = false) {
    const name = lowercase ? 'x-openwrite-workspace-root' : 'X-OpenWrite-Workspace-Root';
    return /[^\x20-\x7e]/.test(root)
        ? { [name]: encodeURIComponent(root), [name + (lowercase ? '-encoding' : '-Encoding')]: 'uri' }
        : { [name]: root };
}
/** A normalized Studio failure: HTTP status plus the server's machine-readable code. */
/** Hard ceiling for one download (export / project archive). */
const MAX_DOWNLOAD_BYTES = 256 * 1024 * 1024;
export class StudioError extends Error {
    status;
    code;
    details;
    requestId = null;
    constructor(message, status, code, details = null) {
        super(message);
        this.name = 'StudioError';
        this.status = status;
        this.code = code;
        this.details = details;
    }
}
/** Narrow `JSON.parse` output to the JsonValue union without `any`. */
function asJson(value) {
    // Studio only ever sends JSON; unrepresentable values degrade to null rather
    // than leaking an untyped `any` into tool output.
    return (value === undefined ? null : value);
}
/** Parse a `Content-Disposition: attachment; filename*=UTF-8''...` header. */
function parseDispositionFilename(header) {
    if (header === null)
        return undefined;
    const encoded = /filename\*=UTF-8''([^;]+)/i.exec(header);
    if (encoded?.[1] !== undefined) {
        try {
            return decodeURIComponent(encoded[1]);
        }
        catch {
            // Malformed percent-encoding: fall through to the plain filename form.
        }
    }
    const plain = /filename="?([^";]+)"?/i.exec(header);
    return plain?.[1];
}
/** Set query params on a URL, expanding array values into repeated entries. */
function applyParams(url, params) {
    for (const [key, value] of Object.entries(params)) {
        if (Array.isArray(value)) {
            for (const item of value)
                url.searchParams.append(key, item);
        }
        else {
            url.searchParams.set(key, value);
        }
    }
}
/** Legacy Core fallback; newer servers declare mutation semantics in a response header. */
export function mutationAffectsState(path, body, headers) {
    const declared = headers?.get('X-OpenWrite-Mutated');
    if (declared === '0' || declared === '1')
        return declared === '1';
    const endpoint = path.split('?')[0]?.replace(/^\/+/, '').replace(/^api\//, '');
    if (endpoint === 'review/history')
        return false;
    if (endpoint !== 'manuscript-editing')
        return true;
    let payload = body;
    if (Buffer.isBuffer(payload))
        payload = payload.toString('utf8');
    if (typeof payload === 'string') {
        try {
            payload = JSON.parse(payload);
        }
        catch {
            return true;
        }
    }
    if (payload === null || typeof payload !== 'object' || Array.isArray(payload))
        return true;
    const action = payload['action'];
    return typeof action !== 'string' || !['versions', 'version', 'compare', 'annotations'].includes(action);
}
export class StudioClient {
    connect;
    baseUrl;
    timeoutMs;
    onMutation;
    /** Workspace context stamped onto every request; undefined for legacy (unscoped) clients. */
    context;
    constructor(options) {
        this.connect = options.connect;
        this.baseUrl = options.baseUrl.replace(/\/+$/, '');
        this.timeoutMs = options.timeoutMs;
        this.onMutation = options.onMutation;
        this.context = options.context;
    }
    /**
     * Derive a lightweight request-scoped client sharing baseUrl/timeout/onMutation.
     * Every request it makes carries the §3 context headers, and mutation
     * notifications report this context so invalidation stays per-root.
     */
    scoped(context) {
        return new StudioClient({ connect: this.connect, baseUrl: this.baseUrl, timeoutMs: this.timeoutMs, onMutation: this.onMutation, context });
    }
    /** §3 context headers; empty for a legacy (unscoped) client. */
    contextHeaders() {
        const context = this.context;
        if (context === undefined)
            return {};
        const headers = workspaceRootHeaders(context.workspaceRoot);
        if (context.workspaceId !== undefined)
            headers['X-OpenWrite-Workspace-Id'] = context.workspaceId;
        if (context.sessionId !== undefined)
            headers['X-OpenWrite-Session-Id'] = context.sessionId;
        if (context.contextEpoch !== undefined)
            headers['X-OpenWrite-Context-Epoch'] = String(context.contextEpoch);
        if (context.toolCallId !== undefined)
            headers['X-OpenWrite-Tool-Call-Id'] = context.toolCallId;
        if (context.rootCallId !== undefined)
            headers['X-OpenWrite-Root-Call-Id'] = context.rootCallId;
        if (context.toolName !== undefined)
            headers['X-OpenWrite-Tool-Name'] = context.toolName;
        return headers;
    }
    /** GET a JSON endpoint. `params` entries are URL-encoded; undefined values are dropped. */
    async getJson(path, params = {}, signal) {
        const url = new URL(`${this.baseUrl}${path}`);
        applyParams(url, params);
        const response = await this.request(url, { method: 'GET', headers: this.contextHeaders() }, signal);
        return this.readJson(response);
    }
    /** POST a JSON object with the Studio write protocol header. */
    async postJson(path, body, signal) {
        const response = await this.request(new URL(`${this.baseUrl}${path}`), {
            method: 'POST',
            headers: { [WRITE_HEADER]: '1', ...this.contextHeaders(), 'Content-Type': 'application/json' },
            body: JSON.stringify(body),
        }, signal);
        const result = await this.readJson(response);
        if (mutationAffectsState(path, body, response.headers))
            this.onMutation?.(path, this.context);
        return result;
    }
    /** PUT a JSON object with the Studio write protocol header. */
    async putJson(path, body, signal) {
        const response = await this.request(new URL(`${this.baseUrl}${path}`), {
            method: 'PUT',
            headers: { [WRITE_HEADER]: '1', ...this.contextHeaders(), 'Content-Type': 'application/json' },
            body: JSON.stringify(body),
        }, signal);
        const result = await this.readJson(response);
        if (mutationAffectsState(path, body, response.headers))
            this.onMutation?.(path, this.context);
        return result;
    }
    /** GET a file-download endpoint (export), returning the raw bytes and filename. */
    async download(path, params, signal) {
        const url = new URL(`${this.baseUrl}${path}`);
        applyParams(url, params);
        const response = await this.request(url, { method: 'GET', headers: this.contextHeaders() }, signal);
        if (!response.ok) {
            // Error downloads are still JSON payloads.
            await this.readJson(response);
        }
        // Bound the buffer: an export or project archive is read fully into memory,
        // so an unbounded body is an OOM vector against the host process. Reject on
        // a declared oversize, and on a stream that exceeds the cap mid-read.
        const declared = Number(response.headers.get('content-length') ?? '');
        if (Number.isFinite(declared) && declared > MAX_DOWNLOAD_BYTES) {
            await response.body?.cancel();
            throw new StudioError(`Studio download is too large (${declared} bytes)`, 502, 'DOWNLOAD_TOO_LARGE', { limit: MAX_DOWNLOAD_BYTES });
        }
        const reader = response.body?.getReader();
        if (reader === undefined) {
            const content = new Uint8Array(await response.arrayBuffer());
            if (content.byteLength > MAX_DOWNLOAD_BYTES) {
                throw new StudioError(`Studio download is too large (${content.byteLength} bytes)`, 502, 'DOWNLOAD_TOO_LARGE', { limit: MAX_DOWNLOAD_BYTES });
            }
            return {
                filename: parseDispositionFilename(response.headers.get('content-disposition')) ?? 'export.bin',
                contentType: response.headers.get('content-type') ?? 'application/octet-stream',
                content,
            };
        }
        const chunks = [];
        let total = 0;
        for (;;) {
            const { done, value } = await reader.read();
            if (done !== undefined && done)
                break;
            if (value === undefined)
                continue;
            total += value.byteLength;
            if (total > MAX_DOWNLOAD_BYTES) {
                await reader.cancel().catch(() => { });
                throw new StudioError(`Studio download exceeded ${MAX_DOWNLOAD_BYTES} bytes`, 502, 'DOWNLOAD_TOO_LARGE', { limit: MAX_DOWNLOAD_BYTES });
            }
            chunks.push(value);
        }
        const content = new Uint8Array(total);
        let offset = 0;
        for (const chunk of chunks) {
            content.set(chunk, offset);
            offset += chunk.byteLength;
        }
        return {
            filename: parseDispositionFilename(response.headers.get('content-disposition')) ?? 'export.bin',
            contentType: response.headers.get('content-type') ?? 'application/octet-stream',
            content,
        };
    }
    /** One fetch honoring both the caller's abort signal and the configured timeout. */
    async request(url, init, signal) {
        try {
            // Arm the deadline only once the connection is known. The runtime bootstrap
            // (`connect()`) is deliberately uncapped — a 23 MB archive over a slow link
            // needs minutes — so a timeout started before it turns every cold-start
            // first call into a spurious network error carrying a misleading "the
            // server may have accepted the request" hint.
            const connection = await this.connect?.();
            const signals = [AbortSignal.timeout(this.timeoutMs)];
            if (signal !== undefined)
                signals.push(signal);
            const target = connection ? new URL(url.pathname + url.search, connection.baseUrl) : url;
            const headers = connection?.token ? { ...init.headers, Authorization: `Bearer ${connection.token}` } : init.headers;
            const response = await fetch(target, { ...init, headers, signal: AbortSignal.any(signals) });
            const actual = response.headers.get('X-OpenWrite-Project-Path');
            if (response.ok && actual && this.context?.workspaceRoot) {
                let expected;
                try {
                    expected = realpathSync(this.context.workspaceRoot);
                }
                catch {
                    // The root was deleted or moved mid-session. Letting ENOENT reach the
                    // transport handler would report it as NETWORK_ERROR and write a
                    // diagnostic blaming the network.
                    await response.body?.cancel();
                    throw new StudioError('The requested workspace root no longer exists', 400, 'WORKSPACE_ROOT_INVALID', { requested_path: this.context.workspaceRoot });
                }
                const received = decodeURIComponent(actual);
                if (!workspaceRootsEqual(received, expected)) {
                    await response.body?.cancel();
                    throw new StudioError('Connected workspace differs from requested project', 409, 'WORKSPACE_CONTEXT_MISMATCH', { requested_path: expected, project_path: received });
                }
            }
            return response;
        }
        catch (error) {
            if (error instanceof StudioError)
                throw error;
            if (error instanceof UnsupportedRuntimePlatformError) {
                throw new StudioError(error.message, error.status, error.code, { platform: error.platform });
            }
            // The caller's own abort is a cancellation, not a failure; it must not be
            // rewritten into a StudioError that looks like a transport problem, and it
            // must not race the client's own timeout for the same outcome.
            if (signal?.aborted)
                throw error;
            // Distinguish the deadline we imposed from "the backend is unreachable".
            // Both are ambiguous about whether the server applied a write, but only
            // the timeout carries that meaning, and collapsing them makes an agent
            // retry a write that may already have landed.
            const timedOut = error instanceof Error && (error.name === 'TimeoutError' || error.name === 'AbortError');
            if (this.context?.workspaceRoot) {
                try {
                    const root = join(this.context.workspaceRoot, '.openwrite', 'transport-errors');
                    await mkdir(root, { recursive: true });
                    await writeFile(join(root, `${randomUUID()}.json`), JSON.stringify({
                        source: 'transport', code: timedOut ? 'REQUEST_TIMEOUT' : 'NETWORK_ERROR',
                        created_at: new Date().toISOString(), path: url.pathname,
                        tool_name: this.context.toolName ?? '', tool_call_id: this.context.toolCallId ?? '',
                    }));
                }
                catch { /* A diagnostic failure must not hide the transport failure. */ }
            }
            const cause = error instanceof Error ? error.cause : undefined;
            const detail = cause instanceof Error ? ` (${cause.message})` : cause === undefined ? '' : ` (${String(cause)})`;
            throw new StudioError(`Studio request failed: ${error instanceof Error ? error.message : String(error)}${detail}`, 0, timedOut ? 'REQUEST_TIMEOUT' : 'NETWORK_ERROR');
        }
    }
    /**
     * Read a JSON response, throwing a normalized StudioError for non-2xx statuses
     * and for bodies carrying the server's `{error, code}` contract. Success
     * envelopes (`{ok: true, data}`) are unwrapped to their `data` payload.
     */
    async readJson(response) {
        let parsed;
        try {
            parsed = await response.json();
        }
        catch (error) {
            // The abort signal applies to the body stream too, so a mid-body abort or
            // a truncated body would otherwise surface as INVALID_RESPONSE with the
            // original success status — an error code on a 2xx, which defeats any
            // caller that keys off `status`.
            if (error instanceof Error && (error.name === 'TimeoutError' || error.name === 'AbortError')) {
                throw new StudioError(`Studio response body was not fully received: ${error.message}`, 0, 'REQUEST_TIMEOUT');
            }
            throw new StudioError(`Studio returned HTTP ${response.status} with a non-JSON body`, response.status, 'INVALID_RESPONSE');
        }
        const body = asJson(parsed);
        if (typeof body === 'object' && body !== null && !Array.isArray(body)) {
            const error = body['error'];
            if (error !== undefined && error !== null && error !== false && error !== '') {
                const nested = typeof error === 'object' && !Array.isArray(error) ? error : {};
                const code = typeof body['code'] === 'string' ? body['code'] : typeof nested['code'] === 'string' ? nested['code'] : 'STUDIO_ERROR';
                // Core sends the generic "Request failed (CODE, HTTP n)" envelope in
                // `message` and the actionable reason in `error`. Prefer the message
                // only when it carries real detail; otherwise surface `error`.
                const envelope = typeof body['message'] === 'string' ? body['message'].trim() : '';
                const genericEnvelope = envelope !== '' && /^Request failed \([^)]*\)$/.test(envelope);
                const errorText = typeof error === 'string' && error !== '' ? error : undefined;
                const nestedMessage = typeof nested['message'] === 'string' && nested['message'] !== '' ? nested['message'] : undefined;
                const message = envelope !== '' && !genericEnvelope
                    ? envelope
                    : errorText ?? nestedMessage ?? (envelope !== '' ? envelope : JSON.stringify(error));
                const details = body['details'] ?? nested['details'] ?? null;
                const failure = new StudioError(message, response.status, code, details);
                failure.requestId = typeof body['request_id'] === 'string' ? body['request_id'] : null;
                throw failure;
            }
            // HTTP status remains authoritative even when a proxy or incompatible
            // server sends a success-shaped envelope with an error status.
            if (response.ok && body['ok'] === true && 'data' in body)
                return body['data'];
        }
        if (!response.ok) {
            throw new StudioError(`Studio returned HTTP ${response.status}`, response.status, 'HTTP_ERROR');
        }
        return body;
    }
}
