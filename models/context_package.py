"""上下文包数据模型

提供 ForeshadowingState / WorldRules / GenerationContext，
适配 opencode_skill/tools/context_builder.py 的上下文组装使用。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, model_validator


class ForeshadowingState(BaseModel):
    """伏笔状态快照"""

    pending: List[Dict[str, Any]] = Field(default_factory=list, description="待回收伏笔")
    planted: List[Dict[str, Any]] = Field(default_factory=list, description="已埋下伏笔")
    resolved: List[Dict[str, Any]] = Field(default_factory=list, description="已回收伏笔")

    def to_context_text(self, max_chars: int = 0) -> str:
        """生成伏笔上下文文本"""
        parts: List[str] = []
        if self.pending:
            parts.append(f"【待回收伏笔 ({len(self.pending)})】")
            for item in self.pending[:5]:
                desc = item.get("description", item.get("content", ""))
                parts.append(f"  - {item.get('id', '?')}: {desc}")
        if self.planted:
            parts.append(f"【已埋下伏笔 ({len(self.planted)})】")
            for item in self.planted[:5]:
                desc = item.get("description", item.get("content", ""))
                parts.append(f"  - {item.get('id', '?')}: {desc}")
        text = "\n".join(parts)
        if max_chars and len(text) > max_chars:
            return text[:max_chars] + "…"
        return text


class WorldRules(BaseModel):
    """世界观规则"""

    constraints: List[str] = Field(default_factory=list, description="世界观约束/涉及设定")
    entities: List[Dict[str, Any]] = Field(default_factory=list, description="相关实体")
    relations: List[Dict[str, Any]] = Field(default_factory=list, description="实体关系")

    def to_context_text(self, max_chars: int = 0) -> str:
        """生成世界观上下文文本"""
        parts: List[str] = []
        if self.constraints:
            parts.append("【世界观约束】")
            for c in self.constraints[:10]:
                parts.append(f"  - {c}")
        if self.entities:
            parts.append(f"【相关实体 ({len(self.entities)})】")
            for e in self.entities[:5]:
                parts.append(f"  - {e.get('name', e.get('id', '?'))}")
        text = "\n".join(parts)
        if max_chars and len(text) > max_chars:
            return text[:max_chars] + "…"
        return text


class GenerationContext(BaseModel):
    """写作 AI 的完整上下文包 — 每次生成章节时由 ContextBuilder 组装"""

    model_config = {"populate_by_name": True}

    # 基础信息
    novel_id: str = Field(default="", description="小说 ID")
    chapter_id: str = Field(default="", description="当前章节 ID")
    author_intent: str = Field(default="", description="整本书长期不变的作者意图")
    creative_focus: str = Field(default="", description="当前阶段的创作罗盘与硬约束")
    chapter_goals: List[str] = Field(default_factory=list, description="本章写作目标")
    target_words: int = Field(default=6000, description="目标字数")
    emotion_arc: str = Field(default="", description="章内微观情绪变化")

    # 戏剧位置（来自节/篇弧线）
    dramatic_context: Dict[str, str] = Field(
        default_factory=dict,
        description="章节在节/篇弧线中的戏剧位置，由 OutlineHierarchy.get_dramatic_context() 生成",
    )

    # 大纲
    outline_window: List[Any] = Field(
        default_factory=list, description="大纲窗口 (OutlineNode 列表)"
    )
    current_chapter: Optional[Any] = Field(default=None, description="当前章节节点")

    # 角色
    active_characters: List[Any] = Field(default_factory=list, description="出场角色列表")

    # 伏笔
    foreshadowing: ForeshadowingState = Field(
        default_factory=ForeshadowingState, description="伏笔状态"
    )

    # 风格
    style_profile: Any = Field(default=None, description="风格档案")

    # 世界观
    world_rules: WorldRules = Field(default_factory=WorldRules, description="世界观规则")

    # 最近文本
    recent_text: str = Field(default="", description="最近章节文本（用于连贯性）")

    # 真相文件
    current_state: str = Field(default="", description="世界当前状态（真相文件）")
    foreshadowing_summary: str = Field(default="", description="待回收伏笔摘要")
    ledger: str = Field(default="", description="资源账本（真相文件）")
    relationships: str = Field(default="", description="角色关系与动态状态（真相文件）")
    chapter_summaries: str = Field(default="", description="章节摘要列表（真相文件）")

    @model_validator(mode="before")
    @classmethod
    def _normalize_legacy_truth_fields(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value

        data = dict(value)
        if "foreshadowing_summary" not in data and "pending_hooks" in data:
            data["foreshadowing_summary"] = data.get("pending_hooks", "")
        if "ledger" not in data and "particle_ledger" in data:
            data["ledger"] = data.get("particle_ledger", "")
        if "relationships" not in data and "character_matrix" in data:
            data["relationships"] = data.get("character_matrix", "")
        return data

    @property
    def pending_hooks(self) -> str:
        return self.foreshadowing_summary

    @property
    def particle_ledger(self) -> str:
        return self.ledger

    @property
    def character_matrix(self) -> str:
        return self.relationships

    def estimate_tokens(self) -> int:
        """粗略估算总 token 数（中文约 1.5 字/token）"""
        total_chars = 0
        for section_text in self.to_prompt_sections().values():
            total_chars += len(section_text)
        return int(total_chars / 1.5)

    def to_prompt_sections(self) -> Dict[str, str]:
        """转为有序的 prompt 段落字典"""
        sections: Dict[str, str] = {}

        if self.author_intent:
            sections["作者意图"] = self.author_intent

        if self.creative_focus:
            sections["创作罗盘（当前最高优先级）"] = self.creative_focus

        if self.recent_text:
            sections["上文"] = self.recent_text

        if self.chapter_summaries:
            sections["历史章节记忆"] = self.chapter_summaries

        if self.outline_window:
            outlines = []
            for node in self.outline_window:
                if hasattr(node, "title") and hasattr(node, "summary"):
                    outlines.append(f"- {node.title}: {node.summary}")
            if outlines:
                sections["大纲窗口"] = "\n".join(outlines)

        if self.current_chapter:
            ch = self.current_chapter
            if hasattr(ch, "title"):
                sections["当前章节"] = f"{ch.title}\n{getattr(ch, 'summary', '')}"

        if self.active_characters:
            chars = []
            for c in self.active_characters:
                if hasattr(c, "to_context_text"):
                    chars.append(c.to_context_text(max_chars=200))
                elif hasattr(c, "name"):
                    chars.append(f"- {c.name}")
            if chars:
                sections["出场角色"] = "\n".join(chars)

        if self.foreshadowing and (self.foreshadowing.pending or self.foreshadowing.planted):
            sections["伏笔"] = self.foreshadowing.to_context_text(max_chars=500)

        if self.style_profile:
            if hasattr(self.style_profile, "to_summary"):
                sections["风格指南"] = self.style_profile.to_summary(max_chars=500)

        if self.world_rules and (self.world_rules.constraints or self.world_rules.entities):
            sections["世界观"] = self.world_rules.to_context_text(max_chars=300)

        if self.chapter_goals:
            sections["本章目标"] = "\n".join(f"- {g}" for g in self.chapter_goals)

        # 戏剧位置（核心：告诉 LLM 这一章在整体弧线里的角色）
        if self.dramatic_context:
            dc = self.dramatic_context
            parts_dc: List[str] = []
            if dc.get("arc_structure"):
                parts_dc.append(f"篇弧线结构: {dc['arc_structure']}")
            if dc.get("arc_emotional_arc"):
                parts_dc.append(f"篇情感走向: {dc['arc_emotional_arc']}")
            if dc.get("section_structure"):
                parts_dc.append(f"节戏剧结构: {dc['section_structure']}")
            if dc.get("section_emotional_arc"):
                parts_dc.append(f"节情感弧线: {dc['section_emotional_arc']}")
            if dc.get("section_tension"):
                parts_dc.append(f"节张力走向: {dc['section_tension']}")
            if dc.get("dramatic_position"):
                parts_dc.append(f"▶ 本章位于: {dc['dramatic_position']}")
            if dc.get("content_focus"):
                parts_dc.append(f"▶ 本章焦点: {dc['content_focus']}")
            if parts_dc:
                sections["戏剧位置"] = "\n".join(parts_dc)

        if self.emotion_arc:
            sections["章内情绪变化"] = self.emotion_arc

        return sections

    def to_prompt_context(self) -> str:
        """生成完整的 prompt 上下文文本"""
        parts: List[str] = []
        for title, content in self.to_prompt_sections().items():
            parts.append(f"## {title}\n\n{content}")
        return "\n\n".join(parts)
