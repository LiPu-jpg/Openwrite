"""Shared chapter length contract for previews, tools and execution."""

from __future__ import annotations

from typing import Any

MIN_TARGET_WORDS = 200
MAX_TARGET_WORDS = 50000
DEFAULT_TARGET_WORDS = 3000


def resolve_target_words(explicit: Any = None, outline: Any = None) -> dict[str, Any]:
    value, source = (
        (explicit, "explicit")
        if explicit is not None
        else ((outline, "outline") if outline else (DEFAULT_TARGET_WORDS, "default"))
    )
    if isinstance(value, bool) or isinstance(value, float) and not value.is_integer():
        raise ValueError("target_words must be an integer")
    parsed = int(value)
    if not MIN_TARGET_WORDS <= parsed <= MAX_TARGET_WORDS:
        raise ValueError(f"target_words must be between {MIN_TARGET_WORDS} and {MAX_TARGET_WORDS}")
    return {
        "target_words": parsed,
        "target_words_source": source,
        "minimum_words": int(parsed * 0.8),
        "maximum_words": int(parsed * 1.5),
    }
