"""Shared serialization helpers for outline runtime cache."""

from __future__ import annotations

from typing import Any

from models.outline import OutlineHierarchy, OutlineNode, OutlineNodeType


def serialize_outline_hierarchy(hierarchy: OutlineHierarchy) -> dict[str, Any]:
    """Serialize canonical outline hierarchy into runtime cache shape."""

    data: dict[str, Any] = {}
    master = hierarchy.master
    if master:
        story_info: dict[str, Any] = {"title": master.title}
        if master.core_theme:
            story_info["theme"] = master.core_theme
        if master.summary:
            story_info["summary"] = master.summary
        if master.word_count_target:
            story_info["word_count_estimate"] = master.word_count_target
        if master.world_premise:
            story_info["world_premise"] = master.world_premise
        if master.ending_direction:
            story_info["ending_direction"] = master.ending_direction
        if master.tone:
            story_info["tone"] = master.tone
        if master.key_turns:
            story_info["key_turns"] = list(master.key_turns)
        data["story_info"] = story_info

    arcs: list[dict[str, Any]] = []
    for arc in hierarchy.arcs:
        chapters = hierarchy.get_chapters_by_arc(arc.node_id)
        chapter_ids = [chapter.node_id for chapter in chapters]
        entry: dict[str, Any] = {
            "id": arc.node_id,
            "title": arc.title,
            "sections": list(arc.children_ids),
            "chapters": chapter_ids,
        }
        if arc.summary:
            entry["summary"] = arc.summary
        if arc.arc_theme:
            entry["theme"] = arc.arc_theme
        chapter_range = arc.chapter_range or _format_chapter_range(chapter_ids)
        if chapter_range:
            entry["description"] = chapter_range
        arcs.append(entry)
    if arcs:
        data["arcs"] = arcs

    sections: list[dict[str, Any]] = []
    for section in hierarchy.sections:
        entry = {
            "id": section.node_id,
            "title": section.title,
            "arc_id": section.parent_id or "",
            "chapters": list(section.children_ids),
        }
        if section.summary:
            entry["summary"] = section.summary
        if section.purpose:
            entry["purpose"] = section.purpose
        if section.involved_characters:
            entry["involved_characters"] = list(section.involved_characters)
        sections.append(entry)
    if sections:
        data["sections"] = sections

    chapters: list[dict[str, Any]] = []
    for chapter in hierarchy.chapters:
        summary = chapter.summary or chapter.content_focus
        entry = {
            "id": chapter.node_id,
            "title": chapter.title,
            "section_id": chapter.parent_id or "",
        }
        if summary:
            entry["summary"] = summary
        if chapter.dramatic_position:
            entry["dramatic_position"] = chapter.dramatic_position
        if chapter.content_focus:
            entry["content_focus"] = chapter.content_focus
        word_count = chapter.estimated_words or chapter.word_count_target
        if word_count:
            entry["word_count"] = word_count
        if chapter.goals:
            entry["goals"] = list(chapter.goals)
        if chapter.status:
            entry["status"] = chapter.status
        if chapter.involved_characters:
            entry["involved_characters"] = list(chapter.involved_characters)
        if chapter.involved_settings:
            entry["involved_settings"] = list(chapter.involved_settings)
        if chapter.emotional_arc:
            entry["emotional_arc"] = chapter.emotional_arc
        if chapter.beats:
            entry["beats"] = list(chapter.beats)
        if chapter.hooks:
            entry["hooks"] = list(chapter.hooks)
        chapters.append(entry)
    if chapters:
        data["chapters"] = chapters

    return data


def deserialize_outline_hierarchy(data: dict[str, Any], novel_id: str) -> OutlineHierarchy:
    """Deserialize runtime cache data back into canonical outline hierarchy."""

    hierarchy = OutlineHierarchy(novel_id=novel_id)

    story_info = data.get("story_info", {})
    if story_info:
        hierarchy.master = OutlineNode(
            node_id="master",
            node_type=OutlineNodeType.MASTER,
            title=story_info.get("title", ""),
            summary=story_info.get("summary", ""),
            core_theme=story_info.get("theme", story_info.get("core_theme", "")),
            ending_direction=story_info.get("ending_direction", ""),
            world_premise=story_info.get("world_premise", ""),
            tone=story_info.get("tone", ""),
            key_turns=list(story_info.get("key_turns", [])),
            word_count_target=_to_int(story_info.get("word_count_estimate", 0)),
        )

    for arc in data.get("arcs", []):
        section_ids = [str(item).strip() for item in arc.get("sections", []) if str(item).strip()]
        chapter_ids = [str(item).strip() for item in arc.get("chapters", []) if str(item).strip()]
        hierarchy.arcs.append(
            OutlineNode(
                node_id=arc.get("id", ""),
                node_type=OutlineNodeType.ARC,
                title=arc.get("title", ""),
                summary=arc.get("summary", ""),
                parent_id=arc.get("parent_id") or "master",
                children_ids=section_ids or chapter_ids,
                arc_theme=arc.get("theme", ""),
                chapter_range=arc.get("description", arc.get("chapter_range", "")),
            )
        )

    for section in data.get("sections", []):
        hierarchy.sections.append(
            OutlineNode(
                node_id=section.get("id", ""),
                node_type=OutlineNodeType.SECTION,
                title=section.get("title", ""),
                summary=section.get("summary", ""),
                parent_id=section.get("arc_id", section.get("parent_id", "")),
                children_ids=[
                    str(item).strip() for item in section.get("chapters", []) if str(item).strip()
                ],
                purpose=section.get("purpose", ""),
                involved_characters=list(section.get("involved_characters", [])),
            )
        )

    for chapter in data.get("chapters", []):
        estimated_words = _to_int(chapter.get("word_count", chapter.get("estimated_words", 0)))
        summary = chapter.get("summary", "")
        hierarchy.chapters.append(
            OutlineNode(
                node_id=chapter.get("id", ""),
                node_type=OutlineNodeType.CHAPTER,
                title=chapter.get("title", ""),
                summary=summary,
                parent_id=chapter.get("section_id", chapter.get("parent_id", "")),
                dramatic_position=chapter.get("dramatic_position", ""),
                content_focus=chapter.get("content_focus", summary),
                goals=list(chapter.get("goals", [])),
                status=chapter.get("status", ""),
                involved_characters=list(chapter.get("involved_characters", [])),
                involved_settings=list(chapter.get("involved_settings", [])),
                estimated_words=estimated_words,
                word_count_target=estimated_words,
                emotional_arc=chapter.get("emotional_arc", ""),
                beats=list(chapter.get("beats", [])),
                hooks=list(chapter.get("hooks", [])),
            )
        )

    return hierarchy


def _format_chapter_range(chapter_ids: list[str]) -> str:
    if not chapter_ids:
        return ""
    return chapter_ids[0] if len(chapter_ids) == 1 else f"{chapter_ids[0]} - {chapter_ids[-1]}"


def _to_int(value: Any) -> int:
    try:
        return int(value)
    except Exception:
        return 0
