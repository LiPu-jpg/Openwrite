import { createServer } from 'node:http';
const BODY_LIMIT_BYTES = 1 * 1024 * 1024;
const REQUEST_TIMEOUT_MS = 120_000;
function json(res, status, payload) {
    const body = JSON.stringify(payload);
    res.writeHead(status, { 'content-type': 'application/json', 'cache-control': 'no-store' });
    res.end(body);
}
async function readJson(req) {
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
    const parsed = JSON.parse(Buffer.concat(chunks).toString('utf8'));
    if (parsed === null || typeof parsed !== 'object' || Array.isArray(parsed))
        throw new Error('request body must be a JSON object');
    return parsed;
}
function nonEmptyString(value) {
    return typeof value === 'string' ? value.trim() : '';
}
/** Normalize the host's search result to the wire shape. */
function searchWire(result) {
    const sources = Array.isArray(result.sources)
        ? result.sources
            .filter(source => source !== null && typeof source === 'object' && nonEmptyString(source.url) !== '')
            .map(source => ({
            url: nonEmptyString(source.url),
            ...(nonEmptyString(source.title) === '' ? {} : { title: nonEmptyString(source.title) }),
            ...(nonEmptyString(source.snippet) === '' ? {} : { snippet: nonEmptyString(source.snippet) }),
            ...(nonEmptyString(source.publishedAt) === '' ? {} : { publishedAt: nonEmptyString(source.publishedAt) }),
        }))
        : [];
    return {
        ...(nonEmptyString(result.content) === '' ? {} : { content: nonEmptyString(result.content) }),
        sources,
        truncated: result.truncated === true,
    };
}
/** Normalize the host's fetch result; body kind and text are always present. */
function fetchWire(result) {
    const kind = result.body?.kind === 'html' ? 'html' : 'text';
    return {
        url: nonEmptyString(result.url),
        statusCode: Number.isInteger(result.statusCode) ? result.statusCode : 0,
        body: { kind, content: typeof result.body?.content === 'string' ? result.body.content : '' },
        truncated: result.truncated === true,
    };
}
/** The Bocha response shape the vendored search provider parses. */
function bochaWire(sources) {
    return {
        code: 200,
        data: {
            webPages: {
                value: sources.map(source => ({
                    name: nonEmptyString(source.title) || nonEmptyString(source.url),
                    url: nonEmptyString(source.url),
                    snippet: nonEmptyString(source.snippet),
                    summary: nonEmptyString(source.snippet),
                })),
            },
        },
    };
}
export class HostWebRelay {
    options;
    server;
    port = 0;
    closed = false;
    constructor(options) {
        this.options = options;
    }
    async listen() {
        if (this.server !== undefined)
            return;
        const server = createServer((req, res) => {
            void this.handle(req, res).catch((error) => {
                if (res.headersSent) {
                    res.end();
                    return;
                }
                json(res, 502, { error: { message: error instanceof Error ? error.message : String(error) } });
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
    baseUrl() {
        return `http://127.0.0.1:${this.port}`;
    }
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
    authorized(req) {
        return req.headers.authorization === `Bearer ${this.options.token}`;
    }
    async handle(req, res) {
        if (!this.authorized(req)) {
            json(res, 401, { error: { message: 'unauthorized' } });
            return;
        }
        if (req.method !== 'POST') {
            json(res, 405, { error: { message: 'method not allowed' } });
            return;
        }
        const url = new URL(req.url ?? '/', 'http://relay');
        const body = await readJson(req);
        const controller = new AbortController();
        const timer = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
        try {
            if (url.pathname === '/search') {
                const query = nonEmptyString(body.query);
                if (query === '')
                    throw new Error('query is required');
                const maxResults = Number.isInteger(body.maxResults) && Number(body.maxResults) > 0 ? Number(body.maxResults) : undefined;
                json(res, 200, searchWire(await this.options.web.search({ query, ...(maxResults === undefined ? {} : { maxResults }) }, controller.signal)));
                return;
            }
            if (url.pathname === '/bocha') {
                const query = nonEmptyString(body.query);
                if (query === '')
                    throw new Error('query is required');
                const count = Number.isInteger(body.count) && Number(body.count) > 0 ? Number(body.count) : 10;
                const result = await this.options.web.search({ query, maxResults: Math.min(count, 50) }, controller.signal);
                json(res, 200, bochaWire(result.sources ?? []));
                return;
            }
            if (url.pathname === '/fetch') {
                const target = nonEmptyString(body.url);
                if (target === '')
                    throw new Error('url is required');
                json(res, 200, fetchWire(await this.options.web.fetch({ url: target }, controller.signal)));
                return;
            }
            json(res, 404, { error: { message: 'not found' } });
        }
        finally {
            clearTimeout(timer);
        }
    }
}
