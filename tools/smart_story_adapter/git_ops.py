from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Callable
from urllib.parse import quote, urlsplit, urlunsplit

from .config import AdapterError


RunCommand = Callable[[list[str], Path | None], str]


class GitOps:
    def __init__(self, run_command: RunCommand | None = None) -> None:
        self.run_command = run_command or self._run

    @staticmethod
    def authenticated_url(clone_url: str, username: str, password: str) -> str:
        parsed = urlsplit(clone_url)
        credentials = f"{quote(username, safe='')}:{quote(password, safe='')}"
        return urlunsplit((parsed.scheme, f"{credentials}@{parsed.netloc}", parsed.path, parsed.query, parsed.fragment))

    def clone_or_fetch(self, workspace: Path, clone_url: str, username: str, password: str, branch: str) -> None:
        auth_url = self.authenticated_url(clone_url, username, password)
        if not (workspace / ".git").exists():
            workspace.parent.mkdir(parents=True, exist_ok=True)
            self.run_command(["git", "clone", "--branch", branch, auth_url, str(workspace)], None)
        else:
            self.run_command(["git", "fetch", "origin", branch], workspace)
        self.run_command(["git", "checkout", branch], workspace)

    def verify_commit(self, workspace: Path, expected_sha: str | None) -> None:
        if not expected_sha:
            return
        actual = self.run_command(["git", "rev-parse", "HEAD"], workspace).strip()
        if actual != expected_sha:
            raise AdapterError(
                f"Workspace HEAD {actual} does not match expected {expected_sha}",
                "git_conflict",
                "Nhánh truyện đã thay đổi trước khi AI bắt đầu chạy.",
            )

    def commit_all(self, workspace: Path, message: str) -> str:
        self.run_command(["git", "add", "-A"], workspace)
        status = self.run_command(["git", "status", "--porcelain"], workspace)
        if status.strip():
            self.run_command(["git", "commit", "-m", message], workspace)
        return self.run_command(["git", "rev-parse", "HEAD"], workspace).strip()

    def push(self, workspace: Path, branch: str) -> None:
        self.run_command(["git", "push", "origin", branch], workspace)

    def _run(self, args: list[str], cwd: Path | None = None) -> str:
        process = subprocess.run(args, cwd=cwd, check=False, text=True, capture_output=True)
        if process.returncode != 0:
            stderr = process.stderr.strip()
            stderr = re.sub(r"://[^@]*@", "://***@", stderr)
            category = "git_conflict" if "non-fast-forward" in stderr or "fetch first" in stderr else "runtime_crashed"
            raise AdapterError(stderr or "git command failed", category, "Không thể cập nhật kho truyện.")
        return process.stdout
