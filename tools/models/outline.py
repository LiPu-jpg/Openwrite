"""Outline domain models."""

from typing import List, Optional

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
