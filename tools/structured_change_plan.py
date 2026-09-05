"""Immutable preview tokens for revision-gated structured domain changes."""

from __future__ import annotations

import difflib
import hashlib
import json
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from tools.mutation_summary import MISSING_VALUE, build_mutation_summary
from tools.project_lock import ProjectBusyError, ProjectWriteLock
from tools.revision_service import RevisionService

SCHEMA_VERSION = 1
TOKEN_PATTERN = re.compile(r"[a-f0-9]{24}")
MAX_CONTENT_BYTES = 4 * 1024 * 1024
ALLOWED_KINDS = {"outline", "asset", "focus", "foreshadowing", "writing_targets"}


class StructuredChangePlanError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        code: str = "STRUCTURED_CHANGE_FAILED",
        recoverable: bool = False,
    ):
        super().__init__(message)
        self.code = code
        self.recoverable = recoverable


class StructuredChangePlanStore:
    """Store and atomically apply exact canonical results produced by domain previews."""

    def __init__(self, project_root: Path, novel_id: str):
        self.project_root = Path(project_root).resolve()
        self.novel_id = str(novel_id)
        self.novel_root = self.project_root / "data" / "novels" / self.novel_id
        self.root = self.novel_root / "data" / "workflows" / "structured_change_plans"

    def save_preview(
        self,
        prepared: dict[str, Any],
        *,
        purpose: str = "preview",
    ) -> tuple[str, dict[str, Any]]:
        record = self._record(prepared, purpose=purpose)
        token = self._save_record(record)
        return token, record

    def load(self, token: str) -> tuple[dict[str, Any], Path]:
        clean_token = str(token or "").strip()
        if not TOKEN_PATTERN.fullmatch(clean_token):
            raise self._invalid("结构化预览凭据格式无效，请重新预览。")
        path = (self.root / f"{clean_token}.json").resolve()
        root = self.root.resolve()
        if root not in path.parents or not path.is_file() or path.is_symlink():
            raise self._invalid("结构化预览凭据不存在或已使用，请重新预览。")
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise self._invalid("结构化预览凭据损坏，请重新预览。") from exc
        record = self._validate_record(raw)
        if self._token(record) != clean_token:
            raise self._invalid("结构化预览凭据校验失败，请重新预览。")
        return record, path

    def reject(self, token: str) -> dict[str, Any]:
        try:
            with ProjectWriteLock(
                self.project_root,
                self.novel_id,
                operation="structured_change_reject",
            ):
                record, path = self.load(token)
                path.unlink(missing_ok=True)
        except ProjectBusyError as exc:
            raise StructuredChangePlanError(
                str(exc), code="PROJECT_BUSY", recoverable=True
            ) from exc
        return {
            "ok": True,
            "applied": False,
            "changed": record["source_revision"] != record["result_revision"],
            "status": "rejected",
            "preview_token": str(token),
            "change_kind": record["change_kind"],
        }

    def apply(self, token: str, *, action: str) -> tuple[dict[str, Any], str]:
        expected_purpose = "undo" if action == "undo" else "preview"
        try:
            with ProjectWriteLock(
                self.project_root,
                self.novel_id,
                operation=f"structured_change_{action}",
            ):
                record, record_path = self.load(token)
                if record["purpose"] != expected_purpose:
                    raise self._invalid(
                        "预览凭据用途不匹配；普通预览使用 apply，撤销凭据使用 undo。"
                    )
                target = self._target(record)
                try:
                    current = target.read_text(encoding="utf-8")
                except OSError as exc:
                    raise StructuredChangePlanError(
                        "结构化变更目标无法读取，请重新预览。",
                        code="STRUCTURED_REVISION_CONFLICT",
                        recoverable=True,
                    ) from exc
                current_revision = RevisionService.fingerprint(current)
                if current_revision != record["source_revision"]:
                    raise StructuredChangePlanError(
                        "目标内容已变化，请检查最新内容并重试预览。",
                        code="STRUCTURED_REVISION_CONFLICT",
                        recoverable=True,
                    )

                undo_record = self._record(
                    {
                        **record,
                        "source_content": record["result_content"],
                        "result_content": record["source_content"],
                        "source_revision": record["result_revision"],
                        "result_revision": record["source_revision"],
                        "summary_before": record.get("summary_after"),
                        "summary_after": record.get("summary_before"),
                        "summary_before_missing": record.get("summary_after_missing", False),
                        "summary_after_missing": record.get("summary_before_missing", False),
                        "change": {},
                        "metadata": {"undo_of": str(token)},
                    },
                    purpose="undo",
                )
                undo_token = self._save_record(undo_record)
                try:
                    self._atomic_write(target, str(record["result_content"]))
                    actual = target.read_text(encoding="utf-8")
                    actual_revision = RevisionService.fingerprint(actual)
                    if actual_revision != record["result_revision"]:
                        raise StructuredChangePlanError(
                            "结构化变更写入结果与确认预览不一致。",
                            code="STRUCTURED_RESULT_MISMATCH",
                        )
                except Exception:
                    (self.root / f"{undo_token}.json").unlink(missing_ok=True)
                    raise
                record_path.unlink(missing_ok=True)
        except ProjectBusyError as exc:
            raise StructuredChangePlanError(
                str(exc), code="PROJECT_BUSY", recoverable=True
            ) from exc
        return record, undo_token

    def response(
        self,
        record: dict[str, Any],
        *,
        status: str,
        applied: bool,
        token: str = "",
        undo_token: str = "",
    ) -> dict[str, Any]:
        execution_status = "committed" if applied else "proposed"
        operation_suffix = "undo" if status == "undone" else "apply" if applied else "plan"
        before = (
            MISSING_VALUE
            if record.get("summary_before_missing")
            else record.get("summary_before")
        )
        after = (
            MISSING_VALUE
            if record.get("summary_after_missing")
            else record.get("summary_after")
        )
        response = {
            "ok": True,
            "applied": applied,
            "changed": record["source_revision"] != record["result_revision"],
            "status": status,
            "change_kind": record["change_kind"],
            "path": record["target_path"],
            "source_revision": record["source_revision"],
            "result_revision": record["result_revision"],
            "diff": self._diff(record),
            "metadata": dict(record.get("metadata") or {}),
            "mutation_summary": build_mutation_summary(
                operation=f"{record['change_kind']}.change_{operation_suffix}",
                entity_kind=str(record["entity_kind"]),
                entity_id=str(record["entity_id"]),
                path=str(record["target_path"]),
                before=before,
                after=after,
                source_revision=str(record["source_revision"]),
                result_revision=str(record["result_revision"]),
                field_prefix=str(record.get("field_prefix") or ""),
                flatten=bool(record.get("flatten", True)),
                execution_status=execution_status,
            ),
        }
        if token:
            response["preview_token"] = token
        if undo_token:
            response["undo_preview_token"] = undo_token
        return response

    def _record(self, prepared: dict[str, Any], *, purpose: str) -> dict[str, Any]:
        source_content = str(prepared.get("source_content") or "")
        result_content = str(prepared.get("result_content") or "")
        largest_content = max(
            len(source_content.encode("utf-8")),
            len(result_content.encode("utf-8")),
        )
        if largest_content > MAX_CONTENT_BYTES:
            raise StructuredChangePlanError(
                "结构化变更目标超过 4 MB，无法建立可撤销预览。",
                code="STRUCTURED_CHANGE_TOO_LARGE",
            )
        change_kind = str(prepared.get("change_kind") or "").strip()
        if change_kind not in ALLOWED_KINDS:
            raise StructuredChangePlanError(
                "不支持的结构化变更类型。", code="INVALID_STRUCTURED_CHANGE_KIND"
            )
        change = prepared.get("change")
        if not isinstance(change, dict):
            change = {}
        record = {
            "schema_version": SCHEMA_VERSION,
            "novel_id": self.novel_id,
            "nonce": uuid4().hex,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "purpose": purpose,
            "change_kind": change_kind,
            "change": change,
            "target_scope": str(prepared.get("target_scope") or "novel"),
            "target_path": str(prepared.get("target_path") or ""),
            "source_content": source_content,
            "result_content": result_content,
            "source_revision": RevisionService.fingerprint(source_content),
            "result_revision": RevisionService.fingerprint(result_content),
            "entity_kind": str(prepared.get("entity_kind") or change_kind),
            "entity_id": str(prepared.get("entity_id") or change_kind),
            "summary_before": prepared.get("summary_before"),
            "summary_after": prepared.get("summary_after"),
            "summary_before_missing": bool(prepared.get("summary_before_missing")),
            "summary_after_missing": bool(prepared.get("summary_after_missing")),
            "field_prefix": str(prepared.get("field_prefix") or ""),
            "flatten": bool(prepared.get("flatten", True)),
            "metadata": (
                dict(prepared.get("metadata") or {})
                if isinstance(prepared.get("metadata"), dict)
                else {}
            ),
        }
        try:
            json.dumps(record, ensure_ascii=False, sort_keys=True)
        except (TypeError, ValueError) as exc:
            raise StructuredChangePlanError(
                "结构化变更包含无法保存的数据。", code="INVALID_STRUCTURED_CHANGE"
            ) from exc
        self._validate_record(record)
        return record

    def _save_record(self, record: dict[str, Any]) -> str:
        token = self._token(record)
        self.root.mkdir(parents=True, exist_ok=True)
        target = self.root / f"{token}.json"
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=self.root,
            prefix=f".{token}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            json.dump(record, handle, ensure_ascii=False, sort_keys=True, indent=2)
            handle.write("\n")
            temporary = Path(handle.name)
        os.replace(temporary, target)
        return token

    def _validate_record(self, raw: Any) -> dict[str, Any]:
        if not isinstance(raw, dict):
            raise self._invalid("结构化预览凭据损坏，请重新预览。")
        required_strings = (
            "novel_id",
            "nonce",
            "created_at",
            "purpose",
            "change_kind",
            "target_scope",
            "target_path",
            "source_content",
            "result_content",
            "source_revision",
            "result_revision",
            "entity_kind",
            "entity_id",
            "field_prefix",
        )
        if (
            raw.get("schema_version") != SCHEMA_VERSION
            or raw.get("novel_id") != self.novel_id
            or any(not isinstance(raw.get(key), str) for key in required_strings)
            or raw.get("purpose") not in {"preview", "undo"}
            or raw.get("change_kind") not in ALLOWED_KINDS
            or raw.get("target_scope") not in {"novel", "project"}
            or not isinstance(raw.get("change"), dict)
            or not isinstance(raw.get("metadata"), dict)
            or not isinstance(raw.get("flatten"), bool)
            or not isinstance(raw.get("summary_before_missing"), bool)
            or not isinstance(raw.get("summary_after_missing"), bool)
            or RevisionService.fingerprint(str(raw.get("source_content")))
            != raw.get("source_revision")
            or RevisionService.fingerprint(str(raw.get("result_content")))
            != raw.get("result_revision")
        ):
            raise self._invalid("结构化预览凭据与当前作品不匹配，请重新预览。")
        self._target(raw)
        return dict(raw)

    def _target(self, record: dict[str, Any]) -> Path:
        relative = Path(str(record.get("target_path") or ""))
        if relative.is_absolute() or ".." in relative.parts:
            raise self._invalid("结构化预览目标路径无效，请重新预览。")
        kind = str(record.get("change_kind") or "")
        scope = str(record.get("target_scope") or "")
        expected_exact = {
            "outline": ("novel", "src/outline.md"),
            "focus": ("novel", "src/story/current_focus.md"),
            "foreshadowing": ("novel", "data/foreshadowing/dag.yaml"),
            "writing_targets": ("project", "novel_config.yaml"),
        }
        if kind in expected_exact and (scope, relative.as_posix()) != expected_exact[kind]:
            raise self._invalid("结构化预览目标与变更类型不匹配，请重新预览。")
        base = self.novel_root if scope == "novel" else self.project_root
        target = (base / relative).resolve()
        if base.resolve() not in target.parents or target.is_symlink():
            raise self._invalid("结构化预览目标路径无效，请重新预览。")
        if kind == "asset":
            allowed = (
                self.novel_root / "src" / "characters",
                self.novel_root / "src" / "world" / "entities",
                self.novel_root / "src" / "progression",
            )
            if scope != "novel" or not any(root.resolve() in target.parents for root in allowed):
                raise self._invalid("结构化资产预览目标无效，请重新预览。")
        return target

    @staticmethod
    def _token(record: dict[str, Any]) -> str:
        serialized = json.dumps(
            record,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()[:24]

    @staticmethod
    def _atomic_write(path: Path, content: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                "w",
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
            os.replace(temporary, path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    @staticmethod
    def _diff(record: dict[str, Any]) -> str:
        path = str(record.get("target_path") or "target")
        return "".join(
            difflib.unified_diff(
                str(record.get("source_content") or "").splitlines(keepends=True),
                str(record.get("result_content") or "").splitlines(keepends=True),
                fromfile=f"a/{path}",
                tofile=f"b/{path}",
            )
        )

    @staticmethod
    def _invalid(message: str) -> StructuredChangePlanError:
        return StructuredChangePlanError(message, code="STRUCTURED_PREVIEW_INVALID")
