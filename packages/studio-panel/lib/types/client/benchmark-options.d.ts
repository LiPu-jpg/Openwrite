export type BenchmarkTaskType = 'chapter' | 'outline';
export type BenchmarkExecutionMode = 'framework' | 'creative';
export interface BenchmarkPipeline {
    id: string;
    executionMode: string;
    nodes: {
        id: string;
        label: string;
        dependsOn: string[];
    }[];
    reviewDomains: {
        id: string;
        label: string;
    }[];
}
export interface BenchmarkOptions {
    chapters: {
        id: string;
        title: string;
        status: string;
        hasManuscript: boolean;
        available: boolean;
        reason: string;
        rewriteAvailable: boolean;
    }[];
    nextChapterId: string;
    defaultOutlineStart: number;
    outlineStartMin: number;
    outlineStartMax: number;
    outlineCountMax: number;
    tasks: {
        taskType: BenchmarkTaskType;
        executionModes: string[];
        pipelines: BenchmarkPipeline[];
        readiness: {
            ok: boolean;
            code: string;
            message: string;
        };
    }[];
}
export declare function parseBenchmarkPipeline(value: unknown): BenchmarkPipeline | null;
export declare function parseBenchmarkOptions(value: unknown): BenchmarkOptions;
export declare function positiveInteger(value: string): number | null;
