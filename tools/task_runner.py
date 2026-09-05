"""Single-novel persistent task runner with cooperative cancellation."""

from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
from threading import Lock
from typing import Any

from tools.task_store import TASK_PHASES, TaskStore, TaskStoreError


class TaskCancelled(RuntimeError):
    pass


class TaskAwaitingConfirmation(RuntimeError):
    def __init__(self, result: dict[str, Any]):
        super().__init__("任务等待用户确认")
        self.result = result


TaskHandler = Callable[[dict[str, Any], "TaskContext"], dict[str, Any]]

PROGRESS_UNIT_KINDS = ("candidates", "evaluations", "chapters", "files")


def _record_origin(record: dict[str, Any]) -> dict[str, Any] | None:
    """Carry workspace origin markers into a retried/confirmed task."""
    origin = {
        key: record.get(key)
        for key in ("workspace_id", "session_id", "context_epoch")
        if record.get(key) is not None
    }
    return origin or None


class TaskContext:
    def __init__(self, store: TaskStore, task_id: str):
        self.store = store
        self.task_id = task_id
        self.phase_name = "queued"

    def phase(self, phase: str, note: str = "") -> None:
        if phase not in TASK_PHASES:
            raise TaskStoreError(f"Invalid task phase: {phase}")
        self.phase_name = phase
        self.store.transition(
            self.task_id,
            phase=phase,
            event="task_phase_changed",
            details={"note": note},
        )

    def cancellation_requested(self) -> bool:
        task = self.store.load(self.task_id)
        return bool(task and task.get("cancel_requested"))

    def checkpoint(self) -> None:
        if self.phase_name != "committing" and self.cancellation_requested():
            raise TaskCancelled("任务已取消")

    def progress_callback(self, phase: str, note: str = "") -> None:
        self.phase(phase, note)

    def report_progress(
        self,
        completed_units: int,
        total_units: int,
        unit_kind: str,
    ) -> None:
        """Persist real unit accounting (never derived from polling or time)."""
        if unit_kind not in PROGRESS_UNIT_KINDS:
            raise TaskStoreError(f"Invalid progress unit kind: {unit_kind}")
        completed = int(completed_units)
        total = int(total_units)
        if completed < 0 or total < 0:
            raise TaskStoreError("Progress units must be non-negative")
        self.store.transition(
            self.task_id,
            updates={
                "progress": {
                    "completed_units": completed,
                    "total_units": total,
                    "ratio": round(completed / total, 4) if total else None,
                    "unit_kind": unit_kind,
                }
            },
            event="task_progress_updated",
            details={
                "unit_kind": unit_kind,
                "completed_units": completed,
                "total_units": total,
            },
        )

    def persist_progress(self, result: dict[str, Any]) -> None:
        self.store.transition(
            self.task_id,
            updates={"result": result},
            event="task_progress_saved",
            details={"completed": len(result.get("completed_chapters") or [])},
        )

    def await_confirmation(self, result: dict[str, Any]) -> None:
        raise TaskAwaitingConfirmation(result)


