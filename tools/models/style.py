"""Style profile models — bridging Pydantic models with the markdown three-layer system.

Provides structured data models for style profiles, plus utilities to load
from composed markdown documents and convert between formats.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, List, Optional

from pydantic import BaseModel, Field


class BannedPhrase(BaseModel):
    phrase: str
    replacement_hint: str = ""


class BannedWord(BaseModel):
    word: str
    replacement_hint: str = ""


class BannedStructure(BaseModel):
    pattern: str
    rewrite_hint: str = ""


class IconicScene(BaseModel):
    type: str
    examples: List[str] = Field(default_factory=list)
    tags: List[str] = Field(default_factory=list)


class StylePositiveFeatures(BaseModel):
    sentence_patterns: List[str] = Field(default_factory=list)
    preferred_vocabulary: List[str] = Field(default_factory=list)
    frequency_ratio: float = 0.15
    rhythm: Dict[str, float] = Field(default_factory=dict)
    iconic_scenes: List[IconicScene] = Field(default_factory=list)


class StyleQualityMetrics(BaseModel):
    directness: int = 0
    rhythm: int = 0
    imagery: int = 0
    characterization: int = 0
    ai_artifact_control: int = 0


class StyleProfile(BaseModel):
    """Structured style profile that bridges YAML and markdown systems."""

    base: Dict[str, str] = Field(default_factory=dict)
    positive_features: StylePositiveFeatures = Field(
        default_factory=StylePositiveFeatures
    )
    banned_phrases: List[BannedPhrase] = Field(default_factory=list)
    banned_words: List[BannedWord] = Field(default_factory=list)
    banned_structures: List[BannedStructure] = Field(default_factory=list)
    quality_metrics: StyleQualityMetrics = Field(default_factory=StyleQualityMetrics)

    # --- Three-layer markdown bridge fields ---
    style_id: str = ""
    novel_id: str = ""
    hard_constraints_summary: str = ""
    style_constraints_summary: str = ""
    craft_reference_summary: str = ""

    @classmethod
    def from_composed_doc(
        cls,
        composed_path: Path,
        style_id: str = "",
        novel_id: str = "",
    ) -> "StyleProfile":
        """Load a StyleProfile from a composed markdown document.

        Parses the three-layer composed output (from StyleComposer) and
        extracts structured data into the Pydantic model.

        Args:
            composed_path: Path to the composed *_final.md file.
            style_id: Style template identifier.
            novel_id: Novel identifier.
        """
        if not composed_path.is_file():
            return cls(style_id=style_id, novel_id=novel_id)

        text = composed_path.read_text(encoding="utf-8")
        return cls._parse_composed_text(text, style_id, novel_id)

    @classmethod
    def from_project(
        cls,
        project_root: Path,
        novel_id: str,
        style_id: str = "",
    ) -> "StyleProfile":
        """Load from project root, auto-detecting the composed file.

        Args:
            project_root: Project root directory.
            novel_id: Novel identifier (used to find composed/{novel_id}_final.md).
            style_id: Style template identifier.
        """
        composed_path = project_root / "composed" / f"{novel_id}_final.md"
        return cls.from_composed_doc(
            composed_path, style_id=style_id, novel_id=novel_id
        )

    @classmethod
    def _parse_composed_text(
        cls, text: str, style_id: str, novel_id: str
    ) -> "StyleProfile":
        """Parse composed markdown text into a StyleProfile."""
        profile = cls(style_id=style_id, novel_id=novel_id)

        # Split by top-level sections
        sections = _split_sections(text)

        # Extract hard constraints (novel layer)
        hard_section = _find_section(sections, ["硬性约束", "作品设定"])
        profile.hard_constraints_summary = hard_section[:2000] if hard_section else ""

        # Extract style constraints (style layer)
        style_section = _find_section(sections, ["风格约束", "作品风格"])
        profile.style_constraints_summary = (
            style_section[:2000] if style_section else ""
        )

        # Extract craft reference
        craft_section = _find_section(sections, ["通用技法", "技法参考"])
        profile.craft_reference_summary = craft_section[:2000] if craft_section else ""

        # Extract banned phrases from the composed doc
        profile.banned_phrases = _extract_banned_phrases(text)

        # Extract positive features
        profile.positive_features = _extract_positive_features(style_section)

        # Extract base metadata
        profile.base = _extract_base_metadata(text, style_id, novel_id)

        # Compute quality metrics from the document
        profile.quality_metrics = _estimate_quality_metrics(text)

        return profile

    def to_summary(self, max_chars: int = 500) -> str:
        """Generate a concise summary for use in agent prompts.

        Returns a compact text suitable for passing to Director/Librarian
        as style context.
        """
        parts: List[str] = []

        if self.style_id:
            parts.append(f"风格模板: {self.style_id}")
        if self.novel_id:
            parts.append(f"作品: {self.novel_id}")

        if self.banned_phrases:
            phrases = [bp.phrase for bp in self.banned_phrases[:10]]
            parts.append(f"禁用表达({len(self.banned_phrases)}): {', '.join(phrases)}")

        if self.positive_features.sentence_patterns:
            patterns = self.positive_features.sentence_patterns[:5]
            parts.append(f"推荐句式: {', '.join(patterns)}")

        if self.positive_features.rhythm:
            rhythm_desc = ", ".join(
                f"{k}={v:.0%}" for k, v in self.positive_features.rhythm.items()
            )
            parts.append(f"节奏: {rhythm_desc}")

        metrics = self.quality_metrics
        if any([metrics.directness, metrics.rhythm, metrics.imagery]):
            parts.append(
                f"质量指标: 直接性={metrics.directness} 节奏={metrics.rhythm} "
                f"意象={metrics.imagery} 角色化={metrics.characterization} "
                f"去AI={metrics.ai_artifact_control}"
            )

        if self.hard_constraints_summary:
            excerpt = self.hard_constraints_summary[:150].replace("\n", " ")
            parts.append(f"硬性约束摘要: {excerpt}...")

        if self.style_constraints_summary:
            excerpt = self.style_constraints_summary[:150].replace("\n", " ")
            parts.append(f"风格约束摘要: {excerpt}...")

        result = "\n".join(parts)
        return result[:max_chars] if len(result) > max_chars else result

    def get_banned_phrase_list(self) -> List[str]:
        """Get flat list of banned phrases for use by Stylist."""
        return [bp.phrase for bp in self.banned_phrases if bp.phrase]

    def merge_banned_phrases(self, extra_phrases: List[str]) -> None:
        """Merge additional banned phrases, deduplicating."""
        existing = {bp.phrase for bp in self.banned_phrases}
        for phrase in extra_phrases:
            if phrase and phrase not in existing:
                self.banned_phrases.append(BannedPhrase(phrase=phrase))
                existing.add(phrase)


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------


def _split_sections(text: str) -> Dict[str, str]:
    """Split markdown text into sections by ## headers."""
    sections: Dict[str, str] = {}
    current_header = ""
    current_lines: List[str] = []

    for line in text.split("\n"):
        header_match = re.match(r"^##\s+(.+)", line)
        if header_match:
            if current_header:
                sections[current_header] = "\n".join(current_lines).strip()
            current_header = header_match.group(1).strip()
            current_lines = []
        else:
            current_lines.append(line)

    if current_header:
        sections[current_header] = "\n".join(current_lines).strip()

    return sections


