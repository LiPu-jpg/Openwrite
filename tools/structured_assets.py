"""Structured editing facade over canonical Markdown and YAML assets."""

from __future__ import annotations

import hashlib
import os
import re
import tempfile
from pathlib import Path
from typing import Any

import yaml

from tools.frontmatter import (
    compose_toml_document,
    parse_toml_front_matter,
    strip_front_matter_padding,
)
from tools.project_lock import ProjectBusyError, ProjectWriteLock
from tools.shared_documents import (
    normalize_character_document,
    normalize_world_entity_document,
)

ASSET_KINDS = {"character", "world", "progression"}
CHARACTER_FIELDS = (
    "name",
    "aliases",
    "tier",
    "summary",
    "tags",
    "personality",
    "goal",
    "fear",
    "taboos",
    "appearance",
    "voice",
    "current_state",
    "state_updated_at",
    "organization",
    "progression_system",
    "progression_stage",
    "detail_refs",
    "related",
)
WORLD_FIELDS = (
    "name",
    "kind",
    "type",
    "subtype",
    "summary",
    "status",
    "tags",
    "detail_refs",
    "related",
)


class StructuredAssetError(RuntimeError):
    def __init__(self, message: str, *, code: str = "ASSET_FAILED", recoverable: bool = False):
        super().__init__(message)
        self.code = code
        self.recoverable = recoverable


