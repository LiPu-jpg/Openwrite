/**
 * 预演大纲数据面（供 OutlineView 以“树内接续”方式渲染）。
 *
 * 每套预演 = 一棵和正式大纲一样语法的迷你树（卷/篇/节/章），并携带“构思”。
 * OutlineView 把它的顶层节点接到正式大纲当前卷的末尾——除颜色外与正式树完全一致。
 */
export interface PlanTreeNode {
    id: string;
    kind: 'act' | 'section' | 'chapter';
    label: string;
    title: string;
    summary: string;
    children: PlanTreeNode[];
}
export interface PlanInfo {
    id: string;
    kind: 'rolling' | 'branch';
    label: string;
    idea: string;
    meta: string;
    nodes: PlanTreeNode[];
    /** rolling 草案专用：正文 / revision / state（供编辑、删除、并入） */
    proposal?: string;
    revision?: string;
    state?: string;
}
export declare const PLAN_PALETTES: {
    accent: string;
    bar: string;
    bg: string;
}[];
export declare function planColor(index: number): {
    accent: string;
    bar: string;
    bg: string;
};
export declare function loadPlans(postStudioApi: (path: string, body: unknown) => Promise<unknown>): Promise<PlanInfo[]>;
