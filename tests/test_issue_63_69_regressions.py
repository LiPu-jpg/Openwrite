"""Regression tests for issues #63/#66, #64/#67, #68, #69.

- #63/#66: residual ``project.lock`` left by a dead process must be detected
  as stale on every platform (Windows ``os.kill(pid, 0)`` semantics differ)
  and busy errors must carry owner context.
- #64/#67: ``continuous_write`` must tolerate per-chapter failures up to
  ``max_failures`` instead of aborting the whole queue, and the writer must
  keep the final draft when length retries are exhausted.
- #68: the benchmark artifact contract must accept live statuses.
- #69: the reviewer output budget floor must rise once a reasoning model is
  observed, and truncation must retry with a raised budget before bisecting.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

import tools.project_lock as project_lock
from tools.contracts_generated import validate_benchmark_v1
from tools.init_project import init_project
from tools.project_lock import ProjectBusyError, ProjectWriteLock

from test_studio_tasks import _save_accepted_chapter, _wait
from tools.studio import StudioApplication


def _write_lock_file(lock: ProjectWriteLock, payload: dict) -> None:
    lock.path.parent.mkdir(parents=True, exist_ok=True)
    lock.path.write_text(json.dumps(payload), encoding="utf-8")


def test_dead_pid_lock_is_stale_and_auto_cleaned(tmp_path: Path) -> None:
    lock = ProjectWriteLock(tmp_path, "demo", operation="write:ch_001")
    _write_lock_file(
        lock,
        {
            "token": "dead",
            "pid": 999999,  # no such process on any test platform
            "operation": "write:ch_013",
            "created_at": "2026-10-08T04:03:55+00:00",
        },
    )
    assert lock._is_stale()
    lock.acquire()
    try:
        assert lock.acquired
        assert not lock.path.exists() or json.loads(lock.path.read_text(encoding="utf-8"))["token"] == lock.token
    finally:
        lock.release()


def test_live_owner_lock_is_not_stale_and_busy_error_has_context(tmp_path: Path) -> None:
    owner = ProjectWriteLock(tmp_path, "demo", operation="write:ch_002")
    owner.acquire()
    try:
        contender = ProjectWriteLock(tmp_path, "demo", operation="review:ch_002")
        assert not contender._is_stale()
        with pytest.raises(ProjectBusyError) as excinfo:
            contender.acquire()
        message = str(excinfo.value)
        assert "write:ch_002" in message
        assert "pid=" in message
        assert "project.lock" in message
    finally:
        owner.release()


def test_unverifiable_liveness_falls_back_to_grace(monkeypatch, tmp_path: Path) -> None:
    lock = ProjectWriteLock(tmp_path, "demo", operation="write:ch_003")
    _write_lock_file(
        lock,
        {"token": "x", "pid": 4242, "operation": "write:ch_003", "created_at": "2026-10-08T04:03:55+00:00"},
    )

    def _boom(pid: int) -> bool:
        raise OSError("cannot probe")

    monkeypatch.setattr(project_lock, "_process_alive", _boom)
    # Fresh lock + unverifiable owner: inside the init grace ⇒ not stale yet.
    assert not lock._is_stale()
    # Age the lock past the grace ⇒ treat as stale (never deadlock writing).
    old = time.time() - (lock.initialization_grace_seconds + 5)
    monkeypatch.setattr(project_lock.Path, "stat", lambda self: type("S", (), {"st_mtime": old})())
    assert lock._is_stale()


def test_process_alive_dead_pid_is_false() -> None:
    assert project_lock._process_alive(999999) is False
    assert project_lock._process_alive(1) in (True, False)  # platform dependent, must not raise


_BENCHMARK_BASE = {
    "schema_version": "openwrite.model-benchmark.v1",
    "run_id": "bench_test123",
    "task_id": "tsk_1",
    "task_type": "chapter",
    "status": "completed",
    "context_hash": "h",
    "config": {"writer_profile_ids": ["p"], "reviewer_profile_ids": ["r"]},
    "candidates": [],
    "evaluations": [],
}


@pytest.mark.parametrize("status", ["running", "cancelling", "cancelled", "partial", "failed"])
def test_benchmark_contract_accepts_live_and_terminal_statuses(status: str) -> None:
    record = {**_BENCHMARK_BASE, "status": status}
    validate_benchmark_v1(json.loads(json.dumps(record)))


def test_reviewer_budget_floor_rises_after_reasoning_observed() -> None:
    from tools.agent.reviewer import ReviewerAgent

    reviewer = ReviewerAgent.__new__(ReviewerAgent)

    class _Config:
        max_tokens = 24000
        context_tokens = 64000

    class _Client:
        config = _Config()

    class _Ctx:
        client = _Client()

    reviewer.ctx = _Ctx()
    assert reviewer._audit_output_budget([1, 2]) == 4096
    reviewer._note_reasoning_usage({"completion_tokens_details": {"reasoning_tokens": 3078}})
    assert reviewer._audit_output_budget([1, 2]) == 16384
    assert reviewer._raised_budget(4096) == 8192


def test_continuous_write_continues_after_single_chapter_failure(tmp_path: Path) -> None:
    init_project(tmp_path, "demo")
    failed_once: set[str] = set()

    def writer(root: Path, args: dict) -> dict:
        chapter_id = args["chapter_id"]
        if chapter_id == "ch_001" and chapter_id not in failed_once:
            failed_once.add(chapter_id)
            raise RuntimeError("transient provider timeout")
        number = int(chapter_id.split("_")[1])
        path, acceptance = _save_accepted_chapter(root, chapter_id, f"第{number}章", f"第{number}章正文。")
        return {
            "ok": True,
            "chapter_id": chapter_id,
            "title": f"第{number}章",
            "word_count": 6,
            "draft_path": str(path),
            "acceptance": acceptance,
        }

    def reviewer(root: Path, args: dict) -> dict:
        del root
        return {
            "ok": True,
            "chapter_id": args["chapter_id"],
            "passed": True,
            "score": 90,
            "issues": 0,
            "issue_details": [],
        }

    app = StudioApplication(tmp_path, writer_executor=writer, review_executor=reviewer)
    outline = app.read_document("src/outline.md")
    app.write_document(
        outline["path"],
        """# 第一卷

