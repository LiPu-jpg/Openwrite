"""Private reference library and explicit project adoption workflow."""

from __future__ import annotations

import difflib
import hashlib
import json
import math
import os
import re
import tempfile
from collections.abc import Iterable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from models.source_analysis import (
    ReferenceAdoptionPreviewV1,
    ReferenceAdoptionSelectionV1,
    ReferenceAdoptionV1,
    ReferenceLibraryRecordV1,
    ReferenceProfileV1,
    ReferenceStructureUnitV1,
    ReferenceStructureV1,
    StyleFingerprintV1,
)
from tools.source_analysis import ChunkAnalyzer, SourceAnalysisError, SourceAnalysisService

REFERENCE_INTENTS = {"reference", "continuation", "canon", "migration"}
ADOPTION_TARGET_REFS = {
    "rules": "data/rules/reference_adoptions.md",
    "inspiration": "data/planning/reference_inspiration.md",
    "setting_candidates": "data/planning/reference_setting_candidates.md",
}
CHAPTER_HEADING_RE = re.compile(
    r"(?m)^[ \t]*(?:#{1,6}[ \t]*)?(?P<title>(?:"
    r"第[零一二三四五六七八九十百千万两\d]+[卷部篇章节回集]|"
    r"(?:chapter|part|book)\s+[0-9ivxlcdm]+)[^\n]{0,80})$",
    re.IGNORECASE,
)


