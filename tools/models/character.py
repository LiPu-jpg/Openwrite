"""Character models: lightweight card + optional detailed markdown profile.

新增文本优先人物档案模型（Phase 7 架构重设计）：
  TextCharacterProfile — 纯文字多段描述，只记录重要角色。
旧模型保留以兼容现有测试。
"""

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



# ═══════════════════════════════════════════════════════════════════════════
# 新文本优先人物档案（Phase 7 架构重设计）
# 用户要求：炮灰不记录，主要角色用多段文字描述
# 格式：人物名/类型/外貌/性格与说话风格/技能与能力/物品/属性
# ═══════════════════════════════════════════════════════════════════════════


class TextCharacterProfile(BaseModel):
    """文本优先人物档案 — 多段自由文字描述，仅记录重要角色。"""
    id: str = Field(..., description="人物ID")
    name: str = Field(..., description="人物名")
    char_type: str = Field(default="配角", description="主角/重要配角/配角")
    appearance: str = Field(default="", description="外貌（多段文字）")
    personality_and_voice: str = Field(default="", description="性格与说话风格（多段文字）")
    skills_and_abilities: str = Field(default="", description="技能与能力（多段文字）")
    items: str = Field(default="", description="物品（多段文字）")
    attributes: str = Field(default="", description="属性（多段文字，如境界、阵营等）")
    notes: str = Field(default="", description="其他备注")
    faction: str = Field(default="", description="势力")
    aliases: List[str] = Field(default_factory=list, description="别名")

    def to_context_text(self, max_chars: int = 0) -> str:
        """生成用于 AI 上下文的纯文本摘要。"""
        parts: List[str] = [f"【{self.name}】 类型：{self.char_type}"]
        if self.appearance:
            parts.append(f"外貌：{self.appearance}")
        if self.personality_and_voice:
            parts.append(f"性格与说话风格：{self.personality_and_voice}")
        if self.skills_and_abilities:
            parts.append(f"技能与能力：{self.skills_and_abilities}")
        if self.items:
            parts.append(f"物品：{self.items}")
        if self.attributes:
            parts.append(f"属性：{self.attributes}")
        if self.notes:
            parts.append(f"备注：{self.notes}")
        text = "\n".join(parts)
        if max_chars and len(text) > max_chars:
            return text[:max_chars] + "…"
        return text

    @classmethod
    def from_legacy_card(cls, card: CharacterCard) -> "TextCharacterProfile":
        """从旧版 CharacterCard 迁移。"""
        return cls(
            id=card.static.id,
            name=card.static.name,
            char_type=card.static.tier,
            appearance=card.static.appearance,
            personality_and_voice=" ".join(card.static.personality) if card.static.personality else "",
            items=" ".join(card.summary.items) if card.summary.items else "",
            attributes=f"境界：{card.summary.realm}" if card.summary.realm != "凡人" else "",
            faction=card.static.faction,
            aliases=card.static.aliases,
        )
