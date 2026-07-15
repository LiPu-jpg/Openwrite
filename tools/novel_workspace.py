"""Novel-only workspace services for OpenWrite.

This module deliberately stays independent from the LLM runtime.  It provides
the deterministic parts of a long-form writing workflow: a creative compass,
manuscript import/export, and project-level progress statistics.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import asdict, dataclass, field
from pathlib import Path

import yaml

CHAPTER_FILE_RE = re.compile(r"^ch_(\d+)\.md$")
CHAPTER_HEADING_RE = re.compile(
    r"^\s*(?:#{1,6}\s*)?"
    r"((?:第[0-9零〇一二两三四五六七八九十百千万]+章|Chapter\s+\d+|序章|楔子|前言|后记|尾声)"
    r"[^\n]*)\s*$",
    re.IGNORECASE | re.MULTILINE,
)


@dataclass
class CreativeFocus:
    goal: str = ""
    must_keep: list[str] = field(default_factory=list)
    must_avoid: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        return not any((self.goal.strip(), self.must_keep, self.must_avoid, self.notes))


@dataclass
class ChapterRecord:
    chapter_id: str
    title: str
    path: Path
    writing_units: int


@dataclass
class WorkspaceSnapshot:
    novel_id: str
    title: str
    current_arc: str
    current_chapter: str
    stage: str
    chapters: int
    writing_units: int
    target_units: int
    characters: int
    world_documents: int
    pending_foreshadowing: int
    total_tokens: int
    reviewed_chapters: int
    average_review_score: float
    creative_focus: CreativeFocus
    readiness: dict[str, bool]
    next_actions: list[str]

    def to_dict(self) -> dict[str, object]:
        data = asdict(self)
        return data


def novel_root(project_root: Path, novel_id: str) -> Path:
    return Path(project_root) / "data" / "novels" / novel_id


def author_intent_path(project_root: Path, novel_id: str) -> Path:
    return novel_root(project_root, novel_id) / "src" / "story" / "author_intent.md"


def current_focus_path(project_root: Path, novel_id: str) -> Path:
    return novel_root(project_root, novel_id) / "src" / "story" / "current_focus.md"


def load_author_intent(project_root: Path, novel_id: str) -> str:
    path = author_intent_path(project_root, novel_id)
    return path.read_text(encoding="utf-8").strip() if path.exists() else ""


def load_creative_focus(project_root: Path, novel_id: str) -> CreativeFocus:
    path = current_focus_path(project_root, novel_id)
    if not path.exists():
        return CreativeFocus()
    text = path.read_text(encoding="utf-8")
    goal = _markdown_section(text, "当前阶段目标")
    if "待填写" in goal:
        goal = ""
    return CreativeFocus(
        goal=goal,
        must_keep=_markdown_list(text, "必须保留"),
        must_avoid=_markdown_list(text, "必须避免"),
        notes=_markdown_list(text, "写作备注"),
    )


def save_creative_focus(
    project_root: Path,
    novel_id: str,
    *,
    goal: str,
    must_keep: Iterable[str] = (),
    must_avoid: Iterable[str] = (),
    notes: Iterable[str] = (),
) -> Path:
    path = current_focus_path(project_root, novel_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    focus = CreativeFocus(
        goal=goal.strip(),
        must_keep=_clean_items(must_keep),
        must_avoid=_clean_items(must_avoid),
        notes=_clean_items(notes),
    )
    path.write_text(render_creative_focus(focus), encoding="utf-8")
    return path


def render_creative_focus(focus: CreativeFocus) -> str:
    return (
        "# 创作罗盘\n\n"
        "<!-- 这是近期写作的最高优先级约束；Dante 会把它注入每章上下文。 -->\n\n"
        "## 当前阶段目标\n\n"
        f"{focus.goal or '（待填写：这一阶段最重要的叙事目标）'}\n\n"
        "## 必须保留\n\n"
        f"{_render_list(focus.must_keep)}\n\n"
        "## 必须避免\n\n"
        f"{_render_list(focus.must_avoid)}\n\n"
        "## 写作备注\n\n"
        f"{_render_list(focus.notes)}\n"
    )


def list_chapters(project_root: Path, novel_id: str) -> list[ChapterRecord]:
    manuscript_root = novel_root(project_root, novel_id) / "data" / "manuscript"
    if not manuscript_root.exists():
        return []

    records: dict[str, ChapterRecord] = {}
    for path in sorted(manuscript_root.glob("**/ch_*.md")):
        match = CHAPTER_FILE_RE.fullmatch(path.name)
        if not path.is_file() or not match:
            continue
        text = path.read_text(encoding="utf-8")
        title = _first_markdown_heading(text) or path.stem
        record = ChapterRecord(
            chapter_id=path.stem,
            title=title,
            path=path,
            writing_units=count_writing_units(text),
        )
        # Prefer the lexically later path for duplicate chapter IDs.  In normal
        # projects there is only one; this keeps the operation deterministic.
        records[path.stem] = record
    return sorted(records.values(), key=lambda item: _chapter_number(item.chapter_id))


def count_writing_units(text: str) -> int:
    """Count CJK characters plus whitespace-delimited non-CJK words.

    This is closer to how Chinese publishing platforms describe manuscript
    length than ``len(text)`` while still working for mixed-language prose.
    Markdown headings and lightweight markup are excluded.
    """

    prose = re.sub(r"^\s{0,3}#{1,6}\s+.*$", "", text, flags=re.MULTILINE)
    prose = re.sub(r"<!--.*?-->", "", prose, flags=re.DOTALL)
    prose = re.sub(r"[`*_~>#\[\](){|}]", " ", prose)
    cjk = re.findall(r"[\u3400-\u4dbf\u4e00-\u9fff]", prose)
    non_cjk = re.sub(r"[\u3400-\u4dbf\u4e00-\u9fff]", " ", prose)
    words = re.findall(r"[A-Za-z0-9]+(?:['’-][A-Za-z0-9]+)*", non_cjk)
    return len(cjk) + len(words)


def import_manuscript(
    project_root: Path,
    novel_id: str,
    source: Path,
    *,
    arc_id: str,
    start_number: int | None = None,
    force: bool = False,
) -> list[ChapterRecord]:
    source = Path(source)
    if not source.is_file():
        raise FileNotFoundError(f"导入文件不存在: {source}")
    if source.suffix.lower() not in {".txt", ".md", ".markdown"}:
        raise ValueError("当前仅支持 TXT 和 Markdown 导入")

    text = source.read_text(encoding="utf-8-sig").strip()
    if not text:
        raise ValueError("导入文件为空")

    chunks = split_manuscript(text, fallback_title=source.stem)
    target_dir = novel_root(project_root, novel_id) / "data" / "manuscript" / arc_id
    target_dir.mkdir(parents=True, exist_ok=True)

    existing = list_chapters(project_root, novel_id)
    next_number = (
        start_number
        if start_number is not None
        else max((_chapter_number(item.chapter_id) for item in existing), default=0) + 1
    )
    if next_number < 1:
        raise ValueError("起始章节号必须大于 0")
    imported: list[ChapterRecord] = []

    for offset, (title, content) in enumerate(chunks):
        chapter_id = f"ch_{next_number + offset:03d}"
        path = target_dir / f"{chapter_id}.md"
        if path.exists() and not force:
            raise FileExistsError(f"章节已存在: {path}")
        normalized = f"# {title.strip()}\n\n{content.strip()}\n"
        path.write_text(normalized, encoding="utf-8")
        imported.append(
            ChapterRecord(
                chapter_id=chapter_id,
                title=title.strip(),
                path=path,
                writing_units=count_writing_units(normalized),
            )
        )
    return imported


def split_manuscript(text: str, *, fallback_title: str) -> list[tuple[str, str]]:
    matches = list(CHAPTER_HEADING_RE.finditer(text))
    if not matches:
        return [(fallback_title.strip() or "导入章节", text.strip())]

    chunks: list[tuple[str, str]] = []
    prefix = text[: matches[0].start()].strip()
    for index, match in enumerate(matches):
        title = match.group(1).strip().lstrip("#").strip()
        content_start = match.end()
        content_end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        content = text[content_start:content_end].strip()
        if index == 0 and prefix:
            content = f"{prefix}\n\n{content}".strip()
        chunks.append((title, content))
    return chunks


def export_manuscript(
    project_root: Path,
    novel_id: str,
    output: Path,
    *,
    format_name: str = "md",
    title: str = "",
) -> Path:
    chapters = list_chapters(project_root, novel_id)
    if not chapters:
        raise ValueError("还没有可导出的章节")

    format_name = format_name.lower()
    if format_name not in {"md", "txt"}:
        raise ValueError("导出格式仅支持 md 或 txt")

    book_title = title.strip() or novel_id
    parts: list[str] = [f"# {book_title}" if format_name == "md" else book_title]
    for chapter in chapters:
        text = chapter.path.read_text(encoding="utf-8").strip()
        if format_name == "txt":
            text = re.sub(r"^\s{0,3}#{1,6}\s+", "", text, flags=re.MULTILINE)
        parts.append(text)

    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n\n".join(parts).rstrip() + "\n", encoding="utf-8")
    return output


def build_workspace_snapshot(project_root: Path, config: dict[str, object]) -> WorkspaceSnapshot:
    from tools.chapter_memory import ChapterMemoryStore
    from tools.review_store import ReviewStore

    project_root = Path(project_root)
    novel_id = str(config.get("novel_id") or "unknown")
    root = novel_root(project_root, novel_id)
    chapters = list_chapters(project_root, novel_id)
    focus = load_creative_focus(project_root, novel_id)
    intent = load_author_intent(project_root, novel_id)
    outline = _read(root / "src" / "outline.md")
    background = _read(root / "src" / "story" / "background.md")
    foundation = _read(root / "src" / "story" / "foundation.md")
    outline_title = _first_markdown_heading(outline)
    title = str(config.get("title") or "")
    if not title and outline_title not in {"", "大纲"}:
        title = outline_title
    title = title or novel_id

    state_stage = "discovery"
    current_arc = str(config.get("current_arc") or "arc_001")
    current_chapter = str(config.get("current_chapter") or "ch_001")
    state_path = root / "data" / "workflows" / "book_state.yaml"
    if state_path.exists():
        try:
            state = yaml.safe_load(state_path.read_text(encoding="utf-8")) or {}
            state_stage = str(state.get("stage") or state_stage)
            current_arc = str(state.get("current_arc") or current_arc)
            current_chapter = str(state.get("current_chapter") or current_chapter)
        except (OSError, yaml.YAMLError):
            pass

    characters = list((root / "src" / "characters").glob("*.md"))
    world_documents = list((root / "src" / "world").glob("**/*.md"))
    pending_foreshadowing = _pending_foreshadowing_count(
        root / "data" / "foreshadowing" / "dag.yaml"
    )
    usage = ChapterMemoryStore(project_root, novel_id).usage_totals()
    review_analytics = ReviewStore(project_root, novel_id).analytics()
    target_units = _target_units(outline)
    readiness = {
        "author_intent": _is_substantive(intent),
        "background": _is_substantive(background),
        "foundation": _is_substantive(foundation),
        "characters": bool(characters),
        "outline": _outline_has_chapter(outline),
        "creative_focus": not focus.is_empty,
    }
    next_actions = _next_actions(readiness, bool(chapters))
    return WorkspaceSnapshot(
        novel_id=novel_id,
        title=title,
        current_arc=current_arc,
        current_chapter=current_chapter,
        stage=state_stage,
        chapters=len(chapters),
        writing_units=sum(item.writing_units for item in chapters),
        target_units=target_units,
        characters=len(characters),
        world_documents=len(world_documents),
        pending_foreshadowing=pending_foreshadowing,
        total_tokens=usage["total_tokens"],
        reviewed_chapters=int(review_analytics["reviewed_chapters"]),
        average_review_score=float(review_analytics["average_score"]),
        creative_focus=focus,
        readiness=readiness,
        next_actions=next_actions,
    )


def update_project_progress(
    project_root: Path,
    *,
    current_chapter: str,
    current_arc: str | None = None,
) -> None:
    config_path = Path(project_root) / "novel_config.yaml"
    if not config_path.exists():
        return
    data = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    data["current_chapter"] = current_chapter
    if current_arc:
        data["current_arc"] = current_arc
    config_path.write_text(
        yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )


def _markdown_section(text: str, heading: str) -> str:
    pattern = re.compile(
        rf"^##\s+{re.escape(heading)}\s*$\n(.*?)(?=^##\s+|\Z)",
        re.MULTILINE | re.DOTALL,
    )
    match = pattern.search(text)
    return match.group(1).strip() if match else ""


def _markdown_list(text: str, heading: str) -> list[str]:
    body = _markdown_section(text, heading)
    items = []
    for line in body.splitlines():
        stripped = line.strip()
        if stripped.startswith(("- ", "* ")):
            value = stripped[2:].strip()
            if value and not value.startswith("（待填写"):
                items.append(value)
    return items


def _clean_items(items: Iterable[str]) -> list[str]:
    clean: list[str] = []
    seen: set[str] = set()
    for item in items:
        value = str(item).strip()
        if value and value not in seen:
            seen.add(value)
            clean.append(value)
    return clean


def _render_list(items: Iterable[str]) -> str:
    values = _clean_items(items)
    return "\n".join(f"- {item}" for item in values) or "- （待填写）"


def _first_markdown_heading(text: str) -> str:
    match = re.search(r"^#\s+(.+?)\s*$", text, re.MULTILINE)
    return match.group(1).strip() if match else ""


def _chapter_number(chapter_id: str) -> int:
    match = re.search(r"(\d+)", chapter_id)
    return int(match.group(1)) if match else 0


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def _is_substantive(text: str) -> bool:
    stripped = re.sub(r"[`#>*_\-\s]", "", text)
    return bool(stripped) and "待填写" not in stripped[:80]


def _outline_has_chapter(text: str) -> bool:
    return bool(re.search(r"^####\s+.+", text, re.MULTILINE))


def _target_units(outline: str) -> int:
    match = re.search(r"目标字数\s*[:：]\s*([\d,]+)", outline)
    return int(match.group(1).replace(",", "")) if match else 0


def _pending_foreshadowing_count(path: Path) -> int:
    if not path.exists():
        return 0
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return 0
    nodes_raw = data.get("nodes", []) if isinstance(data, dict) else []
    nodes = nodes_raw.values() if isinstance(nodes_raw, dict) else nodes_raw
    return sum(
        1
        for node in nodes
        if isinstance(node, dict)
        and str(node.get("status", "pending")).lower()
        not in {"resolved", "closed", "已收", "废弃"}
    )


def _next_actions(readiness: dict[str, bool], has_chapters: bool) -> list[str]:
    if not readiness["author_intent"] or not readiness["background"]:
        return ["openwrite goethe", "先把核心承诺、背景和主角冲突聊清楚"]
    if not readiness["characters"] or not readiness["outline"]:
        return ["openwrite goethe", "补齐主要人物与当前可写范围大纲"]
    if not readiness["creative_focus"]:
        return ["openwrite focus set \"本阶段目标\"", "设定近期创作罗盘"]
    if has_chapters:
        return ["openwrite dante", "继续下一章，写完后审查并结算状态"]
    return ["openwrite dante", "从第一章开始进入写作—审查—结算闭环"]
