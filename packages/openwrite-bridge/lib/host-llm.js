import { createServer } from 'node:http';
import { randomBytes, randomUUID } from 'node:crypto';
/** Pseudo model id meaning "whatever dsh itself would use right now". */
export const HOST_CURRENT_MODEL = 'host/current';
const BODY_LIMIT_BYTES = 8 * 1024 * 1024;
const REQUEST_TIMEOUT_MS = 600_000;
function jsonBody(res, status, payload) {
    const body = JSON.stringify(payload);
    res.writeHead(status, { 'content-type': 'application/json', 'cache-control': 'no-store' });
    res.end(body);
}
/** Read a JSON request body under a hard size cap. */
async function readJsonBody(req) {
    const chunks = [];
    let size = 0;
    for await (const chunk of req) {
        size += chunk.length;
        if (size > BODY_LIMIT_BYTES)
            throw new Error('request body too large');
        chunks.push(Buffer.from(chunk));
    }
    if (chunks.length === 0)
        return {};
    return JSON.parse(Buffer.concat(chunks).toString('utf8'));
}
function textOf(content) {
    if (typeof content === 'string')
        return content;
    if (Array.isArray(content)) {
        return content
            .map(part => {
            if (typeof part === 'string')
                return part;
            if (part && typeof part === 'object' && typeof part.text === 'string') {
                return part.text;
            }
            return '';
        })
            .join('');
    }
    return '';
}
/**
 * Translate one OpenAI chat message into the host's message vocabulary.
 *
 * The host distinguishes the producer of a message (`source`), so a plain
 * OpenAI transcript maps onto: system → system-prompt, user → user,
 * assistant → model, tool → tool result.
 */
