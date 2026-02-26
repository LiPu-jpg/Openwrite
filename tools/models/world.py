"""World graph models."""

from datetime import datetime
from typing import Dict, List

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


class WorldGraph(BaseModel):
    """Whole world graph."""

    entities: Dict[str, WorldEntity] = Field(default_factory=dict)
    relations: List[WorldRelation] = Field(default_factory=list)
    updated_at: str = Field(default_factory=lambda: datetime.now().isoformat())
