"""Write-readiness guards for model benchmarking and chapter generation.

Gap being closed: previously a model benchmark / chapter write could run on a
project whose canonical docs were still the out-of-box placeholders, or on a
chapter id that has no outline node.  The pipeline then faithfully assembled a
thin context and the model free-wrote off-topic prose that even passed blind
review (no canon facts to compare against).

This module centralises two cheap, deterministic checks:

* project readiness: the canonical docs that define the book's identity
  (outline, author intent, creative focus, background, foundation) must exist
  and must not still contain template placeholders.
* target chapter node: the requested chapter id must resolve to a chapter node
  in the outline tree.

Callers (model benchmark / write entrypoints) raise with a stable error code
instead of silently proceeding.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Optional

# Placeholder markers used by every OpenWrite init template.  "待填写" appears
# in every template doc (and only in templates / never as a content word), so
# it is both necessary and sufficient; avoid looser tokens such as "占位",
# which legitimately appears in author notes ("（还有耶）为占位符").
_PLACEHOLDER_RE = re.compile(r"待填写")

# Canonical identity docs that must be authored (not templates) before any
# real chapter-level generation makes sense.
REQUIRED_STORY_DOCS = (
    "author_intent.md",
    "current_focus.md",
    "background.md",
    "foundation.md",
)


def _novel_root(project_root: Path, novel_id: str) -> Path:
    return Path(project_root).resolve() / "data" / "novels" / novel_id


def _looks_like_template(text: str) -> bool:
    return bool(_PLACEHOLDER_RE.search(text or ""))


def readiness_issues(project_root: Path, novel_id: str) -> list[str]:
    """Return a list of human-readable readiness problems (empty = ready).

    Only *present-but-placeholder* documents are flagged.  A project with no
    canonical docs at all is treated as not-judgeable here (headless/synthetic
    projects, legacy shapes); the outline-node check in
    :func:`validate_chapter_writable` still guards real outlines, and the
    template markers catch the "docs exist but were never authored" accident
    that previously let a benchmark run against an empty project.
    """
    novel_root = _novel_root(project_root, novel_id)
    issues: list[str] = []

    outline_path = novel_root / "src" / "outline.md"
    if outline_path.is_file():
        text = outline_path.read_text(encoding="utf-8", errors="replace")
        if _looks_like_template(text):
            issues.append("src/outline.md 仍是初始化模板（含“待填写”占位），请先撰写大纲与章纲")

    story_dir = novel_root / "src" / "story"
    for name in REQUIRED_STORY_DOCS:
        path = story_dir / name
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        if _looks_like_template(text):
            label = name.replace(".md", "")
            issues.append(f"src/story/{name}（{label}）仍是“待填写”模板，请先补齐")

    return issues


def outline_node(
    project_root: Path, novel_id: str, chapter_id: str
) -> Optional[dict[str, Any]]:
    """Find the outline node for ``chapter_id`` (None when absent).

    Returns ``None`` both when the node does not exist and when there is no
    parseable outline at all (synthetic projects) — the caller decides how to
    treat the latter via :func:`validate_chapter_writable`.
    """
    novel_root = _novel_root(project_root, novel_id)
    if not (novel_root / "src" / "outline.md").is_file():
        return None
    try:
        from tools.outline_tree import build_outline_structure, _flatten_nodes

        structure = build_outline_structure(novel_root)
        nodes = _flatten_nodes(list(structure.get("roots") or []))
    except Exception:
        return None
    for node in nodes:
        if str(node.get("id") or "") == chapter_id:
            return node
    return None


def validate_chapter_writable(
    project_root: Path, novel_id: str, chapter_id: str
) -> dict[str, Any]:
    """Validate that ``chapter_id`` may be targeted by a real generation run.

    Returns ``{"ok": True}`` or ``{"ok": False, "code": ..., "message": ...,
    "issues": [...]}``.

    Rules:
    * documents that exist but still contain template placeholders → block;
    * when a real outline exists, the target chapter must have a node → block;
    * a project with no canonical docs / no outline is not judged here (kept
      permissive for headless synthetic flows; their writes still have no
      template docs to mislead with).
    """
    chapter_id = str(chapter_id or "").strip()
    issues: list[str] = []
    has_outline = (_novel_root(project_root, novel_id) / "src" / "outline.md").is_file()

    issues.extend(readiness_issues(project_root, novel_id))

    node = None
    if has_outline:
        node = outline_node(project_root, novel_id, chapter_id) if chapter_id else None
    if not re.fullmatch(r"ch_\d+", chapter_id):
        issues.append(f"无效章节 id: {chapter_id!r}（应为 ch_<数字>）")
    elif has_outline and node is None:
        issues.append(
            f"章节 {chapter_id} 在大纲中没有对应节点：要么该章纲尚未写入大纲，"
            "要么大纲窗口已耗尽。请先补该章章纲（或先生成滚动规划/确认章纲）再运行。"
        )
    elif node is not None and str(node.get("kind") or "") != "chapter":
        issues.append(f"节点 {chapter_id} 不是章节节点（kind={node.get('kind')}）")

    if not issues:
        return {"ok": True, "chapter_id": chapter_id}

    if any("大纲" in issue for issue in issues) and not any(
        "待填写" in issue for issue in issues
    ):
        code = "TARGET_NOT_PLANNED"
    else:
        code = "PROJECT_NOT_READY"
    return {
        "ok": False,
        "chapter_id": chapter_id,
        "code": code,
        "message": "；".join(issues),
        "issues": issues,
    }
