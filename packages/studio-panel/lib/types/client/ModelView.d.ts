import type { PropsLocale } from "@deepseek-ai/dsh-client-ui-slots";
import { type StudioApiInjected } from "./api.ts";
export type ModelNavigationGuard = (navigate: () => void) => void;
/**
 * The model profile library is global: Studio keeps it outside every project
 * and registers every model route with `requires_project=False`.
 *
 * Two hosts render this panel:
 *
 * - the workbench, which injects the project-scoped API;
 * - the host's settings dialog, which is opened with no bound workspace and
 *   therefore reaches the same library through the context-free global API.
 *
 * When nothing is injected the panel falls back to the global calls — the
 * library it edits is the same file either way.
 */
export type ModelViewProps = {
    fetchStudioApi?: StudioApiInjected["fetchStudioApi"];
    postStudioApi?: StudioApiInjected["postStudioApi"];
    refreshNonce?: number;
} & PropsLocale<"studio-panel"> & {
    onNavigationGuardChange?: (guard: ModelNavigationGuard | null) => void;
};
type Props = ModelViewProps;
/**
 * Forget every cached model draft and pending save.
 *
 * The model library is global, so its draft slot is global too — which means
 * a draft can outlive the panel that wrote it. The test layer calls this
 * between cases so one case's draft never reaches the next.
 */
export declare function resetModelViewMemory(): void;
export declare function ModelView({ fetchStudioApi: injectedFetch, postStudioApi: injectedPost, refreshNonce, t, onNavigationGuardChange }: Props): import("react").JSX.Element;
export {};
