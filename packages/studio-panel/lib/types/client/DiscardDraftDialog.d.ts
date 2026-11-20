import type { StudioPanelKey } from './locales.ts';
export interface DiscardDraftDialogProps {
    onKeep: () => void;
    onDiscard: () => void;
    t: (key: StudioPanelKey) => string;
}
/** Mount while a navigation action is waiting for the draft decision. */
export declare function DiscardDraftDialog({ onKeep, onDiscard, t }: DiscardDraftDialogProps): import("react").JSX.Element;
