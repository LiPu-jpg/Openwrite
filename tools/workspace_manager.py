"""Multi-root workspace routing for OpenWrite Studio.

A single Studio server can serve many canonical project roots at once. Each
request carrying an ``X-OpenWrite-Workspace-Root`` header is routed to a
dedicated per-root ``StudioApplication``; requests without the header keep the
legacy single-project behavior driven by the launch application.
"""

from __future__ import annotations

import os
import threading
from dataclasses import dataclass
from http import HTTPStatus
from pathlib import Path
from typing import Any

from tools.project_registry import is_framework_root
from tools.studio_contracts import StudioError

WORKSPACE_ROOT_HEADER = "X-OpenWrite-Workspace-Root"
WORKSPACE_ID_HEADER = "X-OpenWrite-Workspace-Id"
SESSION_ID_HEADER = "X-OpenWrite-Session-Id"
CONTEXT_EPOCH_HEADER = "X-OpenWrite-Context-Epoch"
TOOL_CALL_ID_HEADER = "X-OpenWrite-Tool-Call-Id"
ROOT_CALL_ID_HEADER = "X-OpenWrite-Root-Call-Id"
TOOL_NAME_HEADER = "X-OpenWrite-Tool-Name"


def canonicalize_workspace_root(raw: str) -> Path:
    """Resolve *raw* into the canonical identity of a workspace root.

    The realpath result is the identity: symlink aliases of the same directory
    map to the same root. Every failure raises a stable ``StudioError``.
    """
    value = str(raw or "").strip()
    if not value:
        raise StudioError(
            "缺少工作区根目录",
            code="WORKSPACE_CONTEXT_MISSING",
        )
    expanded = Path(value).expanduser()
    if not expanded.is_absolute():
        raise StudioError(
            "工作区根目录必须是绝对路径",
            code="WORKSPACE_ROOT_INVALID",
            details={"reason": "not_absolute"},
        )
    if any(segment == ".." for segment in expanded.parts):
        raise StudioError(
            "工作区根目录不能包含 .. 路径段",
            code="WORKSPACE_ROOT_INVALID",
            details={"reason": "traversal"},
        )
    root = Path(os.path.realpath(expanded))
    if not root.exists():
        raise StudioError(
            "工作区根目录不存在",
            code="WORKSPACE_ROOT_INVALID",
            details={"reason": "not_found"},
        )
    if not root.is_dir():
        raise StudioError(
            "工作区根目录不是目录",
            code="WORKSPACE_ROOT_INVALID",
            details={"reason": "not_directory"},
        )
    if not os.access(root, os.R_OK | os.X_OK):
        raise StudioError(
            "工作区根目录不可读",
            code="WORKSPACE_ROOT_INVALID",
            details={"reason": "not_readable"},
        )
    return root


@dataclass(frozen=True)
class WorkspaceContext:
    """Routing context parsed from the workspace headers of one request."""

    root: Path
    workspace_id: str = ""
    session_id: str = ""
    context_epoch: int | None = None
    tool_call_id: str = ""
    root_call_id: str = ""
    tool_name: str = ""


