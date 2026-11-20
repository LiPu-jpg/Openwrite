/**
 * Graph view (图谱): OpenWrite continuity data as SVG and React Flow — the
 * foreshadowing board (layered by 主线/支线/彩蛋, ordered by target chapter)
 * and the interactive character/world relationship graph (circular seed layout).
 * Read-only.
 *
 * Wire shape (verified against OpenWrite tools/novel_service.py continuity()
 * + models/foreshadowing.py + tools/world_query.py get_relations_topology):
 * GET /api/continuity answers WITHOUT an envelope —
 * {
 *   truth: {...},
 *   foreshadowing: {
 *     // PENDING nodes only (get_pending_nodes: status 埋伏/待收, weight >= 1);
 *     // the stored DAG's edges are NOT exposed by this endpoint.
 *     nodes: [{ id, content, weight (1-10), layer (主线/支线/彩蛋),
 *               status (埋伏/待收), created_at, target_arc, target_section,
 *               target_chapter, tags }],
 *     total, by_status, by_layer, by_weight,
 *   },
 *   foreshadowing_validation: { valid, errors },
 *   relationship_graph: {
 *     nodes: [{ id, label, kind (character/faction/place/concept/.../unknown),
 *               type, status, description, unresolved }],
 *     edges: [{ id, source, target, label, kind, origin, confirmed,
 *               source_label }],
 *     truncated, ...
 *   },
 *   // 事实账本: three markdown DOCUMENTS (truth_manager.py TruthFiles), not
 *   // structured rows — rendered as-is with MarkdownText.
 *   truth: { current_state: string, ledger: string, relationships: string },
 *   // 章节工作流 (workflow_scheduler.py): stages carry
 *   // status pending/running/completed/failed/skipped.
 *   workflows: [{ chapter_id, current_stage, error,
 *                 stages: [{ name, status, message }] }],
 * }
 *
 * Sections (toolbar chips): 伏笔 (board + DAG validation errors), 关系图
 * (kind-filtered interactive canvas), 事实账本 (the three truth documents), 工作流
 * (per-chapter pipeline stages). All read-only.
 */
import type { ConvViewProps } from '@deepseek-ai/dsh-client-ui-conversation/client';
import type { InjectFace, PropsLocale } from '@deepseek-ai/dsh-client-ui-slots';
import type { StudioApiInjected } from './api.ts';
/** Full graph-view props: conversation-view runtime share & injected fetch & locale seat. */
export type GraphViewProps = ConvViewProps & InjectFace<StudioApiInjected> & PropsLocale<'studio-panel'>;
export declare function GraphView({ fetchStudioApi, postStudioApi, t }: GraphViewProps): import("react").JSX.Element;
