"""Task wire DTO contract tests: normalization, phases, result refs, errors."""

from __future__ import annotations

import time
from http import HTTPStatus
from pathlib import Path

import pytest
import yaml

from tools.cli import _save_chapter
from tools.init_project import init_project
from tools.studio import StudioApplication
from tools.studio_contracts import StudioError
from tools.task_runner import PersistentTaskRunner, TaskContext
from tools.task_store import (
    TASK_PHASES,
    TaskStore,
    TaskStoreError,
    normalize_task_record,
    task_result_ref,
)


def _wait_for(store: TaskStore, task_id: str, status: str, timeout: float = 3.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        task = store.load(task_id)
        if task and task.get("status") == status:
            return task
        time.sleep(0.01)
    raise AssertionError(f"task {task_id} did not reach {status}")


def _writer(root: Path, args: dict) -> dict:
    path = _save_chapter(root, "demo", args["chapter_id"], "第一章", "正文。")
    return {
        "ok": True,
        "chapter_id": args["chapter_id"],
        "title": "第一章",
        "word_count": 3,
        "draft_path": str(path),
    }


def _strip_to_legacy_record(store: TaskStore, task_id: str, *, status: str) -> str:
    """Rewrite a stored snapshot as a pre-upgrade record (no v1 fields)."""
    path = store.snapshot_path(task_id)
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    for key in ("schema_version", "phase", "attempt", "retryable", "error"):
        raw.pop(key, None)
    raw["status"] = status
    path.write_text(yaml.safe_dump(raw, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return path.read_text(encoding="utf-8")


def test_legacy_record_normalizes_without_touching_storage(tmp_path: Path):
    init_project(tmp_path, "demo")
    store = TaskStore(tmp_path, "demo")
    task = store.create("chapter_review", {"chapter_id": "ch_001"}, chapter_id="ch_001")
    stored_before = _strip_to_legacy_record(store, task["task_id"], status="completed")

    loaded = store.load(task["task_id"])

    assert loaded["schema_version"] == "openwrite.task.v0"
    assert loaded["phase"] == "complete"  # only completed maps honestly
    assert loaded["attempt"] == 1
    assert loaded["retryable"] is False  # completed is not failed/interrupted
    assert loaded["error"] is None
    assert loaded["progress"] is None
    # Normalization is pure: the stored YAML keeps its legacy shape.
    assert store.snapshot_path(task["task_id"]).read_text(encoding="utf-8") == stored_before


def test_legacy_phase_mapping_is_conservative() -> None:
    for status, expected in (
        ("completed", "complete"),
        ("pending", None),
        ("running", None),
        ("awaiting_confirmation", None),
        ("failed", None),
        ("cancelled", None),
        ("interrupted", None),
    ):
        record = normalize_task_record({"task_id": "tsk_x", "status": status})
        assert record["phase"] == expected, status
        assert record["schema_version"] == "openwrite.task.v0"
    # failed/interrupted legacy records default to retryable, others do not.
    assert normalize_task_record({"status": "failed"})["retryable"] is True
    assert normalize_task_record({"status": "interrupted"})["retryable"] is True
    assert normalize_task_record({"status": "pending"})["retryable"] is False
    # Explicitly persisted values always win over defaults.
    kept = normalize_task_record({"status": "failed", "phase": "model", "attempt": 3})
    assert kept["phase"] == "model"
    assert kept["attempt"] == 3


def test_new_records_are_v1_and_surface_is_self_describing(tmp_path: Path):
    init_project(tmp_path, "demo")
    app = StudioApplication(tmp_path, writer_executor=_writer)
    try:
        created = app.create_task(
            {"type": "chapter_write", "input": {"chapter_id": "ch_001", "target_words": 10}}
        )
        deadline = time.monotonic() + 3
        surface = app.task_surface()
        while surface["counts"]["completed"] < 1 and time.monotonic() < deadline:
            time.sleep(0.01)
            surface = app.task_surface()

        assert surface["schema_version"] == "openwrite.task-surface.v1"
        assert surface["phase_order"] == list(TASK_PHASES)
        entry = next(t for t in surface["tasks"] if t["task_id"] == created["task_id"])
        assert entry["schema_version"] == "openwrite.task.v1"
        assert entry["status"] == "completed"
        assert entry["phase"] == "complete"
        assert entry["phase_index"] == surface["phase_order"].index("complete")
        assert entry["progress"] is None  # never a fabricated number
        assert entry["result_ref"] == {"type": "chapter", "id": "ch_001"}
        assert entry["attempt"] == 1
        assert entry["retryable"] is True
        assert entry["cancel_requested"] is False
        assert entry["chapter_id"] == "ch_001"
        assert entry["error"] is None
        for key in ("created_at", "updated_at", "started_at", "completed_at", "input_summary"):
            assert key in entry

        detail = app.get_task(created["task_id"])["task"]
        assert detail["schema_version"] == "openwrite.task.v1"
        assert detail["phase_index"] == entry["phase_index"]
        assert detail["result_ref"] == entry["result_ref"]
        assert detail["progress"] is None
    finally:
        if app._task_runner is not None:
            app._task_runner.shutdown(wait=True)


def test_failed_stage_records_phase_at_failure_time(tmp_path: Path):
    init_project(tmp_path, "demo")

    def handler(payload: dict, context: TaskContext) -> dict:
        del payload
        context.phase("preparing", "assembling")
        context.phase("model", "calling model")
        raise RuntimeError("模型超时")

    runner = PersistentTaskRunner(tmp_path, "demo", handlers={"chapter_write": handler})
    try:
        task = runner.submit("chapter_write", {"chapter_id": "ch_001"})
        failed = _wait_for(runner.store, task["task_id"], "failed")
        error = failed["error"]
        assert error["code"] == "TASK_FAILED"
        assert error["message"] == "模型超时"
        assert error["recoverable"] is True
        assert error["failed_stage"] == "model"
    finally:
        runner.shutdown(wait=True)


def test_result_ref_derivation():
    assert task_result_ref({"type": "chapter_write", "chapter_id": "ch_001", "result": {}}) == {
        "type": "chapter",
        "id": "ch_001",
    }
    assert task_result_ref(
        {"type": "chapter_review", "chapter_id": "ch_002", "result": {"score": 90}}
    ) == {"type": "review", "id": "ch_002"}
    assert task_result_ref(
        {"type": "revision_selection", "result": {"proposal_id": "rev_abc"}}
    ) == {"type": "revision", "id": "rev_abc"}
    assert task_result_ref(
        {"type": "revision_from_review", "result": {"proposal_id": "rev_def"}}
    ) == {"type": "revision", "id": "rev_def"}
    assert task_result_ref({"type": "research", "result": {"report_id": "rep_1"}}) == {
        "type": "research_report",
        "id": "rep_1",
    }
    assert task_result_ref({"type": "model_benchmark", "result": {"run_id": "bench_1"}}) == {
        "type": "benchmark_run",
        "id": "bench_1",
    }
    # Types without a reference and missing data are None, never fabricated.
    assert task_result_ref({"type": "source_operation", "result": {}}) is None
    assert task_result_ref({"type": "reference_operation", "result": {}}) is None
    assert task_result_ref({"type": "manuscript_import", "result": {"arc_id": "arc_001"}}) is None
    assert task_result_ref({"type": "research", "result": {}}) is None
    assert task_result_ref({"type": "continuous_write", "chapter_id": "", "result": {}}) is None


def test_cancel_is_idempotent_on_terminal_tasks(tmp_path: Path):
    init_project(tmp_path, "demo")
    store = TaskStore(tmp_path, "demo")
    task = store.create("chapter_review", {"chapter_id": "ch_001"})

    cancelled = store.request_cancel(task["task_id"])
    again = store.request_cancel(task["task_id"])

    assert cancelled["status"] == "cancelled"
    assert again["status"] == "cancelled"
    assert again["completed_at"] == cancelled["completed_at"]
    assert again["cancel_requested"] is True
    # A second cancel persists nothing new.
    events = [event["event"] for event in store.events(task["task_id"])]
    assert events.count("task_cancelled") == 1


def test_retry_and_confirm_reject_invalid_states(tmp_path: Path):
    init_project(tmp_path, "demo")
    app = StudioApplication(tmp_path, writer_executor=_writer)
    try:
        created = app.create_task(
            {"type": "chapter_write", "input": {"chapter_id": "ch_001", "target_words": 10}}
        )
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            task = app.get_task(created["task_id"])["task"]
            if task["status"] == "completed":
                break
            time.sleep(0.01)
        else:
            raise AssertionError("task did not complete")

        with pytest.raises(StudioError) as retry_error:
            app.retry_task(created["task_id"], {})
        assert retry_error.value.status == HTTPStatus.CONFLICT
        assert retry_error.value.code == "TASK_CONFLICT"

        with pytest.raises(StudioError) as confirm_error:
            app.confirm_task(created["task_id"], {})
        assert confirm_error.value.status == HTTPStatus.CONFLICT
        assert confirm_error.value.code == "TASK_CONFLICT"
    finally:
        if app._task_runner is not None:
            app._task_runner.shutdown(wait=True)


def test_on_change_listener_fires_and_never_breaks_transitions(tmp_path: Path):
    init_project(tmp_path, "demo")
    calls: list[str] = []

    def listener(record: dict) -> None:
        calls.append(str(record.get("status")))
        raise RuntimeError("listener boom")

    store = TaskStore(tmp_path, "demo", on_change=listener)
    task = store.create("chapter_review", {"chapter_id": "ch_001"})
    transitioned = store.transition(task["task_id"], status="running", phase="reading")
    store.request_cancel(task["task_id"])

    assert calls == ["pending", "running", "running"]
    assert transitioned["status"] == "running"
    assert store.load(task["task_id"])["cancel_requested"] is True
    # Reads never notify.
    assert calls == ["pending", "running", "running"]


def test_store_without_listener_is_unaffected(tmp_path: Path):
    init_project(tmp_path, "demo")
    store = TaskStore(tmp_path, "demo")
    assert store.on_change is None
    task = store.create("chapter_review", {"chapter_id": "ch_001"})
    store.transition(task["task_id"], status="completed", phase="complete")
    assert store.load(task["task_id"])["status"] == "completed"


def test_task_store_error_still_raises_for_invalid_transition(tmp_path: Path):
    init_project(tmp_path, "demo")
    store = TaskStore(tmp_path, "demo")
    with pytest.raises(TaskStoreError):
        store.transition("tsk_missing_12345678", status="completed")


def test_report_progress_persists_real_units_and_ratio(tmp_path: Path):
    init_project(tmp_path, "demo")

    def handler(payload: dict, context: TaskContext) -> dict:
        del payload
        context.phase("model", "生成候选")
        context.report_progress(0, 2, "candidates")
        context.report_progress(2, 2, "candidates")
        context.phase("validating", "盲评")
        context.report_progress(1, 3, "evaluations")
        return {"ok": True}

    runner = PersistentTaskRunner(tmp_path, "demo", handlers={"model_benchmark": handler})
    try:
        task = runner.submit("model_benchmark", {"chapter_id": "ch_001"})
        done = _wait_for(runner.store, task["task_id"], "completed")
        assert done["progress"] == {
            "completed_units": 1,
            "total_units": 3,
            "ratio": 0.3333,
            "unit_kind": "evaluations",
        }
    finally:
        runner.shutdown(wait=True)


def test_report_progress_rejects_bad_units_and_stays_null_safe(tmp_path: Path):
    init_project(tmp_path, "demo")
    runner = PersistentTaskRunner(tmp_path, "demo", handlers={"model_benchmark": lambda p, c: {}})
    try:
        task = runner.submit("model_benchmark", {"chapter_id": "ch_001"})
        _wait_for(runner.store, task["task_id"], "completed")
        context = TaskContext(runner.store, task["task_id"])
        with pytest.raises(TaskStoreError):
            context.report_progress(1, 2, "unknown")
        with pytest.raises(TaskStoreError):
            context.report_progress(-1, 2, "candidates")
        # A zero total yields a null ratio instead of a division error.
        context.report_progress(0, 0, "candidates")
        progress = runner.store.load(task["task_id"])["progress"]
        assert progress == {
            "completed_units": 0,
            "total_units": 0,
            "ratio": None,
            "unit_kind": "candidates",
        }
    finally:
        runner.shutdown(wait=True)


def test_non_mapping_progress_reads_back_as_null(tmp_path: Path):
    init_project(tmp_path, "demo")
    store = TaskStore(tmp_path, "demo")
    task = store.create("model_benchmark", {"chapter_id": "ch_001"})
    path = store.snapshot_path(task["task_id"])
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    raw["progress"] = 42
    path.write_text(yaml.safe_dump(raw, allow_unicode=True, sort_keys=False), encoding="utf-8")

    assert store.load(task["task_id"])["progress"] is None
