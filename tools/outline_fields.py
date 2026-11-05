"""Chapter metadata fields: the contract label, its legacy spellings, and its value kind.

`src/outline.md` carries chapter facts as `> 键: 值` lines. The key is the
contract label, and the parser reads exactly that label — so a writer that
uses a different spelling either loses the value or leaves the same field on
two lines at once. This module is the single registry that the structured
writer and the parser both use, so the two can never drift apart again.

The field names are the ones the tools speak (`target_words`, `characters`,
`settings`), while the labels are the ones the file speaks (`预估字数`,
`出场角色`, `涉及设定`). See `models/outline.py` for the parsed value kinds and
`tools/outline_contract.py` for the writer-facing contract.
"""

from __future__ import annotations

import re

# Semantic field -> the contract label the parser reads.
CHAPTER_FIELD_LABELS: dict[str, str] = {
    "dramatic_position": "戏剧位置",
    "content_focus": "内容焦点",
    "goals": "本章目标",
    "target_words": "预估字数",
    "word_budget": "字数预算",
    "characters": "出场角色",
    "settings": "涉及设定",
    "emotional_arc": "情感弧线",
    "beats": "节拍",
    "hooks": "悬念",
    "promise": "章节承诺",
    "payoff_of": "回收伏笔",
    "function": "章节功能",
}

# Labels an outline written before the contract rename may still carry.
# Reading accepts them; writing replaces them with the contract label instead
# of leaving the same field on a second line.
CHAPTER_FIELD_LEGACY_LABELS: dict[str, tuple[str, ...]] = {
    "characters": ("涉及人物",),
}

# Input spellings an agent may use for the same semantic field.
CHAPTER_FIELD_INPUT_ALIASES: dict[str, str] = {
    "estimated_words": "target_words",
    "involved_characters": "characters",
    "involved_settings": "settings",
}

# Fields whose contract value is a list of items (see models/outline.py).
# These are the fields that are read back as a merged, de-duplicated list.
CHAPTER_LIST_FIELDS = frozenset(
    {
        "goals",
        "beats",
        "hooks",
        "characters",
        "settings",
        "payoff_of",
        "function",
    }
)

# Fields that additionally accept an array on the way in and join it.
# `promise` is a plain string in the model, but a caller that hands over an
# array of fragments means the same thing, so it is joined on the way in - and
# read back as the untouched string it was written as. Splitting a string
# field on commas and rejoining it would rewrite the file's bytes.
CHAPTER_ARRAY_INPUT_FIELDS = CHAPTER_LIST_FIELDS | {"promise"}

# Fields whose contract value is an integer word count.
CHAPTER_WORD_FIELDS = frozenset({"target_words", "word_budget"})


def chapter_field_labels(key: str) -> tuple[str, ...]:
    """Every label that may carry one semantic field, contract label first."""
    return (CHAPTER_FIELD_LABELS[key], *CHAPTER_FIELD_LEGACY_LABELS.get(key, ()))


def chapter_field_for_label(label: str) -> str | None:
    """The semantic field a `> 键:` line carries, under the contract or a legacy label."""
    text = str(label or "").strip()
    for key in CHAPTER_FIELD_LABELS:
        if text in chapter_field_labels(key):
            return key
    return None


def chapter_field_pattern(key: str) -> re.Pattern[str]:
    """Match the `> 键: 值` line of one semantic field, under any accepted label."""
    labels = "|".join(re.escape(label) for label in chapter_field_labels(key))
    return re.compile(rf"^>\s*(?:{labels})\s*[:：]\s*(.*?)\s*$", re.M)


def split_field_items(value: str) -> list[str]:
    """Split one metadata value into its items, keeping order and dropping repeats."""
    items: list[str] = []
    for part in re.split(r"[,，、]", value):
        part = part.strip()
        if part and part not in items:
            items.append(part)
    return items


def merge_field_items(values: list[str]) -> list[str]:
    """Merge the items of several lines that carry the same field."""
    items: list[str] = []
    for value in values:
        for item in split_field_items(value):
            if item not in items:
                items.append(item)
    return items
