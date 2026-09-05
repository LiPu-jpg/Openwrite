"""Deterministic manuscript export inventory and delivery gates."""

from __future__ import annotations

import hashlib
import json
import re
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any
from xml.etree import ElementTree

import yaml

from tools.character_state_index import strip_character_state_annotations
from tools.manuscript_acceptance import ManuscriptAcceptanceService
from tools.novel_workspace import count_writing_units
from tools.review_store import ReviewStore, review_is_deliverable
from tools.scene_integration import load_scene_surface
from tools.writing_targets import normalize_writing_targets

SCHEMA_VERSION = "openwrite.export-preflight.v1"
CHAPTER_FILE_RE = re.compile(r"^ch_(\d+)\.md$")
PURPOSES = {"backup", "delivery"}
FORMATS = {"md", "txt", "epub"}


class ExportPreflightError(ValueError):
    def __init__(
        self,
        message: str,
        *,
        code: str = "EXPORT_PREFLIGHT_FAILED",
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.details = details or {}


class ExportPreflightService:
    def __init__(self, project_root: Path, novel_id: str) -> None:
        self.project_root = Path(project_root).resolve()
        self.novel_id = str(novel_id)
        self.novel_root = self.project_root / "data" / "novels" / self.novel_id
        self.manuscript_root = self.novel_root / "data" / "manuscript"

    def inspect(
        self,
        *,
        format_name: str = "md",
        purpose: str = "backup",
    ) -> dict[str, Any]:
        clean_format = str(format_name or "md").lower()
        clean_purpose = str(purpose or "backup").lower()
        if clean_format not in FORMATS:
            raise ExportPreflightError("导出格式仅支持 md、txt 或 epub", code="INVALID_FORMAT")
        if clean_purpose not in PURPOSES:
            raise ExportPreflightError("导出用途仅支持 backup 或 delivery", code="INVALID_PURPOSE")

        config = self._config()
        targets = normalize_writing_targets(config.get("writing_targets"))
        chapters, unreadable = self._inventory()
        scene_structure = self._scene_status()
        if scene_structure is not None:
            chapters = self._order_inventory(chapters, scene_structure["chapters"])
        by_id: dict[str, list[dict[str, Any]]] = {}
        for chapter in chapters:
            by_id.setdefault(chapter["chapter_id"], []).append(chapter)
        duplicates = {
            chapter_id: [item["path"] for item in items]
            for chapter_id, items in by_id.items()
            if len(items) > 1
        }
        numbers = sorted({int(item["number"]) for item in chapters})
        missing = (
            [
                f"ch_{number:03d}"
                for number in range(numbers[0], numbers[-1] + 1)
                if number not in numbers
            ]
            if numbers
            else []
        )
        empty = [item["chapter_id"] for item in chapters if item["empty"]]
        review = self._review_status(chapters, duplicates)
        acceptance = self._acceptance_status()
        metadata = {
            "title": str(config.get("title") or "").strip(),
            "author": str(config.get("author") or "").strip(),
            "language": str(config.get("language") or "zh-CN").strip(),
        }

        blockers: list[dict[str, Any]] = []
        warnings: list[dict[str, Any]] = []
        if not chapters:
            blockers.append(self._issue("NO_CHAPTERS", "没有可导出的正文"))
        if unreadable:
            blockers.append(
                self._issue("CHAPTER_UNREADABLE", "存在无法读取的章节", paths=unreadable)
            )
        if duplicates:
            blockers.append(
                self._issue(
                    "DUPLICATE_CHAPTER_ID",
                    "同一章节 ID 对应多个文件，导出会丢失正文",
                    chapters=sorted(duplicates),
                    paths=duplicates,
                )
            )
        self._purpose_issue(
            clean_purpose,
            blockers,
            warnings,
            "CHAPTER_SEQUENCE_GAP",
            "章节编号存在缺口",
            chapters=missing,
            active=bool(missing),
        )
        self._purpose_issue(
            clean_purpose,
            blockers,
            warnings,
            "EMPTY_CHAPTER",
            "存在只有标题或没有正文的章节",
            chapters=empty,
            active=bool(empty),
        )
        for field, label in (("title", "书名"), ("author", "作者"), ("language", "语言")):
            if not metadata[field]:
                self._purpose_issue(
                    clean_purpose,
                    blockers,
                    warnings,
                    f"METADATA_{field.upper()}_MISSING",
                    f"缺少{label}元数据",
                )
        if acceptance["blocking"]:
            self._purpose_issue(
                clean_purpose,
                blockers,
                warnings,
                "MANUSCRIPT_FACTS_NOT_CURRENT",
                "正文事实接纳尚未完成",
                chapters=acceptance["blocking_chapters"],
                acceptance_status=acceptance["status"],
                needs_review=acceptance["needs_review"],
            )
        for code, message, key in (
            ("REVIEW_MISSING", "存在尚未评审的章节", "missing"),
            ("REVIEW_STALE", "存在评审已过期的章节", "stale"),
            ("REVIEW_NOT_APPROVED", "存在评审未通过的章节", "not_approved"),
        ):
            values = review[key]
            if values:
                self._purpose_issue(
                    clean_purpose,
                    blockers,
                    warnings,
                    code,
                    message,
                    chapters=values,
                )
        if scene_structure is not None and scene_structure["status"] != "current":
            self._purpose_issue(
                clean_purpose,
                blockers,
                warnings,
                "SCENE_STRUCTURE_NOT_CURRENT",
                "场景结构已过期或存在歧义",
                status=scene_structure["status"],
                chapters=scene_structure["affected_chapters"],
                issue_codes=scene_structure["issue_codes"],
            )

        total_units = sum(int(item["writing_units"]) for item in chapters)
        report = {
            "schema_version": SCHEMA_VERSION,
            "novel_id": self.novel_id,
            "format": clean_format,
            "purpose": clean_purpose,
            "can_export": not blockers,
            "actual_order": [item["chapter_id"] for item in chapters],
            "chapters": chapters,
            "structure": {
                "duplicates": duplicates,
                "missing": missing,
                "empty": empty,
                "unreadable": unreadable,
            },
            "writing_units": {
                "total": total_units,
                "book_target": targets["book_words"],
                "chapter_target": targets["chapter_words"],
                "completion_ratio": round(total_units / targets["book_words"], 4),
            },
            "metadata": metadata,
            "reviews": review,
            "manuscript_acceptance": acceptance,
            "blockers": blockers,
            "warnings": warnings,
        }
        if scene_structure is not None:
            report["scene_structure"] = scene_structure
        encoded = json.dumps(report, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        report["preflight_revision"] = (
            "sha256:" + hashlib.sha256(encoded.encode("utf-8")).hexdigest()
        )
        return report

    def require_exportable(
        self,
        *,
        format_name: str = "md",
        purpose: str = "backup",
        expected_revision: str = "",
    ) -> dict[str, Any]:
        report = self.inspect(format_name=format_name, purpose=purpose)
        if expected_revision and expected_revision != report["preflight_revision"]:
            raise ExportPreflightError(
                "导出预检结果已经变化，请重新检查",
                code="EXPORT_PREFLIGHT_CHANGED",
                details={"preflight": report},
            )
        if not report["can_export"]:
            raise ExportPreflightError(
                "导出预检未通过",
                details={"preflight": report},
            )
        return report

    def validate_output(self, path: Path, *, format_name: str) -> dict[str, Any]:
        output = Path(path)
        clean_format = str(format_name or "").lower()
        if not output.is_file() or output.stat().st_size == 0:
            raise ExportPreflightError("导出文件不存在或为空", code="EXPORT_OUTPUT_INVALID")
        result: dict[str, Any] = {
            "valid": True,
            "format": clean_format,
            "size": output.stat().st_size,
            "sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
        }
        if clean_format != "epub":
            return result
        try:
            from tools.epub_export import validate_epub

            structural = validate_epub(output)
            with zipfile.ZipFile(output) as archive:
                package = ElementTree.fromstring(archive.read("OEBPS/package.opf"))
                nav = ElementTree.fromstring(archive.read("OEBPS/nav.xhtml"))
                opf_ns = {"opf": "http://www.idpf.org/2007/opf"}
                xhtml_ns = {"xhtml": "http://www.w3.org/1999/xhtml"}
                manifest = {
                    str(item.get("id")): str(item.get("href"))
                    for item in package.findall("opf:manifest/opf:item", opf_ns)
                }
                body_files = [
                    (PurePosixPath("OEBPS") / manifest[str(item.get("idref"))]).as_posix()
                    for item in package.findall("opf:spine/opf:itemref", opf_ns)
                ]
                toc_titles = [
                    "".join(link.itertext()).strip() for link in nav.findall(".//xhtml:a", xhtml_ns)
                ]
                if len(toc_titles) != len(body_files):
                    raise ExportPreflightError(
                        "EPUB 目录与正文数量不一致", code="EPUB_VALIDATION_FAILED"
                    )
                for name in body_files:
                    body = ElementTree.fromstring(archive.read(name))
                    if not "".join(body.itertext()).strip():
                        raise ExportPreflightError(
                            f"EPUB 正文为空: {name}", code="EPUB_VALIDATION_FAILED"
                        )
            result.update(structural)
            result.update({"toc_titles": toc_titles, "body_files": body_files})
            return result
        except ExportPreflightError:
            raise
        except Exception as exc:
            raise ExportPreflightError(
                f"EPUB 格式校验失败: {exc}", code="EPUB_VALIDATION_FAILED"
            ) from exc

    def _inventory(self) -> tuple[list[dict[str, Any]], list[str]]:
        chapters: list[dict[str, Any]] = []
        unreadable: list[str] = []
        if not self.manuscript_root.exists():
            return chapters, unreadable
        for path in self.manuscript_root.rglob("ch_*.md"):
            match = CHAPTER_FILE_RE.fullmatch(path.name)
            if not path.is_file() or not match:
                continue
            relative = path.relative_to(self.novel_root).as_posix()
            try:
                content = path.read_text(encoding="utf-8")
            except (OSError, UnicodeError):
                unreadable.append(relative)
                continue
            prose = strip_character_state_annotations(content)
            units = count_writing_units(content)
            title_match = re.search(r"^\s{0,3}#{1,6}\s+(.+?)\s*$", prose, re.MULTILINE)
            chapters.append(
                {
                    "chapter_id": path.stem,
                    "number": int(match.group(1)),
                    "path": relative,
                    "title": title_match.group(1).strip() if title_match else path.stem,
                    "writing_units": units,
                    "empty": units == 0,
                    "revision": "sha256:" + hashlib.sha256(content.encode("utf-8")).hexdigest(),
                }
            )
        chapters.sort(key=lambda item: (item["number"], item["path"]))
        return chapters, sorted(unreadable)

    def _review_status(
        self,
        chapters: list[dict[str, Any]],
        duplicates: dict[str, list[str]],
    ) -> dict[str, list[str]]:
        result: dict[str, list[str]] = {
            "missing": [],
            "current": [],
            "stale": [],
            "approved": [],
            "not_approved": [],
        }
        store = ReviewStore(self.project_root, self.novel_id)
        for chapter in chapters:
            chapter_id = str(chapter["chapter_id"])
            if chapter_id in duplicates:
                continue
            record = store.load(chapter_id)
            if not record:
                result["missing"].append(chapter_id)
                continue
            revision = str(chapter["revision"])
            source_revision = str(record.get("source_revision") or "")
            stale = bool(record.get("stale")) or not source_revision or source_revision != revision
            result["stale" if stale else "current"].append(chapter_id)
            if stale:
                continue
            if review_is_deliverable(record, current_source_revision=revision):
                result["approved"].append(chapter_id)
            else:
                result["not_approved"].append(chapter_id)
        return {key: sorted(set(value), key=self._chapter_number) for key, value in result.items()}

    def _acceptance_status(self) -> dict[str, Any]:
        surface = ManuscriptAcceptanceService(self.project_root, self.novel_id).inspect()
        blocking_statuses = {
            "baseline_required",
            "pending",
            "processing",
            "failed",
            "stale",
            "external_change",
        }
        blocking_chapters = [
            str(item.get("chapter_id") or "")
            for item in surface.get("chapters") or []
            if str(item.get("status") or "") in blocking_statuses
        ]
        needs_review = [
            str(item.get("domain") or "")
            for item in surface.get("needs_review") or []
            if str(item.get("domain") or "")
        ]
        if needs_review and not blocking_chapters:
            blocking_chapters = [
                str(item.get("chapter_id") or "")
                for item in surface.get("chapters") or []
                if str(item.get("chapter_id") or "")
            ]
        return {
            "status": str(surface.get("status") or ""),
            "blocking": bool(surface.get("blocking")),
            "blocking_chapters": blocking_chapters,
            "needs_review": sorted(set(needs_review)),
        }

    def _scene_status(self) -> dict[str, Any] | None:
        surface = load_scene_surface(self.project_root, self.novel_id)
        if surface.get("status") == "absent":
            return None
        source_revisions: dict[str, set[str]] = {}
        for scene in surface.get("scenes") or []:
            if not isinstance(scene, dict) or not isinstance(scene.get("chapter"), dict):
                continue
            document_id = str(scene["chapter"].get("document_id") or "")
            anchor = scene.get("anchor") if isinstance(scene.get("anchor"), dict) else {}
            source_revision = str(anchor.get("source_revision") or "")
            if document_id and source_revision:
                source_revisions.setdefault(document_id, set()).add(source_revision)
        canonical_source_revisions = {
            document_id: next(iter(revisions)) if len(revisions) == 1 else ""
            for document_id, revisions in source_revisions.items()
        }
        chapters = [
            {
                "chapter_id": str(item.get("chapter_id") or ""),
                "document_id": str(item.get("document_id") or ""),
                "occurrence_id": str(item.get("occurrence_id") or ""),
                "path": str(item.get("path") or ""),
                "source_revision": canonical_source_revisions.get(
                    str(item.get("document_id") or ""), ""
                ),
                "current_source_revision": str(item.get("revision") or ""),
                "freshness": str(item.get("freshness") or "ambiguous"),
            }
            for item in surface.get("chapters") or []
            if isinstance(item, dict)
        ]
        affected = [
            item["chapter_id"]
            for item in chapters
            if item["freshness"] != "current" and item["chapter_id"]
        ]
        affected.extend(
            str(item["chapter"].get("chapter_id") or "")
            for item in surface.get("scenes") or []
            if isinstance(item, dict)
            and isinstance(item.get("chapter"), dict)
            and str(item.get("freshness") or "") != "current"
            and str(item["chapter"].get("chapter_id") or "")
        )
        issues = [
            dict(item)
            for item in surface.get("issues") or []
            if isinstance(item, dict) and item.get("blocking")
        ]
        return {
            "schema_version": str(surface.get("schema_version") or ""),
            "status": str(surface.get("status") or "ambiguous"),
            "revision": str(surface.get("revision") or ""),
            "sidecar_revision": str(surface.get("sidecar_revision") or ""),
            "reading_order_revision": str(surface.get("reading_order_revision") or ""),
            "mutation_allowed": bool(surface.get("mutation_allowed")),
            "chapters": chapters,
            "affected_chapters": list(dict.fromkeys(affected)),
            "issue_codes": list(dict.fromkeys(str(item.get("code") or "") for item in issues)),
            "issues": issues,
        }

    @staticmethod
    def _order_inventory(
        chapters: list[dict[str, Any]],
        scene_chapters: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Order the disk inventory by canonical document paths without dropping rows."""

        ranks = {
            str(item.get("path") or ""): index
            for index, item in enumerate(scene_chapters)
            if str(item.get("path") or "")
        }
        fallback = len(ranks)
        return sorted(
            chapters,
            key=lambda item: (
                ranks.get(str(item.get("path") or ""), fallback),
                int(item.get("number") or 0),
                str(item.get("path") or ""),
            ),
        )

    def _config(self) -> dict[str, Any]:
        path = self.project_root / "novel_config.yaml"
        try:
            value = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except (OSError, yaml.YAMLError) as exc:
            raise ExportPreflightError(f"项目配置无法读取: {exc}") from exc
        return value if isinstance(value, dict) else {}

    @staticmethod
    def _chapter_number(value: str) -> int:
        match = re.fullmatch(r"ch_(\d+)", str(value or ""))
        return int(match.group(1)) if match else 0

    @staticmethod
    def _issue(code: str, message: str, **details: Any) -> dict[str, Any]:
        return {"code": code, "message": message, **details}

    def _purpose_issue(
        self,
        purpose: str,
        blockers: list[dict[str, Any]],
        warnings: list[dict[str, Any]],
        code: str,
        message: str,
        *,
        active: bool = True,
        **details: Any,
    ) -> None:
        if not active:
            return
        target = blockers if purpose == "delivery" else warnings
        target.append(self._issue(code, message, **details))
