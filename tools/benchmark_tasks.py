"""Read-only, task-specific benchmark choices, targets and execution blueprints."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

import yaml

from tools.review_rubric import QUALITY_DOMAINS, selected_domains

OUTLINE_DIMENSIONS = (
    1,
    2,
    3,
    4,
    5,
    6,
    7,
    9,
    11,
    15,
    24,
    25,
    26,
    27,
    28,
    29,
    30,
    31,
    32,
    33,
    34,
    35,
    36,
    37,
)
OUTLINE_RUBRIC_VERSION = "openwrite.outline-review.v1"
OUTLINE_PROMPT_VERSION = "architect-outline-window-v1"
MAX_PLANNING_CONTEXT_CHARS = 120_000


class BenchmarkInputError(ValueError):
    def __init__(self, message: str, *, code: str = "INVALID_INPUT"):
        super().__init__(message)
        self.code = code


def positive_integer(value: Any, *, name: str, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not re.fullmatch(r"\d+", str(value)):
        raise BenchmarkInputError(f"{name} 必须是整数")
    number = int(value)
    if not minimum <= number <= maximum:
        raise BenchmarkInputError(f"{name} 必须在 {minimum}-{maximum} 之间")
    return number


def benchmark_pipeline(task_type: str, execution_mode: str) -> dict[str, Any]:
    if task_type == "outline":
        stages = (
            ("context", "冻结规划上下文"),
            ("plan", "Architect 设计章纲"),
            ("validate", "校验结构与章节范围"),
            ("commit", "保存隔离规划产物"),
            ("review", "大纲专项评审"),
        )
        domains = selected_domains(OUTLINE_DIMENSIONS)
    elif execution_mode == "creative":
        stages = (("context", "冻结章节上下文"), ("draft", "生成候选正文"), ("review", "章节盲评"))
        domains = QUALITY_DOMAINS
    else:
        stages = (
            ("context", "冻结章节上下文"),
            ("plan", "准备章节写作计划"),
            ("draft", "生成候选正文"),
            ("fact_extract", "提取本章事实"),
            ("settle", "结算隔离运行态"),
            ("validate", "验证正文与运行态"),
            ("commit", "提交隔离正文"),
            ("review", "完整章节评审"),
        )
        domains = QUALITY_DOMAINS
    return {
        "id": f"openwrite.benchmark.{task_type}.{execution_mode}.v1",
        "execution_mode": execution_mode,
        "nodes": [
            {"id": stage, "label": label, "depends_on": [stages[index - 1][0]] if index else []}
            for index, (stage, label) in enumerate(stages)
        ],
        "review_domains": [{"id": domain.id, "label": domain.name} for domain in domains]
        + [{"id": "safety", "label": "安全门禁"}],
        "review_dimensions": list(OUTLINE_DIMENSIONS)
        if task_type == "outline"
        else list(range(1, 38)),
    }


def benchmark_options(project_root: Path, novel_id: str) -> dict[str, Any]:
    from tools.outline_tree import _flatten_nodes, build_outline_structure
    from tools.write_guard import readiness_issues

    root = Path(project_root).resolve() / "data" / "novels" / novel_id
    structure = build_outline_structure(root)
    nodes = [
        node
        for node in _flatten_nodes(list(structure.get("roots") or []))
        if node.get("kind") == "chapter"
    ]
    drafted = {
        path.stem
        for path in (root / "data" / "manuscript").rglob("ch_*.md")
        if re.fullmatch(r"ch_\d+", path.stem)
    }
    latest = max((int(item[3:]) for item in drafted), default=0)
    planned = max((int(str(node["id"])[3:]) for node in nodes), default=0)
    next_chapter_id = f"ch_{latest + 1:03d}"
    outline_start = max(planned, latest) + 1
    issues = readiness_issues(project_root, novel_id)
    chapters = []
    for node in nodes:
        chapter_id = str(node["id"])
        historical = int(chapter_id[3:]) <= latest
        reason = (
            "当前事实已包含该章或后续正文，缺少可验证的章前完整基线；请选择尚未写到的章节"
            if historical
            else "；".join(issues)
        )
        chapters.append(
            {
                "chapter_id": chapter_id,
                "title": str(node.get("title") or chapter_id),
                "status": str(node.get("status") or "planned"),
                "has_manuscript": chapter_id in drafted,
                "availability": "unavailable" if reason else "available",
                "reason": reason,
            }
        )
    return {
        "chapters": chapters,
        "next_chapter_id": next_chapter_id,
        "latest_manuscript_chapter": latest,
        "default_outline_start_chapter": outline_start,
        "limits": {
            "outline_start_chapter": {"min": latest + 1, "max": 100000},
            "outline_chapter_count": {"min": 1, "max": 20, "default": 3},
            "target_words": {"min": 200, "max": 12000, "default": 3000},
            "repeats": {"min": 1, "max": 5, "default": 1},
            "concurrency": {"min": 1, "max": 4, "default": 1},
            "planning_context_chars": {"max": MAX_PLANNING_CONTEXT_CHARS},
        },
        "tasks": [
            {
                "task_type": task,
                "execution_modes": modes,
                "pipelines": [benchmark_pipeline(task, mode) for mode in modes],
                "readiness": benchmark_readiness(
                    project_root,
                    novel_id,
                    task,
                    next_chapter_id if task == "chapter" else f"ch_{outline_start:03d}",
                ),
            }
            for task, modes in (("chapter", ["framework", "creative"]), ("outline", ["framework"]))
        ],
    }


def benchmark_readiness(
    project_root: Path, novel_id: str, task_type: str, chapter_id: str
) -> dict[str, Any]:
    """Inspect the same target guards used before generation, without writing facts."""
    from tools.manuscript_acceptance import ManuscriptAcceptanceError, ManuscriptAcceptanceService
    from tools.write_guard import validate_chapter_writable

    try:
        if task_type == "outline":
            validate_outline_ready(project_root, novel_id, chapter_id)
        else:
            ManuscriptAcceptanceService(project_root, novel_id).require_current(chapter_id)
            guard = validate_chapter_writable(project_root, novel_id, chapter_id)
            if not guard.get("ok"):
                return {
                    "ok": False,
                    "code": str(guard.get("code") or "PROJECT_NOT_READY"),
                    "message": str(guard.get("message") or "目标章节尚未就绪"),
                }
    except (ManuscriptAcceptanceError, BenchmarkInputError) as exc:
        return {"ok": False, "code": exc.code, "message": str(exc)}
    return {"ok": True, "code": "", "message": ""}


def benchmark_target(
    project_root: Path, novel_id: str, payload: dict[str, Any], *, enforce_history: bool = True
) -> dict[str, Any]:
    task = str(payload.get("task_type") or "chapter")
    mode = str(payload.get("execution_mode") or "framework")
    if task not in {"chapter", "outline"}:
        raise BenchmarkInputError("task_type 必须是 chapter 或 outline")
    if mode not in {"framework", "creative"} or (task == "outline" and mode != "framework"):
        raise BenchmarkInputError(
            "execution_mode：大纲仅支持 framework；章节支持 framework 或 creative"
        )
    options = benchmark_options(project_root, novel_id)
    latest = options["latest_manuscript_chapter"]
    target: dict[str, Any] = {"task_type": task, "execution_mode": mode}
    if task == "outline":
        start = positive_integer(
            payload.get("outline_start_chapter", options["default_outline_start_chapter"]),
            name="大纲起始章节",
            minimum=1,
            maximum=100000,
        )
        count = positive_integer(
            payload.get("outline_chapter_count", 3), name="大纲章节数量", minimum=1, maximum=20
        )
        if start + count - 1 > 100000:
            raise BenchmarkInputError("大纲结束章节不能超过 100000")
        target.update(
            outline_start_chapter=start,
            outline_chapter_count=count,
            outline_end_chapter=start + count - 1,
        )
        chapter_id = f"ch_{start:03d}"
    else:
        requested = str(payload.get("chapter_id") or "next")
        chapter_id = options["next_chapter_id"] if requested == "next" else requested
        if not re.fullmatch(r"ch_\d+", chapter_id) or int(chapter_id[3:]) < 1:
            raise BenchmarkInputError("章节 ID 必须形如 ch_001")
        chapter_id = f"ch_{int(chapter_id[3:]):03d}"
    if enforce_history and int(chapter_id[3:]) <= latest:
        raise BenchmarkInputError(
            "当前事实包含所选章节或后续正文，不能构建可信的章前测试基线；请选择尚未写到的章节",
            code="BENCHMARK_HISTORICAL_CONTEXT_UNAVAILABLE",
        )
    target["chapter_id"] = chapter_id
    return target


def validate_outline_ready(project_root: Path, novel_id: str, chapter_id: str) -> None:
    from tools.manuscript_acceptance import ManuscriptAcceptanceService
    from tools.write_guard import REQUIRED_STORY_DOCS, _looks_like_template

    root = Path(project_root).resolve() / "data" / "novels" / novel_id
    issues = []
    for name in REQUIRED_STORY_DOCS:
        path = root / "src" / "story" / name
        text = path.read_text(encoding="utf-8") if path.is_file() else ""
        if not text.strip() or _looks_like_template(text):
            issues.append(f"src/story/{name} 尚未准备，请先补齐作者方向和设定")
    if issues:
        raise BenchmarkInputError("；".join(issues), code="PROJECT_NOT_READY")
    ManuscriptAcceptanceService(project_root, novel_id).require_current(chapter_id)


def outline_context_preview(
    project_root: Path, novel_id: str, target: dict[str, Any]
) -> dict[str, Any]:
    """Freeze full canonical sources without a chapter-writable or model dependency."""
    from tools.context_manifest import build_context_manifest

    validate_outline_ready(project_root, novel_id, target["chapter_id"])
    root = Path(project_root).resolve() / "data" / "novels" / novel_id
    paths = sorted(
        {
            *root.glob("src/story/*.md"),
            *root.glob("src/characters/*.md"),
            *root.glob("src/world/**/*.md"),
            *root.glob("data/world/*.md"),
            *root.glob("data/world/*.yaml"),
            *root.glob("data/foreshadowing/*.yaml"),
            *root.glob("data/memory/chapters/*.yaml"),
            *root.glob("src/outline.md"),
        }
    )
    documents = {
        path.relative_to(root).as_posix(): path.read_text(encoding="utf-8")
        for path in paths
        if path.is_file()
    }
    rendered = "\n\n".join(f"## {path}\n{text}" for path, text in documents.items())
    if len(rendered) > MAX_PLANNING_CONTEXT_CHARS:
        raise BenchmarkInputError(
            "规划上下文超过 120000 字符；请先整理设定与大纲后再测试",
            code="BENCHMARK_CONTEXT_TOO_LARGE",
        )
    config = (
        yaml.safe_load((Path(project_root) / "novel_config.yaml").read_text(encoding="utf-8")) or {}
    )
    packet = {
        **target,
        "title": str(config.get("title") or novel_id),
        "genre": str(config.get("genre") or "unspecified"),
        "planning_context": rendered,
        "outline": documents.get("src/outline.md", ""),
        "author_intent": documents.get("src/story/author_intent.md", ""),
        "creative_focus": documents.get("src/story/current_focus.md", ""),
        "core_documents": documents,
    }
    manifest = build_context_manifest(root, packet)
    manifest["strategy"] = "outline-canonical-snapshot-v1"
    manifest["source_revision"] = hashlib.sha256(
        json.dumps(documents, ensure_ascii=False, sort_keys=True).encode()
    ).hexdigest()
    return {
        "chapter_id": target["chapter_id"],
        "packet": packet,
        "manifest": manifest,
        "characters": [],
    }
