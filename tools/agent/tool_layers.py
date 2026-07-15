"""Shared novel-agent action surface for CLI, Studio, Goethe and Dante."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import yaml

from .tool_runtime import build_tool_executors


def _load_novel_id(project_root: Path, requested: str | None = None) -> str:
    if requested:
        return requested
    config_path = project_root / "novel_config.yaml"
    if not config_path.exists():
        return "current"
    data = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    return str(data.get("novel_id") or "current")


def _read_text_arg(args: dict[str, Any], *keys: str, default: str = "") -> str:
    for key in keys:
        value = args.get(key)
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return default


def _positive_int(value: Any) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return 0
    return parsed if parsed > 0 else 0


def _missing_required(action: str, field_name: str) -> dict[str, object]:
    return {
        "action": action,
        "ok": False,
        "blocked": True,
        "error": f"missing_{field_name}",
        "message": f"缺少必需参数: {field_name}",
        field_name: "",
    }


def build_dante_tool_layers(project_root: Path) -> dict[str, object]:
    """Build Dante's direct and high-level action tools without a CLI dependency."""
    from .dante_actions import DanteActionAdapter
    from .orchestrator import OpenWriteOrchestrator
    from .toolkits import DANTE_ACTION_TOOLKIT, DANTE_DIRECT_TOOLKIT

    project_root = Path(project_root).resolve()
    tool_executors = build_tool_executors(project_root)
    orchestrator = OpenWriteOrchestrator(
        project_root=project_root,
        novel_id=_load_novel_id(project_root),
        tool_executors=tool_executors,
    )
    adapter = DanteActionAdapter(orchestrator)
    action_tool_executors: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {
        "summarize_ideation": lambda args: adapter.summarize_ideation(),
        "confirm_ideation_summary": lambda args: adapter.confirm_ideation_summary(
            _read_text_arg(args, "text", "confirmation", default="这个汇总可以")
        ),
        "generate_outline_draft": lambda args: adapter.generate_outline_draft(
            _read_text_arg(args, "request_text", "text", default="帮我生成一份四级大纲")
        ),
        "run_chapter_preflight": lambda args: (
            adapter.run_chapter_preflight(
                _read_text_arg(args, "chapter_id", "chapter")
            )
            if _read_text_arg(args, "chapter_id", "chapter")
            else _missing_required("run_chapter_preflight", "chapter_id")
        ),
        "delegate_chapter_write": lambda args: (
            adapter.delegate_chapter_write(
                _read_text_arg(args, "chapter_id", "chapter"),
                guidance=_read_text_arg(args, "guidance", "text"),
                target_words=_positive_int(args.get("target_words")),
            )
            if _read_text_arg(args, "chapter_id", "chapter")
            else _missing_required("delegate_chapter_write", "chapter_id")
        ),
        "delegate_chapter_review": lambda args: (
            adapter.delegate_chapter_review(
                _read_text_arg(args, "chapter_id", "chapter"),
                guidance=_read_text_arg(args, "guidance", "text"),
            )
            if _read_text_arg(args, "chapter_id", "chapter")
            else _missing_required("delegate_chapter_review", "chapter_id")
        ),
    }
    return {
        "tool_executors": tool_executors,
        "direct_toolkit": DANTE_DIRECT_TOOLKIT,
        "action_toolkit": DANTE_ACTION_TOOLKIT,
        "direct_tool_executors": {
            name: tool_executors[name]
            for name in DANTE_DIRECT_TOOLKIT
            if name in tool_executors
        },
        "action_tool_executors": action_tool_executors,
    }


def build_goethe_tool_layers(
    project_root: Path,
    novel_id: str | None = None,
) -> dict[str, object]:
    """Build Goethe's novel-planning tools from the same action surface."""
    from .goethe_actions import GoetheActionAdapter, GoethePlanningRuntime
    from .toolkits import GOETHE_ACTION_TOOLKIT, GOETHE_DIRECT_TOOLKIT

    project_root = Path(project_root).resolve()
    tool_executors = build_tool_executors(project_root)
    runtime = GoethePlanningRuntime(
        project_root=project_root,
        novel_id=_load_novel_id(project_root, novel_id),
        tool_executors=tool_executors,
    )
    adapter = GoetheActionAdapter(runtime)
    action_tool_executors: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {
        "summarize_ideation": lambda args: adapter.summarize_ideation(),
        "generate_foundation_draft": lambda args: (
            adapter.generate_foundation_draft(
                _read_text_arg(args, "request_text", "text", "brief")
            )
            if _read_text_arg(args, "request_text", "text", "brief")
            else _missing_required("generate_foundation_draft", "request_text")
        ),
        "generate_character_draft": lambda args: (
            adapter.generate_character_draft(
                _read_text_arg(args, "request_text", "text", "brief")
            )
            if _read_text_arg(args, "request_text", "text", "brief")
            else _missing_required("generate_character_draft", "request_text")
        ),
        "generate_outline_draft": lambda args: (
            adapter.generate_outline_draft(
                _read_text_arg(args, "request_text", "text", "brief")
            )
            if _read_text_arg(args, "request_text", "text", "brief")
            else _missing_required("generate_outline_draft", "request_text")
        ),
        "extract_style_source": lambda args: adapter.extract_style_source(
            _read_text_arg(args, "source_id", "source_name"),
            _read_text_arg(args, "source", "source_file", "text"),
        ),
        "extract_setting_source": lambda args: adapter.extract_setting_source(
            _read_text_arg(args, "source_id", "source_name"),
            _read_text_arg(args, "source", "source_file", "text"),
        ),
        "review_source_pack": lambda args: (
            adapter.review_source_pack(
                _read_text_arg(args, "source_id", "source_name")
            )
            if _read_text_arg(args, "source_id", "source_name")
            else _missing_required("review_source_pack", "source_id")
        ),
        "promote_source_pack": lambda args: (
            adapter.promote_source_pack(
                _read_text_arg(args, "source_id", "source_name"),
                target=_read_text_arg(args, "target", default="all"),
            )
            if _read_text_arg(args, "source_id", "source_name")
            else _missing_required("promote_source_pack", "source_id")
        ),
        "prepare_dante_handoff": lambda args: adapter.prepare_dante_handoff(),
    }
    return {
        "tool_executors": tool_executors,
        "direct_toolkit": GOETHE_DIRECT_TOOLKIT,
        "action_toolkit": GOETHE_ACTION_TOOLKIT,
        "direct_tool_executors": {
            name: tool_executors[name]
            for name in GOETHE_DIRECT_TOOLKIT
            if name in tool_executors
        },
        "action_tool_executors": action_tool_executors,
    }
