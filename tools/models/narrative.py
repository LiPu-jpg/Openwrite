"""叙事线数据模型 — 故事线可视化的核心数据结构。

所有故事元素（人物线、地点线、世界线、穿越线）统一为「叙事线」。
叙事线之间通过「连接」表达汇合、分离、跳转、伏笔等关系。
连接的 source 和 target 可以是同一条线（如同线内的伏笔弧、闪回）。
"""

from __future__ import annotations

from enum import Enum
from typing import Dict, List, Optional

from pydantic import BaseModel, Field


class LinkType(str, Enum):
    """连接类型。"""

    CONVERGE = "converge"  # 汇合：两条线在某点相遇
    DIVERGE = "diverge"  # 分离：一条线分出新线
    JUMP = "jump"  # 跳转：穿越、闪回等非线性跳转
    FORESHADOW = "foreshadow"  # 伏笔：埋设→回收的弧线（可同线可跨线）
    REFERENCE = "reference"  # 引用：松散关联（提及、暗示）


class ThreadEvent(BaseModel):
    """叙事线上的一个事件节点。"""

    chapter_id: str = Field(..., description="所属章节 ID，如 ch_003")
    label: str = Field(..., description="事件简述，如「离开余杭镇」")
    detail: str = Field(default="", description="详细内容（大纲摘要）")
    tension: int = Field(default=5, ge=1, le=10, description="张力值 1-10")
    tags: List[str] = Field(
        default_factory=list, description="标签：伏笔埋设、视角切换等"
    )
    meta: Dict[str, str] = Field(default_factory=dict, description="扩展元数据")


class NarrativeThread(BaseModel):
    """一条叙事线 — 一串按章节排列的事件节点。"""

    id: str = Field(..., description="线 ID，如 thread_li_xiaoyao")
    name: str = Field(..., description="显示名，如「李逍遥」")
    color: str = Field(default="", description="十六进制颜色，如 #FF6B6B")
    description: str = Field(default="", description="线的简要说明")
    events: List[ThreadEvent] = Field(
        default_factory=list, description="按章节排序的事件列表"
    )

    def chapter_ids(self) -> List[str]:
        """返回该线涉及的所有章节 ID（有序去重）。"""
        seen: set = set()
        result: List[str] = []
        for e in self.events:
            if e.chapter_id not in seen:
                seen.add(e.chapter_id)
                result.append(e.chapter_id)
        return result


class Link(BaseModel):
    """两个事件节点之间的连接。

    source 和 target 可以在同一条线上（如伏笔弧、闪回），
    也可以跨线（如汇合、分离、穿越跳转）。
    """

    source_thread: str = Field(..., description="起点线 ID")
    source_chapter: str = Field(..., description="起点章节 ID")
    target_thread: str = Field(..., description="终点线 ID")
    target_chapter: str = Field(..., description="终点章节 ID")
    link_type: LinkType = Field(..., description="连接类型")
    label: str = Field(default="", description="连接说明")
    weight: int = Field(default=5, ge=1, le=10, description="视觉权重（线粗细）")
    style: str = Field(default="solid", description="线型：solid / dashed / dotted")


class NarrativeTimeline(BaseModel):
    """完整的叙事时间线 — 所有线 + 所有连接。"""

    novel_id: str = Field(..., description="作品 ID")
    title: str = Field(default="", description="作品标题")
    chapters: List[str] = Field(default_factory=list, description="全局章节顺序")
    threads: List[NarrativeThread] = Field(
        default_factory=list, description="所有叙事线"
    )
    links: List[Link] = Field(default_factory=list, description="所有连接")

    def get_thread(self, thread_id: str) -> Optional[NarrativeThread]:
        """按 ID 查找叙事线。"""
        for t in self.threads:
            if t.id == thread_id:
                return t
        return None

    def threads_at_chapter(self, chapter_id: str) -> List[NarrativeThread]:
        """返回在指定章节有事件的所有叙事线。"""
        return [
            t for t in self.threads if any(e.chapter_id == chapter_id for e in t.events)
        ]

    def links_at_chapter(self, chapter_id: str) -> List[Link]:
        """返回涉及指定章节的所有连接。"""
        return [
            lk
            for lk in self.links
            if lk.source_chapter == chapter_id or lk.target_chapter == chapter_id
        ]

    def active_foreshadowings(self) -> List[Link]:
        """返回所有未回收的伏笔连接（target_chapter 为空或不在 chapters 中）。"""
        return [
            lk
            for lk in self.links
            if lk.link_type == LinkType.FORESHADOW
            and (not lk.target_chapter or lk.target_chapter not in self.chapters)
        ]

    def to_ai_context(self, chapter_id: str) -> Dict:
        """导出指定章节的 AI 上下文（给 Director/Librarian 用）。"""
        active = self.threads_at_chapter(chapter_id)
        chapter_links = self.links_at_chapter(chapter_id)

        converge_pairs = [
            {"threads": [lk.source_thread, lk.target_thread], "label": lk.label}
            for lk in chapter_links
            if lk.link_type == LinkType.CONVERGE
        ]
        diverge_pairs = [
            {"from": lk.source_thread, "to": lk.target_thread, "label": lk.label}
            for lk in chapter_links
            if lk.link_type == LinkType.DIVERGE
        ]
        foreshadow_refs = [
            {
                "id": lk.label or f"{lk.source_thread}→{lk.target_thread}",
                "from_chapter": lk.source_chapter,
                "weight": lk.weight,
            }
            for lk in chapter_links
            if lk.link_type == LinkType.FORESHADOW
        ]

        return {
            "chapter_id": chapter_id,
            "active_threads": [
                {
                    "id": t.id,
                    "name": t.name,
                    "events_here": [
                        {"label": e.label, "tension": e.tension, "tags": e.tags}
                        for e in t.events
                        if e.chapter_id == chapter_id
                    ],
                }
                for t in active
            ],
            "convergences": converge_pairs,
            "divergences": diverge_pairs,
            "foreshadowing_refs": foreshadow_refs,
        }
