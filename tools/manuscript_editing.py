"""Checkpointed manuscript versions and revision-aware annotations."""

from __future__ import annotations

import hashlib
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from models.manuscript_editing import ManuscriptAnnotationV1, ManuscriptVersionV1
from tools.novel_workspace import count_writing_units
from tools.project_lock import ProjectBusyError, ProjectWriteLock
from tools.review_store import ReviewStore


class ManuscriptEditingError(RuntimeError):
    def __init__(self, message: str, *, code: str = "MANUSCRIPT_EDITING_ERROR") -> None:
        super().__init__(message)
        self.code = code


class ManuscriptVersionStore:
    AUTOSAVE_COALESCE_SECONDS = 10 * 60

    def __init__(self, project_root: Path, novel_id: str) -> None:
        self.project_root = Path(project_root).resolve()
        self.novel_id = self._novel_id(novel_id)
        novels_root = (self.project_root / "data" / "novels").resolve()
        self.novel_root = (novels_root / self.novel_id).resolve()
        try:
            self.novel_root.relative_to(novels_root)
        except ValueError as exc:
            raise ManuscriptEditingError(
                "无效作品 ID", code="INVALID_NOVEL_ID"
            ) from exc
        self.root = self.novel_root / "data" / "manuscript_versions"
        self._last_acceptance: dict[str, Any] | None = None

    @property
    def last_acceptance(self) -> dict[str, Any] | None:
        """Return the acceptance operation started by the latest restore."""
        return None if self._last_acceptance is None else dict(self._last_acceptance)

    def checkpoint(
        self,
        chapter_id: str,
        *,
        reason: str = "manual",
        label: str = "",
        content: str | None = None,
    ) -> ManuscriptVersionV1:
        clean_chapter = self._chapter_id(chapter_id)
        path = self.chapter_path(clean_chapter)
        source = path.read_text(encoding="utf-8") if content is None else str(content)
        now = datetime.now(timezone.utc)
        version_id = f"ver_{now.strftime('%Y%m%d%H%M%S')}_{uuid4().hex[:10]}"
        chapter_root = self.root / clean_chapter
        content_path = chapter_root / f"{version_id}.md"
        content_path.parent.mkdir(parents=True, exist_ok=True)
        self._atomic_text(content_path, source)
        version = ManuscriptVersionV1(
            version_id=version_id,
            chapter_id=clean_chapter,
            source_revision=self.fingerprint(source),
            reason=reason,  # type: ignore[arg-type]
            label=str(label or "")[:200],
            created_at=now.isoformat(),
            content_file=content_path.relative_to(self.novel_root).as_posix(),
            writing_units=count_writing_units(source),
        )
        self._atomic_text(
            chapter_root / f"{version_id}.json",
            version.model_dump_json(indent=2) + "\n",
        )
        return version

    def list(self, chapter_id: str) -> list[ManuscriptVersionV1]:
        root = self.root / self._chapter_id(chapter_id)
        versions: list[ManuscriptVersionV1] = []
        if not root.is_dir():
            return versions
        for path in root.glob("ver_*.json"):
            try:
                versions.append(
                    ManuscriptVersionV1.model_validate_json(path.read_text(encoding="utf-8"))
                )
            except (OSError, ValueError):
                continue
        return sorted(versions, key=lambda item: item.created_at, reverse=True)

    def checkpoint_before_change(
        self,
        chapter_id: str,
        *,
        reason: str,
        label: str,
        content: str,
    ) -> tuple[ManuscriptVersionV1, bool]:
        """Keep the oldest source in one short autosave burst, but retain named saves."""
        clean_chapter = self._chapter_id(chapter_id)
        now = datetime.now(timezone.utc)
        if reason == "autosave":
            versions = self.list(clean_chapter)
            if versions and versions[0].reason == "autosave":
                try:
                    created_at = datetime.fromisoformat(versions[0].created_at)
                    if created_at.tzinfo is None:
                        created_at = created_at.replace(tzinfo=timezone.utc)
                    if (now - created_at).total_seconds() <= self.AUTOSAVE_COALESCE_SECONDS:
                        return versions[0], False
                except ValueError:
                    pass
        return (
            self.checkpoint(
                clean_chapter,
                reason=reason,
                label=label,
                content=content,
            ),
            True,
        )

    def compare(self, chapter_id: str, version_id: str) -> dict[str, Any]:
        clean_chapter = self._chapter_id(chapter_id)
        target, target_content = self.load(clean_chapter, version_id)
        current_content = self.chapter_path(clean_chapter).read_text(encoding="utf-8")
        from tools.revision_service import RevisionService

        return {
            "version": target.model_dump(mode="json"),
            "current": {
                "revision": self.fingerprint(current_content),
                "writing_units": count_writing_units(current_content),
            },
            "diff": RevisionService._diff(current_content, target_content),
        }

    def load(self, chapter_id: str, version_id: str) -> tuple[ManuscriptVersionV1, str]:
        clean_chapter = self._chapter_id(chapter_id)
        clean_version = self._version_id(version_id)
        meta_path = self.root / clean_chapter / f"{clean_version}.json"
        if not meta_path.is_file():
            raise ManuscriptEditingError("正文版本不存在", code="VERSION_NOT_FOUND")
        try:
            version = ManuscriptVersionV1.model_validate_json(
                meta_path.read_text(encoding="utf-8")
            )
            content_path = (self.root / clean_chapter / f"{clean_version}.md").resolve()
            content_path.relative_to(self.root.resolve())
            expected_file = content_path.relative_to(self.novel_root).as_posix()
            if (
                version.chapter_id != clean_chapter
                or version.version_id != clean_version
                or version.content_file != expected_file
            ):
                raise ValueError("version metadata identity mismatch")
            content = content_path.read_text(encoding="utf-8")
        except (OSError, ValueError) as exc:
            raise ManuscriptEditingError("正文版本损坏", code="INVALID_VERSION") from exc
        if self.fingerprint(content) != version.source_revision:
            raise ManuscriptEditingError("正文版本校验失败", code="INVALID_VERSION")
        return version, content

    def restore(
        self,
        chapter_id: str,
        version_id: str,
        *,
        current_revision: str,
        confirm: bool = False,
    ) -> ManuscriptVersionV1:
        self._last_acceptance = None
        if not confirm:
            raise ManuscriptEditingError("恢复版本需要显式确认", code="CONFIRMATION_REQUIRED")
        clean_chapter = self._chapter_id(chapter_id)
        clean_version = self._version_id(version_id)
        try:
            with ProjectWriteLock(
                self.project_root,
                self.novel_id,
                operation=f"manuscript_restore:{clean_chapter}:{clean_version}",
            ):
                path = self.chapter_path(clean_chapter)
                current = path.read_text(encoding="utf-8")
                if not self.revision_matches(current_revision, self.fingerprint(current)):
                    raise ManuscriptEditingError("当前正文已变化", code="STALE_REVISION")
                version, content = self.load(clean_chapter, clean_version)
                self.checkpoint(
                    clean_chapter,
                    reason="restore",
                    label=f"恢复前: {clean_version}",
                    content=current,
                )
                self._atomic_text(path, content)
                ReviewStore(self.project_root, self.novel_id).mark_stale(
                    clean_chapter,
                    reason="history_restored",
                    current_source_revision=self.fingerprint(content),
                )
                from tools.manuscript_acceptance import ManuscriptAcceptanceService

                self._last_acceptance = ManuscriptAcceptanceService(
                    self.project_root, self.novel_id
                ).start_acceptance(
                    clean_chapter,
                    source="history_restore",
                    expected_previous_revision=self.fingerprint(current),
                )
        except ProjectBusyError as exc:
            raise ManuscriptEditingError(str(exc), code="PROJECT_BUSY") from exc
        return version

    def chapter_path(self, chapter_id: str) -> Path:
        clean = self._chapter_id(chapter_id)
        manuscript_root = (self.novel_root / "data" / "manuscript").resolve()
        matches: list[Path] = []
        for candidate in manuscript_root.glob(f"**/{clean}.md"):
            try:
                resolved = candidate.resolve()
                resolved.relative_to(manuscript_root)
            except (OSError, ValueError):
                continue
            if resolved.is_file():
                matches.append(resolved)
        if len(matches) != 1:
            raise ManuscriptEditingError("正文章节不存在或 ID 重复", code="CHAPTER_NOT_FOUND")
        return matches[0]

    @staticmethod
    def fingerprint(content: str) -> str:
        return "sha256:" + hashlib.sha256(content.encode("utf-8")).hexdigest()

    @staticmethod
    def revision_matches(provided: str, current: str) -> bool:
        supplied = str(provided or "").strip().casefold()
        canonical = str(current or "").strip().casefold()
        if supplied == canonical:
            return True
        supplied_hash = supplied.removeprefix("sha256:")
        current_hash = canonical.removeprefix("sha256:")
        return bool(
            re.fullmatch(r"[0-9a-f]{16}", supplied_hash)
            and current_hash.startswith(supplied_hash)
        )

    @staticmethod
    def _novel_id(value: str) -> str:
        clean = str(value or "")
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{1,63}", clean):
            raise ManuscriptEditingError("无效作品 ID", code="INVALID_NOVEL_ID")
        return clean

    @staticmethod
    def _chapter_id(value: str) -> str:
        clean = str(value or "")
        if not re.fullmatch(r"ch_\d+", clean):
            raise ManuscriptEditingError("无效章节 ID", code="INVALID_CHAPTER_ID")
        return clean

    @staticmethod
    def _version_id(value: str) -> str:
        clean = str(value or "")
        if not re.fullmatch(r"ver_[A-Za-z0-9_-]{8,80}", clean):
            raise ManuscriptEditingError("无效版本 ID", code="INVALID_VERSION_ID")
        return clean

    @staticmethod
    def _atomic_text(path: Path, content: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
            temporary = Path(handle.name)
        temporary.replace(path)


class ManuscriptAnnotationStore:
    def __init__(self, project_root: Path, novel_id: str) -> None:
        self.versions = ManuscriptVersionStore(project_root, novel_id)
        self.root = self.versions.novel_root / "data" / "annotations"

    def create(
        self,
        chapter_id: str,
        *,
        source_revision: str,
        quote: str,
        start_hint: int,
        end_hint: int,
        note: str,
    ) -> ManuscriptAnnotationV1:
        content = self.versions.chapter_path(chapter_id).read_text(encoding="utf-8")
        current_revision = self.versions.fingerprint(content)
        if not self.versions.revision_matches(source_revision, current_revision):
            raise ManuscriptEditingError("正文已变化，请重新选择批注位置", code="STALE_REVISION")
        start = max(0, int(start_hint))
        end = max(start, int(end_hint))
        selected = content[start:end]
        clean_quote = str(quote or "")
        if selected != clean_quote:
            raise ManuscriptEditingError("批注引用与正文位置不匹配", code="ANCHOR_MISMATCH")
        now = datetime.now(timezone.utc).isoformat()
        annotation = ManuscriptAnnotationV1(
            annotation_id=f"ann_{uuid4().hex[:16]}",
            chapter_id=chapter_id,
            source_revision=current_revision,
            quote=clean_quote,
            start_hint=start,
            end_hint=end,
            note=str(note or "").strip(),
            current_start=start,
            current_end=end,
            created_at=now,
            updated_at=now,
        )
        self.save(annotation)
        return annotation

    def list(self, chapter_id: str) -> list[ManuscriptAnnotationV1]:
        root = self.root / self.versions._chapter_id(chapter_id)
        result: list[ManuscriptAnnotationV1] = []
        if not root.is_dir():
            return result
        content = self.versions.chapter_path(chapter_id).read_text(encoding="utf-8")
        for path in root.glob("ann_*.json"):
            try:
                item = ManuscriptAnnotationV1.model_validate_json(
                    path.read_text(encoding="utf-8")
                )
            except (OSError, ValueError):
                continue
            resolved = self._resolve(item, content)
            if resolved != item:
                self.save(resolved)
            result.append(resolved)
        return sorted(result, key=lambda item: item.created_at)

    def resolve(self, chapter_id: str, annotation_id: str) -> ManuscriptAnnotationV1:
        item = self._load(chapter_id, annotation_id)
        item.status = "resolved"
        item.updated_at = datetime.now(timezone.utc).isoformat()
        self.save(item)
        return item

    def save(self, annotation: ManuscriptAnnotationV1) -> Path:
        target = self._path(annotation.chapter_id, annotation.annotation_id)
        self.versions._atomic_text(
            target, annotation.model_dump_json(indent=2) + "\n"
        )
        return target

    def _load(self, chapter_id: str, annotation_id: str) -> ManuscriptAnnotationV1:
        path = self._path(chapter_id, annotation_id)
        if not path.is_file():
            raise ManuscriptEditingError("批注不存在", code="ANNOTATION_NOT_FOUND")
        try:
            return ManuscriptAnnotationV1.model_validate_json(
                path.read_text(encoding="utf-8")
            )
        except (OSError, ValueError) as exc:
            raise ManuscriptEditingError("批注损坏", code="INVALID_ANNOTATION") from exc

    def _resolve(
        self, item: ManuscriptAnnotationV1, content: str
    ) -> ManuscriptAnnotationV1:
        current_revision = self.versions.fingerprint(content)
        if current_revision == item.source_revision:
            return item.model_copy(
                update={
                    "anchor_state": "attached",
                    "current_start": item.start_hint,
                    "current_end": item.end_hint,
                }
            )
        positions = [match.start() for match in re.finditer(re.escape(item.quote), content)]
        if len(positions) == 1:
            start = positions[0]
            return item.model_copy(
                update={
                    "anchor_state": "relocated",
                    "current_start": start,
                    "current_end": start + len(item.quote),
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                }
            )
        return item.model_copy(
            update={
                "anchor_state": "detached",
                "current_start": None,
                "current_end": None,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
        )

    def _path(self, chapter_id: str, annotation_id: str) -> Path:
        chapter = self.versions._chapter_id(chapter_id)
        clean = str(annotation_id or "")
        if not re.fullmatch(r"ann_[A-Za-z0-9_-]{8,80}", clean):
            raise ManuscriptEditingError("无效批注 ID", code="INVALID_ANNOTATION_ID")
        return self.root / chapter / f"{clean}.json"


def manuscript_editing_action(
    project_root: Path,
    novel_id: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    versions = ManuscriptVersionStore(project_root, novel_id)
    annotations = ManuscriptAnnotationStore(project_root, novel_id)
    action = str(payload.get("action") or "versions")
    chapter_id = str(payload.get("chapter_id") or "")
    if action == "versions":
        return {"versions": [item.model_dump(mode="json") for item in versions.list(chapter_id)]}
    if action == "version":
        version, content = versions.load(
            chapter_id, str(payload.get("version_id") or "")
        )
        return {"version": version.model_dump(mode="json"), "content": content}
    if action == "compare":
        return versions.compare(chapter_id, str(payload.get("version_id") or ""))
    if action == "checkpoint":
        return versions.checkpoint(
            chapter_id,
            reason="manual",
            label=str(payload.get("label") or ""),
        ).model_dump(mode="json")
    if action == "restore":
        restored = versions.restore(
            chapter_id,
            str(payload.get("version_id") or ""),
            current_revision=str(payload.get("revision") or ""),
            confirm=bool(payload.get("confirm")),
        )
        return {
            **restored.model_dump(mode="json"),
            "acceptance": versions.last_acceptance,
        }
    if action == "annotations":
        return {
            "annotations": [
                item.model_dump(mode="json") for item in annotations.list(chapter_id)
            ]
        }
    if action == "annotate":
        return annotations.create(
            chapter_id,
            source_revision=str(payload.get("revision") or ""),
            quote=str(payload.get("quote") or ""),
            start_hint=int(payload.get("start_hint") or 0),
            end_hint=int(payload.get("end_hint") or 0),
            note=str(payload.get("note") or ""),
        ).model_dump(mode="json")
    if action == "resolve_annotation":
        return annotations.resolve(
            chapter_id, str(payload.get("annotation_id") or "")
        ).model_dump(mode="json")
    raise ManuscriptEditingError("未知正文编辑操作", code="INVALID_EDITING_ACTION")
