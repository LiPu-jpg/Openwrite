"""World graph models."""

from datetime import datetime
from typing import Dict, List, Optional

from pydantic import BaseModel, Field


class WorldEntity(BaseModel):
    """World entity node."""

    id: str = Field(..., description="Entity ID")
    name: str = Field(..., description="Entity display name")
    type: str = Field(default="concept", description="Entity type")
    description: str = Field(default="", description="Free-form description")
    tags: List[str] = Field(default_factory=list, description="Tags")
    attributes: Dict[str, str] = Field(default_factory=dict, description="Structured attributes")


class WorldRelation(BaseModel):
    """Directed relation between two world entities."""

    source_id: str = Field(..., description="Source entity ID")
    target_id: str = Field(..., description="Target entity ID")
    relation: str = Field(..., description="Relation label, e.g. belongs_to")
    weight: int = Field(default=1, ge=1, le=10, description="Relation strength")
    note: str = Field(default="", description="Optional relation note")
    chapter_id: str = Field(default="", description="关系生效章节（空=全局）")


class EntityStateSnapshot(BaseModel):
    """实体在某章节的状态快照。"""

    entity_id: str = Field(..., description="实体 ID")
    chapter_id: str = Field(..., description="章节 ID")
    attributes: Dict[str, str] = Field(default_factory=dict, description="该章节时的属性状态")
    note: str = Field(default="", description="变更说明")


class WorldStateLog(BaseModel):
    """实体状态变更日志（按章节记录）。"""

    snapshots: List[EntityStateSnapshot] = Field(
        default_factory=list, description="所有状态快照（按章节序）"
    )


class WorldGraph(BaseModel):
    """Whole world graph."""

    entities: Dict[str, WorldEntity] = Field(default_factory=dict)
    relations: List[WorldRelation] = Field(default_factory=list)
    state_log: WorldStateLog = Field(default_factory=WorldStateLog, description="实体状态变更日志")
    updated_at: str = Field(default_factory=lambda: datetime.now().isoformat())
