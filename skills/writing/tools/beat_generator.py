"""Beat Generator - 节拍生成器。

根据章节上下文生成剧情节拍列表。节拍是章节的剧情骨架，
定义了开场、发展、高潮、收束等关键节点。

节拍由规则引擎生成，可被 LLM 扩写为完整散文。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

import yaml


@dataclass
class BeatTemplates:
    """节拍模板集合。"""

    opening: List[str] = field(default_factory=list)
    development: List[str] = field(default_factory=list)
    climax: List[str] = field(default_factory=list)
    closing: List[str] = field(default_factory=list)

    @classmethod
    def from_yaml(cls, path: Path) -> "BeatTemplates":
        """从 YAML 文件加载模板。

        Args:
            path: YAML 文件路径

        Returns:
            BeatTemplates 实例
        """
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)

        return cls(
            opening=data.get("opening", []),
            development=data.get("development", []),
            climax=data.get("climax", []),
            closing=data.get("closing", []),
        )

    @classmethod
    def default(cls) -> "BeatTemplates":
        """返回默认模板。

        Returns:
            使用内置模板的 BeatTemplates 实例
        """
        return cls(
            opening=[
                "承接上章尾声，{protagonist}面对{situation}，建立本章核心冲突",
                "以{setting}环境描写切入，暗示本章基调与潜在危机",
                "通过{protagonist}的内心独白/行动，揭示当前困境与目标",
            ],
            development=[
                "{protagonist}采取行动推进目标，遭遇{obstacle}形成阻力",
                "引入新信息/角色互动，改变{protagonist}对局势的判断",
                "通过对话/冲突展现角色关系变化，推进人物弧线",
                "伏笔元素自然融入叙事，为后续章节埋下线索",
            ],
            climax=[
                "核心冲突升级至本章高潮，{protagonist}被迫做出关键决策",
                "决策带来代价——获得部分答案但付出相应代价",
            ],
            closing=[
                "冲突暂时收束，{protagonist}消化本章事件的影响",
                "制造新悬念或遗留问题，衔接下一章（{seed}）",
            ],
        )


@dataclass
class SectionMarkers:
    """段落标记集合。"""

    scene: str = "【场景】"
    dialogue: str = "【对话】"
    narration: str = "【叙述】"
    internal: str = "【内心】"
    action: str = "【动作】"
    transition: str = "【转场】"

    @classmethod
    def from_yaml(cls, path: Path) -> "SectionMarkers":
        """从 YAML 文件加载标记。

        Args:
            path: YAML 文件路径

        Returns:
            SectionMarkers 实例
        """
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)

        return cls(
            scene=data.get("scene", "【场景】"),
            dialogue=data.get("dialogue", "【对话】"),
            narration=data.get("narration", "【叙述】"),
            internal=data.get("internal", "【内心】"),
            action=data.get("action", "【动作】"),
            transition=data.get("transition", "【转场】"),
        )

    @classmethod
    def default(cls) -> "SectionMarkers":
        """返回默认标记。

        Returns:
            使用内置标记的 SectionMarkers 实例
        """
        return cls()


class BeatGenerator:
    """节拍生成器。

    根据章节上下文生成剧情节拍列表。使用模板+变量填充的方式，
    确保节拍与上下文（主角、场景、障碍等）相关。

    Attributes:
        templates: 节拍模板
        markers: 段落标记
    """

    def __init__(
        self,
        templates: Optional[BeatTemplates] = None,
        markers: Optional[SectionMarkers] = None,
    ):
        """初始化节拍生成器。

        Args:
            templates: 节拍模板，为空则使用默认模板
            markers: 段落标记，为空则使用默认标记
        """
        self.templates = templates or BeatTemplates.default()
        self.markers = markers or SectionMarkers.default()

    def generate_beats(self, chapter_id: str, context: Dict[str, str]) -> List[str]:
        """生成章节节拍列表。

        根据上下文生成开场、发展、高潮、收束等节拍。
        节拍数量会根据上下文丰富度动态调整。

        Args:
            chapter_id: 章节标识符（如 "ch_001"）
            context: 上下文字典，包含：
                - seed: 种子/悬念
                - outline: 章节大纲
                - characters: 人物状态
                - foreshadowing: 待回收伏笔
                - scenes: 场景标记
                - world: 世界观

        Returns:
            节拍字符串列表
        """
        seed = context.get("seed", "推进主线并保留悬念")
        outline = context.get("outline", "")
        characters = context.get("characters", "")
        foreshadowing = context.get("foreshadowing", "")

        # 提取模板变量
        protagonist = self._extract_protagonist(characters)
        situation = self._extract_situation(outline, seed)
        setting = self._extract_setting(context)
        obstacle = self._extract_obstacle(outline, foreshadowing)

        template_vars = {
            "protagonist": protagonist,
            "situation": situation,
            "setting": setting,
            "obstacle": obstacle,
            "seed": seed,
        }

        beats: List[str] = []

        # 开场节拍
        opening_templates = self.templates.opening
        if opening_templates:
            opening_idx = hash(chapter_id) % len(opening_templates)
            beats.append(
                f"{chapter_id} 开场：{self._fill_template(opening_templates[opening_idx], template_vars)}"
            )

        # 发展节拍 - 数量取决于上下文丰富度
        dev_templates = self.templates.development
        if dev_templates:
            dev_count = self._decide_development_count(context)
            for i in range(dev_count):
                idx = (hash(chapter_id) + i) % len(dev_templates)
                beats.append(
                    f"{chapter_id} 发展{i + 1}：{self._fill_template(dev_templates[idx], template_vars)}"
                )

        # 伏笔节拍（如果有待回收伏笔）
        if foreshadowing and "暂无" not in foreshadowing:
            fs_beat = self._build_foreshadowing_beat(chapter_id, foreshadowing)
            if fs_beat:
                beats.append(fs_beat)

        # 高潮节拍
        climax_templates = self.templates.climax
        if climax_templates:
            climax_idx = hash(chapter_id + "climax") % len(climax_templates)
            beats.append(
                f"{chapter_id} 高潮：{self._fill_template(climax_templates[climax_idx], template_vars)}"
            )

        # 收束节拍
        closing_templates = self.templates.closing
        if closing_templates:
            closing_idx = hash(chapter_id + "closing") % len(closing_templates)
            beats.append(
                f"{chapter_id} 收束：{self._fill_template(closing_templates[closing_idx], template_vars)}"
            )

        return beats

    def _extract_protagonist(self, characters: str) -> str:
        """从角色上下文提取主角名称。"""
        if not characters or "暂无" in characters:
            return "主角"
        # 匹配格式: Name(境界=...)
        match = re.search(r"(\S+?)\(境界=", characters)
        if match:
            return match.group(1)
        return "主角"

    def _extract_situation(self, outline: str, seed: str) -> str:
        """从大纲提取当前局势。"""
        if outline and "暂无" not in outline and len(outline) > 10:
            clean = outline.replace("章节大纲为空", "").strip()
            if clean:
                # 按中文标点分割，取第一个有意义的片段
                segments = re.split(r"[，。；！？、]", clean)
                meaningful = [s.strip() for s in segments if len(s.strip()) > 4]
                if meaningful:
                    return meaningful[0][:40]
        return seed[:30] if seed else "当前局势"

    def _extract_setting(self, context: Dict[str, str]) -> str:
        """从上下文提取场景/地点。"""
        characters = context.get("characters", "")
        # 尝试从角色上下文提取位置
        match = re.search(r"位置=([^,)]+)", characters)
        if match:
            location = match.group(1).strip()
            if location and location != "未知":
                return location
        # 尝试从世界观提取
        world = context.get("world", "")
        if world and "暂无" not in world:
            match = re.search(r"(\S+?)\(", world)
            if match:
                return match.group(1)
        return "当前场景"

    def _extract_obstacle(self, outline: str, foreshadowing: str) -> str:
        """从大纲和伏笔提取潜在障碍。"""
        conflict_keywords = [
            "冲突",
            "危机",
            "阻碍",
            "困难",
            "敌人",
            "对手",
            "威胁",
            "陷阱",
        ]
        if outline:
            for kw in conflict_keywords:
                if kw in outline:
                    return kw + "相关阻力"
        if foreshadowing and "暂无" not in foreshadowing:
            return "伏笔相关的潜在障碍"
        return "意料之外的阻力"

    def _decide_development_count(self, context: Dict[str, str]) -> int:
        """根据上下文丰富度决定发展节拍数量。"""
        score = 0
        if context.get("foreshadowing", "") and "暂无" not in context.get(
            "foreshadowing", ""
        ):
            score += 1
        if context.get("characters", "") and "暂无" not in context.get(
            "characters", ""
        ):
            score += 1
        if context.get("scenes", "") and "未标注" not in context.get("scenes", ""):
            score += 1
        # 2-4 个发展节拍
        return max(2, min(4, score + 1))

    def _build_foreshadowing_beat(
        self, chapter_id: str, foreshadowing: str
    ) -> Optional[str]:
        """构建伏笔节拍。"""
        # 提取高权重伏笔 ID
        ids = re.findall(r"(\w+)\(权重=(\d+)", foreshadowing)
        high_weight = [(nid, int(w)) for nid, w in ids if int(w) >= 7]
        if high_weight:
            top = high_weight[0]
            return (
                f"{chapter_id} 伏笔：自然融入伏笔{top[0]}（权重{top[1]}），"
                f"通过情节推进而非刻意提及"
            )
        if ids:
            return f"{chapter_id} 伏笔：在叙事中自然铺设伏笔线索，不做刻意暗示"
        return None

    def _fill_template(self, template: str, variables: Dict[str, str]) -> str:
        """填充模板变量。"""
        result = template
        for key, value in variables.items():
            result = result.replace(f"{{{key}}}", value)
        return result


def load_beat_generator(
    templates_path: Optional[Path] = None,
    markers_path: Optional[Path] = None,
) -> BeatGenerator:
    """加载节拍生成器。

    优先从指定路径加载模板/标记，失败则使用默认值。

    Args:
        templates_path: 节拍模板 YAML 路径
        markers_path: 段落标记 YAML 路径

    Returns:
        BeatGenerator 实例
    """
    templates = None
    markers = None

    if templates_path and templates_path.exists():
        templates = BeatTemplates.from_yaml(templates_path)

    if markers_path and markers_path.exists():
        markers = SectionMarkers.from_yaml(markers_path)

    return BeatGenerator(templates=templates, markers=markers)
