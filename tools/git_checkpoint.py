"""Conservative Git checkpoints for explicitly private content repositories."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tools.project_registry import load_project_metadata

ALLOWED_PREFIXES = {"outline", "character", "world", "chapter", "checkpoint"}


@dataclass(frozen=True)
class CheckpointResult:
    ok: bool
    committed: bool
    message: str
    revision: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "committed": self.committed,
            "message": self.message,
            "revision": self.revision,
        }


class GitCheckpointManager:
    """Commit confirmed novel assets without ever crossing repository boundaries."""

    def __init__(self, project_root: Path) -> None:
        self.project_root = Path(project_root).resolve()

    def status(self) -> dict[str, Any]:
        metadata = load_project_metadata(self.project_root)
        git_config = metadata.get("git", {}) if isinstance(metadata.get("git"), dict) else {}
        eligible, reason = self._eligibility(metadata)
        return {
            "eligible": eligible,
            "enabled": eligible and bool(git_config.get("auto_checkpoint")),
            "reason": reason,
            "project_type": str(metadata.get("project_type") or "unmarked"),
            "repository_visibility": str(metadata.get("repository_visibility") or "unknown"),
        }

    def checkpoint(self, paths: list[str], message: str) -> CheckpointResult:
        metadata = load_project_metadata(self.project_root)
        eligible, reason = self._eligibility(metadata)
        git_config = metadata.get("git", {}) if isinstance(metadata.get("git"), dict) else {}
        if not eligible:
            return CheckpointResult(False, False, reason)
        if not bool(git_config.get("auto_checkpoint")):
            return CheckpointResult(True, False, "自动 checkpoint 未启用")
        safe_paths = self._safe_paths(paths)
        if not safe_paths:
            return CheckpointResult(False, False, "没有位于作品资产范围内的已确认文件")
        prefix = message.partition(":")[0].strip().lower()
        if prefix not in ALLOWED_PREFIXES:
            return CheckpointResult(False, False, "提交信息必须使用作品 checkpoint 前缀")
        self._git("add", "--", *safe_paths)
        staged = self._git("diff", "--cached", "--name-only").stdout.strip()
        if not staged:
            return CheckpointResult(True, False, "没有需要归档的已确认变更")
        self._git("commit", "-m", message)
        revision = self._git("rev-parse", "--short", "HEAD").stdout.strip()
        return CheckpointResult(True, True, "作品 checkpoint 已创建", revision)

    def _eligibility(self, metadata: dict[str, Any]) -> tuple[bool, str]:
        if metadata.get("project_type") != "novel-content":
            return False, "项目未标记为独立作品仓库"
        if metadata.get("repository_visibility") != "private":
            return False, "自动 checkpoint 仅允许显式标记的私密仓库"
        try:
            result = self._git("rev-parse", "--show-toplevel", check=False)
        except subprocess.TimeoutExpired:
            return False, "Git 检查超时，自动 checkpoint 已禁用"
        except (OSError, subprocess.SubprocessError):
            return False, "Git 不可用，自动 checkpoint 已禁用"
        if result.returncode != 0:
            return False, "当前作品目录不是 Git 仓库"
        try:
            git_root = Path(result.stdout.strip()).resolve()
        except OSError:
            return False, "无法识别 Git 根目录"
        if git_root != self.project_root:
            return False, "作品目录必须是独立 Git 根目录，禁止提交到上层框架仓库"
        return True, "可在确认资产修改后创建 checkpoint"

    def _safe_paths(self, paths: list[str]) -> list[str]:
        allowed_roots = {"novel_config.yaml", "data", "notes", "references", ".openwrite"}
        result: list[str] = []
        for raw in paths:
            relative = Path(str(raw))
            if relative.is_absolute() or ".." in relative.parts or not relative.parts:
                continue
            if relative.parts[0] not in allowed_roots:
                continue
            candidate = (self.project_root / relative).resolve()
            if candidate == self.project_root or self.project_root not in candidate.parents:
                continue
            result.append(relative.as_posix())
        return sorted(set(result))

    def _git(self, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", *args],
            cwd=self.project_root,
            stdin=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            check=check,
            timeout=10,
        )
