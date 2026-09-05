"""Canonical manuscript identity, reading order, navigation, and safe moves.

The projection is rebuilt from ``src/outline.md`` and the manuscript tree on
every call.  A small sidecar stores document identity across service-managed
path moves; it never stores ordering or prose and is not needed for legacy
read-only access.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from collections import defaultdict
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tools.novel_workspace import CHAPTER_FILE_RE, count_writing_units, novel_root
from tools.outline_tree import build_outline_structure
from tools.project_lock import ProjectBusyError, ProjectWriteLock

SURFACE_SCHEMA_VERSION = "openwrite.reading-order.v1"
PACKET_SCHEMA_VERSION = "openwrite.reading-packet.v1"
MUTATION_SCHEMA_VERSION = "openwrite.reading-order-mutation.v1"
IDENTITY_SCHEMA_VERSION = "openwrite.document-identities.v1"
DOCUMENT_ID_RE = re.compile(r"^doc_[0-9a-f]{24}$")
HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s+(.+?)\s*$", re.MULTILINE)
FaultInjector = Callable[[str], None]


class ReadingOrderError(RuntimeError):
    """A stable, user-facing reading-order failure."""

    def __init__(
        self,
        message: str,
        *,
        code: str,
        recoverable: bool = False,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.recoverable = recoverable
        self.details = dict(details or {})


class ReadingOrderService:
    """Build and mutate one novel's canonical reading-order projection."""

    def __init__(self, project_root: Path, novel_id: str) -> None:
        self.project_root = Path(project_root).expanduser().resolve()
        self.novel_id = str(novel_id)
        self.novel_root = novel_root(self.project_root, self.novel_id).resolve()
        self.outline_path = self.novel_root / "src" / "outline.md"
        self.manuscript_root = self.novel_root / "data" / "manuscript"
        self.identity_path = (
            self.novel_root / "data" / "workflows" / "reading_order_identities.json"
        )

    def surface(self) -> dict[str, Any]:
        """Return every real/missing document without chapter-id deduplication."""
        outline_text = self._read_outline()
        outline_structure = (
            build_outline_structure(self.novel_root) if outline_text is not None else None
        )
        disk_documents, disk_issues = self._disk_documents()
        identities, identity_issues = self._identities()
        assigned_ids: set[str] = set()
        for document in disk_documents:
            relative = str(document["path"])
            candidate = identities.get(relative) or self._derived_document_id(relative)
            if candidate in assigned_ids:
                identity_issues.append(
                    self._issue(
                        "DUPLICATE_DOCUMENT_ID",
                        chapter_id=str(document["chapter_id"]),
                        document_ids=[candidate],
                        paths=[relative],
                    )
                )
                candidate = self._derived_document_id(f"{relative}\0duplicate")
            document["document_id"] = candidate
            assigned_ids.add(candidate)

        if outline_structure is None or int(outline_structure["counts"]["chapter"]) == 0:
            return self._legacy_surface(
                outline_text,
                disk_documents,
                [*disk_issues, *identity_issues],
            )
        return self._outline_surface(
            outline_text or "",
            outline_structure,
            disk_documents,
            [*disk_issues, *identity_issues],
        )

    def packet(
        self,
        document_id: str,
        *,
        before: int = 1,
        after: int = 1,
    ) -> dict[str, Any]:
        """Read one bounded, consecutive manuscript window with navigation."""
        if before < 0 or after < 0 or before > 20 or after > 20:
            raise ReadingOrderError(
                "连续阅读窗口必须在前后各 0-20 章之间",
                code="READING_PACKET_RANGE_INVALID",
            )
        surface = self.surface()
        documents = surface["documents"]
        matches = [
            position
            for position, document in enumerate(documents)
            if document["occurrence_id"] == document_id or document["document_id"] == document_id
        ]
        if not matches:
            raise ReadingOrderError(
                "阅读文档不存在，请刷新阅读顺序",
                code="READING_DOCUMENT_NOT_FOUND",
            )
        if len(matches) > 1:
            raise ReadingOrderError(
                "文档标识对应多个阅读位置，请改用 occurrence_id",
                code="READING_DOCUMENT_AMBIGUOUS",
                recoverable=True,
            )
        index = matches[0]
        start = max(0, index - before)
        end = min(len(documents), index + after + 1)
        selected: list[dict[str, Any]] = []
        for document in documents[start:end]:
            item = dict(document)
            item["content"] = self._document_content(document)
            selected.append(item)
        return {
            "schema_version": PACKET_SCHEMA_VERSION,
            "novel_id": self.novel_id,
            "revision": surface["revision"],
            "anchor_document_id": documents[index]["document_id"],
            "anchor_occurrence_id": documents[index]["occurrence_id"],
            "start_index": start,
            "end_index": end - 1,
            "has_previous": start > 0,
            "has_next": end < len(documents),
            "complete": all(item["status"] in {"present", "orphan"} for item in selected),
            "documents": selected,
            "issues": surface["issues"],
        }

    def move(
        self,
        *,
        document_id: str,
        target_volume_id: str,
        target_index: int,
        expected_revision: str,
        fault_injector: FaultInjector | None = None,
    ) -> dict[str, Any]:
        """Revision-checked chapter reorder/cross-volume move with rollback."""
        try:
            with ProjectWriteLock(
                self.project_root,
                self.novel_id,
                operation=f"reading_order_move:{document_id}",
            ):
                current = self.surface()
                if not expected_revision or expected_revision != current["revision"]:
                    raise ReadingOrderError(
                        "阅读顺序已变化，请刷新后重试",
                        code="READING_ORDER_CONFLICT",
                        recoverable=True,
                        details={
                            "expected_revision": str(expected_revision or ""),
                            "current_revision": current["revision"],
                        },
                    )
                if not current["mutation_allowed"]:
                    raise ReadingOrderError(
                        "章节顺序存在歧义或缺失，修复问题后才能调整",
                        code="AMBIGUOUS_READING_ORDER",
                        recoverable=True,
                        details={
                            "issue_codes": [
                                item["code"] for item in current["issues"] if item["blocking"]
                            ]
                        },
                    )
                matches = [
                    item
                    for item in current["documents"]
                    if item["document_id"] == document_id or item["occurrence_id"] == document_id
                ]
                if not matches:
                    raise ReadingOrderError(
                        "阅读文档不存在，请刷新阅读顺序",
                        code="READING_DOCUMENT_NOT_FOUND",
                    )
                if len(matches) > 1:
                    raise ReadingOrderError(
                        "文档标识对应多个阅读位置，请改用 occurrence_id",
                        code="READING_DOCUMENT_AMBIGUOUS",
                        recoverable=True,
                    )
                document = matches[0]
                canonical_document_id = str(document["document_id"])
                if document["status"] != "present" or not document["outline"]["line"]:
                    raise ReadingOrderError(
                        "只有已进入大纲且正文可读的章节才能移动",
                        code="READING_DOCUMENT_NOT_MOVABLE",
                    )
                volume = next(
                    (item for item in current["volumes"] if item["volume_id"] == target_volume_id),
                    None,
                )
                if volume is None:
                    raise ReadingOrderError(
                        "目标卷不存在，请刷新阅读顺序",
                        code="READING_VOLUME_NOT_FOUND",
                    )
                target_documents = [
                    item
                    for item in current["documents"]
                    if item["volume"]["volume_id"] == target_volume_id
                    and item["occurrence_id"] != document["occurrence_id"]
                    and item["outline"]["line"]
                ]
                if target_index < 0 or target_index > len(target_documents):
                    raise ReadingOrderError(
                        "目标卷内位置超出范围",
                        code="READING_TARGET_INDEX_INVALID",
                    )
                current_volume_documents = [
                    item
                    for item in current["documents"]
                    if item["volume"]["volume_id"] == document["volume"]["volume_id"]
                    and item["occurrence_id"] != document["occurrence_id"]
                ]
                if (
                    document["volume"]["volume_id"] == target_volume_id
                    and target_documents == current_volume_documents
                    and self._index_without_document(current, document["occurrence_id"])
                    == target_index
                ):
                    return self._mutation_result(current, current, document, target_index)

                outline_before = self.outline_path.read_bytes()
                source = self._safe_document_path(str(document["path"]))
                source_content = source.read_bytes()
                target = (self.manuscript_root / str(volume["disk_arc_id"]) / source.name).resolve()
                self._require_inside(target, self.manuscript_root)
                if target != source and target.exists():
                    raise ReadingOrderError(
                        "目标卷已存在同名章节文件",
                        code="READING_TARGET_EXISTS",
                        details={"path": target.relative_to(self.novel_root).as_posix()},
                    )
                outline_after = self._moved_outline(
                    document,
                    volume,
                    target_documents,
                    target_index,
                    outline_before.decode("utf-8"),
                ).encode("utf-8")
                registry_before = (
                    self.identity_path.read_bytes() if self.identity_path.is_file() else None
                )
                registry = {
                    str(item["path"]): str(item["document_id"])
                    for item in current["documents"]
                    if item["status"] in {"present", "orphan", "unreadable"} and item["path"]
                }
                source_relative = source.relative_to(self.novel_root).as_posix()
                target_relative = target.relative_to(self.novel_root).as_posix()
                registry.pop(source_relative, None)
                registry[target_relative] = canonical_document_id
                registry_after = (
                    json.dumps(
                        {
                            "schema_version": IDENTITY_SCHEMA_VERSION,
                            "documents": dict(sorted(registry.items())),
                        },
                        ensure_ascii=False,
                        sort_keys=True,
                        indent=2,
                    )
                    + "\n"
                ).encode("utf-8")
                self._commit_move(
                    source=source,
                    target=target,
                    source_content=source_content,
                    outline_before=outline_before,
                    outline_after=outline_after,
                    registry_before=registry_before,
                    registry_after=registry_after,
                    fault_injector=fault_injector,
                )
                result = self.surface()
                moved = next(
                    item
                    for item in result["documents"]
                    if item["document_id"] == canonical_document_id
                )
                return self._mutation_result(current, result, moved, target_index)
        except ReadingOrderError:
            raise
        except ProjectBusyError as exc:
            raise ReadingOrderError(str(exc), code="PROJECT_BUSY", recoverable=True) from exc

    def _outline_surface(
        self,
        outline_text: str,
        structure: dict[str, Any],
        disk_documents: list[dict[str, Any]],
        initial_issues: list[dict[str, Any]],
    ) -> dict[str, Any]:
        issues = list(initial_issues)
        volumes, outline_documents = self._outline_documents(structure)
        disks_by_chapter: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for document in disk_documents:
            disks_by_chapter[str(document["chapter_id"])].append(document)
        for chapter_id, documents in sorted(disks_by_chapter.items()):
            if len(documents) > 1:
                issues.append(
                    self._issue(
                        "DUPLICATE_CHAPTER_ID",
                        chapter_id=chapter_id,
                        document_ids=[str(item["document_id"]) for item in documents],
                        paths=[str(item["path"]) for item in documents],
                    )
                )
        outline_by_chapter: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for item in outline_documents:
            outline_by_chapter[str(item["chapter_id"])].append(item)
        for chapter_id, entries in sorted(outline_by_chapter.items()):
            if len(entries) > 1:
                issues.append(
                    self._issue(
                        "DUPLICATE_OUTLINE_CHAPTER_ID",
                        chapter_id=chapter_id,
                        paths=[],
                        outline_lines=[int(item["line"]) for item in entries],
                    )
                )

        used_paths: set[str] = set()
        ordered: list[dict[str, Any]] = []
        volume_map = {str(item["volume_id"]): item for item in volumes}
        for entry in outline_documents:
            candidates = disks_by_chapter[str(entry["chapter_id"])]
            preferred = f"data/manuscript/{entry['disk_arc_id']}/{entry['chapter_id']}.md"
            disk = next(
                (item for item in candidates if item["path"] == preferred),
                next(
                    (item for item in candidates if item["path"] not in used_paths),
                    None,
                ),
            )
            if disk is None:
                missing_id = self._derived_document_id(preferred)
                document = self._project_document(
                    {
                        "document_id": missing_id,
                        "chapter_id": entry["chapter_id"],
                        "title": entry["title"],
                        "path": preferred,
                        "writing_units": 0,
                        "content_sha256": "",
                        "updated_at": "",
                        "status": "missing",
                    },
                    entry,
                )
                issues.append(
                    self._issue(
                        "MISSING_CHAPTER_FILE",
                        blocking=False,
                        chapter_id=str(entry["chapter_id"]),
                        document_ids=[missing_id],
                        paths=[preferred],
                        outline_lines=[int(entry["line"])],
                    )
                )
            else:
                document = self._project_document(disk, entry)
                used_paths.add(str(disk["path"]))
                if str(disk["path"]) != preferred:
                    issues.append(
                        self._issue(
                            "OUTLINE_DISK_VOLUME_MISMATCH",
                            blocking=False,
                            chapter_id=str(entry["chapter_id"]),
                            document_ids=[str(disk["document_id"])],
                            paths=[str(disk["path"]), preferred],
                        )
                    )
            ordered.append(document)
            volume_map[str(entry["volume_id"])]["document_ids"].append(document["document_id"])

        for disk in disk_documents:
            if str(disk["path"]) in used_paths:
                continue
            volume = self._volume_for_disk(volumes, str(disk["path"]))
            if volume is None:
                volume = self._synthetic_volume(volumes, str(disk["path"]))
                volumes.append(volume)
            orphan = self._project_document(
                {**disk, "status": "orphan"},
                {
                    "line": 0,
                    "end_line": 0,
                    "section_id": "",
                    "section_title": "",
                    "volume_id": volume["volume_id"],
                    "volume_title": volume["title"],
                    "disk_arc_id": volume["disk_arc_id"],
                },
            )
            ordered.append(orphan)
            volume["document_ids"].append(orphan["document_id"])
            issues.append(
                self._issue(
                    "ORPHAN_CHAPTER_FILE",
                    chapter_id=str(disk["chapter_id"]),
                    document_ids=[str(disk["document_id"])],
                    paths=[str(disk["path"])],
                )
            )
        return self._finalize_surface(
            mode="outline",
            outline_text=outline_text,
            volumes=volumes,
            documents=ordered,
            issues=issues,
        )

    def _legacy_surface(
        self,
        outline_text: str | None,
        disk_documents: list[dict[str, Any]],
        initial_issues: list[dict[str, Any]],
    ) -> dict[str, Any]:
        issues = list(initial_issues)
        by_chapter: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for document in disk_documents:
            by_chapter[str(document["chapter_id"])].append(document)
        for chapter_id, documents in sorted(by_chapter.items()):
            if len(documents) > 1:
                issues.append(
                    self._issue(
                        "DUPLICATE_CHAPTER_ID",
                        chapter_id=chapter_id,
                        document_ids=[str(item["document_id"]) for item in documents],
                        paths=[str(item["path"]) for item in documents],
                    )
                )
        groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for document in disk_documents:
            groups[self._disk_arc_id(str(document["path"]))].append(document)
        volumes: list[dict[str, Any]] = []
        ordered: list[dict[str, Any]] = []
        for index, arc_id in enumerate(sorted(groups, key=self._arc_sort_key)):
            volume_id = f"legacy_{arc_id}"
            volume = {
                "volume_id": volume_id,
                "title": arc_id,
                "order": index,
                "disk_arc_id": arc_id,
                "document_ids": [],
            }
            volumes.append(volume)
            for disk in sorted(
                groups[arc_id],
                key=lambda item: (
                    self._chapter_number(str(item["chapter_id"])),
                    str(item["path"]),
                ),
            ):
                document = self._project_document(
                    disk,
                    {
                        "line": 0,
                        "end_line": 0,
                        "section_id": "",
                        "section_title": "",
                        "volume_id": volume_id,
                        "volume_title": arc_id,
                        "disk_arc_id": arc_id,
                    },
                )
                ordered.append(document)
                volume["document_ids"].append(document["document_id"])
        issues.append(self._issue("OUTLINE_ORDER_UNAVAILABLE", paths=["src/outline.md"]))
        return self._finalize_surface(
            mode="legacy_disk_order",
            outline_text=outline_text,
            volumes=volumes,
            documents=ordered,
            issues=issues,
        )

    def _finalize_surface(
        self,
        *,
        mode: str,
        outline_text: str | None,
        volumes: list[dict[str, Any]],
        documents: list[dict[str, Any]],
        issues: list[dict[str, Any]],
    ) -> dict[str, Any]:
        occurrences: dict[str, int] = defaultdict(int)
        for index, document in enumerate(documents):
            document_id = str(document["document_id"])
            ordinal = occurrences[document_id]
            occurrences[document_id] += 1
            document["occurrence_id"] = self._derived_occurrence_id(document_id, ordinal)
            document["reading_index"] = index
            document["order"] = index
            document["previous_document_id"] = (
                documents[index - 1]["document_id"] if index > 0 else ""
            )
            document["next_document_id"] = (
                documents[index + 1]["document_id"] if index + 1 < len(documents) else ""
            )
        for index, document in enumerate(documents):
            document["previous_occurrence_id"] = (
                documents[index - 1]["occurrence_id"] if index > 0 else ""
            )
            document["next_occurrence_id"] = (
                documents[index + 1]["occurrence_id"] if index + 1 < len(documents) else ""
            )

        for volume in volumes:
            members = [
                item for item in documents if item["volume"]["volume_id"] == volume["volume_id"]
            ]
            volume["document_ids"] = [item["document_id"] for item in members]
            volume["occurrence_ids"] = [item["occurrence_id"] for item in members]

        for issue in issues:
            chapter_id = str(issue.get("chapter_id") or "")
            outline_lines = {int(value) for value in issue.get("outline_lines", [])}
            document_ids = {str(value) for value in issue.get("document_ids", [])}
            paths = {str(value) for value in issue.get("paths", [])}
            if outline_lines:
                affected = [
                    item for item in documents if int(item["outline"]["line"]) in outline_lines
                ]
            elif document_ids:
                affected = [item for item in documents if item["document_id"] in document_ids]
            elif paths:
                affected = [item for item in documents if item["path"] in paths]
            else:
                affected = [
                    item for item in documents if chapter_id and item["chapter_id"] == chapter_id
                ]
            issue["occurrence_ids"] = [str(item["occurrence_id"]) for item in affected]
        revision_payload = {
            "outline_sha256": self._digest((outline_text or "").encode("utf-8")),
            "documents": [
                {
                    "document_id": item["document_id"],
                    "occurrence_id": item["occurrence_id"],
                    "chapter_id": item["chapter_id"],
                    "path": item["path"],
                    "content_sha256": item["content_sha256"],
                    "outline_line": item["outline"]["line"],
                    "volume_id": item["volume"]["volume_id"],
                    "status": item["status"],
                }
                for item in documents
            ],
            "issues": [{key: item[key] for key in sorted(item)} for item in issues],
        }
        revision = self._digest(
            json.dumps(
                revision_payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        )
        chapter_index: dict[str, list[str]] = defaultdict(list)
        for document in documents:
            chapter_index[str(document["chapter_id"])].append(str(document["occurrence_id"]))
        return {
            "schema_version": SURFACE_SCHEMA_VERSION,
            "novel_id": self.novel_id,
            "mode": mode,
            "revision": revision,
            "mutation_allowed": not any(item["blocking"] for item in issues),
            "actual_order": [item["occurrence_id"] for item in documents],
            "document_order": [item["document_id"] for item in documents],
            "chapter_index": dict(sorted(chapter_index.items())),
            "volumes": volumes,
            "documents": documents,
            "issues": issues,
        }

    def _disk_documents(self) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        documents: list[dict[str, Any]] = []
        issues: list[dict[str, Any]] = []
        if not self.manuscript_root.is_dir():
            return documents, issues
        for path in sorted(self.manuscript_root.glob("**/ch_*.md")):
            if not CHAPTER_FILE_RE.fullmatch(path.name):
                continue
            relative = path.relative_to(self.novel_root).as_posix()
            status = "present"
            content = b""
            text = ""
            updated_at = ""
            try:
                if path.is_symlink() or not path.is_file():
                    raise OSError("chapter is not a regular file")
                updated_at = datetime.fromtimestamp(
                    path.stat().st_mtime, tz=timezone.utc
                ).isoformat()
                content = path.read_bytes()
                text = content.decode("utf-8")
            except (OSError, UnicodeDecodeError):
                status = "unreadable"
                issues.append(
                    self._issue(
                        "UNREADABLE_CHAPTER_FILE",
                        chapter_id=path.stem,
                        paths=[relative],
                    )
                )
            match = HEADING_RE.search(text)
            documents.append(
                {
                    "document_id": "",
                    "chapter_id": path.stem,
                    "title": match.group(1).strip() if match else path.stem,
                    "path": relative,
                    "writing_units": count_writing_units(text) if text else 0,
                    "content_sha256": self._digest(content) if status != "unreadable" else "",
                    "updated_at": updated_at,
                    "status": status,
                }
            )
        return documents, issues

    def _outline_documents(
        self, structure: dict[str, Any]
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        volumes: list[dict[str, Any]] = []
        documents: list[dict[str, Any]] = []
        for root in structure["roots"]:
            if root["kind"] != "volume":
                continue
            volume_order = len(volumes)
            volume_id = str(root["id"])
            disk_arc_id = f"arc_{volume_order + 1:03d}"
            volumes.append(
                {
                    "volume_id": volume_id,
                    "title": str(root["title"]),
                    "order": volume_order,
                    "disk_arc_id": disk_arc_id,
                    "document_ids": [],
                    "occurrence_ids": [],
                    "outline": {
                        "line": int(root["line"]),
                        "end_line": int(root["end_line"]),
                        "chapter_insert_line": 0,
                    },
                }
            )

            def visit(node: dict[str, Any], section: dict[str, Any] | None) -> None:
                active_section = node if node["kind"] == "section" else section
                if node["kind"] == "section":
                    volumes[-1]["outline"]["chapter_insert_line"] = int(node["end_line"])
                if node["kind"] == "chapter":
                    documents.append(
                        {
                            "chapter_id": str(node["id"]),
                            "title": str(node["title"]),
                            "line": int(node["line"]),
                            "end_line": int(node["end_line"]),
                            "section_id": (
                                str(active_section["id"]) if active_section is not None else ""
                            ),
                            "section_title": (
                                str(active_section["title"]) if active_section is not None else ""
                            ),
                            "volume_id": volume_id,
                            "volume_title": str(root["title"]),
                            "disk_arc_id": disk_arc_id,
                        }
                    )
                    return
                for child in node.get("children", []):
                    visit(child, active_section)

            visit(root, None)
        return volumes, documents

    @staticmethod
    def _project_document(disk: dict[str, Any], outline: dict[str, Any]) -> dict[str, Any]:
        return {
            "document_id": str(disk["document_id"]),
            "chapter_id": str(disk["chapter_id"]),
            "title": str(disk["title"] or outline.get("title") or disk["chapter_id"]),
            "path": str(disk["path"]),
            "status": str(disk["status"]),
            "writing_units": int(disk["writing_units"]),
            "content_sha256": str(disk["content_sha256"]),
            "revision": str(disk["content_sha256"]),
            "updated_at": str(disk.get("updated_at") or ""),
            "outline": {
                "line": int(outline["line"]),
                "end_line": int(outline["end_line"]),
                "section_id": str(outline["section_id"]),
                "section_title": str(outline["section_title"]),
            },
            "volume": {
                "volume_id": str(outline["volume_id"]),
                "title": str(outline["volume_title"]),
                "disk_arc_id": str(outline["disk_arc_id"]),
            },
        }

    def _moved_outline(
        self,
        document: dict[str, Any],
        target_volume: dict[str, Any],
        target_documents: list[dict[str, Any]],
        target_index: int,
        text: str,
    ) -> str:
        lines = text.splitlines(keepends=True)
        source_start = int(document["outline"]["line"]) - 1
        source_end = int(document["outline"]["end_line"])
        block = lines[source_start:source_end]
        if not block:
            raise ReadingOrderError(
                "无法定位大纲中的章节块",
                code="READING_OUTLINE_LOCATION_INVALID",
            )
        if target_index < len(target_documents):
            insertion = int(target_documents[target_index]["outline"]["line"]) - 1
        elif target_documents:
            insertion = int(target_documents[-1]["outline"]["end_line"])
        else:
            insertion = int(target_volume.get("outline", {}).get("chapter_insert_line", 0))
            if insertion <= 0:
                raise ReadingOrderError(
                    "目标卷没有可接纳章节的节标题",
                    code="READING_TARGET_SECTION_MISSING",
                )
        del lines[source_start:source_end]
        if insertion > source_start:
            insertion -= source_end - source_start
        lines[insertion:insertion] = block
        return "".join(lines)

    def _commit_move(
        self,
        *,
        source: Path,
        target: Path,
        source_content: bytes,
        outline_before: bytes,
        outline_after: bytes,
        registry_before: bytes | None,
        registry_after: bytes,
        fault_injector: FaultInjector | None,
    ) -> None:
        temporary: list[Path] = []
        target_was_created = False
        source_was_removed = False
        try:
            outline_temp = self._temporary(self.outline_path, outline_after)
            temporary.append(outline_temp)
            registry_temp = self._temporary(self.identity_path, registry_after)
            temporary.append(registry_temp)
            target_temp: Path | None = None
            if target != source:
                target_temp = self._temporary(target, source_content)
                temporary.append(target_temp)
                target_temp.replace(target)
                target_was_created = True
                self._fault(fault_injector, "document_copied")
            outline_temp.replace(self.outline_path)
            self._fault(fault_injector, "outline_replaced")
            registry_temp.replace(self.identity_path)
            self._fault(fault_injector, "registry_replaced")
            if target != source:
                source.unlink()
                source_was_removed = True
                self._fault(fault_injector, "source_removed")
            self._fsync_directory(self.outline_path.parent)
            self._fsync_directory(self.identity_path.parent)
            self._fsync_directory(source.parent)
            if target.parent != source.parent:
                self._fsync_directory(target.parent)
        except Exception as exc:
            rollback_errors: list[str] = []
            try:
                self._atomic_bytes(self.outline_path, outline_before)
            except OSError as rollback_exc:
                rollback_errors.append(f"outline:{rollback_exc}")
            try:
                if registry_before is None:
                    self.identity_path.unlink(missing_ok=True)
                else:
                    self._atomic_bytes(self.identity_path, registry_before)
            except OSError as rollback_exc:
                rollback_errors.append(f"identity:{rollback_exc}")
            try:
                if source_was_removed or not source.is_file():
                    self._atomic_bytes(source, source_content)
            except OSError as rollback_exc:
                rollback_errors.append(f"source:{rollback_exc}")
            try:
                if target != source and target_was_created:
                    target.unlink(missing_ok=True)
            except OSError as rollback_exc:
                rollback_errors.append(f"target:{rollback_exc}")
            raise ReadingOrderError(
                "章节移动事务失败，已回滚",
                code="READING_ORDER_TRANSACTION_FAILED",
                recoverable=not rollback_errors,
                details={"rollback_errors": rollback_errors},
            ) from exc
        finally:
            for path in temporary:
                path.unlink(missing_ok=True)

    def _identities(self) -> tuple[dict[str, str], list[dict[str, Any]]]:
        if not self.identity_path.is_file():
            return {}, []
        try:
            payload = json.loads(self.identity_path.read_text(encoding="utf-8"))
            raw = payload.get("documents") if isinstance(payload, dict) else None
            if (
                not isinstance(payload, dict)
                or payload.get("schema_version") != IDENTITY_SCHEMA_VERSION
                or not isinstance(raw, dict)
            ):
                raise ValueError("invalid identity registry")
            identities = {
                str(path): str(document_id)
                for path, document_id in raw.items()
                if isinstance(path, str)
                and isinstance(document_id, str)
                and DOCUMENT_ID_RE.fullmatch(document_id)
            }
            if len(identities) != len(raw):
                raise ValueError("invalid identity entry")
            return identities, []
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError):
            return {}, [
                self._issue(
                    "DOCUMENT_IDENTITY_REGISTRY_INVALID",
                    paths=[self.identity_path.relative_to(self.novel_root).as_posix()],
                )
            ]

    def _read_outline(self) -> str | None:
        if not self.outline_path.is_file():
            return None
        try:
            return self.outline_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            raise ReadingOrderError(
                "大纲文件无法读取",
                code="READING_OUTLINE_UNREADABLE",
            ) from exc

    def _document_content(self, document: dict[str, Any]) -> str:
        if document["status"] not in {"present", "orphan"}:
            return ""
        try:
            return self._safe_document_path(str(document["path"])).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return ""

    def _safe_document_path(self, relative: str) -> Path:
        path = (self.novel_root / relative).resolve()
        self._require_inside(path, self.manuscript_root)
        return path

    @staticmethod
    def _require_inside(path: Path, parent: Path) -> None:
        try:
            path.relative_to(parent.resolve())
        except ValueError as exc:
            raise ReadingOrderError(
                "章节路径越出正文目录",
                code="READING_DOCUMENT_PATH_INVALID",
            ) from exc

    def _derived_document_id(self, key: str) -> str:
        digest = hashlib.sha256(f"{self.novel_id}\0{key}".encode()).hexdigest()
        return f"doc_{digest[:24]}"

    def _derived_occurrence_id(self, document_id: str, ordinal: int) -> str:
        digest = hashlib.sha256(f"{self.novel_id}\0{document_id}\0{ordinal}".encode()).hexdigest()
        return f"occ_{digest[:24]}"

    @staticmethod
    def _digest(content: bytes) -> str:
        return "sha256:" + hashlib.sha256(content).hexdigest()

    @staticmethod
    def _chapter_number(chapter_id: str) -> int:
        match = re.search(r"(\d+)$", chapter_id)
        return int(match.group(1)) if match else 10**9

    @staticmethod
    def _disk_arc_id(relative: str) -> str:
        parts = Path(relative).parts
        return parts[-2] if len(parts) >= 2 else "root"

    @staticmethod
    def _arc_sort_key(arc_id: str) -> tuple[int, str]:
        match = re.search(r"(\d+)$", arc_id)
        return (int(match.group(1)) if match else 10**9, arc_id)

    def _volume_for_disk(
        self, volumes: list[dict[str, Any]], relative: str
    ) -> dict[str, Any] | None:
        arc_id = self._disk_arc_id(relative)
        return next((volume for volume in volumes if volume["disk_arc_id"] == arc_id), None)

    def _synthetic_volume(self, volumes: list[dict[str, Any]], relative: str) -> dict[str, Any]:
        arc_id = self._disk_arc_id(relative)
        return {
            "volume_id": f"unmapped_{arc_id}",
            "title": arc_id,
            "order": len(volumes),
            "disk_arc_id": arc_id,
            "document_ids": [],
            "occurrence_ids": [],
            "outline": {"line": 0, "end_line": 0, "chapter_insert_line": 0},
        }

    @staticmethod
    def _issue(
        code: str,
        *,
        blocking: bool = True,
        chapter_id: str = "",
        document_ids: list[str] | None = None,
        paths: list[str] | None = None,
        outline_lines: list[int] | None = None,
    ) -> dict[str, Any]:
        return {
            "code": code,
            "blocking": blocking,
            "chapter_id": chapter_id,
            "document_ids": list(document_ids or []),
            "occurrence_ids": [],
            "paths": list(paths or []),
            "outline_lines": list(outline_lines or []),
        }

    @staticmethod
    def _temporary(target: Path, content: bytes) -> Path:
        target.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=target.parent,
            prefix=f".{target.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
            return Path(handle.name)

    @classmethod
    def _atomic_bytes(cls, target: Path, content: bytes) -> None:
        temporary = cls._temporary(target, content)
        try:
            temporary.replace(target)
        finally:
            temporary.unlink(missing_ok=True)

    @staticmethod
    def _fsync_directory(path: Path) -> None:
        try:
            descriptor = os.open(path, os.O_RDONLY)
        except OSError:
            return
        try:
            os.fsync(descriptor)
        except OSError:
            pass
        finally:
            os.close(descriptor)

    @staticmethod
    def _fault(fault_injector: FaultInjector | None, stage: str) -> None:
        if fault_injector is not None:
            fault_injector(stage)

    @staticmethod
    def _index_without_document(surface: dict[str, Any], occurrence_id: str) -> int:
        document = next(
            item for item in surface["documents"] if item["occurrence_id"] == occurrence_id
        )
        siblings = [
            item
            for item in surface["documents"]
            if item["volume"]["volume_id"] == document["volume"]["volume_id"]
        ]
        original = next(
            index for index, item in enumerate(siblings) if item["occurrence_id"] == occurrence_id
        )
        return min(original, len(siblings) - 1)

    @staticmethod
    def _mutation_result(
        before: dict[str, Any],
        after: dict[str, Any],
        document: dict[str, Any],
        target_index: int,
    ) -> dict[str, Any]:
        return {
            "schema_version": MUTATION_SCHEMA_VERSION,
            "novel_id": after["novel_id"],
            "document_id": document["document_id"],
            "target_volume_id": document["volume"]["volume_id"],
            "target_index": target_index,
            "source_revision": before["revision"],
            "result_revision": after["revision"],
            "reading_order": after,
        }
