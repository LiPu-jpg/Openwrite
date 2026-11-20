/** OpenWrite review v2 decision. Extra keys are allowed (additionalProperties). */
export interface ReviewV2Decision {
    schema_version: "openwrite.review.v2";
    execution_status: "completed" | "partial" | "failed";
    quality_score: number | null;
    coverage: number;
    gate_status: "pass" | "blocked" | "inconclusive";
    delivery_status: "pass" | "revise" | "blocked" | "inconclusive" | "stale";
    production_gate_status?: "pass" | "revise" | "blocked" | "inconclusive" | "stale" | "disabled" | "disabled_uncalibrated";
    [key: string]: unknown;
}
/** dsh-novel review manifest v2. Extra keys are allowed (additionalProperties). */
export interface ReviewManifestV2 {
    schemaVersion: "dsh-novel.review.manifest.v2";
    recordType: "review";
    chapterId: string;
    verdict: "pass" | "fail" | "inconclusive";
    decisionSource?: "v2" | "v1-adapter";
    threshold?: number;
    coverage?: number;
    qualityScore?: number | null;
    [key: string]: unknown;
}
/** DeliveryManifestV2Stage. Extra keys are allowed (additionalProperties). */
export interface DeliveryManifestV2Stage {
    schemaVersion: "dsh-novel.delivery.stage.v2";
    recordType: "delivery-stage";
    chapterId: string;
    stage: string;
    verdict: "pass" | "fail" | "inconclusive";
    status: string;
    evidence: Record<string, unknown>;
    [key: string]: unknown;
}
/** dsh-novel delivery manifest v2. Extra keys are allowed (additionalProperties). */
export interface DeliveryManifestV2 {
    schemaVersion: "dsh-novel.delivery.manifest.v2";
    recordType: "chapter-delivery";
    chapterId: string;
    novelId?: string;
    threshold?: number;
    decisionSource?: "v2" | "v1-adapter";
    readyForDelivery?: boolean;
    stages: Record<string, DeliveryManifestV2Stage>;
    [key: string]: unknown;
}
/** dsh-novel delivery stage v2. Extra keys are allowed (additionalProperties). */
export interface DeliveryStageV2 {
    schemaVersion: "dsh-novel.delivery.stage.v2";
    recordType: "delivery-stage";
    chapterId: string;
    stage: string;
    verdict: "pass" | "fail" | "inconclusive";
    status: string;
    evidence: Record<string, unknown>;
    [key: string]: unknown;
}
/** ModelBenchmarkV1CandidateUsage. Extra keys are allowed (additionalProperties). */
export interface ModelBenchmarkV1CandidateUsage {
    prompt_tokens?: number | null;
    completion_tokens?: number | null;
    reasoning_tokens?: number | null;
    total_tokens?: number | null;
    [key: string]: unknown;
}
/** ModelBenchmarkV1CandidateError. Extra keys are allowed (additionalProperties). */
export interface ModelBenchmarkV1CandidateError {
    code: string;
    message: string;
    [key: string]: unknown;
}
/** ModelBenchmarkV1Candidate. Extra keys are allowed (additionalProperties). */
export interface ModelBenchmarkV1Candidate {
    candidate_id: string;
    writer_profile: Record<string, unknown>;
    reliability_status: "completed" | "failed";
    usage?: ModelBenchmarkV1CandidateUsage | null;
    cost_usd?: number | null;
    cost_reported?: boolean;
    latency_ms?: number | null;
    error?: ModelBenchmarkV1CandidateError | null;
    task_type?: "chapter" | "outline";
    outline_start_chapter?: number;
    outline_end_chapter?: number;
    outline_chapter_count?: number;
    outline_chapters?: Record<string, unknown>[];
    [key: string]: unknown;
}
/** ModelBenchmarkV1EvaluationUsage. Extra keys are allowed (additionalProperties). */
export interface ModelBenchmarkV1EvaluationUsage {
    prompt_tokens?: number | null;
    completion_tokens?: number | null;
    reasoning_tokens?: number | null;
    total_tokens?: number | null;
    [key: string]: unknown;
}
/** ModelBenchmarkV1EvaluationError. Extra keys are allowed (additionalProperties). */
export interface ModelBenchmarkV1EvaluationError {
    code: string;
    message: string;
    [key: string]: unknown;
}
/** ModelBenchmarkV1Evaluation. Extra keys are allowed (additionalProperties). */
export interface ModelBenchmarkV1Evaluation {
    candidate_id: string;
    reviewer_profile: Record<string, unknown>;
    execution_status: "completed" | "partial" | "failed";
    usage?: ModelBenchmarkV1EvaluationUsage | null;
    cost_usd?: number | null;
    cost_reported?: boolean;
    latency_ms?: number | null;
    error?: ModelBenchmarkV1EvaluationError | null;
    [key: string]: unknown;
}
/** ModelBenchmarkV1ConfigPipelineNode. Extra keys are allowed (additionalProperties). */
export interface ModelBenchmarkV1ConfigPipelineNode {
    id: string;
    label: string;
    depends_on: string[];
}
/** ModelBenchmarkV1ConfigPipelineReviewDomain. Extra keys are allowed (additionalProperties). */
export interface ModelBenchmarkV1ConfigPipelineReviewDomain {
    id?: string;
    label?: string;
}
/** ModelBenchmarkV1ConfigPipeline. Extra keys are allowed (additionalProperties). */
export interface ModelBenchmarkV1ConfigPipeline {
    id?: string;
    execution_mode?: "framework" | "creative";
    nodes?: ModelBenchmarkV1ConfigPipelineNode[];
    review_domains?: ModelBenchmarkV1ConfigPipelineReviewDomain[];
}
/** ModelBenchmarkV1Config. Extra keys are allowed (additionalProperties). */
export interface ModelBenchmarkV1Config {
    writer_profile_ids: string[];
    reviewer_profile_ids: string[];
    repeats?: number;
    target_words?: number;
    concurrency?: number;
    blind_review?: boolean;
    run_scoped_profiles?: boolean;
    execution_mode?: "framework" | "creative";
    task_type?: "chapter" | "outline";
    outline_start_chapter?: number;
    outline_end_chapter?: number;
    outline_chapter_count?: number;
    pipeline?: ModelBenchmarkV1ConfigPipeline;
    [key: string]: unknown;
}
/** ModelBenchmarkV1Summary. Extra keys are allowed (additionalProperties). */
export interface ModelBenchmarkV1Summary {
    latency_ms_total?: number | null;
    failed_candidates?: number;
    [key: string]: unknown;
}
/** OpenWrite model benchmark v1 artifact. Extra keys are allowed (additionalProperties). */
export interface ModelBenchmarkV1 {
    schema_version: "openwrite.model-benchmark.v1";
    run_id: string;
    status: "completed" | "partial" | "failed" | "running" | "cancelling" | "cancelled";
    context_hash: string;
    task_id?: string;
    started_at?: string;
    candidates: ModelBenchmarkV1Candidate[];
    evaluations: ModelBenchmarkV1Evaluation[];
    config: ModelBenchmarkV1Config;
    summary?: ModelBenchmarkV1Summary;
    task_type?: "chapter" | "outline";
    [key: string]: unknown;
}
/** OpenWrite independent chat and embedding model surface v1. Extra keys are allowed (additionalProperties). */
export interface ModelProfileSurfaceV1 {
    schema_version: "openwrite.model-profile.v1";
    default_profile_id: string;
    active_embedding_profile_id: string;
    profiles: unknown[];
    embedding_profiles: unknown[];
    routes: Record<string, string>;
    [key: string]: unknown;
}
/** TaskSurfaceV1TaskProgress. Extra keys are allowed (additionalProperties). */
export interface TaskSurfaceV1TaskProgress {
    completed_units: number;
    total_units: number;
    ratio: number | null;
    unit_kind: "candidates" | "evaluations" | "chapters" | "files";
    [key: string]: unknown;
}
/** TaskSurfaceV1TaskError. Extra keys are allowed (additionalProperties). */
export interface TaskSurfaceV1TaskError {
    code: string;
    message: string;
    recoverable: boolean;
    failed_stage?: string | null;
    [key: string]: unknown;
}
/** TaskSurfaceV1TaskResultRef. Extra keys are allowed (additionalProperties). */
export interface TaskSurfaceV1TaskResultRef {
    type: "chapter" | "review" | "revision" | "research_report" | "benchmark_run" | "import" | "archive";
    id: string;
    [key: string]: unknown;
}
/** TaskSurfaceV1Task. Extra keys are allowed (additionalProperties). */
export interface TaskSurfaceV1Task {
    task_id: string;
    type: string;
    status: "pending" | "running" | "awaiting_confirmation" | "completed" | "failed" | "cancelled" | "interrupted";
    phase: "queued" | "reading" | "preparing" | "model" | "validating" | "committing" | "complete" | null;
    phase_index: number | null;
    progress: TaskSurfaceV1TaskProgress | null;
    attempt: number;
    retryable: boolean;
    created_at: string | null;
    updated_at: string | null;
    started_at: string | null;
    completed_at: string | null;
    error: TaskSurfaceV1TaskError | null;
    result_ref: TaskSurfaceV1TaskResultRef | null;
    input_summary: string | null;
    chapter_id: string | null;
    schema_version: string;
    [key: string]: unknown;
}
/** OpenWrite task surface v1 (credential-free). Extra keys are allowed (additionalProperties). */
export interface TaskSurfaceV1 {
    schema_version: "openwrite.task-surface.v1";
    phase_order: "queued" | "reading" | "preparing" | "model" | "validating" | "committing" | "complete"[];
    tasks: TaskSurfaceV1Task[];
    counts: Record<string, unknown>;
    [key: string]: unknown;
}
/** ResearchSurfaceV1SettingsSearchProvider. Extra keys are allowed (additionalProperties). */
export interface ResearchSurfaceV1SettingsSearchProvider {
    id: "bocha" | "bing" | "jina" | "none";
    label: string;
    requires_api_key: boolean;
    configured: boolean;
    credential_configured: boolean;
    [key: string]: unknown;
}
/** ResearchSurfaceV1Settings. Extra keys are allowed (additionalProperties). */
export interface ResearchSurfaceV1Settings {
    search_provider: "bocha" | "bing" | "jina" | "none";
    search_providers: ResearchSurfaceV1SettingsSearchProvider[];
    [key: string]: unknown;
}
/** ResearchSurfaceV1ReportModelProfile. Extra keys are allowed (additionalProperties). */
export interface ResearchSurfaceV1ReportModelProfile {
    id: string | null;
    label: string | null;
    model: string | null;
    provider: string | null;
    [key: string]: unknown;
}
/** ResearchSurfaceV1ReportSource. Extra keys are allowed (additionalProperties). */
export interface ResearchSurfaceV1ReportSource {
    title: string;
    url: string;
    source_type: string;
    cited: boolean;
    [key: string]: unknown;
}
/** ResearchSurfaceV1ReportUsage. Extra keys are allowed (additionalProperties). */
export interface ResearchSurfaceV1ReportUsage {
    total_tokens: number | null;
    reported: boolean;
    [key: string]: unknown;
}
/** ResearchSurfaceV1ReportCostUsd. Extra keys are allowed (additionalProperties). */
export interface ResearchSurfaceV1ReportCostUsd {
    value: number | null;
    reported: boolean;
    [key: string]: unknown;
}
/** ResearchSurfaceV1ReportFailure. Extra keys are allowed (additionalProperties). */
export interface ResearchSurfaceV1ReportFailure {
    code: string;
    message: string;
    [key: string]: unknown;
}
/** ResearchSurfaceV1Report. Extra keys are allowed (additionalProperties). */
export interface ResearchSurfaceV1Report {
    id: string;
    title: string;
    status: "succeeded" | "failed" | "needs_human_review" | "unknown";
    episode_id: string | null;
    task_id: string | null;
    created_at: string | null;
    completed_at: string | null;
    model_profile: ResearchSurfaceV1ReportModelProfile | null;
    search_provider: string | null;
    sources: ResearchSurfaceV1ReportSource[] | null;
    sources_status: "ok" | "unavailable";
    source_count: number | null;
    word_count: number | null;
    latency_ms: number | null;
    usage: ResearchSurfaceV1ReportUsage;
    cost_usd: ResearchSurfaceV1ReportCostUsd;
    failure: ResearchSurfaceV1ReportFailure | null;
    metrics: Record<string, unknown>;
    path: string;
    bytes: number;
    [key: string]: unknown;
}
/** ResearchSurfaceV1ModelRoute. Extra keys are allowed (additionalProperties). */
export interface ResearchSurfaceV1ModelRoute {
    profile_id: string;
    label: string;
    model: string;
    provider: string;
    configured: boolean;
    compatible: boolean;
    [key: string]: unknown;
}
/** OpenWrite research surface v1 (credential-free). Extra keys are allowed (additionalProperties). */
export interface ResearchSurfaceV1 {
    schema_version: "openwrite.research-surface.v1";
    available: boolean;
    node_ready: boolean;
    pnpm_ready: boolean;
    package_ready: boolean;
    dependencies_ready: boolean;
    setup_hint: string;
    settings: ResearchSurfaceV1Settings;
    reports: ResearchSurfaceV1Report[];
    model_route: ResearchSurfaceV1ModelRoute;
    [key: string]: unknown;
}
/** OpenWrite model connection test v1 success payload (chat and embedding variants). Extra keys are allowed (additionalProperties). */
export interface ModelConnectionTestV1 {
    ok: true;
    status: "ok";
    provider: string;
    model: string;
    latency_ms: number;
    tested_at: string;
    reply?: string;
    provider_label?: string;
    dimension?: number;
    max_tokens?: number;
    base_url?: string;
    vectors?: number;
    [key: string]: unknown;
}
type SchemaMap = Record<string, unknown>;
/** Minimal JSON Schema subset validator mirroring OpenWrite
 * `tools/schema_lint.py` and `scripts/schema-lint.mjs`. */
