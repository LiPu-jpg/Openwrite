"""大纲解析器 — 将 Markdown 格式的大纲转换为结构化数据。

支持四级大纲层级：
- 总纲 (Master): H1 标题
- 篇纲 (Arc): H2 标题
- 节纲 (Section): H3 标题
- 章纲 (Chapter): H4 标题
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

import yaml


@dataclass
class MasterOutline:
    """总纲 — 全书顶层规划。"""

    novel_id: str
    title: str = ""
    core_theme: str = ""
    ending_direction: str = ""
    key_turns: List[str] = field(default_factory=list)
    world_premise: str = ""
    tone: str = ""
    target_word_count: int = 0
    arc_ids: List[str] = field(default_factory=list)
    version: str = "1.0"

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典。"""
        return {
            "novel_id": self.novel_id,
            "title": self.title,
            "core_theme": self.core_theme,
            "ending_direction": self.ending_direction,
            "key_turns": self.key_turns,
            "world_premise": self.world_premise,
            "tone": self.tone,
            "target_word_count": self.target_word_count,
            "arc_ids": self.arc_ids,
            "version": self.version,
        }


@dataclass
class ArcOutline:
    """篇纲 — 一个连贯的大剧情弧。"""

    arc_id: str
    novel_id: str = ""
    title: str = ""
    order: int = 0
    main_conflict: str = ""
    resolution: str = ""
    key_characters: List[str] = field(default_factory=list)
    section_ids: List[str] = field(default_factory=list)
    compressed_summary: str = ""
    status: str = "TODO"
    version: str = "1.0"

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典。"""
        return {
            "arc_id": self.arc_id,
            "novel_id": self.novel_id,
            "title": self.title,
            "order": self.order,
            "main_conflict": self.main_conflict,
            "resolution": self.resolution,
            "key_characters": self.key_characters,
            "section_ids": self.section_ids,
            "compressed_summary": self.compressed_summary,
            "status": self.status,
            "version": self.version,
        }


@dataclass
class SectionOutline:
    """节纲 — 一个较完整的情节单元。"""

    section_id: str
    arc_id: str = ""
    title: str = ""
    order: int = 0
    plot_summary: str = ""
    key_events: List[str] = field(default_factory=list)
    foreshadowing_plant: List[str] = field(default_factory=list)
    foreshadowing_recover: List[str] = field(default_factory=list)
    chapter_ids: List[str] = field(default_factory=list)
    compressed_summary: str = ""
    status: str = "TODO"

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典。"""
        return {
            "section_id": self.section_id,
            "arc_id": self.arc_id,
            "title": self.title,
            "order": self.order,
            "plot_summary": self.plot_summary,
            "key_events": self.key_events,
            "foreshadowing_plant": self.foreshadowing_plant,
            "foreshadowing_recover": self.foreshadowing_recover,
            "chapter_ids": self.chapter_ids,
            "compressed_summary": self.compressed_summary,
            "status": self.status,
        }


@dataclass
class ChapterOutline:
    """章纲 — 单次生成目标（5k-8k字）。"""

    chapter_id: str
    section_id: str = ""
    title: str = ""
    order: int = 0
    goals: List[str] = field(default_factory=list)
    key_scenes: List[str] = field(default_factory=list)
    emotion_arc: str = ""
    involved_characters: List[str] = field(default_factory=list)
    involved_settings: List[str] = field(default_factory=list)
    foreshadowing_refs: List[str] = field(default_factory=list)
    target_words: int = 6000
    status: str = "TODO"

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典。"""
        return {
            "chapter_id": self.chapter_id,
            "section_id": self.section_id,
            "title": self.title,
            "order": self.order,
            "goals": self.goals,
            "key_scenes": self.key_scenes,
            "emotion_arc": self.emotion_arc,
            "involved_characters": self.involved_characters,
            "involved_settings": self.involved_settings,
            "foreshadowing_refs": self.foreshadowing_refs,
            "target_words": self.target_words,
            "status": self.status,
        }


@dataclass
class OutlineHierarchy:
    """完整的四级大纲层级结构。"""

    master: MasterOutline
    arcs: Dict[str, ArcOutline] = field(default_factory=dict)
    sections: Dict[str, SectionOutline] = field(default_factory=dict)
    chapters: Dict[str, ChapterOutline] = field(default_factory=dict)

    def get_arc(self, arc_id: str) -> Optional[ArcOutline]:
        """获取篇纲。"""
        return self.arcs.get(arc_id)

    def get_section(self, section_id: str) -> Optional[SectionOutline]:
        """获取节纲。"""
        return self.sections.get(section_id)

    def get_chapter(self, chapter_id: str) -> Optional[ChapterOutline]:
        """获取章纲。"""
        return self.chapters.get(chapter_id)

    def get_chapters_for_section(self, section_id: str) -> List[ChapterOutline]:
        """获取某节下所有章，按 order 排序。"""
        sec = self.sections.get(section_id)
        if not sec:
            return []
        return sorted(
            [self.chapters[cid] for cid in sec.chapter_ids if cid in self.chapters],
            key=lambda c: c.order,
        )

    def get_sections_for_arc(self, arc_id: str) -> List[SectionOutline]:
        """获取某篇下所有节，按 order 排序。"""
        arc = self.arcs.get(arc_id)
        if not arc:
            return []
        return sorted(
            [self.sections[sid] for sid in arc.section_ids if sid in self.sections],
            key=lambda s: s.order,
        )

    def get_all_arcs_ordered(self) -> List[ArcOutline]:
        """按总纲中的顺序返回所有篇纲。"""
        return [self.arcs[aid] for aid in self.master.arc_ids if aid in self.arcs]

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典。"""
        return {
            "master": self.master.to_dict(),
            "arcs": {k: v.to_dict() for k, v in self.arcs.items()},
            "sections": {k: v.to_dict() for k, v in self.sections.items()},
            "chapters": {k: v.to_dict() for k, v in self.chapters.items()},
        }


