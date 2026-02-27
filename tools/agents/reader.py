"""Reader agent — batch text reading with three-layer style extraction.

Implements the PROMPT_READER.md workflow:
  1. Accept text chunks for batch processing
  2. Extract findings tagged by layer (craft / style / novel)
  3. Classify each finding using the layer judgment criteria
  4. Output structured results with file routing suggestions
  5. Generate outline update suggestions

This is a LOCAL rule-based extractor. It uses pattern matching and heuristics
to identify style/craft/novel findings from raw text. For full LLM-powered
extraction, the structured output from this agent serves as the prompt context.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional, Tuple


class FindingLayer(str, Enum):
    """Which layer a finding belongs to."""

    CRAFT = "craft"
    STYLE = "style"
    NOVEL = "novel"


@dataclass
class Finding:
    """A single extracted finding from the text."""

    layer: FindingLayer
    category: str  # e.g. "narrative", "dialogue", "rhythm", "language", "character", "worldbuilding"
    name: str  # pattern/finding name
    description: str
    evidence: List[str] = field(default_factory=list)  # text excerpts as evidence
    target_file: str = ""  # suggested file to update, e.g. "craft/dialogue_craft.md"
    confidence: float = 0.8  # 0.0 - 1.0


@dataclass
class OutlineEvent:
    """A structured event extracted for outline updates."""

    chapter_range: str  # e.g. "ch_001-ch_003"
    event_type: str  # 主线 / 支线 / 人物线 / 设定线 / 伏笔线
    cause: str
    action: str
    result: str
    impact: str


@dataclass
class ReaderOutput:
    """Complete output from a Reader batch processing run."""

    batch_id: str
    chunk_range: str  # e.g. "第1-7章"
    findings: List[Finding] = field(default_factory=list)
    outline_events: List[OutlineEvent] = field(default_factory=list)
    revision_suggestions: List[str] = field(default_factory=list)

    @property
    def craft_findings(self) -> List[Finding]:
        return [f for f in self.findings if f.layer == FindingLayer.CRAFT]

    @property
    def style_findings(self) -> List[Finding]:
        return [f for f in self.findings if f.layer == FindingLayer.STYLE]

    @property
    def novel_findings(self) -> List[Finding]:
        return [f for f in self.findings if f.layer == FindingLayer.NOVEL]

    def summary(self) -> str:
        """Generate a human-readable summary."""
        lines = [
            f"# Reader 批次报告: {self.batch_id}",
            f"- 文本范围: {self.chunk_range}",
            f"- 总发现数: {len(self.findings)}",
            f"  - 通用技法 (craft): {len(self.craft_findings)}",
            f"  - 作者风格 (style): {len(self.style_findings)}",
            f"  - 作品设定 (novel): {len(self.novel_findings)}",
            f"- 大纲事件: {len(self.outline_events)}",
            f"- 修订建议: {len(self.revision_suggestions)}",
            "",
        ]

        for layer_name, findings in [
            ("通用技法发现 (→ craft/)", self.craft_findings),
            ("作者风格发现 (→ styles/)", self.style_findings),
            ("作品设定发现 (→ novels/)", self.novel_findings),
        ]:
            if findings:
                lines.append(f"## {layer_name}")
                for f in findings:
                    lines.append(f"- **{f.name}** [{f.category}] → {f.target_file}")
                    lines.append(f"  {f.description}")
                    if f.evidence:
                        lines.append(f"  证据: {f.evidence[0][:80]}...")
                lines.append("")

        if self.outline_events:
            lines.append("## 大纲更新")
            for evt in self.outline_events:
                lines.append(
                    f"- [{evt.event_type}] {evt.chapter_range}: "
                    f"{evt.cause} → {evt.action} → {evt.result} | 影响: {evt.impact}"
                )
            lines.append("")

        if self.revision_suggestions:
            lines.append("## 修订建议")
            for sug in self.revision_suggestions:
                lines.append(f"- {sug}")

        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Pattern detectors — heuristic rules for finding extraction
# ---------------------------------------------------------------------------

# Craft-layer patterns (universal techniques, applicable across authors)
CRAFT_PATTERNS: List[Tuple[str, str, str]] = [
    # (regex_pattern, finding_name, category)
    (r"(?:紧张|张力).{0,10}(?:松弛|缓和|释放)", "张力-松弛循环", "scene_structure"),
    (r"(?:悬念|钩子|hook).{0,20}(?:章末|结尾|收束)", "章末悬念钩子", "scene_structure"),
    (
        r"(?:信息).{0,10}(?:揭示|揭露|展示).{0,10}(?:策略|方式|手段)",
        "信息揭示策略",
        "information_reveal",
    ),
    (r"(?:视角).{0,10}(?:切换|转换)", "视角切换技巧", "pov_techniques"),
    (r"(?:伏笔).{0,10}(?:埋设|铺垫|回收)", "伏笔管理", "foreshadowing"),
    (
        r"(?:对话).{0,10}(?:推进|驱动).{0,10}(?:剧情|情节)",
        "对话驱动叙事",
        "dialogue_craft",
    ),
    (r"(?:反转|颠覆|打脸).{0,10}(?:期望|预期)", "期望颠覆", "scene_structure"),
]

# Style-layer patterns (author-specific habits)
STYLE_PATTERNS: List[Tuple[str, str, str]] = [
    (r"(?:吐槽|自嘲|内心os)", "吐槽式叙述", "voice"),
    (r"(?:网络用语|网络梗|游戏术语|职场梗)", "现代感语言融入", "language"),
    (r"(?:表里不一|外冷内热|外甜内毒)", "表里不一角色塑造", "character_voice"),
    (r"(?:短段|一句一段|超短段)", "短段快节奏", "rhythm"),
    (r"(?:旁观者).{0,10}(?:视角|反应|误读)", "旁观者视角技巧", "narrative"),
    (
        r"(?:叙述者).{0,10}(?:角色).{0,10}(?:融合|混合|模糊)",
        "叙述者-角色声音融合",
        "voice",
    ),
    (r"(?:歪楼|跑题|联想跳跃)", "歪楼式吐槽", "humor"),
    (r"(?:克制|冷静转折).{0,10}(?:煽情|感动)", "克制煽情", "voice"),
    (r"(?:乒乓球|信息点).{0,10}(?:反应|回应)", "设定说明乒乓球节奏", "dialogue"),
]

# Novel-layer patterns (work-specific settings)
NOVEL_PATTERNS: List[Tuple[str, str, str]] = [
    (r"(?:术灵|奇迹|术师|甲像|虚翼)", "魔法体系术语", "terminology"),
    (r"(?:亚修|索妮娅|伊古拉|菲利克斯|西莉亚)", "角色名称", "characters"),
    (r"(?:碎湖|血月|雨城|蜀山)", "地名/势力", "worldbuilding"),
    (r"(?:死斗|贡献度|监狱)", "世界观机制", "worldbuilding"),
    (r"(?:穿越|系统|游戏界面|抽卡)", "穿越/系统设定", "worldbuilding"),
]


class ReaderAgent:
    """Batch text reader with three-layer style extraction."""

    def __init__(
        self,
        project_root: Optional[Path] = None,
        style_id: str = "",
        novel_id: str = "",
    ):
        self.project_root = project_root
        self.style_id = style_id
        self.novel_id = novel_id

    def read_batch(
        self,
        text: str,
        batch_id: str = "batch_001",
        chunk_range: str = "",
        existing_findings: Optional[List[Finding]] = None,
    ) -> ReaderOutput:
        """Process a text chunk and extract three-layer findings.

        Args:
            text: The raw text chunk to analyze.
            batch_id: Identifier for this batch.
            chunk_range: Human-readable range, e.g. "第1-7章".
            existing_findings: Previously extracted findings to avoid duplicates.
        """
        existing_names = {f.name for f in (existing_findings or [])}

        findings: List[Finding] = []

        # --- Extract craft-layer findings ---
        findings.extend(self._extract_craft_findings(text, existing_names))

        # --- Extract style-layer findings ---
        findings.extend(self._extract_style_findings(text, existing_names))

        # --- Extract novel-layer findings ---
        findings.extend(self._extract_novel_findings(text, existing_names))

        # --- Structural analysis ---
        findings.extend(self._analyze_structure(text, existing_names))

        # --- Extract outline events ---
        outline_events = self._extract_outline_events(text)

        # --- Generate revision suggestions ---
        revision_suggestions = self._generate_revision_suggestions(findings)

        return ReaderOutput(
            batch_id=batch_id,
            chunk_range=chunk_range,
            findings=findings,
            outline_events=outline_events,
            revision_suggestions=revision_suggestions,
        )

    # ------------------------------------------------------------------
    # Craft-layer extraction
    # ------------------------------------------------------------------

    def _extract_craft_findings(self, text: str, existing: set) -> List[Finding]:
        """Extract universal writing technique patterns."""
        findings: List[Finding] = []

        for pattern, name, category in CRAFT_PATTERNS:
            if name in existing:
                continue
            matches = re.findall(pattern, text)
            if matches:
                evidence = [m if isinstance(m, str) else str(m) for m in matches[:3]]
                findings.append(
                    Finding(
                        layer=FindingLayer.CRAFT,
                        category=category,
                        name=name,
                        description=f"检测到通用技法模式「{name}」，出现{len(matches)}次",
                        evidence=evidence,
                        target_file=f"craft/{category}.md",
                    )
                )

        # Detect dialogue-driven narration
        if "对话驱动叙事" not in existing:
            dialogue_ratio = self._compute_dialogue_ratio(text)
            if dialogue_ratio > 0.3:
                findings.append(
                    Finding(
                        layer=FindingLayer.CRAFT,
                        category="dialogue_craft",
                        name="高对话密度叙事",
                        description=f"对话占比{dialogue_ratio:.0%}，叙事以对话为主要驱动力",
                        target_file="craft/dialogue_craft.md",
                        confidence=0.7,
                    )
                )

        return findings

    # ------------------------------------------------------------------
    # Style-layer extraction
    # ------------------------------------------------------------------

    def _extract_style_findings(self, text: str, existing: set) -> List[Finding]:
        """Extract author-specific style patterns."""
        findings: List[Finding] = []
        style_prefix = f"styles/{self.style_id}" if self.style_id else "styles/{id}"

        for pattern, name, category in STYLE_PATTERNS:
            if name in existing:
                continue
            matches = re.findall(pattern, text)
            if matches:
                evidence = [m if isinstance(m, str) else str(m) for m in matches[:3]]
                findings.append(
                    Finding(
                        layer=FindingLayer.STYLE,
                        category=category,
                        name=name,
                        description=f"检测到作者风格模式「{name}」，出现{len(matches)}次",
                        evidence=evidence,
                        target_file=f"{style_prefix}/{category}.md",
                    )
                )

        # Detect paragraph rhythm pattern
        if "段落节奏分布" not in existing:
            rhythm = self._analyze_paragraph_rhythm(text)
            if rhythm:
                findings.append(
                    Finding(
                        layer=FindingLayer.STYLE,
                        category="rhythm",
                        name="段落节奏分布",
                        description=rhythm,
                        target_file=f"{style_prefix}/rhythm.md",
                        confidence=0.9,
                    )
                )

        # Detect humor patterns
        humor_count = self._count_humor_markers(text)
        if humor_count > 0 and "幽默密度" not in existing:
            findings.append(
                Finding(
                    layer=FindingLayer.STYLE,
                    category="humor",
                    name="幽默密度",
                    description=f"检测到{humor_count}处幽默/吐槽标记",
                    target_file=f"{style_prefix}/humor.md",
                    confidence=0.7,
                )
            )

        return findings

    # ------------------------------------------------------------------
    # Novel-layer extraction
    # ------------------------------------------------------------------

    def _extract_novel_findings(self, text: str, existing: set) -> List[Finding]:
        """Extract work-specific settings and terminology."""
        findings: List[Finding] = []
        novel_prefix = f"novels/{self.novel_id}" if self.novel_id else "novels/{id}"

        for pattern, name, category in NOVEL_PATTERNS:
            if name in existing:
                continue
            matches = re.findall(pattern, text)
            if matches:
                unique_matches = list(set(matches))[:5]
                findings.append(
                    Finding(
                        layer=FindingLayer.NOVEL,
                        category=category,
                        name=name,
                        description=f"检测到作品设定「{name}」: {', '.join(unique_matches)}",
                        evidence=unique_matches,
                        target_file=f"{novel_prefix}/{category}.md",
                    )
                )

        # Extract character names and traits
        char_findings = self._extract_characters(text, existing)
        findings.extend(char_findings)

        return findings

    # ------------------------------------------------------------------
    # Structural analysis
    # ------------------------------------------------------------------

    def _analyze_structure(self, text: str, existing: set) -> List[Finding]:
        """Analyze text structure for cross-layer patterns."""
        findings: List[Finding] = []

        # Detect POV switches
        if "视角切换模式" not in existing:
            pov_switches = self._detect_pov_switches(text)
            if pov_switches > 0:
                findings.append(
                    Finding(
                        layer=FindingLayer.CRAFT,
                        category="pov_techniques",
                        name="视角切换模式",
                        description=f"检测到{pov_switches}次视角切换",
                        target_file="craft/pov_techniques.md",
                    )
                )

        # Detect scene transition patterns
        if "场景转换标记" not in existing:
            transitions = len(re.findall(r"(?:……|———|---|\*\*\*)", text))
            if transitions > 0:
                findings.append(
                    Finding(
                        layer=FindingLayer.STYLE,
                        category="rhythm",
                        name="场景转换标记",
                        description=f"使用{transitions}次场景分隔符",
                        target_file=f"styles/{self.style_id}/rhythm.md"
                        if self.style_id
                        else "styles/{id}/rhythm.md",
                        confidence=0.6,
                    )
                )

        # Detect internal monologue density
        if "内心独白密度" not in existing:
            monologue_ratio = self._compute_monologue_ratio(text)
            if monologue_ratio > 0.1:
                findings.append(
                    Finding(
                        layer=FindingLayer.STYLE,
                        category="narrative",
                        name="内心独白密度",
                        description=f"内心独白占比约{monologue_ratio:.0%}",
                        target_file=f"styles/{self.style_id}/narrative.md"
                        if self.style_id
                        else "styles/{id}/narrative.md",
                        confidence=0.7,
                    )
                )

        return findings

    # ------------------------------------------------------------------
    # Outline event extraction
    # ------------------------------------------------------------------

    def _extract_outline_events(self, text: str) -> List[OutlineEvent]:
        """Extract structured events for outline updates."""
        events: List[OutlineEvent] = []

        # Detect chapter markers
        chapter_markers = re.findall(r"第(\d+)章", text)
        if not chapter_markers:
            return events

        chapter_range = f"ch_{chapter_markers[0].zfill(3)}"
        if len(chapter_markers) > 1:
            chapter_range += f"-ch_{chapter_markers[-1].zfill(3)}"

        # Detect major plot events (simplified heuristic)
        conflict_markers = re.findall(
            r"(?:冲突|战斗|对决|死斗|危机|转折|揭秘|真相)", text
        )
        if conflict_markers:
            events.append(
                OutlineEvent(
                    chapter_range=chapter_range,
                    event_type="主线",
                    cause="局势发展",
                    action=f"发生{', '.join(set(conflict_markers))}",
                    result="局势变化",
                    impact="推动主线进展",
                )
            )

        # Detect character introductions
        new_chars = re.findall(
            r"(?:出现|登场|现身|加入)(?:了|的)?(?:一个|一位)?(\S{2,4})", text
        )
        if new_chars:
            events.append(
                OutlineEvent(
                    chapter_range=chapter_range,
                    event_type="人物线",
                    cause="剧情需要",
                    action=f"新角色登场: {', '.join(set(new_chars)[:3])}",
                    result="角色关系扩展",
                    impact="丰富人物网络",
                )
            )

        return events

    # ------------------------------------------------------------------
    # Revision suggestions
    # ------------------------------------------------------------------

    def _generate_revision_suggestions(self, findings: List[Finding]) -> List[str]:
        """Generate suggestions for updating existing style documents."""
        suggestions: List[str] = []

        craft_count = sum(1 for f in findings if f.layer == FindingLayer.CRAFT)
        style_count = sum(1 for f in findings if f.layer == FindingLayer.STYLE)
        novel_count = sum(1 for f in findings if f.layer == FindingLayer.NOVEL)

        if craft_count > 3:
            suggestions.append(
                f"发现{craft_count}个通用技法模式，建议更新 craft/ 目录下的对应文件"
            )
        if style_count > 3:
            suggestions.append(
                f"发现{style_count}个作者风格模式，建议更新 styles/ 目录下的对应文件"
            )
        if novel_count > 3:
            suggestions.append(
                f"发现{novel_count}个作品设定，建议更新 novels/ 目录下的对应文件"
            )

        # Check for high-confidence findings that should be prioritized
        high_conf = [f for f in findings if f.confidence >= 0.9]
        if high_conf:
            suggestions.append(
                f"有{len(high_conf)}个高置信度发现，建议优先处理: "
                + ", ".join(f.name for f in high_conf[:3])
            )

        return suggestions

    # ------------------------------------------------------------------
    # Helper methods
    # ------------------------------------------------------------------

    def _compute_dialogue_ratio(self, text: str) -> float:
        """Compute the ratio of dialogue lines to total lines."""
        lines = [l for l in text.split("\n") if l.strip()]
        if not lines:
            return 0.0
        dialogue_markers = re.compile(r'[""「」『』]')
        dialogue_lines = sum(1 for l in lines if dialogue_markers.search(l))
        return dialogue_lines / len(lines)

    def _analyze_paragraph_rhythm(self, text: str) -> str:
        """Analyze paragraph length distribution and return description."""
        paragraphs = [p for p in text.split("\n") if p.strip()]
        if len(paragraphs) < 5:
            return ""

        short = sum(1 for p in paragraphs if len(p) <= 30)
        medium = sum(1 for p in paragraphs if 30 < len(p) <= 80)
        long = sum(1 for p in paragraphs if len(p) > 80)
        total = len(paragraphs)

        return (
            f"段落分布: 短段({short}/{total}={short / total:.0%}), "
            f"中段({medium}/{total}={medium / total:.0%}), "
            f"长段({long}/{total}={long / total:.0%})"
        )

    def _count_humor_markers(self, text: str) -> int:
        """Count humor/sarcasm markers in text."""
        humor_patterns = [
            r"淦",
            r"卧槽",
            r"我靠",
            r"离谱",
            r"绝了",
            r"内心os",
            r"心里吐槽",
            r"忍不住吐槽",
            r"……行吧",
            r"……好吧",
            r"……算了",
            r"不愧是",
            r"果然是",
        ]
        count = 0
        for pattern in humor_patterns:
            count += len(re.findall(pattern, text))
        return count

    def _extract_characters(self, text: str, existing: set) -> List[Finding]:
        """Extract character names and basic traits."""
        findings: List[Finding] = []
        novel_prefix = f"novels/{self.novel_id}" if self.novel_id else "novels/{id}"

        # Look for character introduction patterns
        # Pattern: Name + description/trait
        char_intros = re.findall(
            r"(?:名叫|叫做|名为|是个|是一个|是一位)(\S{2,4})",
            text,
        )
        if char_intros and "新角色发现" not in existing:
            unique_chars = list(set(char_intros))[:5]
            findings.append(
                Finding(
                    layer=FindingLayer.NOVEL,
                    category="characters",
                    name="新角色发现",
                    description=f"发现角色: {', '.join(unique_chars)}",
                    evidence=unique_chars,
                    target_file=f"{novel_prefix}/characters.md",
                    confidence=0.6,
                )
            )

        return findings

    def _detect_pov_switches(self, text: str) -> int:
        """Detect point-of-view switches in text."""
        # Heuristic: look for name changes in subject position after scene breaks
        scene_breaks = re.split(r"(?:……|———|---|\*\*\*|\n\n\n)", text)
        if len(scene_breaks) <= 1:
            return 0

        pov_chars: List[str] = []
        for segment in scene_breaks:
            # Find the first character name mentioned
            match = re.search(
                r"^.{0,50}?(\S{2,4})(?:看|想|说|走|站|坐|感到)", segment.strip()
            )
            if match:
                pov_chars.append(match.group(1))

        # Count switches (consecutive different POV characters)
        switches = 0
        for i in range(1, len(pov_chars)):
            if pov_chars[i] != pov_chars[i - 1]:
                switches += 1
        return switches

    def _compute_monologue_ratio(self, text: str) -> float:
        """Compute ratio of internal monologue to total text."""
        lines = [l for l in text.split("\n") if l.strip()]
        if not lines:
            return 0.0
        monologue_markers = re.compile(r"(?:心想|心里|内心|暗想|暗自|心中|脑海里|心道)")
        monologue_lines = sum(1 for l in lines if monologue_markers.search(l))
        return monologue_lines / len(lines)

    # ------------------------------------------------------------------
    # Layer classification helper
    # ------------------------------------------------------------------

    @staticmethod
    def classify_layer(finding_description: str) -> FindingLayer:
        """Classify a finding into the correct layer using the judgment criteria.

        Criteria from PROMPT_READER.md:
          - Can this pattern be used by a different author/work? → craft
          - Is this the author's writing habit across works? → style
          - Is this specific to this novel's characters/world? → novel
        """
        # Novel-specific keywords
        novel_keywords = [
            "角色",
            "人物",
            "术语",
            "设定",
            "世界观",
            "地名",
            "势力",
            "魔法体系",
            "能力",
            "规则",
            "禁忌",
        ]
        if any(kw in finding_description for kw in novel_keywords):
            return FindingLayer.NOVEL

        # Style-specific keywords
        style_keywords = [
            "风格",
            "语言",
            "节奏",
            "幽默",
            "吐槽",
            "叙述者",
            "声音",
            "视角",
            "口吻",
            "习惯",
            "偏好",
        ]
        if any(kw in finding_description for kw in style_keywords):
            return FindingLayer.STYLE

        # Default to craft
        return FindingLayer.CRAFT
