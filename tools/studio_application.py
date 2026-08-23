"""Local, novel-only web workbench for OpenWrite."""

from __future__ import annotations

import base64
import binascii
import json
import logging
import mimetypes
import os
import re
import tempfile
import time
import uuid
import webbrowser
from collections import deque
from collections.abc import Callable
from contextlib import nullcontext
from functools import partial
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Lock
from typing import Any, cast
from urllib.parse import parse_qs, quote, urlparse

import yaml

from tools.asset_package import AssetPackageError, AssetPackageService
from tools.character_state_index import CharacterStateIndex
from tools.context_manifest import build_context_manifest
from tools.git_checkpoint import GitCheckpointManager
from tools.library_catalog import (
    CATEGORY_ORDER,
    LIBRARY_SCOPES,
    describe_document,
    iter_library_paths,
)
from tools.llm.model_catalog import MAX_CONTEXT_TOKENS, MAX_OUTPUT_TOKENS
from tools.llm.response import redact_sensitive_text
from tools.model_profiles import (
    ModelProfileError,
    ModelProfileStore,
    activate_model_profile,
)
from tools.novel_service import NovelApplicationService, NovelServiceError
from tools.novel_workspace import (
    count_writing_units,
    list_chapters,
    novel_root,
    split_manuscript,
)
from tools.outline_tree import (
    OutlineEditError,
    build_outline_structure,
    mutate_outline_structure,
)
from tools.project_registry import (
    ProjectRegistry,
    default_registry_path,
    is_ephemeral_project_path,
    is_framework_root,
    write_content_project_metadata,
)
from tools.project_search import ProjectSearchIndex
from tools.reference_library import (
    ReferenceLibraryService,
    default_reference_library_root,
)
from tools.research_service import ResearchService, ResearchServiceError
from tools.review_store import normalize_review_issues
from tools.revision_service import RevisionError, RevisionService
from tools.structured_assets import StructuredAssetError, StructuredAssetService
from tools.studio_contracts import (
    MAX_DOCUMENT_BYTES,
    STATIC_ROOT,
    WRITE_HEADER,
    StudioError,
    missing_required_static_assets,
)
from tools.studio_http import (
    OpenWriteStudioServer as ModularOpenWriteStudioServer,
)
from tools.studio_http import (
    StudioRequestHandler as ModularStudioRequestHandler,
)
from tools.studio_preferences import (
    StudioModelSettingsStore,
    StudioResearchSettingsStore,
)
from tools.studio_runtime import (
    AGENT_TOOL_LABELS,
    DEBUG_ENV,
    render_chat_markdown,
    sanitize_debug_payload,
)
from tools.studio_runtime import (
    configure_debug_logging as _configure_debug_logging,
)
from tools.studio_runtime import (
    debug_json as _debug_json,
)
from tools.studio_runtime import (
    debug_log_path as _debug_log_path,
)
from tools.studio_runtime import (
    truthy_env as _truthy_env,
)
from tools.task_runner import PersistentTaskRunner, TaskCancelled, TaskContext
from tools.task_store import TaskStoreError
from tools.version import __version__
from tools.writing_targets import normalize_writing_targets

logger = logging.getLogger("tools.studio")