## 第一幕

### 第一节

#### 第一章

开场。

#### 第二章

推进。
""",
        outline["version"],
    )
    try:
        task = app.create_task(
            {
                "type": "continuous_write",
                "input": {"max_chapters": 2, "minimum_review_score": 82, "max_failures": 2},
            }
        )
        completed = _wait(app, task["task_id"], {"completed"}, timeout=10)
        result = completed["result"]
        assert [item["chapter_id"] for item in result["completed_chapters"]] == ["ch_001", "ch_002"]
        assert [item["chapter_id"] for item in result["failed_chapters"]] == ["ch_001"]
        assert result["stop_reason"] == "max_chapters_reached"
    finally:
        if app._task_runner is not None:
            app._task_runner.shutdown(wait=True)


def test_continuous_write_max_failures_returns_gracefully(tmp_path: Path) -> None:
    init_project(tmp_path, "demo")

    def writer(root: Path, args: dict) -> dict:
        del root, args
        raise RuntimeError("persistent provider failure")

    def reviewer(root: Path, args: dict) -> dict:
        del root, args
        raise AssertionError("review must not run when writes fail")

    app = StudioApplication(tmp_path, writer_executor=writer, review_executor=reviewer)
    outline = app.read_document("src/outline.md")
    app.write_document(
        outline["path"],
        """# 第一卷

## 第一幕

### 第一节

#### 第一章

开场。

#### 第二章

推进。
""",
        outline["version"],
    )
    try:
        task = app.create_task(
            {
                "type": "continuous_write",
                "input": {"max_chapters": 2, "minimum_review_score": 82, "max_failures": 3},
            }
        )
        completed = _wait(app, task["task_id"], {"completed"}, timeout=10)
        result = completed["result"]
        assert result["stop_reason"] == "max_failures_reached"
        assert len(result["failed_chapters"]) == 3
    finally:
        if app._task_runner is not None:
            app._task_runner.shutdown(wait=True)
