"""Stylist agent — style checking and polishing using the three-layer style system.

Performs rule-based checks on draft text against the composed style document:
  - Anti-pattern detection (AI-sounding phrases, banned expressions)
  - Voice consistency checks (narrator-character fusion)
  - Rhythm validation (paragraph length distribution, pacing)
  - Language style checks (modern metaphors, sentence patterns)

支持 LLM 模式（opt-in）：通过 LLM 进行风格润色。
不传入 llm_client 时保持原有规则模拟行为。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Dict, List, Optional, Tuple

import logging

if TYPE_CHECKING:
    from tools.llm.client import LLMClient
    from tools.llm.router import ModelRouter

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Common AI-sounding phrases to flag (Chinese web novel AI artifacts)
# ---------------------------------------------------------------------------
DEFAULT_AI_BANNED_PHRASES: List[str] = [
    "不禁",
    "缓缓说道",
    "微微一笑",
    "淡淡地说",
    "嘴角微微上扬",
    "眼中闪过一丝",
    "心中暗想",
    "不由得",
    "一股强大的气息",
    "仿佛能够洞察一切",
    "深邃的目光",
    "嘴角勾起一抹弧度",
    "宛如",
    "犹如",
    "恍若",
    "一时间",
    "霎时间",
    "顿时间",
    "与此同时",  # overused transition
    "众人纷纷",
    "不由自主地",
    "心中一凛",
    "心中一动",
    "心中一沉",
    "暗自思忖",
    "若有所思",
    "意味深长",
    "语气平静",
    "波澜不惊",
]


@dataclass
class StyleIssue:
    """A single style issue found in the draft."""

    category: str  # anti_pattern | voice | rhythm | language | structure
    severity: str  # error | warning | suggestion
    message: str
    line_number: int = 0
    context: str = ""


@dataclass
class StylistResult:
    """Result of style checking."""

    text: str
    edits: List[str]
    issues: List[StyleIssue] = field(default_factory=list)
    score: Dict[str, int] = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        return not any(i.severity == "error" for i in self.issues)


@dataclass
class StyleRules:
    """Extracted rules from the composed style document."""

    banned_phrases: List[str] = field(default_factory=list)
    anti_patterns: List[str] = field(default_factory=list)
    short_para_ratio: float = 0.6  # target: 60% short paragraphs
    max_consecutive_long: int = 3
    max_info_dump_lines: int = 3  # no more than 3 paragraphs without character reaction
    chapter_length_range: Tuple[int, int] = (800, 1500)
    prefer_short_sentences: bool = True


class StylistAgent:
    """Checks and polishes draft text against three-layer style rules."""

    def __init__(
        self,
        project_root: Optional[Path] = None,
        style_rules: Optional[StyleRules] = None,
        extra_banned: Optional[List[str]] = None,
        novel_id: str = "",
        llm_client: Optional["LLMClient"] = None,
        router: Optional["ModelRouter"] = None,
    ):
        self.project_root = project_root
        self.novel_id = novel_id
        self.rules = style_rules or StyleRules()
        self._composed_text: Optional[str] = None
        self._style_profile: Optional["StyleProfile"] = None

        self._llm_client = llm_client
        self._router = router
        # Merge default AI banned phrases + any extras
        all_banned = list(DEFAULT_AI_BANNED_PHRASES)
        if extra_banned:
            all_banned.extend(extra_banned)
        if self.rules.banned_phrases:
            all_banned.extend(self.rules.banned_phrases)

        # Auto-load StyleProfile if project_root and novel_id are available
        if project_root and novel_id:
            self._load_style_profile(novel_id, all_banned)
        else:
            self._deduplicate_banned(all_banned)

        # Anti-patterns from fingerprint.md
        self.rules.anti_patterns = [
            "中性叙述句",
            "对比式段子",
            "角色行动前过度分析",
            "连续灌输设定",
            "煽情段落无冷静转折",
        ]

    def _load_style_profile(self, novel_id: str, all_banned: List[str]) -> None:
        """Load StyleProfile and merge its data into rules."""
        try:
            from tools.models.style import StyleProfile
        except ImportError:
            from models.style import StyleProfile

        profile = StyleProfile.from_project(
            self.project_root, novel_id=novel_id  # type: ignore[arg-type]
        )
        self._style_profile = profile

        # Merge profile banned phrases into the list
        profile_banned = profile.get_banned_phrase_list()
        all_banned.extend(profile_banned)
        self._deduplicate_banned(all_banned)

        # Adjust rhythm thresholds from profile if available
        if profile.positive_features.rhythm:
            short_target = profile.positive_features.rhythm.get("short", 0.6)
            self.rules.short_para_ratio = short_target

    def _deduplicate_banned(self, all_banned: List[str]) -> None:
        """Deduplicate banned phrases while preserving order."""
        seen: set = set()
        unique: List[str] = []
        for phrase in all_banned:
            if phrase not in seen:
                seen.add(phrase)
                unique.append(phrase)
        self.rules.banned_phrases = unique

    @property
    def style_profile(self) -> Optional["StyleProfile"]:
        """Access the loaded StyleProfile, if any."""
        return self._style_profile
    def load_composed_style(self, novel_id: str) -> Optional[str]:
        """Load the composed style document for reference."""
        if self.project_root is None:
            return None
        composed_path = self.project_root / "composed" / f"{novel_id}_final.md"
        if composed_path.is_file():
            self._composed_text = composed_path.read_text(encoding="utf-8")
            return self._composed_text
        return None

    def _check_banned_phrases(self, text: str, lines: List[str]) -> List[StyleIssue]:
        """Check for AI-sounding and banned phrases."""
        issues: List[StyleIssue] = []
        for phrase in self.rules.banned_phrases:
            if not phrase:
                continue
            for i, line in enumerate(lines, 1):
                if phrase in line:
                    issues.append(StyleIssue(
                        category="anti_pattern",
                        severity="warning",
                        message=f"检测到AI痕迹/禁用表达: 「{phrase}」",
                        line_number=i,
                        context=line.strip()[:80],
                    ))
        return issues

    def _check_rhythm(self, lines: List[str]) -> List[StyleIssue]:
        """Check paragraph length distribution and pacing."""
        issues: List[StyleIssue] = []

        # Split into paragraphs (non-empty lines)
        paragraphs = [line for line in lines if line.strip()]
        if not paragraphs:
            return issues

        # Classify paragraphs by sentence count
        short_count = 0  # 1-2 sentences
        medium_count = 0  # 3-5 sentences
        long_count = 0  # 6+ sentences
        consecutive_long = 0
        max_consecutive_long_found = 0

        for para in paragraphs:
            # Rough sentence count: split by Chinese period, question mark, exclamation
            sentences = re.split(r'[。！？!?]', para)
            sentences = [s for s in sentences if s.strip()]
            n_sentences = max(len(sentences), 1)

            if n_sentences <= 2:
                short_count += 1
                consecutive_long = 0
            elif n_sentences <= 5:
                medium_count += 1
                consecutive_long = 0
            else:
                long_count += 1
                consecutive_long += 1
                max_consecutive_long_found = max(max_consecutive_long_found, consecutive_long)

        total = short_count + medium_count + long_count
        if total > 0:
            short_ratio = short_count / total
            if short_ratio < 0.4:
                issues.append(StyleIssue(
                    category="rhythm",
                    severity="warning",
                    message=f"短段落占比偏低: {short_ratio:.0%}（目标≥60%），节奏可能过于沉重",
                ))

        if max_consecutive_long_found > self.rules.max_consecutive_long:
            issues.append(StyleIssue(
                category="rhythm",
                severity="warning",
                message=f"连续长段落达{max_consecutive_long_found}段（上限{self.rules.max_consecutive_long}），节奏可能'塌'",
            ))

        return issues

    def _check_chapter_length(self, text: str) -> List[StyleIssue]:
        """Check if chapter length is within expected range."""
        issues: List[StyleIssue] = []
        # Count Chinese characters (rough)
        chinese_chars = len(re.findall(r'[\u4e00-\u9fff]', text))
        min_len, max_len = self.rules.chapter_length_range

        if chinese_chars > 0 and chinese_chars < min_len // 2:
            issues.append(StyleIssue(
                category="rhythm",
                severity="suggestion",
                message=f"章节字数偏少: {chinese_chars}字（参考范围{min_len}-{max_len}字）",
            ))
        elif chinese_chars > max_len * 2:
            issues.append(StyleIssue(
                category="rhythm",
                severity="suggestion",
                message=f"章节字数偏多: {chinese_chars}字（参考范围{min_len}-{max_len}字）",
            ))

        return issues

    def _check_voice_consistency(self, lines: List[str]) -> List[StyleIssue]:
        """Check for neutral narration that lacks character voice fusion."""
        issues: List[StyleIssue] = []

        # Detect overly neutral narration patterns
        neutral_patterns = [
            (r'他(?:静静地|默默地|安静地)(?:看着|望着|注视着)', "中性叙述：缺少角色化用词"),
            (r'她(?:静静地|默默地|安静地)(?:看着|望着|注视着)', "中性叙述：缺少角色化用词"),
            (r'(?:他|她)的(?:内心|心中)(?:十分|非常|极其)', "直白情感描写：应通过细节和反差传递"),
            (r'(?:他|她)(?:感到|觉得)(?:十分|非常|极其)(?:高兴|悲伤|愤怒|开心)', "直白情感描写：应通过行动和细节展现"),
        ]

        for i, line in enumerate(lines, 1):
            for pattern, msg in neutral_patterns:
                if re.search(pattern, line):
                    issues.append(StyleIssue(
                        category="voice",
                        severity="suggestion",
                        message=msg,
                        line_number=i,
                        context=line.strip()[:80],
                    ))

        return issues

    def _check_info_dump(self, lines: List[str]) -> List[StyleIssue]:
        """Check for consecutive exposition without character reaction."""
        issues: List[StyleIssue] = []
        consecutive_exposition = 0
        exposition_start = 0

        # Heuristic: lines without dialogue markers or internal monologue markers
        # are likely exposition
        dialogue_markers = re.compile(r'[""「」『』]|说道|道：|问道|喊道|吐槽|内心|心想')

        for i, line in enumerate(lines, 1):
            stripped = line.strip()
            if not stripped:
                consecutive_exposition = 0
                continue

            if dialogue_markers.search(stripped):
                consecutive_exposition = 0
            else:
                if consecutive_exposition == 0:
                    exposition_start = i
                consecutive_exposition += 1

            if consecutive_exposition > self.rules.max_info_dump_lines + 2:
                issues.append(StyleIssue(
                    category="structure",
                    severity="warning",
                    message=f"连续{consecutive_exposition}段叙述无角色反应（从第{exposition_start}行起），"
                            f"建议插入对话/内心独白/动作反应",
                    line_number=exposition_start,
                ))
                consecutive_exposition = 0  # Reset to avoid duplicate warnings

        return issues

    def check_style(self, text: str, novel_id: Optional[str] = None) -> StylistResult:
        """Run all style checks on the draft text. Returns issues without modifying text."""
        effective_novel = novel_id or self.novel_id
        if effective_novel and self.project_root:
            self.load_composed_style(effective_novel)
            # Lazy-load profile if not loaded at init
            if self._style_profile is None:
                self._load_style_profile(effective_novel, list(self.rules.banned_phrases))
        lines = text.split("\n")
        all_issues: List[StyleIssue] = []

        all_issues.extend(self._check_banned_phrases(text, lines))
        all_issues.extend(self._check_rhythm(lines))
        all_issues.extend(self._check_chapter_length(text))
        all_issues.extend(self._check_voice_consistency(lines))
        all_issues.extend(self._check_info_dump(lines))

        # Compute scores
        score = self._compute_scores(all_issues)

        edits = [f"[{i.severity}] {i.message}" for i in all_issues]

        return StylistResult(
            text=text,
            edits=edits,
            issues=all_issues,
            score=score,
        )

    def _compute_scores(self, issues: List[StyleIssue]) -> Dict[str, int]:
        """Compute style scores (0-100) per category.
        If a StyleProfile is loaded, its quality metrics serve as weight
        multipliers — categories the profile documents well get stricter scoring."""
        categories = ["anti_pattern", "voice", "rhythm", "language", "structure"]
        scores: Dict[str, int] = {}
        # Map categories to profile quality metric fields
        metric_map: Dict[str, str] = {
            "anti_pattern": "ai_artifact_control",
            "voice": "characterization",
            "rhythm": "rhythm",
            "language": "directness",
            "structure": "imagery",
        }
        for cat in categories:
            cat_issues = [i for i in issues if i.category == cat]
            errors = sum(1 for i in cat_issues if i.severity == "error")
            warnings = sum(1 for i in cat_issues if i.severity == "warning")
            suggestions = sum(1 for i in cat_issues if i.severity == "suggestion")
            # Base deductions
            deduction = (errors * 20) + (warnings * 10) + (suggestions * 3)
            # If profile has high quality metric for this category, apply stricter scoring
            if self._style_profile:
                metric_field = metric_map.get(cat, "")
                metric_val = getattr(self._style_profile.quality_metrics, metric_field, 0)
                if metric_val >= 80:
                    # Well-documented category → stricter (1.2x deduction)
                    deduction = int(deduction * 1.2)
            score = 100 - deduction
            scores[cat] = max(0, min(100, score))
        scores["overall"] = sum(scores.values()) // len(categories) if categories else 100
        return scores

    def polish(
        self,
        text: str,
        banned_phrases: Optional[List[str]] = None,
        novel_id: Optional[str] = None,
    ) -> StylistResult:
        """Check style and apply fixes (rule-based or LLM).
        Backward-compatible with the old API signature.
        When llm_client is available, uses LLM for polishing with rule-based fallback.
        """
        # LLM branch: use LLM for polishing, fall back to rule-based on failure
        if self._llm_client and self._router:
            return self._polish_with_llm(text, banned_phrases, novel_id)

        # Rule-based fallback
        return self._polish_rule_based(text, banned_phrases, novel_id)

    def _polish_with_llm(
        self,
        text: str,
        banned_phrases: Optional[List[str]] = None,
        novel_id: Optional[str] = None,
    ) -> StylistResult:
        """LLM 风格润色 — 调用 LLM 润色文本，失败时回退到规则引擎。"""
        from tools.llm.prompts import PromptBuilder
        from tools.llm.router import TaskType

        # 构建风格档案摘要
        profile_summary = ""
        if self._style_profile:
            profile_summary = self._style_profile.to_summary(max_chars=1500)

        messages = PromptBuilder.stylist_polish(
            draft=text,
            style_profile_summary=profile_summary,
            banned_phrases=list(self.rules.banned_phrases[:30]),
        )

        try:
            routes = self._router.get_routes(TaskType.STYLE)  # type: ignore[union-attr]
            response = self._llm_client.complete_with_fallback(  # type: ignore[union-attr]
                messages=messages, routes=routes,
            )
            polished_text = response.content.strip()
            # 运行规则检查以生成评分和 issues
            result = self.check_style(polished_text, novel_id=novel_id)
            return StylistResult(
                text=polished_text,
                edits=["[LLM] 风格润色已应用"] + result.edits,
                issues=result.issues,
                score=result.score,
            )
        except Exception as e:
            logger.warning("Stylist LLM 润色失败，回退到规则引擎: %s", e)
            return self._polish_rule_based(text, banned_phrases, novel_id)

    def _polish_rule_based(
        self,
        text: str,
        banned_phrases: Optional[List[str]] = None,
        novel_id: Optional[str] = None,
    ) -> StylistResult:
        """规则引擎润色（原有行为）。"""
        result = self.check_style(text, novel_id=novel_id)
        polished = text
        applied_edits: List[str] = []
        phrases_to_remove = list(banned_phrases or [])
        for phrase in phrases_to_remove:
            if phrase and phrase in polished:
                polished = polished.replace(phrase, "")
                applied_edits.append(f"移除表达: {phrase}")
        for issue in result.issues:
            if issue.category == "anti_pattern" and "禁用表达" in issue.message:
                match = re.search(r'「(.+?)」', issue.message)
                if match:
                    phrase = match.group(1)
                    if phrase in polished:
                        polished = polished.replace(phrase, "")
                        applied_edits.append(f"移除AI痕迹: {phrase}")
        all_edits = applied_edits + result.edits
        return StylistResult(
            text=polished.strip(),
            edits=all_edits,
            issues=result.issues,
            score=result.score,
        )
