"""Evidence-backed, incremental analysis for user-supplied reference texts."""

from __future__ import annotations

from tools.llm import long_generation_stream

import difflib
import hashlib
import json
import math
import os
import re
import tempfile
from collections import defaultdict
from collections.abc import Callable, Iterable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal, TypeVar, cast

from pydantic import BaseModel

from models.source_analysis import (
    EvidenceRef,
    ProfileItemV1,
    PromotionPreviewV1,
    ReferenceProfileV1,
    SourceChunkRecordV2,
    SourceChunkReportV2,
    SourceFindingV2,
    SourceManifestV2,
    SourceReportV2,
)

PROMPT_VERSION = "source-analysis-v2.7"
DEFAULT_INPUT_BUDGET = 12000
FOCUS_VALUES = {
    "promise",
    "structure",
    "character",
    "world",
    "relationship",
    "progression",
    "timeline",
    "conflict",
    "hook",
    "thread",
    "arc_summary",
    "chapter_summary",
    "pacing",
    "voice",
    "reader_drive",
    "method",
    "risk",
}
PROMOTION_TARGETS = {
    "style": "data/style/reference_profile.md",
    "rules": "data/rules/reference_profile.md",
    "inspiration": "data/planning/reference_inspiration.md",
    "setting_candidates": "data/planning/reference_setting_candidates.md",
}

ChunkAnalyzer = Callable[[str, dict[str, Any]], dict[str, Any] | SourceChunkReportV2]
ModelT = TypeVar("ModelT", bound=BaseModel)
ChangeStatus = Literal["added", "modified", "unchanged", "deleted"]
FindingCategory = Literal[
    "promise",
    "structure",
    "character",
    "world",
    "relationship",
    "progression",
    "timeline",
    "conflict",
    "hook",
    "thread",
    "arc_summary",
    "chapter_summary",
    "pacing",
    "voice",
    "reader_drive",
    "method",
    "risk",
]
PromotionTarget = Literal["style", "rules", "inspiration", "setting_candidates"]


class SourceAnalysisError(RuntimeError):
    def __init__(self, message: str, *, code: str = "SOURCE_ANALYSIS_ERROR"):
        super().__init__(message)
        self.code = code