def _find_section(sections: Dict[str, str], prefixes: List[str]) -> str:
    """Find a section by prefix match. Handles headers like '硬性约束（作品设定层）'."""
    # Try exact match first
    for prefix in prefixes:
        if prefix in sections:
            return sections[prefix]
    # Try prefix match (header may have parenthetical suffix)
    for prefix in prefixes:
        for header, content in sections.items():
            if header.startswith(prefix):
                return content
    return ""

def _extract_banned_phrases(text: str) -> List[BannedPhrase]:
    """Extract banned phrases from composed document."""
    phrases: List[BannedPhrase] = []
    seen: set = set()

    # Look for explicit banned/forbidden lists
    banned_section = re.search(
        r"(?:禁用|禁忌|banned|forbidden|反模式|AI痕迹)(.*?)(?=\n##|\Z)",
        text,
        re.DOTALL | re.IGNORECASE,
    )
    if banned_section:
        content = banned_section.group(1)
        # Extract items from bullet lists
        items = re.findall(
            r'[-·*]\s*[「""]?(\S+?)[」""]?\s*(?:[:：→](.+?))?(?:\n|$)', content
        )
        for phrase, hint in items:
            phrase = phrase.strip()
            if phrase and len(phrase) >= 2 and phrase not in seen:
                phrases.append(
                    BannedPhrase(
                        phrase=phrase,
                        replacement_hint=hint.strip() if hint else "",
                    )
                )
                seen.add(phrase)

    return phrases


