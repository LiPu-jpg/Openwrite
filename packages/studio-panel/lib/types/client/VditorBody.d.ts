/**
 * Vditor live (IR) body editor. The engine is vendored with this plugin and
 * served by the dsh host at a same-origin route; Studio remains a headless
 * domain backend and never supplies browser assets.
 *
 * Mirrors Studio's options: mode 'ir', lang zh_CN, cache off, dark theme
 * mapped from the dsh shell's `body[data-ds-dark-theme]` (ui-theme's
 * boot-theme contract) — classic when light, dark when dark, with a
 * MutationObserver following live theme switches. Toolbar is Studio's
 * compact subset plus headings/code/table (card-body scope).
 */
import type { PropsLocale } from '@deepseek-ai/dsh-client-ui-slots';
import type { EditorSerialization } from './selection-coordinates.ts';
import { type ManuscriptSelection } from './manuscript-selection.ts';
import type { ManuscriptAnnotation } from './manuscript-annotations.ts';
/** The slice of the bundled Vditor API this editor uses. */
interface VditorInstance {
    getValue: () => string;
    getSelection?: () => string;
    insertValue?: (value: string, render?: boolean) => void;
    setTheme: (theme: string, contentTheme?: string, codeTheme?: string, contentThemePath?: string) => void;
    destroy: () => void;
}
type VditorCtor = new (host: HTMLElement, options: Record<string, unknown>) => VditorInstance;
type TFunc = PropsLocale<'studio-panel'>['t'];
/**
 * Attach Vditor's packaged CSS and resolve the constructor bundled into this
 * plugin. Auxiliary language/theme assets continue to use the same-origin
 * vendor route.
 */
export declare function loadVditor(): Promise<VditorCtor>;
export type ManuscriptEditorApi = {
    getValue: () => string;
    getSerialization: () => EditorSerialization | undefined;
    flush: () => void;
    insertAtCaret: (markdown: string) => void;
    revealQuote: (quote: string, start: number) => boolean;
};
interface VditorBodyProps {
    /** Initial markdown (the editor is the source of truth afterwards). */
    initial: string;
    onChange: (value: string) => void;
    onInputStateChange?: (pending: boolean) => void;
    onSelectionChange?: (selection: ManuscriptSelection | null) => void;
    onReady?: () => void;
    onFailed: (cause?: unknown) => void;
    disabled: boolean;
    /** The consumer can synchronously retain callbacks delivered during cleanup. */
    flushOnLeave?: boolean;
    annotations?: readonly ManuscriptAnnotation[];
    annotationSource?: string;
    onInsertMarker?: () => void;
    onEditorApi?: (api: ManuscriptEditorApi | null) => void;
}
/** One Vditor IR instance bound to the shell theme; destroyed on unmount. */
export declare function VditorBody({ initial, onChange, onInputStateChange, onSelectionChange, onReady, onFailed, disabled, flushOnLeave, annotations, annotationSource, onInsertMarker, onEditorApi, }: VditorBodyProps): import("react").JSX.Element;
/** Loading line shown while the Vditor script is in flight. */
export declare function VditorLoading({ t }: {
    t: TFunc;
}): import("react").JSX.Element;
export {};