class SourceAnalysisService:
    """Own V2 source manifests, evidence reports, profiles and proposals."""

    def __init__(
        self,
        project_root: Path,
        novel_id: str,
        *,
        sources_root: Path | None = None,
    ):
        self.project_root = Path(project_root).resolve()
        self.novel_id = str(novel_id)
        self.novel_root = self.project_root / "data" / "novels" / self.novel_id
        self.sources_root = (
            Path(sources_root).resolve()
            if sources_root is not None
            else self.novel_root / "data" / "sources"
        )
        self.profiles_root = self.sources_root / "_profiles"

    def prepare(
        self,
        source_id: str,
        content: str,
        *,
        relative_name: str,
        focus: Iterable[str] | None = None,
        input_budget_tokens: int = DEFAULT_INPUT_BUDGET,
    ) -> dict[str, Any]:
        source_id = self._source_id(source_id)
        text = str(content)
        if not text.strip():
            raise SourceAnalysisError("来源文本不能为空", code="INVALID_INPUT")
        budget = int(input_budget_tokens)
        if budget < 256:
            raise SourceAnalysisError("输入预算至少为 256 tokens", code="INVALID_INPUT")
        clean_name = Path(str(relative_name or "source.txt")).name
        clean_focus = self._focus(focus)
        source_sha = self._sha256(text)
        old_manifest = self.load_manifest(source_id)
        change = (
            "added"
            if old_manifest is None
            else "unchanged"
            if old_manifest.source_sha256 == source_sha
            and old_manifest.prompt_version == PROMPT_VERSION
            else "modified"
        )

        analysis_root = self.analysis_root(source_id)
        snapshot_ref = f"analysis_v2/snapshots/{source_sha}.txt"
        snapshot_path = self.source_root(source_id) / snapshot_ref
        self._atomic_write_text(snapshot_path, text)
        now = self._now()
        ranges = self.split_text(text, budget)
        old_by_sha: dict[str, list[tuple[SourceChunkRecordV2, SourceChunkReportV2]]] = (
            self._reusable_reports(source_id, old_manifest) if old_manifest else {}
        )
        chunks: list[SourceChunkRecordV2] = []
        reused = 0
        for index, (start, end) in enumerate(ranges):
            chunk_text = text[start:end]
            chunk_sha = self._sha256(chunk_text)
            chunk_id = f"chk_{index:04d}_{chunk_sha[:12]}"
            record = SourceChunkRecordV2(
                chunk_id=chunk_id,
                index=index,
                start=start,
                end=end,
                char_count=end - start,
                estimated_tokens=self.estimate_tokens(chunk_text),
                sha256=chunk_sha,
                chapter_hint=self._chapter_hint(chunk_text),
                status="pending",
            )
            candidates = old_by_sha.get(chunk_sha) or []
            if candidates:
                old_chunk, old_report = candidates.pop(0)
                rebased = self._rebase_report(
                    old_report,
                    old_chunk=old_chunk,
                    new_chunk=record,
                    source_text=text,
                )
                report_ref = self._chunk_report_ref(record.chunk_id)
                self._write_model(analysis_root / report_ref, rebased)
                record.status = "completed"
                record.report_ref = report_ref
                reused += 1
            chunks.append(record)

        manifest = SourceManifestV2(
            source_id=source_id,
            relative_name=clean_name,
            source_sha256=source_sha,
            source_snapshot_ref=snapshot_ref,
            prompt_version=PROMPT_VERSION,
            focus=clean_focus,
            change_status=cast(ChangeStatus, change),
            total_chars=len(text),
            input_budget_tokens=budget,
            created_at=old_manifest.created_at if old_manifest else now,
            updated_at=now,
            status="completed" if chunks and reused == len(chunks) else "pending",
            chunks=chunks,
        )
        self._write_model(self.manifest_path(source_id), manifest)
        report = self._build_source_report(manifest)
        return {
            "manifest": manifest.model_dump(mode="json"),
            "report": report.model_dump(mode="json"),
            "reused_chunks": reused,
            "pending_chunks": len(chunks) - reused,
            "model_calls_needed": len(chunks) - reused,
        }

    def analyze(
        self,
        source_id: str,
        *,
        analyzer: ChunkAnalyzer | None = None,
        chunk_ids: Iterable[str] | None = None,
    ) -> dict[str, Any]:
        source_id = self._source_id(source_id)
        manifest = self.require_manifest(source_id)
        if manifest.change_status == "deleted":
            raise SourceAnalysisError("来源已删除，不能继续分析", code="SOURCE_DELETED")
        source_text = self._read_snapshot(manifest)
        selected = set(chunk_ids or [])
        processed = 0
        failures: list[dict[str, str]] = []
        for chunk in manifest.chunks:
            if selected and chunk.chunk_id not in selected:
                continue
            if chunk.status == "completed":
                continue
            chunk.status = "running"
            chunk.error_code = ""
            chunk.error_message = ""
            manifest.status = "running"
            manifest.updated_at = self._now()
            self._write_model(self.manifest_path(source_id), manifest)
            chunk_text = source_text[chunk.start : chunk.end]
            context = {
                "source_id": source_id,
                "relative_name": manifest.relative_name,
                "chunk_id": chunk.chunk_id,
                "chunk_index": chunk.index,
                "chunk_start": chunk.start,
                "chunk_end": chunk.end,
                "line_offset": source_text.count("\n", 0, chunk.start) + 1,
                "chapter_hint": chunk.chapter_hint,
                "focus": manifest.focus,
                "prompt_version": manifest.prompt_version,
            }
            try:
                chunk_report = self._run_analyzer(analyzer, chunk_text, context, chunk)
                self._validate_evidence(chunk_report, source_text, chunk)
                report_ref = self._chunk_report_ref(chunk.chunk_id)
                self._write_model(
                    self.analysis_root(source_id) / report_ref, chunk_report
                )
                chunk.status = "completed"
                chunk.report_ref = report_ref
                processed += 1
            except Exception as exc:
                chunk.status = "failed"
                chunk.report_ref = ""
                chunk.error_code = str(getattr(exc, "code", "ANALYSIS_FAILED"))
                chunk.error_message = self._bounded_error(exc)
                failures.append(
                    {
                        "chunk_id": chunk.chunk_id,
                        "code": chunk.error_code,
                        "message": chunk.error_message,
                    }
                )
            manifest.updated_at = self._now()
            self._refresh_manifest_status(manifest)
            self._write_model(self.manifest_path(source_id), manifest)
        report = self._build_source_report(manifest)
        return {
            "ok": not failures and manifest.status == "completed",
            "manifest": manifest.model_dump(mode="json"),
            "report": report.model_dump(mode="json"),
            "processed_chunks": processed,
            "failures": failures,
        }

    def retry(
        self,
        source_id: str,
        chunk_id: str,
        *,
        analyzer: ChunkAnalyzer | None = None,
    ) -> dict[str, Any]:
        manifest = self.require_manifest(source_id)
        chunk = next((item for item in manifest.chunks if item.chunk_id == chunk_id), None)
        if chunk is None:
            raise SourceAnalysisError("来源分块不存在", code="NOT_FOUND")
        if chunk.status not in {"failed", "stale", "pending"}:
            raise SourceAnalysisError("只有失败、过时或待处理分块可以重试", code="INVALID_STATE")
        chunk.status = "pending"
        chunk.error_code = ""
        chunk.error_message = ""
        manifest.status = "pending"
        manifest.updated_at = self._now()
        self._write_model(self.manifest_path(source_id), manifest)
        return self.analyze(source_id, analyzer=analyzer, chunk_ids=[chunk_id])

    def mark_deleted(self, source_id: str) -> dict[str, Any]:
        manifest = self.require_manifest(source_id)
        manifest.change_status = "deleted"
        manifest.status = "stale"
        manifest.updated_at = self._now()
        for chunk in manifest.chunks:
            if chunk.status == "completed":
                chunk.status = "stale"
        self._write_model(self.manifest_path(source_id), manifest)
        report = self._build_source_report(manifest)
        return {
            "manifest": manifest.model_dump(mode="json"),
            "report": report.model_dump(mode="json"),
        }

    def status(self, source_id: str) -> dict[str, Any]:
        manifest = self.require_manifest(source_id)
        report = self.load_report(source_id)
        counts: dict[str, int] = defaultdict(int)
        for chunk in manifest.chunks:
            counts[chunk.status] += 1
        return {
            "source_id": manifest.source_id,
            "status": manifest.status,
            "change_status": manifest.change_status,
            "source_sha256": manifest.source_sha256,
            "total_chars": manifest.total_chars,
            "chunks": dict(counts),
            "complete": (
                manifest.status == "completed"
                and report is not None
                and report.status == "completed"
            ),
            "manifest": manifest.model_dump(mode="json"),
            "report": report.model_dump(mode="json") if report else None,
        }

    def synthesize(
        self,
        source_ids: Iterable[str],
        *,
        include_source_bound_from: Iterable[str] | None = None,
        source_intents: dict[str, str] | None = None,
    ) -> ReferenceProfileV1:
        clean_ids = list(dict.fromkeys(self._source_id(item) for item in source_ids))
        if not clean_ids:
            raise SourceAnalysisError("至少选择一个来源", code="INVALID_INPUT")
        reports: list[SourceReportV2] = []
        for source_id in clean_ids:
            manifest = self.require_manifest(source_id)
            report = self.load_report(source_id)
            if manifest.status != "completed" or report is None or report.status != "completed":
                raise SourceAnalysisError(
                    f"来源 {source_id} 尚未完整分析", code="SOURCE_INCOMPLETE"
                )
            reports.append(report)

        allowed_bound = {
            self._source_id(item) for item in (include_source_bound_from or [])
        }
        intents = {
            source_id: str((source_intents or {}).get(source_id) or "reference")
            for source_id in clean_ids
        }
        grouped: dict[str, list[tuple[str, SourceFindingV2]]] = defaultdict(list)
        category_claims: dict[str, dict[str, list[tuple[str, SourceFindingV2]]]] = defaultdict(
            lambda: defaultdict(list)
        )
        excluded: list[str] = []
        for report in reports:
            for finding in report.findings:
                authorized_bound = report.source_id in allowed_bound and finding.source_bound
                if not authorized_bound and (
                    finding.source_bound
                    or not finding.reusable
                    or not self._claim_is_safe(finding, report.source_bound_terms)
                ):
                    excluded.append(f"{report.source_id}: {finding.claim}")
                    continue
                claims = category_claims[finding.category]
                key = self._semantic_claim_key(finding.claim, claims)
                grouped[f"{finding.category}\0{key}"].append((report.source_id, finding))
                category_claims[finding.category][key].append((report.source_id, finding))

        common: list[ProfileItemV1] = []
        differences: list[ProfileItemV1] = []
        variants: list[ProfileItemV1] = []
        for entries in grouped.values():
            sources = list(dict.fromkeys(source_id for source_id, _ in entries))
            finding = entries[0][1]
            item = ProfileItemV1(
                item_id=f"item_{self._sha256(finding.category + ':' + finding.claim)[:16]}",
                category=finding.category,
                claim=finding.claim,
                source_ids=sources,
                evidence=self._dedupe_evidence(
                    evidence for _, candidate in entries for evidence in candidate.evidence
                ),
                reusable=all(candidate.reusable for _, candidate in entries),
                source_bound=any(candidate.source_bound for _, candidate in entries),
            )
            if len(sources) >= 2:
                common.append(item)
            elif finding.category in {"voice", "pacing", "structure"}:
                differences.append(item)
            else:
                variants.append(item)

        conflicts: list[str] = []
        for category, claims in category_claims.items():
            represented = {
                source_id
                for entries in claims.values()
                for source_id, _ in entries
            }
            if (
                len(claims) > 1
                and len(represented) > 1
                and category in {"voice", "pacing", "structure"}
            ):
                summary = "；".join(entries[0][1].claim for entries in claims.values())
                conflicts.append(f"{category}: {summary}")

        revisions = {report.source_id: report.source_sha256 for report in reports}
        identity = json.dumps(
            {
                "revisions": revisions,
                "include_source_bound_from": sorted(allowed_bound),
                "source_intents": intents,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        profile_id = f"profile_{self._sha256(identity)[:16]}"
        profile = ReferenceProfileV1(
            profile_id=profile_id,
            source_ids=clean_ids,
            source_revisions=revisions,
            source_intents=intents,
            common_methods=common,
            differences=differences,
            optional_variants=variants,
            conflicts=conflicts,
            excluded_items=list(dict.fromkeys(excluded)),
            generated_at=self._now(),
        )
        self._write_model(self.profile_path(profile_id), profile)
        return profile

    def preview_promotion(
        self, profile_id: str, target: str
    ) -> PromotionPreviewV1:
        profile = self.require_profile(profile_id)
        if target not in PROMOTION_TARGETS:
            raise SourceAnalysisError("晋升目标无效", code="INVALID_INPUT")
        target_ref = PROMOTION_TARGETS[target]
        target_path = self.novel_root / target_ref
        current = target_path.read_text(encoding="utf-8") if target_path.is_file() else ""
        included = [item.claim for item in profile.common_methods]
        if target in {"style", "inspiration", "setting_candidates"}:
            included.extend(item.claim for item in profile.optional_variants)
        included = list(dict.fromkeys(included))
        heading = {
            "style": "参考方法画像",
            "rules": "参考方法规则候选",
            "inspiration": "参考灵感候选",
            "setting_candidates": "参考设定候选",
        }[target]
        generated = [
            f"# {heading}",
            "",
            "> 仅保留跨作品可复用方法；来源原句、专名和专属设定已排除。",
            "",
            f"- profile: {profile.profile_id}",
            f"- sources: {', '.join(profile.source_ids)}",
            "",
            "## 候选",
            "",
        ]
        generated.extend(f"- {claim}" for claim in included)
        proposed = "\n".join(generated).rstrip() + "\n"
        diff = "".join(
            difflib.unified_diff(
                current.splitlines(keepends=True),
                proposed.splitlines(keepends=True),
                fromfile=target_ref,
                tofile=target_ref,
            )
        )
        preview_id = f"promotion_{self._sha256(profile.profile_id + target + proposed)[:16]}"
        preview = PromotionPreviewV1(
            preview_id=preview_id,
            profile_id=profile.profile_id,
            target=cast(PromotionTarget, target),
            target_ref=target_ref,
            baseline_revision=self._revision(current),
            proposed_content=proposed,
            unified_diff=diff,
            included_claims=included,
            excluded_claims=profile.excluded_items,
            created_at=self._now(),
        )
        self._write_model(self.preview_path(preview_id), preview)
        return preview

    def apply_promotion(self, preview_id: str, *, confirm: bool) -> dict[str, Any]:
        if not confirm:
            raise SourceAnalysisError("晋升需要显式确认", code="CONFIRMATION_REQUIRED")
        preview = self.require_preview(preview_id)
        target = (self.novel_root / preview.target_ref).resolve()
        if self.novel_root.resolve() not in target.parents:
            raise SourceAnalysisError("晋升目标越界", code="PATH_OUT_OF_BOUNDS")
        current = target.read_text(encoding="utf-8") if target.is_file() else ""
        if self._revision(current) != preview.baseline_revision:
            raise SourceAnalysisError("目标已变化，请重新预览", code="DOCUMENT_CONFLICT")
        self._atomic_write_text(target, preview.proposed_content)
        return {
            "ok": True,
            "preview_id": preview.preview_id,
            "target": preview.target,
            "target_ref": preview.target_ref,
            "revision": self._revision(preview.proposed_content),
        }

    @staticmethod
    def estimate_tokens(text: str) -> int:
        if not text:
            return 0
        return max(1, math.ceil(len(text.encode("utf-8")) / 3))

    @classmethod
    def split_text(cls, text: str, input_budget_tokens: int) -> list[tuple[int, int]]:
        if not text:
            return []
        ranges: list[tuple[int, int]] = []
        start = 0
        while start < len(text):
            low, high = start + 1, len(text)
            best = low
            while low <= high:
                middle = (low + high) // 2
                if cls.estimate_tokens(text[start:middle]) <= input_budget_tokens:
                    best = middle
                    low = middle + 1
                else:
                    high = middle - 1
            end = best
            if end < len(text):
                end = cls._preferred_boundary(text, start, end)
            if end <= start:
                end = min(len(text), start + 1)
            ranges.append((start, end))
            start = end
        return ranges

    @staticmethod
    def _preferred_boundary(text: str, start: int, hard_end: int) -> int:
        minimum = start + max(1, int((hard_end - start) * 0.55))
        window = text[start:hard_end]
        patterns = (
            r"\n(?=第[零一二三四五六七八九十百千万\d]+[章节回卷篇]\b)",
            r"\n\n+",
            r"[。！？!?]\s*",
            r"\n",
        )
        for pattern in patterns:
            candidates = [start + match.end() for match in re.finditer(pattern, window)]
            candidates = [position for position in candidates if minimum <= position <= hard_end]
            if candidates:
                return candidates[-1]
        return hard_end

    def load_manifest(self, source_id: str) -> SourceManifestV2 | None:
        path = self.manifest_path(self._source_id(source_id))
        return self._read_model(path, SourceManifestV2)

    def require_manifest(self, source_id: str) -> SourceManifestV2:
        manifest = self.load_manifest(source_id)
        if manifest is None:
            raise SourceAnalysisError("V2 来源分析不存在", code="NOT_FOUND")
        return manifest

    def load_report(self, source_id: str) -> SourceReportV2 | None:
        return self._read_model(self.report_path(self._source_id(source_id)), SourceReportV2)

    def require_profile(self, profile_id: str) -> ReferenceProfileV1:
        profile = self._read_model(self.profile_path(profile_id), ReferenceProfileV1)
        if profile is None:
            raise SourceAnalysisError("参考画像不存在", code="NOT_FOUND")
        return profile

    def require_preview(self, preview_id: str) -> PromotionPreviewV1:
        preview = self._read_model(self.preview_path(preview_id), PromotionPreviewV1)
        if preview is None:
            raise SourceAnalysisError("晋升预览不存在", code="NOT_FOUND")
        return preview

    def source_root(self, source_id: str) -> Path:
        return self.sources_root / self._source_id(source_id)

    def analysis_root(self, source_id: str) -> Path:
        return self.source_root(source_id) / "analysis_v2"

    def manifest_path(self, source_id: str) -> Path:
        return self.analysis_root(source_id) / "manifest.json"

    def report_path(self, source_id: str) -> Path:
        return self.analysis_root(source_id) / "report.json"

    def profile_path(self, profile_id: str) -> Path:
        clean = self._artifact_id(profile_id, "profile_")
        return self.profiles_root / f"{clean}.json"

    def preview_path(self, preview_id: str) -> Path:
        clean = self._artifact_id(preview_id, "promotion_")
        return self.profiles_root / "previews" / f"{clean}.json"

    @staticmethod
    def _chunk_report_ref(chunk_id: str) -> str:
        return f"chunk_reports/{chunk_id}.json"

    def _run_analyzer(
        self,
        analyzer: ChunkAnalyzer | None,
        text: str,
        context: dict[str, Any],
        chunk: SourceChunkRecordV2,
    ) -> SourceChunkReportV2:
        if analyzer is not None:
            return self._coerce_report(analyzer(text, context), text, context, chunk)
        first_payload: dict[str, Any] | None = None
        try:
            first_payload = self._llm_analyze(text, context)
            report = self._coerce_report(first_payload, text, context, chunk)
            self._validate_generated_report_quality(report, chunk_chars=len(text))
            return report
        except Exception as first_error:
            if str(getattr(first_error, "code", "")) in {
                "MODEL_EMPTY_RESPONSE",
                "MODEL_OUTPUT_TRUNCATED",
                "MODEL_REASONING_ONLY",
            }:
                raise
            repaired = self._llm_analyze(
                text,
                context,
                repair={
                    "invalid_payload": first_payload,
                    "validation_error": self._bounded_error(first_error),
                },
            )
            report = self._coerce_report(repaired, text, context, chunk)
            self._validate_generated_report_quality(report, chunk_chars=len(text))
            return report

    def _llm_analyze(
        self,
        text: str,
        context: dict[str, Any],
        repair: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        from tools.llm import LLMClient, LLMConfig, Message
        from tools.llm.response import classify_response

        config = LLMConfig.from_env()
        provider = str(getattr(config, "provider", "") or "").lower()
        base_url = str(getattr(config, "base_url", "") or "").lower()
        model = str(getattr(config, "model", "") or "").lower()
        if (
            provider in {"openai", "custom"}
            and "api.deepseek.com" in base_url
            and model == "deepseek-v4-flash"
        ):
            extra = dict(getattr(config, "extra", {}) or {})
            extra_body = dict(extra.get("extra_body") or {})
            thinking = extra_body.get("thinking")
            if not (isinstance(thinking, dict) and thinking.get("type")):
                extra_body["thinking"] = {"type": "disabled"}
                extra["extra_body"] = extra_body
            extra.setdefault("response_format", {"type": "json_object"})
            config.extra = extra
        client = LLMClient(config)
        schema_hint = {
            "summary": "本块摘要",
            "findings": [
                {
                    "category": "method",
                    "claim": "可审阅结论",
                    "confidence": 0.8,
                    "reusable": True,
                    "source_bound": False,
                    "evidence": [{"start": 0, "end": 4, "quote": "原文四字"}],
                }
            ],
        }
        system = (
            "你是长篇小说参考文本分析器。只返回 JSON，不使用 Markdown。"
            "所有 evidence start/end 都是当前片段内的 0-based [start,end) 字符偏移，"
            "quote 必须逐字等于该范围；每个结论至少一个证据。"
            "区分可复用方法与来源绑定内容，后者 source_bound=true 且 reusable=false。"
            "人物、世界设定、关系、成长体系、时间线和具体伏笔应提取为来源绑定事实；"
            "若同时能归纳出不含专名和独特表达的创作方法，另写一条 reusable=true 的方法结论。"
            "arc_summary 只概括当前片段可证实的故事弧进展，chapter_summary 只概括章节事件；"
            "thread 表示尚未回收或正在发展的叙事线索，hook 表示推动继续阅读的局部钩子。"
            "输出 4 到 8 条 findings，最多 8 条；只提取当前片段能由引文直接证明的类别，"
            "严禁为了覆盖分析重点而硬凑结论。优先选择信息量高且类别不重复的结论。"
            "summary 不超过 180 字，claim 不超过 120 字；"
            "每条 finding 只保留 1 到 2 个最强证据，每段 quote 不超过 120 字；"
            "不同结论优先使用不同证据，同一引文最多支持两条结论；证据必须直接支持 claim，"
            "不要只引用标题、称呼或与结论无关的句子；长片段应从开头、中段、后段取证，"
            "至少覆盖三个不同位置；"
            "完整 JSON 不超过 6000 字，不要复述大段原文。"
            f"允许 category: {', '.join(sorted(FOCUS_VALUES))}。"
        )
        user = (
            f"分析重点：{', '.join(context['focus'])}\n"
            f"章节提示：{context['chapter_hint'] or '无'}\n"
            f"输出形状：{json.dumps(schema_hint, ensure_ascii=False)}\n\n"
            f"片段：\n{text}"
        )
        if repair is not None:
            user = (
                "上一次 JSON 未通过严格校验。只修复格式、字段或证据偏移，不增加无证据结论。\n"
                f"错误：{repair['validation_error']}\n"
                "无效输出："
                + json.dumps(
                    repair["invalid_payload"], ensure_ascii=False, default=str
                )[:6000]
                + "\n\n"
                + user
            )
        response = client.chat(
            [Message("system", system), Message("user", user)],
            temperature=0.2,
            stream=long_generation_stream(),
        )
        classify_response(
            response.content,
            finish_reason=getattr(response, "finish_reason", ""),
            reasoning=getattr(response, "reasoning", ""),
        )
        payload = self._parse_json_object(response.content)
        payload["model"] = response.model or config.model
        return payload

    def _coerce_report(
        self,
        payload: dict[str, Any] | SourceChunkReportV2,
        chunk_text: str,
        context: dict[str, Any],
        chunk: SourceChunkRecordV2,
    ) -> SourceChunkReportV2:
        if isinstance(payload, SourceChunkReportV2):
            return payload
        if not isinstance(payload, dict):
            raise SourceAnalysisError("分析结果必须是 JSON 对象", code="INVALID_MODEL_OUTPUT")
        findings: list[SourceFindingV2] = []
        raw_findings = payload.get("findings")
        if not isinstance(raw_findings, list):
            raise SourceAnalysisError("分析结果缺少 findings", code="INVALID_MODEL_OUTPUT")
        for raw in raw_findings:
            if not isinstance(raw, dict):
                raise SourceAnalysisError("finding 必须是对象", code="INVALID_MODEL_OUTPUT")
            evidence_refs: list[EvidenceRef] = []
            raw_evidence = raw.get("evidence")
            if not isinstance(raw_evidence, list) or not raw_evidence:
                raise SourceAnalysisError("finding 缺少证据", code="INVALID_MODEL_OUTPUT")
            for evidence in raw_evidence:
                if not isinstance(evidence, dict):
                    raise SourceAnalysisError("evidence 必须是对象", code="INVALID_MODEL_OUTPUT")
                local_start = int(evidence.get("start", -1))
                local_end = int(evidence.get("end", -1))
                supplied = str(evidence.get("quote") or "")
                if not supplied:
                    continue
                valid_range = (
                    local_start >= 0
                    and local_end > local_start
                    and local_end <= len(chunk_text)
                )
                quote = chunk_text[local_start:local_end] if valid_range else ""
                if supplied != quote:
                    matches: list[tuple[int, int]] = []
                    cursor = chunk_text.find(supplied)
                    while cursor >= 0:
                        matches.append((cursor, cursor + len(supplied)))
                        cursor = chunk_text.find(supplied, cursor + 1)
                    if not matches:
                        matches = self._equivalent_evidence_spans(chunk_text, supplied)
                    if not matches:
                        continue
                    preferred = max(0, local_start)
                    local_start, local_end = min(
                        matches, key=lambda span: abs(span[0] - preferred)
                    )
                    quote = chunk_text[local_start:local_end]
                absolute_start = chunk.start + local_start
                absolute_end = chunk.start + local_end
                evidence_refs.append(
                    EvidenceRef(
                        source_id=context["source_id"],
                        chunk_id=chunk.chunk_id,
                        start=absolute_start,
                        end=absolute_end,
                        line_start=int(context.get("line_offset", 1))
                        + self._line_number(chunk_text, local_start)
                        - 1,
                        line_end=int(context.get("line_offset", 1))
                        + self._line_number(chunk_text, max(local_start, local_end - 1))
                        - 1,
                        quote=quote,
                        sha256=self._sha256(quote),
                    )
                )
            if not evidence_refs:
                raise SourceAnalysisError(
                    "finding 没有可逐字验证的证据", code="INVALID_EVIDENCE"
                )
            category = str(raw.get("category") or "method")
            claim = str(raw.get("claim") or "").strip()
            identity = category + "\0" + claim + "\0" + evidence_refs[0].sha256
            findings.append(
                SourceFindingV2(
                    finding_id=f"finding_{self._sha256(identity)[:16]}",
                    category=cast(FindingCategory, category),
                    claim=claim,
                    confidence=float(raw.get("confidence", 0.5)),
                    reusable=bool(raw.get("reusable", False)),
                    source_bound=bool(raw.get("source_bound", False)),
                    evidence=evidence_refs,
                )
            )
        return SourceChunkReportV2(
            source_id=context["source_id"],
            chunk_id=chunk.chunk_id,
            chunk_sha256=chunk.sha256,
            prompt_version=PROMPT_VERSION,
            model=str(payload.get("model") or ""),
            summary=str(payload.get("summary") or "").strip(),
            findings=findings,
        )

    @staticmethod
    def _validate_generated_report_quality(
        report: SourceChunkReportV2, *, chunk_chars: int
    ) -> None:
        if len(report.findings) > 8:
            raise SourceAnalysisError(
                "生成报告超过每块 8 条结论上限",
                code="INVALID_MODEL_OUTPUT",
            )
        minimum = 0 if chunk_chars <= 200 else 1 if chunk_chars <= 500 else 3
        if len(report.findings) < minimum:
            raise SourceAnalysisError(
                f"生成报告覆盖不足，当前片段至少需要 {minimum} 条有效结论",
                code="INVALID_MODEL_OUTPUT",
            )
        if len(report.findings) < 3:
            return
        primary_spans = [
            (finding.evidence[0].start, finding.evidence[0].end)
            for finding in report.findings
        ]
        distinct_spans = set(primary_spans)
        if len(distinct_spans) < 3:
            raise SourceAnalysisError(
                "生成报告的证据过度重复，至少需要三处不同引文",
                code="INVALID_EVIDENCE",
            )
        if any(primary_spans.count(span) > 2 for span in distinct_spans):
            raise SourceAnalysisError(
                "同一引文不能支持两条以上结论",
                code="INVALID_EVIDENCE",
            )

    def _validate_evidence(
        self,
        report: SourceChunkReportV2,
        source_text: str,
        chunk: SourceChunkRecordV2,
    ) -> None:
        if report.chunk_id != chunk.chunk_id or report.chunk_sha256 != chunk.sha256:
            raise SourceAnalysisError("分块报告与 manifest 不匹配", code="INVALID_EVIDENCE")
        for finding in report.findings:
            if finding.source_bound and finding.reusable:
                raise SourceAnalysisError(
                    "来源绑定结论不能标记为可复用", code="INVALID_MODEL_OUTPUT"
                )
            for evidence in finding.evidence:
                if evidence.start < chunk.start or evidence.end > chunk.end:
                    raise SourceAnalysisError("证据不属于当前分块", code="INVALID_EVIDENCE")
                if source_text[evidence.start : evidence.end] != evidence.quote:
                    raise SourceAnalysisError("证据与来源快照不一致", code="INVALID_EVIDENCE")
                if evidence.sha256 != self._sha256(evidence.quote):
                    raise SourceAnalysisError("证据哈希不一致", code="INVALID_EVIDENCE")

    def _build_source_report(self, manifest: SourceManifestV2) -> SourceReportV2:
        findings: list[SourceFindingV2] = []
        summaries: list[str] = []
        models: list[str] = []
        failed: list[str] = []
        bound: list[str] = []
        source_text = self._read_snapshot(manifest)
        for chunk in manifest.chunks:
            if chunk.status != "completed" or not chunk.report_ref:
                failed.append(chunk.chunk_id)
                continue
            chunk_report = self._read_model(
                self.analysis_root(manifest.source_id) / chunk.report_ref,
                SourceChunkReportV2,
            )
            if chunk_report is None:
                failed.append(chunk.chunk_id)
                continue
            summaries.append(chunk_report.summary)
            if chunk_report.model:
                models.append(chunk_report.model)
            findings.extend(chunk_report.findings)
            bound.extend(
                item.claim for item in chunk_report.findings if item.source_bound
            )
        bound.extend(self._source_terms(source_text))
        status: Literal["completed", "incomplete"] = (
            "completed" if not failed and bool(manifest.chunks) else "incomplete"
        )
        source_report = SourceReportV2(
            source_id=manifest.source_id,
            relative_name=manifest.relative_name,
            source_sha256=manifest.source_sha256,
            prompt_version=manifest.prompt_version,
            models=list(dict.fromkeys(models)),
            status=status,
            summary="\n".join(summaries),
            findings=findings,
            failed_chunks=failed,
            source_bound_terms=list(dict.fromkeys(bound)),
            generated_at=self._now(),
        )
        self._write_model(self.report_path(manifest.source_id), source_report)
        return source_report

    def _reusable_reports(
        self, source_id: str, manifest: SourceManifestV2
    ) -> dict[str, list[tuple[SourceChunkRecordV2, SourceChunkReportV2]]]:
        reusable: dict[
            str, list[tuple[SourceChunkRecordV2, SourceChunkReportV2]]
        ] = defaultdict(list)
        if manifest.prompt_version != PROMPT_VERSION:
            return reusable
        for chunk in manifest.chunks:
            if chunk.status != "completed" or not chunk.report_ref:
                continue
            report = self._read_model(
                self.analysis_root(source_id) / chunk.report_ref,
                SourceChunkReportV2,
            )
            if report is not None and report.chunk_sha256 == chunk.sha256:
                reusable[chunk.sha256].append((chunk, report))
        return reusable

    def _rebase_report(
        self,
        report: SourceChunkReportV2,
        *,
        old_chunk: SourceChunkRecordV2,
        new_chunk: SourceChunkRecordV2,
        source_text: str,
    ) -> SourceChunkReportV2:
        payload = report.model_dump(mode="json")
        payload["chunk_id"] = new_chunk.chunk_id
        payload["chunk_sha256"] = new_chunk.sha256
        for finding in payload["findings"]:
            for evidence in finding["evidence"]:
                relative_start = int(evidence["start"]) - old_chunk.start
                relative_end = int(evidence["end"]) - old_chunk.start
                evidence["chunk_id"] = new_chunk.chunk_id
                evidence["start"] = new_chunk.start + relative_start
                evidence["end"] = new_chunk.start + relative_end
                evidence["line_start"] = (
                    source_text.count("\n", 0, int(evidence["start"])) + 1
                )
                evidence["line_end"] = (
                    source_text.count(
                        "\n",
                        0,
                        max(int(evidence["start"]), int(evidence["end"]) - 1),
                    )
                    + 1
                )
        rebased = SourceChunkReportV2.model_validate(payload)
        self._validate_evidence(rebased, source_text, new_chunk)
        return rebased

    def _read_snapshot(self, manifest: SourceManifestV2) -> str:
        path = (self.source_root(manifest.source_id) / manifest.source_snapshot_ref).resolve()
        if self.source_root(manifest.source_id).resolve() not in path.parents or not path.is_file():
            raise SourceAnalysisError("来源快照不存在或越界", code="NOT_FOUND")
        raw_content = path.read_bytes()
        if hashlib.sha256(raw_content).hexdigest() != manifest.source_sha256:
            raise SourceAnalysisError("来源快照哈希不一致", code="SOURCE_CHANGED")
        try:
            return raw_content.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise SourceAnalysisError("来源快照不是有效 UTF-8", code="SOURCE_CHANGED") from exc

    @staticmethod
    def _refresh_manifest_status(manifest: SourceManifestV2) -> None:
        statuses = {chunk.status for chunk in manifest.chunks}
        if statuses == {"completed"}:
            manifest.status = "completed"
        elif "failed" in statuses:
            manifest.status = "failed"
        elif "running" in statuses:
            manifest.status = "running"
        elif "stale" in statuses:
            manifest.status = "stale"
        else:
            manifest.status = "pending"

    @staticmethod
    def _focus(values: Iterable[str] | None) -> list[str]:
        clean = list(dict.fromkeys(str(item).strip() for item in (values or FOCUS_VALUES)))
        if not clean or any(item not in FOCUS_VALUES for item in clean):
            raise SourceAnalysisError("分析重点无效", code="INVALID_INPUT")
        return clean

    @staticmethod
    def _source_id(value: str) -> str:
        clean = str(value or "").strip()
        if not clean or not re.fullmatch(r"[\w.-]{1,64}", clean) or ".." in clean:
            raise SourceAnalysisError("来源 ID 无效", code="INVALID_INPUT")
        return clean

    @staticmethod
    def _artifact_id(value: str, prefix: str) -> str:
        clean = str(value or "")
        if not clean.startswith(prefix) or not re.fullmatch(r"[A-Za-z0-9_-]{8,80}", clean):
            raise SourceAnalysisError("产物 ID 无效", code="INVALID_INPUT")
        return clean

    @staticmethod
    def _chapter_hint(text: str) -> str:
        for line in text[:1200].splitlines():
            stripped = line.strip()
            if re.match(r"^(第.+[章节回卷篇]|Chapter\s+\d+|序章|楔子|尾声)", stripped, re.I):
                return stripped[:120]
        first = next((line.strip() for line in text.splitlines() if line.strip()), "")
        return first[:120]

    @staticmethod
    def _line_number(text: str, offset: int) -> int:
        return text.count("\n", 0, max(0, offset)) + 1

    @staticmethod
    def _equivalent_evidence_spans(text: str, supplied: str) -> list[tuple[int, int]]:
        translation = str.maketrans(
            {
                "“": '"',
                "”": '"',
                "「": '"',
                "」": '"',
                "『": '"',
                "』": '"',
                "‘": "'",
                "’": "'",
            }
        )
        normalized_text = text.translate(translation)
        normalized_quote = supplied.translate(translation)
        if not normalized_quote or len(normalized_quote) != len(supplied):
            return []
        spans: list[tuple[int, int]] = []
        cursor = normalized_text.find(normalized_quote)
        while cursor >= 0:
            spans.append((cursor, cursor + len(supplied)))
            cursor = normalized_text.find(normalized_quote, cursor + 1)
        return spans

    @staticmethod
    def _normalize_claim(claim: str) -> str:
        return re.sub(r"[\W_]+", "", claim, flags=re.UNICODE).lower()

    @classmethod
    def _semantic_claim_key(
        cls,
        claim: str,
        existing: dict[str, list[tuple[str, SourceFindingV2]]],
    ) -> str:
        normalized = cls._normalize_claim(claim)
        if normalized in existing:
            return normalized
        best_key = ""
        best_score = 0.0
        for key, entries in existing.items():
            if not entries or cls._negation_signature(claim) != cls._negation_signature(
                entries[0][1].claim
            ):
                continue
            score = cls._claim_similarity(normalized, key)
            if score > best_score:
                best_key = key
                best_score = score
        return best_key if best_score >= 0.72 else normalized

    @staticmethod
    def _claim_similarity(left: str, right: str) -> float:
        if not left or not right:
            return 0.0
        sequence = difflib.SequenceMatcher(None, left, right).ratio()
        left_pairs = {left[index : index + 2] for index in range(max(1, len(left) - 1))}
        right_pairs = {right[index : index + 2] for index in range(max(1, len(right) - 1))}
        overlap = len(left_pairs & right_pairs) / max(1, min(len(left_pairs), len(right_pairs)))
        return max(sequence, overlap)

    @staticmethod
    def _negation_signature(claim: str) -> bool:
        return bool(re.search(r"(?:不|别|勿|避免|禁止|减少|弱化|省略|克制)", claim))

    @classmethod
    def _claim_is_safe(cls, finding: SourceFindingV2, bound_terms: list[str]) -> bool:
        normalized_claim = cls._normalize_claim(finding.claim)
        for term in bound_terms:
            normalized_term = cls._normalize_claim(term)
            if len(normalized_term) >= 2 and normalized_term in normalized_claim:
                return False
        for evidence in finding.evidence:
            normalized_quote = cls._normalize_claim(evidence.quote)
            if len(normalized_claim) >= 8 and normalized_claim in normalized_quote:
                return False
            if len(normalized_quote) >= 8 and normalized_quote in normalized_claim:
                return False
        return True

    @staticmethod
    def _source_terms(text: str) -> list[str]:
        terms: list[str] = []
        quote_patterns = (
            r"《([^》]{2,32})》",
            r"“([^”]{2,24})”",
            r"「([^」]{2,24})」",
            r"『([^』]{2,24})』",
            r"`([^`]{2,32})`",
        )
        for pattern in quote_patterns:
            terms.extend(match.group(1).strip() for match in re.finditer(pattern, text))
        for line in text.splitlines():
            stripped = line.strip()
            match = re.match(
                r"^(?:第[零一二三四五六七八九十百千万\d]+[章节回卷篇]|Chapter\s+\d+)"
                r"[\s:：·—-]*(.{2,40})$",
                stripped,
                re.I,
            )
            if match:
                terms.append(match.group(1).strip())
        terms.extend(re.findall(r"\b[A-Z][A-Za-z0-9_-]{2,31}\b", text))
        return list(dict.fromkeys(term for term in terms if term))[:200]

    @staticmethod
    def _dedupe_evidence(items: Iterable[EvidenceRef]) -> list[EvidenceRef]:
        result: list[EvidenceRef] = []
        seen: set[tuple[str, int, int]] = set()
        for item in items:
            key = (item.source_id, item.start, item.end)
            if key not in seen:
                seen.add(key)
                result.append(item)
        return result[:24]

    @staticmethod
    def _parse_json_object(content: str) -> dict[str, Any]:
        text = str(content or "").strip()
        if text.startswith("```"):
            parts = text.split("```")
            text = parts[1] if len(parts) > 2 else text
            if text.lstrip().startswith("json"):
                text = text.lstrip()[4:].lstrip()
        payload = json.loads(text)
        if not isinstance(payload, dict):
            raise SourceAnalysisError("模型输出不是 JSON 对象", code="INVALID_MODEL_OUTPUT")
        return payload

    @staticmethod
    def _bounded_error(exc: Exception) -> str:
        return re.sub(r"sk-[A-Za-z0-9_-]{8,}", "[REDACTED]", str(exc))[:800]

    @staticmethod
    def _sha256(content: str) -> str:
        return hashlib.sha256(content.encode("utf-8")).hexdigest()

    @classmethod
    def _revision(cls, content: str) -> str:
        return "sha256:" + cls._sha256(content)

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _read_model(path: Path, model_type: type[ModelT]) -> ModelT | None:
        if not path.is_file():
            return None
        try:
            return model_type.model_validate_json(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    @staticmethod
    def _write_model(path: Path, model: Any) -> None:
        SourceAnalysisService._atomic_write_text(path, model.model_dump_json(indent=2) + "\n")

    @staticmethod
    def _atomic_write_text(path: Path, content: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            handle.write(content.encode("utf-8"))
            handle.flush()
            os.fsync(handle.fileno())
            temporary = Path(handle.name)
        temporary.replace(path)