class StructuredAssetService:
    def __init__(self, project_root: Path, novel_id: str):
        self.project_root = Path(project_root).resolve()
        self.novel_id = str(novel_id)
        self.novel_root = self.project_root / "data" / "novels" / self.novel_id

    def list(self, kind: str = "") -> list[dict[str, Any]]:
        kinds = [self._kind(kind)] if kind else sorted(ASSET_KINDS)
        result: list[dict[str, Any]] = []
        locations: dict[tuple[str, str], Path] = {}
        for asset_kind in kinds:
            for path in self._paths(asset_kind):
                try:
                    summary = self._summary(asset_kind, path)
                except (OSError, StructuredAssetError, yaml.YAMLError):
                    continue
                key = (asset_kind, summary["id"])
                previous = locations.get(key)
                if previous is not None:
                    raise self._duplicate_id_error(
                        asset_kind,
                        summary["id"],
                        [previous, path],
                    )
                locations[key] = path
                result.append(summary)
        return sorted(result, key=lambda item: (item["kind"], item["name"], item["id"]))

    def read(self, kind: str, asset_id: str) -> dict[str, Any]:
        asset_kind = self._kind(kind)
        path = self._find(asset_kind, asset_id)
        if path is None:
            raise StructuredAssetError("资产不存在", code="ASSET_NOT_FOUND")
        content = path.read_text(encoding="utf-8")
        return self._read_content(asset_kind, path, content)

    def _read_content(
        self,
        asset_kind: str,
        path: Path,
        content: str,
    ) -> dict[str, Any]:
        if asset_kind == "progression":
            data = yaml.safe_load(content) or {}
            if not isinstance(data, dict):
                raise StructuredAssetError("成长体系文件格式无效", code="INVALID_ASSET")
            return {
                "kind": asset_kind,
                "id": str(data.get("id") or path.stem),
                "name": str(data.get("name") or path.stem),
                "data": data,
                "body_markdown": "",
                "raw_text": content,
                "path": self._relative(path),
                "revision": self.fingerprint(content),
            }
        meta, body = parse_toml_front_matter(content)
        clean_body = strip_front_matter_padding(body if meta else content)
        display_name = str(meta.get("name") or self._markdown_title(content) or path.stem)
        data = dict(meta)
        data.setdefault("name", display_name)
        return {
            "kind": asset_kind,
            "id": str(meta.get("id") or path.stem),
            "name": display_name,
            "data": data,
            "body_markdown": clean_body,
            "raw_text": content,
            "path": self._relative(path),
            "revision": self.fingerprint(content),
        }

    def create(self, kind: str, payload: dict[str, Any]) -> dict[str, Any]:
        asset_kind = self._kind(kind)
        asset_id = self._asset_id(payload.get("id"))
        if self._find(asset_kind, asset_id) is not None:
            raise StructuredAssetError("同 ID 资产已存在", code="ASSET_CONFLICT")
        if asset_kind == "progression":
            path = self._directory(asset_kind) / f"{asset_id}.yaml"
            data = self._progression_payload(asset_id, payload.get("data") or payload)
            content = yaml.safe_dump(data, allow_unicode=True, sort_keys=False)
        else:
            path = self._directory(asset_kind) / f"{asset_id}.md"
            meta = {
                "id": asset_id,
                **self._allowed_fields(asset_kind, payload.get("data") or payload),
            }
            meta = self._related_last(meta)
            body = str(payload.get("body_markdown") or "")
            if asset_kind == "character":
                content = normalize_character_document(
                    compose_toml_document(meta, body),
                    fallback_id=asset_id,
                    fallback_name=str(meta.get("name") or asset_id),
                    fallback_description=str(meta.get("summary") or ""),
                )
            else:
                content = normalize_world_entity_document(
                    compose_toml_document(meta, body),
                    fallback_id=asset_id,
                    fallback_name=str(meta.get("name") or asset_id),
                    fallback_summary=str(meta.get("summary") or ""),
                    default_type=str(meta.get("type") or meta.get("kind") or "concept"),
                )
        self._commit(path, content, operation=f"asset_create:{asset_kind}:{asset_id}")
        return self.read(asset_kind, asset_id)

    def update(
        self,
        kind: str,
        asset_id: str,
        payload: dict[str, Any],
        *,
        expected_revision: str,
    ) -> dict[str, Any]:
        preview = self.preview_update(
            kind,
            asset_id,
            payload,
            expected_revision=expected_revision,
        )
        asset_kind = str(preview["kind"])
        clean_id = str(preview["id"])
        path = Path(preview["absolute_path"])
        content = str(preview["after_content"])
        self._commit(
            path,
            content,
            operation=f"asset_update:{asset_kind}:{clean_id}",
            expected_revision=expected_revision,
        )
        return self.read(asset_kind, clean_id)

    def preview_update(
        self,
        kind: str,
        asset_id: str,
        payload: dict[str, Any],
        *,
        expected_revision: str,
    ) -> dict[str, Any]:
        """Validate an asset update and render its exact canonical result without writing."""
        asset_kind = self._kind(kind)
        clean_id = self._asset_id(asset_id)
        path = self._find(asset_kind, clean_id)
        if path is None:
            raise StructuredAssetError("资产不存在", code="ASSET_NOT_FOUND")
        current = path.read_text(encoding="utf-8")
        if not expected_revision or expected_revision != self.fingerprint(current):
            raise StructuredAssetError(
                "资产已在其他位置修改，请重新载入",
                code="ASSET_CONFLICT",
                recoverable=True,
            )
        if "raw_text" in payload:
            content = self._validated_raw_content(
                asset_kind,
                clean_id,
                str(payload.get("raw_text") or ""),
            )
        elif asset_kind == "progression":
            existing = yaml.safe_load(current) or {}
            if not isinstance(existing, dict):
                existing = {}
            merged = {**existing, **dict(payload.get("data") or payload), "id": clean_id}
            content = yaml.safe_dump(
                self._progression_payload(clean_id, merged),
                allow_unicode=True,
                sort_keys=False,
            )
        else:
            meta, body = parse_toml_front_matter(current)
            incoming = payload.get("data") if isinstance(payload.get("data"), dict) else payload
            meta.update(self._allowed_fields(asset_kind, incoming))
            meta["id"] = clean_id
            meta = self._related_last(meta)
            body_markdown = (
                str(payload.get("body_markdown"))
                if "body_markdown" in payload
                else body
            )
            content = compose_toml_document(meta, body_markdown)
            content = (
                normalize_character_document(content, fallback_id=clean_id)
                if asset_kind == "character"
                else normalize_world_entity_document(content, fallback_id=clean_id)
            )
        return {
            "kind": asset_kind,
            "id": clean_id,
            "path": self._relative(path),
            "absolute_path": str(path),
            "before_content": current,
            "after_content": content,
            "before": self._read_content(asset_kind, path, current),
            "after": self._read_content(asset_kind, path, content),
        }

    def _commit(
        self,
        path: Path,
        content: str,
        *,
        operation: str,
        expected_revision: str = "",
    ) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with ProjectWriteLock(self.project_root, self.novel_id, operation=operation):
                if expected_revision:
                    current = path.read_text(encoding="utf-8") if path.exists() else ""
                    if self.fingerprint(current) != expected_revision:
                        raise StructuredAssetError(
                            "资产已在其他位置修改，请重新载入",
                            code="ASSET_CONFLICT",
                            recoverable=True,
                        )
                self._atomic_write(path, content)
        except ProjectBusyError as exc:
            raise StructuredAssetError(str(exc), code="PROJECT_BUSY", recoverable=True) from exc

    def _summary(self, kind: str, path: Path) -> dict[str, Any]:
        content = path.read_text(encoding="utf-8")
        if kind == "progression":
            data = yaml.safe_load(content) or {}
            data = data if isinstance(data, dict) else {}
            stages = data.get("stages") if isinstance(data.get("stages"), list) else []
            return {
                "kind": kind,
                "id": self._asset_id(data.get("id") or path.stem),
                "name": str(data.get("name") or path.stem),
                "summary": str(data.get("summary") or ""),
                "asset_type": str(data.get("kind") or "ability"),
                "tags": [
                    str(item).strip()
                    for item in data.get("tags", [])
                    if str(item).strip()
                ]
                if isinstance(data.get("tags"), list)
                else [],
                "stage_count": len(stages),
                "path": self._relative(path),
            }
        meta, _ = parse_toml_front_matter(content)
        return {
            "kind": kind,
            "id": self._asset_id(meta.get("id") or path.stem),
            "name": str(meta.get("name") or self._markdown_title(content) or path.stem),
            "summary": str(meta.get("summary") or ""),
            "asset_type": str(meta.get("type") or meta.get("kind") or ""),
            "aliases": [
                str(item).strip()
                for item in meta.get("aliases", [])
                if str(item).strip()
            ]
            if isinstance(meta.get("aliases"), list)
            else [],
            "tags": [
                str(item).strip()
                for item in meta.get("tags", [])
                if str(item).strip()
            ]
            if isinstance(meta.get("tags"), list)
            else [],
            "path": self._relative(path),
        }

    @staticmethod
    def _markdown_title(content: str) -> str:
        match = re.search(r"^#\s+(.+?)\s*$", str(content or ""), re.MULTILINE)
        return match.group(1).strip() if match else ""

    def _find(self, kind: str, asset_id: str) -> Path | None:
        clean_id = self._asset_id(asset_id)
        matches: list[Path] = []
        for path in self._paths(kind):
            try:
                summary = self._summary(kind, path)
            except (OSError, StructuredAssetError, yaml.YAMLError):
                continue
            if summary["id"] == clean_id:
                matches.append(path)
        if len(matches) > 1:
            raise self._duplicate_id_error(kind, clean_id, matches)
        return matches[0] if matches else None

    def _paths(self, kind: str) -> list[Path]:
        directory = self._directory(kind)
        if not directory.is_dir():
            return []
        suffixes = {".yaml", ".yml"} if kind == "progression" else {".md"}
        return sorted(
            path
            for path in directory.rglob("*")
            if path.is_file()
            and not path.is_symlink()
            and path.suffix.lower() in suffixes
        )

    def _duplicate_id_error(
        self,
        kind: str,
        asset_id: str,
        paths: list[Path],
    ) -> StructuredAssetError:
        locations = "、".join(self._relative(path) for path in paths)
        return StructuredAssetError(
            f"{kind} 资产 ID {asset_id} 在多个文件中重复：{locations}",
            code="ASSET_CONFLICT",
            recoverable=True,
        )

    def _directory(self, kind: str) -> Path:
        return {
            "character": self.novel_root / "src" / "characters",
            "world": self.novel_root / "src" / "world" / "entities",
            "progression": self.novel_root / "src" / "progression",
        }[kind]

    @staticmethod
    def _allowed_fields(kind: str, value: Any) -> dict[str, Any]:
        if not isinstance(value, dict):
            return {}
        fields = CHARACTER_FIELDS if kind == "character" else WORLD_FIELDS
        return {key: value[key] for key in fields if key in value}

    @staticmethod
    def _related_last(metadata: dict[str, Any]) -> dict[str, Any]:
        ordered = {key: value for key, value in metadata.items() if key != "related"}
        if "related" in metadata:
            ordered["related"] = metadata["related"]
        return ordered

    @staticmethod
    def _progression_payload(asset_id: str, value: Any) -> dict[str, Any]:
        data = dict(value) if isinstance(value, dict) else {}
        name = str(data.get("name") or "").strip()
        kind = str(data.get("kind") or "ability").strip()
        stages = data.get("stages")
        if not name:
            raise StructuredAssetError("成长体系名称不能为空", code="INVALID_ASSET")
        allowed_kinds = {
            "ability",
            "rank",
            "cultivation",
            "career",
            "reputation",
            "curse",
            "custom",
        }
        if kind not in allowed_kinds:
            raise StructuredAssetError("成长体系类型无效", code="INVALID_ASSET")
        if not isinstance(stages, list) or not stages:
            raise StructuredAssetError("成长体系至少需要一个阶段", code="INVALID_ASSET")
        normalized: list[dict[str, Any]] = []
        seen: set[str] = set()
        for raw in stages:
            if not isinstance(raw, dict):
                raise StructuredAssetError("成长阶段必须是对象", code="INVALID_ASSET")
            stage_id = StructuredAssetService._asset_id(raw.get("id"))
            if stage_id in seen:
                raise StructuredAssetError("成长阶段 ID 不能重复", code="INVALID_ASSET")
            seen.add(stage_id)
            stage_name = str(raw.get("name") or "").strip()
            if not stage_name:
                raise StructuredAssetError("成长阶段名称不能为空", code="INVALID_ASSET")
            normalized.append(
                {
                    **raw,
                    "id": stage_id,
                    "name": stage_name,
                    "requirements": [
                        str(item).strip()
                        for item in raw.get("requirements", [])
                        if str(item).strip()
                    ]
                    if isinstance(raw.get("requirements", []), list)
                    else [],
                }
            )
        return {
            **data,
            "id": asset_id,
            "name": name,
            "kind": kind,
            "summary": str(data.get("summary") or ""),
            "stages": normalized,
        }

    @staticmethod
    def _validated_raw_content(kind: str, asset_id: str, content: str) -> str:
        if not content.strip():
            raise StructuredAssetError("资产原文不能为空", code="INVALID_ASSET")
        if kind == "progression":
            try:
                data = yaml.safe_load(content)
            except yaml.YAMLError as exc:
                raise StructuredAssetError("成长体系 YAML 无效", code="INVALID_ASSET") from exc
            if not isinstance(data, dict):
                raise StructuredAssetError("成长体系文件格式无效", code="INVALID_ASSET")
            if str(data.get("id") or "") != asset_id:
                raise StructuredAssetError("原文中的资产 ID 不能改变", code="INVALID_ASSET_ID")
            StructuredAssetService._progression_payload(asset_id, data)
            return content if content.endswith("\n") else content + "\n"
        try:
            metadata, _ = parse_toml_front_matter(content)
        except ValueError as exc:
            raise StructuredAssetError("资产 front matter 无效", code="INVALID_ASSET") from exc
        if not metadata:
            raise StructuredAssetError("资产原文必须包含 TOML front matter", code="INVALID_ASSET")
        if str(metadata.get("id") or "") != asset_id:
            raise StructuredAssetError("原文中的资产 ID 不能改变", code="INVALID_ASSET_ID")
        return content if content.endswith("\n") else content + "\n"

    @staticmethod
    def _kind(value: str) -> str:
        kind = str(value or "").strip()
        if kind not in ASSET_KINDS:
            raise StructuredAssetError("资产类型无效", code="INVALID_ASSET_KIND")
        return kind

    @staticmethod
    def _asset_id(value: Any) -> str:
        asset_id = str(value or "").strip()
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,79}", asset_id) or ".." in asset_id:
            raise StructuredAssetError("资产 ID 格式无效", code="INVALID_ASSET_ID")
        return asset_id

    def _relative(self, path: Path) -> str:
        return path.resolve().relative_to(self.novel_root).as_posix()

    @staticmethod
    def fingerprint(content: str) -> str:
        return "sha256:" + hashlib.sha256(content.encode("utf-8")).hexdigest()

    @staticmethod
    def _atomic_write(path: Path, content: str) -> None:
        temp_path: Path | None = None
        try:
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
                temp_path = Path(handle.name)
            temp_path.replace(path)
        finally:
            if temp_path is not None:
                temp_path.unlink(missing_ok=True)
