/** Runtime-checked DTO boundary for the OpenWrite Studio API. */
export type JsonRecord = Record<string, unknown>;
export declare function asRecord(value: unknown): JsonRecord;
export declare function unwrapData(value: unknown): JsonRecord;
export declare function asText(value: unknown): string;
export declare function asFiniteNumber(value: unknown): number | null;
export declare function asInteger(value: unknown, fallback?: number): number;
/** Server-recorded connection-test outcome on a profile (null = untested). */
export type ModelTestRecordDto = {
    status: 'ok' | 'failed';
    tested_at: string;
    latency_ms: number | null;
    provider: string;
    resolved_model: string;
    error_code: string | null;
    failed_stage: string | null;
};
/** Narrow one last_test record; null when absent or malformed. */
export declare function parseTestRecord(value: unknown): ModelTestRecordDto | null;
export type ModelProfileDto = {
    id: string;
    label: string;
    provider: string;
    model: string;
    base_url: string;
    api_format: string;
    auth_source?: string;
    workspace_id?: string;
    context_tokens: number;
    max_output_tokens: number;
    temperature: number;
    timeout_seconds: number;
    configured: boolean;
    schema_version: string;
    capabilities: {
        chat: boolean;
    };
    used_by_routes: string[];
    last_test: ModelTestRecordDto | null;
};
export declare function parseModelProfiles(value: unknown): ModelProfileDto[];
export declare function parseRouteMap(value: unknown): Record<string, string>;
/**
 * One model of the host's own directory.
 *
 * The host composes the adapters — its own providers and the ones other
 * plugins register into the same directory — so this list is what dsh itself
 * can call. `id` is the `provider/model` route the host's relay expects.
 */
