/**
 * Assets view (资产): OpenWrite's structured canon library (Studio's 资料库)
 * rendered natively as an Obsidian-like master-detail layout — left sidebar
 * (segment switcher, search, compact asset rows with collapsible 设定
 * subcategory groups, 新建 button) + main detail pane (header, two-column
 * fields, 索引, 关系, markdown body) with a read/edit toggle and inline
 * creation. Only the asset domain is writable; manuscript/outline mutations
 * stay with the agent tools.
 *
 * Wire shapes (verified against OpenWrite tools/studio_http.py do_GET,
 * tools/structured_assets.py, tools/world_query.py get_asset_relation_view,
 * tools/studio_application.py workspace/_document_groups/read_document):
 * - GET /api/assets?kind=X — enveloped { ok, data: { assets: [...] } }.
 *   Summaries: character/world { kind, id, name, summary, asset_type,
 *   aliases, tags, path }; progression adds { stage_count }.
 * - GET /api/assets/{kind}/{id} — enveloped detail { kind, id, name,
 *   data: <front-matter/YAML dict>, body_markdown, path, revision } +
 *   character/world only: relation_view { confirmed, registered, suggested,
 *   incoming, counts } with items { target, name, kind, note, origin,
 *   direction, resolved }.
 * - POST /api/assets / POST /api/assets/update — the write contract lives in
 *   AssetEditor.tsx's header comment.
 * - GET /api/workspace — NOT enveloped. documents.core[] is the 作品核心
 *   document list; operations.reference_library is the 参考作品 (reference
 *   works) list — Studio's data-view="deconstruct" surface, NOT the 资料库
 *   nav entry (which is this structured asset library).
 * - GET /api/document?path=<p> — NOT enveloped { path, title, content, ... }.
 */
import type { ConvViewProps } from '@deepseek-ai/dsh-client-ui-conversation/client';
import type { InjectFace, PropsLocale } from '@deepseek-ai/dsh-client-ui-slots';
import { type StudioApiInjected } from './api.ts';
import { type AssetDraftContext } from './asset-drafts.ts';
/** Full assets-view props: conversation-view runtime share & injected fetch & locale seat. */
export type AssetsViewProps = ConvViewProps & InjectFace<StudioApiInjected> & PropsLocale<'studio-panel'> & {
    refreshEpoch?: number;
    draftContext?: AssetDraftContext | undefined;
    onDraftStateChange?: (state: {
        dirty: boolean;
        busy: boolean;
        discard: () => void;
    }) => void;
};
export declare function AssetsView({ fetchStudioApi, postStudioApi, t, refreshEpoch, draftContext, onDraftStateChange }: AssetsViewProps): import("react").JSX.Element;
