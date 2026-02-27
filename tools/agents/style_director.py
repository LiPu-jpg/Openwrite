"""Style Director agent — diff analysis and layered style iteration.

Implements the PROMPT_DIRECTOR.md workflow:
  1. Accept a draft + composed style document
  2. Perform layered diff analysis (style / novel / craft)
  3. Detect deviations per layer with severity scoring
  4. Suggest specific document updates for each layer
  5. Track iteration convergence

This is a LOCAL rule-based analyzer. It compares draft text against the
composed style document to find deviations. For full LLM-powered analysis,
the structured output serves as prompt context.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional, Tuple


class DeviationLayer(str, Enum):
    """Which layer a deviation belongs to."""

    STYLE = "style"  # author style fingerprint
    NOVEL = "novel"  # work-specific settings
    CRAFT = "craft"  # universal techniques


class DeviationSeverity(str, Enum):
    """How severe the deviation is."""

    CRITICAL = "critical"  # breaks hard constraints
    MAJOR = "major"  # significantly off-style
    MINOR = "minor"  # slight deviation
    SUGGESTION = "suggestion"  # improvement opportunity


@dataclass
class Deviation:
    """A single deviation found between draft and style docs."""

    layer: DeviationLayer
    severity: DeviationSeverity
    category: str  # voice / rhythm / language / character / worldbuilding / technique
    description: str
    evidence: str = ""  # excerpt from draft showing the deviation
    fix_suggestion: str = ""
    target_file: str = ""  # which style doc to update if the deviation reveals a gap


@dataclass
class LayerScore:
    """Score for a single layer's conformance."""

    layer: DeviationLayer
    score: int  # 0-100
    deviations: int
    critical_count: int
    major_count: int
    minor_count: int


@dataclass
class DocumentUpdate:
    """A suggested update to a style document."""

    layer: DeviationLayer
    file_path: str
    action: str  # "add" / "revise" / "remove"
    section: str  # which section to update
    content: str  # what to add/change
    reason: str  # why this update is needed


@dataclass
class StyleDirectorOutput:
    """Complete output from a style iteration cycle."""

    draft_excerpt: str  # first 200 chars of analyzed draft
    style_id: str
    novel_id: str
    deviations: List[Deviation] = field(default_factory=list)
    layer_scores: Dict[str, LayerScore] = field(default_factory=dict)
    document_updates: List[DocumentUpdate] = field(default_factory=list)
    iteration_number: int = 1
    converged: bool = False
    new_gaps_found: int = 0

    @property
    def style_deviations(self) -> List[Deviation]:
        return [d for d in self.deviations if d.layer == DeviationLayer.STYLE]

    @property
    def novel_deviations(self) -> List[Deviation]:
        return [d for d in self.deviations if d.layer == DeviationLayer.NOVEL]

    @property
    def craft_deviations(self) -> List[Deviation]:
        return [d for d in self.deviations if d.layer == DeviationLayer.CRAFT]

    def summary(self) -> str:
        """Generate a human-readable diff analysis report."""
        lines = [
            f"# 风格迭代分析报告 (迭代 #{self.iteration_number})",
            f"- 风格: {self.style_id} | 作品: {self.novel_id}",
            f"- 总偏差数: {len(self.deviations)}",
            f"- 新发现风格缺口: {self.new_gaps_found}",
            f"- 收敛状态: {'已收敛' if self.converged else '未收敛'}",
            "",
        ]

        # Layer scores
        lines.append("## 各层评分")
        for layer_name, score in self.layer_scores.items():
            lines.append(
                f"- {layer_name}: {score.score}/100 "
                f"(严重{score.critical_count} 主要{score.major_count} 轻微{score.minor_count})"
            )
        lines.append("")

        # Deviations by layer
        for layer_label, devs in [
            ("风格偏差 (style层)", self.style_deviations),
            ("设定偏差 (novel层)", self.novel_deviations),
            ("技法缺失 (craft层)", self.craft_deviations),
        ]:
            if devs:
                lines.append(f"### {layer_label}")
                for d in devs:
                    severity_icon = {
                        "critical": "🔴",
                        "major": "🟡",
                        "minor": "🔵",
                        "suggestion": "⚪",
                    }.get(d.severity.value, "⚪")
                    lines.append(f"- {severity_icon} [{d.category}] {d.description}")
                    if d.fix_suggestion:
                        lines.append(f"  → 建议: {d.fix_suggestion}")
                lines.append("")

        # Document updates
        if self.document_updates:
            lines.append("## 文档更新建议")
            for upd in self.document_updates:
                lines.append(
                    f"- [{upd.layer.value}] {upd.action} {upd.file_path} / {upd.section}"
                )
                lines.append(f"  原因: {upd.reason}")
                if upd.content:
                    lines.append(f"  内容: {upd.content[:100]}...")
            lines.append("")

        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Style checking rules
