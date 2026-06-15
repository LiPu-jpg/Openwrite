from __future__ import annotations

from pathlib import Path

from tools.smart_story_adapter.config import AdapterConfig
from tools.smart_story_adapter.runner import SmartStoryAdapterRunner
from tests.test_smart_story_adapter_config import valid_env


class FakeMcp:
    def __init__(self) -> None:
        self.progress: list[dict] = []
        self.imports: list[dict] = []

    def report_progress(self, payload: dict) -> dict:
        self.progress.append(payload)
        return {"accepted": True}

    def import_private_draft(self, payload: dict) -> dict:
        self.imports.append(payload)
        return {"private_draft_id": len(self.imports), "duplicate": False}


class FakeGit:
    def __init__(self, workspace: Path) -> None:
        self.workspace = workspace

    def clone_or_fetch(self, workspace: Path, clone_url: str, username: str, password: str, branch: str) -> None:
        workspace.mkdir(parents=True, exist_ok=True)
        (workspace / "novel_config.yaml").write_text("novel_id: demo\n", encoding="utf-8")

    def verify_commit(self, workspace: Path, expected_sha: str | None) -> None:
        return None

    def commit_all(self, workspace: Path, message: str) -> str:
        return "eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee"

    def push(self, workspace: Path, branch: str) -> None:
        return None


def test_runner_reports_progress_imports_draft_and_succeeds(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    mcp = FakeMcp()

    def fake_openwrite(root: Path, config: AdapterConfig) -> int:
        chapter = root / "data" / "novels" / "demo" / "data" / "manuscript" / "arc_001" / "ch_001.md"
        chapter.parent.mkdir(parents=True)
        chapter.write_text("# Chương 1\n\nNội dung bản nháp tiếng Việt đủ dài để import.", encoding="utf-8")
        return 0

    runner = SmartStoryAdapterRunner(
        config=AdapterConfig.from_env(valid_env() | {"OPENWRITE_WORKSPACE": str(workspace)}),
        mcp=mcp,
        git_ops=FakeGit(workspace),
        run_openwrite=fake_openwrite,
    )

    assert runner.run() == 0
    assert [item["status"] for item in mcp.progress] == ["preparing", "running", "submitting", "succeeded"]
    assert len(mcp.imports) == 1
    assert mcp.imports[0]["output_key"] == "chapter-number-1"


def test_runner_handles_missing_config(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    mcp = FakeMcp()

    class FailingGit(FakeGit):
        def clone_or_fetch(self, workspace: Path, clone_url: str, username: str, password: str, branch: str) -> None:
            workspace.mkdir(parents=True, exist_ok=True)
            # Do not create novel_config.yaml

    runner = SmartStoryAdapterRunner(
        config=AdapterConfig.from_env(valid_env() | {"OPENWRITE_WORKSPACE": str(workspace)}),
        mcp=mcp,
        git_ops=FailingGit(workspace),
        run_openwrite=lambda root, config: 0,
    )

    assert runner.run() == 1
    assert mcp.progress[-1]["status"] == "failed"
    assert mcp.progress[-1]["failure_category"] == "configuration_missing"
    assert "Workspace thiếu novel_config.yaml hợp lệ" in mcp.progress[-1]["message"]


def test_runner_handles_invalid_yaml(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    mcp = FakeMcp()

    class InvalidYamlGit(FakeGit):
        def clone_or_fetch(self, workspace: Path, clone_url: str, username: str, password: str, branch: str) -> None:
            workspace.mkdir(parents=True, exist_ok=True)
            (workspace / "novel_config.yaml").write_text("novel_id: [unclosed list", encoding="utf-8")

    runner = SmartStoryAdapterRunner(
        config=AdapterConfig.from_env(valid_env() | {"OPENWRITE_WORKSPACE": str(workspace)}),
        mcp=mcp,
        git_ops=InvalidYamlGit(workspace),
        run_openwrite=lambda root, config: 0,
    )

    assert runner.run() == 1
    assert mcp.progress[-1]["status"] == "failed"
    assert mcp.progress[-1]["failure_category"] == "configuration_missing"
    assert "Workspace thiếu novel_config.yaml hợp lệ" in mcp.progress[-1]["message"]


def test_runner_handles_openwrite_oserror(tmp_path: Path, monkeypatch) -> None:
    workspace = tmp_path / "workspace"
    mcp = FakeMcp()

    import subprocess
    def failing_run(*args, **kwargs):
        raise OSError("Command not found")
    
    monkeypatch.setattr(subprocess, "run", failing_run)

    runner = SmartStoryAdapterRunner(
        config=AdapterConfig.from_env(valid_env() | {"OPENWRITE_WORKSPACE": str(workspace)}),
        mcp=mcp,
        git_ops=FakeGit(workspace),
    )

    assert runner.run() == 1
    assert mcp.progress[-1]["status"] == "failed"
    assert mcp.progress[-1]["failure_category"] == "runtime_crashed"
    assert "Không thể thực thi openwrite" in mcp.progress[-1]["message"]
