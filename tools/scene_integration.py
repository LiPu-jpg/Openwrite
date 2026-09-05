"""Read-only adapters from canonical scene state to exports and writing context.

The manuscript remains the only prose store.  These helpers consume
``SceneStructureService`` and ``ReadingOrderService`` projections and never
persist scene or document state themselves.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SCENE_CONTEXT_SCHEMA_VERSION = "openwrite.scene-context.v1"
_INTERNAL_SCENE_COMMENT_RE = re.compile(
    r"^[ \t]*<!--[ \t]*OPENWRITE:SCENE(?::[^\n]*|[ \t]+[^\n]*)?-->[ \t]*(?:\n|$)",
    re.IGNORECASE | re.MULTILINE,
)


@dataclass(frozen=True)
class SceneExportChapter:
    """One canonical chapter prepared for a public manuscript export."""

    chapter_id: str
    document_id: str
    occurrence_id: str
    title: str
    path: Path
    markdown: str


def load_scene_surface(project_root: Path, novel_id: str) -> dict[str, Any]:
    """Return the canonical scene projection, including the explicit absent state."""

    from tools.scene_structure import SceneStructureService

    return SceneStructureService(project_root, novel_id).surface()


def scene_export_chapters(
    project_root: Path,
    novel_id: str,
) -> list[SceneExportChapter] | None:
    """Prepare scene-aware prose, or ``None`` for byte-compatible legacy behavior.

    Once a scene sidecar exists, chapter locators come from the scene service's
    reading-order projection.  Current scene anchors may order the body.  A
    stale or ambiguous projection falls back to each complete chapter so a
    backup never drops prose.
    """

    root = Path(project_root).resolve()
    novel_root = (root / "data" / "novels" / str(novel_id)).resolve()
    surface = load_scene_surface(root, novel_id)
    if surface.get("status") == "absent":
        return None

    scenes_by_document: dict[str, list[dict[str, Any]]] = {}
    for scene in surface.get("scenes") or []:
        if not isinstance(scene, dict):
            continue
        chapter = scene.get("chapter") if isinstance(scene.get("chapter"), dict) else {}
        document_id = str(chapter.get("document_id") or "")
        if document_id:
            scenes_by_document.setdefault(document_id, []).append(scene)

    prepared: list[SceneExportChapter] = []
    seen_paths: set[Path] = set()
    for chapter in surface.get("chapters") or []:
        if not isinstance(chapter, dict):
            continue
        relative = str(chapter.get("path") or "")
        if not relative:
            continue
        path = (novel_root / relative).resolve()
        manuscript_root = (novel_root / "data" / "manuscript").resolve()
        try:
            path.relative_to(manuscript_root)
        except ValueError:
            continue
        if path in seen_paths or not path.is_file():
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            continue
        seen_paths.add(path)
        document_id = str(chapter.get("document_id") or "")
        markdown = content
        chapter_scenes = scenes_by_document.get(document_id, [])
        if (
            surface.get("status") == "current"
            and chapter.get("freshness") == "current"
            and chapter_scenes
            and all(scene.get("freshness") == "current" for scene in chapter_scenes)
        ):
            markdown = _ordered_scene_body(content, chapter, chapter_scenes)
        markdown = strip_internal_scene_metadata(markdown)
        prepared.append(
            SceneExportChapter(
                chapter_id=str(chapter.get("chapter_id") or path.stem),
                document_id=document_id,
                occurrence_id=str(chapter.get("occurrence_id") or ""),
                title=_first_heading(markdown) or path.stem,
                path=path,
                markdown=markdown,
            )
        )
    return prepared or None


def build_scene_context(
    project_root: Path,
    novel_id: str,
    chapter_id: str,
) -> dict[str, Any]:
    """Build a revision-labelled scene outline for one writing request.

    Stale and ambiguous scene structures return an explicit exclusion record.
    Callers can expose that record in diagnostics while keeping it out of the
    writing prompt.
    """

    surface = load_scene_surface(project_root, novel_id)
    status = str(surface.get("status") or "ambiguous")
    if status == "absent":
        return {}
    matching = [
        item
        for item in surface.get("chapters") or []
        if isinstance(item, dict) and str(item.get("chapter_id") or "") == chapter_id
    ]
    if len(matching) != 1:
        return _excluded_scene_context(surface, chapter_id, "ambiguous", None)
    chapter = matching[0]
    freshness = str(chapter.get("freshness") or status)
    document_id = str(chapter.get("document_id") or "")
    scenes = [
        item
        for item in surface.get("scenes") or []
        if isinstance(item, dict)
        and isinstance(item.get("chapter"), dict)
        and str(item["chapter"].get("document_id") or "") == document_id
    ]
    if (
        status != "current"
        or freshness != "current"
        or any(str(item.get("freshness") or "") != "current" for item in scenes)
    ):
        effective = "ambiguous" if status == "ambiguous" else "stale"
        return _excluded_scene_context(surface, chapter_id, effective, chapter)

    return {
        "schema_version": SCENE_CONTEXT_SCHEMA_VERSION,
        "status": "current",
        "freshness": "current",
        "scene_structure_revision": str(surface.get("revision") or ""),
        "source_revision": _scene_source_revision(surface, document_id)
        or str(chapter.get("revision") or ""),
        "current_source_revision": str(chapter.get("revision") or ""),
        "chapter": _chapter_locator(chapter),
        "scenes": [
            {
                "scene_id": str(item.get("scene_id") or ""),
                "order": int(item.get("order") or 0),
                "title": str(item.get("title") or ""),
                "story_time": _story_time(item.get("story_time")),
                "references": _references(item.get("references")),
                "source_revision": str((item.get("anchor") or {}).get("source_revision") or ""),
                "freshness": "current",
            }
            for item in sorted(scenes, key=_scene_order_key)
        ],
        "issues": [],
    }


def render_scene_context(value: Any) -> str:
    """Render only current scene context for an agent-facing prompt."""

    if not isinstance(value, dict) or value.get("status") != "current":
        return ""
    parts = [
        f"来源正文版本：{value.get('source_revision') or 'unknown'}",
        f"新鲜度：{value.get('freshness') or 'unknown'}",
    ]
    for scene in value.get("scenes") or []:
        if not isinstance(scene, dict):
            continue
        parts.append(
            f"{int(scene.get('order') or 0) + 1}. "
            f"[{scene.get('scene_id') or '?'}] {scene.get('title') or '未命名场景'}"
        )
        story_time = _story_time(scene.get("story_time"))
        if story_time["label"] or story_time["sort_key"]:
            label = story_time["label"] or story_time["sort_key"]
            parts.append(f"   故事时间：{label}")
        references = _references(scene.get("references"))
        for key, label in (("characters", "人物"), ("locations", "地点"), ("events", "事件")):
            if references[key]:
                parts.append(f"   {label}：{'、'.join(references[key])}")
    return "\n".join(parts)


def strip_internal_scene_metadata(text: str) -> str:
    """Remove OpenWrite-owned scene markers without touching author prose."""

    return _INTERNAL_SCENE_COMMENT_RE.sub("", str(text or ""))


def _ordered_scene_body(
    content: str,
    chapter: dict[str, Any],
    scenes: list[dict[str, Any]],
) -> str:
    ordered = sorted(scenes, key=_scene_order_key)
    body_start = _integer(chapter.get("body_start"), -1)
    if body_start < 0 or body_start > len(content):
        return content
    blocks: list[str] = []
    for scene in ordered:
        anchor = scene.get("anchor") if isinstance(scene.get("anchor"), dict) else {}
        start = _integer(anchor.get("start"), -1)
        end = _integer(anchor.get("end"), -1)
        if start < body_start or end < start or end > len(content):
            return content
        block = content[start:end]
        expected = str(anchor.get("content_sha256") or "")
        if expected:
            import hashlib

            actual = "sha256:" + hashlib.sha256(block.encode("utf-8")).hexdigest()
            if actual != expected:
                return content
        blocks.append(block)
    if not blocks:
        return content
    return content[:body_start] + "".join(blocks)


def _excluded_scene_context(
    surface: dict[str, Any],
    chapter_id: str,
    freshness: str,
    chapter: dict[str, Any] | None,
) -> dict[str, Any]:
    document_id = str((chapter or {}).get("document_id") or "")
    relevant_issues = [
        dict(item)
        for item in surface.get("issues") or []
        if isinstance(item, dict) and str(item.get("chapter_id") or "") in {"", chapter_id}
    ]
    return {
        "schema_version": SCENE_CONTEXT_SCHEMA_VERSION,
        "status": "excluded",
        "freshness": freshness,
        "scene_structure_revision": str(surface.get("revision") or ""),
        "source_revision": _scene_source_revision(surface, document_id),
        "current_source_revision": str((chapter or {}).get("revision") or ""),
        "chapter": _chapter_locator(chapter or {"chapter_id": chapter_id}),
        "scenes": [],
        "issues": relevant_issues,
        "exclusion_reason": "scene_structure_not_current",
    }


def _chapter_locator(chapter: dict[str, Any]) -> dict[str, str]:
    return {
        key: str(chapter.get(key) or "")
        for key in ("chapter_id", "document_id", "occurrence_id", "path")
    }


def _story_time(value: Any) -> dict[str, str]:
    value = value if isinstance(value, dict) else {}
    return {
        "sort_key": str(value.get("sort_key") or ""),
        "label": str(value.get("label") or ""),
    }


def _references(value: Any) -> dict[str, list[str]]:
    value = value if isinstance(value, dict) else {}
    return {
        key: [str(item) for item in value.get(key) or [] if str(item).strip()]
        for key in ("characters", "locations", "events")
    }


def _scene_order_key(item: dict[str, Any]) -> tuple[int, str]:
    return _integer(item.get("order"), 0), str(item.get("scene_id") or "")


def _scene_source_revision(surface: dict[str, Any], document_id: str) -> str:
    revisions = {
        str((item.get("anchor") or {}).get("source_revision") or "")
        for item in surface.get("scenes") or []
        if isinstance(item, dict)
        and isinstance(item.get("chapter"), dict)
        and str(item["chapter"].get("document_id") or "") == document_id
        and str((item.get("anchor") or {}).get("source_revision") or "")
    }
    return next(iter(revisions)) if len(revisions) == 1 else ""


def _integer(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _first_heading(text: str) -> str:
    match = re.search(r"^\s{0,3}#{1,6}\s+(.+?)\s*$", text, re.MULTILINE)
    return match.group(1).strip() if match else ""
