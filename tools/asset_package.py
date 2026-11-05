"""Portable, reviewable OpenWrite asset packages."""

from __future__ import annotations

import difflib
import hashlib
import os
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any

import yaml

from tools.frontmatter import compose_toml_document, parse_toml_front_matter
from tools.project_lock import ProjectBusyError, ProjectWriteLock
from tools.structured_assets import ASSET_KINDS, StructuredAssetService

PACKAGE_FORMAT = "openwrite-asset-package"
PACKAGE_VERSION = 1
MAX_PACKAGE_FILES = 500
MAX_UNCOMPRESSED_BYTES = 25 * 1024 * 1024


class AssetPackageError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        code: str = "ASSET_PACKAGE_FAILED",
        recoverable: bool = False,
        details: dict[str, Any] | None = None,
    ):
        super().__init__(message)
        self.code = code
        self.recoverable = recoverable
        self.details = details or {}


class AssetPackageService:
    def __init__(self, project_root: Path, novel_id: str):
        self.project_root = Path(project_root).resolve()
        self.novel_id = str(novel_id)
        self.novel_root = self.project_root / "data" / "novels" / self.novel_id
        self.assets = StructuredAssetService(self.project_root, self.novel_id)

    def export(
        self,
        output: Path,
        *,
        selections: list[dict[str, str]] | None = None,
    ) -> dict[str, Any]:
        selected = self._select_assets(selections)
        if not selected:
            raise AssetPackageError("没有可导出的资产", code="ASSET_SELECTION_EMPTY")
        entries: dict[str, bytes] = {}
        manifest_assets: list[dict[str, Any]] = []
        package_ids = {item["id"] for item in selected}
        relations: list[dict[str, Any]] = []
        for item in selected:
            kind = str(item["kind"])
            asset_id = str(item["id"])
            source = (self.novel_root / str(item["path"])).resolve()
            content = source.read_bytes()
            extension = ".yaml" if kind == "progression" else ".md"
            archive_path = f"assets/{self._archive_kind(kind)}/{asset_id}{extension}"
            dependencies, asset_relations = self._dependencies(kind, content.decode("utf-8"))
            relations.extend(
                {"source": asset_id, **relation}
                for relation in asset_relations
            )
            entries[archive_path] = content
            manifest_assets.append(
                {
                    "id": asset_id,
                    "kind": kind,
                    "name": item.get("name") or asset_id,
                    "path": archive_path,
                    "sha256": hashlib.sha256(content).hexdigest(),
                    "dependencies": sorted(set(dependencies)),
                    "packaged_dependencies": sorted(set(dependencies) & package_ids),
                }
            )
        manifest = {
            "format": PACKAGE_FORMAT,
            "version": PACKAGE_VERSION,
            "source_novel": self.novel_id,
            "exported_at": self._now(),
            "assets": manifest_assets,
        }
        entries["manifest.yaml"] = yaml.safe_dump(
            manifest, allow_unicode=True, sort_keys=False
        ).encode("utf-8")
        entries["relations.yaml"] = yaml.safe_dump(
            {"relations": relations}, allow_unicode=True, sort_keys=False
        ).encode("utf-8")
        output = Path(output).expanduser().resolve()
        if output.suffix != ".zip" and not output.name.endswith(".owasset.zip"):
            output = output.with_suffix(".owasset.zip")
        output.parent.mkdir(parents=True, exist_ok=True)
        temp_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="wb",
                dir=output.parent,
                prefix=f".{output.name}.",
                suffix=".tmp",
                delete=False,
            ) as handle:
                temp_path = Path(handle.name)
            with zipfile.ZipFile(temp_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                for name, content in sorted(entries.items()):
                    archive.writestr(name, content)
            temp_path.replace(output)
        finally:
            if temp_path is not None:
                temp_path.unlink(missing_ok=True)
        return {
            "path": str(output),
            "asset_count": len(manifest_assets),
            "assets": manifest_assets,
            "sha256": self._file_fingerprint(output),
        }

    def preview_import(self, source: Path) -> dict[str, Any]:
        source_path = Path(source).expanduser().resolve()
        package = self._read_package(source_path)
        existing = {
            (str(item["kind"]), str(item["id"])): item
            for item in self.assets.list()
        }
        package_ids = {str(item["id"]) for item in package["manifest"]["assets"]}
        assets: list[dict[str, Any]] = []
        all_dependencies: set[str] = set()
        for item in package["manifest"]["assets"]:
            asset_id = str(item["id"])
            kind = str(item["kind"])
            content = package["entries"][str(item["path"])].decode("utf-8")
            current = existing.get((kind, asset_id))
            dependencies = {str(value) for value in item.get("dependencies", [])}
            all_dependencies.update(dependencies)
            status = "conflict" if current else "new"
            diff = ""
            if current:
                current_path = self.novel_root / str(current["path"])
                current_content = current_path.read_text(encoding="utf-8")
                diff = "".join(
                    difflib.unified_diff(
                        current_content.splitlines(keepends=True),
                        content.splitlines(keepends=True),
                        fromfile=f"current/{asset_id}",
                        tofile=f"package/{asset_id}",
                    )
                )[:6000]
            assets.append(
                {
                    **item,
                    "status": status,
                    "existing": current,
                    "diff": diff,
                    "default_action": "skip" if current else "import",
                }
            )
        existing_ids = {asset_id for _, asset_id in existing}
        missing_dependencies = sorted(all_dependencies - package_ids - existing_ids)
        return {
            "format": PACKAGE_FORMAT,
            "version": PACKAGE_VERSION,
            "source_novel": package["manifest"].get("source_novel"),
            "package_path": str(source_path),
            "package_sha256": self._file_fingerprint(source_path),
            "assets": assets,
            "counts": {
                "new": sum(item["status"] == "new" for item in assets),
                "conflict": sum(item["status"] == "conflict" for item in assets),
            },
            "missing_dependencies": missing_dependencies,
            "relations": package["relations"],
        }

    def import_package(
        self,
        source: Path,
        *,
        expected_sha256: str,
        resolutions: dict[str, dict[str, str]] | None = None,
        allow_missing_dependencies: bool = False,
    ) -> dict[str, Any]:
        source_path = Path(source).expanduser().resolve()
        current_sha = self._file_fingerprint(source_path)
        if not expected_sha256 or expected_sha256 != current_sha:
            raise AssetPackageError(
                "资产包已变化，请重新预览",
                code="ASSET_PACKAGE_CONFLICT",
                recoverable=True,
            )
        preview = self.preview_import(source_path)
        if preview["missing_dependencies"] and not allow_missing_dependencies:
            raise AssetPackageError(
                "资产包存在缺失依赖",
                code="ASSET_DEPENDENCY_MISSING",
                recoverable=True,
                details={"missing_dependencies": preview["missing_dependencies"]},
            )
        package = self._read_package(source_path)
        decisions = resolutions or {}
        # A dependency that is in the package but skipped by a resolution is just
        # as missing as one that was never packaged: `missing_dependencies` only
        # checked package/existing membership, so the gate passed and the imported
        # asset was left pointing at an asset that does not exist.
        preview_skipped = {
            str(item["id"])
            for item in preview["assets"]
            if str((decisions.get(str(item["id"])) or {}).get("action") or item["default_action"]) == "skip"
        }
        packaged_dependencies = {
            str(value)
            for item in package["manifest"]["assets"]
            for value in (item.get("dependencies") or [])
        }
        dangling = sorted(
            set(preview["missing_dependencies"]) | (packaged_dependencies & preview_skipped)
        )
        if dangling and not allow_missing_dependencies:
            raise AssetPackageError(
                "资产包存在缺失依赖",
                code="ASSET_DEPENDENCY_MISSING",
                recoverable=True,
                details={"missing_dependencies": dangling},
            )
        id_map: dict[str, str] = {}
        skipped: list[str] = []
        for item in preview["assets"]:
            asset_id = str(item["id"])
            decision = decisions.get(asset_id, {})
            action = str(decision.get("action") or item["default_action"])
            if action == "skip":
                skipped.append(asset_id)
                continue
            if item["status"] == "conflict" and action not in {"replace", "rename"}:
                raise AssetPackageError(
                    f"资产 {asset_id} 的冲突尚未解决",
                    code="ASSET_CONFLICT",
                    recoverable=True,
                )
            if action == "rename":
                new_id = StructuredAssetService._asset_id(decision.get("new_id"))
                if (
                    self._find_any(str(item["kind"]), new_id) is not None
                    or new_id in id_map.values()
                ):
                    raise AssetPackageError(
                        f"重命名目标已存在: {new_id}",
                        code="ASSET_CONFLICT",
                        recoverable=True,
                    )
                id_map[asset_id] = new_id
            elif action in {"replace", "import"}:
                id_map[asset_id] = asset_id
            else:
                raise AssetPackageError("未知导入决策", code="INVALID_IMPORT_RESOLUTION")
        writes: dict[Path, bytes] = {}
        imported: list[dict[str, Any]] = []
        preview_assets = {
            (str(item["kind"]), str(item["id"])): item
            for item in preview["assets"]
        }
        for item in package["manifest"]["assets"]:
            old_id = str(item["id"])
            if old_id in skipped:
                continue
            new_id = id_map[old_id]
            kind = str(item["kind"])
            raw = package["entries"][str(item["path"])].decode("utf-8")
            rendered = self._remap_content(kind, raw, old_id, new_id, id_map)
            preview_item = preview_assets[(kind, old_id)]
            current = preview_item.get("existing")
            target = (
                (self.novel_root / str(current["path"])).resolve()
                if current and new_id == old_id
                else self._target_path(kind, new_id)
            )
            if target in writes:
                raise AssetPackageError("多个资产映射到同一目标", code="ASSET_CONFLICT")
            writes[target] = rendered.encode("utf-8")
            imported.append(
                {
                    "source_id": old_id,
                    "id": new_id,
                    "kind": kind,
                    "path": target.relative_to(self.novel_root).as_posix(),
                    "replaced": target.exists(),
                }
            )
        self._atomic_apply(writes)
        receipt = self._save_receipt(source_path, current_sha, imported, skipped, id_map)
        return {
            "imported": imported,
            "skipped": skipped,
            "id_map": id_map,
            "receipt_path": receipt.relative_to(self.novel_root).as_posix(),
        }

    def _select_assets(
        self, selections: list[dict[str, str]] | None
    ) -> list[dict[str, Any]]:
        available = self.assets.list()
        if selections is None:
            return available
        keys = {(str(item.get("kind")), str(item.get("id"))) for item in selections}
        selected = [item for item in available if (item["kind"], item["id"]) in keys]
        if len(selected) != len(keys):
            missing = sorted(keys - {(item["kind"], item["id"]) for item in selected})
            raise AssetPackageError(
                "部分导出资产不存在",
                code="ASSET_NOT_FOUND",
                details={"missing": missing},
            )
        return selected

    def _read_package(self, path: Path) -> dict[str, Any]:
        if not path.is_file():
            raise AssetPackageError("资产包不存在", code="ASSET_PACKAGE_NOT_FOUND")
        if path.stat().st_size > MAX_UNCOMPRESSED_BYTES:
            raise AssetPackageError("资产包文件过大", code="INVALID_ASSET_PACKAGE")
        try:
            archive = zipfile.ZipFile(path, "r")
        except (OSError, zipfile.BadZipFile) as exc:
            raise AssetPackageError("资产包不是有效 ZIP", code="INVALID_ASSET_PACKAGE") from exc
        with archive:
            infos = archive.infolist()
            if len(infos) > MAX_PACKAGE_FILES:
                raise AssetPackageError("资产包文件数量过多", code="INVALID_ASSET_PACKAGE")
            if sum(info.file_size for info in infos) > MAX_UNCOMPRESSED_BYTES:
                raise AssetPackageError("资产包解压后过大", code="INVALID_ASSET_PACKAGE")
            entries: dict[str, bytes] = {}
            for info in infos:
                self._validate_archive_path(info.filename)
                if info.is_dir():
                    continue
                entries[info.filename] = archive.read(info)
        try:
            manifest = yaml.safe_load(entries["manifest.yaml"]) or {}
        except (KeyError, yaml.YAMLError, UnicodeDecodeError) as exc:
            raise AssetPackageError("资产包清单无效", code="INVALID_ASSET_PACKAGE") from exc
        if not isinstance(manifest, dict):
            raise AssetPackageError("资产包清单无效", code="INVALID_ASSET_PACKAGE")
        if manifest.get("format") != PACKAGE_FORMAT or manifest.get("version") != PACKAGE_VERSION:
            raise AssetPackageError("资产包格式或版本不受支持", code="INVALID_ASSET_PACKAGE")
        assets = manifest.get("assets")
        if not isinstance(assets, list):
            raise AssetPackageError("资产包缺少资产列表", code="INVALID_ASSET_PACKAGE")
        seen: set[tuple[str, str]] = set()
        for item in assets:
            if not isinstance(item, dict):
                raise AssetPackageError("资产清单条目无效", code="INVALID_ASSET_PACKAGE")
            asset_id = StructuredAssetService._asset_id(item.get("id"))
            kind = str(item.get("kind") or "")
            if kind not in ASSET_KINDS:
                raise AssetPackageError("资产类型无效", code="INVALID_ASSET_PACKAGE")
            key = (kind, asset_id)
            if key in seen:
                raise AssetPackageError("资产 ID 重复", code="INVALID_ASSET_PACKAGE")
            seen.add(key)
            asset_path = str(item.get("path") or "")
            self._validate_archive_path(asset_path)
            content = entries.get(asset_path)
            if content is None:
                raise AssetPackageError("资产文件缺失", code="INVALID_ASSET_PACKAGE")
            if hashlib.sha256(content).hexdigest() != item.get("sha256"):
                raise AssetPackageError("资产校验和不匹配", code="INVALID_ASSET_PACKAGE")
        try:
            relations_data = yaml.safe_load(entries.get("relations.yaml", b"")) or {}
        except (yaml.YAMLError, UnicodeDecodeError):
            relations_data = {}
        relations = relations_data.get("relations", []) if isinstance(relations_data, dict) else []
        return {"manifest": manifest, "entries": entries, "relations": relations}

    def _atomic_apply(self, writes: dict[Path, bytes]) -> None:
        backups: dict[Path, bytes | None] = {}
        temporary: dict[Path, Path] = {}
        try:
            with ProjectWriteLock(
                self.project_root,
                self.novel_id,
                operation="asset_package_import",
            ):
                for target, content in writes.items():
                    target.parent.mkdir(parents=True, exist_ok=True)
                    backups[target] = target.read_bytes() if target.is_file() else None
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
                        temporary[target] = Path(handle.name)
                for target, temp_path in temporary.items():
                    temp_path.replace(target)
        except ProjectBusyError as exc:
            raise AssetPackageError(str(exc), code="PROJECT_BUSY", recoverable=True) from exc
        except Exception:
            for target, previous in backups.items():
                if previous is None:
                    target.unlink(missing_ok=True)
                else:
                    self._atomic_bytes(target, previous)
            raise
        finally:
            for temp_path in temporary.values():
                temp_path.unlink(missing_ok=True)

    def _remap_content(
        self,
        kind: str,
        content: str,
        old_id: str,
        new_id: str,
        id_map: dict[str, str],
    ) -> str:
        if kind == "progression":
            data = yaml.safe_load(content) or {}
            if not isinstance(data, dict):
                raise AssetPackageError("成长体系内容无效", code="INVALID_ASSET_PACKAGE")
            data["id"] = new_id
            return yaml.safe_dump(data, allow_unicode=True, sort_keys=False)
        meta, body = parse_toml_front_matter(content)
        meta["id"] = new_id
        related = meta.get("related")
        if isinstance(related, list):
            for relation in related:
                if isinstance(relation, dict) and relation.get("target") in id_map:
                    relation["target"] = id_map[str(relation["target"])]
        for field in ("organization", "progression_system"):
            if meta.get(field) in id_map:
                meta[field] = id_map[str(meta[field])]
        return compose_toml_document(meta, body)

    def _dependencies(self, kind: str, content: str) -> tuple[list[str], list[dict[str, Any]]]:
        if kind == "progression":
            return [], []
        meta, _ = parse_toml_front_matter(content)
        dependencies: list[str] = []
        relations: list[dict[str, Any]] = []
        related = meta.get("related")
        if isinstance(related, list):
            for relation in related:
                if not isinstance(relation, dict) or not relation.get("target"):
                    continue
                target = str(relation["target"])
                dependencies.append(target)
                relations.append({str(key): value for key, value in relation.items()})
        for field in ("organization", "progression_system"):
            if meta.get(field):
                dependencies.append(str(meta[field]))
        return dependencies, relations

    def _find_any(self, kind: str, asset_id: str) -> dict[str, Any] | None:
        return next(
            (
                item
                for item in self.assets.list(kind)
                if item["id"] == asset_id
            ),
            None,
        )

    def _target_path(self, kind: str, asset_id: str) -> Path:
        extension = ".yaml" if kind == "progression" else ".md"
        directory = {
            "character": self.novel_root / "src" / "characters",
            "world": self.novel_root / "src" / "world" / "entities",
            "progression": self.novel_root / "src" / "progression",
        }[kind]
        return directory / f"{asset_id}{extension}"

    def _save_receipt(
        self,
        source: Path,
        fingerprint: str,
        imported: list[dict[str, Any]],
        skipped: list[str],
        id_map: dict[str, str],
    ) -> Path:
        root = self.novel_root / "data" / "asset_imports"
        root.mkdir(parents=True, exist_ok=True)
        receipt = root / f"import_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.yaml"
        payload = {
            "source_name": source.name,
            "source_sha256": fingerprint,
            "imported_at": self._now(),
            "imported": imported,
            "skipped": skipped,
            "id_map": id_map,
        }
        self._atomic_bytes(
            receipt,
            yaml.safe_dump(payload, allow_unicode=True, sort_keys=False).encode("utf-8"),
        )
        return receipt

    @staticmethod
    def _validate_archive_path(value: str) -> None:
        path = PurePosixPath(str(value or ""))
        if not value or path.is_absolute() or ".." in path.parts or "\\" in value:
            raise AssetPackageError("资产包包含不安全路径", code="INVALID_ASSET_PACKAGE")

    @staticmethod
    def _archive_kind(kind: str) -> str:
        return {"character": "characters", "world": "world", "progression": "progression"}[kind]

    @staticmethod
    def _file_fingerprint(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return "sha256:" + digest.hexdigest()

    @staticmethod
    def _atomic_bytes(path: Path, content: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temp_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="wb",
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

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()
