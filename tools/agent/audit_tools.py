"""Read-only runtime audit tools shared by Dante and Goethe."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import yaml

from tools.llm.response import redact_sensitive_text

AUDIT_TOOL_NAMES = {
    "inspect_agent_context",
    "list_chapter_runs",
    "get_runtime_state",
    "get_chapter_review",
    "get_task_activity",
    "get_goethe_handoff",
}

_SENSITIVE_KEYS = {
    "api_key",
    "apikey",
    "authorization",
    "credential",
    "credentials",
    "password",
    "secret",
    "access_token",
}


def execute_audit_tool(
    project_root: Path,
    novel_id: str,
    operation: str,
    args: dict[str, Any],
) -> dict[str, Any]:
    if operation == "inspect_agent_context":
        return _inspect_agent_context(project_root, args)
    if operation == "list_chapter_runs":
        return _list_chapter_runs(project_root, novel_id, args)
    if operation == "get_runtime_state":
        return _get_runtime_state(project_root, novel_id)
    if operation == "get_chapter_review":
        return _get_chapter_review(project_root, novel_id, args)
    if operation == "get_task_activity":
        return _get_task_activity(project_root, novel_id, args)
    if operation == "get_goethe_handoff":
        return _get_goethe_handoff(project_root, novel_id, args)
    return {"ok": False, "error": f"未知审计工具: {operation}"}


def _inspect_agent_context(project_root: Path, args: dict[str, Any]) -> dict[str, Any]:
    from tools.agent_context_inspector import AgentContextInspector

    agent = str(args.get("agent") or "writer").strip().lower()
    if agent not in AgentContextInspector.AGENTS:
        return {"ok": False, "error": f"不支持的 Agent: {agent}"}
    try:
        inspection = AgentContextInspector(project_root).inspect(
            str(args.get("chapter_id") or "next"),
            agent=agent,
            instruction=str(args.get("instruction") or ""),
            guidance=str(args.get("guidance") or ""),
            target_words=_bounded_int(args.get("target_words"), 0, 0, 100000),
            exclude_latest_session_turn=bool(
                args.get("exclude_latest_session_turn", True)
            ),
        )
    except (RuntimeError, ValueError) as exc:
        return {"ok": False, "error": redact_sensitive_text(exc)}

    include_messages = bool(args.get("include_messages", False))
    include_payload = bool(args.get("include_payload", False))
    if not include_messages:
        inspection["messages"] = [
            {key: value for key, value in message.items() if key != "content"}
            for message in inspection.get("messages", [])
            if isinstance(message, dict)
        ]
    if not include_payload:
        inspection.pop("agent_payload", None)
    return _safe_payload({"ok": True, **inspection})


def _list_chapter_runs(
    project_root: Path, novel_id: str, args: dict[str, Any]
) -> dict[str, Any]:
    from tools.chapter_run_store import ChapterRunStore

    raw_statuses = args.get("statuses")
    statuses = (
        {str(item) for item in raw_statuses if str(item).strip()}
        if isinstance(raw_statuses, list)
        else None
    )
    try:
        runs = ChapterRunStore(project_root, novel_id).list(
            chapter_id=str(args.get("chapter_id") or ""),
            statuses=statuses,
            limit=_bounded_int(args.get("limit"), 20, 1, 100),
        )
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}
    return _safe_payload(
        {
            "ok": True,
            "count": len(runs),
            "runs": [item.model_dump(mode="json") for item in runs],
        }
    )


def _get_runtime_state(project_root: Path, novel_id: str) -> dict[str, Any]:
    from tools.runtime_state import RuntimeStateManager
    from tools.truth_manager import TruthFilesManager

    truth = TruthFilesManager(project_root, novel_id).load_truth_files()
    state = RuntimeStateManager(project_root, novel_id).load(
        {
            "current_state": truth.current_state,
            "ledger": truth.ledger,
            "relationships": truth.relationships,
        }
    )
    payload = state.model_dump(mode="json")
    legacy = payload.pop("legacy_documents", {})
    payload["legacy_document_manifest"] = {
        str(key): {
            "characters": len(str(value or "")),
            "revision": _revision(str(value or "")),
        }
        for key, value in legacy.items()
    }
    return _safe_payload({"ok": True, "runtime_state": payload})


def _get_chapter_review(
    project_root: Path, novel_id: str, args: dict[str, Any]
) -> dict[str, Any]:
    from tools.review_store import ReviewStore

    chapter_id = str(args.get("chapter_id") or "").strip()
    if not chapter_id:
        return {"ok": False, "error": "缺少 chapter_id"}
    store = ReviewStore(project_root, novel_id)
    try:
        review = store.load(chapter_id)
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}
    if review is None:
        return {"ok": False, "error": f"未找到审稿结果: {chapter_id}"}
    current_revision = store._source_revision(chapter_id)
    source_revision = str(review.get("source_revision") or "")
    return _safe_payload(
        {
            "ok": True,
            "chapter_id": chapter_id,
            "stale": bool(source_revision and current_revision != source_revision),
            "current_source_revision": current_revision,
            "review_revision": _revision(
                json.dumps(review, ensure_ascii=False, sort_keys=True, default=str)
            ),
            "review": review,
        }
    )


def _get_task_activity(
    project_root: Path, novel_id: str, args: dict[str, Any]
) -> dict[str, Any]:
    from tools.task_store import TASK_STATUSES, TaskStore, TaskStoreError

    store = TaskStore(project_root, novel_id)
    task_id = str(args.get("task_id") or "").strip()
    limit = _bounded_int(args.get("limit"), 20, 1, 200)
    if task_id:
        try:
            task = store.load(task_id)
            events = store.events(task_id, limit=limit)
        except (TaskStoreError, ValueError) as exc:
            return {"ok": False, "error": str(exc)}
        if task is None:
            return {"ok": False, "error": f"未找到任务: {task_id}"}
        return _safe_payload({"ok": True, "task": task, "events": events})

    raw_statuses = args.get("statuses")
    statuses = None
    if isinstance(raw_statuses, list):
        statuses = {str(item) for item in raw_statuses if str(item).strip()}
        if not statuses.issubset(TASK_STATUSES):
            return {"ok": False, "error": "任务状态筛选无效"}
    try:
        tasks = store.list(statuses=statuses, limit=limit)
    except TaskStoreError as exc:
        return {"ok": False, "error": str(exc)}
    summaries = [
        {
            key: task.get(key)
            for key in (
                "task_id",
                "type",
                "status",
                "phase",
                "chapter_id",
                "input_summary",
                "retryable",
                "retry_of",
                "attempt",
                "created_at",
                "started_at",
                "completed_at",
                "updated_at",
                "last_event_id",
                "error",
            )
        }
        for task in tasks
    ]
    return _safe_payload({"ok": True, "count": len(summaries), "tasks": summaries})


def _handoff_is_stale(manifest: dict[str, Any]) -> bool:
    """Whether any asset changed since the handoff was prepared."""
    recorded = manifest.get("asset_revisions")
    if not isinstance(recorded, dict) or not recorded:
        return False
    current = _current_asset_revisions(manifest)
    return any(current.get(key) != value for key, value in recorded.items())


def _stale_assets(manifest: dict[str, Any]) -> list[str]:
    recorded = manifest.get("asset_revisions")
    if not isinstance(recorded, dict):
        return []
    current = _current_asset_revisions(manifest)
    return sorted(key for key, value in recorded.items() if current.get(key) != value)


def _current_asset_revisions(manifest: dict[str, Any]) -> dict[str, str]:
    """Recompute the same signatures `prepare_dante_handoff` recorded."""
    from ..story_planning import StoryPlanningStore

    revisions: dict[str, str] = {}
    try:
        project_root = Path(str(manifest.get("project_root") or "")) if manifest.get("project_root") else None
        novel_id = str(manifest.get("novel_id") or "")
        if project_root is None or not novel_id:
            return revisions
        store = StoryPlanningStore(project_root, novel_id)
        revisions["outline"] = store.outline_source_revision()
        for label, path in (
            ("ideation_summary", store.ideation_summary_path),
            ("background", store.story_src_dir / "background.md"),
            ("foundation", store.story_src_dir / "foundation.md"),
        ):
            revisions[label] = store._hash_text(path.read_text(encoding="utf-8")) if path.exists() else ""
        for index, path in enumerate(manifest.get("persona_paths") or []):
            target = Path(str(path))
            revisions["persona_%d" % index] = store._hash_text(target.read_text(encoding="utf-8")) if target.exists() else ""
    except Exception:
        # An unreadable project must not crash the audit; report nothing rather
        # than guessing, and let the caller see the manifest as-is.
        return {}
    return revisions


def _get_goethe_handoff(
    project_root: Path, novel_id: str, args: dict[str, Any]
) -> dict[str, Any]:
    from tools.story_planning import StoryPlanningStore

    store = StoryPlanningStore(project_root, novel_id)
    yaml_path = store.goethe_handoff_yaml_path
    markdown_path = store.goethe_handoff_md_path
    if not yaml_path.is_file() and not markdown_path.is_file():
        return {"ok": False, "error": "尚未生成 Goethe -> Dante 交接产物"}
    manifest: dict[str, Any] = {}
    if yaml_path.is_file():
        try:
            loaded = yaml.safe_load(yaml_path.read_text(encoding="utf-8")) or {}
            manifest = loaded if isinstance(loaded, dict) else {}
        except (OSError, yaml.YAMLError):
            manifest = {}
    markdown = markdown_path.read_text(encoding="utf-8") if markdown_path.is_file() else ""
    max_chars = _bounded_int(args.get("max_chars"), 12000, 1000, 80000)
    # K4: report staleness instead of answering "ready" for a handoff whose
    # assets have since been rewritten. The revision hashes the whole manifest,
    # not the rendered Markdown — the Markdown template drops current_arc,
    # current_section, current_chapter and every path, so two handoffs differing
    # only in those produced an identical revision.
    stale = _handoff_is_stale(manifest)
    return _safe_payload(
        {
            "ok": True,
            "manifest": manifest,
            "markdown": markdown[:max_chars],
            "truncated": len(markdown) > max_chars,
            "revision": _revision(json.dumps(manifest, ensure_ascii=False, sort_keys=True)),
            "stale": stale,
            "stale_assets": [] if not stale else _stale_assets(manifest),
            "paths": {
                "markdown": str(markdown_path),
                "yaml": str(yaml_path),
            },
        }
    )


def _safe_payload(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): (
                "<redacted>"
                if str(key).lower() in _SENSITIVE_KEYS
                else _safe_payload(item)
            )
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_safe_payload(item) for item in value]
    if isinstance(value, tuple):
        return [_safe_payload(item) for item in value]
    if isinstance(value, str):
        return redact_sensitive_text(value)
    return value


def _bounded_int(value: Any, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(default if value in {None, ""} else value)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(maximum, parsed))


def _revision(content: str) -> str:
    return "sha256:" + hashlib.sha256(content.encode("utf-8")).hexdigest()
