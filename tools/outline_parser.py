"""大纲 Markdown 解析器

从 Markdown 格式解析为 OutlineHierarchy 对象，"""

from __future__ import annotations

import re
from typing import List, Optional, Tuple

from models.outline import (
    OutlineHierarchy,
    OutlineNode,
    OutlineNodeType,
)


class OutlineMdParser:
    """Markdown 大纲解析器

    解析 Markdown 格式的大纲文本，返回 OutlineHierarchy 对象。

    支持的格式：
    - # 标题（总纲）
    - ## 标题（篇纲）
    - ### 标题（节纲）
    - #### 标题（章纲）
    - > key: value（元数据）
    - **节拍:** 或 **悬念:** 后跟列表
    """

    def parse(self, md_content: str, novel_id: str) -> OutlineHierarchy:
        """解析 Markdown 内容

        Args:
            md_content: Markdown 内容
            novel_id: 小说 ID

        Returns:
            OutlineHierarchy 实例
        """
        md_content = self._strip_ignored_blocks(md_content)
        lines = md_content.split("\n")
        hierarchy = OutlineHierarchy(novel_id=novel_id)

        # 状态追踪
        current_master: Optional[OutlineNode] = None
        current_arc: Optional[OutlineNode] = None
        current_section: Optional[OutlineNode] = None
        current_chapter: Optional[OutlineNode] = None

        # 节点 ID 计数器
        arc_counter = 0
        section_counter = 0
        chapter_counter = 0

        # 当前解析上下文
        in_beats = False
        in_hooks = False
        in_key_turns = False

        i = 0
        while i < len(lines):
            line = lines[i]
            stripped = line.strip()

            # 空行
            if not stripped:
                i += 1
                continue

            # 检测标题层级
            heading_match = re.match(r"^(#{1,4})\s+(.+)$", stripped)
            if heading_match:
                level = len(heading_match.group(1))
                title = heading_match.group(2).strip()

                # 重置列表状态
                in_beats = False
                in_hooks = False
                in_key_turns = False

                if level == 1:
                    # 总纲
                    current_arc = None
                    current_section = None
                    current_chapter = None
                    current_master = OutlineNode(
                        node_id="master",
                        node_type=OutlineNodeType.MASTER,
                        title=title,
                    )
                    hierarchy.master = current_master

                elif level == 2:
                    current_section = None
                    current_chapter = None
                    # 检查是否是"关键转折点"特殊节
                    if "关键转折点" in title:
                        in_key_turns = True
                        i += 1
                        continue

                    # 篇纲
                    arc_counter += 1
                    arc_id = f"arc_{arc_counter:03d}"
                    current_arc = OutlineNode(
                        node_id=arc_id,
                        node_type=OutlineNodeType.ARC,
                        title=title,
                        parent_id="master" if current_master else None,
                    )
                    hierarchy.arcs.append(current_arc)
                    if current_master and arc_id not in current_master.children_ids:
                        current_master.children_ids.append(arc_id)

                elif level == 3:
                    # 节纲
                    current_chapter = None
                    section_counter += 1
                    section_id = f"sec_{section_counter:03d}"
                    current_section = OutlineNode(
                        node_id=section_id,
                        node_type=OutlineNodeType.SECTION,
                        title=title,
                        parent_id=current_arc.node_id if current_arc else None,
                    )
                    hierarchy.sections.append(current_section)
                    if current_arc and section_id not in current_arc.children_ids:
                        current_arc.children_ids.append(section_id)

                elif level == 4:
                    # 章纲
                    chapter_counter += 1
                    chapter_id = f"ch_{chapter_counter:03d}"
                    current_chapter = OutlineNode(
                        node_id=chapter_id,
                        node_type=OutlineNodeType.CHAPTER,
                        title=title,
                        parent_id=current_section.node_id if current_section else None,
                    )
                    hierarchy.chapters.append(current_chapter)
                    if (
                        current_section
                        and chapter_id not in current_section.children_ids
                    ):
                        current_section.children_ids.append(chapter_id)

                i += 1
                continue

            # 元数据（> key: value）
            metadata_match = re.match(r"^>\s*(.+?):\s*(.*)$", stripped)
            if metadata_match:
                key = metadata_match.group(1).strip()
                value = metadata_match.group(2).strip()
                self._apply_metadata(
                    current_chapter or current_section or current_arc or current_master,
                    key,
                    value,
                )
                i += 1
                continue

            # 检测节拍/悬念标题
            if stripped.startswith("**节拍") or stripped.startswith("**beats"):
                in_beats = True
                in_hooks = False
                i += 1
                continue

            if stripped.startswith("**悬念") or stripped.startswith("**hooks"):
                in_beats = False
                in_hooks = True
                i += 1
                continue

            # 列表项
            list_match = re.match(r"^[-*]\s+(.+)$", stripped)
            numbered_match = re.match(r"^\d+\.\s+(.+)$", stripped)

            if list_match or numbered_match:
                item_text = (list_match or numbered_match).group(1).strip()

                if in_key_turns and current_master:
                    current_master.key_turns.append(item_text)
                elif in_beats and current_chapter:
                    current_chapter.beats.append(item_text)
                elif in_hooks and current_chapter:
                    current_chapter.hooks.append(item_text)

                i += 1
                continue

            # 普通文本（可能是摘要的一部分）
            if current_chapter:
                if current_chapter.summary:
                    current_chapter.summary += "\n" + stripped
                else:
                    current_chapter.summary = stripped
            elif current_section:
                if current_section.summary:
                    current_section.summary += "\n" + stripped
                else:
                    current_section.summary = stripped
            elif current_arc:
                if current_arc.summary:
                    current_arc.summary += "\n" + stripped
                else:
                    current_arc.summary = stripped
            elif current_master:
                if current_master.summary:
                    current_master.summary += "\n" + stripped
                else:
                    current_master.summary = stripped

            i += 1

        self._normalize_hierarchy_links(hierarchy)
        return hierarchy

    def _strip_ignored_blocks(self, md_content: str) -> str:
        """剔除不应进入当前可写窗口解析的扩展区块。"""
        patterns = (
            re.compile(
                r"(?ms)^[ \t]*<!--\s*OPENWRITE:LONG_RANGE_PLAN:START\s*-->\s*\n.*?^[ \t]*<!--\s*OPENWRITE:LONG_RANGE_PLAN:END\s*-->\s*$"
            ),
        )
        cleaned = md_content
        for pattern in patterns:
            cleaned = pattern.sub("", cleaned)
        return cleaned

    def _apply_metadata(
        self, node: Optional[OutlineNode], key: str, value: str
    ) -> None:
        """应用元数据到节点

        Args:
            node: 目标节点
            key: 元数据键
            value: 元数据值
        """
        if not node:
            return

        # 标准化键名
        key_lower = key.lower().replace(" ", "_").replace("-", "_")

        # 总纲字段
        if key_lower in ("核心主题", "core_theme", "主题"):
            node.core_theme = value
        elif key_lower in ("结局走向", "ending_direction", "结局"):
            node.ending_direction = value
        elif key_lower in ("世界前提", "world_premise", "世界观"):
            node.world_premise = value
        elif key_lower in ("故事简介", "简介"):
            node.summary = value
        elif key_lower in ("基调", "tone"):
            node.tone = value
        elif key_lower in ("目标字数", "word_count_target", "字数"):
            try:
                node.word_count_target = int(value.replace(",", ""))
            except ValueError:
                pass

        # 篇纲字段
        elif key_lower in ("主题", "theme"):
            if node.node_type == OutlineNodeType.ARC:
                node.core_theme = value
                node.arc_theme = value
        elif key_lower in ("起止章节", "chapters"):
            node.chapter_range = value
        elif key_lower in ("摘要", "summary"):
            node.summary = value
        # 节纲字段
        elif key_lower in ("目的", "purpose"):
            node.purpose = value
        elif key_lower in ("涉及人物", "出场人物", "出场角色", "characters", "人物", "角色"):
            # 解析中英文逗号/顿号分隔的人物列表
            characters = [c.strip() for c in re.split(r"[，,、]", value) if c.strip()]
            node.involved_characters.extend(characters)
        elif key_lower in ("涉及设定", "涉及概念", "设定", "概念", "settings", "concepts"):
            settings = [s.strip() for s in re.split(r"[，,、]", value) if s.strip()]
            node.involved_settings.extend(settings)

        # 章纲字段
        elif key_lower in ("本章目标", "写作目标", "goals", "目标"):
            goals = [g.strip() for g in re.split(r"[，,、]", value) if g.strip()]
            node.goals.extend(goals)
        elif key_lower in ("预估字数", "estimated_words", "字数"):
            try:
                node.estimated_words = int(value.replace(",", ""))
            except ValueError:
                pass
        elif key_lower in ("戏剧位置", "dramatic_position", "位置"):
            node.dramatic_position = value
        elif key_lower in ("内容焦点", "content_focus", "焦点"):
            node.content_focus = value
        elif key_lower in ("情感弧线", "emotional_arc", "情感"):
            node.emotional_arc = value
        elif key_lower in ("节拍", "beats"):
            beats = [b.strip() for b in re.split(r"[，,、]", value) if b.strip()]
            node.beats.extend(beats)
        elif key_lower in ("悬念", "hooks"):
            hooks = [h.strip() for h in re.split(r"[，,、]", value) if h.strip()]
            node.hooks.extend(hooks)

    def _extract_section_text(
        self, lines: List[str], start_idx: int, end_level: int
    ) -> Tuple[str, int]:
        """提取直到下一个同级或更高级标题之前的所有文本

        Args:
            lines: 所有行
            start_idx: 起始索引
            end_level: 结束标题级别（1-4）

        Returns:
            (提取的文本, 结束索引)
        """
        text_lines: List[str] = []
        i = start_idx

        while i < len(lines):
            line = lines[i].strip()
            heading_match = re.match(r"^(#{1,4})\s+", line)
            if heading_match:
                level = len(heading_match.group(1))
                if level <= end_level:
                    break
            text_lines.append(lines[i])
            i += 1

        return "\n".join(text_lines), i

    @staticmethod
    def _parse_chapter_range(value: str) -> List[str]:
        """解析章节范围字符串为章节 ID 列表

        支持格式:
          - "ch_001 - ch_010"
          - "ch_001-ch_010"
          - "ch_1 - ch_10"
          - "1 - 10"（自动补前缀）
          - "ch_001, ch_003, ch_005"（逗号分隔）

        Returns:
            章节 ID 列表，如 ["ch_001", "ch_002", ..., "ch_010"]
        """
        value = value.strip()
        if not value:
            return []

        # 逗号分隔的列表
        if "," in value:
            return [c.strip() for c in value.split(",") if c.strip()]

        # 范围格式：提取起止数字
        range_match = re.match(
            r"(?:ch_)?0*(\d+)\s*[-–—]\s*(?:ch_)?0*(\d+)", value
        )
        if range_match:
            start = int(range_match.group(1))
            end = int(range_match.group(2))
            if start <= end <= start + 500:  # 安全上限
                return [f"ch_{n:03d}" for n in range(start, end + 1)]

        # 单个章节 ID
        single_match = re.match(r"(?:ch_)?0*(\d+)$", value)
        if single_match:
            n = int(single_match.group(1))
            return [f"ch_{n:03d}"]

        return []

    def _normalize_hierarchy_links(self, hierarchy: OutlineHierarchy) -> None:
        """Normalize parser output so arc children only point to sections."""

        section_ids = {section.node_id for section in hierarchy.sections}
        chapter_ids = {chapter.node_id for chapter in hierarchy.chapters}

        for arc in hierarchy.arcs:
            sections = [child_id for child_id in arc.children_ids if child_id in section_ids]
            direct_chapters = [child_id for child_id in arc.children_ids if child_id in chapter_ids]
            chosen = sections or direct_chapters
            deduped: List[str] = []
            seen = set()
            for child_id in chosen:
                if child_id in seen:
                    continue
                seen.add(child_id)
                deduped.append(child_id)
            arc.children_ids = deduped
