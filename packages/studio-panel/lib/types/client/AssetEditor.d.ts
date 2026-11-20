/**
 * Asset editor + create form for the 资产 tab. The write surface is exactly
 * the server's contract (verified against OpenWrite tools/structured_assets.py
 * create/update and tools/studio_application.py create_asset/update_asset):
 *
 * - Update: POST /api/assets/update { kind, id, revision, data } — `revision`
 *   is the optimistic lock (the detail's fingerprint); a stale revision
 *   answers 409 ASSET_CONFLICT. `data` merges into the front matter, filtered
 *   server-side to CHARACTER_FIELDS / WORLD_FIELDS (character: name, aliases,
 *   tier, summary, tags, personality, goal, fear, taboos, appearance, voice,
 *   current_state, organization, progression_system, progression_stage,
 *   detail_refs, related; world: name, kind, type, subtype, summary, status,
 *   tags, detail_refs, related). Relations edit through data.related as
 *   strings or { target, kind, note } dicts. Progression merges data into the
 *   YAML document (absent keys, e.g. stages, are preserved).
 * - Create: POST /api/assets { kind, id, data } — id must match
 *   [A-Za-z0-9][A-Za-z0-9_.-]{0,79}; progression requires a non-empty stages
 *   list of { id, name } and kind in ability/rank/cultivation/career/
 *   reputation/curse/custom.
 */
import type { PropsLocale } from '@deepseek-ai/dsh-client-ui-slots';
/** The summary fields the editor needs from the parsed detail. */
export interface AssetEditorSource {
    name: string;
    summary: string;
    aliases: string[];
    tags: string[];
    scalars: {
        key: string;
        value: string;
    }[];
    /** List-typed whitelist fields (taboos/detail_refs), edited one entry per line. */
    lists: {
        key: string;
        items: string[];
    }[];
    related: RelationDraft[];
    /** The markdown body (body_markdown), edited with a preview toggle. */
    body: string;
    /**
     * Derived relations (incoming edges and annotation-sourced entries) shown
     * read-only in the editor. They live in OTHER assets' front matter (or in
     * body annotations), so they are not editable here — but hiding them made
     * the editor look broken next to the read view, which shows them.
     */
    derivedRelations: DerivedRelation[];
}
/** One derived (non-editable) relation row for editor display. */
export interface DerivedRelation {
    name: string;
    note: string;
    direction: 'outgoing' | 'incoming';
    origin: string;
}
/** One editable frontmatter relation row. */
export interface RelationDraft {
    target: string;
    kind: string;
    note: string;
}
/** A relation-target candidate from the loaded asset list. */
export interface RelationCandidate {
    id: string;
    name: string;
    kind: string;
}
type TFunc = PropsLocale<'studio-panel'>['t'];
/**
 * Localized label for any front-matter field key (edit form + read field
 * table). List-typed keys delegate to the 索引 labels; unmapped keys fall
 * back to the raw key — unknown fields are never hidden.
 */
export declare function fieldLabel(key: string, t: TFunc): string;
interface AssetEditorProps {
    kind: string;
    /** Current values from the freshly loaded detail (remount on epoch change resets the draft). */
    source: AssetEditorSource;
    candidates: readonly RelationCandidate[];
    saving: boolean;
    saveError: string | null;
    conflict: boolean;
    onSave: (data: Record<string, unknown>, bodyMarkdown: string) => void;
    /** Single-field autosave on blur (Obsidian-style): AssetsView owns the revision chain. */
    onFieldSave: (field: string, value: unknown) => void;
    /** The field key whose single-field save is in flight (input stays interactive otherwise). */
    fieldBusy: string | null;
    onCancel: () => void;
    onRefresh: () => void;
    onDirtyChange?: (dirty: boolean) => void;
    initialDraft?: AssetEditorDraft | undefined;
    onDraftChange?: (draft: AssetEditorDraft, dirty: boolean) => void;
    t: TFunc;
}
export interface AssetEditorDraft {
    name: string;
    summary: string;
    aliasesText: string;
    tagsText: string;
    scalars: Record<string, string>;
    related: RelationDraft[];
    listsText: Record<string, string>;
    newTarget: string;
    newNote: string;
    bodyDraft: string;
}
/** Read-write editor over one asset's allowed front-matter fields. */
export declare function AssetEditor({ kind, source, candidates, saving, saveError, conflict, onSave, onFieldSave, fieldBusy, onCancel, onRefresh, onDirtyChange, initialDraft, onDraftChange, t }: AssetEditorProps): import("react").JSX.Element;
interface NewAssetFormProps {
    kind: 'character' | 'world' | 'progression';
    busy: boolean;
    error: string | null;
    onSubmit: (payload: {
        id: string;
        data: Record<string, unknown>;
    }) => void;
    onCancel: () => void;
    onDirtyChange?: (dirty: boolean) => void;
    t: TFunc;
}
/** Inline create form for one asset kind (minimal required fields per the server contract). */
export declare function NewAssetForm({ kind, busy, error, onSubmit, onCancel, onDirtyChange, t }: NewAssetFormProps): import("react").JSX.Element;
export {};
