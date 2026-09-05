"""上下文包数据模型

提供 ForeshadowingState / WorldRules / GenerationContext，
适配 opencode_skill/tools/context_builder.py 的上下文组装使用。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, model_validator

from models.token_estimation import (
    TOKEN_ESTIMATOR_ID,
    estimate_text_tokens,
    unknown_actual_usage,
)


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
    """Static setting rules and related entities (legacy class name)."""

    constraints: List[str] = Field(default_factory=list, description="设定约束/涉及设定")
    entities: List[Dict[str, Any]] = Field(default_factory=list, description="相关实体")
    relations: List[Dict[str, Any]] = Field(default_factory=list, description="实体关系")

    def to_context_text(self, max_chars: int = 0) -> str:
        """生成世界观上下文文本"""
        parts: List[str] = []
        if self.constraints:
            parts.append("【设定约束】")
            for c in self.constraints:
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
    core_documents: Dict[str, str] = Field(
        default_factory=dict,
        description="作品核心文档；通常包含故事背景与基础设定",
    )
    chapter_goals: List[str] = Field(default_factory=list, description="本章写作目标")
    target_words: int = Field(default=6000, description="目标字数")
    emotion_arc: str = Field(default="", description="章内微观情绪变化")

    # 章节自身的戏剧位置
    dramatic_context: Dict[str, str] = Field(
        default_factory=dict,
        description="章节的戏剧位置与内容焦点，由 OutlineHierarchy.get_dramatic_context() 生成",
    )
    scene_context: Dict[str, Any] = Field(
        default_factory=dict,
        description="与当前正文 revision 绑定的本章场景顺序、故事时间与引用",
    )

    # 大纲
    outline_window: List[Any] = Field(
        default_factory=list, description="大纲窗口 (OutlineNode 列表)"
    )
    current_chapter: Optional[Any] = Field(default=None, description="当前章节节点")

    # 角色
    active_characters: List[Any] = Field(default_factory=list, description="出场角色列表")
    character_states: str = Field(
        default="",
        description="由正文/大纲内联批注推导的当前人物状态",
    )

    # 伏笔
    foreshadowing: ForeshadowingState = Field(
        default_factory=ForeshadowingState, description="伏笔状态"
    )

    # 风格
    style_profile: Any = Field(default=None, description="风格档案")

    # 设定（world_rules 保留字段名以兼容既有调用）
    world_rules: WorldRules = Field(default_factory=WorldRules, description="设定规则")

    # 最近文本
    recent_text: str = Field(default="", description="最近章节文本（用于连贯性）")
    semantic_references: str = Field(
        default="",
        description="由语义检索召回的远距离正文与参考资料片段",
    )
    semantic_retrieval: Dict[str, Any] = Field(
        default_factory=dict,
        description="语义上下文检索诊断，不参与 prompt",
    )

    # 真相文件
    current_state: str = Field(default="", description="世界当前状态（真相文件）")
    foreshadowing_summary: str = Field(default="", description="待回收伏笔摘要")
    ledger: str = Field(default="", description="资源账本（真相文件）")
    relationships: str = Field(default="", description="角色关系与动态状态（真相文件）")
    chapter_summaries: str = Field(default="", description="章节摘要列表（真相文件）")
    compression: Dict[str, Any] = Field(
        default_factory=dict,
        description="本次发送前上下文压缩报告，不参与 prompt",
    )

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
        """估算完整写作上下文，包括独立传递的真相文件。"""
        return int(self.token_estimate_report()["total_estimated_tokens"])

    def token_estimate_report(self) -> Dict[str, Any]:
        """Explain the execution estimate and distinguish it from actual usage."""

        sections = self.to_prompt_sections()
        section_tokens = sum(
            estimate_text_tokens(content) for content in sections.values()
        )
        rendered_prompt_tokens = estimate_text_tokens(self.to_prompt_context())
        # The delta contains Markdown headings, separators and any conservative
        # rounding needed to keep the decomposed total at least as large as the
        # estimate of the complete rendered prompt.
        wrapper_tokens = max(0, rendered_prompt_tokens - section_tokens)
        truth_tokens = sum(
            estimate_text_tokens(truth_text)
            for truth_text in (
                self.current_state,
                self.foreshadowing_summary,
                self.ledger,
                self.relationships,
            )
        )
        prompt_tokens = section_tokens + wrapper_tokens
        return {
            "kind": "estimate",
            "estimator": TOKEN_ESTIMATOR_ID,
            "text_scope": "rendered_prompt_and_separate_truth_values",
            "includes_wrapper_overhead": True,
            "section_content_estimated_tokens": section_tokens,
            "wrapper_estimated_tokens": wrapper_tokens,
            "rendered_prompt_estimated_tokens": prompt_tokens,
            "separate_truth_estimated_tokens": truth_tokens,
            "total_estimated_tokens": prompt_tokens + truth_tokens,
            "actual_usage": unknown_actual_usage(),
        }

    def to_prompt_sections(self) -> Dict[str, str]:
        """转为有序的 prompt 段落字典"""
        sections: Dict[str, str] = {}

        if self.author_intent:
            sections["作者意图"] = self.author_intent

        if self.creative_focus:
            sections["创作罗盘（当前最高优先级）"] = self.creative_focus

        if self.core_documents:
            labels = {"background": "故事背景", "foundation": "基础设定"}
            core_parts = [
                f"### {labels.get(key, key)}\n{content}"
                for key, content in self.core_documents.items()
                if str(content or "").strip()
            ]
            if core_parts:
                sections["作品核心"] = "\n\n".join(core_parts)

        if self.recent_text:
            sections["上文"] = self.recent_text

        if self.chapter_summaries:
            sections["历史章节记忆"] = self.chapter_summaries

        if self.semantic_references:
            sections["远程相关片段（不覆盖事实状态）"] = self.semantic_references

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
                chapter_parts = [
                    str(getattr(ch, "title", "") or ""),
                    str(getattr(ch, "summary", "") or ""),
                ]
                for label, attribute in (
                    ("戏剧位置", "dramatic_position"),
                    ("内容焦点", "content_focus"),
                    ("节拍", "beats"),
                    ("悬念", "hooks"),
                    ("情绪变化", "emotional_arc"),
                ):
                    value = getattr(ch, attribute, "")
                    if isinstance(value, list):
                        rendered = "；".join(str(item) for item in value if str(item).strip())
                    else:
                        rendered = str(value or "").strip()
                    if rendered:
                        chapter_parts.append(f"{label}：{rendered}")
                sections["当前章节"] = "\n".join(
                    part for part in chapter_parts if part.strip()
                )

        if self.scene_context.get("status") == "current":
            from tools.scene_integration import render_scene_context

            rendered_scenes = render_scene_context(self.scene_context)
            if rendered_scenes:
                sections["本章场景结构（当前正文）"] = rendered_scenes

        if self.active_characters:
            chars = []
            for c in self.active_characters:
                if hasattr(c, "to_context_text"):
                    chars.append(c.to_context_text(max_chars=200))
                elif hasattr(c, "name"):
                    chars.append(f"- {c.name}")
            if chars:
                sections["出场角色"] = "\n".join(chars)

        if self.character_states:
            sections["人物当前状态（内联批注）"] = self.character_states

        if self.foreshadowing and (self.foreshadowing.pending or self.foreshadowing.planted):
            sections["伏笔"] = self.foreshadowing.to_context_text(max_chars=500)

        if self.style_profile:
            if hasattr(self.style_profile, "to_summary"):
                sections["风格指南"] = self.style_profile.to_summary(max_chars=500)

        if self.world_rules and (self.world_rules.constraints or self.world_rules.entities):
            sections["设定"] = self.world_rules.to_context_text()

        if self.chapter_goals:
            sections["本章目标"] = "\n".join(f"- {g}" for g in self.chapter_goals)

        # 戏剧位置（核心：告诉 LLM 这一章在当前推进中的角色）
        if self.dramatic_context:
            dc = self.dramatic_context
            parts_dc: List[str] = []
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
