"""Canonical scene identity, ordering, migration, metadata, and safe moves.

The manuscript remains canonical prose.  The scene sidecar stores stable identity,
metadata, and revision-bound character offsets; it is never a second copy of the
text and never serves as an independent retrieval runtime.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from base64 import b64decode, b64encode
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from tools.project_lock import ProjectBusyError, ProjectWriteLock
from tools.reading_order import ReadingOrderService

SURFACE_SCHEMA_VERSION = "openwrite.scene-structure.v1"
CHAPTER_SCHEMA_VERSION = "openwrite.scene-chapter.v1"
SIDECAR_SCHEMA_VERSION = "openwrite.scene-sidecar.v1"
PREVIEW_SCHEMA_VERSION = "openwrite.scene-migration-preview.v1"
MIGRATION_SCHEMA_VERSION = "openwrite.scene-migration.v1"
MUTATION_SCHEMA_VERSION = "openwrite.scene-mutation.v1"
SCENE_ID_RE = re.compile(r"^scn_[A-Za-z0-9_-]{12,80}$")
MIGRATION_ID_RE = re.compile(r"^scmig_[A-Za-z0-9_-]{12,80}$")
SCENE_HEADING_RE = re.compile(
    r"^(?P<marks>#{2,6})\s+(?P<title>.*(?:场景|scene).*)\s*$",
    re.IGNORECASE | re.MULTILINE,
)
CHAPTER_HEADING_RE = re.compile(r"^#{1}\s+.+?(?:\n|$)", re.MULTILINE)
FaultInjector = Callable[[str], None]


class SceneStructureError(RuntimeError):
    """Stable domain failure for scene structure operations."""

    def __init__(
        self,
        message: str,
        *,
        code: str = "SCENE_STRUCTURE_ERROR",
        recoverable: bool = True,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.recoverable = recoverable
        self.details = dict(details or {})


class SceneStructureService:
    """Project-scoped canonical scene service."""

    def __init__(
        self,
        project_root: Path,
        novel_id: str,
        *,
        fault_injector: FaultInjector | None = None,
    ) -> None:
        self.project_root = Path(project_root).expanduser().resolve()
        self.novel_id = str(novel_id)
        novels_root = (self.project_root / "data" / "novels").resolve()
        self.novel_root = (novels_root / self.novel_id).resolve()
        try:
            self.novel_root.relative_to(novels_root)
        except ValueError as exc:
            raise SceneStructureError("作品 ID 越出项目目录", code="INVALID_NOVEL_ID") from exc
        self.root = self.novel_root / "data" / "story_structure"
        self.sidecar_path = self.root / "scenes.json"
        self.migrations_dir = self.root / "migrations"
        self._fault_injector = fault_injector

    def inspect(self) -> dict[str, Any]:
        """Alias used by domain consumers that call read surfaces ``inspect``."""
        return self.surface()

    def surface(self) -> dict[str, Any]:
        """Project the persisted anchors over the current canonical manuscripts."""
        reading = ReadingOrderService(self.project_root, self.novel_id).surface()
        raw_bytes, sidecar, load_issue = self._load_sidecar()
        if raw_bytes is None:
            issue = self._issue(
                "SCENE_STRUCTURE_ABSENT",
                severity="info",
                blocking=False,
            )
            return self._empty_surface(reading, status="absent", issues=[issue])
        if sidecar is None:
            return self._empty_surface(
                reading,
                status="ambiguous",
                issues=[load_issue or self._issue("SCENE_SIDECAR_INVALID")],
                sidecar_revision=self._digest(raw_bytes),
            )

        issues: list[dict[str, Any]] = []
        persisted_revision = str(sidecar.get("revision") or "")
        calculated_revision = self._sidecar_revision(sidecar)
        if sidecar.get("schema_version") != SIDECAR_SCHEMA_VERSION:
            issues.append(self._issue("SCENE_SIDECAR_SCHEMA_INVALID"))
        if sidecar.get("novel_id") != self.novel_id:
            issues.append(self._issue("SCENE_SIDECAR_NOVEL_MISMATCH"))
        if persisted_revision != calculated_revision:
            issues.append(self._issue("SCENE_SIDECAR_REVISION_INVALID"))
        sidecar_revision = (
            persisted_revision if persisted_revision == calculated_revision else calculated_revision
        )

        reading_documents = list(reading.get("documents") or [])
        by_document: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for document in reading_documents:
            by_document[str(document.get("document_id") or "")].append(document)
        chapter_rows = sidecar.get("chapters")
        raw_scenes = sidecar.get("scenes")
        if not isinstance(chapter_rows, list):
            chapter_rows = []
            issues.append(self._issue("SCENE_CHAPTER_INDEX_INVALID"))
        if not isinstance(raw_scenes, list):
            raw_scenes = []
            issues.append(self._issue("SCENE_LIST_INVALID"))

        chapter_sidecars: dict[str, dict[str, Any]] = {}
        for row in chapter_rows:
            if not isinstance(row, dict):
                issues.append(self._issue("SCENE_CHAPTER_ENTRY_INVALID"))
                continue
            document_id = str(row.get("document_id") or "")
            if not document_id or document_id in chapter_sidecars:
                issues.append(
                    self._issue(
                        "DUPLICATE_SCENE_CHAPTER",
                        document_id=document_id,
                    )
                )
                continue
            chapter_sidecars[document_id] = row

        chapters: list[dict[str, Any]] = []
        chapter_contents: dict[str, str] = {}
        for document in reading_documents:
            document_id = str(document.get("document_id") or "")
            locator = self._chapter_locator(document)
            row = chapter_sidecars.get(document_id)
            revision = str(document.get("revision") or "")
            freshness = "current"
            body_start = 0
            document_status = str(document.get("status") or "")
            if document_status == "missing":
                freshness = "planned_missing"
                body_start = -1
            elif len(by_document[document_id]) != 1:
                freshness = "ambiguous"
            elif row is None:
                freshness = "stale"
                issues.append(
                    self._issue(
                        "UNMIGRATED_CHAPTER",
                        severity="warning",
                        **locator,
                    )
                )
            else:
                body_start = self._integer(row.get("body_start"), default=-1)
                if str(row.get("chapter_id") or "") != str(document["chapter_id"]):
                    freshness = "ambiguous"
                    issues.append(
                        self._issue(
                            "SCENE_CHAPTER_ID_MISMATCH",
                            **locator,
                        )
                    )
                elif str(row.get("source_revision") or "") != revision:
                    freshness = "stale"
                    issues.append(
                        self._issue(
                            "SCENE_CHAPTER_STALE",
                            severity="warning",
                            **locator,
                        )
                    )
            if document_status not in {"present", "orphan", "missing"}:
                freshness = "stale"
            output = {
                **locator,
                "revision": revision,
                "body_start": body_start,
                "freshness": freshness,
                "status": document_status,
            }
            chapters.append(output)
            if len(by_document[document_id]) == 1 and document.get("status") in {
                "present",
                "orphan",
            }:
                chapter_contents[document_id] = self._read_document(document)

        for document_id in sorted(set(chapter_sidecars) - set(by_document)):
            row = chapter_sidecars[document_id]
            issues.append(
                self._issue(
                    "SCENE_CHAPTER_DOCUMENT_MISSING",
                    chapter_id=str(row.get("chapter_id") or ""),
                    document_id=document_id,
                )
            )

        scene_ids = [
            str(item.get("scene_id") or "") for item in raw_scenes if isinstance(item, dict)
        ]
        duplicate_ids = {scene_id for scene_id, count in Counter(scene_ids).items() if count > 1}
        for scene_id in sorted(duplicate_ids):
            issues.append(self._issue("DUPLICATE_SCENE_ID", scene_id=scene_id))

        scenes: list[dict[str, Any]] = []
        for raw in raw_scenes:
            if not isinstance(raw, dict):
                issues.append(self._issue("SCENE_ENTRY_INVALID"))
                continue
            scene_id = str(raw.get("scene_id") or "")
            document_id = str(raw.get("document_id") or "")
            matches = by_document.get(document_id, [])
            document = matches[0] if len(matches) == 1 else None
            locator = (
                self._chapter_locator(document)
                if document is not None
                else {
                    "chapter_id": "",
                    "document_id": document_id,
                    "occurrence_id": "",
                    "path": "",
                }
            )
            freshness = "current"
            anchor = raw.get("anchor") if isinstance(raw.get("anchor"), dict) else {}
            start = self._integer(anchor.get("start"), default=-1)
            end = self._integer(anchor.get("end"), default=-1)
            source_revision = str(anchor.get("source_revision") or "")
            content_sha = str(anchor.get("content_sha256") or "")
            content = chapter_contents.get(document_id)
            current_revision = str((document or {}).get("revision") or "")
            if not SCENE_ID_RE.fullmatch(scene_id):
                freshness = "ambiguous"
                issues.append(self._issue("SCENE_ID_INVALID", scene_id=scene_id, **locator))
            if document is None:
                freshness = "ambiguous"
                issues.append(self._issue("SCENE_CHAPTER_AMBIGUOUS", scene_id=scene_id, **locator))
            elif source_revision != current_revision:
                freshness = "stale"
                issues.append(
                    self._issue(
                        "SCENE_ANCHOR_STALE",
                        severity="warning",
                        scene_id=scene_id,
                        **locator,
                    )
                )
            elif content is None or start < 0 or end < start or end > len(content):
                freshness = "ambiguous"
                issues.append(self._issue("SCENE_ANCHOR_INVALID", scene_id=scene_id, **locator))
            elif self._fingerprint(content[start:end]) != content_sha:
                freshness = "ambiguous"
                issues.append(
                    self._issue("SCENE_ANCHOR_HASH_MISMATCH", scene_id=scene_id, **locator)
                )
            if scene_id in duplicate_ids:
                freshness = "ambiguous"
            output = {
                "scene_id": scene_id,
                "chapter": {
                    **locator,
                    "reading_index": self._integer(
                        (document or {}).get("reading_index"), default=-1
                    ),
                    "revision": current_revision,
                },
                "order": self._integer(raw.get("order"), default=-1),
                "title": str(raw.get("title") or ""),
                "story_time": self._story_time(raw.get("story_time")),
                "references": self._references(raw.get("references")),
                "anchor": {
                    "start": start,
                    "end": end,
                    "offset_unit": "python_unicode_codepoint",
                    "end_exclusive": True,
                    "content_sha256": content_sha,
                    "source_revision": source_revision,
                },
                "freshness": freshness,
            }
            scenes.append(output)

        self._validate_chapter_layouts(
            scenes=scenes,
            chapters=chapters,
            contents=chapter_contents,
            issues=issues,
        )
        for source_issue in reading.get("issues") or []:
            source_blocks = bool(source_issue.get("blocking")) and str(
                source_issue.get("code") or ""
            ) not in {"OUTLINE_ORDER_UNAVAILABLE"}
            occurrence_ids = list(source_issue.get("occurrence_ids") or [])
            document_ids = list(source_issue.get("document_ids") or [])
            paths = list(source_issue.get("paths") or [])
            issues.append(
                self._issue(
                    str(source_issue.get("code") or "READING_ORDER_INVALID"),
                    severity=("error" if source_blocks else "warning"),
                    blocking=source_blocks,
                    chapter_id=str(source_issue.get("chapter_id") or ""),
                    document_id=str(document_ids[0] if len(document_ids) == 1 else ""),
                    occurrence_id=str(occurrence_ids[0] if len(occurrence_ids) == 1 else ""),
                    path=str(paths[0] if len(paths) == 1 else ""),
                    details={
                        "source_issue": source_issue,
                    },
                )
            )
        if not self._reading_allows_scene_edits(reading):
            issues.append(
                self._issue(
                    "SCENE_READING_ORDER_BLOCKED",
                    details={
                        "codes": [
                            str(item.get("code") or "")
                            for item in reading.get("issues") or []
                            if item.get("blocking")
                        ]
                    },
                )
            )

        scenes.sort(
            key=lambda item: (
                item["chapter"]["reading_index"],
                item["order"],
                item["scene_id"],
            )
        )
        reading_order = [item["scene_id"] for item in scenes]
        by_id = {item["scene_id"]: item for item in scenes}
        reading_positions = {scene_id: index for index, scene_id in enumerate(reading_order)}
        story_time_order = sorted(
            reading_order,
            key=lambda scene_id: (
                not bool(by_id[scene_id]["story_time"]["sort_key"]),
                by_id[scene_id]["story_time"]["sort_key"],
                reading_positions[scene_id],
            ),
        )
        has_ambiguous = any(item["freshness"] == "ambiguous" for item in scenes) or any(
            item["blocking"] and item["severity"] == "error" for item in issues
        )
        has_stale = any(item["freshness"] == "stale" for item in scenes) or any(
            item["freshness"] == "stale" for item in chapters
        )
        status = "ambiguous" if has_ambiguous else "stale" if has_stale else "current"
        return {
            "schema_version": SURFACE_SCHEMA_VERSION,
            "novel_id": self.novel_id,
            "status": status,
            "revision": self._surface_revision(reading["revision"], sidecar_revision),
            "sidecar_revision": sidecar_revision,
            "reading_order_revision": reading["revision"],
            "mutation_allowed": status == "current" and self._reading_allows_scene_edits(reading),
            "reading_order": reading_order,
            "story_time_order": story_time_order,
            "chapters": chapters,
            "scenes": scenes,
            "issues": issues,
        }

    def for_chapter(self, chapter_id: str) -> dict[str, Any]:
        """Return one chapter's scene slice without creating migration state."""
        clean = self._chapter_id(chapter_id)
        surface = self.surface()
        matches = [item for item in surface["chapters"] if item["chapter_id"] == clean]
        if len(matches) != 1:
            raise SceneStructureError("章节不存在或不唯一", code="SCENE_CHAPTER_AMBIGUOUS")
        chapter = matches[0]
        return {
            "schema_version": CHAPTER_SCHEMA_VERSION,
            "novel_id": self.novel_id,
            "status": surface["status"],
            "revision": surface["revision"],
            "chapter": chapter,
            "scenes": [
                item
                for item in surface["scenes"]
                if item["chapter"]["document_id"] == chapter["document_id"]
            ],
            "issues": [
                item
                for item in surface["issues"]
                if not item["chapter_id"] or item["chapter_id"] == clean
            ],
        }

    def migration_preview(self) -> dict[str, Any]:
        """Read manuscript headings and prepare a deterministic, read-only migration."""
        reading = ReadingOrderService(self.project_root, self.novel_id).surface()
        raw_before, existing, _issue = self._load_sidecar()
        migration_issues: list[dict[str, Any]] = []
        if raw_before is not None:
            existing_surface = self.surface()
            if existing_surface["status"] == "ambiguous":
                migration_issues.extend(
                    item for item in existing_surface["issues"] if item.get("blocking")
                )
        existing_exact: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
        existing_hints: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
        existing_orders: dict[tuple[str, int], list[dict[str, Any]]] = defaultdict(list)
        existing_counts: Counter[str] = Counter()
        if existing is not None and isinstance(existing.get("scenes"), list):
            for scene in existing["scenes"]:
                if not isinstance(scene, dict):
                    continue
                anchor = scene.get("anchor") if isinstance(scene.get("anchor"), dict) else {}
                document_id = str(scene.get("document_id") or "")
                order = self._integer(scene.get("order"), default=-1)
                content_sha = str(anchor.get("content_sha256") or "")
                scene_id = str(scene.get("scene_id") or "")
                if SCENE_ID_RE.fullmatch(scene_id):
                    candidate = {
                        "scene_id": scene_id,
                        "document_id": document_id,
                        "order": order,
                        "content_sha256": content_sha,
                        "identity_hint": self._identity_hint(
                            scene.get("identity_hint") or scene.get("title")
                        ),
                        "title": str(scene.get("title") or ""),
                        "story_time": self._story_time(scene.get("story_time")),
                        "references": self._references(scene.get("references")),
                    }
                    existing_counts[document_id] += 1
                    existing_exact[(document_id, content_sha)].append(candidate)
                    existing_hints[(candidate["document_id"], candidate["identity_hint"])].append(
                        candidate
                    )
                    existing_orders[(candidate["document_id"], candidate["order"])].append(
                        candidate
                    )

        input_chapters: list[dict[str, Any]] = []
        plan: list[dict[str, Any]] = []
        used_scene_ids: set[str] = set()
        seen_documents: set[str] = set()
        for document in reading["documents"]:
            document_id = str(document["document_id"])
            if document_id in seen_documents or document["status"] not in {
                "present",
                "orphan",
            }:
                continue
            seen_documents.add(document_id)
            content = self._read_document(document)
            body_start, parsed, strategy = self._segment_document(content)
            scenes: list[dict[str, Any]] = []
            for order, item in enumerate(parsed):
                content_sha = self._fingerprint(content[item["start"] : item["end"]])
                identity_hint = self._identity_hint(item["title"])
                candidate_groups = (
                    existing_exact.get((document_id, content_sha), []),
                    existing_hints.get((document_id, identity_hint), []),
                    (
                        existing_orders.get((document_id, order), [])
                        if existing_counts[document_id] == len(parsed)
                        else []
                    ),
                )
                candidates: list[dict[str, Any]] = []
                for group in candidate_groups:
                    candidates = [
                        candidate
                        for candidate in group
                        if candidate["scene_id"] not in used_scene_ids
                    ]
                    if candidates:
                        break
                if len(candidates) > 1:
                    migration_issues.append(
                        self._issue(
                            "SCENE_IDENTITY_AMBIGUOUS",
                            chapter_id=str(document["chapter_id"]),
                            document_id=document_id,
                            occurrence_id=str(document["occurrence_id"]),
                            path=str(document["path"]),
                            details={
                                "candidate_scene_ids": [
                                    candidate["scene_id"] for candidate in candidates
                                ],
                                "order": order,
                                "identity_hint": identity_hint,
                            },
                        )
                    )
                    candidate = None
                    scene_id = self._derived_scene_id(document_id, order, content_sha)
                elif candidates:
                    candidate = candidates[0]
                    scene_id = str(candidate["scene_id"])
                else:
                    candidate = None
                    scene_id = self._derived_scene_id(document_id, order, content_sha)
                used_scene_ids.add(scene_id)
                scenes.append(
                    {
                        "scene_id": scene_id,
                        "identity_hint": identity_hint,
                        "order": order,
                        "title": (
                            str(candidate["title"]) if candidate is not None else item["title"]
                        ),
                        "story_time": (
                            dict(candidate["story_time"])
                            if candidate is not None
                            else {"sort_key": "", "label": ""}
                        ),
                        "references": (
                            {key: list(values) for key, values in candidate["references"].items()}
                            if candidate is not None
                            else {
                                "characters": [],
                                "locations": [],
                                "events": [],
                            }
                        ),
                        "anchor": {
                            "start": item["start"],
                            "end": item["end"],
                            "offset_unit": "python_unicode_codepoint",
                            "end_exclusive": True,
                            "content_sha256": content_sha,
                            "source_revision": document["revision"],
                        },
                    }
                )
            locator = self._chapter_locator(document)
            input_chapters.append({**locator, "revision": document["revision"]})
            plan.append(
                {
                    **locator,
                    "source_revision": document["revision"],
                    "body_start": body_start,
                    "strategy": strategy,
                    "scenes": scenes,
                }
            )
        rollback_evidence = {
            "sidecar_exists": raw_before is not None,
            "sidecar_sha256": self._digest(raw_before) if raw_before is not None else "",
            "sidecar_revision": (
                str(existing.get("revision") or "") if existing is not None else ""
            ),
        }
        core = {
            "schema_version": PREVIEW_SCHEMA_VERSION,
            "novel_id": self.novel_id,
            "reading_order_revision": reading["revision"],
            "can_apply": self._reading_allows_scene_edits(reading) and not migration_issues,
            "input_chapters": input_chapters,
            "plan": plan,
            "rollback_evidence": rollback_evidence,
            "issues": [*reading["issues"], *migration_issues],
        }
        return {**core, "preview_revision": self._json_digest(core)}

    def apply_migration(
        self,
        *,
        expected_preview_revision: str,
        confirm: bool = False,
    ) -> dict[str, Any]:
        """Persist one exact preview while retaining an exact rollback image."""
        if not confirm:
            raise SceneStructureError("场景迁移需要显式确认", code="CONFIRMATION_REQUIRED")
        try:
            with ProjectWriteLock(
                self.project_root,
                self.novel_id,
                operation="scene_migration",
            ):
                preview = self.migration_preview()
                if (
                    not expected_preview_revision
                    or expected_preview_revision != preview["preview_revision"]
                ):
                    raise SceneStructureError(
                        "迁移预览或正文已变化，请重新预览",
                        code="SCENE_MIGRATION_CONFLICT",
                        details={
                            "expected_revision": str(expected_preview_revision or ""),
                            "current_revision": preview["preview_revision"],
                        },
                    )
                if not preview["can_apply"]:
                    raise SceneStructureError(
                        "正文顺序存在歧义，不能迁移场景结构",
                        code="SCENE_READING_ORDER_BLOCKED",
                    )
                previous = self.sidecar_path.read_bytes() if self.sidecar_path.is_file() else None
                sidecar = self._sidecar_from_preview(preview)
                sidecar_bytes = self._json_bytes(sidecar)
                migration_id = f"scmig_{uuid4().hex}"
                result_revision = self._surface_revision(
                    preview["reading_order_revision"], sidecar["revision"]
                )
                record = {
                    "schema_version": MIGRATION_SCHEMA_VERSION,
                    "migration_id": migration_id,
                    "novel_id": self.novel_id,
                    "status": "applied",
                    "preview_revision": preview["preview_revision"],
                    "input_chapters": preview["input_chapters"],
                    "previous_sidecar_exists": previous is not None,
                    "previous_sidecar_sha256": (
                        self._digest(previous) if previous is not None else ""
                    ),
                    "previous_sidecar_base64": (
                        b64encode(previous).decode("ascii") if previous is not None else ""
                    ),
                    "result_sidecar_revision": sidecar["revision"],
                    "result_revision": result_revision,
                    "created_at": self._now(),
                    "rolled_back_at": "",
                }
                self._commit_migration(sidecar_bytes, record, previous)
                return {
                    "schema_version": MIGRATION_SCHEMA_VERSION,
                    "migration_id": migration_id,
                    "scene_structure": self.surface(),
                }
        except ProjectBusyError as exc:
            raise SceneStructureError(str(exc), code="PROJECT_BUSY") from exc

    def rollback_migration(
        self,
        migration_id: str,
        *,
        expected_revision: str,
    ) -> dict[str, Any]:
        """Restore the byte-exact sidecar that preceded one migration."""
        clean = self._migration_id(migration_id)
        try:
            with ProjectWriteLock(
                self.project_root,
                self.novel_id,
                operation=f"scene_migration_rollback:{clean}",
            ):
                current = self.surface()
                if not expected_revision or expected_revision != current["revision"]:
                    raise SceneStructureError(
                        "场景结构已变化，不能回滚迁移",
                        code="SCENE_STRUCTURE_CONFLICT",
                    )
                record_path = self.migrations_dir / f"{clean}.json"
                record = self._read_json(record_path)
                if record is None or record.get("schema_version") != MIGRATION_SCHEMA_VERSION:
                    raise SceneStructureError("迁移记录不存在", code="SCENE_MIGRATION_NOT_FOUND")
                if (
                    record.get("status") != "applied"
                    or record.get("result_revision") != current["revision"]
                ):
                    raise SceneStructureError(
                        "迁移结果已被后续编辑，不能直接回滚",
                        code="SCENE_MIGRATION_DIVERGED",
                    )
                try:
                    previous = (
                        b64decode(
                            str(record.get("previous_sidecar_base64") or ""),
                            validate=True,
                        )
                        if record.get("previous_sidecar_exists")
                        else None
                    )
                except ValueError as exc:
                    raise SceneStructureError(
                        "迁移回滚证据损坏", code="SCENE_MIGRATION_EVIDENCE_INVALID"
                    ) from exc
                if previous is not None and self._digest(previous) != record.get(
                    "previous_sidecar_sha256"
                ):
                    raise SceneStructureError(
                        "迁移回滚证据损坏", code="SCENE_MIGRATION_EVIDENCE_INVALID"
                    )
                current_bytes = self.sidecar_path.read_bytes()
                updated_record = {
                    **record,
                    "status": "rolled_back",
                    "rolled_back_at": self._now(),
                }
                self._commit_rollback(
                    previous=previous,
                    current=current_bytes,
                    record_path=record_path,
                    record_before=self._json_bytes(record),
                    record_after=self._json_bytes(updated_record),
                )
                return {
                    "schema_version": MIGRATION_SCHEMA_VERSION,
                    "migration_id": clean,
                    "scene_structure": self.surface(),
                }
        except ProjectBusyError as exc:
            raise SceneStructureError(str(exc), code="PROJECT_BUSY") from exc

    def update_metadata(
        self,
        scene_id: str,
        *,
        expected_revision: str,
        title: str | None = None,
        story_time_sort_key: str | None = None,
        story_time_label: str | None = None,
        characters: Iterable[str] | None = None,
        locations: Iterable[str] | None = None,
        events: Iterable[str] | None = None,
    ) -> dict[str, Any]:
        """CAS-update scene metadata without changing manuscript bytes."""
        try:
            with ProjectWriteLock(
                self.project_root,
                self.novel_id,
                operation=f"scene_metadata:{scene_id}",
            ):
                current = self.surface()
                self._require_surface_revision(current, expected_revision)
                scene = self._current_scene(current, scene_id)
                if scene["freshness"] != "current" or current["status"] == "ambiguous":
                    raise SceneStructureError(
                        "场景锚点已过期或有歧义",
                        code="SCENE_STRUCTURE_STALE",
                    )
                sidecar = self._require_sidecar()
                target = next(item for item in sidecar["scenes"] if item["scene_id"] == scene_id)
                if title is not None:
                    clean_title = str(title).strip()
                    if not clean_title:
                        raise SceneStructureError("场景标题不能为空", code="SCENE_TITLE_INVALID")
                    target["title"] = clean_title[:200]
                story_time = self._story_time(target.get("story_time"))
                if story_time_sort_key is not None:
                    story_time["sort_key"] = str(story_time_sort_key).strip()[:120]
                if story_time_label is not None:
                    story_time["label"] = str(story_time_label).strip()[:200]
                target["story_time"] = story_time
                references = self._references(target.get("references"))
                for key, value in (
                    ("characters", characters),
                    ("locations", locations),
                    ("events", events),
                ):
                    if value is not None:
                        references[key] = self._clean_list(value)
                target["references"] = references
                self._seal_sidecar(sidecar)
                self._atomic_bytes(self.sidecar_path, self._json_bytes(sidecar))
                return {
                    "schema_version": MUTATION_SCHEMA_VERSION,
                    "scene_id": scene_id,
                    "scene_structure": self.surface(),
                }
        except ProjectBusyError as exc:
            raise SceneStructureError(str(exc), code="PROJECT_BUSY") from exc

    def move(
        self,
        scene_id: str,
        *,
        target_chapter_id: str,
        target_index: int,
        expected_revision: str,
        expected_source_revision: str,
        expected_target_revision: str,
    ) -> dict[str, Any]:
        """Move one complete scene block with chapter and sidecar rollback."""
        try:
            with ProjectWriteLock(
                self.project_root,
                self.novel_id,
                operation=f"scene_move:{scene_id}",
            ):
                current = self.surface()
                self._require_surface_revision(current, expected_revision)
                if not current["mutation_allowed"]:
                    code = (
                        "SCENE_STRUCTURE_STALE"
                        if current["status"] == "stale"
                        else "SCENE_STRUCTURE_AMBIGUOUS"
                    )
                    raise SceneStructureError("场景结构不可安全移动", code=code)
                scene = self._current_scene(current, scene_id)
                source_chapter = scene["chapter"]
                targets = [
                    item
                    for item in current["chapters"]
                    if item["chapter_id"] == self._chapter_id(target_chapter_id)
                ]
                if len(targets) != 1:
                    raise SceneStructureError(
                        "目标章节不存在或不唯一", code="SCENE_TARGET_CHAPTER_AMBIGUOUS"
                    )
                target_chapter = targets[0]
                if target_chapter["freshness"] != "current":
                    raise SceneStructureError(
                        "目标章节尚无可移动场景的正文",
                        code="SCENE_TARGET_CHAPTER_UNAVAILABLE",
                    )
                if expected_source_revision != source_chapter["revision"]:
                    raise SceneStructureError("源章节已变化", code="SOURCE_REVISION_CONFLICT")
                if expected_target_revision != target_chapter["revision"]:
                    raise SceneStructureError("目标章节已变化", code="TARGET_REVISION_CONFLICT")
                target_scenes = [
                    item
                    for item in current["scenes"]
                    if item["chapter"]["document_id"] == target_chapter["document_id"]
                    and item["scene_id"] != scene_id
                ]
                if target_index < 0 or target_index > len(target_scenes):
                    raise SceneStructureError(
                        "目标场景位置超出范围", code="SCENE_TARGET_INDEX_INVALID"
                    )
                if (
                    source_chapter["document_id"] == target_chapter["document_id"]
                    and scene["order"] == target_index
                ):
                    return {
                        "schema_version": MUTATION_SCHEMA_VERSION,
                        "scene_id": scene_id,
                        "acceptance": None,
                        "scene_structure": current,
                    }
                return self._move_current(
                    current=current,
                    scene=scene,
                    source_chapter=source_chapter,
                    target_chapter=target_chapter,
                    target_index=target_index,
                )
        except ProjectBusyError as exc:
            raise SceneStructureError(str(exc), code="PROJECT_BUSY") from exc

    def _move_current(
        self,
        *,
        current: dict[str, Any],
        scene: dict[str, Any],
        source_chapter: dict[str, Any],
        target_chapter: dict[str, Any],
        target_index: int,
    ) -> dict[str, Any]:
        sidecar = self._require_sidecar()
        raw_by_id = {item["scene_id"]: item for item in sidecar["scenes"]}
        source_document_id = source_chapter["document_id"]
        target_document_id = target_chapter["document_id"]
        source_path = self._safe_path(source_chapter["path"])
        target_path = self._safe_path(target_chapter["path"])
        source_before = source_path.read_text(encoding="utf-8")
        target_before = target_path.read_text(encoding="utf-8")
        source_records = sorted(
            [item for item in sidecar["scenes"] if item["document_id"] == source_document_id],
            key=lambda item: int(item["order"]),
        )
        target_records = (
            source_records
            if source_document_id == target_document_id
            else sorted(
                [item for item in sidecar["scenes"] if item["document_id"] == target_document_id],
                key=lambda item: int(item["order"]),
            )
        )
        texts: dict[str, str] = {}
        for item in {
            entry["scene_id"]: entry for entry in [*source_records, *target_records]
        }.values():
            content = source_before if item["document_id"] == source_document_id else target_before
            anchor = item["anchor"]
            texts[item["scene_id"]] = content[int(anchor["start"]) : int(anchor["end"])]
        moving = raw_by_id[scene["scene_id"]]
        source_remaining = [
            item for item in source_records if item["scene_id"] != scene["scene_id"]
        ]
        if source_document_id == target_document_id:
            target_after = list(source_remaining)
            target_after.insert(target_index, moving)
            source_after = target_after
        else:
            source_after = source_remaining
            target_after = [
                item for item in target_records if item["scene_id"] != scene["scene_id"]
            ]
            target_after.insert(target_index, moving)
            moving["document_id"] = target_document_id

        chapter_rows = {item["document_id"]: item for item in sidecar["chapters"]}
        source_body_start = int(chapter_rows[source_document_id]["body_start"])
        target_body_start = int(chapter_rows[target_document_id]["body_start"])
        source_after_text = source_before[:source_body_start] + "".join(
            texts[item["scene_id"]] for item in source_after
        )
        if source_document_id == target_document_id:
            target_after_text = source_after_text
        else:
            target_after_text = target_before[:target_body_start] + "".join(
                texts[item["scene_id"]] for item in target_after
            )
        new_revisions = {
            source_document_id: self._fingerprint(source_after_text),
            target_document_id: self._fingerprint(target_after_text),
        }
        for document_id, records, body_start in (
            (source_document_id, source_after, source_body_start),
            (target_document_id, target_after, target_body_start),
        ):
            position = body_start
            revision = new_revisions[document_id]
            for order, item in enumerate(records):
                block = texts[item["scene_id"]]
                item["document_id"] = document_id
                item["order"] = order
                item["anchor"] = {
                    "start": position,
                    "end": position + len(block),
                    "content_sha256": self._fingerprint(block),
                    "source_revision": revision,
                }
                position += len(block)
            chapter_rows[document_id]["source_revision"] = revision
        self._seal_sidecar(sidecar)
        acceptance = self._commit_scene_move(
            source_path=source_path,
            source_before=source_before,
            source_after=source_after_text,
            target_path=target_path,
            target_before=target_before,
            target_after=target_after_text,
            sidecar_before=self.sidecar_path.read_bytes(),
            sidecar_after=self._json_bytes(sidecar),
            changed_chapters=[source_chapter, target_chapter],
        )
        return {
            "schema_version": MUTATION_SCHEMA_VERSION,
            "scene_id": scene["scene_id"],
            "acceptance": acceptance,
            "scene_structure": self.surface(),
        }

    def _validate_chapter_layouts(
        self,
        *,
        scenes: list[dict[str, Any]],
        chapters: list[dict[str, Any]],
        contents: dict[str, str],
        issues: list[dict[str, Any]],
    ) -> None:
        for chapter in chapters:
            document_id = chapter["document_id"]
            current = [item for item in scenes if item["chapter"]["document_id"] == document_id]
            orders = [item["order"] for item in current]
            if sorted(orders) != list(range(len(current))):
                issues.append(self._issue("SCENE_ORDER_INVALID", **chapter))
                for item in current:
                    item["freshness"] = "ambiguous"
                continue
            current.sort(key=lambda item: item["order"])
            if chapter["freshness"] != "current":
                continue
            content = contents.get(document_id)
            if content is None or chapter["body_start"] < 0 or chapter["body_start"] > len(content):
                issues.append(self._issue("SCENE_BODY_ANCHOR_INVALID", **chapter))
                chapter["freshness"] = "ambiguous"
                continue
            position = chapter["body_start"]
            for item in current:
                if item["anchor"]["start"] != position:
                    issues.append(
                        self._issue(
                            "SCENE_ANCHOR_GAP_OR_OVERLAP",
                            scene_id=item["scene_id"],
                            **item["chapter"],
                        )
                    )
                    item["freshness"] = "ambiguous"
                position = item["anchor"]["end"]
            if position != len(content):
                issues.append(self._issue("UNASSIGNED_SCENE_CONTENT", **chapter))
                for item in current:
                    item["freshness"] = "ambiguous"

    def _segment_document(self, content: str) -> tuple[int, list[dict[str, Any]], str]:
        heading = CHAPTER_HEADING_RE.search(content)
        body_start = heading.end() if heading is not None else 0
        matches = [match for match in SCENE_HEADING_RE.finditer(content, body_start)]
        if not matches:
            title = self._first_heading(content) or "场景 1"
            return (
                body_start,
                [{"start": body_start, "end": len(content), "title": title}],
                ("fallback_single_scene"),
            )
        scenes: list[dict[str, Any]] = []
        for index, match in enumerate(matches):
            start = body_start if index == 0 else match.start()
            end = matches[index + 1].start() if index + 1 < len(matches) else len(content)
            scenes.append(
                {
                    "start": start,
                    "end": end,
                    "title": match.group("title").strip(),
                }
            )
        return body_start, scenes, "scene_headings"

    def _sidecar_from_preview(self, preview: dict[str, Any]) -> dict[str, Any]:
        sidecar = {
            "schema_version": SIDECAR_SCHEMA_VERSION,
            "novel_id": self.novel_id,
            "revision": "",
            "updated_at": self._now(),
            "chapters": [
                {
                    "document_id": item["document_id"],
                    "chapter_id": item["chapter_id"],
                    "body_start": item["body_start"],
                    "source_revision": item["source_revision"],
                }
                for item in preview["plan"]
            ],
            "scenes": [
                {
                    "scene_id": scene["scene_id"],
                    "document_id": item["document_id"],
                    "order": scene["order"],
                    "identity_hint": scene["identity_hint"],
                    "title": scene["title"],
                    "story_time": scene["story_time"],
                    "references": scene["references"],
                    "anchor": {
                        "start": scene["anchor"]["start"],
                        "end": scene["anchor"]["end"],
                        "content_sha256": scene["anchor"]["content_sha256"],
                        "source_revision": scene["anchor"]["source_revision"],
                    },
                }
                for item in preview["plan"]
                for scene in item["scenes"]
            ],
        }
        self._seal_sidecar(sidecar)
        return sidecar

    def _seal_sidecar(self, sidecar: dict[str, Any]) -> None:
        sidecar["updated_at"] = self._now()
        sidecar["revision"] = self._sidecar_revision(sidecar)

    def _commit_migration(
        self,
        sidecar_after: bytes,
        record: dict[str, Any],
        sidecar_before: bytes | None,
    ) -> None:
        record_path = self.migrations_dir / f"{record['migration_id']}.json"
        sidecar_temp = self._temporary(self.sidecar_path, sidecar_after)
        record_temp = self._temporary(record_path, self._json_bytes(record))
        try:
            sidecar_temp.replace(self.sidecar_path)
            self._fault("sidecar_replaced")
            record_temp.replace(record_path)
            self._fault("migration_record_replaced")
        except Exception as exc:
            if sidecar_before is None:
                self.sidecar_path.unlink(missing_ok=True)
            else:
                self._atomic_bytes(self.sidecar_path, sidecar_before)
            record_path.unlink(missing_ok=True)
            raise SceneStructureError(
                "场景迁移写入失败，已回滚",
                code="SCENE_TRANSACTION_FAILED",
            ) from exc
        finally:
            sidecar_temp.unlink(missing_ok=True)
            record_temp.unlink(missing_ok=True)

    def _commit_rollback(
        self,
        *,
        previous: bytes | None,
        current: bytes,
        record_path: Path,
        record_before: bytes,
        record_after: bytes,
    ) -> None:
        record_temp = self._temporary(record_path, record_after)
        sidecar_temp = (
            self._temporary(self.sidecar_path, previous) if previous is not None else None
        )
        try:
            if sidecar_temp is None:
                self.sidecar_path.unlink()
            else:
                sidecar_temp.replace(self.sidecar_path)
            self._fault("migration_sidecar_restored")
            record_temp.replace(record_path)
        except Exception as exc:
            self._atomic_bytes(self.sidecar_path, current)
            self._atomic_bytes(record_path, record_before)
            raise SceneStructureError(
                "迁移回滚失败，已恢复当前结构",
                code="SCENE_TRANSACTION_FAILED",
            ) from exc
        finally:
            if sidecar_temp is not None:
                sidecar_temp.unlink(missing_ok=True)
            record_temp.unlink(missing_ok=True)

    def _commit_scene_move(
        self,
        *,
        source_path: Path,
        source_before: str,
        source_after: str,
        target_path: Path,
        target_before: str,
        target_after: str,
        sidecar_before: bytes,
        sidecar_after: bytes,
        changed_chapters: list[dict[str, Any]],
    ) -> dict[str, Any]:
        source_temp = self._temporary(source_path, source_after.encode("utf-8"))
        target_temp = (
            None
            if source_path == target_path
            else self._temporary(target_path, target_after.encode("utf-8"))
        )
        sidecar_temp = self._temporary(self.sidecar_path, sidecar_after)
        try:
            source_temp.replace(source_path)
            self._fault("source_replaced")
            if target_temp is not None:
                target_temp.replace(target_path)
                self._fault("target_replaced")
            sidecar_temp.replace(self.sidecar_path)
            self._fault("sidecar_replaced")
            earliest = min(
                {item["chapter_id"]: item for item in changed_chapters}.values(),
                key=lambda item: self._chapter_number(item["chapter_id"]),
            )
            from tools.manuscript_acceptance import ManuscriptAcceptanceService

            acceptance = ManuscriptAcceptanceService(
                self.project_root, self.novel_id
            ).start_acceptance(
                earliest["chapter_id"],
                source="manual",
                expected_previous_revision=earliest["revision"],
            )
            self._fault("acceptance_started")
            return acceptance
        except Exception as exc:
            rollback_errors: list[str] = []
            for path, content, label in (
                (source_path, source_before.encode("utf-8"), "source"),
                (target_path, target_before.encode("utf-8"), "target"),
                (self.sidecar_path, sidecar_before, "sidecar"),
            ):
                if label == "target" and target_path == source_path:
                    continue
                try:
                    self._atomic_bytes(path, content)
                except OSError as rollback_exc:
                    rollback_errors.append(f"{label}:{rollback_exc}")
            raise SceneStructureError(
                "场景移动失败，正文与结构已回滚",
                code="SCENE_TRANSACTION_FAILED",
                recoverable=not rollback_errors,
                details={"rollback_errors": rollback_errors},
            ) from exc
        finally:
            source_temp.unlink(missing_ok=True)
            if target_temp is not None:
                target_temp.unlink(missing_ok=True)
            sidecar_temp.unlink(missing_ok=True)

    def _empty_surface(
        self,
        reading: dict[str, Any],
        *,
        status: str,
        issues: list[dict[str, Any]],
        sidecar_revision: str = "",
    ) -> dict[str, Any]:
        chapters = [
            {
                **self._chapter_locator(item),
                "revision": str(item.get("revision") or ""),
                "body_start": -1,
                "freshness": "absent" if status == "absent" else "ambiguous",
                "status": str(item.get("status") or ""),
            }
            for item in reading["documents"]
        ]
        return {
            "schema_version": SURFACE_SCHEMA_VERSION,
            "novel_id": self.novel_id,
            "status": status,
            "revision": self._surface_revision(reading["revision"], sidecar_revision),
            "sidecar_revision": sidecar_revision,
            "reading_order_revision": reading["revision"],
            "mutation_allowed": False,
            "reading_order": [],
            "story_time_order": [],
            "chapters": chapters,
            "scenes": [],
            "issues": issues,
        }

    def _require_surface_revision(self, current: dict[str, Any], expected: str) -> None:
        if not expected or expected != current["revision"]:
            raise SceneStructureError(
                "场景结构已变化，请刷新后重试",
                code="SCENE_STRUCTURE_CONFLICT",
                details={
                    "expected_revision": str(expected or ""),
                    "current_revision": current["revision"],
                },
            )

    @staticmethod
    def _current_scene(surface: dict[str, Any], scene_id: str) -> dict[str, Any]:
        matches = [item for item in surface["scenes"] if item["scene_id"] == scene_id]
        if len(matches) != 1:
            raise SceneStructureError("场景不存在或不唯一", code="SCENE_ID_AMBIGUOUS")
        return matches[0]

    def _require_sidecar(self) -> dict[str, Any]:
        _raw, sidecar, _issue = self._load_sidecar()
        if sidecar is None or sidecar.get("schema_version") != SIDECAR_SCHEMA_VERSION:
            raise SceneStructureError("场景 sidecar 不存在或损坏", code="SCENE_SIDECAR_INVALID")
        if str(sidecar.get("revision") or "") != self._sidecar_revision(sidecar):
            raise SceneStructureError("场景 sidecar 校验失败", code="SCENE_SIDECAR_INVALID")
        return sidecar

    def _load_sidecar(
        self,
    ) -> tuple[bytes | None, dict[str, Any] | None, dict[str, Any] | None]:
        if not self.sidecar_path.is_file():
            return None, None, None
        try:
            raw = self.sidecar_path.read_bytes()
            payload = json.loads(raw.decode("utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("sidecar is not an object")
            return raw, payload, None
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError):
            raw = self.sidecar_path.read_bytes() if self.sidecar_path.is_file() else b""
            return raw, None, self._issue("SCENE_SIDECAR_INVALID")

    def _read_document(self, document: dict[str, Any]) -> str:
        return self._safe_path(str(document["path"])).read_text(encoding="utf-8")

    def _safe_path(self, relative: str) -> Path:
        manuscript_root = (self.novel_root / "data" / "manuscript").resolve()
        path = (self.novel_root / relative).resolve()
        try:
            path.relative_to(manuscript_root)
        except ValueError as exc:
            raise SceneStructureError(
                "场景章节路径越出正文目录", code="SCENE_CHAPTER_PATH_INVALID"
            ) from exc
        return path

    @staticmethod
    def _chapter_locator(document: dict[str, Any] | None) -> dict[str, Any]:
        document = document or {}
        return {
            "chapter_id": str(document.get("chapter_id") or ""),
            "document_id": str(document.get("document_id") or ""),
            "occurrence_id": str(document.get("occurrence_id") or ""),
            "path": str(document.get("path") or ""),
        }

    @staticmethod
    def _story_time(value: Any) -> dict[str, str]:
        value = value if isinstance(value, dict) else {}
        return {
            "sort_key": str(value.get("sort_key") or ""),
            "label": str(value.get("label") or ""),
        }

    @classmethod
    def _references(cls, value: Any) -> dict[str, list[str]]:
        value = value if isinstance(value, dict) else {}
        return {
            key: cls._clean_list(value.get(key) or [])
            for key in ("characters", "locations", "events")
        }

    @staticmethod
    def _clean_list(values: Iterable[str]) -> list[str]:
        cleaned: list[str] = []
        seen: set[str] = set()
        for value in values:
            item = str(value or "").strip()
            if item and item not in seen:
                seen.add(item)
                cleaned.append(item[:200])
        return cleaned[:200]

    @staticmethod
    def _integer(value: Any, *, default: int) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _first_heading(content: str) -> str:
        match = re.search(r"^#{1,6}\s+(.+?)\s*$", content, re.MULTILINE)
        return match.group(1).strip() if match else ""

    def _derived_scene_id(self, document_id: str, order: int, content_sha: str) -> str:
        digest = hashlib.sha256(
            f"{self.novel_id}\0{document_id}\0{order}\0{content_sha}".encode()
        ).hexdigest()
        return f"scn_{digest[:24]}"

    @staticmethod
    def _reading_allows_scene_edits(reading: dict[str, Any]) -> bool:
        tolerated = {"OUTLINE_ORDER_UNAVAILABLE"}
        return not any(
            item.get("blocking") and str(item.get("code") or "") not in tolerated
            for item in reading.get("issues") or []
        )

    @staticmethod
    def _identity_hint(value: Any) -> str:
        return re.sub(r"\s+", " ", str(value or "").strip().casefold())[:200]

    @staticmethod
    def _fingerprint(content: str) -> str:
        return "sha256:" + hashlib.sha256(content.encode("utf-8")).hexdigest()

    @staticmethod
    def _digest(content: bytes) -> str:
        return "sha256:" + hashlib.sha256(content).hexdigest()

    @classmethod
    def _json_digest(cls, payload: dict[str, Any]) -> str:
        return cls._digest(
            json.dumps(
                payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        )

    @classmethod
    def _sidecar_revision(cls, payload: dict[str, Any]) -> str:
        semantic = {
            key: payload.get(key) for key in ("schema_version", "novel_id", "chapters", "scenes")
        }
        return cls._json_digest(semantic)

    @classmethod
    def _surface_revision(cls, reading_revision: str, sidecar_revision: str) -> str:
        return cls._json_digest(
            {
                "reading_order_revision": reading_revision,
                "sidecar_revision": sidecar_revision,
            }
        )

    @staticmethod
    def _json_bytes(payload: dict[str, Any]) -> bytes:
        return (json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode(
            "utf-8"
        )

    @staticmethod
    def _read_json(path: Path) -> dict[str, Any] | None:
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            return value if isinstance(value, dict) else None
        except (OSError, json.JSONDecodeError):
            return None

    @staticmethod
    def _temporary(path: Path, content: bytes | None) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            handle.write(content or b"")
            handle.flush()
            os.fsync(handle.fileno())
            return Path(handle.name)

    @classmethod
    def _atomic_bytes(cls, path: Path, content: bytes) -> None:
        temporary = cls._temporary(path, content)
        try:
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)

    def _fault(self, stage: str) -> None:
        if self._fault_injector is not None:
            self._fault_injector(stage)

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _chapter_number(chapter_id: str) -> int:
        match = re.search(r"(\d+)$", chapter_id)
        return int(match.group(1)) if match else 10**9

    @staticmethod
    def _chapter_id(value: str) -> str:
        clean = str(value or "")
        if not re.fullmatch(r"ch_\d+", clean):
            raise SceneStructureError("章节 ID 必须形如 ch_001", code="INVALID_CHAPTER_ID")
        return clean

    @staticmethod
    def _migration_id(value: str) -> str:
        clean = str(value or "")
        if not MIGRATION_ID_RE.fullmatch(clean):
            raise SceneStructureError("迁移 ID 无效", code="INVALID_MIGRATION_ID")
        return clean

    @staticmethod
    def _issue(
        code: str,
        *,
        severity: str = "error",
        blocking: bool = True,
        chapter_id: str = "",
        document_id: str = "",
        occurrence_id: str = "",
        path: str = "",
        scene_id: str = "",
        details: dict[str, Any] | None = None,
        **_extra: Any,
    ) -> dict[str, Any]:
        return {
            "code": code,
            "severity": severity,
            "blocking": blocking,
            "chapter_id": chapter_id,
            "document_id": document_id,
            "occurrence_id": occurrence_id,
            "path": path,
            "scene_id": scene_id,
            "details": dict(details or {}),
        }
