"""Stylist agent skeleton."""

from dataclasses import dataclass
from typing import List


@dataclass
class StylistResult:
    text: str
    edits: List[str]


class StylistAgent:
    """Applies simple style cleanup rules."""

    def polish(self, text: str, banned_phrases: List[str]) -> StylistResult:
        edits: List[str] = []
        polished = text
        for phrase in banned_phrases:
            if phrase and phrase in polished:
                polished = polished.replace(phrase, "")
                edits.append(f"移除表达: {phrase}")
        return StylistResult(text=polished.strip(), edits=edits)
