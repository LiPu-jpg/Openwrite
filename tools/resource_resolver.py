from __future__ import annotations

import os
from importlib import resources
from pathlib import Path


class ResourceResolver:
    def __init__(self, workspace: Path, default_root: Path | None = None) -> None:
        self.workspace = Path(workspace)
        configured = os.getenv("OPENWRITE_RESOURCE_ROOT")
        self.default_root = Path(configured) if configured else default_root

    def path(self, category: str, relative_path: str) -> Path | None:
        workspace_path = self.workspace / category / relative_path
        if workspace_path.exists():
            return workspace_path

        if self.default_root is not None:
            default_path = self.default_root / category / relative_path
            if default_path.exists():
                return default_path

        return None

    def read_text(self, category: str, relative_path: str) -> str:
        resolved = self.path(category, relative_path)
        if resolved is not None and resolved.is_file():
            return resolved.read_text(encoding="utf-8")

        package_root = resources.files("tools").joinpath("resources", "defaults", category, relative_path)
        if package_root.is_file():
            return package_root.read_text(encoding="utf-8")

        return ""
