"""Local project discovery and framework/content repository boundaries."""

from __future__ import annotations

import subprocess
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

REGISTRY_LIMIT = 12


def default_registry_path() -> Path:
    return Path.home() / ".config" / "openwrite" / "recent_projects.yaml"


def is_framework_root(path: Path) -> bool:
    """Return whether *path* looks like the OpenWrite source repository."""
    root = Path(path).resolve()
    pyproject = root / "pyproject.toml"
    studio = root / "tools" / "studio.py"
    if not pyproject.is_file() or not studio.is_file():
        return False
    try:
        head = pyproject.read_text(encoding="utf-8")[:2000]
    except OSError:
        return False
    return 'name = "openwrite"' in head.lower()


def is_ephemeral_project_path(path: Path) -> bool:
    """Return whether a project lives under an OS-managed temporary directory."""
    root = Path(path).resolve()
    temporary_roots = {
        Path(tempfile.gettempdir()).resolve(),
        Path("/tmp").resolve(),
        Path("/private/tmp").resolve(),
        Path("/var/tmp").resolve(),
    }
    return any(root == candidate or candidate in root.parents for candidate in temporary_roots)


def project_metadata_path(project_root: Path) -> Path:
    return Path(project_root).resolve() / ".openwrite" / "project.yaml"


def load_project_metadata(project_root: Path) -> dict[str, Any]:
    path = project_metadata_path(project_root)
    if not path.is_file():
        return {}
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return {}
    return payload if isinstance(payload, dict) else {}


def write_content_project_metadata(project_root: Path) -> Path:
    """Create the explicit marker required by private-content automation."""
    path = project_metadata_path(project_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": 1,
        "project_type": "novel-content",
        "repository_visibility": "private",
        "git": {
            "auto_checkpoint": False,
            "checkpoint_on": ["confirmed_asset_change"],
            "debounce_minutes": 15,
        },
    }
    path.write_text(
        yaml.safe_dump(payload, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    return path


def initialize_content_git(project_root: Path) -> bool:
    """Initialize an independent Git repository for a newly created work.

    A nested ``.git`` is intentional when the target sits under another
    repository: content must remain independently checkpointable and must
    never fall back to the OpenWrite framework repository.
    """
    root = Path(project_root).resolve()
    git_path = root / ".git"
    if git_path.is_dir() or git_path.is_file():
        return False
    root.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["git", "init", "--quiet"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )
    return True


@dataclass(frozen=True)
class RecentProject:
    path: str
    title: str
    novel_id: str
    opened_at: str

    def to_dict(self) -> dict[str, str]:
        return {
            "path": self.path,
            "title": self.title,
            "novel_id": self.novel_id,
            "opened_at": self.opened_at,
        }


class ProjectRegistry:
    """Small local-only registry; it never writes into a Git repository."""

    def __init__(self, path: Path | None = None, *, allow_ephemeral: bool = False) -> None:
        self.path = Path(path or default_registry_path()).resolve()
        self.allow_ephemeral = allow_ephemeral

    def list(self) -> list[dict[str, str]]:
        records = self._load()
        available: list[RecentProject] = []
        for record in records:
            root = Path(record.path).resolve()
            if self._should_remember(root) and (root / "novel_config.yaml").is_file():
                available.append(record)
        if available != records:
            self._save(available[:REGISTRY_LIMIT])
        return [record.to_dict() for record in available[:REGISTRY_LIMIT]]

    def remember(self, project_root: Path) -> None:
        root = Path(project_root).resolve()
        if not self._should_remember(root):
            return
        config_path = root / "novel_config.yaml"
        if not config_path.is_file():
            return
        try:
            config = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
        except (OSError, yaml.YAMLError):
            return
        if not isinstance(config, dict) or not config.get("novel_id"):
            return
        record = RecentProject(
            path=str(root),
            title=str(config.get("title") or config["novel_id"]),
            novel_id=str(config["novel_id"]),
            opened_at=datetime.now(timezone.utc).isoformat(),
        )
        records = [item for item in self._load() if item.path != record.path]
        records.insert(0, record)
        self._save(records[:REGISTRY_LIMIT])

    def _should_remember(self, root: Path) -> bool:
        if is_framework_root(root):
            return False
        return self.allow_ephemeral or not is_ephemeral_project_path(root)

    def remove(self, project_path: str) -> None:
        records = [
            item for item in self._load() if item.path != str(Path(project_path).resolve())
        ]
        self._save(records)

    def _load(self) -> list[RecentProject]:
        if not self.path.is_file():
            return []
        try:
            payload = yaml.safe_load(self.path.read_text(encoding="utf-8")) or {}
        except (OSError, yaml.YAMLError):
            return []
        raw_records = payload.get("projects", []) if isinstance(payload, dict) else []
        result: list[RecentProject] = []
        for raw in raw_records if isinstance(raw_records, list) else []:
            if not isinstance(raw, dict) or not raw.get("path"):
                continue
            result.append(
                RecentProject(
                    path=str(raw["path"]),
                    title=str(raw.get("title") or raw.get("novel_id") or "未命名作品"),
                    novel_id=str(raw.get("novel_id") or ""),
                    opened_at=str(raw.get("opened_at") or ""),
                )
            )
        return result

    def _save(self, records: list[RecentProject]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"schema_version": 1, "projects": [item.to_dict() for item in records]}
        self.path.write_text(
            yaml.safe_dump(payload, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )
