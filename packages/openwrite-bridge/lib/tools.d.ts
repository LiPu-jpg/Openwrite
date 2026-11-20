/**
 * The `novel_*` tool definitions bridging dsh agents to the OpenWrite Studio
 * HTTP action surface. Payload shapes are verified against OpenWrite
 * `tools/studio_http.py` (POST_ROUTES / do_GET / do_PUT) and
 * `tools/studio_application.py` (the dispatched methods).
 */
import type { Context } from '@deepseek-ai/cordis';
import { type ToolRunContext } from '@deepseek-ai/dsh-tools';
import type { StudioClient, WorkspaceContext } from './client.js';
/** Plugin-level config the tools need beyond the HTTP client. */
export interface NovelToolsOptions {
    /** Cooperative per-call budget (ms), attached as each tool's `timeoutMs`. */
    timeoutMs: number;
    /** Directory `novel_export` saves downloaded files into. */
    outputDir: string;
}
/**
 * Derive the request-scoped Workspace context from the tool execution, failing
 * closed (docs/WORKSPACE_CONTEXT_CONTRACT.md §2.1): the stamped session cwd is
 * the only root source — never a fallback to the plugin cwd or a fixed project.
 */
export declare function workspaceContextFromExec(exec: ToolRunContext): WorkspaceContext;
/** Register every `novel_*` tool into the host tools registry. */
export declare function registerNovelTools(ctx: Context, clientFactory: (exec: ToolRunContext) => StudioClient, options: NovelToolsOptions): void;
