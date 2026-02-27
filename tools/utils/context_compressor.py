"""Context compressor — priority-based context budget allocation for agent prompts.

Provides intelligent compression of multi-section context dictionaries so that
the total prompt stays within a character budget while preserving the most
important information.

Features:
  - Priority-weighted budget allocation across sections
  - Sentence-boundary truncation (no mid-sentence cuts)
  - Redundancy removal (dedup repeated phrases across sections)
  - Configurable section priorities and minimum guarantees
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple


# Default section priorities (higher = more budget share)
DEFAULT_PRIORITIES: Dict[str, int] = {
    "outline": 10,
    "characters": 9,
    "foreshadowing": 8,
    "scenes": 7,
    "world": 6,
    "cross_chapter": 8,
    "seed": 5,
    "summary": 4,
}

# Minimum chars guaranteed per section (even low-priority sections get this)
MIN_SECTION_CHARS = 40


@dataclass
class CompressionResult:
    """Result of context compression."""

    sections: Dict[str, str]
    total_chars: int
    budget: int
    sections_truncated: List[str] = field(default_factory=list)
    redundancies_removed: int = 0

    def to_flat(self, separator: str = "; ") -> str:
        """Flatten all sections into a single string."""
        parts = []
        for key, value in self.sections.items():
            if value.strip():
                parts.append(f"{key}:{value}")
        return separator.join(parts)


class ContextCompressor:
    """Compresses multi-section context to fit within a character budget."""

    def __init__(
        self,
        budget: int = 2000,
        priorities: Optional[Dict[str, int]] = None,
        min_section_chars: int = MIN_SECTION_CHARS,
    ):
        self.budget = budget
        self.priorities = priorities or dict(DEFAULT_PRIORITIES)
        self.min_section_chars = min_section_chars

    def compress(
        self,
        context: Dict[str, str],
        budget: Optional[int] = None,
    ) -> CompressionResult:
        """Compress a context dictionary to fit within the budget.

        Args:
            context: Section name -> content mapping.
            budget: Override the default budget for this call.
        """
        effective_budget = budget or self.budget

        # Step 1: Remove redundancies across sections
        cleaned, redundancies = self._remove_redundancies(context)

        # Step 2: Allocate budget per section based on priority
        allocations = self._allocate_budget(cleaned, effective_budget)

        # Step 3: Truncate each section to its allocation
        compressed: Dict[str, str] = {}
        truncated: List[str] = []
        for key, content in cleaned.items():
            alloc = allocations.get(key, self.min_section_chars)
            if len(content) <= alloc:
                compressed[key] = content
            else:
                compressed[key] = self._truncate_at_boundary(content, alloc)
                truncated.append(key)

        total = sum(len(v) for v in compressed.values())
        return CompressionResult(
            sections=compressed,
            total_chars=total,
            budget=effective_budget,
            sections_truncated=truncated,
            redundancies_removed=redundancies,
        )

    def _allocate_budget(self, context: Dict[str, str], budget: int) -> Dict[str, int]:
        """Allocate character budget across sections by priority weight."""
        if not context:
            return {}

        # Calculate priority weights
        weights: Dict[str, int] = {}
        for key in context:
            weights[key] = self.priorities.get(key, 3)  # default priority 3

        total_weight = sum(weights.values())
        if total_weight == 0:
            # Equal distribution
            per_section = budget // len(context)
            return {k: per_section for k in context}

        # First pass: proportional allocation
        allocations: Dict[str, int] = {}
        for key, weight in weights.items():
            raw_alloc = int(budget * weight / total_weight)
            allocations[key] = max(raw_alloc, self.min_section_chars)

        # Second pass: if a section's content is shorter than its allocation,
        # redistribute the surplus to other sections
        surplus = 0
        needs_more: List[str] = []
        for key, alloc in allocations.items():
            content_len = len(context.get(key, ""))
            if content_len < alloc:
                surplus += alloc - content_len
                allocations[key] = content_len
            else:
                needs_more.append(key)

        if surplus > 0 and needs_more:
            # Redistribute surplus proportionally to sections that need it
            needs_weight = sum(weights[k] for k in needs_more)
            if needs_weight > 0:
                for key in needs_more:
                    extra = int(surplus * weights[key] / needs_weight)
                    allocations[key] += extra

        return allocations

    def _remove_redundancies(
        self, context: Dict[str, str]
    ) -> Tuple[Dict[str, str], int]:
        """Remove phrases that appear in multiple sections.

        Keeps the phrase in the highest-priority section and removes from others.
        Only removes phrases of 6+ characters to avoid false positives.
        """
        if len(context) < 2:
            return dict(context), 0

        # Sort sections by priority (highest first)
        sorted_keys = sorted(
            context.keys(),
            key=lambda k: self.priorities.get(k, 3),
            reverse=True,
        )

        # Extract significant phrases (6+ chars, appear in 2+ sections)
        all_phrases: Dict[str, List[str]] = {}  # phrase -> list of section keys
        for key in sorted_keys:
            content = context[key]
            # Extract phrases between punctuation/separators
            phrases = re.split(r"[;；,，。!！?？\s]+", content)
            for phrase in phrases:
                phrase = phrase.strip()
                if len(phrase) >= 6:
                    all_phrases.setdefault(phrase, []).append(key)

        # Find duplicates
        duplicates = {p: keys for p, keys in all_phrases.items() if len(keys) > 1}
        if not duplicates:
            return dict(context), 0

        # Remove from lower-priority sections
        cleaned = dict(context)
        removed_count = 0
        for phrase, keys in duplicates.items():
            # Keep in highest-priority section (first in sorted order)
            for key in keys[1:]:
                if phrase in cleaned[key]:
                    cleaned[key] = cleaned[key].replace(phrase, "", 1).strip()
                    # Clean up double separators left behind
                    cleaned[key] = re.sub(r"[;；,，]{2,}", ";", cleaned[key])
                    cleaned[key] = re.sub(r"\s{2,}", " ", cleaned[key])
                    removed_count += 1

        return cleaned, removed_count

    @staticmethod
    def _truncate_at_boundary(text: str, max_chars: int) -> str:
        """Truncate text at the nearest sentence boundary before max_chars.

        Prefers cutting at Chinese sentence endings (。！？) or semicolons.
        Falls back to space/comma boundaries if no sentence end found.
        """
        if len(text) <= max_chars:
            return text

        # Look for the last sentence boundary within budget
        search_region = text[:max_chars]

        # Try sentence boundaries first
        sentence_ends = list(re.finditer(r"[。！？!?;；]", search_region))
        if sentence_ends:
            last_end = sentence_ends[-1]
            return text[: last_end.end()].strip()

        # Try comma/space boundaries
        soft_ends = list(re.finditer(r"[,，、\s]", search_region))
        if soft_ends:
            last_end = soft_ends[-1]
            return text[: last_end.start()].strip()

        # Hard cut as last resort
        return text[:max_chars].strip()