class WorkspaceManager:
    """Own the per-root ``StudioApplication`` instances of one Studio server."""

    def __init__(self, launch_root: Path, app_kwargs: dict[str, Any] | None = None) -> None:
        self.launch_root = Path(os.path.realpath(Path(launch_root).expanduser()))
        self._app_kwargs = dict(app_kwargs or {})
        # ``_contexts`` retains the legacy launch app for compatibility with
        # existing lifecycle/debug code. Context applications live in their
        # own map so a context rooted at ``launch_root`` can never alias the
        # mutable legacy app.
        self._contexts: dict[Path, Any] = {}
        self._context_apps: dict[Path, Any] = {}
        self._epochs: dict[Path, int] = {}
        self._lock = threading.RLock()
        self._request_local = threading.local()
        self._default_app: Any = None

    @property
    def default_app(self) -> Any:
        return self._default_app

    def adopt_default_app(self, app: Any) -> None:
        """Adopt the already-constructed launch application (never built twice)."""
        with self._lock:
            self._default_app = app
            self._contexts[self.launch_root] = app
            app._workspace_manager = self

    def parse_context(self, headers: Any) -> WorkspaceContext | None:
        """Parse workspace headers; ``None`` means legacy (no context) mode."""
        raw_root = headers.get(WORKSPACE_ROOT_HEADER)
        if raw_root is None or not str(raw_root).strip():
            return None
        root = canonicalize_workspace_root(str(raw_root))
        raw_epoch = headers.get(CONTEXT_EPOCH_HEADER)
        epoch: int | None = None
        if raw_epoch is not None and str(raw_epoch).strip():
            try:
                epoch = int(str(raw_epoch).strip())
            except ValueError:
                epoch = None
        return WorkspaceContext(
            root=root,
            workspace_id=str(headers.get(WORKSPACE_ID_HEADER) or "").strip(),
            session_id=str(headers.get(SESSION_ID_HEADER) or "").strip(),
            context_epoch=epoch,
            tool_call_id=str(headers.get(TOOL_CALL_ID_HEADER) or "").strip()[:200],
            root_call_id=str(headers.get(ROOT_CALL_ID_HEADER) or "").strip()[:200],
            tool_name=str(headers.get(TOOL_NAME_HEADER) or "").strip()[:200],
        )

    def app_for(self, context: WorkspaceContext, allow_uninitialized: bool = False) -> Any:
        """Return the per-root application for *context*, creating it on demand."""
        root = context.root
        if is_framework_root(root):
            raise StudioError(
                "工作区根目录是 OpenWrite 框架仓库，不能作为作品项目",
                HTTPStatus.FORBIDDEN,
                code="WORKSPACE_FRAMEWORK_ROOT",
            )
        initialized = (root / "novel_config.yaml").is_file()
        if not initialized and not allow_uninitialized:
            raise StudioError(
                "工作区尚未初始化小说项目",
                HTTPStatus.PRECONDITION_REQUIRED,
                code="WORKSPACE_NOT_INITIALIZED",
            )
        with self._lock:
            # Never reuse ``default_app`` here. Legacy ``/api/project/open``
            # mutates that application in place, so aliasing it would let a
            # legacy request change the dsh context when both use launch_root.
            cached = self._context_apps.get(root)
            if cached is not None:
                return cached
            self._reject_nested(root)
            app = self._build_app(root)
            app._workspace_manager = self

            # Task transitions on the runner thread advance this root's
            # context epoch; reads never do.
            def listener(record: dict[str, Any], *, _root: Path = root) -> None:
                del record  # the epoch bump does not inspect the record
                self.bump_epoch(_root)

            app._task_change_listener = listener
            runner = getattr(app, "_task_runner", None)
            if runner is not None:
                runner.store.on_change = listener
            self._context_apps[root] = app
            # Keep the historical map useful for non-launch context roots;
            # launch_root is already occupied by the legacy app.
            if root != self.launch_root:
                self._contexts[root] = app
            return app

    def bump_epoch(self, root: Path) -> int:
        """Advance the per-root write epoch; a fresh root starts from 1."""
        key = Path(root)
        with self._lock:
            self._epochs[key] = self._epochs.get(key, 1) + 1
            return self._epochs[key]

    def epoch(self, root: Path) -> int:
        with self._lock:
            return self._epochs.get(Path(root), 1)

    def describe(self, context: WorkspaceContext | None, app: Any) -> dict[str, Any]:
        """Diagnostic payload for ``GET /api/workspace/context``."""
        if context is None:
            return {
                "mode": "legacy",
                "workspace_root": str(app.project_root),
                "initialized": bool(app.initialized),
                "novel_id": str(app.novel_id),
            }
        return {
            "mode": "workspace",
            "workspace_id": context.workspace_id,
            "workspace_root": str(context.root),
            "initialized": bool(app.initialized),
            "novel_id": str(app.novel_id),
            "context_epoch": self.epoch(context.root),
        }

    def set_request_context(self, context: WorkspaceContext) -> None:
        self._request_local.context = context

    def clear_request_context(self) -> None:
        self._request_local.context = None

    def current_request_context(self) -> WorkspaceContext | None:
        return getattr(self._request_local, "context", None)

    def shutdown(self, *, wait: bool = False) -> None:
        """Stop every unique task runner owned by this Studio server.

        The legacy launch app and a context app may coexist for the same root,
        so deduplicate by object identity before shutting runners down.
        """
        with self._lock:
            apps = list(self._contexts.values()) + list(self._context_apps.values())
        seen: set[int] = set()
        for app in apps:
            if id(app) in seen:
                continue
            seen.add(id(app))
            runner = getattr(app, "_task_runner", None)
            if runner is not None:
                runner.shutdown(wait=wait)

    def _reject_nested(self, root: Path) -> None:
        """Reject roots nested in either direction among active roots."""
        active_roots = set(self._contexts) | set(self._context_apps)
        for other in active_roots:
            if other != root and (other in root.parents or root in other.parents):
                raise StudioError(
                    "工作区根目录与另一个已激活工作区存在嵌套关系",
                    code="WORKSPACE_ROOT_INVALID",
                    details={"reason": "nested", "parent": str(other)},
                )

    def _build_app(self, root: Path) -> Any:
        from tools.studio_application import StudioApplication

        kwargs = dict(self._app_kwargs)
        # Context applications never write the legacy recent-project registry
        # and never enable debug logging.
        kwargs["project_registry"] = None
        kwargs["debug"] = False
        return StudioApplication(root, **kwargs)
