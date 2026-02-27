"""Outline domain models.

新增四级大纲层级：总纲(MasterOutline) → 篇纲(ArcOutline) → 节纲(SectionOutline) → 章纲(ChapterOutline)
旧模型保留以兼容现有测试。
"""

from typing import Dict, List, Optional

from pydantic import BaseModel, Field


class ForeshadowingNode(BaseModel):
    """A foreshadowing node tracked in DAG."""

    id: str = Field(..., description="Foreshadowing ID")
    content: str = Field(..., description="Description of this foreshadowing")
    weight: int = Field(..., ge=1, le=10, description="Priority weight")
    layer: str = Field(..., description="主线/支线/彩蛋")
    status: str = Field(..., description="埋伏/待收/已收/废弃")
    created_at: str = Field(..., description="Chapter ID where it was introduced")
    target_chapter: Optional[str] = Field(
        default=None, description="Expected recovery chapter"
    )
    tags: List[str] = Field(default_factory=list, description="Tags")


class ForeshadowingEdge(BaseModel):
    """Dependency/reinforcement/reversal edge between foreshadowings."""

    from_: str = Field(..., alias="from", description="Source foreshadowing ID")
    to: str = Field(..., description="Target foreshadowing ID or recovery point")
    type: str = Field(..., description="依赖/强化/反转")


class OutlineArchetype(BaseModel):
    """Top-level story archetype."""

    core_theme: str = Field(..., description="Core theme")
    ending: str = Field(..., description="Ending direction")
    key_turns: List[str] = Field(default_factory=list, description="Major turns")
    version: str = Field(default="1.0", description="Version")


class OutlineVolume(BaseModel):
    """Volume-level outline."""

    volume_id: str = Field(..., description="Volume ID")
    title: str = Field(..., description="Volume title")
    start_chapter: str = Field(..., description="Start chapter ID")
    end_chapter: str = Field(..., description="End chapter ID")
    main_conflict: str = Field(..., description="Main conflict")
    characters_enter: List[str] = Field(default_factory=list, description="Entrants")
    characters_exit: List[str] = Field(default_factory=list, description="Exits")
    tension_score: int = Field(default=5, ge=1, le=10, description="Tension score")
    version: str = Field(default="1.0", description="Version")


class OutlineChapter(BaseModel):
    """Chapter-level outline."""

    chapter_id: str = Field(..., description="Chapter ID")
    title: str = Field(..., description="Chapter title")
    goals: List[str] = Field(default_factory=list, description="Chapter goals")
    key_scenes: List[str] = Field(default_factory=list, description="Key scenes")
    emotion_tag: str = Field(default="日常", description="Emotion tag")
    status: str = Field(default="TODO", description="TODO/WRITING/REVIEW/DONE")
    foreshadowing: List[ForeshadowingNode] = Field(
        default_factory=list, description="Foreshadowings in this chapter"
    )


class OutlineScene(BaseModel):
    """Scene-level outline."""

    scene_id: str = Field(..., description="Scene ID")
    chapter_id: str = Field(..., description="Parent chapter ID")
    content: str = Field(default="", description="Scene content")
    dialogue_points: List[str] = Field(default_factory=list, description="Dialogue cues")
    action_details: List[str] = Field(default_factory=list, description="Action details")
    status: str = Field(default="TODO", description="TODO/WRITING/REVIEW/DONE")



# ═══════════════════════════════════════════════════════════════════════
# 新四级大纲层级（Phase 7 架构重设计）
# 总纲(Master) → 篇纲(Arc) → 节纲(Section) → 章纲(Chapter)
# ═══════════════════════════════════════════════════════════════════════