function toHostMessages(messages, provider, model) {
    return messages.map(message => {
        const id = randomUUID();
        const role = String(message.role || 'user').toLowerCase();
        const text = textOf(message.content);
        if (role === 'system' || role === 'developer') {
            return { id, role: 'system', content: [{ type: 'text', text }], source: { kind: 'system-prompt' } };
        }
        if (role === 'tool') {
            const callId = String(message.tool_call_id || '');
            return {
                id,
                role: 'tool',
                content: [{ type: 'text', text }],
                source: { kind: 'tool', callId },
                toolCallId: callId,
            };
        }
        if (role === 'assistant') {
            const content = [];
            if (text !== '')
                content.push({ type: 'text', text });
            for (const call of message.tool_calls ?? []) {
                content.push({
                    type: 'tool-call',
                    id: String(call.id ?? ''),
                    name: String(call.function?.name ?? ''),
                    arguments: String(call.function?.arguments ?? ''),
                });
            }
            return { id, role: 'assistant', content, source: { kind: 'model', provider, model } };
        }
        return { id, role: 'user', content: [{ type: 'text', text }], source: { kind: 'user' } };
    });
}
/** Translate OpenAI function declarations into the host's tool schema shape. */
function toHostTools(tools) {
    if (!Array.isArray(tools) || tools.length === 0)
        return undefined;
    const converted = [];
    for (const entry of tools) {
        if (!entry || typeof entry !== 'object')
            continue;
        const fn = entry.function;
        const name = String(fn?.name ?? '');
        if (name === '')
            continue;
        converted.push({
            name,
            description: String(fn?.description ?? ''),
            parameters: (fn?.parameters ?? { type: 'object', properties: {} }),
        });
    }
    return converted.length === 0 ? undefined : converted;
}
/** Consume the host's chunk stream into one OpenAI-shaped message. */
async function assemble(chunks) {
    const partials = new Map();
    const order = [];
    let finishReason = 'stop';
    let failureDetail = null;
    let promptTokens = 0;
    let completionTokens = 0;
    let totalTokens = 0;
    const ensure = (index, blockType) => {
        let partial = partials.get(index);
        if (partial === undefined) {
            partial = { blockType, text: '', toolCallId: '', toolCallName: '', toolCallArguments: '' };
            partials.set(index, partial);
            order.push(index);
        }
        return partial;
    };
    for await (const chunk of chunks) {
        if (chunk.type === 'block-start') {
            ensure(chunk.index, chunk.blockType);
        }
        else if (chunk.type === 'text-delta' || chunk.type === 'reasoning-delta') {
            const partial = ensure(chunk.index, chunk.type === 'text-delta' ? 'text' : 'reasoning');
            if (partial.closed !== undefined)
                continue;
            partial.text += chunk.text;
        }
        else if (chunk.type === 'tool-call-delta') {
            const partial = ensure(chunk.index, 'tool-call');
            if (partial.closed !== undefined)
                continue;
            if (chunk.id !== '')
                partial.toolCallId = chunk.id;
            if (chunk.name !== undefined)
                partial.toolCallName = chunk.name;
            partial.toolCallArguments += chunk.argumentsDelta;
        }
        else if (chunk.type === 'block-end') {
            const partial = ensure(chunk.index, chunk.block?.type ?? 'text');
            // First close wins: a re-closed block is a straggler.
            if (partial.closed === undefined)
                partial.closed = chunk.block;
        }
        else if (chunk.type === 'usage') {
            promptTokens = chunk.usage.inputTokens ?? promptTokens;
            completionTokens = chunk.usage.outputTokens ?? completionTokens;
            totalTokens = chunk.usage.totalTokens ?? promptTokens + completionTokens;
        }
        else if (chunk.type === 'finish') {
            const kind = typeof chunk.reason === 'string' ? chunk.reason : String(chunk.reason?.kind ?? 'stop');
            finishReason = kind;
            if (kind === 'error' || kind === 'aborted') {
                const failure = typeof chunk.reason === 'string' ? undefined : chunk.reason?.failure;
                failureDetail = {
                    message: String(failure?.message ?? '宿主模型调用失败'),
                    code: String(failure?.code ?? kind),
                    status: Number(failure?.status ?? 0),
                };
            }
        }
    }
    let content = '';
    let reasoning = '';
    const toolCalls = [];
    for (const index of order) {
        const partial = partials.get(index);
        if (partial === undefined)
            continue;
        const closed = partial.closed;
        const type = closed?.type ?? partial.blockType;
        if (type === 'text')
            content += closed?.text ?? partial.text;
        else if (type === 'reasoning')
            reasoning += closed?.text ?? partial.text;
        else if (type === 'tool-call') {
            toolCalls.push({
                id: closed?.id ?? partial.toolCallId,
                name: closed?.name ?? partial.toolCallName,
                arguments: closed?.arguments ?? partial.toolCallArguments,
            });
        }
    }
    if (toolCalls.length > 0 && failureDetail === null)
        finishReason = 'tool-calls';
    return {
        content,
        reasoning,
        toolCalls,
        finishReason,
        usage: { promptTokens, completionTokens, totalTokens },
        failure: failureDetail,
    };
}
/** Map the host's finish reason onto the OpenAI vocabulary. */
function openAiFinishReason(reason) {
    if (reason === 'tool-calls')
        return 'tool_calls';
    if (reason === 'max-tokens')
        return 'length';
    return 'stop';
}
/**
 * How long one provider's directory may take before the catalog gives up on it.
 *
 * A plugin that registers its own providers resolves its model directory over
 * the network the first time it is asked, so a cold host can make a single
 * provider slow: the our-free-model channel pack fetches each channel's
 * directory with a timeout of its own. The catalog must still answer - a
 * provider that misses the deadline is left out and the rest is returned.
 */
const PROVIDER_DEADLINE_MS = 4000;
/**
 * How long one model's context lookup may take.
 *
 * The context window is decoration on an entry that is otherwise complete, so
 * a slow lookup costs the entry its decoration, never the entry.
 */
