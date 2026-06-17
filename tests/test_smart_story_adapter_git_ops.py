from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from tools.smart_story_adapter.config import AdapterError
from tools.smart_story_adapter.git_ops import GitOps


def test_authenticated_url_injects_credentials_correctly() -> None:
    url = GitOps.authenticated_url(
        "https://git.example.com/owner/repo.git",
        "agent-user",
        "secret-token",
    )

    assert url == "https://agent-user:secret-token@git.example.com/owner/repo.git"


def test_git_ops_runs_clone_checkout_commit_and_push(tmp_path: Path) -> None:
    calls: list[list[str]] = []

    def fake_run(args: list[str], cwd: Path | None = None) -> str:
        calls.append(args)
        if args[0] == "git" and args[1] == "clone":
            (tmp_path / "workspace" / ".git").mkdir(parents=True)
        if args == ["git", "rev-parse", "HEAD"]:
            return "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\n"
        if args == ["git", "status", "--porcelain"]:
            return " M some_file.txt\n"
        return ""

    ops = GitOps(run_command=fake_run)
    ops.clone_or_fetch(tmp_path / "workspace", "https://git.example.com/owner/repo.git", "agent", "token", "main")
    sha = ops.commit_all(tmp_path / "workspace", "Smart Story run 10")
    ops.push(tmp_path / "workspace", "main")

    assert ["git", "checkout", "main"] in calls
    assert ["git", "config", "user.name", "agent"] in calls
    assert ["git", "config", "user.email", "agent@smart-story.ai"] in calls
    assert ["git", "add", "-A"] in calls
    assert ["git", "commit", "-m", "Smart Story run 10"] in calls
    assert ["git", "push", "origin", "main"] in calls
    assert sha == "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"


def test_git_ops_skips_commit_if_no_changes(tmp_path: Path) -> None:
    calls: list[list[str]] = []

    def fake_run(args: list[str], cwd: Path | None = None) -> str:
        calls.append(args)
        if args == ["git", "rev-parse", "HEAD"]:
            return "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb\n"
        if args == ["git", "status", "--porcelain"]:
            return ""  # No changes
        return ""

    ops = GitOps(run_command=fake_run)
    sha = ops.commit_all(tmp_path / "workspace", "Empty commit message")

    assert ["git", "add", "-A"] in calls
    assert ["git", "commit", "-m", "Empty commit message"] not in calls
    assert sha == "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"


def test_run_error_mapping_and_scrubbing() -> None:
    ops = GitOps()
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = subprocess.CompletedProcess(
            args=["git", "clone", "https://user:pass@example.com/repo.git"],
            returncode=128,
            stderr="fatal: Authentication failed for 'https://user:pass@example.com/repo.git'",
            stdout=""
        )
        with pytest.raises(AdapterError) as exc:
            ops._run(["git", "clone", "https://user:pass@example.com/repo.git"])

        assert exc.value.failure_category == "runtime_crashed"
        assert "user:pass" not in str(exc.value)
        assert "https://***@example.com" in str(exc.value)


def test_run_error_mapping_conflict() -> None:
    ops = GitOps()
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = subprocess.CompletedProcess(
            args=["git", "push"],
            returncode=1,
            stderr="error: failed to push some refs ... non-fast-forward",
            stdout=""
        )
        with pytest.raises(AdapterError) as exc:
            ops._run(["git", "push"])

        assert exc.value.failure_category == "git_conflict"