def _extract_positive_features(style_text: str) -> StylePositiveFeatures:
    """Extract positive style features from style section."""
    features = StylePositiveFeatures()

    if not style_text:
        return features

    # Extract sentence patterns
    pattern_matches = re.findall(
        r"(?:句式|句型|sentence).{0,5}[:：]\s*(.+)", style_text
    )
    if pattern_matches:
        features.sentence_patterns = [m.strip() for m in pattern_matches[:10]]

    # Extract rhythm preferences
    short_match = re.search(r"短段.{0,10}?(\d+)%", style_text)
    medium_match = re.search(r"中段.{0,10}?(\d+)%", style_text)
    long_match = re.search(r"长段.{0,10}?(\d+)%", style_text)
    if short_match:
        features.rhythm["short"] = int(short_match.group(1)) / 100
    if medium_match:
        features.rhythm["medium"] = int(medium_match.group(1)) / 100
    if long_match:
        features.rhythm["long"] = int(long_match.group(1)) / 100

    # Extract preferred vocabulary
    vocab_matches = re.findall(
        r"(?:偏好|推荐|preferred).{0,10}(?:词汇|用语|vocabulary).{0,5}[:：]\s*(.+)",
        style_text,
    )
    if vocab_matches:
        for match in vocab_matches:
            words = re.split(r"[,，、;；]", match)
            features.preferred_vocabulary.extend(w.strip() for w in words if w.strip())

    return features


def _extract_base_metadata(text: str, style_id: str, novel_id: str) -> Dict[str, str]:
    """Extract base metadata from composed document."""
    base: Dict[str, str] = {
        "style_id": style_id,
        "novel_id": novel_id,
        "source": "composed_markdown",
    }

    # Try to extract title
    title_match = re.search(r"^#\s+(.+)", text)
    if title_match:
        base["title"] = title_match.group(1).strip()

    return base


def _estimate_quality_metrics(text: str) -> StyleQualityMetrics:
    """Estimate quality metrics from the composed document content."""
    metrics = StyleQualityMetrics()

    # Estimate based on document completeness
    has_rhythm = bool(re.search(r"(?:节奏|rhythm)", text, re.IGNORECASE))
    has_voice = bool(re.search(r"(?:声音|voice|叙述者)", text, re.IGNORECASE))
    has_banned = bool(re.search(r"(?:禁用|banned|反模式)", text, re.IGNORECASE))
    has_imagery = bool(re.search(r"(?:意象|比喻|imagery)", text, re.IGNORECASE))
    has_character = bool(re.search(r"(?:角色|人物|character)", text, re.IGNORECASE))

    # Score based on coverage (0-100 scale, higher = more documented)
    metrics.rhythm = 80 if has_rhythm else 30
    metrics.directness = 70 if has_voice else 30
    metrics.ai_artifact_control = 90 if has_banned else 40
    metrics.imagery = 60 if has_imagery else 30
    metrics.characterization = 70 if has_character else 30

    return metrics