class OutlineParser:
    """Markdown 大纲解析器。"""

    HEADING_PATTERN = re.compile(r"^(#{1,4})\s+(.+)$")
    YAML_BLOCK_START = "---"
    LIST_ITEM_PATTERN = re.compile(r"^[-*]\s+(.+)$")

    def __init__(self):
        self.lines: List[str] = []
        self.current_line = 0
        self.master: Optional[MasterOutline] = None
        self.arcs: Dict[str, ArcOutline] = {}
        self.sections: Dict[str, SectionOutline] = {}
        self.chapters: Dict[str, ChapterOutline] = {}
        self.current_arc: Optional[ArcOutline] = None
        self.current_section: Optional[SectionOutline] = None

    def parse(self, content: str) -> OutlineHierarchy:
        """解析 Markdown 文本为 OutlineHierarchy。

        Args:
            content: Markdown 文本内容

        Returns:
            OutlineHierarchy 实例

        Raises:
            ValueError: 解析失败时抛出
        """
        self.lines = content.split("\n")
        self.current_line = 0
        self.master = None
        self.arcs = {}
        self.sections = {}
        self.chapters = {}
        self.current_arc = None
        self.current_section = None

        while self.current_line < len(self.lines):
            line = self.lines[self.current_line].rstrip()

            # 匹配标题
            match = self.HEADING_PATTERN.match(line)
            if match:
                level = len(match.group(1))
                title = match.group(2).strip()
                self._parse_heading(level, title)
            else:
                self.current_line += 1

        if not self.master:
            raise ValueError("未找到总纲（H1 标题）")

        # 构建 ID 列表
        self._build_id_lists()

        return OutlineHierarchy(
            master=self.master,
            arcs=self.arcs,
            sections=self.sections,
            chapters=self.chapters,
        )

    def parse_file(self, file_path: Union[str, Path]) -> OutlineHierarchy:
        """解析文件。

        Args:
            file_path: 文件路径

        Returns:
            OutlineHierarchy 实例
        """
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"大纲文件不存在: {file_path}")

        content = path.read_text(encoding="utf-8")
        return self.parse(content)

    def _parse_heading(self, level: int, title: str):
        """解析标题并提取元数据。"""
        self.current_line += 1

        # 提取 YAML 元数据
        metadata = self._extract_yaml_block()

        if level == 1:
            self._parse_master(title, metadata)
        elif level == 2:
            self._parse_arc(title, metadata)
        elif level == 3:
            self._parse_section(title, metadata)
        elif level == 4:
            self._parse_chapter(title, metadata)

    def _extract_yaml_block(self) -> Dict[str, Any]:
        """提取 YAML 前置块。"""
        if (
            self.current_line >= len(self.lines)
            or self.lines[self.current_line].strip() != self.YAML_BLOCK_START
        ):
            return {}

        self.current_line += 1
        yaml_lines = []

        while self.current_line < len(self.lines):
            line = self.lines[self.current_line].rstrip()
            if line == self.YAML_BLOCK_START:
                self.current_line += 1
                break
            yaml_lines.append(line)
            self.current_line += 1

        if not yaml_lines:
            return {}

        try:
            return yaml.safe_load("\n".join(yaml_lines)) or {}
        except yaml.YAMLError as e:
            raise ValueError(f"YAML 解析失败（行 {self.current_line}）: {e}")

    def _extract_key_turns(self) -> List[str]:
        """提取关键转折点列表（仅用于总纲）。"""
        key_turns = []

        # 跳过空行
        while (
            self.current_line < len(self.lines)
            and not self.lines[self.current_line].strip()
        ):
            self.current_line += 1

        # 查找列表项
        while self.current_line < len(self.lines):
            line = self.lines[self.current_line].rstrip()
            match = self.LIST_ITEM_PATTERN.match(line)
            if match:
                key_turns.append(match.group(1).strip())
                self.current_line += 1
            elif self.HEADING_PATTERN.match(line) or not line.strip():
                break
            else:
                self.current_line += 1

        return key_turns

    def _parse_master(self, title: str, metadata: Dict[str, Any]):
        """解析总纲。"""
        if not metadata.get("novel_id"):
            raise ValueError("总纲缺少必需字段：novel_id")

        # 提取关键转折点
        key_turns = self._extract_key_turns()

        self.master = MasterOutline(
            novel_id=metadata["novel_id"],
            title=title,
            core_theme=metadata.get("core_theme", ""),
            ending_direction=metadata.get("ending_direction", ""),
            key_turns=key_turns,
            world_premise=metadata.get("world_premise", ""),
            tone=metadata.get("tone", ""),
            target_word_count=metadata.get("target_word_count", 0),
            arc_ids=[],  # 稍后构建
            version=metadata.get("version", "1.0"),
        )

    def _parse_arc(self, title: str, metadata: Dict[str, Any]):
        """解析篇纲。"""
        if not metadata.get("arc_id"):
            raise ValueError(f"篇纲「{title}」缺少必需字段：arc_id")
        if "order" not in metadata:
            raise ValueError(f"篇纲「{title}」缺少必需字段：order")

        arc = ArcOutline(
            arc_id=metadata["arc_id"],
            novel_id=self.master.novel_id if self.master else "",
            title=title,
            order=metadata["order"],
            main_conflict=metadata.get("main_conflict", ""),
            resolution=metadata.get("resolution", ""),
            key_characters=metadata.get("key_characters", []),
            section_ids=[],  # 稍后构建
            compressed_summary=metadata.get("compressed_summary", ""),
            status=metadata.get("status", "TODO"),
            version=metadata.get("version", "1.0"),
        )

        self.arcs[arc.arc_id] = arc
        self.current_arc = arc
        self.current_section = None  # 重置节上下文

    def _parse_section(self, title: str, metadata: Dict[str, Any]):
        """解析节纲。"""
        if not self.current_arc:
            raise ValueError(f"节纲「{title}」必须位于某个篇纲之下")
        if not metadata.get("section_id"):
            raise ValueError(f"节纲「{title}」缺少必需字段：section_id")
        if "order" not in metadata:
            raise ValueError(f"节纲「{title}」缺少必需字段：order")

        section = SectionOutline(
            section_id=metadata["section_id"],
            arc_id=self.current_arc.arc_id,
            title=title,
            order=metadata["order"],
            plot_summary=metadata.get("plot_summary", ""),
            key_events=metadata.get("key_events", []),
            foreshadowing_plant=metadata.get("foreshadowing_plant", []),
            foreshadowing_recover=metadata.get("foreshadowing_recover", []),
            chapter_ids=[],  # 稍后构建
            compressed_summary=metadata.get("compressed_summary", ""),
            status=metadata.get("status", "TODO"),
        )

        self.sections[section.section_id] = section
        self.current_section = section

    def _parse_chapter(self, title: str, metadata: Dict[str, Any]):
        """解析章纲。"""
        if not self.current_section:
            raise ValueError(f"章纲「{title}」必须位于某个节纲之下")
        if not metadata.get("chapter_id"):
            raise ValueError(f"章纲「{title}」缺少必需字段：chapter_id")
        if "order" not in metadata:
            raise ValueError(f"章纲「{title}」缺少必需字段：order")

        chapter = ChapterOutline(
            chapter_id=metadata["chapter_id"],
            section_id=self.current_section.section_id,
            title=title,
            order=metadata["order"],
            goals=metadata.get("goals", []),
            key_scenes=metadata.get("key_scenes", []),
            emotion_arc=metadata.get("emotion_arc", ""),
            involved_characters=metadata.get("involved_characters", []),
            involved_settings=metadata.get("involved_settings", []),
            foreshadowing_refs=metadata.get("foreshadowing_refs", []),
            target_words=metadata.get("target_words", 6000),
            status=metadata.get("status", "TODO"),
        )

        self.chapters[chapter.chapter_id] = chapter

    def _build_id_lists(self):
        """构建各层级的 ID 列表。"""
        if not self.master:
            return

        # 构建 master.arc_ids
        arc_list = sorted(self.arcs.values(), key=lambda a: a.order)
        self.master.arc_ids = [a.arc_id for a in arc_list]

        # 构建 arc.section_ids
        for arc in self.arcs.values():
            section_list = sorted(
                [s for s in self.sections.values() if s.arc_id == arc.arc_id],
                key=lambda s: s.order,
            )
            arc.section_ids = [s.section_id for s in section_list]

        # 构建 section.chapter_ids
        for section in self.sections.values():
            chapter_list = sorted(
                [
                    c
                    for c in self.chapters.values()
                    if c.section_id == section.section_id
                ],
                key=lambda c: c.order,
            )
            section.chapter_ids = [c.chapter_id for c in chapter_list]


def parse_outline(content: str) -> OutlineHierarchy:
    """解析 Markdown 大纲文本。

    Args:
        content: Markdown 文本内容

    Returns:
        OutlineHierarchy 实例

    Raises:
        ValueError: 解析失败时抛出
    """
    parser = OutlineParser()
    return parser.parse(content)
