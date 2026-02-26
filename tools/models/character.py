"""Character models: lightweight card + optional detailed markdown profile."""

from datetime import datetime
from typing import Dict, List, Optional

from pydantic import BaseModel, Field, model_validator


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
    """Legacy structured state model (kept for backward compatibility)."""

    health: str = Field(default="健康", description="Health status")
    realm: str = Field(default="凡人", description="Realm")
    stamina: int = Field(default=100, ge=0, le=100, description="Stamina percent")
    mental_state: str = Field(default="平稳", description="Mental state")
    location: str = Field(default="未知", description="Current location")
    inventory: Dict[str, int] = Field(default_factory=dict, description="Items and counts")
    flags: List[str] = Field(default_factory=list, description="State flags")


class StateMutation(BaseModel):
    """Timeline entry with optional structured mutation."""

    mutation_id: str = Field(..., description="Mutation ID")
    chapter_id: str = Field(..., description="Chapter where mutation happened")
    timestamp: str = Field(default_factory=lambda: datetime.now().isoformat())
    action: Optional[str] = Field(default=None, description="Mutation action, e.g. acquire")
    payload: Dict[str, str] = Field(default_factory=dict, description="Action payload")
    note: str = Field(default="", description="Free-form timeline note")
    reason: Optional[str] = Field(
        default=None, description="Deprecated alias kept for old logs"
    )
    before_state: Optional[CharacterState] = Field(
        default=None, description="Deprecated verbose snapshot (legacy)"
    )
    after_state: Optional[CharacterState] = Field(
        default=None, description="Deprecated verbose snapshot (legacy)"
    )

    @model_validator(mode="after")
    def _normalize_note(self) -> "StateMutation":
        if not self.note and self.reason:
            self.note = self.reason
        return self


class CharacterSummary(BaseModel):
    """Lightweight summary shown in character card."""

    realm: str = Field(default="凡人", description="Current realm")
    location: str = Field(default="未知", description="Current location")
    statuses: List[str] = Field(default_factory=list, description="Status tags")
    items: List[str] = Field(default_factory=list, description="Key items")
    highlights: List[str] = Field(default_factory=list, description="Optional short notes")


class CharacterCard(BaseModel):
    """Character card: static profile + lightweight summary + dynamic markdown link."""

    static: CharacterStatic
    summary: CharacterSummary = Field(default_factory=CharacterSummary)
    dynamic_profile: str = Field(
        default="", description="Relative path to detailed markdown profile"
    )
    relationships: List[CharacterRelationship] = Field(default_factory=list)
    current_snapshot: str = Field(default="", description="Latest snapshot file name")
    initial_state: Optional[CharacterState] = Field(
        default=None, description="Legacy field (deprecated)"
    )
    current_state: Optional[CharacterState] = Field(
        default=None, description="Legacy field (deprecated)"
    )

    @model_validator(mode="after")
    def _migrate_from_legacy_state(self) -> "CharacterCard":
        state = self.current_state
        has_summary = (
            bool(self.summary.statuses)
            or bool(self.summary.items)
            or bool(self.summary.highlights)
            or self.summary.realm != "凡人"
            or self.summary.location != "未知"
        )
        if state is not None and not has_summary:
            self.summary.realm = state.realm or self.summary.realm
            self.summary.location = state.location or self.summary.location
            if state.health and state.health != "健康":
                self.summary.statuses.append(state.health)
            if state.mental_state and state.mental_state != "平稳":
                self.summary.statuses.append(state.mental_state)
            for flag in state.flags:
                if flag and flag not in self.summary.statuses:
                    self.summary.statuses.append(flag)
            for item, count in state.inventory.items():
                if count <= 0:
                    continue
                item_text = item if count == 1 else f"{item} x{count}"
                self.summary.items.append(item_text)
        return self