# ---------------------------------------------------------------------------

# Voice consistency checks
VOICE_CHECKS: List[Tuple[str, str, str]] = [
    # (pattern_to_detect, deviation_description, fix_suggestion)
    (
        r"(?:他|她)(?:静静地|默默地|安静地)(?:看着|望着)",
        "中性叙述句：缺少角色化用词，叙述者声音与角色脱离",
        "将中性描写替换为角色口吻的叙述，融入角色的思维方式和比喻体系",
    ),
    (
        r"(?:他|她)(?:感到|觉得)(?:十分|非常|极其)(?:高兴|悲伤|愤怒|开心|难过)",
        "直白情感描写：应通过细节和反差传递情感",
        "用角色的行动、细节观察或内心吐槽来间接展现情感",
    ),
    (
        r"(?:不禁|缓缓说道|微微一笑|淡淡地说|嘴角微微上扬)",
        "AI痕迹表达：使用了常见的AI生成套话",
        "删除或替换为更自然的表达，参考原著的角色化叙述方式",
    ),
]

# Rhythm checks
RHYTHM_CHECKS: List[Tuple[str, str]] = [
    ("consecutive_long", "连续长段落超过3段，节奏可能过于沉重"),
    ("low_short_ratio", "短段落占比低于40%，不符合短段快节奏风格"),
    ("no_dialogue_break", "连续叙述超过5段无对话/内心独白打断"),
]

# Setting consistency keywords (novel layer)
SETTING_VIOLATION_PATTERNS: List[Tuple[str, str]] = [
    (r"(?:魔法|法术|咒语)", "术语偏差：应使用「奇迹」而非通用魔法术语"),
    (r"(?:怪物|魔兽)", "术语偏差：应使用作品特定的生物称谓"),
]


