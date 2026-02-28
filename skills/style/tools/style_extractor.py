"""Style Extractor — 从参考文本中提取可复用的风格特征。

核心功能：
1. 分析文本风格特征
2. 区分层级（craft/style/novel）
3. 生成结构化提取报告
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml


class ExtractionLayer(str, Enum):
    """提取结果所属层级。"""

    CRAFT = "craft"  # 通用技法
    STYLE = "style"  # 作者风格
    NOVEL = "novel"  # 作品设定


@dataclass
class ExtractedFeature:
    """提取的风格特征。"""

    name: str
    layer: ExtractionLayer
    category: str  # voice, language, rhythm, dialogue, humor, emotion
    description: str
    evidence: List[str] = field(default_factory=list)
    confidence: float = 0.8
    target_file: str = ""


@dataclass
class ExtractionReport:
    """完整的风格提取报告。"""

    source_id: str
    word_count: int
    chapter_range: str = ""

    # 各维度提取结果
    voice_features: List[ExtractedFeature] = field(default_factory=list)
    language_features: List[ExtractedFeature] = field(default_factory=list)
    rhythm_features: List[ExtractedFeature] = field(default_factory=list)
    dialogue_features: List[ExtractedFeature] = field(default_factory=list)
    humor_features: List[ExtractedFeature] = field(default_factory=list)
    emotion_features: List[ExtractedFeature] = field(default_factory=list)

    # 可复用特征
    reusable_features: List[Dict[str, Any]] = field(default_factory=list)

    # 作品特定特征（不应复用）
    novel_specific: List[str] = field(default_factory=list)

    # 建议的目标文件
    target_files: List[Dict[str, str]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式。

        Returns:
            字典表示
        """
        return {
            "source": {
                "text_id": self.source_id,
                "word_count": self.word_count,
                "chapter_range": self.chapter_range,
            },
            "extraction": {
                "voice": self._features_to_list(self.voice_features),
                "language": self._features_to_list(self.language_features),
                "rhythm": self._features_to_list(self.rhythm_features),
                "dialogue": self._features_to_list(self.dialogue_features),
                "humor": self._features_to_list(self.humor_features),
                "emotion": self._features_to_list(self.emotion_features),
            },
            "reusable_features": self.reusable_features,
            "novel_specific": self.novel_specific,
            "target_files": self.target_files,
        }

    def _features_to_list(
        self, features: List[ExtractedFeature]
    ) -> Dict[str, Any]:
        """将特征列表转换为字典。

        Args:
            features: 特征列表

        Returns:
            字典表示
        """
        if not features:
            return {}

        result: Dict[str, Any] = {}
        for f in features:
            if f.name not in result:
                result[f.name] = {
                    "description": f.description,
                    "evidence": f.evidence,
                    "confidence": f.confidence,
                }
        return result


