"""Traceable manifest for assembled writing context."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from models.token_estimation import (
    estimate_measurement,
    estimate_text_tokens,
    unknown_actual_usage,
)
from tools.context_protection import protection_reason, render_context_value

SECTION_SOURCES: dict[str, tuple[int, list[str]]] = {
    "author_intent": (3, ["src/story/author_intent.md"]),
    "creative_focus": (1, ["src/story/current_focus.md"]),
    "story_background": (3, ["src/story/background.md", "src/story/foundation.md"]),
    "core_documents": (3, ["src/story/background.md", "src/story/foundation.md"]),
    "historical_arc_summaries": (4, ["src/outline.md"]),
    "current_arc_sections": (2, ["src/outline.md"]),
    "chapter_requirements": (0, ["src/outline.md"]),
    "scene_context": (0, ["data/story_structure/scenes.json"]),
    "previous_chapter_content": (0, ["data/manuscript/"]),
    "character_states": (1, ["data/manuscript/", "src/outline.md"]),
    "semantic_references": (4, ["data/manuscript/", "data/sources/"]),
    "protagonist_state": (1, ["data/world/current_state.md"]),
    "current_state": (3, ["data/world/current_state.md"]),
    "ledger": (3, ["data/world/ledger.md"]),
    "relationships": (3, ["data/world/relationships.md"]),
    "character_documents": (2, ["src/characters/"]),
    "concept_documents": (2, ["src/world/"]),
    "setting_documents": (2, ["src/world/", "src/progression/"]),
    "continuity_documents": (
        3,
        ["data/world/", "data/foreshadowing/"],
    ),
    "style_documents": (3, ["data/style/", "craft/"]),
}

SELECTION_REASONS: dict[str, str] = {
    "author_intent": "book_level_author_direction",
    "creative_focus": "active_author_focus",
    "core_documents": "book_level_canon",
    "story_background": "book_level_canon",
    "chapter_requirements": "target_chapter_outline",
    "scene_context": "current_revision_scene_outline",
    "historical_arc_summaries": "long_range_continuity",
    "current_arc_sections": "target_arc_structure",
    "previous_chapter_content": "immediate_prose_continuity",
    "character_states": "target_chapter_mentions_and_runtime_state",
    "semantic_references": "semantic_retrieval_for_distant_relevance",
    "protagonist_state": "target_chapter_character_state",
    "current_state": "runtime_canon",
    "ledger": "runtime_canon",
    "relationships": "runtime_canon",
    "continuity_documents": "runtime_canon",
    "character_documents": "characters_named_by_target_chapter",
    "concept_documents": "concepts_named_by_target_chapter",
    "setting_documents": "settings_named_by_target_chapter",
    "style_documents": "active_style_stack",
}

EXPECTED_SECTIONS = (
    "author_intent",
    "creative_focus",
    "core_documents",
    "chapter_requirements",
)

CANONICAL_SECTION_ALIASES: dict[str, tuple[str, ...]] = {
    "core_documents": ("story_background",),
    "setting_documents": ("concept_documents",),
    "continuity_documents": ("current_state", "ledger", "relationships"),
}


def build_context_manifest(novel_root: Path, packet: dict[str, Any]) -> dict[str, Any]:
    """Describe context layers, provenance, size and stable revisions."""
    root = Path(novel_root).resolve()
    items: list[dict[str, Any]] = []
    suppressed_aliases = {
        alias
        for canonical, aliases in CANONICAL_SECTION_ALIASES.items()
        if _render(packet.get(canonical)).strip()
        for alias in aliases
    }
    for section, (level, sources) in SECTION_SOURCES.items():
        if section in suppressed_aliases:
            continue
        value = packet.get(section)
        if (
            section == "scene_context"
            and isinstance(value, dict)
            and value.get("status") != "current"
        ):
            continue
        rendered = render_context_value(value)
        if not rendered.strip():
            continue
        resolved = _resolve_sources(root, sources)
        compression = _section_compression(packet.get("compression"), section)
        reason = protection_reason(section)
        item = {
                "section": section,
                "level": level,
                "characters": len(rendered),
                "estimated_tokens": estimate_text_tokens(rendered),
                "measurement": estimate_measurement(
                    text_scope="rendered_section_value",
                    includes_wrapper_overhead=False,
                ),
                "sources": resolved,
                "revision": hashlib.sha256(rendered.encode("utf-8")).hexdigest()[:16],
                "snippet": _snippet(rendered),
                "selection_reason": SELECTION_REASONS.get(
                    section, "available_in_assembled_packet"
                ),
                "status": compression["status"],
                "compression_reason": compression["reason"],
                "protected": bool(reason),
                "protection_reason": reason,
            }
        if section == "scene_context" and isinstance(value, dict):
            item["freshness"] = str(value.get("freshness") or "unknown")
            item["source_revision"] = str(value.get("source_revision") or "")
            item["current_source_revision"] = str(
                value.get("current_source_revision") or ""
            )
            item["scene_structure_revision"] = str(
                value.get("scene_structure_revision") or ""
            )
        items.append(item)
    revision_seed = "\n".join(
        f"{item['section']}:{item['revision']}" for item in items
    )
    section_estimated_tokens = sum(int(item["estimated_tokens"]) for item in items)
    compression_report = (
        dict(packet.get("compression") or {})
        if isinstance(packet.get("compression"), dict)
        else {}
    )
    source_seed = "\n".join(
        f"{source['path']}:{source['revision']}"
        for item in items
        for source in item["sources"]
    )
    missing_items = _missing_items(root, packet, suppressed_aliases)
    dropped = [
        {
            "section": _compression_label_section(str(label)),
            "label": str(label),
            "status": "excluded",
            "reason": "input_budget",
        }
        for label in compression_report.get("dropped_documents", [])
    ]
    scene_context = packet.get("scene_context")
    if (
        isinstance(scene_context, dict)
        and scene_context
        and scene_context.get("status") != "current"
    ):
        dropped.append(
            {
                "section": "scene_context",
                "status": "excluded",
                "reason": str(
                    scene_context.get("exclusion_reason")
                    or "scene_structure_not_current"
                ),
                "freshness": str(scene_context.get("freshness") or "unknown"),
                "source_revision": str(scene_context.get("source_revision") or ""),
                "current_source_revision": str(
                    scene_context.get("current_source_revision") or ""
                ),
                "scene_structure_revision": str(
                    scene_context.get("scene_structure_revision") or ""
                ),
            }
        )
    manifest = {
        "schema_version": 2,
        "strategy": "hierarchical-provenance-v1",
        "revision": hashlib.sha256(revision_seed.encode("utf-8")).hexdigest()[:16],
        "packet_revision": hashlib.sha256(revision_seed.encode("utf-8")).hexdigest()[:16],
        "source_revision": hashlib.sha256(source_seed.encode("utf-8")).hexdigest()[:16],
        "measurement": estimate_measurement(
            text_scope="rendered_section_values",
            includes_wrapper_overhead=False,
        ),
        "estimated_tokens": section_estimated_tokens,
        "section_estimated_tokens": section_estimated_tokens,
        # A manifest describes source values before an agent-specific prompt
        # wraps them. Unknown wrapper/provider usage must remain unknown, not 0.
        "wrapper_estimated_tokens": None,
        "actual_usage": unknown_actual_usage(),
        "request_budget": _request_budget(compression_report),
        "session_budget": {
            "scope": "dsh_session",
            "available": False,
            "reason": "not_reported_by_session_runtime",
        },
        "compression": compression_report,
        "excluded_items": dropped,
        "missing_items": missing_items,
        "items": items,
    }
    manifest["freshness"] = check_context_manifest_freshness(root, manifest)
    return manifest


def check_context_manifest_freshness(
    novel_root: Path, manifest: dict[str, Any]
) -> dict[str, Any]:
    """Compare a previously assembled manifest with its current source files."""

    root = Path(novel_root).resolve()
    changed: list[str] = []
    for item in manifest.get("items", []):
        if not isinstance(item, dict):
            continue
        for source in item.get("sources", []):
            if not isinstance(source, dict):
                continue
            relative = str(source.get("path") or "")
            if not relative:
                continue
            current = _resolve_sources(root, [relative])[0]
            if (
                current.get("revision") != source.get("revision")
                or current.get("exists") != source.get("exists")
            ):
                changed.append(relative)
    unique = list(dict.fromkeys(changed))
    return {
        "status": "stale" if unique else "current",
        "reason": "source_revision_changed" if unique else "assembled_from_current_sources",
        "changed_sources": unique,
    }


def _render(value: Any) -> str:
    return render_context_value(value)


def _resolve_sources(root: Path, sources: list[str]) -> list[dict[str, Any]]:
    resolved: list[dict[str, Any]] = []
    for relative in sources:
        path = root / relative
        if relative.endswith("/"):
            exists = path.is_dir()
            revision = _directory_revision(path) if exists else "missing"
        else:
            exists = path.is_file()
            revision = _file_revision(path) if exists else "missing"
        resolved.append({"path": relative, "exists": exists, "revision": revision})
    return resolved


def _file_revision(path: Path) -> str:
    try:
        content = path.read_bytes()
    except OSError:
        return "unreadable"
    return hashlib.sha256(content).hexdigest()[:16]


def _directory_revision(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        files = sorted(item for item in path.rglob("*") if item.is_file())
    except OSError:
        return "unreadable"
    for item in files:
        try:
            relative = item.relative_to(path).as_posix()
            digest.update(relative.encode("utf-8"))
            digest.update(item.read_bytes())
        except OSError:
            return "unreadable"
    return digest.hexdigest()[:16]


def _snippet(text: str, limit: int = 180) -> str:
    compact = " ".join(text.split())
    return compact if len(compact) <= limit else compact[: limit - 1] + "…"


def _request_budget(compression: dict[str, Any]) -> dict[str, Any]:
    budget = int(compression.get("budget_tokens") or 0)
    return {
        "scope": "openwrite_writing_request",
        "available": budget > 0,
        "input_budget_tokens": budget or None,
        "context_window_tokens": compression.get("context_window_tokens"),
        "reserved_output_tokens": compression.get("reserved_output_tokens"),
        "safety_tokens": compression.get("safety_tokens"),
        "estimated_tokens": compression.get("final_estimated_tokens"),
        "actual_usage": compression.get("actual_usage", unknown_actual_usage()),
    }


def _missing_items(
    root: Path,
    packet: dict[str, Any],
    suppressed_aliases: set[str],
) -> list[dict[str, Any]]:
    missing: list[dict[str, Any]] = []
    for section in EXPECTED_SECTIONS:
        aliases = CANONICAL_SECTION_ALIASES.get(section, ())
        if any(render_context_value(packet.get(alias)).strip() for alias in aliases):
            continue
        if section in suppressed_aliases or render_context_value(packet.get(section)).strip():
            continue
        _level, sources = SECTION_SOURCES[section]
        reason = protection_reason(section)
        missing.append(
            {
                "section": section,
                "status": "missing",
                "reason": "source_missing_or_empty",
                "sources": _resolve_sources(root, sources),
                "protected": bool(reason),
                "protection_reason": reason,
            }
        )
    return missing


def _section_compression(value: Any, section: str) -> dict[str, str]:
    report = value if isinstance(value, dict) else {}
    truncated = [str(item) for item in report.get("truncated_documents", [])]
    prefixes = {
        "historical_arc_summaries": ("outline:arc",),
        "current_arc_sections": ("outline:section",),
        "previous_chapter_content": ("recent:previous_chapter",),
        "protagonist_state": ("continuity:protagonist_state",),
        "character_documents": ("character:",),
        "setting_documents": ("setting:",),
        "style_documents": ("style:",),
    }.get(section, (section,))
    if any(label.startswith(prefix) for label in truncated for prefix in prefixes):
        return {"status": "compressed", "reason": "input_budget"}
    return {"status": "selected", "reason": ""}


def _compression_label_section(label: str) -> str:
    prefix = label.split(":", 1)[0]
    return {
        "outline": "outline",
        "recent": "previous_chapter_content",
        "continuity": "continuity_documents",
        "character": "character_documents",
        "setting": "setting_documents",
        "style": "style_documents",
    }.get(prefix, prefix)