class StyleDirectorAgent:
    """Performs layered diff analysis between draft and style documents."""

    def __init__(
        self,
        project_root: Optional[Path] = None,
        style_id: str = "",
        novel_id: str = "",
    ):
        self.project_root = project_root
        self.style_id = style_id
        self.novel_id = novel_id
        self._composed_text: Optional[str] = None
        self._style_rules: Dict[str, str] = {}

    def load_style_context(self) -> bool:
        """Load composed style document for comparison."""
        if not self.project_root or not self.novel_id:
            return False
        composed_path = self.project_root / "composed" / f"{self.novel_id}_final.md"
        if composed_path.is_file():
            self._composed_text = composed_path.read_text(encoding="utf-8")
            self._parse_style_rules()
            return True
        return False

    def _parse_style_rules(self) -> None:
        """Parse key rules from the composed style document."""
        if not self._composed_text:
            return
        # Extract sections by headers
        sections = re.split(r"\n##\s+", self._composed_text)
        for section in sections:
            lines = section.strip().split("\n")
            if lines:
                header = lines[0].strip().lstrip("#").strip()
                content = "\n".join(lines[1:]).strip()
                self._style_rules[header] = content

    def analyze(
        self,
        draft: str,
        iteration: int = 1,
        previous_gaps: int = 0,
    ) -> StyleDirectorOutput:
        """Perform full layered diff analysis on a draft.

        Args:
            draft: The draft text to analyze.
            iteration: Current iteration number.
            previous_gaps: Number of gaps found in previous iteration.
        """
        self.load_style_context()

        deviations: List[Deviation] = []

        # --- Style layer analysis ---
        deviations.extend(self._check_voice(draft))
        deviations.extend(self._check_rhythm(draft))
        deviations.extend(self._check_language(draft))
        deviations.extend(self._check_humor(draft))

        # --- Novel layer analysis ---
        deviations.extend(self._check_setting_consistency(draft))
        deviations.extend(self._check_character_consistency(draft))
        deviations.extend(self._check_terminology(draft))

        # --- Craft layer analysis ---
        deviations.extend(self._check_scene_structure(draft))
        deviations.extend(self._check_information_reveal(draft))
        deviations.extend(self._check_dialogue_craft(draft))

        # Compute layer scores
        layer_scores = self._compute_layer_scores(deviations)

        # Generate document updates
        document_updates = self._generate_updates(deviations)

        # Check convergence
        new_gaps = len([d for d in deviations if d.target_file])
        converged = new_gaps <= 1 and iteration > 1

        return StyleDirectorOutput(
            draft_excerpt=draft[:200],
            style_id=self.style_id,
            novel_id=self.novel_id,
            deviations=deviations,
            layer_scores={s.layer.value: s for s in layer_scores},
            document_updates=document_updates,
            iteration_number=iteration,
            converged=converged,
            new_gaps_found=new_gaps,
        )

    # ------------------------------------------------------------------
    # Style layer checks
    # ------------------------------------------------------------------

    def _check_voice(self, draft: str) -> List[Deviation]:
        """Check voice consistency against style fingerprint."""
        deviations: List[Deviation] = []
        lines = draft.split("\n")

        for pattern, desc, fix in VOICE_CHECKS:
            for i, line in enumerate(lines):
                if re.search(pattern, line):
                    deviations.append(
                        Deviation(
                            layer=DeviationLayer.STYLE,
                            severity=DeviationSeverity.MAJOR,
                            category="voice",
                            description=desc,
                            evidence=line.strip()[:80],
                            fix_suggestion=fix,
                        )
                    )
        return deviations

    def _check_rhythm(self, draft: str) -> List[Deviation]:
        """Check paragraph rhythm against style preferences."""
        deviations: List[Deviation] = []
        paragraphs = [p for p in draft.split("\n") if p.strip()]
        if not paragraphs:
            return deviations

        # Check short paragraph ratio
        short_count = sum(1 for p in paragraphs if len(p.strip()) <= 30)
        total = len(paragraphs)
        if total > 0:
            ratio = short_count / total
            if ratio < 0.4:
                deviations.append(
                    Deviation(
                        layer=DeviationLayer.STYLE,
                        severity=DeviationSeverity.MAJOR,
                        category="rhythm",
                        description=f"短段落占比{ratio:.0%}，低于目标60%，节奏偏沉重",
                        fix_suggestion="拆分长段落，增加一句一段的短段使用",
                    )
                )

        # Check consecutive long paragraphs
        consecutive_long = 0
        max_consecutive = 0
        for p in paragraphs:
            sentences = re.split(r"[。！？!?]", p)
            sentences = [s for s in sentences if s.strip()]
            if len(sentences) >= 6:
                consecutive_long += 1
                max_consecutive = max(max_consecutive, consecutive_long)
            else:
                consecutive_long = 0

        if max_consecutive > 3:
            deviations.append(
                Deviation(
                    layer=DeviationLayer.STYLE,
                    severity=DeviationSeverity.MINOR,
                    category="rhythm",
                    description=f"连续{max_consecutive}段长段落，节奏可能'塌'",
                    fix_suggestion="在长段落之间插入短段或对话打断",
                )
            )

        return deviations

    def _check_language(self, draft: str) -> List[Deviation]:
        """Check language style conformance."""
        deviations: List[Deviation] = []

        # Check for overly formal language (should be casual/modern)
        formal_patterns = [
            (r"(?:然而|尽管如此|与此同时|综上所述)", "过于书面化的连接词"),
            (r"(?:不可否认|毋庸置疑|显而易见)", "过于正式的表达"),
        ]
        for pattern, desc in formal_patterns:
            matches = re.findall(pattern, draft)
            if matches:
                deviations.append(
                    Deviation(
                        layer=DeviationLayer.STYLE,
                        severity=DeviationSeverity.MINOR,
                        category="language",
                        description=f"语言风格偏差：{desc}（出现{len(matches)}次）",
                        evidence=matches[0],
                        fix_suggestion="替换为更口语化/现代感的表达",
                    )
                )

        return deviations

    def _check_humor(self, draft: str) -> List[Deviation]:
        """Check humor density and quality."""
        deviations: List[Deviation] = []

        # Count humor markers
        humor_markers = re.findall(
            r"(?:淦|卧槽|离谱|绝了|不愧是|……行吧|……好吧|内心os|吐槽)",
            draft,
        )
        # Count total paragraphs
        paragraphs = [p for p in draft.split("\n") if p.strip()]
        total = len(paragraphs)

        if total > 10 and len(humor_markers) == 0:
            deviations.append(
                Deviation(
                    layer=DeviationLayer.STYLE,
                    severity=DeviationSeverity.MAJOR,
                    category="humor",
                    description="吐槽密度为零：缺少幽默/吐槽元素",
                    fix_suggestion="在严肃设定后添加角色内心吐槽，使用歪楼式幽默",
                    target_file=f"styles/{self.style_id}/humor.md"
                    if self.style_id
                    else "",
                )
            )

        return deviations

    # ------------------------------------------------------------------
    # Novel layer checks
    # ------------------------------------------------------------------

    def _check_setting_consistency(self, draft: str) -> List[Deviation]:
        """Check for setting/worldbuilding violations."""
        deviations: List[Deviation] = []

        for pattern, desc in SETTING_VIOLATION_PATTERNS:
            matches = re.findall(pattern, draft)
            if matches:
                deviations.append(
                    Deviation(
                        layer=DeviationLayer.NOVEL,
                        severity=DeviationSeverity.CRITICAL,
                        category="worldbuilding",
                        description=desc,
                        evidence=matches[0],
                        fix_suggestion="使用作品特定术语替换通用表达",
                    )
                )

        return deviations

    def _check_character_consistency(self, draft: str) -> List[Deviation]:
        """Check character behavior consistency."""
        deviations: List[Deviation] = []

        # Check for character voice mixing (simplified)
        # If composed style has character voice rules, check against them
        if self._composed_text and "角色" in self._composed_text:
            # Check for characters acting out of character
            # This is a simplified heuristic — full check needs LLM
            ooc_patterns = [
                (
                    r"主角(?:大声|高声)(?:宣布|宣告|声明)",
                    "角色行为偏差：主角不应高调宣告",
                ),
            ]
            for pattern, desc in ooc_patterns:
                if re.search(pattern, draft):
                    deviations.append(
                        Deviation(
                            layer=DeviationLayer.NOVEL,
                            severity=DeviationSeverity.MAJOR,
                            category="character",
                            description=desc,
                            fix_suggestion="参考角色设定中的行为约束",
                        )
                    )

        return deviations

    def _check_terminology(self, draft: str) -> List[Deviation]:
        """Check terminology usage against novel settings."""
        deviations: List[Deviation] = []

        # Extract terminology from composed doc if available
        if self._composed_text:
            # Look for terminology section
            term_match = re.search(
                r"(?:术语|terminology)(.*?)(?=\n##|\Z)",
                self._composed_text,
                re.DOTALL | re.IGNORECASE,
            )
            if term_match:
                term_section = term_match.group(1)
                # Extract defined terms
                terms = re.findall(r"[-·]\s*(\S+?)[:：]", term_section)
                # Check if draft uses undefined terms that look like they should be defined
                # This is a gap detection — finding terms the doc doesn't cover
                draft_terms = re.findall(r"「(\S{2,6})」", draft)
                undefined = [
                    t for t in set(draft_terms) if t not in terms and len(t) >= 2
                ]
                if len(undefined) > 3:
                    deviations.append(
                        Deviation(
                            layer=DeviationLayer.NOVEL,
                            severity=DeviationSeverity.MINOR,
                            category="terminology",
                            description=f"发现{len(undefined)}个未定义术语: {', '.join(undefined[:5])}",
                            fix_suggestion="将新术语添加到术语表",
                            target_file=f"novels/{self.novel_id}/terminology.md"
                            if self.novel_id
                            else "",
                        )
                    )

        return deviations

    # ------------------------------------------------------------------
    # Craft layer checks
    # ------------------------------------------------------------------

    def _check_scene_structure(self, draft: str) -> List[Deviation]:
        """Check if scene structure follows craft best practices."""
        deviations: List[Deviation] = []

        # Check for tension arc
        paragraphs = [p for p in draft.split("\n") if p.strip()]
        if len(paragraphs) > 15:
            # Simple heuristic: check if there's a climax marker in the middle-to-end
            mid_point = len(paragraphs) // 2
            latter_half = "\n".join(paragraphs[mid_point:])
            climax_markers = re.findall(
                r"(?:突然|猛然|瞬间|爆发|冲突|危机|转折)", latter_half
            )
            if not climax_markers:
                deviations.append(
                    Deviation(
                        layer=DeviationLayer.CRAFT,
                        severity=DeviationSeverity.SUGGESTION,
                        category="scene_structure",
                        description="后半段缺少高潮/冲突标记，张力曲线可能平坦",
                        fix_suggestion="在章节中后段安排冲突升级或转折点",
                        target_file="craft/scene_structures.md",
                    )
                )

        return deviations

    def _check_information_reveal(self, draft: str) -> List[Deviation]:
        """Check information reveal strategy."""
        deviations: List[Deviation] = []

        # Check for info dumps (consecutive exposition without character reaction)
        lines = draft.split("\n")
        dialogue_re = re.compile(r'[""「」『』]|说道|道：|问道|吐槽|心想')
        consecutive_expo = 0

        for line in lines:
            stripped = line.strip()
            if not stripped:
                consecutive_expo = 0
                continue
            if dialogue_re.search(stripped):
                consecutive_expo = 0
            else:
                consecutive_expo += 1

            if consecutive_expo > 5:
                deviations.append(
                    Deviation(
                        layer=DeviationLayer.CRAFT,
                        severity=DeviationSeverity.MAJOR,
                        category="information_reveal",
                        description="信息灌输：连续叙述超过5段无角色反应",
                        fix_suggestion="遵循乒乓球规则：每1-2个信息点后插入角色反应",
                        target_file="craft/information_reveal.md",
                    )
                )
                consecutive_expo = 0  # Reset

        return deviations

    def _check_dialogue_craft(self, draft: str) -> List[Deviation]:
        """Check dialogue quality and patterns."""
        deviations: List[Deviation] = []

        # Check for dialogue tags variety
        said_patterns = re.findall(r"(?:说道|说|道)", draft)
        total_dialogue = len(re.findall(r'[「""]', draft)) // 2  # rough count

        if total_dialogue > 5 and len(said_patterns) > total_dialogue * 0.7:
            deviations.append(
                Deviation(
                    layer=DeviationLayer.CRAFT,
                    severity=DeviationSeverity.MINOR,
                    category="dialogue",
                    description="对话标签单调：过度使用「说道」类标签",
                    fix_suggestion="减少对话标签，用动作/表情替代，或直接省略",
                )
            )

        return deviations

    # ------------------------------------------------------------------
    # Scoring
    # ------------------------------------------------------------------

    def _compute_layer_scores(self, deviations: List[Deviation]) -> List[LayerScore]:
        """Compute conformance scores per layer."""
        scores: List[LayerScore] = []

        for layer in DeviationLayer:
            layer_devs = [d for d in deviations if d.layer == layer]
            critical = sum(
                1 for d in layer_devs if d.severity == DeviationSeverity.CRITICAL
            )
            major = sum(1 for d in layer_devs if d.severity == DeviationSeverity.MAJOR)
            minor = sum(1 for d in layer_devs if d.severity == DeviationSeverity.MINOR)
            suggestions = sum(
                1 for d in layer_devs if d.severity == DeviationSeverity.SUGGESTION
            )

            score = (
                100 - (critical * 25) - (major * 15) - (minor * 5) - (suggestions * 2)
            )
            score = max(0, min(100, score))

            scores.append(
                LayerScore(
                    layer=layer,
                    score=score,
                    deviations=len(layer_devs),
                    critical_count=critical,
                    major_count=major,
                    minor_count=minor,
                )
            )

        return scores

    # ------------------------------------------------------------------
    # Document update generation
    # ------------------------------------------------------------------

    def _generate_updates(self, deviations: List[Deviation]) -> List[DocumentUpdate]:
        """Generate document update suggestions from deviations."""
        updates: List[DocumentUpdate] = []

        # Group deviations by target file
        file_devs: Dict[str, List[Deviation]] = {}
        for d in deviations:
            if d.target_file:
                file_devs.setdefault(d.target_file, []).append(d)

        for file_path, devs in file_devs.items():
            # Determine the layer from the first deviation
            layer = devs[0].layer
            categories = list(set(d.category for d in devs))

            updates.append(
                DocumentUpdate(
                    layer=layer,
                    file_path=file_path,
                    action="revise",
                    section=", ".join(categories),
                    content="; ".join(d.description for d in devs[:3]),
                    reason=f"发现{len(devs)}个偏差需要文档更新",
                )
            )

        # Check for style gaps (deviations that suggest missing rules)
        gap_devs = [
            d
            for d in deviations
            if d.severity in (DeviationSeverity.MAJOR, DeviationSeverity.CRITICAL)
            and not d.target_file
        ]
        if gap_devs:
            # Group by category
            gap_cats: Dict[str, List[Deviation]] = {}
            for d in gap_devs:
                gap_cats.setdefault(d.category, []).append(d)

            for cat, cat_devs in gap_cats.items():
                layer = cat_devs[0].layer
                if layer == DeviationLayer.STYLE:
                    target = (
                        f"styles/{self.style_id}/{cat}.md"
                        if self.style_id
                        else f"styles/{{id}}/{cat}.md"
                    )
                elif layer == DeviationLayer.NOVEL:
                    target = (
                        f"novels/{self.novel_id}/{cat}.md"
                        if self.novel_id
                        else f"novels/{{id}}/{cat}.md"
                    )
                else:
                    target = f"craft/{cat}.md"

                updates.append(
                    DocumentUpdate(
                        layer=layer,
                        file_path=target,
                        action="add",
                        section=cat,
                        content="; ".join(
                            d.fix_suggestion for d in cat_devs[:3] if d.fix_suggestion
                        ),
                        reason=f"发现{len(cat_devs)}个{cat}类偏差，现有文档可能缺少相关规则",
                    )
                )

        return updates
