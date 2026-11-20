import type { AnnotationColor, ManuscriptAnnotation } from './manuscript-annotations.ts';
import type { MarkerSpan } from './manuscript-markers.ts';
import type { EditorSerialization } from './selection-coordinates.ts';
export type OverlayKind = 'note' | 'state' | 'relation' | 'invalid';
export type OverlayBand = {
    kind: OverlayKind;
    start: number;
    end: number;
    needle: string;
    occurrence: number;
    color?: AnnotationColor;
    title: string;
};
/** Display-only bands. Never written back into markdown. */
export declare function overlayBands(content: string, notes: readonly ManuscriptAnnotation[], markers: readonly MarkerSpan[], source?: string, serialization?: EditorSerialization): OverlayBand[];
export declare const OVERLAY_THEME: {
    readonly light: {
        readonly note: {
            readonly amber: "color-mix(in srgb, var(--dsw-alias-state-warn-primary) 48%, transparent)";
            readonly rose: "color-mix(in srgb, var(--dsw-alias-state-error-primary) 42%, transparent)";
            readonly sky: "color-mix(in srgb, var(--dsw-alias-state-business-primary) 42%, transparent)";
            readonly lime: "color-mix(in srgb, var(--dsw-alias-state-success-primary) 42%, transparent)";
            readonly violet: "color-mix(in srgb, var(--dsw-alias-label-primary) 28%, transparent)";
        };
        readonly state: "color-mix(in srgb, var(--dsw-alias-state-business-primary) 26%, transparent)";
        readonly relation: "color-mix(in srgb, var(--dsw-alias-state-warn-primary) 26%, transparent)";
        readonly invalid: "color-mix(in srgb, var(--dsw-alias-state-error-primary) 18%, transparent)";
    };
    readonly dark: {
        readonly note: {
            readonly amber: "color-mix(in srgb, var(--dsw-alias-state-warn-primary) 55%, transparent)";
            readonly rose: "color-mix(in srgb, var(--dsw-alias-state-error-primary) 50%, transparent)";
            readonly sky: "color-mix(in srgb, var(--dsw-alias-state-business-primary) 50%, transparent)";
            readonly lime: "color-mix(in srgb, var(--dsw-alias-state-success-primary) 50%, transparent)";
            readonly violet: "color-mix(in srgb, var(--dsw-alias-label-primary) 34%, transparent)";
        };
        readonly state: "color-mix(in srgb, var(--dsw-alias-state-business-primary) 32%, transparent)";
        readonly relation: "color-mix(in srgb, var(--dsw-alias-state-warn-primary) 32%, transparent)";
        readonly invalid: "color-mix(in srgb, var(--dsw-alias-state-error-primary) 22%, transparent)";
    };
};
export declare function overlayFill(kind: OverlayKind, theme: 'light' | 'dark', color?: AnnotationColor): string;
export declare function overlayUnderline(theme: 'light' | 'dark', color?: AnnotationColor): string;
