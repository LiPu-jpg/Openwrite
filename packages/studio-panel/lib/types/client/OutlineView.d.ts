/**
 * Outline view (大纲): the OpenWrite outline tree rendered natively — AND
 * editable in place, Obsidian-style: titles and body blocks render as
 * borderless inputs that look identical to plain text; click into them and
 * type. Commits ride the revision-guarded atomic tree editor
 * (POST /api/outline/edit; operations verified against OpenWrite
 * tools/outline_tree.py mutate_outline_structure):
 *
 * - title input  blur/Enter → rename        (chapters must carry a number)
 * - body textarea blur       → update_summary (updates prose synopsis, preserving metadata)
 * - hover buttons → add_child / add_after / delete (server renumbers on delete)
 * - toolbar      → add a top-level volume (add_child with empty node_id)
 *
 * Commit semantics: optimistic local patch + silent revision bump on success
 * (no tree re-render — focus and scroll survive); 409 reloads the tree and
 * asks for a retry; other failures revert the field and toast the server
 * message. A chapter rename changes its node id server-side, so a follow-up
 * op on the same node may 404 — the error path reloads and the user retries.
 *
 * Wire shape (verified against OpenWrite tools/outline_tree.py
 * build_outline_structure): GET /api/outline answers WITHOUT an envelope —
 * { path, revision, roots, counts, drafted_chapters, recommendation }.
 */
import type { ConvViewProps } from '@deepseek-ai/dsh-client-ui-conversation/client';
import type { InjectFace, PropsLocale } from '@deepseek-ai/dsh-client-ui-slots';
import { type StudioApiInjected } from './api.ts';
/** Full outline-view props: conversation-view runtime share & injected fetch & locale seat. */
export type OutlineViewProps = ConvViewProps & InjectFace<StudioApiInjected> & PropsLocale<'studio-panel'>;
export declare function OutlineView({ fetchStudioApi, postStudioApi, t }: OutlineViewProps): import("react").JSX.Element;
