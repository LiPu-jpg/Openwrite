import type { AssetEditorDraft, AssetEditorSource } from './AssetEditor.tsx';
export interface AssetDraftContext {
    workspaceId: string;
    root: string;
}
export interface AssetDraftIdentity extends AssetDraftContext {
    kind: string;
    id: string;
}
export interface AssetDraftRecord extends AssetDraftIdentity {
    baseRevision: string;
    source: AssetEditorSource;
    draft: AssetEditorDraft;
}
export declare function readAssetDraft(identity: AssetDraftIdentity): AssetDraftRecord | null;
export declare function latestAssetDraft(context: AssetDraftContext): AssetDraftRecord | null;
export declare function writeAssetDraft(record: AssetDraftRecord): boolean;
export declare function removeAssetDraft(identity: AssetDraftIdentity): void;
/** A slow save from an unmounted editor must not erase a newer local draft. */
export declare function removeAssetDraftIfUnchanged(identity: AssetDraftIdentity, saved: AssetEditorDraft): void;