class StyleExtractor:
    """风格提取器，从文本中提取可复用的风格特征。"""

    def __init__(self, project_root: Path):
        """初始化风格提取器。

        Args:
            project_root: 项目根目录
        """
        self.project_root = project_root
        self.styles_dir = project_root / "styles"

    def extract(self, text: str, source_id: str = "unknown") -> ExtractionReport:
        """从文本中提取风格特征。

        Args:
            text: 待分析的文本
            source_id: 文本来源标识

        Returns:
            提取报告
        """
        # 基本统计
        word_count = len(text)
        chapter_range = self._detect_chapter_range(text)

        report = ExtractionReport(
            source_id=source_id,
            word_count=word_count,
            chapter_range=chapter_range,
        )

        # 各维度分析
        report.voice_features = self._extract_voice(text)
        report.language_features = self._extract_language(text)
        report.rhythm_features = self._extract_rhythm(text)
        report.dialogue_features = self._extract_dialogue(text)
        report.humor_features = self._extract_humor(text)
        report.emotion_features = self._extract_emotion(text)

        # 汇总可复用特征
        report.reusable_features = self._summarize_reusable(report)

        # 识别作品特定特征
        report.novel_specific = self._identify_novel_specific(text)

        # 生成目标文件建议
        report.target_files = self._generate_target_files(report)

        return report

    def _detect_chapter_range(self, text: str) -> str:
        """检测文本的章节范围。

        Args:
            text: 文本内容

        Returns:
            章节范围字符串
        """
        # 尝试匹配章节标题
        chapter_pattern = r"第(\d+)[章节回]"
        matches = re.findall(chapter_pattern, text)

        if matches:
            chapters = [int(m) for m in matches]
            if len(chapters) > 1:
                return f"第{min(chapters)}-{max(chapters)}章"
            else:
                return f"第{chapters[0]}章"

        return ""

    def _extract_voice(self, text: str) -> List[ExtractedFeature]:
        """提取叙述声音特征。

        Args:
            text: 文本内容

        Returns:
            声音特征列表
        """
        features: List[ExtractedFeature] = []

        # 检测视角
        perspective = self._detect_perspective(text)
        if perspective:
            features.append(
                ExtractedFeature(
                    name="perspective",
                    layer=ExtractionLayer.STYLE,
                    category="voice",
                    description=perspective,
                    evidence=self._find_perspective_evidence(text, perspective),
                    confidence=0.9,
                    target_file="styles/{id}/voice.md",
                )
            )

        # 检测叙述态度
        attitude = self._detect_attitude(text)
        if attitude:
            features.append(
                ExtractedFeature(
                    name="attitude",
                    layer=ExtractionLayer.STYLE,
                    category="voice",
                    description=attitude,
                    evidence=self._find_attitude_evidence(text),
                    confidence=0.8,
                    target_file="styles/{id}/voice.md",
                )
            )

        return features

    def _detect_perspective(self, text: str) -> str:
        """检测叙述视角。

        Args:
            text: 文本内容

        Returns:
            视角描述
        """
        # 第一人称指标
        first_person_count = len(re.findall(r"\b我\b", text[:5000]))

        # 第三人称指标
        third_person_count = len(re.findall(r"\b他\b|\b她\b", text[:5000]))

        if first_person_count > third_person_count * 0.5:
            return "第一人称"
        elif third_person_count > first_person_count * 3:
            return "第三人称限制" if self._has_limited_pov(text) else "第三人称全知"
        else:
            return "混合视角"

    def _has_limited_pov(self, text: str) -> bool:
        """检测是否为限制视角。

        Args:
            text: 文本内容

        Returns:
            是否为限制视角
        """
        # 检测是否频繁切换视角
        pov_markers = ["视角", "从...看来", "在...眼中"]
        marker_count = sum(len(re.findall(m, text)) for m in pov_markers)

        return marker_count < 3  # 切换少则为限制视角

    def _find_perspective_evidence(
        self, text: str, perspective: str
    ) -> List[str]:
        """找到视角的证据。

        Args:
            text: 文本内容
            perspective: 检测到的视角

        Returns:
            证据句子列表
        """
        evidence: List[str] = []

        if "第一" in perspective:
            matches = re.findall(r"[^。]*我[^。]*[。]", text[:2000])
            evidence.extend(matches[:3])
        elif "第三" in perspective:
            matches = re.findall(r"[^。]*(他|她)[^。]*[。]", text[:2000])
            evidence.extend(matches[:3])

        return evidence

    def _detect_attitude(self, text: str) -> str:
        """检测叙述态度。

        Args:
            text: 文本内容

        Returns:
            态度描述
        """
        # 幽默/调侃指标
        humor_markers = ["吐槽", "自嘲", "搞笑", "有趣"]
        humor_count = sum(text.count(m) for m in humor_markers)

        # 严肃指标
        serious_markers = ["沉重", "庄严", "肃穆", "凝重"]
        serious_count = sum(text.count(m) for m in serious_markers)

        if humor_count > serious_count:
            return "调侃/幽默"
        elif serious_count > humor_count:
            return "严肃/客观"
        else:
            return "中立"

    def _find_attitude_evidence(self, text: str) -> List[str]:
        """找到态度的证据。

        Args:
            text: 文本内容

        Returns:
            证据句子列表
        """
        # 找带有态度词的句子
        attitude_words = ["吐槽", "自嘲", "沉重", "庄严"]
        evidence: List[str] = []

        for word in attitude_words:
            matches = re.findall(rf"[^。]*{word}[^。]*[。]", text)
            evidence.extend(matches[:2])

        return evidence[:5]

    def _extract_language(self, text: str) -> List[ExtractedFeature]:
        """提取语言风格特征。

        Args:
            text: 文本内容

        Returns:
            语言特征列表
        """
        features: List[ExtractedFeature] = []

        # 词汇特点
        vocab_style = self._detect_vocabulary_style(text)
        features.append(
            ExtractedFeature(
                name="vocabulary",
                layer=ExtractionLayer.STYLE,
                category="language",
                description=vocab_style,
                evidence=[],
                confidence=0.8,
                target_file="styles/{id}/language.md",
            )
        )

        # 句式特点
        sentence_style = self._detect_sentence_style(text)
        features.append(
            ExtractedFeature(
                name="sentence_style",
                layer=ExtractionLayer.STYLE,
                category="language",
                description=sentence_style,
                evidence=[],
                confidence=0.7,
                target_file="styles/{id}/language.md",
            )
        )

        return features

    def _detect_vocabulary_style(self, text: str) -> str:
        """检测词汇风格。

        Args:
            text: 文本内容

        Returns:
            词汇风格描述
        """
        # 古风词汇
        archaic_markers = ["之", "乎", "者", "也", "矣", "焉"]
        archaic_count = sum(text.count(m) for m in archaic_markers)

        # 现代网络用语
        modern_markers = ["yyds", "绝绝子", "emo", "内卷"]
        modern_count = sum(text.count(m) for m in modern_markers)

        if archaic_count > modern_count * 2:
            return "古风/文言"
        elif modern_count > 0:
            return "现代/网络用语"
        else:
            return "标准现代汉语"

    def _detect_sentence_style(self, text: str) -> str:
        """检测句式特点。

        Args:
            text: 文本内容

        Returns:
            句式描述
        """
        sentences = re.split(r"[。！？]", text)
        sentences = [s for s in sentences if len(s) > 5]

        if not sentences:
            return "无法判断"

        # 计算平均句长
        avg_length = sum(len(s) for s in sentences) / len(sentences)

        if avg_length < 20:
            return "短句为主，节奏明快"
        elif avg_length > 50:
            return "长句为主，铺陈细腻"
        else:
            return "长短结合，张弛有度"

    def _extract_rhythm(self, text: str) -> List[ExtractedFeature]:
        """提取节奏特征。

        Args:
            text: 文本内容

        Returns:
            节奏特征列表
        """
        features: List[ExtractedFeature] = []

        # 段落分析
        paragraphs = [p for p in text.split("\n\n") if p.strip()]
        if paragraphs:
            avg_para_length = sum(len(p) for p in paragraphs) / len(paragraphs)
            short_ratio = sum(1 for p in paragraphs if len(p) < 100) / len(paragraphs)

            pacing = "快" if short_ratio > 0.5 else "慢" if short_ratio < 0.3 else "中"

            features.append(
                ExtractedFeature(
                    name="pacing",
                    layer=ExtractionLayer.STYLE,
                    category="rhythm",
                    description=f"节奏{pacing}，短段比例{short_ratio:.1%}",
                    evidence=[f"平均段落长度: {avg_para_length:.0f}字"],
                    confidence=0.8,
                    target_file="styles/{id}/rhythm.md",
                )
            )

        return features

    def _extract_dialogue(self, text: str) -> List[ExtractedFeature]:
        """提取对话特征。

        Args:
            text: 文本内容

        Returns:
            对话特征列表
        """
        features: List[ExtractedFeature] = []

        # 检测对话
        dialogue_pattern = r'[\u300c\u201c][^\u300c\u201d\u300d]*[\u300d\u201d]'
        dialogues = re.findall(dialogue_pattern, text)

        if dialogues:
            dialogue_chars = sum(len(d) for d in dialogues)
            dialogue_ratio = dialogue_chars / len(text) if text else 0

            features.append(
                ExtractedFeature(
                    name="dialogue_ratio",
                    layer=ExtractionLayer.STYLE,
                    category="dialogue",
                    description=f"对话占比: {dialogue_ratio:.1%}",
                    evidence=[f"检测到{len(dialogues)}处对话"],
                    confidence=0.9,
                    target_file="styles/{id}/dialogue.md",
                )
            )

            # 检测对话格式
            has_action_tags = bool(re.search(r'[^\u300c\u201c]*说[^\u300c\u201d]*[\u300d\u201d]', text))
            if has_action_tags:
                features.append(
                    ExtractedFeature(
                        name="dialogue_format",
                        layer=ExtractionLayer.CRAFT,
                        category="dialogue",
                        description="使用动作标签的对话格式",
                        evidence=[],
                        confidence=0.7,
                        target_file="craft/dialogue_craft.md",
                    )
                )

        return features

    def _extract_humor(self, text: str) -> List[ExtractedFeature]:
        """提取幽默特征。

        Args:
            text: 文本内容

        Returns:
            幽默特征列表
        """
        features: List[ExtractedFeature] = []

        # 幽默指标
        humor_patterns = [
            (r"（[^）]*吐槽[^）]*）", "括号吐槽"),
            (r"[^。]*？[^。]*。", "反问修辞"),
            (r"不料|没想到|谁知", "反转幽默"),
        ]

        found_humor: List[Tuple[str, List[str]]] = []
        for pattern, humor_type in humor_patterns:
            matches = re.findall(pattern, text)
            if matches:
                found_humor.append((humor_type, matches[:3]))

        if found_humor:
            humor_types = [h[0] for h in found_humor]
            evidence = [m for _, matches in found_humor for m in matches]

            features.append(
                ExtractedFeature(
                    name="humor_type",
                    layer=ExtractionLayer.STYLE,
                    category="humor",
                    description=f"幽默类型: {', '.join(humor_types)}",
                    evidence=evidence,
                    confidence=0.7,
                    target_file="styles/{id}/humor.md",
                )
            )

        return features

    def _extract_emotion(self, text: str) -> List[ExtractedFeature]:
        """提取情感表达特征。

        Args:
            text: 文本内容

        Returns:
            情感特征列表
        """
        features: List[ExtractedFeature] = []

        # 情感词统计
        emotion_words = {
            "正面": ["温暖", "感动", "幸福", "快乐", "欣慰"],
            "负面": ["悲伤", "愤怒", "恐惧", "焦虑", "绝望"],
            "复杂": ["纠结", "矛盾", "苦涩", "无奈"],
        }

        emotion_counts: Dict[str, int] = {}
        for category, words in emotion_words.items():
            count = sum(text.count(w) for w in words)
            if count > 0:
                emotion_counts[category] = count

        if emotion_counts:
            dominant = max(emotion_counts, key=emotion_counts.get)
            features.append(
                ExtractedFeature(
                    name="emotion_tone",
                    layer=ExtractionLayer.STYLE,
                    category="emotion",
                    description=f"情感基调偏{dominant}",
                    evidence=[f"{k}情感词出现{v}次" for k, v in emotion_counts.items()],
                    confidence=0.6,
                    target_file="styles/{id}/emotion.md",
                )
            )

        return features

    def _summarize_reusable(self, report: ExtractionReport) -> List[Dict[str, Any]]:
        """汇总可复用特征。

        Args:
            report: 提取报告

        Returns:
            可复用特征列表
        """
        reusable: List[Dict[str, Any]] = []

        # 收集所有 style 层的特征
        all_features = (
            report.voice_features
            + report.language_features
            + report.rhythm_features
            + report.dialogue_features
            + report.humor_features
            + report.emotion_features
        )

        for f in all_features:
            if f.layer == ExtractionLayer.STYLE:
                reusable.append(
                    {
                        "name": f.name,
                        "description": f.description,
                        "applicability": "同类型作品",
                        "examples": f.evidence[:2] if f.evidence else [],
                    }
                )

        return reusable

    def _identify_novel_specific(self, text: str) -> List[str]:
        """识别作品特定特征（不应复用）。

        Args:
            text: 文本内容

        Returns:
            作品特定特征列表
        """
        specific: List[str] = []

        # 角色名（简单检测）
        name_pattern = r"[李王张刘陈杨赵黄周吴徐孙胡朱高林何郭马罗][伟芳娜敏静丽强磊军洋勇艳杰娟涛明超秀英华][^，。！？]*"
        names = set(re.findall(name_pattern, text[:5000]))
        if names:
            specific.append(f"角色名: {', '.join(list(names)[:5])}")

        # 专有名词（粗略检测）
        if "术师" in text or "法师" in text:
            specific.append("世界观职业设定")

        return specific

    def _generate_target_files(
        self, report: ExtractionReport
    ) -> List[Dict[str, str]]:
        """生成目标文件建议。

        Args:
            report: 提取报告

        Returns:
            目标文件列表
        """
        files: List[Dict[str, str]] = []

        # 按类别组织
        categories: Dict[str, List[str]] = {
            "voice": [],
            "language": [],
            "rhythm": [],
            "dialogue": [],
            "humor": [],
            "emotion": [],
        }

        all_features = (
            report.voice_features
            + report.language_features
            + report.rhythm_features
            + report.dialogue_features
            + report.humor_features
            + report.emotion_features
        )

        for f in all_features:
            if f.category in categories:
                categories[f.category].append(f.description)

        # 生成文件建议
        for category, contents in categories.items():
            if contents:
                files.append(
                    {
                        "path": f"styles/{{id}}/{category}.md",
                        "content": "\n".join(f"- {c}" for c in contents),
                    }
                )

        return files

    def save_report(
        self, report: ExtractionReport, style_id: str
    ) -> Path:
        """保存提取报告。

        Args:
            report: 提取报告
            style_id: 风格 ID

        Returns:
            保存的文件路径
        """
        output_dir = self.styles_dir / style_id
        output_dir.mkdir(parents=True, exist_ok=True)

        output_path = output_dir / "extraction_report.yaml"
        with open(output_path, "w", encoding="utf-8") as f:
            yaml.dump(report.to_dict(), f, allow_unicode=True, default_flow_style=False)

        return output_path