export declare function validateSchema(value: unknown, schema: SchemaMap, path?: string, root?: SchemaMap): string[];
/** Validate `value` against the review_v2_decision schema; throw on failure. */
export declare function validateReviewV2Decision(value: unknown): ReviewV2Decision;
/** Validate `value` against the review_manifest_v2 schema; throw on failure. */
export declare function validateReviewManifestV2(value: unknown): ReviewManifestV2;
/** Validate `value` against the delivery_manifest_v2 schema; throw on failure. */
export declare function validateDeliveryManifestV2(value: unknown): DeliveryManifestV2;
/** Validate `value` against the delivery_stage_v2 schema; throw on failure. */
export declare function validateDeliveryStageV2(value: unknown): DeliveryStageV2;
/** Validate `value` against the model_benchmark_v1 schema; throw on failure. */
export declare function validateModelBenchmarkV1(value: unknown): ModelBenchmarkV1;
/** Validate `value` against the model_profile_surface_v1 schema; throw on failure. */
export declare function validateModelProfileSurfaceV1(value: unknown): ModelProfileSurfaceV1;
/** Validate `value` against the task_surface_v1 schema; throw on failure. */
export declare function validateTaskSurfaceV1(value: unknown): TaskSurfaceV1;
/** Validate `value` against the research_surface_v1 schema; throw on failure. */
export declare function validateResearchSurfaceV1(value: unknown): ResearchSurfaceV1;
/** Validate `value` against the model_connection_test_v1 schema; throw on failure. */
export declare function validateModelConnectionTestV1(value: unknown): ModelConnectionTestV1;
export {};
