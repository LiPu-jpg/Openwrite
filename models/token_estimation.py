"""Shared, provider-agnostic token estimates and measurement metadata."""

from __future__ import annotations

from typing import Any

TOKEN_ESTIMATOR_ID = "mixed-script-conservative-v1"


def estimate_text_tokens(text: str) -> int:
    """Conservatively estimate tokens for mixed Chinese and Latin text.

    This is deliberately an estimate rather than a provider tokenizer result.
    Chinese characters are weighted at 1.5 tokens and other characters at
    0.25 tokens. Every non-empty rendered value costs at least one token.
    """

    if not text:
        return 0
    chinese_chars = sum(1 for char in text if "\u4e00" <= char <= "\u9fff")
    other_chars = len(text) - chinese_chars
    return max(1, int(chinese_chars * 1.5 + other_chars * 0.25))


def estimate_measurement(
    *, text_scope: str, includes_wrapper_overhead: bool
) -> dict[str, Any]:
    """Return stable metadata describing what an estimate measures."""

    return {
        "kind": "estimate",
        "estimator": TOKEN_ESTIMATOR_ID,
        "text_scope": text_scope,
        "includes_wrapper_overhead": includes_wrapper_overhead,
    }


def unknown_actual_usage() -> dict[str, Any]:
    """Represent unavailable provider usage without conflating it with zero."""

    return {
        "reported": False,
        "prompt_tokens": None,
        "total_tokens": None,
    }
