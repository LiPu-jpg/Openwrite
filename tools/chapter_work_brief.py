"""Read-only, canonical work summary for one manuscript chapter.

The brief is a projection over existing manuscript, acceptance, review,
revision, task, outline and foreshadowing records.  It deliberately owns no
state of its own so callers cannot make a dashboard disagree with the files
that drive writing and delivery gates.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from tools.manuscript_acceptance import ManuscriptAcceptanceService
from tools.novel_workspace import count_writing_units
from tools.outline_tree import build_outline_structure
from tools.review_store import (
    ReviewStore,
    canonical_review_decision,
    review_is_deliverable,
)
from tools.revision_store import RevisionStore
from tools.task_store import TaskStore
from tools.writing_targets import normalize_writing_targets

SCHEMA_VERSION = "openwrite.chapter-work-brief.v1"
CHAPTER_ID_RE = re.compile(r"ch_(\d+)")
EXPLICIT_TARGET_RE = re.compile(r"预估字数\s*[:：]\s*([\d,]+)")


class ChapterWorkBriefError(RuntimeError):
    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.code = code


class ChapterWorkBriefService:
    """Build chapter work briefs strictly within one project and novel root."""

    FORESHADOW_CATEGORIES = (
        "must_resolve",
        "overdue",
        "upcoming",
        "prohibited_early",
        "to_plant",
    )
    _CLOSED_FORESHADOW_STATUSES = {
        "已收",
        "废弃",
        "resolved",
        "closed",
        "abandoned",
        "discarded",
    }
    _PLANNED_FORESHADOW_STATUSES = {
        "planned",
        "计划",
        "待埋",
        "unplanted",
        "to_plant",
    }

    def __init__(self, project_root: Path, novel_id: str) -> None:
        self.project_root = Path(project_root).resolve()
        self.novel_id = str(novel_id)
        self.novel_root = (
            self.project_root / "data" / "novels" / self.novel_id
        ).resolve()

    def get(
        self,
        chapter_id: str,
        *,
        document_id: str | None = None,
        recent_limit: int = 20,
    ) -> dict[str, Any]:
        """Return a fresh brief for exactly one canonical manuscript file."""
        clean_id = self._chapter_id(chapter_id)
        path = self._chapter_path(clean_id)
        try:
            content = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            raise ChapterWorkBriefError(
                f"章节无法读取: {clean_id}", code="CHAPTER_UNREADABLE"
            ) from exc

        current_revision = self._text_revision(content)
        writing_units = count_writing_units(content)
        manuscript = {
            "path": path.relative_to(self.novel_root).as_posix(),
            "title": self._title(content, clean_id),
            "save_status": "saved_empty" if not content.strip() else "saved",
            "current_revision": current_revision,
            "sha256": current_revision.removeprefix("sha256:"),
            "writing_units": writing_units,
            "bytes": len(content.encode("utf-8")),
            "modified_at": self._mtime(path),
        }
        acceptance = self._acceptance(clean_id)
        review = self._review(clean_id, current_revision)
        revisions = RevisionStore(self.project_root, self.novel_id).list(
            chapter_id=clean_id
        )
        latest_revision = self._latest_revision(revisions)
        tasks = self._tasks(clean_id)
        target = self._target(clean_id, writing_units)
        foreshadowing = self._foreshadowing(clean_id)
        recent_edits = self._recent_edits(
            chapter_id=clean_id,
            document_id=document_id,
            manuscript=manuscript,
            acceptance=acceptance,
            review=review,
            revisions=revisions,
            tasks=tasks,
            limit=recent_limit,
        )
        return {
            "schema_version": SCHEMA_VERSION,
            "novel_id": self.novel_id,
            "chapter_id": clean_id,
            "document_id": document_id,
            "manuscript": manuscript,
            "acceptance": acceptance,
            "review": review,
            "latest_revision": latest_revision,
            "tasks": tasks,
            "target": target,
            "recent_edits": recent_edits,
            "foreshadowing": foreshadowing,
        }

    def list(
        self,
        *,
        document_ids: Mapping[str, str] | None = None,
        recent_limit: int = 20,
    ) -> dict[str, Any]:
        """Return briefs in numeric chapter order, rejecting duplicate IDs."""
        manuscript_root = self.novel_root / "data" / "manuscript"
        paths = [
            path
            for path in manuscript_root.rglob("ch_*.md")
            if path.is_file() and CHAPTER_ID_RE.fullmatch(path.stem)
        ] if manuscript_root.is_dir() else []
        by_id: dict[str, list[Path]] = {}
        for path in paths:
            by_id.setdefault(path.stem, []).append(path)
        duplicates = sorted(chapter_id for chapter_id, items in by_id.items() if len(items) > 1)
        if duplicates:
            raise ChapterWorkBriefError(
                f"章节 ID 重复: {', '.join(duplicates)}",
                code="DUPLICATE_CHAPTER_ID",
            )
        chapter_ids = sorted(by_id, key=self._chapter_number)
        return {
            "schema_version": "openwrite.chapter-work-surface.v1",
            "novel_id": self.novel_id,
            "chapters": [
                self.get(
                    chapter_id,
                    document_id=(document_ids or {}).get(chapter_id),
                    recent_limit=recent_limit,
                )
                for chapter_id in chapter_ids
            ],
        }

    def _chapter_path(self, chapter_id: str) -> Path:
        manuscript_root = self.novel_root / "data" / "manuscript"
        matches = [
            path
            for path in manuscript_root.rglob(f"{chapter_id}.md")
            if path.is_file() and path.stem == chapter_id
        ] if manuscript_root.is_dir() else []
        if not matches:
            raise ChapterWorkBriefError(
                f"章节不存在: {chapter_id}", code="CHAPTER_NOT_FOUND"
            )
        if len(matches) != 1:
            raise ChapterWorkBriefError(
                f"章节 ID 重复: {chapter_id}", code="DUPLICATE_CHAPTER_ID"
            )
        return matches[0]

    def _acceptance(self, chapter_id: str) -> dict[str, Any]:
        surface = ManuscriptAcceptanceService(
            self.project_root, self.novel_id
        ).inspect()
        head = next(
            (
                item
                for item in surface.get("chapters", [])
                if item.get("chapter_id") == chapter_id
            ),
            None,
        )
        if not isinstance(head, dict):
            return {
                "status": "baseline_required",
                "blocking": True,
                "accepted_revision": "",
                "pending_revision": "",
                "facts_revision": "",
                "operation_id": "",
                "source": "",
                "updated_at": "",
                "impacts": [],
            }
        impacts = [
            dict(item)
            for item in surface.get("impacts", [])
            if isinstance(item, Mapping)
            and str(item.get("source_chapter") or "") == chapter_id
        ]
        status = str(head.get("status") or "baseline_required")
        if status == "current" and any(
            str(item.get("status") or "") == "needs_review" for item in impacts
        ):
            status = "needs_review"
        return {
            "status": status,
            "blocking": status != "current",
            "accepted_revision": str(head.get("accepted_revision") or ""),
            "pending_revision": str(head.get("pending_revision") or ""),
            "facts_revision": str(head.get("facts_revision") or ""),
            "operation_id": str(head.get("operation_id") or ""),
            "source": str(head.get("source") or ""),
            "updated_at": str(head.get("updated_at") or ""),
            "impacts": impacts,
        }

    def _review(self, chapter_id: str, current_revision: str) -> dict[str, Any]:
        store = ReviewStore(self.project_root, self.novel_id)
        revisioned = store.load_revisioned(chapter_id)
        if revisioned is None:
            return {
                "exists": False,
                "schema_version": "",
                "review_revision": "",
                "freshness_status": "missing",
                "stale": False,
                "stale_reason": "",
                "gate_status": "not_reviewed",
                "delivery_status": "not_reviewed",
                "deliverable": False,
                "quality_score": None,
                "coverage": None,
                "source_revision": "",
                "current_source_revision": current_revision,
                "reviewed_at": "",
                "issue_count": 0,
                "latest_closure": None,
            }
        stored, review_revision = revisioned
        source_revision = str(stored.get("source_revision") or "")
        try:
            decision = canonical_review_decision(
                stored, current_source_revision=current_revision
            )
        except (TypeError, ValueError):
            return {
                "exists": True,
                "schema_version": "invalid",
                "review_revision": review_revision,
                "freshness_status": "invalid",
                "stale": bool(stored.get("stale")),
                "stale_reason": str(stored.get("stale_reason") or ""),
                "gate_status": "inconclusive",
                "delivery_status": "inconclusive",
                "deliverable": False,
                "quality_score": None,
                "coverage": None,
                "source_revision": source_revision,
                "current_source_revision": current_revision,
                "reviewed_at": str(stored.get("reviewed_at") or ""),
                "issue_count": self._issue_count(stored),
                "latest_closure": self._latest_closure(stored),
            }
        freshness = str(decision.get("freshness_status") or "unknown")
        if stored.get("stale"):
            freshness = "stale"
        elif source_revision and current_revision:
            freshness = "current" if source_revision == current_revision else "stale"
        delivery = str(decision.get("delivery_status") or "inconclusive")
        if freshness == "stale":
            delivery = "stale"
        deliverable = review_is_deliverable(
            stored, current_source_revision=current_revision
        ) and freshness != "stale"
        return {
            "exists": True,
            "schema_version": str(decision.get("schema_version") or ""),
            "review_revision": review_revision,
            "freshness_status": freshness,
            "stale": freshness == "stale",
            "stale_reason": str(stored.get("stale_reason") or ""),
            "gate_status": str(decision.get("gate_status") or "inconclusive"),
            "delivery_status": delivery,
            "deliverable": deliverable,
            "quality_score": decision.get("quality_score"),
            "coverage": decision.get("coverage"),
            "source_revision": source_revision,
            "current_source_revision": current_revision,
            "reviewed_at": str(stored.get("reviewed_at") or ""),
            "issue_count": self._issue_count(stored),
            "latest_closure": self._latest_closure(stored),
        }

    @staticmethod
    def _issue_count(review: Mapping[str, Any]) -> int:
        issues = review.get("issue_details")
        return len(issues) if isinstance(issues, list) else 0

    @staticmethod
    def _latest_closure(review: Mapping[str, Any]) -> dict[str, Any] | None:
        closures = review.get("revision_closures")
        if not isinstance(closures, list):
            return None
        raw = next(
            (item for item in reversed(closures) if isinstance(item, Mapping)),
            None,
        )
        if raw is None:
            return None
        outcomes = [
            {
                "issue_id": str(item.get("issue_id") or ""),
                "outcome": str(item.get("outcome") or ""),
            }
            for item in raw.get("issue_outcomes", [])
            if isinstance(item, Mapping)
            and str(item.get("outcome") or "") in {"resolved", "retained"}
        ]
        regressions = [
            {
                "issue_id": str(item.get("issue_id") or ""),
                "outcome": "regressed",
                "issue": dict(item.get("issue") or {})
                if isinstance(item.get("issue"), Mapping)
                else {},
            }
            for item in raw.get("regressions", [])
            if isinstance(item, Mapping)
        ]
        return {
            key: str(raw.get(key) or "")
            for key in (
                "schema_version",
                "closure_id",
                "proposal_id",
                "source_review_revision",
                "stale_review_revision",
                "rereview_review_revision",
                "source_revision",
                "applied_revision",
                "rereview_source_revision",
                "closed_at",
            )
        } | {
            "selected_issue_ids": [
                str(item)
                for item in raw.get("selected_issue_ids", [])
                if str(item)
            ]
            if isinstance(raw.get("selected_issue_ids"), list)
            else [],
            "issue_outcomes": outcomes,
            "regressions": regressions,
        }

    @staticmethod
    def _latest_revision(revisions: list[dict[str, Any]]) -> dict[str, Any] | None:
        if not revisions:
            return None
        item = revisions[0]
        status = str(item.get("status") or "")
        return {
            "proposal_id": str(item.get("proposal_id") or ""),
            "kind": str(item.get("kind") or ""),
            "status": status,
            "apply_status": status,
            "source_revision": str(item.get("source_revision") or ""),
            "applied_revision": str(item.get("applied_revision") or ""),
            "review_issue_ids": [
                str(value) for value in item.get("review_issue_ids", [])
            ] if isinstance(item.get("review_issue_ids"), list) else [],
            "created_at": str(item.get("created_at") or ""),
            "applied_at": str(item.get("applied_at") or ""),
        }

    def _tasks(self, chapter_id: str) -> list[dict[str, Any]]:
        related: list[dict[str, Any]] = []
        for task in TaskStore(self.project_root, self.novel_id).list(limit=500):
            task_chapter = str(task.get("chapter_id") or "")
            if not task_chapter and isinstance(task.get("input"), Mapping):
                task_chapter = str(task["input"].get("chapter_id") or "")
            if task_chapter != chapter_id:
                continue
            related.append(
                {
                    "task_id": str(task.get("task_id") or ""),
                    "schema_version": str(task.get("schema_version") or ""),
                    "type": str(task.get("type") or ""),
                    "status": str(task.get("status") or ""),
                    "phase": task.get("phase"),
                    "progress": task.get("progress"),
                    "retryable": bool(task.get("retryable")),
                    "input_summary": str(task.get("input_summary") or ""),
                    "created_at": str(task.get("created_at") or ""),
                    "updated_at": str(task.get("updated_at") or ""),
                    "completed_at": str(task.get("completed_at") or ""),
                }
            )
        return related

    def _target(self, chapter_id: str, actual_units: int) -> dict[str, Any]:
        config = self._yaml_mapping(self.project_root / "novel_config.yaml")
        targets = normalize_writing_targets(config.get("writing_targets"))
        target_units = int(targets["chapter_words"])
        source = "project_default"
        structure = build_outline_structure(
            self.novel_root,
            chapter_id=chapter_id,
            writing_targets=targets,
        )
        for node in self._outline_nodes(structure.get("roots")):
            if node.get("kind") != "chapter" or node.get("id") != chapter_id:
                continue
            target_units = max(1, int(node.get("chapter_target_words") or target_units))
            content = str(node.get("content") or "")
            if EXPLICIT_TARGET_RE.search(content):
                source = "outline"
            break
        return {
            "writing_units": target_units,
            "source": source,
            "actual_units": actual_units,
            "remaining_units": max(0, target_units - actual_units),
            "progress": actual_units / target_units if target_units else 0.0,
        }

    @classmethod
    def _outline_nodes(cls, roots: Any) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        if not isinstance(roots, list):
            return result
        for raw in roots:
            if not isinstance(raw, dict):
                continue
            result.append(raw)
            result.extend(cls._outline_nodes(raw.get("children")))
        return result

    def _foreshadowing(self, chapter_id: str) -> dict[str, Any]:
        result: dict[str, Any] = {name: [] for name in self.FORESHADOW_CATEGORIES}
        dag_path = self.novel_root / "data" / "foreshadowing" / "dag.yaml"
        if not dag_path.is_file():
            return {**result, "source_revision": "", "counts": self._counts(result)}
        try:
            raw_bytes = dag_path.read_bytes()
            payload = yaml.safe_load(raw_bytes.decode("utf-8")) or {}
        except (OSError, UnicodeError, yaml.YAMLError):
            return {**result, "source_revision": "", "counts": self._counts(result)}
        if not isinstance(payload, Mapping):
            return {**result, "source_revision": "", "counts": self._counts(result)}
        graph_revision = "sha256:" + hashlib.sha256(raw_bytes).hexdigest()
        statuses = payload.get("status") if isinstance(payload.get("status"), Mapping) else {}
        for key, raw in self._foreshadow_nodes(payload.get("nodes")):
            status = str(statuses.get(key) or raw.get("status") or "").strip()
            if status.casefold() in self._CLOSED_FORESHADOW_STATUSES:
                continue
            item = self._foreshadow_item(key, raw, status, graph_revision)
            category = self._foreshadow_category(chapter_id, item)
            result[category].append(item)
        for name in self.FORESHADOW_CATEGORIES:
            result[name].sort(key=lambda item: (-int(item["weight"]), item["id"]))
        return {
            **result,
            "source_revision": graph_revision,
            "counts": self._counts(result),
        }

    @staticmethod
    def _foreshadow_nodes(value: Any) -> list[tuple[str, dict[str, Any]]]:
        if isinstance(value, Mapping):
            return [
                (str(key), dict(raw))
                for key, raw in value.items()
                if isinstance(raw, Mapping)
            ]
        if isinstance(value, list):
            result: list[tuple[str, dict[str, Any]]] = []
            for raw in value:
                if not isinstance(raw, Mapping):
                    continue
                item = dict(raw)
                key = str(item.get("id") or "")
                if not key:
                    canonical = json.dumps(item, ensure_ascii=False, sort_keys=True, default=str)
                    key = "foreshadow_" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:12]
                result.append((key, item))
            return result
        return []

    def _foreshadow_item(
        self,
        key: str,
        raw: dict[str, Any],
        status: str,
        graph_revision: str,
    ) -> dict[str, Any]:
        anchors = raw.get("anchors") if isinstance(raw.get("anchors"), Mapping) else {}
        plant = self._anchor(
            raw.get("plant_anchor")
            or anchors.get("plant")
            or raw.get("planned_plant_chapter")
            or raw.get("plant_chapter"),
            source="plant_anchor",
        )
        if not plant and raw.get("created_at"):
            plant = self._anchor(raw.get("created_at"), source="legacy_created_at")
        reveal = self._anchor(
            raw.get("reveal_anchor") or anchors.get("reveal"),
            source="reveal_anchor",
        )
        if not reveal and raw.get("target_chapter"):
            reveal = self._anchor(
                raw.get("target_chapter"), source="legacy_target_chapter"
            )
        earliest = str(
            raw.get("earliest_reveal")
            or raw.get("earliest_reveal_chapter")
            or ""
        ).strip()
        planned = bool(raw.get("planned")) or status.casefold() in self._PLANNED_FORESHADOW_STATUSES
        try:
            weight = max(1, min(10, int(raw.get("weight") or 5)))
        except (TypeError, ValueError):
            weight = 5
        return {
            "id": str(raw.get("id") or key),
            "content": str(raw.get("content") or ""),
            "status": status,
            "weight": weight,
            "layer": str(raw.get("layer") or ""),
            "planned": planned,
            "plant_anchor": plant,
            "reveal_anchor": reveal,
            "earliest_reveal": earliest,
            "source_revision": str(raw.get("source_revision") or graph_revision),
            "tags": [str(tag) for tag in raw.get("tags", [])]
            if isinstance(raw.get("tags"), list)
            else [],
        }

    @staticmethod
    def _anchor(value: Any, *, source: str) -> dict[str, Any]:
        if isinstance(value, Mapping):
            anchor = dict(value)
            chapter = str(
                anchor.get("chapter_id") or anchor.get("chapter") or ""
            ).strip()
            if chapter:
                anchor["chapter_id"] = chapter
            anchor.setdefault("source", source)
            return anchor
        chapter = str(value or "").strip()
        return {"chapter_id": chapter, "source": source} if chapter else {}

    def _foreshadow_category(self, chapter_id: str, item: Mapping[str, Any]) -> str:
        current = self._chapter_number(chapter_id)
        reveal = str((item.get("reveal_anchor") or {}).get("chapter_id") or "")
        target = self._optional_chapter_number(reveal)
        earliest = self._optional_chapter_number(str(item.get("earliest_reveal") or ""))
        plant = str((item.get("plant_anchor") or {}).get("chapter_id") or "")
        if target is not None and target < current:
            return "overdue"
        if bool(item.get("planned")) and plant == chapter_id:
            return "to_plant"
        if earliest is not None and current < earliest:
            return "prohibited_early"
        if reveal == chapter_id or target == current:
            return "must_resolve"
        return "upcoming"

    @classmethod
    def _counts(cls, groups: Mapping[str, Any]) -> dict[str, int]:
        return {
            name: len(groups.get(name, []))
            if isinstance(groups.get(name), list)
            else 0
            for name in cls.FORESHADOW_CATEGORIES
        }

    def _recent_edits(
        self,
        *,
        chapter_id: str,
        document_id: str | None,
        manuscript: Mapping[str, Any],
        acceptance: Mapping[str, Any],
        review: Mapping[str, Any],
        revisions: list[dict[str, Any]],
        tasks: list[dict[str, Any]],
        limit: int,
    ) -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []
        path = str(manuscript.get("path") or "")
        self._event(
            events,
            kind="manuscript_saved",
            updated_at=manuscript.get("modified_at"),
            event_id=str(manuscript.get("current_revision") or ""),
            status=str(manuscript.get("save_status") or ""),
            document_id=document_id,
            path=path,
            chapter_id=chapter_id,
            revision=str(manuscript.get("current_revision") or ""),
            writing_units_delta=None,
            reason=None,
        )
        self._event(
            events,
            kind="acceptance_updated",
            updated_at=acceptance.get("updated_at"),
            event_id=str(acceptance.get("operation_id") or "acceptance"),
            status=str(acceptance.get("status") or ""),
            document_id=document_id,
            path=path,
            chapter_id=chapter_id,
            revision=str(
                acceptance.get("pending_revision")
                or acceptance.get("accepted_revision")
                or ""
            ),
            writing_units_delta=None,
            reason=None,
        )
        self._event(
            events,
            kind="reviewed",
            updated_at=review.get("reviewed_at"),
            event_id=str(review.get("review_revision") or "review"),
            status=str(review.get("freshness_status") or ""),
            document_id=document_id,
            path=path,
            chapter_id=chapter_id,
            revision=str(review.get("review_revision") or ""),
            writing_units_delta=None,
            reason=str(review.get("stale_reason") or "") or None,
        )
        for revision in revisions:
            applied = str(revision.get("status") or "") == "applied"
            selection = revision.get("selection")
            selection = selection if isinstance(selection, Mapping) else {}
            replacement = str(revision.get("replacement_text") or "")
            original = str(selection.get("original_text") or "")
            writing_units_delta = (
                count_writing_units(replacement) - count_writing_units(original)
                if applied
                else None
            )
            rationale = str(revision.get("rationale") or "").strip()
            self._event(
                events,
                kind="revision_applied" if applied else "revision_updated",
                updated_at=(
                    revision.get("applied_at") if applied else revision.get("created_at")
                ),
                event_id=str(revision.get("proposal_id") or ""),
                status=str(revision.get("status") or ""),
                document_id=document_id,
                path=path,
                chapter_id=chapter_id,
                revision=str(
                    revision.get("applied_revision")
                    or revision.get("source_revision")
                    or ""
                ),
                writing_units_delta=writing_units_delta,
                reason=rationale or None,
            )
        for task in tasks:
            self._event(
                events,
                kind="task_updated",
                updated_at=task.get("updated_at") or task.get("created_at"),
                event_id=str(task.get("task_id") or ""),
                status=str(task.get("status") or ""),
                document_id=document_id,
                path=path,
                chapter_id=chapter_id,
                revision="",
                writing_units_delta=None,
                reason=str(task.get("input_summary") or "") or None,
            )
        events.sort(
            key=lambda item: (item["updated_at"], item["id"]), reverse=True
        )
        clean_limit = max(1, min(100, int(limit)))
        return events[:clean_limit]

    @staticmethod
    def _event(
        events: list[dict[str, Any]],
        *,
        kind: str,
        updated_at: Any,
        event_id: str,
        status: str,
        document_id: str | None,
        path: str,
        chapter_id: str,
        revision: str,
        writing_units_delta: int | None,
        reason: str | None,
    ) -> None:
        timestamp = str(updated_at or "")
        if timestamp:
            events.append(
                {
                    "kind": kind,
                    "id": event_id,
                    "status": status,
                    "document_id": document_id,
                    "path": path,
                    "chapter_id": chapter_id,
                    "revision": revision,
                    "updated_at": timestamp,
                    "writing_units_delta": writing_units_delta,
                    "reason": reason,
                }
            )

    @staticmethod
    def _yaml_mapping(path: Path) -> dict[str, Any]:
        if not path.is_file():
            return {}
        try:
            value = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except (OSError, UnicodeError, yaml.YAMLError):
            return {}
        return dict(value) if isinstance(value, Mapping) else {}

    @staticmethod
    def _title(content: str, chapter_id: str) -> str:
        for line in content.splitlines():
            match = re.match(r"^\s*#{1,6}\s+(.+?)\s*$", line)
            if match:
                return match.group(1)
        return chapter_id

    @staticmethod
    def _text_revision(content: str) -> str:
        return "sha256:" + hashlib.sha256(content.encode("utf-8")).hexdigest()

    @staticmethod
    def _mtime(path: Path) -> str:
        return datetime.fromtimestamp(
            path.stat().st_mtime, tz=timezone.utc
        ).isoformat()

    @staticmethod
    def _chapter_id(value: str) -> str:
        clean = str(value or "").strip()
        if not CHAPTER_ID_RE.fullmatch(clean):
            raise ChapterWorkBriefError("章节 ID 无效", code="INVALID_CHAPTER_ID")
        return clean

    @staticmethod
    def _chapter_number(value: str) -> int:
        match = CHAPTER_ID_RE.fullmatch(str(value or ""))
        return int(match.group(1)) if match else 10**12

    @staticmethod
    def _optional_chapter_number(value: str) -> int | None:
        match = CHAPTER_ID_RE.fullmatch(str(value or "").strip())
        return int(match.group(1)) if match else None