class PersistentTaskRunner:
    """Run one task at a time for one novel and persist every state change."""

    def __init__(
        self,
        project_root: Path,
        novel_id: str,
        *,
        handlers: dict[str, TaskHandler] | None = None,
        on_change: Callable[[dict[str, Any]], None] | None = None,
    ):
        self.project_root = Path(project_root).resolve()
        self.novel_id = str(novel_id)
        self.store = TaskStore(self.project_root, self.novel_id, on_change=on_change)
        self.handlers = dict(handlers or {})
        self._executor = ThreadPoolExecutor(
            max_workers=1,
            thread_name_prefix=f"openwrite-{self.novel_id}-task",
        )
        self._futures: dict[str, Future[Any]] = {}
        self._lock = Lock()
        self.recovered = self.store.recover_interrupted()

    def register(self, task_type: str, handler: TaskHandler) -> None:
        self.handlers[task_type] = handler

    def submit(
        self,
        task_type: str,
        payload: dict[str, Any],
        *,
        chapter_id: str = "",
        input_summary: str = "",
        retryable: bool = True,
        retry_of: str = "",
        attempt: int = 1,
        origin: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if task_type not in self.handlers:
            raise TaskStoreError(f"No handler registered for task type: {task_type}")
        task = self.store.create(
            task_type,
            payload,
            chapter_id=chapter_id,
            input_summary=input_summary,
            retryable=retryable,
            retry_of=retry_of,
            attempt=attempt,
            origin=origin,
        )
        self._schedule(str(task["task_id"]))
        return task

    def retry(self, task_id: str) -> dict[str, Any]:
        previous = self.store.load(task_id)
        if previous is None:
            raise TaskStoreError("Task not found")
        if not previous.get("retryable"):
            raise TaskStoreError("Task is not retryable")
        if previous.get("status") not in {"failed", "cancelled", "interrupted"}:
            raise TaskStoreError("Only failed, cancelled or interrupted tasks can be retried")
        payload = self.store.materialize_input(previous)
        result = self.store.materialize_result(previous)
        if result.get("completed_chapters"):
            payload["_already_completed"] = list(result["completed_chapters"])
        if result.get("usage"):
            payload["_already_used"] = dict(result["usage"])
        return self.submit(
            str(previous["type"]),
            payload,
            chapter_id=str(previous.get("chapter_id") or ""),
            input_summary=str(previous.get("input_summary") or ""),
            retryable=True,
            retry_of=task_id,
            attempt=int(previous.get("attempt") or 1) + 1,
            origin=_record_origin(previous),
        )

    def cancel(self, task_id: str) -> dict[str, Any]:
        task = self.store.request_cancel(task_id)
        if task.get("status") == "cancelled":
            with self._lock:
                future = self._futures.get(task_id)
            if future is not None:
                future.cancel()
        return task

    def confirm(self, task_id: str) -> dict[str, Any]:
        previous = self.store.load(task_id)
        if previous is None:
            raise TaskStoreError("Task not found")
        if previous.get("status") != "awaiting_confirmation":
            raise TaskStoreError("Task is not awaiting confirmation")
        payload = self.store.materialize_input(previous)
        result = self.store.materialize_result(previous)
        payload["_already_completed"] = list(result.get("completed_chapters") or [])
        if result.get("usage"):
            payload["_already_used"] = dict(result["usage"])
        return self.submit(
            str(previous["type"]),
            payload,
            chapter_id=str(previous.get("chapter_id") or ""),
            input_summary=str(previous.get("input_summary") or ""),
            retryable=bool(previous.get("retryable")),
            retry_of=task_id,
            attempt=int(previous.get("attempt") or 1) + 1,
            origin=_record_origin(previous),
        )

    def shutdown(self, *, wait: bool = False) -> None:
        self._executor.shutdown(wait=wait, cancel_futures=False)

    def _schedule(self, task_id: str) -> None:
        future = self._executor.submit(self._run, task_id)
        with self._lock:
            self._futures[task_id] = future
        future.add_done_callback(lambda completed: self._forget(task_id, completed))

    def _forget(self, task_id: str, future: Future[Any]) -> None:
        del future
        with self._lock:
            self._futures.pop(task_id, None)

    def _run(self, task_id: str) -> None:
        task = self.store.load(task_id)
        if task is None or task.get("status") != "pending":
            return
        handler = self.handlers.get(str(task.get("type") or ""))
        if handler is None:
            self.store.transition(
                task_id,
                status="failed",
                updates={
                    "error": {
                        "code": "TASK_HANDLER_MISSING",
                        "message": "任务处理器不存在",
                        "recoverable": False,
                        "failed_stage": task.get("phase") or None,
                    }
                },
                event="task_failed",
            )
            return
        context = TaskContext(self.store, task_id)
        try:
            self.store.transition(
                task_id,
                status="running",
                phase="reading",
                event="task_started",
            )
            context.phase_name = "reading"
            context.checkpoint()
            payload = self.store.materialize_input(task)
            result = handler(payload, context)
            context.checkpoint()
            self.store.transition(
                task_id,
                status="completed",
                phase="complete",
                updates={"result": result, "error": None},
                event="task_completed",
            )
        except TaskAwaitingConfirmation as exc:
            self.store.transition(
                task_id,
                status="awaiting_confirmation",
                updates={"result": exc.result, "error": None},
                event="task_awaiting_confirmation",
            )
        except TaskCancelled as exc:
            self.store.transition(
                task_id,
                status="cancelled",
                updates={
                    "error": {
                        "code": "TASK_CANCELLED",
                        "message": str(exc),
                        "recoverable": True,
                    }
                },
                event="task_cancelled",
            )
        except Exception as exc:
            self.store.transition(
                task_id,
                status="failed",
                updates={
                    "error": {
                        "code": str(getattr(exc, "code", "TASK_FAILED")),
                        "message": str(exc),
                        "recoverable": bool(task.get("retryable")),
                        "failed_stage": context.phase_name or None,
                    }
                },
                event="task_failed",
            )
