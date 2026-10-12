"""Project-level writing and outline length targets."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

DEFAULT_WRITING_TARGETS: dict[str, int] = {
    "book_words": 100_000,
    "chapter_words": 3_000,
    "outline_volume_words": 800,
    "outline_act_words": 500,
    "outline_section_words": 300,
    "outline_chapter_words": 180,
}

WRITING_TARGET_LIMITS: dict[str, tuple[int, int]] = {
    "book_words": (10_000, 5_000_000),
    "chapter_words": (200, 50_000),
    "outline_volume_words": (100, 5_000),
    "outline_act_words": (80, 3_000),
    "outline_section_words": (50, 2_000),
    "outline_chapter_words": (30, 1_000),
}

WRITING_TARGET_LABELS = {
    "book_words": "全书目标字数",
    "chapter_words": "每章正文默认",
    "outline_volume_words": "每卷大纲目标",
    "outline_act_words": "每幕大纲目标",
    "outline_section_words": "每节大纲目标",
    "outline_chapter_words": "每个章纲目标",
}


def normalize_writing_targets(
    value: Any,
    *,
    base: Mapping[str, Any] | None = None,
    strict: bool = False,
) -> dict[str, int]:
    """Return a complete, bounded writing-target mapping.

    Stored projects may omit this block, so reads fall back to stable defaults.
    Studio saves use ``strict=True`` to reject invalid values instead of silently
    changing an author's requested target.
    """
    source = value if isinstance(value, Mapping) else {}
    baseline = base if isinstance(base, Mapping) else DEFAULT_WRITING_TARGETS
    result: dict[str, int] = {}
    for key, fallback in DEFAULT_WRITING_TARGETS.items():
        label = WRITING_TARGET_LABELS[key]
        raw = source.get(key, baseline.get(key, fallback))
        minimum, maximum = WRITING_TARGET_LIMITS[key]
        try:
            parsed = int(raw)
        except (TypeError, ValueError):
            if strict:
                raise ValueError(f"{label}必须是整数") from None
            parsed = int(baseline.get(key, fallback))
        if not minimum <= parsed <= maximum:
            if strict:
                raise ValueError(f"{label}必须在 {minimum} 到 {maximum} 之间")
            parsed = int(baseline.get(key, fallback))
            parsed = max(minimum, min(maximum, parsed))
        result[key] = parsed
    return result


def outline_prompt_constraints(targets: Mapping[str, Any]) -> str:
    values = normalize_writing_targets(targets)
    return "\n".join(
        [
            "字数规划：",
            f"- 全书正文目标约 {values['book_words']} 字",
            (
                f"- 每章正文默认目标 {values['chapter_words']} 字；"
                f"每个章节点必须写 `> 预估字数: {values['chapter_words']}`"
            ),
            f"- 每卷节点说明约 {values['outline_volume_words']} 字",
            f"- 每幕节点说明约 {values['outline_act_words']} 字",
            f"- 每节节点说明约 {values['outline_section_words']} 字",
            f"- 每个章纲说明约 {values['outline_chapter_words']} 字",
            "这些是详略目标，允许为内容完整小幅浮动，但不能省略层级或用空泛套话凑字数。",
        ]
    )
