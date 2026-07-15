"""Cross-process lock for chapter write/review operations."""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from types import TracebackType
from uuid import uuid4


class ProjectBusyError(RuntimeError):
    pass


class ProjectWriteLock:
    def __init__(
        self,
        project_root: Path,
        novel_id: str,
        *,
        operation: str,
        stale_after_seconds: int = 6 * 60 * 60,
    ):
        self.path = (
            Path(project_root).resolve()
            / "data"
            / "novels"
            / novel_id
            / "data"
            / "workflows"
            / "project.lock"
        )
        self.operation = operation
        self.stale_after_seconds = stale_after_seconds
        self.token = uuid4().hex
        self.acquired = False

    def acquire(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        for _ in range(2):
            try:
                descriptor = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            except FileExistsError:
                if self._is_stale():
                    self.path.unlink(missing_ok=True)
                    continue
                owner = self._read_owner()
                operation = str(owner.get("operation") or "未知任务")
                raise ProjectBusyError(f"项目正由另一个进程执行：{operation}")
            payload = {
                "token": self.token,
                "pid": os.getpid(),
                "operation": self.operation,
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False)
                handle.flush()
                os.fsync(handle.fileno())
            self.acquired = True
            return
        raise ProjectBusyError("项目锁无法恢复")

    def release(self) -> None:
        if not self.acquired:
            return
        owner = self._read_owner()
        if owner.get("token") == self.token:
            self.path.unlink(missing_ok=True)
        self.acquired = False

    def _is_stale(self) -> bool:
        try:
            age = time.time() - self.path.stat().st_mtime
        except OSError:
            return True
        if age > self.stale_after_seconds:
            return True
        owner = self._read_owner()
        raw_pid = owner.get("pid")
        if not isinstance(raw_pid, (int, str)):
            return True
        try:
            pid = int(raw_pid)
        except (TypeError, ValueError):
            return True
        if pid <= 0:
            return True
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return True
        except PermissionError:
            return False
        return False

    def _read_owner(self) -> dict[str, object]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return data if isinstance(data, dict) else {}

    def __enter__(self) -> ProjectWriteLock:
        self.acquire()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.release()