const MODEL_DEADLINE_MS = 2000;
/**
 * Resolve a promise, or give up after `ms` milliseconds.
 *
 * The loser is not cancelled - the host owns that promise - but its rejection
 * is swallowed, so a late failure never becomes an unhandled rejection.
 * @param work - the promise to wait for
 * @param ms - how long to wait before giving up
 * @returns the resolved value, or `undefined` when the work was too slow or failed
 */
function withDeadline(work, ms) {
    return new Promise((resolve) => {
        const timer = setTimeout(() => resolve(undefined), ms);
        void work.then((value) => { clearTimeout(timer); resolve(value); }, () => { clearTimeout(timer); resolve(undefined); });
    });
}
export class HostLlmRelay {
    options;
    server;
    port = 0;
    closed = false;
    constructor(options) {
        this.options = options;
    }
    /** Bind the loopback port. Idempotent. */
    async listen() {
        if (this.server !== undefined)
            return;
        const server = createServer((req, res) => {
            void this.handle(req, res).catch(() => {
                if (!res.headersSent)
                    jsonBody(res, 500, { error: { message: 'host relay failed', type: 'server_error' } });
                else
                    res.end();
            });
        });
        await new Promise((resolve, reject) => {
            server.once('error', reject);
            server.listen(0, '127.0.0.1', () => {
                server.removeListener('error', reject);
                resolve();
            });
        });
        const address = server.address();
        this.port = typeof address === 'object' && address !== null ? address.port : 0;
        this.server = server;
    }
    /** The OpenAI-compatible base URL Core should use. */
    baseUrl() {
        return `http://127.0.0.1:${this.port}/v1`;
    }
    /** The machine token Core must present. */
    token() {
        return this.options.token;
    }
    async close() {
        if (this.closed)
            return;
        this.closed = true;
        const server = this.server;
        this.server = undefined;
        if (server === undefined)
            return;
        await new Promise(resolve => server.close(() => resolve()));
    }
    /** The host's model directory, including the models other plugins registered. */
    async catalog() {
        const providers = this.options.llm.listProviders().map(provider => ({ id: provider.id, name: provider.name }));
        // Every provider is asked at once, and every model of that provider at once
        // too. The directory is assembled from plugins that each answer over the
        // network, and asking them one after another made the whole answer as slow
        // as their sum: ten providers that each spend a second on a cold start
        // took ten seconds, and the Core behind this relay gives up after ten.
        // The host's own model catalog asks them in parallel for the same reason.
        const groups = await Promise.all(providers.map(provider => this.providerModels(provider)));
        const models = groups.flat();
        const current = this.options.defaultSelection?.();
        if (current !== undefined && current.provider !== '' && current.model !== '') {
            models.unshift({
                id: HOST_CURRENT_MODEL,
                provider: current.provider,
                model: current.model,
                label: '宿主当前模型',
                description: `${current.provider} · ${current.model}`,
                contextTokens: await this.contextTokens(current.provider, current.model),
            });
        }
        return { available: true, providers, models, current: current ?? null, error: '' };
    }
    /** One provider's models, or none when that provider did not answer in time. */
    async providerModels(provider) {
        const deadline = this.options.providerDeadlineMs ?? PROVIDER_DEADLINE_MS;
        let entries = [];
        try {
            entries = await withDeadline(Promise.resolve(this.options.llm.listModels(provider.id)), deadline) ?? [];
        }
        catch {
            return [];
        }
        return await Promise.all(entries.map(async (entry) => ({
            id: `${provider.id}/${entry.id}`,
            provider: provider.id,
            model: entry.id,
            label: entry.name || entry.id,
            description: entry.description ?? '',
            contextTokens: await this.contextTokens(provider.id, entry.id),
        })));
    }
    /** The route's own context budget, or 0 when the adapter declares none. */
    async contextTokens(provider, model) {
        const resolve = this.options.llm.resolveModelInfo;
        if (typeof resolve !== 'function')
            return 0;
        const deadline = this.options.modelDeadlineMs ?? MODEL_DEADLINE_MS;
        let info;
        try {
            info = await withDeadline(Promise.resolve(resolve.call(this.options.llm, provider, model)), deadline);
        }
        catch {
            return 0;
        }
        const window = Number(info?.context?.contextWindow ?? 0);
        return Number.isFinite(window) && window > 0 ? window : 0;
    }
    /** Split `provider/model`; the first segment is the provider route. */
    resolveRoute(model) {
        const raw = String(model || '').trim();
        if (raw === HOST_CURRENT_MODEL) {
            const selection = this.options.defaultSelection?.();
            if (selection === undefined || selection.provider === '' || selection.model === '') {
                throw new Error('宿主没有配置默认模型');
            }
            return { provider: selection.provider, model: selection.model, reasoningEffort: selection.reasoningEffort };
        }
        const separator = raw.indexOf('/');
        if (separator <= 0 || separator === raw.length - 1) {
            throw new Error(`模型必须写成 provider/model 形式: ${raw}`);
        }
        return { provider: raw.slice(0, separator), model: raw.slice(separator + 1) };
    }
    async handle(req, res) {
        const url = String(req.url ?? '/');
        if (url === '/v1/models') {
            if (!this.authorized(req)) {
                jsonBody(res, 401, { error: { message: 'invalid host relay token', type: 'invalid_request_error' } });
                return;
            }
            if (req.method !== 'GET') {
                jsonBody(res, 405, { error: { message: 'method not allowed', type: 'invalid_request_error' } });
                return;
            }
            const catalog = await this.catalog();
            jsonBody(res, 200, {
                object: 'list',
                data: catalog.models.map(entry => ({
                    id: entry.id,
                    object: 'model',
                    created: 0,
                    owned_by: entry.provider,
                    // Beyond the OpenAI shape: the Core side renders these fields, and
                    // an OpenAI-compatible client simply ignores what it does not know.
                    provider: entry.provider,
                    model: entry.model,
                    label: entry.label,
                    description: entry.description,
                    context_tokens: entry.contextTokens,
                })),
            });
            return;
        }
        if (url === '/v1/chat/completions') {
            if (!this.authorized(req)) {
                jsonBody(res, 401, { error: { message: 'invalid host relay token', type: 'invalid_request_error' } });
                return;
            }
            if (req.method !== 'POST') {
                jsonBody(res, 405, { error: { message: 'method not allowed', type: 'invalid_request_error' } });
                return;
            }
            await this.chatCompletions(req, res);
            return;
        }
        jsonBody(res, 404, { error: { message: 'not found', type: 'invalid_request_error' } });
    }
    authorized(req) {
        const header = req.headers['authorization'];
        const raw = Array.isArray(header) ? header[0] : header;
        if (typeof raw !== 'string')
            return false;
        return raw === `Bearer ${this.options.token}`;
    }
    async chatCompletions(req, res) {
        let payload;
        try {
            payload = (await readJsonBody(req));
        }
        catch {
            jsonBody(res, 400, { error: { message: 'invalid JSON body', type: 'invalid_request_error' } });
            return;
        }
        const messages = Array.isArray(payload.messages) ? payload.messages : [];
        if (messages.length === 0) {
            jsonBody(res, 400, { error: { message: 'messages is required', type: 'invalid_request_error' } });
            return;
        }
        let route;
        try {
            route = this.resolveRoute(String(payload.model ?? ''));
        }
        catch (error) {
            jsonBody(res, 400, { error: { message: error instanceof Error ? error.message : String(error), type: 'invalid_request_error' } });
            return;
        }
        const controller = new AbortController();
        const timer = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
        req.once('close', () => { if (!res.writableEnded)
            controller.abort(); });
        const options = {
            provider: route.provider,
            model: route.model,
            messages: toHostMessages(messages, route.provider, route.model),
        };
        if (typeof payload.temperature === 'number')
            options.temperature = payload.temperature;
        if (typeof payload.max_tokens === 'number')
            options.maxTokens = payload.max_tokens;
        if (Array.isArray(payload.stop) && payload.stop.length > 0)
            options.stop = payload.stop.map(String);
        const tools = toHostTools(payload.tools);
        if (tools !== undefined)
            options.tools = tools;
        // "No reasoning" reaches the Core as an OpenAI-shaped body field, because
        // LiteLLM strips a `reasoning_effort` parameter for a custom model name
        // (drop_params). The host speaks reasoning effort, so translate here: a
        // flash model that keeps reasoning spends the whole output budget on
        // reasoning and answers with an empty "length" stop, which the Core can
        // only read as an unparseable answer.
        const thinkingType = payload.thinking?.type;
        if (typeof thinkingType === 'string' && thinkingType === 'disabled') {
            options.reasoningEffort = 'off';
        }
        else {
            const effort = payload.reasoning_effort ?? route.reasoningEffort;
            if (typeof effort === 'string' && effort !== '')
                options.reasoningEffort = effort;
        }
        options.signal = controller.signal;
        let chunks;
        try {
            chunks = this.options.llm.stream(options);
        }
        catch (error) {
            clearTimeout(timer);
            jsonBody(res, 502, { error: { message: error instanceof Error ? error.message : String(error), type: 'server_error' } });
            return;
        }
        chunks = this.withEffortFallback(options, chunks);
        const completionId = `chatcmpl-${randomUUID()}`;
        const created = Math.floor(Date.now() / 1000);
        const requestedModel = String(payload.model ?? '');
        if (payload.stream === true) {
            res.writeHead(200, { 'content-type': 'text/event-stream', 'cache-control': 'no-store', connection: 'keep-alive' });
            let opened = false;
            // An adapter may stream a block's deltas or only close it. Whatever it
            // did, the client must see the content exactly once.
            const streamedText = new Set();
            const streamedTool = new Set();
            try {
                for await (const chunk of chunks) {
                    if (res.writableEnded)
                        break;
                    if (chunk.type === 'text-delta' && chunk.text !== '') {
                        opened = true;
                        streamedText.add(chunk.index);
                        this.writeChunk(res, completionId, created, requestedModel, { content: chunk.text });
                    }
                    else if (chunk.type === 'tool-call-delta') {
                        opened = true;
                        streamedTool.add(chunk.index);
                        this.writeChunk(res, completionId, created, requestedModel, {
                            tool_calls: [{ index: chunk.index, id: chunk.id, type: 'function', function: { name: chunk.name ?? '', arguments: chunk.argumentsDelta } }],
                        });
                    }
                    else if (chunk.type === 'block-end') {
                        const block = chunk.block;
                        if (block?.type === 'text' && !streamedText.has(chunk.index) && (block.text ?? '') !== '') {
                            opened = true;
                            streamedText.add(chunk.index);
                            this.writeChunk(res, completionId, created, requestedModel, { content: block.text });
                        }
                        else if (block?.type === 'tool-call' && !streamedTool.has(chunk.index)) {
                            opened = true;
                            streamedTool.add(chunk.index);
                            this.writeChunk(res, completionId, created, requestedModel, {
                                tool_calls: [{ index: chunk.index, id: block.id ?? '', type: 'function', function: { name: block.name ?? '', arguments: block.arguments ?? '' } }],
                            });
                        }
                    }
                    else if (chunk.type === 'usage') {
                        this.writeChunk(res, completionId, created, requestedModel, {}, {
                            prompt_tokens: chunk.usage.inputTokens ?? 0,
                            completion_tokens: chunk.usage.outputTokens ?? 0,
                            total_tokens: chunk.usage.totalTokens ?? 0,
                        });
                    }
                    else if (chunk.type === 'finish') {
                        const kind = typeof chunk.reason === 'string' ? chunk.reason : String(chunk.reason?.kind ?? 'stop');
                        if (kind === 'error' || kind === 'aborted') {
                            const failure = typeof chunk.reason === 'string' ? undefined : chunk.reason?.failure;
                            this.writeChunk(res, completionId, created, requestedModel, {}, undefined, undefined, String(failure?.message ?? '宿主模型调用失败'));
                            continue;
                        }
                        this.writeChunk(res, completionId, created, requestedModel, {}, undefined, openAiFinishReason(kind));
                    }
                }
            }
            catch (error) {
                this.writeChunk(res, completionId, created, requestedModel, {}, undefined, undefined, error instanceof Error ? error.message : String(error));
            }
            clearTimeout(timer);
            if (!res.writableEnded) {
                res.write('data: [DONE]\n\n');
                res.end();
            }
            return;
        }
        try {
            const assembled = await assemble(chunks);
            clearTimeout(timer);
            if (assembled.failure !== null) {
                // The host's adapter reported a provider failure. Answering 200 with an
                // empty completion would hide it: the caller would read "the model
                // answered nothing" instead of "the provider refused". The provider's
                // own status travels with it, so a rate limit stays a rate limit.
                const status = assembled.failure.status >= 400 && assembled.failure.status <= 599
                    ? assembled.failure.status
                    : 502;
                jsonBody(res, status, {
                    error: {
                        message: assembled.failure.message,
                        type: 'upstream_error',
                        code: assembled.failure.code,
                    },
                });
                return;
            }
            const message = { role: 'assistant', content: assembled.content };
            if (assembled.toolCalls.length > 0) {
                message['tool_calls'] = assembled.toolCalls.map(call => ({
                    id: call.id,
                    type: 'function',
                    function: { name: call.name, arguments: call.arguments },
                }));
            }
            jsonBody(res, 200, {
                id: completionId,
                object: 'chat.completion',
                created,
                model: requestedModel,
                choices: [{
                        index: 0,
                        message,
                        finish_reason: openAiFinishReason(assembled.finishReason),
                    }],
                usage: {
                    prompt_tokens: assembled.usage.promptTokens,
                    completion_tokens: assembled.usage.completionTokens,
                    total_tokens: assembled.usage.totalTokens,
                },
            });
        }
        catch (error) {
            clearTimeout(timer);
            if (!res.headersSent) {
                jsonBody(res, 502, { error: { message: error instanceof Error ? error.message : String(error), type: 'server_error' } });
            }
            else if (!res.writableEnded) {
                res.end();
            }
        }
    }
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
    async *withEffortFallback(options, first) {
        let current = first;
        for (let attempt = 0; attempt < 2; attempt++) {
            let produced = false;
            let refused = false;
            for await (const chunk of current) {
                if (!produced && chunk.type === 'finish') {
                    const reason = chunk.reason;
                    const kind = typeof reason === 'string' ? reason : String(reason?.kind ?? 'stop');
                    const code = typeof reason === 'string' ? '' : String(reason?.failure?.code ?? '');
                    if (kind === 'error' && code === 'UNSUPPORTED_REASONING_EFFORT' && options.reasoningEffort !== undefined) {
                        refused = true;
                        break;
                    }
                }
                produced = true;
                yield chunk;
            }
            if (!refused)
                return;
            current = this.options.llm.stream({ ...options, reasoningEffort: undefined });
        }
    }
    writeChunk(res, id, created, model, delta, usage, finishReason, errorMessage) {
        if (res.writableEnded)
            return;
        const payload = {
            id,
            object: 'chat.completion.chunk',
            created,
            model,
            choices: [{ index: 0, delta, finish_reason: finishReason ?? null }],
        };
        if (usage !== undefined)
            payload['usage'] = usage;
        if (errorMessage !== undefined)
            payload['error'] = { message: errorMessage, type: 'server_error' };
        res.write(`data: ${JSON.stringify(payload)}\n\n`);
    }
}
/** A fresh machine token for one relay instance. */
export function newRelayToken() {
    return randomBytes(32).toString('hex');
}
