/**
 * OpenWrite's page in the host's settings dialog.
 *
 * The host dialog is the one surface the author opens without a novel in
 * front of them, so this page owns every setting that is not tied to one
 * work: the writing environment, the model profile library (global by
 * design), the host's current model, and the companion plugins.
 *
 * The groups are tabs, the way `dsh-our-free-model` groups its own page: one
 * section, several groups, and the chosen group survives a dialog reopen.
 *
 * Every fact here comes from a host route that does not need a bound
 * workspace. The model library is global too — Studio keeps it outside every
 * project — so it is reached through the context-free global API.
 */
import type { PropsLocale } from '@deepseek-ai/dsh-client-ui-slots';
import { type CompanionStatus } from './companions.js';
import { type HostModelCatalogDto } from './dto.ts';
import type { StudioPanelKey } from './locales.ts';
/** The host's default-model selection, as the host's own route reports it. */
export interface HostModelSelection {
    available: boolean;
    provider: string;
    model: string;
    reasoningEffort: string;
}
/** The writing environment's lifecycle, as the host's runtime route reports it. */
export interface RuntimeStatus {
    phase: string;
    message: string;
    error?: string;
    downloadedBytes?: number;
    totalBytes?: number;
}
/** The Studio backend the bridge talks to. */
export interface StudioBackend {
    studioUrl: string;
    managed: boolean;
    available?: boolean;
}
/** The groups of this page, in the order they are shown. */
export type OpenWriteSettingsTab = 'environment' | 'models' | 'search' | 'host';
/** The host's default model selection. Null when the route is unreachable. */
export declare function fetchHostModel(signal?: AbortSignal): Promise<HostModelSelection | null>;
/**
 * The host's own model directory.
 *
 * The host owns the adapters — its own providers and the ones other plugins
 * register into the same registry — so this is what dsh itself can call. The
 * list is read through the backend's machine channel; the browser never sees
 * the relay's token.
 */
export declare function fetchHostModelCatalog(signal?: AbortSignal): Promise<HostModelCatalogDto | null>;
/** The writing environment's status. Null when the route is unreachable. */
export declare function fetchRuntimeStatus(signal?: AbortSignal): Promise<RuntimeStatus | null>;
/** The Studio backend address. Null when the route is unreachable. */
export declare function fetchStudioBackend(signal?: AbortSignal): Promise<StudioBackend | null>;
/**
 * Ask the host to act on the writing environment.
 *
 * `prepare` and `retry` reach the same server-side action; the caller picks
 * the word that matches the phase it is looking at. `cancel` stops a run that
 * is already under way.
 */
export declare function postRuntimeAction(action: 'prepare' | 'retry' | 'cancel'): Promise<RuntimeStatus | null>;
/** The upstream open-source repository for stars and issue reports. */
export declare const GITHUB_REPO_URL = "https://github.com/LiPu-jpg/Openwrite";
/**
 * Strip user-identifying home paths and accidental credentials from a
 * diagnostic string before showing it in the copyable bug-report block or
 * pre-filling a GitHub issue URL.
 */
export declare function sanitizeDiagnosticText(input: string): string;
/**
 * Build a privacy-safe diagnostic summary containing only environment, host,
 * and companion metadata — never novel manuscripts, outlines, character/world
 * assets, workspace paths, or API keys.
 */
export declare function formatDiagnosticReport(runtime: RuntimeStatus | null, backend: StudioBackend | null, hostModel: HostModelSelection | null, companions: CompanionStatus | null): string;
export type FeedbackCategory = 'bug' | 'install' | 'model' | 'feature';
export interface FeedbackDraft {
    category: FeedbackCategory;
    title: string;
    description: string;
}
export interface FeedbackFinding {
    key: StudioPanelKey;
    list?: string;
    severity: 'info' | 'warn';
}
/**
 * Inspect current runtime/backend/model/companion states and surface actionable
 * local self-checks before the author files an upstream GitHub issue.
 */
export declare function analyzeFeedbackHealth(runtime: RuntimeStatus | null, backend: StudioBackend | null, hostModel: HostModelSelection | null, companions: CompanionStatus | null): FeedbackFinding[];
/** Validate that a feedback draft has a real title and description before opening GitHub. */
export declare function validateFeedbackDraft(draft: FeedbackDraft): {
    valid: boolean;
    errorKey: StudioPanelKey | null;
};
/** Build a sanitized title and Markdown body from a guided feedback draft. */
export declare function formatFeedbackMarkdown(diagnosticReport: string, draft: FeedbackDraft): {
    title: string;
    body: string;
};
/** Result of dispatching a `/feedback` prompt directly into the host's Agent Loop. */
export type FeedbackAgentDispatchResult = {
    status: 'dispatched';
    sessionId: string;
} | {
    status: 'fallback';
    reason?: string;
};
export interface OpenWriteSettingsProps extends PropsLocale<'studio-panel'> {
    onDispatchFeedbackToAgent?: (prompt: string) => Promise<FeedbackAgentDispatchResult>;
}
/** Build a sanitized `/feedback` prompt for the host Agent Loop. */
export declare function buildAgentFeedbackPrompt(diagnosticReport: string, draft?: Partial<FeedbackDraft>): string;
/** Pre-fill a GitHub issue URL with the sanitized diagnostic summary (and optional guided draft). */
export declare function buildGitHubIssueUrl(diagnosticReport: string, draft?: FeedbackDraft): string;
export declare function OpenWriteSettings({ t, onDispatchFeedbackToAgent }: OpenWriteSettingsProps): JSX.Element;
