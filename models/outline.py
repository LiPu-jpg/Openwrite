"""大纲数据模型

提供统一的 OutlineNode + OutlineNodeType + OutlineHierarchy，
适配 opencode_skill/tools 中 context_builder / outline_parser / outline_serializer 使用的接口。
"""

from __future__ import annotations

from enum import Enum
from typing import Dict, List, Optional

from pydantic import BaseModel, Field


class OutlineNodeType(str, Enum):
    """大纲节点类型"""
    MASTER = "master"
    ARC = "arc"
    SECTION = "section"
    CHAPTER = "chapter"


class OutlineNode(BaseModel):
    """统一大纲节点 — 通过 node_type 区分层级

    设计理念:
      - 总纲(Master)、篇(Arc)、节(Section) 都用普通梗概描述事件推进
      - 节(Section) 用普通梗概归纳一组章节的主要事件与推进结果
      - 章(Chapter) 是最小写作单元: 只描述"这几千字写什么",
        以及本章的戏剧位置(dramatic_position)
    """

    node_id: str = Field(..., description="节点 ID")
    node_type: OutlineNodeType = Field(..., description="节点类型")
    title: str = Field(default="", description="标题")
    summary: str = Field(default="", description="摘要/描述")
    parent_id: Optional[str] = Field(default=None, description="父节点 ID")
    children_ids: List[str] = Field(default_factory=list, description="子节点 ID 列表")
    status: str = Field(default="", description="状态 (TODO/WRITING/REVIEW/DONE)")

    # ── 总纲 (MASTER) 字段 ──
    core_theme: str = Field(default="", description="核心主题")
    ending_direction: str = Field(default="", description="结局走向")
    world_premise: str = Field(default="", description="世界前提")
    tone: str = Field(default="", description="基调")
    key_turns: List[str] = Field(default_factory=list, description="关键转折点")
    word_count_target: int = Field(default=0, description="目标字数")

    # ── 篇纲 (ARC) 字段 ──
    arc_theme: str = Field(default="", description="本篇主题")
    chapter_range: str = Field(default="", description="篇纲覆盖的章节范围")

    # ── 节纲 (SECTION) 字段 ──
    purpose: str = Field(default="", description="节目的")

    # ── 章纲 (CHAPTER) 字段 —— 最小写作单元 ──
    dramatic_position: str = Field(
        default="",
        description="本章的戏剧位置，如 '起'/'承'/'转'/'合'/'过渡'"
    )
    content_focus: str = Field(
        default="",
        description="本章内容焦点（这几千字要写什么）"
    )
    goals: List[str] = Field(default_factory=list, description="本章写作目标")
    beats: List[str] = Field(default_factory=list, description="节拍列表（章内微结构）")
    hooks: List[str] = Field(default_factory=list, description="悬念/钩子")
    involved_characters: List[str] = Field(default_factory=list, description="涉及人物")
    involved_settings: List[str] = Field(default_factory=list, description="涉及设定")
    estimated_words: int = Field(default=0, description="预估字数")
    # 章内微观情绪变化 (canonical field)
    emotional_arc: str = Field(default="", description="章内情绪变化（微观）")

    @property
    def emotion_arc(self) -> str:
        """兼容别名，统一指向 emotional_arc"""
        return self.emotional_arc


class OutlineHierarchy(BaseModel):
    """完整四级大纲层级结构"""

    novel_id: str = Field(default="", description="小说 ID")
    master: Optional[OutlineNode] = Field(default=None, description="总纲")
    arcs: List[OutlineNode] = Field(default_factory=list, description="篇纲列表")
    sections: List[OutlineNode] = Field(default_factory=list, description="节纲列表")
    chapters: List[OutlineNode] = Field(default_factory=list, description="章纲列表")

    def get_node(self, node_id: str) -> Optional[OutlineNode]:
        """根据 ID 查找任意层级的节点"""
        if self.master and self.master.node_id == node_id:
            return self.master
        for pool in (self.arcs, self.sections, self.chapters):
            for node in pool:
                if node.node_id == node_id:
                    return node
        return None

    def get_chapter_window(
        self, chapter_id: str, window_size: int = 5
    ) -> List[OutlineNode]:
        """获取目标章节前后 window_size 范围内的章节列表"""
        idx = None
        for i, ch in enumerate(self.chapters):
            if ch.node_id == chapter_id:
                idx = i
                break
        if idx is None:
            return []
        start = max(0, idx - window_size)
        end = min(len(self.chapters), idx + window_size + 1)
        return self.chapters[start:end]

    def get_chapters_by_arc(self, arc_id: str) -> List[OutlineNode]:
        """获取某篇下所有章节"""
        arc = None
        for a in self.arcs:
            if a.node_id == arc_id:
                arc = a
                break
        if not arc:
            return []

        chapter_ids: List[str] = []
        for child_id in arc.children_ids:
            node = self.get_node(child_id)
            if not node:
                continue
            if node.node_type == OutlineNodeType.CHAPTER:
                chapter_ids.append(node.node_id)
            elif node.node_type == OutlineNodeType.SECTION:
                chapter_ids.extend(node.children_ids)

        if not chapter_ids:
            return []

        chapter_map = {chapter.node_id: chapter for chapter in self.chapters}
        return [chapter_map[ch_id] for ch_id in chapter_ids if ch_id in chapter_map]

    def get_parent_section(self, chapter_id: str) -> Optional[OutlineNode]:
        """获取章节所属的节"""
        for sec in self.sections:
            if chapter_id in sec.children_ids:
                return sec
        # fallback: 通过 parent_id
        ch = self.get_node(chapter_id)
        if ch and ch.parent_id:
            return self.get_node(ch.parent_id)
        return None

    def get_parent_arc(self, chapter_id: str) -> Optional[OutlineNode]:
        """获取章节所属的篇"""
        # 先找节，再找节的父篇
        section = self.get_parent_section(chapter_id)
        if section:
            for arc in self.arcs:
                if section.node_id in arc.children_ids:
                    return arc
                if section.parent_id == arc.node_id:
                    return arc
        # fallback: 直接看哪个 arc 包含此章
        for arc in self.arcs:
            if chapter_id in arc.children_ids:
                return arc
        return None

    def get_dramatic_context(self, chapter_id: str) -> Dict[str, str]:
        """获取章节的完整戏剧位置上下文

        返回该章自身的戏剧位置信息，
        供 LLM 理解"这一章应该写出什么感觉"。

        Returns:
            {
                "dramatic_position": "转",
                "content_focus": "主角发现真相，内心崩溃",
            }
        """
        result: Dict[str, str] = {}

        ch = self.get_node(chapter_id)
        if ch:
            if ch.dramatic_position:
                result["dramatic_position"] = ch.dramatic_position
            if ch.content_focus:
                result["content_focus"] = ch.content_focus

        return result
