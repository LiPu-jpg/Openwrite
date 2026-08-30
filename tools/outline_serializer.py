"""大纲 Markdown 序列化器

将 OutlineHierarchy 序列化为 Markdown 格式，支持四级大纲结构。
"""

from __future__ import annotations

from models.outline import OutlineHierarchy, OutlineNode, OutlineNodeType
from typing import List, Optional


class OutlineMdSerializer:
    """Markdown 大纲序列化器

    将 OutlineHierarchy 序列化为 Markdown 格式。

    格式示例：
    ```markdown
    # 城市异象录

    一名普通人在异常世界中逐渐学会主动选择并承担代价。

    > 核心主题: 成长与选择
    > 结局走向: 开放式结局
    > 世界前提: 现代都市隐藏着异常世界
    > 基调: 轻松幽默中带点严肃
    > 目标字数: 2000000

    ## 关键转折点

    - 第10章：主角觉醒
    - 第50章：加入组织
    - 第100章：身份暴露

    ## 第一篇：觉醒篇

    主角意外觉醒异常感知能力，并在第一次危机中选择成为术师。

    > 篇主题: 从普通人到术师
    > 起止章节: ch_001 - ch_020

    ### 第一节：初入术界

    主角发现异常、接触术师组织，并完成第一次主动选择。

    > 目的: 展示主角的日常生活和意外觉醒
    > 涉及人物: 林岑, 周岚

    #### 第一章：平凡的早晨

    主角在上学路上第一次看见异常，并被迫使用刚刚觉醒的能力。

    > 预估字数: 6000
    > 情感弧线: 平静 → 惊讶

    **节拍:**
    1. 日常起床场景
    2. 上学路上的异常
    3. 第一次使用能力

    **悬念:**
    - 这个能力从何而来？
    - 为什么只有我能看到？
    ```
    """

    def serialize(self, hierarchy: OutlineHierarchy) -> str:
        """序列化大纲层级为 Markdown

        Args:
            hierarchy: 大纲层级对象

        Returns:
            Markdown 格式的大纲文本
        """
        lines: List[str] = []

        # 1. 序列化总纲
        if hierarchy.master:
            lines.extend(self._serialize_master(hierarchy.master))
            lines.append("")

        # 2. 序列化关键转折点
        if hierarchy.master and hierarchy.master.key_turns:
            lines.append("## 关键转折点")
            lines.append("")
            for turn in hierarchy.master.key_turns:
                lines.append(f"- {turn}")
            lines.append("")

        # 3. 序列化篇纲
        for arc in hierarchy.arcs:
            lines.extend(self._serialize_arc(arc, hierarchy))
            lines.append("")

        return "\n".join(lines).strip() + "\n"

    def _serialize_master(self, node: OutlineNode) -> List[str]:
        """序列化总纲节点

        Args:
            node: 总纲节点

        Returns:
            Markdown 行列表
        """
        lines: List[str] = []

        # 标题
        lines.append(f"# {node.title}")
        lines.append("")

        if node.summary:
            lines.extend(node.summary.strip().splitlines())
            lines.append("")

        # 元数据（引用格式）
        metadata = []

        if node.core_theme:
            metadata.append(f"> 核心主题: {node.core_theme}")
        if node.ending_direction:
            metadata.append(f"> 结局走向: {node.ending_direction}")
        if node.world_premise:
            metadata.append(f"> 世界前提: {node.world_premise}")
        if node.tone:
            metadata.append(f"> 基调: {node.tone}")
        if node.word_count_target:
            metadata.append(f"> 目标字数: {node.word_count_target}")

        if metadata:
            lines.extend(metadata)
            lines.append("")

        return lines

    def _serialize_arc(
        self, node: OutlineNode, hierarchy: OutlineHierarchy
    ) -> List[str]:
        """序列化篇纲节点

        Args:
            node: 篇纲节点
            hierarchy: 大纲层级

        Returns:
            Markdown 行列表
        """
        lines: List[str] = []

        # 标题
        lines.append(f"## {node.title}")
        lines.append("")

        if node.summary:
            lines.extend(node.summary.strip().splitlines())
            lines.append("")

        # 元数据
        metadata = []

        if node.arc_theme:
            metadata.append(f"> 篇主题: {node.arc_theme}")
        if node.word_count_target:
            metadata.append(f"> 目标字数: {node.word_count_target}")

        # 起止章节
        chapter_range = node.chapter_range
        if not chapter_range:
            chapters = hierarchy.get_chapters_by_arc(node.node_id)
            if chapters:
                first_ch = chapters[0].node_id
                last_ch = chapters[-1].node_id
                chapter_range = f"{first_ch} - {last_ch}"
        if chapter_range:
            metadata.append(f"> 起止章节: {chapter_range}")

        if metadata:
            lines.extend(metadata)
            lines.append("")

        # 序列化子节
        for section_id in node.children_ids:
            section = hierarchy.get_node(section_id)
            if section:
                lines.extend(self._serialize_section(section, hierarchy))
                lines.append("")

        return lines

    def _serialize_section(
        self, node: OutlineNode, hierarchy: OutlineHierarchy
    ) -> List[str]:
        """序列化节纲节点

        Args:
            node: 节纲节点
            hierarchy: 大纲层级

        Returns:
            Markdown 行列表
        """
        lines: List[str] = []

        # 标题
        lines.append(f"### {node.title}")
        lines.append("")

        if node.summary:
            lines.extend(node.summary.splitlines())
            lines.append("")

        # 元数据
        metadata = []

        if node.purpose:
            metadata.append(f"> 目的: {node.purpose}")
        if node.involved_characters:
            metadata.append(f"> 涉及人物: {', '.join(node.involved_characters)}")

        if metadata:
            lines.extend(metadata)
            lines.append("")

        # 序列化子章
        for chapter_id in node.children_ids:
            chapter = hierarchy.get_node(chapter_id)
            if chapter:
                lines.extend(self._serialize_chapter(chapter))
                lines.append("")

        return lines

    def _serialize_chapter(self, node: OutlineNode) -> List[str]:
        """序列化章纲节点

        Args:
            node: 章纲节点

        Returns:
            Markdown 行列表
        """
        lines: List[str] = []

        # 标题
        lines.append(f"#### {node.title}")
        lines.append("")

        if node.summary:
            lines.extend(node.summary.splitlines())
            lines.append("")

        # 元数据
        metadata = []

        metadata.append(f"> 章节 ID: {node.node_id}")
        if node.dramatic_position:
            metadata.append(f"> 戏剧位置: {node.dramatic_position}")
        if node.content_focus:
            metadata.append(f"> 内容焦点: {node.content_focus}")
        if node.estimated_words:
            metadata.append(f"> 预估字数: {node.estimated_words}")
        if node.emotional_arc:
            metadata.append(f"> 情感弧线: {node.emotional_arc}")
        if node.status:
            metadata.append(f"> 状态: {node.status}")

        if metadata:
            lines.extend(metadata)
            lines.append("")

        # 节拍
        if node.beats:
            lines.append("**节拍:**")
            for i, beat in enumerate(node.beats, 1):
                lines.append(f"{i}. {beat}")
            lines.append("")

        # 悬念
        if node.hooks:
            lines.append("**悬念:**")
            for hook in node.hooks:
                lines.append(f"- {hook}")
            lines.append("")

        # 涉及人物
        if node.involved_characters:
            lines.append(f"**涉及人物:** {', '.join(node.involved_characters)}")
            lines.append("")

        # 目标
        if node.goals:
            lines.append("**本章目标:**")
            for goal in node.goals:
                lines.append(f"- {goal}")
            lines.append("")

        return lines

    def serialize_node(
        self, node: OutlineNode, hierarchy: Optional[OutlineHierarchy] = None
    ) -> str:
        """序列化单个节点

        Args:
            node: 要序列化的节点
            hierarchy: 可选的大纲层级（用于获取子节点）

        Returns:
            Markdown 格式的节点文本
        """
        if node.node_type == OutlineNodeType.MASTER:
            lines = self._serialize_master(node)
        elif node.node_type == OutlineNodeType.ARC:
            lines = self._serialize_arc(
                node, hierarchy or OutlineHierarchy(novel_id="")
            )
        elif node.node_type == OutlineNodeType.SECTION:
            lines = self._serialize_section(
                node, hierarchy or OutlineHierarchy(novel_id="")
            )
        elif node.node_type == OutlineNodeType.CHAPTER:
            lines = self._serialize_chapter(node)
        else:
            lines = [f"# {node.title}", "", node.summary]

        return "\n".join(lines)