export type HostModelDto = {
    id: string;
    provider: string;
    model: string;
    label: string;
    description: string;
    context_tokens: number;
};
/** The host model directory, as Core reads it through the host relay. */
export type HostModelCatalogDto = {
    available: boolean;
    models: HostModelDto[];
    error: string;
};
export declare function parseHostModelCatalog(value: unknown): HostModelCatalogDto;
/** Success payload of POST /model/test and /model/embedding/test (enveloped). */
export type ConnectionTestResultDto = {
    status: string;
    provider: string;
    model: string;
    latency_ms: number | null;
    tested_at: string;
    reply: string;
    dimension: number | null;
    vectors: number | null;
};
export declare function parseConnectionTestResult(value: unknown): ConnectionTestResultDto;
/** Read-only payload of POST /model/profiles/delete-preview (enveloped). */
export type DeletePreviewDto = {
    profile_id: string;
    used_by_routes: string[];
    routes_that_would_fail: string[];
    fallback_candidates: {
        id: string;
        label: string;
        configured: boolean;
    }[];
    resulting_routes: Record<string, string> | null;
    deletable: boolean;
    blocking_reasons: string[];
};
export declare function parseDeletePreview(value: unknown): DeletePreviewDto;
/** Response data of POST /model/routes: the swapped map plus the change impact. */
export type RouteImpactDto = {
    routes: Record<string, string>;
    changed_routes: {
        route: string;
        from: string;
        to: string;
    }[];
    profiles_affected: string[];
};
export declare function parseRouteImpact(value: unknown): RouteImpactDto;
/** Real progress units on a task (benchmark tasks report candidate/evaluation units). */
export type TaskProgressDto = {
    completed_units: number;
    total_units: number;
    ratio: number | null;
    unit_kind: string;
};
export declare function parseTaskProgress(value: unknown): TaskProgressDto | null;
/** Pointer from a finished task to its artifact (e.g. a benchmark run). */
export type ResultRefDto = {
    type: string;
    id: string;
};
export declare function parseResultRef(value: unknown): ResultRefDto | null;
export type ExportFormatDto = 'md' | 'txt' | 'epub';
export type ExportPurposeDto = 'backup' | 'delivery' | 'personal_archive';
export type ExportChapterDto = {
    chapter_id: string;
    number: number;
    path: string;
    title: string;
    writing_units: number;
    empty: boolean;
    revision: string;
};
export type ExportIssueDto = {
    code: string;
    message: string;
    details: JsonRecord;
};
export type ExportPreflightDto = {
    schema_version: string;
    novel_id: string;
    format: ExportFormatDto;
    purpose: ExportPurposeDto;
    can_export: boolean;
    actual_order: string[];
    chapters: ExportChapterDto[];
    structure: {
        duplicates: Record<string, string[]>;
        missing: string[];
        empty: string[];
        unreadable: string[];
    };
    writing_units: {
        total: number;
        book_target: number;
        chapter_target: number;
        completion_ratio: number | null;
    };
    metadata: {
        title: string;
        author: string;
        language: string;
    };
    reviews: {
        missing: string[];
        current: string[];
        stale: string[];
        approved: string[];
        not_approved: string[];
    };
    manuscript_acceptance: {
        status: string;
        blocking: boolean;
        blocking_chapters: string[];
        needs_review: string[];
    };
    blockers: ExportIssueDto[];
    warnings: ExportIssueDto[];
    preflight_revision: string;
};
/** Runtime-check the stable `openwrite.export-preflight.v1` success envelope. */
export declare function parseExportPreflight(value: unknown): ExportPreflightDto;
export declare const IMPORT_STAGE_NAMES: readonly ["snapshot", "split", "structure_confirmed", "published", "acceptance", "reconcile", "synthesis", "complete"];
export type ImportStageNameDto = typeof IMPORT_STAGE_NAMES[number];
export type ImportStageDto = {
    status: string;
    attempts: number;
    input_sha256: string;
    output_sha256: string;
    started_at: string;
    completed_at: string;
    error_code: string;
};
export type ManuscriptImportOperationDto = {
    schema_version: string;
    import_id: string;
    novel_id: string;
    status: string;
    arc_id: string;
    source: {
        filename: string;
        suffix: string;
        bytes: number;
        sha256: string;
    };
    preview_revision: string;
    confirmed_preview_revision: string;
    chapter_count: number;
    writing_units: number;
    progress: {
        current_stage: string;
        completed_stages: number;
        total_stages: number;
        published_chapters: number;
        total_chapters: number;
    };
    stages: Record<ImportStageNameDto, ImportStageDto>;
    publication: {
        sha256: string;
        swap_status: string;
        committed: boolean;
    };
    acceptance: {
        operation_id: string;
        status: string;
    };
    synthesis_sha256: string;
    failure: {
        code: string;
        stage: string;
        recoverable: boolean;
    } | null;
    created_at: string;
    updated_at: string;
    completed_at: string;
    discarded_at: string;
};
export type ManuscriptImportChapterDto = {
    order: number;
    chapter_id: string;
    title: string;
    content: string;
    writing_units: number;
    sha256: string;
};
export type ManuscriptImportPreviewDto = {
    schema_version: string;
    import_id: string;
    arc_id: string;
    source_sha256: string;
    revision: string;
    chapter_count: number;
    writing_units: number;
    chapters: ManuscriptImportChapterDto[];
    updated_at: string;
};
export declare function parseManuscriptImportList(value: unknown): {
    schema_version: string;
    novel_id: string;
    operations: ManuscriptImportOperationDto[];
    counts: Record<string, number>;
};
export declare function parseManuscriptImportDetail(value: unknown): {
    operation: ManuscriptImportOperationDto;
    preview: ManuscriptImportPreviewDto | null;
};
export type ArchiveFileDto = {
    path: string;
    archive_path: string;
    category: string;
    sha256: string;
    size: number;
};
export type ArchiveNoticeDto = {
    path: string;
    location: string;
    kind: string;
    source: string;
    target: string;
    source_path: string;
    target_path: string;
    source_paths: string[];
    format: string;
    value: string;
    before: string;
    after: string;
    message: string;
    reason: string;
    state: string;
    sha256_before: string;
    sha256_after: string;
    reference_count: number;
    replacement_count: number;
};
export type ProjectArchivePlanDto = {
    schema_version: string;
    novel_id: string;
    archive_id: string;
    preflight_revision: string;
    includes: {
        roots: string[];
        file_count: number;
        total_size: number;
        category_counts: Record<string, number>;
        directories: string[];
        files: ArchiveFileDto[];
    };
    excludes: {
        rules: string[];
        entries: ArchiveNoticeDto[];
    };
    missing: {
        required: string[];
        optional: ArchiveNoticeDto[];
    };
    reference_inventory: {
        known: ArchiveNoticeDto[];
        preserved: ArchiveNoticeDto[];
        warnings: ArchiveNoticeDto[];
    };
    policies: {
        tasks: string;
        target: string;
        reference_default: string;
        reference_supported: string[];
    };
};
export declare function parseProjectArchivePreflight(value: unknown): ProjectArchivePlanDto;
export type ProjectArchiveSummaryDto = {
    archive_id: string;
    archive_sha256: string;
    created_at: string;
    file_count: number;
    total_size: number;
    missing_required: string[];
    missing_optional: ArchiveNoticeDto[];
};
export declare function parseProjectArchiveList(value: unknown): {
    schema_version: string;
    novel_id: string;
    archives: ProjectArchiveSummaryDto[];
};
export declare function parseProjectArchiveDetail(value: unknown): {
    archive_sha256: string;
    file_count: number;
    total_size: number;
    plan: ProjectArchivePlanDto;
};
export type ProjectRestorePreviewDto = {
    archive_id: string;
    archive_sha256: string;
    source_novel_id: string;
    target_novel_id: string;
    target_root: string;
    reference_policy: 'preserve_relative' | 'rewrite_novel_id';
    can_restore: boolean;
    conflicts: string[];
    file_count: number;
    total_size: number;
    missing: {
        required: string[];
        optional: ArchiveNoticeDto[];
    };
    task_file_count: number;
    task_archive_path: string;
    auto_resume_tasks: boolean;
    path_rewrites: ArchiveNoticeDto[];
    rewritten_files: ArchiveNoticeDto[];
    rewritten_references: ArchiveNoticeDto[];
    preserved_references: ArchiveNoticeDto[];
    reference_warnings: ArchiveNoticeDto[];
    reference_conflicts: ArchiveNoticeDto[];
};
export declare function parseProjectRestorePreview(value: unknown): ProjectRestorePreviewDto;
export type ChapterWorkEventDto = {
    kind: string;
    id: string;
    status: string;
    document_id: string;
    path: string;
    chapter_id: string;
    revision: string;
    updated_at: string;
    writing_units_delta: number | null;
    reason: string;
};
export type ReadingOrderDocumentDto = {
    document_id: string;
    occurrence_id: string;
    chapter_id: string;
    title: string;
    path: string;
    status: string;
    volume_id: string;
    writing_units: number;
    revision: string;
    updated_at: string;
    reading_index: number;
    previous_occurrence_id: string;
    next_occurrence_id: string;
    content: string;
};
export type ReadingOrderDto = {
    schema_version: string;
    novel_id: string;
    revision: string;
    mode: string;
    mutation_allowed: boolean;
    actual_order: string[];
    volumes: {
        volume_id: string;
        title: string;
        order: number;
        occurrence_ids: string[];
    }[];
    documents: ReadingOrderDocumentDto[];
    issues: unknown[];
};
export type ReadingPacketDto = {
    schema_version: string;
    novel_id: string;
    revision: string;
    anchor_document_id: string;
    anchor_occurrence_id: string;
    start_index: number;
    end_index: number;
    has_previous: boolean;
    has_next: boolean;
    complete: boolean;
    documents: ReadingOrderDocumentDto[];
    issues: unknown[];
};
/** Canonical reading order. Every occurrence is retained, including repeated documents. */
export declare function parseReadingOrder(value: unknown): ReadingOrderDto;
/** Bounded continuous-reading packet with immutable occurrence identities. */
export declare function parseReadingPacket(value: unknown): ReadingPacketDto;
export type DocumentChangePlanDto = {
    applied: boolean;
    changed: boolean;
    status: string;
    path: string;
    revision: string;
    diff: string;
    preview_token: string;
    undo_preview_token: string;
    mutation_summary: {
        execution_status: string;
        source_revision: string;
        result_revision: string;
    };
};
/** Server-owned immutable document change preview/apply projection. */
export declare function parseDocumentChangePlan(value: unknown): DocumentChangePlanDto;
export type ChapterForeshadowItemDto = {
    id: string;
    content: string;
    status: string;
    weight: number;
    layer: string;
    planned: boolean;
    plant_chapter_id: string;
    reveal_chapter_id: string;
    earliest_reveal: string;
    source_revision: string;
    tags: string[];
};
export type ChapterForeshadowBucket = 'due' | 'overdue' | 'to_plant';
export type ChapterForeshadowingDto = {
    due: ChapterForeshadowItemDto[];
    overdue: ChapterForeshadowItemDto[];
    to_plant: ChapterForeshadowItemDto[];
    source_revision: string;
    counts: Record<ChapterForeshadowBucket, number>;
};
export type ChapterWorkBriefDto = {
    schema_version: string;
    novel_id: string;
    chapter_id: string;
    document_id: string;
    manuscript: {
        path: string;
        title: string;
        save_status: string;
        current_revision: string;
        writing_units: number;
        modified_at: string;
    };
    review: {
        exists: boolean;
        review_revision: string;
        freshness_status: string;
        stale: boolean;
        stale_reason: string;
        source_revision: string;
        current_source_revision: string;
        reviewed_at: string;
        issue_count: number;
        latest_closure: null | {
            closure_id: string;
            proposal_id: string;
            source_review_revision: string;
            rereview_review_revision: string;
            applied_revision: string;
            rereview_source_revision: string;
            closed_at: string;
            issue_outcomes: {
                issue_id: string;
                outcome: 'resolved' | 'retained';
            }[];
            regressions: {
                issue_id: string;
                outcome: 'regressed';
                issue: unknown;
            }[];
        };
    };
    target: {
        writing_units: number;
        source: string;
        actual_units: number;
        remaining_units: number;
        progress: number;
    };
    recent_edits: ChapterWorkEventDto[];
    foreshadowing: ChapterForeshadowingDto;
};
/** Map OpenWrite work-brief categories onto author actions; keep no second store. */
export declare function parseChapterForeshadowing(value: unknown): ChapterForeshadowingDto;
export type ChapterSprintStats = {
    targetUnits: number;
    actualUnits: number;
    remainingUnits: number;
    progress: number;
    added: number;
    deleted: number;
    net: number;
    knownDeltaEvents: number;
    unknownDeltaEvents: number;
    aiNet: number | null;
    humanNet: number | null;
};
/** Derive sprint UX from the work-brief target (source of truth) and known edit deltas. */
export declare function chapterSprintStats(brief: ChapterWorkBriefDto): ChapterSprintStats;
export declare function chapterForeshadowActions(brief: ChapterWorkBriefDto): {
    bucket: ChapterForeshadowBucket;
    item: ChapterForeshadowItemDto;
}[];
/** Narrow the chapter work projection used by editor CAS and activity UI. */
export declare function parseChapterWorkBrief(value: unknown): ChapterWorkBriefDto;
