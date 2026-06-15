from __future__ import annotations

import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Protocol

import yaml

from .config import AdapterConfig, AdapterError
from .git_ops import GitOps
from .mcp import McpClient
from .outputs import collect_private_drafts


class ProgressClient(Protocol):
    def report_progress(self, payload: dict) -> dict: ...
    def import_private_draft(self, payload: dict) -> dict: ...


RunOpenWrite = Callable[[Path, AdapterConfig], int]


class SmartStoryAdapterRunner:
    def __init__(
        self,
        config: AdapterConfig,
        mcp: ProgressClient | None = None,
        git_ops: GitOps | None = None,
        run_openwrite: RunOpenWrite | None = None,
    ) -> None:
        self.config = config
        self.workspace = Path(config.workspace)
        self.mcp = mcp or McpClient(config.mcp_endpoint, config.mcp_token)
        self.git_ops = git_ops or GitOps()
        self.run_openwrite = run_openwrite or default_run_openwrite

    def run(self) -> int:
        try:
            self._progress("preparing", 1, "Adapter started.")
            self.git_ops.clone_or_fetch(
                self.workspace,
                self.config.git_clone_url,
                self.config.git_username,
                self.config.git_password,
                self.config.source_branch,
            )
            self.git_ops.verify_commit(self.workspace, self.config.source_commit_sha)
            novel_id = self._novel_id()
            self._progress("running", 20, "Running OpenWrite.")
            code = self.run_openwrite(self.workspace, self.config)
            if code != 0:
                raise AdapterError("OpenWrite command failed", "runtime_crashed", "OpenWrite không tạo được bản nháp.")
            final_commit = self.git_ops.commit_all(self.workspace, self._commit_message())
            self.git_ops.push(self.workspace, self.config.source_branch)
            self._progress("submitting", 80, "Submitting private drafts.", commit_sha=final_commit)
            output_ids = []
            for draft in collect_private_drafts(self.workspace, novel_id, final_commit, self.config.source_branch):
                draft["agent_project_id"] = self.config.agent_project_id
                result = self.mcp.import_private_draft(draft)
                output_ids.append({"type": "private_draft", "id": result.get("private_draft_id"), "duplicate": result.get("duplicate", False)})
            self._progress("succeeded", 100, "Completed.", commit_sha=final_commit, output_ids=output_ids)
            return 0
        except AdapterError as exc:
            try:
                self._progress("failed", 100, exc.user_message, failure_category=exc.failure_category, user_message=exc.user_message)
            except Exception:
                pass  # Best-effort: don't let progress reporting mask the original error
            return 1

    def _novel_id(self) -> str:
        config_path = self.workspace / "novel_config.yaml"
        try:
            text = config_path.read_text(encoding="utf-8")
            data = yaml.safe_load(text) or {}
        except (OSError, yaml.YAMLError) as exc:
            raise AdapterError(f"Failed to read novel_config: {exc}", "configuration_missing", "Workspace thiếu novel_config.yaml hợp lệ.") from exc
        novel_id = str(data.get("novel_id", "")).strip()
        if not novel_id:
            raise AdapterError("novel_config.yaml missing novel_id", "configuration_missing", "Workspace thiếu novel_id.")
        return novel_id

    def _progress(self, status: str, percent: int, message: str, **extra: object) -> None:
        payload = {
            "agent_project_id": self.config.agent_project_id,
            "status": status,
            "progress_percent": percent,
            "message": message,
            "heartbeat_at": datetime.now(timezone.utc).isoformat(),
        }
        payload.update({key: value for key, value in extra.items() if value is not None})
        self.mcp.report_progress(payload)

    def _commit_message(self) -> str:
        return (
            f"Smart Story hosted run {self.config.agent_run_id}\n\n"
            f"Agent project: {self.config.agent_project_id}\n"
            f"Story: {self.config.story_id}\n"
            f"Task: {self.config.task_type}\n"
            f"Source commit: {self.config.source_commit_sha or 'unknown'}"
        )


def default_run_openwrite(workspace: Path, config: AdapterConfig) -> int:
    env = os.environ.copy()
    env.update(config.openwrite_env())
    try:
        process = subprocess.run(
            ["openwrite", "multi-write", "next", "--no-review"],
            cwd=workspace,
            env=env,
            check=False,
        )
        return process.returncode
    except OSError as exc:
        raise AdapterError(f"Failed to execute openwrite: {exc}", "runtime_crashed", "Không thể thực thi openwrite.") from exc