class StudioApplication:
    """Filesystem and writing operations exposed to the local HTTP layer."""

    def __init__(
        self,
        project_root: Path,
        writer_executor: Callable[[Path, dict[str, Any]], dict[str, Any]] | None = None,
        review_executor: Callable[[Path, dict[str, Any]], dict[str, Any]] | None = None,
        chat_executor: Callable[[Path, str, str, str], dict[str, Any]] | None = None,
        source_executor: Callable[[Path, dict[str, Any]], dict[str, Any]] | None = None,
        revision_executor: Callable[[Path, dict[str, Any]], dict[str, Any] | str]
        | None = None,
        model_test_executor: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
        project_registry: ProjectRegistry | None = None,
        model_settings_store: StudioModelSettingsStore | None = None,
        model_profile_store: ModelProfileStore | None = None,
        reference_library_root: Path | None = None,
        debug: bool = False,
    ):
        self.launch_root = Path(project_root).resolve()
        self.project_root = self.launch_root
        self.debug_enabled = bool(debug or _truthy_env(os.environ.get(DEBUG_ENV, "")))
        self.debug_log_path: Path | None = None
        self._project_registry = project_registry
        if reference_library_root is not None:
            self.reference_library_root = Path(reference_library_root).expanduser().resolve()
        elif (
            project_registry is not None
            and project_registry.path != default_registry_path().resolve()
        ):
            self.reference_library_root = (
                project_registry.path.parent / "reference-library"
            ).resolve()
        elif is_ephemeral_project_path(self.launch_root):
            self.reference_library_root = (
                self.launch_root / ".openwrite" / "test-reference-library"
            ).resolve()
        else:
            self.reference_library_root = default_reference_library_root()
        self._writer_executor = writer_executor
        self._review_executor = review_executor
        self._chat_executor = chat_executor
        self._source_executor = source_executor
        self._revision_executor = revision_executor
        self._model_test_executor = model_test_executor
        self._model_settings_store = model_settings_store or StudioModelSettingsStore()
        self._saved_model_settings = self._model_settings_store.restore_environment()
        self._model_profile_store = model_profile_store or ModelProfileStore(
            self._model_settings_store.directory
        )
        self._research_settings_store = StudioResearchSettingsStore(
            self._model_profile_store.directory
        )
        self._write_lock = Lock()
        self._agent_activity_lock = Lock()
        self._agent_activities: dict[str, dict[str, Any]] = {}
        self._task_runner: PersistentTaskRunner | None = None
        self._structured_asset_service: StructuredAssetService | None = None
        self._asset_package_service: AssetPackageService | None = None
        self._research_service: ResearchService | None = None
        self._activate_project(self.project_root)

    def _activate_project(self, project_root: Path) -> None:
        if self._task_runner is not None:
            self._task_runner.shutdown(wait=False)
            self._task_runner = None
        self.project_root = Path(project_root).resolve()
        self.config_path = self.project_root / "novel_config.yaml"
        self.initialized = self.config_path.exists() and not is_framework_root(
            self.project_root
        )
        self.config = self._load_config() if self.initialized else {}
        self.novel_id = str(self.config.get("novel_id") or "")
        if self.initialized and not self.novel_id:
            raise StudioError("novel_config.yaml 缺少 novel_id")
        self.novel_root = (
            novel_root(self.project_root, self.novel_id).resolve()
            if self.initialized
            else self.project_root
        )
        self._novel_service = self._build_novel_service() if self.initialized else None
        self._revision_service = self._build_revision_service() if self.initialized else None
        self._task_runner = self._build_task_runner() if self.initialized else None
        self._structured_asset_service = (
            StructuredAssetService(self.project_root, self.novel_id)
            if self.initialized
            else None
        )
        self._asset_package_service = (
            AssetPackageService(self.project_root, self.novel_id)
            if self.initialized
            else None
        )
        self._research_service = (
            ResearchService(
                self.novel_root,
                settings_store=self._research_settings_store,
            )
            if self.initialized
            else None
        )
        if self.initialized and self._project_registry is not None:
            self._project_registry.remember(self.project_root)
        self._configure_debug_mode()
        self._debug_event(
            "project_activated",
            project_root=str(self.project_root),
            novel_id=self.novel_id,
            initialized=self.initialized,
            log_path=str(self.debug_log_path or ""),
        )

    def _deactivate_project(self) -> None:
        if self._task_runner is not None:
            self._task_runner.shutdown(wait=False)
            self._task_runner = None
        self.project_root = self.launch_root
        self.config_path = self.project_root / "novel_config.yaml"
        self.initialized = self.config_path.exists()
        self.config = {}
        self.novel_id = ""
        self.novel_root = self.project_root
        self._novel_service = None
        self._revision_service = None
        self._structured_asset_service = None
        self._asset_package_service = None

    def _configure_debug_mode(self) -> None:
        if not self.debug_enabled:
            return
        self.debug_log_path = _debug_log_path(
            self.project_root,
            self.novel_root,
            self.initialized,
        )
        _configure_debug_logging(self.debug_log_path)

    def _debug_event(self, event: str, **payload: Any) -> None:
        if not self.debug_enabled:
            return
        logger.debug("studio.%s %s", event, _debug_json(payload))

    def agent_activity(self, run_id: str) -> dict[str, Any]:
        clean_id = self._normalize_activity_run_id(run_id)
        with self._agent_activity_lock:
            activity = self._agent_activities.get(clean_id)
            if activity is None:
                raise StudioError("未找到 AI 运行记录", HTTPStatus.NOT_FOUND)
            payload = dict(activity)
            payload["events"] = [dict(item) for item in activity.get("events", [])]
        payload["elapsed_seconds"] = max(
            0,
            int((payload.get("finished_at") or time.time()) - payload["started_at"]),
        )
        return payload

    def _start_agent_activity(
        self,
        run_id: str,
        *,
        agent: str,
        session_id: str,
    ) -> None:
        now = time.time()
        label = "Goethe" if agent == "goethe" else "Dante"
        activity = {
            "run_id": run_id,
            "agent": agent,
            "agent_label": label,
            "session_id": session_id,
            "status": "running",
            "phase": "reading_context",
            "step_index": 0,
            "title": f"{label} 正在读取项目",
            "note": "正在恢复会话、作品状态和本轮上下文。",
            "tool": "",
            "turn": 0,
            "started_at": now,
            "updated_at": now,
            "finished_at": 0.0,
            "event_sequence": 0,
            "events": [],
        }
        with self._agent_activity_lock:
            self._agent_activities[run_id] = activity
            if len(self._agent_activities) > 50:
                oldest = sorted(
                    self._agent_activities.values(),
                    key=lambda item: float(item.get("updated_at") or 0),
                )[: len(self._agent_activities) - 50]
                for item in oldest:
                    self._agent_activities.pop(str(item["run_id"]), None)

    def _record_agent_activity(
        self,
        run_id: str,
        event: dict[str, Any],
    ) -> None:
        event_name = str(event.get("event") or "")
        now = time.time()
        with self._agent_activity_lock:
            activity = self._agent_activities.get(run_id)
            if activity is None:
                return
            label = str(activity["agent_label"])
            turn = int(event.get("turn") or activity.get("turn") or 0)
            tool = str(event.get("tool") or activity.get("tool") or "")
            activity["updated_at"] = now
            activity["turn"] = turn
            activity["tool"] = tool
            tool_label = AGENT_TOOL_LABELS.get(tool, tool or "项目工具")

            if event_name == "run_started":
                activity.update(
                    phase="reading_context",
                    step_index=0,
                    title=f"{label} 已读取项目",
                    note="会话与作品状态已载入，准备分析本轮目标。",
                )
            elif event_name == "model_started":
                activity.update(
                    phase="thinking",
                    step_index=1,
                    title=f"{label} 正在思考",
                    note=f"第 {turn} 轮：等待模型决定下一步。",
                )
            elif event_name == "model_completed":
                tool_count = int(event.get("tool_count") or 0)
                activity.update(
                    phase="tool_selection" if tool_count else "response",
                    step_index=2 if tool_count else 3,
                    title=(
                        f"{label} 已选择 {tool_count} 个工具"
                        if tool_count
                        else f"{label} 正在整理回复"
                    ),
                    note=(
                        "模型已返回，准备执行并校验工具结果。"
                        if tool_count
                        else "模型已完成本轮分析，正在整理回复。"
                    ),
                )
            elif event_name == "model_retry":
                attempt = int(event.get("repair_attempt") or 1)
                limit = int(event.get("repair_limit") or attempt)
                reason = str(event.get("reason") or "模型输出未通过校验")
                activity.update(
                    phase="thinking",
                    step_index=1,
                    title=f"{label} 正在自动修复输出",
                    note=f"第 {attempt}/{limit} 次修复：{reason}",
                )
            elif event_name == "tool_started":
                activity.update(
                    phase="tool_running",
                    step_index=2,
                    title=f"{label} 正在调用工具",
                    note=f"第 {turn} 轮：{tool_label}",
                )
            elif event_name == "tool_completed":
                ok = bool(event.get("ok", True))
                reason = str(event.get("reason") or "")
                activity.update(
                    phase="tool_result",
                    step_index=2,
                    title=f"{tool_label}{'已完成' if ok else '失败'}",
                    note=(
                        "结果已返回给模型，等待下一步判断。"
                        if ok
                        else (reason or "工具返回失败，Agent 正在判断是否可以恢复。")
                    ),
                )
            elif event_name == "response_ready":
                activity.update(
                    phase="response",
                    step_index=3,
                    title=f"{label} 正在整理回复",
                    note="工具与状态已经核对，正在写入本轮回复和会话历史。",
                )
            elif event_name == "run_completed":
                activity.update(
                    phase="complete",
                    step_index=4,
                    title=f"{label} 本轮已完成",
                    note="回复与会话状态已经保存。",
                )
            elif event_name == "run_failed":
                reason = str(event.get("reason") or "Agent 本轮执行失败")
                activity.update(
                    phase="error",
                    title=f"{label} 本轮已停止",
                    note=reason,
                )

            events = activity.setdefault("events", [])
            sequence = int(activity.get("event_sequence") or 0) + 1
            activity["event_sequence"] = sequence
            events.append(
                {
                    "sequence": sequence,
                    "event": event_name,
                    "turn": turn,
                    "tool": tool,
                    "tool_label": tool_label if tool else "",
                    "tool_call_id": str(event.get("tool_call_id") or "")[:120],
                    "tool_count": int(event.get("tool_count") or 0),
                    "has_content": bool(event.get("has_content")),
                    "ok": event.get("ok"),
                    "message": self._agent_activity_detail(
                        event.get("message"), limit=900
                    ),
                    "arguments": self._agent_activity_detail(
                        event.get("arguments"), limit=1800
                    ),
                    "result": self._agent_activity_detail(
                        event.get("result"), limit=2400
                    ),
                    "reason": self._agent_activity_detail(
                        event.get("reason"), limit=900
                    ),
                    "repair_attempt": int(event.get("repair_attempt") or 0),
                    "repair_limit": int(event.get("repair_limit") or 0),
                    "timestamp": now,
                }
            )
            del events[:-80]

    @staticmethod
    def _agent_activity_detail(value: Any, *, limit: int) -> str:
        if value in (None, "", [], {}):
            return ""
        if isinstance(value, (dict, list, tuple)):
            text = json.dumps(
                sanitize_debug_payload(value),
                ensure_ascii=False,
                indent=2,
                default=str,
            )
        else:
            text = str(value)
        text = redact_sensitive_text(text).strip()
        if len(text) <= limit:
            return text
        return f"{text[:limit].rstrip()}\n...（已截断）"

    def _finish_agent_activity(
        self,
        run_id: str,
        *,
        status: str,
        message: str = "",
    ) -> None:
        now = time.time()
        with self._agent_activity_lock:
            activity = self._agent_activities.get(run_id)
            if activity is None:
                return
            label = str(activity["agent_label"])
            activity.update(
                status=status,
                phase="complete" if status == "complete" else "error",
                step_index=4 if status == "complete" else activity.get("step_index", 0),
                title=(f"{label} 本轮已完成" if status == "complete" else f"{label} 本轮已中断"),
                note=(
                    "回复与会话状态已经保存。"
                    if status == "complete"
                    else (message or "请求未完成，请检查模型连接或 debug 日志。")
                ),
                updated_at=now,
                finished_at=now,
            )

    @staticmethod
    def _normalize_activity_run_id(value: Any) -> str:
        run_id = str(value or "").strip()
        if not run_id:
            return uuid.uuid4().hex
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{7,95}", run_id):
            raise StudioError("AI 运行 ID 无效")
        return run_id

    def _debug_book_state(self) -> dict[str, Any]:
        if not self.initialized:
            return {}
        path = self.novel_root / "data" / "workflows" / "book_state.yaml"
        if not path.is_file():
            return {}
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except (OSError, UnicodeDecodeError, yaml.YAMLError):
            return {"error": "unreadable"}
        if not isinstance(data, dict):
            return {"error": "invalid"}
        return {
            key: data.get(key, "")
            for key in (
                "stage",
                "pending_confirmation",
                "current_arc",
                "current_section",
                "current_chapter",
                "blocking_reason",
                "last_agent_action",
            )
        }

    def workspace(self) -> dict[str, Any]:
        if not self.initialized:
            return {
                "version": __version__,
                "initialized": False,
                "project": self._project_payload(),
                "snapshot": {
                    "novel_id": "",
                    "title": "新小说",
                    "current_arc": "arc_001",
                    "current_chapter": "ch_001",
                    "stage": "discovery",
                    "chapters": 0,
                    "writing_units": 0,
                    "target_units": 0,
                    "characters": 0,
                    "world_documents": 0,
                    "pending_foreshadowing": 0,
                    "total_tokens": 0,
                    "reviewed_chapters": 0,
                    "average_review_score": 0,
                    "creative_focus": {
                        "goal": "",
                        "must_keep": [],
                        "must_avoid": [],
                        "notes": [],
                    },
                    "readiness": {
                        "author_intent": False,
                        "background": False,
                        "foundation": False,
                        "characters": False,
                        "outline": False,
                        "creative_focus": False,
                    },
                    "next_actions": ["先创建小说项目"],
                    "next_action_items": [
                        {
                            "id": "init_project",
                            "label": "先创建小说项目",
                            "cli": "openwrite init <novel_id>",
                            "studio_action": "open_project_dialog",
                            "seed": "",
                        }
                    ],
                },
                "documents": {
                    "outline": [],
                    "core": [],
                    "characters": [],
                    "settings": [],
                    "chapters": [],
                },
                "model": self._model_payload(),
                "model_profiles": self.model_profiles(),
                "operations": {
                    "sync": {"needs_sync": False},
                    "source_packs": [],
                    "diagnostics": [{"name": "项目配置", "ok": False, "detail": "尚未创建"}],
                },
            }
        self.config = self._load_config()
        snapshot = self._service().workspace_snapshot()
        chapters = list_chapters(self.project_root, self.novel_id)
        return {
            "version": __version__,
            "initialized": True,
            "project": self._project_payload(),
            "snapshot": snapshot,
            "documents": self._document_groups(chapters),
            "model": self._model_payload(),
            "model_profiles": self.model_profiles(),
            "operations": self.operation_status(),
        }

    def initialize_project(self, payload: dict[str, Any]) -> dict[str, Any]:
        raw_target = str(payload.get("project_path") or "").strip()
        novel_id = str(payload.get("novel_id") or "").strip()
        title = str(payload.get("title") or "").strip()
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{1,63}", novel_id):
            raise StudioError("小说 ID 需为 2-64 位字母、数字、横线或下划线")
        if not title or len(title) > 120:
            raise StudioError("书名不能为空且不能超过 120 字")
        if raw_target:
            target_path = Path(raw_target).expanduser()
            target = (
                target_path.resolve()
                if target_path.is_absolute()
                else (self.launch_root / target_path).resolve()
            )
        elif is_framework_root(self.launch_root):
            target = self._default_project_directory(title, novel_id)
        else:
            target = self.project_root
        self._debug_event(
            "project_init_requested",
            target=str(target),
            novel_id=payload.get("novel_id"),
            title=payload.get("title"),
        )
        if self.initialized and target == self.project_root:
            raise StudioError("当前目录已经是小说项目", HTTPStatus.CONFLICT)
        if target == self.launch_root and is_framework_root(target):
            raise StudioError("框架仓库不能直接保存私人作品，请选择独立作品目录")
        if target.exists() and not target.is_dir():
            raise StudioError("作品路径不是目录")
        target.mkdir(parents=True, exist_ok=True)
        if (target / "novel_config.yaml").exists():
            raise StudioError("目标目录已经是小说项目", HTTPStatus.CONFLICT)
        template = str(payload.get("template") or "default").strip()
        if template not in {"default", "demo_short"}:
            raise StudioError("不支持的模板类型，可选 default 或 demo_short")
        try:
            NovelApplicationService.initialize(target, novel_id, title, template=template)
        except NovelServiceError as exc:
            raise self._translate_service_error(exc) from exc
        write_content_project_metadata(target)
        self._activate_project(target)
        self._debug_event(
            "project_init_completed",
            target=str(target),
            novel_id=novel_id,
            template=template,
        )
        return self.workspace()

    def _default_project_directory(self, title: str, novel_id: str) -> Path:
        slug = re.sub(r"[^\w\u4e00-\u9fff]+", "_", title.lower()).strip("_")
        return (self.launch_root.parent / "OpenWriteNovels" / (slug[:64] or novel_id)).resolve()

    def open_project(self, payload: dict[str, Any]) -> dict[str, Any]:
        self._require_no_active_tasks()
        raw_path = str(payload.get("project_path") or "").strip()
        if not raw_path:
            raise StudioError("请输入作品目录")
        target = Path(raw_path).expanduser().resolve()
        self._debug_event("project_open_requested", target=str(target))
        if not target.is_dir() or not (target / "novel_config.yaml").is_file():
            raise StudioError("所选目录不是有效的 OpenWrite 作品项目")
        with self._write_lock:
            self._activate_project(target)
        self._debug_event("project_open_completed", target=str(target), novel_id=self.novel_id)
        return self.workspace()

    def delete_project(self, payload: dict[str, Any]) -> dict[str, Any]:
        raw_path = str(payload.get("project_path") or "").strip()
        confirm = str(payload.get("confirm") or "").strip()
        if not raw_path:
            raise StudioError("请指定要删除的作品目录")
        target = Path(raw_path).expanduser().resolve()
        if target == self.project_root:
            self._require_no_active_tasks()
        self._debug_event("project_delete_requested", target=str(target))
        if target == self.launch_root and is_framework_root(target):
            raise StudioError("不能删除框架仓库")
        if not target.is_dir() or not (target / "novel_config.yaml").is_file():
            raise StudioError("所选目录不是有效的 OpenWrite 作品项目")
        config_path = target / "novel_config.yaml"
        try:
            import yaml as _yaml

            cfg = _yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
            novel_id = str(cfg.get("novel_id") or "")
        except (OSError, _yaml.YAMLError):
            novel_id = ""
        if confirm != novel_id:
            raise StudioError(
                f"删除确认不匹配（预期: {novel_id}）",
                HTTPStatus.PRECONDITION_REQUIRED,
            )
        import shutil

        with self._write_lock:
            shutil.rmtree(target)
        if self._project_registry is not None:
            self._project_registry.remove(str(target))
        if self.project_root == target:
            self._deactivate_project()
        self._debug_event("project_delete_completed", target=str(target))
        return self.workspace()

    def _require_no_active_tasks(self) -> None:
        if self._task_runner is None:
            return
        active = self._task_runner.store.list(
            statuses={"pending", "running", "awaiting_confirmation"},
            limit=1,
        )
        if active:
            raise StudioError(
                "当前作品仍有未结束任务，请先完成或取消任务",
                HTTPStatus.CONFLICT,
                code="ACTIVE_TASKS_PRESENT",
                recoverable=True,
                details={"task_id": active[0].get("task_id")},
            )

    def _project_payload(self) -> dict[str, Any]:
        recent = self._project_registry.list() if self._project_registry is not None else []
        return {
            "root": str(self.project_root),
            "launch_root": str(self.launch_root),
            "framework_root": is_framework_root(self.launch_root),
            "requires_external_location": (
                not self.initialized and is_framework_root(self.project_root)
            ),
            "recent": recent,
            "writing_targets": normalize_writing_targets(
                self.config.get("writing_targets") if self.initialized else {}
            ),
        }

    def require_project(self) -> None:
        if not self.initialized:
            raise StudioError("请先创建小说项目", HTTPStatus.PRECONDITION_REQUIRED)

    def _build_novel_service(self) -> NovelApplicationService:
        return NovelApplicationService(
            self.project_root,
            writer_executor=self._writer_executor,
            review_executor=self._review_executor,
            source_executor=self._source_executor,
            task_lock=self._write_lock,
        )

    def _service(self) -> NovelApplicationService:
        self.require_project()
        if self._novel_service is None:
            self._novel_service = self._build_novel_service()
        return self._novel_service

    def _build_revision_service(self) -> RevisionService:
        generator = None
        if self._revision_executor is not None:
            executor = self._revision_executor

            def generator(payload: dict[str, Any]) -> dict[str, Any] | str:
                return executor(self.project_root, payload)

        return RevisionService(
            self.project_root,
            self.novel_id,
            generator=generator,
        )

    def _revisions(self) -> RevisionService:
        self.require_project()
        if self._revision_service is None:
            self._revision_service = self._build_revision_service()
        return self._revision_service

    def _build_task_runner(self) -> PersistentTaskRunner:
        return PersistentTaskRunner(
            self.project_root,
            self.novel_id,
            handlers={
                "chapter_write": self._task_write_chapter,
                "chapter_review": self._task_review_chapter,
                "revision_selection": self._task_revision_selection,
                "revision_from_review": self._task_revision_from_review,
                "source_operation": self._task_source_operation,
                "reference_operation": self._task_reference_operation,
                "manuscript_import": self._task_import_manuscript,
                "continuous_write": self._task_continuous_write,
                "research": self._task_research,
            },
        )

    def _tasks(self) -> PersistentTaskRunner:
        self.require_project()
        if self._task_runner is None:
            self._task_runner = self._build_task_runner()
        return self._task_runner

    def _assets(self) -> StructuredAssetService:
        self.require_project()
        if self._structured_asset_service is None:
            self._structured_asset_service = StructuredAssetService(
                self.project_root,
                self.novel_id,
            )
        return self._structured_asset_service

    def _asset_packages(self) -> AssetPackageService:
        self.require_project()
        if self._asset_package_service is None:
            self._asset_package_service = AssetPackageService(
                self.project_root,
                self.novel_id,
            )
        return self._asset_package_service

    def _research(self) -> ResearchService:
        self.require_project()
        if self._research_service is None:
            self._research_service = ResearchService(
                self.novel_root,
                settings_store=self._research_settings_store,
            )
        return self._research_service

    def _reference_library(self) -> ReferenceLibraryService:
        self.require_project()
        return ReferenceLibraryService(
            self.reference_library_root,
            project_root=self.project_root,
            novel_id=self.novel_id,
        )

    @staticmethod
    def _translate_service_error(exc: NovelServiceError) -> StudioError:
        status = {
            "PROJECT_BUSY": HTTPStatus.CONFLICT,
            "CONFLICT": HTTPStatus.CONFLICT,
            "NOT_FOUND": HTTPStatus.NOT_FOUND,
            "INVALID_PROJECT": HTTPStatus.PRECONDITION_FAILED,
            "INVALID_INPUT": HTTPStatus.BAD_REQUEST,
            "INVALID_STATE": HTTPStatus.CONFLICT,
            "INVALID_EVIDENCE": HTTPStatus.UNPROCESSABLE_ENTITY,
            "INVALID_MODEL_OUTPUT": HTTPStatus.BAD_GATEWAY,
            "SOURCE_INCOMPLETE": HTTPStatus.CONFLICT,
            "SOURCE_DELETED": HTTPStatus.GONE,
            "SOURCE_CHANGED": HTTPStatus.CONFLICT,
            "CONFIRMATION_REQUIRED": HTTPStatus.PRECONDITION_REQUIRED,
            "DOCUMENT_CONFLICT": HTTPStatus.CONFLICT,
            "PATH_OUT_OF_BOUNDS": HTTPStatus.BAD_REQUEST,
        }.get(exc.code, HTTPStatus.BAD_GATEWAY)
        return StudioError(str(exc), status)

    def operation_status(self) -> dict[str, Any]:
        sources_root = self.novel_root / "data" / "sources"
        source_packs = []
        if sources_root.exists():
            for path in sorted(sources_root.iterdir()):
                if not path.is_dir() or path.name.startswith("_"):
                    continue
                analysis_manifest = path / "analysis_v2" / "manifest.json"
                analysis: dict[str, Any] = {}
                if analysis_manifest.is_file():
                    try:
                        loaded = json.loads(analysis_manifest.read_text(encoding="utf-8"))
                        if isinstance(loaded, dict):
                            chunks = loaded.get("chunks") or []
                            analysis = {
                                "status": str(loaded.get("status") or ""),
                                "change_status": str(
                                    loaded.get("change_status") or ""
                                ),
                                "relative_name": str(loaded.get("relative_name") or ""),
                                "total_chars": int(loaded.get("total_chars") or 0),
                                "input_budget_tokens": int(
                                    loaded.get("input_budget_tokens") or 0
                                ),
                                "updated_at": str(loaded.get("updated_at") or ""),
                                "source_sha256": str(
                                    loaded.get("source_sha256") or ""
                                ),
                                "total_chunks": len(chunks),
                                "completed_chunks": sum(
                                    1
                                    for chunk in chunks
                                    if isinstance(chunk, dict)
                                    and chunk.get("status") == "completed"
                                ),
                                "failed_chunks": sum(
                                    1
                                    for chunk in chunks
                                    if isinstance(chunk, dict)
                                    and chunk.get("status") == "failed"
                                ),
                            }
                    except (OSError, json.JSONDecodeError):
                        analysis = {"status": "invalid"}
                source_packs.append(
                    {
                        "source_id": path.name,
                        "review_ready": (path / "source.md").exists(),
                        "style_ready": (path / "style").is_dir(),
                        "setting_ready": (path / "setting_profile.md").exists(),
                        "analysis_v2": analysis,
                    }
                )
        sync = self._service().sync_status()
        diagnostics = [
            {
                "name": "项目配置",
                "ok": self.config_path.is_file() and bool(self.novel_id),
                "detail": self.novel_id,
            },
            {
                "name": "模型连接",
                "ok": any(
                    bool(profile.get("configured"))
                    for profile in self.model_profiles().get("profiles", [])
                ),
                "detail": next(
                    (
                        str(profile.get("model") or "")
                        for profile in self.model_profiles().get("profiles", [])
                        if profile.get("configured")
                    ),
                    "未配置",
                ),
            },
            {
                "name": "源文件同步",
                "ok": not bool(sync.get("needs_sync")),
                "detail": "待同步" if sync.get("needs_sync") else "已同步",
            },
            {
                "name": "作品写入",
                "ok": os.access(self.novel_root, os.W_OK),
                "detail": "可写" if os.access(self.novel_root, os.W_OK) else "只读",
            },
        ]
        return {
            "sync": sync,
            "source_packs": source_packs,
            "reference_library": self._reference_library().list(),
            "reference_style": self._reference_library().project_style_surface(),
            "diagnostics": diagnostics,
            "git_checkpoint": GitCheckpointManager(self.project_root).status(),
            "runtime_skills": self.runtime_skill_action({"action": "list"}),
            "runtime_rules": self.rule_action({"action": "status"}),
            "chapter_runs_v2": self.chapter_run_v2_action(
                {"action": "list", "limit": 10}
            ),
            "runtime_diagnostics": self.runtime_diagnostics(),
            "rolling_plans": self.rolling_plan_action({"action": "list", "limit": 10}),
            "narrative_forecasts": self.narrative_forecast_action(
                {"action": "list", "limit": 10}
            ),
        }

    def chapter_run_v2_action(self, payload: dict[str, Any]) -> dict[str, Any]:
        from tools.chapter_run_v2 import (
            ChapterRunV2Error,
            chapter_run_v2_action,
        )

        self.require_project()
        try:
            return chapter_run_v2_action(
                self.project_root,
                self.novel_id,
                payload,
            )
        except ChapterRunV2Error as exc:
            if exc.code == "RUN_NOT_FOUND":
                status = HTTPStatus.NOT_FOUND
            elif exc.code in {
                "REVISION_REQUIRED",
                "CONFIRMATION_REQUIRED",
            }:
                status = HTTPStatus.PRECONDITION_REQUIRED
            else:
                status = HTTPStatus.CONFLICT
            raise StudioError(str(exc), status, code=exc.code) from exc

    def runtime_diagnostics(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        from tools.runtime_diagnostics import RuntimeDiagnosticsService

        self.require_project()
        options = payload if isinstance(payload, dict) else {}
        return RuntimeDiagnosticsService(self.project_root, self.novel_id).run(
            stuck_minutes=int(options.get("stuck_minutes") or 30)
        ).model_dump(mode="json")

    def rolling_plan_action(self, payload: dict[str, Any]) -> dict[str, Any]:
        from tools.rolling_planning import RollingPlanningError, rolling_plan_action

        self.require_project()
        try:
            return rolling_plan_action(self.project_root, self.novel_id, payload)
        except RollingPlanningError as exc:
            status = (
                HTTPStatus.NOT_FOUND
                if exc.code == "CANDIDATE_NOT_FOUND"
                else HTTPStatus.CONFLICT
            )
            raise StudioError(str(exc), status, code=exc.code) from exc

    def narrative_forecast_action(self, payload: dict[str, Any]) -> dict[str, Any]:
        from tools.narrative_forecast import (
            NarrativeForecastError,
            narrative_forecast_action,
        )

        self.require_project()
        try:
            return narrative_forecast_action(self.project_root, self.novel_id, payload)
        except NarrativeForecastError as exc:
            status = (
                HTTPStatus.NOT_FOUND
                if exc.code in {"FORECAST_NOT_FOUND", "BRANCH_NOT_FOUND"}
                else HTTPStatus.CONFLICT
            )
            raise StudioError(str(exc), status, code=exc.code) from exc

    def manuscript_editing_action(self, payload: dict[str, Any]) -> dict[str, Any]:
        from tools.manuscript_editing import (
            ManuscriptEditingError,
            manuscript_editing_action,
        )

        self.require_project()
        try:
            return manuscript_editing_action(
                self.project_root,
                self.novel_id,
                payload,
            )
        except ManuscriptEditingError as exc:
            if exc.code in {
                "CHAPTER_NOT_FOUND",
                "VERSION_NOT_FOUND",
                "ANNOTATION_NOT_FOUND",
            }:
                status = HTTPStatus.NOT_FOUND
            elif exc.code == "CONFIRMATION_REQUIRED":
                status = HTTPStatus.PRECONDITION_REQUIRED
            else:
                status = HTTPStatus.CONFLICT
            raise StudioError(str(exc), status, code=exc.code) from exc

    def runtime_skill_action(self, payload: dict[str, Any]) -> dict[str, Any]:
        from tools.agent.tool_runtime import build_tool_executors
        from tools.agent.toolkits import (
            DANTE_ACTION_TOOLKIT,
            DANTE_DIRECT_TOOLKIT,
            GOETHE_ACTION_TOOLKIT,
            GOETHE_DIRECT_TOOLKIT,
            ORCHESTRATOR_TOOLKIT,
            WRITING_TOOLKIT,
        )
        from tools.runtime_skills import RuntimeSkillResolver

        self.require_project()
        resolver = RuntimeSkillResolver(self.project_root)
        action = str(payload.get("action") or "list")
        if action == "list":
            return resolver.list_skills()
        if action == "diagnose":
            return resolver.diagnose()
        if action != "resolve":
            raise StudioError("未知 Runtime Skill 操作", HTTPStatus.BAD_REQUEST)
        agent = str(payload.get("agent") or "studio")
        baselines = {
            "dante": set(DANTE_DIRECT_TOOLKIT) | set(DANTE_ACTION_TOOLKIT),
            "goethe": set(GOETHE_DIRECT_TOOLKIT) | set(GOETHE_ACTION_TOOLKIT),
            "writer": set(WRITING_TOOLKIT),
            "reviewer": set(ORCHESTRATOR_TOOLKIT) | {"review_chapter"},
        }
        baseline = baselines.get(agent, set(build_tool_executors(self.project_root)))
        explicit = payload.get("skills")
        resolution = resolver.resolve(
            agent=agent,
            task=str(payload.get("task") or ""),
            intent=str(payload.get("intent") or ""),
            document_type=str(payload.get("document_type") or ""),
            explicit_skills=(
                [str(item) for item in explicit]
                if isinstance(explicit, list)
                else None
            ),
            base_tools=baseline,
        )
        return resolution.model_dump(mode="json")

    def rule_action(self, payload: dict[str, Any]) -> dict[str, Any]:
        from tools.runtime_skills import RuleCompiler
        from tools.runtime_skills.resolver import RuntimeSkillError

        self.require_project()
        compiler = RuleCompiler(self.project_root)
        action = str(payload.get("action") or "status")
        try:
            if action == "status":
                active = compiler.active()
                return active.model_dump(mode="json") if active else {"active": False}
            if action == "preview":
                return compiler.preview().model_dump(mode="json")
            if action == "apply":
                return compiler.apply(
                    str(payload.get("preview_id") or ""),
                    confirm=bool(payload.get("confirm")),
                ).model_dump(mode="json")
            raise StudioError("未知规则操作", HTTPStatus.BAD_REQUEST)
        except RuntimeSkillError as exc:
            status = (
                HTTPStatus.PRECONDITION_REQUIRED
                if exc.code == "CONFIRMATION_REQUIRED"
                else HTTPStatus.CONFLICT
            )
            raise StudioError(str(exc), status) from exc

    def read_document(self, relative_path: str) -> dict[str, Any]:
        path = self._resolve_document(relative_path, write=False)
        if not path.is_file():
            raise StudioError("文档不存在", HTTPStatus.NOT_FOUND)
        if path.stat().st_size > MAX_DOCUMENT_BYTES:
            raise StudioError(
                "文档超过 2 MB，Studio 不直接打开",
                HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
            )
        content = path.read_text(encoding="utf-8")
        result = {
            "path": self._relative(path),
            "title": self._document_title(path),
            "content": content,
            "version": str(path.stat().st_mtime_ns),
            "revision": RevisionService.fingerprint(content),
        }
        descriptor = describe_document(result["path"], content)
        if descriptor.scope in LIBRARY_SCOPES:
            result.update(descriptor.to_dict())
        return result

    def write_document(
        self,
        relative_path: str,
        content: str,
        version: str | int | None,
        *,
        force: bool = False,
    ) -> dict[str, Any]:
        path = self._resolve_document(relative_path, write=True)
        encoded = content.encode("utf-8")
        self._debug_event(
            "document_write_requested",
            path=self._relative(path),
            bytes=len(encoded),
            version=version,
            force=force,
        )
        if len(encoded) > MAX_DOCUMENT_BYTES:
            raise StudioError("文档超过 2 MB，已拒绝保存", HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
        if "\x00" in content:
            raise StudioError("文档包含无效字符")

        with self._write_lock:
            if path.exists() and version is not None and not force:
                current_version = str(path.stat().st_mtime_ns)
                if current_version != str(version):
                    raise StudioError("文档已在其他位置修改，请重新载入", HTTPStatus.CONFLICT)
            path.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=path.parent,
                prefix=f".{path.name}.",
                suffix=".tmp",
                delete=False,
            ) as handle:
                handle.write(content)
                temp_path = Path(handle.name)
            temp_path.replace(path)
        relative = self._relative(path)
        if relative == "src/outline.md" or relative.startswith(
            ("src/", "data/manuscript/")
        ):
            try:
                CharacterStateIndex(self.project_root, self.novel_id).refresh()
            except Exception as exc:
                logger.warning("Failed to refresh character state index: %s", exc)
        saved = self.read_document(self._relative(path))
        checkpoint_path = path.resolve().relative_to(self.project_root).as_posix()
        checkpoint = GitCheckpointManager(self.project_root).checkpoint(
            [checkpoint_path], self._checkpoint_message(path)
        )
        saved["checkpoint"] = checkpoint.to_dict()
        self._debug_event(
            "document_write_completed",
            path=saved.get("path"),
            version=saved.get("version"),
            checkpoint=saved["checkpoint"],
        )
        return saved

    def delete_chapter(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Delete the latest manuscript chapter after an exact manual confirmation."""
        self._require_no_active_tasks()
        relative_path = str(payload.get("path") or "").strip()
        path = self._resolve_document(relative_path, write=True)
        manuscript_root = (self.novel_root / "data" / "manuscript").resolve()
        if manuscript_root not in path.parents or not re.fullmatch(r"ch_\d+", path.stem):
            raise StudioError("只能删除正文章节", HTTPStatus.FORBIDDEN)
        if not path.is_file():
            raise StudioError("正文章节不存在", HTTPStatus.NOT_FOUND)

        chapter_id = path.stem
        if str(payload.get("confirm") or "").strip() != chapter_id:
            raise StudioError(
                f"删除确认不匹配（请输入 {chapter_id}）",
                HTTPStatus.PRECONDITION_REQUIRED,
            )
        expected_version = payload.get("version")
        if expected_version is None or str(expected_version) != str(path.stat().st_mtime_ns):
            raise StudioError("正文已变化，请重新载入后再删除", HTTPStatus.CONFLICT)

        chapters = list_chapters(self.project_root, self.novel_id)
        if not chapters:
            raise StudioError("当前没有可删除的正文章节", HTTPStatus.NOT_FOUND)
        latest = chapters[-1]
        if latest.path.resolve() != path:
            raise StudioError(
                f"为保护连续性，请先删除最新章节 {latest.chapter_id}",
                HTTPStatus.CONFLICT,
            )

        from models.runtime_state import RuntimeState
        from tools.agent.book_state import BookStage, BookStateStore
        from tools.chapter_memory import ChapterMemoryStore
        from tools.manuscript_editing import ManuscriptVersionStore
        from tools.review_store import ReviewStore
        from tools.runtime_state import RuntimeStateManager
        from tools.truth_manager import TruthFilesManager

        previous_chapter = chapters[-2].chapter_id if len(chapters) > 1 else ""
        checkpoint_path = path.resolve().relative_to(self.project_root).as_posix()

        with self._write_lock:
            if not path.is_file() or str(expected_version) != str(path.stat().st_mtime_ns):
                raise StudioError("正文已变化，请重新载入后再删除", HTTPStatus.CONFLICT)
            git_checkpoint = GitCheckpointManager(self.project_root).checkpoint(
                [checkpoint_path], f"chapter: backup {chapter_id} before Studio delete"
            )
            backup = ManuscriptVersionStore(self.project_root, self.novel_id).checkpoint(
                chapter_id,
                reason="manual",
                label="Studio 删除前自动备份",
            )
            path.unlink()
            ChapterMemoryStore(self.project_root, self.novel_id).delete(chapter_id)
            ReviewStore(self.project_root, self.novel_id).path_for(chapter_id).unlink(
                missing_ok=True
            )

            import shutil

            for artifact_root in (
                self.novel_root / "data" / "revisions" / chapter_id,
                self.novel_root / "data" / "revisions" / "backups" / chapter_id,
                self.novel_root / "data" / "annotations" / chapter_id,
            ):
                if artifact_root.is_dir():
                    shutil.rmtree(artifact_root)

            truth_manager = TruthFilesManager(self.project_root, self.novel_id)
            snapshot_number = max(int(chapter_id.split("_")[-1]) - 1, 0)
            snapshots = sorted(
                truth_manager.snapshots_dir.glob(f"snapshot_{snapshot_number}_*.json")
            )
            runtime_restored = bool(
                snapshots and truth_manager.restore_snapshot(snapshots[-1].stem)
            )
            if not previous_chapter:
                RuntimeStateManager(self.project_root, self.novel_id).save_with_projections(
                    RuntimeState(novel_id=self.novel_id)
                )
                runtime_restored = True

            state_store = BookStateStore(self.project_root, self.novel_id)
            state = state_store.load_or_create()
            state.current_chapter = previous_chapter
            state.current_section = "" if not previous_chapter else state.current_section
            state.stage = (
                BookStage.CHAPTER_PREFLIGHT
                if previous_chapter
                else BookStage.ROLLING_OUTLINE
            )
            state.pending_confirmation = ""
            state.blocking_reason = ""
            state.last_agent_action = "manual_chapter_deleted"
            state_store.save(state)

        try:
            CharacterStateIndex(self.project_root, self.novel_id).refresh()
        except Exception as exc:
            logger.warning("Failed to refresh character state index after deletion: %s", exc)

        self._debug_event(
            "chapter_delete_completed",
            chapter_id=chapter_id,
            previous_chapter=previous_chapter,
            backup_version=backup.version_id,
            runtime_restored=runtime_restored,
        )
        return {
            "ok": True,
            "chapter_id": chapter_id,
            "previous_chapter": previous_chapter,
            "backup": backup.model_dump(mode="json"),
            "runtime_restored": runtime_restored,
            "checkpoint": git_checkpoint.to_dict(),
            "workspace": self.workspace(),
        }

    def _checkpoint_message(self, path: Path) -> str:
        relative = self._relative(path)
        if relative == "src/outline.md":
            prefix = "outline"
        elif relative.startswith("src/story/"):
            prefix = "core"
        elif relative.startswith("src/characters/"):
            prefix = "character"
        elif relative.startswith(("src/world/", "src/progression/")):
            prefix = "setting"
        elif relative.startswith("data/manuscript/"):
            prefix = "chapter"
        else:
            prefix = "checkpoint"
        return f"{prefix}: save {path.stem} from Studio"

    def update_focus(self, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            self._service().update_focus(
                goal=str(payload.get("goal") or ""),
                must_keep=self._string_list(payload.get("must_keep")),
                must_avoid=self._string_list(payload.get("must_avoid")),
                notes=self._string_list(payload.get("notes")),
            )
        except NovelServiceError as exc:
            raise self._translate_service_error(exc) from exc
        return self.workspace()

    def update_writing_targets(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.require_project()
        current = normalize_writing_targets(self.config.get("writing_targets"))
        try:
            targets = normalize_writing_targets(
                payload,
                base=current,
                strict=True,
            )
        except ValueError as exc:
            raise StudioError(str(exc), HTTPStatus.BAD_REQUEST) from exc

        with self._write_lock:
            config = self._load_config()
            config["writing_targets"] = targets
            content = yaml.safe_dump(config, allow_unicode=True, sort_keys=False)
            descriptor, temp_name = tempfile.mkstemp(
                prefix=".novel_config.",
                suffix=".yaml.tmp",
                dir=str(self.config_path.parent),
            )
            temp_path = Path(temp_name)
            try:
                with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                    handle.write(content)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(temp_path, self.config_path)
            finally:
                temp_path.unlink(missing_ok=True)
            self.config = config
            if self._novel_service is not None:
                self._novel_service.refresh()

        self._debug_event("writing_targets_updated", **targets)
        return self.workspace()

    def configure_model(self, payload: dict[str, Any]) -> dict[str, Any]:
        settings = self._validated_model_settings(payload)
        supplied_api_key = str(payload.get("api_key") or "").strip()
        os.environ["LLM_PROVIDER"] = settings["provider"]
        os.environ["LLM_MODEL"] = settings["model"]
        os.environ["LLM_API_FORMAT"] = settings["api_format"]
        os.environ["LLM_BASE_URL"] = settings["base_url"]
        os.environ["OPENWRITE_CONTEXT_TOKENS"] = str(settings["context_tokens"])
        os.environ["LLM_MAX_TOKENS"] = str(settings["max_tokens"])
        if settings["api_key"]:
            os.environ["LLM_API_KEY"] = settings["api_key"]
        remember_api_key = bool(payload.get("remember_api_key", True))
        persisted = {
            key: settings[key]
            for key in (
                "provider",
                "model",
                "api_format",
                "base_url",
                "context_tokens",
                "max_tokens",
            )
        }
        persisted["remember_api_key"] = remember_api_key
        try:
            self._model_settings_store.save_settings(persisted)
            if not remember_api_key:
                self._model_settings_store.clear_credential()
            elif supplied_api_key:
                self._model_settings_store.save_credential(supplied_api_key)
        except OSError as exc:
            raise StudioError("模型已应用，但本机持久化失败，请检查配置目录权限") from exc
        self._saved_model_settings = persisted
        try:
            self._model_profile_store.save_profile(
                {
                    "id": "default",
                    "label": "默认模型",
                    **settings,
                    "max_output_tokens": settings["max_tokens"],
                    "credential_ref": "key_default",
                },
                api_key=supplied_api_key,
                remember_api_key=remember_api_key,
            )
        except (ModelProfileError, OSError) as exc:
            raise StudioError("默认模型档案保存失败，请检查配置") from exc
        return self.workspace()

    def model_profiles(self) -> dict[str, Any]:
        try:
            return self._model_profile_store.surface(self._project_model_routes())
        except ModelProfileError as exc:
            raise self._translate_model_profile_error(exc) from exc

    def save_model_profile(self, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            profile = self._model_profile_store.save_profile(
                payload,
                api_key=str(payload.get("api_key") or ""),
                embedding_api_key=str(payload.get("embedding_api_key") or ""),
                remember_api_key=bool(payload.get("remember_api_key", True)),
            )
        except (ModelProfileError, OSError) as exc:
            if isinstance(exc, ModelProfileError):
                raise self._translate_model_profile_error(exc) from exc
            raise StudioError("模型档案保存失败，请检查配置目录权限") from exc
        return {
            "profile": profile,
            "model_profiles": self.model_profiles(),
            "workspace": self.workspace(),
        }

    def save_model_routes(self, payload: dict[str, Any]) -> dict[str, Any]:
        routes = payload.get("routes")
        if not isinstance(routes, dict):
            raise StudioError("routes 必须是 JSON 对象", code="INVALID_REQUEST_BODY")
        try:
            self._model_profile_store.save_routes(routes)
        except (ModelProfileError, OSError) as exc:
            if isinstance(exc, ModelProfileError):
                raise self._translate_model_profile_error(exc) from exc
            raise StudioError("任务路由保存失败，请检查配置目录权限") from exc
        return {"model_profiles": self.model_profiles()}

    def delete_model_profile(self, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            result = self._model_profile_store.delete_profile(
                str(payload.get("profile_id") or ""),
                fallback_id=str(payload.get("fallback_id") or ""),
                project_routes=self._project_model_routes(),
            )
        except (ModelProfileError, OSError) as exc:
            if isinstance(exc, ModelProfileError):
                raise self._translate_model_profile_error(exc) from exc
            raise StudioError("模型档案删除失败，请检查配置目录权限") from exc
        return {**result, "model_profiles": self.model_profiles()}

    def test_model_connection(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Validate a candidate connection without replacing active settings."""
        if payload.get("id"):
            try:
                candidate = self._model_profile_store.test_candidate(
                    payload,
                    api_key=str(payload.get("api_key") or ""),
                )
            except ModelProfileError as exc:
                raise self._translate_model_profile_error(exc) from exc
            settings = {
                **candidate,
                "max_tokens": candidate["max_output_tokens"],
            }
        else:
            settings = self._validated_model_settings(payload)
        started = time.monotonic()
        try:
            if self._model_test_executor is not None:
                result = self._model_test_executor(dict(settings))
            else:
                result = self._default_model_connection_test(settings)
        except Exception as exc:
            raise StudioError(self._safe_model_connection_error(exc)) from exc
        return {
            "ok": True,
            "provider": settings["provider"],
            "model": settings["model"],
            "latency_ms": max(1, int((time.monotonic() - started) * 1000)),
            "reply": str(result.get("reply") or "OK")[:120] if isinstance(result, dict) else "OK",
        }

    def test_embedding_connection(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Probe the candidate embedding route without saving or exposing credentials."""
        from tools.embedding_runtime import (
            EmbeddingRuntimeError,
            EmbeddingSettings,
            run_embedding_probe,
        )

        try:
            candidate = self._model_profile_store.test_embedding_candidate(
                payload,
                api_key=str(payload.get("api_key") or ""),
                embedding_api_key=str(payload.get("embedding_api_key") or ""),
            )
            settings = EmbeddingSettings(
                provider=str(candidate.get("embedding_provider") or "openai"),
                model=str(candidate.get("embedding_model") or ""),
                dimension=int(candidate.get("embedding_dimension") or 0),
                max_tokens=int(candidate.get("embedding_max_tokens") or 0),
                base_url=str(
                    candidate.get("embedding_base_url")
                    or candidate.get("base_url")
                    or ""
                ),
                api_key=str(candidate.get("embedding_api_key") or ""),
                timeout_seconds=max(1, int(candidate.get("timeout_seconds") or 120)),
            )
            return run_embedding_probe(settings)
        except ModelProfileError as exc:
            raise self._translate_model_profile_error(exc) from exc
        except EmbeddingRuntimeError as exc:
            raise StudioError(str(exc), HTTPStatus.BAD_GATEWAY) from exc

    def _validated_model_settings(self, payload: dict[str, Any]) -> dict[str, Any]:
        provider = str(payload.get("provider") or "openai").strip().lower()
        model = str(payload.get("model") or "").strip()
        base_url = str(payload.get("base_url") or "").strip()
        api_format = str(payload.get("api_format") or "chat").strip().lower()
        api_key = str(payload.get("api_key") or "").strip()
        if provider not in {"openai", "anthropic", "custom"}:
            raise StudioError("模型提供方无效")
        if api_format not in {"chat", "responses"}:
            raise StudioError("API 格式无效")
        if not model or len(model) > 120:
            raise StudioError("模型名称不能为空且不能超过 120 字")
        defaults = {
            "openai": "https://api.openai.com/v1",
            "anthropic": "https://api.anthropic.com",
        }
        base_url = base_url or defaults.get(provider, "")
        if provider == "custom" and not base_url:
            raise StudioError("自定义模型必须填写 Base URL")
        if base_url:
            parsed = urlparse(base_url)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                raise StudioError("Base URL 必须是有效的 HTTP(S) 地址")
        api_key = api_key or os.environ.get("LLM_API_KEY", "").strip()
        if not api_key:
            raise StudioError("API Key 不能为空")
        context_tokens = self._bounded_int(
            payload.get("context_tokens"),
            default=self._env_int("OPENWRITE_CONTEXT_TOKENS", 64000),
            minimum=12000,
            maximum=MAX_CONTEXT_TOKENS,
            label="上下文预算",
        )
        max_tokens = self._bounded_int(
            payload.get("max_tokens"),
            default=self._env_int("LLM_MAX_TOKENS", 24000),
            minimum=256,
            maximum=MAX_OUTPUT_TOKENS,
            label="最大输出",
        )
        if max_tokens >= context_tokens:
            raise StudioError("最大输出必须小于上下文预算，以便为输入保留空间")
        return {
            "provider": provider,
            "model": model,
            "base_url": base_url.rstrip("/"),
            "api_format": api_format,
            "api_key": api_key,
            "context_tokens": context_tokens,
            "max_tokens": max_tokens,
        }

    def _model_payload(self) -> dict[str, Any]:
        profiles = self.model_profiles()
        profile_by_id = {
            str(profile.get("id") or ""): profile
            for profile in profiles.get("profiles", [])
            if isinstance(profile, dict)
        }
        default_profile = profile_by_id.get(str(profiles.get("default_profile_id") or ""))
        routed_ids = [
            str(profile_id or "")
            for profile_id in profiles.get("routes", {}).values()
        ]
        configured_profile = (
            default_profile
            if default_profile and bool(default_profile.get("configured"))
            else next(
                (
                    profile_by_id[profile_id]
                    for profile_id in routed_ids
                    if profile_id in profile_by_id
                    and bool(profile_by_id[profile_id].get("configured"))
                ),
                None,
            )
        )
        legacy_configured = bool(os.environ.get("LLM_API_KEY", "").strip())
        provider = (
            str(configured_profile.get("provider") or "openai").strip().lower()
            if configured_profile
            else os.environ.get("LLM_PROVIDER", "openai").strip().lower()
        ) or "openai"
        base_url = (
            str(configured_profile.get("base_url") or "").strip()
            if configured_profile
            else os.environ.get("LLM_BASE_URL", "").strip()
        )
        if not base_url:
            base_url = (
                "https://api.anthropic.com"
                if provider == "anthropic"
                else "https://api.openai.com/v1"
            )
        return {
            "configured": bool(configured_profile) or legacy_configured,
            "provider": provider,
            "base_url": base_url,
            "name": (
                str(configured_profile.get("model") or "").strip()
                if configured_profile
                else os.environ.get("LLM_MODEL", "").strip()
            ) or "gpt-4o-mini",
            "api_format": (
                str(configured_profile.get("api_format") or "").strip()
                if configured_profile
                else os.environ.get("LLM_API_FORMAT", "chat").strip()
            ) or "chat",
            "context_tokens": (
                int(configured_profile.get("context_tokens") or 64000)
                if configured_profile
                else self._env_int("OPENWRITE_CONTEXT_TOKENS", 64000)
            ),
            "max_tokens": (
                int(configured_profile.get("max_output_tokens") or 24000)
                if configured_profile
                else self._env_int("LLM_MAX_TOKENS", 24000)
            ),
            "persistence": {
                "settings_saved": self._model_settings_store.settings_persisted,
                "credential_saved": self._model_settings_store.credential_persisted,
                "remember_api_key": bool(self._saved_model_settings.get("remember_api_key", False)),
            },
        }

    def _project_model_routes(self) -> dict[str, Any]:
        routes = self.config.get("model_routes") if isinstance(self.config, dict) else None
        return routes if isinstance(routes, dict) else {}

    def _operation_profile(
        self,
        operation: str,
        *,
        injected_executor: Any = None,
    ) -> dict[str, Any] | None:
        try:
            return self._model_profile_store.resolve(
                operation,
                self._project_model_routes(),
            )
        except ModelProfileError as exc:
            if injected_executor is not None:
                return None
            raise self._translate_model_profile_error(exc) from exc

    def _model_context(self, profile: dict[str, Any] | None):
        search_profile = None
        try:
            search_profile = self._model_profile_store.resolve(
                "search", self._project_model_routes()
            )
        except ModelProfileError:
            pass
        primary_profile = profile or search_profile
        if not primary_profile:
            return nullcontext()
        return activate_model_profile(
            primary_profile,
            search_profile=search_profile,
        )

    @staticmethod
    def _translate_model_profile_error(exc: ModelProfileError) -> StudioError:
        status = {
            "MODEL_PROFILE_NOT_CONFIGURED": HTTPStatus.PRECONDITION_FAILED,
            "MODEL_CREDENTIAL_MISSING": HTTPStatus.PRECONDITION_FAILED,
            "MODEL_PROFILE_NOT_FOUND": HTTPStatus.NOT_FOUND,
            "MODEL_PROFILE_IN_USE": HTTPStatus.CONFLICT,
            "MODEL_PROFILE_LAST_PROFILE": HTTPStatus.CONFLICT,
        }.get(exc.code, HTTPStatus.BAD_REQUEST)
        return StudioError(
            str(exc),
            status,
            code=exc.code,
            recoverable=exc.code in {
                "MODEL_PROFILE_NOT_CONFIGURED",
                "MODEL_CREDENTIAL_MISSING",
                "MODEL_PROFILE_IN_USE",
            },
        )

    @staticmethod
    def _safe_model_connection_error(exc: Exception) -> str:
        """Map provider errors to useful messages without echoing credentials."""
        message = str(exc).lower()
        if any(term in message for term in ("401", "unauthorized", "authentication", "api key")):
            return "连接测试失败：认证失败，请检查 API Key。"
        if any(term in message for term in ("404", "not found", "model_not_found")):
            return "连接测试失败：模型或 API 地址不存在，请检查模型名称和 Base URL。"
        if any(term in message for term in ("429", "rate limit", "too many requests")):
            return "连接测试失败：服务商限流或额度不足，请稍后重试并检查账户额度。"
        if any(term in message for term in ("timeout", "timed out")):
            return "连接测试失败：请求超时，请检查网络和 Base URL。"
        if any(term in message for term in ("connection", "dns", "name resolution")):
            return "连接测试失败：无法连接到服务商，请检查网络和 Base URL。"
        if "empty model reply" in message or "模型返回空内容" in message:
            return "连接测试失败：模型返回空内容，请调大最大输出后重试。"
        return f"连接测试失败：{type(exc).__name__}。请检查模型配置。"

    @staticmethod
    def _env_int(name: str, default: int) -> int:
        try:
            return int(os.environ.get(name, str(default)))
        except ValueError:
            return default

    @staticmethod
    def _bounded_int(
        value: Any,
        *,
        default: int,
        minimum: int,
        maximum: int,
        label: str,
    ) -> int:
        try:
            parsed = int(value) if value not in {None, ""} else default
        except (TypeError, ValueError) as exc:
            raise StudioError(f"{label}必须是整数") from exc
        if not minimum <= parsed <= maximum:
            raise StudioError(f"{label}必须在 {minimum}-{maximum} 之间")
        return parsed

    @staticmethod
    def _default_model_connection_test(settings: dict[str, Any]) -> dict[str, Any]:
        from tools.llm import LLMClient, LLMConfig, Message

        config = LLMConfig(
            provider=settings["provider"],
            api_key=settings["api_key"],
            base_url=settings["base_url"],
            model=settings["model"],
            max_tokens=settings["max_tokens"],
            api_format=settings["api_format"],
            stream=False,
            timeout_seconds=30,
            max_retries=0,
        )
        response = LLMClient(config).chat(
            [Message("user", "这是连接测试。请只回复 OK。")],
            temperature=0,
            max_tokens=32,
            stream=False,
        )
        reply = response.content.strip()
        if not reply:
            raise RuntimeError("empty model reply")
        return {"reply": reply}

    def sync_project(self) -> dict[str, Any]:
        try:
            result = self._service().sync()
        except NovelServiceError as exc:
            raise self._translate_service_error(exc) from exc
        return {**result, "workspace": self.workspace()}

    def create_document(self, payload: dict[str, Any]) -> dict[str, Any]:
        kind = str(payload.get("kind") or "").strip()
        name = str(payload.get("name") or "").strip()
        description = str(payload.get("description") or "").strip()
        self._debug_event(
            "document_create_requested",
            kind=kind,
            name=name,
            description=description,
        )
        with self._write_lock:
            try:
                path = self._service().create_document(
                    kind=kind,
                    name=name,
                    description=description,
                )
            except NovelServiceError as exc:
                raise self._translate_service_error(exc) from exc
        document = self.read_document(self._relative(path))
        self._debug_event(
            "document_create_completed",
            kind=kind,
            name=name,
            path=document.get("path"),
        )
        return {"document": document, "workspace": self.workspace()}

    def import_text(self, payload: dict[str, Any]) -> dict[str, Any]:
        filename = str(payload.get("filename") or "import.md").strip()
        content = str(payload.get("content") or "")
        if not content.strip():
            raise StudioError("导入内容不能为空")
        suffix = Path(filename).suffix.lower()
        if suffix not in {".txt", ".md", ".markdown"}:
            raise StudioError("当前仅支持 TXT 和 Markdown 导入")
        arc_id = str(payload.get("arc_id") or self.config.get("current_arc") or "arc_001")
        if not re.fullmatch(r"arc_\d+", arc_id):
            raise StudioError("篇 ID 必须形如 arc_001")
        start_number = payload.get("start_number")
        if start_number in {None, ""}:
            start = None
        else:
            try:
                start = int(start_number)
            except (TypeError, ValueError) as exc:
                raise StudioError("起始章节必须是整数") from exc
        with self._write_lock, tempfile.TemporaryDirectory(prefix="openwrite-import-") as temp_dir:
            source = Path(temp_dir) / f"source{suffix}"
            source.write_text(content, encoding="utf-8")
            try:
                result = self._service().import_book(
                    source,
                    arc_id=arc_id,
                    start_number=start,
                    force=bool(payload.get("force")),
                )
            except NovelServiceError as exc:
                raise self._translate_service_error(exc) from exc
        return {
            "imported": result["imported"],
            "workspace": self.workspace(),
        }

    def preview_import(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Parse an import without writing chapters or advancing project state."""
        self.require_project()
        filename = str(payload.get("filename") or "import.md").strip()
        content = str(payload.get("content") or "")
        if not content.strip():
            raise StudioError("导入内容不能为空")
        suffix = Path(filename).suffix.lower()
        if suffix not in {".txt", ".md", ".markdown"}:
            raise StudioError("当前仅支持 TXT 和 Markdown 导入")
        arc_id = str(payload.get("arc_id") or self.config.get("current_arc") or "arc_001")
        if not re.fullmatch(r"arc_\d+", arc_id):
            raise StudioError("篇 ID 必须形如 arc_001")

        existing = list_chapters(self.project_root, self.novel_id)
        start_number = payload.get("start_number")
        if start_number in {None, ""}:
            numbers = [
                int(match.group(1))
                for item in existing
                if (match := re.fullmatch(r"ch_(\d+)", item.chapter_id))
            ]
            start = max(numbers, default=0) + 1
        else:
            try:
                start = int(start_number)
            except (TypeError, ValueError) as exc:
                raise StudioError("起始章节必须是整数") from exc
        if start < 1:
            raise StudioError("起始章节号必须大于 0")

        chunks = split_manuscript(content.strip(), fallback_title=Path(filename).stem)
        target_dir = self.novel_root / "data" / "manuscript" / arc_id
        chapters: list[dict[str, Any]] = []
        for offset, (title, body) in enumerate(chunks):
            chapter_id = f"ch_{start + offset:03d}"
            normalized = f"# {title.strip()}\n\n{body.strip()}\n"
            path = target_dir / f"{chapter_id}.md"
            chapters.append(
                {
                    "chapter_id": chapter_id,
                    "title": title.strip(),
                    "writing_units": count_writing_units(normalized),
                    "exists": path.exists(),
                    "preview": re.sub(r"\s+", " ", body.strip())[:160],
                }
            )
        conflicts = [item["chapter_id"] for item in chapters if item["exists"]]
        force = bool(payload.get("force"))
        return {
            "filename": filename,
            "arc_id": arc_id,
            "start_number": start,
            "chapter_count": len(chapters),
            "writing_units": sum(int(item["writing_units"]) for item in chapters),
            "detected_headings": len(chunks) > 1,
            "conflicts": conflicts,
            "can_import": not conflicts or force,
            "force": force,
            "chapters": chapters,
        }

    def context_preview(self, chapter_id: str) -> dict[str, Any]:
        profile = self._operation_profile(
            "chapter_write",
            injected_executor=self._service(),
        )
        try:
            with self._model_context(profile):
                result = self._service().context_preview(chapter_id)
        except NovelServiceError as exc:
            raise self._translate_service_error(exc) from exc
        packet = result.pop("packet", None)
        if isinstance(packet, dict):
            result["manifest"] = build_context_manifest(self.novel_root, packet)
        return result

    def outline_structure(self, chapter_id: str = "") -> dict[str, Any]:
        """Return the live outline tree and an optional chapter recommendation."""
        self.require_project()
        return build_outline_structure(
            self.novel_root,
            chapter_id=chapter_id,
            writing_targets=normalize_writing_targets(
                self.config.get("writing_targets")
            ),
        )

    def edit_outline_structure(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Apply one atomic tree edit while preserving the Markdown source of truth."""
        self.require_project()
        document = self.read_document("src/outline.md")
        self._debug_event(
            "outline_edit_requested",
            operation=payload.get("operation"),
            node_id=payload.get("node_id"),
            kind=payload.get("kind"),
            title=payload.get("title"),
            summary=payload.get("summary"),
            revision=payload.get("revision"),
        )
        try:
            edit = mutate_outline_structure(
                self.novel_root,
                operation=str(payload.get("operation") or ""),
                revision=str(payload.get("revision") or ""),
                node_id=str(payload.get("node_id") or ""),
                title=str(payload.get("title") or ""),
                summary=str(payload.get("summary") or ""),
                kind=str(payload.get("kind") or ""),
            )
        except OutlineEditError as exc:
            status = HTTPStatus.CONFLICT if exc.code == "conflict" else HTTPStatus.BAD_REQUEST
            raise StudioError(str(exc), status) from exc
        saved = self.write_document(
            "src/outline.md",
            str(edit["content"]),
            document["version"],
        )
        outline = self.outline_structure()
        selected_node_id = self._resolve_outline_selection(
            outline,
            edit.get("selection_hint", {}),
        )
        result = {
            "outline": outline,
            "selected_node_id": selected_node_id,
            "message": str(edit["message"]),
            "renumbered": edit.get("renumbered", []),
            "skipped_renumbering": edit.get("skipped_renumbering", []),
            "checkpoint": saved.get("checkpoint", {}),
        }
        self._debug_event(
            "outline_edit_completed",
            operation=payload.get("operation"),
            node_id=payload.get("node_id"),
            selected_node_id=selected_node_id,
            message=result["message"],
            renumbered=result["renumbered"],
            skipped_renumbering=result["skipped_renumbering"],
        )
        return result

    @staticmethod
    def _resolve_outline_selection(outline: dict[str, Any], hint: dict[str, Any]) -> str:
        nodes: list[dict[str, Any]] = []
        pending = list(reversed(outline.get("roots", [])))
        while pending:
            node = pending.pop()
            nodes.append(node)
            pending.extend(reversed(node.get("children", [])))
        parent_id = str(hint.get("parent_id") or "")
        if parent_id and any(node["id"] == parent_id for node in nodes):
            return parent_id
        matches = [
            node
            for node in nodes
            if node.get("kind") == hint.get("kind") and node.get("title") == hint.get("title")
        ]
        if matches:
            expected_line = int(hint.get("line") or matches[0]["line"])
            return min(matches, key=lambda node: abs(int(node["line"]) - expected_line))["id"]
        return str(outline.get("recommendation", {}).get("chapter_id") or "")

    def search_project(self, query: str, scope: str = "all", limit: int = 20) -> dict[str, Any]:
        self.require_project()
        try:
            profile = self._operation_profile(
                "search",
                injected_executor=ProjectSearchIndex,
            )
            with self._model_context(profile):
                return ProjectSearchIndex(self.novel_root).search(
                    query,
                    scope=scope,
                    limit=limit,
                )
        except (OSError, ValueError) as exc:
            raise StudioError(str(exc)) from exc

    def continuity(self) -> dict[str, Any]:
        try:
            return self._service().continuity()
        except NovelServiceError as exc:
            raise self._translate_service_error(exc) from exc

    def manage_foreshadowing(self, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            result = self._service().manage_foreshadowing(payload)
        except NovelServiceError as exc:
            raise self._translate_service_error(exc) from exc
        return {**result, "workspace": self.workspace()}

    def agent_surface(
        self,
        agent_name: str,
        limit: int = 200,
        session_id: str | None = None,
    ) -> dict[str, Any]:
        """Expose the live Agent tool catalog and persisted transcript to Studio."""
        self.require_project()
        agent_name = self._normalize_agent_name(agent_name)
        active_session_id = self._normalize_agent_session_id(session_id)
        limit = max(1, min(int(limit), 500))
        return {
            "agent": agent_name,
            "active_session_id": active_session_id,
            "sessions": self._agent_session_catalog(agent_name),
            "tools": self._agent_tool_catalog(agent_name),
            "history": self._agent_history(agent_name, limit, active_session_id),
        }

    def create_agent_session(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.require_project()
        agent_name = self._normalize_agent_name(payload.get("agent") or "goethe")
        session_id = self._new_agent_session_id(agent_name)
        self._debug_event(
            "agent_session_create_requested",
            agent=agent_name,
            session_id=session_id,
        )
        self._agent_session_store(agent_name, session_id).load_or_create()
        result = {
            **self.agent_surface(agent_name, limit=80, session_id=session_id),
            "created": True,
        }
        self._debug_event(
            "agent_session_create_completed",
            agent=agent_name,
            session_id=session_id,
        )
        return result

    def delete_agent_session(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.require_project()
        agent_name = self._normalize_agent_name(payload.get("agent") or "goethe")
        session_id = self._normalize_agent_session_id(payload.get("session_id"))
        clearing_default = session_id == "default"
        store = self._agent_session_store(agent_name, session_id)
        session_root = self.novel_root / "data" / "workflows" / "sessions" / agent_name
        self._debug_event(
            "agent_session_delete_requested",
            agent=agent_name,
            session_id=session_id,
            clearing_default=clearing_default,
            state_path=self._project_relative_path(store.path),
            transcript_path=self._project_relative_path(store.transcript_path),
        )
        candidates = {
            store.path,
            store.transcript_path,
            session_root / f"{store.path.stem}.yml",
        }
        deleted_files = []
        for path in sorted(candidates):
            if not path.exists():
                continue
            try:
                path.unlink()
            except OSError as exc:
                raise StudioError(f"删除会话失败: {path.name}") from exc
            deleted_files.append(self._project_relative_path(path))
        result = {
            **self.agent_surface(agent_name, limit=80, session_id="default"),
            "deleted": not clearing_default,
            "cleared": clearing_default,
            "deleted_session_id": session_id,
            "deleted_files": deleted_files,
        }
        self._debug_event(
            "agent_session_delete_completed",
            agent=agent_name,
            session_id=session_id,
            clearing_default=clearing_default,
            deleted_files=deleted_files,
        )
        return result

    @staticmethod
    def _normalize_agent_name(agent_name: Any) -> str:
        normalized = str(agent_name or "goethe").strip().lower()
        if normalized not in {"goethe", "dante"}:
            raise StudioError("Agent 仅支持 goethe 或 dante")
        return normalized

    @staticmethod
    def _normalize_agent_session_id(session_id: Any) -> str:
        normalized = str(session_id or "default").strip()
        if normalized in {"", "default"}:
            return "default"
        if len(normalized) > 128 or not re.fullmatch(
            r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", normalized
        ):
            raise StudioError("会话 ID 格式无效")
        return normalized

    @staticmethod
    def _new_agent_session_id(agent_name: str) -> str:
        timestamp = time.strftime("%Y%m%d-%H%M%S")
        return f"{agent_name}-{timestamp}-{uuid.uuid4().hex[:6]}"

    def _agent_session_store(self, agent_name: str, session_id: str | None):
        normalized = self._normalize_agent_session_id(session_id)
        store_session_id = None if normalized == "default" else normalized
        if agent_name == "goethe":
            from tools.agent.goethe_session_state import GoetheSessionStateStore

            return GoetheSessionStateStore(
                self.project_root,
                self.novel_id,
                session_id=store_session_id,
            )
        from tools.agent.session_state import SessionStateStore

        return SessionStateStore(
            self.project_root,
            self.novel_id,
            session_id=store_session_id,
        )

    def _agent_session_catalog(self, agent_name: str) -> list[dict[str, Any]]:
        sessions = [
            self._agent_session_summary(
                agent_name,
                "default",
                self._agent_session_store(agent_name, "default"),
                is_default=True,
            )
        ]
        session_root = self.novel_root / "data" / "workflows" / "sessions" / agent_name
        if session_root.is_dir():
            stems = {
                path.stem
                for path in session_root.iterdir()
                if path.is_file() and path.suffix in {".jsonl", ".yaml", ".yml"}
            }
            for stem in sorted(stems):
                sessions.append(
                    self._agent_session_summary(
                        agent_name,
                        stem,
                        self._agent_session_store(agent_name, stem),
                        is_default=False,
                    )
                )
        default = sessions[:1]
        named = sorted(
            sessions[1:],
            key=lambda item: str(item.get("updated_at") or ""),
            reverse=True,
        )
        return default + named

    def _agent_session_summary(
        self,
        agent_name: str,
        session_id: str,
        store: Any,
        *,
        is_default: bool,
    ) -> dict[str, Any]:
        transcript = self._read_agent_transcript(store.transcript_path, limit=1)
        state_updated = self._read_agent_state_updated_at(store.path)
        updated_at = transcript.get("updated_at") or state_updated
        first_user = str(transcript.get("first_user") or "").strip()
        last_preview = str(transcript.get("last_preview") or "").strip()
        label = "初始会话" if is_default else "新会话"
        title_source = first_user or last_preview
        title = self._agent_session_title(title_source, label)
        return {
            "id": session_id,
            "title": title,
            "agent": agent_name,
            "messages": int(transcript.get("total") or 0),
            "updated_at": updated_at,
            "preview": self._agent_session_preview(last_preview),
            "is_default": is_default,
            "state_path": self._project_relative_path(store.path),
            "transcript_path": self._project_relative_path(store.transcript_path),
            "exists": store.path.exists() or store.transcript_path.exists(),
        }

    @staticmethod
    def _agent_session_title(content: str, fallback: str) -> str:
        compact = " ".join(str(content or "").split())
        if not compact:
            return fallback
        return compact[:28] + ("..." if len(compact) > 28 else "")

    @staticmethod
    def _agent_session_preview(content: str) -> str:
        compact = " ".join(str(content or "").split())
        return compact[:64] + ("..." if len(compact) > 64 else "")

    @staticmethod
    def _read_agent_state_updated_at(path: Path) -> str:
        if not path.is_file():
            return ""
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, yaml.YAMLError):
            return ""
        if not isinstance(data, dict):
            return ""
        return str(data.get("updated_at") or "")

    def _project_relative_path(self, path: Path) -> str:
        try:
            return path.relative_to(self.novel_root).as_posix()
        except ValueError:
            return str(path)

    @staticmethod
    def _agent_tool_catalog(agent_name: str) -> list[dict[str, str]]:
        if agent_name == "goethe":
            from tools.agent.toolkits import GOETHE_ACTION_TOOLKIT
            from tools.goethe import _build_goethe_tool_definitions

            definitions = _build_goethe_tool_definitions()
            action_tools = GOETHE_ACTION_TOOLKIT
        else:
            from tools.agent.dante import _build_dante_tool_definitions
            from tools.agent.toolkits import DANTE_ACTION_TOOLKIT

            definitions = _build_dante_tool_definitions()
            action_tools = DANTE_ACTION_TOOLKIT
        return [
            {
                "name": tool.name,
                "description": tool.description,
                "kind": "action" if tool.name in action_tools else "direct",
            }
            for tool in definitions
        ]

    def _read_agent_transcript(self, path: Path, limit: int) -> dict[str, Any]:
        records: deque[dict[str, Any]] = deque(maxlen=limit)
        total = 0
        first_user = ""
        last_preview = ""
        updated_at = ""
        if path.is_file():
            try:
                with path.open("r", encoding="utf-8") as handle:
                    for line in handle:
                        try:
                            record = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        if not isinstance(record, dict):
                            continue
                        role = str(record.get("role") or "").strip().lower()
                        content = str(record.get("content") or "")
                        if role not in {"user", "assistant"} or not content:
                            continue
                        total += 1
                        if role == "user" and not first_user:
                            first_user = content
                        last_preview = content
                        updated_at = str(record.get("timestamp") or updated_at)
                        records.append(
                            {
                                "role": role,
                                "content": content,
                                "content_html": (
                                    render_chat_markdown(content) if role == "assistant" else ""
                                ),
                                "timestamp": str(record.get("timestamp") or ""),
                            }
                        )
            except (OSError, UnicodeDecodeError):
                records.clear()
                total = 0
                first_user = ""
                last_preview = ""
                updated_at = ""
        return {
            "messages": list(records),
            "shown": len(records),
            "total": total,
            "has_more": total > len(records),
            "first_user": first_user,
            "last_preview": last_preview,
            "updated_at": updated_at,
        }

    def _agent_history(
        self,
        agent_name: str,
        limit: int,
        session_id: str | None = None,
    ) -> dict[str, Any]:
        store = self._agent_session_store(agent_name, session_id)
        transcript = self._read_agent_transcript(store.transcript_path, limit)
        session_id = self._normalize_agent_session_id(session_id)
        return {
            **transcript,
            "session_id": session_id,
            "path": self._project_relative_path(store.transcript_path),
        }

    def chat_turn(self, payload: dict[str, Any]) -> dict[str, Any]:
        agent_name = self._normalize_agent_name(payload.get("agent") or "dante")
        profile = self._operation_profile(
            agent_name,
            injected_executor=self._chat_executor,
        )
        session_id = self._normalize_agent_session_id(payload.get("session_id"))
        run_id = self._normalize_activity_run_id(payload.get("run_id"))
        message = str(payload.get("message") or "").strip()
        if not message or len(message) > 12000:
            raise StudioError("消息不能为空且不能超过 12000 字")
        self._start_agent_activity(
            run_id,
            agent=agent_name,
            session_id=session_id,
        )
        if not self._write_lock.acquire(blocking=False):
            self._finish_agent_activity(
                run_id,
                status="error",
                message="已有 AI 任务正在运行。",
            )
            raise StudioError("已有 AI 任务正在运行", HTTPStatus.CONFLICT)
        self._debug_event(
            "chat_turn_started",
            agent=agent_name,
            session_id=session_id,
            run_id=run_id,
            message_chars=len(message),
            message_preview=message,
            book_state=self._debug_book_state(),
        )
        try:
            with self._model_context(profile):
                if self._chat_executor is not None:
                    self._record_agent_activity(
                        run_id,
                        {"event": "model_started", "turn": 1},
                    )
                    result = self._chat_executor(
                        self.project_root, self.novel_id, agent_name, message
                    )
                    self._record_agent_activity(
                        run_id,
                        {"event": "response_ready", "turn": 1},
                    )
                elif agent_name == "goethe":
                    from tools.goethe import GoetheChatAgent

                    session_store = self._agent_session_store(agent_name, session_id)
                    response = GoetheChatAgent(
                        self.project_root,
                        self.novel_id,
                        session_store=session_store,
                        activity_callback=lambda event: self._record_agent_activity(
                            run_id, event
                        ),
                    ).respond(message)
                    result = {"content": response}
                else:
                    from tools.agent.dante import DanteChatAgent
                    from tools.agent.tool_layers import build_dante_tool_layers

                    layers = build_dante_tool_layers(self.project_root)
                    session_store = self._agent_session_store(agent_name, session_id)
                    agent = DanteChatAgent(
                        self.project_root,
                        self.novel_id,
                        session_store=session_store,
                        tool_executors=layers.get("direct_tool_executors", {}),
                        action_executors=layers.get("action_tool_executors", {}),
                        activity_callback=lambda event: self._record_agent_activity(
                            run_id, event
                        ),
                    )
                    result = {"content": agent.respond(message)}
        except Exception as exc:
            self._finish_agent_activity(
                run_id,
                status="error",
                message=str(exc),
            )
            from tools.llm.response import ProviderResponseError

            if isinstance(exc, ProviderResponseError):
                raise StudioError(
                    str(exc),
                    HTTPStatus.BAD_GATEWAY,
                    code=exc.code,
                    recoverable=True,
                    details={**exc.details, "failed_tool_executed": False},
                ) from exc
            raise
        finally:
            self._write_lock.release()
        if result.get("error"):
            self._debug_event(
                "chat_turn_failed",
                agent=agent_name,
                session_id=session_id,
                error=str(result["error"]),
                book_state=self._debug_book_state(),
            )
            self._finish_agent_activity(
                run_id,
                status="error",
                message=str(result["error"]),
            )
            raise StudioError(str(result["error"]), HTTPStatus.BAD_GATEWAY)
        content = str(result.get("content") or "")
        self._finish_agent_activity(run_id, status="complete")
        self._debug_event(
            "chat_turn_completed",
            agent=agent_name,
            session_id=session_id,
            content_chars=len(content),
            content_preview=content,
            book_state=self._debug_book_state(),
        )
        return {
            "agent": agent_name,
            "session_id": session_id,
            "run_id": run_id,
            "content": content,
            "content_html": render_chat_markdown(content),
            "workspace": self.workspace(),
        }

    def source_action(self, payload: dict[str, Any]) -> dict[str, Any]:
        action = str(payload.get("action") or "").strip()
        source_id = str(payload.get("source_id") or "").strip()
        try:
            if action == "extract":
                profile = self._operation_profile(
                    "source_extract",
                    injected_executor=self._source_executor,
                )
                text = str(payload.get("content") or "")
                if not text.strip():
                    raise StudioError("来源文本不能为空")
                with tempfile.TemporaryDirectory(prefix="openwrite-source-") as temp_dir:
                    source = Path(temp_dir) / "source.txt"
                    source.write_text(text, encoding="utf-8")
                    with self._model_context(profile):
                        result = self._service().extract_source(
                            source_id=source_id,
                            source_file=source,
                            focus=str(payload.get("focus") or "style"),
                        )
            elif action == "analyze_v2":
                profile = self._operation_profile("source_extract")
                text = str(payload.get("content") or "")
                if not text.strip():
                    raise StudioError("来源文本不能为空")
                raw_focus = payload.get("focus")
                focus = (
                    [str(item) for item in raw_focus]
                    if isinstance(raw_focus, list)
                    else None
                )
                prepared = self._service().prepare_source_analysis_v2(
                    source_id=source_id,
                    content=text,
                    relative_name=str(payload.get("relative_name") or "source.txt"),
                    focus=focus,
                    input_budget_tokens=int(payload.get("input_budget_tokens") or 12000),
                )
                with self._model_context(profile):
                    analyzed = self._service().analyze_source_v2(source_id)
                result = {"prepared": prepared, "analysis": analyzed}
            elif action == "status_v2":
                result = self._service().source_status_v2(source_id)
            elif action == "retry_v2":
                profile = self._operation_profile("source_extract")
                with self._model_context(profile):
                    result = self._service().retry_source_v2(
                        source_id, str(payload.get("chunk_id") or "")
                    )
            elif action == "synthesize_v2":
                source_ids = payload.get("source_ids")
                if not isinstance(source_ids, list):
                    raise StudioError("请选择至少一个来源")
                result = self._service().synthesize_sources_v2(
                    [str(item) for item in source_ids]
                )
            elif action == "profile_v2":
                result = self._service().source_profile_v2(
                    str(payload.get("profile_id") or "")
                )
            elif action == "promotion_preview_v2":
                result = self._service().preview_source_promotion_v2(
                    str(payload.get("profile_id") or ""),
                    str(payload.get("target") or ""),
                )
            elif action == "promote_v2":
                result = self._service().apply_source_promotion_v2(
                    str(payload.get("preview_id") or ""),
                    confirm=bool(payload.get("confirm")),
                )
            elif action == "review":
                result = self._service().review_source(source_id)
            elif action == "promote":
                result = self._service().promote_source(
                    source_id,
                    str(payload.get("target") or "all"),
                )
            elif action == "synthesize":
                profile = self._operation_profile(
                    "source_extract",
                    injected_executor=self._source_executor,
                )
                with self._model_context(profile):
                    result = self._service().synthesize_style(source_id)
            else:
                raise StudioError("未知来源操作")
        except NovelServiceError as exc:
            raise self._translate_service_error(exc) from exc
        return {"result": result, "workspace": self.workspace()}

    def reference_library_action(self, payload: dict[str, Any]) -> dict[str, Any]:
        from tools.source_analysis import SourceAnalysisError

        action = str(payload.get("action") or "").strip()
        source_id = str(payload.get("source_id") or "").strip()
        service = self._reference_library()
        try:
            if action == "list":
                result: Any = service.list()
            elif action == "prepare":
                raw_focus = payload.get("focus")
                result = service.prepare(
                    source_id,
                    str(payload.get("content") or ""),
                    title=str(payload.get("title") or ""),
                    relative_name=str(payload.get("relative_name") or "source.txt"),
                    intent=str(payload.get("intent") or "reference"),
                    focus=(
                        [str(item) for item in raw_focus]
                        if isinstance(raw_focus, list)
                        else None
                    ),
                    input_budget_tokens=int(
                        payload.get("input_budget_tokens") or 12000
                    ),
                )
            elif action == "confirm_structure":
                units = payload.get("units")
                result = service.confirm_structure(
                    source_id,
                    units=units if isinstance(units, list) else None,
                )
            elif action == "analyze":
                profile = self._operation_profile("source_extract")
                with self._model_context(profile):
                    result = service.analyze(source_id)
            elif action == "status":
                result = service.status(source_id)
            elif action == "retry":
                profile = self._operation_profile("source_extract")
                with self._model_context(profile):
                    result = service.retry(
                        source_id, str(payload.get("chunk_id") or "")
                    )
            elif action == "synthesize":
                source_ids = payload.get("source_ids")
                if not isinstance(source_ids, list):
                    raise StudioError("请选择至少一个参考作品")
                result = service.synthesize(
                    [str(item) for item in source_ids]
                ).model_dump(mode="json")
            elif action == "profile":
                result = service.profile(
                    str(payload.get("profile_id") or "")
                ).model_dump(mode="json")
            elif action == "adoption_preview":
                selections = payload.get("selections")
                if not isinstance(selections, list):
                    raise StudioError("采纳选择必须是数组")
                rejected = payload.get("rejected_item_ids")
                result = service.preview_adoption(
                    str(payload.get("profile_id") or ""),
                    [item for item in selections if isinstance(item, dict)],
                    rejected_item_ids=(
                        [str(item) for item in rejected]
                        if isinstance(rejected, list)
                        else None
                    ),
                ).model_dump(mode="json")
            elif action == "adopt":
                result = service.apply_adoption(
                    str(payload.get("preview_id") or ""),
                    confirm=bool(payload.get("confirm")),
                )
            else:
                raise StudioError("未知参考库操作")
        except SourceAnalysisError as exc:
            status = {
                "NOT_FOUND": HTTPStatus.NOT_FOUND,
                "CONFIRMATION_REQUIRED": HTTPStatus.PRECONDITION_REQUIRED,
                "DOCUMENT_CONFLICT": HTTPStatus.CONFLICT,
                "SOURCE_CHANGED": HTTPStatus.CONFLICT,
                "SOURCE_INCOMPLETE": HTTPStatus.CONFLICT,
                "INVALID_PROJECT": HTTPStatus.PRECONDITION_FAILED,
                "INVALID_INPUT": HTTPStatus.BAD_REQUEST,
                "PATH_OUT_OF_BOUNDS": HTTPStatus.BAD_REQUEST,
            }.get(exc.code, HTTPStatus.BAD_GATEWAY)
            raise StudioError(str(exc), status, code=exc.code) from exc
        return {"result": result, "workspace": self.workspace()}

    def write_next_chapter(self, payload: dict[str, Any]) -> dict[str, Any]:
        profile = self._operation_profile(
            "chapter_write",
            injected_executor=self._writer_executor,
        )
        try:
            target_words = int(payload.get("target_words") or 3000)
        except (TypeError, ValueError) as exc:
            raise StudioError("目标字数必须是整数") from exc
        if not 200 <= target_words <= 12000:
            raise StudioError("目标字数必须在 200 到 12000 之间")
        guidance = str(payload.get("guidance") or "").strip()
        requested_chapter = str(payload.get("chapter_id") or "").strip()
        outline = self.outline_structure(requested_chapter)
        expected_revision = str(payload.get("outline_revision") or "").strip()
        if expected_revision and expected_revision != outline["revision"]:
            raise StudioError(
                "大纲已变化，请重新查看章节建议后再创建",
                HTTPStatus.CONFLICT,
            )
        recommendation = outline.get("recommendation")
        if requested_chapter:
            if not recommendation or recommendation["chapter_id"] != requested_chapter:
                raise StudioError("所选章节不在当前大纲中")
            if recommendation["status"] == "drafted":
                raise StudioError("该章节已有正文，请从正文列表打开", HTTPStatus.CONFLICT)
        chapter_id = (
            str(recommendation["chapter_id"]) if isinstance(recommendation, dict) else "next"
        )
        self._debug_event(
            "write_chapter_requested",
            chapter_id=chapter_id,
            requested_chapter=requested_chapter,
            target_words=target_words,
            guidance=guidance,
            outline_revision=outline.get("revision"),
            book_state=self._debug_book_state(),
        )
        try:
            with self._model_context(profile):
                result = self._service().write_chapter(
                    {
                        "chapter_id": chapter_id,
                        "guidance": guidance,
                        "target_words": target_words,
                        "temperature": float(payload.get("temperature") or 0.7),
                    }
                )
        except NovelServiceError as exc:
            self._debug_event(
                "write_chapter_failed",
                chapter_id=chapter_id,
                error=str(exc),
                code=getattr(exc, "code", ""),
                book_state=self._debug_book_state(),
            )
            raise self._translate_service_error(exc) from exc
        self._debug_event(
            "write_chapter_completed",
            chapter_id=result.get("chapter_id", chapter_id),
            title=result.get("title", ""),
            word_count=result.get("word_count", 0),
            draft_path=result.get("draft_path", ""),
            book_state=self._debug_book_state(),
        )
        return {"result": result, "workspace": self.workspace()}

    def review_chapter(self, payload: dict[str, Any]) -> dict[str, Any]:
        profile = self._operation_profile(
            "review",
            injected_executor=self._review_executor,
        )
        relative_path = str(payload.get("path") or "")
        path = self._resolve_document(relative_path, write=False)
        manuscript_root = (self.novel_root / "data" / "manuscript").resolve()
        if manuscript_root not in path.parents or not re.fullmatch(r"ch_\d+", path.stem):
            raise StudioError("只能审查正文章节")

        try:
            with self._model_context(profile):
                result = self._service().review_chapter(
                    path.stem,
                    strict=bool(payload.get("strict", False)),
                    dimensions=(
                        payload.get("dimensions")
                        if isinstance(payload.get("dimensions"), list)
                        else None
                    ),
                )
        except NovelServiceError as exc:
            self._debug_event(
                "review_chapter_failed",
                chapter_id=path.stem,
                error=str(exc),
                code=getattr(exc, "code", ""),
            )
            raise self._translate_service_error(exc) from exc
        result = dict(result)
        result["issue_details"] = normalize_review_issues(
            path.stem, result.get("issue_details", [])
        )
        self._debug_event(
            "review_chapter_completed",
            chapter_id=path.stem,
            passed=result.get("passed"),
            score=result.get("score"),
            issues=result.get("issues"),
        )
        return {"result": result, "workspace": self.workspace()}

    def create_selection_revision(self, payload: dict[str, Any]) -> dict[str, Any]:
        profile = self._require_revision_model()
        try:
            with self._model_context(profile):
                return self._revisions().create_selection(
                    chapter_id=str(payload.get("chapter_id") or ""),
                    start=int(payload.get("start")),
                    end=int(payload.get("end")),
                    original_text=str(payload.get("original_text") or ""),
                    instruction=str(payload.get("instruction") or ""),
                    action=str(payload.get("action") or "rewrite"),
                    target_units=int(payload.get("target_units") or 0),
                    full_chapter=bool(payload.get("full_chapter")),
                )
        except (TypeError, ValueError) as exc:
            raise StudioError(
                "选区位置和目标字数必须是整数",
                code="INVALID_SELECTION",
            ) from exc
        except RevisionError as exc:
            raise self._translate_revision_error(exc) from exc

    def create_review_revision(self, payload: dict[str, Any]) -> dict[str, Any]:
        profile = self._require_revision_model()
        issue_ids = payload.get("issue_ids")
        if not isinstance(issue_ids, list):
            raise StudioError("issue_ids 必须是数组", code="INVALID_REQUEST_BODY")
        try:
            with self._model_context(profile):
                return self._revisions().create_from_review(
                    chapter_id=str(payload.get("chapter_id") or ""),
                    issue_ids=[str(item) for item in issue_ids],
                    instruction=str(payload.get("instruction") or ""),
                    target_units=int(payload.get("target_units") or 0),
                )
        except (TypeError, ValueError) as exc:
            raise StudioError("目标字数必须是整数", code="INVALID_INPUT") from exc
        except RevisionError as exc:
            raise self._translate_revision_error(exc) from exc

    def list_revisions(self, chapter_id: str = "", status: str = "") -> dict[str, Any]:
        try:
            proposals = self._revisions().list(chapter_id=chapter_id, status=status)
        except RevisionError as exc:
            raise self._translate_revision_error(exc) from exc
        return {"proposals": proposals}

    def get_revision(self, proposal_id: str) -> dict[str, Any]:
        try:
            return self._revisions().get(proposal_id)
        except RevisionError as exc:
            raise self._translate_revision_error(exc) from exc

    def apply_revision(self, proposal_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            replacement_text = payload.get("replacement_text")
            if replacement_text is not None and not isinstance(replacement_text, str):
                raise RevisionError("替换文本格式无效", code="INVALID_INPUT")
            selected_hunk_ids = payload.get("selected_hunk_ids")
            if selected_hunk_ids is not None and not isinstance(selected_hunk_ids, list):
                raise RevisionError("差异块选择格式无效", code="INVALID_INPUT")
            proposal = self._revisions().apply(
                proposal_id,
                replacement_text=replacement_text,
                selected_hunk_ids=selected_hunk_ids,
            )
        except RevisionError as exc:
            raise self._translate_revision_error(exc) from exc
        self._debug_event(
            "revision_applied",
            proposal_id=proposal_id,
            chapter_id=proposal.get("chapter_id"),
            source_revision=proposal.get("source_revision"),
            applied_revision=proposal.get("applied_revision"),
        )
        return {"proposal": proposal, "workspace": self.workspace()}

    def reject_revision(self, proposal_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        del payload
        try:
            return self._revisions().reject(proposal_id)
        except RevisionError as exc:
            raise self._translate_revision_error(exc) from exc

    def regenerate_revision(
        self, proposal_id: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        del payload
        profile = self._require_revision_model()
        try:
            with self._model_context(profile):
                return self._revisions().regenerate(proposal_id)
        except RevisionError as exc:
            raise self._translate_revision_error(exc) from exc

    def _require_revision_model(self) -> dict[str, Any] | None:
        return self._operation_profile(
            "revision",
            injected_executor=self._revision_executor,
        )

    @staticmethod
    def _translate_revision_error(exc: RevisionError) -> StudioError:
        status = {
            "DOCUMENT_CONFLICT": HTTPStatus.CONFLICT,
            "PROJECT_BUSY": HTTPStatus.CONFLICT,
            "REVISION_STATUS_CONFLICT": HTTPStatus.CONFLICT,
            "REVISION_NOT_PROPOSED": HTTPStatus.CONFLICT,
            "REVISION_ALREADY_APPLIED": HTTPStatus.CONFLICT,
            "REVISION_NOT_FOUND": HTTPStatus.NOT_FOUND,
            "REVIEW_NOT_FOUND": HTTPStatus.NOT_FOUND,
            "REVIEW_ISSUE_NOT_FOUND": HTTPStatus.NOT_FOUND,
            "DOCUMENT_NOT_FOUND": HTTPStatus.NOT_FOUND,
            "REVISION_GENERATION_FAILED": HTTPStatus.BAD_GATEWAY,
        }.get(exc.code, HTTPStatus.BAD_REQUEST)
        return StudioError(
            str(exc),
            status,
            code=exc.code,
            recoverable=exc.recoverable,
            details=exc.details,
        )

    def task_surface(self, limit: int = 100) -> dict[str, Any]:
        try:
            tasks = self._tasks().store.list(limit=limit)
        except (TaskStoreError, ValueError) as exc:
            raise StudioError("任务数量必须是有效整数", code="INVALID_INPUT") from exc
        counts = {
            status: sum(1 for task in tasks if task.get("status") == status)
            for status in (
                "pending",
                "running",
                "awaiting_confirmation",
                "completed",
                "failed",
                "cancelled",
                "interrupted",
            )
        }
        return {"tasks": tasks, "counts": counts}

    def get_task(self, task_id: str) -> dict[str, Any]:
        try:
            task = self._tasks().store.load(task_id)
            if task is None:
                raise TaskStoreError("Task not found")
            return {
                "task": task,
                "events": self._tasks().store.events(task_id),
            }
        except TaskStoreError as exc:
            raise self._translate_task_error(exc) from exc

    def create_task(self, payload: dict[str, Any]) -> dict[str, Any]:
        task_type = str(payload.get("type") or "").strip()
        task_input = payload.get("input")
        if not isinstance(task_input, dict):
            raise StudioError("任务 input 必须是 JSON 对象", code="INVALID_REQUEST_BODY")
        ai_tasks = {
            "chapter_write",
            "chapter_review",
            "revision_selection",
            "revision_from_review",
            "source_operation",
            "reference_operation",
            "continuous_write",
            "research",
        }
        if task_type in ai_tasks:
            injected = {
                "chapter_write": self._writer_executor,
                "chapter_review": self._review_executor,
                "revision_selection": self._revision_executor,
                "revision_from_review": self._revision_executor,
                "source_operation": self._source_executor,
                "reference_operation": self._source_executor,
                "continuous_write": (
                    self._writer_executor
                    if self._writer_executor is not None and self._review_executor is not None
                    else None
                ),
                "research": None,
            }.get(task_type)
            operation = {
                "chapter_write": "chapter_write",
                "chapter_review": "review",
                "revision_selection": "revision",
                "revision_from_review": "revision",
                "source_operation": "source_extract",
                "reference_operation": "source_extract",
                "continuous_write": "chapter_write",
                "research": "research",
            }[task_type]
            self._operation_profile(operation, injected_executor=injected)
        chapter_id = str(
            task_input.get("chapter_id")
            or self._chapter_id_from_document(str(task_input.get("path") or ""))
            or ""
        )
        try:
            task = self._tasks().submit(
                task_type,
                dict(task_input),
                chapter_id=chapter_id,
                input_summary=self._task_input_summary(task_type, task_input),
                retryable=True,
            )
        except TaskStoreError as exc:
            raise self._translate_task_error(exc) from exc
        self._debug_event(
            "task_queued",
            task_id=task.get("task_id"),
            task_type=task_type,
            chapter_id=chapter_id,
        )
        return task

    def cancel_task(self, task_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        del payload
        try:
            return self._tasks().cancel(task_id)
        except TaskStoreError as exc:
            raise self._translate_task_error(exc) from exc

    def retry_task(self, task_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        del payload
        try:
            return self._tasks().retry(task_id)
        except TaskStoreError as exc:
            raise self._translate_task_error(exc) from exc

    def confirm_task(self, task_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        del payload
        try:
            return self._tasks().confirm(task_id)
        except TaskStoreError as exc:
            raise self._translate_task_error(exc) from exc

    def _task_write_chapter(
        self, payload: dict[str, Any], context: TaskContext
    ) -> dict[str, Any]:
        args = dict(payload)
        expected_revision = str(args.get("outline_revision") or "")
        if expected_revision:
            outline = self.outline_structure(str(args.get("chapter_id") or ""))
            if expected_revision != outline.get("revision"):
                raise StudioError(
                    "大纲已变化，请重新查看章节建议后再创建",
                    HTTPStatus.CONFLICT,
                    code="DOCUMENT_CONFLICT",
                    recoverable=True,
                )
        args["_task_phase"] = context.progress_callback
        args["_cancel_requested"] = context.cancellation_requested
        context.phase("preparing", "准备章节写作")
        context.checkpoint()
        context.phase("model", "生成章节草稿")
        try:
            profile = self._operation_profile(
                "chapter_write",
                injected_executor=self._writer_executor,
            )
            with self._model_context(profile):
                return self._service().write_chapter(args)
        except NovelServiceError as exc:
            if exc.code == "TASK_CANCELLED":
                raise TaskCancelled(str(exc)) from exc
            raise

    def _task_review_chapter(
        self, payload: dict[str, Any], context: TaskContext
    ) -> dict[str, Any]:
        chapter_id = str(
            payload.get("chapter_id")
            or self._chapter_id_from_document(str(payload.get("path") or ""))
        )
        context.phase("preparing", "准备章节审稿")
        context.checkpoint()
        context.phase("model", "执行章节审稿")
        try:
            profile = self._operation_profile(
                "review",
                injected_executor=self._review_executor,
            )
            with self._model_context(profile):
                result = self._service().review_chapter(
                    chapter_id,
                    strict=bool(payload.get("strict", False)),
                    dimensions=(
                        payload.get("dimensions")
                        if isinstance(payload.get("dimensions"), list)
                        else None
                    ),
                    task_phase=context.progress_callback,
                    cancel_requested=context.cancellation_requested,
                )
        except NovelServiceError as exc:
            if exc.code == "TASK_CANCELLED":
                raise TaskCancelled(str(exc)) from exc
            raise
        return {
            **result,
            "issue_details": normalize_review_issues(
                chapter_id, result.get("issue_details", [])
            ),
        }

    def _task_revision_selection(
        self, payload: dict[str, Any], context: TaskContext
    ) -> dict[str, Any]:
        context.phase("preparing", "准备选区与上下文")
        context.checkpoint()
        context.phase("model", "生成修订提案")
        profile = self._operation_profile(
            "revision",
            injected_executor=self._revision_executor,
        )
        with self._model_context(profile):
            proposal = self._revisions().create_selection(
                chapter_id=str(payload.get("chapter_id") or ""),
                start=int(payload.get("start")),
                end=int(payload.get("end")),
                original_text=str(payload.get("original_text") or ""),
                instruction=str(payload.get("instruction") or ""),
                action=str(payload.get("action") or "rewrite"),
                target_units=int(payload.get("target_units") or 0),
                full_chapter=bool(payload.get("full_chapter")),
            )
        context.phase("validating", "准备 diff 预览")
        if context.cancellation_requested():
            self._revisions().reject(str(proposal["proposal_id"]))
            raise TaskCancelled("任务已取消，生成的提案已放弃")
        return proposal

    def _task_revision_from_review(
        self, payload: dict[str, Any], context: TaskContext
    ) -> dict[str, Any]:
        issue_ids = payload.get("issue_ids")
        if not isinstance(issue_ids, list):
            raise RevisionError("issue_ids 必须是数组", code="INVALID_INPUT")
        context.phase("preparing", "定位审稿问题")
        context.checkpoint()
        context.phase("model", "生成问题修订提案")
        profile = self._operation_profile(
            "revision",
            injected_executor=self._revision_executor,
        )
        with self._model_context(profile):
            proposal = self._revisions().create_from_review(
                chapter_id=str(payload.get("chapter_id") or ""),
                issue_ids=[str(item) for item in issue_ids],
                instruction=str(payload.get("instruction") or ""),
                target_units=int(payload.get("target_units") or 0),
            )
        context.phase("validating", "准备 diff 预览")
        if context.cancellation_requested():
            self._revisions().reject(str(proposal["proposal_id"]))
            raise TaskCancelled("任务已取消，生成的提案已放弃")
        return proposal

    def _task_source_operation(
        self, payload: dict[str, Any], context: TaskContext
    ) -> dict[str, Any]:
        context.phase("preparing", "准备来源文本")
        context.checkpoint()
        context.phase("model", "执行来源操作")
        response = self.source_action(payload)
        context.phase("validating", "整理来源结果")
        context.checkpoint()
        result = response.get("result", {})
        if str(payload.get("action") or "") == "analyze_v2" and isinstance(result, dict):
            analysis = result.get("analysis")
            if isinstance(analysis, dict) and analysis.get("ok") is False:
                failures = analysis.get("failures")
                failure_list = failures if isinstance(failures, list) else []
                first = failure_list[0] if failure_list else {}
                first = first if isinstance(first, dict) else {}
                message = str(first.get("message") or "来源分块分析未完成")
                raise StudioError(
                    f"参考分析未完成：{message}",
                    HTTPStatus.BAD_GATEWAY,
                    code=str(first.get("code") or "SOURCE_ANALYSIS_FAILED"),
                    recoverable=True,
                    details={
                        "source_id": str(payload.get("source_id") or ""),
                        "failures": failure_list,
                    },
                )
        return {"result": result}

    def _task_reference_operation(
        self, payload: dict[str, Any], context: TaskContext
    ) -> dict[str, Any]:
        context.phase("preparing", "读取参考库快照与已确认结构")
        context.checkpoint()
        context.phase("model", "执行全文证据拆解")
        response = self.reference_library_action(payload)
        context.phase("validating", "验证证据并生成结构化资产")
        context.checkpoint()
        result = response.get("result", {})
        if isinstance(result, dict) and result.get("ok") is False:
            failures = result.get("failures")
            failure_list = failures if isinstance(failures, list) else []
            first = failure_list[0] if failure_list else {}
            first = first if isinstance(first, dict) else {}
            raise StudioError(
                f"参考作品拆解未完成：{first.get('message') or '存在失败分块'}",
                HTTPStatus.BAD_GATEWAY,
                code=str(first.get("code") or "REFERENCE_ANALYSIS_FAILED"),
                recoverable=True,
                details={"source_id": str(payload.get("source_id") or "")},
            )
        return {"result": result}

    def _task_research(
        self, payload: dict[str, Any], context: TaskContext
    ) -> dict[str, Any]:
        try:
            profile = self._operation_profile("research")
            return self._research().run(payload, context, model_profile=profile)
        except ResearchServiceError as exc:
            raise StudioError(str(exc), code=exc.code, recoverable=True) from exc

    def research_surface(self) -> dict[str, Any]:
        try:
            surface = self._research().status()
            models = self.model_profiles()
            profile_id = str(
                models.get("routes", {}).get("research")
                or models.get("default_profile_id")
                or ""
            )
            profile = next(
                (
                    item
                    for item in models.get("profiles", [])
                    if item.get("id") == profile_id
                ),
                None,
            )
            surface["model_route"] = (
                {
                    "profile_id": profile_id,
                    "label": str(profile.get("label") or profile_id),
                    "model": str(profile.get("model") or ""),
                    "provider": str(profile.get("provider") or ""),
                    "configured": bool(profile.get("configured")),
                    "compatible": str(profile.get("provider") or "") != "anthropic",
                }
                if profile
                else {
                    "profile_id": profile_id,
                    "label": "尚未配置",
                    "model": "",
                    "provider": "",
                    "configured": False,
                    "compatible": False,
                }
            )
            return surface
        except ResearchServiceError as exc:
            raise StudioError(str(exc), code=exc.code, recoverable=True) from exc

    def save_research_settings(self, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            self._research().save_settings(payload)
            return self.research_surface()
        except (ResearchServiceError, OSError) as exc:
            if isinstance(exc, ResearchServiceError):
                raise StudioError(str(exc), code=exc.code, recoverable=True) from exc
            raise StudioError("深度研究 API 设置保存失败，请检查配置目录权限") from exc

    def research_report(self, report_id: str) -> dict[str, Any]:
        try:
            return self._research().read_report(report_id)
        except ResearchServiceError as exc:
            status = (
                HTTPStatus.NOT_FOUND
                if exc.code == "REPORT_NOT_FOUND"
                else HTTPStatus.BAD_REQUEST
            )
            raise StudioError(str(exc), status, code=exc.code) from exc

    def _task_import_manuscript(
        self, payload: dict[str, Any], context: TaskContext
    ) -> dict[str, Any]:
        context.phase("reading", "读取导入文本")
        context.checkpoint()
        context.phase("preparing", "切分章节")
        context.checkpoint()
        context.phase("committing", "提交导入章节")
        response = self.import_text(payload)
        return {
            key: response.get(key)
            for key in ("arc_id", "next_chapter", "writing_units", "imported")
        }

    def _task_continuous_write(
        self, payload: dict[str, Any], context: TaskContext
    ) -> dict[str, Any]:
        max_chapters = self._bounded_int(
            payload.get("max_chapters"),
            default=1,
            minimum=1,
            maximum=10,
            label="连续章节数",
        )
        minimum_score = self._bounded_int(
            payload.get("minimum_review_score"),
            default=82,
            minimum=0,
            maximum=100,
            label="最低审稿分",
        )
        max_tokens = self._bounded_int(
            payload.get("max_tokens"),
            default=0,
            minimum=0,
            maximum=10_000_000,
            label="Token 上限",
        )
        max_failures = self._bounded_int(
            payload.get("max_failures"),
            default=2,
            minimum=1,
            maximum=10,
            label="连续失败上限",
        )
        try:
            max_cost_usd = max(0.0, min(10000.0, float(payload.get("max_cost_usd") or 0)))
        except (TypeError, ValueError) as exc:
            raise StudioError("成本上限必须是数字") from exc
        completed = list(payload.get("_already_completed") or [])
        already_used = payload.get("_already_used")
        usage = dict(already_used) if isinstance(already_used, dict) else {}
        total_tokens = int(usage.get("total_tokens") or 0)
        total_cost_usd = float(usage.get("cost_usd") or 0)
        consecutive_failures = int(usage.get("consecutive_failures") or 0)
        remaining = max(0, max_chapters - len(completed))
        stop_reason = "max_chapters_reached"
        for _ in range(remaining):
            context.phase("reading", "读取下一章建议")
            context.checkpoint()
            from tools.chapter_run_v2 import ChapterRunV2Store

            latest_runs = ChapterRunV2Store(
                self.project_root, self.novel_id
            ).list(limit=20)
            pending_intervention = next(
                (
                    item
                    for run in latest_runs
                    for item in run.interventions
                    if item.state
                    in {
                        "recorded",
                        "facts_read",
                        "classified",
                        "proposed",
                        "awaiting_confirmation",
                        "confirmed",
                    }
                ),
                None,
            )
            if pending_intervention is not None:
                stop_reason = "pending_intervention"
                break
            outline = self.outline_structure()
            recommendation = outline.get("recommendation")
            if not isinstance(recommendation, dict) or recommendation.get("status") == "drafted":
                stop_reason = "outline_gap"
                break
            chapter_id = str(recommendation.get("chapter_id") or "")
            write_payload = {
                "chapter_id": chapter_id,
                "guidance": str(payload.get("guidance") or recommendation.get("guidance") or ""),
                "target_words": int(
                    payload.get("target_words")
                    or recommendation.get("target_words")
                    or 3000
                ),
                "temperature": float(payload.get("temperature") or 0.7),
            }
            try:
                write_result = self._task_write_chapter(write_payload, context)
                context.checkpoint()
                review_result = self._task_review_chapter(
                    {"chapter_id": chapter_id}, context
                )
                consecutive_failures = 0
            except Exception:
                consecutive_failures += 1
                usage["consecutive_failures"] = consecutive_failures
                context.persist_progress(
                    {
                        "completed_chapters": completed,
                        "usage": usage,
                        "stop_reason": "chapter_failure",
                    }
                )
                if consecutive_failures >= max_failures:
                    return {
                        "completed_chapters": completed,
                        "usage": usage,
                        "stop_reason": "max_failures_reached",
                    }
                raise
            completed.append(
                {
                    "chapter_id": chapter_id,
                    "write": write_result,
                    "review": review_result,
                }
            )
            write_usage = write_result.get("usage")
            write_usage = write_usage if isinstance(write_usage, dict) else {}
            total_tokens += int(
                write_usage.get("total_tokens")
                or write_usage.get("output_tokens")
                or 0
            )
            total_cost_usd += float(write_usage.get("cost_usd") or 0)
            usage = {
                "total_tokens": total_tokens,
                "cost_usd": total_cost_usd,
                "consecutive_failures": consecutive_failures,
            }
            context.persist_progress(
                {
                    "completed_chapters": completed,
                    "usage": usage,
                    "stop_reason": "in_progress",
                }
            )
            if max_tokens and total_tokens >= max_tokens:
                stop_reason = "max_tokens_reached"
                break
            if max_cost_usd and total_cost_usd >= max_cost_usd:
                stop_reason = "max_cost_reached"
                break
            issue_details = review_result.get("issue_details") or []
            has_blocker = any(item.get("severity") == "blocker" for item in issue_details)
            has_continuity = any(
                str(item.get("dimension") or "").startswith("continuity")
                and item.get("severity") in {"blocker", "high"}
                for item in issue_details
            )
            if bool(payload.get("stop_on_blocker", True)) and has_blocker:
                stop_reason = "review_blocker"
                break
            if bool(payload.get("stop_on_continuity_error", True)) and has_continuity:
                stop_reason = "continuity_error"
                break
            if float(review_result.get("score") or 0) < minimum_score:
                stop_reason = "review_score_below_minimum"
                break
            if (
                bool(payload.get("require_confirmation_after_each_chapter"))
                and len(completed) < max_chapters
            ):
                context.await_confirmation(
                    {
                        "completed_chapters": completed,
                        "stop_reason": "confirmation_required",
                    }
                )
        return {
            "completed_chapters": completed,
            "usage": usage,
            "stop_reason": stop_reason,
        }

    @staticmethod
    def _chapter_id_from_document(path: str) -> str:
        match = re.search(r"(?:^|/)(ch_\d+)\.md$", str(path or ""))
        return match.group(1) if match else ""

    @staticmethod
    def _task_input_summary(task_type: str, payload: dict[str, Any]) -> str:
        chapter = str(
            payload.get("chapter_id")
            or StudioApplication._chapter_id_from_document(str(payload.get("path") or ""))
        )
        labels = {
            "chapter_write": "写作章节",
            "chapter_review": "审稿",
            "revision_selection": "生成局部修订",
            "revision_from_review": "按审稿问题修订",
            "source_operation": "处理来源文本",
            "reference_operation": "拆解参考作品",
            "manuscript_import": "导入旧稿",
            "continuous_write": "受控连续写作",
            "research": "深度研究",
        }
        return " · ".join(item for item in (labels.get(task_type, task_type), chapter) if item)

    @staticmethod
    def _translate_task_error(exc: TaskStoreError) -> StudioError:
        message = str(exc)
        status = HTTPStatus.NOT_FOUND if "not found" in message.lower() else HTTPStatus.CONFLICT
        code = "TASK_NOT_FOUND" if status == HTTPStatus.NOT_FOUND else "TASK_CONFLICT"
        return StudioError(message, status, code=code, recoverable=status != HTTPStatus.NOT_FOUND)

    def asset_surface(self, kind: str = "") -> dict[str, Any]:
        try:
            return {"assets": self._assets().list(kind)}
        except StructuredAssetError as exc:
            raise self._translate_asset_error(exc) from exc

    def read_asset(self, kind: str, asset_id: str) -> dict[str, Any]:
        try:
            return self._asset_with_relations(self._assets().read(kind, asset_id))
        except StructuredAssetError as exc:
            raise self._translate_asset_error(exc) from exc

    def create_asset(self, payload: dict[str, Any]) -> dict[str, Any]:
        kind = str(payload.get("kind") or "")
        try:
            asset = self._assets().create(kind, payload)
            sync = self._service().sync()
        except StructuredAssetError as exc:
            raise self._translate_asset_error(exc) from exc
        except NovelServiceError as exc:
            raise self._translate_service_error(exc) from exc
        return {"asset": self._asset_with_relations(asset), "sync": sync}

    def update_asset(self, payload: dict[str, Any]) -> dict[str, Any]:
        kind = str(payload.get("kind") or "")
        asset_id = str(payload.get("id") or "")
        revision = str(payload.get("revision") or "")
        try:
            asset = self._assets().update(
                kind,
                asset_id,
                payload,
                expected_revision=revision,
            )
            sync = self._service().sync()
        except StructuredAssetError as exc:
            raise self._translate_asset_error(exc) from exc
        except NovelServiceError as exc:
            raise self._translate_service_error(exc) from exc
        return {"asset": self._asset_with_relations(asset), "sync": sync}

    def _asset_with_relations(self, asset: dict[str, Any]) -> dict[str, Any]:
        if asset.get("kind") not in {"character", "world"}:
            return asset
        from tools.world_query import get_asset_relation_view

        return {
            **asset,
            "relation_view": get_asset_relation_view(
                self.novel_id,
                str(asset.get("id") or ""),
                project_root=self.project_root,
                asset_kind=str(asset.get("kind") or ""),
            ),
        }

    def asset_package_preview(self, payload: dict[str, Any]) -> dict[str, Any]:
        encoded = str(payload.get("package_base64") or "")
        if not encoded:
            raise StudioError("请选择资产包", code="ASSET_PACKAGE_REQUIRED")
        try:
            content = base64.b64decode(encoded, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise StudioError("资产包内容无效", code="INVALID_ASSET_PACKAGE") from exc
        if not content or len(content) > 25 * 1024 * 1024:
            raise StudioError(
                "资产包大小必须在 25 MB 以内",
                HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
                code="ASSET_PACKAGE_TOO_LARGE",
            )
        upload_id = f"pkg_{uuid.uuid4().hex}"
        stage_root = self.novel_root / "data" / "workflows" / "asset_packages"
        stage_root.mkdir(parents=True, exist_ok=True)
        target = stage_root / f"{upload_id}.owasset.zip"
        temp_path = target.with_name(f".{target.name}.{uuid.uuid4().hex}.tmp")
        try:
            temp_path.write_bytes(content)
            temp_path.replace(target)
            preview = self._asset_packages().preview_import(target)
        except AssetPackageError as exc:
            target.unlink(missing_ok=True)
            raise self._translate_asset_package_error(exc) from exc
        finally:
            temp_path.unlink(missing_ok=True)
        return {**preview, "upload_id": upload_id}

    def import_asset_package(self, payload: dict[str, Any]) -> dict[str, Any]:
        upload_id = str(payload.get("upload_id") or "")
        source = self._staged_asset_package(upload_id)
        resolutions = payload.get("resolutions")
        if resolutions is not None and not isinstance(resolutions, dict):
            raise StudioError("资产包冲突决策无效", code="INVALID_IMPORT_RESOLUTION")
        try:
            result = self._asset_packages().import_package(
                source,
                expected_sha256=str(payload.get("package_sha256") or ""),
                resolutions=resolutions,
                allow_missing_dependencies=bool(payload.get("allow_missing_dependencies")),
            )
            sync = self._service().sync()
        except AssetPackageError as exc:
            raise self._translate_asset_package_error(exc) from exc
        except NovelServiceError as exc:
            raise self._translate_service_error(exc) from exc
        source.unlink(missing_ok=True)
        return {**result, "sync": sync}

    def asset_package_download(
        self,
        selections: list[dict[str, str]],
    ) -> tuple[str, bytes, str]:
        with tempfile.TemporaryDirectory(prefix="openwrite-assets-") as temp_dir:
            output = Path(temp_dir) / f"{self.novel_id}-assets.owasset.zip"
            try:
                self._asset_packages().export(output, selections=selections or None)
            except AssetPackageError as exc:
                raise self._translate_asset_package_error(exc) from exc
            content = output.read_bytes()
        return output.name, content, "application/zip"

    def _staged_asset_package(self, upload_id: str) -> Path:
        if not re.fullmatch(r"pkg_[a-f0-9]{32}", upload_id):
            raise StudioError("资产包暂存标识无效", code="INVALID_ASSET_PACKAGE")
        path = (
            self.novel_root
            / "data"
            / "workflows"
            / "asset_packages"
            / f"{upload_id}.owasset.zip"
        )
        if not path.is_file():
            raise StudioError(
                "资产包预览已失效，请重新选择文件",
                HTTPStatus.NOT_FOUND,
                code="ASSET_PACKAGE_NOT_FOUND",
                recoverable=True,
            )
        return path

    @staticmethod
    def _translate_asset_error(exc: StructuredAssetError) -> StudioError:
        status = {
            "ASSET_NOT_FOUND": HTTPStatus.NOT_FOUND,
            "ASSET_CONFLICT": HTTPStatus.CONFLICT,
            "PROJECT_BUSY": HTTPStatus.CONFLICT,
        }.get(exc.code, HTTPStatus.BAD_REQUEST)
        return StudioError(
            str(exc),
            status,
            code=exc.code,
            recoverable=exc.recoverable,
        )

    @staticmethod
    def _translate_asset_package_error(exc: AssetPackageError) -> StudioError:
        status = {
            "ASSET_PACKAGE_NOT_FOUND": HTTPStatus.NOT_FOUND,
            "ASSET_PACKAGE_CONFLICT": HTTPStatus.CONFLICT,
            "ASSET_CONFLICT": HTTPStatus.CONFLICT,
            "ASSET_DEPENDENCY_MISSING": HTTPStatus.CONFLICT,
            "PROJECT_BUSY": HTTPStatus.CONFLICT,
        }.get(exc.code, HTTPStatus.BAD_REQUEST)
        return StudioError(
            str(exc),
            status,
            code=exc.code,
            recoverable=exc.recoverable,
            details=exc.details,
        )

    def export_download(self, format_name: str) -> tuple[str, bytes, str]:
        if format_name not in {"md", "txt", "epub"}:
            raise StudioError("导出格式仅支持 md、txt 或 epub")
        title = str(self.config.get("title") or self.novel_id)
        with tempfile.TemporaryDirectory(prefix="openwrite-export-") as temp_dir:
            output = Path(temp_dir) / f"{self.novel_id}.{format_name}"
            try:
                self._service().export_book(
                    output,
                    format_name=format_name,
                    title=title,
                )
            except NovelServiceError as exc:
                raise self._translate_service_error(exc) from exc
            content = output.read_bytes()
        mime = {
            "md": "text/markdown; charset=utf-8",
            "txt": "text/plain; charset=utf-8",
            "epub": "application/epub+zip",
        }[format_name]
        return f"{self.novel_id}.{format_name}", content, mime

    def _load_config(self) -> dict[str, Any]:
        try:
            data = yaml.safe_load(self.config_path.read_text(encoding="utf-8")) or {}
        except (OSError, yaml.YAMLError) as exc:
            raise StudioError(f"项目配置无法读取: {exc}") from exc
        return data if isinstance(data, dict) else {}

    def _document_groups(self, chapters: list[Any]) -> dict[str, list[dict[str, Any]]]:
        src = self.novel_root / "src"
        groups = {
            "outline": [],
            "core": [],
            "characters": [],
            "settings": [],
            "chapters": [self._chapter_summary(item) for item in chapters],
        }
        for path in iter_library_paths(self.novel_root):
            try:
                content = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            summary = self._library_document_summary(path, content)
            scope = str(summary.get("scope") or "")
            if scope in LIBRARY_SCOPES:
                groups[scope].append(summary)
        for scope in LIBRARY_SCOPES:
            groups[scope].sort(
                key=lambda item: (
                    CATEGORY_ORDER.get(str(item.get("category") or ""), 999),
                    str(item.get("title") or "").casefold(),
                )
            )
        outline = src / "outline.md"
        if outline.exists():
            groups["outline"].append(self._document_summary(outline))
        return groups

    def _chapter_summary(self, item: Any) -> dict[str, Any]:
        review = self._load_review_result(item.chapter_id)
        subtitle = f"{item.chapter_id} · {item.writing_units:,} 字"
        if review:
            subtitle += (
                " · 审稿待刷新"
                if review.get("stale")
                else f" · {float(review.get('score', 0)):.0f} 分"
            )
        return {
            "path": self._relative(item.path),
            "title": item.title,
            "subtitle": subtitle,
            "review": review,
        }

    def _load_review_result(self, chapter_id: str) -> dict[str, Any] | None:
        from tools.review_store import ReviewStore

        data = ReviewStore(self.project_root, self.novel_id).load(chapter_id)
        if data is None:
            return None
        return {
            "score": float(data.get("score") or 0),
            "passed": bool(data.get("passed")),
            "issues": int(data.get("issues") or 0),
            "reviewed_at": str(data.get("reviewed_at") or ""),
            "stale": bool(data.get("stale")),
            "issue_details": normalize_review_issues(
                chapter_id, data.get("issue_details", [])
            ),
            "issue_delta": (
                data.get("issue_delta")
                if isinstance(data.get("issue_delta"), dict)
                else None
            ),
        }

    def _collect_documents(self, root: Path, *, recursive: bool) -> list[dict[str, Any]]:
        if not root.exists():
            return []
        iterator = root.rglob("*.md") if recursive else root.glob("*.md")
        return [self._document_summary(path) for path in sorted(iterator) if path.is_file()]

    def _document_summary(self, path: Path) -> dict[str, Any]:
        return {
            "path": self._relative(path),
            "title": self._document_title(path),
            "subtitle": str(path.relative_to(self.novel_root).parent),
        }

    def _library_document_summary(self, path: Path, content: str) -> dict[str, Any]:
        relative = self._relative(path)
        descriptor = describe_document(relative, content)
        return {
            "path": relative,
            "title": self._document_title(path),
            "subtitle": descriptor.category_label,
            **descriptor.to_dict(),
        }

    def _document_title(self, path: Path) -> str:
        try:
            head = path.read_text(encoding="utf-8")[:2000]
        except OSError:
            return path.stem
        match = re.search(r"^#\s+(.+?)\s*$", head, re.MULTILINE)
        if match:
            return match.group(1).strip()
        if path.suffix.lower() in {".yaml", ".yml"}:
            try:
                payload = yaml.safe_load(head) or {}
            except yaml.YAMLError:
                payload = {}
            if isinstance(payload, dict) and str(payload.get("name") or "").strip():
                return str(payload["name"]).strip()
        return path.stem.replace("_", " ")

    def _resolve_document(self, relative_path: str, *, write: bool) -> Path:
        if not isinstance(relative_path, str) or not relative_path.strip():
            raise StudioError("缺少文档路径")
        candidate = (self.novel_root / relative_path).resolve()
        allowed_roots = [
            (self.novel_root / "src").resolve(),
            (self.novel_root / "data" / "manuscript").resolve(),
        ]
        if not any(candidate == root or root in candidate.parents for root in allowed_roots):
            raise StudioError("文档路径不在 Studio 可访问范围", HTTPStatus.FORBIDDEN)
        if candidate.suffix.lower() != ".md":
            raise StudioError("Studio 仅编辑 Markdown 文档")
        if write and candidate.is_symlink():
            raise StudioError("不允许写入符号链接", HTTPStatus.FORBIDDEN)
        return candidate

    def _relative(self, path: Path) -> str:
        return path.resolve().relative_to(self.novel_root).as_posix()

    @staticmethod
    def _string_list(value: Any) -> list[str]:
        if isinstance(value, str):
            values = value.splitlines()
        elif isinstance(value, list):
            values = value
        else:
            return []
        return [str(item).strip().removeprefix("- ") for item in values if str(item).strip()]


class LegacyStudioRequestHandler(SimpleHTTPRequestHandler):
    server_version = "OpenWriteStudio/5.8"

    @property
    def app(self) -> StudioApplication:
        return cast(StudioApplication, getattr(self.server, "app"))

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        try:
            if parsed.path == "/api/health":
                self._json({"ok": True})
                return
            if parsed.path == "/api/workspace":
                self._json(self.app.workspace())
                return
            if parsed.path == "/api/continuity":
                self.app.require_project()
                self._json(self.app.continuity())
                return
            if parsed.path == "/api/agents":
                params = parse_qs(parsed.query)
                agent_name = params.get("agent", ["goethe"])[0]
                session_id = params.get("session_id", ["default"])[0]
                try:
                    limit = int(params.get("limit", ["200"])[0])
                except ValueError as exc:
                    raise StudioError("历史消息数量必须是整数") from exc
                self._json(self.app.agent_surface(agent_name, limit, session_id))
                return
            if parsed.path == "/api/agent/activity":
                run_id = parse_qs(parsed.query).get("run_id", [""])[0]
                self._json(self.app.agent_activity(run_id))
                return
            if parsed.path == "/api/context":
                self.app.require_project()
                chapter_id = parse_qs(parsed.query).get("chapter", ["next"])[0]
                self._json(self.app.context_preview(chapter_id))
                return
            if parsed.path == "/api/outline":
                chapter_id = parse_qs(parsed.query).get("chapter", [""])[0]
                self._json(self.app.outline_structure(chapter_id))
                return
            if parsed.path == "/api/search":
                self.app.require_project()
                params = parse_qs(parsed.query)
                query = params.get("q", [""])[0]
                scope = params.get("scope", ["all"])[0]
                try:
                    limit = int(params.get("limit", ["20"])[0])
                except ValueError as exc:
                    raise StudioError("搜索数量必须是整数") from exc
                self._json(self.app.search_project(query, scope, limit))
                return
            if parsed.path == "/api/document":
                self.app.require_project()
                path = parse_qs(parsed.query).get("path", [""])[0]
                self._json(self.app.read_document(path))
                return
            if parsed.path == "/api/export":
                self.app.require_project()
                format_name = parse_qs(parsed.query).get("format", ["md"])[0]
                filename, content, mime = self.app.export_download(format_name)
                self.send_response(HTTPStatus.OK)
                self._security_headers()
                self.send_header("Content-Type", mime)
                self.send_header(
                    "Content-Disposition",
                    f"attachment; filename*=UTF-8''{quote(filename)}",
                )
                self.send_header("Content-Length", str(len(content)))
                self.end_headers()
                self.wfile.write(content)
                return
            if parsed.path in {"/brand/logo.svg", "/brand/logo-dark.svg"}:
                self._serve_brand_logo(parsed.path.endswith("dark.svg"))
                return
            self._serve_static(parsed.path)
        except StudioError as exc:
            self._debug_http_error(exc.status, str(exc))
            self._json({"error": str(exc)}, status=exc.status)
        except Exception as exc:
            self._debug_http_error(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                exc.__class__.__name__,
            )
            self._json({"error": "Studio 内部错误"}, status=HTTPStatus.INTERNAL_SERVER_ERROR)

    def do_PUT(self) -> None:
        try:
            self._require_write_header()
            if urlparse(self.path).path != "/api/document":
                raise StudioError("接口不存在", HTTPStatus.NOT_FOUND)
            self.app.require_project()
            payload = self._body_json()
            result = self.app.write_document(
                str(payload.get("path") or ""),
                str(payload.get("content") or ""),
                (
                    payload.get("version")
                    if isinstance(payload.get("version"), (str, int))
                    else None
                ),
                force=bool(payload.get("force")),
            )
            self._json(result)
        except StudioError as exc:
            self._debug_http_error(exc.status, str(exc))
            self._json({"error": str(exc)}, status=exc.status)

    def do_POST(self) -> None:
        try:
            self._require_write_header()
            route = urlparse(self.path).path
            payload = self._body_json()
            if route == "/api/focus":
                self._json(self.app.update_focus(payload))
                return
            if route == "/api/model":
                self._json(self.app.configure_model(payload))
                return
            if route == "/api/model/test":
                self._json(self.app.test_model_connection(payload))
                return
            if route == "/api/model/embedding/test":
                self._json(self.app.test_embedding_connection(payload))
                return
            if route == "/api/project/init":
                self._json(self.app.initialize_project(payload))
                return
            if route == "/api/project/open":
                self._json(self.app.open_project(payload))
                return
            if route == "/api/project/delete":
                self._json(self.app.delete_project(payload))
                return
            if route == "/api/project/writing-targets":
                self._json(self.app.update_writing_targets(payload))
                return
            self.app.require_project()
            if route == "/api/write":
                self._json(self.app.write_next_chapter(payload))
                return
            if route == "/api/chapter/delete":
                self._json(self.app.delete_chapter(payload))
                return
            if route == "/api/outline/edit":
                self._json(self.app.edit_outline_structure(payload))
                return
            if route == "/api/review":
                self._json(self.app.review_chapter(payload))
                return
            if route == "/api/sync":
                self._json(self.app.sync_project())
                return
            if route == "/api/document/create":
                self._json(self.app.create_document(payload))
                return
            if route == "/api/import":
                self._json(self.app.import_text(payload))
                return
            if route == "/api/import/preview":
                self._json(self.app.preview_import(payload))
                return
            if route == "/api/foreshadowing":
                self._json(self.app.manage_foreshadowing(payload))
                return
            if route == "/api/chat":
                self._json(self.app.chat_turn(payload))
                return
            if route == "/api/agent/session":
                self._json(self.app.create_agent_session(payload))
                return
            if route == "/api/agent/session/delete":
                self._json(self.app.delete_agent_session(payload))
                return
            if route == "/api/source":
                self._json(self.app.source_action(payload))
                return
            if route == "/api/runtime-skills":
                self._json(self.app.runtime_skill_action(payload))
                return
            if route == "/api/rules":
                self._json(self.app.rule_action(payload))
                return
            raise StudioError("接口不存在", HTTPStatus.NOT_FOUND)
        except StudioError as exc:
            self._debug_http_error(exc.status, str(exc))
            self._json({"error": str(exc)}, status=exc.status)

    def do_OPTIONS(self) -> None:
        self.send_response(HTTPStatus.METHOD_NOT_ALLOWED)
        self._security_headers()
        self.end_headers()

    def log_message(self, format: str, *args: Any) -> None:
        if self.path.startswith("/api/") and not self.path.startswith("/api/health"):
            super().log_message(format, *args)

    def _debug_http_error(self, status: HTTPStatus | int, message: str) -> None:
        if not self.app.debug_enabled:
            return
        self.app._debug_event(
            "http_error",
            method=self.command,
            path=urlparse(self.path).path,
            status=int(status),
            message=message,
        )

    def _serve_static(self, request_path: str) -> None:
        relative = "index.html" if request_path in {"", "/"} else request_path.lstrip("/")
        path = (STATIC_ROOT / relative).resolve()
        if STATIC_ROOT.resolve() not in path.parents and path != STATIC_ROOT.resolve():
            raise StudioError("资源不存在", HTTPStatus.NOT_FOUND)
        if not path.is_file():
            raise StudioError("资源不存在", HTTPStatus.NOT_FOUND)
        content = path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self._security_headers()
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def _serve_brand_logo(self, dark: bool) -> None:
        path = STATIC_ROOT / ("logo-dark.svg" if dark else "logo.svg")
        if not path.is_file():
            raise StudioError("品牌资源不存在", HTTPStatus.NOT_FOUND)
        content = path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self._security_headers()
        self.send_header("Content-Type", "image/svg+xml")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def _body_json(self) -> dict[str, Any]:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError as exc:
            raise StudioError("无效请求长度") from exc
        if length <= 0 or length > MAX_DOCUMENT_BYTES + 65536:
            raise StudioError("无效请求体", HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
        try:
            payload = json.loads(self.rfile.read(length))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise StudioError("请求 JSON 无效") from exc
        if not isinstance(payload, dict):
            raise StudioError("请求必须是 JSON 对象")
        return payload

    def _require_write_header(self) -> None:
        if self.headers.get(WRITE_HEADER) != "1":
            raise StudioError("缺少 Studio 写入凭证", HTTPStatus.FORBIDDEN)

    def _json(self, payload: Any, status: int = HTTPStatus.OK) -> None:
        body = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(status)
        self._security_headers()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _security_headers(self) -> None:
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; img-src 'self' data:; style-src 'self'; "
            "script-src 'self'; connect-src 'self'; frame-ancestors 'none'",
        )
        self.send_header("Cache-Control", "no-store")


class LegacyOpenWriteStudioServer(ThreadingHTTPServer):
    app: StudioApplication


StudioRequestHandler = ModularStudioRequestHandler
OpenWriteStudioServer = ModularOpenWriteStudioServer


def create_server(
    project_root: Path,
    *,
    host: str = "127.0.0.1",
    port: int = 4567,
    writer_executor: Callable[[Path, dict[str, Any]], dict[str, Any]] | None = None,
    review_executor: Callable[[Path, dict[str, Any]], dict[str, Any]] | None = None,
    chat_executor: Callable[[Path, str, str, str], dict[str, Any]] | None = None,
    source_executor: Callable[[Path, dict[str, Any]], dict[str, Any]] | None = None,
    revision_executor: Callable[[Path, dict[str, Any]], dict[str, Any] | str]
    | None = None,
    project_registry: ProjectRegistry | None = None,
    model_settings_store: StudioModelSettingsStore | None = None,
    model_profile_store: ModelProfileStore | None = None,
    reference_library_root: Path | None = None,
    debug: bool = False,
) -> ModularOpenWriteStudioServer:
    if not STATIC_ROOT.is_dir():
        raise StudioError(f"Studio 静态资源缺失: {STATIC_ROOT}")
    missing_assets = missing_required_static_assets()
    if missing_assets:
        raise StudioError(
            "OpenWrite 安装不完整，缺少 Studio 核心资源: " + ", ".join(missing_assets),
            HTTPStatus.INTERNAL_SERVER_ERROR,
            code="STUDIO_INSTALLATION_INCOMPLETE",
            details={"missing_assets": missing_assets},
        )
    app = StudioApplication(
        project_root,
        writer_executor=writer_executor,
        review_executor=review_executor,
        chat_executor=chat_executor,
        source_executor=source_executor,
        revision_executor=revision_executor,
        project_registry=project_registry,
        model_settings_store=model_settings_store,
        model_profile_store=model_profile_store,
        reference_library_root=reference_library_root,
        debug=debug,
    )
    handler = partial(ModularStudioRequestHandler, directory=str(STATIC_ROOT))
    server = ModularOpenWriteStudioServer((host, port), handler)
    server.app = app
    return server


def run_studio(
    project_root: Path,
    *,
    port: int = 4567,
    open_browser: bool = True,
    debug: bool = False,
) -> int:
    server = create_server(
        project_root,
        port=port,
        debug=debug,
        project_registry=ProjectRegistry(),
    )
    url = f"http://127.0.0.1:{server.server_port}"
    print(f"OpenWrite Studio: {url}")
    if server.app.debug_enabled and server.app.debug_log_path is not None:
        print(f"Debug log: {server.app.debug_log_path}")
    print("按 Ctrl+C 停止")
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStudio 已停止")
    finally:
        server.server_close()
    return 0
