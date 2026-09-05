"""Portable, checksummed whole-novel archives and fail-closed restoration."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any

import yaml

from tools.init_project import validate_novel_id
from tools.project_lock import ProjectBusyError, ProjectWriteLock

ARCHIVE_FORMAT = "openwrite-novel-archive"
ARCHIVE_VERSION = 1
ARCHIVE_SCHEMA_VERSION = "openwrite.novel-archive.v1"
MANIFEST_NAME = "manifest.json"
MAX_ARCHIVE_FILES = 20_000
MAX_ARCHIVE_BYTES = 1024 * 1024 * 1024
MAX_FILE_BYTES = 256 * 1024 * 1024
FIXED_ZIP_TIME = (1980, 1, 1, 0, 0, 0)

ARCHIVE_CATEGORIES = {
    "config",
    "source",
    "manuscript",
    "structured_data",
    "history",
    "review",
    "references",
    "tasks",
}

EXCLUSION_RULES = (
    {"id": "credentials", "description": "环境文件、凭据目录和密钥文件"},
    {"id": "lock", "description": "进程锁和项目写锁"},
    {"id": "cache", "description": "缓存、索引缓存和测试输出"},
    {"id": "temporary", "description": "临时文件、编辑器交换文件和临时目录"},
    {"id": "export", "description": "导出成品和已有归档包"},
    {"id": "symlink", "description": "符号链接及其目标"},
    {"id": "outside_novel_scope", "description": "活动作品目录之外的项目文件"},
    {"id": "other_novel", "description": "同一项目根下的其他作品"},
    {"id": "special_file", "description": "非普通文件"},
)


class NovelArchiveError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        code: str = "NOVEL_ARCHIVE_FAILED",
        recoverable: bool = False,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.recoverable = recoverable
        self.details = details or {}


class NovelArchiveService:
    """Create and restore a complete novel without activating old task records."""

    def __init__(self, project_root: Path, novel_id: str) -> None:
        self.project_root = Path(project_root).expanduser().resolve()
        try:
            self.novel_id = validate_novel_id(novel_id)
        except ValueError as exc:
            raise NovelArchiveError("作品 ID 无效", code="INVALID_NOVEL_ID") from exc
        self.novel_root = self.project_root / "data" / "novels" / self.novel_id

    def preflight(self, output: Path | None = None) -> dict[str, Any]:
        """Return the exact archive plan without writing a package."""
        if not self.project_root.is_dir() or not self.novel_root.is_dir():
            raise NovelArchiveError("作品目录不存在", code="NOVEL_NOT_FOUND")
        output_path = Path(output).expanduser().resolve() if output is not None else None
        try:
            with ProjectWriteLock(
                self.project_root,
                self.novel_id,
                operation="novel_archive_preflight",
            ):
                manifest, _entries = self._build_manifest(
                    self._collect_project(output_path)
                )
        except ProjectBusyError as exc:
            raise NovelArchiveError(
                str(exc), code="PROJECT_BUSY", recoverable=True
            ) from exc
        return {
            "schema_version": ARCHIVE_SCHEMA_VERSION,
            "novel_id": self.novel_id,
            "preflight_revision": manifest["preflight_revision"],
            "archive_id": manifest["archive_id"],
            "policies": manifest["policies"],
            "includes": manifest["includes"],
            "excludes": manifest["excludes"],
            "missing": manifest["missing"],
            "reference_inventory": manifest["reference_inventory"],
        }

    def create_archive(
        self,
        output: Path,
        *,
        expected_preflight_revision: str = "",
    ) -> dict[str, Any]:
        if not self.project_root.is_dir() or not self.novel_root.is_dir():
            raise NovelArchiveError("作品目录不存在", code="NOVEL_NOT_FOUND")
        output_path = Path(output).expanduser().resolve()
        if output_path.suffix.casefold() != ".zip":
            output_path = output_path.with_name(output_path.name + ".owarchive.zip")
        try:
            with ProjectWriteLock(
                self.project_root,
                self.novel_id,
                operation="novel_archive_create",
            ):
                collected = self._collect_project(output_path)
                manifest, entries = self._build_manifest(collected)
                expected = str(expected_preflight_revision or "").strip().casefold()
                if expected and expected != manifest["preflight_revision"]:
                    raise NovelArchiveError(
                        "归档内容在预检后发生变化",
                        code="PREFLIGHT_CHANGED",
                        recoverable=True,
                        details={
                            "expected": expected,
                            "current": manifest["preflight_revision"],
                        },
                    )
                manifest_bytes = (
                    json.dumps(
                        manifest,
                        ensure_ascii=False,
                        sort_keys=True,
                        indent=2,
                    )
                    + "\n"
                ).encode("utf-8")
                archive_entries = {MANIFEST_NAME: manifest_bytes, **entries}
                self._write_zip(output_path, archive_entries)
        except ProjectBusyError as exc:
            raise NovelArchiveError(
                str(exc), code="PROJECT_BUSY", recoverable=True
            ) from exc
        archive_sha256 = self._file_fingerprint(output_path)
        return {
            "schema_version": ARCHIVE_SCHEMA_VERSION,
            "archive_id": manifest["archive_id"],
            "preflight_revision": manifest["preflight_revision"],
            "path": str(output_path),
            "archive_sha256": archive_sha256,
            "file_count": manifest["includes"]["file_count"],
            "total_size": manifest["includes"]["total_size"],
            "excluded_count": len(manifest["excludes"]["entries"]),
            "missing": manifest["missing"],
        }

    @classmethod
    def inspect_archive(cls, source: Path) -> dict[str, Any]:
        package = cls._read_archive(Path(source).expanduser().resolve())
        return {
            "schema_version": ARCHIVE_SCHEMA_VERSION,
            "archive_sha256": package["archive_sha256"],
            "file_count": len(package["manifest"]["includes"]["files"]),
            "total_size": package["manifest"]["includes"]["total_size"],
            "manifest": package["manifest"],
        }

    @classmethod
    def preview_restore(
        cls,
        source: Path,
        target_root: Path,
        *,
        target_novel_id: str | None = None,
        reference_policy: str = "preserve_relative",
    ) -> dict[str, Any]:
        package = cls._read_archive(Path(source).expanduser().resolve())
        manifest = package["manifest"]
        source_novel_id = str(manifest["source"]["novel_id"])
        requested_novel_id = str(target_novel_id or source_novel_id)
        try:
            requested_novel_id = validate_novel_id(requested_novel_id)
        except ValueError as exc:
            raise NovelArchiveError(
                "目标作品 ID 无效", code="INVALID_NOVEL_ID"
            ) from exc
        supported_reference_policies = {"preserve_relative", "rewrite_novel_id"}
        if reference_policy not in supported_reference_policies:
            raise NovelArchiveError(
                "作品档案不支持所选引用策略",
                code="REFERENCE_POLICY_UNSUPPORTED",
                details={"supported_policies": sorted(supported_reference_policies)},
            )
        if (
            requested_novel_id != source_novel_id
            and reference_policy != "rewrite_novel_id"
        ):
            raise NovelArchiveError(
                "修改作品 ID 时必须显式选择引用重写策略",
                code="NOVEL_ID_POLICY_CONFLICT",
                details={
                    "source_novel_id": source_novel_id,
                    "target_novel_id": requested_novel_id,
                    "required_reference_policy": "rewrite_novel_id",
                },
            )
        reference_plan = cls._reference_plan(
            package,
            target_novel_id=requested_novel_id,
            reference_policy=reference_policy,
        )
        target = cls._target_path(target_root)
        conflicts = ["TARGET_NOT_EMPTY"] if cls._target_not_empty(target) else []
        if reference_plan["reference_conflicts"]:
            conflicts.append("REFERENCE_CONFLICT")
        task_files = [
            item
            for item in manifest["includes"]["files"]
            if item["category"] == "tasks"
        ]
        task_archive_path = cls._task_archive_path(
            requested_novel_id, str(manifest["archive_id"])
        )
        return {
            "schema_version": ARCHIVE_SCHEMA_VERSION,
            "archive_id": manifest["archive_id"],
            "archive_sha256": package["archive_sha256"],
            "source_novel_id": source_novel_id,
            "target_novel_id": requested_novel_id,
            "target_root": str(target),
            "reference_policy": reference_policy,
            "can_restore": not conflicts,
            "conflicts": conflicts,
            "file_count": len(manifest["includes"]["files"]),
            "total_size": manifest["includes"]["total_size"],
            "missing": manifest["missing"],
            "task_file_count": len(task_files),
            "task_archive_path": task_archive_path,
            "auto_resume_tasks": False,
            "path_rewrites": reference_plan["path_rewrites"],
            "rewritten_files": reference_plan["rewritten_files"],
            "rewritten_references": reference_plan["rewritten_references"],
            "preserved_references": reference_plan["preserved_references"],
            "reference_warnings": reference_plan["reference_warnings"],
            "reference_conflicts": reference_plan["reference_conflicts"],
        }

    @classmethod
    def restore_archive(
        cls,
        source: Path,
        target_root: Path,
        *,
        expected_archive_sha256: str = "",
        confirm: bool = False,
        target_novel_id: str | None = None,
        reference_policy: str = "preserve_relative",
    ) -> dict[str, Any]:
        source_path = Path(source).expanduser().resolve()
        if not confirm:
            preview = cls.preview_restore(
                source_path,
                target_root,
                target_novel_id=target_novel_id,
                reference_policy=reference_policy,
            )
            raise NovelArchiveError(
                "恢复作品档案需要显式确认",
                code="CONFIRMATION_REQUIRED",
                recoverable=True,
                details={"preview": preview},
            )
        expected = cls._checksum(expected_archive_sha256)
        actual = cls._file_fingerprint(source_path)
        if expected != actual:
            raise NovelArchiveError(
                "归档文件在预览后发生变化",
                code="ARCHIVE_CHANGED",
                recoverable=True,
                details={"expected": expected, "current": actual},
            )
        preview = cls.preview_restore(
            source_path,
            target_root,
            target_novel_id=target_novel_id,
            reference_policy=reference_policy,
        )
        if "TARGET_NOT_EMPTY" in preview["conflicts"]:
            raise NovelArchiveError(
                "目标目录非空，拒绝覆盖",
                code="TARGET_NOT_EMPTY",
                recoverable=True,
                details={"target_root": preview["target_root"]},
            )
        if preview["reference_conflicts"]:
            raise NovelArchiveError(
                "作品档案包含无法安全处理的引用",
                code="REFERENCE_CONFLICT",
                details={"conflicts": preview["reference_conflicts"]},
            )
        package = cls._read_archive(source_path)
        if package["archive_sha256"] != expected:
            raise NovelArchiveError(
                "归档文件在确认后发生变化",
                code="ARCHIVE_CHANGED",
                recoverable=True,
                details={
                    "expected": expected,
                    "current": package["archive_sha256"],
                },
            )
        target = cls._target_path(target_root)
        manifest = package["manifest"]
        source_novel_id = str(manifest["source"]["novel_id"])
        novel_id = str(preview["target_novel_id"])
        archive_id = str(manifest["archive_id"])
        task_archive_path = cls._task_archive_path(novel_id, archive_id)
        reference_plan = cls._reference_plan(
            package,
            target_novel_id=novel_id,
            reference_policy=reference_policy,
        )
        target.parent.mkdir(parents=True, exist_ok=True)
        staging = Path(
            tempfile.mkdtemp(
                prefix=f".{target.name}.restore-",
                dir=target.parent,
            )
        )
        try:
            for directory in manifest["includes"]["directories"]:
                destination = cls._restore_destination(
                    staging,
                    str(directory),
                    source_novel_id=source_novel_id,
                    target_novel_id=novel_id,
                    archive_id=archive_id,
                )
                destination.mkdir(parents=True, exist_ok=True)
            for record in manifest["includes"]["files"]:
                destination = cls._restore_destination(
                    staging,
                    str(record["path"]),
                    source_novel_id=source_novel_id,
                    target_novel_id=novel_id,
                    archive_id=archive_id,
                )
                destination.parent.mkdir(parents=True, exist_ok=True)
                source_project_path = str(record["path"])
                content = reference_plan["contents"].get(
                    source_project_path,
                    package["entries"][str(record["archive_path"])],
                )
                destination.write_bytes(content)
                expected_output_sha = cls._bytes_fingerprint(content)
                if cls._bytes_fingerprint(destination.read_bytes()) != expected_output_sha:
                    raise NovelArchiveError(
                        "恢复后的文件校验失败",
                        code="RESTORE_CHECKSUM_MISMATCH",
                        details={"path": record["path"]},
                    )
            if target.exists():
                if cls._target_not_empty(target):
                    raise NovelArchiveError(
                        "目标目录非空，拒绝覆盖",
                        code="TARGET_NOT_EMPTY",
                        recoverable=True,
                    )
                target.rmdir()
            staging.replace(target)
        except NovelArchiveError:
            raise
        except OSError as exc:
            raise NovelArchiveError(
                f"恢复作品档案失败: {exc}",
                code="RESTORE_FAILED",
                recoverable=True,
            ) from exc
        finally:
            if staging.exists():
                shutil.rmtree(staging, ignore_errors=True)
        return {
            "schema_version": ARCHIVE_SCHEMA_VERSION,
            "archive_id": archive_id,
            "archive_sha256": actual,
            "target_root": str(target),
            "source_novel_id": source_novel_id,
            "novel_id": novel_id,
            "restored_files": len(manifest["includes"]["files"]),
            "task_archive_path": task_archive_path,
            "task_file_count": preview["task_file_count"],
            "auto_resume_tasks": False,
            "reference_policy": reference_policy,
            "path_rewrites": reference_plan["path_rewrites"],
            "rewritten_files": reference_plan["rewritten_files"],
            "rewritten_references": reference_plan["rewritten_references"],
            "preserved_references": reference_plan["preserved_references"],
            "reference_warnings": reference_plan["reference_warnings"],
        }

    def _collect_project(self, output: Path | None) -> dict[str, Any]:
        prefix = f"data/novels/{self.novel_id}"
        files: dict[str, bytes] = {}
        directories = {"data", "data/novels", prefix}
        excluded: list[dict[str, str]] = []
        config = self.project_root / "novel_config.yaml"
        if config.is_symlink():
            excluded.append({"path": "novel_config.yaml", "reason": "symlink"})
        elif config.is_file():
            files["novel_config.yaml"] = self._read_source_file(config)

        for current_raw, dirnames, filenames in os.walk(
            self.novel_root,
            topdown=True,
            followlinks=False,
        ):
            current = Path(current_raw)
            relative_current = current.relative_to(self.project_root).as_posix()
            directories.add(relative_current)
            retained: list[str] = []
            for name in sorted(dirnames):
                child = current / name
                relative = child.relative_to(self.project_root).as_posix()
                reason = "symlink" if child.is_symlink() else self._exclusion_reason(child)
                if reason:
                    excluded.append({"path": relative + "/", "reason": reason})
                else:
                    retained.append(name)
                    directories.add(relative)
            dirnames[:] = retained
            for name in sorted(filenames):
                path = current / name
                relative = path.relative_to(self.project_root).as_posix()
                if output is not None and path == output:
                    reason = "export"
                elif path.is_symlink():
                    reason = "symlink"
                else:
                    reason = self._exclusion_reason(path)
                try:
                    is_regular = stat.S_ISREG(path.stat(follow_symlinks=False).st_mode)
                except OSError:
                    is_regular = False
                if not reason and not is_regular:
                    reason = "special_file"
                if reason:
                    excluded.append({"path": relative, "reason": reason})
                    continue
                files[relative] = self._read_source_file(path)

        self._collect_outside_scope(excluded, output)
        required = ["novel_config.yaml", f"{prefix}/src/outline.md"]
        missing_required = [path for path in required if path not in files]
        if missing_required:
            raise NovelArchiveError(
                "作品缺少归档必需内容",
                code="REQUIRED_CONTENT_MISSING",
                details={"missing": missing_required},
            )
        config_payload = self._load_config(files["novel_config.yaml"])
        if str(config_payload.get("novel_id") or "") != self.novel_id:
            raise NovelArchiveError(
                "配置中的作品 ID 与归档目标不一致",
                code="NOVEL_ID_MISMATCH",
            )
        sensitive_keys = self._sensitive_config_keys(config_payload)
        if sensitive_keys:
            raise NovelArchiveError(
                "novel_config.yaml 含凭据字段，拒绝写入归档",
                code="CREDENTIALS_PRESENT",
                details={"keys": sensitive_keys},
            )
        optional = (
            f"{prefix}/src/characters",
            f"{prefix}/src/world",
            f"{prefix}/data/manuscript",
            f"{prefix}/data/manuscript_versions",
            f"{prefix}/data/revisions",
            f"{prefix}/data/manuscript_acceptance",
            f"{prefix}/data/reviews",
            f"{prefix}/data/sources",
            f"{prefix}/data/workflows/tasks",
        )
        missing_optional = [
            {"path": path, "state": "absent"}
            for path in optional
            if path not in directories and not any(item.startswith(path + "/") for item in files)
        ]
        return {
            "files": files,
            "directories": sorted(directories),
            "excluded": sorted(excluded, key=lambda item: item["path"]),
            "missing": {"required": [], "optional": missing_optional},
            "config": config_payload,
        }

    def _collect_outside_scope(
        self,
        excluded: list[dict[str, str]],
        output: Path | None,
    ) -> None:
        for child in sorted(self.project_root.iterdir(), key=lambda item: item.name):
            if child.name in {"novel_config.yaml", "data"}:
                continue
            relative = child.relative_to(self.project_root).as_posix()
            reason = (
                "export"
                if output is not None and child == output
                else self._exclusion_reason(child)
            )
            excluded.append(
                {
                    "path": relative + ("/" if child.is_dir() else ""),
                    "reason": reason or "outside_novel_scope",
                }
            )
        data_root = self.project_root / "data"
        if data_root.is_dir():
            for child in sorted(data_root.iterdir(), key=lambda item: item.name):
                if child.name == "novels":
                    continue
                relative = child.relative_to(self.project_root).as_posix()
                excluded.append(
                    {
                        "path": relative + ("/" if child.is_dir() else ""),
                        "reason": self._exclusion_reason(child) or "outside_novel_scope",
                    }
                )
        novels_root = data_root / "novels"
        if novels_root.is_dir():
            for child in sorted(novels_root.iterdir(), key=lambda item: item.name):
                if child.name == self.novel_id:
                    continue
                relative = child.relative_to(self.project_root).as_posix()
                excluded.append(
                    {
                        "path": relative + ("/" if child.is_dir() else ""),
                        "reason": "other_novel",
                    }
                )

    def _build_manifest(
        self,
        collected: dict[str, Any],
    ) -> tuple[dict[str, Any], dict[str, bytes]]:
        entries: dict[str, bytes] = {}
        records: list[dict[str, Any]] = []
        category_counts = {category: 0 for category in sorted(ARCHIVE_CATEGORIES)}
        total_size = 0
        for path, content in sorted(collected["files"].items()):
            archive_path = f"project/{path}"
            category = self._category(path)
            record = {
                "path": path,
                "archive_path": archive_path,
                "category": category,
                "sha256": self._bytes_fingerprint(content),
                "size": len(content),
            }
            records.append(record)
            entries[archive_path] = content
            category_counts[category] += 1
            total_size += len(content)
        identity = {
            "format": ARCHIVE_FORMAT,
            "version": ARCHIVE_VERSION,
            "novel_id": self.novel_id,
            "files": [
                {key: record[key] for key in ("path", "sha256", "size")}
                for record in records
            ],
        }
        content_digest = self._bytes_fingerprint(
            json.dumps(identity, sort_keys=True, separators=(",", ":")).encode("utf-8")
        )
        archive_id = f"owa_{content_digest.removeprefix('sha256:')[:24]}"
        reference_inventory = self._reference_inventory(
            collected["files"], self.novel_id
        )
        policies = {
            "novel_id": {
                "default": "preserve",
                "remap_requires": "rewrite_novel_id",
            },
            "references": {
                "default": "preserve_relative",
                "supported": ["preserve_relative", "rewrite_novel_id"],
            },
            "tasks": "archive_no_resume",
            "target": "new_or_empty",
        }
        preflight_payload = {
            "schema_version": ARCHIVE_SCHEMA_VERSION,
            "novel_id": self.novel_id,
            "policies": policies,
            "includes": {
                "directories": collected["directories"],
                "files": records,
            },
            "excludes": collected["excluded"],
            "missing": collected["missing"],
            "reference_inventory": reference_inventory,
        }
        preflight_revision = self._bytes_fingerprint(
            json.dumps(
                preflight_payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        )
        manifest = {
            "format": ARCHIVE_FORMAT,
            "version": ARCHIVE_VERSION,
            "schema_version": ARCHIVE_SCHEMA_VERSION,
            "archive_id": archive_id,
            "preflight_revision": preflight_revision,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "source": {
                "novel_id": self.novel_id,
                "title": str(collected["config"].get("title") or ""),
            },
            "policies": policies,
            "integrity": {
                "algorithm": "sha256",
                "content_digest": content_digest,
            },
            "includes": {
                "roots": ["novel_config.yaml", f"data/novels/{self.novel_id}"],
                "file_count": len(records),
                "total_size": total_size,
                "category_counts": category_counts,
                "directories": collected["directories"],
                "files": records,
            },
            "excludes": {
                "rules": list(EXCLUSION_RULES),
                "entries": collected["excluded"],
            },
            "missing": collected["missing"],
            "reference_inventory": reference_inventory,
        }
        return manifest, entries

    @classmethod
    def _reference_inventory(
        cls,
        files: dict[str, bytes],
        novel_id: str,
    ) -> dict[str, Any]:
        known: list[dict[str, Any]] = []
        preserved: list[dict[str, Any]] = []
        warnings: list[dict[str, Any]] = []
        for path, content in sorted(files.items()):
            structured = cls._parse_structured(path, content)
            if structured is not None:
                format_name, payload = structured
                cls._inspect_reference_value(
                    payload,
                    path=path,
                    format_name=format_name,
                    novel_id=novel_id,
                    location="$",
                    key="",
                    known=known,
                    preserved=preserved,
                    warnings=warnings,
                )
                continue
            try:
                text = content.decode("utf-8")
            except UnicodeDecodeError:
                continue
            matches = list(cls._relative_reference_pattern(novel_id).finditer(text))
            for match in matches:
                known.append(
                    {
                        "path": path,
                        "format": "text",
                        "location": f"line:{text.count(chr(10), 0, match.start()) + 1}",
                        "kind": "project_relative_path",
                        "value": match.group(0).lstrip(" \t\"'(:="),
                    }
                )
            marker = f"data/novels/{novel_id}"
            if marker in text and not matches:
                warnings.append(
                    {
                        "path": path,
                        "format": "text",
                        "location": "$",
                        "kind": "unresolved_project_reference",
                        "value": marker,
                    }
                )
        return {
            "schema_version": "openwrite.novel-archive.references.v1",
            "known": sorted(known, key=cls._reference_sort_key),
            "preserved": sorted(preserved, key=cls._reference_sort_key),
            "warnings": sorted(warnings, key=cls._reference_sort_key),
        }

    @classmethod
    def _inspect_reference_value(
        cls,
        value: Any,
        *,
        path: str,
        format_name: str,
        novel_id: str,
        location: str,
        key: str,
        known: list[dict[str, Any]],
        preserved: list[dict[str, Any]],
        warnings: list[dict[str, Any]],
    ) -> None:
        if isinstance(value, dict):
            for raw_key, item in value.items():
                child_key = str(raw_key)
                cls._inspect_reference_value(
                    item,
                    path=path,
                    format_name=format_name,
                    novel_id=novel_id,
                    location=f"{location}.{child_key}",
                    key=child_key,
                    known=known,
                    preserved=preserved,
                    warnings=warnings,
                )
            return
        if isinstance(value, list):
            for index, item in enumerate(value):
                cls._inspect_reference_value(
                    item,
                    path=path,
                    format_name=format_name,
                    novel_id=novel_id,
                    location=f"{location}[{index}]",
                    key=key,
                    known=known,
                    preserved=preserved,
                    warnings=warnings,
                )
            return
        if not isinstance(value, str):
            return
        normalized_key = re.sub(r"[-\s]+", "_", key.casefold())
        base = {
            "path": path,
            "format": format_name,
            "location": location,
            "value": value[:1000],
        }
        if cls._is_absolute_reference(value):
            warnings.append({**base, "kind": "absolute_reference_preserved"})
            return
        if normalized_key in {"novel_id", "source_novel_id", "target_novel_id"}:
            if value == novel_id:
                known.append({**base, "kind": "novel_id"})
            elif novel_id in value:
                warnings.append({**base, "kind": "unexpected_novel_id_reference"})
            return
        if normalized_key == "style_id" and value == novel_id:
            preserved.append({**base, "kind": "style_asset_id"})
            return
        replaced, replacements = cls._replace_relative_references(
            value, novel_id, "__TARGET_NOVEL_ID__"
        )
        if replacements:
            known.append(
                {
                    **base,
                    "kind": "project_relative_path",
                    "replacement_count": replacements,
                }
            )
        elif value == novel_id:
            warnings.append({**base, "kind": "ambiguous_novel_id_preserved"})
        elif f"data/novels/{novel_id}" in value and replaced == value:
            warnings.append({**base, "kind": "unresolved_project_reference"})

    @classmethod
    def _rewrite_file_references(
        cls,
        path: str,
        content: bytes,
        *,
        source_novel_id: str,
        target_novel_id: str,
    ) -> tuple[bytes, list[dict[str, Any]]]:
        structured = cls._parse_structured(path, content)
        if structured is None:
            try:
                text = content.decode("utf-8")
            except UnicodeDecodeError:
                return content, []
            rewritten, count = cls._replace_relative_references(
                text, source_novel_id, target_novel_id
            )
            if not count:
                return content, []
            return rewritten.encode("utf-8"), [
                {
                    "path": path,
                    "format": "text",
                    "location": "$",
                    "kind": "project_relative_path",
                    "before": f"data/novels/{source_novel_id}",
                    "after": f"data/novels/{target_novel_id}",
                    "replacement_count": count,
                }
            ]
        format_name, payload = structured
        rewritten_payload, changes = cls._rewrite_reference_value(
            payload,
            path=path,
            format_name=format_name,
            source_novel_id=source_novel_id,
            target_novel_id=target_novel_id,
            location="$",
            key="",
        )
        if not changes:
            return content, []
        if format_name == "json":
            ending = "\n" if content.endswith(b"\n") else ""
            rendered = json.dumps(
                rewritten_payload,
                ensure_ascii=False,
                sort_keys=False,
                indent=2,
            ) + ending
        elif format_name == "jsonl":
            rendered = "\n".join(
                json.dumps(item, ensure_ascii=False, sort_keys=False, separators=(",", ":"))
                for item in rewritten_payload
            )
            if content.endswith(b"\n"):
                rendered += "\n"
        else:
            rendered = yaml.safe_dump(
                rewritten_payload,
                allow_unicode=True,
                sort_keys=False,
            )
        return rendered.encode("utf-8"), changes

    @classmethod
    def _rewrite_reference_value(
        cls,
        value: Any,
        *,
        path: str,
        format_name: str,
        source_novel_id: str,
        target_novel_id: str,
        location: str,
        key: str,
    ) -> tuple[Any, list[dict[str, Any]]]:
        changes: list[dict[str, Any]] = []
        if isinstance(value, dict):
            rewritten: dict[Any, Any] = {}
            for raw_key, item in value.items():
                child_key = str(raw_key)
                updated, child_changes = cls._rewrite_reference_value(
                    item,
                    path=path,
                    format_name=format_name,
                    source_novel_id=source_novel_id,
                    target_novel_id=target_novel_id,
                    location=f"{location}.{child_key}",
                    key=child_key,
                )
                rewritten[raw_key] = updated
                changes.extend(child_changes)
            return rewritten, changes
        if isinstance(value, list):
            rewritten_list: list[Any] = []
            for index, item in enumerate(value):
                updated, child_changes = cls._rewrite_reference_value(
                    item,
                    path=path,
                    format_name=format_name,
                    source_novel_id=source_novel_id,
                    target_novel_id=target_novel_id,
                    location=f"{location}[{index}]",
                    key=key,
                )
                rewritten_list.append(updated)
                changes.extend(child_changes)
            return rewritten_list, changes
        if not isinstance(value, str) or cls._is_absolute_reference(value):
            return value, changes
        normalized_key = re.sub(r"[-\s]+", "_", key.casefold())
        updated = value
        kind = ""
        count = 0
        if (
            normalized_key in {"novel_id", "source_novel_id", "target_novel_id"}
            and value == source_novel_id
        ):
            updated = target_novel_id
            kind = "novel_id"
            count = 1
        else:
            updated, count = cls._replace_relative_references(
                value, source_novel_id, target_novel_id
            )
            if count:
                kind = "project_relative_path"
        if updated != value:
            changes.append(
                {
                    "path": path,
                    "format": format_name,
                    "location": location,
                    "kind": kind,
                    "before": value[:1000],
                    "after": updated[:1000],
                    "replacement_count": count,
                }
            )
        return updated, changes

    @classmethod
    def _reference_plan(
        cls,
        package: dict[str, Any],
        *,
        target_novel_id: str,
        reference_policy: str,
    ) -> dict[str, Any]:
        manifest = package["manifest"]
        source_novel_id = str(manifest["source"]["novel_id"])
        archive_id = str(manifest["archive_id"])
        contents: dict[str, bytes] = {}
        rewritten_files: list[dict[str, Any]] = []
        rewritten_references: list[dict[str, Any]] = []
        path_rewrites: list[dict[str, str]] = []
        reference_conflicts: list[dict[str, Any]] = []
        target_paths: dict[str, str] = {}
        for record in manifest["includes"]["files"]:
            source_path = str(record["path"])
            target_path = cls._mapped_project_path(
                source_path,
                source_novel_id=source_novel_id,
                target_novel_id=target_novel_id,
                archive_id=archive_id,
            )
            previous_source = target_paths.setdefault(target_path.casefold(), source_path)
            if previous_source != source_path:
                reference_conflicts.append(
                    {
                        "kind": "target_path_collision",
                        "target_path": target_path,
                        "source_paths": sorted({previous_source, source_path}),
                    }
                )
            if target_path != source_path:
                path_rewrites.append({"source": source_path, "target": target_path})
            if reference_policy != "rewrite_novel_id":
                continue
            original = package["entries"][str(record["archive_path"])]
            rewritten, changes = cls._rewrite_file_references(
                source_path,
                original,
                source_novel_id=source_novel_id,
                target_novel_id=target_novel_id,
            )
            if rewritten == original:
                continue
            contents[source_path] = rewritten
            rewritten_references.extend(changes)
            rewritten_files.append(
                {
                    "source_path": source_path,
                    "target_path": target_path,
                    "sha256_before": cls._bytes_fingerprint(original),
                    "sha256_after": cls._bytes_fingerprint(rewritten),
                    "reference_count": len(changes),
                }
            )
        inventory = manifest["reference_inventory"]
        return {
            "contents": contents,
            "path_rewrites": path_rewrites,
            "rewritten_files": rewritten_files,
            "rewritten_references": rewritten_references,
            "preserved_references": list(inventory["preserved"]),
            "reference_warnings": list(inventory["warnings"]),
            "reference_conflicts": reference_conflicts,
        }

    @staticmethod
    def _parse_structured(path: str, content: bytes) -> tuple[str, Any] | None:
        suffix = PurePosixPath(path).suffix.casefold()
        if suffix not in {".json", ".jsonl", ".yaml", ".yml"} and path != "novel_config.yaml":
            return None
        try:
            text = content.decode("utf-8")
            if suffix == ".json":
                return "json", json.loads(text)
            if suffix == ".jsonl":
                return "jsonl", [json.loads(line) for line in text.splitlines() if line.strip()]
            return "yaml", yaml.safe_load(text)
        except (UnicodeDecodeError, json.JSONDecodeError, yaml.YAMLError):
            return None

    @staticmethod
    def _relative_reference_pattern(novel_id: str) -> re.Pattern[str]:
        return re.compile(
            rf"(?:^|[\s\"'(:=])(?:\./)?data/novels/{re.escape(novel_id)}"
            rf"(?=$|[/\s\"')\],}}#?])",
            flags=re.MULTILINE,
        )

    @classmethod
    def _replace_relative_references(
        cls,
        value: str,
        source_novel_id: str,
        target_novel_id: str,
    ) -> tuple[str, int]:
        pattern = cls._relative_reference_pattern(source_novel_id)

        def replace(match: re.Match[str]) -> str:
            matched = match.group(0)
            marker = f"data/novels/{source_novel_id}"
            return matched.replace(marker, f"data/novels/{target_novel_id}", 1)

        return pattern.subn(replace, value)

    @staticmethod
    def _is_absolute_reference(value: str) -> bool:
        clean = value.strip()
        return clean.startswith(("/", "file://")) or bool(
            re.match(r"^[A-Za-z]:[\\/]", clean)
        )

    @staticmethod
    def _reference_sort_key(item: dict[str, Any]) -> tuple[str, str, str]:
        return (
            str(item.get("path") or ""),
            str(item.get("location") or ""),
            str(item.get("kind") or ""),
        )

    @classmethod
    def _read_archive(cls, source: Path) -> dict[str, Any]:
        if not source.is_file():
            raise NovelArchiveError("作品档案不存在", code="ARCHIVE_NOT_FOUND")
        if source.stat().st_size > MAX_ARCHIVE_BYTES:
            raise NovelArchiveError("作品档案过大", code="INVALID_ARCHIVE")
        archive_sha256 = cls._file_fingerprint(source)
        try:
            archive = zipfile.ZipFile(source, "r")
        except (OSError, zipfile.BadZipFile) as exc:
            raise NovelArchiveError("作品档案不是有效 ZIP", code="INVALID_ARCHIVE") from exc
        with archive:
            infos = archive.infolist()
            if len(infos) > MAX_ARCHIVE_FILES:
                raise NovelArchiveError("作品档案文件过多", code="INVALID_ARCHIVE")
            if sum(info.file_size for info in infos) > MAX_ARCHIVE_BYTES:
                raise NovelArchiveError("作品档案解压后过大", code="INVALID_ARCHIVE")
            entries: dict[str, bytes] = {}
            seen: set[str] = set()
            for info in infos:
                cls._validate_archive_path(info.filename)
                folded = info.filename.casefold()
                if folded in seen:
                    raise NovelArchiveError(
                        "作品档案包含重复路径", code="DUPLICATE_ARCHIVE_PATH"
                    )
                seen.add(folded)
                mode = (info.external_attr >> 16) & 0xFFFF
                if stat.S_ISLNK(mode):
                    raise NovelArchiveError(
                        "作品档案包含符号链接", code="UNSAFE_ARCHIVE_PATH"
                    )
                if info.flag_bits & 0x1:
                    raise NovelArchiveError("不支持加密作品档案", code="INVALID_ARCHIVE")
                if info.file_size > MAX_FILE_BYTES:
                    raise NovelArchiveError("作品档案单文件过大", code="INVALID_ARCHIVE")
                if info.is_dir():
                    continue
                try:
                    entries[info.filename] = archive.read(info)
                except (OSError, RuntimeError, zipfile.BadZipFile) as exc:
                    raise NovelArchiveError(
                        "作品档案内容损坏", code="INVALID_ARCHIVE"
                    ) from exc
        raw_manifest = entries.get(MANIFEST_NAME)
        if raw_manifest is None:
            raise NovelArchiveError("作品档案缺少清单", code="MANIFEST_MISSING")
        try:
            manifest = json.loads(raw_manifest.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise NovelArchiveError("作品档案清单无效", code="MANIFEST_INVALID") from exc
        cls._validate_manifest(manifest, entries)
        return {
            "manifest": manifest,
            "entries": entries,
            "archive_sha256": archive_sha256,
        }

    @classmethod
    def _validate_manifest(cls, manifest: Any, entries: dict[str, bytes]) -> None:
        if not isinstance(manifest, dict):
            raise NovelArchiveError("作品档案清单无效", code="MANIFEST_INVALID")
        if (
            manifest.get("format") != ARCHIVE_FORMAT
            or manifest.get("version") != ARCHIVE_VERSION
            or manifest.get("schema_version") != ARCHIVE_SCHEMA_VERSION
        ):
            raise NovelArchiveError("作品档案版本不受支持", code="UNSUPPORTED_ARCHIVE_VERSION")
        source = manifest.get("source")
        includes = manifest.get("includes")
        missing = manifest.get("missing")
        if not isinstance(source, dict) or not isinstance(includes, dict):
            raise NovelArchiveError("作品档案清单结构无效", code="MANIFEST_INVALID")
        try:
            novel_id = validate_novel_id(str(source.get("novel_id") or ""))
        except ValueError as exc:
            raise NovelArchiveError("作品档案的作品 ID 无效", code="MANIFEST_INVALID") from exc
        if not isinstance(missing, dict) or missing.get("required") != []:
            raise NovelArchiveError("作品档案缺少必需内容", code="REQUIRED_CONTENT_MISSING")
        files = includes.get("files")
        directories = includes.get("directories")
        if not isinstance(files, list) or not isinstance(directories, list):
            raise NovelArchiveError("作品档案文件清单无效", code="MANIFEST_INVALID")
        seen_paths: set[str] = set()
        expected_entries = {MANIFEST_NAME}
        normalized_records: list[dict[str, Any]] = []
        total_size = 0
        for item in files:
            if not isinstance(item, dict):
                raise NovelArchiveError("作品档案文件条目无效", code="MANIFEST_INVALID")
            path = str(item.get("path") or "")
            archive_path = str(item.get("archive_path") or "")
            cls._validate_project_path(path, novel_id)
            cls._validate_archive_path(archive_path)
            if archive_path != f"project/{path}":
                raise NovelArchiveError("作品档案路径映射无效", code="MANIFEST_INVALID")
            folded = path.casefold()
            if folded in seen_paths:
                raise NovelArchiveError("作品档案项目路径重复", code="MANIFEST_INVALID")
            seen_paths.add(folded)
            category = str(item.get("category") or "")
            if category not in ARCHIVE_CATEGORIES or category != cls._category(path):
                raise NovelArchiveError("作品档案文件分类无效", code="MANIFEST_INVALID")
            try:
                size = int(item.get("size"))
            except (TypeError, ValueError) as exc:
                raise NovelArchiveError("作品档案文件大小无效", code="MANIFEST_INVALID") from exc
            checksum = str(item.get("sha256") or "")
            if size < 0 or not re.fullmatch(r"sha256:[0-9a-f]{64}", checksum):
                raise NovelArchiveError("作品档案文件校验信息无效", code="MANIFEST_INVALID")
            content = entries.get(archive_path)
            if content is None:
                raise NovelArchiveError(
                    "作品档案文件缺失",
                    code="ARCHIVE_ENTRY_MISSING",
                    details={"path": path},
                )
            if len(content) != size or cls._bytes_fingerprint(content) != checksum:
                raise NovelArchiveError(
                    "作品档案文件校验和不匹配",
                    code="CHECKSUM_MISMATCH",
                    details={"path": path},
                )
            total_size += size
            expected_entries.add(archive_path)
            normalized_records.append({"path": path, "sha256": checksum, "size": size})
        actual_entries = set(entries)
        if actual_entries != expected_entries:
            raise NovelArchiveError(
                "作品档案包含未列入清单的文件",
                code="UNLISTED_ARCHIVE_ENTRY",
                details={"entries": sorted(actual_entries - expected_entries)},
            )
        seen_directories: set[str] = set()
        for directory in directories:
            normalized_directory = str(directory or "")
            cls._validate_project_path(normalized_directory, novel_id)
            folded_directory = normalized_directory.casefold()
            if (
                folded_directory in seen_directories
                or folded_directory in seen_paths
            ):
                raise NovelArchiveError(
                    "作品档案目录清单冲突", code="MANIFEST_INVALID"
                )
            seen_directories.add(folded_directory)
        required = {"novel_config.yaml", f"data/novels/{novel_id}/src/outline.md"}
        if not required.issubset(seen_paths):
            raise NovelArchiveError("作品档案缺少必需内容", code="REQUIRED_CONTENT_MISSING")
        if includes.get("file_count") != len(files) or includes.get("total_size") != total_size:
            raise NovelArchiveError("作品档案汇总信息无效", code="MANIFEST_INVALID")
        expected_category_counts = {
            category: sum(item["category"] == category for item in files)
            for category in sorted(ARCHIVE_CATEGORIES)
        }
        if includes.get("category_counts") != expected_category_counts:
            raise NovelArchiveError("作品档案分类汇总无效", code="MANIFEST_INVALID")
        identity = {
            "format": ARCHIVE_FORMAT,
            "version": ARCHIVE_VERSION,
            "novel_id": novel_id,
            "files": normalized_records,
        }
        digest = cls._bytes_fingerprint(
            json.dumps(identity, sort_keys=True, separators=(",", ":")).encode("utf-8")
        )
        integrity = manifest.get("integrity")
        if (
            not isinstance(integrity, dict)
            or integrity.get("algorithm") != "sha256"
            or integrity.get("content_digest") != digest
            or manifest.get("archive_id")
            != f"owa_{digest.removeprefix('sha256:')[:24]}"
        ):
            raise NovelArchiveError("作品档案内容摘要无效", code="MANIFEST_INVALID")
        config_record = next(item for item in files if item["path"] == "novel_config.yaml")
        config = cls._load_config(entries[str(config_record["archive_path"])])
        if str(config.get("novel_id") or "") != novel_id:
            raise NovelArchiveError("作品档案配置 ID 不一致", code="NOVEL_ID_MISMATCH")
        policies = {
            "novel_id": {
                "default": "preserve",
                "remap_requires": "rewrite_novel_id",
            },
            "references": {
                "default": "preserve_relative",
                "supported": ["preserve_relative", "rewrite_novel_id"],
            },
            "tasks": "archive_no_resume",
            "target": "new_or_empty",
        }
        if manifest.get("policies") != policies:
            raise NovelArchiveError("作品档案恢复策略无效", code="MANIFEST_INVALID")
        file_contents = {
            str(record["path"]): entries[str(record["archive_path"])]
            for record in files
        }
        reference_inventory = cls._reference_inventory(file_contents, novel_id)
        if manifest.get("reference_inventory") != reference_inventory:
            raise NovelArchiveError("作品档案引用清单无效", code="MANIFEST_INVALID")
        excludes = manifest.get("excludes")
        if (
            not isinstance(excludes, dict)
            or excludes.get("rules") != list(EXCLUSION_RULES)
            or not isinstance(excludes.get("entries"), list)
        ):
            raise NovelArchiveError("作品档案排除清单无效", code="MANIFEST_INVALID")
        preflight_payload = {
            "schema_version": ARCHIVE_SCHEMA_VERSION,
            "novel_id": novel_id,
            "policies": policies,
            "includes": {
                "directories": directories,
                "files": files,
            },
            "excludes": excludes["entries"],
            "missing": missing,
            "reference_inventory": reference_inventory,
        }
        expected_preflight_revision = cls._bytes_fingerprint(
            json.dumps(
                preflight_payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        )
        if manifest.get("preflight_revision") != expected_preflight_revision:
            raise NovelArchiveError("作品档案预检修订无效", code="MANIFEST_INVALID")

    @staticmethod
    def _write_zip(output: Path, entries: dict[str, bytes]) -> None:
        output.parent.mkdir(parents=True, exist_ok=True)
        temporary: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="wb",
                dir=output.parent,
                prefix=f".{output.name}.",
                suffix=".tmp",
                delete=False,
            ) as handle:
                temporary = Path(handle.name)
            with zipfile.ZipFile(
                temporary,
                "w",
                compression=zipfile.ZIP_DEFLATED,
                compresslevel=9,
            ) as archive:
                for name, content in sorted(entries.items()):
                    info = zipfile.ZipInfo(name, date_time=FIXED_ZIP_TIME)
                    info.compress_type = zipfile.ZIP_DEFLATED
                    info.create_system = 3
                    info.external_attr = 0o100644 << 16
                    archive.writestr(
                        info,
                        content,
                        compress_type=zipfile.ZIP_DEFLATED,
                        compresslevel=9,
                    )
            temporary.replace(output)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    @classmethod
    def _restore_destination(
        cls,
        staging: Path,
        project_path: str,
        *,
        source_novel_id: str,
        target_novel_id: str,
        archive_id: str,
    ) -> Path:
        mapped = PurePosixPath(
            cls._mapped_project_path(
                project_path,
                source_novel_id=source_novel_id,
                target_novel_id=target_novel_id,
                archive_id=archive_id,
            )
        )
        destination = staging.joinpath(*mapped.parts)
        try:
            destination.resolve().relative_to(staging.resolve())
        except ValueError as exc:
            raise NovelArchiveError(
                "恢复路径越出目标目录", code="UNSAFE_ARCHIVE_PATH"
            ) from exc
        return destination

    @classmethod
    def _mapped_project_path(
        cls,
        project_path: str,
        *,
        source_novel_id: str,
        target_novel_id: str,
        archive_id: str,
    ) -> str:
        relative = PurePosixPath(project_path)
        source_novel_root = PurePosixPath(f"data/novels/{source_novel_id}")
        source_tasks = source_novel_root / "data" / "workflows" / "tasks"
        if relative == source_tasks or source_tasks in relative.parents:
            suffix = relative.relative_to(source_tasks)
            return (
                PurePosixPath(cls._task_archive_path(target_novel_id, archive_id))
                / suffix
            ).as_posix()
        if relative == source_novel_root or source_novel_root in relative.parents:
            suffix = relative.relative_to(source_novel_root)
            return (
                PurePosixPath(f"data/novels/{target_novel_id}") / suffix
            ).as_posix()
        return relative.as_posix()

    @staticmethod
    def _task_archive_path(novel_id: str, archive_id: str) -> str:
        return f"data/novels/{novel_id}/data/workflows/task_archive/{archive_id}"

    @staticmethod
    def _target_path(target_root: Path) -> Path:
        target = Path(target_root).expanduser()
        if target.exists() and target.is_symlink():
            raise NovelArchiveError("目标目录不能是符号链接", code="TARGET_NOT_EMPTY")
        return target.resolve()

    @staticmethod
    def _target_not_empty(target: Path) -> bool:
        if not target.exists():
            return False
        if not target.is_dir():
            return True
        try:
            next(target.iterdir())
        except StopIteration:
            return False
        return True

    @staticmethod
    def _validate_archive_path(value: str) -> None:
        raw = str(value or "")
        path = PurePosixPath(raw)
        if (
            not raw
            or "\x00" in raw
            or "\\" in raw
            or path.is_absolute()
            or ".." in path.parts
            or raw != path.as_posix()
            or any(":" in part for part in path.parts)
        ):
            raise NovelArchiveError(
                "作品档案包含不安全路径", code="UNSAFE_ARCHIVE_PATH"
            )

    @classmethod
    def _validate_project_path(cls, value: str, novel_id: str) -> None:
        cls._validate_archive_path(value)
        if value == "novel_config.yaml" or value in {"data", "data/novels"}:
            return
        prefix = f"data/novels/{novel_id}"
        if value != prefix and not value.startswith(prefix + "/"):
            raise NovelArchiveError("作品档案项目路径无效", code="MANIFEST_INVALID")

    @staticmethod
    def _checksum(value: str) -> str:
        checksum = str(value or "").strip().casefold()
        if not re.fullmatch(r"sha256:[0-9a-f]{64}", checksum):
            raise NovelArchiveError(
                "请先预览并提交完整归档校验和",
                code="PREVIEW_REQUIRED",
                recoverable=True,
            )
        return checksum

    @staticmethod
    def _load_config(content: bytes) -> dict[str, Any]:
        try:
            payload = yaml.safe_load(content.decode("utf-8")) or {}
        except (UnicodeDecodeError, yaml.YAMLError) as exc:
            raise NovelArchiveError("novel_config.yaml 无效", code="INVALID_PROJECT") from exc
        if not isinstance(payload, dict):
            raise NovelArchiveError("novel_config.yaml 无效", code="INVALID_PROJECT")
        return payload

    @classmethod
    def _sensitive_config_keys(
        cls,
        value: Any,
        *,
        prefix: str = "",
    ) -> list[str]:
        sensitive = {
            "api_key",
            "access_token",
            "refresh_token",
            "password",
            "secret",
            "credential",
            "credentials",
        }
        found: list[str] = []
        if isinstance(value, dict):
            for raw_key, item in value.items():
                key = str(raw_key)
                location = f"{prefix}.{key}" if prefix else key
                normalized = re.sub(r"[-\s]+", "_", key.casefold())
                if (
                    normalized in sensitive
                    and item is not None
                    and item != ""
                    and item != "[redacted]"
                ):
                    found.append(location)
                else:
                    found.extend(cls._sensitive_config_keys(item, prefix=location))
        elif isinstance(value, list):
            for index, item in enumerate(value):
                location = f"{prefix}[{index}]"
                found.extend(cls._sensitive_config_keys(item, prefix=location))
        return found

    @staticmethod
    def _read_source_file(path: Path) -> bytes:
        try:
            content = path.read_bytes()
        except OSError as exc:
            raise NovelArchiveError(
                f"无法读取归档源文件: {path.name}", code="SOURCE_READ_FAILED"
            ) from exc
        if len(content) > MAX_FILE_BYTES:
            raise NovelArchiveError(
                f"归档源文件过大: {path.name}", code="SOURCE_FILE_TOO_LARGE"
            )
        return content

    @staticmethod
    def _category(path: str) -> str:
        parts = PurePosixPath(path).parts
        if path == "novel_config.yaml":
            return "config"
        try:
            data_index = parts.index("data", 3)
        except ValueError:
            return "source" if "src" in parts else "structured_data"
        relative = parts[data_index + 1 :]
        head = relative[0] if relative else ""
        if head == "manuscript":
            return "manuscript"
        if head in {
            "manuscript_versions",
            "revisions",
            "manuscript_acceptance",
            "snapshots",
            "history",
            "backups",
        }:
            return "history"
        if head == "reviews":
            return "review"
        if head in {"sources", "citations", "research"}:
            return "references"
        if len(relative) >= 2 and relative[:2] == ("workflows", "tasks"):
            return "tasks"
        return "structured_data"

    @staticmethod
    def _exclusion_reason(path: Path) -> str:
        parts = tuple(part.casefold() for part in path.parts)
        name = path.name.casefold()
        credential_dirs = {
            "credentials",
            "secrets",
            "model-settings",
            ".credentials",
            ".ssh",
        }
        cache_dirs = {
            "cache",
            "caches",
            ".cache",
            ".openwrite",
            "__pycache__",
            ".pytest_cache",
            ".mypy_cache",
            ".ruff_cache",
            "lightrag",
            "search_index",
            "test_outputs",
        }
        temporary_dirs = {"tmp", "temp", "temporary"}
        export_dirs = {"export", "exports"}
        if any(part in credential_dirs for part in parts):
            return "credentials"
        if (
            name in {
                ".env",
                ".netrc",
                ".npmrc",
                ".pypirc",
                "id_rsa",
                "id_ed25519",
            }
            or name.startswith(".env.")
            or re.fullmatch(
                r"(?:credentials?|secrets?|api[_-]?keys?)\.(?:json|ya?ml|toml|txt)",
                name,
            )
            or path.suffix.casefold() in {".pem", ".p12", ".pfx"}
        ):
            return "credentials"
        if (
            "benchmarks" in parts
            and "workspaces" in parts
        ) or any(
            left == "data" and right == "logs"
            for left, right in zip(parts, parts[1:])
        ) or any(part in cache_dirs for part in parts) or name in {
            "character-state-index.json",
        }:
            return "cache"
        if any(part in temporary_dirs for part in parts) or name.endswith(
            (".tmp", ".temp", ".swp", ".swo", "~")
        ):
            return "temporary"
        if any(part in export_dirs for part in parts) or name.endswith(".owarchive.zip"):
            return "export"
        if name.endswith(".lock") or name in {"lock", "project.lock"}:
            return "lock"
        return ""

    @staticmethod
    def _bytes_fingerprint(content: bytes) -> str:
        return "sha256:" + hashlib.sha256(content).hexdigest()

    @staticmethod
    def _file_fingerprint(path: Path) -> str:
        digest = hashlib.sha256()
        try:
            with path.open("rb") as handle:
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    digest.update(chunk)
        except OSError as exc:
            raise NovelArchiveError("无法读取作品档案", code="ARCHIVE_NOT_FOUND") from exc
        return "sha256:" + digest.hexdigest()
