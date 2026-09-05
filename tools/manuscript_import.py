"""Durable, revision-gated import of legacy manuscripts.

An import operation owns an immutable source snapshot and an editable split
preview.  Canonical manuscript files are not touched until the exact preview
revision has been explicitly confirmed.  Publication stages a complete arc and
then swaps it into place, so a process interruption never exposes half a batch.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
from collections.abc import Callable, Iterable, Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from tools.novel_workspace import count_writing_units, split_manuscript
from tools.project_lock import ProjectBusyError, ProjectWriteLock

SCHEMA_VERSION = "openwrite.manuscript-import.v1"
PREVIEW_SCHEMA_VERSION = "openwrite.manuscript-import-preview.v1"
SYNTHESIS_SCHEMA_VERSION = "openwrite.manuscript-import-synthesis.v1"
STAGE_NAMES = (
    "snapshot",
    "split",
    "structure_confirmed",
    "published",
    "acceptance",
    "reconcile",
    "synthesis",
    "complete",
)
SUPPORTED_SUFFIXES = {".txt", ".md", ".markdown"}
MAX_SOURCE_BYTES = 32 * 1024 * 1024
MAX_CHAPTERS = 10_000

FaultInjector = Callable[[str], None]


class ManuscriptImportError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        code: str = "MANUSCRIPT_IMPORT_ERROR",
        recoverable: bool = True,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.recoverable = recoverable
        self.details = details or {}


class ManuscriptImportService:
    """Persist and resume one legacy-manuscript import transaction."""

    def __init__(self, project_root: Path, novel_id: str) -> None:
        self.project_root = Path(project_root).resolve()
        self.novel_id = str(novel_id)
        self.novel_root = self.project_root / "data" / "novels" / self.novel_id
        self.root = self.novel_root / "data" / "manuscript_imports"
        self.operations_dir = self.root / "operations"

    def operation_root(self, import_id: str) -> Path:
        clean = self._import_id(import_id)
        return self.operations_dir / clean

    def operation_path(self, import_id: str) -> Path:
        return self.operation_root(import_id) / "journal.json"

    def operation(self, import_id: str) -> dict[str, Any]:
        path = self.operation_path(import_id)
        payload = self._read_json(path)
        if (
            not isinstance(payload, dict)
            or payload.get("schema_version") != SCHEMA_VERSION
            or payload.get("novel_id") != self.novel_id
        ):
            raise ManuscriptImportError(
                "旧稿导入操作不存在或损坏",
                code="IMPORT_OPERATION_NOT_FOUND",
                recoverable=False,
            )
        self._bind_operation_paths(payload)
        return payload

    def list_operations(self, limit: int = 50) -> dict[str, Any]:
        """Return latest-first, credential-free journal summaries."""
        try:
            bounded = int(limit)
        except (TypeError, ValueError) as exc:
            raise ManuscriptImportError(
                "旧稿导入记录数量必须是整数", code="INVALID_IMPORT_LIMIT"
            ) from exc
        if bounded < 1 or bounded > 500:
            raise ManuscriptImportError(
                "旧稿导入记录数量必须在 1 到 500 之间",
                code="INVALID_IMPORT_LIMIT",
            )
        records: list[dict[str, Any]] = []
        if self.operations_dir.is_dir():
            for path in self.operations_dir.glob("import_*/journal.json"):
                payload = self._read_json(path)
                if (
                    isinstance(payload, dict)
                    and payload.get("schema_version") == SCHEMA_VERSION
                    and payload.get("novel_id") == self.novel_id
                ):
                    self._bind_operation_paths(payload)
                    records.append(payload)
        records.sort(key=lambda item: str(item.get("created_at") or ""), reverse=True)
        summaries = [self._operation_summary(item) for item in records[:bounded]]
        counts: dict[str, int] = {}
        for item in summaries:
            status = str(item["status"])
            counts[status] = counts.get(status, 0) + 1
        return {
            "schema_version": SCHEMA_VERSION,
            "novel_id": self.novel_id,
            "operations": summaries,
            "counts": counts,
        }

    def discard(self, import_id: str, *, confirm: bool = False) -> dict[str, Any]:
        if not confirm:
            raise ManuscriptImportError("丢弃旧稿导入需要显式确认", code="CONFIRMATION_REQUIRED")
        try:
            with ProjectWriteLock(
                self.project_root,
                self.novel_id,
                operation=f"manuscript_import_discard:{import_id}",
            ):
                operation = self.operation(import_id)
                if operation.get("status") == "discarded":
                    return self._operation_summary(operation)
                published_status = str(operation["stages"]["published"]["status"])
                before_publish = published_status == "pending"
                failed_without_commit = operation.get(
                    "status"
                ) == "failed" and not self._has_committed_canonical(operation)
                if not before_publish and not failed_without_commit:
                    raise ManuscriptImportError(
                        "已发布或已调和的旧稿导入不能丢弃",
                        code="IMPORT_DISCARD_FORBIDDEN",
                        recoverable=False,
                    )
                self._rollback_uncommitted_publication(operation)
                self._remove_staging_directory(operation)
                operation["status"] = "discarded"
                operation["discarded_at"] = self._now()
                operation["updated_at"] = operation["discarded_at"]
                operation["last_error"] = None
                self._write_operation(operation)
                return self._operation_summary(operation)
        except ProjectBusyError as exc:
            raise ManuscriptImportError(str(exc), code="PROJECT_BUSY", recoverable=True) from exc

    def start(
        self,
        source: Path,
        *,
        arc_id: str,
        start_number: int | None = None,
        fault_injector: FaultInjector | None = None,
    ) -> dict[str, Any]:
        source_path = Path(source).expanduser().resolve()
        if not source_path.is_file():
            raise ManuscriptImportError(
                "旧稿源文件不存在", code="IMPORT_SOURCE_NOT_FOUND", recoverable=False
            )
        suffix = source_path.suffix.lower()
        if suffix not in SUPPORTED_SUFFIXES:
            raise ManuscriptImportError(
                "当前仅支持 TXT 和 Markdown 旧稿",
                code="UNSUPPORTED_IMPORT_SOURCE",
                recoverable=False,
            )
        try:
            content = source_path.read_bytes()
        except OSError as exc:
            raise ManuscriptImportError(
                "旧稿源文件无法读取", code="IMPORT_SOURCE_UNREADABLE"
            ) from exc
        if len(content) > MAX_SOURCE_BYTES:
            raise ManuscriptImportError(
                "旧稿源文件超过 32 MB",
                code="IMPORT_SOURCE_TOO_LARGE",
                recoverable=False,
            )
        try:
            decoded = content.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise ManuscriptImportError(
                "旧稿源文件必须使用 UTF-8 编码",
                code="IMPORT_SOURCE_ENCODING",
                recoverable=False,
            ) from exc
        if not decoded.strip():
            raise ManuscriptImportError(
                "旧稿源文件为空", code="EMPTY_IMPORT_SOURCE", recoverable=False
            )
        clean_arc = self._arc_id(arc_id)
        first_number = self._start_number(start_number)
        import_id = (
            f"import_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}_{uuid4().hex[:12]}"
        )
        operation_root = self.operation_root(import_id)
        snapshot_path = operation_root / f"source{suffix}"
        preview_path = operation_root / "preview.json"
        now = self._now()
        source_sha = self.fingerprint(content)
        stages = {
            name: {
                "status": "pending",
                "attempts": 0,
                "input_sha256": "",
                "output_sha256": "",
                "started_at": "",
                "completed_at": "",
                "error_code": "",
                "error_message": "",
            }
            for name in STAGE_NAMES
        }
        record: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "import_id": import_id,
            "novel_id": self.novel_id,
            "status": "running",
            "arc_id": clean_arc,
            "start_number": first_number,
            "source": {
                "original_path": str(source_path),
                "filename": source_path.name,
                "suffix": suffix,
                "bytes": len(content),
                "sha256": source_sha,
                "snapshot_path": str(snapshot_path),
                "snapshot_relative_path": snapshot_path.relative_to(self.novel_root).as_posix(),
            },
            "preview_path": str(preview_path),
            "preview_revision": "",
            "confirmed_preview_revision": "",
            "chapter_count": 0,
            "writing_units": 0,
            "publish_plan": [],
            "published_chapters": [],
            "publication_sha256": "",
            "publication_transaction": {},
            "acceptance_operation_id": "",
            "acceptance_status": "",
            "synthesis_path": "",
            "synthesis_sha256": "",
            "stages": stages,
            "created_at": now,
            "updated_at": now,
            "completed_at": "",
            "last_error": None,
        }
        self._write_operation(record)
        return self._resume(
            record,
            source_bytes=content,
            fault_injector=fault_injector,
        )

    def preview(self, import_id: str) -> dict[str, Any]:
        operation = self.operation(import_id)
        return self._load_preview(operation)

    def revise_preview(
        self,
        import_id: str,
        *,
        expected_preview_revision: str,
        chapters: Iterable[Mapping[str, Any]],
    ) -> dict[str, Any]:
        operation = self.operation(import_id)
        if operation["stages"]["published"]["status"] != "pending":
            raise ManuscriptImportError(
                "旧稿发布已经开始，不能再修改切分预览",
                code="IMPORT_ALREADY_PUBLISHING",
                recoverable=False,
            )
        current = self._load_preview(operation)
        self._require_preview_revision(current, expected_preview_revision)
        normalized = self._normalize_chapters(chapters)
        updated = self._preview_payload(operation, normalized)
        self._atomic_json(Path(operation["preview_path"]), updated)
        operation["preview_revision"] = updated["revision"]
        operation["confirmed_preview_revision"] = ""
        operation["chapter_count"] = len(normalized)
        operation["writing_units"] = sum(int(item["writing_units"]) for item in normalized)
        operation["status"] = "awaiting_confirmation"
        operation["updated_at"] = self._now()
        operation["last_error"] = None
        operation["stages"]["structure_confirmed"] = self._empty_stage()
        self._write_operation(operation)
        return updated

    def confirm_structure(
        self,
        import_id: str,
        *,
        expected_preview_revision: str,
        confirm: bool = False,
    ) -> dict[str, Any]:
        if not confirm:
            raise ManuscriptImportError(
                "发布旧稿切分结构需要显式确认", code="CONFIRMATION_REQUIRED"
            )
        operation = self.operation(import_id)
        preview = self._load_preview(operation)
        self._require_preview_revision(preview, expected_preview_revision)
        stage = operation["stages"]["structure_confirmed"]
        if (
            stage["status"] == "completed"
            and operation.get("confirmed_preview_revision") == preview["revision"]
        ):
            return operation
        self._assert_no_duplicate_targets(operation, preview["chapters"])
        self._begin_stage(operation, "structure_confirmed", preview["revision"])
        operation["confirmed_preview_revision"] = preview["revision"]
        self._finish_stage(
            operation,
            "structure_confirmed",
            output_sha256=preview["revision"],
        )
        operation["status"] = "ready_to_publish"
        operation["updated_at"] = self._now()
        self._write_operation(operation)
        return operation

    def resume(
        self,
        import_id: str,
        *,
        fault_injector: FaultInjector | None = None,
    ) -> dict[str, Any]:
        return self._resume(
            self.operation(import_id),
            source_bytes=None,
            fault_injector=fault_injector,
        )

    def _resume(
        self,
        operation: dict[str, Any],
        *,
        source_bytes: bytes | None,
        fault_injector: FaultInjector | None,
    ) -> dict[str, Any]:
        if operation.get("status") == "completed":
            return operation
        if operation.get("status") == "discarded":
            return operation
        try:
            if operation["stages"]["snapshot"]["status"] != "completed":
                self._snapshot(operation, source_bytes, fault_injector)
            if operation["stages"]["split"]["status"] != "completed":
                self._split(operation, fault_injector)
            if operation["stages"]["structure_confirmed"]["status"] != "completed":
                self._set_waiting(operation, "awaiting_confirmation")
                return operation
            if operation["stages"]["published"]["status"] != "completed":
                self._publish(operation, fault_injector)
            if operation["stages"]["acceptance"]["status"] != "completed":
                self._start_acceptance(operation, fault_injector)
            if operation["stages"]["reconcile"]["status"] != "completed":
                if not self._observe_reconciliation(operation):
                    return operation
            if operation["stages"]["synthesis"]["status"] != "completed":
                self._synthesize(operation, fault_injector)
            if operation["stages"]["complete"]["status"] != "completed":
                self._complete(operation)
            return operation
        except Exception as exc:
            self._record_failure(operation, exc)
            raise

    def _snapshot(
        self,
        operation: dict[str, Any],
        source_bytes: bytes | None,
        fault_injector: FaultInjector | None,
    ) -> None:
        expected_sha = str(operation["source"]["sha256"])
        self._begin_stage(operation, "snapshot", expected_sha)
        snapshot_path = Path(operation["source"]["snapshot_path"])
        if snapshot_path.is_file():
            frozen = snapshot_path.read_bytes()
            if self.fingerprint(frozen) != expected_sha:
                raise ManuscriptImportError(
                    "旧稿冻结快照损坏",
                    code="IMPORT_SNAPSHOT_CORRUPT",
                    recoverable=False,
                )
        else:
            if source_bytes is None or self.fingerprint(source_bytes) != expected_sha:
                raise ManuscriptImportError(
                    "旧稿源文件未能冻结，请重新创建导入操作",
                    code="IMPORT_SNAPSHOT_MISSING",
                    recoverable=False,
                )
            self._atomic_bytes(snapshot_path, source_bytes)
            snapshot_path.chmod(0o444)
        if fault_injector:
            fault_injector("snapshot")
        self._finish_stage(operation, "snapshot", output_sha256=expected_sha)

    def _split(
        self,
        operation: dict[str, Any],
        fault_injector: FaultInjector | None,
    ) -> None:
        source_sha = str(operation["source"]["sha256"])
        self._begin_stage(operation, "split", source_sha)
        snapshot_path = Path(operation["source"]["snapshot_path"])
        try:
            frozen = snapshot_path.read_bytes()
            if self.fingerprint(frozen) != source_sha:
                raise ValueError("snapshot hash mismatch")
            text = frozen.decode("utf-8-sig").strip()
        except (OSError, UnicodeDecodeError, ValueError) as exc:
            raise ManuscriptImportError(
                "旧稿冻结快照无法解析",
                code="IMPORT_SNAPSHOT_CORRUPT",
                recoverable=False,
            ) from exc
        split = split_manuscript(
            text,
            fallback_title=Path(str(operation["source"]["filename"])).stem,
        )
        first = int(operation["start_number"])
        chapters = self._normalize_chapters(
            {
                "chapter_id": f"ch_{first + offset:03d}",
                "title": title,
                "content": content,
            }
            for offset, (title, content) in enumerate(split)
        )
        preview = self._preview_payload(operation, chapters)
        self._atomic_json(Path(operation["preview_path"]), preview)
        operation["preview_revision"] = preview["revision"]
        operation["chapter_count"] = len(chapters)
        operation["writing_units"] = sum(int(item["writing_units"]) for item in chapters)
        operation["updated_at"] = self._now()
        self._write_operation(operation)
        if fault_injector:
            fault_injector("split")
        self._finish_stage(operation, "split", output_sha256=preview["revision"])
        self._set_waiting(operation, "awaiting_confirmation")

    def _publish(
        self,
        operation: dict[str, Any],
        fault_injector: FaultInjector | None,
    ) -> None:
        preview = self._load_preview(operation)
        confirmed = str(operation.get("confirmed_preview_revision") or "")
        if confirmed != preview["revision"]:
            raise ManuscriptImportError(
                "切分预览已变化，请重新确认",
                code="STALE_PREVIEW_REVISION",
            )
        try:
            with ProjectWriteLock(
                self.project_root,
                self.novel_id,
                operation=f"manuscript_import:{operation['import_id']}",
            ):
                self._begin_stage(operation, "published", confirmed)
                plan = operation.get("publish_plan")
                if not isinstance(plan, list) or not plan:
                    self._assert_no_duplicate_targets(operation, preview["chapters"])
                    plan = self._prepare_publish_plan(operation, preview["chapters"])
                    operation["publish_plan"] = plan
                    operation["updated_at"] = self._now()
                    self._write_operation(operation)
                transaction, target_arc, _staged, _backup = self._publication_transaction_paths(
                    operation
                )
                installed = bool(transaction.get("final_sha256")) and self._tree_fingerprint(
                    target_arc
                ) == transaction.get("final_sha256")
                if not installed:
                    self._stage_publish_plan(operation, plan, fault_injector)
                    self._swap_published_arc(operation)
        except ProjectBusyError as exc:
            raise ManuscriptImportError(str(exc), code="PROJECT_BUSY", recoverable=True) from exc
        publication_sha = self._publication_sha(plan)
        operation["publication_sha256"] = publication_sha
        operation["published_chapters"] = [
            {
                "chapter_id": str(item["chapter_id"]),
                "title": str(item["title"]),
                "path": str(item["target_path"]),
                "relative_path": str(item["target_relative_path"]),
                "sha256": str(item["sha256"]),
                "writing_units": int(item["writing_units"]),
            }
            for item in plan
        ]
        operation["updated_at"] = self._now()
        self._write_operation(operation)
        if fault_injector:
            fault_injector("published")
        self._finish_stage(operation, "published", output_sha256=publication_sha)
        operation["status"] = "published"
        operation["updated_at"] = self._now()
        self._write_operation(operation)

    def _prepare_publish_plan(
        self,
        operation: dict[str, Any],
        chapters: Iterable[Mapping[str, Any]],
    ) -> list[dict[str, Any]]:
        target_arc = self._target_arc_path(str(operation["arc_id"]))
        operation_root = self.operation_root(operation["import_id"])
        staging = operation_root / "publication"
        backup = operation_root / "replaced_arc"
        base_sha = self._tree_fingerprint(target_arc)
        operation["publication_transaction"] = {
            "target_arc_path": str(target_arc),
            "stage_path": str(staging),
            "backup_path": str(backup),
            "base_sha256": base_sha,
            "final_sha256": "",
            "swap_status": "preparing",
        }
        plan: list[dict[str, Any]] = []
        for chapter in chapters:
            chapter_id = str(chapter["chapter_id"])
            rendered = self._render_chapter(chapter)
            content = rendered.encode("utf-8")
            staged = staging / f"{chapter_id}.md"
            target = self._target_path(str(operation["arc_id"]), chapter_id)
            plan.append(
                {
                    "chapter_id": chapter_id,
                    "title": str(chapter["title"]),
                    "staged_path": str(staged),
                    "target_path": str(target),
                    "target_relative_path": target.relative_to(self.novel_root).as_posix(),
                    "sha256": self.fingerprint(content),
                    "writing_units": count_writing_units(rendered),
                    "staged": False,
                    "staged_at": "",
                }
            )
        return plan

    def _stage_publish_plan(
        self,
        operation: dict[str, Any],
        plan: list[dict[str, Any]],
        fault_injector: FaultInjector | None,
    ) -> None:
        transaction, target_arc, stage_root, _backup = self._publication_transaction_paths(
            operation
        )
        base_sha = str(transaction["base_sha256"])
        if not stage_root.is_dir():
            if self._tree_fingerprint(target_arc) != base_sha:
                raise ManuscriptImportError(
                    "发布前目标篇章已变化",
                    code="IMPORT_PUBLISH_CONFLICT",
                )
            self._copy_arc_for_staging(target_arc, stage_root)
        expected_targets = {
            str(item["chapter_id"]): Path(str(item["target_path"])).resolve() for item in plan
        }
        for chapter_id, target in expected_targets.items():
            duplicates = [
                path for path in self._canonical_paths(chapter_id) if path.resolve() != target
            ]
            if duplicates:
                raise ManuscriptImportError(
                    f"章节 ID 已存在: {chapter_id}",
                    code="DUPLICATE_CHAPTER_ID",
                    details={
                        "chapter_ids": [chapter_id],
                        "paths": [str(path) for path in duplicates],
                    },
                )
        for item in plan:
            chapter_id = str(item["chapter_id"])
            staged = Path(str(item["staged_path"])).resolve()
            expected_staged = (stage_root / f"{chapter_id}.md").resolve()
            expected_target = (target_arc / f"{chapter_id}.md").resolve()
            if (
                staged != expected_staged
                or Path(str(item["target_path"])).resolve() != expected_target
            ):
                raise ManuscriptImportError(
                    "旧稿发布计划路径损坏",
                    code="IMPORT_PUBLISH_JOURNAL_CORRUPT",
                    recoverable=False,
                )
            expected_sha = str(item["sha256"])
            if staged.is_file():
                current_sha = self.fingerprint(staged.read_bytes())
                if current_sha != expected_sha and item.get("staged"):
                    raise ManuscriptImportError(
                        "旧稿发布暂存文件损坏",
                        code="IMPORT_STAGING_CORRUPT",
                        recoverable=False,
                        details={
                            "chapter_id": chapter_id,
                            "expected": expected_sha,
                            "current": current_sha,
                        },
                    )
            if not staged.is_file() or self.fingerprint(staged.read_bytes()) != expected_sha:
                rendered = next(
                    self._render_chapter(candidate)
                    for candidate in self._load_preview(operation)["chapters"]
                    if candidate["chapter_id"] == chapter_id
                )
                self._atomic_bytes(staged, rendered.encode("utf-8"))
            if fault_injector:
                fault_injector(f"publish:{chapter_id}")
            if not item.get("staged"):
                item["staged"] = True
                item["staged_at"] = self._now()
                operation["updated_at"] = self._now()
                self._write_operation(operation)
        final_sha = self._tree_fingerprint(stage_root)
        transaction["final_sha256"] = final_sha
        transaction["swap_status"] = "staged"
        operation["updated_at"] = self._now()
        self._write_operation(operation)

    def _copy_arc_for_staging(self, source: Path, target: Path) -> None:
        temporary = target.with_name(f".{target.name}.{uuid4().hex}.tmp")
        try:
            if source.is_dir():
                shutil.copytree(source, temporary)
            else:
                temporary.mkdir(parents=True, exist_ok=False)
            temporary.replace(target)
        finally:
            if temporary.is_dir():
                shutil.rmtree(temporary)

    def _swap_published_arc(self, operation: dict[str, Any]) -> None:
        transaction, target, staged, backup = self._publication_transaction_paths(operation)
        base_sha = str(transaction["base_sha256"])
        final_sha = str(transaction["final_sha256"])

        target_sha = self._tree_fingerprint(target)
        if target_sha == final_sha:
            transaction["swap_status"] = "installed"
            operation["updated_at"] = self._now()
            self._write_operation(operation)
            return
        if target_sha not in {base_sha, "sha256:missing"}:
            raise ManuscriptImportError(
                "发布目标篇章已变化",
                code="IMPORT_PUBLISH_CONFLICT",
                details={"expected": base_sha, "current": target_sha},
            )
        if target.exists():
            if backup.exists():
                raise ManuscriptImportError(
                    "旧稿发布备份与目标同时存在，无法安全换入",
                    code="IMPORT_PUBLISH_CONFLICT",
                )
            backup.parent.mkdir(parents=True, exist_ok=True)
            target.replace(backup)
            transaction["swap_status"] = "target_moved"
            operation["updated_at"] = self._now()
            self._write_operation(operation)
        elif backup.exists() and self._tree_fingerprint(backup) != base_sha:
            raise ManuscriptImportError(
                "旧稿发布备份校验失败",
                code="IMPORT_PUBLISH_JOURNAL_CORRUPT",
                recoverable=False,
            )
        if not staged.is_dir() or self._tree_fingerprint(staged) != final_sha:
            raise ManuscriptImportError(
                "旧稿发布暂存篇章校验失败",
                code="IMPORT_STAGING_CORRUPT",
                recoverable=False,
            )
        target.parent.mkdir(parents=True, exist_ok=True)
        staged.replace(target)
        if self._tree_fingerprint(target) != final_sha:
            raise ManuscriptImportError(
                "旧稿发布结果校验失败",
                code="IMPORT_PUBLISH_VERIFY_FAILED",
                recoverable=False,
            )
        transaction["swap_status"] = "installed"
        operation["updated_at"] = self._now()
        self._write_operation(operation)

    def _start_acceptance(
        self,
        operation: dict[str, Any],
        fault_injector: FaultInjector | None,
    ) -> None:
        publication_sha = str(operation.get("publication_sha256") or "")
        self._begin_stage(operation, "acceptance", publication_sha)
        acceptance = self._recover_acceptance(operation)
        if acceptance is None:
            from tools.manuscript_acceptance import (
                ManuscriptAcceptanceError,
                ManuscriptAcceptanceService,
            )

            service = ManuscriptAcceptanceService(self.project_root, self.novel_id)
            earliest = min(
                operation["published_chapters"],
                key=lambda item: self._chapter_number(str(item["chapter_id"])),
            )
            previous = ""
            for item in service.inspect().get("chapters") or []:
                if item.get("chapter_id") == earliest["chapter_id"]:
                    previous = str(
                        item.get("pending_revision") or item.get("accepted_revision") or ""
                    )
                    break
            try:
                acceptance = service.start_acceptance(
                    str(earliest["chapter_id"]),
                    source="import",
                    expected_previous_revision=previous,
                    source_run_id=str(operation["import_id"]),
                )
            except ManuscriptAcceptanceError as exc:
                raise ManuscriptImportError(
                    str(exc),
                    code=exc.code,
                    recoverable=exc.recoverable,
                    details=exc.details,
                ) from exc
        if fault_injector:
            fault_injector("acceptance")
        operation["acceptance_operation_id"] = str(acceptance["operation_id"])
        operation["acceptance_status"] = str(acceptance["status"])
        output_sha = self._json_fingerprint(acceptance)
        operation["updated_at"] = self._now()
        self._write_operation(operation)
        self._finish_stage(operation, "acceptance", output_sha256=output_sha)
        operation["status"] = "awaiting_reconciliation"
        operation["updated_at"] = self._now()
        self._write_operation(operation)

    def _recover_acceptance(self, operation: dict[str, Any]) -> dict[str, Any] | None:
        from tools.manuscript_acceptance import (
            ManuscriptAcceptanceError,
            ManuscriptAcceptanceService,
        )

        service = ManuscriptAcceptanceService(self.project_root, self.novel_id)
        recorded = str(operation.get("acceptance_operation_id") or "")
        candidates: list[str] = [recorded] if recorded else []
        if service.operations_dir.is_dir():
            candidates.extend(
                path.stem
                for path in sorted(service.operations_dir.glob("accept_*.json"), reverse=True)
                if path.stem != recorded
            )
        for operation_id in candidates:
            try:
                candidate = service.operation(operation_id)
            except ManuscriptAcceptanceError:
                continue
            if candidate.get("source") == "import" and candidate.get(
                "source_run_id"
            ) == operation.get("import_id"):
                return candidate
        return None

    def _observe_reconciliation(self, operation: dict[str, Any]) -> bool:
        from tools.manuscript_acceptance import (
            ManuscriptAcceptanceError,
            ManuscriptAcceptanceService,
        )

        acceptance_id = str(operation.get("acceptance_operation_id") or "")
        try:
            acceptance = ManuscriptAcceptanceService(self.project_root, self.novel_id).operation(
                acceptance_id
            )
        except ManuscriptAcceptanceError as exc:
            raise ManuscriptImportError(
                str(exc),
                code="IMPORT_ACCEPTANCE_MISSING",
                details={"acceptance_operation_id": acceptance_id},
            ) from exc
        acceptance_status = str(acceptance.get("status") or "")
        operation["acceptance_status"] = acceptance_status
        input_sha = self._json_fingerprint(acceptance)
        if acceptance_status != "completed":
            stage = operation["stages"]["reconcile"]
            if stage["status"] != "waiting" or stage.get("input_sha256") != input_sha:
                stage.update(
                    {
                        "status": "waiting",
                        "attempts": max(1, int(stage.get("attempts") or 0)),
                        "input_sha256": input_sha,
                        "output_sha256": "",
                        "started_at": str(stage.get("started_at") or self._now()),
                        "completed_at": "",
                        "error_code": "",
                        "error_message": "",
                    }
                )
                operation["updated_at"] = self._now()
            operation["status"] = "awaiting_reconciliation"
            self._write_operation(operation)
            return False
        self._begin_stage(operation, "reconcile", input_sha)
        self._finish_stage(operation, "reconcile", output_sha256=input_sha)
        return True

    def _synthesize(
        self,
        operation: dict[str, Any],
        fault_injector: FaultInjector | None,
    ) -> None:
        acceptance_id = str(operation["acceptance_operation_id"])
        synthesis_input = self._synthesis_input(operation)
        input_sha = self._json_fingerprint(synthesis_input)
        self._begin_stage(operation, "synthesis", input_sha)
        coverage = synthesis_input["fact_coverage"]
        if coverage["missing_chapters"] or coverage["stale_chapters"]:
            raise ManuscriptImportError(
                "全书综合所需的章节事实不完整",
                code="IMPORT_SYNTHESIS_FACTS_INCOMPLETE",
                details=coverage,
            )
        synthesis_path = self.operation_root(operation["import_id"]) / "synthesis.json"
        payload = {
            "schema_version": SYNTHESIS_SCHEMA_VERSION,
            "import_id": str(operation["import_id"]),
            "novel_id": self.novel_id,
            "source_sha256": str(operation["source"]["sha256"]),
            "preview_revision": str(operation["confirmed_preview_revision"]),
            "publication_sha256": str(operation["publication_sha256"]),
            "acceptance_operation_id": acceptance_id,
            "chapter_count": int(operation["chapter_count"]),
            "writing_units": int(operation["writing_units"]),
            "chapters": list(operation["published_chapters"]),
            "chapter_facts": synthesis_input["chapter_facts"],
            "runtime_revision": synthesis_input["runtime_revision"],
            "fact_coverage": coverage,
            "input_sha256": input_sha,
            "created_at": self._now(),
        }
        output_sha = self._json_fingerprint(payload)
        payload["sha256"] = output_sha
        self._atomic_json(synthesis_path, payload)
        if fault_injector:
            fault_injector("synthesis")
        operation["synthesis_path"] = str(synthesis_path)
        operation["synthesis_sha256"] = output_sha
        operation["updated_at"] = self._now()
        self._write_operation(operation)
        self._finish_stage(operation, "synthesis", output_sha256=output_sha)

    def _synthesis_input(self, operation: Mapping[str, Any]) -> dict[str, Any]:
        from tools.manuscript_acceptance import ManuscriptAcceptanceService
        from tools.runtime_state import RuntimeStateManager

        acceptance = ManuscriptAcceptanceService(self.project_root, self.novel_id)
        published = sorted(
            list(operation.get("published_chapters") or []),
            key=lambda item: self._chapter_number(str(item.get("chapter_id") or "")),
        )
        facts: list[dict[str, str]] = []
        missing: list[str] = []
        stale: list[str] = []
        for published_chapter in published:
            chapter_id = self._chapter_id(str(published_chapter.get("chapter_id") or ""))
            paths = self._canonical_paths(chapter_id)
            if len(paths) != 1:
                raise ManuscriptImportError(
                    f"全书综合发现重复章节 ID: {chapter_id}",
                    code="DUPLICATE_CHAPTER_ID",
                    details={
                        "chapter_ids": [chapter_id],
                        "paths": [str(path) for path in paths],
                    },
                )
            fact = self._read_json(acceptance.fact_path(chapter_id))
            if not isinstance(fact, dict):
                missing.append(chapter_id)
                continue
            current_revision = self.fingerprint(paths[0].read_bytes())
            source_revision = str(fact.get("source_revision") or "")
            if source_revision != current_revision:
                stale.append(chapter_id)
                continue
            facts.append(
                {
                    "chapter_id": chapter_id,
                    "title": str(fact.get("title") or published_chapter.get("title") or chapter_id),
                    "chapter_summary": str(fact.get("chapter_summary") or ""),
                    "observations": str(fact.get("observations") or ""),
                    "source_revision": source_revision,
                }
            )
        coverage = {
            "covered": len(facts),
            "total": len(published),
            "missing_chapters": missing,
            "stale_chapters": stale,
            "coverage_ratio": round(len(facts) / len(published), 4) if published else 1.0,
        }
        runtime = RuntimeStateManager(self.project_root, self.novel_id).load()
        return {
            "acceptance_operation_id": str(operation["acceptance_operation_id"]),
            "chapter_facts": facts,
            "runtime_revision": int(runtime.revision),
            "fact_coverage": coverage,
        }

    def _complete(self, operation: dict[str, Any]) -> None:
        synthesis_sha = str(operation["synthesis_sha256"])
        self._begin_stage(operation, "complete", synthesis_sha)
        self._finish_stage(operation, "complete", output_sha256=synthesis_sha)
        operation["status"] = "completed"
        operation["completed_at"] = self._now()
        operation["updated_at"] = operation["completed_at"]
        operation["last_error"] = None
        self._write_operation(operation)

    def _preview_payload(
        self,
        operation: Mapping[str, Any],
        chapters: list[dict[str, Any]],
    ) -> dict[str, Any]:
        revision = self._json_fingerprint(
            {
                "arc_id": str(operation["arc_id"]),
                "source_sha256": str(operation["source"]["sha256"]),
                "chapters": chapters,
            }
        )
        return {
            "schema_version": PREVIEW_SCHEMA_VERSION,
            "import_id": str(operation["import_id"]),
            "arc_id": str(operation["arc_id"]),
            "source_sha256": str(operation["source"]["sha256"]),
            "revision": revision,
            "chapter_count": len(chapters),
            "writing_units": sum(int(item["writing_units"]) for item in chapters),
            "chapters": chapters,
            "updated_at": self._now(),
        }

    def _load_preview(self, operation: Mapping[str, Any]) -> dict[str, Any]:
        expected_path = self.operation_root(str(operation.get("import_id") or "")) / "preview.json"
        if Path(str(operation.get("preview_path") or "")).resolve() != expected_path.resolve():
            raise ManuscriptImportError(
                "旧稿切分预览路径损坏",
                code="IMPORT_PREVIEW_CORRUPT",
                recoverable=False,
            )
        payload = self._read_json(expected_path)
        if (
            not isinstance(payload, dict)
            or payload.get("schema_version") != PREVIEW_SCHEMA_VERSION
            or payload.get("import_id") != operation.get("import_id")
        ):
            raise ManuscriptImportError(
                "旧稿切分预览不存在或损坏",
                code="IMPORT_PREVIEW_CORRUPT",
                recoverable=False,
            )
        chapters = payload.get("chapters")
        normalized = self._normalize_chapters(chapters if isinstance(chapters, list) else [])
        expected = self._preview_payload(operation, normalized)["revision"]
        if payload.get("revision") != expected or operation.get("preview_revision") != expected:
            raise ManuscriptImportError(
                "旧稿切分预览校验失败",
                code="IMPORT_PREVIEW_CORRUPT",
                recoverable=False,
            )
        return payload

    def _normalize_chapters(self, chapters: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
        values = list(chapters)
        if not values:
            raise ManuscriptImportError("旧稿切分结果不能为空", code="EMPTY_IMPORT_PREVIEW")
        if len(values) > MAX_CHAPTERS:
            raise ManuscriptImportError(
                "旧稿切分章节数量过多",
                code="IMPORT_CHAPTER_LIMIT_EXCEEDED",
                recoverable=False,
            )
        seen: set[str] = set()
        duplicates: set[str] = set()
        normalized: list[dict[str, Any]] = []
        for index, item in enumerate(values):
            if not isinstance(item, Mapping):
                raise ManuscriptImportError(
                    "旧稿章节预览条目必须是对象", code="INVALID_IMPORT_PREVIEW"
                )
            chapter_id = self._chapter_id(str(item.get("chapter_id") or ""))
            if chapter_id in seen:
                duplicates.add(chapter_id)
            seen.add(chapter_id)
            title = re.sub(r"\s+", " ", str(item.get("title") or "").strip().lstrip("#"))
            title = title or chapter_id
            content = str(item.get("content") or "").strip()
            if not content:
                raise ManuscriptImportError(
                    f"{chapter_id} 正文不能为空", code="EMPTY_IMPORT_CHAPTER"
                )
            rendered = self._render_chapter(
                {"chapter_id": chapter_id, "title": title, "content": content}
            )
            normalized.append(
                {
                    "order": index,
                    "chapter_id": chapter_id,
                    "title": title,
                    "content": content,
                    "writing_units": count_writing_units(rendered),
                    "sha256": self.fingerprint(rendered.encode("utf-8")),
                }
            )
        if duplicates:
            raise ManuscriptImportError(
                "旧稿切分包含重复章节 ID",
                code="DUPLICATE_CHAPTER_ID",
                details={"chapter_ids": sorted(duplicates, key=self._chapter_number)},
            )
        return normalized

    def _assert_no_duplicate_targets(
        self,
        operation: Mapping[str, Any],
        chapters: Iterable[Mapping[str, Any]],
    ) -> None:
        del operation
        conflicts: dict[str, list[str]] = {}
        for item in chapters:
            chapter_id = str(item["chapter_id"])
            paths = self._canonical_paths(chapter_id)
            if paths:
                conflicts[chapter_id] = [str(path) for path in paths]
        if conflicts:
            chapter_ids = sorted(conflicts, key=self._chapter_number)
            raise ManuscriptImportError(
                "目标章节 ID 已存在: " + ", ".join(chapter_ids),
                code="DUPLICATE_CHAPTER_ID",
                details={
                    "chapter_ids": chapter_ids,
                    "paths": [path for cid in chapter_ids for path in conflicts[cid]],
                },
            )

    def _canonical_paths(self, chapter_id: str) -> list[Path]:
        manuscript_root = self.novel_root / "data" / "manuscript"
        if not manuscript_root.is_dir():
            return []
        return sorted(
            path.resolve()
            for path in manuscript_root.rglob(f"{chapter_id}.md")
            if path.is_file()
            and path.name == f"{chapter_id}.md"
            and not any(part.startswith(".") for part in path.relative_to(manuscript_root).parts)
        )

    def _target_arc_path(self, arc_id: str) -> Path:
        root = (self.novel_root / "data" / "manuscript").resolve()
        target = root / self._arc_id(arc_id)
        if target.is_symlink():
            raise ManuscriptImportError(
                "旧稿发布目标不能是符号链接",
                code="IMPORT_PATH_OUT_OF_BOUNDS",
                recoverable=False,
            )
        resolved = target.resolve()
        try:
            resolved.relative_to(root)
        except ValueError as exc:
            raise ManuscriptImportError(
                "旧稿发布路径越界",
                code="IMPORT_PATH_OUT_OF_BOUNDS",
                recoverable=False,
            ) from exc
        return resolved

    def _target_path(self, arc_id: str, chapter_id: str) -> Path:
        return self._target_arc_path(arc_id) / f"{self._chapter_id(chapter_id)}.md"

    def _bind_operation_paths(self, operation: dict[str, Any]) -> None:
        """Bind archived journals to this service's current workspace root.

        Import journals keep paths for diagnostics, but those paths are never
        capabilities.  A restored archive may contain absolute paths from its
        source workspace, so all internal and canonical paths are derived again
        from validated identifiers before the journal is used.
        """
        import_id = self._import_id(str(operation.get("import_id") or ""))
        arc_id = self._arc_id(str(operation.get("arc_id") or ""))
        operation_root = self.operation_root(import_id)
        source = operation.get("source")
        if not isinstance(source, dict):
            raise ManuscriptImportError(
                "旧稿导入源记录损坏",
                code="IMPORT_OPERATION_NOT_FOUND",
                recoverable=False,
            )
        suffix = str(source.get("suffix") or "").lower()
        if suffix not in SUPPORTED_SUFFIXES:
            raise ManuscriptImportError(
                "旧稿导入源记录损坏",
                code="IMPORT_OPERATION_NOT_FOUND",
                recoverable=False,
            )
        snapshot = operation_root / f"source{suffix}"
        source["snapshot_path"] = str(snapshot)
        source["snapshot_relative_path"] = snapshot.relative_to(self.novel_root).as_posix()
        preview = operation_root / "preview.json"
        operation["preview_path"] = str(preview)
        operation["preview_relative_path"] = preview.relative_to(self.novel_root).as_posix()

        synthesis = operation_root / "synthesis.json"
        if operation.get("synthesis_path") or synthesis.is_file():
            operation["synthesis_path"] = str(synthesis)

        target_arc = self._target_arc_path(arc_id)
        transaction = operation.get("publication_transaction")
        if isinstance(transaction, dict) and transaction:
            transaction["target_arc_path"] = str(target_arc)
            transaction["stage_path"] = str(operation_root / "publication")
            transaction["backup_path"] = str(operation_root / "replaced_arc")

        plan = operation.get("publish_plan")
        if isinstance(plan, list):
            for item in plan:
                if not isinstance(item, dict):
                    raise ManuscriptImportError(
                        "旧稿发布计划损坏",
                        code="IMPORT_PUBLISH_JOURNAL_CORRUPT",
                        recoverable=False,
                    )
                chapter_id = self._chapter_id(str(item.get("chapter_id") or ""))
                target = self._target_path(arc_id, chapter_id)
                item["staged_path"] = str(operation_root / "publication" / f"{chapter_id}.md")
                item["target_path"] = str(target)
                item["target_relative_path"] = target.relative_to(self.novel_root).as_posix()

        published = operation.get("published_chapters")
        if isinstance(published, list):
            for item in published:
                if not isinstance(item, dict):
                    raise ManuscriptImportError(
                        "旧稿已发布章节记录损坏",
                        code="IMPORT_PUBLISH_JOURNAL_CORRUPT",
                        recoverable=False,
                    )
                chapter_id = self._chapter_id(str(item.get("chapter_id") or ""))
                target = self._target_path(arc_id, chapter_id)
                item["path"] = str(target)
                item["relative_path"] = target.relative_to(self.novel_root).as_posix()

    def _tree_fingerprint(self, path: Path) -> str:
        candidate = Path(path)
        if not candidate.exists():
            return "sha256:missing"
        if candidate.is_symlink() or not candidate.is_dir():
            raise ManuscriptImportError(
                "旧稿发布篇章目录无效",
                code="IMPORT_PUBLISH_JOURNAL_CORRUPT",
                recoverable=False,
            )
        entries: list[dict[str, Any]] = []
        for item in sorted(candidate.rglob("*")):
            if item.is_symlink():
                raise ManuscriptImportError(
                    "旧稿发布篇章不能包含符号链接",
                    code="IMPORT_PUBLISH_JOURNAL_CORRUPT",
                    recoverable=False,
                )
            if item.is_file():
                content = item.read_bytes()
                entries.append(
                    {
                        "path": item.relative_to(candidate).as_posix(),
                        "bytes": len(content),
                        "sha256": self.fingerprint(content),
                    }
                )
        return self._json_fingerprint(entries)

    def _has_committed_canonical(self, operation: Mapping[str, Any]) -> bool:
        transaction = operation.get("publication_transaction")
        if not isinstance(transaction, Mapping):
            return bool(operation.get("publication_sha256"))
        final_sha = str(transaction.get("final_sha256") or "")
        target_raw = str(transaction.get("target_arc_path") or "")
        if not final_sha or not target_raw:
            return bool(operation.get("publication_sha256"))
        _transaction, target, _stage, _backup = self._publication_transaction_paths(operation)
        return self._tree_fingerprint(target) == final_sha

    def _remove_staging_directory(self, operation: Mapping[str, Any]) -> None:
        transaction = operation.get("publication_transaction")
        if not isinstance(transaction, Mapping) or not transaction:
            return
        _transaction, _target, stage, _backup = self._publication_transaction_paths(operation)
        if stage.is_dir():
            shutil.rmtree(stage)

    def _rollback_uncommitted_publication(self, operation: Mapping[str, Any]) -> None:
        transaction = operation.get("publication_transaction")
        if not isinstance(transaction, Mapping) or not transaction:
            return
        _transaction, target, _stage, expected_backup = self._publication_transaction_paths(
            operation
        )
        base_sha = str(transaction.get("base_sha256") or "")
        current_sha = self._tree_fingerprint(target)
        if current_sha == base_sha:
            return
        if current_sha == "sha256:missing" and expected_backup.is_dir():
            if self._tree_fingerprint(expected_backup) != base_sha:
                raise ManuscriptImportError(
                    "旧稿发布备份校验失败",
                    code="IMPORT_PUBLISH_JOURNAL_CORRUPT",
                    recoverable=False,
                )
            expected_backup.replace(target)
            return
        if current_sha == "sha256:missing" and base_sha == "sha256:missing":
            return
        raise ManuscriptImportError(
            "旧稿发布目录已有提交或外部变化，不能丢弃",
            code="IMPORT_DISCARD_FORBIDDEN",
            recoverable=False,
        )

    def _publication_transaction_paths(
        self, operation: Mapping[str, Any]
    ) -> tuple[Mapping[str, Any], Path, Path, Path]:
        transaction = operation.get("publication_transaction")
        if not isinstance(transaction, Mapping) or not transaction:
            raise ManuscriptImportError(
                "旧稿发布事务缺失",
                code="IMPORT_PUBLISH_JOURNAL_CORRUPT",
                recoverable=False,
            )
        operation_root = self.operation_root(str(operation.get("import_id") or ""))
        target = self._validated_transaction_path(
            str(transaction.get("target_arc_path") or ""),
            parent=(self.novel_root / "data" / "manuscript").resolve(),
            expected_name=self._arc_id(str(operation.get("arc_id") or "")),
        )
        stage = self._validated_transaction_path(
            str(transaction.get("stage_path") or ""),
            parent=operation_root.resolve(),
            expected_name="publication",
        )
        backup = self._validated_transaction_path(
            str(transaction.get("backup_path") or ""),
            parent=operation_root.resolve(),
            expected_name="replaced_arc",
        )
        return transaction, target, stage, backup

    @staticmethod
    def _validated_transaction_path(
        raw: str,
        *,
        parent: Path,
        expected_name: str | None,
    ) -> Path:
        candidate = Path(raw)
        if not candidate.is_absolute():
            raise ManuscriptImportError(
                "旧稿发布事务路径无效",
                code="IMPORT_PUBLISH_JOURNAL_CORRUPT",
                recoverable=False,
            )
        resolved_parent = parent.resolve()
        resolved = candidate.resolve()
        if resolved.parent != resolved_parent or (
            expected_name is not None and resolved.name != expected_name
        ):
            raise ManuscriptImportError(
                "旧稿发布事务路径越界",
                code="IMPORT_PUBLISH_JOURNAL_CORRUPT",
                recoverable=False,
            )
        return resolved

    def _require_preview_revision(self, preview: Mapping[str, Any], expected: str) -> None:
        current = str(preview.get("revision") or "")
        if not expected or str(expected) != current:
            raise ManuscriptImportError(
                "旧稿切分预览已变化，请重新读取",
                code="STALE_PREVIEW_REVISION",
                details={"expected": str(expected or ""), "current": current},
            )

    def _begin_stage(self, operation: dict[str, Any], stage_name: str, input_sha256: str) -> None:
        stage = operation["stages"][stage_name]
        if stage["status"] == "completed":
            return
        stage.update(
            {
                "status": "running",
                "attempts": int(stage.get("attempts") or 0) + 1,
                "input_sha256": str(input_sha256),
                "output_sha256": "",
                "started_at": self._now(),
                "completed_at": "",
                "error_code": "",
                "error_message": "",
            }
        )
        operation["status"] = "running"
        operation["updated_at"] = self._now()
        operation["last_error"] = None
        self._write_operation(operation)

    def _finish_stage(
        self,
        operation: dict[str, Any],
        stage_name: str,
        *,
        output_sha256: str,
    ) -> None:
        stage = operation["stages"][stage_name]
        stage.update(
            {
                "status": "completed",
                "output_sha256": str(output_sha256),
                "completed_at": self._now(),
                "error_code": "",
                "error_message": "",
            }
        )
        operation["updated_at"] = self._now()
        self._write_operation(operation)

    def _set_waiting(self, operation: dict[str, Any], status: str) -> None:
        if operation.get("status") == status:
            return
        operation["status"] = status
        operation["updated_at"] = self._now()
        self._write_operation(operation)

    def _record_failure(self, operation: dict[str, Any], exc: BaseException) -> None:
        active = next(
            (name for name in STAGE_NAMES if operation["stages"][name]["status"] == "running"),
            "",
        )
        code = str(getattr(exc, "code", type(exc).__name__))
        if active:
            operation["stages"][active].update(
                {
                    "status": "failed",
                    "completed_at": self._now(),
                    "error_code": code,
                    "error_message": str(exc)[:1000],
                }
            )
        operation["status"] = "failed"
        operation["updated_at"] = self._now()
        operation["last_error"] = {
            "code": code,
            "message": str(exc)[:1000],
            "stage": active,
            "recoverable": bool(getattr(exc, "recoverable", True)),
        }
        self._write_operation(operation)

    def _operation_summary(self, operation: Mapping[str, Any]) -> dict[str, Any]:
        raw_stages = operation.get("stages")
        stages: dict[str, dict[str, Any]] = {}
        if isinstance(raw_stages, Mapping):
            for name in STAGE_NAMES:
                raw = raw_stages.get(name)
                stage = raw if isinstance(raw, Mapping) else {}
                stages[name] = {
                    "status": str(stage.get("status") or "pending"),
                    "attempts": int(stage.get("attempts") or 0),
                    "input_sha256": str(stage.get("input_sha256") or ""),
                    "output_sha256": str(stage.get("output_sha256") or ""),
                    "started_at": str(stage.get("started_at") or ""),
                    "completed_at": str(stage.get("completed_at") or ""),
                    "error_code": str(stage.get("error_code") or ""),
                }
        completed_stages = sum(item["status"] == "completed" for item in stages.values())
        current_stage = next(
            (
                name
                for name in STAGE_NAMES
                if stages.get(name, {}).get("status") in {"running", "failed", "waiting"}
            ),
            next(
                (name for name in STAGE_NAMES if stages.get(name, {}).get("status") != "completed"),
                "complete",
            ),
        )
        raw_error = operation.get("last_error")
        error = raw_error if isinstance(raw_error, Mapping) else {}
        transaction = operation.get("publication_transaction")
        publication = transaction if isinstance(transaction, Mapping) else {}
        source = operation.get("source")
        source_summary = source if isinstance(source, Mapping) else {}
        return {
            "schema_version": SCHEMA_VERSION,
            "import_id": str(operation.get("import_id") or ""),
            "novel_id": self.novel_id,
            "status": str(operation.get("status") or "unknown"),
            "arc_id": str(operation.get("arc_id") or ""),
            "source": {
                "filename": str(source_summary.get("filename") or ""),
                "suffix": str(source_summary.get("suffix") or ""),
                "bytes": int(source_summary.get("bytes") or 0),
                "sha256": str(source_summary.get("sha256") or ""),
            },
            "preview_revision": str(operation.get("preview_revision") or ""),
            "confirmed_preview_revision": str(operation.get("confirmed_preview_revision") or ""),
            "chapter_count": int(operation.get("chapter_count") or 0),
            "writing_units": int(operation.get("writing_units") or 0),
            "progress": {
                "current_stage": current_stage,
                "completed_stages": completed_stages,
                "total_stages": len(STAGE_NAMES),
                "published_chapters": len(operation.get("published_chapters") or []),
                "total_chapters": int(operation.get("chapter_count") or 0),
            },
            "stages": stages,
            "publication": {
                "sha256": str(operation.get("publication_sha256") or ""),
                "swap_status": str(publication.get("swap_status") or ""),
                "committed": self._has_committed_canonical(operation),
            },
            "acceptance": {
                "operation_id": str(operation.get("acceptance_operation_id") or ""),
                "status": str(operation.get("acceptance_status") or ""),
            },
            "synthesis_sha256": str(operation.get("synthesis_sha256") or ""),
            "failure": (
                {
                    "code": str(error.get("code") or ""),
                    "stage": str(error.get("stage") or ""),
                    "recoverable": bool(error.get("recoverable", True)),
                }
                if error
                else None
            ),
            "created_at": str(operation.get("created_at") or ""),
            "updated_at": str(operation.get("updated_at") or ""),
            "completed_at": str(operation.get("completed_at") or ""),
            "discarded_at": str(operation.get("discarded_at") or ""),
        }

    @staticmethod
    def _empty_stage() -> dict[str, Any]:
        return {
            "status": "pending",
            "attempts": 0,
            "input_sha256": "",
            "output_sha256": "",
            "started_at": "",
            "completed_at": "",
            "error_code": "",
            "error_message": "",
        }

    def _write_operation(self, operation: dict[str, Any]) -> None:
        self._atomic_json(self.operation_path(str(operation["import_id"])), operation)

    @staticmethod
    def _publication_sha(plan: Iterable[Mapping[str, Any]]) -> str:
        return ManuscriptImportService._json_fingerprint(
            [
                {
                    "chapter_id": str(item["chapter_id"]),
                    "path": str(item["target_relative_path"]),
                    "sha256": str(item["sha256"]),
                }
                for item in plan
            ]
        )

    @staticmethod
    def _render_chapter(chapter: Mapping[str, Any]) -> str:
        return f"# {str(chapter['title']).strip()}\n\n{str(chapter['content']).strip()}\n"

    @staticmethod
    def fingerprint(content: bytes | str) -> str:
        raw = content.encode("utf-8") if isinstance(content, str) else content
        return "sha256:" + hashlib.sha256(raw).hexdigest()

    @staticmethod
    def _json_fingerprint(payload: Any) -> str:
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return ManuscriptImportService.fingerprint(encoded)

    def _start_number(self, value: int | None) -> int:
        if value is None:
            manuscript_root = self.novel_root / "data" / "manuscript"
            numbers = (
                [
                    self._chapter_number(path.stem)
                    for path in manuscript_root.rglob("ch_*.md")
                    if path.is_file() and re.fullmatch(r"ch_\d+", path.stem)
                ]
                if manuscript_root.is_dir()
                else []
            )
            return max(numbers, default=0) + 1
        if isinstance(value, bool):
            raise ManuscriptImportError("起始章节号必须是整数", code="INVALID_START_NUMBER")
        try:
            parsed = int(value)
        except (TypeError, ValueError) as exc:
            raise ManuscriptImportError(
                "起始章节号必须是整数", code="INVALID_START_NUMBER"
            ) from exc
        if parsed < 1:
            raise ManuscriptImportError("起始章节号必须大于 0", code="INVALID_START_NUMBER")
        return parsed

    @staticmethod
    def _chapter_id(value: str) -> str:
        clean = str(value or "").strip()
        if not re.fullmatch(r"ch_\d+", clean):
            raise ManuscriptImportError("章节 ID 必须形如 ch_001", code="INVALID_CHAPTER_ID")
        return clean

    @staticmethod
    def _chapter_number(value: str) -> int:
        match = re.fullmatch(r"ch_(\d+)", str(value or ""))
        return int(match.group(1)) if match else 0

    @staticmethod
    def _arc_id(value: str) -> str:
        clean = str(value or "").strip()
        if not re.fullmatch(r"arc_\d+", clean):
            raise ManuscriptImportError("篇 ID 必须形如 arc_001", code="INVALID_ARC_ID")
        return clean

    @staticmethod
    def _import_id(value: str) -> str:
        clean = str(value or "").strip()
        if not re.fullmatch(r"import_\d{14}_[a-f0-9]{12}", clean):
            raise ManuscriptImportError(
                "旧稿导入操作 ID 无效",
                code="INVALID_IMPORT_ID",
                recoverable=False,
            )
        return clean

    @staticmethod
    def _read_json(path: Path) -> dict[str, Any] | None:
        if not path.is_file():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        return payload if isinstance(payload, dict) else None

    @staticmethod
    def _atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
        ManuscriptImportService._atomic_bytes(
            path,
            (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8"),
        )

    @staticmethod
    def _atomic_bytes(path: Path, content: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="wb",
                dir=path.parent,
                prefix=f".{path.name}.",
                suffix=".tmp",
                delete=False,
            ) as handle:
                temporary = Path(handle.name)
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            temporary.replace(path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()


__all__ = [
    "ManuscriptImportError",
    "ManuscriptImportService",
    "SCHEMA_VERSION",
    "STAGE_NAMES",
]
