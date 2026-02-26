"""Character and state tracking models."""

from datetime import datetime
from typing import Dict, List, Optional

from pydantic import BaseModel, Field


class CharacterStatic(BaseModel):
    """Immutable-ish character profile."""

    id: str = Field(..., description="Character ID")
    name: str = Field(..., description="Character name")
    aliases: List[str] = Field(default_factory=list, description="Known aliases")
    gender: Optional[str] = Field(default=None, description="Gender")
    age: Optional[int] = Field(default=None, ge=0, description="Age")
    appearance: str = Field(default="", description="Appearance description")
    personality: List[str] = Field(default_factory=list, description="Personality tags")
    background: str = Field(default="", description="Background")
    faction: str = Field(default="", description="Faction")
    tier: str = Field(
        default="普通配角", description="主角/重要配角/普通配角/炮灰"
    )


class CharacterRelationship(BaseModel):
    """Relationship entry with another character."""

    target_id: str = Field(..., description="Target character ID")
    target_name: str = Field(..., description="Target character name")
    relation: str = Field(default="陌生", description="Relation label")
    affinity: int = Field(default=0, ge=-100, le=100, description="Affinity score")
    latest_event: str = Field(default="", description="Last related event")


class CharacterState(BaseModel):
    """Mutable character state at a point in timeline."""

    health: str = Field(default="健康", description="Health status")
    realm: str = Field(default="凡人", description="Realm")
    stamina: int = Field(default=100, ge=0, le=100, description="Stamina percent")
    mental_state: str = Field(default="平稳", description="Mental state")
    location: str = Field(default="未知", description="Current location")
    inventory: Dict[str, int] = Field(default_factory=dict, description="Items and counts")
    flags: List[str] = Field(default_factory=list, description="State flags")


class StateMutation(BaseModel):
    """A state mutation event."""

    mutation_id: str = Field(..., description="Mutation ID")
    chapter_id: str = Field(..., description="Chapter where mutation happened")
    timestamp: str = Field(default_factory=lambda: datetime.now().isoformat())
    action: str = Field(..., description="Mutation action, e.g. acquire")
    payload: Dict[str, str] = Field(default_factory=dict, description="Action payload")
    reason: str = Field(default="", description="Reason")
    before_state: CharacterState = Field(..., description="State before mutation")
    after_state: CharacterState = Field(..., description="State after mutation")


class CharacterCard(BaseModel):
    """Character card with mutable and immutable sections."""

    static: CharacterStatic
    initial_state: CharacterState = Field(default_factory=CharacterState)
    current_state: CharacterState = Field(default_factory=CharacterState)
    relationships: List[CharacterRelationship] = Field(default_factory=list)
    current_snapshot: str = Field(default="", description="Latest snapshot file name")
