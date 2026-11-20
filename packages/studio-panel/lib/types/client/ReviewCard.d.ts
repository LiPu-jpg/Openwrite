/**
 * novel_review_chapter toolview: the OpenWrite multi-dimensional chapter
 * review as a readable report card. Registrant posture over the keyed
 * tool.call.toolview hole — imports the slot contract only, never the chat
 * domain (the bash-sample.tsx pattern).
 *
 * Wire shape (verified against OpenWrite tools/chapter_pipeline.py review
 * stage + tools/review_store.py normalize_review_issues): the tool value is
 * { result: { ok, chapter_id, passed, score, review_v2, issues: <count int>,
 * summary, issue_details: [...], strict, dimensions, ... }, workspace: {...} }.
 * Review v2 is authoritative for quality score, coverage, gate, and delivery.
 * Issue review severity (critical/warning/info) is independent from revision
 * priority (blocker/high/medium/low).
 *
 * Anything unexpected (running call, non-JSON output, missing fields) falls
 * back to the raw pretty-JSON card — the review text is never swallowed.
 */
import type { ToolCallViewProps } from '@deepseek-ai/dsh-client-ui-tool/client';
import type { PropsLocale } from '@deepseek-ai/dsh-client-ui-slots';
/** Review card props: the toolview runtime share plus the standard locale seat. */
type ReviewCardProps = ToolCallViewProps & PropsLocale<'studio-panel'>;
/**
 * The review card: collapsed summary row (tool · chapter · score · verdict)
 * toggling the expanded report — verdict banner, summary, then issue groups
 * with severity badges, quotes, and suggestions.
 */
export declare function NovelReviewCard({ block, t }: ReviewCardProps): import("react").JSX.Element;
export {};
