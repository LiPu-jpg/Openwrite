import type { JsonValue } from './client.js';
type RecordValue = Record<string, unknown>;
export declare const DOG_REVIEW_DIMENSIONS: Readonly<Record<number, string>>;
export declare const DOG_REVIEW_DOMAINS: readonly [{
    readonly id: "coherence";
    readonly name: "连贯与逻辑";
    readonly weight: 20;
    readonly legacyCheckIds: readonly [2, 3, 4, 5, 9, 11, 35];
}, {
    readonly id: "character";
    readonly name: "角色与关系";
    readonly weight: 15;
    readonly legacyCheckIds: readonly [1, 13, 14, 16, 34, 36];
}, {
    readonly id: "plot";
    readonly name: "情节与承诺";
    readonly weight: 20;
    readonly legacyCheckIds: readonly [6, 15, 24, 25, 32, 33];
}, {
    readonly id: "pacing";
    readonly name: "节奏与场景";
    readonly weight: 15;
    readonly legacyCheckIds: readonly [7, 17, 26];
}, {
    readonly id: "prose";
    readonly name: "文风与表达";
    readonly weight: 15;
    readonly legacyCheckIds: readonly [8, 10, 19, 20, 21, 22, 23];
}, {
    readonly id: "canon";
    readonly name: "正典与资料";
    readonly weight: 15;
    readonly legacyCheckIds: readonly [12, 18, 28, 29, 30, 31, 37];
}];
export declare function dogReviewFrameworkRevision(frameworkValue: unknown): string;
/** Bind OpenWrite's versioned review blueprint to one chapter. The bridge
 * supplies paths only; all nodes and edges come from the canonical server. */
export declare function instantiateDogReviewFramework(frameworkValue: unknown, chapterId: string, relativeDirectory: string): RecordValue;
export declare function buildDogReviewBundle(reviewValue: unknown, chapterId: string, threshold: number): {
    manifest: RecordValue;
    dimensionRecords: RecordValue[];
};
/** Materialize the review response into model-free files consumable by dsh-dog. */
export declare function materializeDogReview(response: unknown, chapterId: string, threshold: number, expectedRoot?: string): Promise<JsonValue>;
export declare function materializeCompletedDogTaskReview(response: unknown, workspace: unknown, framework: unknown, threshold?: number, expectedRoot?: string): Promise<JsonValue | undefined>;
export declare function reviewChapterId(args: {
    path?: string;
    chapter_id?: string;
}): string;
export {};
