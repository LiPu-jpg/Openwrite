import type { ModelNavigationGuard } from './ModelView.js';
import type { OperationsViewProps } from './OperationsView.js';
/** Deterministic chapter diagnostics and author-owned serial-writing assets. */
export declare function SerialWritingView({ fetchStudioApi, postStudioApi, t, onNavigationGuardChange, refreshEpoch }: Pick<OperationsViewProps, 'fetchStudioApi' | 'postStudioApi' | 't'> & {
    onNavigationGuardChange?: (guard: ModelNavigationGuard | null) => void;
    refreshEpoch?: number;
}): import("react").JSX.Element;
