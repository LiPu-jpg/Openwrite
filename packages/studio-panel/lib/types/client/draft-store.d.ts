/** IndexedDB-backed recovery drafts for manuscript documents. */
export declare const MANUSCRIPT_DRAFT_FORMAT_VERSION: 1;
export interface ManuscriptDraftIdentity {
    workspaceId: string;
    novelId: string;
    path: string;
}
export interface ManuscriptDraftRecord extends ManuscriptDraftIdentity {
    key: string;
    formatVersion: typeof MANUSCRIPT_DRAFT_FORMAT_VERSION;
    baseRevision: string;
    content: string;
    updatedAt: number;
}
export interface ManuscriptDraftStore {
    load: (identity: ManuscriptDraftIdentity) => Promise<ManuscriptDraftRecord | null>;
    save: (record: ManuscriptDraftRecord) => Promise<void>;
    remove: (identity: ManuscriptDraftIdentity) => Promise<void>;
    removeIfContent: (identity: ManuscriptDraftIdentity, content: string) => Promise<boolean>;
}
export declare class ManuscriptDraftStorageError extends Error {
    constructor(message: string, options?: ErrorOptions);
}
export declare function manuscriptDraftKey(identity: ManuscriptDraftIdentity): string;
export declare function manuscriptNovelId(workspacePayload: unknown, path: string): string;
export declare const manuscriptDraftStore: ManuscriptDraftStore;
