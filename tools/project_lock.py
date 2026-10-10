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


def _process_alive(pid: int) -> bool:
    """Best-effort liveness probe that is correct on Windows.

    ``os.kill(pid, 0)`` is POSIX-only semantics: on Windows ``0`` equals
    ``signal.CTRL_C_EVENT``, so the call raises ``OSError [WinError 87]``
    for dead PIDs instead of ``ProcessLookupError`` and is not a probe at
    all. Use the process API there instead.
    """
    if os.name == "nt":
        import ctypes

        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        STILL_ACTIVE = 259
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            return False
        try:
            code = ctypes.c_ulong()
            if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
                return False
            return code.value == STILL_ACTIVE
        finally:
            kernel32.CloseHandle(handle)

    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


class ProjectWriteLock:
    def __init__(
        self,
        project_root: Path,
        novel_id: str,
        *,
        operation: str,
        stale_after_seconds: int = 6 * 60 * 60,
        initialization_grace_seconds: float = 5.0,
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
        self.initialization_grace_seconds = initialization_grace_seconds
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
                raise ProjectBusyError(self._busy_message(owner))
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
        raise ProjectBusyError(f"项目锁无法恢复：{self.path}（持有者仍存活且未超时）")

    def _busy_message(self, owner: dict[str, object]) -> str:
        operation = str(owner.get("operation") or "未知任务")
        pid = owner.get("pid")
        created_at = str(owner.get("created_at") or "未知时间")
        return (
            f"项目正由另一个进程执行：{operation}"
            f"（pid={pid}，起始 {created_at}，锁文件 {self.path}）"
            f"；如确认该任务已终止，可删除锁文件后重试"
        )

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
            return age > self.initialization_grace_seconds
        try:
            pid = int(raw_pid)
        except (TypeError, ValueError):
            return age > self.initialization_grace_seconds
        if pid <= 0:
            return True
        try:
            alive = _process_alive(pid)
        except OSError:
            # 无法验证持有者存活 ⇒ 按陈旧处理（受初始化宽限约束），
            # 宁可误清理也不要让残留锁卡死写作。
            return age > self.initialization_grace_seconds
        return not alive

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
