"""Markdown 大纲解析器 — 将 outline.md 转换为 OutlineHierarchy。

根据 docs/OUTLINE_MD_SPEC.md 规范实现。
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

import yaml

try:
    from tools.models.outline import (
        ArcOutline,
        ChapterOutline,
        MasterOutline,
        OutlineHierarchy,
        SectionOutline,
    )
except ImportError:  # pragma: no cover
    from models.outline import (
        ArcOutline,
        ChapterOutline,
        MasterOutline,
        OutlineHierarchy,
        SectionOutline,
    )


class OutlineMdParser:
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


def parse_outline_md(content: str) -> OutlineHierarchy:
    """解析 Markdown 大纲文本。

    Args:
        content: Markdown 文本内容

    Returns:
        OutlineHierarchy 实例

    Raises:
        ValueError: 解析失败时抛出
    """
    parser = OutlineMdParser()
    return parser.parse(content)