def default_reference_library_root() -> Path:
    configured = os.environ.get("OPENWRITE_REFERENCE_LIBRARY_ROOT", "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    return (Path.home() / ".local" / "share" / "openwrite" / "reference-library").resolve()


class ReferenceLibraryService:
    """Keep raw references outside projects and publish only confirmed snapshots."""

    def __init__(
        self,
        library_root: Path,
        *,
        project_root: Path | None = None,
        novel_id: str = "",
    ) -> None:
        self.library_root = Path(library_root).expanduser().resolve()
        self.sources_root = self.library_root / "sources"
        self.project_root = Path(project_root).resolve() if project_root is not None else None
        self.novel_id = str(novel_id or "")

    def prepare(
        self,
        source_id: str,
        content: str,
        *,
        title: str,
        relative_name: str,
        intent: str = "reference",
        focus: Iterable[str] | None = None,
        input_budget_tokens: int = 12000,
    ) -> dict[str, Any]:
        clean_id = self._source_id(source_id)
        clean_intent = str(intent or "reference").strip().lower()
        if clean_intent not in REFERENCE_INTENTS:
            raise SourceAnalysisError("参考资料导入意图无效", code="INVALID_INPUT")
        clean_title = str(title or "").strip() or Path(relative_name or clean_id).stem
        if len(clean_title) > 160:
            raise SourceAnalysisError("参考作品标题不能超过 160 字", code="INVALID_INPUT")

        analysis = self._analysis()
        prepared = analysis.prepare(
            clean_id,
            content,
            relative_name=relative_name,
            focus=focus,
            input_budget_tokens=input_budget_tokens,
        )
        manifest = prepared["manifest"]
        existing = self._read_record(clean_id)
        now = self._now()
        record = ReferenceLibraryRecordV1(
            source_id=clean_id,
            title=clean_title,
            relative_name=str(manifest["relative_name"]),
            intent=clean_intent,
            source_sha256=str(manifest["source_sha256"]),
            source_snapshot_ref=str(manifest["source_snapshot_ref"]),
            total_chars=int(manifest["total_chars"]),
            created_at=existing.created_at if existing else now,
            updated_at=now,
        )
        self._write_model(self._record_path(clean_id), record)

        previous_structure = self._read_structure(clean_id)
        structure = self._project_structure(clean_id, str(content), record.source_sha256)
        if (
            previous_structure is not None
            and previous_structure.status == "confirmed"
            and previous_structure.source_sha256 == structure.source_sha256
            and previous_structure.units == structure.units
        ):
            structure.status = "confirmed"
            structure.confirmed_at = previous_structure.confirmed_at
        self._write_model(self._structure_path(clean_id), structure)
        return {
            "record": record.model_dump(mode="json"),
            "structure": structure.model_dump(mode="json"),
            "analysis": prepared,
            "next_action": (
                "analyze" if structure.status == "confirmed" else "confirm_structure"
            ),
        }

    def confirm_structure(
        self,
        source_id: str,
        *,
        units: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        clean_id = self._source_id(source_id)
        record = self.require_record(clean_id)
        structure = self.require_structure(clean_id)
        if structure.source_sha256 != record.source_sha256:
            raise SourceAnalysisError("来源结构已过时，请重新导入", code="SOURCE_CHANGED")
        if units is not None:
            try:
                structure.units = [ReferenceStructureUnitV1.model_validate(item) for item in units]
                structure = ReferenceStructureV1.model_validate(
                    {**structure.model_dump(mode="json"), "units": units}
                )
            except ValidationError as exc:
                raise SourceAnalysisError(f"结构预览无效: {exc}", code="INVALID_INPUT") from exc
        if structure.units[-1].end != record.total_chars:
            raise SourceAnalysisError("结构预览必须覆盖完整原文", code="INVALID_INPUT")
        structure.status = "confirmed"
        structure.confirmed_at = self._now()
        self._write_model(self._structure_path(clean_id), structure)
        return {
            "record": record.model_dump(mode="json"),
            "structure": structure.model_dump(mode="json"),
            "next_action": "analyze",
        }

    def analyze(
        self,
        source_id: str,
        *,
        analyzer: ChunkAnalyzer | None = None,
        chunk_ids: Iterable[str] | None = None,
    ) -> dict[str, Any]:
        clean_id = self._source_id(source_id)
        structure = self.require_structure(clean_id)
        if structure.status != "confirmed":
            raise SourceAnalysisError(
                "请先确认卷章结构，再开始拆解", code="CONFIRMATION_REQUIRED"
            )
        result = self._analysis().analyze(
            clean_id,
            analyzer=analyzer,
            chunk_ids=chunk_ids,
        )
        assets: dict[str, Any] = {}
        if result.get("ok"):
            assets = self._build_assets(clean_id)
        return {**result, "assets": assets}

    def retry(
        self,
        source_id: str,
        chunk_id: str,
        *,
        analyzer: ChunkAnalyzer | None = None,
    ) -> dict[str, Any]:
        result = self._analysis().retry(
            self._source_id(source_id), chunk_id, analyzer=analyzer
        )
        if result.get("ok"):
            result["assets"] = self._build_assets(source_id)
        return result

    def list(self) -> list[dict[str, Any]]:
        if not self.sources_root.is_dir():
            return []
        records: list[dict[str, Any]] = []
        for path in sorted(self.sources_root.iterdir()):
            if not path.is_dir() or path.name.startswith("_"):
                continue
            try:
                records.append(self.status(path.name, include_report=False))
            except SourceAnalysisError:
                continue
        return sorted(
            records,
            key=lambda item: str(item.get("record", {}).get("updated_at", "")),
            reverse=True,
        )

    def list_profiles(self) -> list[dict[str, Any]]:
        """List synthesized profiles without exposing their full evidence payloads."""
        profiles_root = self.sources_root / "_profiles"
        if not profiles_root.is_dir():
            return []

        adoption_ids: dict[str, list[str]] = {}
        if self.project_root is not None and self.novel_id:
            novel_root = self.project_root / "data" / "novels" / self.novel_id
            for path in sorted(
                (novel_root / "data" / "reference_adoptions").glob("adoption_*.yaml")
            ):
                payload = self._read_yaml(path)
                profile_id = str(payload.get("profile_id") or "").strip()
                if profile_id:
                    adoption_ids.setdefault(profile_id, []).append(path.stem)

        result: list[dict[str, Any]] = []
        for path in sorted(profiles_root.glob("profile_*.json")):
            profile = self._read_model(path, ReferenceProfileV1)
            if profile is None:
                continue
            stale_source_ids: list[str] = []
            for source_id, expected_sha in profile.source_revisions.items():
                try:
                    current_sha = self.require_record(source_id).source_sha256
                except SourceAnalysisError:
                    current_sha = ""
                if current_sha != expected_sha:
                    stale_source_ids.append(source_id)
            result.append(
                {
                    "profile_id": profile.profile_id,
                    "source_ids": profile.source_ids,
                    "source_intents": profile.source_intents,
                    "generated_at": profile.generated_at,
                    "status": "stale" if stale_source_ids else "current",
                    "stale_source_ids": stale_source_ids,
                    "item_counts": {
                        "common_methods": len(profile.common_methods),
                        "differences": len(profile.differences),
                        "optional_variants": len(profile.optional_variants),
                        "conflicts": len(profile.conflicts),
                        "excluded": len(profile.excluded_items),
                    },
                    "adoption_ids": adoption_ids.get(profile.profile_id, []),
                }
            )
        return sorted(
            result,
            key=lambda item: str(item.get("generated_at") or ""),
            reverse=True,
        )

    def status(self, source_id: str, *, include_report: bool = True) -> dict[str, Any]:
        clean_id = self._source_id(source_id)
        record = self.require_record(clean_id)
        structure = self.require_structure(clean_id)
        analysis_status = self._analysis().status(clean_id)
        if not include_report:
            analysis_status = {
                key: analysis_status.get(key)
                for key in (
                    "source_id",
                    "status",
                    "change_status",
                    "source_sha256",
                    "total_chars",
                    "chunks",
                    "complete",
                )
            }
        return {
            "record": record.model_dump(mode="json"),
            "structure": structure.model_dump(mode="json"),
            "analysis": analysis_status,
            "assets": self._asset_index(clean_id),
        }

    def read_content(self, source_id: str) -> dict[str, Any]:
        """Return a read-only reference snapshot and its confirmed units."""
        clean_id = self._source_id(source_id)
        record = self.require_record(clean_id)
        structure = self.require_structure(clean_id)
        if structure.source_sha256 != record.source_sha256:
            raise SourceAnalysisError("来源结构已过时，请重新导入", code="SOURCE_CHANGED")
        text = self._snapshot_text(record)
        units: list[dict[str, Any]] = []
        for unit in structure.units:
            start = max(0, min(int(unit.start), len(text)))
            end = max(start, min(int(unit.end), len(text)))
            units.append(
                {
                    **unit.model_dump(mode="json"),
                    "content": text[start:end],
                }
            )
        return {
            "record": record.model_dump(mode="json"),
            "structure": structure.model_dump(mode="json"),
            "content": text,
            "units": units,
            "revision": self._revision(text),
        }

    def synthesize(self, source_ids: Iterable[str]) -> ReferenceProfileV1:
        clean_ids = list(dict.fromkeys(self._source_id(item) for item in source_ids))
        records = {source_id: self.require_record(source_id) for source_id in clean_ids}
        intents = {source_id: record.intent for source_id, record in records.items()}
        return self._analysis().synthesize(
            clean_ids,
            include_source_bound_from=[
                source_id
                for source_id, intent in intents.items()
                if intent in {"continuation", "canon", "migration"}
            ],
            source_intents=intents,
        )

    def profile(self, profile_id: str) -> ReferenceProfileV1:
        return self._analysis().require_profile(profile_id)

    def project_style_surface(self) -> dict[str, Any]:
        _, _, novel_root = self._require_project()
        style_root = novel_root / "data" / "style"
        recipe = self._read_yaml(style_root / "recipe.yaml")
        fingerprint = self._read_yaml(style_root / "fingerprint.yaml")
        composed_path = style_root / "composed.md"
        selections = recipe.get("selections") if isinstance(recipe, dict) else []
        if not isinstance(selections, list):
            selections = []
        adoption_root = novel_root / "data" / "reference_adoptions"
        adoptions = sorted(path.stem for path in adoption_root.glob("adoption_*.yaml"))
        return {
            "recipe": recipe,
            "fingerprint": fingerprint,
            "selections": selections,
            "adoptions": adoptions,
            "composed_ready": composed_path.is_file(),
            "composed_revision": (
                self._revision(composed_path.read_text(encoding="utf-8"))
                if composed_path.is_file()
                else ""
            ),
        }

    def preview_adoption(
        self,
        profile_id: str,
        selections: list[dict[str, Any]],
        *,
        rejected_item_ids: Iterable[str] | None = None,
    ) -> ReferenceAdoptionPreviewV1:
        project_root, novel_id, novel_root = self._require_project()
        profile = self.profile(profile_id)
        available = self._profile_items(profile)
        normalized: list[ReferenceAdoptionSelectionV1] = []
        primary_keys: set[tuple[str, str, str]] = set()
        for raw in selections:
            item_id = str(raw.get("item_id") or "").strip()
            item = available.get(item_id)
            if item is None:
                raise SourceAnalysisError(f"画像候选不存在: {item_id}", code="INVALID_INPUT")
            payload = {
                **raw,
                "item_id": item_id,
                "claim": str(raw.get("adapted_claim") or item.claim).strip(),
                "source_ids": item.source_ids,
                "evidence": [e.model_dump(mode="json") for e in item.evidence],
                "source_bound": item.source_bound,
            }
            try:
                selection = ReferenceAdoptionSelectionV1.model_validate(payload)
            except ValidationError as exc:
                raise SourceAnalysisError(f"采纳选择无效: {exc}", code="INVALID_INPUT") from exc
            if item.source_bound:
                if selection.target == "style":
                    raise SourceAnalysisError(
                        "来源绑定事实不能作为风格配方", code="INVALID_INPUT"
                    )
                if any(
                    self.require_record(source_id).intent == "reference"
                    for source_id in item.source_ids
                ):
                    raise SourceAnalysisError(
                        "参考模式中的来源绑定事实不能晋升到项目", code="INVALID_INPUT"
                    )
            if selection.role == "primary" and selection.target == "style":
                key = (selection.dimension, selection.scope, selection.scope_id)
                if key in primary_keys:
                    raise SourceAnalysisError(
                        "同一范围和风格维度只能有一个主风格", code="INVALID_INPUT"
                    )
                primary_keys.add(key)
            normalized.append(selection)
        if not normalized:
            raise SourceAnalysisError("至少选择一条候选", code="INVALID_INPUT")

        selected_ids = {item.item_id for item in normalized}
        rejected = list(
            dict.fromkeys(
                str(item).strip()
                for item in (
                    rejected_item_ids
                    if rejected_item_ids is not None
                    else (set(available) - selected_ids)
                )
                if str(item).strip() and str(item).strip() not in selected_ids
            )
        )
        identity = json.dumps(
            {
                "profile": profile.profile_id,
                "selections": [item.model_dump(mode="json") for item in normalized],
                "rejected": rejected,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        adoption_id = f"adoption_{self._sha256(identity)[:16]}"
        adoption = ReferenceAdoptionV1(
            adoption_id=adoption_id,
            novel_id=novel_id,
            profile_id=profile.profile_id,
            source_revisions=profile.source_revisions,
            selections=normalized,
            rejected_item_ids=rejected,
            created_at=self._now(),
        )
        proposed_files = self._project_outputs(adoption)
        baseline_revisions: dict[str, str] = {}
        diffs: list[str] = []
        for relative_ref, proposed in proposed_files.items():
            path = (novel_root / relative_ref).resolve()
            if novel_root not in path.parents:
                raise SourceAnalysisError("采纳目标越界", code="PATH_OUT_OF_BOUNDS")
            current = path.read_text(encoding="utf-8") if path.is_file() else ""
            baseline_revisions[relative_ref] = self._revision(current)
            diffs.append(
                "".join(
                    difflib.unified_diff(
                        current.splitlines(keepends=True),
                        proposed.splitlines(keepends=True),
                        fromfile=relative_ref,
                        tofile=relative_ref,
                    )
                )
            )
        preview_identity = identity + json.dumps(baseline_revisions, sort_keys=True)
        preview_id = f"adoption_preview_{self._sha256(preview_identity)[:16]}"
        preview = ReferenceAdoptionPreviewV1(
            preview_id=preview_id,
            adoption=adoption,
            baseline_revisions=baseline_revisions,
            proposed_files=proposed_files,
            unified_diff="\n".join(part for part in diffs if part).strip(),
            created_at=self._now(),
        )
        self._write_model(self._preview_path(preview_id), preview)
        return preview

    def apply_adoption(self, preview_id: str, *, confirm: bool) -> dict[str, Any]:
        if not confirm:
            raise SourceAnalysisError("采纳需要显式确认", code="CONFIRMATION_REQUIRED")
        preview = self._read_model(self._preview_path(preview_id), ReferenceAdoptionPreviewV1)
        if preview is None:
            raise SourceAnalysisError("采纳预览不存在", code="NOT_FOUND")
        project_root, novel_id, novel_root = self._require_project()
        for source_id, expected_sha in preview.adoption.source_revisions.items():
            if self.require_record(source_id).source_sha256 != expected_sha:
                raise SourceAnalysisError(
                    f"参考来源 {source_id} 已变化，请重新审议", code="SOURCE_CHANGED"
                )
        for relative_ref, proposed in preview.proposed_files.items():
            target = (novel_root / relative_ref).resolve()
            if novel_root not in target.parents:
                raise SourceAnalysisError("采纳目标越界", code="PATH_OUT_OF_BOUNDS")
            current = target.read_text(encoding="utf-8") if target.is_file() else ""
            if self._revision(current) != preview.baseline_revisions.get(relative_ref):
                raise SourceAnalysisError(
                    f"项目文件 {relative_ref} 已变化，请重新预览",
                    code="DOCUMENT_CONFLICT",
                )
        for relative_ref, proposed in preview.proposed_files.items():
            self._atomic_write_text(novel_root / relative_ref, proposed)

        from tools.style_synthesizer import synthesize_style_document

        style_result = synthesize_style_document(
            project_root,
            novel_id,
            "reference-recipe",
            allow_llm=False,
        )
        return {
            "ok": True,
            "adoption_id": preview.adoption.adoption_id,
            "profile_id": preview.adoption.profile_id,
            "written": sorted(preview.proposed_files),
            "style_manifest": str(style_result["manifest_path"]),
            "style_document": str(style_result["composed_path"]),
        }

    def _project_outputs(self, proposed: ReferenceAdoptionV1) -> dict[str, str]:
        _, novel_id, novel_root = self._require_project()
        adoption_ref = f"data/reference_adoptions/{proposed.adoption_id}.yaml"
        existing: dict[str, ReferenceAdoptionV1] = {}
        adoption_root = novel_root / "data" / "reference_adoptions"
        if adoption_root.is_dir():
            for path in sorted(adoption_root.glob("adoption_*.yaml")):
                try:
                    loaded = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
                    adoption = ReferenceAdoptionV1.model_validate(loaded)
                    existing[adoption.adoption_id] = adoption
                except (OSError, yaml.YAMLError, ValidationError):
                    continue
        existing[proposed.adoption_id] = proposed
        adoptions = sorted(existing.values(), key=lambda item: item.adoption_id)
        style_items = [
            item
            for adoption in adoptions
            for item in adoption.selections
            if item.target == "style"
        ]
        recipe = {
            "schema_version": 1,
            "novel_id": novel_id,
            "updated_at": self._now(),
            "adoption_ids": [item.adoption_id for item in adoptions],
            "selections": [item.model_dump(mode="json") for item in style_items],
            "priority_order": [
                "author_intent",
                "project_hard_rules",
                "chapter_override",
                "arc_override",
                "project_recipe",
                "reference_defaults",
            ],
        }
        outputs = {
            adoption_ref: yaml.safe_dump(
                proposed.model_dump(mode="json"), allow_unicode=True, sort_keys=False
            ),
            "data/style/recipe.yaml": yaml.safe_dump(
                recipe, allow_unicode=True, sort_keys=False
            ),
            "data/style/fingerprint.yaml": yaml.safe_dump(
                self._fingerprint_targets(adoptions),
                allow_unicode=True,
                sort_keys=False,
            ),
        }
        for target, relative_ref in ADOPTION_TARGET_REFS.items():
            target_items = [
                selection
                for adoption in adoptions
                for selection in adoption.selections
                if selection.target == target
            ]
            outputs[relative_ref] = self._render_candidate_document(target, target_items)
        return outputs

    def _fingerprint_targets(self, adoptions: list[ReferenceAdoptionV1]) -> dict[str, Any]:
        style_items = [
            selection
            for adoption in adoptions
            for selection in adoption.selections
            if selection.target == "style"
        ]
        source_ids = list(
            dict.fromkeys(source for selection in style_items for source in selection.source_ids)
        )
        fingerprints = [
            fingerprint
            for source_id in source_ids
            if (fingerprint := self._read_fingerprint(source_id)) is not None
        ]

        def target(field: str, *, padding: float = 0.1) -> dict[str, float]:
            values = [float(getattr(item, field)) for item in fingerprints]
            if not values:
                return {"min": 0.0, "max": 0.0}
            low, high = min(values), max(values)
            margin = max(abs(high - low) * 0.25, max(abs(low), abs(high)) * padding)
            return {"min": round(max(0.0, low - margin), 3), "max": round(high + margin, 3)}

        primary = [item.claim for item in style_items if item.role == "primary"]
        validation = [
            item.claim for item in style_items if item.role == "validation_only"
        ]
        avoid = [item.claim for item in style_items if item.role == "avoid"]
        narration = [item.claim for item in style_items if item.dimension == "narration"]
        language = [item.claim for item in style_items if item.dimension == "language"]
        rhythm = [item.claim for item in style_items if item.dimension == "rhythm"]
        return {
            "schema_version": 2,
            "mode": "review_validation",
            "writer_injection": False,
            "source_ids": source_ids,
            "primary_signals": primary,
            "voice": "；".join(narration[:4]),
            "language_style": "；".join(language[:4]),
            "rhythm": "；".join(rhythm[:4]),
            "targets": {
                "avg_sentence_chars": target("avg_sentence_chars"),
                "sentence_stddev": target("sentence_stddev"),
                "avg_paragraph_chars": target("avg_paragraph_chars"),
                "dialogue_ratio": target("dialogue_ratio", padding=0.08),
                "short_paragraph_ratio": target("short_paragraph_ratio", padding=0.08),
            },
            "validation_rules": validation,
            "avoid": avoid,
            "updated_at": self._now(),
        }

    @staticmethod
    def _render_candidate_document(
        target: str, selections: list[ReferenceAdoptionSelectionV1]
    ) -> str:
        titles = {
            "rules": "参考方法规则",
            "inspiration": "参考灵感候选",
            "setting_candidates": "参考设定候选",
        }
        lines = [f"# {titles[target]}", "", "> 仅包含用户明确采纳的抽象结论。", ""]
        for item in selections:
            lines.append(f"- {item.claim}")
        if not selections:
            lines.append("- （尚未采纳）")
        return "\n".join(lines).rstrip() + "\n"

    def _build_assets(self, source_id: str) -> dict[str, Any]:
        clean_id = self._source_id(source_id)
        record = self.require_record(clean_id)
        report = self._analysis().load_report(clean_id)
        if report is None or report.status != "completed":
            raise SourceAnalysisError("来源分析尚未完成", code="SOURCE_INCOMPLETE")
        asset_root = self._asset_root(clean_id)
        mapping = {
            "style": {"voice", "pacing", "reader_drive", "method"},
            "structure": {"promise", "structure", "conflict", "hook"},
            "characters": {"character"},
            "world": {"world"},
            "relationships": {"relationship"},
            "progression": {"progression"},
            "timeline": {"timeline"},
            "threads": {"thread", "hook"},
            "summaries": {"arc_summary", "chapter_summary"},
            "risks": {"risk"},
        }
        written: dict[str, Any] = {}
        for name, categories in mapping.items():
            findings = [
                item.model_dump(mode="json")
                for item in report.findings
                if item.category in categories
            ]
            payload = {
                "schema_version": 1,
                "source_id": clean_id,
                "source_sha256": record.source_sha256,
                "categories": sorted(categories),
                "findings": findings,
                "generated_at": self._now(),
            }
            path = asset_root / f"{name}.json"
            self._atomic_write_text(
                path, json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
            )
            written[name] = {"path": str(path), "items": len(findings)}
        fingerprint = self._fingerprint(clean_id)
        self._write_model(asset_root / "fingerprint.json", fingerprint)
        written["fingerprint"] = {
            "path": str(asset_root / "fingerprint.json"),
            "metrics": 9,
        }
        return written

    def _fingerprint(self, source_id: str) -> StyleFingerprintV1:
        record = self.require_record(source_id)
        text = self._snapshot_text(record)
        sentences = [
            item.strip()
            for item in re.split(r"[。！？!?\n]+", text)
            if item.strip() and not CHAPTER_HEADING_RE.fullmatch(item.strip())
        ]
        paragraphs = [item.strip() for item in re.split(r"\n\s*\n|\n", text) if item.strip()]
        sentence_lengths = [self._writing_units(item) for item in sentences]
        paragraph_lengths = [self._writing_units(item) for item in paragraphs]
        avg_sentence = self._mean(sentence_lengths)
        variance = self._mean([(value - avg_sentence) ** 2 for value in sentence_lengths])
        nonspace = max(1, len(re.sub(r"\s+", "", text)))
        dialogue_lines = [
            item
            for item in paragraphs
            if re.search(r"[“”\"「」『』]", item)
            or re.match(r"^[^，。！？!?\n]{1,12}[：:]", item)
        ]
        dialogue_units = sum(self._writing_units(item) for item in dialogue_lines)
        return StyleFingerprintV1(
            source_id=source_id,
            source_sha256=record.source_sha256,
            sentence_count=len(sentences),
            paragraph_count=len(paragraphs),
            avg_sentence_chars=round(avg_sentence, 3),
            sentence_stddev=round(math.sqrt(max(0.0, variance)), 3),
            avg_paragraph_chars=round(self._mean(paragraph_lengths), 3),
            paragraph_min_chars=min(paragraph_lengths, default=0),
            paragraph_max_chars=max(paragraph_lengths, default=0),
            dialogue_ratio=round(min(1.0, dialogue_units / nonspace), 4),
            short_paragraph_ratio=round(
                sum(1 for value in paragraph_lengths if value <= 25)
                / max(1, len(paragraph_lengths)),
                4,
            ),
            punctuation_per_1000={
                mark: round(text.count(mark) * 1000 / nonspace, 3)
                for mark in ("，", "。", "！", "？", "；", "：")
            },
            pov_markers={
                marker: len(re.findall(marker, text))
                for marker in ("我", "我们", "他", "她", "他们", "她们")
            },
            generated_at=self._now(),
        )

    def _project_structure(
        self, source_id: str, text: str, source_sha256: str
    ) -> ReferenceStructureV1:
        matches = list(CHAPTER_HEADING_RE.finditer(text))
        units: list[ReferenceStructureUnitV1] = []
        if matches:
            if matches[0].start() > 0:
                units.append(
                    ReferenceStructureUnitV1(
                        unit_id="front_0000",
                        kind="front_matter",
                        title="章前内容",
                        start=0,
                        end=matches[0].start(),
                    )
                )
            for index, match in enumerate(matches):
                title = match.group("title").strip()
                kind = "volume" if re.search(r"[卷部]|^(?:part|book)\b", title, re.I) else "chapter"
                units.append(
                    ReferenceStructureUnitV1(
                        unit_id=f"{kind}_{index + 1:04d}",
                        kind=kind,
                        title=title,
                        start=match.start(),
                        end=matches[index + 1].start() if index + 1 < len(matches) else len(text),
                    )
                )
        else:
            units.append(
                ReferenceStructureUnitV1(
                    unit_id="body_0001",
                    kind="body",
                    title="全文",
                    start=0,
                    end=len(text),
                )
            )
        return ReferenceStructureV1(
            source_id=source_id,
            source_sha256=source_sha256,
            status="awaiting_confirmation",
            units=units,
            generated_at=self._now(),
        )

    def _analysis(self) -> SourceAnalysisService:
        project_root = self.project_root or self.library_root
        novel_id = self.novel_id or "_reference_library"
        return SourceAnalysisService(
            project_root,
            novel_id,
            sources_root=self.sources_root,
        )

    def require_record(self, source_id: str) -> ReferenceLibraryRecordV1:
        record = self._read_record(self._source_id(source_id))
        if record is None:
            raise SourceAnalysisError("参考作品不存在", code="NOT_FOUND")
        return record

    def require_structure(self, source_id: str) -> ReferenceStructureV1:
        structure = self._read_structure(self._source_id(source_id))
        if structure is None:
            raise SourceAnalysisError("参考作品结构不存在", code="NOT_FOUND")
        return structure

    def _read_record(self, source_id: str) -> ReferenceLibraryRecordV1 | None:
        return self._read_model(self._record_path(source_id), ReferenceLibraryRecordV1)

    def _read_structure(self, source_id: str) -> ReferenceStructureV1 | None:
        return self._read_model(self._structure_path(source_id), ReferenceStructureV1)

    def _read_fingerprint(self, source_id: str) -> StyleFingerprintV1 | None:
        return self._read_model(
            self._asset_root(source_id) / "fingerprint.json", StyleFingerprintV1
        )

    def _snapshot_text(self, record: ReferenceLibraryRecordV1) -> str:
        path = self.sources_root / record.source_id / record.source_snapshot_ref
        if not path.is_file():
            raise SourceAnalysisError("参考作品原文快照缺失", code="NOT_FOUND")
        return path.read_text(encoding="utf-8")

    def _asset_index(self, source_id: str) -> list[dict[str, Any]]:
        root = self._asset_root(source_id)
        if not root.is_dir():
            return []
        result: list[dict[str, Any]] = []
        for path in sorted(root.glob("*.json")):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            result.append(
                {
                    "kind": path.stem,
                    "items": len(payload.get("findings") or []) if isinstance(payload, dict) else 0,
                    "revision": self._revision(path.read_text(encoding="utf-8")),
                }
            )
        return result

    @staticmethod
    def _profile_items(profile: ReferenceProfileV1) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for item in [
            *profile.common_methods,
            *profile.differences,
            *profile.optional_variants,
        ]:
            identity = (item.category + ":" + item.claim).encode("utf-8")
            item_id = item.item_id or f"item_{hashlib.sha256(identity).hexdigest()[:16]}"
            item.item_id = item_id
            result[item_id] = item
        return result

    def _require_project(self) -> tuple[Path, str, Path]:
        if self.project_root is None or not self.novel_id:
            raise SourceAnalysisError("当前操作需要打开小说项目", code="INVALID_PROJECT")
        novel_root = self.project_root / "data" / "novels" / self.novel_id
        if not novel_root.is_dir():
            raise SourceAnalysisError("小说项目不存在", code="INVALID_PROJECT")
        return self.project_root, self.novel_id, novel_root.resolve()

    def _record_path(self, source_id: str) -> Path:
        return self.sources_root / source_id / "library.json"

    def _structure_path(self, source_id: str) -> Path:
        return self.sources_root / source_id / "structure.json"

    def _asset_root(self, source_id: str) -> Path:
        return self.sources_root / self._source_id(source_id) / "assets"

    def _preview_path(self, preview_id: str) -> Path:
        clean = str(preview_id).strip()
        if not re.fullmatch(r"adoption_preview_[0-9a-f]{16}", clean):
            raise SourceAnalysisError("采纳预览 ID 无效", code="INVALID_INPUT")
        return self.library_root / "adoption-previews" / f"{clean}.json"

    @staticmethod
    def _source_id(value: str) -> str:
        clean = str(value or "").strip()
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{1,63}", clean):
            raise SourceAnalysisError(
                "来源 ID 需为 2-64 位字母、数字、横线或下划线",
                code="INVALID_INPUT",
            )
        return clean

    @staticmethod
    def _mean(values: list[float] | list[int]) -> float:
        return sum(values) / len(values) if values else 0.0

    @staticmethod
    def _writing_units(text: str) -> int:
        cjk = re.findall(r"[\u3400-\u4dbf\u4e00-\u9fff]", text)
        words = re.findall(
            r"[A-Za-z0-9]+(?:['’-][A-Za-z0-9]+)?",
            re.sub(r"[\u3400-\u4dbf\u4e00-\u9fff]", " ", text),
        )
        return len(cjk) + len(words)

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _sha256(value: str) -> str:
        return hashlib.sha256(value.encode("utf-8")).hexdigest()

    @staticmethod
    def _revision(value: str) -> str:
        return hashlib.sha256(value.encode("utf-8")).hexdigest()

    @staticmethod
    def _atomic_write_text(path: Path, content: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, raw_path = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
        temp_path = Path(raw_path)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_path, path)
        finally:
            temp_path.unlink(missing_ok=True)

    def _write_model(self, path: Path, model: Any) -> None:
        self._atomic_write_text(
            path,
            json.dumps(model.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
        )

    @staticmethod
    def _read_model(path: Path, model_type: Any) -> Any | None:
        if not path.is_file():
            return None
        try:
            return model_type.model_validate_json(path.read_text(encoding="utf-8"))
        except (OSError, ValidationError, ValueError):
            return None

    @staticmethod
    def _read_yaml(path: Path) -> dict[str, Any]:
        if not path.is_file():
            return {}
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except (OSError, yaml.YAMLError):
            return {}
        return data if isinstance(data, dict) else {}
