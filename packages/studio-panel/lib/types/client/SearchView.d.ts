/**
 * Search view (搜索): native project search over the OpenWrite library —
 * debounced query input + scope selector, results with the query highlighted
 * in the snippet. Click-to-read: any result opens an inline preview pane
 * (document via GET /api/document?path=…, hit line highlighted). GET-only;
 * this is the panel's one interactive (non-mutating) view.
 *
 * Wire shape (verified against OpenWrite tools/studio_http.py do_GET +
 * tools/studio_application.py search_project + tools/project_search.py
 * ProjectSearchIndex.search + tools/library_catalog.py scopes):
 * GET /api/search?q=<query>&scope=<scope>&limit=<n> answers WITHOUT an
 * envelope —
 * {
 *   query, scope, scope_label,
 *   results: [{ path, title, line, heading, snippet, scope, scope_label,
 *               category, category_label, score, retrieval: [...], excerpt }],
 *   indexed, engine (lightrag/literal-fallback/none),
 *   warning, warning_code, retrieval_stats, index_updates, embedding,
 * }
 * GET /api/document?path=<p> answers WITHOUT an envelope —
 * { path, title, content, version, revision, ... } (any project document:
 * outline / manuscript chapters / character & world sources).
 * Canonical scopes (library_catalog.py CANONICAL_SEARCH_SCOPES): all /
 * outline / core / characters / settings / continuity / chapters / sources.
 * The payload carries no match offsets, so highlighting re-matches the
 * (server-normalized) query inside the snippet client-side.
 */
import type { ConvViewProps } from '@deepseek-ai/dsh-client-ui-conversation/client';
import type { InjectFace, PropsLocale } from '@deepseek-ai/dsh-client-ui-slots';
import { type StudioApiInjected } from './api.ts';
/** Full search-view props: conversation-view runtime share & injected fetch & locale seat. */
export type SearchViewProps = ConvViewProps & InjectFace<StudioApiInjected> & PropsLocale<'studio-panel'>;
export declare function SearchView({ fetchStudioApi, postStudioApi, t }: SearchViewProps): import("react").JSX.Element;