class MasterOutline(BaseModel):
    """总纲 — 全书顶层规划。"""

    novel_id: str = Field(..., description="小说ID")
    title: str = Field(default="", description="书名")
    core_theme: str = Field(default="", description="核心主题")
    ending_direction: str = Field(default="", description="结局走向")
    key_turns: List[str] = Field(default_factory=list, description="全书关键转折")
    world_premise: str = Field(default="", description="世界观前提概述")
    tone: str = Field(default="", description="整体基调")
    target_word_count: int = Field(default=0, description="目标总字数")
    arc_ids: List[str] = Field(default_factory=list, description="篇纲ID有序列表")
    version: str = Field(default="1.0", description="版本")


class ArcOutline(BaseModel):
    """篇纲 — 一个连贯的大剧情弧。完成后触发前文压缩。"""

    arc_id: str = Field(..., description="篇纲ID，如 arc_001")
    novel_id: str = Field(default="", description="所属小说ID")
    title: str = Field(default="", description="篇名")
    order: int = Field(default=0, description="在总纲中的排序")
    main_conflict: str = Field(default="", description="本篇主要矛盾")
    resolution: str = Field(default="", description="本篇收束方向")
    key_characters: List[str] = Field(default_factory=list, description="本篇核心人物")
    section_ids: List[str] = Field(default_factory=list, description="节纲ID有序列表")
    compressed_summary: str = Field(default="", description="本篇完成后的压缩摘要")
    status: str = Field(default="TODO", description="TODO/WRITING/DONE")
    version: str = Field(default="1.0", description="版本")


class SectionOutline(BaseModel):
    """节纲 — 一个较完整的情节单元。"""

    section_id: str = Field(..., description="节纲ID，如 sec_001")
    arc_id: str = Field(default="", description="所属篇纲ID")
    title: str = Field(default="", description="节名")
    order: int = Field(default=0, description="在篇纲中的排序")
    plot_summary: str = Field(default="", description="本节情节概要")
    key_events: List[str] = Field(default_factory=list, description="关键事件")
    foreshadowing_plant: List[str] = Field(default_factory=list, description="本节埋设的伏笔ID")
    foreshadowing_recover: List[str] = Field(default_factory=list, description="本节回收的伏笔ID")
    chapter_ids: List[str] = Field(default_factory=list, description="章纲ID有序列表")
    compressed_summary: str = Field(default="", description="本节完成后的压缩摘要")
    status: str = Field(default="TODO", description="TODO/WRITING/DONE")


class ChapterOutline(BaseModel):
    """章纲 — 单次生成目标（5k-8k字）。"""

    chapter_id: str = Field(..., description="章纲ID，如 ch_001")
    section_id: str = Field(default="", description="所属节纲ID")
    title: str = Field(default="", description="章名")
    order: int = Field(default=0, description="在节纲中的排序")
    goals: List[str] = Field(default_factory=list, description="本章写作目标")
    key_scenes: List[str] = Field(default_factory=list, description="关键场景")
    emotion_arc: str = Field(default="", description="情绪弧线描述")
    involved_characters: List[str] = Field(default_factory=list, description="涉及人物ID列表")
    involved_settings: List[str] = Field(default_factory=list, description="涉及设定（地点/道具等）")
    foreshadowing_refs: List[str] = Field(default_factory=list, description="相关伏笔ID")
    target_words: int = Field(default=6000, ge=3000, le=12000, description="目标字数")
    status: str = Field(default="TODO", description="TODO/WRITING/REVIEW/DONE")


class OutlineHierarchy(BaseModel):
    """完整的四级大纲层级结构（用于序列化/反序列化）。"""

    master: MasterOutline
    arcs: Dict[str, ArcOutline] = Field(default_factory=dict)
    sections: Dict[str, SectionOutline] = Field(default_factory=dict)
    chapters: Dict[str, ChapterOutline] = Field(default_factory=dict)

    def get_arc(self, arc_id: str) -> Optional[ArcOutline]:
        return self.arcs.get(arc_id)

    def get_section(self, section_id: str) -> Optional[SectionOutline]:
        return self.sections.get(section_id)

    def get_chapter(self, chapter_id: str) -> Optional[ChapterOutline]:
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
        return [
            self.arcs[aid] for aid in self.master.arc_ids if aid in self.arcs
        ]
