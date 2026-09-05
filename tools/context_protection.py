"""Shared hard-constraint protection for writing context assembly."""

from __future__ import annotations

import hashlib
from typing import Any, Mapping

from models.token_estimation import estimate_text_tokens

PROTECTION_REASONS: dict[str, str] = {
    "system_prompts": "framework_execution_contract",
    "author_intent": "author_hard_constraint",
    "creative_focus": "author_hard_constraint",
    "core_documents": "critical_canon",
    "story_background": "critical_canon",
    "current_state": "critical_canon",
    "ledger": "critical_canon",
    "relationships": "critical_canon",
    "continuity_documents": "critical_canon",
    "world_rules_constraints": "critical_canon",
    "chapter_requirements": "chapter_required_condition",
    "scene_context": "chapter_required_condition",
}

PROTECTED_SOURCE_PATHS: dict[str, tuple[str, ...]] = {
    "author_intent": ("src/story/author_intent.md",),
    "creative_focus": ("src/story/current_focus.md",),
    "core_documents": ("src/story/background.md", "src/story/foundation.md"),
    "story_background": ("src/story/background.md",),
    "current_state": ("data/world/current_state.md",),
    "ledger": ("data/world/ledger.md",),
    "relationships": ("data/world/relationships.md",),
    "continuity_documents": (
        "data/world/current_state.md",
        "data/world/ledger.md",
        "data/world/relationships.md",
    ),
    "world_rules_constraints": ("src/world/",),
    "chapter_requirements": ("src/outline.md",),
    "scene_context": ("data/story_structure/scenes.json",),
}


class ContextBudgetError(RuntimeError):
    """Raised when immutable writing constraints cannot fit the request budget."""

    code = "PROTECTED_CONTEXT_OVER_BUDGET"

    def __init__(
        self,
        *,
        budget_tokens: int,
        required_tokens: int,
        protected_items: Mapping[str, Any],
    ) -> None:
        names = [name for name, value in protected_items.items() if _has_content(value)]
        self.details = {
            "budget_tokens": int(budget_tokens),
            "required_tokens": int(required_tokens),
            "over_by_tokens": max(0, int(required_tokens) - int(budget_tokens)),
            "protected_items": names,
            "source_paths": list(
                dict.fromkeys(
                    path
                    for name in names
                    for path in PROTECTED_SOURCE_PATHS.get(name, ())
                )
            ),
            "adjustments": [
                "increase_the_writing_request_context_budget",
                "edit_the_named_source_documents_to_remove_obsolete_constraints",
                "split_the_chapter_request_without_removing_required_conditions",
            ],
        }
        super().__init__(
            "受保护的作者约束、关键正典或本章必需条件已超过写章请求预算；"
            "请提高该请求的上下文预算，或回到列出的来源精简过期约束。"
        )


def render_context_value(value: Any) -> str:
    """Render structured context deterministically for accounting and hashing."""

    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    if isinstance(value, Mapping):
        return "\n".join(
            f"{key}: {render_context_value(item)}"
            for key, item in value.items()
            if _has_content(item)
        )
    if isinstance(value, (list, tuple, set)):
        return "\n".join(
            rendered
            for item in value
            if (rendered := render_context_value(item)).strip()
        )
    return str(value)


def generation_protected_items(context: Any) -> dict[str, Any]:
    """Return the immutable subset of a ``GenerationContext``."""

    current_chapter = getattr(context, "current_chapter", None)
    chapter_requirements: dict[str, Any] = {
        "chapter_id": getattr(context, "chapter_id", ""),
        "goals": getattr(context, "chapter_goals", []),
        "dramatic_context": getattr(context, "dramatic_context", {}),
        "emotion_arc": getattr(context, "emotion_arc", ""),
    }
    if current_chapter is not None:
        chapter_requirements["outline"] = _chapter_requirements(current_chapter)
    world_rules = getattr(context, "world_rules", None)
    scene_context = getattr(context, "scene_context", {})
    if not isinstance(scene_context, Mapping) or scene_context.get("status") != "current":
        scene_context = {}
    return _nonempty(
        {
            "author_intent": getattr(context, "author_intent", ""),
            "creative_focus": getattr(context, "creative_focus", ""),
            "core_documents": getattr(context, "core_documents", {}),
            "current_state": getattr(context, "current_state", ""),
            "ledger": getattr(context, "ledger", ""),
            "relationships": getattr(context, "relationships", ""),
            "world_rules_constraints": getattr(world_rules, "constraints", []),
            "chapter_requirements": chapter_requirements,
            "scene_context": scene_context,
        }
    )


def packet_protected_items(packet: Any) -> dict[str, Any]:
    """Return the immutable subset of a ``ChapterAssemblyPacket``."""

    def get(name: str, default: Any) -> Any:
        if isinstance(packet, Mapping):
            return packet.get(name, default)
        return getattr(packet, name, default)

    core = get("core_documents", {}) or {}
    continuity = get("continuity_documents", {}) or {
        "current_state": get("current_state", ""),
        "ledger": get("ledger", ""),
        "relationships": get("relationships", ""),
    }
    values = {
        "system_prompts": get("system_prompts", {}),
        "author_intent": get("author_intent", ""),
        "creative_focus": get("creative_focus", ""),
        "core_documents": core,
        "continuity_documents": continuity,
        "chapter_requirements": get("chapter_requirements", {}),
    }
    if not core:
        values["story_background"] = get("story_background", "")
    return _nonempty(values)


def protected_token_count(items: Mapping[str, Any]) -> int:
    return sum(estimate_text_tokens(render_context_value(value)) for value in items.values())


def protected_snapshot(items: Mapping[str, Any]) -> dict[str, str]:
    return {
        name: hashlib.sha256(render_context_value(value).encode("utf-8")).hexdigest()
        for name, value in items.items()
    }


def ensure_protected_fits(items: Mapping[str, Any], budget_tokens: int) -> int:
    required = protected_token_count(items)
    if required > budget_tokens:
        raise ContextBudgetError(
            budget_tokens=budget_tokens,
            required_tokens=required,
            protected_items=items,
        )
    return required


def assert_protected_unchanged(
    before: Mapping[str, str],
    after_items: Mapping[str, Any],
) -> None:
    after = protected_snapshot(after_items)
    if dict(before) != after:
        changed = sorted(set(before) | set(after))
        raise RuntimeError(f"Protected context changed during assembly: {', '.join(changed)}")


def protection_reason(section: str) -> str:
    return PROTECTION_REASONS.get(section, "")


def _chapter_requirements(chapter: Any) -> dict[str, Any]:
    return _nonempty(
        {
            "node_id": getattr(chapter, "node_id", ""),
            "title": getattr(chapter, "title", ""),
            "summary": getattr(chapter, "summary", ""),
            "dramatic_position": getattr(chapter, "dramatic_position", ""),
            "content_focus": getattr(chapter, "content_focus", ""),
            "goals": getattr(chapter, "goals", []),
            "beats": getattr(chapter, "beats", []),
            "hooks": getattr(chapter, "hooks", []),
            "emotional_arc": getattr(chapter, "emotional_arc", ""),
        }
    )


def chapter_requirements(chapter: Any) -> dict[str, Any]:
    """Public serializer for the current chapter's non-negotiable conditions."""

    return _chapter_requirements(chapter)


def _nonempty(values: Mapping[str, Any]) -> dict[str, Any]:
    return {name: value for name, value in values.items() if _has_content(value)}


def _has_content(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, Mapping):
        return any(_has_content(item) for item in value.values())
    if isinstance(value, (list, tuple, set)):
        return any(_has_content(item) for item in value)
    return bool(value)
